"""
Tests for cross-approach CCF substitution in guarantee processing.

When an IRB exposure is guaranteed by an SA counterparty, the guaranteed
portion must use SA CCFs (0%, 20%, 50%, 100%) for COREP C07 reporting.
If the guarantor is IRB, the original IRB CCF is retained.

Covers:
- F-IRB + SA guarantor → SA CCF for guaranteed portion
- F-IRB + IRB guarantor → original CCF retained
- SA + SA guarantor → no change
- Fully drawn (nominal=0) → no CCF effect
- Edge cases: LR (both 0%), FR (both 100%), MLR (75% vs 20%)
- A-IRB modelled CCF + SA guarantor
- Mixed batch with SA and FIRB exposures
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crm_processor() -> CRMProcessor:
    """Create CRM processor instance."""
    return CRMProcessor()


@pytest.fixture
def firb_config() -> CalculationConfig:
    """CRR config with F-IRB permissions for corporate."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture
def full_irb_config() -> CalculationConfig:
    """CRR config with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def sa_only_config() -> CalculationConfig:
    """CRR config with SA only (no IRB permissions)."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


def _make_bundle(
    exposures: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    rating_inheritance: pl.LazyFrame | None = None,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle for testing."""
    empty_mappings = pl.LazyFrame(
        schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }
    )
    empty_ultimate = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }
    )
    if rating_inheritance is None:
        rating_inheritance = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "rating_type": pl.String,
            },
        )
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=pl.LazyFrame(),
        equity_exposures=None,
        counterparty_lookup=CounterpartyLookup(
            counterparties=counterparties,
            parent_mappings=empty_mappings,
            ultimate_parent_mappings=empty_ultimate,
            rating_inheritance=rating_inheritance,
        ),
        collateral=None,
        guarantees=guarantees,
        provisions=None,
    )


def _base_exposure(
    ref: str = "EXP001",
    drawn: float = 500.0,
    interest: float = 20.0,
    nominal: float = 300.0,
    risk_type: str = "MR",
    approach: str = "foundation_irb",
    exposure_class: str = "corporate",
    counterparty_ref: str = "BORROWER01",
) -> dict:
    """Return a single exposure row as a dict."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": counterparty_ref,
        "exposure_class": exposure_class,
        "approach": approach,
        "drawn_amount": drawn,
        "interest": interest,
        "nominal_amount": nominal,
        "risk_type": risk_type,
        "lgd": 0.45,
        "seniority": "senior",
    }


def _base_guarantee(
    beneficiary: str = "EXP001",
    guarantor: str = "GUARANTOR01",
    amount: float = 0.0,
    pct: float = 0.6,
) -> dict:
    """Return a single guarantee row as a dict."""
    return {
        "beneficiary_reference": beneficiary,
        "guarantor": guarantor,
        "amount_covered": amount,
        "percentage_covered": pct,
    }


def _base_counterparty(
    ref: str = "GUARANTOR01",
    entity_type: str = "corporate",
) -> dict:
    """Return a single counterparty row as a dict."""
    return {
        "counterparty_reference": ref,
        "entity_type": entity_type,
    }


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposure_rows: list[dict],
    guarantee_rows: list[dict],
    counterparty_rows: list[dict],
    rating_rows: list[dict] | None = None,
) -> pl.DataFrame:
    """Run CRM pipeline and return collected result."""
    exposures = pl.LazyFrame(exposure_rows)
    guarantees = pl.LazyFrame(guarantee_rows)
    counterparties = pl.LazyFrame(counterparty_rows)
    rating_inheritance = pl.LazyFrame(rating_rows) if rating_rows else None

    bundle = _make_bundle(exposures, guarantees, counterparties, rating_inheritance)
    result = processor.get_crm_adjusted_bundle(bundle, config)
    return result.exposures.collect()


# =============================================================================
# Test: F-IRB + SA guarantor → SA CCF for guaranteed portion
# =============================================================================


