"""
Integration test: the return-template compare page inside the reconciliation tab.

Pipeline position:
    TestClient -> GET /reconciliation/{id}/templates
        -> ui.views.return_recon -> analysis.return_recon (both sides generated)
        -> recon_templates.html

Key responsibilities tested:
- The route renders a real comparison for a registered reconciliation whose
  legacy extract was projected into the reporting ledger — the picker, the
  grid, the worst-cell ranking and the migration matrix.
- A column the mapping cannot populate renders as *not mapped* with its remedy,
  and NEVER as a legacy zero. That is the difference between "your provisions
  are unmapped" and "your provisions are nil", and only one of them is true.
- A reconciliation with no projected legacy ledger DEGRADES with an explanation
  and a 200, rather than 500ing or showing an empty grid that reads as a
  tie-out.
- Selecting a cell renders either its four-way waterfall or the refusal that
  says why the four terms do not apply — a weighted average gets the refusal.
- Both sides are generated ONCE per reconciliation, not once per request.
- An unknown recon id is a styled 404.

The reconciliation is registered directly (as the materiality-toggle tests in
``test_ui_reconciliation.py`` do) so the route is driven without the heavy
background job, while the legacy side still goes through the production
``LegacyOutputLoader`` -> ``project_legacy_ledger`` path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rwa_calc.analysis.legacy_ledger import project_legacy_ledger
from rwa_calc.analysis.recon_registry import (
    CarrierMapping,
    ComponentMapping,
    LegacyColumnMapping,
)
from rwa_calc.analysis.reconciliation import ReconciliationRunner
from rwa_calc.analysis.return_recon import build_recon, decompose_cell
from rwa_calc.api.models import CalculationResponse, ReconciliationResponse, SummaryStatistics
from rwa_calc.api.reconciliation import LegacyOutputLoader, ReconciliationSettings
from rwa_calc.api.rest import register_reconciliation_with_id
from rwa_calc.ui.app.main import create_app
from rwa_calc.ui.app.recon_state import STATE_DIR_ENV_VAR
from rwa_calc.ui.views import return_recon as rr
from tests.fixtures.recon_ledger import with_reporting_ledger

FRAMEWORK = "CRR"
SHEET = "corporate"

#: C 08.03's first money column — the one a thin mapping leaves unpopulatable
#: while the generator still prints a confident 0.00 for it.
GROSS_COL = "0010"

# The firm's extract, in the firm's own column names, labels and units. Note
# what is NOT here: any provisions column. C 08.03 column 0110 is therefore
# unpopulatable from this mapping, which is the case the page must render as
# "not mapped" rather than as a legacy zero.
_LEGACY_ROWS: dict[str, list[object]] = {
    "Loan Ref": ["A0", "A1", "A2", "B0", "B1", "MOVER"],
    "Obligor Ref": ["CP_A0", "CP_A1", "CP_A2", "CP_B0", "CP_B1", "CP_MOVER"],
    "Asset Class": ["CORP"] * 6,
    "Approach": ["FIRB"] * 6,
    "Product": ["TERM LOAN"] * 6,
    "EAD 000": [300.0, 900.0, 990.0, 2_160.0, 2_400.0, 630.0],
    "Drawn 000": [300.0, 900.0, 990.0, 2_160.0, 2_400.0, 630.0],
    "RWA 000": [90.0, 300.0, 330.0, 720.0, 800.0, 210.0],
    "RW Pct": [30.0, 33.33, 33.33, 33.33, 33.33, 33.33],
    # MOVER's PD is 2.00% on their side and 0.12% on ours — the band mover.
    "PD Pct": [0.03, 0.12, 0.12, 1.00, 2.00, 2.00],
    "LGD Pct": [45.0] * 6,
    "Maturity Yrs": [2.5] * 6,
    "CCF Pct": [100.0] * 6,
}

_OUR_PDS = [0.0003, 0.0012, 0.0012, 0.0100, 0.0200, 0.0012]


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the saved-run prefill out of the developer's real state home."""
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _clean_comparison_cache() -> None:
    """Each test starts with an empty comparison memo (module-level state)."""
    rr.clear_comparison_cache()


@pytest.fixture
def client() -> TestClient:
    # Loopback base_url so the app's TrustedHostMiddleware accepts test requests.
    return TestClient(create_app(), base_url="http://localhost")


# =============================================================================
# Fixtures — a registered reconciliation with a projected legacy ledger
# =============================================================================


