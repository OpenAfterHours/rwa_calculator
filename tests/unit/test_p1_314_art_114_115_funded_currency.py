"""
P1.314 — the "denominated AND **funded**" limb on the DIRECT exposure path.

CRR Art. 114(4), Art. 114(7), Art. 115(5) and PS1/26 Art. 114(4), Art. 115(2),
Art. 115(5) each condition their relief on the exposure being "denominated
**and funded**" in the domestic currency. The engine implements the
denomination limb only on the direct path; the guarantor path (Art. 235(3))
already carries the funding limb (P1.229, ``engine/eu_sovereign.py``).

Verbatim text the legs below are built from (pymupdf-extracted, Wave 0):
    CRR Art. 114(4)  — "Exposures to [the central government of the United
        Kingdom and the Bank denominated and funded in sterling] shall be
        assigned a risk weight of 0 %."
    CRR Art. 114(7)  — "... to their central government and central bank
        denominated and funded in the domestic currency ..."
    CRR Art. 115(5)  — "Exposures to regional governments or local authorities
        of the [United Kingdom] ... denominated and funded in [pounds
        sterling] shall be assigned a risk weight of 20 %."
    PS1/26 Art. 115(2) — the Scottish Government, the Welsh Government and the
        Northern Ireland Executive "shall be treated as exposures to the
        central government of the UK and assigned a risk weight in accordance
        with Article 114".

Null convention: **PERMISSIVE**. An unreported funding currency falls back to
the exposure's denomination (``eu_sovereign.funding_currency_expr``), so a
dataset that does not populate the field keeps its existing treatment and no
data-quality event is raised. Leg C is the pin for that policy.

Both regimes, reddened separately (.claude/LESSONS.md C7): the two override
chains are separate functions sharing no code
(``risk_weights.py::_apply_crr_risk_weight_overrides`` /
``_apply_b31_risk_weight_overrides``), yet every expected value here is
IDENTICAL across regimes because both read the same rulepack entries. A single
red across a collapsed both-regimes parametrisation therefore proves ONE chain
was fixed, not two — run ``-k crr`` and ``-k b31`` as separate invocations.

References:
    - .claude/state/outputs/P1.314-scenario.md (§3.2 legs A-I, ADDENDUM legs
      J and K) — full hand-calculation and pack attribution for every value.
    - tests/acceptance/{crr,basel31}/test_p1_314_art_114_7_funded_currency.py
      — the end-to-end leg, which is the only leg that can see a comparison
      against the POST-FX ``currency`` column.
    - src/rwa_calc/engine/eu_sovereign.py — funding_currency_expr /
      denomination_currency_expr / build_eu_domestic_currency_expr.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.branch_reasons import UNKNOWN_FALLBACK, SovereignFloorReason
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.b31_risk_weight_tables import B31_SCRA_RISK_WEIGHTS
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    INSTITUTION_SHORT_TERM_UNRATED_RW_CRR,
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    RGLA_UK_DEVOLVED_RW,
)
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# =============================================================================
# SCENARIO CONSTANTS
# =============================================================================

#: Every leg carries the same EAD, so a risk-weight movement is the only thing
#: that can move RWA — and so ``ead_final`` can be asserted identically on all
#: of them (a zero-EAD row would make every RWA assertion vacuous).
EAD = Decimal("10000000")
EAD_F = 10_000_000.0

CGCB = "CENTRAL_GOVT_CENTRAL_BANK"
RGLA = "rgla"
INSTITUTION = "INSTITUTION"

# Expected risk weights. Stated as absolute literals (never as a movement
# relative to a baseline — .claude/LESSONS.md C1), and cross-checked against the
# pack-binding shims by ``test_p1_314_scenario_scalars_match_the_rulepack``
# below, so a pack drift reddens that guard instead of silently rewriting the
# scenario.
RW_CGCB_DOMESTIC = 0.00  # Art. 114(4)/(7) relief applies
RW_CGCB_CQS6 = 1.50  # cgcb_risk_weights[CQS6] — relief denied
RW_CGCB_CQS3 = 0.50  # cgcb_risk_weights[CQS3] — Art. 115(2) routing to Art. 114
RW_RGLA_DOMESTIC = 0.20  # Art. 115(5) flat — rgla_domestic_currency_rw
RW_RGLA_SOV_DERIVED_CQS3 = 1.00  # Art. 115(1)(a) Table 1A — relief denied
RW_RGLA_DEVOLVED = 0.00  # rgla_uk_devolved_rw
RW_SCRA_A = 0.40  # b31_scra_risk_weights["A"] — leg I base
RW_INSTITUTION_SHORT_TERM = 0.20  # Art. 121(3) flat — leg K base


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture(params=["crr", "b31"])
def either_regime_config(request) -> CalculationConfig:
    """Both regimes — every Art. 114/115 value below is regime-invariant.

    ``_apply_crr_risk_weight_overrides`` and ``_apply_b31_risk_weight_overrides``
    are separate functions that share no code, so this parametrisation is the
    only thing standing between "both chains carry the limb" and "one chain
    does". See the module docstring on running the two ids separately.
    """
    if request.param == "crr":
        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


# =============================================================================
# SHARED ASSERTIONS (presence / non-null / money-carrier identity)
# =============================================================================


def _assert_leg(result: dict, *, leg: str, expected_rw: float, why: str) -> None:
    """Assert one leg's weight, its money carrier, and its negative space.

    Absence — not wrongness — is this project's dominant production-escape
    class, so the value assertion is bracketed by the checks that make it
    meaningful: a positive EAD (otherwise every RWA claim is vacuous), a
    non-null weight (a ``when/then`` whose predicate goes indeterminate falls
    to ``otherwise``, and a chain with no ``otherwise`` yields null), a
    non-null RWA, and the ``rwa == ead x rw`` identity that binds the weight
    to the money.
    """
    expected_rwa = EAD_F * expected_rw

    # EAD integrity first — a zero-EAD row passes every RWA assertion below.
    assert result["ead_final"] == pytest.approx(EAD_F, abs=1e-9), (
        f"P1.314 leg {leg}: ead_final should be {EAD_F:,.2f}, got {result['ead_final']}. "
        f"A zero/short EAD makes the risk-weight and RWA assertions vacuous."
    )

    assert result["risk_weight"] is not None, (
        f"P1.314 leg {leg}: risk_weight is NULL. The override chain's predicate "
        f"went indeterminate (a null-propagating comparison against a null "
        f"funding currency is the expected cause). {why}"
    )
    assert result["risk_weight"] == pytest.approx(expected_rw, abs=1e-9), (
        f"P1.314 leg {leg}: risk_weight should be {expected_rw:.2f}. "
        f"Got {result['risk_weight']:.4f}. {why}"
    )

    assert result["rwa"] is not None, f"P1.314 leg {leg}: rwa_post_factor is NULL."
    assert result["rwa"] == pytest.approx(expected_rwa, abs=1e-9), (
        f"P1.314 leg {leg}: rwa_post_factor should be {expected_rwa:,.2f} "
        f"(= {EAD_F:,.2f} x {expected_rw:.2f}). Got {result['rwa']:,.4f}."
    )
    assert result["rwa"] == pytest.approx(result["ead_final"] * result["risk_weight"], abs=1e-9), (
        f"P1.314 leg {leg}: rwa_post_factor must equal ead_final x risk_weight; "
        f"got {result['rwa']} against {result['ead_final']} x {result['risk_weight']}."
    )

    # The explanation carrier must be populated and must never be the
    # "I do not know" name — an UNKNOWN_FALLBACK here would mean the
    # domesticity predicate itself became indeterminate.
    reason = result["sa_risk_weight_branch_reason"]
    assert reason is not None, f"P1.314 leg {leg}: sa_risk_weight_branch_reason is NULL."
    assert reason != UNKNOWN_FALLBACK, (
        f"P1.314 leg {leg}: sa_risk_weight_branch_reason is {UNKNOWN_FALLBACK} — the "
        f"Art. 121(6) domesticity test went indeterminate on this row."
    )


# =============================================================================
# PACK ANCHOR — the scenario's scalars, read back from the rulepack
# =============================================================================


def test_p1_314_scenario_scalars_match_the_rulepack() -> None:
    """Every expected weight in this module is the pack value it claims to be.

    The legs assert absolute literals so that a movement cannot hide behind a
    relative comparison. This test is what keeps those literals honest: if a
    pack entry moves, THIS reddens, rather than the scenario silently
    re-anchoring itself to whatever the engine now returns.
    """
    # Arrange / Act — read the pack-binding shims.
    # Assert
    assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS3] == Decimal(str(RW_CGCB_CQS3))
    assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS6] == Decimal(str(RW_CGCB_CQS6))
    assert RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS.CQS3] == Decimal(str(RW_RGLA_SOV_DERIVED_CQS3))
    assert Decimal(str(RW_RGLA_DOMESTIC)) == RGLA_DOMESTIC_CURRENCY_RW
    assert Decimal(str(RW_RGLA_DEVOLVED)) == RGLA_UK_DEVOLVED_RW
    assert B31_SCRA_RISK_WEIGHTS["A"] == Decimal(str(RW_SCRA_A))
    assert Decimal(str(RW_INSTITUTION_SHORT_TERM)) == INSTITUTION_SHORT_TERM_UNRATED_RW_CRR


# =============================================================================
# ART. 114(4) — UK CGCB, "denominated and funded in sterling"
# =============================================================================


class TestP1314Art1144UKCentralGovernment:
    """CRR / PS1/26 Art. 114(4): the UK sterling 0% needs BOTH limbs."""

    def test_p1_314_leg_a_uk_cgcb_funded_sterling_keeps_zero(
        self, sa_calculator, either_regime_config
    ):
        """Leg A — SURVIVOR. GB/GBP CQS 6, funded GBP: 0% relief legitimately applies.

        Green before and after by design. Without it the fix is
        indistinguishable from deleting the Art. 114(4) branch outright.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=CGCB,
            config=either_regime_config,
            cqs=6,
            country_code="GB",
            currency="GBP",
            funding_currency="GBP",
        )

        # Assert
        _assert_leg(
            result,
            leg="A",
            expected_rw=RW_CGCB_DOMESTIC,
            why="GB counterparty, sterling denomination AND sterling funding — "
            "Art. 114(4) is satisfied on both limbs and the 0% stands.",
        )

    def test_p1_314_leg_b_uk_cgcb_funded_usd_loses_zero(self, sa_calculator, either_regime_config):
        """Leg B — DISCRIMINATING. GB/GBP CQS 6, funded USD: 0% denied, 150% stands.

        PRE-FIX: 0.00 / 0.00 (the engine reads the denomination limb only).
        POST-FIX: 1.50 / 15,000,000.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=CGCB,
            config=either_regime_config,
            cqs=6,
            country_code="GB",
            currency="GBP",
            funding_currency="USD",
        )

        # Assert — no later CGCB branch matches, so the CQS 6 base join stands.
        _assert_leg(
            result,
            leg="B",
            expected_rw=RW_CGCB_CQS6,
            why="Sterling-denominated but USD-FUNDED, so Art. 114(4) is not "
            "satisfied and the exposure falls back to the Art. 114(2) Table 1 "
            "ladder at CQS 6. A 0.00 here means the funding limb is absent.",
        )

    def test_p1_314_leg_c_uk_cgcb_null_funding_is_permissive(
        self, sa_calculator, either_regime_config
    ):
        """Leg C — PERMISSIVE-NULL PIN. Column PRESENT and null: 0% still applies.

        Discriminates against BOTH strict variants, and nothing else does.
        Permissiveness lives in the ``fill_null`` INSIDE
        ``funding_currency_expr``, not in the comparison:

            permissive (correct)  -> "GBP".eq("GBP")            -> true  -> 0.00
            raw ``.eq()``         -> null.eq("GBP")             -> null  -> otherwise -> 1.50
            ``eq_missing``        -> null.eq_missing("GBP")     -> false -> otherwise -> 1.50

        ``pl.when(null)`` routes to ``otherwise``, so a null-propagating
        comparison is silently STRICT — the opposite of the intended policy.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=CGCB,
            config=either_regime_config,
            cqs=6,
            country_code="GB",
            currency="GBP",
            funding_currency_null=True,
        )

        # Assert
        _assert_leg(
            result,
            leg="C",
            expected_rw=RW_CGCB_DOMESTIC,
            why="A null funding currency is PERMISSIVE — it falls back to the "
            "GBP denomination, which matches, so the 0% stands. A 1.50 here "
            "means the comparison is null-propagating (or eq_missing) and the "
            "convention has silently inverted to strict.",
        )


