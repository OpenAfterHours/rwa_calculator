"""
Conservation of the GROSS and COLLATERAL carriers against the SOURCE DATA.

Pipeline position:
    ExposureSpec literals -> build_bundle -> PipelineOrchestrator
        -> CRMProcessor -> RealEstateSplitter (fans one exposure into a secured
        leg plus a residual leg) -> sealed ledger
        -> COREPGenerator / Pillar3Generator

What this proves:
Every identity in this file has its EXPECTED side summed from the INPUT — the
``ExposureSpec`` literals a portfolio is written as, cross-checked against the raw
loader tables ``build_bundle`` seals. Nothing on the expected side is read back
out of the results frame, and nothing re-implements the carrier expression under
test. That is the whole point of the file and it is not decoration: an identity
whose two sides are both derived from the engine cannot fail when the engine is
wrong (`.claude/LESSONS.md` B3 — "if your test and your code were written from
the same sentence, the test proves nothing").

WHY THIS FILE EXISTS — the loan-splitter carrier-duplication defect:
    ``engine/stages/re_split/splitter.py`` runs AFTER the CRM stage and fans one
    real-estate exposure into a secured leg plus a residual leg. Its leg builders
    override roughly ten columns and INHERIT thirty-four numeric columns whole,
    ``drawn_amount`` and the collateral valuation columns among them. EAD is
    allocated across the legs correctly; the GROSS and COLLATERAL carriers are
    DUPLICATED once per leg. Measured on :data:`~tests.properties.corpus.RE_SPLIT`
    against the pre-fix engine: 5,000,000 of input drawn is published as
    9,000,000 of gross exposure, and 4,500,000 of pledged property is published
    as 7,500,000 of real-estate collateral under CRR.

    Every pre-existing gate is structurally blind to it:

    - ``test_conservation.py`` keys all five of its identities on
      ``reporting_ead`` / ``ead_final`` / ``rwa_final`` — the three quantities the
      splitter DOES allocate correctly. It has no identity on a gross or
      collateral carrier at all.
    - A footing or partition identity cannot see it. The duplication is uniform,
      so CR4's class rows still sum to CR4's total exactly and every
      internal-consistency rule passes.
    - The reporting goldens were captured from this engine's own output, so they
      froze the duplication as expected behaviour.

    Only an identity anchored OUTSIDE the engine can see it. That is this file.

EXPECTED RED PRE-FIX (measured against the unfixed engine; "both regimes" means
CRR and B31 alike):
    ``test_ledger_on_balance_sheet_gross_equals_the_input_drawn_amounts``
        RED on ``re_split`` (9,000,000 against 5,000,000, +4,000,000) and on
        ``re_split_with_financial`` (14,000,000 against 8,000,000, +6,000,000).
    ``test_cr4_on_balance_sheet_gross_equals_the_input_drawn_amounts``
    ``test_c07_gross_exposure_equals_the_input_on_and_off_balance_sheet_amounts``
        RED on ``re_split``, by the same +4,000,000.
    ``test_ledger_collateral_never_exceeds_the_pledged_market_value``
        RED on 11 of its 16 live cases. On the ``market_value`` basis it is red in
        BOTH regimes wherever a split portfolio pledges: ``re_split`` real estate
        7,500,000 against 4,500,000, ``re_split_with_financial`` real estate
        6,000,000 against 3,000,000 and financial 3,300,000 against 1,900,000. On
        the ``adjusted`` basis it is red in both regimes on
        ``re_split_with_financial`` but only under CRR on ``re_split`` — see below.
        The ``mitigated`` control (pledges, does not split) is GREEN on both bases
        in both regimes, which is what makes the reds attributable to the split.
    Every other parametrisation is GREEN pre-fix. None of these is xfailed: they
    are the proof-of-fix, and an xfail would let the fix land without evidence.

WHY THE ADJUSTED BASIS ALONE WAS NOT ENOUGH EVIDENCE:
    ``reporting_crm_lgd_real_estate`` reports the AIRB market value or, for every
    other leg, the Art. 223 adjusted value C_i. Pre-fix on ``re_split`` the Basel
    3.1 adjusted value happened to sum to exactly the 4,500,000 pledged, so the
    ``<=`` HELD there while CRR breached it by 3,000,000. The duplication was
    present in both regimes; only the basis masked it.

    That is why the inequality also runs on the RAW market-value carriers. A market
    value is an input fact — regime-invariant, because no regime's haircut, cap,
    eligibility gate or method-dependent basis switch may move it — so a duplication
    of it cannot slip under the bound in one regime and not the other. Measured
    pre-fix: ``collateral_re_market_value`` summed to 7,500,000 under CRR *and*
    Basel 3.1. The market-value arm is what makes the proof-of-fix independent of a
    regime coincidence, and it is the reason that arm exists.

    Recorded rather than papered over: the temptation when one regime passes and the
    other does not is to loosen the assertion until they agree, which would have
    deleted the only red evidence there was. The fix was to find a basis on which
    both regimes tell the truth, not to weaken the one that did.

HOW TIGHT EACH COLLATERAL CASE ACTUALLY IS — AND WHICH SIX ARE LOOSE:
    A green inequality proves the bound holds; it does not prove the bound is close
    enough to catch a re-introduction of the defect. So the published side of every
    live case was scaled by a factor against the FIXED engine to find the smallest
    over-statement each case would still detect. Three factors were run; the ceilings
    quoted below are arithmetic from the measured values, bracketed by those runs:

    ==========  ============  ===================================================
    factor      cases RED     survivors
    ==========  ============  ===================================================
    x1.01       10 of 16      4x ``mitigated-*-financial-*``,
                              ``re_split-B31-real_estate-adjusted``,
                              ``re_split_with_financial-B31-real_estate-adjusted``
    x1.34       14 of 16      the two ``B31-real_estate-adjusted`` cases
    x1.67       16 of 16      none
    ==========  ============  ===================================================

    **The ``market_value`` arm is what actually holds the bound.** All six of its
    split-portfolio cases are EXACTLY tight — published equals pledged to the penny
    — so x1.01 reddens every one of them, in BOTH regimes. Trust that arm for
    tightness. The ``adjusted`` arm is a coarser guard, for the two reasons below.

    **Finding 1 — the two ``B31-real_estate-adjusted`` cases survive x1.34 and fall
    only by x1.67 (ceiling ~x1.667).** Post-fix
    they sit ~40% below their bound (2,700,000 against 4,500,000 pledged on
    ``re_split``; 1,800,000 against 3,000,000 on ``re_split_with_financial``), because
    under Basel 3.1 the Art. 124F 55% cap and the Art. 223 adjusted-value basis both
    bite harder than they do under CRR. That headroom is a legitimate regulatory
    reduction, not slack in the test — but it means the ADJUSTED arm alone would not
    detect a re-introduced duplication below about x1.667 in Basel 3.1. The
    ``market_value`` arm covers exactly that hole, which is the second reason it
    exists. Note the challenge that surfaced this named only the ``re_split`` case;
    the ``re_split_with_financial`` case has the same mechanism and the same ceiling,
    and is recorded here because enumerating the family beats building to the members
    someone quoted (`LESSONS.md` C6).

    **Finding 2 — the ``mitigated`` CONTROL carries ~25% DEAD headroom, and that is
    the more serious of the two.** All four of its cases survive x1.01 and fall by
    x1.34 (ceiling ~x1.333). The mechanism
    is on the INPUT side, in ``_input_pledged``: ``mitigated`` pledges 6,000,000 of
    which 1,500,000 is written ``collateral_type="bond"``, a string
    ``VALID_COLLATERAL_TYPES`` accepts but ``COLLATERAL_TYPE_CATEGORY`` does not
    dispatch (see ``_UNCATEGORISED_INPUT_TYPES``). The expected side counts that
    pledge; the engine's category carriers drop it. So the bound is inflated by
    exactly the dropped 1,500,000 and both bases sit at 4,500,000, 75% of it.

    This matters because ``mitigated`` is the DECLARED CONTROL — it pledges but does
    not split, and its greenness is what makes the other portfolios' reds attributable
    to the splitter rather than to collateral handling generally. A control that is
    green partly because it is slack is a weak control, and saying so is the point of
    this block. It is a consequence of the separate ``bond``-dispatch plan item, not a
    defect in this test, and closing that item tightens the control automatically: the
    ``market_value`` arm would then read 6,000,000 against a 6,000,000 bound (exactly
    tight) and the ``adjusted`` arm would retain only the legitimate Art. 224 haircut
    on the bond.

    Neither finding is a licence to drop a case. Both remain parametrised with their
    assertions unchanged, because a case that cannot be reddened is a FINDING about the
    coverage, not a case to delete (`LESSONS.md` C7). What the reader needs is to know
    WHICH arm is load-bearing, and that is written above.

WHAT IS VACUOUS TODAY, AND WHY IT IS SKIPPED RATHER THAN PASSED:
    Of the four CRM collateral families only two are live on today's fixtures —
    ``financial`` (``mitigated``, ``re_split_with_financial``) and ``real_estate``
    (``re_split``, ``re_split_with_financial``). ``other_physical`` and
    ``receivables`` sum to 0.00 in both regimes on every portfolio and both bases,
    because no fixture pledges either yet. Every ``<=`` below therefore carries a
    two-sided guard: a family the portfolio never pledged is SKIPPED with the missing
    fixture named, and a family it DID pledge whose carrier still sums to 0.00 FAILS
    as a dead carrier. Neither may quietly pass over an empty sum.

    Pillar 3 CR7-A is deliberately absent. Its four funded-collateral columns
    (b/d/e/f) are RATIOS over ``collateral_financial_value`` /
    ``collateral_re_value`` / ``collateral_receivables_value`` /
    ``collateral_other_physical_value``, and all four read 0.0 on every corpus
    portfolio in both regimes — including ``mitigated``, whose A-IRB leg carries a
    3,000,000 cash pledge that C 08.01 col 0180 discloses in full. A cash pledge
    populates ``collateral_cash_value``, which CR7-A's numerator does not read.
    An assertion here could only pass vacuously, so none is written; the gap is a
    recorded finding for CR7-A rather than something to paper over.

ROW-AXIS DISCIPLINE:
    Template frames carry parent rows and their own breakdown rows, so summing a
    whole frame double counts by construction (`LESSONS.md` E4). Measured: C 08.01
    col 0180 on the ``mitigated`` portfolio is 3,000,000, and rows 0010, 0020 and
    0070 each carry it — a naive whole-frame sum reads 9,000,000, exactly 3.0x.
    Every template read below therefore takes the published TOTAL row and nothing
    else: CR4 row "17", C 07.00 row "0010", C 08.01 row "0070" ("Exposures
    assigned to obligor grades or pools: Total").

References:
- CRR Art. 111 / PS1/26 Art. 111: SA exposure value, gross of conversion factors
- CRR Art. 166: IRB exposure value
- CRR Art. 125 / 126, PS1/26 Art. 124F / 124H: real-estate loan-splitting
- CRR Art. 197 / 199: eligible financial and non-financial collateral
- COREP Annex II, C 07.00 col 0010 / C 08.01 cols 0180-0210
- Pillar 3 CR4 cols a and b: on- and off-balance-sheet exposures before CCF/CRM
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.data.schemas import COLLATERAL_TYPE_CATEGORY, VALID_COLLATERAL_TYPES
from rwa_calc.reporting.kernel.columns import ensure_gross_side_carriers
from tests.properties.corpus import CORPUS, RE_SPLIT, RE_SPLIT_WITH_FINANCIAL
from tests.properties.portfolios import (
    ExposureSpec,
    build_bundle,
    corep_bundle,
    pillar3_bundle,
    results_df,
)

#: Absolute money tolerance, matching the sibling property files. Template cells
#: are group-by/sum aggregates and Polars Float64 group-by sums are not
#: process-deterministic in the last ulps. Deliberately ABSOLUTE rather than
#: relative: every recorded stranding incident here was millions, and a relative
#: tolerance grows with the portfolio exactly where the defect does.
MONEY_TOLERANCE = 0.005

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

#: Every corpus portfolio plus the two splitter reproducers. Both are imported by
#: name because both are deliberately absent from ``CORPUS`` — they change the row
#: count, which would redden seven unrelated property suites at once.
#: ``re_split_with_financial`` is the two-route shape (immovable property through
#: the Art. 125/126 split AND financial collateral through Art. 197/223 on the same
#: exposure), so it is the only portfolio on which BOTH collateral families are live
#: at once and the only one where a split leg carries a non-zero adjusted value.
SOURCE_PORTFOLIOS: dict[str, tuple[ExposureSpec, ...]] = {
    **CORPUS,
    "re_split": RE_SPLIT,
    "re_split_with_financial": RE_SPLIT_WITH_FINANCIAL,
}

#: Portfolios read at TEMPLATE level. CR4 and C 07.00 are standardised-only
#: surfaces, so their in-scope population equals the whole input only for a
#: portfolio every leg of which routes standardised — which each test asserts as
#: a precondition rather than assuming. ``irb_mix`` and ``mitigated`` are excluded
#: for that reason (both carry IRB legs), not because they are uninteresting;
#: they are still covered by the ledger-level identities, which are
#: approach-agnostic. ``defaulted`` and ``edge_cases`` are standardised-only but
#: add no gross-carrier shape the other three lack, and a COREP bundle costs an
#: order of magnitude more than a run.
TEMPLATE_PORTFOLIOS: tuple[str, ...] = ("sa_broad", "off_balance_sheet", "re_split")

#: Portfolios that pledge collateral at all. A portfolio that pledges nothing is
#: not a MISSING fixture for a family — it is simply not a collateral portfolio,
#: and skipping it once per family would bury the skips that DO name a real gap
#: under forty that name nothing. ``mitigated`` is the CONTROL: it pledges but does
#: not split, so it must stay green under every basis while the two split
#: portfolios go red.
COLLATERAL_PORTFOLIOS: tuple[str, ...] = ("mitigated", "re_split", "re_split_with_financial")

#: Portfolios read for the PUBLISHED form of the collateral inequality. Only one,
#: and the reason is the finding recorded in the module docstring: C 08.01/02 and
#: CR7-A are IRB-only surfaces while real-estate loan-splitting is a standardised
#: mechanism, so ``re_split`` — the portfolio whose collateral IS duplicated —
#: emits no C 08.01 sheet at all, and ``irb_mix`` reaches the sheets but pledges
#: nothing. ``mitigated`` is the only portfolio that is both IRB and collateralised.
C08_COLLATERAL_PORTFOLIOS: tuple[str, ...] = ("mitigated",)

#: The four CRM collateral families x the two BASES the ledger carries each family
#: on, family -> the carrier columns that basis sums (a tuple, because one family's
#: amount can live in more than one column — see the cash fold below).
#:
#: ``adjusted`` is the reported basis: ``reporting_crm_lgd_*``, what COREP
#: C 08.01/02 cols 0180-0210 publish. It is METHOD-DEPENDENT — an A-IRB leg reports
#: the estimated market value, every other leg the Art. 223 adjusted value C_i —
#: and it is REGIME-DEPENDENT, because the haircuts, caps and split points differ
#: between CRR and Basel 3.1.
#:
#: ``market_value`` is the raw valuation carrier, and it exists as a separate arm of
#: the identity for one reason: **market value is regime-invariant.** It is an input
#: fact. No regime's haircut, cap, eligibility gate or basis switch may move it, so
#: an over-statement of it cannot be masked by a regime whose adjusted basis happens
#: to land under the bound. That is not hypothetical — it is exactly what happened
#: pre-fix, where the duplicated real-estate value breached the adjusted bound under
#: CRR and slipped under it by coincidence under Basel 3.1. On this arm the same
#: defect is RED IN BOTH REGIMES, so the evidence does not rest on a coincidence.
#:
#: The ``financial`` market-value entry folds the CASH carrier in, mirroring the
#: aggregator's own documented fold for ``reporting_crm_lgd_financial``
#: (``_crm_lgd_carriers``: cash on deposit is Art. 197(1)(a) eligible financial
#: collateral). Without the fold this arm would read 0.00 for a cash pledge while the
#: input side counted it, which is a carrier-ladder mismatch rather than a defect —
#: `LESSONS.md` B1 in the test rather than in production.
LEDGER_COLLATERAL_BASES: dict[str, dict[str, tuple[str, ...]]] = {
    "adjusted": {
        "financial": ("reporting_crm_lgd_financial",),
        "real_estate": ("reporting_crm_lgd_real_estate",),
        "other_physical": ("reporting_crm_lgd_other_physical",),
        "receivables": ("reporting_crm_lgd_receivables",),
    },
    "market_value": {
        "financial": ("collateral_financial_market_value", "collateral_cash_market_value"),
        "real_estate": ("collateral_re_market_value",),
        "other_physical": ("collateral_other_physical_market_value",),
        "receivables": ("collateral_receivables_market_value",),
    },
}

#: The families, in publication order. Taken from one basis and asserted identical
#: across both by :func:`test_both_collateral_bases_cover_the_same_families`, so a
#: family added to one map and forgotten in the other cannot silently go untested.
COLLATERAL_FAMILIES: tuple[str, ...] = tuple(LEDGER_COLLATERAL_BASES["adjusted"])

#: The same four families as published C 08.01/02 columns.
C08_COLLATERAL_COLUMNS: dict[str, str] = {
    "financial": "0180",
    "real_estate": "0190",
    "other_physical": "0200",
    "receivables": "0210",
}

#: Input-contract ``collateral_type`` strings that ``COLLATERAL_TYPE_CATEGORY`` does
#: NOT categorise, mapped to the family the input plainly intends.
#:
#: The input side of these inequalities buckets a pledge by family, and it reads
#: ``data/schemas.COLLATERAL_TYPE_CATEGORY`` to do it — the canonical, single-source
#: ``collateral_type`` -> CRM category mapping — rather than a hand-written string
#: set that could bucket nothing and quietly make the expected side 0.00
#: (`LESSONS.md` B2/B3). This dict is the recorded GAP in that mapping, and it has
#: exactly one entry: ``bond`` is in ``VALID_COLLATERAL_TYPES``, so the loader accepts
#: it, but it is absent from ``FINANCIAL_COLLATERAL_TYPES`` (the CRM dispatcher
#: recognises ``government_bond`` / ``corporate_bond``), so a pledge written as
#: ``bond`` is accepted and then categorised "other", reporting in no CRM column at
#: all. The ``mitigated`` portfolio's 1,500,000 bond pledge is exactly that case, and
#: it is why its financial carrier reads 4,500,000 against 6,000,000 pledged: the
#: slack is a DROPPED PLEDGE, not a haircut.
#:
#: :func:`test_the_uncategorised_input_types_are_exactly_the_recorded_gap` pins this
#: set, so closing the gap in ``schemas.py`` reddens this file and tells the fixer to
#: delete the entry rather than leaving a stale workaround behind.
_UNCATEGORISED_INPUT_TYPES: dict[str, str] = {"bond": "financial"}

#: What a vacuous collateral case is actually waiting for, named per family so a
#: skip line points at the work rather than at "some fixture". A conservation
#: identity that passes because both sides are zero is worse than no test — it
#: manufactures confidence — so every skip below has to say what would make it
#: live.
_MISSING_FIXTURE: dict[str, str] = {
    "financial": "an Art. 197 financial pledge on this portfolio",
    "real_estate": "an Art. 125/126 property pledge on this portfolio",
    "other_physical": "the outstanding Art. 199(8) other-physical-collateral fixture",
    "receivables": "the outstanding Art. 199(5) receivables-collateral fixture",
}

#: CR4's footing row and the two gross columns it publishes.
CR4_TOTAL_ROW = "17"
CR4_ON_BS_GROSS_COLUMN = "a"
CR4_OFF_BS_GROSS_COLUMN = "b"

#: C 07.00's total row and its gross-exposure column. The cell is a SafeSum over
#: ``reporting_gross_on_bs``, ``reporting_gross_off_bs`` and ``c07_ccr_gross``, so
#: the identity it satisfies is the COMBINED on-plus-off input amount. No corpus
#: portfolio carries a CCR leg, so the third term contributes nothing.
C07_TOTAL_ROW = "0010"
C07_GROSS_COLUMN = "0010"

#: C 08.01's published total row, "Exposures assigned to obligor grades or pools:
#: Total". Its PD-band rows are hierarchical parents of one another, so this is
#: the only row that may be read (see the module docstring).
C08_01_TOTAL_ROW = "0070"

_ALL_CASES = [(name, regime) for name in SOURCE_PORTFOLIOS for regime in REGIME_NAMES]
_TEMPLATE_CASES = [(name, regime) for name in TEMPLATE_PORTFOLIOS for regime in REGIME_NAMES]
_COLLATERAL_CASES = [
    (name, regime, family, basis)
    for name in COLLATERAL_PORTFOLIOS
    for regime in REGIME_NAMES
    for family in COLLATERAL_FAMILIES
    for basis in LEDGER_COLLATERAL_BASES
]
_C08_CASES = [
    (name, regime, family)
    for name in C08_COLLATERAL_PORTFOLIOS
    for regime in REGIME_NAMES
    for family in C08_COLLATERAL_COLUMNS
]


# ---------------------------------------------------------------------------
# The input side is the input side
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("portfolio_name", list(SOURCE_PORTFOLIOS))
def test_the_expected_side_matches_the_raw_input_tables(portfolio_name: str):
    """The ``ExposureSpec`` sums equal the loader tables ``build_bundle`` seals.

    Every identity below states its expected side as a sum over the spec literals,
    because a literal is the furthest thing from the code under test. That is only
    sound while the builder puts exactly those literals into the raw tables — if
    ``ExposureSpec`` grew a second drawn-money field, or the builder started
    emitting a second loan row per spec, the literal sums would quietly stop
    describing the input and every identity below would be measuring the wrong
    thing while staying green.

    This pins the two together, so the spec-literal shortcut is checked rather
    than assumed. It reads the RAW input frames, never the results. The pledged leg
    sums over EVERY family key the specs produce rather than over the four families
    the inequalities test, so a pledge in a fifth category (a covered bond, a life
    policy) shows up as a divergence here instead of silently falling out.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    bundle = build_bundle(portfolio)

    # Act
    raw = {
        "on_balance_sheet": _sum_input_column(bundle.loans, "drawn_amount")
        + _sum_input_column(bundle.loans, "interest"),
        "nominal": _sum_input_column(bundle.contingents, "nominal_amount"),
        "pledged": _sum_input_column(bundle.collateral, "market_value"),
    }
    from_specs = {
        "on_balance_sheet": _input_on_balance_sheet(portfolio),
        "nominal": _input_off_balance_sheet(portfolio),
        "pledged": sum(_input_pledged_by_family(portfolio).values()),
    }

    # Assert
    divergent = {
        key: (from_specs[key], raw[key])
        for key in raw
        if abs(from_specs[key] - raw[key]) > MONEY_TOLERANCE
    }
    assert divergent == {}, (
        f"the spec-literal expected side no longer describes the raw input tables for "
        f"{portfolio_name} — {{key: (from_specs, raw_tables)}}: {divergent}"
    )


