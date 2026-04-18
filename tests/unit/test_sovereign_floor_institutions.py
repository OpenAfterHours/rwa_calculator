"""
Unit tests for Art. 121(6) / CRE20.22 sovereign RW floor for FX institution exposures.

Tests verify that unrated institution exposures denominated in a foreign
currency (not the institution's domestic currency) receive a risk weight
no lower than the sovereign risk weight of the institution's jurisdiction.

References:
- CRR Art. 121(6): Sovereign floor for unrated institution FX exposures
- PRA PS1/26 Art. 121(6): Same requirement under Basel 3.1
- CRE20.22: Basel 3.1 SCRA sovereign floor for unrated banks
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
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


# =========================================================================
# Basel 3.1 — SCRA sovereign floor
# =========================================================================


class TestB31SovereignFloorSCRA:
    """Basel 3.1 sovereign floor for unrated institutions via SCRA."""

    def test_sovereign_floor_binds_grade_a_cqs4(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """SCRA Grade A = 40% but sovereign CQS 4 = 100% → floor binds to 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_sovereign_floor_binds_grade_b_cqs4(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """SCRA Grade B = 75% but sovereign CQS 4 = 100% → floor binds to 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="B",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_sovereign_floor_does_not_bind_grade_c(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """SCRA Grade C = 150% already exceeds sovereign CQS 4 = 100% → no change."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="C",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        assert result["risk_weight"] == pytest.approx(1.5)

    def test_sovereign_floor_cqs6_binds_grade_a(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Sovereign CQS 6 = 150% → SCRA A (40%) floored to 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=6,
            local_currency="ARS",
            currency="USD",
            country_code="AR",
        )
        assert result["risk_weight"] == pytest.approx(1.5)

    def test_sovereign_floor_cqs1_never_binds(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Sovereign CQS 1 = 0% → never binds (floor is 0%)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=1,
            local_currency="GBP",
            currency="USD",
            country_code="GB",
        )
        # SCRA A = 40% stands (sovereign floor 0% does not bind)
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_sovereign_floor_cqs3_binds_enhanced_a(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """SCRA A_ENHANCED = 30% but sovereign CQS 3 = 50% → floor binds."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A_ENHANCED",
            sovereign_cqs=3,
            local_currency="BRL",
            currency="USD",
            country_code="BR",
        )
        assert result["risk_weight"] == pytest.approx(0.50)


# =========================================================================
# Domestic currency — floor should NOT apply
# =========================================================================


class TestDomesticCurrencyNoFloor:
    """Domestic currency exposures are exempt from the sovereign floor."""

    def test_domestic_currency_no_floor_via_local_currency(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Exposure in institution's domestic currency → no floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,  # Would be 100% if floor applied
            local_currency="TRY",
            currency="TRY",  # Domestic currency match
            country_code="TR",
        )
        # SCRA A = 40% stands — domestic currency, floor does not apply
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_uk_institution_gbp_no_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """UK institution in GBP → domestic, no floor (even without local_currency)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=1,
            currency="GBP",
            country_code="GB",
            # No local_currency — falls back to _is_domestic_currency
        )
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_uk_institution_usd_floor_applies(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """UK institution in USD → FX, sovereign floor applies (CQS 1 = 0%, no effect)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=1,
            currency="USD",
            country_code="GB",
            # No local_currency — falls back to _is_domestic_currency
        )
        # Floor is 0% (UK CQS 1), SCRA A = 40% stands
        assert result["risk_weight"] == pytest.approx(0.40)


# =========================================================================
# Rated institution — floor does NOT apply
# =========================================================================


class TestRatedInstitutionNoFloor:
    """Rated institutions use ECRA — sovereign floor only applies to unrated."""

    def test_rated_institution_no_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Rated institution (CQS 2 = 30%) not subject to sovereign floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            cqs=2,  # Rated — uses ECRA
            sovereign_cqs=4,  # Would be 100% if floor applied
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        # CQS 2 = 30% (UK deviation), not floored
        assert result["risk_weight"] == pytest.approx(0.30)


# =========================================================================
# Trade exemption
# =========================================================================


class TestTradeExemption:
    """Self-liquidating trade items ≤ 1yr exempt from sovereign floor."""

    def test_trade_lc_exempt_from_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Short-term trade LC with maturity ≤ 1yr → exempt from sovereign floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,  # Would be 100% if floor applied
            local_currency="TRY",
            currency="USD",
            country_code="TR",
            is_short_term_trade_lc=True,
            residual_maturity_years=0.5,  # ≤ 1yr
        )
        # SCRA A = 40% stands — trade exempt
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_trade_lc_over_1yr_not_exempt(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Short-term trade LC with maturity > 1yr → NOT exempt, floor applies."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
            is_short_term_trade_lc=True,
            residual_maturity_years=1.5,  # > 1yr
        )
        # Sovereign floor 100% binds over SCRA A 40%
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_non_trade_not_exempt(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Non-trade exposure with short maturity → NOT exempt from floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
            is_short_term_trade_lc=False,
            residual_maturity_years=0.5,
        )
        # Sovereign floor 100% binds — not trade LC
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_trade_lc_exactly_1yr_exempt(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Trade LC with maturity exactly 1yr → exempt (≤ 1yr)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
            is_short_term_trade_lc=True,
            residual_maturity_years=1.0,
        )
        assert result["risk_weight"] == pytest.approx(0.40)


# =========================================================================
# Null / missing data — backward compatibility
# =========================================================================


class TestBackwardCompatibility:
    """Null sovereign CQS or missing columns → no floor applied."""

    def test_null_sovereign_cqs_no_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Null sovereign CQS → no floor, backward compatible."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=None,  # No sovereign CQS
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        # SCRA A = 40% stands — no sovereign data
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_missing_columns_backward_compat(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """No sovereign_cqs or local_currency columns → no floor."""
        # Build minimal LazyFrame without sovereign fields
        data = {
            "exposure_reference": ["SINGLE"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["INSTITUTION"],
            "cqs": [None],
            "cp_scra_grade": ["A"],
            "currency": ["USD"],
            "cp_country_code": ["TR"],
        }
        df = pl.DataFrame(data).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        # SCRA A = 40% — no sovereign columns means no floor
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_null_local_currency_fallback_to_domestic(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Null local_currency → falls back to UK/EU domestic check.

        GB institution with null local_currency in GBP → detected as domestic.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=4,
            local_currency=None,  # Falls back to _is_domestic_currency
            currency="GBP",
            country_code="GB",
        )
        # GB+GBP = domestic → no floor
        assert result["risk_weight"] == pytest.approx(0.40)


# =========================================================================
# CRR path — same sovereign floor applies
# =========================================================================


class TestCRRSovereignFloor:
    """CRR Art. 121(6) sovereign floor for unrated FX institution exposures."""

    def test_crr_sovereign_floor_binds(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR unrated institution = 40%, sovereign CQS 4 = 100% → floor binds."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=crr_config,
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_crr_rated_institution_no_floor(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR rated institution (CQS 3 = 50%) → no sovereign floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=crr_config,
            cqs=3,  # Rated
            sovereign_cqs=4,
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_crr_domestic_no_floor(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR domestic currency → no floor."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=crr_config,
            sovereign_cqs=4,
            local_currency="GBP",
            currency="GBP",
            country_code="GB",
        )
        # CRR unrated = 100% (Art. 120(2) Table 3) — domestic, no floor
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_null_sovereign_cqs_no_floor(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR null sovereign CQS → no floor, backward compatible."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=crr_config,
            sovereign_cqs=None,
            currency="USD",
            country_code="TR",
        )
        # CRR unrated = 100% (Art. 120(2) Table 3) — no sovereign data
        assert result["risk_weight"] == pytest.approx(1.00)


# =========================================================================
# Non-institution — floor should NOT apply
# =========================================================================


class TestNonInstitutionNoFloor:
    """Sovereign floor only applies to institution exposure class."""

    def test_corporate_no_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Corporate exposure → sovereign floor does not apply."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="CORPORATE",
            config=b31_config,
            sovereign_cqs=6,  # Would be 150% if floor applied
            local_currency="TRY",
            currency="USD",
            country_code="TR",
        )
        # Unrated corporate = 100% (not floored to 150%)
        assert result["risk_weight"] == pytest.approx(1.0)


# =========================================================================
# RWA correctness
# =========================================================================


class TestRWACorrectness:
    """Verify RWA = EAD × floored_RW."""

    def test_rwa_with_sovereign_floor(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """RWA = EAD × sovereign_RW when floor binds."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",  # 40%
            sovereign_cqs=3,  # 50% floor
            local_currency="INR",
            currency="USD",
            country_code="IN",
        )
        assert result["risk_weight"] == pytest.approx(0.50)
        assert result["rwa"] == pytest.approx(250_000)


# =========================================================================
# Mixed batch — multiple exposures
# =========================================================================


class TestMixedBatch:
    """Mixed batch with floor-eligible and non-eligible exposures."""

    def test_mixed_batch(self, sa_calculator: SACalculator, b31_config: CalculationConfig) -> None:
        """3 institution exposures: domestic (no floor), FX floor binds, FX no floor."""
        data = {
            "exposure_reference": ["INST_DOM", "INST_FX_FLOOR", "INST_FX_NOFX"],
            "ead_final": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "exposure_class": ["INSTITUTION", "INSTITUTION", "INSTITUTION"],
            "cqs": [None, None, None],
            "cp_scra_grade": ["A", "A", "A"],
            "cp_sovereign_cqs": [4, 4, 1],
            "cp_local_currency": ["TRY", "TRY", "GBP"],
            "currency": ["TRY", "USD", "USD"],
            "cp_country_code": ["TR", "TR", "GB"],
        }
        df = pl.DataFrame(data).lazy()
        results = sa_calculator.calculate_branch(df, b31_config).collect()
        rw = results.get_column("risk_weight").to_list()

        # INST_DOM: domestic TRY → SCRA A = 40%
        assert rw[0] == pytest.approx(0.40)
        # INST_FX_FLOOR: FX USD → sovereign CQS 4 = 100% floor binds
        assert rw[1] == pytest.approx(1.0)
        # INST_FX_NOFX: FX USD but sovereign CQS 1 = 0% → SCRA A = 40% stands
        assert rw[2] == pytest.approx(0.40)


# =========================================================================
# Sovereign CQS → RW mapping correctness
# =========================================================================


class TestSovereignCQSMapping:
    """Verify all CQS values map to correct sovereign RW."""

    @pytest.mark.parametrize(
        ("sov_cqs", "expected_sov_rw"),
        [
            (1, 0.0),
            (2, 0.20),
            (3, 0.50),
            (4, 1.0),
            (5, 1.0),
            (6, 1.50),
        ],
    )
    def test_sovereign_cqs_to_rw_mapping(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        sov_cqs: int,
        expected_sov_rw: float,
    ) -> None:
        """Each sovereign CQS maps to correct RW per Art. 114 table."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A_ENHANCED",  # 30% — lowest non-zero, so floor binds for CQS 2+
            sovereign_cqs=sov_cqs,
            local_currency="XXX",
            currency="USD",
            country_code="XX",
        )
        # Floor = max(30%, sovereign_rw). For CQS 1 (0%), 30% stands.
        expected_rw = max(0.30, expected_sov_rw)
        assert result["risk_weight"] == pytest.approx(expected_rw)
