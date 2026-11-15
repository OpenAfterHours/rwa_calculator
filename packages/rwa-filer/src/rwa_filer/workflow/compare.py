"""
Compare — two returns for the same entity and date, and why they differ.

Pipeline position:
    baseline SourceReading + candidate SourceReading  ->  compare_returns
        ->  boe.engine.trace_rules (each file)  ->  explain.explain_differences
        ->  ReturnComparison  ->  render_text (``rwa-filer compare``) / as_record (JSON)
            / the dashboard's Compare page

Key responsibilities:
- Put every cell either return reports into one category: the same, within
  the rounding the two files state, a zero against a blank, in a template only
  one return reports, or a material difference.
- Group the material differences into findings, each saying which side the
  Bank's own rules point at (``explain``), so a reviewer explains a handful of
  findings instead of reading thousands of cells.
- Keep what reading each file could not place — a fact the module has no cell
  for — beside the comparison, never silently out of it: such a fact is in
  neither return as far as the regulator's checks go.
- Say when the two returns are equivalent, and mean it: same header, same
  templates, nothing unplaced, no material difference, and no rule that breaks
  in one file only.

Which return is which: the BASELINE is the one already trusted — the filing
already made, or the return the firm's current system produces — and the
CANDIDATE is the one being checked against it. A difference is candidate minus
baseline. Nothing here assumes the candidate is right.

References:
- rwa_filer.workflow.explain — the categories and how findings are formed
- rwa_filer.boe.engine.trace_rules — the rule evaluations both sides are judged by
- BoE XBRL Filing Manual v1.0.1, rule 2.18 (interpretation of decimals)
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, RuleTrace, trace_rules
from rwa_filer.model import COORDINATE_COLUMNS
from rwa_filer.release import resolve_release
from rwa_filer.validate.structure import filing_indicators
from rwa_filer.workflow.explain import (
    CATEGORIES,
    CATEGORY_MATERIAL,
    CATEGORY_ROUNDING,
    CATEGORY_SAME,
    CATEGORY_SCOPE,
    CATEGORY_ZERO_OR_BLANK,
    POINTS_AT_INPUTS,
    POINTS_AT_NEITHER,
    SIDE_BASELINE,
    SIDE_CANDIDATE,
    Cell,
    CellDifference,
    Discrepancy,
    Names,
    explain_differences,
)

if TYPE_CHECKING:
    from datetime import date

    from rwa_filer.boe.engine import Evaluation
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.readers import SourceReading
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The cell table, in column order: each side's figure or text, the category,
#: which side holds a cell only one return reports, the difference
#: (candidate - baseline) and the number of the finding that explains it.
COMPARISON_SCHEMA: Final = pl.Schema(
    {
        "table": pl.String,
        "sheet": pl.String,
        "open_key": pl.String,
        "row": pl.String,
        "column": pl.String,
        "baseline": pl.Float64,
        "candidate": pl.Float64,
        "baseline_text": pl.String,
        "candidate_text": pl.String,
        "category": pl.String,
        "held_by": pl.String,
        "delta": pl.Float64,
        "finding": pl.Int32,
    }
)


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class ReturnComparison:
    """Two returns compared cell by cell and rule by rule.

    Attributes:
        names: What the two returns are called in findings and reports.
        header: ``{field: (baseline, candidate)}`` for each header field that differs.
        indicators: ``{template: (baseline, candidate)}`` for each filing
            indicator the two declare differently; ``None`` where one does not
            mention the template.
        cells: Every cell either return reports (``COMPARISON_SCHEMA``), in
            coordinate order.
        findings: The material differences, grouped and explained.
        baseline_unplaced / candidate_unplaced: What reading each file found
            that the module has no place for.
        shared_breaks: Rules that break in both returns: not a difference, and
            not something either return satisfies.
        evaluated_only_in: ``{side: rules}`` evaluated in that return and not
            the other — one return gave them cells to read.
        rules_compared: Whether a rule book was available to judge both sides.
    """

    names: Names
    header: dict[str, tuple[str | None, str | None]]
    indicators: dict[str, tuple[bool | None, bool | None]]
    cells: pl.DataFrame
    findings: tuple[Discrepancy, ...]
    baseline_unplaced: tuple[Finding, ...]
    candidate_unplaced: tuple[Finding, ...]
    shared_breaks: tuple[str, ...]
    evaluated_only_in: dict[str, tuple[str, ...]]
    rules_compared: bool

    def counts(self) -> dict[str, int]:
        """Cells per category, always with every category."""
        found = dict(self.cells.group_by("category").len().iter_rows())
        return {category: found.get(category, 0) for category in CATEGORIES}

    @property
    def is_equivalent(self) -> bool:
        """Whether nothing differs that a reviewer would have to explain.

        Rounding within the files' stated accuracy, and a zero against a blank
        that no rule minds, are not differences. Anything else is.
        """
        return not (
            self.header
            or self.indicators
            or self.findings
            or self.baseline_unplaced
            or self.candidate_unplaced
        )

    def by_finding(self, number: int) -> pl.DataFrame:
        """The cells one finding explains."""
        return self.cells.filter(pl.col("finding") == number)

    def as_record(self) -> dict[str, Any]:
        """A JSON-ready record of the whole comparison."""
        return {
            "equivalent": self.is_equivalent,
            "names": {SIDE_BASELINE: self.names.baseline, SIDE_CANDIDATE: self.names.candidate},
            "header": {name: list(pair) for name, pair in self.header.items()},
            "indicators": {code: list(pair) for code, pair in self.indicators.items()},
            "counts": self.counts(),
            "findings": [_finding_record(item) for item in self.findings],
            "unplaced": {
                SIDE_BASELINE: [_source_record(item) for item in self.baseline_unplaced],
                SIDE_CANDIDATE: [_source_record(item) for item in self.candidate_unplaced],
            },
            "shared_breaks": list(self.shared_breaks),
            "evaluated_only_in": {side: list(ids) for side, ids in self.evaluated_only_in.items()},
            "rules_compared": self.rules_compared,
            "cells": self.cells.filter(pl.col("category") != CATEGORY_SAME).to_dicts(),
        }


def compare_returns(
    baseline: SourceReading,
    candidate: SourceReading,
    *,
    names: Names | None = None,
    tolerance: float = 0.0,
    taxonomy: str | None = None,
    today: date | None = None,
) -> ReturnComparison:
    """Compare ``candidate`` with ``baseline``, cell by cell and rule by rule.

    Args:
        baseline: The return already trusted: the filing made, or the one the
            current system produces.
        candidate: The return being checked against it.
        names: What to call the two in findings. Defaults to "the baseline"
            and "the candidate".
        tolerance: An absolute amount within which two figures count as the
            same, on top of the rounding the files state. For sources that
            state no accuracy — a fact table rounded to thousands, say.
        taxonomy: The release, by version, for a side whose reading has none
            (a fact table read with ``load_source``). ``None`` for the default.
            A side read with its own release keeps it.
        today: The run date the default release is worked out for.

    Raises:
        ReleaseNotFoundError: a side has no release and one could not be
            resolved for its module.
    """
    names = names or Names()
    baseline_release = baseline.release or resolve_release(
        baseline.ret.header.module, taxonomy, today=today
    )
    candidate_release = candidate.release or resolve_release(
        candidate.ret.header.module, taxonomy, today=today
    )
    baseline_pack, candidate_pack = baseline_release.pack, candidate_release.pack
    indicators = {
        SIDE_BASELINE: filing_indicators(baseline.ret, baseline_pack),
        SIDE_CANDIDATE: filing_indicators(candidate.ret, candidate_pack),
    }
    differences = _categorise(
        baseline.ret, candidate.ret, candidate_pack, indicators, tolerance=tolerance
    )
    traces = {
        SIDE_BASELINE: _trace(baseline.ret, baseline_release),
        SIDE_CANDIDATE: _trace(candidate.ret, candidate_release),
    }
    baseline_trace, candidate_trace = traces[SIDE_BASELINE], traces[SIDE_CANDIDATE]
    rules_compared = baseline_trace is not None and candidate_trace is not None
    evaluations: tuple[tuple[Evaluation, ...], tuple[Evaluation, ...]] = ((), ())
    if baseline_trace is not None and candidate_trace is not None:
        evaluations = (baseline_trace.evaluations, candidate_trace.evaluations)
    findings = explain_differences(
        differences, evaluations[0], evaluations[1], candidate_pack, names=names
    )
    comparison = ReturnComparison(
        names=names,
        header=_header_changes(baseline.ret, candidate.ret),
        indicators=_indicator_changes(indicators),
        cells=_cell_frame(differences, findings),
        findings=findings,
        baseline_unplaced=tuple(baseline.findings),
        candidate_unplaced=tuple(candidate.findings),
        shared_breaks=_shared_breaks(traces) if rules_compared else (),
        evaluated_only_in=_evaluated_only_in(traces) if rules_compared else {},
        rules_compared=rules_compared,
    )
    logger.info(
        "compared %s with %s: %d cell(s), %d finding(s)",
        names.candidate,
        names.baseline,
        comparison.cells.height,
        len(findings),
    )
    return comparison


def render_text(comparison: ReturnComparison) -> str:
    """The comparison as ``rwa-filer compare`` prints it: the verdict, the cells, the findings."""
    names = comparison.names
    counts = comparison.counts()
    lines = [
        _verdict_line(comparison),
        f"  baseline   {names.baseline}",
        f"  candidate  {names.candidate}",
        "",
        f"{comparison.cells.height:>9,} cells",
    ]
    lines.extend(f"{counts[category]:>9,}  {words}" for category, words in _CATEGORY_WORDS.items())
    for name, (before, after) in comparison.header.items():
        lines.append(f"  header     {name}: {before} -> {after}")
    for code, pair in comparison.indicators.items():
        lines.append(
            f"  templates  {code}: {_filed(pair[0])} in {names.baseline}, "
            f"{_filed(pair[1])} in {names.candidate}"
        )
    for side_name, unplaced in (
        (names.baseline, comparison.baseline_unplaced),
        (names.candidate, comparison.candidate_unplaced),
    ):
        lines.extend(f"  unplaced   {side_name}: {item.code} {item.message}" for item in unplaced)
    if comparison.findings:
        lines.extend(["", "FINDINGS"])
    for item in comparison.findings:
        points = _POINTS_WORDS.get(item.points_at) or names.of(item.points_at)
        lines.append(
            textwrap.fill(
                f"[points at {points}] {item.title}",
                width=_WIDTH,
                initial_indent=f"{item.number:>2}  ",
                subsequent_indent="    ",
            )
        )
        lines.append(
            textwrap.fill(
                item.detail, width=_WIDTH, initial_indent="      ", subsequent_indent="      "
            )
        )
        lines.extend(
            f"      {rule.rule_id:<14}{names.baseline}: {rule.baseline}   "
            f"{names.candidate}: {rule.candidate}"
            for rule in item.rules[:_RULES_SHOWN]
        )
        if len(item.rules) > _RULES_SHOWN:
            lines.append(f"      ... and {len(item.rules) - _RULES_SHOWN} more rule(s)")
    lines.extend(_also_lines(comparison))
    return "\n".join(lines)


# =============================================================================
# Private helpers — cells
# =============================================================================


def _categorise(
    baseline: CanonicalReturn,
    candidate: CanonicalReturn,
    pack: TaxonomyPack,
    indicators: dict[str, dict[str, bool]],
    *,
    tolerance: float,
) -> dict[Cell, CellDifference]:
    """Every cell either return reports, with its category."""
    coordinates = list(COORDINATE_COLUMNS)

    def side(ret: CanonicalReturn, tag: str) -> pl.DataFrame:
        return ret.facts.select(
            *coordinates,
            pl.col("value").alias(f"{tag}_value"),
            pl.col("text_value").alias(f"{tag}_text"),
            pl.col("decimals").alias(f"{tag}_decimals"),
            pl.lit(value=True).alias(f"in_{tag}"),
        )

    joined = side(baseline, SIDE_BASELINE).join(
        side(candidate, SIDE_CANDIDATE), on=coordinates, how="full", coalesce=True, nulls_equal=True
    )
    filed = {
        table: pack.tables[table].filing_indicator if table in pack.tables else table
        for table in joined.get_column("table").unique().to_list()
    }
    differences: dict[Cell, CellDifference] = {}
    for row in joined.iter_rows(named=True):
        cell: Cell = (row["table"], row["sheet"], row["open_key"], row["row"], row["column"])
        differences[cell] = _difference(cell, row, filed[row["table"]], indicators, tolerance)
    return differences


def _difference(
    cell: Cell,
    row: dict[str, Any],
    indicator: str,
    indicators: dict[str, dict[str, bool]],
    tolerance: float,
) -> CellDifference:
    base_value, cand_value = row["baseline_value"], row["candidate_value"]
    base = base_value if base_value is not None else row["baseline_text"]
    cand = cand_value if cand_value is not None else row["candidate_text"]
    numeric = row["baseline_text"] is None and row["candidate_text"] is None
    delta = (cand_value or 0.0) - (base_value or 0.0) if numeric else None
    allowance = _allowance(row["baseline_decimals"]) + _allowance(row["candidate_decimals"])
    if row["in_baseline"] and row["in_candidate"]:
        category = _both_reported(base, cand, delta, allowance + tolerance)
        return CellDifference(cell, category, base, cand, delta, allowance)
    held_by = SIDE_BASELINE if row["in_baseline"] else SIDE_CANDIDATE
    other = SIDE_CANDIDATE if held_by == SIDE_BASELINE else SIDE_BASELINE
    value = base if held_by == SIDE_BASELINE else cand
    category = _one_reported(
        value, delta, other_reports=indicators[other].get(indicator, False), tolerance=tolerance
    )
    return CellDifference(cell, category, base, cand, delta, allowance, held_by)


def _both_reported(
    base: float | str | None, cand: float | str | None, delta: float | None, within: float
) -> str:
    """The category of a cell both returns report."""
    if base == cand:
        return CATEGORY_SAME
    if delta is not None and abs(delta) <= within:
        return CATEGORY_ROUNDING
    return CATEGORY_MATERIAL


def _one_reported(
    value: float | str | None, delta: float | None, *, other_reports: bool, tolerance: float
) -> str:
    """The category of a cell one return reports, given whether the other reports its template."""
    if not other_reports:
        return CATEGORY_SCOPE
    if value == 0:
        return CATEGORY_ZERO_OR_BLANK
    if delta is not None and abs(delta) <= tolerance:
        return CATEGORY_ROUNDING
    return CATEGORY_MATERIAL


def _allowance(decimals: int | None) -> float:
    """Half a unit of the stated accuracy: ``decimals=-3`` is good to 500 either way.

    A figure that states no accuracy is taken as exact.
    """
    return 0.0 if decimals is None else 0.5 * 10.0 ** (-int(decimals))


def _cell_frame(
    differences: dict[Cell, CellDifference], findings: tuple[Discrepancy, ...]
) -> pl.DataFrame:
    explained_by = {cell: item.number for item in findings for cell in item.cells}
    rows = [
        {
            "table": cell[0],
            "sheet": cell[1],
            "open_key": cell[2],
            "row": cell[3],
            "column": cell[4],
            "baseline": item.baseline if not isinstance(item.baseline, str) else None,
            "candidate": item.candidate if not isinstance(item.candidate, str) else None,
            "baseline_text": item.baseline if isinstance(item.baseline, str) else None,
            "candidate_text": item.candidate if isinstance(item.candidate, str) else None,
            "category": item.category,
            "held_by": item.held_by,
            "delta": item.delta,
            "finding": explained_by.get(cell),
        }
        for cell, item in differences.items()
    ]
    frame = pl.DataFrame(rows, schema=COMPARISON_SCHEMA)
    return frame.sort(list(COORDINATE_COLUMNS), nulls_last=False)


# =============================================================================
# Private helpers — rules, header, indicators
# =============================================================================


def _trace(ret: CanonicalReturn, release: Release) -> RuleTrace | None:
    """Every enforced rule of the side's own release, traced on its return."""
    module = release.pack.info.module
    if release.rulebook is None:
        logger.warning(
            "taxonomy %s packages no rule book for module %s; rules not compared",
            release.version,
            module,
        )
        return None
    return trace_rules(ret, release.pack, release.rulebook.enforced(module))


