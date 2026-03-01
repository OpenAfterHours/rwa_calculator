"""
Unit tests for Basel 3.1 SA risk weights.

Tests cover Basel 3.1 risk weight changes from CRR:
- Residential RE: LTV-band risk weights (general + income-producing)
- Commercial RE: Preferential treatment + income-producing LTV bands
- ADC exposures: 150% default, 100% pre-sold
- Revised corporate CQS weights: CQS3 = 75% (was 100%), CQS5 = 100% (was 150%)
- SCRA-based institution weights for unrated: Grade A (40%), B (75%), C (150%)
- Investment-grade corporate: 65% risk weight
- SME corporate: 85% risk weight (was 100%)
- Subordinated debt: flat 150% risk weight
- CRR regression: existing CRR risk weights unchanged

Why these tests matter:
    Basel 3.1 replaces CRR's simple binary LTV splits with granular LTV-band
    risk weights and introduces differentiated CQS-based corporate weights,
    SCRA grading for unrated institutions, and special treatments for
    investment-grade corporates, SME corporates, and subordinated debt.
    These changes fundamentally alter SA RWA and directly impact output floor
    calculations for IRB firms.

References:
- CRE20.16-21: Institution ECRA/SCRA risk weights
- CRE20.22-26: Revised corporate CQS risk weights
- CRE20.47-49: Subordinated debt, investment-grade, SME corporate
- CRE20.73: Residential RE (general) whole-loan LTV bands
- CRE20.82: Residential RE (income-producing) LTV bands
- CRE20.85: Commercial RE (general) preferential treatment
- CRE20.86: Commercial RE (income-producing) LTV bands
- CRE20.87-88: ADC exposures
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_risk_weights import (
    B31_ADC_PRESOLD_RISK_WEIGHT,
    B31_ADC_RISK_WEIGHT,
    B31_COMMERCIAL_GENERAL_PREFERENTIAL_CAP,
    B31_COMMERCIAL_INCOME_LTV_BANDS,
    B31_CORPORATE_INVESTMENT_GRADE_RW,
    B31_CORPORATE_RISK_WEIGHTS,
    B31_CORPORATE_SME_RW,
    B31_RESIDENTIAL_GENERAL_LTV_BANDS,
    B31_RESIDENTIAL_INCOME_LTV_BANDS,
    B31_SCRA_RISK_WEIGHTS,
    B31_SUBORDINATED_DEBT_RW,
    get_b31_combined_cqs_risk_weights,
    lookup_b31_commercial_rw,
    lookup_b31_residential_rw,
)
from rwa_calc.engine.sa import SACalculator

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration (post-2027)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration (pre-2027)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# RESIDENTIAL RE — GENERAL (CRE20.73)
# =============================================================================


class TestB31ResidentialGeneral:
    """Basel 3.1 residential RE risk weights — general (not income-producing).

    Whole-loan approach (CRE20.73): risk weight applied to entire exposure
    based on LTV band. Seven bands from 20% to 70%.
    """

    @pytest.mark.parametrize(
        ("ltv", "expected_rw"),
        [
            (Decimal("0.30"), Decimal("0.20")),  # LTV 30% → 20%
            (Decimal("0.50"), Decimal("0.20")),  # LTV 50% (boundary) → 20%
            (Decimal("0.55"), Decimal("0.25")),  # LTV 55% → 25%
            (Decimal("0.60"), Decimal("0.25")),  # LTV 60% (boundary) → 25%
            (Decimal("0.65"), Decimal("0.25")),  # LTV 65% → 25%
            (Decimal("0.70"), Decimal("0.25")),  # LTV 70% (boundary) → 25%
            (Decimal("0.75"), Decimal("0.30")),  # LTV 75% → 30%
            (Decimal("0.80"), Decimal("0.30")),  # LTV 80% (boundary) → 30%
            (Decimal("0.85"), Decimal("0.40")),  # LTV 85% → 40%
            (Decimal("0.90"), Decimal("0.40")),  # LTV 90% (boundary) → 40%
            (Decimal("0.95"), Decimal("0.50")),  # LTV 95% → 50%
            (Decimal("1.00"), Decimal("0.50")),  # LTV 100% (boundary) → 50%
            (Decimal("1.10"), Decimal("0.70")),  # LTV 110% → 70%
            (Decimal("1.50"), Decimal("0.70")),  # LTV 150% → 70%
        ],
        ids=[
            "ltv_30pct",
            "ltv_50pct_boundary",
            "ltv_55pct",
            "ltv_60pct_boundary",
            "ltv_65pct",
            "ltv_70pct_boundary",
            "ltv_75pct",
            "ltv_80pct_boundary",
            "ltv_85pct",
            "ltv_90pct_boundary",
            "ltv_95pct",
            "ltv_100pct_boundary",
            "ltv_110pct",
            "ltv_150pct",
        ],
    )
    def test_ltv_band_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        ltv: Decimal,
        expected_rw: Decimal,
    ) -> None:
        """Each LTV band maps to the correct risk weight under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=ltv,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(expected_rw)

    def test_null_ltv_defaults_to_highest_band(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null LTV should default to 1.0 (fill_null) → 50% band."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=None,
            config=b31_config,
        )

        # fill_null(1.0) → LTV=1.0 → 90-100% band → 50%
        assert result["risk_weight"] == pytest.approx(Decimal("0.50"))

    def test_rwa_calculation(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """RWA = EAD × RW for a Basel 3.1 residential mortgage."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.65"),  # 60-70% band → 25%
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.25"))
        assert result["rwa"] == pytest.approx(Decimal("100000"))  # 400k × 25%


# =============================================================================
# RESIDENTIAL RE — INCOME-PRODUCING (CRE20.82)
# =============================================================================


class TestB31ResidentialIncomeProducing:
    """Basel 3.1 residential RE risk weights — income-producing.

    Applies to exposures materially dependent on cash flows from the property
    (e.g., buy-to-let). Higher risk weights than general residential.
    """

    @pytest.mark.parametrize(
        ("ltv", "expected_rw"),
        [
            (Decimal("0.30"), Decimal("0.30")),  # LTV 30% → 30%
            (Decimal("0.50"), Decimal("0.30")),  # LTV 50% (boundary) → 30%
            (Decimal("0.55"), Decimal("0.35")),  # LTV 55% → 35%
            (Decimal("0.65"), Decimal("0.45")),  # LTV 65% → 45%
            (Decimal("0.75"), Decimal("0.50")),  # LTV 75% → 50%
            (Decimal("0.85"), Decimal("0.60")),  # LTV 85% → 60%
            (Decimal("0.95"), Decimal("0.75")),  # LTV 95% → 75%
            (Decimal("1.10"), Decimal("1.05")),  # LTV 110% → 105%
        ],
        ids=[
            "ltv_30pct",
            "ltv_50pct_boundary",
            "ltv_55pct",
            "ltv_65pct",
            "ltv_75pct",
            "ltv_85pct",
            "ltv_95pct",
            "ltv_110pct",
        ],
    )
    def test_income_producing_ltv_band(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        ltv: Decimal,
        expected_rw: Decimal,
    ) -> None:
        """Income-producing residential RE uses higher risk weight table."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=ltv,
            has_income_cover=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(expected_rw)


# =============================================================================
# COMMERCIAL RE — GENERAL (CRE20.85)
# =============================================================================


class TestB31CommercialREGeneral:
    """Basel 3.1 commercial RE (general) — preferential treatment.

    For CRE not materially dependent on property cash flows:
    - LTV ≤ 60%: min(60%, counterparty risk weight)
    - LTV > 60%: counterparty risk weight (no cap)
    """

    def test_low_ltv_unrated_corporate_capped_at_60pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated corporate CRE (100% cp RW), LTV ≤ 60% → capped at 60%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.55],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Counterparty RW = 100% (unrated corporate fallback), min(60%, 100%) = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_low_ltv_rated_corporate_uses_lower_cp_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 1 corporate CRE (20% cp RW), LTV ≤ 60% → min(60%, 20%) = 20%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["CORPORATE"],
                "cqs": [1],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "property_type": ["commercial"],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # CQS 1 corporate RW = 20%, min(60%, 20%) = 20%
        assert df["risk_weight"][0] == pytest.approx(0.20)

    def test_high_ltv_uses_counterparty_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE LTV > 60%, general → counterparty RW (no cap)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.75],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Unrated corporate fallback = 100%, LTV > 60% → no cap → 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_boundary_ltv_60pct_gets_preferential(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV exactly 60% qualifies for preferential treatment."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.60],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # LTV = 60% ≤ 60% → min(60%, 100%) = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)


# =============================================================================
# COMMERCIAL RE — INCOME-PRODUCING (CRE20.86)
# =============================================================================


class TestB31CommercialREIncomeProducing:
    """Basel 3.1 commercial RE (income-producing) — LTV bands.

    Fixed risk weights by LTV band: 70% / 90% / 110%.
    """

    @pytest.mark.parametrize(
        ("ltv", "expected_rw"),
        [
            (Decimal("0.40"), Decimal("0.70")),  # LTV 40% → 70%
            (Decimal("0.60"), Decimal("0.70")),  # LTV 60% (boundary) → 70%
            (Decimal("0.70"), Decimal("0.90")),  # LTV 70% → 90%
            (Decimal("0.80"), Decimal("0.90")),  # LTV 80% (boundary) → 90%
            (Decimal("0.90"), Decimal("1.10")),  # LTV 90% → 110%
            (Decimal("1.20"), Decimal("1.10")),  # LTV 120% → 110%
        ],
        ids=[
            "ltv_40pct",
            "ltv_60pct_boundary",
            "ltv_70pct",
            "ltv_80pct_boundary",
            "ltv_90pct",
            "ltv_120pct",
        ],
    )
    def test_income_producing_cre_ltv_band(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        ltv: Decimal,
        expected_rw: Decimal,
    ) -> None:
        """Income-producing CRE uses fixed LTV-band risk weights."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [float(ltv)],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(float(expected_rw))


# =============================================================================
# ADC EXPOSURES (CRE20.87-88)
# =============================================================================


class TestB31ADCExposures:
    """Basel 3.1 ADC exposure risk weights.

    Land acquisition, development and construction: 150% default.
    Pre-sold/pre-let to qualifying buyer: 100%.
    """

    def test_adc_default_150pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """ADC exposure should get 150% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="CORPORATE",
            is_adc=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("1.50"))
        assert result["rwa"] == pytest.approx(Decimal("3000000"))  # 2m × 150%

    def test_adc_presold_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Pre-sold ADC exposure should get 100% RW."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="CORPORATE",
            is_adc=True,
            is_presold=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("1.00"))
        assert result["rwa"] == pytest.approx(Decimal("2000000"))  # 2m × 100%

    def test_adc_takes_priority_over_re(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """ADC flag should override RE LTV-band treatment."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),  # Would be 20% under B31 LTV bands
            is_adc=True,
            config=b31_config,
        )

        # ADC overrides: 150%, not 20%
        assert result["risk_weight"] == pytest.approx(Decimal("1.50"))

    def test_adc_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """ADC flag should be ignored under CRR (no ADC treatment in CRR SA)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_adc=True,
            config=crr_config,
        )

        # Under CRR, no ADC treatment → standard corporate unrated 100%
        assert result["risk_weight"] == pytest.approx(Decimal("1.0"))


