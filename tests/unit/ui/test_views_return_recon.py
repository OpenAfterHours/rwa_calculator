"""
Unit tests: the return-reconciliation template view (ui/views/return_recon.py).

Pins the rendering rules that stand between an analyst and a wrong number on a
regulatory comparison. Each one has been measured in this codebase, and each is
asserted against a source of truth that cannot drift with the view:

- **Four blanks, four meanings.** The state vocabulary is read off
  ``return_recon.CellState`` itself, so a new state cannot be added without a
  rendering, and no state renders as ``0``.
- **Unavailable is not zero.** A column the legacy ``LedgerCoverage`` names as
  unpopulatable renders ``n/a`` with the remedy, carries a NULL delta, and is
  listed separately rather than ranked among the differences.
- **A missing row is not a zero.** A row emitted on one side only keeps our
  figure and shows theirs as absent; a pair the template binds nowhere renders
  as a third thing again.
- **A refused decomposition is not a zero waterfall.** A weighted average is
  refused with a reason and NO steps.
- **The migration matrix conserves money on BOTH sides.** The five movement
  classes are asserted to equal the fixture's own per-leg totals — ours and
  theirs, as equalities, under both frameworks.
- **Materiality is one threshold, set once.** Both floors must be cleared.
- **The exposures behind a cell are PAIRED and ranked on contribution.**
  Asserted on the RENDERED page, positionally, against a probe portfolio built
  so that a size ranking cannot show a single driver — a per-side listing capped
  at 25 a side put 50 agreeing loans on the page and every driver below the cap.
  A side holding no leg for an exposure is asserted to render an explicit fifth
  state, and the cap is asserted to state what it hid.
- **The waterfall is not a scope check, and the page says so.** The sheet-level
  conservation line is asserted to NET on a portfolio whose only difference is a
  moved row and to BREAK on one holding a genuinely one-sided exposure, with the
  overlapping parent rows excluded from the sum.

References:
- Regulation (EU) 2021/451, Annex II: C 08.03 (and OF 08.03 under PS1/26)
- docs/plans/return-reconciliation.md, Phase 3
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING, get_args
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.analysis.legacy_ledger import LedgerCoverage
from rwa_calc.analysis.return_recon import (
    ABSENT_ROW,
    CELL_PAIRS_LIMIT,
    PLACEMENT_ATTRIBUTION,
    TERM_NAMES,
    UNDECIDABLE_ROW,
    CellState,
    build_recon,
    decompose_cell,
    diff_cells,
)
from rwa_calc.api.rest import register_reconciliation_with_id
from rwa_calc.ui.app import main as ui_main
from rwa_calc.ui.views import return_recon as rr

if TYPE_CHECKING:
    from collections.abc import Iterator

    from rwa_calc.analysis.return_recon import CellDecomposition, ReturnRecon

FRAMEWORKS = ("CRR", "BASEL_3_1")
TEMPLATE = "c08_03"
SHEET = "corporate"

# Two PD bands per parent, chosen to be distinct under BOTH row scales: CRR
# splits 0.00-0.15 at 0.10 (rows 0020 / 0030) and Basel 3.1 at 0.05 (rows 0015 /
# 0025), so 0.03% and 0.12% land in different rows either way. Without two
# populated children a parent band is indistinguishable from a leaf, comes back
# with a NULL flag, and the matrix legitimately empties into the undecidable
# bucket — which would make the conservation assertions vacuous.
PD_LOW = 0.0003
PD_MID = 0.0012
PD_HIGH_A = 0.0100
PD_HIGH_B = 0.0200
#: A band no other leg reaches, so the row it lands in is emitted on one side only.
PD_SOLO = 0.0500

# The fixture's own money, which the matrix assertions are stated against.
RWA_A0, RWA_A1, RWA_A2 = 90_000.0, 300_000.0, 330_000.0
RWA_B0, RWA_B1 = 720_000.0, 800_000.0
RWA_MOVER = 210_000.0
RWA_OURS_ONLY = 150_000.0
RWA_THEIRS_ONLY = 120_000.0
RWA_SOLO = 640_000.0
AGREED_RWA = RWA_A0 + RWA_A1 + RWA_A2 + RWA_B0 + RWA_B1

#: A provisions column C 08.03 publishes and a thin mapping cannot populate.
UNMAPPED_COL = "0110"
UNMAPPED_REMEDY = "needs scra_provision_amount, gcra_provision_amount"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clean_comparison_cache() -> Iterator[None]:
    """The comparison memo is module-level state keyed on a caller-chosen id.

    Cleared around EVERY test: two tests reusing one id (a parametrisation over
    frameworks, say) would otherwise hand the second the first's recon, and a
    test that failed before its own cleanup would leak into the next.
    """
    rr.clear_comparison_cache()
    yield
    rr.clear_comparison_cache()


class _FrameSource:
    """A minimal ``ResultsSource`` over a hand-built sealed ledger."""

    def __init__(self, frame: pl.LazyFrame, framework: str = "CRR") -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame


def _leg(  # noqa: PLR0913 - one leg's raw shape, every field defaulted
    reference: str,
    *,
    pd: float,
    rwa: float,
    ead: float | None = None,
    exposure_class: str = SHEET,
    source: str | None = None,
    supplies_source_ref: bool = True,
) -> dict[str, object]:
    """One IRB leg in the raw shape the sealed ledger is derived from.

    ``source`` names the PRE-SPLIT base exposure a leg belongs to; ``None``
    means the leg is unsplit and is its own base, which is every other fixture
    here. ``supplies_source_ref=False`` mirrors the projected legacy side, which
    supplies no ``source_exposure_reference`` at all — it is neither a component
    nor a carrier in ``recon_registry``, so it arrives as a typed NULL.
    """
    exposure = ead if ead is not None else rwa * 3.0
    base = source or reference
    return {
        "exposure_reference": reference,
        "source_exposure_reference": base if supplies_source_ref else None,
        "counterparty_reference": f"CP_{base}",
        "exposure_class": exposure_class,
        "exposure_class_applied": exposure_class,
        "exposure_class_post_crm": exposure_class,
        "approach_applied": "foundation_irb",
        "approach_post_crm": "foundation_irb",
        "exposure_type": "loan",
        "drawn_amount": exposure,
        "undrawn_amount": 0.0,
        "nominal_amount": 0.0,
        "interest": 0.0,
        "ead_final": exposure,
        "rwa_final": rwa,
        "risk_weight": rwa / exposure,
        "ccf": 1.0,
        "pd": pd,
        "pd_floored": pd,
        "lgd_floored": 0.45,
        "irb_maturity_m": 2.5,
        "expected_loss": pd * 0.45 * exposure,
        "scra_provision_amount": 0.0,
        "gcra_provision_amount": 0.0,
        "sa_cqs": 0,
        "is_defaulted": False,
        "reporting_leg_role": "whole",
    }


def _source(legs: list[dict[str, object]], framework: str) -> _FrameSource:
    frame = pl.LazyFrame(
        legs,
        schema_overrides={
            "pd": pl.Float64,
            "pd_floored": pl.Float64,
            "lgd_floored": pl.Float64,
            "irb_maturity_m": pl.Float64,
            "sa_cqs": pl.Int8,
            # Pinned so a side whose legs ALL omit the base reference still
            # carries the column as a typed NULL String, exactly as the sealed
            # membership schema declares it.
            "source_exposure_reference": pl.String,
        },
    )
    return _FrameSource(with_reporting_ledger(frame), framework)


def _base_legs() -> list[dict[str, object]]:
    """Legs identical on both sides — two populated children per parent band."""
    return [
        _leg("A0", pd=PD_LOW, rwa=RWA_A0),
        _leg("A1", pd=PD_MID, rwa=RWA_A1),
        _leg("A2", pd=PD_MID, rwa=RWA_A2),
        _leg("B0", pd=PD_HIGH_A, rwa=RWA_B0),
        _leg("B1", pd=PD_HIGH_B, rwa=RWA_B1),
    ]


@lru_cache(maxsize=8)
def _recon(framework: str) -> ReturnRecon:
    """All five causes live at once: agreement, a mover, and one leg each side.

    Cached — a ``ReturnRecon`` carries memo dictionaries, so nothing may mutate
    what this returns.
    """
    ours = [
        *_base_legs(),
        _leg("MOVER", pd=PD_MID, rwa=RWA_MOVER),
        _leg("ONLY_OURS", pd=PD_MID, rwa=RWA_OURS_ONLY),
    ]
    theirs = [
        *_base_legs(),
        _leg("MOVER", pd=PD_HIGH_B, rwa=RWA_MOVER),
        _leg("ONLY_THEIRS", pd=PD_MID, rwa=RWA_THEIRS_ONLY),
    ]
    return build_recon(_source(ours, framework), _source(theirs, framework))


@lru_cache(maxsize=8)
def _recon_one_sided(framework: str) -> ReturnRecon:
    """A leg in a PD band nobody on their side reaches.

    C 08.03's rows are SPARSE — only a populated band emits — so this is the
    shape in which a population difference becomes a MISSING ROW rather than a
    zero. Kept apart from ``_recon`` so the matrix fixtures are not perturbed.
    """
    theirs = _base_legs()
    ours = [*theirs, _leg("SOLO", pd=PD_SOLO, rwa=RWA_SOLO)]
    return build_recon(_source(ours, framework), _source(theirs, framework))


def _coverage() -> LedgerCoverage:
    """A legacy mapping that reaches C 08.03 but cannot populate provisions."""
    return LedgerCoverage(
        supplied=frozenset({"ead_final", "rwa_final", "pd_floored"}),
        missing=frozenset({"scra_provision_amount", "gcra_provision_amount"}),
        unavailable_cells={TEMPLATE: (f"{UNMAPPED_COL}: {UNMAPPED_REMEDY}",)},
        reachable_templates=frozenset({TEMPLATE}),
        present_approaches=frozenset({"foundation_irb"}),
        populated_templates=frozenset({TEMPLATE, "c08_01"}),
    )


def _thin_ledger(legs: list[dict[str, object]], framework: str = "CRR") -> _FrameSource:
    """A projection of a mapping with NO gross-exposure sources at all.

    This is what ``project_legacy_ledger`` emits for a thin mapping: only the
    columns the mapping supplied, with the gross carriers simply absent. It is
    the shape that produces the FALSE ZERO — ``ensure_gross_side_carriers``
    injects an all-null column downstream and ``sum`` returns ``0.0`` over it,
    not null — so C 08.03's gross columns print a confident legacy zero unless
    the coverage record is threaded through.
    """
    supplied = (
        "exposure_reference",
        "source_exposure_reference",
        "counterparty_reference",
        "exposure_class",
        "exposure_class_applied",
        "exposure_class_post_crm",
        "approach_applied",
        "approach_post_crm",
        "ead_final",
        "rwa_final",
        "risk_weight",
        "ccf",
        "pd",
        "pd_floored",
        "lgd_floored",
        "irb_maturity_m",
        "is_defaulted",
        "reporting_leg_role",
    )
    frame = _source(legs, framework)._frame.select(supplied)
    return _FrameSource(with_reporting_ledger(frame).drop(_GROSS_COLUMNS), framework)


#: The gross carriers the thin projection cannot supply, and the C 08.03 column
#: that reads them. ``0010`` is "original exposure pre-conversion, on-balance
#: sheet" — the first money column of the sheet.
_GROSS_COLUMNS = (
    "reporting_gross_on_bs",
    "reporting_gross_off_bs",
    "reporting_gross_drawn",
    "reporting_gross_interest",
    "reporting_gross_nominal",
    "reporting_gross_undrawn",
)
GROSS_COL = "0010"
GROSS_REMEDY = "needs drawn_amount, reporting_gross_on_bs"


def _thin_coverage() -> LedgerCoverage:
    """The coverage that thin mapping returns: C 08.03 col 0010 unpopulatable."""
    return LedgerCoverage(
        supplied=frozenset({"ead_final", "rwa_final", "pd_floored"}),
        missing=frozenset({"drawn_amount", "reporting_gross_on_bs"}),
        unavailable_cells={TEMPLATE: (f"{GROSS_COL}: {GROSS_REMEDY}",)},
        reachable_templates=frozenset({TEMPLATE}),
        present_approaches=frozenset({"foundation_irb"}),
        populated_templates=frozenset({TEMPLATE}),
    )


@lru_cache(maxsize=8)
def _recon_with_coverage(framework: str) -> ReturnRecon:
    """The same portfolio, with the legacy side's coverage record threaded in."""
    legs = [*_base_legs(), _leg("MOVER", pd=PD_MID, rwa=RWA_MOVER)]
    return build_recon(
        _source(legs, framework),
        _source(legs, framework),
        theirs_coverage=_coverage(),
    )