# =============================================================================
# ART. 114(7) — third-country / EU CGCB, "denominated and funded in the
# domestic currency"
# =============================================================================


class TestP1314Art1147EUCentralGovernment:
    """CRR Art. 114(7), which survives unchanged under PS1/26 Art. 114(1)(b)."""

    def test_p1_314_leg_f_eu_cgcb_funded_usd_loses_zero(self, sa_calculator, either_regime_config):
        """Leg F — DISCRIMINATING (EU limb). DE/EUR CQS 6, funded USD: 150%.

        The EU disjunct is a separate expression from the UK one
        (``build_eu_domestic_currency_expr``), so a fix applied to only
        ``is_uk_domestic`` passes legs A-C and fails here.

        PRE-FIX: 0.00 / 0.00. POST-FIX: 1.50 / 15,000,000.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=CGCB,
            config=either_regime_config,
            cqs=6,
            country_code="DE",
            currency="EUR",
            funding_currency="USD",
        )

        # Assert
        _assert_leg(
            result,
            leg="F",
            expected_rw=RW_CGCB_CQS6,
            why="DE/EUR passes the denomination limb (eu_country_domestic_currency"
            "['DE'] == 'EUR') but is USD-FUNDED, so Art. 114(7) relief is denied "
            "and Table 1 CQS 6 stands.",
        )

    def test_p1_314_leg_f2_eu_cgcb_funded_eur_keeps_zero(self, sa_calculator, either_regime_config):
        """Leg F2 — SURVIVOR (EU limb). DE/EUR CQS 6, funded EUR: 0% stands.

        Green before and after by design: the two-leg "one moves, one stays"
        pattern applied to the EU disjunct as well as the UK one, so the fix
        cannot be confused with removing the Art. 114(7) branch.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=CGCB,
            config=either_regime_config,
            cqs=6,
            country_code="DE",
            currency="EUR",
            funding_currency="EUR",
        )

        # Assert
        _assert_leg(
            result,
            leg="F2",
            expected_rw=RW_CGCB_DOMESTIC,
            why="DE sovereign denominated AND funded in EUR — Art. 114(7) is "
            "satisfied on both limbs.",
        )


