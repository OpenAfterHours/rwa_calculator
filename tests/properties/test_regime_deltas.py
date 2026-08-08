"""
Cross-regime delta regression: one portfolio, run under CRR and Basel 3.1.

Pipeline position:
    curated portfolio -> PipelineOrchestrator (CRR @ 2025-12-31)
                      -> PipelineOrchestrator (Basel 3.1 @ 2027-06-01)
        -> the two aggregator-exit frames, compared leg-by-leg

What this proves:
The rest of the property suite runs each portfolio under one regime at a time and
never asserts what happens to a SINGLE exposure when the regime flips from CRR
(effective to 31 Dec 2026) to Basel 3.1 / PS1/26 (effective 1 Jan 2027). This
module pins that transition with a CURATED delta map: each leg is one obligor
whose CRR->B31 behaviour is known and derived from the cited rulepack, then
cross-checked against the authoritative PS1/26 PDF text (``docs/assets/
ps126app1.pdf``). A silent re-tiering of any SA risk-weight table shows up here as
a single changed leg rather than as a diffuse movement in a portfolio total.

The book is DELIBERATELY all-standardised, fully drawn, and unmitigated. That is
the load-bearing design choice: with no IRB leg there is no output floor (the
SA-equivalent RWA equals the actual RWA, so 72.5% of it can never bind — pinned in
``test_output_floor_is_inert_for_this_all_sa_book``), and with one standalone
counterparty per leg there is no lending-group aggregation and no retail
granularity limb. Every leg's RWA is therefore independent of every other, so the
portfolio delta is exactly the sum of the per-leg deltas (Bookkeeping identity
below) with no cross-leg term to explain away.

THE DELTA MAP (risk weights unless stated; RWA where a supporting factor makes the
weight ambiguous). Every value verified against the pack via ``resolve`` AND read
back out of the PS1/26 PDF:

    leg                     CRR RW     B31 RW    CRR article -> PS1/26 counterpart
    --------------------    -------    ------    ---------------------------------
    NO CHANGE
      US sovereign CQS2      20%        20%      Art.114(2) Table 1 -> Art.114(2) Table 1 (unchanged)
      US sovereign CQS4     100%       100%      Art.114(2) Table 1 -> Art.114(2) Table 1 (unchanged)
      corporate CQS1         20%        20%      Art.122   Table 6 -> Art.122(2) Table 6 (unchanged)
      corporate CQS4        100%       100%      Art.122   Table 6 -> Art.122(2) Table 6 (unchanged)
      corporate CQS5        150%       150%      Art.122   Table 6 -> Art.122(2) Table 6 (unchanged*)
      institution CQS1       20%        20%      Art.120   Table 3 -> Art.120(1) Table 3 (unchanged)
      institution CQS3       50%        50%      Art.120   Table 3 -> Art.120(1) Table 3 (unchanged)
      covered bond CQS1      10%        10%      Art.129   Table 6A-> Art.129(4) Table 7 (unchanged)
    CHANGED
      corporate CQS3        100%        75%      Art.122   Table 6 -> Art.122(2) Table 6
      institution CQS2       50%        30%      Art.120   Table 3 -> Art.120(1) Table 3
      SME rated CQS3     100%xSF        75%      Art.122 + Art.501 -> Art.122(2) Table 6, Art.501 removed
      SME unrated       100%xSF        85%      Art.122 + Art.501 -> Art.122(11), Art.501 removed

The two SME legs are stated on RWA, not on the base risk weight: under CRR the
base weight is 100% and the Art. 501 SME supporting factor (0.7619 for an
exposure at or below the EUR 2.5m threshold) is applied to the RWA, so a EUR-1m
leg carries 1,000,000 x 1.00 x 0.7619 = 761,900. PS1/26 removes Art. 501
entirely, so the B31 RWA is the plain 75% (rated, Table 6) or 85% (unrated,
Art. 122(11)) with no factor.

(*) The pack, this engine, and the PS1/26 PDF (Art. 122 Table 6:
20/50/75/100/150/150) all agree corporate CQS5 stays at 150%. The
``basel31`` skill's ``sa-risk-weights.md`` summary is wrong on this one row (it
prints 100%); the authoritative text wins, and this no-change leg is the guard
that keeps the summary bug from ever reaching the engine.

NOT COVERED — real CRR->B31 differences deliberately absent because the shared,
read-only ``ExposureSpec`` cannot express the input that would exercise them:
- Real-estate loan-splitting (CRR Art. 125/126 whole-loan preferential weight ->
  PS1/26 Art. 124A-124L 20%-secured / counterparty-RW-residual split) — the
  TOP-PRIORITY missing leg. ``ExposureSpec`` has no ``is_mortgage`` / property
  type / LTV, and its collateral is sealed as eligible FINANCIAL collateral
  (issuer sovereign), not a mortgage, so no leg can reach the RE class.
- Subordinated debt 150% (CRR Art. 122 -> PS1/26 Art. 128) — the loan builder
  hardcodes ``seniority="senior"``; there is no subordination field.
- Equity 250%/400% and the removal of the IRB equity approach (PS1/26 Art. 133)
  — equity has its own pipeline and fixtures; ``ExposureSpec`` emits only
  loans / contingents.
- SA currency-mismatch 1.5x multiplier (PS1/26 Art. 123B) — ``ExposureSpec``
  fixes the currency to GBP, so no mismatch can arise.
- Investment-grade unrated corporate 65% (PS1/26 Art. 122(6) / CRE20.44) — no
  ``is_investment_grade`` field, so the CRR-100% -> B31-65% change cannot be
  shown (a plain unrated corporate is 100% under both = no change).
- Unrated institution SCRA (CRR Art. 121 sovereign-derived -> PS1/26 Art. 121
  SCRA grades) — this IS a real change, but the B31 value rides on the default
  SCRA grade C (no grade data is supplied), a fixture-default artefact rather
  than a clean table read, so it is excluded rather than asserted fragilely.

References:
- PRA PS1/26 Art. 114 Table 1 (sovereign), Art. 120 Table 3 (institution ECRA),
  Art. 122 Table 6 + Art. 122(11) (corporate + unrated SME), Art. 129 Table 7
  (covered bond) — verbatim from docs/assets/ps126app1.pdf
- CRR Art. 114 / 120 / 122 / 129 / 501: the pre-2027 counterparts
- docs/plans/independent-validation-system.md (D4: cross-regime delta regression)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest

from tests.properties.portfolios import ExposureSpec, Portfolio, results_df, total_rwa

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Risk weights are clean decimals compiled to IEEE doubles, so equality is exact;
#: the tolerance only absorbs the last bit of float representation.
RW_TOL = 1e-9

#: RWA figures here are whole pounds (or 761,900.00), so half a penny is ample and
#: keeps a genuine re-tiering — the smallest of which is 11,900 — orders of
#: magnitude clear of the noise.
RWA_TOL = 0.01

#: The SME Art. 501 supporting factor for an exposure at or below the threshold,
#: as held in the CRR pack (``supporting_factors_values.sme_factor_under_threshold``).
#: Used only to document the arithmetic; the assertions are on the resulting RWA.
CRR_SME_SUPPORTING_FACTOR = 0.7619


# ---------------------------------------------------------------------------
# The curated leg map
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegCase:
    """One obligor with its CRR and Basel 3.1 expectations, both DERIVED.

    ``crr_rw`` / ``b31_rw`` are the base risk weights the ``risk_weight`` column
    carries (pre-supporting-factor). ``crr_rwa`` / ``b31_rwa`` are ``rwa_final``,
    which for an SME leg reflects the CRR supporting factor. ``kind`` partitions
    the map into the no-change and changed sets; ``crr_supporting_factor`` records
    whether CRR applies the Art. 501 SME relief (Basel 3.1 never does).
    """

    label: str
    spec: ExposureSpec
    exposure_class: str
    crr_rw: float
    b31_rw: float
    crr_rwa: float
    b31_rwa: float
    kind: str  # "no_change" | "change"
    crr_supporting_factor: bool
    citation: str


#: Each leg is one counterparty with one fully-drawn loan and no CRM, so
#: ``ead_final == drawn`` and ``rwa_final == ead x rw`` (except the SME legs, where
#: the CRR supporting factor scales the RWA). Order is load-bearing: the builder
#: assigns ``exposure_reference`` positionally as ``LN{index:03d}``.
LEG_CASES: tuple[LegCase, ...] = (
    # -- No-change set ------------------------------------------------------
    LegCase(
        label="us_sovereign_cqs2",
        # A NON-UK sovereign in GBP: Art. 114(4)'s 0% UK-sterling short-circuit
        # does not apply, so the Table 1 CQS mapping is what is under test.
        spec=ExposureSpec(
            entity_type="sovereign", drawn=4_000_000.0, external_cqs=2, country_code="US"
        ),
        exposure_class="central_govt_central_bank",
        crr_rw=0.20,
        b31_rw=0.20,
        crr_rwa=800_000.0,
        b31_rwa=800_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 114(2) Table 1 == PS1/26 Art. 114(2) Table 1 (sovereign table unchanged)",
    ),
    LegCase(
        label="us_sovereign_cqs4",
        spec=ExposureSpec(
            entity_type="sovereign", drawn=4_000_000.0, external_cqs=4, country_code="US"
        ),
        exposure_class="central_govt_central_bank",
        crr_rw=1.00,
        b31_rw=1.00,
        crr_rwa=4_000_000.0,
        b31_rwa=4_000_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 114(2) Table 1 == PS1/26 Art. 114(2) Table 1 (sovereign table unchanged)",
    ),
    LegCase(
        label="corporate_cqs1",
        spec=ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=1),
        exposure_class="corporate",
        crr_rw=0.20,
        b31_rw=0.20,
        crr_rwa=800_000.0,
        b31_rwa=800_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 122 Table 6 == PS1/26 Art. 122(2) Table 6 (CQS1 20%, unchanged)",
    ),
    LegCase(
        label="corporate_cqs4",
        spec=ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=4),
        exposure_class="corporate",
        crr_rw=1.00,
        b31_rw=1.00,
        crr_rwa=4_000_000.0,
        b31_rwa=4_000_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 122 Table 6 == PS1/26 Art. 122(2) Table 6 (CQS4 100%, unchanged)",
    ),
    LegCase(
        label="corporate_cqs5",
        spec=ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=5),
        exposure_class="corporate",
        crr_rw=1.50,
        b31_rw=1.50,
        crr_rwa=6_000_000.0,
        b31_rwa=6_000_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        # PDF-verified: Art. 122 Table 6 CQS5 = 150% (the skill summary's 100% is wrong).
        citation="CRR Art. 122 Table 6 == PS1/26 Art. 122(2) Table 6 (CQS5 150%, unchanged)",
    ),
    LegCase(
        label="institution_cqs1",
        spec=ExposureSpec(entity_type="institution", drawn=3_000_000.0, external_cqs=1),
        exposure_class="institution",
        crr_rw=0.20,
        b31_rw=0.20,
        crr_rwa=600_000.0,
        b31_rwa=600_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 120 Table 3 == PS1/26 Art. 120(1) Table 3 (CQS1 20%, unchanged)",
    ),
    LegCase(
        label="institution_cqs3",
        spec=ExposureSpec(entity_type="institution", drawn=3_000_000.0, external_cqs=3),
        exposure_class="institution",
        crr_rw=0.50,
        b31_rw=0.50,
        crr_rwa=1_500_000.0,
        b31_rwa=1_500_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 120 Table 3 == PS1/26 Art. 120(1) Table 3 (CQS3 50%, unchanged)",
    ),
    LegCase(
        label="covered_bond_cqs1",
        spec=ExposureSpec(entity_type="covered_bond", drawn=2_000_000.0, external_cqs=1),
        exposure_class="covered_bond",
        crr_rw=0.10,
        b31_rw=0.10,
        crr_rwa=200_000.0,
        b31_rwa=200_000.0,
        kind="no_change",
        crr_supporting_factor=False,
        citation="CRR Art. 129 Table 6A == PS1/26 Art. 129(4) Table 7 (CQS1 10%, unchanged)",
    ),
    # -- Changed set --------------------------------------------------------
    LegCase(
        label="corporate_cqs3",
        spec=ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=3),
        exposure_class="corporate",
        crr_rw=1.00,
        b31_rw=0.75,
        crr_rwa=4_000_000.0,
        b31_rwa=3_000_000.0,
        kind="change",
        crr_supporting_factor=False,
        citation="CRR Art. 122 Table 6 (CQS3 100%) -> PS1/26 Art. 122(2) Table 6 (CQS3 75%)",
    ),
    LegCase(
        label="institution_cqs2",
        spec=ExposureSpec(entity_type="institution", drawn=3_000_000.0, external_cqs=2),
        exposure_class="institution",
        crr_rw=0.50,
        b31_rw=0.30,
        crr_rwa=1_500_000.0,
        b31_rwa=900_000.0,
        kind="change",
        crr_supporting_factor=False,
        citation="CRR Art. 120 Table 3 (CQS2 50%) -> PS1/26 Art. 120(1) Table 3 (CQS2 30%)",
    ),
    LegCase(
        label="sme_rated_cqs3",
        # Revenue 20m < the SME turnover ceiling and exposure 1m < the EUR 2.5m
        # Art. 501 threshold, so CRR applies the 0.7619 factor to the 100% base.
        spec=ExposureSpec(
            entity_type="corporate", drawn=1_000_000.0, external_cqs=3, annual_revenue=20_000_000.0
        ),
        exposure_class="corporate_sme",
        crr_rw=1.00,  # base weight; the SF scales the RWA, not this column
        b31_rw=0.75,
        crr_rwa=761_900.0,  # 1,000,000 x 1.00 x 0.7619
        b31_rwa=750_000.0,  # 1,000,000 x 0.75, no factor
        kind="change",
        crr_supporting_factor=True,
        citation="CRR Art. 122 + Art. 501 SF (100%x0.7619) -> PS1/26 Art. 122(2) Table 6 75%, Art. 501 removed",
    ),
    LegCase(
        label="sme_unrated",
        spec=ExposureSpec(
            entity_type="corporate",
            drawn=1_000_000.0,
            external_cqs=None,
            annual_revenue=20_000_000.0,
        ),
        exposure_class="corporate_sme",
        crr_rw=1.00,
        b31_rw=0.85,
        crr_rwa=761_900.0,  # 1,000,000 x 1.00 x 0.7619
        b31_rwa=850_000.0,  # 1,000,000 x 0.85 (Art. 122(11)), no factor -> B31 is HIGHER here
        kind="change",
        crr_supporting_factor=True,
        citation="CRR Art. 122 + Art. 501 SF (100%x0.7619) -> PS1/26 Art. 122(11) 85%, Art. 501 removed",
    ),
)

#: The portfolio the whole module runs, and the per-index reference the builder
#: assigns each leg. ``run``/``results_df`` memoise on ``(PORTFOLIO, regime)``, so
#: the two pipeline runs are shared across every test below.
PORTFOLIO: Portfolio = tuple(case.spec for case in LEG_CASES)

_ALL: tuple[tuple[int, LegCase], ...] = tuple(enumerate(LEG_CASES))
_NO_CHANGE = [(i, c) for i, c in _ALL if c.kind == "no_change"]
_CHANGE = [(i, c) for i, c in _ALL if c.kind == "change"]
_SME = [(i, c) for i, c in _ALL if c.crr_supporting_factor]


# ---------------------------------------------------------------------------
# No-change set: identical risk weight under both regimes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("index", "leg"), _NO_CHANGE, ids=[c.label for _, c in _NO_CHANGE])
def test_no_change_leg_is_identical_across_regimes(index: int, leg: LegCase):
    """A leg whose SA table is unchanged carries the SAME risk weight and RWA.

    Both the measured CRR value and the measured B31 value must equal the derived
    weight, AND they must equal each other — so a re-tiering that moved the CRR
    row and the B31 row by the same amount could not sneak through.
    """
    # Arrange / Act
    crr = _leg_row("CRR", index)
    b31 = _leg_row("B31", index)

    # Assert — table is internally a no-change entry, then measurement confirms it
    assert leg.crr_rw == leg.b31_rw and leg.crr_rwa == leg.b31_rwa
    assert crr["risk_weight"] == pytest.approx(leg.crr_rw, abs=RW_TOL)
    assert b31["risk_weight"] == pytest.approx(leg.b31_rw, abs=RW_TOL)
    assert crr["risk_weight"] == pytest.approx(b31["risk_weight"], abs=RW_TOL)
    assert crr["rwa_final"] == pytest.approx(leg.crr_rwa, abs=RWA_TOL)
    assert b31["rwa_final"] == pytest.approx(leg.b31_rwa, abs=RWA_TOL)


# ---------------------------------------------------------------------------
# Changed set: exact expected value under BOTH regimes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("index", "leg"), _CHANGE, ids=[c.label for _, c in _CHANGE])
def test_changed_leg_matches_expected_value_in_both_regimes(index: int, leg: LegCase):
    """A leg with a known CRR->B31 difference hits the exact derived value each side.

    The change must be REAL, not merely directional: the measured RWA under the
    two regimes must differ by more than float noise, and each side must match its
    own derived figure (base weight and RWA).
    """
    # Arrange / Act
    crr = _leg_row("CRR", index)
    b31 = _leg_row("B31", index)

    # Assert — the table entry really is a change, then both sides land exactly
    assert leg.crr_rwa != pytest.approx(leg.b31_rwa, abs=RWA_TOL)
    assert crr["risk_weight"] == pytest.approx(leg.crr_rw, abs=RW_TOL)
    assert b31["risk_weight"] == pytest.approx(leg.b31_rw, abs=RW_TOL)
    assert crr["rwa_final"] == pytest.approx(leg.crr_rwa, abs=RWA_TOL)
    assert b31["rwa_final"] == pytest.approx(leg.b31_rwa, abs=RWA_TOL)
    assert crr["rwa_final"] != pytest.approx(b31["rwa_final"], abs=RWA_TOL)


# ---------------------------------------------------------------------------
# Supporting factor: applied under CRR for SMEs, never under Basel 3.1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("index", "leg"), _ALL, ids=[c.label for _, c in _ALL])
def test_supporting_factor_matches_regime(index: int, leg: LegCase):
    """CRR applies the Art. 501 SME factor iff the leg is an SME; B31 never does.

    The cross-regime statement of PS1/26 removing Art. 501: whatever a leg's SF
    status under CRR, its Basel 3.1 ``supporting_factor_applied`` is always False.
    """
    # Arrange / Act
    crr = _leg_row("CRR", index)
    b31 = _leg_row("B31", index)

    # Assert
    assert bool(crr["supporting_factor_applied"]) is leg.crr_supporting_factor
    assert bool(b31["supporting_factor_applied"]) is False


def test_crr_sme_supporting_factor_is_the_documented_multiplier():
    """The CRR SME RWA is exactly the 100% base scaled by the Art. 501 0.7619 factor.

    Pins the arithmetic the SME delta rests on, so a change to the pack's
    ``sme_factor_under_threshold`` moves this test rather than silently re-basing
    the delta map.
    """
    # Arrange / Act / Assert
    for index, leg in _SME:
        crr = _leg_row("CRR", index)
        base_rwa = crr["ead_final"] * leg.crr_rw
        assert crr["rwa_final"] == pytest.approx(
            base_rwa * CRR_SME_SUPPORTING_FACTOR, abs=RWA_TOL
        ), leg.label


# ---------------------------------------------------------------------------
# Classification: guard against a silent re-class hiding a matching weight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("index", "leg"), _ALL, ids=[c.label for _, c in _ALL])
def test_leg_is_classified_as_expected_in_both_regimes(index: int, leg: LegCase):
    """Each leg lands in its expected exposure class under both regimes.

    A leg that silently reclassifies (e.g. an SME falling back to plain corporate)
    could match a risk weight by coincidence; asserting the class as well as the
    weight closes that gap (LESSONS.md B6).
    """
    # Arrange / Act / Assert
    assert _leg_row("CRR", index)["exposure_class"] == leg.exposure_class
    assert _leg_row("B31", index)["exposure_class"] == leg.exposure_class


# ---------------------------------------------------------------------------
# Bookkeeping identity + why it holds (output floor inert)
# ---------------------------------------------------------------------------


def test_portfolio_delta_is_the_sum_of_the_curated_leg_deltas():
    """Total CRR->B31 RWA delta == sum of the per-leg deltas, with no cross term.

    The strong form: each regime's portfolio total equals the sum of that regime's
    per-leg DERIVED RWAs. If any leg were perturbed by a cross-leg effect (the
    output floor's pro-rata, a lending-group or granularity interaction) a total
    would miss its sum-of-legs and this would fail — which is why the identity is
    evidence of independence, not just of arithmetic.
    """
    # Arrange
    crr_total = total_rwa(PORTFOLIO, "CRR")
    b31_total = total_rwa(PORTFOLIO, "B31")

    # Act
    expected_crr = sum(leg.crr_rwa for _, leg in _ALL)
    expected_b31 = sum(leg.b31_rwa for _, leg in _ALL)
    expected_delta = expected_crr - expected_b31

    # Assert
    assert crr_total == pytest.approx(expected_crr, abs=RWA_TOL)
    assert b31_total == pytest.approx(expected_b31, abs=RWA_TOL)
    assert (crr_total - b31_total) == pytest.approx(expected_delta, abs=RWA_TOL)


def test_output_floor_is_inert_for_this_all_sa_book():
    """No leg is floored under Basel 3.1 — which is what makes the legs independent.

    An all-standardised book has SA-equivalent RWA equal to its actual RWA, so the
    72.5% output floor cannot bind; documenting that here is the justification for
    reading each leg's RWA in isolation above.
    """
    # Arrange / Act
    b31 = results_df(PORTFOLIO, "B31")

    # Assert
    assert float(b31["floor_impact_rwa"].fill_null(0.0).sum()) == pytest.approx(0.0, abs=RWA_TOL)
    assert not bool(b31["is_floor_binding"].fill_null(False).any())


# ---------------------------------------------------------------------------
# Anti-vacuity: every asserted leg is present and carries real exposure
# ---------------------------------------------------------------------------


def test_every_curated_leg_is_present_and_non_vacuous():
    """Each leg produces exactly one row with positive EAD under BOTH regimes.

    Guards the failure mode the whole suite is built against (LESSONS.md B4): a leg
    that silently drops to zero rows, or is zeroed to no exposure, would make its
    delta trivially satisfied. Both partitions must also be non-empty, so the
    module can never pass by having nothing to check.
    """
    # Arrange / Assert — the map itself exercises both classes and the SME path
    assert _NO_CHANGE, "no-change set is empty"
    assert _CHANGE, "changed set is empty"
    assert _SME, "supporting-factor set is empty"

    # Act / Assert — every leg is present with real exposure in both regimes
    for index, leg in _ALL:
        for regime in ("CRR", "B31"):
            row = _leg_row(regime, index)  # asserts exactly one row exists
            assert row["ead_final"] is not None and row["ead_final"] > 0.0, (
                f"{leg.label} carries no exposure under {regime}"
            )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _leg_row(regime: str, index: int) -> dict:
    """The single result row for the leg at ``index`` (asserts exactly one).

    The leg's ``exposure_reference`` is ``LN{index:03d}`` — assigned positionally
    by ``portfolios.build_bundle``. A missing or duplicated row fails here, which
    is the anti-vacuity backstop every parametrized test inherits.
    """
    ref = f"LN{index:03d}"
    rows = results_df(PORTFOLIO, regime).filter(pl.col("exposure_reference") == ref).to_dicts()
    assert len(rows) == 1, f"{ref} produced {len(rows)} rows under {regime}, expected exactly 1"
    return rows[0]
