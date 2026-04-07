"""Unit tests for P1.67: SA specialised lending as corporate sub-type.

Under SA, specialised lending is a corporate sub-type (Art. 112(1)(g) / Art. 112
Table A2) — not a separate exposure class.  Under IRB, SL is a legitimate
separate sub-class (Art. 147(8)).

This file tests:
- Classifier sets exposure_class_sa = CORPORATE for SL
- Classifier keeps exposure_class = SPECIALISED_LENDING (approach routing)
- ENTITY_TYPE_TO_SA_CLASS maps SL → CORPORATE
- COREP C 07.00 merges SL into corporate (no separate SL sheet)
- SA calculator risk weights are unaffected (regression)
- Approach routing still works (SL gets SLOTTING/AIRB correctly)

References:
- CRR Art. 112(1)(g), Art. 112 Table A2
- CRR Art. 147(8)
- PRA PS1/26 Art. 122A-122B (SA SL risk weights)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    PermissionMode,
)
from rwa_calc.engine.classifier import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
    ExposureClassifier,
)
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.reporting.corep.generator import COREPGenerator

# =============================================================================
# Helpers (same pattern as test_b31_approach_restrictions.py)
# =============================================================================


def _make_counterparty(
    ref: str = "CP001",
    entity_type: str = "corporate",
    annual_revenue: float = 100_000_000.0,
    default_status: bool = False,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "counterparty_reference": [ref],
            "counterparty_name": [f"Test {ref}"],
            "entity_type": [entity_type],
            "country_code": ["GB"],
            "annual_revenue": [annual_revenue],
            "total_assets": [500_000_000.0],
            "default_status": [default_status],
            "sector_code": ["MANU"],
            "apply_fi_scalar": [False],
            "is_managed_as_retail": [False],
        }
    ).lazy()


def _make_exposure(
    ref: str = "EXP001",
    cp_ref: str = "CP001",
    lgd: float | None = 0.45,
    internal_pd: float | None = 0.005,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": [ref],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [cp_ref],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [5_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [lgd],
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            "internal_pd": [internal_pd],
        }
    ).lazy()


def _make_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    specialised_lending: pl.LazyFrame | None = None,
) -> ResolvedHierarchyBundle:
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )
    exp_schema = exposures.collect_schema()
    if "residential_collateral_value" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.lit(0.0).alias("residential_collateral_value"),
        )
    if "exposure_for_retail_threshold" not in exp_schema.names():
        exposures = exposures.with_columns(
            (
                pl.col("drawn_amount")
                + pl.col("nominal_amount")
                - pl.col("residential_collateral_value")
            ).alias("exposure_for_retail_threshold"),
        )
    if "lending_group_adjusted_exposure" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
        )
    return ResolvedHierarchyBundle(
        exposures=exposures,
        counterparty_lookup=CounterpartyLookup(
            counterparties=enriched_cp,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        specialised_lending=specialised_lending,
        model_permissions=None,
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_drawn": pl.Float64,
                "total_nominal": pl.Float64,
                "total_exposure": pl.Float64,
                "adjusted_exposure": pl.Float64,
                "total_residential_coverage": pl.Float64,
                "exposure_count": pl.UInt32,
            }
        ),
    )


def _make_sl_table(sl_type: str, is_hvcre: bool = False) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "counterparty_reference": ["CP001"],
            "sl_type": [sl_type],
            "slotting_category": ["good"],
            "is_hvcre": [is_hvcre],
        }
    ).lazy()


def _classify(
    entity_type: str = "corporate",
    specialised_lending: pl.LazyFrame | None = None,
    framework: str = "b31",
    default_status: bool = False,
    lgd: float | None = 0.45,
    internal_pd: float | None = 0.005,
) -> pl.DataFrame:
    cp = _make_counterparty(entity_type=entity_type, default_status=default_status)
    exp = _make_exposure(lgd=lgd, internal_pd=internal_pd)
    bundle = _make_bundle(exp, cp, specialised_lending=specialised_lending)

    if framework == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )

    classifier = ExposureClassifier()
    result = classifier.classify(bundle, config)
    collected = result.all_exposures.collect()
    assert isinstance(collected, pl.DataFrame)
    return collected


# =============================================================================
# Entity-type mapping constants
# =============================================================================


class TestEntityTypeMappingConstants:
    """ENTITY_TYPE_TO_SA_CLASS and ENTITY_TYPE_TO_IRB_CLASS for SL."""

    def test_sa_class_maps_sl_to_corporate(self) -> None:
        """Art. 112(1)(g): SL is a corporate sub-type under SA."""
        assert ENTITY_TYPE_TO_SA_CLASS["specialised_lending"] == ExposureClass.CORPORATE.value

    def test_irb_class_maps_sl_to_specialised_lending(self) -> None:
        """Art. 147(8): SL is a legitimate separate class under IRB."""
        assert (
            ENTITY_TYPE_TO_IRB_CLASS["specialised_lending"]
            == ExposureClass.SPECIALISED_LENDING.value
        )

    def test_sa_and_irb_class_differ_for_sl(self) -> None:
        """SA and IRB class maps should disagree for specialised_lending."""
        assert (
            ENTITY_TYPE_TO_SA_CLASS["specialised_lending"]
            != ENTITY_TYPE_TO_IRB_CLASS["specialised_lending"]
        )

    def test_sa_class_corporate_matches_direct_corporate(self) -> None:
        """SL entity_type under SA should give the same class as 'corporate'."""
        assert (
            ENTITY_TYPE_TO_SA_CLASS["specialised_lending"] == ENTITY_TYPE_TO_SA_CLASS["corporate"]
        )


# =============================================================================
# Classifier — exposure_class_sa vs exposure_class
# =============================================================================


class TestClassifierSLExposureClass:
    """Classifier assigns CORPORATE to exposure_class_sa but keeps
    SPECIALISED_LENDING on exposure_class for approach routing."""

    def test_exposure_class_sa_is_corporate_via_sl_join(self) -> None:
        """SL join: exposure_class_sa = CORPORATE."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl)
        assert df["exposure_class_sa"][0] == ExposureClass.CORPORATE.value

    def test_exposure_class_irb_is_sl_via_sl_join(self) -> None:
        """SL join: exposure_class_irb = SPECIALISED_LENDING."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl)
        assert df["exposure_class_irb"][0] == ExposureClass.SPECIALISED_LENDING.value

    def test_exposure_class_is_sl_for_approach_routing(self) -> None:
        """Primary exposure_class stays SPECIALISED_LENDING for approach routing."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl)
        assert df["exposure_class"][0] == ExposureClass.SPECIALISED_LENDING.value

    def test_exposure_class_for_sa_is_corporate_via_sl_join(self) -> None:
        """SA floor path: exposure_class_for_sa = CORPORATE for non-defaulted SL."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl)
        assert df["exposure_class_for_sa"][0] == ExposureClass.CORPORATE.value

    def test_exposure_class_for_sa_defaulted_sl(self) -> None:
        """Defaulted SL gets DEFAULTED in exposure_class_for_sa (priority)."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl, default_status=True)
        assert df["exposure_class_for_sa"][0] == ExposureClass.DEFAULTED.value

    def test_exposure_class_sa_corporate_via_entity_type(self) -> None:
        """entity_type='specialised_lending' also gives exposure_class_sa=CORPORATE."""
        df = _classify(entity_type="specialised_lending")
        assert df["exposure_class_sa"][0] == ExposureClass.CORPORATE.value

    def test_crr_exposure_class_sa_corporate(self) -> None:
        """CRR framework: SL entity_type gives exposure_class_sa=CORPORATE."""
        df = _classify(entity_type="specialised_lending", framework="crr")
        assert df["exposure_class_sa"][0] == ExposureClass.CORPORATE.value

    def test_non_sl_corporate_unaffected(self) -> None:
        """Regular corporate is not affected by SL reclassification."""
        df = _classify(entity_type="corporate")
        assert df["exposure_class_sa"][0] == ExposureClass.CORPORATE.value
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value


