"""
Unit tests: the loan forensic's placement panel, key resolution and breadcrumb.

Pipeline position:
    ReconciliationResponse (+ the memoised ReturnRecon)
        -> ui.views.reconciliation -> recon_loan.html

Three trails break once an analyst reaches ``/reconciliation/{id}/loan``, and
each is asserted here against something that cannot drift with the code:

- **Where this exposure lands.** ``placement_panel`` answers the reverse lookup
  the template-compare page cannot: which ``(template, sheet, row)`` this key
  reached, OURS BESIDE THEIRS. The fixture is built so the same exposure lands
  in a DIFFERENT PD band on each side, and the assertions are stated against the
  row NAMES the generators emit ("0.10 to <0.15" vs "1.75 to <2.5"), not against
  refs — a panel that lost the move would have to invent the names to pass.
  A row reached on one side only asserts an explicit, non-blank display: this
  codebase's standing rule is that a blank is never a zero and the KINDS of
  blank are not each other.
- **``is_parent_row`` is TRI-STATE.** ``True`` / ``False`` / ``None`` are three
  different statements about a row, and the panel is asserted to keep them
  three: the leaf placement takes the single provably-``False`` row and refuses
  to place a leg whose only rows are parents or indistinguishable.
- **A composite join key must not dead-end.** ``recon_templates.html`` links a
  leg through on its exposure reference alone, while the loan route looks up
  ``_recon_key`` — a ``||``-joined concatenation of the mapping's ``our_keys``.
  ``resolve_recon_key`` is asserted on a REAL composite-key reconciliation, so
  a resolver that only ever sees the single-column default cannot pass.

References:
- analysis/reconciliation.py::_key_expr (the ``_recon_key`` grammar)
- reporting/membership.py::MEMBERSHIP_SCHEMA (the placement grain)
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
from fastapi.testclient import TestClient
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.analysis.legacy_ledger import LedgerCoverage
from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.analysis.reconciliation import ReconciliationRunner
from rwa_calc.analysis.return_recon import build_recon
from rwa_calc.api.models import CalculationResponse, ReconciliationResponse, SummaryStatistics
from rwa_calc.api.rest import register_reconciliation_with_id
from rwa_calc.ui.app.main import create_app
from rwa_calc.ui.app.recon_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.views import reconciliation as rv
from rwa_calc.ui.views import return_recon as rr

if TYPE_CHECKING:
    from collections.abc import Iterator

    from rwa_calc.analysis.return_recon import ReturnRecon

TEMPLATE = "c08_03"
SHEET = "corporate"

# Four PDs that land in four DIFFERENT rows of the CRR C 08.03 PD scale, chosen
# so that every parent band has two populated children — without that, a parent
# is indistinguishable from a leaf, comes back with a NULL flag, and the leaf
# assertions below would be vacuous rather than green.
PD_A, PD_B = 0.0003, 0.0012
PD_C, PD_D = 0.0100, 0.0200

# The rows those PDs reach, and the names the generator prints for them. Stated
# as the fixture's own expectations so a panel that dropped the names cannot
# pass by echoing a ref.
ROW_PARENT_LOW, ROW_LEAF_LOW = "0010", "0030"
ROW_PARENT_HIGH, ROW_LEAF_HIGH = "0070", "0090"
NAME_LEAF_LOW = "0.10 to <0.15"
NAME_LEAF_HIGH = "1.75 to <2.5"


# =============================================================================
# Fixtures — a two-sided comparison in which one exposure moved band
# =============================================================================


class _FrameSource:
    """A minimal ``ResultsSource`` over a hand-built sealed ledger."""

    def __init__(self, frame: pl.LazyFrame, framework: str = "CRR") -> None:
        self._frame = frame
        self.framework = framework

    def scan_results(self) -> pl.LazyFrame:
        return self._frame


def _leg(reference: str, *, pd: float, rwa: float) -> dict[str, object]:
    """One IRB leg in the raw shape the sealed reporting ledger derives from."""
    exposure = rwa * 3.0
    return {
        "exposure_reference": reference,
        "source_exposure_reference": reference,
        "counterparty_reference": f"CP_{reference}",
        "exposure_class": SHEET,
        "exposure_class_applied": SHEET,
        "exposure_class_post_crm": SHEET,
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


def _source(legs: list[dict[str, object]]) -> _FrameSource:
    frame = pl.LazyFrame(
        legs,
        schema_overrides={
            "pd": pl.Float64,
            "pd_floored": pl.Float64,
            "lgd_floored": pl.Float64,
            "irb_maturity_m": pl.Float64,
            "sa_cqs": pl.Int8,
        },
    )
    return _FrameSource(with_reporting_ledger(frame))


@lru_cache(maxsize=2)
def _recon() -> ReturnRecon:
    """Both sides, with three placements at once.

    ``AGREE`` lands in the same rows on both sides, ``MOVER`` lands in a
    different PD band on each, and ``ONLY_OURS`` exists on our side alone — the
    three answers the panel must keep distinct.
    """

    base = [
        _leg("AGREE", pd=PD_A, rwa=90_000.0),
        _leg("FILLER_LOW", pd=PD_B, rwa=300_000.0),
        _leg("FILLER_HIGH", pd=PD_C, rwa=500_000.0),
        _leg("FILLER_TOP", pd=PD_D, rwa=800_000.0),
    ]
    ours = [*base, _leg("MOVER", pd=PD_B, rwa=210_000.0), _leg("ONLY_OURS", pd=PD_B, rwa=1_000.0)]
    theirs = [*base, _leg("MOVER", pd=PD_D, rwa=210_000.0)]
    return build_recon(_source(ours), _source(theirs))


def _group(panel: rv.PlacementPanel, template_id: str = TEMPLATE) -> rv.PlacementGroup:
    """The panel's single group for one template (C 08.03 has one per sheet)."""
    groups = [g for g in panel.groups if g.template_id == template_id]
    assert groups, f"no placement group for {template_id}"
    return groups[0]


