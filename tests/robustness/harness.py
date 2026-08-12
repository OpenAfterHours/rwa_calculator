"""
The triage invariant, and the machinery for injecting pathological input.

Pipeline position:
    known-good RawDataBundle -> inject(...) -> PipelineOrchestrator.run_with_data
        -> AggregatedResultBundle -> triage(...) -> list[Violation]

Key responsibilities:
- Rebuild a sealed ``RawDataBundle`` around a mutated table, so an injection
  goes through exactly the seal production data goes through
  (``tests.fixtures.raw_bundle.make_raw_bundle``).
- Account for EVERY input exposure row in the output, and report the ones that
  are neither soundly computed nor named by an error.

The invariant, and why it has four clauses rather than two
----------------------------------------------------------
``docs/plans/test-space-correctness-proposal.md`` Phase 2 states it as a
dichotomy — *for every input row, exactly one of: (a) it carries a finite,
in-bounds result, or (b) a ``CalculationError`` names it*. Measured against this
codebase that dichotomy both false-positives and false-negatives, so the
implemented invariant is:

**Every input exposure row is ACCOUNTED FOR.** A row is accounted for when at
least one of these holds:

(a) **Sound result.** At least one output row joins back to it, and every such
    row carries a non-null, finite, in-bounds ``ead_final`` / ``risk_weight`` /
    ``rwa_final`` (bounds per :data:`OUTPUT_BOUNDS`, which restate
    ``contracts/validation.py::validate_aggregated_bundle``'s OUT001-OUT004).

(b) **Named error.** A ``CalculationError`` names the row — by its input
    reference, by any of the OUTPUT references that join back to it, or by its
    ``counterparty_reference``. All three forms occur: the input-domain gate
    names the input reference, ``validate_aggregated_bundle`` names the *output*
    reference (so a split leg is named ``LN000_sec``, not ``LN000``), and the
    classifier's diagnostics name the obligor.

(c) **Table/column aggregate error.** An error with ``exposure_reference=None``
    whose ``(table, column)`` matches an injected field. Excuses an UNSOUND
    result only — never a vanished or collapsed row (see :func:`triage`). This
    clause is not optional politeness — it is the difference between a suite
    that is used and one that is switched off. ``_collect_domain_violations`` samples at most
    ``sample_cap=5`` named errors per column and then emits ONE summary carrying
    the omitted count (pinned by ``tests/contracts/test_validation.py``), so
    injecting six bad values into one column produces a sixth row that NO error
    names individually. ``DQ001`` (missing required column) and ``DQ010``
    (unreferenced negative amount) never name a row at all, and ``DQ006``
    (invalid categorical) names only the value and its count. Without clause (c)
    every one of those is a false failure.

(d) **Nothing — which is the failure.** The row produced no output row and no
    error mentions it. It was filtered out, lost by a join, or collapsed by a
    ``group_by``, and the portfolio total is short by its capital with no signal
    whatsoever. Nothing else in the estate states a count identity between input
    and output rows except ``tests/acceptance/stress/test_stress_pipeline.py``
    ``::TestRowCountPreservation``, which counts a clean portfolio only.

A fifth outcome exists and is reported separately as ``collapsed``: duplicate
input rows sharing one reference. The join is on the reference, so k input rows
collapsing to one output row is invisible to a per-reference identity — the
reference IS present. It is nonetheless silent data loss, so
:func:`triage` counts input ROWS as well as references.

Why the join is on ``source_exposure_reference``
------------------------------------------------
``exposure_reference`` is NOT 1:1 with the input. The real-estate splitter turns
one parent row into ``LN000_sec`` / ``LN000_res``, guarantee substitution emits
``__G_`` / ``__REM`` legs, and a committed facility emits an ``_UNDRAWN`` leg.
``source_exposure_reference`` (``contracts/edges.py``) is the pre-split base
reference kept stable for reconciliation, and is therefore the only column that
joins an output row back to the input row that produced it. Joining on
``exposure_reference`` would report every correct split as a vanished row.

Following ``tests/properties/test_source_conservation.py``'s discipline, the
carrier is REQUIRED rather than defaulted: if ``source_exposure_reference`` is
absent from the results frame :func:`triage` raises, because reading a missing
carrier as "no match" would turn a schema regression into a wall of false
vanish reports (`.claude/LESSONS.md` B1).

References:
- docs/plans/test-space-correctness-proposal.md — Phase 2
- CRR Art. 92(3): the 1250% risk-weight cap that bounds a sound result
- .claude/LESSONS.md B1 (a presence guard on a wrong column fails silently),
  B3 (state the expected side from raw input, never from engine output)
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.properties.portfolios import config_for

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from rwa_calc.contracts.bundles import AggregatedResultBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The regime every test in this suite runs under unless it says otherwise. One
#: of ``tests/properties/portfolios.REGIMES``. Set by the nightly workflow's
#: matrix; ``CRR`` locally so a developer's run is deterministic.
DEFAULT_REGIME: str = os.environ.get("RWA_ROBUSTNESS_REGIME", "CRR")

#: ``RawDataBundle`` fields that are NOT sealed frames, so they cannot be passed
#: back through ``make_raw_bundle``'s frame path.
_NON_FRAME_FIELDS = frozenset({"ccr", "sft", "errors"})

#: Input tables that produce output exposure rows one-for-one (before the split
#: and substitution legs described in the module docstring), keyed by their
#: natural reference column.
#:
#: ``facilities`` is DELIBERATELY absent. A facility emits a ``facility_undrawn``
#: leg only when it is committed AND carries undrawn headroom after its mapped
#: drawings, so "one facility row, one output row" is not an identity the engine
#: claims and asserting it would produce false vanish reports on correct
#: behaviour. Its undrawn legs still reach clause (a) through their own
#: ``source_exposure_reference``; what is not asserted is that they exist.
EXPOSURE_TABLES: dict[str, str] = {
    "loans": "loan_reference",
    "contingents": "contingent_reference",
}

#: (column, lower, upper) for a sound output row. Restates OUT001-OUT004 in
#: ``contracts/validation.py::validate_aggregated_bundle`` — 1250% is the
#: CRR Art. 92(3) cap, and negative EAD/RWA are not representable outcomes.
#: ``rwa_final``'s lower bound carries the same float64 round-off tolerance the
#: production validator uses, so a -1e-12 dust value is not reported as a defect.
OUTPUT_BOUNDS: tuple[tuple[str, float, float | None], ...] = (
    ("ead_final", 0.0, None),
    ("risk_weight", 0.0, 12.5),
    ("rwa_final", -1e-9, None),
)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Injection:
    """One pathological (table, column) edit, and what it was meant to express.

    Frozen and hashable so a Hypothesis counter-example prints as a literal that
    can be pasted into a deterministic reproducer.
    """

    table: str
    column: str
    description: str

    def __str__(self) -> str:
        return f"{self.table}.{self.column} ({self.description})"


@dataclass(frozen=True)
class Violation:
    """One input row the run failed to account for."""

    kind: Literal["vanished", "unsound", "collapsed"]
    reference: str
    table: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.table}:{self.reference} — {self.detail}"


@dataclass(frozen=True)
class TriageReport:
    """The outcome of checking one run against the invariant."""

    violations: tuple[Violation, ...]
    input_rows: int
    output_rows: int
    errors: tuple[CalculationError, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    def describe(self, injections: Sequence[Injection] = ()) -> str:
        """A failure message carrying enough to reproduce and to triage."""
        codes = sorted({e.code for e in self.errors}) or ["<no errors at all>"]
        lines = [
            f"{len(self.violations)} input row(s) unaccounted for "
            f"({self.input_rows} input rows -> {self.output_rows} output rows)",
            f"injections: {[str(i) for i in injections] or '<none>'}",
            f"accumulated error codes: {codes}",
        ]
        lines.extend(f"  {violation}" for violation in self.violations[:20])
        if len(self.violations) > 20:
            lines.append(f"  ... {len(self.violations) - 20} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def inject(bundle: RawDataBundle, **tables: pl.LazyFrame) -> RawDataBundle:
    """Rebuild ``bundle`` with the named tables replaced, re-sealing every frame.

    The ONLY sanctioned way this suite mutates a bundle. ``RawDataBundle``
    is frozen and ``__post_init__`` rejects any frame that does not carry its
    edge brand, so a mutated frame has to go back through the loader's own seal
    — which is the point: an injection that the seal silently repairs (a
    Boolean null filled to its default, an uncastable value nulled) is a fact
    about production behaviour, not an artefact of the test.
    """
    fields = {
        field.name: getattr(bundle, field.name)
        for field in dataclasses.fields(RawDataBundle)
        if field.name not in _NON_FRAME_FIELDS
    }
    unknown = set(tables) - set(fields)
    if unknown:
        raise ValueError(f"not RawDataBundle frame fields: {sorted(unknown)}")
    fields.update(tables)
    return make_raw_bundle(**fields)


def with_columns(bundle: RawDataBundle, table: str, *exprs: pl.Expr) -> RawDataBundle:
    """``inject`` shorthand for an expression-level edit to one table."""
    frame = getattr(bundle, table)
    if frame is None:
        raise ValueError(f"bundle has no '{table}' table to mutate")
    return inject(bundle, **{table: frame.with_columns(*exprs)})


def present_columns(
    bundle: RawDataBundle, pairs: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The ``(table, column)`` pairs ``bundle`` actually carries.

    An injection into a table the portfolio does not populate, or into a column
    the seal did not emit, edits nothing — and a generator that reports "no
    defect" after editing nothing is the worst outcome available. Callers filter
    through this and skip when it is empty.
    """
    present: list[tuple[str, str]] = []
    schemas: dict[str, set[str]] = {}
    for table, column in pairs:
        if table not in schemas:
            frame = getattr(bundle, table, None)
            schemas[table] = set() if frame is None else set(frame.collect_schema().names())
        if column in schemas[table]:
            present.append((table, column))
    return present