def test_the_uncategorised_input_types_are_exactly_the_recorded_gap():
    """The loader accepts exactly one ``collateral_type`` the CRM mapping drops.

    The input side buckets a pledge by reading ``COLLATERAL_TYPE_CATEGORY``, so it
    cannot bucket on an invented string and quietly make the expected side 0.00
    (`LESSONS.md` B2/B3). ``_UNCATEGORISED_INPUT_TYPES`` is the workaround for the
    one input-contract string that mapping does not cover, and a workaround with no
    expiry is how a fixed defect keeps being worked around for years.

    So the set is PINNED rather than merely used: if ``bond`` is added to
    ``FINANCIAL_COLLATERAL_TYPES``, this fails and names the entry to delete; if a
    second uncategorised string appears in ``VALID_COLLATERAL_TYPES``, this fails
    before it can silently fall out of an expected total.
    """
    # Arrange
    accepted = set(VALID_COLLATERAL_TYPES)

    # Act
    uncategorised = {value for value in accepted if value not in COLLATERAL_TYPE_CATEGORY}

    # Assert
    assert uncategorised == set(_UNCATEGORISED_INPUT_TYPES), (
        f"the loader accepts {sorted(uncategorised)} but COLLATERAL_TYPE_CATEGORY "
        f"categorises none of them, while this file records "
        f"{sorted(_UNCATEGORISED_INPUT_TYPES)}. If the gap was CLOSED in "
        f"data/schemas.py, delete the closed entry from _UNCATEGORISED_INPUT_TYPES; if a "
        f"NEW uncategorised type appeared, a pledge of it reports in no CRM column at all "
        f"(CRM021) and needs a family here before it can be bounded"
    )


