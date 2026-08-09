"""
C4b — a second opinion on what each money cell is made of.

Pipeline position:
    portfolio -> PipelineOrchestrator -> sealed aggregator-exit ledger
        -> COREPGenerator / Pillar3Generator (the engine's answer)
        -> cell_rederivation.toml (an independently authored answer)
        -> these assertions

What this proves that nothing else does:
``reporting/lineage.py`` re-runs the generator's own ``RowPredicate`` by design,
so a wrong ``CellSpec`` produces a number that is self-consistent,
lineage-explicable, golden-matching and rule-passing — and still wrong. Both
sides here read the SAME sealed ledger, so any difference can only be a
disagreement about which rows and which carrier a cell is made of. That is the
defect class the row-axis property cannot reach: a cell whose population is
complete but whose carrier, sheet or scale is wrong.

Coverage is bounded and the bound is stated: UK OV1, C 07.00 / OF 07.00,
C 08.01 / OF 08.01, C 08.02 and C 02.00 / OF 02.00 — four of the nineteen
template modules. ``meta.limits`` in the data file records what a green run does
NOT settle, and ``rederive.py`` refuses to load a cell that does not state its
own ``basis``.

References:
- UK Pillar 3 Annex II Template UK OV1; CRR Annex II C 02.00 / C 07.00 / C 08.01;
  PS1/26 Annex II OF 02.00 / OF 07.00 / OF 08.01
- docs/plans/independent-validation-system.md §C4b
"""

from __future__ import annotations

import logging

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.conformance.rederive import CellDerivation, load_derivations
from tests.properties.portfolios import ExposureSpec, pillar3_bundle, results_df, run

logger = logging.getLogger(__name__)

#: Money agreement tolerance. The two sides sum the same Float64 column over the
#: same rows in a different order, so only float reassociation separates them.
MONEY_TOLERANCE = 0.005

REGIMES: tuple[str, ...] = ("CRR", "B31")

#: A portfolio that lights every OV1 credit-risk row (standardised, F-IRB, A-IRB,
#: slotting, equity) and, on top of that, the three axes the extension needed:
#:
#: - an off-balance-sheet commitment on an IRB leg (LN004), so C 08.01 rows
#:   0020/0030 partition something. No golden portfolio had one, which is
#:   .claude/LESSONS.md B5 in its IRB form;
#: - two distinct corporate PD bands (LN004/LN006 at 1.5%/2.0%, LN012 at 0.4%),
#:   so the C 08.02 band boundary is load-bearing rather than agreeing with any
#:   interval that happens to contain the whole class;
#: - both balance-sheet sides on the SA corporate sheet (LN009/CT009, CT010).
#:
#: Deliberately small — thirteen obligors — because the assertion is about which
#: rows and which carrier a cell is made of, not about scale.
PORTFOLIO: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=3),
    ExposureSpec(entity_type="institution", drawn=2_500_000.0, external_cqs=2),
    ExposureSpec(entity_type="sovereign", drawn=6_000_000.0, external_cqs=1),
    ExposureSpec(entity_type="individual", drawn=600_000.0, external_cqs=None),
    ExposureSpec(
        entity_type="corporate",
        drawn=3_000_000.0,
        internal_pd=0.015,
        off_bs_nominal=1_500_000.0,
    ),
    ExposureSpec(entity_type="institution", drawn=1_800_000.0, internal_pd=0.004),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, internal_pd=0.02, firm_lgd=0.35),
    ExposureSpec(entity_type="individual", drawn=500_000.0, internal_pd=0.03, firm_lgd=0.25),
    ExposureSpec(
        entity_type="corporate",
        drawn=7_000_000.0,
        internal_pd=0.01,
        is_specialised_lending=True,
        sl_type="project_finance",
    ),
    ExposureSpec(entity_type="corporate", drawn=1_200_000.0, off_bs_nominal=900_000.0),
    ExposureSpec(entity_type="corporate", drawn=0.0, off_bs_nominal=2_000_000.0),
    ExposureSpec(entity_type="equity", drawn=1_500_000.0, external_cqs=None),
    ExposureSpec(entity_type="corporate", drawn=2_000_000.0, internal_pd=0.004),
)

