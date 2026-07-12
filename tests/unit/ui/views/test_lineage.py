"""
Unit tests: the cell-lineage drill-down view (ui.views.lineage).

Pins what a reader must not get wrong when they click a cell:
- contributions reconcile to the REPORTED figure across the Annex II §1.3 sign
  convention (a deduction column is reported negative while its legs contribute
  positive magnitudes) — the panel says so rather than looking self-contradictory;
- a cell whose sources the engine never produces is flagged: its reported 0.0 is
  the template's empty-cell policy, not a measured zero;
- criteria on template-derived discriminators are marked as such, so they are not
  mistaken for sealed facts about the exposure.

References:
- docs/plans/report-cell-lineage.md §5 (Phase C)
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.lineage import CellLineage, CellQuery, FilterTerm
from rwa_calc.ui.views import lineage as view

# =============================================================================
# Builders
# =============================================================================


def _query(**kwargs: object) -> CellQuery:
    base: dict[str, object] = {
        "template_id": "c07_00",
        "sheet": "corporate",
        "row_ref": "0010",
        "col_ref": "0220",
        "row_name": "TOTAL EXPOSURES",
        "kind": "rows",
        "metric": "sum",
        "metric_columns": ("rwa_final",),
        "filter_terms": (),
        "scope": ("Standardised-approach legs",),
    }
    base.update(kwargs)
    return CellQuery(**base)  # type: ignore[arg-type]


def _result(query: CellQuery, **kwargs: object) -> CellLineage:
    base: dict[str, object] = {
        "query": query,
        "run_id": "r1",
        "cell_value": 1_000_000.0,
        "contribution_total": 1_000_000.0,
        "total_rows": 1,
        "rows": pl.DataFrame({"exposure_reference": ["LN-1"], "rwa_final": [1_000_000.0]}),
    }
    base.update(kwargs)
    return CellLineage(**base)  # type: ignore[arg-type]


def _panel(result: CellLineage) -> view.LineagePanel:
    return view.lineage_panel(
        result, run_id="r1", template_title="C 07.00", col_name="RWEA", back_url="/back"
    )


# =============================================================================
# Reconciliation against the reported figure
# =============================================================================


def test_contributions_reconcile_to_the_reported_cell() -> None:
    # Act
    panel = _panel(_result(_query()))

    # Assert
    assert panel.reconciles is True
    assert panel.cell_display == "1,000,000"
    assert panel.contribution_display == "1,000,000"


def test_a_deduction_column_reconciles_across_the_sign_convention() -> None:
    # Arrange — reported negative (Annex II §1.3); legs contribute positive.
    query = _query(col_ref="0030", sign="negated", metric_columns=("provisions",))
    result = _result(query, cell_value=-500.0, contribution_total=500.0)

    # Act
    panel = _panel(result)

    # Assert — the panel must not look like it disagrees with the return.
    assert panel.reconciles is True
    assert panel.sign == "negated"
    assert "deduction column" in (panel.warning or "")


def test_a_genuine_mismatch_is_reported_as_a_defect() -> None:
    # Arrange
    result = _result(_query(), cell_value=1_000_000.0, contribution_total=999.0)

    # Act
    panel = _panel(result)

    # Assert — this is the one thing the drill-down exists to catch.
    assert panel.reconciles is False


def test_reconciliation_is_not_claimed_when_it_does_not_apply() -> None:
    # Arrange — a formula cell has no contributing legs to sum.
    query = _query(kind="formula", metric=None, metric_columns=(), refs=("0010", "0030"))
    result = _result(query, contribution_total=None, total_rows=0, rows=pl.DataFrame())

    # Act
    panel = _panel(result)

    # Assert — None, never a False that merely means "not checked".
    assert panel.reconciles is None
    assert panel.refs == ("0010", "0030")
    assert "other cells" in panel.summary


# =============================================================================
# The honest warnings
# =============================================================================


def test_a_cell_whose_sources_are_never_produced_warns_it_is_not_a_measured_zero() -> None:
    # Arrange — C 07.00 col 0030: the engine does not produce the provision columns.
    query = _query(
        col_ref="0030",
        metric_columns=("scra_provision_amount", "gcra_provision_amount"),
        missing_columns=("scra_provision_amount", "gcra_provision_amount"),
    )
    result = _result(query, cell_value=0.0, contribution_total=None, total_rows=0)

    # Act
    panel = _panel(result)

    # Assert — "we cannot compute this" must not read as "we computed zero".
    assert panel.warning is not None
    assert "does not produce its source" in panel.warning
    assert "scra_provision_amount" in panel.warning
    assert "not a measured value" in panel.warning


def test_a_cell_with_no_matching_legs_says_there_is_nothing_to_attribute() -> None:
    # Arrange
    result = _result(_query(), cell_value=0.0, contribution_total=0.0, total_rows=0)

    # Act
    panel = _panel(result)

    # Assert
    assert "No exposure legs match" in (panel.warning or "")


# =============================================================================
# Criteria, in terms a reviewer can check
# =============================================================================


def test_criteria_distinguish_sealed_facts_from_template_derived_discriminators() -> None:
    # Arrange
    query = _query(
        filter_terms=(
            FilterTerm("reporting_class_origin", "in", ("corporate",), "ledger"),
            FilterTerm("c07_rw_band", "eq", "100%", "derived"),
        )
    )

    # Act
    criteria = view.criteria(query)

    # Assert — a derived discriminator must not pass as a fact about the exposure.
    assert criteria[0] == "reporting_class_origin is one of: corporate"
    assert criteria[1] == "c07_rw_band = 100% (template-derived)"


def test_an_unconstrained_cell_has_no_criteria() -> None:
    # Act — C 07.00's total row covers the whole sheet population.
    panel = _panel(_result(_query()))

    # Assert
    assert panel.criteria == ()
    assert panel.metric == "Sum of rwa_final"
    assert panel.scope == ("Standardised-approach legs",)