# =============================================================================
# ART. 115(5) — UK RGLA flat 20%, "denominated and funded in sterling"
# =============================================================================


class TestP1314Art1155UKLocalAuthority:
    """The Art. 115(5) flat 20% is UK/GBP-scoped and needs the funding limb."""

    def test_p1_314_leg_d_uk_local_authority_funded_sterling_keeps_20pct(
        self, sa_calculator, either_regime_config
    ):
        """Leg D — SURVIVOR. GB local authority, GBP, funded GBP: 20% stands."""
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=RGLA,
            config=either_regime_config,
            country_code="GB",
            currency="GBP",
            funding_currency="GBP",
            entity_type="rgla_institution",
            sovereign_cqs=3,
        )

        # Assert
        _assert_leg(
            result,
            leg="D",
            expected_rw=RW_RGLA_DOMESTIC,
            why="UK RGLA denominated AND funded in sterling — Art. 115(5) flat "
            "20% legitimately applies.",
        )

    def test_p1_314_leg_e_uk_local_authority_funded_usd_falls_to_table_1a(
        self, sa_calculator, either_regime_config
    ):
        """Leg E — DISCRIMINATING. GB local authority, GBP, funded USD: 100%.

        PRE-FIX: 0.20 / 2,000,000. POST-FIX: 1.00 / 10,000,000 — a 5x move.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=RGLA,
            config=either_regime_config,
            country_code="GB",
            currency="GBP",
            funding_currency="USD",
            entity_type="rgla_institution",
            sovereign_cqs=3,
        )

        # Assert — Art. 115(5) denied, so the unrated RGLA falls to the
        # Art. 115(1)(a) Table 1A sovereign-derived ladder at CQS 3.
        _assert_leg(
            result,
            leg="E",
            expected_rw=RW_RGLA_SOV_DERIVED_CQS3,
            why="Sterling-denominated but USD-FUNDED, so the Art. 115(5) flat 20% "
            "is denied and Table 1A CQS 3 (100%) applies. A 0.20 here means the "
            "funding limb never reached the Art. 115(5) branch.",
        )

    def test_p1_314_leg_j_eu_local_authority_funded_domestic_stays_on_table_1a(
        self, sa_calculator, either_regime_config
    ):
        """Leg J — ANTI-DEGENERATE SURVIVOR. DE/EUR RGLA funded EUR stays at 100%.

        **This leg is GREEN before and after the fix, deliberately. Do not
        "fix" it for failing to fail first** — its job is to redden a WRONG
        fix, not to move.

        What it catches: feeding the COMPOSITE ``is_domestic_currency_funded``
        (UK-or-EU) into the Art. 115(5) RGLA sites instead of the UK-only
        ``is_uk_domestic_funded``. Measured, that sends this row 1.00 -> 0.20,
        an 80% RWA REDUCTION — and **all of legs A-I pass under it, in both
        regimes**, because none of them is an EU RGLA.

        The mistake is the one the repo's own sibling code invites:
        ``eu_sovereign.build_domestic_cgcb_guarantor_expr`` returns the
        composite by design (Art. 235(3) guarantor relief genuinely spans both
        disjuncts), and it lives in the very file this item extends. Art.
        115(5) does not span both — ``risk_weights.py`` already records that
        the composite is "deliberately NOT reused here", and a non-UK RGLA in
        its own domestic currency must fall through to the Art. 115(1)
        ladders.

        The only other guard in the estate is
        ``test_rgla_risk_weights.py::test_eu_domestic_currency_rgla``, which is
        CRR-only and rated (CQS 4, Table 1B) — under Basel 3.1 the mistake is
        invisible to the entire suite, because ``currency="EUR"`` appears on
        exactly one RGLA row in all of ``tests/``.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=RGLA,
            config=either_regime_config,
            country_code="DE",
            currency="EUR",
            funding_currency="EUR",
            entity_type="rgla_institution",
            sovereign_cqs=3,
        )

        # Assert — Art. 115(5) reaches UK RGLAs only, whatever the funding
        # currency; an unrated DE RGLA prices off Table 1A at CQS 3.
        _assert_leg(
            result,
            leg="J",
            expected_rw=RW_RGLA_SOV_DERIVED_CQS3,
            why="Art. 115(5) is scoped to UK RGLAs denominated and funded in "
            "STERLING. A 0.20 here means the composite UK-or-EU domestic flag "
            "was wired into the RGLA sites, granting the flat 20% to EU RGLAs.",
        )