# =============================================================================
# Approach routing — SL still gets SLOTTING/AIRB/SA correctly
# =============================================================================


class TestSLApproachRoutingUnchanged:
    """SL approach routing must still work because exposure_class retains
    SPECIALISED_LENDING for the Phase 5 approach expression."""

    def test_ipre_forced_to_slotting_b31(self) -> None:
        """IPRE under B31 → forced SLOTTING (Art. 147A(1)(c))."""
        sl = _make_sl_table("ipre")
        df = _classify(specialised_lending=sl, framework="b31")
        assert df["approach"][0] == ApproachType.SLOTTING.value

    def test_hvcre_forced_to_slotting_b31(self) -> None:
        """HVCRE under B31 → forced SLOTTING."""
        sl = _make_sl_table("hvcre", is_hvcre=True)
        df = _classify(specialised_lending=sl, framework="b31")
        assert df["approach"][0] == ApproachType.SLOTTING.value

    def test_pf_can_get_airb_b31(self) -> None:
        """Project finance under B31 can use AIRB when permission + rating exist."""
        sl = _make_sl_table("project_finance")
        df = _classify(specialised_lending=sl, framework="b31")
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_sl_entity_type_without_sl_table_gets_sa(self) -> None:
        """entity_type='specialised_lending' without SL table → SA fallback."""
        df = _classify(entity_type="specialised_lending", lgd=None, internal_pd=None)
        assert df["approach"][0] == ApproachType.SA.value