def _our_results() -> pl.LazyFrame:
    """Our own sealed reporting ledger for the same six exposures."""
    rows = []
    for index, reference in enumerate(_LEGACY_ROWS["Loan Ref"]):
        ead = float(_LEGACY_ROWS["EAD 000"][index]) * 1_000.0  # type: ignore[arg-type]
        rwa = float(_LEGACY_ROWS["RWA 000"][index]) * 1_000.0  # type: ignore[arg-type]
        pd_value = _OUR_PDS[index]
        rows.append(
            {
                "exposure_reference": str(reference),
                "source_exposure_reference": str(reference),
                "counterparty_reference": f"CP_{reference}",
                "exposure_class": SHEET,
                "exposure_class_applied": SHEET,
                "exposure_class_post_crm": SHEET,
                "approach_applied": "foundation_irb",
                "approach_post_crm": "foundation_irb",
                "exposure_type": "loan",
                "drawn_amount": ead,
                "undrawn_amount": 0.0,
                "nominal_amount": 0.0,
                "interest": 0.0,
                "ead_final": ead,
                "rwa_final": rwa,
                "risk_weight": rwa / ead,
                "ccf": 1.0,
                "pd": pd_value,
                "pd_floored": pd_value,
                "lgd_floored": 0.45,
                "irb_maturity_m": 2.5,
                "expected_loss": pd_value * 0.45 * ead,
                "scra_provision_amount": 0.0,
                "gcra_provision_amount": 0.0,
                "sa_cqs": 0,
                "is_defaulted": False,
                "reporting_leg_role": "whole",
            }
        )
    frame = pl.LazyFrame(
        rows,
        schema_overrides={
            "pd": pl.Float64,
            "pd_floored": pl.Float64,
            "lgd_floored": pl.Float64,
            "irb_maturity_m": pl.Float64,
            "sa_cqs": pl.Int8,
        },
    )
    return with_reporting_ledger(frame)


def _mapping(*, thin: bool = False) -> LegacyColumnMapping:
    """The firm's mapping — deliberately WITHOUT a provisions component.

    ``thin`` additionally drops ``drawn``, which is what makes C 08.03's FIRST
    money column (0010, original exposure pre-conversion, on-balance sheet)
    unpopulatable. That column is the one the generator prints a confident
    ``0.00`` for, because ``ensure_gross_side_carriers`` injects an all-null
    column and ``sum`` returns 0.0 over it — so it is the shape the coverage
    guard exists to catch.
    """
    components = {
        "exposure_class": ComponentMapping("Asset Class", value_map={"CORP": "corporate"}),
        "approach": ComponentMapping("Approach", value_map={"FIRB": "foundation_irb"}),
        "ead": ComponentMapping("EAD 000", scale=1_000.0),
        "rwa": ComponentMapping("RWA 000", scale=1_000.0),
        "risk_weight": ComponentMapping("RW Pct", unit="percent"),
        "pd": ComponentMapping("PD Pct", unit="percent"),
        "lgd": ComponentMapping("LGD Pct", unit="percent"),
        "maturity": ComponentMapping("Maturity Yrs"),
        "ccf": ComponentMapping("CCF Pct", unit="percent"),
    }
    if not thin:
        components["drawn"] = ComponentMapping("Drawn 000", scale=1_000.0)
    return LegacyColumnMapping(
        legacy_keys=("Loan Ref",),
        our_keys=("exposure_reference",),
        components=components,
        carriers={
            "obligor": CarrierMapping("Obligor Ref"),
            "exposure_type": CarrierMapping("Product", value_map={"TERM LOAN": "loan"}),
        },
    )


def _calculation(tmp_path: Path) -> CalculationResponse:
    """Our side, cached to a parquet exactly as a real run leaves it."""
    results_path = tmp_path / "last_results.parquet"
    _our_results().collect().write_parquet(results_path)
    return CalculationResponse(
        success=True,
        framework=FRAMEWORK,
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("7380000"),
            total_rwa=Decimal("2450000"),
            exposure_count=6,
            average_risk_weight=Decimal("0.33"),
        ),
        results_path=results_path,
    )