# =============================================================================
# ART. 115(2) — devolved administrations routed through Art. 114
# =============================================================================


class TestP1314Art1152DevolvedAdministration:
    """PS1/26 Art. 115(2) / CRR Art. 115(4): a second consumer of the UK flag.

    ``rgla.py::rgla_sovereign_rw_expr`` reads the UK-domestic flag independently
    of the Art. 115(5) branch, so legs D/E cannot cover it.
    """

    def test_p1_314_leg_g_devolved_funded_usd_uses_cgcb_ladder(
        self, sa_calculator, either_regime_config
    ):
        """Leg G — DISCRIMINATING. GB devolved govt, GBP, funded USD: 50%.

        PRE-FIX: 0.00 / 0.00 (the hardcoded devolved 0%).
        POST-FIX: 0.50 / 5,000,000 (Art. 114(2) Table 1 at sovereign CQS 3).
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=RGLA,
            config=either_regime_config,
            country_code="GB",
            currency="GBP",
            funding_currency="USD",
            entity_type="rgla_sovereign",
            sovereign_cqs=3,
        )

        # Assert
        _assert_leg(
            result,
            leg="G",
            expected_rw=RW_CGCB_CQS3,
            why="A devolved administration is treated as the UK central "
            "government (Art. 115(2)); sterling-denominated but USD-FUNDED "
            "fails Art. 114(4), so the Table 1 ladder prices it at CQS 3.",
        )

    def test_p1_314_leg_h_devolved_funded_sterling_keeps_zero(
        self, sa_calculator, either_regime_config
    ):
        """Leg H — SURVIVOR. GB devolved govt, GBP, funded GBP: 0% stands.

        Green before and after by design — the Art. 115(2) sibling of leg A.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=RGLA,
            config=either_regime_config,
            country_code="GB",
            currency="GBP",
            funding_currency="GBP",
            entity_type="rgla_sovereign",
            sovereign_cqs=3,
        )

        # Assert
        _assert_leg(
            result,
            leg="H",
            expected_rw=RW_RGLA_DEVOLVED,
            why="Denominated AND funded in sterling — the devolved 0% stands.",
        )