def _compare(framework: str = "CRR") -> rr.SheetCompare:
    compare = rr.sheet_compare(_recon(framework), TEMPLATE, SHEET)
    assert compare is not None
    return compare


def _cells(compare: rr.SheetCompare) -> list[rr.CompareCell]:
    return [cell for row in compare.rows for cell in row.cells]


def _row_of(recon: ReturnRecon, reference: str, *, ours: bool) -> str:
    """The C 08.03 leaf row one leg landed in, read off the membership.

    Never a literal: CRR's row axis is 17 rows and Basel 3.1's is 18, so a
    hard-coded ref would silently pin one framework.
    """
    side = recon.ours if ours else recon.theirs
    rows = side.membership.legs.filter(
        (pl.col("template_id") == TEMPLATE)
        & (pl.col("sheet") == SHEET)
        & (pl.col("exposure_reference") == reference)
        & (pl.col("is_parent_row").eq(other=False))
    )
    assert rows.height == 1, f"{reference} is in {rows.height} leaf rows, expected 1"
    return str(rows["row_ref"][0])


# =============================================================================
# Rule 1 — four blanks, four meanings
# =============================================================================


def test_every_cell_state_has_its_own_rendering() -> None:
    # Arrange — the vocabulary comes from the analysis layer, not a hand list.
    states = set(get_args(CellState.__value__))

    # Assert — one rendering per state, no more and no fewer.
    assert set(rr.STATE_DISPLAY) == states


def test_the_four_state_glyphs_are_pairwise_distinct() -> None:
    # Arrange
    glyphs = [glyph for glyph, _css, _title in rr.STATE_DISPLAY.values()]
    classes = [css for _glyph, css, _title in rr.STATE_DISPLAY.values()]

    # Assert — three blanks that look alike are one blank.
    assert len(set(glyphs)) == len(glyphs)
    assert len(set(classes)) == len(classes)


@pytest.mark.parametrize("state", ["empty", "unavailable", "absent"])
def test_a_blank_state_never_renders_as_a_zero(state: str) -> None:
    # Act
    figure = rr._side_figure(0.0, state, "")

    # Assert — the value is dropped with the state; a printed 0.0 is an artefact.
    assert figure.value is None
    assert figure.display not in {"0", "0.0", "0.00", ""}


def test_a_reported_zero_still_renders_as_zero() -> None:
    # Assert — a measured zero is a finding, and must not look like a blank.
    figure = rr._side_figure(0.0, "figure", "")
    assert figure.display == "0"
    assert figure.value == 0.0


# =============================================================================
# Rule 2 — an unavailable cell is not a zero
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_coverage_unavailable_column_renders_not_mapped_never_zero(framework: str) -> None:
    # Arrange — the two sides hold the SAME legs, so any delta here is an
    # artefact of the mapping rather than of the book.
    compare = rr.sheet_compare(
        _recon_with_coverage(framework), TEMPLATE, SHEET, coverage=_coverage()
    )
    assert compare is not None

    # Act
    blocked = [cell for cell in _cells(compare) if cell.col_ref == UNMAPPED_COL]

    # Assert — never a figure, never a delta, and the remedy travels with it.
    assert blocked, "the unmappable column is not on this sheet"
    for cell in blocked:
        assert cell.theirs.state == "unavailable"
        assert cell.theirs.display == rr.UNMEASURABLE_DISPLAY
        assert cell.delta is None
        assert cell.delta_display == rr.UNMEASURABLE_DISPLAY
        assert cell.status == "unmeasurable"
        assert UNMAPPED_REMEDY in cell.note


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_unmeasurable_cells_are_listed_apart_from_the_ranked_differences(framework: str) -> None:
    # Arrange
    compare = rr.sheet_compare(
        _recon_with_coverage(framework), TEMPLATE, SHEET, coverage=_coverage()
    )
    assert compare is not None

    # Assert — they have no delta to rank on, so a single list would drop them.
    assert compare.unmeasurable_count > 0
    assert {cell.col_ref for cell in compare.unmeasurable} == {UNMAPPED_COL}
    assert all(cell.measurable for cell in compare.worst)


def test_an_unavailable_side_kills_the_delta_even_when_a_figure_was_printed() -> None:
    # Arrange — the dangerous shape: an injected all-null column sums to 0.0.
    record = {
        "row_ref": "0010",
        "col_ref": UNMAPPED_COL,
        "ours": 1_000_000.0,
        "theirs": None,
        "delta": None,
        "ours_state": "figure",
        "theirs_state": "unavailable",
        "status": "unmeasurable",
    }

    # Act
    cell = rr._cell(
        record,
        row_name="",
        col_name="",
        largest=1_000_000.0,
        materiality=rr.DEFAULT_MATERIALITY,
        remedy="not mapped: needs provisions",
        template_block="",
    )

    # Assert
    assert cell.delta_display == rr.UNMEASURABLE_DISPLAY
    assert not cell.is_material
    assert cell.heat == 0.0


# =============================================================================
# Rule 2b — THIS VIEW arms the guard. Not "coverage works" — that we pass it.
# =============================================================================


def test_build_comparison_threads_the_legacy_coverage_onto_the_side_it_guards() -> None:
    # Arrange
    rr.clear_comparison_cache()
    legs = _base_legs()

    # Act
    recon = rr.build_comparison(
        "guard-armed", _source(legs, "CRR"), _thin_ledger(legs), theirs_coverage=_thin_coverage()
    )

    # Assert — the record reached the LEGACY SideView, which is the only place
    # it does anything. ``build_recon`` defaults it to None, so a call site that
    # omits it leaves this None and every guard downstream is inert.
    assert recon.theirs.coverage is not None
    assert recon.theirs.coverage.unavailable_refs(TEMPLATE) == (GROSS_COL,)
    rr.clear_comparison_cache()