def run(bundle: RawDataBundle, regime: str | None = None) -> AggregatedResultBundle:
    """Run the FULL pipeline — the whole point of this suite.

    ``calculate_branch`` and the per-transform helpers bypass the input contract
    and the aggregator's output bounds, which are exactly the two gates a
    pathology suite exists to exercise.

    ``regime`` defaults to :data:`DEFAULT_REGIME`, which reads
    ``RWA_ROBUSTNESS_REGIME``. The nightly workflow runs CRR and Basel 3.1 as
    separate matrix legs rather than parametrising every test, because a
    pathology absorbed differently by the two regimes is exactly the shape
    ``.claude/LESSONS.md`` C7 records — a both-regimes parametrisation whose
    author reads one green half proves one regime, not two. Two legs make the
    per-regime verdict unmissable.
    """
    return PipelineOrchestrator().run_with_data(bundle, config_for(regime or DEFAULT_REGIME))


def run_with(bundle: RawDataBundle, config: CalculationConfig) -> AggregatedResultBundle:
    """As :func:`run`, for a caller that already holds a config."""
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def triage(
    bundle: RawDataBundle,
    result: AggregatedResultBundle,
    injections: Sequence[Injection] = (),
) -> TriageReport:
    """Account for every input exposure row in ``result``.

    Args:
        bundle: The bundle that was run — the source of the expected side.
            Read from the RAW input rather than re-derived from engine output,
            per ``.claude/LESSONS.md`` B3.
        result: What the pipeline returned.
        injections: The pathological fields this run carries. Used ONLY by
            clause (c): a table/column-level aggregate error can only excuse a
            row for a field that was actually injected, so an unrelated
            pre-existing aggregate warning cannot silence an unrelated defect.

    Returns:
        A :class:`TriageReport`. ``ok`` is the invariant.
    """
    inputs = _input_rows(bundle)
    outputs = _output_rows(result)

    per_reference = _join_input_to_output(inputs, outputs)
    suspects = per_reference.filter(
        pl.col("n_out").is_null() | (pl.col("n_bad") > 0) | (pl.col("n_in") > 1)
    )

    # Clause (c) is evaluated at RUN level, not per row, and deliberately: an
    # injection replaces a whole column of a whole table, so every exposure row
    # in the run is downstream of it. Scoping the excuse to "rows of the injected
    # table" would be wrong in the common case — a garbage `entity_type` on
    # `counterparties` is what makes a row in `loans` misclassify.
    aggregate_covered = _aggregate_covers(
        result.errors,
        {injection.column for injection in injections},
        {injection.table for injection in injections},
    )
    named = _named_references(result.errors)
    output_refs_by_source = _output_refs_for(outputs, suspects["reference"].to_list())

    violations: list[Violation] = []
    for row in suspects.iter_rows(named=True):
        aliases = {row["reference"], *output_refs_by_source.get(row["reference"], ())}
        if aliases & named or row["counterparty_reference"] in named:
            continue
        violation = _violation(row)
        # Clause (c) excuses an UNSOUND result only. It must not excuse a
        # vanished or collapsed row, and that restriction is the difference
        # between an invariant and a formality: an aggregate error saying "this
        # column held N bad values" explains why a row's NUMBER is wrong; it says
        # nothing about why the row is GONE. Letting it excuse a disappearance
        # would widen the invariant to accommodate exactly the defect class this
        # suite exists to find — and would have silenced the duplicate-collapse
        # finding the moment any injection produced a table-level warning.
        if violation.kind == "unsound" and aggregate_covered:
            continue
        violations.append(violation)

    return TriageReport(
        violations=tuple(violations),
        input_rows=inputs.height,
        output_rows=outputs.height,
        errors=tuple(result.errors),
    )


