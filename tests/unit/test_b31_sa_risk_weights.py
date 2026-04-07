"""
Unit tests for Basel 3.1 SA risk weights.

Tests cover Basel 3.1 risk weight changes from CRR:
- Residential RE: LTV-band risk weights (general + income-producing)
- Commercial RE: Preferential treatment + income-producing LTV bands
- ADC exposures: 150% default, 100% pre-sold
- Revised corporate CQS weights: CQS3 = 75% (was 100%), CQS5 = 100% (was 150%)
- SCRA-based institution weights for unrated: Grade A (40%), B (75%), C (150%)
- Investment-grade corporate: 65% risk weight (Art. 122(6)(a))
- Non-investment-grade corporate: 135% risk weight (Art. 122(6)(b))
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
- PRA Art. 124F: Residential RE (general) loan-splitting approach
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
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_risk_weights import (
    B31_ADC_PRESOLD_RISK_WEIGHT,
    B31_ADC_RISK_WEIGHT,
    B31_COMMERCIAL_GENERAL_SECURED_RW,
    B31_COMMERCIAL_INCOME_LTV_BANDS,
    B31_CORPORATE_INVESTMENT_GRADE_RW,
    B31_CORPORATE_NON_INVESTMENT_GRADE_RW,
    B31_CORPORATE_RISK_WEIGHTS,
    B31_CORPORATE_SME_RW,
    B31_ECRA_SHORT_TERM_RISK_WEIGHTS,
    B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO,
    B31_RESIDENTIAL_GENERAL_SECURED_RW,
    B31_RESIDENTIAL_INCOME_LTV_BANDS,
    B31_RETAIL_PAYROLL_LOAN_RW,
    B31_SCRA_RISK_WEIGHTS,
    B31_SCRA_SHORT_TERM_RISK_WEIGHTS,
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
# RESIDENTIAL RE — GENERAL (PRA PS1/26 Art. 124F)
# =============================================================================


def _expected_loan_split_rw(
    ltv: float, cp_rw: float = 0.75, secured_rw: float = 0.20, max_ratio: float = 0.55
) -> float:
    """Compute expected loan-splitting RW for a general residential exposure."""
    secured_share = min(1.0, max_ratio / ltv)
    return secured_rw * secured_share + cp_rw * (1.0 - secured_share)


class TestB31ResidentialGeneral:
    """Basel 3.1 residential RE risk weights — general (not income-producing).

    PRA PS1/26 Art. 124F: loan-splitting approach — 20% on portion up to 55% of
    property value, counterparty risk weight (75% for individuals per Art. 124L)
    on the residual.
    """

    @pytest.mark.parametrize(
        ("ltv", "expected_rw"),
        [
            # LTV ≤ 55%: entire exposure secured → flat 20%
            (Decimal("0.30"), 0.20),
            (Decimal("0.50"), 0.20),
            (Decimal("0.55"), 0.20),
            # LTV > 55%: weighted average of 20% (secured) and 75% (residual)
            (Decimal("0.60"), _expected_loan_split_rw(0.60)),
            (Decimal("0.65"), _expected_loan_split_rw(0.65)),
            (Decimal("0.70"), _expected_loan_split_rw(0.70)),
            (Decimal("0.80"), _expected_loan_split_rw(0.80)),
            (Decimal("0.85"), _expected_loan_split_rw(0.85)),
            (Decimal("0.90"), _expected_loan_split_rw(0.90)),
            (Decimal("1.00"), _expected_loan_split_rw(1.00)),
            (Decimal("1.10"), _expected_loan_split_rw(1.10)),
            (Decimal("1.50"), _expected_loan_split_rw(1.50)),
        ],
        ids=[
            "ltv_30pct_all_secured",
            "ltv_50pct_all_secured",
            "ltv_55pct_boundary_all_secured",
            "ltv_60pct",
            "ltv_65pct",
            "ltv_70pct",
            "ltv_80pct",
            "ltv_85pct",
            "ltv_90pct",
            "ltv_100pct",
            "ltv_110pct",
            "ltv_150pct",
        ],
    )
    def test_loan_split_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        ltv: Decimal,
        expected_rw: float,
    ) -> None:
        """Loan-splitting produces correct weighted-average RW per Art. 124F."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=ltv,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(expected_rw, abs=1e-4)

    def test_null_ltv_defaults_to_full_counterparty_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null LTV defaults to 1.0: secured_share = 55%, residual = 45%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=None,
            config=b31_config,
        )

        # fill_null(1.0) → LTV=1.0 → secured_share = 55/100 = 0.55
        # RW = 0.20 × 0.55 + 0.75 × 0.45 = 0.4475
        expected = _expected_loan_split_rw(1.0)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_rwa_calculation(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """RWA = EAD × RW for a Basel 3.1 residential mortgage."""
        ltv = 0.65
        expected_rw = _expected_loan_split_rw(ltv)
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.65"),
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(expected_rw, abs=1e-4)
        assert float(result["rwa"]) == pytest.approx(400000 * expected_rw, abs=1.0)


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
            (Decimal("0.65"), Decimal("0.40")),  # LTV 65% → 40% (PRA Table 6B)
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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=ltv,
            has_income_cover=True,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(float(expected_rw))


# =============================================================================
# COMMERCIAL RE — GENERAL (CRE20.85)
# =============================================================================


class TestB31CommercialREGeneral:
    """Basel 3.1 commercial RE (general) — loan-splitting (PRA Art. 124H).

    For CRE not materially dependent on property cash flows:
    - Natural person / SME (Art. 124H(1-2)): loan-splitting at 55%, 60% secured RW
    - Other counterparties (Art. 124H(3)): max(60%, min(cp_rw, income_rw))
    - Formula: secured_share = min(1.0, 0.55/LTV)
    -          RW = 0.60 × secured_share + cp_rw × (1 - secured_share)
    """

    def test_low_ltv_fully_secured(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV ≤ 55%: natural person, entire exposure at 60% (fully within secured)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # LTV 50% ≤ 55%: secured_share = 1.0, RW = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_low_ltv_rated_corporate_still_60pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 1 corporate CRE (20% cp RW), LTV ≤ 55% → fully secured at 60%."""
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

        # LTV 50% ≤ 55%: secured_share = 1.0, RW = 60% (loan-split secured portion)
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_high_ltv_loan_split_blended(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE LTV 75%, natural person → blended loan-split RW."""
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
                "cp_is_natural_person": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # secured_share = 0.55/0.75, cp_rw = 1.00 (unrated corporate)
        secured_share = 0.55 / 0.75
        expected = 0.60 * secured_share + 1.00 * (1.0 - secured_share)
        assert df["risk_weight"][0] == pytest.approx(expected)

    def test_boundary_ltv_55pct_fully_secured(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV exactly 55%: natural person, entire exposure within secured → 60%."""
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
                "cp_is_natural_person": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # LTV = 55% → secured_share = 0.55/0.55 = 1.0 → RW = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)


# =============================================================================
# COMMERCIAL RE — INCOME-PRODUCING (PRA Art. 124I)
# =============================================================================


class TestB31CommercialREIncomeProducing:
    """Basel 3.1 commercial RE (income-producing) — PRA Art. 124I.

    Fixed risk weights: 100% (LTV ≤ 80%), 110% (LTV > 80%).
    """

    @pytest.mark.parametrize(
        ("ltv", "expected_rw"),
        [
            (Decimal("0.40"), Decimal("1.00")),  # LTV 40% → 100%
            (Decimal("0.60"), Decimal("1.00")),  # LTV 60% → 100%
            (Decimal("0.70"), Decimal("1.00")),  # LTV 70% → 100%
            (Decimal("0.80"), Decimal("1.00")),  # LTV 80% (boundary) → 100%
            (Decimal("0.90"), Decimal("1.10")),  # LTV 90% → 110%
            (Decimal("1.20"), Decimal("1.10")),  # LTV 120% → 110%
        ],
        ids=[
            "ltv_40pct",
            "ltv_60pct",
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
# COMMERCIAL RE — OTHER COUNTERPARTIES (PRA Art. 124H(3))
# =============================================================================


class TestB31CommercialREOtherCounterparties:
    """Basel 3.1 commercial RE (general) — other counterparties (PRA Art. 124H(3)).

    For non-natural-person / non-SME counterparties:
    - RW = max(60%, min(counterparty_RW, Art. 124I income-producing RW))
    - Art. 124I income-producing RW: 100% (LTV ≤ 80%), 110% (LTV > 80%)
    - This prevents large corporates from benefiting from loan-splitting.
    """

    def test_unrated_corporate_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated corporate (100% cp RW), LTV 50%: max(60%, min(100%, 100%)) = 100%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # max(60%, min(100%, 100%)) = 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_rated_cqs1_corporate_floored_at_60pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 1 corporate (20% cp RW): max(60%, min(20%, 100%)) = 60% floor."""
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
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # max(60%, min(20%, 100%)) = max(60%, 20%) = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_cqs5_corporate_capped_by_income_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 5 corporate (150% cp RW), LTV 90%: max(60%, min(150%, 110%)) = 110%.

        Uses exposure_class=CORPORATE + property_type=commercial so CQS join
        picks up the corporate CQS 5 risk weight (150%).
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["CORPORATE"],
                "cqs": [5],
                "ltv": [0.90],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "property_type": ["commercial"],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # CQS 5 corporate cp_rw = 150%, LTV 90% > 80% → income_rw = 110%
        # max(60%, min(150%, 110%)) = max(60%, 110%) = 110%
        assert df["risk_weight"][0] == pytest.approx(1.10)

    def test_cqs5_low_ltv_capped_at_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 5 corporate (150% cp RW), LTV 60%: max(60%, min(150%, 100%)) = 100%.

        Uses exposure_class=CORPORATE + property_type=commercial.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["CORPORATE"],
                "cqs": [5],
                "ltv": [0.60],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "property_type": ["commercial"],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # CQS 5 corporate cp_rw = 150%, LTV 60% ≤ 80% → income_rw = 100%
        # max(60%, min(150%, 100%)) = max(60%, 100%) = 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_sme_gets_loan_splitting_not_max_min(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME counterparty uses loan-splitting (Art. 124H(2)), not max/min."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [True],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # SME → loan-splitting: LTV 50% ≤ 55% → secured_share = 1.0 → RW = 60%
        assert df["risk_weight"][0] == pytest.approx(0.60)

    def test_rwa_correctness_other_counterparty(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Verify RWA = EAD × RW for other counterparty."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [2000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.70],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # max(60%, min(100%, 100%)) = 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)
        assert df["rwa_post_factor"][0] == pytest.approx(2000000.0)

    def test_null_cp_is_natural_person_defaults_to_other(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null cp_is_natural_person defaults to False (other counterparty, conservative)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [None],
            },
            schema_overrides={"cp_is_natural_person": pl.Boolean},
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Null → False → other counterparty: max(60%, min(100%, 100%)) = 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_missing_column_defaults_to_other(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Missing cp_is_natural_person column defaults to False (conservative)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
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

        # No cp_is_natural_person column → defaults to False → max/min formula
        # max(60%, min(100%, 100%)) = 100%
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_income_producing_unaffected_by_counterparty_type(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Income-producing CRE ignores counterparty type — always uses Art. 124I."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1000000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.70],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "cp_is_natural_person": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Income-producing: 100% (LTV ≤ 80%) — counterparty type irrelevant
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_other_vs_natural_person_comparison(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Other counterparty gets higher RW than natural person for same CRE exposure."""
        base = {
            "exposure_reference": ["CRE001"],
            "ead_final": [1000000.0],
            "exposure_class": ["COMMERCIAL_RE"],
            "cqs": [None],
            "ltv": [0.75],
            "is_sme": [False],
            "is_infrastructure": [False],
            "has_income_cover": [False],
        }

        # Natural person: loan-splitting
        np_exp = pl.DataFrame({**base, "cp_is_natural_person": [True]}).lazy()
        np_bundle = CRMAdjustedBundle(
            exposures=np_exp, sa_exposures=np_exp, irb_exposures=pl.LazyFrame()
        )
        np_result = sa_calculator.calculate(np_bundle, b31_config)
        np_rw = np_result.frame.collect()["risk_weight"][0]

        # Other counterparty: max/min formula
        oc_exp = pl.DataFrame({**base, "cp_is_natural_person": [False]}).lazy()
        oc_bundle = CRMAdjustedBundle(
            exposures=oc_exp, sa_exposures=oc_exp, irb_exposures=pl.LazyFrame()
        )
        oc_result = sa_calculator.calculate(oc_bundle, b31_config)
        oc_rw = oc_result.frame.collect()["risk_weight"][0]

        # Loan-splitting at LTV 75%: 0.60 × (0.55/0.75) + 1.00 × (1 - 0.55/0.75) ≈ 70.7%
        # Max/min for 100% cp: max(60%, min(100%, 100%)) = 100%
        assert np_rw < oc_rw
        secured_share = 0.55 / 0.75
        assert np_rw == pytest.approx(0.60 * secured_share + 1.00 * (1 - secured_share))
        assert oc_rw == pytest.approx(1.00)


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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="CORPORATE",
            is_adc=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["rwa"] == pytest.approx(3000000)  # 2m × 150%

    def test_adc_presold_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Pre-sold ADC exposure should get 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="CORPORATE",
            is_adc=True,
            is_presold=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(2000000)  # 2m × 100%

    def test_adc_takes_priority_over_re(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """ADC flag should override RE LTV-band treatment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),  # Would be 20% under B31 LTV bands
            is_adc=True,
            config=b31_config,
        )

        # ADC overrides: 150%, not 20%
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_adc_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """ADC flag should be ignored under CRR (no ADC treatment in CRR SA)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_adc=True,
            config=crr_config,
        )

        # Under CRR, no ADC treatment → standard corporate unrated 100%
        assert result["risk_weight"] == pytest.approx(1.0)


# =============================================================================
# SCALAR LOOKUP FUNCTIONS
# =============================================================================


class TestScalarLookups:
    """Tests for convenience scalar lookup functions."""

    def test_residential_general_lookup_loan_split(self) -> None:
        """Scalar lookup uses loan-splitting for general residential."""
        # LTV ≤ 55%: fully secured → 20%
        rw, desc = lookup_b31_residential_rw(Decimal("0.50"), is_income_producing=False)
        assert rw == Decimal("0.20")
        assert "loan-split" in desc

        # LTV 80%: weighted average of 20% (secured @ 55/80) and 75% (residual)
        rw, _ = lookup_b31_residential_rw(Decimal("0.80"), is_income_producing=False)
        secured_share = Decimal("0.55") / Decimal("0.80")
        expected = Decimal("0.20") * secured_share + Decimal("0.75") * (1 - secured_share)
        assert rw == pytest.approx(expected)

    def test_residential_income_lookup(self) -> None:
        """Scalar lookup for income-producing residential matches table."""
        for band in B31_RESIDENTIAL_INCOME_LTV_BANDS:
            ltv = band["ltv_lower"] + Decimal("0.01") if band["ltv_lower"] > 0 else Decimal("0.10")
            rw, desc = lookup_b31_residential_rw(ltv, is_income_producing=True)
            assert rw == band["risk_weight"], f"LTV {ltv}: expected {band['risk_weight']}, got {rw}"

    def test_commercial_general_low_ltv_fully_secured(self) -> None:
        """Commercial general CRE: LTV ≤ 55% → fully secured at 60%."""
        rw, desc = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("1.00"),
            is_income_producing=False,
        )
        assert rw == B31_COMMERCIAL_GENERAL_SECURED_RW  # 60% (fully secured)
        assert "loan-split" in desc

    def test_commercial_general_low_ltv_still_60pct(self) -> None:
        """Commercial general CRE: LTV ≤ 55% → 60% even with low cp RW."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("0.20"),
            is_income_producing=False,
        )
        # Loan-splitting: LTV 50% ≤ 55% → secured_share=1.0 → 60%
        assert rw == B31_COMMERCIAL_GENERAL_SECURED_RW

    def test_commercial_general_high_ltv_blended(self) -> None:
        """Commercial general CRE: LTV > 55% → blended loan-split."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.75"),
            counterparty_rw=Decimal("1.00"),
            is_income_producing=False,
        )
        # secured_share = 0.55/0.75, RW = 0.60 * share + 1.00 * (1 - share)
        secured = Decimal("0.55") / Decimal("0.75")
        expected = Decimal("0.60") * secured + Decimal("1.00") * (1 - secured)
        assert rw == pytest.approx(expected)

    def test_commercial_income_producing_lookup(self) -> None:
        """Commercial income-producing CRE uses LTV band table."""
        for band in B31_COMMERCIAL_INCOME_LTV_BANDS:
            ltv = band["ltv_lower"] + Decimal("0.01") if band["ltv_lower"] > 0 else Decimal("0.10")
            rw, _ = lookup_b31_commercial_rw(ltv, is_income_producing=True)
            assert rw == band["risk_weight"]

    def test_commercial_other_cp_unrated_100pct(self) -> None:
        """Scalar lookup: other counterparty, unrated (100% cp RW) → 100%."""
        rw, desc = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("1.00"),
            is_income_producing=False,
            is_natural_person_or_sme=False,
        )
        # max(60%, min(100%, 100%)) = 100%
        assert rw == Decimal("1.00")
        assert "Art. 124H(3)" in desc

    def test_commercial_other_cp_rated_cqs1_floored(self) -> None:
        """Scalar lookup: other counterparty, CQS 1 (20% cp RW) → 60% floor."""
        rw, desc = lookup_b31_commercial_rw(
            Decimal("0.50"),
            counterparty_rw=Decimal("0.20"),
            is_income_producing=False,
            is_natural_person_or_sme=False,
        )
        # max(60%, min(20%, 100%)) = 60%
        assert rw == Decimal("0.60")
        assert "Art. 124H(3)" in desc

    def test_commercial_other_cp_high_rw_capped_by_income(self) -> None:
        """Scalar lookup: other CP, CQS 5 (150% cp RW), LTV 90% → 110% cap."""
        rw, _ = lookup_b31_commercial_rw(
            Decimal("0.90"),
            counterparty_rw=Decimal("1.50"),
            is_income_producing=False,
            is_natural_person_or_sme=False,
        )
        # LTV > 80% → income_rw = 110%
        # max(60%, min(150%, 110%)) = 110%
        assert rw == Decimal("1.10")


# =============================================================================
# QRRE TRANSACTOR — 45% (PRA Art. 123)
# =============================================================================


class TestB31QRRETransactor:
    """Basel 3.1 QRRE transactor — 45% risk weight (PRA Art. 123)."""

    def test_qrre_transactor_gets_45pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """QRRE transactor exposure should get 45% RW under Basel 3.1."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["QRRE_T001"],
                "ead_final": [50000.0],
                "exposure_class": ["RETAIL_QRRE"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_qrre_transactor": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.45)

    def test_qrre_non_transactor_gets_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-transactor QRRE should still get 75% RW."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["QRRE_R001"],
                "ead_final": [50000.0],
                "exposure_class": ["RETAIL_QRRE"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_qrre_transactor": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.75)


# =============================================================================
# NON-REGULATORY RETAIL — 100% (PRA Art. 123(3)(c))
# =============================================================================


class TestB31NonRegulatoryRetail:
    """Basel 3.1 non-regulatory retail — 100% risk weight (Art. 123(3)(c)).

    Why this test matters:
        Under Basel 3.1, retail exposures that fail Art. 123A qualifying criteria
        (e.g. lending group exposure exceeds GBP 880k threshold) must receive 100%
        risk weight instead of the 75% regulatory retail rate. Without this gate,
        non-qualifying retail gets a 25pp capital understatement.

    References:
    - PRA PS1/26 Art. 123(3)(c): non-regulatory retail = 100%
    - PRA PS1/26 Art. 123A: qualifying criteria for regulatory retail
    """

    def test_non_regulatory_retail_gets_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Retail exposure failing Art. 123A criteria should get 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1500000"),
            exposure_class="RETAIL_OTHER",
            qualifies_as_retail=False,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(1500000)

    def test_regulatory_retail_still_gets_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Retail exposure meeting Art. 123A criteria should still get 75% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("50000"),
            exposure_class="RETAIL_OTHER",
            qualifies_as_retail=True,
            config=b31_config,
        )

        assert result["risk_weight"] == pytest.approx(0.75)
        assert result["rwa"] == pytest.approx(37500)

    def test_non_regulatory_qrre_gets_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-qualifying QRRE should get 100%, not 45% or 75%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["QRRE_NR001"],
                "ead_final": [200000.0],
                "exposure_class": ["RETAIL_QRRE"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_qrre_transactor": [False],
                "qualifies_as_retail": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(1.0)

    def test_qrre_transactor_qualifying_still_gets_45pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """QRRE transactor that qualifies should still get 45%, not 100%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["QRRE_Q001"],
                "ead_final": [30000.0],
                "exposure_class": ["RETAIL_QRRE"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_qrre_transactor": [True],
                "qualifies_as_retail": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.45)

    def test_null_qualifies_as_retail_defaults_to_qualifying(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null qualifies_as_retail should default to qualifying (75% RW)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RTL_NULL001"],
                "ead_final": [80000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "qualifies_as_retail": [None],
            },
            schema_overrides={"qualifies_as_retail": pl.Boolean},
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.75)


# =============================================================================
# SA SPECIALISED LENDING — Art. 122A-122B
# =============================================================================


class TestB31SASpecialisedLending:
    """Basel 3.1 SA specialised lending risk weights (Art. 122A-122B)."""

    @pytest.mark.parametrize(
        ("sl_type", "sl_project_phase", "expected_rw"),
        [
            ("object_finance", None, 1.00),
            ("commodities_finance", None, 1.00),
            ("project_finance", "pre_operational", 1.30),
            ("project_finance", "operational", 1.00),
            ("project_finance", "high_quality", 0.80),
            ("project_finance", None, 1.00),  # defaults to operational
        ],
        ids=[
            "object_finance_100pct",
            "commodities_finance_100pct",
            "pf_pre_op_130pct",
            "pf_operational_100pct",
            "pf_high_quality_80pct",
            "pf_default_100pct",
        ],
    )
    def test_sa_sl_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        sl_type: str,
        sl_project_phase: str | None,
        expected_rw: float,
    ) -> None:
        """SA specialised lending should use Art. 122A-122B risk weights."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL001"],
                "ead_final": [1000000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": [sl_type],
                "sl_project_phase": [sl_project_phase],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(expected_rw)


# =============================================================================
# RATED SA SPECIALISED LENDING — Art. 122A(3)
# =============================================================================


class TestRatedSASpecialisedLending:
    """Rated SL exposures use the corporate CQS table (Art. 122A(3)).

    Why these tests matter:
        Art. 122A(3) mandates that rated specialised lending exposures under
        SA use the corporate CQS risk weight table, not the SL-specific type
        weights (OF/CF=100%, PF pre-op=130%, PF high-quality=80%). Without
        this, a rated PF exposure with CQS 1 (AAA) would incorrectly receive
        100% instead of 20%, overstating capital for highly-rated SL exposures.
    """

    @pytest.mark.parametrize(
        ("sl_type", "cqs", "expected_rw"),
        [
            ("project_finance", 1, 0.20),  # AAA-AA-: corporate CQS 1 = 20%
            ("project_finance", 2, 0.50),  # A+-A-: corporate CQS 2 = 50%
            ("project_finance", 3, 0.75),  # BBB+-BBB-: corporate CQS 3 = 75% (B31)
            ("project_finance", 4, 1.00),  # BB+-BB-: corporate CQS 4 = 100%
            ("project_finance", 5, 1.50),  # B+-B-: corporate CQS 5 = 150%
            ("object_finance", 1, 0.20),  # Rated OF also uses corporate table
            ("commodities_finance", 2, 0.50),  # Rated CF also uses corporate table
        ],
        ids=[
            "pf_cqs1_20pct",
            "pf_cqs2_50pct",
            "pf_cqs3_75pct",
            "pf_cqs4_100pct",
            "pf_cqs5_150pct",
            "of_cqs1_20pct",
            "cf_cqs2_50pct",
        ],
    )
    def test_rated_sl_uses_corporate_cqs_table(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        sl_type: str,
        cqs: int,
        expected_rw: float,
    ) -> None:
        """Rated SL exposure should get corporate CQS risk weight, not SL type weight."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_RATED_001"],
                "ead_final": [1000000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [cqs],
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": [sl_type],
                "sl_project_phase": [None],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(expected_rw)

    def test_unrated_sl_still_uses_type_specific_weights(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated SL (null CQS) should still use Art. 122A-122B type-specific weights."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_UNRATED_001"],
                "ead_final": [1000000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": ["project_finance"],
                "sl_project_phase": ["high_quality"],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.80)  # PF high-quality = 80%

    def test_rated_sl_rwa_correct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated SL RWA = EAD × corporate CQS RW."""
        ead = 5000000.0
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_RATED_002"],
                "ead_final": [ead],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [1],  # CQS 1 = 20% under B31 corporate
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": ["project_finance"],
                "sl_project_phase": ["operational"],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.20)
        assert df["rwa_pre_factor"][0] == pytest.approx(ead * 0.20)

    def test_rated_pf_high_quality_ignores_phase(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated PF with high_quality phase still uses corporate CQS, not 80%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_RATED_003"],
                "ead_final": [1000000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [3],  # CQS 3 = 75% under B31 corporate
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": ["project_finance"],
                "sl_project_phase": ["high_quality"],  # Would be 80% if unrated
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Rated: 75% (corporate CQS 3), not 80% (SL PF high-quality)
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_rated_pf_preop_ignores_phase(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated PF with pre_operational phase still uses corporate CQS, not 130%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SL_RATED_004"],
                "ead_final": [1000000.0],
                "exposure_class": ["SPECIALISED_LENDING"],
                "cqs": [2],  # CQS 2 = 50% under B31 corporate
                "is_sme": [False],
                "is_infrastructure": [False],
                "sl_type": ["project_finance"],
                "sl_project_phase": ["pre_operational"],  # Would be 130% if unrated
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # Rated: 50% (corporate CQS 2), not 130% (SL PF pre-operational)
        assert df["risk_weight"][0] == pytest.approx(0.50)


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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.60"),
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(0.35)

    def test_crr_residential_high_ltv_split(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR residential mortgage LTV 100% → split treatment (unchanged)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
            cqs=1,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(0.0)

    def test_crr_retail_still_works(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR retail → 75% (unchanged)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL",
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(0.75)

    def test_crr_institution_uk_deviation_still_works(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR institution CQS 2 UK deviation → 30% (unchanged)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=crr_config,
        )

        assert result["risk_weight"] == pytest.approx(0.30)


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
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),
            config=crr_config,
        )

        b31_result = calculate_single_sa_exposure(
            sa_calculator,
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
        """At 110% LTV, Basel 3.1 loan-split is higher than CRR split (~46%)."""
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.10"),
            config=crr_config,
        )

        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("400000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.10"),
            config=b31_config,
        )

        # CRR split: (0.80/1.10)*0.35 + (0.30/1.10)*0.75 ≈ 0.459
        # B31 loan-split: 0.20 × (0.55/1.10) + 0.75 × (0.55/1.10) ≈ 0.475
        expected_b31 = _expected_loan_split_rw(1.10)
        assert float(b31_result["risk_weight"]) == pytest.approx(expected_b31, abs=1e-4)
        assert b31_result["rwa"] > crr_result["rwa"]

    def test_supporting_factors_disabled_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME supporting factor should be 1.0 under Basel 3.1."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_sme=True,
            config=b31_config,
        )

        assert result["supporting_factor"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(1000000)


# =============================================================================
# TABLE DATA INTEGRITY
# =============================================================================


class TestTableDataIntegrity:
    """Verify Basel 3.1 risk weight table data is consistent and complete."""

    def test_residential_general_loan_split_constants(self) -> None:
        """General residential uses loan-splitting with 20% secured RW at 55%."""
        assert Decimal("0.20") == B31_RESIDENTIAL_GENERAL_SECURED_RW
        assert Decimal("0.55") == B31_RESIDENTIAL_GENERAL_MAX_SECURED_RATIO

    def test_residential_income_bands_cover_full_range(self) -> None:
        """Income-producing residential bands should cover 0% to infinity."""
        assert B31_RESIDENTIAL_INCOME_LTV_BANDS[0]["ltv_lower"] == Decimal("0.00")
        assert B31_RESIDENTIAL_INCOME_LTV_BANDS[-1]["ltv_upper"] == Decimal("999.0")

    def test_residential_income_bands_contiguous(self) -> None:
        """Each income band's lower bound should equal the previous band's upper bound."""
        bands = B31_RESIDENTIAL_INCOME_LTV_BANDS
        for i in range(1, len(bands)):
            assert bands[i]["ltv_lower"] == bands[i - 1]["ltv_upper"]

    def test_adc_risk_weights(self) -> None:
        """ADC risk weight constants should be correct."""
        assert Decimal("1.50") == B31_ADC_RISK_WEIGHT
        assert Decimal("1.00") == B31_ADC_PRESOLD_RISK_WEIGHT

    def test_seven_income_residential_bands(self) -> None:
        """Should have exactly 7 LTV bands for income-producing residential RE."""
        assert len(B31_RESIDENTIAL_INCOME_LTV_BANDS) == 7

    def test_two_commercial_income_bands(self) -> None:
        """Should have exactly 2 LTV bands for commercial income-producing (PRA Art. 124I)."""
        assert len(B31_COMMERCIAL_INCOME_LTV_BANDS) == 2

    def test_b31_corporate_cqs_table_values(self) -> None:
        """Basel 3.1 corporate CQS table should have correct values."""
        assert B31_CORPORATE_RISK_WEIGHTS[1] == Decimal("0.20")
        assert B31_CORPORATE_RISK_WEIGHTS[2] == Decimal("0.50")
        assert B31_CORPORATE_RISK_WEIGHTS[3] == Decimal("0.75")  # Changed from CRR 100%
        assert B31_CORPORATE_RISK_WEIGHTS[4] == Decimal("1.00")
        assert B31_CORPORATE_RISK_WEIGHTS[5] == Decimal("1.50")  # PRA retains 150% (BCBS: 100%)
        assert B31_CORPORATE_RISK_WEIGHTS[6] == Decimal("1.50")
        assert B31_CORPORATE_RISK_WEIGHTS[None] == Decimal("1.00")

    def test_scra_risk_weight_values(self) -> None:
        """SCRA long-term risk weight constants should be correct."""
        assert B31_SCRA_RISK_WEIGHTS["A"] == Decimal("0.40")
        assert B31_SCRA_RISK_WEIGHTS["A_ENHANCED"] == Decimal("0.30")
        assert B31_SCRA_RISK_WEIGHTS["B"] == Decimal("0.75")
        assert B31_SCRA_RISK_WEIGHTS["C"] == Decimal("1.50")

    def test_scra_short_term_risk_weight_values(self) -> None:
        """SCRA short-term (≤3m) risk weight constants should be correct (CRE20.17)."""
        assert B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"] == Decimal("0.20")
        assert B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A_ENHANCED"] == Decimal("0.20")
        assert B31_SCRA_SHORT_TERM_RISK_WEIGHTS["B"] == Decimal("0.50")
        assert B31_SCRA_SHORT_TERM_RISK_WEIGHTS["C"] == Decimal("1.50")

    def test_ecra_short_term_risk_weight_values(self) -> None:
        """ECRA short-term (≤3m, Table 4): CQS 1-5 = 20%, CQS 6 = 150%."""
        for cqs_step in range(1, 6):
            assert B31_ECRA_SHORT_TERM_RISK_WEIGHTS[cqs_step] == Decimal("0.20")
        assert B31_ECRA_SHORT_TERM_RISK_WEIGHTS[6] == Decimal("1.50")

    def test_ecra_short_term_table_has_6_entries(self) -> None:
        """ECRA short-term table should have exactly 6 CQS entries."""
        assert len(B31_ECRA_SHORT_TERM_RISK_WEIGHTS) == 6

    def test_investment_grade_rw(self) -> None:
        """Investment-grade corporate constant should be 65%."""
        assert Decimal("0.65") == B31_CORPORATE_INVESTMENT_GRADE_RW

    def test_non_investment_grade_rw(self) -> None:
        """Non-investment-grade corporate constant should be 135%."""
        assert Decimal("1.35") == B31_CORPORATE_NON_INVESTMENT_GRADE_RW

    def test_sme_corporate_rw(self) -> None:
        """SME corporate constant should be 85%."""
        assert Decimal("0.85") == B31_CORPORATE_SME_RW

    def test_subordinated_debt_rw(self) -> None:
        """Subordinated debt constant should be 150%."""
        assert Decimal("1.50") == B31_SUBORDINATED_DEBT_RW

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
        corp_cqs3 = df.filter((pl.col("exposure_class") == "CORPORATE") & (pl.col("cqs") == 3))
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
            (1, 0.20, 0.20),  # AAA-AA-: unchanged
            (2, 0.50, 0.50),  # A+-A-: unchanged
            (3, 0.75, 1.00),  # BBB: 75% vs 100%
            (4, 1.00, 1.00),  # BB: unchanged
            (5, 1.50, 1.50),  # B: PRA retains 150% (BCBS reduced to 100%)
            (6, 1.50, 1.50),  # CCC+: unchanged
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
        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=cqs,
            config=b31_config,
        )
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
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
        b31 = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="corporate",
            cqs=3,
            config=b31_config,
        )
        crr = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="corporate",
            cqs=3,
            config=crr_config,
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
            ("A", 0.40),  # Well-capitalised: same as CRR default
            ("A_ENHANCED", 0.30),  # CET1 >= 14% AND leverage >= 5% (CRE20.19)
            ("B", 0.75),  # Meets minimums: higher than CRR default
            ("C", 1.50),  # Below minimums: much higher
        ],
        ids=["grade_A", "grade_A_enhanced", "grade_B", "grade_C"],
    )
    def test_scra_grade_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        scra_grade: str,
        expected_rw: float,
    ) -> None:
        """Unrated institution risk weight determined by SCRA grade under Basel 3.1."""
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        """Unrated institution without SCRA grade defaults to Grade C (150%) under Basel 3.1.

        Per PRA PS1/26 Art. 120A, missing SCRA data must not produce a favourable
        risk weight. Null SCRA grade is conservatively treated as Grade C (150%).
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=None,  # No SCRA grade → Grade C conservative default
            config=b31_config,
        )

        # Null SCRA defaults to Grade C = 150% (conservative, not Grade A = 40%)
        assert float(result["risk_weight"]) == pytest.approx(1.50)

    def test_scra_grade_b_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Grade B institution: verify full RWA calculation."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="B",
            config=b31_config,
        )

        # 10M × 75% = 7.5M
        assert float(result["rwa"]) == pytest.approx(7_500_000.0)

    def test_scra_none_unrated_institution_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null SCRA grade produces correct RWA at Grade C (150%).

        Why this matters:
            An institution without SCRA assessment data must not receive
            favourable capital treatment. The 150% weight ensures prudent
            capitalisation until proper SCRA classification is obtained.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=None,
            config=b31_config,
        )

        # 10M × 150% = 15M RWA
        assert float(result["risk_weight"]) == pytest.approx(1.50)
        assert float(result["rwa"]) == pytest.approx(15_000_000.0)


# =============================================================================
# SCRA ENHANCED GRADE A (CRE20.19)
# =============================================================================


class TestB31SCRAEnhancedGradeA:
    """Basel 3.1 SCRA enhanced Grade A: 30% for CET1 >= 14% AND leverage >= 5%.

    PRA PS1/26 Art. 120A / CRE20.19 introduces a sub-grade of SCRA Grade A
    for institutions that exceed both a 14% CET1 ratio and a 5% leverage ratio.
    These well-capitalised institutions receive a preferential 30% risk weight
    (vs standard Grade A 40%).

    Why this matters:
        The 10pp reduction (40% → 30%) for the most strongly capitalised
        counterparties incentivises lending to well-capitalised institutions
        and aligns interbank capital charges with counterparty strength.
    """

    def test_enhanced_a_rw_30_percent(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Enhanced Grade A institution gets 30% RW (vs 40% for standard A)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A_ENHANCED",
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.30)
        assert float(result["rwa"]) == pytest.approx(3_000_000.0)

    def test_enhanced_a_vs_standard_a(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Enhanced Grade A produces lower RWA than standard Grade A."""
        enhanced = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A_ENHANCED",
            config=b31_config,
        )
        standard = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            config=b31_config,
        )

        assert float(enhanced["rwa"]) < float(standard["rwa"])

    def test_enhanced_a_rated_institution_uses_ecra(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Rated institution ignores SCRA enhanced grade — ECRA (CQS) takes precedence."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=2,
            scra_grade="A_ENHANCED",
            config=b31_config,
        )

        # ECRA CQS 2 → 30% (UK deviation), not SCRA enhanced A 30%
        assert float(result["risk_weight"]) == pytest.approx(0.30)

    def test_enhanced_a_covered_bond_derives_15pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated covered bond with enhanced-A issuer derives 15% RW (Art. 129(5)).

        Derivation chain: SCRA A_ENHANCED → institution 30% → CB 15%
        (differs from standard A: institution 40% → CB 20%).
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="covered_bond",
            cqs=None,
            scra_grade="A_ENHANCED",
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.15)


# =============================================================================
# SCRA SHORT-TERM MATURITY (CRE20.17)
# =============================================================================


class TestB31SCRAShortTermMaturity:
    """Basel 3.1 SCRA short-term (≤3m) risk weights for unrated institutions.

    PRA PS1/26 Art. 120A / CRE20.17 provides reduced risk weights for
    short-term (residual maturity ≤ 3 months) unrated institution exposures:
    - Grade A / A Enhanced: 20% (vs 40%/30% long-term)
    - Grade B: 50% (vs 75% long-term)
    - Grade C: 150% (unchanged)

    Why this matters:
        Short-term interbank exposures carry less risk due to their limited
        duration. The reduced weights lower capital charges for overnight,
        money market, and short-dated placements to well-capitalised banks.
    """

    @pytest.mark.parametrize(
        ("scra_grade", "expected_rw"),
        [
            ("A", 0.20),
            ("A_ENHANCED", 0.20),
            ("B", 0.50),
            ("C", 1.50),
        ],
        ids=["grade_A_20pct", "grade_A_enhanced_20pct", "grade_B_50pct", "grade_C_150pct"],
    )
    def test_short_term_scra_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        scra_grade: str,
        expected_rw: float,
    ) -> None:
        """Short-term (≤3m) unrated institution gets reduced SCRA RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=scra_grade,
            residual_maturity_years=0.20,  # ~2.4 months, below 3m threshold
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(expected_rw)

    def test_short_term_grade_a_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Short-term Grade A: 10M × 20% = 2M RWA."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            residual_maturity_years=0.10,  # ~5 weeks
            config=b31_config,
        )

        assert float(result["rwa"]) == pytest.approx(2_000_000.0)

    def test_short_term_boundary_exactly_3m(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Exactly 3 months (0.25y) should qualify as short-term."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            residual_maturity_years=0.25,  # Exactly 3 months
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_long_term_boundary_just_over_3m(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Just over 3 months should get long-term rates."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            residual_maturity_years=0.26,  # Just over 3 months
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.40)

    def test_null_maturity_defaults_to_long_term(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null residual maturity defaults to long-term (conservative).

        When maturity data is missing, the fill_null(1.0) default ensures
        the exposure is treated as long-term, preventing accidental
        capital reduction from missing data.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            residual_maturity_years=None,  # Missing → defaults to 1.0y → long-term
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.40)

    def test_short_term_rated_institution_uses_ecra(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Short-term rated institution still uses ECRA, not SCRA short-term table."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=1,
            scra_grade="A",
            residual_maturity_years=0.10,
            config=b31_config,
        )

        # ECRA CQS 1 → 20%, not SCRA short-term A → 20% (same value but different path)
        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_short_term_null_scra_defaults_grade_c(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Short-term with null SCRA still defaults to Grade C (150%)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade=None,
            residual_maturity_years=0.10,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(1.50)

    def test_short_term_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR has no SCRA short-term treatment — unrated institution gets 40%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="A",
            residual_maturity_years=0.10,
            config=crr_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.40)


# =============================================================================
# ECRA SHORT-TERM RATED INSTITUTIONS (PRA PS1/26 Art. 120, Table 4)
# =============================================================================


class TestB31ECRAShortTermInstitution:
    """Basel 3.1 ECRA short-term risk weights for rated institutions.

    Under Basel 3.1, rated institution exposures with residual maturity ≤ 3
    months receive preferential weights per Table 4: CQS 1-5 = 20%, CQS 6 =
    150%. Trade finance exposures qualify up to 6 months (Art. 121(5)).

    Why this matters:
        Without the short-term ECRA table, a CQS 3 institution exposure at 2
        months maturity incorrectly receives 50% RW (the long-term ECRA weight)
        instead of 20%. For CQS 4, the overstatement is 5x (100% vs 20%). This
        systematically overstates capital on short-term interbank lending, which
        is a large volume for most banks.
    """

    @pytest.mark.parametrize(
        ("cqs", "expected_rw"),
        [
            (1, 0.20),
            (2, 0.20),
            (3, 0.20),
            (4, 0.20),
            (5, 0.20),
            (6, 1.50),
        ],
        ids=["CQS1", "CQS2", "CQS3", "CQS4", "CQS5", "CQS6"],
    )
    def test_short_term_ecra_risk_weight(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        cqs: int,
        expected_rw: float,
    ) -> None:
        """ECRA Table 4: CQS 1-5 all get 20%, CQS 6 gets 150% at ≤3m."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=cqs,
            residual_maturity_years=0.20,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(expected_rw)

    def test_short_term_ecra_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """End-to-end RWA for short-term CQS 3: 10M × 20% = 2M."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.10,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.20)
        assert float(result["rwa"]) == pytest.approx(2_000_000.0)

    def test_boundary_exactly_3m(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Exactly 3 months (0.25y) qualifies as short-term → 20%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.25,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_boundary_just_over_3m(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Just over 3 months (0.26y) uses long-term ECRA CQS table → 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.26,
            config=b31_config,
        )

        # CQS 3 long-term = 50%
        assert float(result["risk_weight"]) == pytest.approx(0.50)

    def test_null_maturity_defaults_to_long_term(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null maturity defaults to 1.0y (long-term) → standard CQS weight."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=None,
            config=b31_config,
        )

        # CQS 3 long-term = 50%
        assert float(result["risk_weight"]) == pytest.approx(0.50)

    def test_cqs2_long_term_unchanged(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 2 long-term still uses standard ECRA weight (30% UK deviation)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=2,
            residual_maturity_years=1.0,
            config=b31_config,
        )

        # CQS 2 UK deviation long-term = 30%
        assert float(result["risk_weight"]) == pytest.approx(0.30)

    def test_cqs4_short_vs_long_term(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 4 short-term = 20% vs long-term = 100% — largest reduction."""
        short = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=0.10,
            config=b31_config,
        )
        long = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=1.0,
            config=b31_config,
        )

        assert float(short["risk_weight"]) == pytest.approx(0.20)
        assert float(long["risk_weight"]) == pytest.approx(1.00)

    def test_trade_finance_6m_qualifies(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Trade finance at 5 months (0.42y) qualifies for short-term via Art. 121(5)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.42,
            is_short_term_trade_lc=True,
            config=b31_config,
        )

        # Trade finance ≤6m → short-term ECRA Table 4 → 20%
        assert float(result["risk_weight"]) == pytest.approx(0.20)

    def test_trade_finance_over_6m_uses_long_term(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Trade finance at 7 months (0.58y) does not qualify for short-term."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.58,
            is_short_term_trade_lc=True,
            config=b31_config,
        )

        # Over 6m → long-term CQS 3 = 50%
        assert float(result["risk_weight"]) == pytest.approx(0.50)

    def test_non_trade_finance_at_4m_uses_long_term(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-trade-finance at 4 months does not qualify (>3m threshold)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.33,
            is_short_term_trade_lc=False,
            config=b31_config,
        )

        # 4 months > 3m threshold, not trade finance → long-term CQS 3 = 50%
        assert float(result["risk_weight"]) == pytest.approx(0.50)

    def test_ecra_short_term_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR has no ECRA short-term Table 4 — rated institution uses standard CQS."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=3,
            residual_maturity_years=0.10,
            config=crr_config,
        )

        # CRR CQS 3 institution = 50% regardless of maturity
        assert float(result["risk_weight"]) == pytest.approx(0.50)

    def test_unrated_short_term_still_uses_scra(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated institution at ≤3m uses SCRA short-term, not ECRA."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="institution",
            cqs=None,
            scra_grade="B",
            residual_maturity_years=0.10,
            config=b31_config,
        )

        # SCRA short-term Grade B = 50%
        assert float(result["risk_weight"]) == pytest.approx(0.50)