def test_the_view_renders_an_unpopulatable_gross_column_as_not_mapped() -> None:
    """The end-to-end shape of the false zero, through ``build_comparison``.

    The counterfactual is asserted in the same test rather than assumed: the
    identical pair built WITHOUT the coverage record produces a confident legacy
    ``0.00`` and a waterfall that RECONCILES, with the fabricated money landing
    in ``measurement`` — "same loans, different number", which is the most
    misleading thing this page could say. If that counterfactual ever stops
    holding, this test says so instead of quietly guarding nothing.
    """
    # Arrange
    rr.clear_comparison_cache()
    legs = _base_legs()
    ours, theirs = _source(legs, "CRR"), _thin_ledger(legs)

    # Act — armed, the way the route does it.
    recon = rr.build_comparison("guard-render", ours, theirs, theirs_coverage=_thin_coverage())
    compare = rr.sheet_compare(recon, TEMPLATE, SHEET, coverage=_thin_coverage())
    assert compare is not None
    blocked = [cell for cell in _cells(compare) if cell.col_ref == GROSS_COL]

    # Assert — not mapped, no figure, no delta, and named remedy.
    assert blocked
    assert {cell.theirs.state for cell in blocked} == {"unavailable"}
    assert {cell.theirs.value for cell in blocked} == {None}
    assert {cell.theirs.display for cell in blocked} == {rr.UNMEASURABLE_DISPLAY}
    assert {cell.delta for cell in blocked} == {None}
    assert {cell.delta_display for cell in blocked} == {rr.UNMEASURABLE_DISPLAY}
    assert all(GROSS_REMEDY in cell.note for cell in blocked)
    # ... it is NOT a difference, so it is not ranked among them ...
    assert all(cell.col_ref != GROSS_COL for cell in compare.worst)
    assert GROSS_COL in {cell.col_ref for cell in compare.unmeasurable}
    # ... and it is refused, as a COVERAGE refusal rather than any other kind.
    explanation = rr.explain_cell(
        recon, TEMPLATE, SHEET, blocked[0].row_ref, GROSS_COL, coverage=_thin_coverage()
    )
    assert explanation.refused
    assert explanation.refusal_kind == "coverage"
    assert explanation.steps == ()
    assert GROSS_REMEDY in explanation.remedy

    # Assert the COUNTERFACTUAL — unarmed, this cell fabricates a measurement.
    unarmed = build_recon(ours, theirs, [TEMPLATE])
    fabricated = decompose_cell(unarmed, TEMPLATE, SHEET, blocked[0].row_ref, GROSS_COL)
    assert fabricated.refusal is None, "the guard has nothing to guard against here"
    assert fabricated.theirs == 0.0
    assert fabricated.reconciles
    assert fabricated.amount("measurement") != 0.0
    rr.clear_comparison_cache()


# =============================================================================
# Rule 3 — a missing row is not a zero
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_row_only_we_emit_shows_our_figure_against_an_explained_blank(framework: str) -> None:
    # Arrange — SOLO occupies a PD band nobody on their side reaches, so C 08.03
    # (whose rows are sparse) emits that row on our sheet and not on theirs.
    recon = _recon_one_sided(framework)
    compare = rr.sheet_compare(recon, TEMPLATE, SHEET)
    assert compare is not None
    ours_only = [cell for cell in _cells(compare) if cell.status == "ours_only"]

    # Assert — the shape exists at all (a vacuous loop would prove nothing) ...
    assert ours_only, "no one-sided cell on this sheet — the fixture proves nothing"
    money = [cell for cell in ours_only if cell.col_ref == "0090"]
    assert money, "the RWEA column is not one-sided here"
    # ... their blank is EXPLAINED, never a zero ...
    for cell in ours_only:
        assert cell.ours.state == "figure"
        assert cell.theirs.state in {"empty", "absent"}
        assert cell.theirs.display in {"—", "·"}
        assert cell.theirs.display != "0"
    # ... and the delta is the WHOLE of our figure, asserted on BOTH sides: our
    # exact RWEA against their exact absence, not a one-sided bound.
    assert {cell.ours.value for cell in money} == {RWA_SOLO}
    assert {cell.theirs.value for cell in money} == {None}
    assert {cell.delta for cell in money} == {RWA_SOLO}


def test_a_pair_the_template_binds_nowhere_is_a_third_thing_again() -> None:
    # Act
    cell = rr._absent_cell("0010", "0.00 to <0.15", rr.ColumnHead(ref="9999", name="nothing"))

    # Assert — not a figure, not an unmeasurable delta, and never a zero.
    assert cell.ours.state == "absent"
    assert cell.theirs.state == "absent"
    assert cell.delta is None
    assert cell.delta_display == rr.NO_CELL_DISPLAY
    assert cell.delta_display != rr.UNMEASURABLE_DISPLAY
    assert cell.delta_display != "0"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_grid_row_is_aligned_to_the_header(framework: str) -> None:
    # Arrange
    compare = _compare(framework)

    # Assert — a short row would shift every later cell one column left, which
    # relabels real figures rather than merely losing a blank.
    refs = tuple(head.ref for head in compare.columns)
    for row in compare.rows:
        assert tuple(cell.col_ref for cell in row.cells) == refs


# =============================================================================
# Rule 4 — a refused decomposition is not a zero waterfall
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_weighted_average_cell_is_refused_with_a_reason_and_no_steps(framework: str) -> None:
    # Arrange — col 0050 is the exposure-weighted average PD.
    recon = _recon(framework)
    row_ref = _row_of(recon, "MOVER", ours=True)

    # Act
    explanation = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0050")

    # Assert
    assert explanation.refused
    assert explanation.steps == ()
    assert "non-additive" in explanation.refusal


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_an_additive_money_cell_is_decomposed_and_reconciles(framework: str) -> None:
    # Arrange — col 0090 is RWEA, a plain sum.
    recon = _recon(framework)
    row_ref = _row_of(recon, "MOVER", ours=True)

    # Act
    explanation = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0090")

    # Assert — the terms exist, are labelled, and are scored against the report.
    assert not explanation.refused
    assert {step.name for step in explanation.steps} == set(rr.TERM_LABELS)
    assert explanation.reconciles
    assert explanation.attribution == PLACEMENT_ATTRIBUTION


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_four_refusals_are_classified_apart(framework: str) -> None:
    # Arrange — a weighted average and a coverage-blocked sum on the same sheet.
    recon = _recon(framework)
    row_ref = _row_of(recon, "MOVER", ours=True)
    blocked = rr.build_comparison(
        f"refusal-kinds-{framework}",
        _source(_base_legs(), framework),
        _thin_ledger(_base_legs(), framework),
        theirs_coverage=_thin_coverage(),
    )

    # Act
    average = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0050")
    unmapped_row = next(
        cell.row_ref
        for cell in _cells(rr.sheet_compare(blocked, TEMPLATE, SHEET) or ())  # type: ignore[arg-type]
        if cell.col_ref == GROSS_COL
    )
    unmapped = rr.explain_cell(
        blocked, TEMPLATE, SHEET, unmapped_row, GROSS_COL, coverage=_thin_coverage()
    )
    money = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0090")
    rr.clear_comparison_cache()

    # Assert — three different kinds, three different headlines, one of them
    # explicitly NOT a difference at all.
    assert average.refusal_kind == "non_additive"
    assert unmapped.refusal_kind == "coverage"
    assert money.refusal_kind == ""
    assert average.refusal_headline != unmapped.refusal_headline
    assert "not a difference" in unmapped.refusal_headline
    assert "not a difference" not in average.refusal_headline
    # ... and only the coverage one names a mapping remedy.
    assert unmapped.remedy
    assert not average.remedy


def test_every_refusal_kind_has_its_own_headline() -> None:
    # Assert — four kinds, four distinct first lines. Rendering any two alike
    # gives the analyst the wrong next action.
    headlines = list(rr.REFUSAL_HEADLINES.values())
    assert len(set(headlines)) == len(headlines)
    assert set(rr.REFUSAL_HEADLINES) == {
        "coverage",
        "non_additive",
        "not_row_backed",
        "unbound",
    }


def test_the_waterfall_labels_cover_the_terms_the_module_publishes() -> None:
    # Assert — anchored to ``return_recon.TERM_NAMES``, not to a belief about
    # what the terms are. The published names have already been corrected once.
    assert set(rr.TERM_LABELS) == set(TERM_NAMES)


def test_a_refused_decomposition_carries_no_step_whatever_its_amounts() -> None:
    # Assert — the refusal branch is structural, not a filter on zero amounts.
    from rwa_calc.analysis.return_recon import CellDecomposition, CellTerm

    refused = CellDecomposition(
        template_id=TEMPLATE,
        sheet=SHEET,
        row_ref="0010",
        col_ref="0050",
        kind="rows",
        metric="weighted_avg",
        ours=1.0,
        theirs=2.0,
        ours_state="figure",
        theirs_state="figure",
        delta=-1.0,
        terms=(CellTerm(name="measurement", amount=-1.0, keys=1, differing_keys=1),),
        reconciles=True,
        residual=0.0,
        refusal="non-additive metric",
    )
    # Asserted under a SELECTED cause too: the filter must not resurrect steps
    # on a cell whose split does not apply.
    assert rr._steps(refused, None) == ()
    assert rr._steps(refused, "measurement") == ()


# =============================================================================
# Rule 4b — a split exposure is ONE exposure, through THIS view's entry point
# =============================================================================

