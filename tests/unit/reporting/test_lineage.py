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

from rwa_calc.reporting import lineage
from rwa_calc.reporting.cellspec import (
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
    WeightedAvg,
)

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
