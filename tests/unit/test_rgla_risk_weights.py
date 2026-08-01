"""
Unit tests for RGLA (Regional Government and Local Authority) risk weights.

Why these tests matter:
    RGLA exposures include UK devolved governments (Scotland, Wales, NI), UK local
    authorities, and foreign regional/municipal governments. Without correct RGLA risk
    weight tables, all RGLA exposures silently default to 100% via the CQS join
    fallback. This produces capital overstatement for UK devolved govts (should be 0%),
    UK local authorities (should be 20%), and well-rated foreign RGLAs (CQS 1 = 20%),
    while understating capital for poorly-rated RGLAs (CQS 6 should be 150%).

RGLA treatment (Art. 115) is identical under CRR and PRA PS1/26 Basel 3.1:
    - Rated RGLAs (own ECAI): Table 1B (Art. 115(1)(b))
    - Unrated RGLAs: Sovereign-derived Table 1A (Art. 115(1)(a))
    - UK devolved administrations: 0% (PRA designation)
    - UK local authorities: 20% (PRA designation)
    - Domestic-currency RGLA: 20% regardless of CQS, but scoped to UK RGLAs
      denominated and funded in sterling only (Art. 115(5)) -- non-UK
      domestic-currency RGLAs (e.g. EU) fall through to Table 1A/1B instead

References:
    - CRR Art. 115 / PRA PS1/26 Art. 115: RGLA risk weights
    - Table 1A: Sovereign-derived risk weights
    - Table 1B: Own-rating risk weights
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.b31_risk_weight_tables import get_b31_combined_cqs_risk_weights
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_RISK_WEIGHTS_OWN_RATING,
    RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    RGLA_UK_DEVOLVED_RW,
    RGLA_UK_LOCAL_AUTH_RW,
    RGLA_UNRATED_DEFAULT_RW,
    get_combined_cqs_risk_weights,
    lookup_risk_weight,
)
from tests.fixtures.single_exposure import calculate_single_sa_exposure

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


class TestRGLARiskWeightTables:
    """Tests for RGLA risk weight dict tables and DataFrame generators."""

    def test_sovereign_derived_table_values(self):
        """Table 1A (Art. 115(1)(a)): sovereign-derived RGLA risk weights."""
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS1] == Decimal("0.20")
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS2] == Decimal("0.50")
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS3] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS4] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS5] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS6] == Decimal("1.50")

    def test_own_rating_table_values(self):
        """Table 1B (Art. 115(1)(b)): own-rating RGLA risk weights."""
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS1] == Decimal("0.20")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS2] == Decimal("0.50")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS3] == Decimal("0.50")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS4] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS5] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS6] == Decimal("1.50")

    def test_cqs3_differs_between_tables(self):
        """CQS 3 is 100% sovereign-derived (Table 1A) but 50% own-rating (Table 1B)."""
        assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS3] == Decimal("1.00")
        assert RGLA_RISK_WEIGHTS_OWN_RATING[CQS.CQS3] == Decimal("0.50")

    def test_uk_devolved_rw(self):
        """PRA designation: UK devolved administrations receive 0%."""
        assert Decimal("0.00") == RGLA_UK_DEVOLVED_RW

    def test_uk_local_auth_rw(self):
        """PRA designation: UK local authorities receive 20%."""
        assert Decimal("0.20") == RGLA_UK_LOCAL_AUTH_RW

    def test_domestic_currency_rw(self):
        """Art. 115(5): domestic-currency RGLA → 20%."""
        assert Decimal("0.20") == RGLA_DOMESTIC_CURRENCY_RW

    def test_unrated_default(self):
        """Conservative fallback for unrated RGLA when sovereign CQS unknown."""
        assert Decimal("1.00") == RGLA_UNRATED_DEFAULT_RW

    def test_rgla_in_combined_crr_table(self):
        """RGLA rows are included in the combined CRR CQS risk weight table."""
        combined = get_combined_cqs_risk_weights()
        rgla_rows = combined.filter(combined["exposure_class"] == "RGLA")
        assert len(rgla_rows) == 6  # CQS 1-6, no unrated row

    def test_rgla_in_combined_b31_table(self):
        """RGLA rows are included in the combined B31 CQS risk weight table."""
        combined = get_b31_combined_cqs_risk_weights()
        rgla_rows = combined.filter(combined["exposure_class"] == "RGLA")
        assert len(rgla_rows) == 6  # CQS 1-6, no unrated row

    def test_lookup_risk_weight_rated_rgla(self):
        """lookup_risk_weight returns Table 1B values for rated RGLA."""
        assert lookup_risk_weight("RGLA", 1) == Decimal("0.20")
        assert lookup_risk_weight("RGLA", 2) == Decimal("0.50")
        assert lookup_risk_weight("RGLA", 3) == Decimal("0.50")
        assert lookup_risk_weight("RGLA", 4) == Decimal("1.00")
        assert lookup_risk_weight("RGLA", 5) == Decimal("1.00")
        assert lookup_risk_weight("RGLA", 6) == Decimal("1.50")

    def test_lookup_risk_weight_unrated_rgla(self):
        """lookup_risk_weight returns conservative 100% for unrated RGLA."""
        assert lookup_risk_weight("RGLA", None) == Decimal("1.00")
        assert lookup_risk_weight("RGLA", 0) == Decimal("1.00")


# =============================================================================
# CRR SA CALCULATOR TESTS
# =============================================================================


class TestCRRRGLARiskWeights:
    """Tests for RGLA risk weights through the CRR SA calculator pipeline."""

    def test_rated_rgla_cqs1(self, sa_calculator, crr_config):
        """CRR rated RGLA CQS 1 → 20% via Table 1B join."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=1,
            config=crr_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_rgla_cqs3(self, sa_calculator, crr_config):
        """CRR rated RGLA CQS 3 → 50% (Table 1B, not 100% from Table 1A)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=3,
            config=crr_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_rgla_cqs6(self, sa_calculator, crr_config):
        """CRR rated RGLA CQS 6 → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=6,
            config=crr_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_uk_devolved_govt_zero_percent(self, sa_calculator, crr_config):
        """CRR UK devolved government (rgla_sovereign) → 0% (PRA designation)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=crr_config,
            country_code="GB",
            entity_type="rgla_sovereign",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_uk_local_authority_domestic_currency(self, sa_calculator, crr_config):
        """CRR UK local authority in GBP → 20% via Art. 115(5) domestic currency."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=crr_config,
            country_code="GB",
            currency="GBP",
            entity_type="rgla_institution",
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_uk_rgla(self, sa_calculator, crr_config):
        """CRR unrated UK RGLA → 20% (sovereign-derived, UK CQS 1)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=crr_config,
            country_code="GB",
            sovereign_cqs=1,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_non_uk_rgla(self, sa_calculator, crr_config):
        """CRR unrated non-UK RGLA → 100% conservative default."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=crr_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rwa_calculation(self, sa_calculator, crr_config):
        """CRR RGLA RWA = EAD x RW = 5,000,000 x 0.20 = 1,000,000."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=1,
            config=crr_config,
            country_code="DE",
        )
        assert result["rwa"] == pytest.approx(5_000_000 * 0.20)

    def test_eu_domestic_currency_rgla(self, sa_calculator, crr_config):
        """
        CRR EU RGLA in domestic currency (DE+EUR), rated CQS 4 → 100%
        (P1.222: Art. 115(5) is scoped to UK RGLAs denominated AND funded
        in sterling only -- non-UK domestic-currency RGLAs are NOT exempt
        from the flat 20% override and instead fall to Table 1B own-rating,
        CQS 4 = 100%).
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=4,
            config=crr_config,
            country_code="DE",
            currency="EUR",
        )
        # Art. 115(5) domestic-currency 20% is UK/GBP-scoped and does NOT apply
        # here; falls through to Table 1B own-rating CQS 4 = 100%.
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_non_uk_devolved_not_zero(self, sa_calculator, crr_config):
        """Non-UK rgla_sovereign does NOT get 0% — only UK devolved govts do."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=crr_config,
            country_code="DE",
            entity_type="rgla_sovereign",
        )
        # Non-UK, non-domestic-currency, unrated → 100% conservative default
        assert result["risk_weight"] == pytest.approx(1.00)


# =============================================================================
# BASEL 3.1 SA CALCULATOR TESTS
# =============================================================================


class TestB31RGLARiskWeights:
    """Tests for RGLA risk weights through the Basel 3.1 SA calculator pipeline."""

    def test_rated_rgla_cqs1(self, sa_calculator, b31_config):
        """B31 rated RGLA CQS 1 → 20% via Table 1B join."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=1,
            config=b31_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_rgla_cqs3(self, sa_calculator, b31_config):
        """B31 rated RGLA CQS 3 → 50% (Table 1B own-rating)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=3,
            config=b31_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_rgla_cqs6(self, sa_calculator, b31_config):
        """B31 rated RGLA CQS 6 → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=6,
            config=b31_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_uk_devolved_govt_zero_percent(self, sa_calculator, b31_config):
        """B31 UK devolved government (rgla_sovereign) → 0%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=b31_config,
            country_code="GB",
            entity_type="rgla_sovereign",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_uk_local_authority_domestic_currency(self, sa_calculator, b31_config):
        """B31 UK local authority in GBP → 20%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=b31_config,
            country_code="GB",
            currency="GBP",
            entity_type="rgla_institution",
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_uk_rgla(self, sa_calculator, b31_config):
        """B31 unrated UK RGLA → 20% (sovereign-derived)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=b31_config,
            country_code="GB",
            sovereign_cqs=1,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_non_uk_rgla(self, sa_calculator, b31_config):
        """B31 unrated non-UK RGLA → 100% conservative default."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=b31_config,
            country_code="DE",
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_null_country_unrated_rgla(self, sa_calculator, b31_config):
        """B31 unrated RGLA with null country → 100% conservative."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_uk_devolved_with_cqs_still_zero(self, sa_calculator, b31_config):
        """UK devolved govt with a CQS rating still gets 0% (PRA overrides CQS)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="rgla",
            cqs=3,
            config=b31_config,
            country_code="GB",
            entity_type="rgla_sovereign",
        )
        assert result["risk_weight"] == pytest.approx(0.0)


