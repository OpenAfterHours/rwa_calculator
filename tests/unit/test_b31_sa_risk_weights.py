"""
Unit tests for Basel 3.1 SA risk weights.

Tests cover the Basel 3.1 real estate risk weight changes:
- Residential RE: LTV-band risk weights (general + income-producing)
- Commercial RE: Preferential treatment + income-producing LTV bands
- ADC exposures: 150% default, 100% pre-sold
- CRR regression: existing CRR risk weights unchanged

Why these tests matter:
    Basel 3.1 replaces CRR's simple binary LTV splits with granular LTV-band
    risk weights. This is a fundamental change to SA real estate RWA and
    directly impacts output floor calculations for IRB firms.

References:
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
    B31_RESIDENTIAL_GENERAL_LTV_BANDS,
    B31_RESIDENTIAL_INCOME_LTV_BANDS,
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