def assert_accounted(
    bundle: RawDataBundle,
    result: AggregatedResultBundle,
    injections: Sequence[Injection] = (),
) -> TriageReport:
    """Run :func:`triage` and assert the invariant, with a triage-able message."""
    report = triage(bundle, result, injections)
    assert report.ok, report.describe(injections)
    return report


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _input_rows(bundle: RawDataBundle) -> pl.DataFrame:
    """One row per input exposure, with its reference and obligor."""
    frames: list[pl.LazyFrame] = []
    for table, key_column in EXPOSURE_TABLES.items():
        frame = getattr(bundle, table)
        if frame is None:
            continue
        names = frame.collect_schema().names()
        if key_column not in names:
            raise AssertionError(
                f"input table '{table}' carries no '{key_column}' — the invariant "
                "cannot join it to the output, and reading it as zero rows would "
                "hide exactly the loss this suite looks for"
            )
        counterparty = (
            pl.col("counterparty_reference").cast(pl.String)
            if "counterparty_reference" in names
            else pl.lit(None, dtype=pl.String)
        )
        frames.append(
            frame.select(
                pl.col(key_column).cast(pl.String).alias("reference"),
                counterparty.alias("counterparty_reference"),
                pl.lit(table).alias("table"),
            )
        )
    if not frames:
        return pl.DataFrame(
            schema={"reference": pl.String, "counterparty_reference": pl.String, "table": pl.String}
        )
    return pl.concat(frames, how="vertical").collect()