def _return_target(html: str) -> str:
    """The destination the loan page actually resolved, off the sign-off form.

    Read from the form's ``return_to`` rather than from the breadcrumb, because
    the breadcrumb is only rendered when the destination DIFFERS from the
    explorer — so its absence and its presence are both ambiguous on their own.
    """
    match = re.search(r'name="return_to" value="([^"]*)"', unescape(html))
    return match.group(1) if match else ""


def _placement_cells(html: str, row_ref: str, section: str = "C 08.03") -> list[str]:
    """The rendered ``<td>`` text of one placement row, in column order.

    Asserting that a word appears SOMEWHERE on the page is not asserting that it
    appears in the CELL that carries the claim — measured: mutating the template
    so the "theirs" hierarchy column rendered the OURS state left a page-level
    assertion green, because the correct word was still present in the row's
    note. Positional cells are what make the two states separable.

    SCOPED TO ONE GROUP'S TABLE, because the page renders several and their row
    refs overlap: an unscoped search for row 0010 found C 08.01's, whose flags
    are all indistinguishable, and asserted against C 08.03's expectations. The
    helper caught that on its first run, which is the argument for positional
    assertions over substring ones restated one level up.

    Tags are stripped from the raw HTML and each cell unescaped afterwards; doing
    it the other way round turns a row name like ``0.10 to &lt;0.15`` into
    something the tag stripper eats.
    """
    start = html.find(section, html.find("Where this exposure lands"))
    assert start != -1, f"no {section} placement group on the page"
    scoped = html[start:]
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", scoped, re.S):
        cells = [
            unescape(re.sub(r"<[^>]+>", "", cell)).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)
        ]
        if cells and cells[0] == row_ref:
            return cells
    return []


def _row(group: rv.PlacementGroup, row_ref: str) -> rv.PlacementRow:
    match = [r for r in group.rows if r.row_ref == row_ref]
    assert match, f"row {row_ref} not in {[r.row_ref for r in group.rows]}"
    return match[0]


# =============================================================================
# C-a — where this exposure lands
# =============================================================================


def test_placement_panel_pairs_our_rows_beside_theirs() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "AGREE")

    # Assert — an agreeing leg reaches the same rows on both sides, and every
    # row says so explicitly rather than by leaving a side blank.
    group = _group(panel)
    assert panel.available
    assert {r.row_ref for r in group.rows} == {ROW_PARENT_LOW, "0020"}
    assert all(r.in_ours and r.in_theirs for r in group.rows)
    assert {r.side for r in group.rows} == {rv.PLACEMENT_BOTH}


def test_a_move_reads_as_our_row_name_against_theirs() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "MOVER")

    # Assert — the whole point of the panel: the band it left and the band it
    # landed in, by NAME, on one line.
    group = _group(panel)
    assert group.moved
    assert group.our_placement_name == NAME_LEAF_LOW
    assert group.their_placement_name == NAME_LEAF_HIGH
    assert group.our_placement == ROW_LEAF_LOW
    assert group.their_placement == ROW_LEAF_HIGH


def test_a_row_reached_on_one_side_only_is_never_a_blank() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "MOVER")

    # Assert — the row we hold and they do not is labelled as OURS ONLY, and the
    # absent side carries an explicit display string. A blank there reads as
    # agreement, which is the failure this panel exists to prevent.
    group = _group(panel)
    ours_only = _row(group, ROW_LEAF_LOW)
    theirs_only = _row(group, ROW_LEAF_HIGH)
    assert ours_only.side == rv.PLACEMENT_OURS_ONLY
    assert theirs_only.side == rv.PLACEMENT_THEIRS_ONLY
    assert ours_only.their_display == rv.NOT_REACHED_DISPLAY
    assert theirs_only.our_display == rv.NOT_REACHED_DISPLAY
    assert rv.NOT_REACHED_DISPLAY.strip() != ""
    # Stated absolutely as well as relatively: the four assertions above are all
    # relative to the constants, so aliasing two of them together would leave
    # every one of them green while the page said the same thing about two
    # different findings. Measured — that mutation was silent until this line.
    assert ours_only.side != theirs_only.side
    assert len({rv.PLACEMENT_BOTH, rv.PLACEMENT_OURS_ONLY, rv.PLACEMENT_THEIRS_ONLY}) == 3


def test_an_exposure_only_we_hold_is_ours_only_on_every_row() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "ONLY_OURS")

    # Assert — their side holds the leg in no group at all, which is a finding,
    # not an empty panel.
    group = _group(panel)
    assert group.rows
    assert {r.side for r in group.rows} == {rv.PLACEMENT_OURS_ONLY}
    assert group.their_placement == ""
    assert group.their_placement_name == rv.NOT_REACHED_DISPLAY


def test_a_parent_row_is_never_presented_as_a_leaf() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "MOVER")

    # Assert — 0010 strictly contains 0030 in this group, so it is a PARENT and
    # is neither the placement nor labelled like one.
    group = _group(panel)
    parent = _row(group, ROW_PARENT_LOW)
    assert parent.our_parent is True
    assert parent.our_parent_state == rv.PARENT_ROW
    assert "parent" in parent.parent_note.casefold()
    assert group.our_placement != ROW_PARENT_LOW
    assert group.their_placement != ROW_PARENT_HIGH