#: C 08.03's RWEA column, ``Sum(rwa_col)`` — a plain additive money cell.
RWEA_COL = "0090"
#: Our two legs of one guaranteed loan, and their whole loan. Split 60/40 so
#: neither leg alone can be mistaken for the whole.
SPLIT_G_RWA, SPLIT_REM_RWA = 60_000.0, 40_000.0


def _split_recon(framework: str) -> ReturnRecon:
    """One guaranteed loan, split on our side and whole on theirs.

    Built through ``build_comparison`` — the production entry point, which never
    passes a ``key_column`` — rather than through ``build_recon`` directly, so a
    fix that only works when the caller opts into a different join key does not
    satisfy this. The base legs occupy every band except ``PD_HIGH_A``, so the
    split exposure lands in a leaf row of its own.
    """
    bands = (("A0", PD_LOW, RWA_A0), ("A1", PD_MID, RWA_A1), ("B1", PD_HIGH_B, RWA_B1))
    ours = [
        *(_leg(ref, pd=pd, rwa=rwa) for ref, pd, rwa in bands),
        _leg("L1__G_BANK", source="L1", pd=PD_HIGH_A, rwa=SPLIT_G_RWA, ead=600_000.0),
        _leg("L1__REM", source="L1", pd=PD_HIGH_A, rwa=SPLIT_REM_RWA, ead=400_000.0),
    ]
    legacy = [
        *(_leg(ref, pd=pd, rwa=rwa, supplies_source_ref=False) for ref, pd, rwa in bands),
        _leg(
            "L1",
            pd=PD_HIGH_A,
            rwa=SPLIT_G_RWA + SPLIT_REM_RWA,
            ead=1_000_000.0,
            supplies_source_ref=False,
        ),
    ]
    return rr.build_comparison(
        f"split-{framework}", _source(ours, framework), _source(legacy, framework)
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_view_pairs_a_split_exposure_against_the_legacy_whole_loan(framework: str) -> None:
    """The page must not tell an analyst that an agreeing loan is missing twice.

    Our sealed ledger holds a guaranteed loan as two legs under one base
    reference; their extract holds it whole under the original one. Keyed on
    ``exposure_reference`` alone the two never meet, so a cell where both sides
    agree to the penny renders GBP 100,000 leaving our population and GBP
    100,000 arriving in theirs — and the waterfall still reconciles, because the
    two terms net.

    Asserted through ``build_comparison`` because that is where production
    enters, and on the rendered ``steps`` because that is what the analyst
    reads. The pair table is asserted to collapse our two legs into ONE row
    carrying both sides' money: the page's unit is the exposure, and a table
    that still showed two of our legs against one of theirs would put the
    reader straight back into the arithmetic the keying fix removed.
    """
    # Arrange
    recon = _split_recon(framework)
    row_ref = _row_of(recon, "L1", ours=False)

    # Act
    explanation = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, RWEA_COL)
    steps = {step.name: step for step in explanation.steps}

    # Assert — the cell is decomposed, both sides carry a figure, and they agree.
    assert not explanation.refused, explanation.refusal
    assert explanation.ours.value == pytest.approx(SPLIT_G_RWA + SPLIT_REM_RWA)
    assert explanation.theirs.value == pytest.approx(SPLIT_G_RWA + SPLIT_REM_RWA)
    assert explanation.delta == pytest.approx(0.0)

    # Assert — and the page reports that agreement as agreement.
    assert steps["population_ours_only"].amount == 0.0
    assert steps["population_ours_only"].keys == 0
    assert steps["population_theirs_only"].amount == 0.0
    assert steps["population_theirs_only"].keys == 0
    assert steps["measurement"].keys == 1
    assert explanation.reconciles

    # Assert — ONE row for the exposure, carrying both sides' money and a
    # linkable key. Two rows here (or one with a blank side) would say the whole
    # loan is missing from one side, which is the finding the keying fix closed.
    rows = [row for row in explanation.pairs.rows if row.key == "L1"]
    assert len(rows) == 1, [row.key for row in explanation.pairs.rows]
    assert rows[0].ours.value == pytest.approx(SPLIT_G_RWA + SPLIT_REM_RWA)
    assert rows[0].theirs.value == pytest.approx(SPLIT_G_RWA + SPLIT_REM_RWA)
    assert rows[0].identified
    # Our side is two legs and theirs one, and the row says so rather than
    # hiding the split: the roles are read off the membership carriers.
    assert "role" in rows[0].placement


# =============================================================================
# Rule 4c — the exposures behind a cell are PAIRED, and ranked on contribution
# =============================================================================

#: The probe portfolio the ranking rule was measured on. Thirty loans that agree
#: to the penny at GBP 1,000,000 each, and seven exposures that drive the
#: difference: four small value breaks, one exposure on each side only, and one
#: band mover. EVERY driver is smaller than EVERY agreeing loan, which is the
#: whole point — ranked on size, not one of them reaches a 25-row page, and the
#: per-side listing this replaced rendered 50 rows of exact agreement.
PROBE_AGREE_RWA = 1_000_000.0
PROBE_AGREE_COUNT = 30
PROBE_BREAK_OURS, PROBE_BREAK_THEIRS = 12_000.0, 10_000.0
PROBE_BREAK_COUNT = 4
PROBE_ONLY_OURS = 15_000.0
PROBE_ONLY_THEIRS = 12_000.0
PROBE_MOVER = 210_000.0
PROBE_DELTA = (
    PROBE_BREAK_COUNT * (PROBE_BREAK_OURS - PROBE_BREAK_THEIRS)
    + PROBE_ONLY_OURS
    - PROBE_ONLY_THEIRS
    + PROBE_MOVER
)
#: What survives once the mover's two cells cancel across the sheet: the mover
#: contributes +210,000 to the row it left and -210,000 to the row it arrived
#: in, so the sheet residual is the money that is genuinely one-sided plus the
#: value breaks. It is NOT zero, which is what makes the "does not net" branch
#: of the conservation line testable at all.
PROBE_SHEET_RESIDUAL = PROBE_DELTA - PROBE_MOVER
#: In |delta| order, ties broken on the key — the order the page must produce.
PROBE_DRIVERS: tuple[str, ...] = (
    "MOVER",
    "ONLY_OURS",
    "ONLY_THEIRS",
    *(f"BRK{index}" for index in range(PROBE_BREAK_COUNT)),
)

#: Positional column indices of the rendered pair table. Named because the point
#: of these tests is that a value lands in the cell that MEANS it: a test that
#: asserts a word appears somewhere on the page passes while the template puts
#: it in the wrong column, which has already happened in this batch.
COL_EXPOSURE, COL_CAUSE, COL_OURS, COL_THEIRS, COL_DELTA = range(5)

_TEMPLATE_HTML = (
    Path(rr.__file__).resolve().parents[1] / "app" / "templates" / "recon_templates.html"
)