def test_both_collateral_bases_cover_the_same_families():
    """The adjusted and market-value maps describe the same four families.

    The inequality is parametrised over (family x basis). A family present in one
    map and absent from the other would simply not be generated for the missing
    basis — no error, no skip, just a case that never runs. Absence is this
    project's dominant escape class (`LESSONS.md` B4), so the symmetry is asserted
    rather than eyeballed.
    """
    # Arrange
    families = {basis: set(carriers) for basis, carriers in LEDGER_COLLATERAL_BASES.items()}

    # Act
    asymmetric = {
        basis: sorted(present ^ set(COLLATERAL_FAMILIES)) for basis, present in families.items()
    }

    # Assert
    broken = {basis: diff for basis, diff in asymmetric.items() if diff}
    assert broken == {}, (
        f"a collateral family is covered by one basis and not the other, so its "
        f"parametrisation silently never runs for the missing basis: {broken}"
    )


# ---------------------------------------------------------------------------
# A1 / A2 — gross exposure, at the ledger seal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _ALL_CASES)
def test_ledger_on_balance_sheet_gross_equals_the_input_drawn_amounts(
    portfolio_name: str, regime: str
):
    """The sealed on-balance-sheet gross carrier totals the drawn money lent.

    ``reporting_gross_on_bs`` is the pre-CCF, pre-CRM gross exposure every
    on-balance-sheet template cell reads (CRR Art. 111 SA / Art. 166 IRB). It is a
    RESTATEMENT of the book, not a computation over it: no stage may create or
    destroy drawn principal, so the portfolio total is fixed by the input and no
    amount of splitting, substitution or reclassification may change it.

    Approach-agnostic on purpose — the carrier is sealed for every credit leg, so
    this identity holds across the whole corpus including the IRB portfolios, and
    a defect in a stage that fans out rows shows here first.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    expected = _input_on_balance_sheet(portfolio)

    # Act
    published = _ledger_sum(results_df(portfolio, regime), "reporting_gross_on_bs")

    # Assert
    residual = published - expected
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"the ledger publishes {published:,.2f} of on-balance-sheet gross exposure under "
        f"{regime} but the input lent {expected:,.2f} (residual {residual:,.2f})"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _ALL_CASES)
def test_ledger_off_balance_sheet_gross_equals_the_input_nominal_amounts(
    portfolio_name: str, regime: str
):
    """The sealed off-balance-sheet gross carrier totals the nominals committed.

    The off-side twin of the identity above (CRR Annex I / PS1/26 Table A1): a
    contingent's nominal, a facility's undrawn counted exactly once, and a loan's
    true zero. Same argument — an off-balance-sheet commitment is an input fact.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    expected = _input_off_balance_sheet(portfolio)
    if expected <= 0.0:
        pytest.skip(
            f"{portfolio_name} has no off-balance-sheet leg, so this identity would compare "
            f"0.00 against 0.00 and could not fail. The live subject is the "
            f"'off_balance_sheet' corpus portfolio, which carries one nominal per CRR "
            f"Annex I conversion-factor bucket."
        )

    # Act
    published = _ledger_sum(results_df(portfolio, regime), "reporting_gross_off_bs")

    # Assert
    residual = published - expected
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"the ledger publishes {published:,.2f} of off-balance-sheet gross exposure under "
        f"{regime} but the input committed {expected:,.2f} (residual {residual:,.2f})"
    )


