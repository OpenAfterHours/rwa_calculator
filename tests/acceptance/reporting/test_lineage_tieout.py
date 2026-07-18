"""
Acceptance: report-cell lineage ties out to the REPORTED template cell.

Runs the rich reporting portfolio through the real pipeline, generates COREP
C 07.00, and checks the lineage of its cells against the figures the generator
actually reported.

This is the feature's correctness anchor. Lineage reads the template's own
``TemplateSpec`` and re-runs the same ``RowPredicate`` over the same prepared
frame, so agreement is structural — but only a test against the GENERATED
template can prove that the two post-``execute`` passes (all-null inert rows;
the Annex II §1.3 "(-)" negation) are accounted for rather than quietly
disagreed with.

The sweep (``test_every_cell_of_the_sheet_is_consistent_with_its_kind``) is what
makes the model trustworthy beyond the one showcased cell: it asserts EVERY
row x column of the corporates sheet is consistent with its declared kind.

References:
- docs/plans/report-cell-lineage.md §4.5 (B3)
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting import lineage
from rwa_calc.reporting.corep.generator import COREPGenerator

_SHEET = "corporate"
_RTOL = 1e-9
_ATOL = 1e-6


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
def c07(source: _Source):  # noqa: ANN201 - dict[str, pl.DataFrame]
    """The generated C 07.00 bundle — the figures actually reported."""
    return COREPGenerator().generate(source).c07_00


# =============================================================================
# The showcased cell: C 07.00 / corporate / row 0010 / col 0220 (RWEA)
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
    # Arrange — col 0030 sums the SCRA/GCRA provision amounts, which the engine
    # does not produce onto the ledger (a Phase 7 F6 permanently-null source).
    reported = c07[_SHEET].filter(_row("0010"))["0030"][0]

    # Act
    result = lineage.drilldown(source, "c07_00", "0010", "0030", sheet=_SHEET)

    # Assert — the cell reports 0.0 under the COREP zero policy, but that zero is
    # NOT a measured zero. The drill-down must distinguish "we computed zero"
    # from "we cannot compute this": no source column reaches the ledger, so
    # there is no contribution to total.
    assert result is not None
    assert reported == 0.0
    assert result.query.missing_columns == result.query.metric_columns
    assert result.query.is_source_backed is False
    assert result.contribution_total is None


# =============================================================================
# The sweep — every cell of the sheet, not just the showcased one
# =============================================================================


def test_every_cell_of_the_sheet_is_consistent_with_its_kind(source: _Source, c07) -> None:  # noqa: ANN001, C901
    # Arrange
    sheet = c07[_SHEET]
    reported = {
        (row["row_ref"], col): row[col]
        for row in sheet.iter_rows(named=True)
        for col in sheet.columns
        if col not in ("row_ref", "row_name")
    }

    # Act / Assert — one resolver for the whole sheet (one plan, one generation).
    resolver = lineage.sheet_lineage(source, "c07_00", _SHEET)
    assert resolver is not None
    checked = 0
    for (row_ref, col_ref), value in reported.items():
        result = resolver.cell(row_ref, col_ref)
        assert result is not None, f"no lineage for {row_ref}/{col_ref}"
        query = result.query
        checked += 1

        # 1. The reported value is always echoed verbatim.
        if value is None:
            assert result.cell_value is None, f"{row_ref}/{col_ref}"
        else:
            assert result.cell_value == pytest.approx(value, rel=_RTOL, abs=_ATOL)

        # 2. Only row-backed cells have contributing legs.
        if query.kind != "rows":
            assert result.total_rows == 0, f"{row_ref}/{col_ref} is {query.kind} but has rows"
            assert result.rows.height == 0

        # 3. A row-backed cell with NO contributing legs can never report a
        #    non-zero figure. It is either null (the row itself is inert/empty —
        #    the _null_empty_rows contract) or zero (the row is populated but
        #    this cell's own narrower predicate matched nothing, so the COREP
        #    zero policy applies). Both are legitimate; a number is not.
        if query.kind == "rows" and result.total_rows == 0:
            assert value is None or value == 0.0, (
                f"{row_ref}/{col_ref} has no contributing legs but reports {value}"
            )

        # 4. A summed, populated cell reconciles to the reported figure (modulo
        #    the recorded Annex II sign convention).
        if (
            query.kind == "rows"
            and query.metric == "sum"
            and result.total_rows > 0
            and result.contribution_total is not None
            and value is not None
        ):
            expected = -value if query.sign == "negated" else value
            assert result.contribution_total == pytest.approx(expected, rel=_RTOL, abs=_ATOL), (
                f"{row_ref}/{col_ref} does not reconcile"
            )

    assert checked > 100, "the sweep did not cover the sheet"


def _row(ref: str):  # noqa: ANN202 - pl.Expr
    import polars as pl

    return pl.col("row_ref") == ref