class TestFIRBWithSAGuarantor:
    """F-IRB exposure guaranteed by SA counterparty should use SA CCFs."""

    def test_mr_risk_type_ccf_recalculation(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        MR risk_type: F-IRB CCF=75%, SA CCF=50%.
        Guaranteed portion should use 50% CCF.

        Worked example:
        drawn=500, interest=20, nominal=300, 60% guaranteed
        on_bal = 520, ratio = 0.60
        guaranteed = (520*0.6) + (300*0.6*0.50) = 312 + 90 = 402
        unguaranteed = (520*0.4) + (300*0.4*0.75) = 208 + 90 = 298
        total EAD = 700 (was 745 with uniform 75% CCF)
        """
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure()],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),  # SA entity type
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantor_approach"][0] == "sa"
        assert row["ccf_original"][0] == pytest.approx(0.75)
        assert row["ccf_guaranteed"][0] == pytest.approx(0.50)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.75)
        assert row["guaranteed_portion"][0] == pytest.approx(402.0)
        assert row["unguaranteed_portion"][0] == pytest.approx(298.0)
        assert row["ead_final"][0] == pytest.approx(700.0)

    def test_mlr_risk_type_large_ccf_difference(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        MLR risk_type: F-IRB CCF=75%, SA CCF=20%.
        Largest CCF difference scenario.
        """
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure(risk_type="MLR")],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["ccf_guaranteed"][0] == pytest.approx(0.20)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.75)
        # on_bal=520, nominal=300, ratio=0.60
        # guaranteed = 520*0.6 + 300*0.6*0.20 = 312 + 36 = 348
        # unguaranteed = 520*0.4 + 300*0.4*0.75 = 208 + 90 = 298
        assert row["guaranteed_portion"][0] == pytest.approx(348.0)
        assert row["unguaranteed_portion"][0] == pytest.approx(298.0)

    def test_fr_risk_type_both_100_percent(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        FR risk_type: both SA and F-IRB CCF = 100%.
        No EAD change despite cross-approach substitution.
        """
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure(risk_type="FR")],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["ccf_guaranteed"][0] == pytest.approx(1.0)
        assert row["ccf_unguaranteed"][0] == pytest.approx(1.0)
        # Both CCFs are 100%, so EAD = 520 + 300 = 820
        assert row["ead_final"][0] == pytest.approx(820.0)

    def test_lr_risk_type_both_0_percent(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        LR risk_type: both SA and F-IRB CCF = 0%.
        No EAD change despite cross-approach substitution.
        """
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure(risk_type="LR")],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["ccf_guaranteed"][0] == pytest.approx(0.0)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.0)
        # on_bal=520, nominal=300 but CCF=0%, so EAD = 520 + 0 = 520
        assert row["ead_final"][0] == pytest.approx(520.0)


# =============================================================================
# Test: F-IRB + IRB guarantor → original CCF retained
# =============================================================================


