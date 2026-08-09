"""Template (template, column) coverage census, with a two-way ratchet.

A reporting defect can only be caught by a test if some portfolio puts a figure
in the cell it moves. ``.claude/LESSONS.md`` B5 records the recurrence: C 08.01
r0253 held ``0.00`` in all six golden portfolios, so the mandatory Tier 2 gate
was structurally incapable of seeing a change to that column and ran green over
a simulated fix. The same shape hid the real-estate loan-splitter's duplication
of ~34 inherited numeric columns across split legs.

``scripts/coverage_report.py`` measures the neighbouring quantity — per-CELL
liveness over the COREP frames the *validation* index binds — and gates on
nothing. This script answers the coarser, reviewable question it cannot:
**which (template, column) pairs does the whole portfolio estate never put a
non-zero figure into**, over COREP *and* Pillar 3, so a column that legitimately
has no data can be told apart from one that silently stopped reporting.

The census is a union over 14 portfolios x 2 regimes (28 runs):

- the eight reporting fixtures, taken from ``RUNS`` in
  ``tests/acceptance/reporting/test_supervisory_validations.py`` — imported,
  never re-declared, so each portfolio runs under its OWN canonical config
  (including the prior-period run that C 08.04 needs). A single uniform config
  across all twelve is what makes this measurement lie: six of them then emit
  "IRB permission mode selected but no model_permissions data provided", and
  every IRB-only column they would have lit up is recorded dead for a reason
  that is an artefact of the harness; and
- the six ``tests/properties/corpus.py`` portfolios under
  ``portfolios.config_for``.

Each pair is LIVE when some run put a NON-ZERO value in it, and DEAD otherwise.
A dead pair carries a reason code in the baseline:

``ENGINE_CANNOT_PRODUCE``
    The engine genuinely does not hold the input — prior-period movement
    drivers, ECAI-mapped PD back-testing, observed default counts.
``NO_FIXTURE``
    A real coverage gap we owe a scenario. The conservative default: where the
    classification is not settled, it is ours.

The two counts are ratcheted **both ways** against
``scripts/template_cell_coverage_baseline.json`` (house style — cf.
``check_doc_links.py`` and the supervisory validation register): a live column
going dead is a REGRESSION and fails; a dead column going live is an
IMPROVEMENT that also fails until it is banked, so the win cannot silently
regress back.

Known blind spot, recorded rather than papered over: the unit is a COLUMN, so a
template whose dead axis is the ROW is invisible here. C 08.04 is the worked
example — its one column (0010, RWEA) is live, while six of its nine movement
rows never carry a figure. ``coverage_report.py``'s ``dead_cells`` is the
per-cell measure for the COREP frames the validation index binds; this census is
the coarser one that also covers Pillar 3.

Failing loudly is load-bearing. A portfolio that raises produces no frames,
which looks exactly like a clean result and would record every column it feeds
as dead — so a raising portfolio is a hard error, never a skip, the run count is
asserted against the expected matrix size, and a pipeline warning that indicates
silent degradation is fatal.

Usage:
    uv run python scripts/check_template_cell_coverage.py                    # census
    uv run python scripts/check_template_cell_coverage.py --check            # ratchet gate
    uv run python scripts/check_template_cell_coverage.py --update-baseline  # bank it

Exit codes:
    0 = census printed (default), or --check matched the baseline
    1 = --check found a regression or an unbanked improvement; a portfolio
        raised; a run degraded silently; or the matrix was short
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import polars as pl  # noqa: E402
from tests.acceptance.reporting.test_supervisory_validations import RUNS  # noqa: E402
from tests.properties.corpus import CORPUS  # noqa: E402
from tests.properties.portfolios import build_bundle, config_for  # noqa: E402

from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402
from rwa_calc.reporting import catalog  # noqa: E402
from rwa_calc.reporting.corep.generator import COREPGenerator  # noqa: E402
from rwa_calc.reporting.pillar3.generator import Pillar3Generator  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig

BASELINE_PATH = REPO_ROOT / "scripts" / "template_cell_coverage_baseline.json"

#: Reason codes a dead column may carry. ``NO_FIXTURE`` is the conservative
#: default: an unsettled classification is our gap until proven otherwise.
REASON_CODES: tuple[str, ...] = ("ENGINE_CANNOT_PRODUCE", "NO_FIXTURE")

#: Written for a dead column nobody has classified yet. The contract test fails
#: on it, so a newly banked baseline cannot be committed untriaged.
UNCLASSIFIED = "unclassified - say why this column carries no non-zero figure"

#: The baseline's self-describing header. A constant so the committed file and
#: this script cannot drift apart.
BASELINE_COMMENT = (
    "Template (template, column) coverage census "
    "(scripts/check_template_cell_coverage.py --check). A LIVE column going dead is a "
    "regression - some portfolio stopped reporting a figure it used to report, and every "
    "gate over that column just went blind (.claude/LESSONS.md B5). A DEAD column going "
    "live is an improvement that must be banked here so it cannot silently regress back. "
    "Each dead entry carries a reason code: ENGINE_CANNOT_PRODUCE (the engine does not "
    "hold the input) or NO_FIXTURE (a coverage gap we owe a scenario - the conservative "
    "default). Never raise a count to clear a red gate. Only the live_columns / "
    "dead_columns SETS are ratcheted: the cell tallies under counts are informational and "
    "have been observed to move by a cell or two between identical runs (float dust "
    "crossing zero), which is exactly why the gate is stated on column liveness across the "
    "whole matrix rather than per cell."
)

#: Reporting portfolios deliberately OUTSIDE the census, and why. Recorded in the
#: baseline so a reader can see what the number excludes rather than having to
#: infer it. The census takes its reporting half from ``RUNS`` and nowhere else:
#: registering a portfolio there (which ``.claude/LESSONS.md`` B5 already requires
#: of any fixture that exercises a previously-dead column) pulls it in
#: automatically, and the ratchet then fires as an IMPROVEMENT to be banked.
EXCLUDED_PORTFOLIOS: dict[str, str] = {
    "tests/fixtures/reporting_funded_protection_portfolio.py": (
        "WITHHELD from RUNS deliberately, not an oversight. Registering it needs a "
        "config electing the Art. 222 SIMPLE Method (_fcsm_config); registered against "
        "_sa_config, which defaults to comprehensive, the fixture sits in the gate with "
        "its own feature silenced - C 07.00 col 0070 reads 0.00 under comprehensive and "
        "non-zero under SIMPLE on the identical bundle, and dropping its two runs left "
        "this census at 210 live / 129 dead unchanged, so it contributed no liveness. "
        "Registered CORRECTLY it exposes two ERROR-severity supervisory breaks "
        "(boe_b0471, v0308_m) that predate the carrier fix, so the registration is filed "
        "as a Tier 1 item with the Art. 222 defect rather than banked here. Its canonical "
        "config lives in tests/acceptance/reporting/test_funded_protection_coverage.py. "
        "Registering it should move the Simple Method (C 07.00 col 0070) and "
        "Art. 199 (C 08.01/02 cols 0200/0210, CR7-A cols e/f) columns off NO_FIXTURE."
    ),
}

#: Corpus regimes, as ``portfolios.REGIMES`` keys. ``B31_FLOORED`` is deliberately
#: excluded: it is the same BASEL_3_1 framework at a post-2030 date, so it adds a
#: pipeline run per portfolio and no new template column.
CORPUS_REGIMES: tuple[tuple[str, str], ...] = (("crr", "CRR"), ("b31", "B31"))

#: A pipeline WARNING matching any of these means the run silently degraded into
#: measuring something other than what it claims to — the harness artefact this
#: census exists to avoid. Fatal, not recorded.
FATAL_WARNING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"no model_permissions data provided", re.IGNORECASE),
    re.compile(r"will route to SA", re.IGNORECASE),
)

#: Bundle fields that are run metadata rather than a template.
NON_TEMPLATE_FIELDS = frozenset({"framework", "reporting_basis", "institution_type", "errors"})

#: Catalogue family -> the prefix a column id is addressed by.
FAMILY_PREFIX = {"corep": "corep", "pillar3": "p3"}

#: Printed rows per section. The full lists live in the baseline, never here.
PRINTED_ROWS = 25


class ColumnKey(NamedTuple):
    """One (template, column) pair — the unit the ratchet is stated on.

    Deliberately NOT regime-qualified. The question is whether the estate ever
    reports a figure in this column at all; a column that only exists under one
    framework is still one column of one template.
    """

    family: str
    template: str
    column: str

    def describe(self) -> str:
        return f"{FAMILY_PREFIX.get(self.family, self.family)}/{self.template}/{self.column}"


class RunSpec(NamedTuple):
    """One portfolio through one regime, with its own canonical config."""

    source: str
    portfolio: str
    regime: str
    framework: str
    build_bundle: Callable[[], RawDataBundle]
    build_config: Callable[[], CalculationConfig]
    build_prior_config: Callable[[], CalculationConfig] | None = None

    def describe(self) -> str:
        return f"{self.source}/{self.portfolio}/{self.regime}"


class Census(NamedTuple):
    """Everything the matrix produced, accumulated across runs."""

    #: Columns declared by the frozen template definitions, both frameworks.
    declared: frozenset[ColumnKey]
    #: Numeric columns some run actually emitted. The measured population.
    observed: frozenset[ColumnKey]
    #: Non-numeric emitted columns (row axis labels, PD-range text). Excluded
    #: from the pair space: they carry no figure, so "non-zero" is meaningless.
    non_numeric: frozenset[ColumnKey]
    #: Columns some run put a non-zero value in.
    live: frozenset[ColumnKey]
    numeric_cells: int
    non_null_cells: int
    non_zero_cells: int
    frames: int
    runs: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    @property
    def pairs(self) -> frozenset[ColumnKey]:
        """The pair space: every column declared or emitted, numeric only.

        Declared-but-never-emitted columns are IN, deliberately (LESSONS B4 —
        assert what should be there, not only what is). A column no portfolio
        reaches is exactly the blind spot this census exists to name.
        """
        return (self.declared | self.observed) - self.non_numeric

    @property
    def dead(self) -> frozenset[ColumnKey]:
        return self.pairs - self.live

    def fill_pct(self) -> float:
        """Non-zero share of the numeric cells actually emitted."""
        if not self.numeric_cells:
            return 0.0
        return 100.0 * self.non_zero_cells / self.numeric_cells


def declared_columns() -> frozenset[ColumnKey]:
    """Every (template, column) the frozen template definitions declare.

    Read from ``reporting/catalog.py``'s registry — the one place that maps a
    bundle field to its column definitions — under BOTH frameworks, because a
    column can exist under one regime only. Never a hand-written list: a
    hand-written list goes stale silently (``.claude/LESSONS.md`` B3), which is
    the exact failure mode this census is built to detect.
    """
    keys: set[ColumnKey] = set()
    # catalog._TEMPLATES is private but is the ONLY registry of frozen layouts;
    # see this function's docstring. ruff does not select SLF001, so no per-line
    # ignore is warranted.
    for spec in catalog._TEMPLATES:
        for framework in ("CRR", "BASEL_3_1"):
            for column in spec.columns(framework):
                keys.add(ColumnKey(spec.family, spec.id, column.ref))
    return frozenset(keys)


def run_specs() -> tuple[RunSpec, ...]:
    """The 12 portfolios x 2 regimes, each with the config its own test uses.

    The reporting half is ``RUNS`` verbatim — imported so it cannot silently
    diverge from the gate, and so each portfolio keeps the config (and the
    prior-period run) its own goldens were derived under.
    """
    reporting = tuple(
        RunSpec(
            "reporting",
            run.portfolio,
            run.regime,
            run.framework,
            run.build_bundle,
            run.build_config,
            run.build_prior_config,
        )
        for run in RUNS
    )
    corpus = tuple(
        RunSpec(
            "corpus",
            name,
            regime,
            "CRR" if regime_key == "CRR" else "BASEL_3_1",
            _corpus_bundle(portfolio),
            _corpus_config(regime_key),
        )
        for name, portfolio in CORPUS.items()
        for regime, regime_key in CORPUS_REGIMES
    )
    return reporting + corpus


#: How many runs a complete census performs. Asserted rather than inferred: a
#: short matrix records every column its missing portfolios feed as dead.
EXPECTED_RUNS = len(RUNS) + len(CORPUS) * len(CORPUS_REGIMES)


def census(limit: int | None = None) -> Census:
    """Run the whole matrix and accumulate the coverage facts.

    Raises:
        SystemExit: a portfolio raised, or a run degraded silently. Either makes
            every column that run feeds look dead, so neither may be absorbed.
    """
    specs = run_specs()[:limit] if limit else run_specs()
    observed: set[ColumnKey] = set()
    non_numeric: set[ColumnKey] = set()
    live: set[ColumnKey] = set()
    warnings: list[str] = []
    runs: list[dict[str, Any]] = []
    cells = nulls = non_zero = frames = 0

    for index, spec in enumerate(specs, start=1):
        sys.stderr.write(f"  [{index}/{len(specs)}] {spec.describe()} ...\n")
        started = time.perf_counter()
        with _captured_warnings() as captured:
            corep, pillar3 = _generate(spec)
        _fail_on_degradation(spec, captured)
        warnings.extend(f"{spec.describe()}: {message}" for message in captured)

        scan = _scan_run(corep, pillar3)
        observed |= scan.observed
        non_numeric |= scan.non_numeric
        live |= scan.live
        cells += scan.cells
        nulls += scan.nulls
        non_zero += scan.non_zero
        run_frames = scan.frames
        run_cells = scan.cells

        frames += run_frames
        runs.append(
            {
                "source": spec.source,
                "portfolio": spec.portfolio,
                "regime": spec.regime,
                "framework": spec.framework,
                "prior_period_run": spec.build_prior_config is not None,
                "frames": run_frames,
                "numeric_cells": run_cells,
                "warnings": len(captured),
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
        del corep, pillar3
        gc.collect()

    return Census(
        declared=declared_columns(),
        observed=frozenset(observed),
        non_numeric=frozenset(non_numeric),
        live=frozenset(live),
        numeric_cells=cells,
        non_null_cells=cells - nulls,
        non_zero_cells=non_zero,
        frames=frames,
        runs=tuple(runs),
        warnings=tuple(warnings),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Template (template, column) coverage census, with a two-way ratchet."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="two-way ratchet against the baseline")
    mode.add_argument("--update-baseline", action="store_true", help="bank the current census")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="run only the first N of the matrix (smoke testing only — a partial "
        "matrix records every column its missing portfolios feed as dead)",
    )
    args = parser.parse_args()
    partial = bool(args.limit)

    started = time.perf_counter()
    sys.stderr.write(f"Running {args.limit or EXPECTED_RUNS} portfolio/regime runs ...\n")
    measured = census(args.limit)
    if not partial:
        _assert_matrix_complete(measured)
    elapsed = round(time.perf_counter() - started, 1)

    if args.update_baseline:
        return _write_baseline(measured, elapsed, partial=partial)
    if args.check:
        _report(measured, elapsed)
        return _check_baseline(measured, partial=partial)
    _report(measured, elapsed)
    return 0


# ---------------------------------------------------------------------------
# Baseline read / write
# ---------------------------------------------------------------------------


def _write_baseline(measured: Census, elapsed: float, *, partial: bool) -> int:
    """Bank the census, PRESERVING every hand-written reason that still applies.

    Only the reason is curated; the population and the counts are facts about
    the current estate and are always refreshed. A newly dead column arrives as
    ``UNCLASSIFIED`` and the contract test fails until somebody says why.
    """
    if partial:
        sys.stderr.write("REFUSING to bank a baseline from a partial matrix (--limit).\n")
        return 1
    existing = _existing_reasons()
    dead = sorted(measured.dead)
    payload = {
        "_comment": BASELINE_COMMENT,
        "provenance": {
            "portfolios": [
                {"source": spec.source, "portfolio": spec.portfolio, "regime": spec.regime}
                for spec in run_specs()
            ],
            "frameworks": sorted({spec.framework for spec in run_specs()}),
            "runs": EXPECTED_RUNS,
            "prior_period_runs": sum(
                1 for spec in run_specs() if spec.build_prior_config is not None
            ),
            "config_source": (
                "each portfolio runs under its OWN canonical config - RUNS in "
                "tests/acceptance/reporting/test_supervisory_validations.py for the "
                "reporting fixtures, tests/properties/portfolios.py::config_for for the "
                "corpus. One uniform config would strand six portfolios in the "
                "missing-model_permissions SA fallback and record their IRB columns dead."
            ),
            "excludes": EXCLUDED_PORTFOLIOS,
            "seconds": elapsed,
        },
        "counts": _counts(measured),
        "caveats": list(measured.warnings),
        "dead_columns": [
            {
                "id": key.describe(),
                "reason_code": existing.get(key.describe(), (REASON_CODES[1], UNCLASSIFIED))[0],
                "reason": existing.get(key.describe(), (REASON_CODES[1], UNCLASSIFIED))[1],
                "status": "never_emitted" if key not in measured.observed else "always_zero",
            }
            for key in dead
        ],
        "live_columns": [key.describe() for key in sorted(measured.live)],
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    untriaged = sum(1 for entry in payload["dead_columns"] if entry["reason"] == UNCLASSIFIED)
    sys.stderr.write(
        f"baseline banked: {len(measured.pairs)} pairs, {len(measured.live)} live, "
        f"{len(dead)} dead ({untriaged} untriaged)\n"
    )
    return 0


def _check_baseline(measured: Census, *, partial: bool) -> int:
    """Two-way ratchet the measured census against the committed baseline."""
    if partial:
        sys.stderr.write(
            "REFUSING to ratchet against a partial matrix (--limit): the census is a "
            "union across runs and a short matrix understates every column.\n"
        )
        return 1
    if not BASELINE_PATH.exists():
        sys.stderr.write(
            f"No baseline at {_display(BASELINE_PATH)}. Capture it first:\n"
            "  uv run python scripts/check_template_cell_coverage.py --update-baseline\n"
        )
        return 1

    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    was_live = set(payload.get("live_columns", []))
    was_dead = {entry["id"] for entry in payload.get("dead_columns", [])}
    now_live = {key.describe() for key in measured.live}
    now_dead = {key.describe() for key in measured.dead}

    regressed = sorted(was_live & now_dead)
    improved = sorted(was_dead & now_live)
    appeared = sorted((now_live | now_dead) - was_live - was_dead)
    vanished = sorted((was_live | was_dead) - now_live - now_dead)

    if regressed:
        _write_lines("REGRESSION: live column(s) now dead", regressed)
        sys.stderr.write(
            f"\nREGRESSION: {len(regressed)} column(s) that carried a figure no longer do. "
            "Some portfolio stopped reporting it, and every gate over that column is now "
            "blind (.claude/LESSONS.md B5). Fix the reporting defect — do not bank this.\n"
        )
        return 1
    if improved or appeared or vanished:
        _write_lines("IMPROVED: dead column(s) now live", improved)
        _write_lines("NEW: column(s) not in the baseline", appeared)
        _write_lines("GONE: baseline column(s) no longer in any layout", vanished)
        sys.stderr.write(
            f"\nIMPROVED: {len(improved)} newly live, {len(appeared)} new, "
            f"{len(vanished)} gone vs the baseline. Bank it (and give every new dead "
            "column a reason code):\n"
            "  uv run python scripts/check_template_cell_coverage.py --update-baseline\n"
        )
        return 1
    sys.stderr.write(f"[OK] {len(measured.live)} live / {len(measured.dead)} dead == baseline\n")
    return 0


def _existing_reasons() -> dict[str, tuple[str, str]]:
    """``{column id: (reason_code, reason)}`` from the committed baseline."""
    if not BASELINE_PATH.exists():
        return {}
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {
        entry["id"]: (entry.get("reason_code", REASON_CODES[1]), entry.get("reason", UNCLASSIFIED))
        for entry in payload.get("dead_columns", [])
    }


def _counts(measured: Census) -> dict[str, Any]:
    """The aggregate census figures, as the baseline records them."""
    return {
        "template_column_pairs": len(measured.pairs),
        "live": len(measured.live),
        "dead": len(measured.dead),
        "emitted_pairs": len(measured.observed),
        "never_emitted_pairs": len(measured.pairs - measured.observed),
        "non_numeric_columns_excluded": len(measured.non_numeric),
        "frames": measured.frames,
        "numeric_cells": measured.numeric_cells,
        "non_null_cells": measured.non_null_cells,
        "non_zero_cells": measured.non_zero_cells,
        "cell_fill_pct": round(measured.fill_pct(), 2),
    }


# ---------------------------------------------------------------------------
# Running one portfolio
# ---------------------------------------------------------------------------


def _generate(spec: RunSpec) -> tuple[Any, Any]:
    """Run one portfolio and generate both template bundles.

    A raising portfolio is fatal. Skipping it would record every column it feeds
    as dead, and a silently short matrix is worse than no census at all.
    """
    try:
        result = PipelineOrchestrator().run_with_data(spec.build_bundle(), spec.build_config())
        prior = (
            PipelineOrchestrator().run_with_data(spec.build_bundle(), spec.build_prior_config())
            if spec.build_prior_config is not None
            else None
        )
        corep = COREPGenerator().generate_from_lazyframe(
            result.results,
            framework=spec.framework,
            previous_period_results=None if prior is None else prior.results,
        )
        pillar3 = Pillar3Generator().generate_from_lazyframe(
            result.results,
            framework=spec.framework,
            # CR8 is the Pillar 3 twin of C 08.04 and takes the same prior frame.
            # Withholding it here while COREP gets it would record CR8's flow
            # rows dead for a harness reason rather than an estate one.
            previous_period_results=None if prior is None else prior.results,
        )
    # Broad on purpose: ANY generator failure must become a fatal census error,
    # because a run that produces no frames is indistinguishable from one whose
    # columns are all zero. Re-raised below as SystemExit.
    except Exception as error:
        raise SystemExit(
            f"FATAL: {spec.describe()} raised {type(error).__name__}: {error}\n"
            "A portfolio that produces no frames is indistinguishable from one whose "
            "columns are all zero, so the census refuses to continue rather than "
            "recording every column it feeds as dead."
        ) from error
    return corep, pillar3


class _RunScan(NamedTuple):
    """The coverage facts one portfolio-regime run contributes."""

    observed: frozenset[ColumnKey]
    non_numeric: frozenset[ColumnKey]
    live: frozenset[ColumnKey]
    cells: int
    nulls: int
    non_zero: int
    frames: int


def _scan_run(corep: Any, pillar3: Any) -> _RunScan:
    """Tally one run's frames into a :class:`_RunScan`.

    Extracted from ``census`` so that function reads as the matrix walk it is:
    the per-column tallying is a separate concern and nesting it there put the
    loop body three levels deep.
    """
    observed: set[ColumnKey] = set()
    non_numeric: set[ColumnKey] = set()
    live: set[ColumnKey] = set()
    cells = nulls = non_zero = frames = 0

    for key, frame in _template_frames(corep, pillar3):
        frames += 1
        for column, dtype in zip(frame.columns, frame.dtypes, strict=True):
            if column in catalog.STRUCTURAL_COLS:
                continue
            address = key._replace(column=column)
            if not dtype.is_numeric():
                non_numeric.add(address)
                continue
            observed.add(address)
            series = frame.get_column(column)
            column_non_zero = int(series.fill_null(0).ne(0).sum())
            cells += series.len()
            nulls += series.null_count()
            non_zero += column_non_zero
            if column_non_zero:
                live.add(address)

    return _RunScan(
        observed=frozenset(observed),
        non_numeric=frozenset(non_numeric),
        live=frozenset(live),
        cells=cells,
        nulls=nulls,
        non_zero=non_zero,
        frames=frames,
    )


def _field_frames(value: Any) -> Iterator[pl.DataFrame]:
    """The non-empty frames a single bundle field holds.

    A field is either ``pl.DataFrame | None`` or ``dict[str, pl.DataFrame]``;
    normalising both shapes here keeps the shape-dispatch out of the walk.
    """
    if isinstance(value, pl.DataFrame):
        if not value.is_empty():
            yield value
    elif isinstance(value, dict):
        for frame in value.values():
            if isinstance(frame, pl.DataFrame) and not frame.is_empty():
                yield frame


def _template_frames(corep: Any, pillar3: Any) -> Iterator[tuple[ColumnKey, pl.DataFrame]]:
    """Every emitted template frame, keyed by (family, template, "").

    Templates are enumerated by walking ``dataclasses.fields()`` of the two
    bundles rather than from a list here: a hand-written template list would
    silently stop covering a newly added template.
    """
    for family, bundle in (("corep", corep), ("pillar3", pillar3)):
        for field in dataclasses.fields(bundle):
            if field.name in NON_TEMPLATE_FIELDS:
                continue
            key = ColumnKey(family, field.name, "")
            for frame in _field_frames(getattr(bundle, field.name)):
                yield key, frame


class _WarningCollector(logging.Handler):
    """Collects WARNING+ messages emitted on the ``rwa_calc`` namespace."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