def _output_rows(result: AggregatedResultBundle) -> pl.DataFrame:
    """The results frame, reduced to the columns the invariant reads.

    Raises when a carrier is missing rather than defaulting it — see the module
    docstring and ``.claude/LESSONS.md`` B1.
    """
    lf = result.results
    names = set(lf.collect_schema().names())
    required = {"exposure_reference", "source_exposure_reference"}
    missing = sorted(required - names)
    if missing:
        raise AssertionError(
            f"results frame is missing {missing}; the triage invariant cannot "
            "join output rows back to input rows without it"
        )

    bad = pl.lit(value=False)
    for column, lower, upper in OUTPUT_BOUNDS:
        if column not in names:
            raise AssertionError(
                f"results frame is missing '{column}'; a bound that cannot be "
                "evaluated must not read as satisfied"
            )
        bad = bad | _unsound(column, lower, upper)

    return lf.select(
        pl.col("exposure_reference").cast(pl.String),
        # Null source means the row cannot be traced back at all; fall back to
        # its own reference so the row is still counted rather than dropped.
        pl.coalesce(pl.col("source_exposure_reference"), pl.col("exposure_reference"))
        .cast(pl.String)
        .alias("source"),
        bad.alias("is_bad"),
    ).collect()


def _unsound(column: str, lower: float, upper: float | None) -> pl.Expr:
    """True where ``column`` is null, non-finite, or outside its bound.

    Every comparison is ``fill_null(False)``-ed after the explicit null test so
    a null is counted once, and so ``|`` never propagates a null (a null in the
    combined flag would make ``n_bad`` under-count).
    """
    value = pl.col(column)
    unsound = (
        value.is_null()
        | value.is_nan().fill_null(value=False)
        | value.is_infinite().fill_null(value=False)
        | (value < lower).fill_null(value=False)
    )
    if upper is not None:
        unsound = unsound | (value > upper).fill_null(value=False)
    return unsound