# =============================================================================
# SCALAR LOOKUP FUNCTIONS
# =============================================================================


class TestScalarLookups:
    """Tests for convenience scalar lookup functions."""

    def test_residential_general_lookup(self) -> None:
        """Scalar lookup matches LTV band table."""
        for band in B31_RESIDENTIAL_GENERAL_LTV_BANDS:
            ltv = band["ltv_lower"] + Decimal("0.01") if band["ltv_lower"] > 0 else Decimal("0.10")
            rw, desc = lookup_b31_residential_rw(ltv, is_income_producing=False)
            assert rw == band["risk_weight"], f"LTV {ltv}: expected {band['risk_weight']}, got {rw}"

    def test_residential_income_lookup(self) -> None:
        """Scalar lookup for income-producing residential matches table."""
        for band in B31_RESIDENTIAL_INCOME_LTV_BANDS:
            ltv = band["ltv_lower"] + Decimal("0.01") if band["ltv_lower"] > 0 else Decimal("0.10")
            rw, desc = lookup_b31_residential_rw(ltv, is_income_producing=True)
            assert rw == band["risk_weight"], f"LTV {ltv}: expected {band['risk_weight']}, got {rw}"

    def test_commercial_general_low_ltv(self) -> None:
        """Commercial general CRE: min(60%, counterparty RW) for LTV ≤ 60%."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("1.00"),
            is_income_producing=False,
        )
        assert rw == B31_COMMERCIAL_GENERAL_PREFERENTIAL_CAP  # min(60%, 100%) = 60%

    def test_commercial_general_low_ltv_lower_cp_rw(self) -> None:
        """Commercial general CRE: min(60%, 20%) = 20% for CQS 1."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("0.20"),
            is_income_producing=False,
        )
        assert rw == Decimal("0.20")

    def test_commercial_general_high_ltv(self) -> None:
        """Commercial general CRE: counterparty RW for LTV > 60%."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.75"),
            counterparty_rw=Decimal("1.00"),
            is_income_producing=False,
        )
        assert rw == Decimal("1.00")

    def test_commercial_income_producing_lookup(self) -> None:
        """Commercial income-producing CRE uses LTV band table."""
        for band in B31_COMMERCIAL_INCOME_LTV_BANDS:
            ltv = band["ltv_lower"] + Decimal("0.01") if band["ltv_lower"] > 0 else Decimal("0.10")
            rw, _ = lookup_b31_commercial_rw(ltv, is_income_producing=True)
            assert rw == band["risk_weight"]


# =============================================================================
# CRR REGRESSION — existing risk weights unchanged
# =============================================================================


class TestCRRRegression:
    """Ensure CRR risk weights remain unchanged after Basel 3.1 additions."""

    def test_crr_residential_low_ltv_35pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR residential mortgage LTV ≤ 80% → 35% (unchanged)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.60"),
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.35"))

    def test_crr_residential_high_ltv_split(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR residential mortgage LTV 100% → split treatment (unchanged)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.00"),
            config=crr_config,
        )

        expected_rw = 0.80 * 0.35 + 0.20 * 0.75  # 43%
        assert float(result["risk_weight"]) == pytest.approx(expected_rw, rel=0.01)

    def test_crr_commercial_re_low_ltv_with_income_50pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR commercial RE LTV ≤ 50% with income cover → 50% (unchanged)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [600000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.40],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.50)

    def test_crr_sovereign_still_works(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR sovereign CQS 1 → 0% (unchanged)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
            cqs=1,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.0"))

    def test_crr_retail_still_works(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR retail → 75% (unchanged)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("100000"),
            exposure_class="RETAIL",
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.75"))

    def test_crr_institution_uk_deviation_still_works(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR institution CQS 2 UK deviation → 30% (unchanged)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(Decimal("0.30"))


# =============================================================================
# CROSS-FRAMEWORK COMPARISON
# =============================================================================


class TestCRRvsBasel31Comparison:
    """Compare CRR and Basel 3.1 risk weights for the same exposure."""

    def test_low_ltv_mortgage_b31_lower(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> None:
        """At 50% LTV, Basel 3.1 (20%) is lower than CRR (35%)."""
        crr_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),
            config=crr_config,
        )

        b31_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),
            config=b31_config,
        )

        assert float(crr_result["risk_weight"]) == pytest.approx(0.35)
        assert float(b31_result["risk_weight"]) == pytest.approx(0.20)
        assert b31_result["rwa"] < crr_result["rwa"]

    def test_high_ltv_mortgage_b31_higher(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> None:
        """At 110% LTV, Basel 3.1 (70%) is higher than CRR split (~43%)."""
        crr_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.10"),
            config=crr_config,
        )

        b31_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.10"),
            config=b31_config,
        )

        # CRR split: (0.80/1.10)*0.35 + (0.30/1.10)*0.75 ≈ 0.459
        # B31: 70% flat
        assert float(b31_result["risk_weight"]) == pytest.approx(0.70)
        assert b31_result["rwa"] > crr_result["rwa"]

    def test_supporting_factors_disabled_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME supporting factor should be 1.0 under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_sme=True,
            config=b31_config,
        )

        assert result["supporting_factor"] == pytest.approx(Decimal("1.0"))
        assert result["rwa"] == pytest.approx(Decimal("1000000"))


# =============================================================================
# TABLE DATA INTEGRITY
# =============================================================================


class TestTableDataIntegrity:
    """Verify Basel 3.1 risk weight table data is consistent and complete."""

    def test_residential_general_bands_cover_full_range(self) -> None:
        """Residential general bands should cover 0% to infinity."""
        assert B31_RESIDENTIAL_GENERAL_LTV_BANDS[0]["ltv_lower"] == Decimal("0.00")
        assert B31_RESIDENTIAL_GENERAL_LTV_BANDS[-1]["ltv_upper"] == Decimal("999.0")

    def test_residential_general_bands_contiguous(self) -> None:
        """Each band's lower bound should equal the previous band's upper bound."""
        bands = B31_RESIDENTIAL_GENERAL_LTV_BANDS
        for i in range(1, len(bands)):
            assert bands[i]["ltv_lower"] == bands[i - 1]["ltv_upper"]

    def test_residential_income_bands_higher_rw(self) -> None:
        """Income-producing RWs should be ≥ general RWs at each LTV band."""
        for gen, inc in zip(
            B31_RESIDENTIAL_GENERAL_LTV_BANDS,
            B31_RESIDENTIAL_INCOME_LTV_BANDS,
            strict=True,
        ):
            assert inc["risk_weight"] >= gen["risk_weight"]

    def test_adc_risk_weights(self) -> None:
        """ADC risk weight constants should be correct."""
        assert Decimal("1.50") == B31_ADC_RISK_WEIGHT
        assert Decimal("1.00") == B31_ADC_PRESOLD_RISK_WEIGHT

    def test_seven_residential_bands(self) -> None:
        """Should have exactly 7 LTV bands for residential RE."""
        assert len(B31_RESIDENTIAL_GENERAL_LTV_BANDS) == 7
        assert len(B31_RESIDENTIAL_INCOME_LTV_BANDS) == 7

    def test_three_commercial_income_bands(self) -> None:
        """Should have exactly 3 LTV bands for commercial income-producing."""
        assert len(B31_COMMERCIAL_INCOME_LTV_BANDS) == 3

    def test_b31_corporate_cqs_table_values(self) -> None:
        """Basel 3.1 corporate CQS table should have correct values."""
        assert B31_CORPORATE_RISK_WEIGHTS[1] == Decimal("0.20")
        assert B31_CORPORATE_RISK_WEIGHTS[2] == Decimal("0.50")
        assert B31_CORPORATE_RISK_WEIGHTS[3] == Decimal("0.75")  # Changed from CRR 100%
        assert B31_CORPORATE_RISK_WEIGHTS[4] == Decimal("1.00")
        assert B31_CORPORATE_RISK_WEIGHTS[5] == Decimal("1.00")  # Changed from CRR 150%
        assert B31_CORPORATE_RISK_WEIGHTS[6] == Decimal("1.50")
        assert B31_CORPORATE_RISK_WEIGHTS[None] == Decimal("1.00")

    def test_scra_risk_weight_values(self) -> None:
        """SCRA risk weight constants should be correct."""
        assert B31_SCRA_RISK_WEIGHTS["A"] == Decimal("0.40")
        assert B31_SCRA_RISK_WEIGHTS["B"] == Decimal("0.75")
        assert B31_SCRA_RISK_WEIGHTS["C"] == Decimal("1.50")

    def test_investment_grade_rw(self) -> None:
        """Investment-grade corporate constant should be 65%."""
        assert B31_CORPORATE_INVESTMENT_GRADE_RW == Decimal("0.65")

    def test_sme_corporate_rw(self) -> None:
        """SME corporate constant should be 85%."""
        assert B31_CORPORATE_SME_RW == Decimal("0.85")

    def test_subordinated_debt_rw(self) -> None:
        """Subordinated debt constant should be 150%."""
        assert B31_SUBORDINATED_DEBT_RW == Decimal("1.50")

    def test_b31_combined_cqs_table_has_all_classes(self) -> None:
        """B31 combined CQS table should include sovereign, institution, corporate."""
        df = get_b31_combined_cqs_risk_weights()
        classes = set(df["exposure_class"].to_list())
        assert "CENTRAL_GOVT_CENTRAL_BANK" in classes
        assert "INSTITUTION" in classes
        assert "CORPORATE" in classes

    def test_b31_combined_cqs_table_corporate_cqs3_is_75pct(self) -> None:
        """B31 combined table should have 75% for corporate CQS3 (not CRR's 100%)."""
        df = get_b31_combined_cqs_risk_weights()
        corp_cqs3 = df.filter(
            (pl.col("exposure_class") == "CORPORATE") & (pl.col("cqs") == 3)
        )
        assert corp_cqs3["risk_weight"][0] == pytest.approx(0.75)


# =============================================================================
# REVISED CORPORATE CQS RISK WEIGHTS (CRE20.22-26)
# =============================================================================


class TestB31CorporateCQS:
    """Basel 3.1 revised corporate CQS-based risk weights.

    Key changes from CRR:
    - CQS 3 (BBB): 75% (was 100%)
    - CQS 5 (B): 100% (was 150%)
    Other CQS grades unchanged.

    Why this matters:
        The reduced CQS 3 and CQS 5 weights lower SA RWA for BBB- and B-rated
        corporates, affecting output floor calculations for IRB firms holding
        investment-grade corporate portfolios.
    """

    @pytest.mark.parametrize(
        ("cqs", "expected_b31_rw", "expected_crr_rw"),
        [
            (1, 0.20, 0.20),   # AAA-AA-: unchanged
            (2, 0.50, 0.50),   # A+-A-: unchanged
            (3, 0.75, 1.00),   # BBB: 75% vs 100%
            (4, 1.00, 1.00),   # BB: unchanged
            (5, 1.00, 1.50),   # B: 100% vs 150%
            (6, 1.50, 1.50),   # CCC+: unchanged
            (None, 1.00, 1.00),  # Unrated: unchanged
        ],
        ids=["cqs1", "cqs2", "cqs3_changed", "cqs4", "cqs5_changed", "cqs6", "unrated"],
    )
    def test_corporate_cqs_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        crr_config: CalculationConfig,
        cqs: int | None,
        expected_b31_rw: float,
        expected_crr_rw: float,
    ) -> None:
        """Corporate CQS risk weights differ between CRR and Basel 3.1."""
        b31_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=cqs,
            config=b31_config,
        )
        crr_result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=cqs,
            config=crr_config,
        )

        assert float(b31_result["risk_weight"]) == pytest.approx(expected_b31_rw)
        assert float(crr_result["risk_weight"]) == pytest.approx(expected_crr_rw)

    def test_corporate_cqs3_rwa_reduction(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        crr_config: CalculationConfig,
    ) -> None:
        """CQS 3 corporate: Basel 3.1 RWA should be 25% lower than CRR."""
        ead = Decimal("1000000")
        b31 = sa_calculator.calculate_single_exposure(
            ead=ead, exposure_class="corporate", cqs=3, config=b31_config,
        )
        crr = sa_calculator.calculate_single_exposure(
            ead=ead, exposure_class="corporate", cqs=3, config=crr_config,
        )

        # B31: 1M × 75% = 750k, CRR: 1M × 100% = 1M
        assert float(b31["rwa"]) == pytest.approx(750_000.0)
        assert float(crr["rwa"]) == pytest.approx(1_000_000.0)


