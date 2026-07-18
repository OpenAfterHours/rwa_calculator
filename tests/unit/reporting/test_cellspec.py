"""
Unit tests for the declarative cell-spec executor (Phase 7 S7).

Pins the vocabulary semantics the strangler slices build on:
- Sum/Mean/WeightedAvg/Ratio/Count evaluation over the ledger frame
- the per-template empty-cell policy (COREP zero vs Pillar 3 null — the
  recorded drift, never unified)
- RowPredicate compilation over the canonical reporting-ledger columns
- PriorPeriod (None without a prior frame; evaluated over it when present)
- Formula ref resolution (own-row column ref first, then own-column row ref)
  and its prior_available semantics
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

import polars as pl
import pytest

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    Mean,
    PriorPeriod,
    Ratio,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext


@dataclass(frozen=True)
class _Row:
    ref: str
    name: str


def _ledger() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["A", "B", "C"],
            "reporting_class": ["corporate", "corporate", "retail"],
            "reporting_class_origin": ["corporate", "corporate", "corporate"],
            "reporting_method": ["FIRB", "STD", "FIRB"],
            "reporting_approach_origin": ["foundation_irb", "standardised", "foundation_irb"],
            "reporting_leg_role": ["whole", "guaranteed", "retained"],
            "reporting_on_balance_sheet": [True, False, None],
            "reporting_subclass": ["sme", None, None],
            "is_defaulted": [False, False, True],
            "reporting_ead": [100.0, 200.0, 300.0],
            "reporting_rw": [0.5, 0.2, 1.0],
            "rwa_final": [50.0, 40.0, 300.0],
        }
    )


def _spec(cells: dict, *, empty_cell: str = "zero", predicate=None) -> TemplateSpec:
    return TemplateSpec(
        name="t",
        rows=(_Row("1", "first"), _Row("2", "second")),
        column_refs=("a", "b"),
        cells=cells,
        predicate=predicate,
        empty_cell=cast(Literal["zero", "null"], empty_cell),
    )


class TestBindings:
    def test_sum_and_unbound_policy_zero(self) -> None:
        df = execute(_spec({("1", "a"): CellSpec(Sum("rwa_final"))}), _ledger())
        assert df.row(0, named=True) == {"row_ref": "1", "row_name": "first", "a": 390.0, "b": 0.0}
        assert df.row(1, named=True)["a"] == 0.0  # unbound, COREP zero policy

    def test_unbound_policy_null(self) -> None:
        df = execute(_spec({}, empty_cell="null"), _ledger())
        assert df.row(0, named=True)["a"] is None

    def test_empty_subset_null_vs_zero(self) -> None:
        empty_pred = RowPredicate(classes=("no_such_class",))
        cells = {("1", "a"): CellSpec(Sum("rwa_final"), predicate=empty_pred)}
        assert execute(_spec(cells, empty_cell="null"), _ledger()).row(0, named=True)["a"] is None
        assert execute(_spec(cells, empty_cell="zero"), _ledger()).row(0, named=True)["a"] == 0.0

    def test_mean_scale(self) -> None:
        """CR9 shape: the average-PD column reports the arithmetic mean x100."""
        cells = {("1", "a"): CellSpec(Mean("reporting_rw", scale=100.0))}
        df = execute(_spec(cells), _ledger())
        assert df.row(0, named=True)["a"] == pytest.approx((0.5 + 0.2 + 1.0) / 3 * 100.0)

    def test_weighted_avg_scale(self) -> None:
        """CR6 shape: PD/LGD columns report the weighted average x100."""
        cells = {("1", "a"): CellSpec(WeightedAvg("reporting_rw", scale=100.0))}
        df = execute(_spec(cells), _ledger())
        assert df.row(0, named=True)["a"] == pytest.approx(390.0 / 600.0 * 100.0)

    def test_weighted_avg_mean_ratio_count(self) -> None:
        cells = {
            ("1", "a"): CellSpec(WeightedAvg("reporting_rw", weight="reporting_ead")),
            ("1", "b"): CellSpec(Mean("reporting_rw")),
            ("2", "a"): CellSpec(Ratio("rwa_final", "reporting_ead", scale=100.0)),
            ("2", "b"): CellSpec(Count("reporting_class", distinct=True)),
        }
        df = execute(_spec(cells), _ledger())
        # (0.5*100 + 0.2*200 + 1.0*300) / 600
        assert df.row(0, named=True)["a"] == pytest.approx(390.0 / 600.0)
        assert df.row(0, named=True)["b"] == pytest.approx((0.5 + 0.2 + 1.0) / 3)
        assert df.row(1, named=True)["a"] == pytest.approx(390.0 / 600.0 * 100.0)
        assert df.row(1, named=True)["b"] == 2.0


class TestPredicates:
    def test_template_and_cell_predicates_conjoin(self) -> None:
        spec = _spec(
            {("1", "a"): CellSpec(Sum("rwa_final"), predicate=RowPredicate(method="FIRB"))},
            predicate=RowPredicate(classes_origin=("corporate",)),
        )
        # template: all 3 rows (origin corporate); cell: FIRB only -> A + C
        assert execute(spec, _ledger()).row(0, named=True)["a"] == 350.0

    def test_ledger_field_coverage(self) -> None:
        pred = RowPredicate(
            classes=("corporate",),
            approaches_origin=("foundation_irb", "standardised"),
            leg_role="guaranteed",
            on_balance_sheet=False,
            is_defaulted=False,
        )
        expr = pred.to_expr()
        assert expr is not None
        assert _ledger().filter(expr)["exposure_reference"].to_list() == ["B"]

    def test_subclass_and_no_constraint(self) -> None:
        assert RowPredicate().to_expr() is None
        pred = RowPredicate(subclass="sme")
        expr = pred.to_expr()
        assert expr is not None
        assert _ledger().filter(expr)["exposure_reference"].to_list() == ["A"]

    def test_between_half_open_band(self) -> None:
        """CR5 band shape: low <= col < high, so a boundary value falls in
        exactly one band."""
        in_band = RowPredicate(between=(("reporting_rw", 0.195, 0.205),))
        assert in_band.apply(_ledger())["exposure_reference"].to_list() == ["B"]
        at_lower = RowPredicate(between=(("reporting_rw", 0.2, 0.3),))
        assert at_lower.apply(_ledger())["exposure_reference"].to_list() == ["B"]
        at_upper = RowPredicate(between=(("reporting_rw", 0.1, 0.2),))
        assert at_upper.apply(_ledger()).height == 0

    def test_between_absent_column_yields_empty_subset(self) -> None:
        pred = RowPredicate(between=(("no_such_column", 0.0, 1.0),))
        assert pred.apply(_ledger()).height == 0

    def test_any_of_unions_class_and_tolerant_equals_limbs(self) -> None:
        """CR5 row-9 shape: exposure class OR a split-leg role column."""
        data = _ledger().with_columns(
            pl.Series("re_split_role", [None, "secured", None], dtype=pl.String)
        )
        pred = RowPredicate(
            any_of=(
                RowPredicate(classes=("retail",)),
                RowPredicate(equals=(("re_split_role", "secured"),)),
            )
        )
        assert pred.apply(data)["exposure_reference"].to_list() == ["B", "C"]

    def test_any_of_limb_with_absent_tolerant_column_matches_nothing(self) -> None:
        """A role limb over a frame without the role column contributes no
        rows — the class limb still matches."""
        pred = RowPredicate(
            any_of=(
                RowPredicate(classes=("retail",)),
                RowPredicate(equals=(("re_split_role", "secured"),)),
            )
        )
        assert pred.apply(_ledger())["exposure_reference"].to_list() == ["C"]

    def test_any_of_conjoins_with_outer_terms(self) -> None:
        pred = RowPredicate(
            is_defaulted=False,
            any_of=(
                RowPredicate(classes=("retail",)),
                RowPredicate(classes=("corporate",)),
            ),
        )
        assert pred.apply(_ledger())["exposure_reference"].to_list() == ["A", "B"]

    def test_nested_any_of_raises(self) -> None:
        with pytest.raises(ValueError, match="any_of"):
            RowPredicate(any_of=(RowPredicate(any_of=(RowPredicate(),)),))


class TestSafeSum:
    def test_sums_present_columns_and_skips_absent(self) -> None:
        data = _ledger().with_columns(pl.Series("drawn_amount", [10.0, 20.0, 30.0]))
        cells = {("1", "a"): CellSpec(SafeSum(("drawn_amount", "interest")))}
        assert execute(_spec(cells), data).row(0, named=True)["a"] == 60.0

    def test_no_named_column_present_takes_empty_policy(self) -> None:
        cells = {("1", "a"): CellSpec(SafeSum(("drawn_amount", "interest")))}
        assert execute(_spec(cells, empty_cell="null"), _ledger()).row(0, named=True)["a"] is None
        assert execute(_spec(cells, empty_cell="zero"), _ledger()).row(0, named=True)["a"] == 0.0

    def test_empty_subset_with_present_column_is_zero(self) -> None:
        """kernel safe_sum_or_none semantics: a present column over an empty
        subset sums to 0.0 even under the null template policy."""
        data = _ledger().with_columns(pl.Series("drawn_amount", [10.0, 20.0, 30.0]))
        cells = {
            ("1", "a"): CellSpec(
                SafeSum(("drawn_amount",)), predicate=RowPredicate(classes=("no_such_class",))
            )
        }
        assert execute(_spec(cells, empty_cell="null"), data).row(0, named=True)["a"] == 0.0


class TestPriorPeriodAndFormula:
    def test_prior_period_none_without_prior_frame(self) -> None:
        cells = {("1", "a"): CellSpec(PriorPeriod(Sum("rwa_final")))}
        df = execute(_spec(cells, empty_cell="null"), _ledger(), ReportingContext())
        assert df.row(0, named=True)["a"] is None

    def test_prior_period_evaluates_over_prior_frame(self) -> None:
        ctx = ReportingContext(previous_period_results=_ledger().lazy())
        cells = {("1", "a"): CellSpec(PriorPeriod(Sum("rwa_final")))}
        df = execute(_spec(cells, empty_cell="null"), _ledger().head(1), ctx)
        assert df.row(0, named=True)["a"] == 390.0

    def test_formula_cross_row_resolution_and_prior_flag(self) -> None:
        """CR8 shape: row 2 col a = row-1 value minus a constant; the fn sees
        prior availability so flow residuals can null without a prior period."""

        def residual(
            cells: Mapping[str, int | float | None], prior_available: bool
        ) -> float | None:
            if not prior_available:
                return None
            return (cells["1"] or 0.0) - 40.0

        cells = {
            ("1", "a"): CellSpec(Sum("rwa_final")),
            ("2", "a"): CellSpec(Formula(refs=("1",), fn=residual)),
        }
        no_prior = execute(_spec(cells, empty_cell="null"), _ledger(), ReportingContext())
        assert no_prior.row(1, named=True)["a"] is None

        with_prior = execute(
            _spec(cells, empty_cell="null"),
            _ledger(),
            ReportingContext(previous_period_results=_ledger().lazy()),
        )
        assert with_prior.row(1, named=True)["a"] == 350.0

    def test_formula_own_row_column_ref_wins(self) -> None:
        """COREP shape: refs resolve as column refs in the formula's own row."""
        cells = {
            ("1", "a"): CellSpec(Sum("rwa_final")),
            ("1", "b"): CellSpec(Formula(refs=("a",), fn=lambda c, _p: (c["a"] or 0.0) * 2)),
        }
        df = execute(_spec(cells), _ledger())
        assert df.row(0, named=True)["b"] == 780.0

    def test_formula_unknown_ref_raises(self) -> None:
        cells = {("1", "a"): CellSpec(Formula(refs=("zz",), fn=lambda c, _p: 0.0))}
        with pytest.raises(KeyError, match="zz"):
            execute(_spec(cells), _ledger())


class TestOutputShape:
    def test_schema_matches_the_generator_convention(self) -> None:
        df = execute(_spec({}), _ledger())
        assert df.columns == ["row_ref", "row_name", "a", "b"]
        assert df.schema["row_ref"] == pl.String
        assert df.schema["a"] == pl.Float64
        assert df.height == 2
