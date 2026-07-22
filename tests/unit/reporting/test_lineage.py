"""
Unit tests: report-cell lineage (reporting.lineage).

Pins the model that makes the drill-down honest:
- the SIX cell kinds fall out of the binding vocabulary, so every cell gets a
  truthful answer — not just the summable ones. A formula cell derives from
  other CELLS (no rows); a constant cell is a source the engine never produces;
  an unbound cell is the template's empty policy.
- a cell's filter criteria are read off the spec the generator executes, and each
  term is tagged ledger (a sealed fact) or derived (a template discriminator).
- an uninstrumented template resolves to None — a clean "no lineage", never a
  re-derived guess.

References:
- docs/plans/report-cell-lineage.md §4 (Phase B)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest

from rwa_calc.reporting import lineage
from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    FirstNonNull,
    Formula,
    Mean,
    PriorPeriod,
    Ratio,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

# =============================================================================
# The six cell kinds
# =============================================================================


def test_summing_bindings_are_row_backed() -> None:
    # Act / Assert — these are the cells with contributing exposures.
    assert lineage._binding_facts(Sum("rwa_final")) == ("rows", "sum", ("rwa_final",), ())
    assert lineage._binding_facts(SafeSum(("a", "b"))) == ("rows", "sum", ("a", "b"), ())
    assert lineage._binding_facts(Mean("pd")) == ("rows", "mean", ("pd",), ())
    assert lineage._binding_facts(WeightedAvg("lgd")) == (
        "rows",
        "weighted_avg",
        ("lgd", "reporting_ead"),
        (),
    )
    assert lineage._binding_facts(Ratio("a", "b")) == ("rows", "ratio", ("a", "b"), ())
    assert lineage._binding_facts(Count("x", distinct=True)) == ("rows", "count", ("x",), ())
    assert lineage._binding_facts(FirstNonNull("x")) == ("rows", "first_non_null", ("x",), ())


def test_a_formula_cell_derives_from_other_cells_not_from_rows() -> None:
    # Arrange — C 07.00's 0040 = 0010 - 0030 waterfall.
    binding = Formula(refs=("0010", "0030"), fn=lambda _cells, _prior: 0.0)

    # Act
    kind, metric, columns, refs = lineage._binding_facts(binding)

    # Assert
    assert (kind, metric, columns) == ("formula", None, ())
    assert refs == ("0010", "0030")


def test_a_refless_formula_is_a_constant_not_a_derivation_of_nothing() -> None:
    # Arrange — the recorded structural-null / fixed-zero cells (e.g. 0210).
    binding = Formula(refs=(), fn=lambda _cells, _prior: None)

    # Act
    kind, _metric, _columns, refs = lineage._binding_facts(binding)

    # Assert
    assert kind == "constant"
    assert refs == ()


def test_side_context_and_prior_period_are_out_of_frame_kinds() -> None:
    # Act / Assert — C 07.00 col 0100 (substitution inflow); CR8/C 08.04 opening.
    assert lineage._binding_facts(SideContext("substitution_inflow")) == (
        "side_context",
        "side_context",
        ("substitution_inflow",),
        (),
    )
    assert lineage._binding_facts(PriorPeriod(Sum("rwa_final"))) == (
        "prior_period",
        "sum",
        ("rwa_final",),
        (),
    )


def test_an_unbound_cell_is_the_templates_empty_policy() -> None:
    # Act / Assert
    assert lineage._binding_facts(None) == ("unbound", None, (), ())


# =============================================================================
# Filter criteria — read off the spec, tagged ledger vs derived
# =============================================================================


_SEALED = {"reporting_class_origin", "reporting_leg_role", "is_defaulted", "reporting_rw"}


def test_sealed_ledger_terms_are_tagged_ledger() -> None:
    # Arrange
    predicate = RowPredicate(
        classes_origin=("corporate",), leg_role="guaranteed", is_defaulted=True
    )

    # Act
    terms = lineage._terms(predicate, _SEALED)

    # Assert
    assert [(t.column, t.op, t.value, t.source) for t in terms] == [
        ("reporting_class_origin", "in", ("corporate",), "ledger"),
        ("reporting_leg_role", "eq", "guaranteed", "ledger"),
        ("is_defaulted", "eq", True, "ledger"),
    ]


def test_template_derived_discriminators_are_tagged_derived() -> None:
    # Arrange — C 07.00 derives its RW band / CCF bucket for its own row structure.
    predicate = RowPredicate(equals=(("c07_rw_band", "100%"),))

    # Act
    (term,) = lineage._terms(predicate, _SEALED)

    # Assert — a reviewer can see this is not a sealed fact about the exposure.
    assert (term.column, term.source) == ("c07_rw_band", "derived")


def test_band_and_any_of_terms_are_flattened() -> None:
    # Arrange
    predicate = RowPredicate(
        rw_between=(0.0, 0.2),
        between=(("cr5_rw_bucket", 0.35, 0.5),),
        any_of=(RowPredicate(classes_origin=("retail",)),),
    )

    # Act
    terms = lineage._terms(predicate, _SEALED)

    # Assert
    ops = {(t.column, t.op) for t in terms}
    assert ("reporting_rw", "between") in ops
    assert ("cr5_rw_bucket", "between") in ops
    assert ("any_of", "any_of") in ops


def test_no_predicate_means_no_constraint() -> None:
    # Act / Assert — C 07.00's total row (0010) selects the whole sheet.
    assert lineage._terms(None, _SEALED) == []
    assert lineage._terms(RowPredicate(), _SEALED) == []


# =============================================================================
# Coverage boundary
# =============================================================================


def test_only_instrumented_templates_have_lineage() -> None:
    # Assert — C 34.x / CCR1-8 are still imperative: no TemplateSpec to read, so
    # no lineage. Coverage is explicit, never a guess.
    assert "c07_00" in lineage.LINEAGE_PLANS
    assert "c34_01" not in lineage.LINEAGE_PLANS
    assert "ccr1" not in lineage.LINEAGE_PLANS


# R20 — the four single-frame Pillar 3 templates (cr4/cr6a/cr7/cr8) instrumented.
_R20_SINGLE_FRAME_TEMPLATES = ("cr4", "cr6a", "cr7", "cr8")


@pytest.mark.parametrize("template_id", _R20_SINGLE_FRAME_TEMPLATES)
def test_r20_pillar3_templates_are_single_frame_instrumented(template_id: str) -> None:
    # Assert — each R20 template is instrumented as a SINGLE-FRAME provider (no
    # sheet axis -> cells report sheet=None), with a populated scope (the
    # population wording a reviewer checks) and no sheet label.
    assert lineage.is_instrumented(template_id)
    provider = lineage.LINEAGE_PLANS[template_id]
    assert provider.single_frame is True
    assert provider.scope
    assert provider.sheet_label == ""


def test_cr8_opening_row_is_a_prior_period_cell() -> None:
    # Assert — CR8's row 1 (opening RWEA) is a PriorPeriod binding, so its cell
    # kind is "prior_period" (out-of-frame, not row-backed). CR8 is the first
    # such template through the tie-out sweep.
    from rwa_calc.reporting.pillar3.cr8 import CR8_SPEC

    binding = CR8_SPEC.cells[("1", "a")].binding
    kind, metric, _columns, _refs = lineage._binding_facts(binding)
    assert (kind, metric) == ("prior_period", "sum")


def test_cr8_prior_period_derived_cells_are_refused_by_the_resolver() -> None:
    # Arrange — a current-period IRB frame (CR8 reads approach_applied + rwa_final).
    frame = pl.DataFrame(
        {
            "exposure_reference": ["EXP-FIRB", "EXP-AIRB"],
            "approach_applied": ["foundation_irb", "advanced_irb"],
            "rwa_final": [720_000.0, 430_000.0],
        }
    )
    resolver = lineage.sheet_lineage(_FrameSource(frame), "cr8")
    assert resolver is not None

    # Act / Assert — the closing row (9, current period) resolves and is
    # row-backed; the opening (1, PriorPeriod) and residual (8, Formula over the
    # opening) rows are prior-period-derived, so the resolver DECLINES them — a
    # clean refusal, never a cell_value that could contradict a comparative period.
    closing = resolver.query("9", "a")
    assert closing is not None
    assert closing.derives_from_prior_period is False
    assert resolver.cell("9", "a") is not None
    for prior_row in ("1", "8"):
        query = resolver.query(prior_row, "a")
        assert query is not None
        assert query.derives_from_prior_period is True
        assert resolver.cell(prior_row, "a") is None


# =============================================================================
# Sheet-key resolution — multi-sheet vs the single-frame {sheet: None} convention
# =============================================================================


def _stub_plan() -> SheetPlan:
    """A minimal SheetPlan — enough for the key-only resolution helper."""
    return SheetPlan(
        spec=TemplateSpec(name="t", rows=(), column_refs=(), cells={}, empty_cell="zero"),
        frame=pl.DataFrame(),
        ctx=ReportingContext(),
        negative_cols=frozenset(),
    )


def test_resolve_sheet_key_multi_sheet_defaults_to_first_and_rejects_unknown() -> None:
    # Arrange
    plans = {"corporate": _stub_plan(), "retail": _stub_plan()}

    # Act / Assert — sheet=None defaults to the first sheet; a named sheet
    # resolves to itself; an unknown sheet is unresolvable (a clean no-lineage).
    assert lineage._resolve_sheet_key(plans, None, single_frame=False) == ("corporate", "corporate")
    assert lineage._resolve_sheet_key(plans, "retail", single_frame=False) == ("retail", "retail")
    assert lineage._resolve_sheet_key(plans, "nope", single_frame=False) is None


def test_resolve_sheet_key_single_frame_always_reports_sheet_none() -> None:
    # Arrange — a single-frame template keys its one plan under a canonical key.
    plans = {"__single__": _stub_plan()}

    # Act / Assert — the sheet param is ignored; the reported sheet is None.
    assert lineage._resolve_sheet_key(plans, None, single_frame=True) == ("__single__", None)
    assert lineage._resolve_sheet_key(plans, "anything", single_frame=True) == ("__single__", None)


@dataclass(frozen=True)
class _Row:
    """A structural TemplateRow for a synthetic spec."""

    ref: str
    name: str


class _FrameSource:
    """A minimal ResultsSource over a hand-built frame (no parquet round-trip)."""

    framework = "CRR"

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def scan_results(self) -> pl.LazyFrame:
        return self._frame.lazy()


def _single_frame_provider() -> tuple[lineage._Provider, pl.DataFrame]:
    """A synthetic single-frame template: one plan, one Sum cell, sheet=None."""
    frame = pl.DataFrame(
        {
            "reporting_class_origin": ["corporate", "corporate"],
            "rwa_final": [100.0, 50.0],
            "exposure_reference": ["E1", "E2"],
        }
    )
    spec = TemplateSpec(
        name="t_demo",
        rows=(_Row("0010", "Total"),),
        column_refs=("0220",),
        cells={("0010", "0220"): CellSpec(Sum("rwa_final"))},
        empty_cell="zero",
    )
    ctx = ReportingContext()
    plan = SheetPlan(spec=spec, frame=frame, ctx=ctx, negative_cols=frozenset())

    def _plans(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, SheetPlan]:
        return {"__single__": plan}

    def _generate(
        _results: pl.LazyFrame, _cols: set[str], _framework: str, _errors: list[str]
    ) -> dict[str, pl.DataFrame]:
        return {"__single__": execute(spec, frame, ctx)}

    provider = lineage._Provider(
        plans=_plans,
        generate=_generate,
        scope=("demo scope",),
        sheet_label="",
        single_frame=True,
    )
    return provider, frame


def test_single_frame_template_resolves_end_to_end_with_sheet_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — register a synthetic single-frame provider.
    provider, frame = _single_frame_provider()
    monkeypatch.setitem(lineage.LINEAGE_PLANS, "t_demo", provider)

    # Act — no sheet named (the single-frame caller passes None).
    result = lineage.drilldown(_FrameSource(frame), "t_demo", "0010", "0220")

    # Assert — the cell resolves, its sheet axis is None, and its legs sum back.
    assert result is not None
    assert result.query.sheet is None
    assert result.cell_value == pytest.approx(150.0)
    assert result.contribution_total == pytest.approx(150.0)
    assert result.total_rows == 2
    # A single-frame template adds no "Sheet: … = …" scope line.
    assert not any("Sheet:" in step for step in result.query.scope)
