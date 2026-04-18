"""
Unit tests for PSE (Public Sector Entity) risk weights under CRR and Basel 3.1.

Why these tests matter:
    PSE exposures are common in UK banking portfolios (government agencies,
    NHS trusts, universities, transport authorities). Without correct PSE risk
    weight tables, all PSE exposures silently default to 100% via the CQS join
    fallback, producing capital overstatement for most UK PSEs (should be 20%)
    and capital understatement for poorly-rated PSEs (CQS 6 should be 150%).

PSE treatment (Art. 116) is identical under CRR and PRA PS1/26 Basel 3.1:
    - Rated PSEs (own ECAI): Table 2A (Art. 116(2))
    - Unrated PSEs: Sovereign-derived Table 2 (Art. 116(1))
    - Short-term (<=3m): 20% flat (Art. 116(3))

References:
    - CRR Art. 116 / PRA PS1/26 Art. 116: PSE risk weights
    - Table 2: Sovereign-derived risk weights
    - Table 2A: Own-rating risk weights
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_risk_weights import get_b31_combined_cqs_risk_weights
from rwa_calc.data.tables.crr_risk_weights import (
    PSE_RISK_WEIGHTS_OWN_RATING,
    PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    PSE_SHORT_TERM_RW,
    PSE_UNRATED_DEFAULT_RW,
    get_combined_cqs_risk_weights,
    lookup_risk_weight,
)
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa import SACalculator

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# DATA TABLE TESTS
# =============================================================================


class TestPSERiskWeightTables:
    """Tests for PSE risk weight dict tables and DataFrame generators."""

    def test_sovereign_derived_table_values(self):
        """Table 2 (Art. 116(1)): sovereign-derived PSE risk weights."""
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS1] == Decimal("0.20")
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS2] == Decimal("0.50")
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS3] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS4] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS5] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS6] == Decimal("1.50")

    def test_own_rating_table_values(self):
        """Table 2A (Art. 116(2)): own-rating PSE risk weights.

        Key difference from Table 2: CQS 3 = 50% (not 100%).
        """
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS1] == Decimal("0.20")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS2] == Decimal("0.50")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS3] == Decimal("0.50")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS4] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS5] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS6] == Decimal("1.50")

    def test_cqs3_differs_between_tables(self):
        """CQS 3 is the key difference: 100% sovereign-derived vs 50% own-rating."""
        assert PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS3] == Decimal("1.00")
        assert PSE_RISK_WEIGHTS_OWN_RATING[CQS.CQS3] == Decimal("0.50")

    def test_short_term_rw(self):
        """Art. 116(3): short-term PSE exposures get 20%."""
        assert Decimal("0.20") == PSE_SHORT_TERM_RW

    def test_unrated_default(self):
        """Unrated PSEs default to 100% when sovereign CQS is unknown."""
        assert Decimal("1.00") == PSE_UNRATED_DEFAULT_RW

    def test_pse_in_combined_crr_table(self):
        """PSE rows are included in the CRR combined CQS table."""
        df = get_combined_cqs_risk_weights()
        pse_rows = df.filter(df["exposure_class"] == "PSE")
        assert pse_rows.height == 6  # CQS 1-6 (no unrated row)

    def test_pse_in_combined_b31_table(self):
        """PSE rows are included in the B31 combined CQS table."""
        df = get_b31_combined_cqs_risk_weights()
        pse_rows = df.filter(df["exposure_class"] == "PSE")
        assert pse_rows.height == 6

    def test_lookup_risk_weight_rated_pse(self):
        """Scalar lookup for rated PSE returns Table 2A weights."""
        assert lookup_risk_weight("PSE", 1) == Decimal("0.20")
        assert lookup_risk_weight("PSE", 2) == Decimal("0.50")
        assert lookup_risk_weight("PSE", 3) == Decimal("0.50")
        assert lookup_risk_weight("PSE", 4) == Decimal("1.00")
        assert lookup_risk_weight("PSE", 5) == Decimal("1.00")
        assert lookup_risk_weight("PSE", 6) == Decimal("1.50")

    def test_lookup_risk_weight_unrated_pse(self):
        """Scalar lookup for unrated PSE returns conservative 100%."""
        assert lookup_risk_weight("PSE", None) == Decimal("1.00")
        assert lookup_risk_weight("PSE", 0) == Decimal("1.00")


# =============================================================================
# SA CALCULATOR — CRR PSE RISK WEIGHTS
# =============================================================================


class TestCRRPSERiskWeights:
    """CRR path: PSE risk weights via SA calculator."""

    def test_rated_pse_cqs1_20pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 1 → 20% (Table 2A)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=1,
            country_code="GB",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_pse_cqs2_50pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 2 → 50% (Table 2A)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=2,
            country_code="GB",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_pse_cqs3_50pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 3 → 50% (Table 2A — not 100% like Table 2)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=3,
            country_code="GB",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_pse_cqs4_100pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 4 → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=4,
            country_code="DE",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rated_pse_cqs5_100pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 5 → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=5,
            country_code="DE",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rated_pse_cqs6_150pct(self, sa_calculator, crr_config):
        """CRR: Rated PSE with CQS 6 → 150% — capital understatement risk if missing."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=6,
            country_code="DE",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_unrated_uk_pse_20pct(self, sa_calculator, crr_config):
        """CRR: Unrated UK PSE → 20% (sovereign-derived, UK sovereign CQS=1)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code="GB",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_non_uk_pse_100pct(self, sa_calculator, crr_config):
        """CRR: Unrated non-UK PSE → 100% conservative default."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code="DE",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_short_term_pse_20pct(self, sa_calculator, crr_config):
        """CRR: Short-term PSE (≤3m) → 20% regardless of rating (Art. 116(3))."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=4,
            country_code="DE",
            residual_maturity_years=0.2,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_short_term_unrated_pse_20pct(self, sa_calculator, crr_config):
        """CRR: Unrated short-term PSE → 20% (short-term overrides sovereign-derived)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code="DE",
            residual_maturity_years=0.1,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rwa_calculation_pse(self, sa_calculator, crr_config):
        """CRR: PSE RWA = EAD × RW."""
        ead = Decimal("5000000")
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="pse",
            cqs=1,
            country_code="GB",
            config=crr_config,
        )
        expected_rwa = float(ead) * 0.20
        assert result["rwa"] == pytest.approx(expected_rwa)