def _shared_breaks(traces: dict[str, RuleTrace | None]) -> tuple[str, ...]:
    broken = [
        {result.rule_id for result in trace.results if result.status == STATUS_FAIL}
        for trace in traces.values()
        if trace is not None
    ]
    return tuple(sorted(set.intersection(*broken))) if len(broken) == len(traces) else ()


def _evaluated_only_in(traces: dict[str, RuleTrace | None]) -> dict[str, tuple[str, ...]]:
    evaluated = {
        side: {r.rule_id for r in trace.results if r.status != STATUS_NOT_EVALUATED}
        for side, trace in traces.items()
        if trace is not None
    }
    return {
        side: tuple(sorted(ids - set().union(*(o for s, o in evaluated.items() if s != side))))
        for side, ids in evaluated.items()
    }


def _header_changes(
    baseline: CanonicalReturn, candidate: CanonicalReturn
) -> dict[str, tuple[str | None, str | None]]:
    before, after = baseline.header.as_fields(), candidate.header.as_fields()
    return {
        name: (before.get(name), after.get(name))
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }


def _indicator_changes(
    indicators: dict[str, dict[str, bool]],
) -> dict[str, tuple[bool | None, bool | None]]:
    base, cand = indicators[SIDE_BASELINE], indicators[SIDE_CANDIDATE]
    return {
        code: (base.get(code), cand.get(code))
        for code in sorted(set(base) | set(cand))
        if base.get(code, False) != cand.get(code, False)
    }