def _probe_legs(framework: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The probe portfolio's two sides.

    The base legs are included so every PD band has two populated children —
    without them the parent band is INDISTINGUISHABLE from a leaf, comes back
    with a NULL ``is_parent_row``, and the cell has no provable leaf row to
    address at all (measured: ``_row_of`` finds zero rows).
    """
    ours = [
        *_base_legs(),
        *(
            _leg(f"P{index:02d}", pd=PD_MID, rwa=PROBE_AGREE_RWA)
            for index in range(PROBE_AGREE_COUNT)
        ),
    ]
    theirs = list(ours)
    for index in range(PROBE_BREAK_COUNT):
        ours.append(_leg(f"BRK{index}", pd=PD_MID, rwa=PROBE_BREAK_OURS))
        theirs.append(_leg(f"BRK{index}", pd=PD_MID, rwa=PROBE_BREAK_THEIRS))
    ours.append(_leg("ONLY_OURS", pd=PD_MID, rwa=PROBE_ONLY_OURS))
    theirs.append(_leg("ONLY_THEIRS", pd=PD_MID, rwa=PROBE_ONLY_THEIRS))
    ours.append(_leg("MOVER", pd=PD_MID, rwa=PROBE_MOVER))
    theirs.append(_leg("MOVER", pd=PD_HIGH_B, rwa=PROBE_MOVER))
    return ours, theirs


@lru_cache(maxsize=8)
def _probe(framework: str = "CRR") -> ReturnRecon:
    ours, theirs = _probe_legs(framework)
    return build_recon(_source(ours, framework), _source(theirs, framework))


def _probe_row(framework: str = "CRR") -> str:
    """The leaf row the whole probe population sits in on OUR side."""
    return _row_of(_probe(framework), "MOVER", ours=True)


def _probe_cell(framework: str = "CRR") -> CellDecomposition:
    """The probe's RWEA cell — an additive money cell, which is the precondition
    ``sheet_conservation`` takes the decomposition in order to check."""
    return decompose_cell(_probe(framework), TEMPLATE, SHEET, _probe_row(framework), RWEA_COL)


class _ProbeResponse:
    """The fields the templates ROUTE reads off a ``ReconciliationResponse``."""

    def __init__(self, ours: object, theirs: object, coverage: object = None) -> None:
        self.success = True
        self.errors: tuple[object, ...] = ()
        self.framework = getattr(ours, "framework", "CRR")
        self.calculation = ours
        self.legacy_ledger = theirs
        self.legacy_ledger_coverage = coverage


@pytest.fixture
def client() -> TestClient:
    return TestClient(ui_main.create_app(), base_url="http://localhost")


def _register_probe(recon_id: str, framework: str = "CRR") -> None:
    ours, theirs = _probe_legs(framework)
    register_reconciliation_with_id(
        recon_id,
        _ProbeResponse(_source(ours, framework), _source(theirs, framework)),  # type: ignore[arg-type]
    )


def _cell_page(client: TestClient, recon_id: str, *, row: str, col: str, **extra: str) -> str:
    """The rendered template-compare page for one cell, through the ROUTE.

    Through the route rather than through a hand-built Jinja context, because a
    context assembled in the test could only ever agree with itself: the keys
    ``recon_templates.html`` reads are ``main.py``'s to supply, and a link built
    from a key this test invented would render and mean nothing.
    """
    params = {"template": TEMPLATE, "sheet": SHEET, "row": row, "col": col, **extra}
    response = client.get(f"/reconciliation/{recon_id}/templates", params=params)
    assert response.status_code == 200, response.text[:400]
    return response.text


_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)


def _cell_text(fragment: str) -> str:
    """One ``<td>``'s visible text: tags stripped, entities decoded, collapsed."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _table_rows(html: str, name: str) -> list[list[str]]:
    """Every ``<td>`` of one identified table, row by row and column by column.

    Positional by construction, which is the whole reason these tests read the
    rendered page rather than the view object: asserting a word appears
    somewhere on a page is not asserting it appears in the cell that means it.
    """
    match = re.search(rf'<table[^>]*data-table="{name}"[^>]*>(.*?)</table>', html, re.DOTALL)
    assert match is not None, f"the page renders no table marked data-table={name!r}"
    return [
        [_cell_text(cell) for cell in _CELL_RE.findall(row)]
        for row in _ROW_RE.findall(match.group(1))
        if _CELL_RE.search(row)
    ]


def _pairs_note(html: str) -> str:
    """The line that says what the pair table is showing and what it is not."""
    match = re.search(r'<p class="muted" data-pairs="note">(.*?)</p>', html, re.DOTALL)
    assert match is not None, "the pair table publishes no note"
    return _cell_text(match.group(1))


def _term_link(html: str, term: str) -> str:
    """The href the waterfall's row for *term* links to."""
    match = re.search(rf'<tr data-term="{term}"[^>]*>\s*<td><a href="([^"]+)"', html)
    assert match is not None, f"the waterfall renders no linked row for {term!r}"
    return unescape(match.group(1))


def _exposure_link(html: str, reference: str) -> str:
    """The loan href the pair table builds for one exposure."""
    match = re.search(rf'<a href="([^"]*key={reference}[^"]*)"', html)
    assert match is not None, f"the pair table links no exposure named {reference!r}"
    return unescape(match.group(1))


def test_the_pair_table_puts_every_driver_of_the_difference_on_the_page(
    client: TestClient,
) -> None:
    """The measured failure this replaces: 50 rows, every one an agreeing loan.

    The old panel read each side's membership independently, sorted each on
    ``|rwa_final|`` and capped each at 25, so on a cell whose difference lives in
    the small loans it rendered two full pages of exact agreement and not one of
    the exposures driving the number. Asserted on the RENDERED page, by column
    position, because the value has to land in the cell that means it.
    """
    # Arrange — fixture adequacy FIRST. A probe that could not hide its drivers
    # under a size ranking would make this test pass under the old code too.
    assert PROBE_AGREE_COUNT > CELL_PAIRS_LIMIT > len(PROBE_DRIVERS), (
        "the probe must hold more agreeing loans than the page has rows, and "
        "more rows than it has drivers — otherwise a size-ranked page would "
        "show the drivers anyway and this test would prove nothing"
    )
    largest_driver = max(PROBE_MOVER, PROBE_ONLY_OURS, PROBE_ONLY_THEIRS, PROBE_BREAK_OURS)
    assert largest_driver < PROBE_AGREE_RWA, (
        "every driver must be SMALLER than every agreeing loan; a driver that "
        "is also the largest loan on the sheet is found by any ranking"
    )
    _register_probe("probe-rank")

    # Act
    body = _cell_page(client, "probe-rank", row=_probe_row(), col=RWEA_COL)
    rows = _table_rows(body, "cell-pairs")

    # Assert — the page is full, and the drivers are the TOP of it, in order.
    assert len(rows) == CELL_PAIRS_LIMIT
    assert [row[COL_EXPOSURE] for row in rows][: len(PROBE_DRIVERS)] == list(PROBE_DRIVERS)

    # Assert — positionally, on the cells that carry the numbers.
    mover = rows[0]
    assert mover[COL_CAUSE] == rr.TERM_LABELS["row_placement"]
    assert mover[COL_OURS] == "210,000"
    assert mover[COL_DELTA] == "+210,000"
    breaks = [row for row in rows if row[COL_EXPOSURE].startswith("BRK")]
    assert len(breaks) == PROBE_BREAK_COUNT
    for row in breaks:
        assert row[COL_CAUSE] == rr.TERM_LABELS["measurement"]
        assert row[COL_OURS] == "12,000"
        assert row[COL_THEIRS] == "10,000"
        assert row[COL_DELTA] == "+2,000"


def test_a_side_that_holds_no_leg_says_so_rather_than_rendering_a_blank(
    client: TestClient,
) -> None:
    """A one-sided exposure is the case a blank cell silently turns into a tie."""
    # Arrange
    _register_probe("probe-blank")
    glyph, _css, _title = rr.PAIR_STATE_DISPLAY[rr.NOT_HELD_STATE]

    # Act
    rows = _table_rows(
        _cell_page(client, "probe-blank", row=_probe_row(), col=RWEA_COL), "cell-pairs"
    )
    ours_only = next(row for row in rows if row[COL_EXPOSURE] == "ONLY_OURS")
    theirs_only = next(row for row in rows if row[COL_EXPOSURE] == "ONLY_THEIRS")

    # Assert — the absent side is explicit, on the side that is absent, and is
    # neither empty (which reads as agreement) nor a zero (a nil holding).
    assert ours_only[COL_THEIRS] == glyph
    assert ours_only[COL_OURS] == "15,000"
    assert theirs_only[COL_OURS] == glyph
    assert theirs_only[COL_THEIRS] == "12,000"
    for row in (ours_only, theirs_only):
        assert glyph not in {"", "0", "0.0", "0.00"}
        assert row[COL_DELTA] not in {"", "0"}


def test_the_pair_vocabulary_extends_the_cell_states_rather_than_replacing_them() -> None:
    # Assert — every ``CellState`` keeps its EXACT rendering, and the fifth
    # state is an addition. A parallel vocabulary is how one blank comes to mean
    # two things two panels apart on the same page.
    assert set(rr.PAIR_STATE_DISPLAY) == set(rr.STATE_DISPLAY) | {rr.NOT_HELD_STATE}
    for state, rendering in rr.STATE_DISPLAY.items():
        assert rr.PAIR_STATE_DISPLAY[state] == rendering
    glyphs = [glyph for glyph, _css, _title in rr.PAIR_STATE_DISPLAY.values()]
    classes = [css for _glyph, css, _title in rr.PAIR_STATE_DISPLAY.values()]
    assert len(set(glyphs)) == len(glyphs)
    assert len(set(classes)) == len(classes)


def test_every_pair_state_looks_different_in_the_template() -> None:
    """A vocabulary the stylesheet renders alike is one blank, not five."""
    # Arrange — read the template's own map rather than restating it.
    block = re.search(
        r"\{% set STATE_STYLE = \{(.*?)\} %\}",
        _TEMPLATE_HTML.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None, "recon_templates.html declares no STATE_STYLE map"
    styles = dict(re.findall(r'"([\w-]+)":\s*"([^"]*)"', block.group(1)))

    # Assert — every state the view can emit has a style, and the four non-figure
    # states are pairwise distinct.
    classes = {css for _glyph, css, _title in rr.PAIR_STATE_DISPLAY.values()}
    assert classes <= set(styles), classes - set(styles)
    rendered = [styles[css] for css in sorted(classes) if css != "is-figure"]
    assert len(set(rendered)) == len(rendered)


def test_clicking_a_cause_narrows_the_table_to_that_cause(client: TestClient) -> None:
    """The join between the two halves of the panel, followed for real."""
    # Arrange
    _register_probe("probe-filter")
    body = _cell_page(client, "probe-filter", row=_probe_row(), col=RWEA_COL)
    assert len({row[COL_CAUSE] for row in _table_rows(body, "cell-pairs")}) > 1, (
        "the unfiltered table shows one cause only, so narrowing it to one "
        "cause could not be told from not narrowing it"
    )

    # Act — follow the waterfall row's own link rather than building one.
    filtered = client.get(_term_link(body, "row_placement"))

    # Assert — the table is that cause and only that cause, and the waterfall
    # says which row is selected.
    assert filtered.status_code == 200
    rows = _table_rows(filtered.text, "cell-pairs")
    assert {row[COL_CAUSE] for row in rows} == {rr.TERM_LABELS["row_placement"]}
    assert [row[COL_EXPOSURE] for row in rows] == ["MOVER"]
    assert re.search(r'<tr data-term="row_placement" data-selected="true"', filtered.text)
    # ... and the split above it is still the WHOLE cell's, so the narrowed
    # table is read against the full picture rather than replacing it.
    assert len(_table_rows(filtered.text, "waterfall")) == len(TERM_NAMES) + 1


def test_an_unknown_cause_falls_back_to_every_cause_rather_than_failing(
    client: TestClient,
) -> None:
    """A hand-edited URL renders the default view, and SAYS that it did.

    ``cell_pairs`` raises on an unknown term — correctly, since filtering to an
    empty table is a silent zero — so the view has to absorb it. The fallback is
    only safe because the page names the filter it is showing: a wider table
    standing in silently for a narrower one is the failure mode here.
    """
    # Arrange
    _register_probe("probe-unknown-term")

    # Act
    body = _cell_page(
        client, "probe-unknown-term", row=_probe_row(), col=RWEA_COL, term="not_a_cause"
    )

    # Assert
    rows = _table_rows(body, "cell-pairs")
    assert len({row[COL_CAUSE] for row in rows}) > 1
    assert rr.EVERY_CAUSE in body
    assert "not_a_cause" not in body


def test_the_cap_states_what_it_hid(client: TestClient) -> None:
    """A silent cap on a regulatory comparison is a silent zero by another name."""
    # Arrange
    recon = _probe()
    row_ref = _probe_row()
    table = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, RWEA_COL).pairs
    assert table.hidden_keys > 0, (
        "the cap is not engaged on this fixture, so the note would be about "
        "nothing and this test would prove nothing"
    )

    # Assert — the arithmetic ties, and the whole scope is reported, not the page.
    assert table.keys == len(table.rows) + table.hidden_keys
    assert table.total_delta == pytest.approx(PROBE_DELTA)
    assert table.hidden_delta == pytest.approx(table.total_delta - table.shown_delta)

    # Assert — uncapped, the same total comes out of a table that hides nothing.
    whole = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, RWEA_COL, limit=None).pairs
    assert whole.hidden_keys == 0
    assert len(whole.rows) == table.keys
    assert whole.total_delta == pytest.approx(table.total_delta)

    # Assert — and the PAGE says all four numbers.
    _register_probe("probe-cap")
    note = _pairs_note(_cell_page(client, "probe-cap", row=row_ref, col=RWEA_COL))
    assert f"{len(table.rows):,}" in note
    assert f"{table.hidden_keys:,}" in note
    assert rr._signed(table.shown_delta) in note
    assert rr._signed(table.total_delta) in note