def _join_input_to_output(inputs: pl.DataFrame, outputs: pl.DataFrame) -> pl.DataFrame:
    """Per input reference: input row count, output row count, unsound count."""
    per_input = inputs.group_by("reference").agg(
        pl.len().alias("n_in"),
        pl.col("table").first(),
        pl.col("counterparty_reference").first(),
    )
    per_output = outputs.group_by("source").agg(
        pl.len().alias("n_out"),
        pl.col("is_bad").sum().alias("n_bad"),
    )
    return per_input.join(per_output, left_on="reference", right_on="source", how="left")


def _output_refs_for(outputs: pl.DataFrame, sources: list[str]) -> dict[str, tuple[str, ...]]:
    """The output references produced by each of ``sources``.

    Materialised only for the suspect references, so the cost is proportional to
    the number of problems rather than to the portfolio.
    """
    if not sources:
        return {}
    grouped = (
        outputs.filter(pl.col("source").is_in(sources))
        .group_by("source")
        .agg(pl.col("exposure_reference"))
    )
    return {
        row["source"]: tuple(row["exposure_reference"]) for row in grouped.iter_rows(named=True)
    }


def _named_references(errors: Iterable[CalculationError]) -> set[str]:
    """Every row-level reference any error names, in any of its three forms."""
    named: set[str] = set()
    for error in errors:
        for reference in (error.exposure_reference, error.counterparty_reference):
            if reference:
                named.add(str(reference))
    return named


def _aggregate_covers(
    errors: Iterable[CalculationError],
    columns: set[str],
    tables: set[str],
) -> bool:
    """Clause (c): is there a table/column-level error for an injected field?

    Matching is on BOTH the column and the table, because a column name alone is
    ambiguous — ``lgd`` is declared on loans, facilities and contingents, and an
    aggregate error about one must not excuse a row in another.

    The table is matched against the three renderings the error factories
    actually use, none of which is a structured field:
    ``[table]`` (``validate_column_values``, ``_collect_domain_violations``,
    ``_validate_negative_amounts_without_netting``), ``'table.column'``
    (``non_finite_raw_input_error``), and ``actual_value == table``
    (``missing_required_column_error``). A structured ``table`` field on
    ``CalculationError`` would be better and is worth having; until it exists,
    matching the rendered forms is what can be done without changing production
    code.
    """
    if not columns:
        return False
    for error in errors:
        if error.exposure_reference is not None or error.field_name not in columns:
            continue
        for table in tables:
            if (
                f"[{table}]" in error.message
                or f"'{table}.{error.field_name}'" in error.message
                or error.actual_value == table
            ):
                return True
    return False


def _violation(row: dict) -> Violation:
    """Classify one suspect row into its violation kind."""
    reference = row["reference"]
    table = row["table"]
    if row["n_out"] is None:
        return Violation(
            kind="vanished",
            reference=reference,
            table=table,
            detail=(
                "produced no output row and no error names it — its capital is "
                "missing from the portfolio total with no signal"
            ),
        )
    if row["n_in"] > 1:
        return Violation(
            kind="collapsed",
            reference=reference,
            table=table,
            detail=(
                f"{row['n_in']} input rows share this reference and collapsed to "
                f"{row['n_out']} output row(s); no error says so"
            ),
        )
    return Violation(
        kind="unsound",
        reference=reference,
        table=table,
        detail=(
            f"{row['n_bad']} of {row['n_out']} output row(s) carry a null, "
            "non-finite or out-of-bounds ead_final / risk_weight / rwa_final "
            "and no error names them"
        ),
    )