def _response(
    tmp_path: Path, *, with_ledger: bool = True, thin: bool = False
) -> ReconciliationResponse:
    """A registered reconciliation, with or without its projected legacy ledger."""
    legacy_path = tmp_path / "legacy.parquet"
    pl.DataFrame(_LEGACY_ROWS).write_parquet(legacy_path)
    mapping = _mapping(thin=thin)
    legacy = LegacyOutputLoader(
        ReconciliationSettings(legacy_file=legacy_path, mapping=mapping, legacy_format="parquet")
    ).load()
    calculation = _calculation(tmp_path)
    bundle = ReconciliationRunner().reconcile(calculation.scan_results(), legacy, mapping)
    ledger, coverage = (
        project_legacy_ledger(legacy, mapping, framework=FRAMEWORK) if with_ledger else (None, None)
    )
    return ReconciliationResponse.from_bundle(
        bundle,
        legacy_file=legacy_path,
        framework=FRAMEWORK,
        reporting_date=date(2025, 1, 1),
        calculation=calculation,
        legacy_ledger=ledger,
        legacy_ledger_coverage=coverage,
    )


def _register(
    tmp_path: Path, recon_id: str, *, with_ledger: bool = True, thin: bool = False
) -> str:
    register_reconciliation_with_id(
        recon_id, _response(tmp_path, with_ledger=with_ledger, thin=thin)
    )
    return recon_id


# =============================================================================
# The page renders
# =============================================================================


def test_the_template_page_renders_a_comparison(client: TestClient, tmp_path: Path) -> None:
    # Arrange
    recon_id = _register(tmp_path, "tpl-renders")

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/templates")

    # Assert — the picker, the grid and the sheet are all on the page.
    assert resp.status_code == 200
    assert "Return templates" in resp.text
    assert "C 08.03" in resp.text
    assert 'class="data grid"' in resp.text
    assert SHEET in resp.text


def test_the_page_offers_a_route_back_and_a_cell_drill(client: TestClient, tmp_path: Path) -> None:
    recon_id = _register(tmp_path, "tpl-links")
    resp = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c08_03"})
    assert resp.status_code == 200
    assert f'href="/reconciliation/{recon_id}"' in resp.text
    assert f"/reconciliation/{recon_id}/templates?" in resp.text