# =============================================================================
# SCRA-BASED INSTITUTION RISK WEIGHTS (CRE20.16-21)
# =============================================================================


class TestB31SCRAInstitutionWeights:
    """Basel 3.1 SCRA-based risk weights for unrated institutions.

    Under Basel 3.1, unrated institutions are classified by SCRA grade
    based on their capital ratios:
    - Grade A (CET1 > 14%, Leverage > 5%): 40% RW
    - Grade B (CET1 > 5.5%, Leverage > 3%): 75% RW
    - Grade C (below minimums): 150% RW

    Under CRR, unrated institutions get 40% (UK deviation from sovereign CQS2).

    Why this matters:
        SCRA replaces the single 40% default for unrated institutions with a
        risk-sensitive grading. Grade B and C institutions now carry higher
        capital charges, while Grade A institutions retain the 40% weight.
    """

    @pytest.mark.parametrize(
        ("scra_grade", "expected_rw"),
        [
            ("A", 0.40),   # Well-capitalised: same as CRR default
            ("B", 0.75),   # Meets minimums: higher than CRR default
            ("C", 1.50),   # Below minimums: much higher
        ],
        ids=["grade_A", "grade_B", "grade_C"],
    )
    def test_scra_grade_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        scra_grade: str,
        expected_rw: float,
    ) -> None:
        """Unrated institution risk weight determined by SCRA grade under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=scra_grade,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(expected_rw)

    def test_scra_not_applied_when_rated(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated institutions use ECRA (CQS-based), not SCRA, even if grade provided."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=2,  # CQS 2 → 30% (UK deviation)
            scra_grade="C",  # Would be 150% under SCRA
            config=b31_config,
        )

        # ECRA takes precedence: CQS 2 → 30%
        assert float(result["risk_weight"]) == pytest.approx(0.30)

    def test_scra_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SCRA should be ignored under CRR — unrated institutions get 40%."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="C",  # Would be 150% under Basel 3.1
            config=crr_config,
        )

        # CRR: unrated institution → 40% (UK deviation)
        assert float(result["risk_weight"]) == pytest.approx(0.40)

    def test_scra_none_unrated_institution_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated institution without SCRA grade uses CQS table default under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=None,  # No SCRA grade provided
            config=b31_config,
        )

        # Falls through to CQS-based unrated institution → 40% (UK deviation)
        assert float(result["risk_weight"]) == pytest.approx(0.40)

    def test_scra_grade_b_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Grade B institution: verify full RWA calculation."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="B",
            config=b31_config,
        )

        # 10M × 75% = 7.5M
        assert float(result["rwa"]) == pytest.approx(7_500_000.0)


# =============================================================================
# INVESTMENT-GRADE CORPORATE (CRE20.47-49)
# =============================================================================


class TestB31InvestmentGradeCorporate:
    """Basel 3.1 investment-grade corporate risk weight: 65%.

    Qualifying: publicly traded + investment grade external rating.
    This is a preferential treatment for qualifying unrated corporates.

    Why this matters:
        The 65% weight (vs 100% unrated default) significantly reduces SA RWA
        for large, well-capitalised corporates, narrowing the gap between SA
        and IRB capital requirements for investment-grade portfolios.
    """

    def test_investment_grade_65pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Investment-grade corporate gets 65% under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=True,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.65)
        assert float(result["rwa"]) == pytest.approx(1_300_000.0)  # 2M × 65%

    def test_investment_grade_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Investment-grade treatment does not exist under CRR → 100%."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=True,
            config=crr_config,
        )

        # CRR: no investment-grade treatment → standard unrated 100%
        assert float(result["risk_weight"]) == pytest.approx(1.00)

    def test_investment_grade_not_applied_to_sme(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Investment-grade flag should not apply to corporate_sme class."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="corporate_sme",
            cqs=None,
            is_investment_grade=True,
            config=b31_config,
        )

        # SME corporate gets 85%, not 65% (SME treatment takes priority)
        assert float(result["risk_weight"]) == pytest.approx(0.85)

    def test_rated_corporate_uses_cqs_not_investment_grade(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated corporate uses CQS-based weight, not investment-grade override."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=1,
            is_investment_grade=True,
            config=b31_config,
        )

        # CQS 1 → 20% (from CQS table, not 65%)
        assert float(result["risk_weight"]) == pytest.approx(0.20)


# =============================================================================
# SME CORPORATE RISK WEIGHT (CRE20.47-49, Basel 3.1)
# =============================================================================


class TestB31SMECorporate:
    """Basel 3.1 SME corporate risk weight: 85% (was 100% under CRR).

    Applies to unrated SME corporates (turnover <= EUR 50m).

    Why this matters:
        The 15pp reduction from 100% to 85% for SME corporates under Basel 3.1
        partially compensates for the removal of CRR Art. 501 SME supporting
        factor (0.7619x discount).
    """

    def test_sme_corporate_85pct_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME corporate gets 85% under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.85)
        assert float(result["rwa"]) == pytest.approx(425_000.0)  # 500k × 85%

    def test_sme_corporate_100pct_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SME corporate gets 100% under CRR (no preferential treatment)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            config=crr_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(1.00)

    def test_sme_managed_as_retail_still_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME managed as retail keeps 75% under both frameworks."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            is_managed_as_retail=True,
            config=b31_config,
        )

        # Managed-as-retail overrides SME corporate → 75%
        assert float(result["risk_weight"]) == pytest.approx(0.75)


# =============================================================================
# SUBORDINATED DEBT RISK WEIGHT (CRE20.47, Basel 3.1)
# =============================================================================


class TestB31SubordinatedDebt:
    """Basel 3.1 subordinated debt: flat 150% risk weight.

    Under Basel 3.1, all subordinated debt (institution + corporate) receives
    150% RW regardless of CQS. This overrides the CQS-based lookup.

    Under CRR, subordinated debt uses the same CQS-based table as senior
    debt (with different LGD under IRB only).

    Why this matters:
        The flat 150% creates a significant capital surcharge for subordinated
        debt holdings, reflecting the higher loss-given-default risk of
        subordinated instruments. This particularly impacts interbank
        exposures where Tier 2 capital instruments are held.
    """

    def test_subordinated_corporate_150pct_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Subordinated corporate debt gets flat 150% under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=1,  # CQS 1 would normally be 20%
            seniority="subordinated",
            config=b31_config,
        )

        # Subordinated debt overrides CQS 1 → 150%
        assert float(result["risk_weight"]) == pytest.approx(1.50)

    def test_subordinated_institution_150pct_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Subordinated institution debt gets flat 150% under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=2,  # CQS 2 would normally be 30% (UK)
            seniority="subordinated",
            config=b31_config,
        )

        # Subordinated debt overrides CQS 2 → 150%
        assert float(result["risk_weight"]) == pytest.approx(1.50)
        assert float(result["rwa"]) == pytest.approx(7_500_000.0)  # 5M × 150%

    def test_subordinated_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Subordinated debt uses normal CQS table under CRR (no override)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=1,
            seniority="subordinated",
            config=crr_config,
        )

        # CRR: subordinated treated same as senior for SA → CQS 1 = 20%
        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_senior_debt_unaffected_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Senior debt uses normal CQS-based weight under Basel 3.1."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=1,
            seniority="senior",
            config=b31_config,
        )

        # Senior debt: CQS 1 → 20% (unchanged)
        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_subordinated_overrides_investment_grade(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Subordinated debt 150% takes priority over investment-grade 65%."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=None,
            seniority="subordinated",
            is_investment_grade=True,
            config=b31_config,
        )

        # Subordinated debt checked first → 150% (not 65%)
        assert float(result["risk_weight"]) == pytest.approx(1.50)

    def test_subordinated_not_applied_to_sovereign(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Subordinated debt override only applies to institution + corporate."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            exposure_class="central_govt_central_bank",
            cqs=1,
            seniority="subordinated",
            config=b31_config,
        )

        # Sovereign: subordinated debt override does not apply → CQS 1 = 0%
        assert float(result["risk_weight"]) == pytest.approx(0.00)

    def test_subordinated_sme_corporate_150pct_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Subordinated SME corporate debt gets flat 150% (not 85%)."""
        result = sa_calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            seniority="subordinated",
            config=b31_config,
        )

        # Subordinated overrides SME treatment → 150%
        assert float(result["risk_weight"]) == pytest.approx(1.50)