def test_an_indistinguishable_row_is_reported_as_neither_leaf_nor_parent() -> None:
    # Arrange / Act — C 08.01's TOTAL / on-balance-sheet / obligor-grades rows
    # hold exactly the same legs here, so containment cannot decide between them.
    panel = rv.placement_panel(_recon(), "AGREE")

    # Assert — the NULL flag keeps its own third state, and no placement is
    # claimed from rows that cannot be ranked.
    group = _group(panel, "c08_01")
    assert {r.our_parent for r in group.rows} == {None}
    assert {r.our_parent_state for r in group.rows} == {rv.PARENT_INDISTINGUISHABLE}
    assert {r.their_parent_state for r in group.rows} == {rv.PARENT_INDISTINGUISHABLE}
    assert group.our_placement == ""
    assert not group.moved


def test_every_group_names_the_columns_its_population_serves() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "MOVER")

    # Assert — the reverse lookup has to land back on a CELL, so the group
    # carries the published columns its predicate group backs.
    group = _group(panel)
    assert group.columns
    assert "0010" in group.columns


def test_a_panel_with_no_comparison_degrades_with_the_reason() -> None:
    # Arrange / Act — the typed reason ``comparison_inputs`` already returns.
    panel = rv.placement_panel(None, "MOVER", reason="no legacy ledger")

    # Assert — an explanation, never an empty panel that reads as "landed nowhere".
    assert not panel.available
    assert panel.reason == "no legacy ledger"
    assert panel.groups == ()


@lru_cache(maxsize=2)
def _recon_split() -> ReturnRecon:
    """A real-estate split: two child legs under one parent reference.

    THE DOMINANT PRODUCTION SHAPE, and the one the panel would miss if it matched
    membership on ``exposure_reference`` alone. Under the default mapping the
    reconciliation collapses sub-rows back to the parent, so the loan page's key
    is ``M1`` while every membership leg carries ``M1_res`` / ``M1_cre``. Only
    ``source_exposure_reference`` joins the two.
    """
    legs = [
        _leg("FILLER_LOW", pd=PD_B, rwa=300_000.0),
        _leg("FILLER_HIGH", pd=PD_C, rwa=500_000.0),
        _leg("FILLER_TOP", pd=PD_D, rwa=800_000.0),
        _leg("M1_res", pd=PD_A, rwa=90_000.0) | {"source_exposure_reference": "M1"},
        _leg("M1_cre", pd=PD_B, rwa=60_000.0) | {"source_exposure_reference": "M1"},
    ]
    return build_recon(_source(legs), _source(legs))


def test_a_split_exposure_is_placed_by_its_parent_reference() -> None:
    # Arrange / Act — the key the loan page holds is the COLLAPSED parent, which
    # appears on no membership leg's ``exposure_reference``.
    panel = rv.placement_panel(_recon_split(), "M1")

    # Assert — both children's rows are found, under the one parent key.
    group = _group(panel)
    assert {r.row_ref for r in group.rows} >= {"0020", ROW_LEAF_LOW}
    assert all(r.side == rv.PLACEMENT_BOTH for r in group.rows)


def test_a_key_that_reaches_no_instrumented_row_is_not_an_unavailable_panel() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon(), "NOT_A_LOAN")

    # Assert — "the comparison could not be built" and "this exposure reached no
    # instrumented template row" are different answers and stay different.
    assert panel.available
    assert panel.groups == ()
    assert panel.reason == ""


# =============================================================================
# C-b — a composite join key must not dead-end
# =============================================================================