# =============================================================================
# Private helpers — records
# =============================================================================


def _finding_record(item: Discrepancy) -> dict[str, Any]:
    return {
        "number": item.number,
        "kind": item.kind,
        "points_at": item.points_at,
        "title": item.title,
        "detail": item.detail,
        "cells": [list(cell) for cell in item.cells],
        "rules": [
            {"rule": rule.rule_id, SIDE_BASELINE: rule.baseline, SIDE_CANDIDATE: rule.candidate}
            for rule in item.rules
        ],
        "moves": [
            {
                "table": move.table,
                "sheet": move.sheet,
                "open_key": move.open_key,
                "baseline_row": move.baseline_row,
                "candidate_row": move.candidate_row,
                "columns": list(move.columns),
                "amount": move.amount,
            }
            for move in item.moves
        ],
        "breakdown": [
            {
                "cell": list(part.cell),
                "delta": part.delta,
                "explained": part.explained,
                "unexplained": part.unexplained,
            }
            for part in item.breakdown
        ],
        "gap": item.gap,
        "rate_check": None
        if item.rate_check is None
        else {
            "column": item.rate_check.column,
            "implied": item.rate_check.implied,
            "observed": item.rate_check.observed,
            "consistent": item.rate_check.consistent,
        },
    }


def _source_record(item: Finding) -> dict[str, str]:
    return {"code": item.code, "severity": item.severity, "message": item.message}