def test_the_migration_matrix_is_drawn_with_its_attribution(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange
    recon_id = _register(tmp_path, "tpl-matrix")

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c08_03"})

    # Assert — the headline feature, priced, and the line that stops it being
    # misread as evidence about their BANDING RULE.
    assert resp.status_code == 200
    assert "Row migration" in resp.text
    assert "VALUE-driven by construction" in resp.text
    assert "moved row (their value differs)" in resp.text
    # MOVER's RWEA moved band; the agreeing legs did not. Both classes are
    # asserted against the fixture's own money, so a matrix that silently lost
    # one of them cannot pass — a page-text search alone would not catch that,
    # because the same figure appears in the grid above.
    assert "210,000" in resp.text
    assert "2,240,000" in resp.text
    recon = rr._CACHE[recon_id]
    groups = rr.migration_groups(recon, "c08_03", SHEET)
    matrix = rr.migration_matrix(recon, "c08_03", SHEET, groups[0].predicate_key)
    assert matrix is not None
    assert matrix.totals.agreed == pytest.approx(2_240_000.0)
    assert matrix.totals.moved == pytest.approx(210_000.0)
    assert matrix.totals.undecidable == pytest.approx(0.0)
    assert matrix.axis_is_partition


# =============================================================================
# An unmapped column is not a legacy zero
# =============================================================================


def test_an_unmappable_column_renders_not_mapped_never_a_zero(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — the mapping carries no provisions component, so C 08.03 col 0110
    # cannot be populated on their side.
    recon_id = _register(tmp_path, "tpl-unmapped")

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c08_03"})

    # Assert — the page says what to map, and the cell shows the unmeasurable
    # glyph rather than a confident zero.
    assert resp.status_code == 200
    assert "cannot populate everything" in resp.text
    assert "not mapped: needs provision_allocated" in resp.text
    assert rr.UNMEASURABLE_DISPLAY in resp.text
    assert "Not measurable" in resp.text

    # ... and the view underneath agrees: every cell of that column has a NULL
    # delta on the legacy side, not a zero.
    recon = rr._CACHE[recon_id]
    compare = rr.sheet_compare(recon, "c08_03", SHEET, coverage=recon.theirs.coverage)
    assert compare is not None
    blocked = [cell for row in compare.rows for cell in row.cells if cell.col_ref == "0110"]
    assert blocked
    assert {cell.delta for cell in blocked} == {None}
    assert {cell.delta_display for cell in blocked} == {rr.UNMEASURABLE_DISPLAY}
    assert {cell.theirs.value for cell in blocked} == {None}
    assert {cell.theirs.display for cell in blocked} == {rr.UNMEASURABLE_DISPLAY}
    assert {cell.status for cell in blocked} == {"unmeasurable"}


def test_the_route_arms_the_false_zero_guard(client: TestClient, tmp_path: Path) -> None:
    """The route must pass ``theirs_coverage`` — the guard is inert without it.

    A thin mapping leaves C 08.03 col 0010 unpopulatable, and the generator
    prints ``0.00`` for it regardless (an injected all-null column sums to
    zero, not null). Unguarded, the cell reads as a real legacy figure and its
    waterfall RECONCILES, attributing our whole gross to ``measurement`` —
    "same loans, different number". The counterfactual is asserted here too, so
    this test cannot go quietly vacuous.
    """
    # Arrange
    recon_id = _register(tmp_path, "tpl-guard", thin=True)

    # Act — through the real route, which is the call site under test.
    resp = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c08_03"})

    # Assert — the coverage record reached the LEGACY side of the comparison.
    assert resp.status_code == 200
    recon = rr._CACHE[recon_id]
    assert recon.theirs.coverage is not None, "the route did not pass theirs_coverage"
    assert GROSS_COL in recon.theirs.coverage.unavailable_refs("c08_03")

    # ... the page names it as a mapping gap, not as a difference ...
    assert "needs drawn_amount" in resp.text
    compare = rr.sheet_compare(recon, "c08_03", SHEET, coverage=recon.theirs.coverage)
    assert compare is not None
    blocked = [cell for row in compare.rows for cell in row.cells if cell.col_ref == GROSS_COL]
    assert blocked
    assert {cell.theirs.value for cell in blocked} == {None}
    assert {cell.delta for cell in blocked} == {None}
    assert {cell.delta_display for cell in blocked} == {rr.UNMEASURABLE_DISPLAY}
    assert all(cell.col_ref != GROSS_COL for cell in compare.worst)

    # ... the cell page renders a COVERAGE refusal, distinctly ...
    cell = client.get(
        f"/reconciliation/{recon_id}/templates",
        params={
            "template": "c08_03",
            "sheet": SHEET,
            "row": blocked[0].row_ref,
            "col": GROSS_COL,
        },
    )
    assert cell.status_code == 200
    assert 'data-refusal="coverage"' in cell.text
    assert "Not mapped" in cell.text
    assert "Why it differs" not in cell.text

    # ... and unguarded, the very same pair fabricates a MEASUREMENT difference.
    response = _response(tmp_path, thin=True)
    inputs = rr.comparison_inputs(response)
    unguarded = build_recon(inputs.ours, inputs.theirs, ["c08_03"])
    fabricated = decompose_cell(unguarded, "c08_03", SHEET, blocked[0].row_ref, GROSS_COL)
    assert fabricated.refusal is None
    assert fabricated.theirs == 0.0
    assert fabricated.reconciles
    assert fabricated.amount("measurement") != 0.0


def test_a_reachable_but_unpopulated_template_is_not_called_a_mapping_problem(
    client: TestClient, tmp_path: Path
) -> None:
    """An all-FIRB book has no C 07.00. That is not a mapping defect."""
    # Arrange — the fixture's book is entirely foundation-IRB, so C 07.00 is
    # reachable (nothing about the mapping stops it) and unpopulated.
    recon_id = _register(tmp_path, "tpl-unpopulated")
    client.get(f"/reconciliation/{recon_id}/templates")
    coverage = rr._CACHE[recon_id].theirs.coverage
    assert coverage is not None
    assert "c07_00" in coverage.reachable_templates
    assert coverage.populated_templates is not None
    assert "c07_00" not in coverage.populated_templates

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c07_00"})

    # Assert — "nothing to fix", not "map these columns".
    assert resp.status_code == 200
    assert 'data-template-state="unpopulated"' in resp.text
    assert "Nothing to fix here" in resp.text
    assert 'data-template-state="unreachable"' not in resp.text


def test_the_page_explains_its_three_kinds_of_blank(client: TestClient, tmp_path: Path) -> None:
    recon_id = _register(tmp_path, "tpl-blanks")
    resp = client.get(f"/reconciliation/{recon_id}/templates")
    assert resp.status_code == 200
    assert "A blank is never a zero" in resp.text


# =============================================================================
# Selecting a cell
# =============================================================================


def test_selecting_a_money_cell_renders_the_four_way_waterfall(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — the band the mover leaves on our side, read off the comparison
    # rather than pinned as a literal (the row axes differ by framework).
    recon_id = _register(tmp_path, "tpl-waterfall")
    client.get(f"/reconciliation/{recon_id}/templates")
    recon = rr._CACHE[recon_id]
    row_ref = _leaf_row(recon, "MOVER")

    # Act
    resp = client.get(
        f"/reconciliation/{recon_id}/templates",
        params={"template": "c08_03", "sheet": SHEET, "row": row_ref, "col": "0090"},
    )

    # Assert
    assert resp.status_code == 200
    assert "Why it differs" in resp.text
    assert "row placement — moved band" in resp.text
    assert "population — in ours only" in resp.text


def test_selecting_a_weighted_average_cell_renders_the_refusal(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — col 0050 is the exposure-weighted average PD.
    recon_id = _register(tmp_path, "tpl-refusal")
    client.get(f"/reconciliation/{recon_id}/templates")
    row_ref = _leaf_row(rr._CACHE[recon_id], "MOVER")

    # Act
    resp = client.get(
        f"/reconciliation/{recon_id}/templates",
        params={"template": "c08_03", "sheet": SHEET, "row": row_ref, "col": "0050"},
    )

    # Assert — a refusal with a reason, and NO waterfall beside it. It is the
    # NON-ADDITIVE refusal, visibly distinct from the coverage one: the figures
    # here are real and comparable, and only the split does not apply.
    assert resp.status_code == 200
    assert 'data-refusal="non_additive"' in resp.text
    assert "it is an average, not a total" in resp.text
    assert "non-additive" in resp.text
    assert "Why it differs" not in resp.text
    assert "Not mapped" not in resp.text


# =============================================================================
# Degradation, cost and 404
# =============================================================================


def test_a_reconciliation_with_no_legacy_ledger_degrades_without_500(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — a mapping too thin to project carries no ledger at all.
    recon_id = _register(tmp_path, "tpl-no-ledger", with_ledger=False)

    # Act
    resp = client.get(f"/reconciliation/{recon_id}/templates")

    # Assert — an explanation with the remedy, not an error and not an empty
    # grid that would read as a tie-out.
    assert resp.status_code == 200
    assert "No template comparison" in resp.text
    assert "no legacy ledger" in resp.text
    assert 'class="data grid"' not in resp.text


def test_an_unknown_recon_id_is_a_styled_404(client: TestClient) -> None:
    assert client.get("/reconciliation/does-not-exist/templates").status_code == 404


def test_both_sides_are_generated_once_per_reconciliation(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange — generating a template bundle is expensive and this page is a
    # screenful of cells; one generation per request would be unusable.
    recon_id = _register(tmp_path, "tpl-memo")

    # Act
    first = client.get(f"/reconciliation/{recon_id}/templates")
    cached = rr._CACHE[recon_id]
    second = client.get(f"/reconciliation/{recon_id}/templates", params={"template": "c08_01"})

    # Assert
    assert first.status_code == 200
    assert second.status_code == 200
    assert rr._CACHE[recon_id] is cached
    assert len(rr._CACHE) == 1


def test_an_unknown_template_or_sheet_falls_back_rather_than_404ing(
    client: TestClient, tmp_path: Path
) -> None:
    # Assert — what a run produced is data, not a contract; a hand-edited URL
    # renders the default view.
    recon_id = _register(tmp_path, "tpl-fallback")
    resp = client.get(
        f"/reconciliation/{recon_id}/templates",
        params={"template": "c99_99", "sheet": "not-a-class"},
    )
    assert resp.status_code == 200
    assert 'class="data grid"' in resp.text


# =============================================================================
# Helpers
# =============================================================================


def _leaf_row(recon: object, reference: str) -> str:
    """The C 08.03 leaf row a leg landed in on our side, off the membership."""
    legs = recon.ours.membership.legs  # type: ignore[attr-defined]
    rows = legs.filter(
        (pl.col("template_id") == "c08_03")
        & (pl.col("sheet") == SHEET)
        & (pl.col("exposure_reference") == reference)
        & (pl.col("is_parent_row").eq(other=False))
    )
    assert rows.height == 1, f"{reference} is in {rows.height} leaf rows, expected 1"
    return str(rows["row_ref"][0])