# =============================================================================
# LEAK DETECTORS — Art. 121(6) must keep the UNFUNDED expression
# =============================================================================


class TestP1314Art1216SovereignFloorMustNotAcquireFundingLimb:
    """``is_domestic_currency`` is dual-purpose; only ONE consumer takes the limb.

    ``risk_weights.py`` passes ``is_domestic_currency`` to
    ``apply_sovereign_floor_for_institutions``. Art. 121(6) / PS1/26 Art.
    121(6)(a) is denomination-only by its own text — "is not in the local
    currency of the jurisdiction of incorporation of the debtor institution" —
    so threading the FUNDED variant there would arm the floor on rows that are
    domestically denominated, overstating them.

    Both legs are GREEN before and after by design. Each asserts the value AND
    the ``sa_risk_weight_branch_reason``, so a leak that happened to land on
    the same number could still not pass: an armed floor names the row
    ``floor_bound`` where the correct answer is ``domestic_currency``.
    """

    def test_p1_314_leg_i_b31_scra_institution_floor_stays_denomination_only(
        self, sa_calculator, b31_config
    ):
        """Leg I — LEAK DETECTOR (Basel 3.1). GB/GBP SCRA A institution, funded USD.

        Correct: ``is_domestic_currency`` (unfunded) is True, so the row is
        not in FX, the floor does not apply, and the SCRA A 40% base stands.
        Leaked: the funded flag is False -> FX -> the floor binds at
        cgcb_risk_weights[CQS6] = 1.50, a **3.75x overstatement**.

        This leg had to be constructed rather than reused. The nearest existing
        guard, ``test_sovereign_floor_institutions.py::test_uk_institution_gbp_no_floor``,
        **cannot detect the leak**: it uses ``sovereign_cqs=1``, whose floor
        value is cgcb_risk_weights[CQS1] = 0.00 and can never bind above a 40%
        base, so it passes whether or not the funded flag leaks — the
        .claude/LESSONS.md C1 shape inside the file nominated as the leak
        detector. CQS 6 is what makes the floor able to bind.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=INSTITUTION,
            config=b31_config,
            country_code="GB",
            currency="GBP",
            funding_currency="USD",
            entity_type="institution",
            scra_grade="A",
            sovereign_cqs=6,
            local_currency=None,  # forces the ~is_domestic_currency fallback
        )

        # Assert — value ...
        _assert_leg(
            result,
            leg="I",
            expected_rw=RW_SCRA_A,
            why="Art. 121(6) is DENOMINATION-only. A GBP-denominated exposure to "
            "a GB institution is not in FX, whatever it is funded in, so the "
            "SCRA A base stands. A 1.50 means the funded flag leaked into "
            "apply_sovereign_floor_for_institutions.",
        )
        # ... and explanation, so the two cannot drift.
        assert result["sa_risk_weight_branch_reason"] == SovereignFloorReason.DOMESTIC_CURRENCY, (
            f"P1.314 leg I: the floor should name this row "
            f"'{SovereignFloorReason.DOMESTIC_CURRENCY.value}' (the trigger is absent). "
            f"Got '{result['sa_risk_weight_branch_reason']}' — "
            f"'{SovereignFloorReason.FLOOR_BOUND.value}' means the funded flag leaked."
        )

    def test_p1_314_leg_k_crr_short_term_institution_floor_stays_denomination_only(
        self, sa_calculator, crr_config
    ):
        """Leg K — LEAK DETECTOR (CRR). GB/GBP unrated institution, 0.1y, funded USD.

        The CRR side of the same leak. It needs the Art. 121(3) short-term
        flat 20% as its base: on the Art. 121(1) Table 5 ladder,
        ``institution_rw_sovereign_derived`` is pointwise >= the CGCB ladder,
        so the floor can never bind for a CRR institution priced off the same
        sovereign — the leak would be unobservable. At an ORIGINAL maturity of
        0.1y the base is 20%, below the CQS 3 CGCB floor of 50%.

        Correct: 0.20 with reason ``domestic_currency``.
        Leaked: 0.50 with reason ``floor_bound``.
        """
        # Arrange / Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=EAD,
            exposure_class=INSTITUTION,
            config=crr_config,
            country_code="GB",
            currency="GBP",
            funding_currency="USD",
            entity_type="institution",
            sovereign_cqs=3,
            local_currency=None,  # forces the ~is_domestic_currency fallback
            original_maturity_years=0.1,
        )

        # Assert — value ...
        _assert_leg(
            result,
            leg="K",
            expected_rw=RW_INSTITUTION_SHORT_TERM,
            why="Art. 121(3) pins an unrated short-dated institution exposure at "
            "20%; Art. 121(6) is denomination-only and this GBP exposure to a GB "
            "institution is not in FX. A 0.50 means the funded flag leaked and "
            "the CQS 3 sovereign floor armed.",
        )
        # ... and explanation.
        assert result["sa_risk_weight_branch_reason"] == SovereignFloorReason.DOMESTIC_CURRENCY, (
            f"P1.314 leg K: the floor should name this row "
            f"'{SovereignFloorReason.DOMESTIC_CURRENCY.value}'. Got "
            f"'{result['sa_risk_weight_branch_reason']}'."
        )