# =============================================================================
# Private helpers — text
# =============================================================================

_WIDTH: Final = 100
_RULES_SHOWN: Final = 4
_CATEGORY_WORDS: Final = {
    CATEGORY_SAME: "the same",
    CATEGORY_ROUNDING: "within the rounding both files state",
    CATEGORY_ZERO_OR_BLANK: "a zero in one return, nothing in the other",
    CATEGORY_SCOPE: "in a template only one return reports",
    CATEGORY_MATERIAL: "material differences, in the findings below",
}
_POINTS_WORDS: Final = {POINTS_AT_INPUTS: "the inputs", POINTS_AT_NEITHER: "neither return"}


def _verdict_line(comparison: ReturnComparison) -> str:
    if comparison.is_equivalent:
        return (
            "EQUIVALENT: the same header, the same templates, and no difference beyond the "
            "rounding the files state"
        )
    findings = comparison.findings
    sides = [item.points_at for item in findings]
    parts = [
        f"{sides.count(side)} at {_POINTS_WORDS.get(side) or comparison.names.of(side)}"
        for side in (SIDE_BASELINE, SIDE_CANDIDATE, POINTS_AT_INPUTS, POINTS_AT_NEITHER)
        if sides.count(side)
    ]
    pointing = f" ({', '.join(parts)})" if parts else ""
    return f"DIFFERENT: {len(findings)} finding{'s' if len(findings) != 1 else ''} to explain{pointing}"


def _filed(declared: bool | None) -> str:
    return {True: "reported", False: "declared not reported"}.get(declared, "not mentioned")


def _also_lines(comparison: ReturnComparison) -> list[str]:
    names = comparison.names
    lines: list[str] = []
    for rule_id in comparison.shared_breaks:
        lines.append(
            f"  {rule_id} breaks in both returns: not a difference, but neither satisfies it"
        )
    only_baseline = comparison.evaluated_only_in.get(SIDE_BASELINE, ())
    only_candidate = comparison.evaluated_only_in.get(SIDE_CANDIDATE, ())
    if only_baseline or only_candidate:
        lines.append(
            f"  {len(only_baseline)} rule(s) had cells to read in {names.baseline} only, "
            f"{len(only_candidate)} in {names.candidate} only"
        )
    if not comparison.rules_compared:
        lines.append("  no rule book is packaged for the module: the rules were not compared")
    return ["", "ALSO", *lines] if lines else []
