"""
P1.415 Basel 3.1 — PS1/26 Art. 229(1)(b): F-IRB property collateral net of prior claims.

Scenario: the P1.235 attested real-estate F-IRB case — a 10m senior non-FSE corporate
loan secured by a 10m residential property, attested IRB-eligible, PD 2% — run at
2027-06-30 (M 2.0y), with ``prior_charge_ltv`` set on the property.

PS1/26 Art. 229(1)(b), verbatim: the value is reduced "to take account of any claims
on the immovable property with priority over the institution's claim ... by reducing
the value of the property by: P / (1 - HC - Hfx) where: P = total value of all claims
ranking higher than the institution's claim"; and "Where the calculations under this
paragraph 1 result in a negative value, the institution shall assign zero value to
the collateral." Substituted into Art. 230(1)'s ES (HC 40% for immovable property, no
currency mismatch here so Hfx 0):

    ES = (MV - P / (1 - HC - Hfx)) x (1 - HC - Hfx) = max(0, MV x 0.60 - P)

    prior 0.0 -> ES 6m, LGD* 0.28   (control, unchanged)
    prior 0.3 -> ES 3m, LGD* 0.34
    prior 0.6 -> ES 0,  LGD  0.40
    prior 1.2 -> ES 0 (negative value -> zero), LGD 0.40

LGD* = LGDU x EU/E + LGDS x ES/E with LGDU 40% (Art. 161(1)(aa) non-FSE corporate) and
LGDS 20% (immovable property). Pre-fix the engine ignored ``prior_charge_ltv`` on the
F-IRB path: every leg gave LGD 0.28 and a 6m real-estate carrier. The prior 0.3 leg is
the one that tells ``MV x (1 - HC) - P`` (3m) from the wrong ``(MV - P) x (1 - HC)``
(4.2m, LGD 0.316).

The pari-passu limb, Art. 229(1)(c), is NOT built here: ``prior_charge_ltv`` mixes
prior and pari-passu claims, so the whole input is deducted as P (conservative) until
P1.449 splits the input.

RWA is the corporate IRB formula (Art. 153(1), no 1.06 scaling under Basel 3.1) at
PD 2%, M 2.0y, EAD 10m, hand-computed independently of the engine; the control leg
reproduces the engine's own pre-fix figure (6,750,678.81), which anchors the formula.

Further legs:

- A real-estate synonym (``residential_property``, ``Residential_Property``) at prior
  0.3 takes the same deduction (LGD* 0.34, ES 3m): ``collateral_category_expr`` files
  it as real estate. (The input-domain gate raises a DQ006 warning on the spelling.)
- A property maturing 2028-06-30 against the 2029-06-30 loan, prior 0.3: Art. 230(1)
  builds ES from the Art. 229(1)(b) value "after the application of" HC, Hfx and the
  Art. 237-239 maturity adjustment, so ES = (MV x (1 - HC) - P) x MM. MM 0.429409,
  ES 1,288,227, LGD* 0.374235. Deducting P after the factor would give
  max(0, 6m x MM - 3m) = 0 and LGD 0.40.
- The A-IRB LGD input floor (Art. 161(5)(b)): for the P1.248 corporate A-IRB property
  case (own LGD 5%, collateral modelled, M 3.0y at 2027-01-01) the floor is LGD*
  computed "using the Foundation Collateral Method" with LGDU 25% and LGDS 10%
  (immovable property), so it reads ES net of P:

      prior null -> ES 6m, floor 0.25 x 0.4 + 0.10 x 0.6 = 0.16
      prior 0.3  -> ES 3m, floor 0.25 x 0.7 + 0.10 x 0.3 = 0.205
      prior 0.6  -> ES 0,  floor 0.25

  RWA at those floors: 4,309,881.08 / 5,522,035.13 / 6,734,189.18 (the last is
  P1.248's flat-25% figure, which anchors the formula).

References:
    - PS1/26 Art. 229(1)(b): P / (1 - HC - Hfx) deduction; negative value -> zero.
    - PS1/26 Art. 230(1)-(2): ES and the 40% immovable-property HC.
    - PS1/26 Art. 161(1)(aa): LGDU 40% senior unsecured non-FSE corporate.
    - PS1/26 Art. 161(5)(b): A-IRB LGD input floor = LGD* with LGDU 25%, LGDS 10%.
    - IMPLEMENTATION_PLAN.md: P1.415.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.acceptance.p1_415_pipeline_helpers import (
    AIRB_EAD,
    B31_REPORTING_DATE,
    run_airb_prior_claim,
    run_prior_claim,
)
from tests.fixtures.p1_235.p1_235 import COLLATERAL_MV, DRAWN_AMOUNT

_LOAN_MATURITY = date(2029, 6, 30)
_PROPERTY_MATURITY = date(2028, 6, 30)

# prior_charge_ltv -> (A-IRB LGD input floor, crm_alloc_real_estate, IRB rwa), by hand.
_AIRB_EXPECTED: dict[float | None, tuple[float, float, float]] = {
    None: (0.16, 6_000_000.0, 4_309_881.08),
    0.3: (0.205, 3_000_000.0, 5_522_035.13),
    0.6: (0.25, 0.0, 6_734_189.18),
}

# prior_charge_ltv -> (lgd_floored, collateral_re_value, IRB rwa), hand-computed.
_EXPECTED: dict[float, tuple[float, float, float]] = {
    0.3: (0.34, 3_000_000.0, 8_197_252.84),
    0.6: (0.40, 0.0, 9_643_826.87),
    1.2: (0.40, 0.0, 9_643_826.87),
}


class TestP1415B31PriorClaims:
    """Basel 3.1: ES = max(0, MV x (1 - HC - Hfx) - P) on the Foundation Collateral Method."""

    def test_fixture_can_discriminate(self) -> None:
        """Adequacy: a 10m property behind a 10m loan, so every prior leg moves ES."""
        assert COLLATERAL_MV == DRAWN_AMOUNT == 10_000_000.0

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_lgd_reflects_prior_claims(self, prior: float) -> None:
        """F-IRB LGD* is computed on ES net of the prior claims (Art. 229(1)(b))."""
        # Arrange
        expected_lgd, _, _ = _EXPECTED[prior]

        # Act
        row = run_prior_claim("b31", prior).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(expected_lgd, abs=1e-6)

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_real_estate_carrier_is_net_of_prior_claims(self, prior: float) -> None:
        """The Foundation-limb carrier (OF 08.01 col 0190, adjusted Ci) is net of P."""
        # Arrange
        _, expected_value, _ = _EXPECTED[prior]

        # Act
        row = run_prior_claim("b31", prior).row

        # Assert
        assert row["collateral_re_value"] == pytest.approx(expected_value, abs=0.01)
        assert row["collateral_re_market_value"] == pytest.approx(COLLATERAL_MV, abs=0.01), (
            "the AIRB market-value carrier is the gross property value and must not move"
        )

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_irb_rwa_reflects_prior_claims(self, prior: float) -> None:
        """Pre-floor IRB RWA at the hand-computed LGD (PD 2%, M 2.0y)."""
        # Arrange
        _, _, expected_rwa = _EXPECTED[prior]

        # Act
        row = run_prior_claim("b31", prior).row

        # Assert
        assert row["rwa"] == pytest.approx(expected_rwa, rel=1e-6)

    @pytest.mark.parametrize("prior", [0.0, None])
    def test_first_charge_is_unchanged(self, prior: float | None) -> None:
        """Control: no prior claim (0.0 or unreported) keeps LGD* 0.28 and a 6m ES."""
        # Act
        row = run_prior_claim("b31", prior).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(0.28, abs=1e-6)
        assert row["collateral_re_value"] == pytest.approx(6_000_000.0, abs=0.01)
        assert row["rwa"] == pytest.approx(6_750_678.81, rel=1e-6)


class TestP1415B31PriorClaimsAcrossSpellingAndMaturity:
    """The deduction follows the real-estate category, and precedes the maturity factor."""

    @pytest.mark.parametrize("collateral_type", ["residential_property", "Residential_Property"])
    def test_real_estate_synonym_is_net_of_prior_claims(self, collateral_type: str) -> None:
        """A synonym-spelled property gives ES = MV x (1 - HC) - P, as ``real_estate`` does."""
        # Act
        row = run_prior_claim("b31", 0.3, collateral_type=collateral_type).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(0.34, abs=1e-6)
        assert row["collateral_re_value"] == pytest.approx(3_000_000.0, abs=0.01)
        assert row["rwa"] == pytest.approx(8_197_252.84, rel=1e-6)

    def test_prior_claims_come_off_before_the_maturity_factor(self) -> None:
        """ES = (MV x (1 - HC) - P) x (t - 0.25) / (T - 0.25) (Art. 229(1)(b), 230(1)(c))."""
        # Arrange
        t = (_PROPERTY_MATURITY - B31_REPORTING_DATE).days / 365.25
        big_t = (_LOAN_MATURITY - B31_REPORTING_DATE).days / 365.25
        mm = (t - 0.25) / (big_t - 0.25)
        expected_es = (COLLATERAL_MV * (1.0 - 0.40) - 0.3 * COLLATERAL_MV) * mm
        expected_lgd = 0.40 - (0.40 - 0.20) * expected_es / DRAWN_AMOUNT

        # Act
        row = run_prior_claim("b31", 0.3, collateral_maturity_date=_PROPERTY_MATURITY).row

        # Assert
        assert row["collateral_re_value"] == pytest.approx(expected_es, rel=1e-9)
        assert row["lgd_floored"] == pytest.approx(expected_lgd, rel=1e-9)


class TestP1415B31AirbLgdInputFloor:
    """Art. 161(5)(b): the A-IRB LGD input floor is LGD* on ES net of prior claims."""

    @pytest.mark.parametrize("prior", [None, 0.3, 0.6])
    def test_lgd_input_floor_reflects_prior_claims(self, prior: float | None) -> None:
        """Floor = 25% x EU/E + 10% x ES/E with ES = MV x (1 - 40%) - P."""
        # Arrange
        expected_floor, expected_es, _ = _AIRB_EXPECTED[prior]

        # Act
        row = run_airb_prior_claim(prior).row

        # Assert
        assert row["crm_alloc_real_estate"] == pytest.approx(expected_es, abs=0.01)
        assert row["lgd_floored"] == pytest.approx(expected_floor, abs=1e-9)
        assert expected_floor == pytest.approx(
            0.25 * (AIRB_EAD - expected_es) / AIRB_EAD + 0.10 * expected_es / AIRB_EAD
        )

    @pytest.mark.parametrize("prior", [None, 0.3, 0.6])
    def test_airb_rwa_reflects_prior_claims(self, prior: float | None) -> None:
        """IRB RWA at the floored LGD (PD 2%, M 3.0y, EAD 10m, no 1.06 scaling)."""
        # Arrange
        _, _, expected_rwa = _AIRB_EXPECTED[prior]

        # Act
        row = run_airb_prior_claim(prior).row

        # Assert
        assert row["rwa"] == pytest.approx(expected_rwa, rel=1e-6)
