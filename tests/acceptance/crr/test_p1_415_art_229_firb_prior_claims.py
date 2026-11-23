"""
P1.415 CRR — Art. 229(1): F-IRB property collateral is valued net of prior claims.

Scenario: the P1.235 attested real-estate F-IRB case — a 10m senior non-FSE corporate
loan secured by a 10m residential property, attested IRB-eligible, PD 2%, M 3.0y —
with ``prior_charge_ltv`` set on the property. CRR Art. 229(1): "The value of the
collateral shall be the market value ... reduced as appropriate ... to take account
of any prior claims on the immovable property", so C = MV - P with
P = prior_charge_ltv x MV. That C feeds the Art. 230(2) Table 5 C* (30%) test and the
C** (140%) secured portion:

    prior 0.0 -> C 10m, ES 10m/1.4 = 7.142857m, LGD* 0.378571   (control, unchanged)
    prior 0.3 -> C  7m, ES  7m/1.4 = 5m,        LGD* 0.400000
    prior 0.6 -> C  4m, ES  4m/1.4 = 2.857143m, LGD* 0.421429
    prior 0.8 -> C  2m, C/E 0.20 < C* 0.30,     LGD  0.45 (fully unsecured, CRM022)
    prior 1.2 -> C  0 (claims exceed the property), LGD 0.45

LGD* = (ES x 35% + (E - ES) x 45%) / E (Art. 161(1)(a) LGDU 45%, Table 5 LGDS 35%).
Pre-fix the engine ignored ``prior_charge_ltv`` on the F-IRB path: every leg gave
LGD 0.378571 and a 10m real-estate carrier.

RWA is the CRR corporate IRB formula (Art. 153(1), x1.06 scaling) at PD 2%, M 3.0y,
EAD 10m, hand-computed independently of the engine; the control leg reproduces the
engine's own pre-fix figure (10,809,335.66), which anchors the formula.

Two further legs at prior 0.3:

- A real-estate synonym (``residential_property``, ``Residential_Property``) takes the
  same deduction: ``collateral_category_expr`` files it as real estate, so it reaches
  the C* test and the carrier exactly as ``real_estate`` does. (The input-domain gate
  raises a DQ006 warning on the spelling; the engine still categorises it.)
- A property maturing 2028-06-30 against the 2029-06-30 loan: Art. 229(1) sets the
  collateral's value and the Art. 237-239 maturity factor then scales it, so
  C = (MV - P) x MM, MM = (t - 0.25) / (T - 0.25) with t, T in days / 365.25 from the
  reporting date: MM 0.636703, C 4,456,921, LGD* 0.418165. Deducting P after the factor
  would give C 3,367,030 and LGD* 0.425950.

The CRR text was read from watchfire's legislation.gov.uk snapshot of Art. 229(1)
(docs/assets/crr.pdf is empty here). The change raises RWA, so LESSONS A2's
mandatory-PDF rule does not bind.

References:
    - CRR Art. 229(1): value net of prior claims on the immovable property.
    - CRR Art. 230(2) Table 5: C* 30%, C** 140%, LGDS 35% for real estate.
    - CRR Art. 161(1)(a): LGDU 45% senior unsecured corporate.
    - IMPLEMENTATION_PLAN.md: P1.415.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_415_pipeline_helpers import CRR_REPORTING_DATE, run_prior_claim
from tests.fixtures.p1_235.p1_235 import COLLATERAL_MV, DRAWN_AMOUNT

_LOAN_MATURITY = date(2029, 6, 30)
_PROPERTY_MATURITY = date(2028, 6, 30)

# prior_charge_ltv -> (lgd_floored, collateral_re_value, IRB rwa), hand-computed.
_EXPECTED: dict[float, tuple[float, float, float]] = {
    0.3: (0.400000, 7_000_000.0, 11_421_184.85),
    0.6: (0.421429, 4_000_000.0, 12_033_034.04),
    0.8: (0.450000, 2_000_000.0, 12_848_832.96),
    1.2: (0.450000, 0.0, 12_848_832.96),
}


class TestP1415CrrPriorClaims:
    """CRR: claims ranking ahead reduce C before the C* test and the C** split."""

    def test_fixture_can_discriminate(self) -> None:
        """Adequacy: a 10m property behind a 10m loan, so every prior leg moves C/E."""
        assert COLLATERAL_MV == DRAWN_AMOUNT == 10_000_000.0

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_lgd_reflects_prior_claims(self, prior: float) -> None:
        """F-IRB LGD* is computed on C = MV - P (Art. 229(1) into Art. 230(2))."""
        # Arrange
        expected_lgd, _, _ = _EXPECTED[prior]

        # Act
        row = run_prior_claim("crr", prior).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(expected_lgd, abs=1e-6)

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_real_estate_carrier_is_net_of_prior_claims(self, prior: float) -> None:
        """The Foundation-limb carrier (C 08.01 col 0190) reports C = MV - P, floor 0."""
        # Arrange
        _, expected_value, _ = _EXPECTED[prior]

        # Act
        row = run_prior_claim("crr", prior).row

        # Assert
        assert row["collateral_re_value"] == pytest.approx(expected_value, abs=0.01)
        assert row["collateral_re_market_value"] == pytest.approx(COLLATERAL_MV, abs=0.01), (
            "the AIRB market-value carrier is the gross property value and must not move"
        )

    @pytest.mark.parametrize("prior", sorted(_EXPECTED))
    def test_irb_rwa_reflects_prior_claims(self, prior: float) -> None:
        """Pre-floor IRB RWA at the hand-computed LGD (PD 2%, M 3.0y, x1.06)."""
        # Arrange
        _, _, expected_rwa = _EXPECTED[prior]

        # Act
        row = run_prior_claim("crr", prior).row

        # Assert
        assert row["rwa"] == pytest.approx(expected_rwa, rel=1e-6)

    def test_prior_claim_below_c_star_raises_crm022(self) -> None:
        """Prior 0.8 leaves C/E = 0.20 < C* 0.30: the property is dropped (CRM022)."""
        # Act
        run = run_prior_claim("crr", 0.8)

        # Assert
        assert "CRM022" in run.error_codes

    @pytest.mark.parametrize("prior", [0.0, None])
    def test_first_charge_is_unchanged(self, prior: float | None) -> None:
        """Control: no prior claim (0.0 or unreported) keeps LGD* 0.378571 and 10m."""
        # Act
        row = run_prior_claim("crr", prior).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(0.378571, abs=1e-6)
        assert row["collateral_re_value"] == pytest.approx(10_000_000.0, abs=0.01)
        assert row["rwa"] == pytest.approx(10_809_335.66, rel=1e-6)


class TestP1415CrrPriorClaimsAcrossSpellingAndMaturity:
    """The deduction follows the real-estate category, and precedes the maturity factor."""

    @pytest.mark.parametrize("collateral_type", ["residential_property", "Residential_Property"])
    def test_real_estate_synonym_is_net_of_prior_claims(self, collateral_type: str) -> None:
        """A synonym-spelled property is valued C = MV - P, as ``real_estate`` is."""
        # Act
        row = run_prior_claim("crr", 0.3, collateral_type=collateral_type).row

        # Assert
        assert row["lgd_floored"] == pytest.approx(0.40, abs=1e-6)
        assert row["collateral_re_value"] == pytest.approx(7_000_000.0, abs=0.01)
        assert row["rwa"] == pytest.approx(11_421_184.85, rel=1e-6)

    def test_prior_claims_come_off_before_the_maturity_factor(self) -> None:
        """C = (MV - P) x (t - 0.25) / (T - 0.25), not MV x MM - P (Art. 229(1), 237-239)."""
        # Arrange
        t = (_PROPERTY_MATURITY - CRR_REPORTING_DATE).days / 365.25
        big_t = (_LOAN_MATURITY - CRR_REPORTING_DATE).days / 365.25
        mm = (t - 0.25) / (big_t - 0.25)
        expected_c = (COLLATERAL_MV - 0.3 * COLLATERAL_MV) * mm
        expected_lgd = 0.45 - (0.45 - 0.35) * (expected_c / 1.4) / DRAWN_AMOUNT

        # Act
        row = run_prior_claim("crr", 0.3, collateral_maturity_date=_PROPERTY_MATURITY).row

        # Assert
        assert row["collateral_re_value"] == pytest.approx(expected_c, rel=1e-9)
        assert row["lgd_floored"] == pytest.approx(expected_lgd, rel=1e-9)
