"""
P1.254 — PS1/26 Art. 121(6): the SCRA sovereign floor when the sovereign is UNRATED.

Art. 121(6) (ps126app1.pdf): "Notwithstanding paragraphs 2 to 5, the risk weight
assigned to an exposure to an institution for which a credit assessment by a
nominated ECAI is not available may not be less than the risk weight applicable to
exposures to the central government of the jurisdiction where the institution is
incorporated **as set out in Article 114(1) and (2)** if:
  (a) the exposure: (i) is not in the local currency of the jurisdiction of
      incorporation of the debtor institution; or (ii) for a borrowing booked in a
      branch of the debtor institution in a foreign jurisdiction, is not in the
      local currency of the jurisdiction in which the branch operates; and
  (b) the exposure is not a self-liquidating, trade-related contingent item arising
      from the movement of goods with an original maturity of less than one year."

The floor is defined by reference to Art. 114(1) **and** (2) — not (2) alone.
Art. 114(2) Table 1 is the *rated* ladder (CQS 1 -> 0%, 2 -> 20%, 3 -> 50%,
4 -> 100%, 5 -> 100%, 6 -> 150%). Art. 114(1) is the residual: "Exposures to central
governments or central banks shall be assigned a **100% risk weight**" unless one of
the listed reliefs applies. So an institution incorporated in a jurisdiction whose
central government carries NO ECAI assessment does not escape the floor — its floor
is the Art. 114(1) 100%.

``_apply_sovereign_floor_for_institutions`` currently reads Art. 114(2) only: it
maps ``cp_sovereign_cqs`` through ``CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS`` with a
null fallback and then gates the floor on ``_sovereign_rw.is_not_null()``, so a null
``cp_sovereign_cqs`` silently disapplies the floor entirely. Row T below pins the
Art. 114(1) 100% outcome; C1-C3 are the anti-confound controls that keep the fix
narrow — a blanket 100% for every unrated institution would break C1 and C2, and
dropping the trade carve-out would break C3.

References:
- PS1/26 Art. 121(6)(a)-(b): sovereign floor scope and the trade carve-out
- PS1/26 Art. 114(1): unrated central government -> 100%
- PS1/26 Art. 114(2) Table 1: rated central government ladder
- PS1/26 Art. 121(2)-(3) / CRE20.19-21: SCRA Grade A long-term 40%
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from tests.fixtures.single_exposure import calculate_single_sa_exposure

_EAD = Decimal("1000000")

# SCRA Grade A, long-term (original maturity > 3m) — PS1/26 Art. 121(2), Table 5.
_SCRA_A_LONG_TERM_RW = 0.40

# Art. 114(1) residual risk weight for a central government with no ECAI assessment.
_UNRATED_SOVEREIGN_RW = 1.00


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


class TestArt1216UnratedSovereignFloor:
    """Art. 121(6) floors an FX unrated-institution exposure at the Art. 114(1) 100%."""

    def test_p1_254_unrated_sovereign_floors_fx_institution_at_100pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Row T — null sovereign CQS + FX + non-trade: floor binds at Art. 114(1) 100%."""
        # Arrange / Act — unrated institution (SCRA Grade A = 40%) incorporated in a
        # jurisdiction whose central government carries no ECAI assessment, borrowing
        # in USD rather than its local ZWG.
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=None,
            local_currency="ZWG",
            currency="USD",
            country_code="ZW",
        )

        # Assert — Art. 114(1) 100% floors the 40% SCRA weight.
        assert result["risk_weight"] == pytest.approx(_UNRATED_SOVEREIGN_RW)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_p1_254_rated_sovereign_floor_reads_table_1_not_a_blanket_100pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Control C1 — CQS 1 sovereign: floor is Art. 114(2) 0%, so SCRA A stands."""
        # Arrange / Act — identical to row T except the central government is rated
        # CQS 1.
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=1,
            local_currency="ZWG",
            currency="USD",
            country_code="ZW",
        )

        # Assert — the floor still reads the sovereign's own value (0%), so it does
        # not bind. A blanket 100% for unrated institutions would fail here.
        assert result["risk_weight"] == pytest.approx(_SCRA_A_LONG_TERM_RW)

    def test_p1_254_local_currency_exposure_is_outside_art_121_6_a(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Control C2 — local-currency exposure: Art. 121(6)(a) unmet, no floor."""
        # Arrange / Act — identical to row T except the exposure is denominated in the
        # institution's local currency.
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=None,
            local_currency="ZWG",
            currency="ZWG",
            country_code="ZW",
        )

        # Assert — SCRA Grade A 40% stands; the currency limb gates the floor off.
        assert result["risk_weight"] == pytest.approx(_SCRA_A_LONG_TERM_RW)

    def test_p1_254_short_term_trade_item_is_carved_out_by_art_121_6_b(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Control C3 — self-liquidating trade item < 1yr: Art. 121(6)(b) carve-out.

        Original maturity is 0.9y, not 0.5y: it sits inside the Art. 121(6)(b)
        "less than one year" carve-out but OUTSIDE the Art. 121(3)/(4) SCRA
        short-term window (<= 3m, extended to <= 6m for trade LCs). That keeps the
        expected weight at the long-term Grade A 40% and isolates the carve-out from
        the short-term-weight branch, which would otherwise return 20%.
        """
        # Arrange / Act — identical to row T except the exposure is a self-liquidating
        # trade-related contingent item with original maturity < 1 year.
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="INSTITUTION",
            config=b31_config,
            scra_grade="A",
            sovereign_cqs=None,
            local_currency="ZWG",
            currency="USD",
            country_code="ZW",
            is_short_term_trade_lc=True,
            original_maturity_years=0.9,
        )

        # Assert — SCRA Grade A 40% stands; the trade carve-out gates the floor off.
        assert result["risk_weight"] == pytest.approx(_SCRA_A_LONG_TERM_RW)