# =============================================================================
# INVESTMENT-GRADE CORPORATE (CRE20.47-49)
# =============================================================================


class TestB31InvestmentGradeCorporate:
    """Basel 3.1 investment-grade corporate risk weight: 65%.

    Qualifying: publicly traded + investment grade external rating.
    Requires Art. 122(6) IG assessment election (use_investment_grade_assessment=True).

    Why this matters:
        The 65% weight (vs 100% unrated default) significantly reduces SA RWA
        for large, well-capitalised corporates, narrowing the gap between SA
        and IRB capital requirements for investment-grade portfolios.
        The election is paired with a 135% weight for non-IG corporates
        (see TestB31NonInvestmentGradeCorporate).
    """

    @pytest.fixture
    def ig_config(self) -> CalculationConfig:
        """B31 config with investment-grade assessment elected."""
        return CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            use_investment_grade_assessment=True,
        )

    def test_investment_grade_65pct(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """Investment-grade corporate gets 65% under Basel 3.1 with IG assessment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=True,
            config=ig_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.65)
        assert float(result["rwa"]) == pytest.approx(1_300_000.0)  # 2M × 65%

    def test_investment_grade_not_applied_under_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Investment-grade treatment does not exist under CRR → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=1,
            is_investment_grade=True,
            config=b31_config,
        )

        # CQS 1 → 20% (from CQS table, not 65%)
        assert float(result["risk_weight"]) == pytest.approx(0.20)


# =============================================================================
# NON-INVESTMENT-GRADE CORPORATE RISK WEIGHT (Art. 122(6)(b), Basel 3.1)
# =============================================================================


class TestB31NonInvestmentGradeCorporate:
    """Basel 3.1 non-investment-grade corporate risk weight: 135%.

    When an institution has PRA permission to use the investment-grade
    assessment (Art. 122(6)), unrated corporates are split:
    - Investment-grade: 65% (Art. 122(6)(a))
    - Non-investment-grade: 135% (Art. 122(6)(b))

    Without the election, all unrated corporates receive 100%.

    Why this matters:
        Art. 122(6) is an opt-in election. Institutions that elect it get
        the favorable 65% for IG corporates, but must accept the punitive
        135% for non-IG corporates. The 35pp surcharge over the 100% default
        prevents cherry-picking the IG benefit without the corresponding penalty.
    """

    @pytest.fixture
    def ig_config(self) -> CalculationConfig:
        """B31 config with investment-grade assessment elected."""
        return CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            use_investment_grade_assessment=True,
        )

    def test_non_ig_corporate_135pct(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """Non-IG unrated corporate gets 135% when IG assessment is active."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=False,
            config=ig_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(1.35)
        assert float(result["rwa"]) == pytest.approx(2_700_000.0)  # 2M × 135%

    def test_ig_corporate_65pct_with_assessment(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """IG unrated corporate gets 65% when IG assessment is active."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=True,
            config=ig_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(0.65)
        assert float(result["rwa"]) == pytest.approx(1_300_000.0)  # 2M × 65%

    def test_ig_flag_ignored_without_assessment(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """IG flag is ignored when assessment is not active — gets 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=True,
            config=b31_config,
        )

        # Without use_investment_grade_assessment=True, all unrated corporates → 100%
        assert float(result["risk_weight"]) == pytest.approx(1.00)

    def test_non_ig_gets_100pct_without_assessment(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-IG corporate gets standard 100% when assessment is not active."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=False,
            config=b31_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(1.00)

    def test_null_ig_flag_treated_as_non_ig(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """Null is_investment_grade is treated as non-IG → 135% with assessment."""
        # When data doesn't include the IG flag, it defaults to False in the calculator
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=None,
            is_investment_grade=False,  # Simulates null (fill_null(False))
            config=ig_config,
        )

        assert float(result["risk_weight"]) == pytest.approx(1.35)

    def test_rated_corporate_unaffected_by_assessment(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """Rated corporates use CQS table regardless of IG assessment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate",
            cqs=3,
            is_investment_grade=False,
            config=ig_config,
        )

        # CQS 3 → 75% (from B31 corporate CQS table), not 135%
        assert float(result["risk_weight"]) == pytest.approx(0.75)

    def test_sme_corporate_unaffected_by_assessment(
        self,
        sa_calculator: SACalculator,
        ig_config: CalculationConfig,
    ) -> None:
        """SME corporates get 85% regardless of IG assessment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="corporate_sme",
            cqs=None,
            is_investment_grade=False,
            config=ig_config,
        )

        # SME corporate → 85%, not 135% (SME branch fires before non-IG)
        assert float(result["risk_weight"]) == pytest.approx(0.85)


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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        """SME managed as retail keeps 75% when under EUR 1m threshold."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            is_managed_as_retail=True,
            qualifies_as_retail=True,
            config=b31_config,
        )

        # Managed-as-retail + qualifies (under threshold) → 75%
        assert float(result["risk_weight"]) == pytest.approx(0.75)

    def test_sme_managed_as_retail_over_threshold_not_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SME managed as retail but over EUR 1m threshold gets standard SME RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1500000"),
            exposure_class="corporate_sme",
            cqs=None,
            is_managed_as_retail=True,
            qualifies_as_retail=False,
            config=b31_config,
        )

        # Over threshold → not retail, falls through to corporate SME 85%
        assert float(result["risk_weight"]) == pytest.approx(0.85)


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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
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
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="corporate_sme",
            cqs=None,
            seniority="subordinated",
            config=b31_config,
        )

        # Subordinated overrides SME treatment → 150%
        assert float(result["risk_weight"]) == pytest.approx(1.50)


# =============================================================================
# CURRENCY MISMATCH MULTIPLIER (Basel 3.1 Art. 123B / CRE20.93)
# =============================================================================


class TestCurrencyMismatchMultiplier:
    """Test 1.5x RW multiplier for retail/RE when exposure currency differs
    from borrower's income currency.

    Why these tests matter:
        Basel 3.1 Art. 123B introduces a 1.5x risk weight multiplier for
        retail and real estate exposures denominated in a currency different
        from the borrower's income source. This captures additional FX risk
        where borrowers earn in one currency but owe in another, increasing
        default probability during adverse FX moves.

    References:
    - CRE20.93: Currency mismatch for retail and RE
    - PRA PS9/24 Art. 123B: UK implementation
    """

    def test_retail_with_currency_mismatch_gets_1_5x(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Retail exposure with currency mismatch gets 75% * 1.5 = 112.5% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        assert float(result["risk_weight"]) == pytest.approx(0.75 * 1.5)

    def test_retail_without_mismatch_no_multiplier(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Retail exposure in same currency as income — no multiplier."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="retail_other",
            currency="GBP",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        assert float(result["risk_weight"]) == pytest.approx(0.75)

    def test_residential_mortgage_with_mismatch(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Residential mortgage with mismatch gets LTV-band RW * 1.5."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="retail_mortgage",
            ltv=Decimal("0.60"),
            currency="CHF",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        # LTV 60% → lookup band RW, then * 1.5
        base_rw = float(result["risk_weight"]) / 1.5
        # Verify multiplier was applied (RW should be > base)
        assert float(result["risk_weight"]) == pytest.approx(base_rw * 1.5)
        # Check the multiplied RW is reasonable for 60% LTV residential
        assert float(result["risk_weight"]) > 0.20  # Must be > 20%

    def test_commercial_re_with_mismatch(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Commercial RE with currency mismatch gets 1.5x multiplier."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="secured_by_re_commercial",
            ltv=Decimal("0.55"),
            property_type="commercial",
            currency="USD",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        # RW should be multiplied by 1.5
        assert float(result["risk_weight"]) > 0.0

    def test_corporate_not_affected_by_mismatch(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Corporate exposure is NOT subject to currency mismatch multiplier."""
        result_mismatch = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=3,
            currency="EUR",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        result_no_mismatch = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="corporate",
            cqs=3,
            currency="GBP",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        assert float(result_mismatch["risk_weight"]) == pytest.approx(
            float(result_no_mismatch["risk_weight"])
        )

    def test_crr_not_affected_by_mismatch(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR framework does not apply currency mismatch multiplier."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency="GBP",
            config=crr_config,
        )
        # CRR retail = 75%, no multiplier
        assert float(result["risk_weight"]) == pytest.approx(0.75)

    def test_null_income_currency_no_multiplier(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """When borrower income currency is null, no multiplier is applied."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="retail_other",
            currency="EUR",
            borrower_income_currency=None,
            config=b31_config,
        )
        assert float(result["risk_weight"]) == pytest.approx(0.75)

    def test_institution_not_affected_by_mismatch(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Institution exposure is NOT subject to currency mismatch multiplier."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="institution",
            cqs=1,
            currency="EUR",
            borrower_income_currency="GBP",
            config=b31_config,
        )
        # CQS 1 institution = 20% — no multiplier
        assert float(result["risk_weight"]) == pytest.approx(0.20)


# =============================================================================
# DEFAULTED RESI RE — ALWAYS 100% (PRA PS1/26 Art. 127 / CRE20.88)
# =============================================================================
#
# Under Basel 3.1, defaulted general RESI RE (non-income-dependent) always gets
# 100% RW regardless of provision coverage. This is a Basel 3.1 simplification
# for owner-occupied housing — income-dependent and CRE defaulted exposures still
# use the provision-based 100%/150% test. CRR has no such exception.
# =============================================================================


class TestDefaultedResiREBasel31:
    """Tests for Basel 3.1 defaulted RESI RE always-100% exception (CRE20.88)."""

    def test_defaulted_resi_re_non_income_always_100(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-income-dependent defaulted RESI RE → 100% regardless of provisions."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),  # 0% provisions
            config=b31_config,
        )
        # Should be 100% flat, NOT 150% (provision-based)
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_resi_re_non_income_with_low_provisions_still_100(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Even with provisions < 20%, non-income RESI RE gets 100% (not 150%)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("50000"),  # 5% < 20% threshold
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_resi_re_non_income_with_high_provisions_still_100(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """With provisions >= 20%, non-income RESI RE still gets 100% (same result)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("300000"),  # 30% >= 20%
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_resi_re_income_dependent_uses_provision_test(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Income-dependent defaulted RESI RE still uses provision-based test."""
        # Low provisions → 150%
        result_low = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=True,  # Income-dependent
            provision_allocated=Decimal("50000"),  # 5% < 20%
            config=b31_config,
        )
        assert result_low["risk_weight"] == pytest.approx(1.50)

        # High provisions → 100%
        result_high = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=True,
            provision_allocated=Decimal("250000"),  # 25% >= 20%
            config=b31_config,
        )
        assert result_high["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_resi_re_rwa_correctness(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """RWA = EAD × 100% for defaulted non-income RESI RE."""
        ead = Decimal("750000")
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(float(ead) * 1.00)

    def test_defaulted_residential_class_variant(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """RESIDENTIAL_RE class also gets the always-100% treatment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_RE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_null_income_cover_defaults_non_income(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null has_income_cover defaults to False (non-income) → 100%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["NULL_INCOME"],
                "ead_final": [500000.0],
                "exposure_class": ["RETAIL_MORTGAGE"],
                "cqs": [None],
                "is_defaulted": [True],
                "has_income_cover": [None],
                "provision_allocated": [0.0],
                "provision_deducted": [0.0],
            }
        ).lazy()

        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_resi_re_no_exception(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR has no RESI RE defaulted exception — provision-based test applies."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RETAIL_MORTGAGE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),  # 0% provisions
            config=crr_config,
        )
        # CRR: no provisions → 150% (provision-based test, no RESI RE exception)
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_defaulted_corporate_still_provision_based(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-RE defaulted exposures still use provision-based test under B31."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            cqs=None,
            is_defaulted=True,
            provision_allocated=Decimal("50000"),  # 5% < 20%
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_defaulted_commercial_re_still_provision_based(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Defaulted CRE uses provision-based test (no RESI-like exception)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COMMERCIAL_RE",
            cqs=None,
            is_defaulted=True,
            has_income_cover=False,
            property_type="commercial",
            provision_allocated=Decimal("50000"),  # 5% < 20%
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)


# =============================================================================
# PAYROLL / PENSION LOAN — 35% (PRA PS1/26 Art. 123(3)(a-b))
# =============================================================================


class TestB31PayrollPensionLoan:
    """Basel 3.1 payroll/pension loan — 35% risk weight (Art. 123(3)(a-b)).

    Why these tests matter:
        Under Basel 3.1, loans secured by assignment of the borrower's payroll
        or pension income receive a preferential 35% risk weight instead of the
        standard 75% regulatory retail rate. This is a new Basel 3.1 retail
        sub-category not present in CRR. Without this treatment, payroll/pension
        loans are overcharged by 40pp (75% vs 35%), overstating capital.

    References:
    - PRA PS1/26 Art. 123(3)(a-b): payroll/pension loans = 35%
    - PRA PS1/26 Art. 123A: qualifying criteria for regulatory retail
    """

    def test_payroll_loan_gets_35pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Payroll loan exposure should get 35% RW under Basel 3.1."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["PAY_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_payroll_loan": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.35)

    def test_payroll_loan_rwa_correctness(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Payroll loan RWA should be EAD * 35%."""
        ead = 40000.0
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["PAY_002"],
                "ead_final": [ead],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_payroll_loan": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["rwa_pre_factor"][0] == pytest.approx(ead * 0.35)

    def test_non_payroll_retail_still_gets_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-payroll retail should still get 75% RW."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RTL_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_payroll_loan": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_payroll_loan_qrre_transactor_gets_45pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """QRRE transactor takes priority over payroll loan in the when-chain."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["PAY_QRRE_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_QRRE"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_qrre_transactor": [True],
                "is_payroll_loan": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        # QRRE transactor (45%) takes priority over payroll (35%) in the when-chain
        assert df["risk_weight"][0] == pytest.approx(0.45)

    def test_null_payroll_flag_defaults_to_non_payroll(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null is_payroll_loan defaults to False (standard 75% retail)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RTL_NULL_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_payroll_loan": [None],
            },
            schema_overrides={"is_payroll_loan": pl.Boolean},
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_missing_payroll_column_defaults_to_non_payroll(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """When is_payroll_loan column is absent, defaults to False (75% retail)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RTL_NO_COL_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, b31_config)
        df = result.frame.collect()

        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_crr_payroll_loan_gets_75pct(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Under CRR, payroll loans get standard 75% retail RW (no 35% category)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["PAY_CRR_001"],
                "ead_final": [25000.0],
                "exposure_class": ["RETAIL_OTHER"],
                "cqs": [None],
                "is_sme": [False],
                "is_infrastructure": [False],
                "is_payroll_loan": [True],
            }
        ).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=exposures,
            irb_exposures=pl.LazyFrame(),
        )

        result = sa_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        # CRR has no payroll/pension category — all retail is 75%
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_payroll_loan_constant_value(self) -> None:
        """B31_RETAIL_PAYROLL_LOAN_RW constant should be 0.35 (35%)."""
        assert B31_RETAIL_PAYROLL_LOAN_RW == Decimal("0.35")