#: Regime -> the ``framework`` string the generators take.
_FRAMEWORKS: dict[str, str] = {"CRR": "CRR", "B31": "BASEL_3_1"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ledgers() -> dict[str, pl.DataFrame]:
    """regime -> the collected sealed aggregator-exit ledger."""
    return {regime: results_df(PORTFOLIO, regime) for regime in REGIMES}


@pytest.fixture(scope="module")
def templates() -> dict[str, dict[str, pl.DataFrame]]:
    """regime -> "<template>" or "<template>:<member>" -> the generated frame.

    The COREP bundle is generated HERE rather than through
    ``tests.properties.portfolios.corep_bundle`` for one reason: OF 02.00 rows
    0035/0036 read ``OutputFloorSummary``, and a bundle generated without it
    reports a 0.0 multiplier that looks exactly like a defect. Passing the sealed
    summary from the same run keeps the floor column assertable.
    """
    out: dict[str, dict[str, pl.DataFrame]] = {}
    for regime in REGIMES:
        bundle = run(PORTFOLIO, regime)
        corep = COREPGenerator().generate_from_lazyframe(
            bundle.results,
            framework=_FRAMEWORKS[regime],
            output_floor_summary=bundle.output_floor_summary,
        )
        frames: dict[str, pl.DataFrame] = {}
        pillar3 = pillar3_bundle(PORTFOLIO, regime)
        if pillar3.ov1 is not None:
            frames["OV1"] = pillar3.ov1
        if corep.c_02_00 is not None:
            frames["C0200"] = corep.c_02_00
        for template, sheets in (
            ("C0700", corep.c07_00),
            ("C0801", corep.c08_01),
            ("C0802", corep.c08_02),
        ):
            for member, frame in sheets.items():
                frames[f"{template}:{member}"] = frame
        out[regime] = frames
    return out


@pytest.fixture(scope="module")
def floor_summaries() -> dict[str, object]:
    """regime -> the sealed portfolio output floor summary (or None)."""
    return {regime: run(PORTFOLIO, regime).output_floor_summary for regime in REGIMES}


# ---------------------------------------------------------------------------
# Anti-vacuity — the portfolio must reach the cells before agreement means anything
# ---------------------------------------------------------------------------


def test_the_portfolio_reaches_every_approach_the_cells_partition(ledgers) -> None:
    """Every OV1 approach row carries non-zero RWEA under at least one regime.

    Arrange: the sealed ledger for both regimes.
    Act: sum ``rwa_final`` per origin approach.
    Assert: standardised, F-IRB, A-IRB and slotting are all non-zero somewhere.
    A cell nothing populates agrees with any re-derivation at 0.00, which is the
    ``.claude/LESSONS.md`` C2 trap in miniature — measure the crossing amount
    before trusting green.
    """
    reached: dict[str, float] = {}
    for regime, ledger in ledgers.items():
        totals = (
            ledger.group_by("reporting_approach_origin")
            .agg(pl.col("rwa_final").fill_null(0.0).sum().alias("rwa"))
            .to_dicts()
        )
        for entry in totals:
            key = entry["reporting_approach_origin"]
            reached[key] = max(reached.get(key, 0.0), abs(float(entry["rwa"])))
        logger.info("C4b %s approach RWEA: %s", regime, totals)
    for approach in ("standardised", "foundation_irb", "advanced_irb", "slotting"):
        assert reached.get(approach, 0.0) > 0.0, (
            f"no {approach} RWEA in either regime — the OV1 cells for it would "
            f"agree at 0.00 without asserting anything: {reached}"
        )


def test_every_authored_cell_is_reachable(templates) -> None:
    """Each re-derived cell names a sheet, row and column the generator emitted.

    A cell whose sheet or row_ref does not exist would be read as 0.0 by any
    lenient accessor and would pass silently; this makes the address itself an
    assertion. It is also the only check that would catch a template sheet
    disappearing entirely (``.claude/LESSONS.md`` B4 — assert what should be
    there, not only what is).
    """
    missing: list[str] = []
    for cell in load_derivations():
        for regime in cell.regimes:
            frame = templates[regime].get(_key(cell))
            if frame is None:
                missing.append(f"{cell.id}: {regime} emitted no {_key(cell)}")
                continue
            if frame.filter(pl.col("row_ref") == cell.row).height == 0:
                missing.append(f"{cell.id}: {regime} {_key(cell)} has no row {cell.row!r}")
            elif cell.column not in frame.columns:
                missing.append(f"{cell.id}: {regime} {_key(cell)} has no column {cell.column}")
    assert not missing, "unreachable cell addresses:\n  " + "\n  ".join(missing)


def test_every_cell_carries_money_unless_it_says_otherwise(ledgers) -> None:
    """Each cell's own re-derivation is non-zero somewhere, or declares itself vacuous.

    Arrange: the sealed ledger for both regimes.
    Act: evaluate every authored predicate.
    Assert: it is non-zero under at least one regime, unless its ``basis`` says
    the word VACUOUS. That escape hatch is deliberate and narrow: a genuinely
    zero cell (a 0%-weighted sovereign class) is worth authoring, but it has to
    admit in writing that its agreement proves nothing — otherwise the file
    accumulates cells that pass because nothing reaches them, which is the
    failure mode ``.claude/LESSONS.md`` B5 records as self-concealing.
    """
    silent: list[str] = []
    for cell in load_derivations():
        if "VACUOUS" in cell.basis:
            continue
        reached = max(abs(cell.evaluate(ledgers[regime])) for regime in cell.regimes)
        if reached <= MONEY_TOLERANCE:
            silent.append(f"{cell.id} ({cell.address}) re-derives 0.00 in every regime")
    assert not silent, (
        "cells that assert nothing — populate the portfolio or mark the basis "
        "VACUOUS:\n  " + "\n  ".join(silent)
    )


# ---------------------------------------------------------------------------
# The second opinion
# ---------------------------------------------------------------------------


def _cell_params() -> list[pytest.param]:
    """One param per cell, xfailing STRICTLY where a difference is registered.

    Strict is the point: a registered difference that gets fixed turns the xfail
    into an XPASS failure, which forces the entry out of the data file. The
    register cannot rot in the passing direction.
    """
    params = []
    for cell in load_derivations():
        marks = (
            [pytest.mark.xfail(strict=True, reason=f"{cell.address}: {cell.known_difference}")]
            if cell.known_difference
            else []
        )
        params.append(pytest.param(cell.id, marks=marks, id=cell.id))
    return params


@pytest.mark.parametrize("cell_id", _cell_params())
def test_generated_cell_matches_the_independent_rederivation(
    ledgers, templates, cell_id: str
) -> None:
    """The generator and the independently-authored predicate agree on one cell.

    Arrange: the sealed ledger and the generated template, per regime.
    Act: rebuild the cell from ``cell_rederivation.toml`` — a separately
    authored predicate, carrier and scale sourced from the Annex II text.
    Assert: the two agree to float-reassociation tolerance. They read the same
    ledger, so a difference is a disagreement about the cell's DEFINITION.
    """
    cell = _cell(cell_id)
    differences: list[str] = []
    for regime in cell.regimes:
        frame = templates[regime][_key(cell)]
        published = _published(frame, cell.row, cell.column)
        rederived = cell.evaluate(ledgers[regime])
        if abs(published - rederived) > MONEY_TOLERANCE:
            differences.append(
                f"{regime} {cell.address}: generated {published:,.2f} vs "
                f"re-derived {rederived:,.2f} (delta {published - rederived:,.2f})"
            )
    assert not differences, f"{cell.id} [{cell.citation}]:\n  " + "\n  ".join(differences)


# ---------------------------------------------------------------------------
# Identities the instruction text states directly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "member", "total", "parts", "column"),
    [
        ("C0700", "corporate", "0010", ("0070", "0080"), "0010"),
        ("C0700", "corporate", "0010", ("0070", "0080"), "0200"),
        ("C0801", "corporate", "0010", ("0020", "0030"), "0020"),
    ],
)
def test_the_balance_sheet_sides_partition_their_total(
    templates, template: str, member: str, total: str, parts: tuple[str, ...], column: str
) -> None:
    """On-balance-sheet plus off-balance-sheet equals the total exposures row.

    Arrange: the generated sheet for both regimes.
    Act: add the two side rows and compare against the total row.
    Assert: they agree. Annex II states the partition directly — "Exposures that
    are subject to counterparty credit risk shall be reported in rows 0090-0130,
    and therefore shall not be reported in this row" makes the two side rows
    exhaustive on a book with no CCR. Authored as an identity rather than as
    cells because it binds three cells at once: a defect that inflated a side
    while deflating the other would pass all three cell assertions.
    """
    breaks: list[str] = []
    for regime in REGIMES:
        frame = templates[regime][f"{template}:{member}"]
        if column not in frame.columns:
            continue
        whole = _published(frame, total, column)
        pieces = sum(_published(frame, part, column) for part in parts)
        if abs(whole - pieces) > MONEY_TOLERANCE:
            breaks.append(
                f"{regime} {template}[{member}] c{column}: r{total}={whole:,.2f} vs "
                f"{' + '.join('r' + p for p in parts)}={pieces:,.2f}"
            )
    assert not breaks, "balance-sheet sides do not partition the total:\n  " + "\n  ".join(breaks)