# Lower-case name on purpose: this is a context-manager helper used as
# ``with _captured_warnings() as w:``, so it reads as a verb phrase at the call
# site rather than as a type. ruff does not select N801, so no suppression is
# needed here — a per-line ignore comment previously suppressed nothing while
# implying a rule was being overridden.
class _captured_warnings:
    """Capture one run's pipeline warnings so degradation cannot pass as silence."""

    def __init__(self) -> None:
        self._handler = _WarningCollector()
        self._logger = logging.getLogger("rwa_calc")

    def __enter__(self) -> list[str]:
        self._logger.addHandler(self._handler)
        return self._handler.messages

    def __exit__(self, *_exc: object) -> None:
        self._logger.removeHandler(self._handler)


def _fail_on_degradation(spec: RunSpec, messages: list[str]) -> None:
    """Abort when a run warned that it silently fell back to something else.

    The worked example is ``IRB permission mode selected but no model_permissions
    data provided``: the run completes, emits templates, and every IRB-only
    column it would have populated reads dead — a harness artefact banked as a
    coverage fact. Fatal rather than recorded.
    """
    hits = [
        message
        for message in messages
        if any(pattern.search(message) for pattern in FATAL_WARNING_PATTERNS)
    ]
    if not hits:
        return
    detail = "\n".join(f"  {message}" for message in hits)
    raise SystemExit(
        f"FATAL: {spec.describe()} degraded silently:\n{detail}\n"
        "The run completed but measured a different estate than it claims to. Fix the "
        "config or the fixture; do not bank a census over it."
    )