# =============================================================================
# SA CALCULATOR — BASEL 3.1 PSE RISK WEIGHTS
# =============================================================================


class TestB31PSERiskWeights:
    """Basel 3.1 path: PSE risk weights are identical to CRR per PRA PS1/26."""

    def test_rated_pse_cqs1_20pct(self, sa_calculator, b31_config):
        """B31: Rated PSE with CQS 1 → 20% (same as CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=1,
            country_code="GB",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_pse_cqs3_50pct(self, sa_calculator, b31_config):
        """B31: Rated PSE with CQS 3 → 50% (Table 2A)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=3,
            country_code="GB",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_pse_cqs6_150pct(self, sa_calculator, b31_config):
        """B31: Rated PSE with CQS 6 → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=6,
            country_code="DE",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_unrated_uk_pse_20pct(self, sa_calculator, b31_config):
        """B31: Unrated UK PSE → 20% sovereign-derived."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code="GB",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_non_uk_pse_100pct(self, sa_calculator, b31_config):
        """B31: Unrated non-UK PSE → 100% conservative default."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code="DE",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_short_term_pse_overrides_cqs(self, sa_calculator, b31_config):
        """B31: Short-term PSE ≤3m → 20% even with CQS 5 (Art. 116(3))."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=5,
            country_code="DE",
            residual_maturity_years=0.25,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_above_3m_uses_cqs_table(self, sa_calculator, b31_config):
        """B31: PSE with maturity > 3m uses CQS table, not short-term treatment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=5,
            country_code="DE",
            residual_maturity_years=0.5,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_null_maturity_uses_cqs_table(self, sa_calculator, b31_config):
        """B31: PSE with null maturity uses CQS table (short-term not triggered)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=2,
            country_code="GB",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_null_country_unrated_pse_100pct(self, sa_calculator, b31_config):
        """B31: Unrated PSE with null country → 100% conservative default."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=None,
            country_code=None,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# =============================================================================
# SA CALCULATOR — PSE SHORT-TERM KEYS ON ORIGINAL MATURITY (Art. 116(3))
# =============================================================================
# CRR Art. 116(3) and PRA PS1/26 Art. 116(3) both specify "original maturity
# of three months or less". A seasoned long-dated bond with short residual
# must NOT receive the 20% short-term concession.


class TestPSEShortTermOriginalMaturityCRR:
    """CRR Art. 116(3): short-term test keys on ORIGINAL maturity, not residual."""

    def test_seasoned_bond_short_residual_not_short_term(self, sa_calculator, crr_config):
        """5y bond with 0.1y residual: original > 3m → NOT 20% short-term."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=4,
            country_code="DE",
            residual_maturity_years=0.1,
            original_maturity_years=5.0,
            config=crr_config,
        )
        # CQS 4 → sovereign-derived 100% (Table 2, non-UK)
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_fresh_bond_original_under_3m_gets_short_term(self, sa_calculator, crr_config):
        """3-month bond (original = residual = 0.2y) gets 20%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=4,
            country_code="DE",
            residual_maturity_years=0.2,
            original_maturity_years=0.2,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)


class TestPSEShortTermOriginalMaturityB31:
    """PRA PS1/26 Art. 116(3): short-term test keys on ORIGINAL maturity."""

    def test_seasoned_bond_short_residual_not_short_term(self, sa_calculator, b31_config):
        """CQS 5 seasoned bond with 0.1y residual: NOT 20% (original > 3m)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=5,
            country_code="DE",
            residual_maturity_years=0.1,
            original_maturity_years=10.0,
            config=b31_config,
        )
        # Non-UK PSE CQS 5 falls through to CQS-based weight (currently 100%);
        # importantly must NOT be 20%.
        assert result["risk_weight"] != pytest.approx(0.20)

    def test_fresh_bond_original_under_3m_gets_short_term(self, sa_calculator, b31_config):
        """3-month bond with CQS 5 gets 20% via Art. 116(3) short-term override."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="pse",
            cqs=5,
            country_code="DE",
            residual_maturity_years=0.2,
            original_maturity_years=0.2,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)