# =============================================================================
# COREP — SL merged into corporate for SA C 07.00
# =============================================================================


class TestCOREPSLMergedIntoCorporate:
    """COREP C 07.00 should include SA SL data under the corporate sheet."""

    def test_no_separate_sl_key_in_c07(self) -> None:
        """C 07.00 dict should NOT have a 'specialised_lending' key."""
        gen = COREPGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_1", "SL_1"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "specialised_lending"],
                "drawn_amount": [1000.0, 2000.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [1000.0, 2000.0],
                "risk_weight": [1.00, 1.00],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        assert "specialised_lending" not in bundle.c07_00
        assert "corporate" in bundle.c07_00

    def test_sl_ead_included_in_corporate_total(self) -> None:
        """Corporate total row includes both regular corporate and SL EAD."""
        gen = COREPGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_1", "SL_1"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "specialised_lending"],
                "drawn_amount": [1000.0, 2000.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [1000.0, 2000.0],
                "risk_weight": [1.00, 1.00],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        corp_df = bundle.c07_00["corporate"]
        total_row = corp_df.filter(pl.col("row_ref") == "0010")
        # EAD col 0200 should aggregate both corporate (1000) + SL (2000) = 3000
        assert total_row["0200"][0] == pytest.approx(3000.0)

    def test_sl_rwa_included_in_corporate_total(self) -> None:
        """Corporate total row includes SL RWA."""
        gen = COREPGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_1", "SL_1"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "specialised_lending"],
                "drawn_amount": [1000.0, 2000.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, 2600.0],
                "risk_weight": [0.50, 1.30],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        corp_df = bundle.c07_00["corporate"]
        total_row = corp_df.filter(pl.col("row_ref") == "0010")
        # RWA col 0220 should aggregate 500 + 2600 = 3100
        assert total_row["0220"][0] == pytest.approx(3100.0)

    def test_sl_only_no_regular_corporate(self) -> None:
        """SL-only SA data still appears under 'corporate' key."""
        gen = COREPGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SL_1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["specialised_lending"],
                "drawn_amount": [5000.0],
                "undrawn_amount": [0.0],
                "ead_final": [5000.0],
                "rwa_final": [5000.0],
                "risk_weight": [1.00],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        assert "specialised_lending" not in bundle.c07_00
        assert "corporate" in bundle.c07_00

    def test_irb_sl_still_separate_class(self) -> None:
        """IRB SL stays as 'specialised_lending' in C 08.01 (Art. 147(8))."""
        gen = COREPGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SL_IRB_1"],
                "approach_applied": ["slotting"],
                "exposure_class": ["specialised_lending"],
                "drawn_amount": [10000.0],
                "undrawn_amount": [0.0],
                "ead_final": [10000.0],
                "rwa_final": [9000.0],
                "risk_weight": [0.90],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        # IRB SL stays as its own class
        assert "specialised_lending" in bundle.c08_01


# =============================================================================
# SA calculator regression — risk weights unchanged
# =============================================================================


class TestSACalculatorSLRegressionB31:
    """SA calculator still produces correct SL risk weights after
    the classifier change.  The SA calculator reads exposure_class (which
    remains SPECIALISED_LENDING) and sl_type for routing."""

    @pytest.fixture()
    def sa_calculator(self) -> SACalculator:
        return SACalculator()

    @pytest.fixture()
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

    @pytest.mark.parametrize(
        ("sl_type", "sl_project_phase", "expected_rw"),
        [
            ("object_finance", None, 1.00),
            ("commodities_finance", None, 1.00),
            ("project_finance", "pre_operational", 1.30),
            ("project_finance", "operational", 1.00),
            ("project_finance", "high_quality", 0.80),
        ],
        ids=["OF_100", "CF_100", "PF_pre_130", "PF_op_100", "PF_hq_80"],
    )
    def test_sl_risk_weight_unchanged(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        sl_type: str,
        sl_project_phase: str | None,
        expected_rw: float,
    ) -> None:
        """SL risk weights per Art. 122A/B are unaffected by reclassification."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": [sl_type],
                "sl_project_phase": [sl_project_phase],
            }
        ).lazy()

        result = sa_calculator.calculate_branch(exposures, b31_config).collect()
        assert result["risk_weight"][0] == pytest.approx(expected_rw)

    def test_rated_sl_uses_corporate_cqs_table(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated SL still uses corporate CQS table (Art. 122A(3))."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_RATED"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [1],
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": ["project_finance"],
                "sl_project_phase": [None],
            }
        ).lazy()

        result = sa_calculator.calculate_branch(exposures, b31_config).collect()
        # CQS 1 corporate → 20%
        assert result["risk_weight"][0] == pytest.approx(0.20)