def _assert_matrix_complete(measured: Census) -> None:
    """The census ran every portfolio x regime it says it did."""
    if len(measured.runs) == EXPECTED_RUNS:
        return
    raise SystemExit(
        f"FATAL: census ran {len(measured.runs)} of {EXPECTED_RUNS} portfolio/regime "
        "combinations. A short matrix records every column its missing portfolios "
        "feed as dead."
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report(measured: Census, elapsed: float) -> None:
    counts = _counts(measured)
    sys.stdout.write("\n")
    sys.stdout.write("=" * 78 + "\n")
    sys.stdout.write("TEMPLATE CELL COVERAGE - union over 12 portfolios x 2 regimes\n")
    sys.stdout.write("=" * 78 + "\n")
    for name in (
        "template_column_pairs",
        "live",
        "dead",
        "emitted_pairs",
        "never_emitted_pairs",
        "frames",
        "numeric_cells",
        "non_null_cells",
        "non_zero_cells",
        "cell_fill_pct",
    ):
        sys.stdout.write(f"  {name:<28} {counts[name]:>10}\n")

    dead_by_template: dict[str, list[str]] = {}
    for key in sorted(measured.dead):
        prefix = f"{FAMILY_PREFIX.get(key.family, key.family)}/{key.template}"
        dead_by_template.setdefault(prefix, []).append(key.column)
    sys.stdout.write(f"\nDead columns by template ({len(dead_by_template)} templates)\n")
    for template, columns in sorted(
        dead_by_template.items(), key=lambda item: (-len(item[1]), item[0])
    )[:PRINTED_ROWS]:
        sys.stdout.write(f"  {template:<20} {len(columns):>3}  {', '.join(columns)}\n")
    if len(dead_by_template) > PRINTED_ROWS:
        sys.stdout.write(f"  ... {len(dead_by_template) - PRINTED_ROWS} more templates\n")

    if measured.warnings:
        sys.stdout.write(f"\nRecorded caveats ({len(measured.warnings)} pipeline warning(s))\n")
        for message in measured.warnings[:PRINTED_ROWS]:
            sys.stdout.write(f"  {message}\n")

    sys.stderr.write(
        f"\n{len(measured.pairs)} (template, column) pairs: {len(measured.live)} live, "
        f"{len(measured.dead)} dead; {counts['cell_fill_pct']}% cell fill "
        f"over {measured.frames} frames in {elapsed}s\n"
    )


def _write_lines(header: str, entries: list[str]) -> None:
    if not entries:
        return
    sys.stdout.write(f"\n{header} ({len(entries)})\n")
    for entry in entries[:PRINTED_ROWS]:
        sys.stdout.write(f"  {entry}\n")
    if len(entries) > PRINTED_ROWS:
        sys.stdout.write(f"  ... {len(entries) - PRINTED_ROWS} more\n")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Corpus adapters
# ---------------------------------------------------------------------------


def _corpus_bundle(portfolio: tuple[Any, ...]) -> Callable[[], RawDataBundle]:
    """A zero-argument bundle builder for one corpus portfolio."""

    def build() -> RawDataBundle:
        return build_bundle(portfolio)

    return build


def _corpus_config(regime_key: str) -> Callable[[], CalculationConfig]:
    """The corpus portfolio's own canonical config for a regime."""

    def build() -> CalculationConfig:
        return config_for(regime_key)

    return build


if __name__ == "__main__":
    raise SystemExit(main())