# ---------------------------------------------------------------------------
# A1 / A2 — gross exposure, on the published templates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_cr4_on_balance_sheet_gross_equals_the_input_drawn_amounts(
    portfolio_name: str, regime: str
):
    """Pillar 3 CR4 column a, on the Total row, is the drawn money lent.

    CR4 col a is "on-balance-sheet exposures" before conversion factors and before
    credit risk mitigation, so for a wholly standardised book it is the input
    drawn amount and nothing else. Asserted on the published TOTAL row, never on a
    sum of class rows — a class row that no leg reaches would make a row sum agree
    with a wrong total (`LESSONS.md` B6).
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    expected = _input_on_balance_sheet(portfolio)
    _require_wholly_standardised(portfolio, regime, portfolio_name)

    # Act
    cr4 = pillar3_bundle(portfolio, regime).cr4
    assert cr4 is not None, "CR4 was not emitted at all"
    published = _template_cell(cr4, CR4_TOTAL_ROW, CR4_ON_BS_GROSS_COLUMN)

    # Assert
    residual = published - expected
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"CR4 row {CR4_TOTAL_ROW} col {CR4_ON_BS_GROSS_COLUMN} discloses {published:,.2f} of "
        f"on-balance-sheet gross exposure under {regime} but the input lent {expected:,.2f} "
        f"(residual {residual:,.2f})"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_cr4_off_balance_sheet_gross_equals_the_input_nominal_amounts(
    portfolio_name: str, regime: str
):
    """Pillar 3 CR4 column b, on the Total row, is the nominal committed."""
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    expected = _input_off_balance_sheet(portfolio)
    if expected <= 0.0:
        pytest.skip(
            f"{portfolio_name} has no off-balance-sheet leg, so CR4 col "
            f"{CR4_OFF_BS_GROSS_COLUMN} would be compared 0.00 against 0.00. The live "
            f"subject is the 'off_balance_sheet' corpus portfolio."
        )
    _require_wholly_standardised(portfolio, regime, portfolio_name)

    # Act
    cr4 = pillar3_bundle(portfolio, regime).cr4
    assert cr4 is not None, "CR4 was not emitted at all"
    published = _template_cell(cr4, CR4_TOTAL_ROW, CR4_OFF_BS_GROSS_COLUMN)

    # Assert
    residual = published - expected
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"CR4 row {CR4_TOTAL_ROW} col {CR4_OFF_BS_GROSS_COLUMN} discloses {published:,.2f} of "
        f"off-balance-sheet gross exposure under {regime} but the input committed "
        f"{expected:,.2f} (residual {residual:,.2f})"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_c07_gross_exposure_equals_the_input_on_and_off_balance_sheet_amounts(
    portfolio_name: str, regime: str
):
    """COREP C 07.00 column 0010, summed over its sheets, is the whole input book.

    An INDEPENDENT surface from CR4 reading the SAME two sealed carriers: C 07.00
    is published one sheet per Art. 112(1) class and its column 0010 is a SafeSum
    of the on-side and off-side gross, so the union of its sheets' total rows is
    the input's combined on-plus-off amount. Asserting both surfaces is the point
    — a defect in one generator moves one of them, a defect in the shared carrier
    moves both, and the pair distinguishes those two stories.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    expected = _input_on_balance_sheet(portfolio) + _input_off_balance_sheet(portfolio)
    _require_wholly_standardised(portfolio, regime, portfolio_name)

    # Act
    sheets = corep_bundle(portfolio, regime).c07_00 or {}
    assert sheets, "C 07.00 emitted no sheet at all"
    published = sum(
        _template_cell(frame, C07_TOTAL_ROW, C07_GROSS_COLUMN) for frame in sheets.values()
    )

    # Assert
    residual = published - expected
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"C 07.00 row {C07_TOTAL_ROW} col {C07_GROSS_COLUMN} sums to {published:,.2f} over "
        f"{len(sheets)} sheets under {regime} but the input book is {expected:,.2f} "
        f"(residual {residual:,.2f})"
    )