class TestFIRBWithIRBGuarantor:
    """F-IRB exposure guaranteed by IRB counterparty retains original CCF."""

    def test_irb_guarantor_no_ccf_change(
        self,
        crm_processor: CRMProcessor,
        full_irb_config: CalculationConfig,
    ) -> None:
        """
        When guarantor has IRB permission AND internal rating, original CCF kept.
        """
        result = _run_crm(
            crm_processor,
            full_irb_config,
            [_base_exposure()],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "corporate"),  # IRB entity type
                _base_counterparty("BORROWER01", "corporate"),
            ],
            rating_rows=[
                {
                    "counterparty_reference": "GUARANTOR01",
                    "cqs": None,
                    "pd": 0.005,
                    "rating_type": "internal",
                }
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantor_approach"][0] == "irb"
        assert row["ccf_original"][0] == pytest.approx(0.75)
        assert row["ccf_guaranteed"][0] == pytest.approx(0.75)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.75)

    def test_irb_permitted_but_external_rating_gets_sa(
        self,
        crm_processor: CRMProcessor,
        full_irb_config: CalculationConfig,
    ) -> None:
        """
        Even if IRB is permitted for the class, a guarantor with only an
        external rating (no internal PD) is treated under SA.
        """
        result = _run_crm(
            crm_processor,
            full_irb_config,
            [_base_exposure()],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "corporate"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
            rating_rows=[
                {
                    "counterparty_reference": "GUARANTOR01",
                    "cqs": 2,
                    "pd": None,
                    "rating_type": "external",
                }
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantor_approach"][0] == "sa"
        assert row["ccf_guaranteed"][0] == pytest.approx(0.50)  # SA MR CCF


# =============================================================================
# Test: SA + SA guarantor → no change
# =============================================================================


class TestSAWithSAGuarantor:
    """SA exposure with SA guarantor should have no CCF change."""

    def test_sa_exposure_no_ccf_recalculation(
        self,
        crm_processor: CRMProcessor,
        sa_only_config: CalculationConfig,
    ) -> None:
        """SA exposure guaranteed by SA counterparty — no cross-approach substitution."""
        result = _run_crm(
            crm_processor,
            sa_only_config,
            [_base_exposure(approach="standardised", exposure_class="retail_other")],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "individual"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantor_approach"][0] == "sa"
        # SA MR CCF = 50%, no recalculation needed
        assert row["ccf_original"][0] == pytest.approx(0.50)
        assert row["ccf_guaranteed"][0] == pytest.approx(0.50)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.50)


# =============================================================================
# Test: Fully drawn (nominal=0) → no CCF effect
# =============================================================================


class TestFullyDrawnExposure:
    """Fully drawn exposure with no nominal should have no CCF effect."""

    def test_fully_drawn_no_ccf_impact(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Fully drawn loan (nominal=0) — CCF substitution has no effect."""
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure(nominal=0.0)],
            [_base_guarantee()],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        # No nominal → CCF doesn't matter, needs_ccf_sub = False (nominal > 0 check)
        assert row["ccf_original"][0] == pytest.approx(0.0)  # CCF=0 when nominal=0
        # EAD = drawn + interest = 520
        assert row["ead_final"][0] == pytest.approx(520.0)


# =============================================================================
# Test: A-IRB with modelled CCF + SA guarantor
# =============================================================================


class TestAIRBWithSAGuarantor:
    """A-IRB exposure with modelled CCF guaranteed by SA counterparty."""

    def test_airb_modelled_ccf_replaced_by_sa(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        A-IRB exposure with ccf_modelled=0.65, MR risk_type.
        Guaranteed by SA counterparty (individual → retail_other, SA-only under firb_config).
        Guaranteed portion gets SA CCF (0.50), unguaranteed keeps modelled (0.65).
        """
        exp = _base_exposure(approach="advanced_irb")
        exp["ccf_modelled"] = 0.65

        result = _run_crm(
            crm_processor,
            firb_config,
            [exp],
            [_base_guarantee(pct=0.6, guarantor="GUARANTOR01")],
            [
                _base_counterparty(
                    "GUARANTOR01", "individual"
                ),  # SA (retail_other under firb_config)
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantor_approach"][0] == "sa"
        assert row["ccf_original"][0] == pytest.approx(0.65)
        assert row["ccf_guaranteed"][0] == pytest.approx(0.50)
        assert row["ccf_unguaranteed"][0] == pytest.approx(0.65)


# =============================================================================
# Test: Mixed batch — SA and FIRB exposures with SA guarantors
# =============================================================================


class TestMixedBatch:
    """Mixed batch with SA and FIRB exposures — only FIRB gets recalculation."""

    def test_only_firb_gets_ccf_recalculation(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """In a mixed batch, only FIRB exposure gets CCF recalculation."""
        sa_exp = _base_exposure(
            ref="SA_EXP",
            approach="standardised",
            exposure_class="retail_other",
            counterparty_ref="BORROWER_SA",
        )
        firb_exp = _base_exposure(
            ref="FIRB_EXP",
            approach="foundation_irb",
            exposure_class="corporate",
            counterparty_ref="BORROWER_FIRB",
        )

        result = _run_crm(
            crm_processor,
            firb_config,
            [sa_exp, firb_exp],
            [
                _base_guarantee(beneficiary="SA_EXP", guarantor="GUARANTOR01"),
                _base_guarantee(beneficiary="FIRB_EXP", guarantor="GUARANTOR01"),
            ],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER_SA", "individual"),
                _base_counterparty("BORROWER_FIRB", "corporate"),
            ],
        )

        sa_row = result.filter(pl.col("exposure_reference") == "SA_EXP")
        firb_row = result.filter(pl.col("exposure_reference") == "FIRB_EXP")

        # SA exposure: no recalculation (SA→SA)
        assert sa_row["ccf_original"][0] == pytest.approx(0.50)
        assert sa_row["ccf_guaranteed"][0] == pytest.approx(0.50)  # SA CCF = same

        # FIRB exposure: recalculated (IRB→SA)
        assert firb_row["ccf_original"][0] == pytest.approx(0.75)
        assert firb_row["ccf_guaranteed"][0] == pytest.approx(0.50)  # SA CCF


# =============================================================================
# Test: Guarantee ratio calculation
# =============================================================================


class TestGuaranteeRatio:
    """Tests for guarantee_ratio calculation."""

    def test_guarantee_ratio_capped_at_1(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Guarantee ratio should be capped at 1.0 even if guarantee > EAD."""
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure()],
            [_base_guarantee(amount=99999.0, pct=0.0)],  # Huge guarantee amount
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantee_ratio"][0] <= 1.0

    def test_100_percent_guarantee(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """100% guarantee: entire EAD uses SA CCF."""
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure()],
            [_base_guarantee(pct=1.0)],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["guarantee_ratio"][0] == pytest.approx(1.0)
        assert row["unguaranteed_portion"][0] == pytest.approx(0.0)
        # All EAD uses SA CCF: 520 + 300*0.5 = 670
        assert row["ead_final"][0] == pytest.approx(670.0)

    def test_negative_drawn_with_sa_guarantor(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Negative drawn should be floored at 0 in cross-approach CCF split.

        drawn=-100, interest=10, nominal=300, MR risk_type, 60% SA guarantee.
        on_bal = max(-100, 0) + 10 = 10 (not -90).
        Guaranteed:   10*0.6 + 300*0.6*0.5 = 6 + 90 = 96
        Unguaranteed: 10*0.4 + 300*0.4*0.75 = 4 + 90 = 94
        ead_final = 96 + 94 = 190
        """
        result = _run_crm(
            crm_processor,
            firb_config,
            [_base_exposure(drawn=-100.0, interest=10.0, nominal=300.0)],
            [_base_guarantee(pct=0.6)],
            [
                _base_counterparty("GUARANTOR01", "individual"),
                _base_counterparty("BORROWER01", "corporate"),
            ],
        )

        row = result.filter(pl.col("exposure_reference") == "EXP001")
        # on_bal should use floored drawn (0, not -100)
        assert row["ead_final"][0] == pytest.approx(190.0)