def test_a_refused_cell_renders_no_pair_table_and_still_carries_its_reason(
    client: TestClient,
) -> None:
    """``pairs == ()`` must never read as "no contract drives this difference"."""
    # Arrange — column 0050 is a weighted average, which is not decomposable.
    _register_probe("probe-refused")

    # Act
    body = _cell_page(client, "probe-refused", row=_probe_row(), col="0050")

    # Assert — no table at all, and a note that says REFUSAL rather than empty.
    assert 'data-table="cell-pairs"' not in body
    note = _pairs_note(body)
    assert "REFUSAL" in note
    assert "empty population" in note


def test_a_coverage_unavailable_cell_renders_no_pair_table(client: TestClient) -> None:
    """The false-zero cell: pairing it would show our loans against their 0.00.

    Their mapping cannot populate this column at all, so a table of "theirs: not
    held" rows against it would invite an analyst to reconcile a column their
    engine was never asked about.
    """
    # Arrange — the thin projection plus the coverage record that names it.
    legs = _base_legs()
    register_reconciliation_with_id(
        "probe-coverage",
        _ProbeResponse(_source(legs, "CRR"), _thin_ledger(legs), _thin_coverage()),  # type: ignore[arg-type]
    )
    row_ref = _row_of(
        rr.build_comparison(
            "probe-coverage-row",
            _source(legs, "CRR"),
            _thin_ledger(legs),
            theirs_coverage=_thin_coverage(),
        ),
        "A1",
        ours=True,
    )

    # Act
    body = _cell_page(client, "probe-coverage", row=row_ref, col=GROSS_COL)

    # Assert — refused, no table, and the reason travels with the empty table.
    assert 'data-refusal="coverage"' in body
    assert 'data-table="cell-pairs"' not in body
    assert "REFUSAL" in _pairs_note(body)


def test_the_loan_link_returns_to_the_cell_it_came_from(client: TestClient) -> None:
    """The breadcrumb is an explicit signal, and it survives the origin guard."""
    # Arrange
    _register_probe("probe-return")
    row_ref = _probe_row()

    # Act
    body = _cell_page(client, "probe-return", row=row_ref, col=RWEA_COL)
    href = _exposure_link(body, "MOVER")
    query = parse_qs(urlsplit(href).query)

    # Assert — the link carries the cell, not just the key.
    assert query["key"] == ["MOVER"]
    target = query["return_to"][0]
    assert urlsplit(target).path == "/reconciliation/probe-return/templates"
    back = parse_qs(urlsplit(target).query)
    assert back["row"] == [row_ref]
    assert back["col"] == [RWEA_COL]
    assert back["template"] == [TEMPLATE]

    # Assert — and the guard the loan route puts it through ACCEPTS it. A link
    # the template builds and the guard then discards is worse than no link:
    # the page would look wired up and silently fall back to the explorer.
    assert ui_main._safe_return_to(target, "/reconciliation/probe-return/rows") == target


def test_the_referer_breadcrumb_still_works_without_an_explicit_return_to() -> None:
    """The explicit parameter is an ADDED signal, not a replacement for a guard.

    Every OTHER entry point to the loan forensic — the explorer's rows, the
    sign-off worklist, a hand-typed link — appends no ``return_to``, and the
    same-origin ``Referer`` is what carries their breadcrumb. This item is the
    one that could plausibly have deleted that as redundant, so it is asserted
    here rather than left to the file that owns the loan route.
    """
    # Arrange — a same-origin referrer naming a template cell.
    cell = "/reconciliation/r1/templates?template=c08_03&row=0030&col=0090"
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/reconciliation/r1/loan",
        "raw_path": b"/reconciliation/r1/loan",
        "query_string": b"key=L1",
        "root_path": "",
        "server": ("localhost", 80),
        "headers": [(b"host", b"localhost"), (b"referer", f"http://localhost{cell}".encode())],
    }

    # Act / Assert — no explicit parameter, and the cell still comes back.
    assert ui_main._loan_return_to(Request(scope), "r1", "") == cell


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_moved_row_nets_across_the_sheet_and_a_one_sided_exposure_does_not(
    framework: str,
) -> None:
    """The sheet line, on the two cases it exists to tell apart.

    Parametrised over both frameworks because the row axis itself differs — CRR
    bands C 08.03 in 17 rows and Basel 3.1 in 18 — so a leaf-scoped sum that
    happened to work on one scale is not evidence about the other.
    """
    # Arrange — a portfolio whose ONLY difference is a leg in a different band.
    ours = [*_base_legs(), _leg("MOVER", pd=PD_MID, rwa=RWA_MOVER)]
    theirs = [*_base_legs(), _leg("MOVER", pd=PD_HIGH_B, rwa=RWA_MOVER)]
    moved = build_recon(_source(ours, framework), _source(theirs, framework))
    row_ref = _row_of(moved, "MOVER", ours=True)

    # Adequacy — the CELL must differ, or "the sheet nets" is trivially true of
    # a portfolio in which nothing differs anywhere.
    cell = decompose_cell(moved, TEMPLATE, SHEET, row_ref, RWEA_COL)
    assert cell.delta == pytest.approx(RWA_MOVER)

    # Act
    conservation = rr.sheet_conservation(moved, TEMPLATE, SHEET, cell)

    # Assert — a move nets: it lands in two cells of one sheet with opposite signs.
    assert conservation is not None
    assert conservation.decidable
    assert conservation.conserves
    assert conservation.delta == pytest.approx(0.0)
    assert conservation.leaf_rows >= 2

    # Assert — and a genuinely one-sided population does not net, by exactly the
    # money that is one-sided plus the values the two sides disagree about.
    probe = rr.sheet_conservation(_probe(framework), TEMPLATE, SHEET, _probe_cell(framework))
    assert probe is not None
    assert probe.decidable
    assert not probe.conserves
    assert probe.delta == pytest.approx(PROBE_SHEET_RESIDUAL)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_sheet_total_excludes_the_rows_that_would_double_count(framework: str) -> None:
    """This row axis overlaps; summing every emitted row double-counts."""
    # Act
    conservation = rr.sheet_conservation(_probe(framework), TEMPLATE, SHEET, _probe_cell(framework))
    assert conservation is not None

    # Adequacy — a sheet with nothing to exclude cannot exercise the guard.
    assert conservation.excluded_rows > 0, (
        "no parent or indistinguishable row was excluded on this fixture, so "
        "the double-count guard is not engaged and this test proves nothing"
    )

    # Assert — the naive sum over EVERY emitted row is a different number, so
    # the exclusion is doing work rather than being decorative.
    naive = diff_cells(_probe(framework), TEMPLATE, SHEET).filter(pl.col("col_ref") == RWEA_COL)
    assert float(naive.get_column("delta").sum()) != pytest.approx(conservation.delta)
    assert conservation.leaf_rows + conservation.excluded_rows == naive.height


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_non_additive_column_gets_no_sheet_total_at_all(framework: str) -> None:
    """A sheet total is a SUM, and a sum down a column of averages has no referent.

    Found by rendering the panel and reading it: column 0050 is an
    exposure-weighted average PD, and the page reported "the sheet total is
    +0.0000" and "column 0050 NETS across this sheet" — the same fabricated
    number ``decompose_cell`` refuses to produce for the same reason, wearing a
    total's clothes instead of a waterfall's.
    """
    # Arrange
    recon = _probe(framework)
    row_ref = _probe_row(framework)
    average = decompose_cell(recon, TEMPLATE, SHEET, row_ref, "0050")

    # Adequacy — 0050 must really be the non-additive case, not merely absent.
    assert average.metric == "weighted_avg", average.metric
    assert average.kind == "rows"

    # Assert — refused outright, and the refusal reaches the explanation.
    assert rr.sheet_conservation(recon, TEMPLATE, SHEET, average) is None
    assert rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0050").conservation is None
    # ... while the additive column beside it still gets one, so "None" is a
    # statement about the metric rather than about this sheet.
    assert rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, RWEA_COL).conservation is not None


