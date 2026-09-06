"""
Unit tests for the cellspec compiled-expression caches.

The executor's Python-side expression construction is memoised on
(predicate value, column signature) and (spec value, column signature).
These tests pin what makes that safe — every key carries everything the
output depends on, and nothing data-dependent is cached:

- a compiled predicate is keyed on the frame's COLUMN SIGNATURE: a tolerant
  term compiled to match-nothing on a frame lacking its column must not be
  reused on a frame that has it (the trap: a cached ``pl.lit(False)``);
- a sheet plan is data-independent: the same spec over two frames with the
  same columns gives each frame its own numbers; a spec REBUILT by value hits
  the plan cache, a spec differing in one cell does not, and the same spec
  over a frame with a different column signature does not;
- a spec that cannot be hashed by value still executes, uncached.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date

import polars as pl
from polars.testing import assert_frame_equal

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting import cellspec
from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.corep import c07
from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.fixtures.reporting_portfolio import build_reporting_bundle


@dataclass(frozen=True)
class _Row:
    ref: str
    name: str


def _ledger(scale: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["A", "B", "C"],
            "reporting_class": ["corporate", "corporate", "retail"],
            "reporting_ead": [100.0, 200.0, 300.0],
            "rwa_final": [50.0 * scale, 40.0 * scale, 300.0 * scale],
        }
    )


def _spec(cells: dict[tuple[str, str], CellSpec]) -> TemplateSpec:
    return TemplateSpec(
        name="t",
        rows=(_Row("1", "one"),),
        column_refs=("a", "b"),
        cells=cells,
        empty_cell="zero",
    )


def _clear_caches() -> None:
    cellspec._intern_columns.cache_clear()  # noqa: SLF001 - the caches under test
    cellspec._compile_predicate.cache_clear()  # noqa: SLF001
    cellspec._spec_key.cache_clear()  # noqa: SLF001
    cellspec._intern_spec_key.cache_clear()  # noqa: SLF001
    cellspec._cached_sheet_plan.cache_clear()  # noqa: SLF001


class TestPredicateCache:
    def test_equal_predicates_compile_once_per_column_signature(self) -> None:
        _clear_caches()
        first = RowPredicate(classes=("corporate",))
        second = RowPredicate(classes=("corporate",))
        assert first is not second, "the test needs two OBJECTS equal by value"

        out_first = first.apply(_ledger())["exposure_reference"].to_list()
        out_second = second.apply(_ledger())["exposure_reference"].to_list()

        assert out_first == out_second == ["A", "B"]
        info = cellspec._compile_predicate.cache_info()  # noqa: SLF001
        assert (info.misses, info.hits) == (1, 1)

    def test_tolerant_term_recompiles_when_its_column_appears(self) -> None:
        """A tolerant ``equals`` column absent from the frame compiles to
        match-nothing. Applied FIRST to a frame without the column and THEN to
        one with it, the second frame must get its own compile — a cached
        match-nothing reused across signatures would silently empty the
        subset on every frame that carries the column."""
        _clear_caches()
        pred = RowPredicate(equals=(("flag", True),))
        without = _ledger()
        with_flag = _ledger().with_columns(pl.Series("flag", [True, False, True]))

        assert pred.apply(without).height == 0
        assert pred.apply(with_flag)["exposure_reference"].to_list() == ["A", "C"]
        assert cellspec._compile_predicate.cache_info().misses == 2  # noqa: SLF001


class TestSheetPlanCache:
    def test_plan_is_data_independent(self) -> None:
        """The same spec object over two frames with the same columns but
        different values: one plan compile, two different (correct) sums."""
        _clear_caches()
        spec = _spec({("1", "a"): CellSpec(Sum("rwa_final"))})

        assert execute(spec, _ledger()).row(0, named=True)["a"] == 390.0
        assert execute(spec, _ledger(scale=2.0)).row(0, named=True)["a"] == 780.0
        info = cellspec._cached_sheet_plan.cache_info()  # noqa: SLF001
        assert (info.misses, info.hits) == (1, 1)

    def test_rebuilt_spec_hits_and_a_changed_cell_misses(self) -> None:
        _clear_caches()
        rebuilt = _spec({("1", "a"): CellSpec(Sum("rwa_final"))})
        again = _spec({("1", "a"): CellSpec(Sum("rwa_final"))})
        assert rebuilt is not again, "the test needs two spec OBJECTS equal by value"
        changed = _spec({("1", "a"): CellSpec(Sum("reporting_ead"))})

        assert execute(rebuilt, _ledger()).row(0, named=True)["a"] == 390.0
        assert execute(again, _ledger()).row(0, named=True)["a"] == 390.0
        assert execute(changed, _ledger()).row(0, named=True)["a"] == 600.0

        # Three distinct objects -> three identity-front misses; two spec
        # VALUES -> one plan hit (the rebuilt spec) and two plan misses.
        assert cellspec._spec_key.cache_info().misses == 3  # noqa: SLF001
        info = cellspec._cached_sheet_plan.cache_info()  # noqa: SLF001
        assert (info.misses, info.hits) == (2, 1)

    def test_column_signature_is_part_of_the_plan_key(self) -> None:
        """A Sum over a column ABSENT from the frame is None (col_sum's own
        contract); the same spec over a frame that HAS the column sums it.
        Same spec object, two signatures, two plans."""
        _clear_caches()
        spec = _spec({("1", "a"): CellSpec(Sum("rwa_final"))})

        assert execute(spec, _ledger().drop("rwa_final")).row(0, named=True)["a"] is None
        assert execute(spec, _ledger()).row(0, named=True)["a"] == 390.0
        info = cellspec._cached_sheet_plan.cache_info()  # noqa: SLF001
        assert (info.misses, info.hits) == (2, 0)

    def test_unhashable_formula_callable_executes_uncached(self) -> None:
        """A callable defining ``__eq__`` without ``__hash__`` makes the spec
        unhashable by value: the executor must still run it — compiled per
        call — rather than raise from the cache key."""

        class _Unhashable:
            __hash__ = None  # type: ignore[assignment]

            def __eq__(self, other: object) -> bool:
                return self is other

            def __call__(self, _cells: Mapping[str, float | None], _prior: bool) -> float:
                return 42.0

        _clear_caches()
        spec = _spec(
            {
                ("1", "a"): CellSpec(Sum("rwa_final")),
                ("1", "b"): CellSpec(Formula(refs=(), fn=_Unhashable())),
            }
        )

        row = execute(spec, _ledger()).row(0, named=True)

        assert (row["a"], row["b"]) == (390.0, 42.0)
        assert cellspec._cached_sheet_plan.cache_info().misses == 0  # noqa: SLF001


class TestConstFormulaFactory:
    def test_const_returns_one_callable_per_value(self) -> None:
        """C 07.00 rebuilds its spec per generate call; ``_const`` returning
        the SAME callable per value is what keeps the rebuilt spec value-equal
        to the last one (a ``Formula`` participates in the plan key through
        the identity of its ``fn``)."""
        assert c07._const(None) is c07._const(None)  # noqa: SLF001
        assert c07._const(0.0) is c07._const(0.0)  # noqa: SLF001
        assert c07._const(0.0)({}, False) == 0.0  # noqa: SLF001
        assert c07._const(None)({}, False) is None  # noqa: SLF001


class TestWarmCacheServesTheSameNumbers:
    def test_second_generation_matches_the_first_on_a_real_portfolio(self) -> None:
        """The sheet-plan cache is keyed on the spec OBJECT's identity, so the
        invariant a template author must keep — build the ``cells`` mapping,
        construct the spec, never mutate it — has one observable form: a
        second COREP generation in the same process, served from the warm
        caches, reports the same numbers as the cold first one. Compared at
        the goldens' tolerance because the engine's own summation order
        drifts at the last ULP between runs, with or without the caches."""
        # Arrange
        bundle = build_reporting_bundle()
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
        results = PipelineOrchestrator().run_with_data(bundle, config).results

        # Act
        cold = COREPGenerator().generate_from_lazyframe(results, framework="CRR")
        warm = COREPGenerator().generate_from_lazyframe(results, framework="CRR")

        # Assert
        compared = 0
        for field in fields(cold):
            first, second = getattr(cold, field.name), getattr(warm, field.name)
            if isinstance(first, pl.DataFrame):
                assert_frame_equal(first, second, rel_tol=1e-9, abs_tol=1e-6)
                compared += 1
            elif isinstance(first, dict):
                assert first.keys() == second.keys(), field.name
                for key, sheet in first.items():
                    if isinstance(sheet, pl.DataFrame):
                        assert_frame_equal(sheet, second[key], rel_tol=1e-9, abs_tol=1e-6)
                        compared += 1
        assert compared > 0, "the bundle carried no sheets to compare"