def test_the_grade_and_slotting_rows_do_not_double_count(templates) -> None:
    """C 08.01 r0070 and r0080 are disjoint and together make the total.

    Arrange: the generated C 08.01 sheets.
    Act: add "exposures assigned to obligor grades or pools: total" (r0070) and
    "specialised lending slotting approach: total" (r0080), per sheet.
    Assert: the sum equals r0010. Annex II confines r0080 to "the exposure class
    corporate - specialised lending", so a slotting leg that also appeared under
    a PD grade would double-count the sheet's whole RWEA.
    """
    breaks: list[str] = []
    for regime in REGIMES:
        for key, frame in templates[regime].items():
            if not key.startswith("C0801:"):
                continue
            column = "0110"
            whole = _published(frame, "0010", column)
            pieces = _published(frame, "0070", column) + _published(frame, "0080", column)
            if abs(whole - pieces) > MONEY_TOLERANCE:
                breaks.append(
                    f"{regime} {key} c{column}: r0010={whole:,.2f} vs r0070+r0080={pieces:,.2f}"
                )
    assert not breaks, "grade / slotting rows do not partition r0010:\n  " + "\n  ".join(breaks)


#: The OV1 "of which" rows that partition row 1. UK 4a is absent from the Basel 3.1
#: template (PS1/26 Art. 147A removes the IRB equity treatment the row discloses),
#: so it is filtered on presence rather than asserted into existence.
_OV1_OF_WHICH: tuple[str, ...] = ("2", "3", "4", "UK4a", "5")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OV1 double-counts an SA equity leg: it is summed into row 2 AND into row UK 4a. "
        "Measured on the portfolio below — CRR row 1 a = 30,098,477.21 against an of-which sum "
        "(rows 2 + 3 + 4 + UK 4a + 5) of 31,598,477.21, over by exactly UK 4a's 1,500,000.00. "
        "The same defect is already BANKED in the shipped golden "
        "tests/expected_outputs/reporting/crr/pillar3__ov1.ndjson, where row 1 a = "
        "145,511,467.29 against an of-which sum of 148,411,467.29, over by that portfolio's "
        "UK 4a of 2,900,000.00. Root cause: src/rwa_calc/reporting/pillar3/ov1.py's "
        "_APPROACH_REFS maps '2' -> ('standardised', 'equity') and 'UK4a' -> ('equity',), so "
        "UK 4a is keyed on the approach LABEL. The published instruction keys it on the "
        "treatment: UK 4a is 'equities under the simple risk weighted approach' per CRR "
        "Art. 155(2), an IRB method, while rows 2/3/5 each read 'excluding the RWEAs disclosed "
        "in row 4 ... and in row UK 4a' — so the of-which block is meant to partition row 1. "
        "This leg is Art. 133 SA equity, so it belongs in row 2 and NOT in UK 4a, which makes "
        "row 2's own 9,850,000.00 correct and UK 4a's repetition the defect. Note for whoever "
        "fixes it: this is NOT a one-line key swap. The discriminator that would separate the "
        "two treatments, `equity_method`, is absent from the aggregator exit entirely on this "
        "portfolio — the only equity column the sealed ledger carries is `equity_type`, and it "
        "is null on the leg — so the method has to be plumbed through before UK 4a can be keyed "
        "on it. Basel 3.1 is blind to all of this twice over: the B31 template emits no UK 4a "
        "row at all, and the B31 equity leg's rwa_final is null anyway (the "
        "test_every_equity_leg_carries_its_rwea_to_rwa_final defect), so B31 partitions at "
        "0.00 for two wrong reasons. That is the .claude/LESSONS.md C7 shape — a regime that "
        "cannot see the defect is not evidence the defect is absent."
    ),
)
def test_the_of_which_rows_partition_the_credit_risk_total(templates) -> None:
    """OV1 row 1 equals the sum of its "of which" approach rows.

    Arrange: the generated OV1 frames for both regimes.
    Act: add rows 2, 3, 4, UK 4a and 5 and compare against row 1.
    Assert: they agree. Rows 2, 3 and 5 each carry the instruction "excluding the
    RWEAs disclosed in row 4 for specialised lending exposures subject to the
    slotting approach and in row UK 4a for equities under the simple risk weighted
    approach", which makes the block a partition of row 1 rather than a set of
    overlapping subsets. Nothing else in the estate asserts this: the cells check
    each row against the ledger one at a time, so a leg counted by TWO rows agrees
    with both of them and only the partition catches it.
    """
    breaks: list[str] = []
    for regime in REGIMES:
        frame = templates[regime].get("OV1")
        if frame is None:
            continue
        # Presence, not non-zero: a legitimately 0.00 of-which row must stay in the
        # sum and in the message, or a later reader cannot tell which rows were added.
        present = [ref for ref in _OV1_OF_WHICH if frame.filter(pl.col("row_ref") == ref).height]
        whole = _published(frame, "1", "a")
        pieces = sum(_published(frame, ref, "a") for ref in present)
        logger.info("C4b %s OV1 row 1 = %.2f vs %s = %.2f", regime, whole, present, pieces)
        if abs(whole - pieces) > MONEY_TOLERANCE:
            breaks.append(
                f"{regime} OV1 r1/a = {whole:,.2f} but rows {'+'.join(present)} sum to "
                f"{pieces:,.2f} (delta {whole - pieces:,.2f})"
            )
    assert not breaks, "OV1 of-which rows do not partition row 1:\n  " + "\n  ".join(breaks)


