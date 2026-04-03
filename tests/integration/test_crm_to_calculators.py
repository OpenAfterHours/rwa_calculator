"""
Integration tests: CRMProcessor → SA / IRB / Slotting calculators.

Validates that CRM-adjusted exposures are correctly split by approach
and that each calculator branch produces valid results with expected
columns and values.

Why Priority 2: The CRM→calculator boundary is where approach-split
exposures first enter calculation engines. Misrouted exposures or
missing columns silently produce wrong RWA.

Components wired: HierarchyResolver (real) → ExposureClassifier (real)
    → CRMProcessor (real) → SACalculator / IRBCalculator / SlottingCalculator (real)
No mocking. LazyFrames passed between stages as in production.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)


def _make_internal_rating(
    counterparty_reference: str = "CP001",
    pd: float = 0.02,
    **overrides: Any,
) -> dict[str, Any]:
    """Build an internal rating row for IRB eligibility."""
    defaults: dict[str, Any] = {
        "rating_reference": f"RAT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
    }
    defaults.update(overrides)
    return defaults


def _make_bundle_with_ratings(
    counterparties: list[dict[str, Any]] | None = None,
    loans: list[dict[str, Any]] | None = None,
    facilities: list[dict[str, Any]] | None = None,
    ratings: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> RawDataBundle:
    """Build a RawDataBundle that includes ratings (for IRB eligibility).

    Wraps make_raw_data_bundle and injects ratings into the bundle.
    """
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=loans,
        facilities=facilities,
        **kwargs,
    )
    ratings_lf = _rows_to_lazyframe(ratings, RATINGS_SCHEMA) if ratings else None
    # Reconstruct with ratings (frozen dataclass — use __class__ constructor)
    return RawDataBundle(
        facilities=bundle.facilities,
        loans=bundle.loans,
        counterparties=bundle.counterparties,
        facility_mappings=bundle.facility_mappings,
        lending_mappings=bundle.lending_mappings,
        org_mappings=bundle.org_mappings,
        contingents=bundle.contingents,
        collateral=bundle.collateral,
        guarantees=bundle.guarantees,
        provisions=bundle.provisions,
        ratings=ratings_lf,
        specialised_lending=bundle.specialised_lending,
        equity_exposures=bundle.equity_exposures,
        fx_rates=bundle.fx_rates,
        model_permissions=bundle.model_permissions,
    )


def _run_pipeline(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> CRMAdjustedBundle:
    """Run hierarchy + classifier + CRM and return the CRM-adjusted bundle."""
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return crm_processor.get_crm_adjusted_bundle(classified, config)


# =============================================================================
# SA branch (4 tests)
# =============================================================================


class TestSABranch:
    """Verify SA calculator receives correct exposures and produces valid RWA."""

    def test_sa_exposure_gets_risk_weight(
        self, hierarchy_resolver, classifier, crm_processor, sa_calculator, crr_config
    ):
        """Unrated corporate SA exposure → risk_weight=1.0 (100%)."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        sa_result = sa_calculator.get_sa_result_bundle(crm_bundle, crr_config)
        df = sa_result.results.collect()

        assert df.height >= 1
        assert df["risk_weight"][0] == pytest.approx(1.0)

    def test_sa_rwa_equals_ead_times_rw(
        self, hierarchy_resolver, classifier, crm_processor, sa_calculator, crr_config
    ):
        """Verify RWA = EAD x risk_weight for SA (pre supporting factor)."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        sa_result = sa_calculator.get_sa_result_bundle(crm_bundle, crr_config)
        df = sa_result.results.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        ead = loan_row["ead_final"][0]
        rw = loan_row["risk_weight"][0]
        rwa_pre = loan_row["rwa_pre_factor"][0]
        assert rwa_pre == pytest.approx(ead * rw, rel=1e-6)

    def test_sa_supporting_factor_applied_crr(
        self, hierarchy_resolver, classifier, crm_processor, sa_calculator, crr_config
    ):
        """CRR: SME corporate (annual_revenue < EUR 50M threshold) → supporting_factor < 1.0."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(entity_type="corporate", annual_revenue=30_000_000.0)
            ],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        sa_result = sa_calculator.get_sa_result_bundle(crm_bundle, crr_config)
        df = sa_result.results.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        factor = loan_row["supporting_factor"][0]
        # SME supporting factor is ~0.7619
        assert factor < 1.0
        assert factor == pytest.approx(0.7619, rel=1e-2)
        # Post-factor RWA should be less than pre-factor
        assert loan_row["rwa_post_factor"][0] < loan_row["rwa_pre_factor"][0]

    def test_sa_no_supporting_factor_basel31(
        self, hierarchy_resolver, classifier, crm_processor_b31, sa_calculator, basel31_config
    ):
        """Basel 3.1: SME corporate → supporting_factor=1.0 (no supporting factors in B3.1)."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(entity_type="corporate", annual_revenue=30_000_000.0)
            ],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor_b31, basel31_config, bundle
        )
        sa_result = sa_calculator.get_sa_result_bundle(crm_bundle, basel31_config)
        df = sa_result.results.collect()

        loan_row = df.filter(pl.col("exposure_type") == "loan")
        assert loan_row.height >= 1
        # Basel 3.1: no supporting factors, always 1.0
        assert loan_row["supporting_factor"][0] == pytest.approx(1.0)
        # Basel 3.1 uses SME corporate risk weight of 85% instead of 100%
        assert loan_row["risk_weight"][0] == pytest.approx(0.85)


# =============================================================================
# IRB branch (5 tests)
# =============================================================================


class TestIRBBranch:
    """Verify IRB calculator receives correct exposures and produces valid outputs."""

    def test_irb_firb_uses_supervisory_lgd(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """FIRB senior unsecured → LGD 45% (CRR supervisory value)."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(seniority="senior")],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_result = irb_calculator.get_irb_result_bundle(crm_bundle, crr_firb_config)
        df = irb_result.results.collect()

        assert df.height >= 1
        # CRR FIRB senior unsecured LGD = 45%
        lgd_col = "lgd_floored" if "lgd_floored" in df.columns else "lgd"
        assert df[lgd_col][0] == pytest.approx(0.45, abs=0.01)

    def test_irb_airb_uses_modelled_lgd(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        irb_calculator,
        crr_full_irb_config,
    ):
        """AIRB with lgd=0.30 on loan → LGD preserved in IRB output."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(lgd=0.30, seniority="senior")],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_full_irb_config, bundle
        )
        irb_result = irb_calculator.get_irb_result_bundle(crm_bundle, crr_full_irb_config)
        df = irb_result.results.collect()

        airb_rows = df.filter(pl.col("approach") == ApproachType.AIRB.value)
        assert airb_rows.height >= 1
        # AIRB uses modelled LGD — should be at least 0.30 (may be floored but not below input)
        lgd_col = "lgd_floored" if "lgd_floored" in df.columns else "lgd"
        assert airb_rows[lgd_col][0] >= 0.30 - 1e-6

    def test_irb_pd_floor_applied(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """PD from counterparty → floored at 0.03% (CRR) minimum."""
        # Use a very low PD to verify flooring
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.0001)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_result = irb_calculator.get_irb_result_bundle(crm_bundle, crr_firb_config)
        df = irb_result.results.collect()

        assert df.height >= 1
        pd_col = "pd_floored" if "pd_floored" in df.columns else "pd"
        pd_value = df[pd_col][0]
        # CRR PD floor is 0.03% = 0.0003
        assert pd_value >= 0.0003 - 1e-8

    def test_irb_expected_loss_calculated(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """Expected loss = PD x LGD x EAD is computed in IRB output."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_result = irb_calculator.get_irb_result_bundle(crm_bundle, crr_firb_config)
        df = irb_result.results.collect()

        assert df.height >= 1
        assert "expected_loss" in df.columns
        el = df["expected_loss"][0]
        assert el is not None
        assert el > 0.0

        # Verify EL = PD x LGD x EAD
        pd_val = df["pd_floored"][0] if "pd_floored" in df.columns else df["pd"][0]
        lgd_val = df["lgd_floored"][0] if "lgd_floored" in df.columns else df["lgd"][0]
        ead_val = df["ead_final"][0]
        assert el == pytest.approx(pd_val * lgd_val * ead_val, rel=1e-4)

    def test_irb_scaling_factor_crr_only(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        crm_processor_b31,
        irb_calculator,
        crr_firb_config,
    ):
        """CRR includes 1.06 scaling in RWA; Basel 3.1 does not."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )

        # CRR pipeline
        crm_crr = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_crr = irb_calculator.get_irb_result_bundle(crm_crr, crr_firb_config)
        df_crr = irb_crr.results.collect()

        assert df_crr.height >= 1
        # CRR should have scaling_factor = 1.06
        assert "scaling_factor" in df_crr.columns
        assert df_crr["scaling_factor"][0] == pytest.approx(1.06)

        # Basel 3.1 FIRB pipeline
        b31_firb_config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 15),
            permission_mode=PermissionMode.IRB,
        )
        crm_b31 = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor_b31, b31_firb_config, bundle
        )
        irb_b31 = irb_calculator.get_irb_result_bundle(crm_b31, b31_firb_config)
        df_b31 = irb_b31.results.collect()

        assert df_b31.height >= 1
        # Basel 3.1 should have scaling_factor = 1.0
        assert "scaling_factor" in df_b31.columns
        assert df_b31["scaling_factor"][0] == pytest.approx(1.0)

        # Both should produce positive RWA
        assert df_crr["rwa"][0] > 0.0
        assert df_b31["rwa"][0] > 0.0


# =============================================================================
# Slotting branch (3 tests)
# =============================================================================


class TestSlottingBranch:
    """Verify slotting calculator handles empty/None exposures correctly."""

    def test_empty_slotting_produces_valid_result(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        slotting_calculator,
        crr_config,
    ):
        """No slotting exposures → empty result, no errors."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        slotting_result = slotting_calculator.get_slotting_result_bundle(crm_bundle, crr_config)
        df = slotting_result.results.collect()

        # No slotting exposures in a simple corporate portfolio
        assert df.height == 0
        assert len(slotting_result.errors) == 0

    def test_slotting_result_bundle_has_required_fields(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        slotting_calculator,
        crr_config,
    ):
        """SlottingResultBundle has results and errors fields."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_config, bundle
        )
        slotting_result = slotting_calculator.get_slotting_result_bundle(crm_bundle, crr_config)

        # Bundle has the expected attributes
        assert hasattr(slotting_result, "results")
        assert hasattr(slotting_result, "errors")
        assert hasattr(slotting_result, "calculation_audit")
        # Results is a LazyFrame
        assert isinstance(slotting_result.results, pl.LazyFrame)

    def test_slotting_calculator_handles_none_exposures(self, slotting_calculator, crr_config):
        """slotting_exposures=None → empty result."""
        # Construct a CRMAdjustedBundle with slotting_exposures=None directly
        empty_lf = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
        crm_bundle = CRMAdjustedBundle(
            exposures=empty_lf,
            sa_exposures=empty_lf,
            irb_exposures=empty_lf,
            slotting_exposures=None,
        )
        slotting_result = slotting_calculator.get_slotting_result_bundle(crm_bundle, crr_config)
        df = slotting_result.results.collect()

        assert df.height == 0
        assert len(slotting_result.errors) == 0


# =============================================================================
# Split correctness (3 tests)
# =============================================================================


class TestSplitCorrectness:
    """Verify exposures are correctly split across SA/IRB/slotting branches."""

    def test_all_exposures_assigned_to_exactly_one_branch(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """No duplicates across SA/IRB/slotting splits."""
        bundle = _make_bundle_with_ratings(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP_CORP",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CP_GOV",
                    entity_type="central_government",
                    annual_revenue=0.0,
                    total_assets=0.0,
                ),
            ],
            loans=[
                make_loan(
                    loan_reference="LN_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_loan(
                    loan_reference="LN_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            facilities=[
                make_facility(
                    facility_reference="FAC_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_facility(
                    facility_reference="FAC_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            ratings=[
                _make_internal_rating(counterparty_reference="CP_CORP", pd=0.02),
            ],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )

        sa_refs = set(
            crm_bundle.sa_exposures.select("exposure_reference")
            .collect()["exposure_reference"]
            .to_list()
        )
        irb_refs = set(
            crm_bundle.irb_exposures.select("exposure_reference")
            .collect()["exposure_reference"]
            .to_list()
        )
        slotting_df = crm_bundle.slotting_exposures
        slotting_refs = (
            set(slotting_df.select("exposure_reference").collect()["exposure_reference"].to_list())
            if slotting_df is not None
            else set()
        )

        # No overlap between branches
        assert sa_refs.isdisjoint(irb_refs), f"SA/IRB overlap: {sa_refs & irb_refs}"
        assert sa_refs.isdisjoint(slotting_refs), f"SA/slotting overlap: {sa_refs & slotting_refs}"
        assert irb_refs.isdisjoint(slotting_refs), (
            f"IRB/slotting overlap: {irb_refs & slotting_refs}"
        )

    def test_branch_results_combine_to_total_exposure_count(
        self, hierarchy_resolver, classifier, crm_processor, crr_firb_config
    ):
        """SA + IRB + slotting = total exposures."""
        bundle = _make_bundle_with_ratings(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP_CORP",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CP_GOV",
                    entity_type="central_government",
                    annual_revenue=0.0,
                    total_assets=0.0,
                ),
            ],
            loans=[
                make_loan(
                    loan_reference="LN_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_loan(
                    loan_reference="LN_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            facilities=[
                make_facility(
                    facility_reference="FAC_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_facility(
                    facility_reference="FAC_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            ratings=[
                _make_internal_rating(counterparty_reference="CP_CORP", pd=0.02),
            ],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )

        total = crm_bundle.exposures.collect().height
        sa_count = crm_bundle.sa_exposures.collect().height
        irb_count = crm_bundle.irb_exposures.collect().height
        slotting_count = (
            crm_bundle.slotting_exposures.collect().height
            if crm_bundle.slotting_exposures is not None
            else 0
        )

        assert sa_count + irb_count + slotting_count == total

    def test_sa_and_irb_approaches_from_mixed_portfolio(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        crr_firb_config,
    ):
        """Mixed portfolio: corporate (FIRB) + sovereign (SA) → each calculator gets correct set."""
        bundle = _make_bundle_with_ratings(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP_CORP",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CP_GOV",
                    entity_type="central_government",
                    annual_revenue=0.0,
                    total_assets=0.0,
                ),
            ],
            loans=[
                make_loan(
                    loan_reference="LN_CORP",
                    counterparty_reference="CP_CORP",
                    drawn_amount=1_000_000.0,
                ),
                make_loan(
                    loan_reference="LN_GOV",
                    counterparty_reference="CP_GOV",
                    drawn_amount=500_000.0,
                ),
            ],
            facilities=[
                make_facility(
                    facility_reference="FAC_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_facility(
                    facility_reference="FAC_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            ratings=[
                _make_internal_rating(counterparty_reference="CP_CORP", pd=0.02),
            ],
        )
        crm_bundle = _run_pipeline(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )

        # SA branch should contain sovereign exposures
        sa_result = sa_calculator.get_sa_result_bundle(crm_bundle, crr_firb_config)
        sa_df = sa_result.results.collect()
        sa_approaches = set(sa_df["approach"].unique().to_list())
        assert ApproachType.SA.value in sa_approaches

        # IRB branch should contain corporate exposures
        irb_result = irb_calculator.get_irb_result_bundle(crm_bundle, crr_firb_config)
        irb_df = irb_result.results.collect()
        irb_approaches = set(irb_df["approach"].unique().to_list())
        assert irb_approaches.issubset({ApproachType.FIRB.value, ApproachType.AIRB.value})

        # Both branches should have results
        assert sa_df.height > 0
        assert irb_df.height > 0