# ---------------------------------------------------------------------------
# A3 / A4 — collateral never exceeds what was pledged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime", "family", "basis"), _COLLATERAL_CASES)
def test_ledger_collateral_never_exceeds_the_pledged_market_value(
    portfolio_name: str, regime: str, family: str, basis: str
):
    """A recognised collateral amount is bounded by the market value pledged.

    An INEQUALITY rather than an equality, and deliberately so: haircuts
    (Art. 223-224), the exposure-value cap and the eligibility gates
    (Art. 197 financial, Art. 199 non-financial) can only ever REDUCE a pledge's
    recognised amount. There is no mechanism in the regulation by which the
    recognised value of collateral exceeds its market value, so a breach is
    always a defect and never a modelling choice.

    Run over BOTH bases (see :data:`LEDGER_COLLATERAL_BASES`). The ``adjusted``
    basis is what the templates publish; the ``market_value`` basis is what makes
    the identity regime-proof, because a market value is an input fact that no
    regime's haircut, cap or basis switch may move. A duplication of it is therefore
    RED IN BOTH REGIMES, where the same duplication on the adjusted basis breached
    CRR and slipped under the bound by coincidence under Basel 3.1.

    Stated on the ledger carriers rather than on the templates because that is
    where it has a genuine red case. The template form is deferred: real-estate
    loan-splitting is a standardised-approach mechanism, C 08.01/02 and CR7-A are
    IRB-only surfaces, so the duplicated property value reaches no cell of theirs
    on the split path at all.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    pledged = _input_pledged(portfolio, family)
    carriers = LEDGER_COLLATERAL_BASES[basis][family]
    if pledged <= 0.0:
        pytest.skip(
            f"VACUOUS: {portfolio_name} pledges no {family} collateral, so the {basis} "
            f"inequality would compare 0.00 against 0.00 and could not fail. Missing "
            f"fixture: {_MISSING_FIXTURE[family]}."
        )

    # Act
    published = _ledger_sum(results_df(portfolio, regime), *carriers)

    # Assert
    assert published > 0.0, (
        f"{portfolio_name} pledges {pledged:,.2f} of {family} collateral but its {basis} "
        f"carriers {carriers} sum to 0.00 under {regime} — a dead carrier, which is "
        f"indistinguishable from an unmitigated book to every consumer of it"
    )
    assert published <= pledged + MONEY_TOLERANCE, (
        f"the {basis} carriers {carriers} recognise {published:,.2f} under {regime} "
        f"against {pledged:,.2f} of {family} collateral actually pledged (excess "
        f"{published - pledged:,.2f}); haircuts, caps and eligibility only ever reduce"
    )


@pytest.mark.parametrize(("portfolio_name", "regime", "family"), _C08_CASES)
def test_c08_crm_in_lgd_never_exceeds_the_pledged_market_value(
    portfolio_name: str, regime: str, family: str
):
    """COREP C 08.01's CRM-in-LGD block is bounded by the market value pledged.

    The published form of the inequality above (Annex II cols 0180/0190/0200/0210,
    "CRM techniques taken into account in LGD estimates"). Read on the TOTAL row
    0070 only — its PD-band rows are hierarchical parents of one another, so a
    whole-frame sum reads 3.0x the true figure on today's fixtures.

    The bound is the WHOLE portfolio's pledged amount while the template sees only
    its IRB subset, so the inequality is necessarily loose here. It is still worth
    stating: it is an upper bound no correct disclosure can breach, and it is the
    surface a supervisor reads.
    """
    # Arrange
    portfolio = SOURCE_PORTFOLIOS[portfolio_name]
    pledged = _input_pledged(portfolio, family)
    if pledged <= 0.0:
        pytest.skip(
            f"VACUOUS: {portfolio_name} pledges no {family} collateral, so C 08.01 col "
            f"{C08_COLLATERAL_COLUMNS[family]} would be compared 0.00 against 0.00. Missing "
            f"fixture: {_MISSING_FIXTURE[family]}, pledged to an IRB obligor."
        )
    column = C08_COLLATERAL_COLUMNS[family]

    # Act
    sheets = corep_bundle(portfolio, regime).c08_01 or {}
    assert sheets, "C 08.01 emitted no sheet at all"
    published = sum(_template_cell(frame, C08_01_TOTAL_ROW, column) for frame in sheets.values())

    # Assert
    assert published > 0.0, (
        f"{portfolio_name} pledges {pledged:,.2f} of {family} collateral to an IRB obligor "
        f"but C 08.01 row {C08_01_TOTAL_ROW} col {column} sums to 0.00 over "
        f"{len(sheets)} sheets under {regime} — a dead cell, which reads to a supervisor "
        f"exactly like an unmitigated book"
    )
    assert published <= pledged + MONEY_TOLERANCE, (
        f"C 08.01 row {C08_01_TOTAL_ROW} col {column} discloses {published:,.2f} under "
        f"{regime} against {pledged:,.2f} of {family} collateral actually pledged (excess "
        f"{published - pledged:,.2f})"
    )


# ---------------------------------------------------------------------------
# A5 — the gross rule exists twice and the two copies must agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _ALL_CASES)
def test_the_two_gross_side_rule_implementations_agree_row_for_row(
    portfolio_name: str, regime: str
):
    """The sealed gross carriers equal the ones the generator kernel derives.

    The on/off-balance-sheet gross rule is written TWICE: once in
    ``engine/aggregator/aggregator.py::_add_reporting_projection``, which seals the
    two columns onto the production results frame, and once in
    ``reporting/kernel/columns.py::ensure_gross_side_carriers``, which derives them
    for any frame that reaches a generator without them (synthetic, legacy and
    unit frames). Two copies of one rule that must stay identical, with no gate on
    the pair, is a latent divergence: a fix applied to one copy would leave the
    unit-test frames describing a rule production no longer implements.

    This is a PIN, not a proof-of-fix — it is expected green. Nulls are compared
    as nulls (``eq_missing``), because the whole subtlety of the rule is that an
    unknown side stays UNKNOWN rather than becoming 0.0, and a comparison that
    filled nulls first would agree loudly on exactly the case the rule is careful
    about.

    COVERAGE NOTE: the corpus reaches ``loan`` and ``contingent`` only. The
    ``facility_undrawn`` limb, the legacy ``facility`` alias and the CCR /
    settlement null-both-sides branch are therefore NOT exercised here, and the
    failure message names the types actually seen so a future reader can tell.
    """
    # Arrange
    sealed = results_df(SOURCE_PORTFOLIOS[portfolio_name], regime)
    stripped = sealed.drop("reporting_gross_on_bs", "reporting_gross_off_bs").lazy()

    # Act
    derived = ensure_gross_side_carriers(stripped, set(stripped.collect_schema().names())).collect()
    comparison = derived.select(
        pl.col("exposure_reference"),
        pl.col("exposure_type"),
        pl.col("reporting_gross_on_bs").alias("derived_on_bs"),
        pl.col("reporting_gross_off_bs").alias("derived_off_bs"),
    ).with_columns(
        sealed_on_bs=sealed["reporting_gross_on_bs"],
        sealed_off_bs=sealed["reporting_gross_off_bs"],
    )
    divergent = comparison.filter(
        pl.col("derived_on_bs").eq_missing(pl.col("sealed_on_bs")).not_()
        | pl.col("derived_off_bs").eq_missing(pl.col("sealed_off_bs")).not_()
    ).to_dicts()

    # Assert
    assert divergent == [], (
        f"the aggregator's sealed gross carriers and the reporting kernel's derived twins "
        f"disagree under {regime} over exposure types "
        f"{sorted(sealed['exposure_type'].unique().to_list())}: {divergent}"
    )


# ---------------------------------------------------------------------------
# Private helpers — the INPUT side
# ---------------------------------------------------------------------------


def _input_on_balance_sheet(portfolio: tuple[ExposureSpec, ...]) -> float:
    """The on-balance-sheet money the portfolio lends, off the spec literals.

    Drawn principal plus accrued interest, each floored at zero per leg. Floored
    mirroring the regulation rather than the code: a negative drawn amount is the
    on-balance netting convention (CRR Art. 195/219) and a gross-exposure disclosure
    may not go negative. An unset ``interest`` contributes 0 rather than making the
    leg unknown, which is the sealed rule's own treatment of a single null component
    (a leg is null only when drawn AND interest are both null, and a spec always
    carries a drawn amount).
    """
    return sum(max(spec.drawn, 0.0) + max(spec.interest or 0.0, 0.0) for spec in portfolio)


def _input_off_balance_sheet(portfolio: tuple[ExposureSpec, ...]) -> float:
    """The off-balance-sheet nominal the portfolio commits, off the spec literals."""
    return sum(max(spec.off_bs_nominal, 0.0) for spec in portfolio)


def _input_pledged(portfolio: tuple[ExposureSpec, ...], family: str) -> float:
    """The market value of ``family`` collateral pledged, off the spec literals."""
    return _input_pledged_by_family(portfolio).get(family, 0.0)


def _input_pledged_by_family(portfolio: tuple[ExposureSpec, ...]) -> dict[str, float]:
    """``{family: pledged market value}`` over both of a spec's pledge slots.

    ``ExposureSpec`` carries TWO independent pledges, and both must be counted or the
    expected side under-states what the book actually pledged: ``collateral_value``
    (the primary pledge, immovable property when ``collateral_property_type`` is set)
    and ``financial_collateral_value`` (a second pledge that is always eligible
    financial collateral, never real estate, whatever the property field says — see
    ``portfolios._financial_collateral``).

    Keyed on whatever families the specs produce rather than on the four this file
    bounds, so a pledge in a fifth CRM category surfaces in
    :func:`test_the_expected_side_matches_the_raw_input_tables` instead of vanishing.
    """
    pledged: dict[str, float] = {}
    for spec in portfolio:
        if spec.collateral_value > 0.0:
            family = (
                "real_estate"
                if spec.collateral_property_type is not None
                else _collateral_family(spec.collateral_type)
            )
            pledged[family] = pledged.get(family, 0.0) + spec.collateral_value
        if spec.financial_collateral_value > 0.0:
            family = _collateral_family(spec.financial_collateral_type)
            pledged[family] = pledged.get(family, 0.0) + spec.financial_collateral_value
    return pledged


def _collateral_family(collateral_type: str) -> str:
    """The CRM family one ``collateral_type`` string belongs to.

    Resolved through ``data/schemas.COLLATERAL_TYPE_CATEGORY``, the canonical
    single-source mapping, so the input side cannot bucket on a string the engine
    does not recognise and quietly leave the expected total at 0.00. Falls back to
    the recorded ``_UNCATEGORISED_INPUT_TYPES`` gap, and RAISES on anything in
    neither: a new pledge type must be classified deliberately rather than dropped
    out of every expected total (a programming error, so an exception is correct —
    this is not a data-quality finding).
    """
    family = COLLATERAL_TYPE_CATEGORY.get(collateral_type) or _UNCATEGORISED_INPUT_TYPES.get(
        collateral_type
    )
    if family is None:
        raise ValueError(
            f"collateral_type {collateral_type!r} is categorised by neither "
            f"data/schemas.COLLATERAL_TYPE_CATEGORY nor _UNCATEGORISED_INPUT_TYPES, so a "
            f"pledge of it would fall out of every expected total silently"
        )
    return family


def _sum_input_column(frame: pl.LazyFrame | pl.DataFrame | None, column: str) -> float:
    """Sum one column of a RAW loader table, with an absent table reading zero."""
    if frame is None:
        return 0.0
    collected = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
    if column not in collected.columns or collected.height == 0:
        return 0.0
    return float(collected[column].fill_null(0.0).sum())


# ---------------------------------------------------------------------------
# Private helpers — the PUBLISHED side
# ---------------------------------------------------------------------------


def _ledger_sum(df: pl.DataFrame, *columns: str) -> float:
    """Sum one or more sealed ledger carriers over every leg, a null cell as zero.

    A MISSING column raises rather than reading zero. A carrier ladder that silently
    resolves to nothing is the exact shape of `LESSONS.md` B1 — a presence guard on a
    wrong column name that publishes nothing on every run and never raises — and here
    it would make the left-hand side of an inequality 0.00 and the inequality
    unfailable. A renamed carrier must break this file loudly.
    """
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise AssertionError(
            f"the sealed ledger carries no column {missing} — a renamed or removed carrier. "
            f"Reading it as 0.00 would make every inequality over it pass unfailably"
        )
    return float(sum(float(df[column].fill_null(0.0).sum()) for column in columns))


def _template_cell(frame: pl.DataFrame, row_ref: str, column: str) -> float:
    """One published template cell, with an unpublished cell read as zero."""
    row = frame.filter(pl.col("row_ref") == row_ref)
    if row.height == 0 or column not in frame.columns:
        return 0.0
    value = row[column][0]
    return float(value) if value is not None else 0.0


def _require_wholly_standardised(
    portfolio: tuple[ExposureSpec, ...], regime: str, portfolio_name: str
) -> None:
    """Assert the template's in-scope population is the whole input population.

    CR4 and C 07.00 disclose the standardised book. Comparing either against the
    WHOLE input is only sound while every leg routes standardised — otherwise a
    residual would just be the IRB legs, and the identity would be measuring
    routing rather than conservation. Checked against the ledger rather than
    inferred from the specs, because routing is a regime-dependent engine decision
    (PS1/26 removes the IRB approach for sovereigns, so the same spec routes
    differently under the two regimes).
    """
    df = results_df(portfolio, regime)
    approaches = sorted(df["reporting_approach"].unique().to_list())
    assert approaches == ["standardised"], (
        f"{portfolio_name} is not wholly standardised under {regime} ({approaches}), so the "
        f"standardised-only templates cannot be compared against the whole input book; drop "
        f"it from TEMPLATE_PORTFOLIOS or state the identity over the standardised subset"
    )