def test_own_funds_columns_are_exactly_eight_percent_of_their_rwea(templates) -> None:
    """Every OV1 column-c cell is 8% of the column-a cell on the SAME row.

    Arrange: the generated OV1 frames.
    Act: compare column c against 0.08 x column a, row by row.
    Assert: they agree. The instruction is "own fund requirements corresponding
    to the RWEAs for the different risk categories" (CRR Art. 92(1)), so any row
    where the two are unrelated has taken its own-funds figure from a different
    population than its RWEA figure — the E2 shape, one row wide.
    """
    breaks: list[str] = []
    for regime in REGIMES:
        frame = templates[regime].get("OV1")
        if frame is None:
            continue
        for row in frame.iter_rows(named=True):
            rwea, own_funds = row.get("a"), row.get("c")
            if rwea is None or own_funds is None:
                continue
            if abs(float(own_funds) - 0.08 * float(rwea)) > MONEY_TOLERANCE:
                breaks.append(
                    f"{regime} r{row['row_ref']}: c={float(own_funds):,.2f} "
                    f"vs 0.08 x a={0.08 * float(rwea):,.2f}"
                )
    assert not breaks, "OV1 own-funds columns not 8% of their RWEA:\n  " + "\n  ".join(breaks)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OF 02.00 r0010 c0030 publishes the post-floor TREA, not the floor amount. Measured on "
        "the portfolio below: published 25,461,099.93, which is exactly c0010; the sealed "
        "OutputFloorSummary on the same run holds floor_pct 0.6, s_trea 20,825,000.00, of_adj "
        "-1,263,500.00 and floor_threshold 11,231,500.00. Delta 14,229,599.93. PS1/26 Annex II "
        "(printed p.29) states the cell directly: 'The output floor (reported in row 0010 column "
        "0030) should reflect the formula provided in Article 92 (2a) ... x * S-TREA + OF-ADJ', "
        "and row 0034 is defined as activated 'when, in row 0010, the value in column 0030 is "
        "equal to or greater than the value in column 0010'. Setting c0030 equal to c0010 is "
        "deliberate in reporting/corep/c02.py ('col 0030 (output floor) = the same total'), and "
        "it makes that comparison degenerate: c0030 can never be LESS than c0010, so the "
        "activation test can never come out negative on its own terms, and the engine computes "
        "r0034 from rwa_pre_floor instead. The correct figure already exists on the bundle and "
        "is simply not the one published. The engine is believed wrong. One caveat recorded "
        "honestly: PS1/26 p.29 defines S-TREA as 'the total of all SA exposures provided in "
        "columns 0010 and 0020', which is arguably the whole-portfolio 30,762,500.00 that c0020 "
        "carries rather than the floor-eligible 20,825,000.00 the summary uses — that is a "
        "separate question about the floor's own scope, and this test deliberately compares "
        "against the engine's OWN threshold so it cannot be confused with it."
    ),
)
def test_output_floor_column_is_the_floor_amount(templates, floor_summaries) -> None:
    """OF 02.00 r0010 c0030 equals x * S-TREA + OF-ADJ from the sealed summary.

    Arrange: the generated OF 02.00 frame and the sealed ``OutputFloorSummary``
    from the same run.
    Act: read the published floor cell and the summary's ``floor_threshold``.
    Assert: they agree. The comparison is against a SEALED bundle field, not
    against anything the generator produced, so it stays a second opinion.
    """
    summary = floor_summaries["B31"]
    assert summary is not None, "no output floor summary — the cell cannot be judged"
    frame = templates["B31"]["C0200"]
    published = _published(frame, "0010", "0030")
    expected = float(summary.floor_threshold)  # ty: ignore[unresolved-attribute]
    logger.info("C4b OF 02.00 r0010 c0030 published=%.2f floor_threshold=%.2f", published, expected)
    assert abs(published - expected) <= MONEY_TOLERANCE, (
        f"OF 02.00 r0010/c0030 published {published:,.2f} but Art. 92(2a) "
        f"x * S-TREA + OF-ADJ is {expected:,.2f} (delta {published - expected:,.2f})"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "An SA-treated equity leg reaches no C 07.00 sheet. Measured under CRR: LN011 carries "
        "reporting_approach 'equity', ead_final 1,500,000 and rwa_final 1,500,000, and C 02.00 "
        "row 0210 ('1.1.1.1.15 Equity', whose whole instruction is 'See CR SA template') "
        "publishes that 1,500,000 — but C 07.00 emits sheets for exactly four classes "
        "(central_govt_central_bank, corporate, institution, retail_other) and none of them is "
        "equity. CRR Art. 112(1)(p) makes equity exposures an SA exposure class, and Annex II "
        "paragraphs 47-48 put every SA class except securitisation positions in CR SA, so the "
        "row C 02.00 points at does not exist: 1,500,000 of exposure value and RWEA sits in the "
        "footing template with nothing to tie to. The engine is believed wrong on the missing "
        "sheet. Caveat: CRR also has a CR EQU IRB template for IRB-METHOD equity "
        "(Art. 155(2)/(3)) which this generator does not produce at all, so a fix has to decide "
        "which of the two templates each equity method belongs in rather than just adding a "
        "sheet."
    ),
)
def test_an_sa_equity_leg_reaches_a_c0700_sheet(templates, ledgers) -> None:
    """An equity leg treated under the SA appears on a C 07.00 exposure-class sheet.

    Arrange: the CRR ledger and the generated C 07.00 sheets.
    Act: find the legs whose applied approach is ``equity`` with non-zero RWEA,
    then look for a C 07.00 sheet keyed on their reporting class.
    Assert: one exists. Scoped to CRR because under Basel 3.1 the same leg's
    ``rwa_final`` is null (the defect the next test records), which would conflate
    the two findings.
    """
    equity = ledgers["CRR"].filter(
        (pl.col("reporting_approach") == "equity") & (pl.col("rwa_final").fill_null(0.0) != 0.0)
    )
    assert equity.height, "no SA-treated equity RWEA — the assertion would be vacuous"
    sheets = {key.removeprefix("C0700:") for key in templates["CRR"] if key.startswith("C0700:")}
    orphaned = [
        f"{row['exposure_reference']}: reporting_class={row['reporting_class']!r} "
        f"ead_final={row['ead_final']:,.2f} rwa_final={row['rwa_final']:,.2f}"
        for row in equity.iter_rows(named=True)
        if row["reporting_class"] not in sheets
    ]
    assert not orphaned, (
        f"SA equity RWEA with no C 07.00 sheet (emitted sheets: {sorted(sheets)}):\n  "
        + "\n  ".join(orphaned)
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A Basel 3.1 equity leg is CALCULATED and then dropped. Measured on the portfolio "
        "below: LN011, EAD 1,500,000, reporting_rw 2.5 (the PS1/26 Art. 133 250% equity risk "
        "weight), sa_rwa 3,750,000 — and rwa_final NULL. The same leg under CRR carries "
        "rwa_final 1,500,000 at 100%. Because rwa_final is the carrier every credit-risk "
        "template and OV1 row sums, 3,750,000 of RWEA and 300,000 of own funds requirement "
        "(CRR Art. 92(1)) leave the Basel 3.1 submission with no error, no null cell and no "
        "failing published rule — the row simply is not there. The engine is believed wrong: "
        "a leg whose risk weight the engine has resolved must reach rwa_final, and null is "
        "not a defensible response to an input shape it otherwise processed. Caveat recorded "
        "honestly: the canonical input for an equity holding is the dedicated "
        "equity_exposures table, and this leg reaches the equity approach from the loans "
        "table, so the population may be narrower than every equity holding."
    ),
)
def test_every_equity_leg_carries_its_rwea_to_rwa_final(ledgers) -> None:
    """An equity leg the engine risk-weighted reaches the carrier the templates sum.

    Arrange: the sealed ledger for both regimes.
    Act: select the legs whose origin approach is ``equity``.
    Assert: each has a non-null ``rwa_final``. This is the ``.claude/LESSONS.md``
    B4 shape — assert what should be there, not only what is — at the one place
    where a null and a genuine zero are indistinguishable downstream.
    """
    dropped: list[str] = []
    for regime, ledger in ledgers.items():
        equity = ledger.filter(pl.col("reporting_approach_origin") == "equity")
        for row in equity.iter_rows(named=True):
            if row["rwa_final"] is None:
                dropped.append(
                    f"{regime} {row['exposure_reference']}: ead_final="
                    f"{row['ead_final']:,.2f} reporting_rw={row['reporting_rw']} "
                    f"sa_rwa={row['sa_rwa']:,.2f} rwa_final=None"
                )
    assert not dropped, "equity RWEA never reaches rwa_final:\n  " + "\n  ".join(dropped)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _cell(cell_id: str) -> CellDerivation:
    return next(c for c in load_derivations() if c.id == cell_id)


def _key(cell: CellDerivation) -> str:
    """The ``templates`` fixture key for a cell's sheet."""
    return f"{cell.template}:{cell.member}" if cell.member else cell.template


def _published(frame: pl.DataFrame, row_ref: str, column: str) -> float:
    """One generated cell, with a null read as 0.00.

    Reading a null as zero is safe HERE only because
    ``test_every_authored_cell_is_reachable`` has already proved the address
    exists — otherwise a missing row and a genuine zero would be the same value.
    """
    row = frame.filter(pl.col("row_ref") == row_ref)
    value = row[column][0] if row.height else None
    return float(value) if value is not None else 0.0
