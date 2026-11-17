#!/usr/bin/env python3
"""
Referee differential — do Arelle and our rule engine agree on what we would file?

Pipeline position:
    (no pipeline stage — gates the filing package end to end)
    RUNS (Basel 3.1)  ->  COREPGenerator  ->  filing.build_canonical_return
        ->  rwa_filer.xbrl.write_instance  ->  <portfolio>.xbrl
        ->  rwa_filer.referee.run_referee (Arelle, on the Bank's taxonomy package)
        ->  rwa_filer.referee.differential.compare (against rwa_filer's own verdicts)
        ->  scripts/referee_differential_baseline.json

Every other gate on the filing package is this project checking its own work:
our writer against our reader, our rule engine against our reading of the
rules. This one asks someone else. Arelle is the reference open-source XBRL
processor, and the Bank of England's taxonomy package holds the same rules as
XBRL formulas — what the Bank's gateway runs. For each golden return:

- Arelle must load it with NO error-level message: valid XBRL 2.1, dimensionally
  valid, no filing-rule breach. That is the writer, refereed.
- Arelle's verdict on every rule the return's templates trigger must be the
  verdict of rwa-filer's native engine. That is the engine, refereed. A
  disagreement means one of the two has misread a rule; the three found while
  building this gate were one in each direction and one in the taxonomy.
  Arelle runs the taxonomy's formulas and knows nothing of the Bank's
  validations deny list, so a rule the list deactivates or downgrades is
  compared as its formula evaluates it (``RuleResult.formula``, read by
  ``rwa_filer.referee.differential.compare``), never as the gateway now runs it.

A golden return is every Basel 3.1 portfolio of the supervisory register's
matrix (``RUNS``, imported and never re-declared) whose generated estate has no
structure finding — the others cannot be written as valid XBRL at all, and are
the filing-mapping ratchet's business. Which portfolios are golden is itself
held: one that drops out, or newly qualifies, must be re-banked and explained.

What is held, per golden return, two-way against the baseline:

- ``disagreements`` — the rules the two engines differ on. Exactly the banked
  list: a new one fails, and so does one that has gone away unrecorded.
- ``arelle_errors`` — Arelle's error-level message codes. Exactly the banked
  list, which is empty.
- ``count_differences`` — rules with one verdict over two evaluation counts.
  Exactly the banked list. Reported separately because a count is weaker
  evidence than a verdict (see ``rwa_filer.referee.differential.COUNT_DIFFERS``).
- ``rules_compared`` — may not FALL. An empty comparison agrees with everything.

A referee run that did not finish is a failure, never a pass.

Needs Arelle and the taxonomy package, neither of which is in the repository.
Both are found at fixed places, never named on the command line (arch_check
check 19 — a script does not build a path from what its caller types):

- the Bank's package at ``.taxonomy/boe-banking-v411.zip`` (git-ignored);
- an interpreter that has ``arelle-release``, named by ``RWA_FILER_ARELLE_PYTHON``
  — which ``rwa_filer.referee`` reads — or else the current one.

    RWA_FILER_ARELLE_PYTHON=/path/to/arelle-venv/bin/python \\
        uv run python scripts/referee_differential.py --check

Every golden return is built and filed first, one after another. Then every
Arelle worker of every return runs through ONE pool, as many at once as fit in
the memory available at ``--max-rss-gb`` each (``--jobs N`` to say how many;
``rwa_filer.referee.resolve_jobs``), and only then is each return set beside the
native engine. A worker is about a minute and 3-4 GB of Arelle; a return is
three or four of them. ``--portfolio`` restricts the run for a quick local
look; a restricted run cannot be banked. The instances, Arelle's per-worker
files, the measurement and the timings are left in ``.referee-run/``
(git-ignored), which is cleared at the start of every run — all but its
``cache/``.

A worker's result is cached, keyed by a SHA-256 over everything it depends on
(the instance's bytes, the taxonomy package's, the overlay's members, the
filing-rule plug-in, the spec's settings, the Arelle release and the referee's
own code) and never over a path; see ``rwa_filer.referee.runner``. A hit skips
that Arelle worker only: every return is still built, filed, merged and set
beside the native engine. The cache is ``.referee-run/cache/``, or the folder
``RWA_FILER_REFEREE_CACHE`` names (read by ``rwa_filer.referee``, not here:
check 19); ``--no-cache`` runs every worker and stores nothing.

Exit codes:
    0 = measured (and, with --check, nothing moved)
    1 = a disagreement, an Arelle error, an unfinished run, or a moved register

References:
- packages/rwa-filer/src/rwa_filer/referee — the referee and the differential
- Bank of England Banking Taxonomy v4.1.1 — package ``boe-banking-v411.zip``
- docs/rwa-filer/index.md
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.filing_mapping_report import (  # noqa: E402
    ENTITY_IDENTIFIER,
    REFERENCE_DATE,
    filed_runs,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402
from rwa_calc.reporting.corep.generator import COREPGenerator  # noqa: E402
from rwa_calc.reporting.filing.canonical import (  # noqa: E402
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.model import ReturnHeader  # noqa: E402
from rwa_filer.referee import (  # noqa: E402
    PreparedReferee,
    find_arelle_python,
    prepare_referee,
    referee_cache_dir,
    resolve_jobs,
    run_referees,
)
from rwa_filer.referee.differential import compare  # noqa: E402
from rwa_filer.release import resolve_release  # noqa: E402
from rwa_filer.validate.returns import validate_return  # noqa: E402
from rwa_filer.validate.structure import check_structure  # noqa: E402
from rwa_filer.xbrl.reader import read_instance  # noqa: E402
from rwa_filer.xbrl.writer import write_instance  # noqa: E402

BASELINE_PATH = _REPO_ROOT / "scripts" / "referee_differential_baseline.json"
#: Where the Bank of England's taxonomy package is expected. Not in the
#: repository: it is the publisher's file. The workflow downloads it here.
TAXONOMY_PACKAGE = _REPO_ROOT / ".taxonomy" / "boe-banking-v411.zip"
#: Where a run leaves its instances, Arelle's per-worker files and its measurement.
RUN_DIRECTORY = _REPO_ROOT / ".referee-run"
MEASUREMENT_PATH = RUN_DIRECTORY / "measured.json"
#: How long each part of the run took. Kept apart from the measurement, which
#: is banked: a timing is not a verdict.
TIMINGS_PATH = RUN_DIRECTORY / "timings.json"
#: The resident memory one Arelle worker is held to, in GB. The largest of the
#: 51 workers of the 16 golden returns peaked at 3.89 GB (a 120 MB chunk, the
#: cyclic collector off; 3.66 with it on). The cap is also what the automatic
#: number of workers at once budgets: at 5 GB, two on a 16 GB machine.
DEFAULT_MAX_RSS_GB = 5.0
#: Where workers' results are cached unless ``RWA_FILER_REFEREE_CACHE`` says
#: otherwise. Inside the run directory, and kept when the rest of it is cleared.
CACHE_DIRECTORY = RUN_DIRECTORY / "cache"

#: Per-portfolio registers held exactly: nothing may join or leave unrecorded.
REGISTERS = ("disagreements", "arelle_errors", "count_differences")
#: Per-portfolio counts that may not fall.
RATCHET_MIN = ("rules_compared",)

BASELINE_COMMENT = (
    "Referee differential baseline (scripts/referee_differential.py --check). For each golden "
    "return: disagreements, arelle_errors and count_differences are held EXACTLY (a new entry "
    "fails, and so does one that went away unrecorded); rules_compared may not DECREASE. "
    "Re-measure with --update-baseline after a deliberate change and say why in _note; never "
    "type the entries."
)
UNEXPLAINED_NOTE = "unexplained — say why this baseline was re-banked"


def main() -> int:
    """Measure, then print, gate or re-bank as asked."""
    parser = argparse.ArgumentParser(
        description="File golden Basel 3.1 returns, have Arelle referee them, and hold the "
        "native rule engine to Arelle's verdicts.",
    )
    parser.add_argument(
        "--portfolio",
        action="append",
        metavar="NAME",
        help="run only this portfolio (repeatable); a restricted run cannot be banked",
    )
    parser.add_argument(
        "--max-rss-gb",
        type=float,
        default=DEFAULT_MAX_RSS_GB,
        metavar="GB",
        help="the resident memory one Arelle worker is held to; it is killed above it "
        "(default %(default)s)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        metavar="N",
        help="Arelle workers to run at once (default: as many as fit in the memory "
        "available at --max-rss-gb each, one per CPU at most)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="run every Arelle worker and store no result (default: reuse a worker's "
        "result from .referee-run/cache/, or $RWA_FILER_REFEREE_CACHE, when nothing it "
        "depends on changed)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if anything moved")
    mode.add_argument(
        "--update-baseline", action="store_true", help="re-bank the baseline from this run"
    )
    args = parser.parse_args()
    if not TAXONOMY_PACKAGE.is_file():
        parser.error(
            f"the Bank of England taxonomy package is not at "
            f"{TAXONOMY_PACKAGE.relative_to(_REPO_ROOT).as_posix()}; download "
            "boe-banking-v411.zip from the Bank's banking taxonomy page and put it there"
        )
    if args.update_baseline and args.portfolio:
        parser.error("a run restricted with --portfolio cannot be banked")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be at least 1")

    started = time.perf_counter()
    cache_dir = None if args.no_cache else referee_cache_dir(CACHE_DIRECTORY)
    if cache_dir is not None and cache_dir.resolve() == RUN_DIRECTORY.resolve():
        parser.error(f"{cache_dir} is the run directory, which every run clears")
    clear_run_directory(keep=(CACHE_DIRECTORY, *(() if cache_dir is None else (cache_dir,))))
    timings: dict[str, Any] = {}
    measured = measure(
        TAXONOMY_PACKAGE,
        workdir=RUN_DIRECTORY,
        only=frozenset(args.portfolio or ()),
        max_rss_gb=args.max_rss_gb,
        jobs=args.jobs,
        cache_dir=cache_dir,
        timings=timings,
    )
    timings["total_s"] = round(time.perf_counter() - started, 1)
    print_report(measured, timings["total_s"])
    print_timings(timings)
    MEASUREMENT_PATH.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    TIMINGS_PATH.write_text(json.dumps(timings, indent=2) + "\n", encoding="utf-8")

    if args.update_baseline:
        write_baseline(measured)
        print(f"\nWrote {BASELINE_PATH.relative_to(_REPO_ROOT).as_posix()}")
        return 0
    problems = run_problems(measured)
    if args.check:
        problems += check_against_baseline(
            measured, load_baseline(), restricted=bool(args.portfolio)
        )
    print("\nReferee differential")
    if problems:
        for problem in problems:
            print(f"  [FAIL] {problem}")
        return 1
    print("  [OK] Arelle accepts every golden return and the two engines agree")
    return 0


# =============================================================================
# Measurement
# =============================================================================


@dataclass(frozen=True)
class FiledReturn:
    """A golden return, written to disk and planned for Arelle, awaiting the pool."""

    name: str
    content: bytes
    facts: int
    prepared: PreparedReferee


def measure(
    taxonomy_package: Path,
    *,
    workdir: Path,
    python: Path | None = None,
    only: frozenset[str] = frozenset(),
    max_rss_gb: float = DEFAULT_MAX_RSS_GB,
    jobs: int | None = None,
    cache_dir: Path | None = None,
    timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """File every golden return, have Arelle referee them all, then compare each.

    Three phases. Every golden return is built and written, one after another.
    Every Arelle worker of every return then runs through one pool. Then each
    return's referee result is set beside the native engine's verdicts on the
    same file.

    Args:
        taxonomy_package: The Bank's taxonomy package zip.
        workdir: Where each instance and Arelle's per-worker files are written.
        python: An interpreter that has Arelle. Defaults to the referee's own
            lookup: ``RWA_FILER_ARELLE_PYTHON``, then the current interpreter.
        only: Portfolio names to restrict the run to; empty runs them all.
        max_rss_gb: The memory an Arelle worker is held to.
        jobs: Arelle workers run at once; ``None`` for as many as fit.
        cache_dir: Where Arelle workers' results are reused from and stored;
            ``None`` to run every worker and store nothing.
        timings: Filled in, when given, with how long each phase and each
            return took. Never part of the measurement.
    """
    timings = {} if timings is None else timings
    header = ReturnHeader(ENTITY_IDENTIFIER, REFERENCE_DATE, FILING_MODULE)
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    not_golden: dict[str, int] = {}
    runs = [run for run in filed_runs() if not only or run.portfolio in only]

    phase = time.perf_counter()
    golden: list[FiledReturn] = []
    timings["build_s"] = {}
    for index, run in enumerate(runs, start=1):
        name = portfolio_key(run)
        print(f"  [{index}/{len(runs)}] {name} ...", flush=True)
        built = time.perf_counter()
        filed = file_return(run, name, header, pack, workdir, taxonomy_package)
        timings["build_s"][name] = round(time.perf_counter() - built, 1)
        if isinstance(filed, int):
            not_golden[name] = filed
            print(f"        not golden: {filed} structure finding(s); not filed")
            continue
        golden.append(filed)
    timings["build_phase_s"] = round(time.perf_counter() - phase, 1)

    phase = time.perf_counter()
    workers = resolve_jobs(jobs, max_rss_gb)
    planned = sum(len(item.prepared.specs) for item in golden)
    print(
        f"  Arelle: {planned} worker(s) for {len(golden)} golden return(s), {workers} at a "
        f"time, each held to {max_rss_gb:g} GB; "
        + ("no cache" if cache_dir is None else f"cache {cache_dir}"),
        flush=True,
    )
    referees = run_referees(
        [item.prepared for item in golden],
        python=python,
        jobs=workers,
        max_rss_gb=max_rss_gb,
        cache_dir=cache_dir,
    )
    timings["jobs"] = workers
    timings["arelle_workers_reused"] = sum(
        chunk.cached for referee in referees for chunk in referee.chunks
    )
    timings["arelle_phase_s"] = round(time.perf_counter() - phase, 1)
    timings["arelle_workers_s"] = {
        item.name: [chunk.wall_s for chunk in referee.chunks]
        for item, referee in zip(golden, referees, strict=True)
    }

    phase = time.perf_counter()
    portfolios: dict[str, Any] = {}
    for item, referee in zip(golden, referees, strict=True):
        # The native engine reads the FILE, as Arelle does — not the frame it
        # was written from.
        filed = read_instance(item.content, pack=pack)
        report = validate_return(filed.ret, filed.pack, source_findings=filed.findings).report
        if report is None:
            raise SystemExit(f"no rule book is packaged for module {FILING_MODULE}")
        differential = compare(report.results, referee)
        portfolios[item.name] = {
            "facts": item.facts,
            "referee_complete": referee.complete,
            "rules_evaluated_by_arelle": len(referee.rules),
            "rules_compared": differential.compared,
            "agree": differential.counts()["agree"],
            "disagreements": [describe(entry) for entry in differential.disagreements],
            "count_differences": [describe(entry) for entry in differential.count_differences],
            "arelle_errors": sorted({message.code for message in referee.errors}),
            "arelle_messages": sorted({message.code for message in referee.messages}),
            "lost": list(referee.lost),
        }
    timings["compare_phase_s"] = round(time.perf_counter() - phase, 1)

    return {
        "measured_with": {
            "arelle": arelle_version(python),
            "taxonomy_package_sha256": hashlib.sha256(taxonomy_package.read_bytes()).hexdigest(),
        },
        "portfolios": portfolios,
        "provenance": {
            "golden": sorted(portfolios),
            "not_golden": dict(sorted(not_golden.items())),
        },
    }


def file_return(
    run: Any,
    name: str,
    header: ReturnHeader,
    pack: Any,
    workdir: Path,
    taxonomy_package: Path,
) -> FiledReturn | int:
    """Build one portfolio's return, write it and plan its Arelle run.

    Returns the filed return, or — for a return that cannot be written as
    valid XBRL — the number of its structure findings.
    """
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    # With the run's own floor summary, as ``export_filing_package`` files it.
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    canonical = build_canonical_return(corep, header, pack=pack).canonical
    del result, corep
    gc.collect()

    findings = check_structure(canonical, pack)
    if findings:
        return len(findings)

    folder = workdir / name.replace("/", "_")
    folder.mkdir(parents=True, exist_ok=True)
    written = write_instance(canonical, pack)
    instance = folder / f"{ENTITY_IDENTIFIER}_{FILING_MODULE}_{REFERENCE_DATE.isoformat()}.xbrl"
    instance.write_bytes(written.content)
    return FiledReturn(
        name=name,
        content=written.content,
        facts=written.facts,
        prepared=prepare_referee(instance, taxonomy_package, workdir=folder / "arelle"),
    )


def clear_run_directory(*, keep: tuple[Path, ...]) -> None:
    """Empty the run directory of everything but the folders ``keep`` names or holds.

    The cache lives in the run directory by default and must outlive the run
    that filled it; whatever else is there is the previous run's, and goes.
    """
    RUN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    kept = [folder.resolve() for folder in keep]
    for entry in RUN_DIRECTORY.iterdir():
        resolved = entry.resolve()
        if any(folder == resolved or folder.is_relative_to(resolved) for folder in kept):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def arelle_version(python: Path | None) -> str:
    """The ``arelle-release`` version of the interpreter the referee runs under."""
    interpreter = find_arelle_python(python)
    probe = "from importlib.metadata import version; print(version('arelle-release'))"
    done = subprocess.run(  # noqa: S603 - the interpreter the operator named, a fixed script
        [str(interpreter), "-I", "-c", probe], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def portfolio_key(run: Any) -> str:
    """``regime/portfolio`` — how a run is named in the baseline."""
    return f"{run.regime}/{run.portfolio}"


def describe(item: Any) -> str:
    """One compared rule as a line that says both standings."""
    referee = "" if item.referee_counts is None else f" {list(item.referee_counts)}"
    return (
        f"{item.rule_id}: native {item.native} {list(item.native_counts)}, "
        f"Arelle {item.referee}{referee}"
    )


def rule_of(entry: str) -> str:
    """The rule a ``describe`` line is about."""
    return entry.split(":", 1)[0]


# =============================================================================
# Baseline
# =============================================================================


def load_baseline() -> dict[str, Any]:
    """Read the committed baseline. A missing one is a failure, never a pass."""
    if not BASELINE_PATH.exists():
        raise SystemExit(
            f"{BASELINE_PATH} does not exist. A gate with no baseline gates nothing: "
            "create it with --update-baseline."
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(measured: dict[str, Any]) -> None:
    """Re-bank the baseline from this run, preserving a hand-written ``_note``."""
    note = UNEXPLAINED_NOTE
    if BASELINE_PATH.exists():
        note = json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("_note", note)
    payload = {"_comment": BASELINE_COMMENT, "_note": note, **measured}
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_problems(measured: dict[str, Any]) -> list[str]:
    """What is wrong with the run itself, whatever the baseline says."""
    problems: list[str] = []
    if not measured["portfolios"]:
        problems.append("no golden return was filed: nothing was refereed")
    for name, entry in measured["portfolios"].items():
        if not entry["referee_complete"]:
            problems.append(
                f"{name}: the Arelle run did not finish ({len(entry['lost'])} rule(s) lost); "
                "an unfinished run proves nothing"
            )
        if not entry["rules_compared"]:
            problems.append(f"{name}: no rule was compared")
    return problems


def check_against_baseline(
    measured: dict[str, Any], baseline: dict[str, Any], *, restricted: bool = False
) -> list[str]:
    """Every way ``measured`` departs from ``baseline``. Empty means nothing moved.

    Args:
        restricted: The run covered only some portfolios (``--portfolio``); the
            ones it did not run are not reported as missing.
    """
    problems: list[str] = []
    banked = baseline.get("portfolios", {})
    if measured["measured_with"] != baseline.get("measured_with"):
        problems.append(
            f"measured with {measured['measured_with']}, banked with "
            f"{baseline.get('measured_with')}: a different taxonomy package or Arelle release "
            "is a new measurement — re-bank it, and say what changed"
        )
    if not restricted and measured["provenance"] != baseline.get("provenance"):
        problems.append(
            "the golden returns changed: measured "
            f"{measured['provenance']}, banked {baseline.get('provenance')}. A portfolio that "
            "gained or lost a structure finding moved in or out of this gate; re-bank and say why"
        )
    for name, entry in measured["portfolios"].items():
        if name not in banked:
            if restricted or measured["provenance"] == baseline.get("provenance"):
                problems.append(f"{name}: the baseline does not bank this portfolio")
            continue
        was = banked[name]
        for register in REGISTERS:
            if register not in was:
                problems.append(f"{name}: the baseline does not bank {register}")
                continue
            now_rules = {rule_of(line) for line in entry[register]}
            was_rules = {rule_of(line) for line in was[register]}
            if new := sorted(now_rules - was_rules):
                lines = [line for line in entry[register] if rule_of(line) in new]
                problems.append(f"{name}: new {register}: {'; '.join(lines)}")
            if gone := sorted(was_rules - now_rules):
                problems.append(
                    f"{name}: {register} no longer found: {', '.join(gone)} — re-bank to "
                    "record the improvement"
                )
        for total in RATCHET_MIN:
            if total not in was:
                problems.append(f"{name}: the baseline does not bank {total}")
            elif entry[total] < was[total]:
                problems.append(f"{name}: {total} fell from {was[total]} to {entry[total]}")
    return problems


# =============================================================================
# Reporting
# =============================================================================


def print_timings(timings: dict[str, Any]) -> None:
    """Print where the time went: the three phases, and each return's Arelle workers."""
    print(
        f"\nTimings  build {timings.get('build_phase_s', 0):.0f}s, Arelle "
        f"{timings.get('arelle_phase_s', 0):.0f}s ({timings.get('jobs', '?')} at a time, "
        f"{timings.get('arelle_workers_reused', 0)} worker(s) reused from the cache), "
        f"compare {timings.get('compare_phase_s', 0):.0f}s"
    )
    for name, walls in timings.get("arelle_workers_s", {}).items():
        print(
            f"  {name:<32} build {timings['build_s'].get(name, 0):>5.1f}s  "
            f"Arelle {sum(walls):>6.1f}s in {len(walls)} worker(s)"
        )


def print_report(measured: dict[str, Any], seconds: float) -> None:
    """Print one line per golden return, then whatever did not simply agree."""
    print(f"\nReferee differential  ({seconds:.0f}s)")
    for name, entry in measured["portfolios"].items():
        state = "complete" if entry["referee_complete"] else "INCOMPLETE"
        print(
            f"  {name:<32} {entry['facts']:>5} facts  Arelle {state}, "
            f"{len(entry['arelle_errors'])} error(s)  compared {entry['rules_compared']:>4}: "
            f"{entry['agree']} agree, {len(entry['count_differences'])} count, "
            f"{len(entry['disagreements'])} DISAGREE"
        )
        for register in REGISTERS:
            for line in entry[register]:
                print(f"      {register}: {line}")
    for name, findings in measured["provenance"]["not_golden"].items():
        print(f"  {name:<32} not filed: {findings} structure finding(s)")


if __name__ == "__main__":
    sys.exit(main())
