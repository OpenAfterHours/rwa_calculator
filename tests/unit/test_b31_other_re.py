"""
Tests for Basel 3.1 Other Real Estate (Art. 124J) risk weights.

Non-qualifying RE — real estate that fails Art. 124A criteria (independent valuation,
first charge, etc.) — has three sub-treatments:
- Income-dependent: 150% flat
- RESI non-dependent: counterparty RW (no floor)
- CRE non-dependent: max(60%, counterparty RW)

References:
- PRA PS1/26 Art. 124J
- docs/specifications/crr/sa-risk-weights.md §Other Real Estate
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_risk_weights import (
    B31_OTHER_RE_CRE_FLOOR_RW,
    B31_OTHER_RE_INCOME_DEPENDENT_RW,
    b31_other_re_rw_expr,
    lookup_b31_other_re_rw,
)
from rwa_calc.engine.sa import SACalculator


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _make_bundle(data: dict) -> CRMAdjustedBundle:
    """Build a CRMAdjustedBundle from a column dict."""
    df = pl.DataFrame(data).lazy()
    return CRMAdjustedBundle(exposures=df, sa_exposures=df, irb_exposures=pl.LazyFrame())


# =============================================================================
# CONSTANT TESTS
# =============================================================================


class TestOtherREConstants:
    """Art. 124J risk weight constants."""

    def test_income_dependent_rw(self) -> None:
        assert B31_OTHER_RE_INCOME_DEPENDENT_RW == Decimal("1.50")

    def test_cre_floor_rw(self) -> None:
        assert B31_OTHER_RE_CRE_FLOOR_RW == Decimal("0.60")


# =============================================================================
# EXPRESSION BUILDER TESTS
# =============================================================================


class TestOtherREExpression:
    """Vectorised Polars expression for Art. 124J Other RE."""

    def test_income_dependent_residential_150pct(self) -> None:
        """Income-dependent RESI Other RE → 150% regardless of cp RW."""
        df = pl.DataFrame({
            "has_income_cover": [True],
            "property_type": ["residential"],
            "_cqs_risk_weight": [0.20],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(1.50)

    def test_income_dependent_commercial_150pct(self) -> None:
        """Income-dependent CRE Other RE → 150% regardless of property type."""
        df = pl.DataFrame({
            "has_income_cover": [True],
            "property_type": ["commercial"],
            "_cqs_risk_weight": [0.50],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(1.50)

    def test_resi_non_dependent_uses_cp_rw(self) -> None:
        """Non-dependent RESI Other RE → counterparty RW (no floor)."""
        df = pl.DataFrame({
            "has_income_cover": [False],
            "property_type": ["residential"],
            "_cqs_risk_weight": [0.75],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(0.75)

    def test_resi_non_dependent_low_cp_rw(self) -> None:
        """Non-dependent RESI Other RE with low cp RW — no 60% floor."""
        df = pl.DataFrame({
            "has_income_cover": [False],
            "property_type": ["residential"],
            "_cqs_risk_weight": [0.20],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(0.20)

    def test_cre_non_dependent_max_60_cp_rw(self) -> None:
        """Non-dependent CRE Other RE → max(60%, cp RW). cp=100% → 100%."""
        df = pl.DataFrame({
            "has_income_cover": [False],
            "property_type": ["commercial"],
            "_cqs_risk_weight": [1.00],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(1.00)

    def test_cre_non_dependent_floor_binds(self) -> None:
        """Non-dependent CRE Other RE — 60% floor binds when cp RW < 60%."""
        df = pl.DataFrame({
            "has_income_cover": [False],
            "property_type": ["commercial"],
            "_cqs_risk_weight": [0.20],
        })
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(0.60)

    def test_null_income_defaults_non_dependent(self) -> None:
        """Null has_income_cover → non-dependent (conservative for CRE)."""
        df = pl.DataFrame(
            {
                "has_income_cover": [None],
                "property_type": ["commercial"],
                "_cqs_risk_weight": [1.00],
            },
            schema_overrides={"has_income_cover": pl.Boolean},
        )
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(1.00)

    def test_null_property_type_defaults_commercial(self) -> None:
        """Null property_type → not residential → CRE path with 60% floor."""
        df = pl.DataFrame(
            {
                "has_income_cover": [False],
                "property_type": [None],
                "_cqs_risk_weight": [0.20],
            },
            schema_overrides={"property_type": pl.Utf8},
        )
        result = df.select(b31_other_re_rw_expr().alias("rw"))
        assert result["rw"][0] == pytest.approx(0.60)


# =============================================================================
# SCALAR LOOKUP TESTS
# =============================================================================


class TestOtherREScalarLookup:
    """Single-exposure lookup for Art. 124J."""

    def test_income_dependent(self) -> None:
        rw, desc = lookup_b31_other_re_rw(
            property_type="residential", is_income_producing=True
        )
        assert rw == Decimal("1.50")
        assert "income-dependent" in desc
        assert "124J" in desc

    def test_resi_non_dependent(self) -> None:
        rw, desc = lookup_b31_other_re_rw(
            property_type="residential",
            is_income_producing=False,
            counterparty_rw=Decimal("0.75"),
        )
        assert rw == Decimal("0.75")
        assert "RESI" in desc
        assert "124J" in desc

    def test_cre_non_dependent_floor_binds(self) -> None:
        rw, desc = lookup_b31_other_re_rw(
            property_type="commercial",
            is_income_producing=False,
            counterparty_rw=Decimal("0.20"),
        )
        assert rw == Decimal("0.60")
        assert "CRE" in desc

    def test_cre_non_dependent_cp_above_floor(self) -> None:
        rw, desc = lookup_b31_other_re_rw(
            property_type="commercial",
            is_income_producing=False,
            counterparty_rw=Decimal("1.50"),
        )
        assert rw == Decimal("1.50")


# =============================================================================
# SA CALCULATOR INTEGRATION TESTS
# =============================================================================


class TestOtherRESACalculator:
    """Full SA calculator integration for Art. 124J Other RE."""

    def test_non_qualifying_resi_income_150pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying income-dependent RESI → 150%."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE001"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [True],
            "is_qualifying_re": [False],
            "property_type": ["residential"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.50)

    def test_non_qualifying_resi_non_income_cp_rw(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying non-dependent RESI → counterparty RW (100% for unrated corp)."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE002"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.60],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "is_qualifying_re": [False],
            "property_type": ["residential"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        # Unrated counterparty RW = 1.0 (from CQS table fallback)
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_non_qualifying_cre_income_150pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying income-dependent CRE → 150%."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE003"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["corporate"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [True],
            "is_qualifying_re": [False],
            "property_type": ["commercial"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.50)

    def test_non_qualifying_cre_non_income_max_60_cp(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying non-dependent CRE → max(60%, cp RW). Unrated corp = 100%."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE004"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["corporate"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "is_qualifying_re": [False],
            "property_type": ["commercial"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_non_qualifying_cre_rated_cqs1_floor_binds(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying CRE with CQS 1 (20%) → max(60%, 20%) = 60%."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE005"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["corporate"],
            "cqs": [1],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "is_qualifying_re": [False],
            "property_type": ["commercial"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_qualifying_re_unchanged(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Qualifying RE (is_qualifying_re=True) → standard loan-splitting treatment."""
        bundle = _make_bundle({
            "exposure_reference": ["QRE001"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "is_qualifying_re": [True],
            "property_type": ["residential"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        # Qualifying RESI: loan-splitting at 55% threshold
        # LTV=50%, secured_share = min(1.0, 0.55/0.50) = 1.0 → fully secured at 20%
        assert df["risk_weight"][0] == pytest.approx(0.20)

    def test_null_qualifying_defaults_to_qualifying(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Null is_qualifying_re → defaults to qualifying (True). Backward compatible."""
        bundle = _make_bundle({
            "exposure_reference": ["QRE002"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "property_type": ["residential"],
        })
        # is_qualifying_re not set → null → treated as qualifying
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        # Should get qualifying RESI treatment (20% at LTV 50%)
        assert df["risk_weight"][0] == pytest.approx(0.20)

    def test_missing_column_defaults_to_qualifying(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Missing is_qualifying_re column → defaults to qualifying via _ensure_columns."""
        data = {
            "exposure_reference": ["QRE003"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "property_type": ["residential"],
        }
        df = pl.DataFrame(data).lazy()
        # Confirm column is NOT in the schema
        assert "is_qualifying_re" not in df.collect_schema().names()
        bundle = CRMAdjustedBundle(
            exposures=df, sa_exposures=df, irb_exposures=pl.LazyFrame()
        )
        result = sa_calculator.calculate(bundle, b31_config)
        df_out = result.frame.collect()
        # Should get qualifying RESI treatment (20%)
        assert df_out["risk_weight"][0] == pytest.approx(0.20)

    def test_rwa_correctness(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """RWA = EAD × RW for non-qualifying income-dependent RE."""
        ead = 2_000_000.0
        bundle = _make_bundle({
            "exposure_reference": ["ORE006"],
            "ead_final": [ead],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.70],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [True],
            "is_qualifying_re": [False],
            "property_type": ["residential"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()
        assert df["risk_weight"][0] == pytest.approx(1.50)
        assert df["rwa_post_factor"][0] == pytest.approx(ead * 1.50)

    def test_crr_no_other_re_treatment(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR has no Other RE concept — non-qualifying flag is ignored."""
        bundle = _make_bundle({
            "exposure_reference": ["ORE007"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
            "is_qualifying_re": [False],
            "property_type": ["residential"],
        })
        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()
        # CRR: standard mortgage treatment regardless of is_qualifying_re
        # LTV 50% ≤ 80% threshold → 35% residential RW (Art. 125)
        assert df["risk_weight"][0] == pytest.approx(0.35)

    def test_non_qualifying_vs_qualifying_comparison(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying gets higher RW than qualifying for same RESI exposure."""
        base = {
            "ead_final": [1_000_000.0],
            "exposure_class": ["retail_mortgage"],
            "cqs": [None],
            "ltv": [0.50],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [True],
            "property_type": ["residential"],
        }
        # Qualifying: income-producing RESI → 30% (first LTV band)
        q_bundle = _make_bundle({
            **base,
            "exposure_reference": ["Q001"],
            "is_qualifying_re": [True],
        })
        q_result = sa_calculator.calculate(q_bundle, b31_config)
        q_df = q_result.frame.collect()

        # Non-qualifying: income-dependent → 150%
        nq_bundle = _make_bundle({
            **base,
            "exposure_reference": ["NQ001"],
            "is_qualifying_re": [False],
        })
        nq_result = sa_calculator.calculate(nq_bundle, b31_config)
        nq_df = nq_result.frame.collect()

        assert nq_df["risk_weight"][0] > q_df["risk_weight"][0]
        assert q_df["risk_weight"][0] == pytest.approx(0.30)  # Income-producing RESI
        assert nq_df["risk_weight"][0] == pytest.approx(1.50)  # Other RE income

    def test_mixed_batch_qualifying_and_non_qualifying(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Mixed batch: qualifying and non-qualifying exposures processed correctly."""
        bundle = _make_bundle({
            "exposure_reference": ["Q001", "NQ001", "NQ002"],
            "ead_final": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "exposure_class": ["retail_mortgage", "retail_mortgage", "corporate"],
            "cqs": [None, None, None],
            "ltv": [0.50, 0.50, 0.50],
            "is_sme": [False, False, False],
            "is_infrastructure": [False, False, False],
            "has_income_cover": [False, True, False],
            "is_qualifying_re": [True, False, False],
            "property_type": ["residential", "residential", "commercial"],
        })
        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect().sort("exposure_reference")
        # NQ001: non-qualifying RESI income → 150%
        assert df["risk_weight"][0] == pytest.approx(1.50)
        # NQ002: non-qualifying CRE non-income → max(60%, 100%) = 100%
        assert df["risk_weight"][1] == pytest.approx(1.00)
        # Q001: qualifying RESI non-income → 20% (fully secured at LTV 50%)
        assert df["risk_weight"][2] == pytest.approx(0.20)