def test_a_refused_cell_renders_no_sheet_total_it_cannot_state(client: TestClient) -> None:
    # Arrange
    _register_probe("probe-noscope")

    # Act — the weighted-average column, refused.
    body = _cell_page(client, "probe-noscope", row=_probe_row(), col="0050")

    # Assert — no verdict block at all, rather than a netting one.
    assert "data-conservation=" not in body
    assert "sheet total" not in body


def test_the_page_states_that_the_waterfall_is_not_a_scope_check(client: TestClient) -> None:
    # Arrange
    _register_probe("probe-scope")

    # Act
    body = _cell_page(client, "probe-scope", row=_probe_row(), col=RWEA_COL)

    # Assert — the verdict is marked, the figure is rendered, and the sentence
    # that stops the waterfall being read as a scope check is on the page.
    assert 'data-conservation="breaks"' in body
    assert "not a scope check" in body
    match = re.search(r'data-conservation-delta="true">([^<]*)<', body)
    assert match is not None
    assert _cell_text(match.group(1)) == rr._signed(PROBE_SHEET_RESIDUAL)


def test_an_unmeasurable_column_is_not_netted_to_a_confident_total() -> None:
    """A total over PART of a column reads exactly like a total over all of it."""
    # Arrange — the thin projection: this column is unpopulatable on their side.
    legs = _base_legs()
    recon = rr.build_comparison(
        "probe-undecidable",
        _source(legs, "CRR"),
        _thin_ledger(legs),
        theirs_coverage=_thin_coverage(),
    )

    # Act
    row_ref = _row_of(recon, "A1", ours=True)
    conservation = rr.sheet_conservation(
        recon, TEMPLATE, SHEET, decompose_cell(recon, TEMPLATE, SHEET, row_ref, GROSS_COL)
    )

    # Assert — no verdict, no figure, and the count of what blocked it.
    assert conservation is not None
    assert not conservation.decidable
    assert not conservation.conserves
    assert conservation.delta is None
    assert conservation.display == rr.UNMEASURABLE_DISPLAY
    assert conservation.unmeasurable_rows > 0


# =============================================================================
# Rule 5 — the migration matrix, and what it must never sum
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_matrix_diagonal_is_agreement_and_the_off_diagonal_is_the_mover(
    framework: str,
) -> None:
    # Arrange
    recon = _recon(framework)
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    assert len(groups) == 1, "C 08.03 rows carry one predicate group"
    matrix = rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key)
    assert matrix is not None
    our_row = _row_of(recon, "MOVER", ours=True)
    their_row = _row_of(recon, "MOVER", ours=False)
    assert our_row != their_row, "the mover must actually move for this to test anything"

    # Act
    by_pair = {
        (cell.our_row_ref, cell.their_row_ref): cell
        for row in matrix.cells
        for cell in row
        if cell is not None
    }

    # Assert — the mover sits off the diagonal, priced, and labelled value-driven.
    moved = by_pair[(our_row, their_row)]
    assert moved.money == pytest.approx(RWA_MOVER)
    assert moved.basis == "value_driven"
    assert not moved.is_diagonal
    # ... and every diagonal cell is agreement.
    for (ours, theirs), cell in by_pair.items():
        if ours == theirs and ours not in {ABSENT_ROW, UNDECIDABLE_ROW}:
            assert cell.basis == "agreed"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_matrix_conserves_money_on_both_sides(framework: str) -> None:
    # Arrange
    recon = _recon(framework)
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    matrix = rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key)
    assert matrix is not None
    cells = [cell for row in matrix.cells for cell in row if cell is not None]

    # Act
    ours = sum(cell.money_ours or 0.0 for cell in cells)
    theirs = sum(cell.money_theirs or 0.0 for cell in cells)

    # Assert — EQUALITIES against the fixture's own totals, on BOTH sides. A
    # one-sided bound would pass while a whole side read 0.00.
    assert ours == pytest.approx(AGREED_RWA + RWA_MOVER + RWA_OURS_ONLY)
    assert theirs == pytest.approx(AGREED_RWA + RWA_MOVER + RWA_THEIRS_ONLY)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_movement_classes_partition_the_population(framework: str) -> None:
    # Arrange
    recon = _recon(framework)
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    matrix = rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key)
    assert matrix is not None

    # Assert — each class is the fixture's own figure, and none is a row sum.
    assert matrix.totals.agreed == pytest.approx(AGREED_RWA)
    assert matrix.totals.moved == pytest.approx(RWA_MOVER)
    assert matrix.totals.ours_only == pytest.approx(RWA_OURS_ONLY)
    assert matrix.totals.theirs_only == pytest.approx(RWA_THEIRS_ONLY)
    assert matrix.totals.undecidable == pytest.approx(0.0)
    assert matrix.axis_is_partition


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_matrix_carries_the_value_driven_attribution_verbatim(framework: str) -> None:
    # Assert — a reader must not take an off-diagonal as evidence about their
    # BANDING RULE; that difference is structurally invisible on this path.
    recon = _recon(framework)
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    matrix = rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key)
    assert matrix is not None
    assert matrix.attribution == PLACEMENT_ATTRIBUTION


def test_a_matrix_is_scoped_to_one_predicate_key_and_names_it() -> None:
    # Assert — the API cannot express a matrix over several groups, which is
    # what stops a consumer summing across BASES (measured at 3.00x and 1.86x).
    recon = _recon("CRR")
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    matrix = rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key)
    assert matrix is not None
    assert matrix.predicate_key == groups[0].predicate_key
    assert set(matrix.columns) <= set(groups[0].columns)


def test_an_unknown_money_column_is_a_programming_error() -> None:
    recon = _recon("CRR")
    groups = rr.migration_groups(recon, TEMPLATE, SHEET)
    with pytest.raises(ValueError, match="money_column"):
        rr.migration_matrix(recon, TEMPLATE, SHEET, groups[0].predicate_key, money_column="ead")


# =============================================================================
# The tri-state parent flag
# =============================================================================


@pytest.mark.parametrize("parent", [True, None])
def test_a_parent_or_indistinguishable_row_is_never_reported_as_a_leaf(
    parent: bool | None,
) -> None:
    # Assert — NULL means "may double count", which is the safe reading.
    note = rr._parent_note(parent).lower().replace("-", " ")
    assert "double count" in note


def test_a_provable_leaf_says_so() -> None:
    assert "no other row" in rr._parent_note(parent=False)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_explanation_reports_the_parent_flag_as_measured(framework: str) -> None:
    # Arrange — the C 08.03 parent bands strictly contain their children here.
    recon = _recon(framework)
    row_ref = _row_of(recon, "MOVER", ours=True)

    # Act
    explanation = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0090")

    # Assert — tri-state, never coerced to a boolean.
    assert explanation.row_is_parent in {True, False, None}
    assert explanation.row_is_parent is False
    assert explanation.parent_note


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_cell_reads_the_one_group_that_serves_it(framework: str) -> None:
    # Arrange
    recon = _recon(framework)
    row_ref = _row_of(recon, "MOVER", ours=True)

    # Act
    explanation = rr.explain_cell(recon, TEMPLATE, SHEET, row_ref, "0090")

    # Assert — the population is addressed through the column mapping, and the
    # exposures paired beneath it are that group's, not the row's several.
    assert explanation.predicate_key
    served = rr._group_columns(recon.ours, TEMPLATE, SHEET).filter(
        (pl.col("row_ref") == row_ref) & (pl.col("col_ref") == "0090")
    )
    assert served.height >= 1
    assert str(served["predicate_key"][0]) == explanation.predicate_key
    assert {row.key for row in explanation.pairs.rows} >= {"MOVER"}


# =============================================================================
# Rule 6 — materiality is one threshold, set once
# =============================================================================


def test_materiality_needs_both_floors_cleared() -> None:
    threshold = rr.Materiality(absolute=1_000.0, percent=1.0)

    # Below the absolute floor: rounding, not a finding.
    assert not threshold.is_material(500.0, 500.0, 0.0)
    # Above the absolute floor but below the relative one: float dust.
    assert not threshold.is_material(5_000.0, 1_000_000.0, 995_000.0)
    # Above both.
    assert threshold.is_material(50_000.0, 1_000_000.0, 950_000.0)


def test_a_zero_or_absent_delta_is_never_material() -> None:
    threshold = rr.Materiality(absolute=0.0, percent=0.0)
    assert not threshold.is_material(0.0, 100.0, 100.0)
    assert not threshold.is_material(None, 100.0, None)