def _composite_response() -> ReconciliationResponse:
    """A reconciliation keyed on ``(exposure_reference, exposure_class)``.

    ``L3`` appears under two classes, so a link built from the reference alone is
    genuinely ambiguous — the case a resolver that always takes the first match
    would answer with the wrong loan.
    """
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3", "L3"],
            "source_exposure_reference": ["L1", "L2", "L3", "L3"],
            "exposure_class": ["corporate", "retail", "corporate", "retail"],
            "approach_applied": ["standardised"] * 4,
            "ead_final": [100.0, 200.0, 500.0, 50.0],
            "rwa_final": [50.0, 150.0, 250.0, 25.0],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3", "L3"],
            "legacy_exposure_class": ["corporate", "retail", "corporate", "retail"],
            "legacy_ead": [100.0, 200.0, 500.0, 50.0],
            "legacy_rwa": [50.0, 150.0, 300.0, 25.0],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference", "legacy_exposure_class"),
        our_keys=("exposure_reference", "exposure_class"),
        components={
            "ead": ComponentMapping("EAD"),
            "rwa": ComponentMapping("RWA"),
            "exposure_class": ComponentMapping("Asset_Class"),
        },
    )
    bundle = ReconciliationRunner().reconcile(with_reporting_ledger(ours), legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


def _simple_response() -> ReconciliationResponse:
    """The default single-column key, where link and lookup already coincide."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2"],
            "source_exposure_reference": ["L1", "L2"],
            "exposure_class": ["corporate", "retail"],
            "approach_applied": ["standardised"] * 2,
            "ead_final": [100.0, 200.0],
            "rwa_final": [50.0, 150.0],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2"],
            "legacy_ead": [100.0, 200.0],
            "legacy_rwa": [60.0, 150.0],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(with_reporting_ledger(ours), legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


@pytest.fixture(scope="module")
def composite() -> ReconciliationResponse:
    return _composite_response()


@pytest.fixture(scope="module")
def simple() -> ReconciliationResponse:
    return _simple_response()


def test_an_exact_key_resolves_to_itself(simple: ReconciliationResponse) -> None:
    resolved = rv.resolve_recon_key(simple, "L1")
    assert resolved.recon_key == "L1"
    assert resolved.matched_exactly
    assert resolved.reason == ""


def test_a_composite_key_resolves_from_its_exposure_reference(
    composite: ReconciliationResponse,
) -> None:
    # Act — exactly the link ``recon_templates.html`` builds today.
    resolved = rv.resolve_recon_key(composite, "L1")

    # Assert — the full ``_recon_key``, not a 404.
    assert resolved.recon_key == "L1||corporate"
    assert not resolved.matched_exactly
    assert resolved.reason == ""


def test_an_ambiguous_reference_offers_its_candidates_and_names_the_key_columns(
    composite: ReconciliationResponse,
) -> None:
    # Act — L3 is reconciled twice, once per class.
    resolved = rv.resolve_recon_key(composite, "L3")

    # Assert — a choice, not a guess, and the message says WHY there is a choice.
    assert resolved.recon_key == ""
    assert set(resolved.candidates) == {"L3||corporate", "L3||retail"}
    assert resolved.key_columns == ("exposure_reference", "exposure_class")
    assert "exposure_class" in resolved.reason


def test_an_unknown_key_says_what_the_join_key_is(composite: ReconciliationResponse) -> None:
    resolved = rv.resolve_recon_key(composite, "NOPE")
    assert resolved.recon_key == ""
    assert resolved.candidates == ()
    assert resolved.key_columns == ("exposure_reference", "exposure_class")
    assert "NOPE" in resolved.reason


def test_an_empty_key_is_unresolved_rather_than_matching_everything(
    simple: ReconciliationResponse,
) -> None:
    resolved = rv.resolve_recon_key(simple, "")
    assert resolved.recon_key == ""
    assert resolved.candidates == ()


# =============================================================================
# The route: the composite link renders, and the breadcrumb comes back
# =============================================================================


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_comparison_cache() -> Iterator[None]:
    rr.clear_comparison_cache()
    yield
    rr.clear_comparison_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://localhost")


def test_the_loan_route_resolves_a_composite_key_instead_of_404ing(
    client: TestClient, composite: ReconciliationResponse
) -> None:
    # Arrange
    recon_id = "loan-composite"
    register_reconciliation_with_id(recon_id, composite)

    # Act — the link the template builds: the exposure reference alone.
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "L1"})

    # Assert — the forensic, on the resolved key.
    assert resp.status_code == 200
    assert "L1||corporate" in resp.text
    assert "No reconciliation row matches that key." not in resp.text


def test_an_ambiguous_key_explains_itself_instead_of_reading_as_a_missing_loan(
    client: TestClient, composite: ReconciliationResponse
) -> None:
    # Arrange
    recon_id = "loan-ambiguous"
    register_reconciliation_with_id(recon_id, composite)

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "L3"})

    # Assert — both candidates offered, and the join key named.
    assert resp.status_code == 300
    assert "L3||corporate" in resp.text
    assert "L3||retail" in resp.text
    assert "exposure_class" in resp.text


def test_the_breadcrumb_returns_to_the_cell_it_came_from(
    client: TestClient, composite: ReconciliationResponse
) -> None:
    # Arrange
    recon_id = "loan-breadcrumb"
    register_reconciliation_with_id(recon_id, composite)
    cell = f"/reconciliation/{recon_id}/templates?template=c08_03&row=0030&col=0010"

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "L1", "return_to": cell})

    # Assert — the exact cell is linked back to, and the sign-off form returns
    # there too (the existing ``return_to`` field, not a second mechanism).
    assert resp.status_code == 200
    assert "row=0030" in resp.text
    assert "col=0010" in resp.text
    assert resp.text.count("template=c08_03") >= 2


#: Return targets that must never reach the breadcrumb or the sign-off redirect,
#: through EITHER channel. ``//evil.example/...`` is the one that mattered: a
#: scheme-relative URL has an EMPTY scheme, so an origin test written as
#: ``if parts.scheme and ...`` skips itself and reduces a foreign referrer to its
#: path. Measured on this route before it was fixed.
HOSTILE_RETURN_TO: tuple[str, ...] = (
    "//evil.example/reconciliation/x",
    "///evil.example/reconciliation/x",
    "/\\evil.example/reconciliation/x",
    "\\\\evil.example\\reconciliation\\x",
    "https://evil.example/reconciliation/x",
    "http://evil.example/reconciliation/x",
    "javascript:/reconciliation/x",
    "/reconciliation.evil.example/x",
    "/reconciliationX/y",
    # Dot-segment escapes from the reconciliation subtree. All three spellings
    # resolve identically in a browser: a raw ``..``, its percent-encoded form
    # (``%2e%2e`` IS a dot segment per RFC 3986 / WHATWG), and the backslash
    # form (WHATWG folds ``\`` to ``/`` for special schemes). A guard that
    # tests the raw string leaves the last two open.
    "/reconciliation/../../evil",
    "/reconciliation/%2e%2e/%2e%2e/evil",
    "/reconciliation/..\\..\\evil",
    # UNPARSEABLE, which is a different failure class from hostile-but-well-
    # formed and was missing from this corpus entirely — the natural way to
    # build an injection corpus is "valid URLs that point somewhere bad", and it
    # misses the whole crash class. ``urlsplit`` raises ``ValueError: Invalid
    # IPv6 URL`` on any unbalanced bracket in the authority, so before the guard
    # these 500'd the loan forensic through the ``Referer`` header — a denial of
    # service reachable by anyone who can get a user to follow a link. These are
    # the measured spellings, not invented ones.
    "http://[::1",
    "http://[",
    "//[",
    "//[::1",
    "https://[::1]extra/reconciliation/x",
    "http://]/x",
    "http://[]]/x",
    "http://user@[::1/x",
    "https://[1:2:3:4:5:6:7:8:9]/x",
)


@pytest.mark.parametrize("hostile", HOSTILE_RETURN_TO)
@pytest.mark.parametrize("channel", ["query", "referer"])
def test_a_hostile_return_target_never_reaches_the_page(
    client: TestClient, composite: ReconciliationResponse, hostile: str, channel: str
) -> None:
    # Arrange — BOTH channels, because they are guarded by different code: the
    # query param goes straight to ``_safe_return_to``, the header goes through
    # ``_same_origin_path`` first, and only the second had the hole.
    recon_id = f"loan-hostile-{channel}"
    register_reconciliation_with_id(recon_id, composite)
    params = {"key": "L1"}
    headers = {}
    if channel == "query":
        params["return_to"] = hostile
    else:
        headers["referer"] = hostile

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params=params, headers=headers)

    # Assert — on the RESOLVED DESTINATION, not on the absence of the hostname.
    # The hostname assertions below are necessary and NOT sufficient, and that is
    # measured: under the scheme-only origin test this route shipped with,
    # ``//evil.example/reconciliation/x`` resolved to ``/reconciliation/x`` —
    # a foreign referrer steering the page, with "evil.example" nowhere in the
    # body. Only the equality against the fallback fails in that state.
    body = unescape(resp.text)
    assert resp.status_code == 200
    assert _return_target(resp.text) == f"/reconciliation/{recon_id}/rows"
    assert "Back to the cell you came from" not in body
    assert "evil.example" not in body
    assert "javascript:" not in body


def test_a_quote_in_a_return_target_cannot_break_out_of_the_attribute(
    client: TestClient, composite: ReconciliationResponse
) -> None:
    # Arrange — this one is ACCEPTED by the path guard (it is a relative
    # /reconciliation/ path), so escaping is the only thing between it and an
    # injected handler.
    recon_id = "loan-quote"
    register_reconciliation_with_id(recon_id, composite)
    payload = '/reconciliation/x" onmouseover="alert(1)'

    # Act
    resp = client.get(
        f"/reconciliation/{recon_id}/loan", params={"key": "L1", "return_to": payload}
    )

    # Assert — the raw response carries the ESCAPED quote and no live handler.
    # Note this is asserted on ``resp.text``, not the unescaped body: unescaping
    # first would destroy the very evidence.
    assert resp.status_code == 200
    assert 'onmouseover="alert(1)"' not in resp.text
    assert "&#34;" in resp.text or "&quot;" in resp.text


def test_the_loan_page_carries_the_placement_panel(
    client: TestClient, composite: ReconciliationResponse
) -> None:
    # Arrange — this reconciliation carries no second side to compare against, so
    # the panel must DEGRADE with the reason rather than 500 or go silently blank.
    recon_id = "loan-placement-degraded"
    register_reconciliation_with_id(recon_id, composite)

    # Assert the premise, so the assertion below cannot pass against a different
    # degraded path than the one this fixture actually drives.
    reason = rr.comparison_inputs(composite).reason
    assert reason

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "L1"})

    # Assert — the panel is on the page, and it carries the TYPED reason
    # ``comparison_inputs`` returns rather than an empty section.
    assert resp.status_code == 200
    assert "Where this exposure lands" in resp.text
    assert reason in resp.text


def _two_sided_response(tmp_path: Path) -> ReconciliationResponse:
    """A reconciliation that CAN be compared: our calculation plus their ledger.

    Built so the loan route reaches a populated placement panel. Without this the
    route tests above only ever exercise the DEGRADED panel, and a panel that
    renders nothing on the live path would pass every one of them — the shape
    this codebase has been caught by before (a registered fixture whose cell is
    dead is indistinguishable from a clean estate).
    """
    base = [
        _leg("AGREE", pd=PD_A, rwa=90_000.0),
        _leg("FILLER_LOW", pd=PD_B, rwa=300_000.0),
        _leg("FILLER_HIGH", pd=PD_C, rwa=500_000.0),
        _leg("FILLER_TOP", pd=PD_D, rwa=800_000.0),
    ]
    our_legs = [*base, _leg("MOVER", pd=PD_B, rwa=210_000.0)]
    their_legs = [*base, _leg("MOVER", pd=PD_D, rwa=210_000.0)]

    results_path = tmp_path / "last_results.parquet"
    _source(our_legs)._frame.collect().write_parquet(results_path)
    calculation = CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("5730000"),
            total_rwa=Decimal("1900000"),
            exposure_count=len(our_legs),
            average_risk_weight=Decimal("0.33"),
        ),
        results_path=results_path,
    )
    references = [str(leg["exposure_reference"]) for leg in our_legs]
    legacy = pl.LazyFrame(
        {
            "exposure_reference": references,
            "legacy_ead": [float(leg["ead_final"]) for leg in our_legs],  # type: ignore[arg-type]
            "legacy_rwa": [float(leg["rwa_final"]) for leg in their_legs],  # type: ignore[arg-type]
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(calculation.scan_results(), legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle,
        legacy_file=Path("legacy.csv"),
        framework="CRR",
        calculation=calculation,
        legacy_ledger=_source(their_legs),  # type: ignore[arg-type]
        # Threaded because production always has one: without it every column the
        # mapping cannot populate reads as a measured figure. This panel reads no
        # figures, but a fixture that models a disarmed guard teaches the wrong
        # shape to whoever copies it next.
        legacy_ledger_coverage=LedgerCoverage(
            supplied=frozenset({"ead_final", "rwa_final", "pd_floored"}),
            missing=frozenset(),
            unavailable_cells={},
            reachable_templates=frozenset({TEMPLATE, "c08_01"}),
            present_approaches=frozenset({"foundation_irb"}),
            populated_templates=frozenset({TEMPLATE, "c08_01"}),
        ),
    )


def _divergent_response(tmp_path: Path) -> ReconciliationResponse:
    """A row that is a provable LEAF on our side and INDISTINGUISHABLE on theirs.

    Measured, not assumed: our side has two populated children under C 08.03 row
    0010, so 0010 is a strict parent and 0020 / 0030 are provable leaves; their
    side has one child, so 0010 and 0030 hold exactly the same leg and neither
    can be decided. Exposure ``X`` therefore sits in row 0030 with
    ``is_parent_row`` False on ours and NULL on theirs — the shape a single
    collapsed hierarchy label renders as a flat "leaf" for both sides.
    """
    our_legs = [_leg("X", pd=PD_B, rwa=210_000.0), _leg("Y", pd=PD_A, rwa=90_000.0)]
    their_legs = [_leg("X", pd=PD_B, rwa=210_000.0)]

    results_path = tmp_path / "divergent.parquet"
    _source(our_legs)._frame.collect().write_parquet(results_path)
    calculation = CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("1"),
            total_rwa=Decimal("1"),
            exposure_count=len(our_legs),
            average_risk_weight=Decimal("0.33"),
        ),
        results_path=results_path,
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": [str(leg["exposure_reference"]) for leg in our_legs],
            "legacy_ead": [float(leg["ead_final"]) for leg in our_legs],  # type: ignore[arg-type]
            "legacy_rwa": [float(leg["rwa_final"]) for leg in our_legs],  # type: ignore[arg-type]
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(calculation.scan_results(), legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle,
        legacy_file=Path("legacy.csv"),
        framework="CRR",
        calculation=calculation,
        legacy_ledger=_source(their_legs),  # type: ignore[arg-type]
        legacy_ledger_coverage=LedgerCoverage(
            supplied=frozenset({"ead_final", "rwa_final", "pd_floored"}),
            missing=frozenset(),
            unavailable_cells={},
            reachable_templates=frozenset({TEMPLATE, "c08_01"}),
            present_approaches=frozenset({"foundation_irb"}),
            populated_templates=frozenset({TEMPLATE, "c08_01"}),
        ),
    )


def test_a_divergent_hierarchy_pair_cannot_render_as_agreement(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — asserted on the RENDERED PAGE, not on the dataclass. The
    # dataclass kept the tri-state correctly all along; the defect was one step
    # later, where a single label took ours and spoke for theirs.
    recon_id = "loan-divergent"
    register_reconciliation_with_id(recon_id, _divergent_response(tmp_path))
    client.get(f"/reconciliation/{recon_id}/templates")

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "X"})
    body = unescape(resp.text)

    # Assert the premise first — the fixture really does produce the divergence,
    # so a green result cannot mean "the shape was never built".
    panel = rv.placement_panel(rr.cached_comparison(recon_id), "X")
    row = _row(_group(panel), ROW_LEAF_LOW)
    assert (row.our_parent, row.their_parent) == (False, None)

    # ... then that BOTH claims reach the page, and the note names its sides.
    assert resp.status_code == 200
    assert row.our_parent_state == rv.LEAF_ROW
    assert row.their_parent_state == rv.PARENT_INDISTINGUISHABLE
    assert "hierarchy (ours)" in body
    assert "hierarchy (theirs)" in body
    assert "Ours —" in body
    assert "Theirs —" in body

    # ... asserted on the CELLS, positionally. "The word is on the page" is not
    # the same claim as "the word is in the column that means it", and only the
    # second one separates the two sides.
    cells = _placement_cells(resp.text, ROW_LEAF_LOW)
    assert cells, "the placement table has no row 0030"
    assert cells[4] == rv.LEAF_ROW
    assert cells[5] == rv.PARENT_INDISTINGUISHABLE
    assert cells[4] != cells[5]

    parent_cells = _placement_cells(resp.text, ROW_PARENT_LOW)
    assert parent_cells[4] == rv.PARENT_ROW
    assert parent_cells[5] == rv.PARENT_INDISTINGUISHABLE


def test_a_side_that_does_not_reach_a_row_makes_no_hierarchy_claim() -> None:
    # Arrange / Act — the fourth state. ``is_parent_row`` is NULL both for a
    # genuinely undecidable row and for a side that is simply not in the row,
    # and reporting the second as "indistinguishable" claims an uncertainty
    # where the truth is an absence.
    panel = rv.placement_panel(_recon(), "MOVER")

    # Assert
    group = _group(panel)
    ours_only = _row(group, ROW_LEAF_LOW)
    assert ours_only.our_parent_state == rv.LEAF_ROW
    assert ours_only.their_parent_state == rv.HIERARCHY_NOT_REACHED
    assert rv.HIERARCHY_NOT_REACHED != rv.PARENT_INDISTINGUISHABLE
    assert "no containment claim" in ours_only.parent_note


def test_cached_comparison_reads_the_memo_and_never_builds_one() -> None:
    # Arrange — the public read-only seam the placement panel is built on. If
    # this ever builds, the panel's whole cost guarantee goes with it.
    ours = _source([_leg("A", pd=PD_A, rwa=90_000.0)])
    theirs = _source([_leg("A", pd=PD_A, rwa=90_000.0)])

    # Act / Assert — nothing memoised, so nothing is returned AND nothing is made.
    assert rr.cached_comparison("never-built") is None
    assert "never-built" not in rr._CACHE

    # ... and once built, the SAME object comes back, not a rebuild.
    built = rr.build_comparison("built", ours, theirs)
    assert rr.cached_comparison("built") is built
    # A miss stays a miss even when the memo is non-empty. Asserted separately
    # because the empty-memo miss above passes for a resolver that returns any
    # arbitrary cached entry — and that resolver would put ANOTHER
    # reconciliation's placements on this loan's page.
    assert rr.cached_comparison("some-other-recon") is None
    rr.clear_comparison_cache()
    assert rr.cached_comparison("built") is None


def test_a_cold_loan_page_offers_the_comparison_rather_than_building_it(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — both sides ARE available, but nothing has generated them yet.
    # Building here costs ~1s at 10k exposures and ~5s at 100k against a 20ms
    # page, so the panel offers the build instead of performing it.
    recon_id = "loan-placement-cold"
    register_reconciliation_with_id(recon_id, _two_sided_response(tmp_path))

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "MOVER"})

    # Assert — an offer with the link, and NO comparison was generated.
    assert resp.status_code == 200
    assert "has not been generated yet" in resp.text
    assert f"/reconciliation/{recon_id}/templates" in resp.text
    assert "Moved row" not in resp.text
    assert recon_id not in rr._CACHE


def test_opening_the_comparison_fills_the_placement_panel_in(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — the self-healing half of the decision above. If this fails the
    # gate is not a guard, it is a permanent hole: the cold panel would offer a
    # link that changes nothing.
    recon_id = "loan-placement-heals"
    register_reconciliation_with_id(recon_id, _two_sided_response(tmp_path))
    assert (
        "has not been generated yet"
        in client.get(f"/reconciliation/{recon_id}/loan", params={"key": "MOVER"}).text
    )

    # Act — the one click the cold panel offers.
    assert client.get(f"/reconciliation/{recon_id}/templates").status_code == 200
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "MOVER"})

    # Assert — the panel is now populated.
    assert resp.status_code == 200
    assert "Moved row" in unescape(resp.text)
    assert "has not been generated yet" not in resp.text


def test_the_placement_panel_renders_the_moved_band_on_the_live_route(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — a reconciliation with BOTH sides, generated (as arriving from a
    # template cell leaves it), so the panel is populated.
    recon_id = "loan-placement-live"
    register_reconciliation_with_id(recon_id, _two_sided_response(tmp_path))
    client.get(f"/reconciliation/{recon_id}/templates")

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/loan", params={"key": "MOVER"})

    # Assert — the band it left and the band it landed in, by name, plus the
    # tri-state hierarchy label. A panel that lost either side, or that rendered
    # a one-sided row as a blank, cannot produce this text. Unescaped because the
    # band names carry ``<`` and Jinja autoescapes it.
    rendered = unescape(resp.text)
    assert resp.status_code == 200
    assert "Moved row" in rendered
    assert NAME_LEAF_LOW in rendered
    assert NAME_LEAF_HIGH in rendered
    assert rv.NOT_REACHED_DISPLAY in rendered
    assert rv.PARENT_ROW in rendered


# =============================================================================
# Adversarial-review regressions: key matching, and two unguarded rules
# =============================================================================

# A composite mapping keying on the counterparty AND the exposure. Its
# ``_recon_key`` is "CP||X", whose segments are {"CP", "X"} — and "CP" is a
# perfectly ordinary exposure reference for an overdraft booked at counterparty
# level, which is what makes the leak below reachable rather than contrived.
COMPOSITE_KEY_COLUMNS = ("counterparty_reference", "exposure_reference")


@lru_cache(maxsize=2)
def _recon_decoy() -> ReturnRecon:
    """A book holding both loan ``X`` and an exposure referenced ``CP``.

    ``X`` moves band (PD_B ours, PD_D theirs). The decoy sits at PD_A on our
    side, so leaking it adds a row ``X`` never reached AND gives our side a
    second provably-leaf row — which is what silently deletes the move.
    """

    def legs(x_pd: float, cp_pd: float) -> list[dict[str, object]]:
        return [
            _leg("X", pd=x_pd, rwa=210_000.0),
            _leg("CP", pd=cp_pd, rwa=500_000.0),
            _leg("F1", pd=PD_A, rwa=90_000.0),
            _leg("F2", pd=PD_C, rwa=300_000.0),
        ]

    return build_recon(_source(legs(PD_B, PD_A)), _source(legs(PD_D, PD_D)))


def test_a_composite_key_segment_cannot_drag_in_another_exposure() -> None:
    # Arrange — the same loan, addressed two ways. The composite panel must be
    # indistinguishable from the single-key control, which is the only statement
    # of correctness that does not depend on believing the fixture.
    control = rv.placement_panel(_recon_decoy(), "X")
    composite = rv.placement_panel(_recon_decoy(), "CP||X", key_columns=COMPOSITE_KEY_COLUMNS)

    # Act
    control_group = _group(control)
    composite_group = _group(composite)

    # Assert — measured before the fix: the composite panel gained row 0020
    # (which X never reached) and lost the move entirely, moved True -> False
    # with our_placement '0030' -> ''. Both directions of wrong, at once.
    assert composite_group.rows == control_group.rows
    assert composite_group.moved == control_group.moved is True
    assert composite_group.our_placement == control_group.our_placement == ROW_LEAF_LOW
    assert composite_group.their_placement == control_group.their_placement == ROW_LEAF_HIGH
    assert "0020" not in {row.row_ref for row in composite_group.rows}


def test_a_key_naming_no_exposure_column_matches_nothing_and_says_so() -> None:
    # Arrange / Act — a composite key of counterparty + class holds no exposure
    # identity, so no segment of it may be matched against a leg.
    panel = rv.placement_panel(
        _recon_decoy(), "CP||corporate", key_columns=("counterparty_reference", "exposure_class")
    )

    # Assert — an explanation naming the remedy, never a wide match.
    assert not panel.available
    assert panel.groups == ()
    assert panel.reason == rv.PLACEMENT_NO_IDENTITY_KEY


def _separator_response() -> ReconciliationResponse:
    """A SINGLE-column mapping whose references legitimately contain ``||``."""
    refs = ["L1||A", "L2", "L3"]
    ours = pl.LazyFrame(
        {
            "exposure_reference": refs,
            "source_exposure_reference": refs,
            "exposure_class": ["corporate"] * 3,
            "approach_applied": ["standardised"] * 3,
            "ead_final": [100.0, 200.0, 500.0],
            "rwa_final": [50.0, 150.0, 250.0],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": refs,
            "legacy_ead": [100.0, 200.0, 500.0],
            "legacy_rwa": [60.0, 150.0, 250.0],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(with_reporting_ledger(ours), legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


@pytest.fixture(scope="module")
def separator() -> ReconciliationResponse:
    return _separator_response()


def test_a_separator_inside_a_reference_is_data_not_structure(
    separator: ReconciliationResponse,
) -> None:
    # Assert — the join key is ONE column, however many ``||`` its values carry.
    # Measured before the fix: reported as ``? + ?``, because no column
    # reproduces "L1" or "A" — the column holds the whole string.
    assert rv.resolve_recon_key(separator, "L1||A").key_columns == ("exposure_reference",)


@pytest.mark.parametrize("fragment", ["L1", "A"])
def test_half_a_reference_does_not_resolve_to_a_whole_loan(
    separator: ReconciliationResponse, fragment: str
) -> None:
    # Act — before the fix BOTH of these resolved to "L1||A", silently and with
    # an empty reason: a link built from a different exposure's partial
    # reference landed on this loan's forensic.
    resolved = rv.resolve_recon_key(separator, fragment)

    # Assert
    assert resolved.recon_key == ""
    assert resolved.candidates == ()
    assert fragment in resolved.reason
    # ... and the message does not send the analyst after a composite mapping
    # that does not exist.
    assert "composite" not in resolved.reason


def test_the_whole_reference_still_resolves_exactly(separator: ReconciliationResponse) -> None:
    resolved = rv.resolve_recon_key(separator, "L1||A")
    assert resolved.recon_key == "L1||A"
    assert resolved.matched_exactly


@lru_cache(maxsize=2)
def _recon_two_cuts() -> ReturnRecon:
    """A book in which one exposure reaches TWO provably-leaf rows.

    C 08.01's row axis is not a tree: row 0020 is on-balance-sheet and row 0070
    is "assigned to obligor grades", which are different CUTS of the same book.
    With a slotting leg on each side of the balance-sheet cut and a graded leg on
    each side too, neither row contains the other and both are provable leaves —
    and the ordinary on-balance-sheet graded loan sits in both.

    This is the shape whose existence was denied in an earlier round of this
    work, on the strength of C 08.03's PD scale, where a leg really does fall in
    exactly one band. The generalisation to a non-tree axis was wrong: measured
    here, exposure ``A`` has leaves ``['0020', '0070']``. Nothing about the
    portfolio is contrived — an IRB book with graded and slotting exposures,
    drawn and undrawn.
    """
    off_bs: dict[str, object] = {
        "drawn_amount": 0.0,
        "undrawn_amount": 900_000.0,
        "exposure_type": "commitment",
    }
    slotting: dict[str, object] = {
        "approach_applied": "slotting",
        "approach_post_crm": "slotting",
    }

    def leg(reference: str, **over: object) -> dict[str, object]:
        base = _leg(reference, pd=PD_B, rwa=300_000.0)
        base.update(over)
        return base

    legs = [leg("A"), leg("D", **slotting), leg("E", **off_bs), leg("F", **off_bs, **slotting)]
    return build_recon(_source(legs), _source(legs))


def test_an_exposure_in_two_provable_leaf_rows_is_not_placed_in_either() -> None:
    # Arrange / Act
    panel = rv.placement_panel(_recon_two_cuts(), "A")
    group = _group(panel, "c08_01")

    # Assert the premise FIRST — two rows, both provably leaves, both holding A.
    # Without this the assertion below passes on any portfolio with no leaf at
    # all, which is the vacuous version of this test.
    leaves = {row.row_ref for row in group.rows if row.our_parent is False}
    assert leaves == {"0020", "0070"}

    # ... then the rule: a leg with two candidate leaves has no single place, so
    # neither is claimed. Taking the first would place the exposure on the
    # strength of dictionary order.
    assert group.our_placement == ""
    assert group.our_placement_name == rv.UNDECIDED_DISPLAY
    assert not group.moved


def test_reached_but_unrankable_is_not_the_same_blank_as_not_reached() -> None:
    # Arrange / Act — two sides of the same field, on two portfolios that
    # produce the two different blanks.
    unrankable = _group(rv.placement_panel(_recon(), "AGREE"), "c08_01")
    unreached = _group(rv.placement_panel(_recon(), "ONLY_OURS"))

    # Assert — "we hold this leg but no row is its place" and "we do not hold
    # this leg here" are different findings and must not print alike.
    assert unrankable.our_placement == unreached.their_placement == ""
    assert unrankable.our_placement_name == rv.UNDECIDED_DISPLAY
    assert unreached.their_placement_name == rv.NOT_REACHED_DISPLAY
    assert rv.UNDECIDED_DISPLAY != rv.NOT_REACHED_DISPLAY
