"""
Acceptance: report-cell lineage ties out to the REPORTED template cells.

Runs the rich reporting portfolio through the real pipeline, generates the
COREP / Pillar 3 bundles, and checks the lineage of their cells against the
figures the generators actually reported.

This is the feature's correctness anchor. Lineage reads a template's own
``TemplateSpec`` and re-runs the same ``RowPredicate`` over the same prepared
frame, so agreement is structural — but only a test against the GENERATED
template can prove that the two post-``execute`` passes (all-null inert rows;
the Annex II §1.3 "(-)" negation) are accounted for rather than quietly
disagreed with.

The harness is per-template: ``test_sheet_lineage_ties_out_to_every_reported_cell``
is parametrised over ``_TIEOUT_CASES`` and runs the FULL sweep for each
instrumented ``(template, sheet)`` — cell value, kind consistency, predicate
satisfaction and sign-aware reconciliation across the whole sheet. A new
instrumented template (R20-R26) earns its tie-out by ADDING A TUPLE to
``_TIEOUT_CASES``, not by cloning this file. The C 07.00 tests below the sweep
pin that template's specific regulatory knowledge (the RWEA metric, the scope
wording, the deduction sign, the never-produced vs measured-zero distinction).

References:
- docs/plans/report-cell-lineage.md §4.5 (B3 — the fidelity tie-out)
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting import catalog, lineage
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

_SHEET = "corporate"
_RTOL = 1e-9
_ATOL = 1e-6

# The instrumented (template, sheet) pairs under fidelity tie-out. Adding a
# template to LINEAGE_PLANS (R20-R26) = appending its (template_id, sheet) here;
# the parametrised sweep then covers it with no new test code.
_TIEOUT_CASES: list[tuple[str, str | None]] = [
    ("c07_00", "corporate"),
]


class _Source:
    """A ResultsSource over an in-memory pipeline result (no parquet round-trip)."""

    def __init__(self, results, framework: str) -> None:  # noqa: ANN001 - LazyFrame
        self._results = results
        self.framework = framework

    def scan_results(self):  # noqa: ANN201 - LazyFrame
        return self._results


@pytest.fixture(scope="module")
def source() -> _Source:
    """The reporting portfolio run through the real CRR pipeline."""
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    return _Source(result.results, "CRR")


@pytest.fixture(scope="module")
def bundles(source: _Source):  # noqa: ANN201 - (COREPTemplateBundle, Pillar3TemplateBundle)
    """The generated COREP + Pillar 3 bundles — the figures actually reported.

    Resolved through ``reporting.catalog`` so a tie-out case names any template
    (COREP or Pillar 3) by its id, without this harness knowing the bundle
    field shape.
    """
    corep = COREPGenerator().generate(source)
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        source.scan_results(), framework=source.framework
    )
    return corep, pillar3


@pytest.fixture(scope="module")
def c07(bundles):  # noqa: ANN001, ANN201 - dict[str, pl.DataFrame]
    """The generated C 07.00 bundle (reused from the shared bundles fixture)."""
    corep, _pillar3 = bundles
    return corep.c07_00


# =============================================================================
# The per-template sweep — every cell of every instrumented sheet
# =============================================================================


@pytest.mark.parametrize(("template_id", "sheet"), _TIEOUT_CASES)
def test_sheet_lineage_ties_out_to_every_reported_cell(  # noqa: C901 - one sweep, several honesty checks
    source: _Source,
    bundles,  # noqa: ANN001
    template_id: str,
    sheet: str | None,
) -> None:
    # Arrange — the reported frame (what the user saw) and one resolver for the
    # whole sheet (one plan build, one generation).
    corep, pillar3 = bundles
    view = catalog.template_sheet(corep, pillar3, template_id, sheet)
    assert view is not None, f"{template_id}/{sheet}: no reported frame"
    reported = view.frame
    resolver = lineage.sheet_lineage(source, template_id, sheet)
    assert resolver is not None, f"{template_id}: not instrumented"

    checked = 0
    for record in reported.iter_rows(named=True):
        row_ref = record["row_ref"]
        for col_ref, value in record.items():
            if col_ref in ("row_ref", "row_name"):
                continue
            result = resolver.cell(row_ref, col_ref, limit=1000)
            assert result is not None, f"{template_id}: no lineage for {row_ref}/{col_ref}"
            query = result.query
            checked += 1

            # 1. The reported value is echoed verbatim (never recomputed).
            if value is None:
                assert result.cell_value is None, f"{template_id} {row_ref}/{col_ref}"
            else:
                assert result.cell_value == pytest.approx(value, rel=_RTOL, abs=_ATOL), (
                    f"{template_id} {row_ref}/{col_ref}"
                )

            # 2. Only row-backed cells have contributing legs.
            if query.kind != "rows":
                assert result.total_rows == 0, f"{template_id} {row_ref}/{col_ref} is {query.kind}"
                assert result.rows.height == 0

            # 3. A row-backed cell's returned legs ARE its predicate's rows — the
            #    drill-down runs the very predicate the generator ran.
            if query.kind == "rows":
                assert result.total_rows == _predicate_match_count(resolver, row_ref, col_ref), (
                    f"{template_id} {row_ref}/{col_ref} rows != predicate matches"
                )

            # 4. A row-backed cell with NO legs can only be null (inert/empty row)
            #    or zero (populated row, narrower predicate matched nothing).
            if query.kind == "rows" and result.total_rows == 0:
                assert value is None or value == 0.0, (
                    f"{template_id} {row_ref}/{col_ref} has no legs but reports {value}"
                )

            # 5. A summed, populated cell reconciles to the reported figure modulo
            #    the recorded Annex II §1.3 sign convention.
            if (
                query.kind == "rows"
                and query.metric == "sum"
                and result.total_rows > 0
                and result.contribution_total is not None
                and value is not None
            ):
                expected = -value if query.sign == "negated" else value
                assert result.contribution_total == pytest.approx(expected, rel=_RTOL, abs=_ATOL), (
                    f"{template_id} {row_ref}/{col_ref} does not reconcile"
                )

    assert checked > 100, f"{template_id}: the sweep did not cover the sheet"


# =============================================================================
# C 07.00 — the showcased cell's regulatory specifics (kept identical in substance)
# =============================================================================


def test_rwea_cell_value_is_the_reported_figure(source: _Source, c07) -> None:  # noqa: ANN001
    # Arrange
    reported = c07[_SHEET].filter(_row("0010"))["0220"][0]

    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0220", sheet=_SHEET)

    # Assert — the number the user clicked is ground truth, never recomputed.
    assert result is not None
    assert result.cell_value == pytest.approx(reported, rel=_RTOL, abs=_ATOL)


def test_rwea_contributions_reconcile_to_the_reported_cell(source: _Source) -> None:
    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0220", sheet=_SHEET)

    # Assert — the legs the drill-down shows SUM to the figure on the return.
    assert result is not None
    assert result.total_rows > 0
    assert result.contribution_total == pytest.approx(result.cell_value, rel=_RTOL, abs=_ATOL)


def test_rwea_cell_declares_its_metric_scope_and_basis(source: _Source) -> None:
    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0220", sheet=_SHEET)
    assert result is not None
    query = result.query

    # Assert — the cell is self-describing: what it sums, over which population.
    assert (query.kind, query.metric, query.metric_columns) == ("rows", "sum", ("rwa_final",))
    assert query.basis == "aggregator_exit"
    assert query.sign == "positive"
    assert any("Specialised lending" in step for step in query.scope)
    assert any(f"= {_SHEET}" in step for step in query.scope)


def test_contributing_rows_are_legs_of_the_corporate_book(source: _Source) -> None:
    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0220", sheet=_SHEET, limit=500)

    # Assert — a contributor is a LEG (guaranteed exposures are split), and every
    # one of them really is on this sheet's obligor class.
    assert result is not None
    rows = result.rows
    assert "reporting_leg_role" in rows.columns
    assert set(rows["reporting_class_origin"].unique()) <= {"corporate", "specialised_lending"}
    assert set(rows["reporting_leg_role"].unique()) <= {"whole", "guaranteed", "retained"}


def test_deduction_columns_declare_the_annex_ii_sign_convention(source: _Source) -> None:
    # Act — col 0030 (provisions) is a "(-)"-labelled deduction column.
    result = lineage.drilldown(source, "c07_00", "0010", "0030", sheet=_SHEET)

    # Assert — the sign flag is what reconciles a negatively-REPORTED cell with
    # the positive magnitudes its legs contribute, rather than the drill-down
    # silently disagreeing with the return.
    assert result is not None
    assert result.query.sign == "negated"
    positive = lineage.drilldown(source, "c07_00", "0010", "0220", sheet=_SHEET)
    assert positive is not None
    assert positive.query.sign == "positive"


def test_a_cell_whose_sources_are_never_produced_says_so(source: _Source, c07) -> None:  # noqa: ANN001
    # Arrange — col 0020 sums own_funds_deduction_amount, which the engine does
    # not produce onto the ledger (an unproduced source; col 0030 used to be the
    # showcase here, but R9 rebound it to the sealed provision carrier).
    reported = c07[_SHEET].filter(_row("0010"))["0020"][0]

    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0020", sheet=_SHEET)

    # Assert — the cell reports a structural null (its source column never
    # reaches the ledger), and the drill-down agrees: "we cannot compute this"
    # rather than a measured value — no source column, so no contribution.
    assert result is not None
    assert reported is None
    assert result.query.missing_columns == result.query.metric_columns
    assert result.query.is_source_backed is False
    assert result.contribution_total is None


def test_provisions_cell_is_source_backed_by_the_sealed_carrier(source: _Source, c07) -> None:  # noqa: ANN001
    # Arrange — R9 rebound col 0030 ("(-) Value adjustments and provisions") from
    # the never-sealed SCRA/GCRA sum to the sealed SA Art. 111(2) deducted
    # provision (via the module-derived c07_provision carrier). The portfolio
    # carries no provisions, so the cell is 0.0 — but now a MEASURED zero.
    reported = c07[_SHEET].filter(_row("0010"))["0030"][0]

    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0030", sheet=_SHEET)

    # Assert — a produced source reaches the ledger, so the zero is measured
    # (contribution_total is 0.0, not None) and the "(-)" sign is declared.
    assert result is not None
    assert reported == 0.0
    assert result.query.missing_columns == ()
    assert result.query.is_source_backed is True
    assert result.query.sign == "negated"
    assert result.contribution_total == pytest.approx(0.0, abs=_ATOL)


# =============================================================================
# Helpers
# =============================================================================


def _predicate_match_count(resolver: lineage.SheetLineage, row_ref: str, col_ref: str) -> int:
    """Independently re-apply the cell's predicate chain to the plan frame.

    Mirrors ``lineage._matching_rows`` using only the public ``RowPredicate.apply``,
    so the sweep's row count is checked against a second evaluation of the SAME
    predicate the generator ran — not the drill-down's own internal count.
    """
    plan = resolver._plan  # noqa: SLF001 - the sweep verifies the plan the resolver holds
    cell = plan.spec.cells.get((row_ref, col_ref))
    frame = plan.frame
    for predicate in (plan.spec.predicate, cell.predicate if cell is not None else None):
        if predicate is not None:
            frame = predicate.apply(frame)
    return frame.height


def _row(ref: str):  # noqa: ANN202 - pl.Expr
    import polars as pl

    return pl.col("row_ref") == ref