def test_float_dust_is_not_a_difference() -> None:
    """Two sums that agree to the arithmetic's own residue agreed exactly.

    Both floors are zero here, so nothing else can exclude the value: an exact
    ``== 0.0`` test would let a delta of 1e-12 through, and — because the base
    is then compared against zero — report it as 100% of the cell. The
    reconciliation engine settles the same question with the same epsilon.
    """
    threshold = rr.Materiality(absolute=0.0, percent=0.0)

    # Arrange / Act / Assert — dust on both the ordinary and the zero-base path.
    assert not threshold.is_material(1e-12, 100.0, 100.0)
    assert not threshold.is_material(-1e-12, 100.0, 100.0)
    assert not threshold.is_material(1e-12, 0.0, 0.0)

    # A delta genuinely above the dust floor still reports, so the guard has not
    # simply swallowed the small-delta case.
    assert threshold.is_material(1e-6, 100.0, 100.0)


def test_a_delta_against_a_zero_base_clears_the_relative_floor() -> None:
    # Assert — it is 100% of the cell; only the absolute floor can exclude it.
    threshold = rr.Materiality(absolute=1_000.0, percent=50.0)
    assert threshold.is_material(2_000.0, 2_000.0, 0.0)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_raising_the_floor_shrinks_the_worklist_without_losing_the_cells(
    framework: str,
) -> None:
    # Arrange
    recon = _recon(framework)
    loose = rr.sheet_compare(recon, TEMPLATE, SHEET, materiality=rr.Materiality(1.0, 0.0))
    strict = rr.sheet_compare(recon, TEMPLATE, SHEET, materiality=rr.Materiality(10_000_000.0, 0.0))
    assert loose is not None
    assert strict is not None

    # Assert — the threshold filters the RANKED list, never the grid.
    assert loose.material_count > strict.material_count
    assert strict.material_count == 0
    assert loose.cell_count == strict.cell_count
    assert all(cell.is_material for cell in loose.worst)


# =============================================================================
# The picker, the labels and the degraded page
# =============================================================================


@pytest.mark.parametrize(("framework", "expected"), [("CRR", "C 08.03"), ("BASEL_3_1", "OF 08.03")])
def test_a_template_is_labelled_for_the_run_framework(framework: str, expected: str) -> None:
    # Assert — the same generators are OF NN.NN under PS1/26.
    page = rr.template_page(_recon(framework), recon_id="r", framework=framework)
    labels = {option.id: option.label for option in page.templates}
    assert labels[TEMPLATE].startswith(expected)


def test_an_unknown_template_falls_back_rather_than_raising() -> None:
    page = rr.template_page(_recon("CRR"), recon_id="r", framework="CRR", template_id="c99_99")
    assert page.available
    assert page.selected is not None
    assert page.selected.id in {option.id for option in page.templates}


def test_an_unknown_sheet_falls_back_to_the_first() -> None:
    page = rr.template_page(
        _recon("CRR"), recon_id="r", framework="CRR", template_id=TEMPLATE, sheet="nope"
    )
    assert page.sheet == SHEET


def test_no_legacy_ledger_degrades_with_a_reason_and_a_remedy() -> None:
    # Act
    page = rr.template_page(
        None,
        recon_id="r",
        framework="CRR",
        coverage=_coverage(),
        unavailable_reason="",
        warnings=["[REC008] projection unavailable"],
    )

    # Assert — an explanation, not an error, and nothing pretending to compare.
    assert not page.available
    assert "no legacy ledger" in page.unavailable_reason
    assert page.compare is None
    assert page.matrix is None
    assert page.templates == ()
    assert page.warnings == ("[REC008] projection unavailable",)


def test_the_degraded_page_names_the_columns_to_map() -> None:
    page = rr.template_page(None, recon_id="r", framework="CRR", coverage=_coverage())
    assert any(UNMAPPED_REMEDY in line for line in page.remedies)


def test_an_unreachable_template_is_still_offered_with_the_blocking_columns() -> None:
    # Arrange — reachable_templates is empty, so nothing can be produced.
    coverage = replace(_coverage(), reachable_templates=frozenset())

    # Act
    options = rr.template_options(_recon("CRR"), coverage)

    # Assert — "map these columns" is an answer; a missing template is not.
    blocked = {option.id: option for option in options}
    assert not blocked[TEMPLATE].reachable
    assert blocked[TEMPLATE].blocked_reason
    assert blocked[TEMPLATE].state == "unreachable"


def test_a_reachable_but_unpopulated_template_is_not_a_mapping_problem() -> None:
    """ "Your book has no such exposures" and "your mapping is broken" are not
    the same sentence, and telling an all-standardised firm the second would
    send it chasing a fix that does not exist."""
    # Arrange — reachable everywhere, but the book carries only C 08.03's
    # population. C 08.01 is therefore reachable-and-unpopulated.
    coverage = replace(
        _coverage(),
        reachable_templates=frozenset({TEMPLATE, "c08_01", "c07_00"}),
        populated_templates=frozenset({TEMPLATE}),
    )

    # Act
    options = {option.id: option for option in rr.template_options(_recon("CRR"), coverage)}

    # Assert — reachable is decided on reachable_templates, never on
    # populated_templates; the two states read differently to the analyst.
    assert options["c08_01"].reachable
    assert options["c08_01"].populated is False
    assert options["c08_01"].state == "unpopulated"
    assert options["c08_01"].blocked_reason == ""
    assert "nothing to fix" in options["c08_01"].population_note
    assert options[TEMPLATE].state == "comparable"


def test_an_unmeasured_vocabulary_leaves_the_population_question_unanswered() -> None:
    # Assert — ``populated_templates`` None means the question was never asked,
    # and neither answer may be shown.
    coverage = replace(_coverage(), populated_templates=None)
    options = {option.id: option for option in rr.template_options(_recon("CRR"), coverage)}
    assert options[TEMPLATE].populated is None
    assert options[TEMPLATE].population_note == ""
    assert options[TEMPLATE].state == "comparable"


def test_an_unpopulated_template_is_not_rendered_as_unavailable_cells() -> None:
    # Assert — its cells are ORDINARY empties. Only unreachability makes a cell
    # unavailable, so a book with no such exposures never shows "not mapped".
    coverage = replace(
        _coverage(),
        unavailable_cells={},
        reachable_templates=frozenset({TEMPLATE}),
        populated_templates=frozenset(),
    )
    compare = rr.sheet_compare(_recon("CRR"), TEMPLATE, SHEET, coverage=coverage)
    assert compare is not None
    assert compare.unmeasurable_count == 0


# =============================================================================
# The one-comparison-per-request contract
# =============================================================================


def test_the_comparison_is_built_once_per_recon_id() -> None:
    # Arrange — generating a template bundle is expensive; a screenful of cells
    # must not cost one generation per cell.
    rr.clear_comparison_cache()
    legs = _base_legs()
    ours, theirs = _source(legs, "CRR"), _source(legs, "CRR")

    # Act
    first = rr.build_comparison("recon-1", ours, theirs)
    second = rr.build_comparison("recon-1", ours, theirs)

    # Assert
    assert first is second
    rr.clear_comparison_cache()


def test_the_cache_is_bounded() -> None:
    rr.clear_comparison_cache()
    legs = _base_legs()
    for index in range(rr._CACHE_LIMIT + 2):
        rr.build_comparison(f"recon-{index}", _source(legs, "CRR"), _source(legs, "CRR"))
    assert len(rr._CACHE) <= rr._CACHE_LIMIT
    rr.clear_comparison_cache()


# =============================================================================
# ``comparison_inputs`` — what the route degrades on
# =============================================================================


class _Response:
    """The two fields of a ``ReconciliationResponse`` this view reads."""

    def __init__(self, calculation: object, ledger: object, coverage: object = None) -> None:
        self.calculation = calculation
        self.legacy_ledger = ledger
        self.legacy_ledger_coverage = coverage


def test_comparison_inputs_reports_a_missing_ledger() -> None:
    inputs = rr.comparison_inputs(_Response(_source(_base_legs(), "CRR"), None))  # type: ignore[arg-type]
    assert inputs.ours is None
    assert inputs.theirs is None
    assert not inputs.comparable
    assert "no legacy ledger" in inputs.reason


def test_comparison_inputs_reports_a_missing_calculation() -> None:
    inputs = rr.comparison_inputs(_Response(None, _source(_base_legs(), "CRR")))  # type: ignore[arg-type]
    assert "no calculation results" in inputs.reason


def test_comparison_inputs_refuses_a_framework_mismatch() -> None:
    # Assert — two frameworks are two different templates; comparing them would
    # produce a large meaningless delta rather than an error.
    response = _Response(_source(_base_legs(), "CRR"), _source(_base_legs(), "BASEL_3_1"))
    assert "different frameworks" in rr.comparison_inputs(response).reason  # type: ignore[arg-type]


def test_comparison_inputs_carries_the_legacy_coverage_alongside_the_source() -> None:
    # Assert — the coverage travels WITH the side it guards. A call site that
    # has to fetch it separately is a call site that can forget to, and
    # forgetting disarms the false-zero guard entirely (see build_comparison).
    response = _Response(_source(_base_legs(), "CRR"), _source(_base_legs(), "CRR"), _coverage())
    inputs = rr.comparison_inputs(response)  # type: ignore[arg-type]
    assert inputs.comparable
    assert inputs.theirs_coverage is not None
    assert inputs.reason == ""
    # Our own side is the sealed output of a real run: no mapping, no coverage.
    # The field exists so an our-side projection would be guarded, not so it can
    # be hardcoded away at the call site.
    assert inputs.ours_coverage is None