# =============================================================================
# P1.282 — RGLA SOVEREIGN-EQUIVALENCE ROUTED THROUGH ART. 114 (CGCB)
# =============================================================================


@pytest.fixture(params=["crr", "b31"])
def either_regime_config(request) -> CalculationConfig:
    """Both regimes — Art. 114/115 sovereign-equivalence is regime-invariant."""
    if request.param == "crr":
        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


class TestP1282RGLASovereignEquivalenceViaCGCB:
    """
    P1.282: sovereign-equivalent RGLAs must price off the Art. 114 CGCB ladder.

    Art. 115(2) directs exposures to the Scottish Government, the Welsh
    Government and the Northern Ireland Executive to be "treated as exposures
    to the central government of the UK and assigned a risk weight in
    accordance with Article 114" — not pinned at 0% irrespective of the
    sovereign's CQS. The CRR Art. 115(4) equivalence-list mechanism survives
    under PS1/26 (the PRA left the provision out of the Rulebook), so the same
    Art. 114 routing applies to a non-UK ``rgla_sovereign``.

    The engine currently short-circuits ``rgla_sovereign`` two ways, both wrong:
      - GB rows are pinned to 0% regardless of currency and sovereign CQS
        (understates once the UK CQS exceeds 1 on a non-sterling exposure);
      - non-GB rows fall into the ordinary Art. 115(1)(a) Table 1A chain and
        take 100% at CQS 3 where Art. 114 gives 50% (overstates).

    CQS 3 is the discriminating point: CGCB Table 1 gives 50%, Table 1A gives
    100%, the Art. 115(5) sterling flat gives 20% and the hardcoded devolved
    branch gives 0% — all four separate cleanly, so a leak cannot hide.

    References:
        - PS1/26 Art. 115(2) — devolved administrations take Art. 114
        - CRR Art. 115(4) — third-country RGLA sovereign equivalence
        - PS1/26 Art. 114(2) Table 1 — CGCB CQS 3 -> 50%
        - PS1/26 Art. 115(1)(a) Table 1A — sovereign-derived CQS 3 -> 100%
    """

    def test_p1_282_gb_rgla_sovereign_non_sterling_uses_cgcb_ladder(
        self, sa_calculator, either_regime_config
    ):
        """T1: GB devolved govt, USD, sovereign CQS 3 → Art. 114 50%, not 0%."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=either_regime_config,
            country_code="GB",
            currency="USD",
            entity_type="rgla_sovereign",
            sovereign_cqs=3,
        )

        # Assert — Art. 115(2) routes to Art. 114(2) Table 1, CQS 3 = 50%.
        assert result["risk_weight"] == pytest.approx(0.50)
        assert result["rwa"] == pytest.approx(5_000_000.0)

    def test_p1_282_non_gb_rgla_sovereign_uses_cgcb_ladder(
        self, sa_calculator, either_regime_config
    ):
        """T2: non-GB sovereign-equivalent RGLA, sovereign CQS 3 → 50%, not 100%."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=either_regime_config,
            country_code="DE",
            currency="USD",
            entity_type="rgla_sovereign",
            sovereign_cqs=3,
        )

        # Assert — Art. 115(4) equivalence takes Art. 114 (50%), not the
        # ordinary Art. 115(1)(a) Table 1A 100%. This limb REDUCES RWA.
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_p1_282_ordinary_rgla_not_routed_through_cgcb(
        self, sa_calculator, either_regime_config
    ):
        """C1: ordinary RGLA with a sovereign CQS stays on Table 1A (100%)."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=either_regime_config,
            country_code="GB",
            currency="USD",
            entity_type="rgla_institution",
            sovereign_cqs=3,
        )

        # Assert — Art. 115(1)(a) Table 1A CQS 3 = 100%; the sovereign-
        # equivalence re-route must not leak onto ordinary RGLAs.
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_p1_282_gb_sterling_rgla_sovereign_still_zero(
        self, sa_calculator, either_regime_config
    ):
        """C2: GB devolved govt in sterling keeps the 0% base case."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=either_regime_config,
            country_code="GB",
            currency="GBP",
            entity_type="rgla_sovereign",
            sovereign_cqs=3,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_p1_282_rgla_sovereign_without_sovereign_cqs_still_zero(
        self, sa_calculator, either_regime_config
    ):
        """C3: no sovereign CQS → the Art. 114 route does not fire; 0% stands."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="rgla",
            config=either_regime_config,
            country_code="GB",
            currency="USD",
            entity_type="rgla_sovereign",
            sovereign_cqs=None,
        )

        # Assert
        assert result["risk_weight"] == pytest.approx(0.0)
