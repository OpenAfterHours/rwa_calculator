"""
Cold-process benchmark of the ``rwa-filer`` commands a user runs.

Pipeline position:
    rwa-calc golden runs -> COREP -> canonical PRA001 returns (``build``)
        -> each command in a fresh process, timed (``run``)

Key responsibilities:
- Build the benchmark returns from the Basel 3.1 golden runs the filing-mapping
  ratchet measures (``scripts/filing_mapping_report.py::filed_runs``), as fact
  tables and as XBRL instances, plus the richest return copied out to 50 and
  200 countries on the open country axis of OF 09.01 / OF 09.02 — the shape at
  which the engine's open-axis costs show. Open keys are written as the
  member's local name, the form ``rwa_filer.model`` specifies and the XBRL
  reader produces.
- Time each command in a fresh process, as a user waits for it: wall clock and
  the child's own CPU (user + system, from ``os.wait4``), best of N. Wall clock
  on a shared box moves by tens of per cent between identical runs; the CPU
  figure moves far less, so both are reported.
- Compare builds: ``--against REV`` also times the ``rwa-filer`` of a git
  revision (a commit, branch or tag), checked out in a worktree under
  ``.rwa-filer-bench/builds/`` with an environment holding that member alone.
  The two run interleaved, case by case and round by round, so a change in the
  box's load falls on each of them alike.

This measures; it asserts nothing. The gates that keep a cost from coming back
are the scaling and count tests under ``packages/rwa-filer/tests``; this is how
the numbers in ``docs/plans/rwa-filer-performance-review-2026-11-22.md`` were
taken, so that they can be taken again.

Usage:
    uv run python scripts/rwa_filer_benchmark.py build
    uv run python scripts/rwa_filer_benchmark.py run
    uv run python scripts/rwa_filer_benchmark.py run --against master --repeats 5 --only validate

Every location is fixed (the returns, the baseline builds), and a revision is
named, never a path: a script that builds a path from an operator's string is
the file-read sink ``scripts/arch_check.py`` check 19 bans.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — the review these numbers serve
- scripts/filing_mapping_report.py — the golden Basel 3.1 runs
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
# Run as a script, only scripts/ is on the path; the golden runs live in
# scripts.filing_mapping_report, which imports from the repository root.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
#: Where ``build`` writes the returns and ``run`` reads them (git-ignored).
RETURNS = REPO_ROOT / ".rwa-filer-bench" / "returns"
#: Where ``run --against`` checks out the revision it compares with (git-ignored).
BUILDS = REPO_ROOT / ".rwa-filer-bench" / "builds"
#: The console script's place inside a virtual environment.
_SCRIPTS, _EXECUTABLE = ("Scripts", "rwa-filer.exe") if os.name == "nt" else ("bin", "rwa-filer")
#: The richest golden return, the one copied out to many countries.
RICH = "rich"
#: The two tables with an open country axis.
GEOGRAPHICAL = ("OF09.01.01.01", "OF09.02.01.01")
#: How many countries the wide copies report.
COUNTRY_COUNTS = (50, 200)
#: The header a fact table carries on the command line (it has none of its own).
ENTITY = "5493001KJTIIGC8Y1R12"
REFERENCE_DATE = "2027-03-31"
MODULE = "PRA001"
#: A fixed submission date, so an evidence export does not change with the day.
SUBMISSION_DATE = "2026-11-22"


@dataclass(frozen=True)
class Case:
    """One command to time.

    Attributes:
        name: How the case is labelled in the table.
        argv: The command's arguments after ``rwa-filer``. ``{returns}`` is the
            returns directory and ``{out}`` a fresh output directory per run.
    """

    name: str
    argv: tuple[str, ...]

    def arguments(self, returns: Path, out: Path) -> list[str]:
        """The arguments with the two directories filled in."""
        return [part.format(returns=returns, out=out) for part in self.argv]


def _header(*argv: str) -> tuple[str, ...]:
    """``argv`` followed by the header options a fact table needs."""
    return (*argv, "--entity", ENTITY, "--reference-date", REFERENCE_DATE, "--module", MODULE)


#: The commands timed, in the order of the table.
CASES: tuple[Case, ...] = (
    Case("--help", ("--help",)),
    Case("taxonomy list", ("taxonomy", "list")),
    Case("validate rich.parquet (2.2k facts)", _header("validate", "{returns}/rich.parquet")),
    Case("validate rich.xbrl (2.2k facts)", ("validate", "{returns}/rich.xbrl")),
    Case("validate rich-50c.parquet (8k facts)", _header("validate", "{returns}/rich-50c.parquet")),
    Case(
        "validate rich-200c.parquet (26k facts)", _header("validate", "{returns}/rich-200c.parquet")
    ),
    Case("validate rich-200c.xbrl (26k facts)", ("validate", "{returns}/rich-200c.xbrl")),
    Case(
        "validate --evidence rich.parquet",
        _header(
            "validate",
            "{returns}/rich.parquet",
            "--evidence",
            "{out}/rich.evidence.jsonl.gz",
            "--submission-date",
            SUBMISSION_DATE,
        ),
    ),
    Case(
        "validate --evidence rich-200c.parquet",
        _header(
            "validate",
            "{returns}/rich-200c.parquet",
            "--evidence",
            "{out}/rich-200c.evidence.jsonl.gz",
            "--submission-date",
            SUBMISSION_DATE,
        ),
    ),
    # --force: the golden returns break published rules, and a build that
    # refuses writes nothing, which would time only the validation.
    Case(
        "build rich.parquet",
        _header("build", "{returns}/rich.parquet", "--out", "{out}/b", "--force"),
    ),
    Case(
        "build rich-200c.parquet",
        _header("build", "{returns}/rich-200c.parquet", "--out", "{out}/b", "--force"),
    ),
    Case(
        "compare rich.xbrl irb-classes.xbrl",
        ("compare", "{returns}/rich.xbrl", "{returns}/irb-classes.xbrl"),
    ),
    Case(
        "compare rich-200c.xbrl rich-50c.xbrl",
        ("compare", "{returns}/rich-200c.xbrl", "{returns}/rich-50c.xbrl"),
    ),
    Case(
        "diff rich.xbrl irb-classes.xbrl",
        ("diff", "{returns}/rich.xbrl", "{returns}/irb-classes.xbrl"),
    ),
    Case(
        "diff rich.parquet irb-classes.parquet",
        _header("diff", "{returns}/rich.parquet", "{returns}/irb-classes.parquet"),
    ),
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``build`` or ``run`` sub-command and return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="build the benchmark returns")
    run = commands.add_parser("run", help="time the commands")
    run.add_argument(
        "--against",
        metavar="REV",
        help="also time the rwa-filer of this git revision (a commit, branch or tag)",
    )
    run.add_argument("--repeats", type=int, default=3, help="runs per case and build")
    run.add_argument("--only", default="", help="time only the cases whose name contains this")
    args = parser.parse_args(argv)
    if args.command == "build":
        return build_returns(RETURNS)
    filers = {"this checkout": Path(sys.executable).parent / _EXECUTABLE}
    if args.against:
        filers = {args.against: baseline_filer(args.against), **filers}
    return time_cases(RETURNS, filers, repeats=args.repeats, only=args.only)


def baseline_filer(revision: str) -> Path:
    """The ``rwa-filer`` of ``revision``, checked out and installed on its own.

    The checkout is a detached worktree under ``BUILDS`` named by the commit,
    kept between runs; its environment holds the rwa-filer member alone
    (``uv sync --package rwa-filer``), which is all the command line needs.
    """
    commit = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree = BUILDS / commit[:12]
    if not tree.exists():
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "add", "--detach", str(tree), commit],
            check=True,
        )
    subprocess.run(["uv", "sync", "--quiet", "--package", "rwa-filer"], cwd=tree, check=True)
    return tree / ".venv" / _SCRIPTS / _EXECUTABLE


def build_returns(returns: Path) -> int:
    """Write the golden Basel 3.1 returns, and the wide copies of ``rich``, to ``returns``."""
    # Imported here so that ``run`` (and the contract test of the cases) needs
    # neither the rwa-calc pipeline nor a pipeline run.
    import polars as pl
    from scripts.filing_mapping_report import (
        ENTITY_IDENTIFIER,
        FILING_MODULE,
        FILING_TAXONOMY,
        filed_runs,
    )
    from scripts.filing_mapping_report import (
        REFERENCE_DATE as FILING_REFERENCE_DATE,
    )

    from rwa_calc.engine.pipeline import PipelineOrchestrator
    from rwa_calc.reporting.corep.generator import COREPGenerator
    from rwa_calc.reporting.filing.canonical import build_canonical_return
    from rwa_filer.model import CanonicalReturn, ReturnHeader
    from rwa_filer.release import resolve_release
    from rwa_filer.validate.structure import check_structure
    from rwa_filer.xbrl.writer import write_instance

    returns.mkdir(parents=True, exist_ok=True)
    header = ReturnHeader(ENTITY_IDENTIFIER, FILING_REFERENCE_DATE, FILING_MODULE)
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack

    def save(name: str, ret: CanonicalReturn) -> None:
        findings = check_structure(ret, pack)
        ret.facts.write_parquet(returns / f"{name}.parquet")
        if not findings:
            (returns / f"{name}.xbrl").write_bytes(write_instance(ret, pack).content)
        print(f"{name}: {ret.facts.height:,} facts, {len(findings)} structure findings")

    for run in filed_runs():
        result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
        corep = COREPGenerator().generate_from_lazyframe(
            result.results,
            framework=run.framework,
            output_floor_summary=result.output_floor_summary,
        )
        save(
            run.portfolio.replace("/", "_"),
            build_canonical_return(corep, header, pack=pack).canonical,
        )

    rich = pl.read_parquet(returns / f"{RICH}.parquet")
    for countries in COUNTRY_COUNTS:
        parts = [rich.filter(~pl.col("table").is_in(GEOGRAPHICAL))]
        for table in GEOGRAPHICAL:
            axis = pack.tables[table].open_axis
            assert axis is not None, f"{table} has no open axis"
            own = rich.filter(pl.col("table") == table)
            first = own.filter(pl.col("open_key") == own["open_key"].drop_nulls().min())
            keys = [member.rpartition(":")[2] for member in axis.members[:countries]]
            parts.append(
                first.drop("open_key")
                .join(pl.DataFrame({"open_key": keys}), how="cross")
                .select(rich.columns)
            )
        save(f"{RICH}-{countries}c", CanonicalReturn.from_frame(header, pl.concat(parts)))
    return 0


def time_cases(returns: Path, filers: Mapping[str, Path], *, repeats: int, only: str = "") -> int:
    """Time every case (or those matching ``only``) with each build; print a table."""
    if not (returns / f"{RICH}.parquet").exists():
        print(f"no benchmark returns in {returns}: run the 'build' command first", file=sys.stderr)
        return 2
    cases = [case for case in CASES if only in case.name]
    print(f"| Case | {' | '.join(f'{label}: wall / CPU (s)' for label in filers)} |")
    print(f"|---|{'---|' * len(filers)}")
    for case in cases:
        best = dict.fromkeys(filers, (float("inf"), float("inf")))
        for _ in range(repeats):
            for label, filer in filers.items():
                wall, cpu = _timed(filer, case, returns)
                best[label] = (min(best[label][0], wall), min(best[label][1], cpu))
        cells = " | ".join(f"{wall:.2f} / {cpu:.2f}" for wall, cpu in best.values())
        print(f"| {case.name} | {cells} |", flush=True)
    return 0


def _timed(filer: Path, case: Case, returns: Path) -> tuple[float, float]:
    """Run one case once in a fresh process: its wall clock and its own CPU, in seconds."""
    out = Path(tempfile.mkdtemp(prefix="rwa-filer-bench-"))
    try:
        started = time.perf_counter()
        process = subprocess.Popen(
            [str(filer), *case.arguments(returns, out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _, status, usage = os.wait4(process.pid, 0)
        wall = time.perf_counter() - started
        process.returncode = os.waitstatus_to_exitcode(status)
        if process.returncode not in (0, 1):
            raise RuntimeError(f"{case.name} with {filer} exited {process.returncode}")
        return wall, usage.ru_utime + usage.ru_stime
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
