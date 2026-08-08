"""
Defect-injection scorecard (independent validation plan, C6).

Everything C1-C5 builds is a *hypothesis* about what would have been caught.
This measures it. For each mutant in ``scripts/defect_catalogue.py`` the harness
injects the defect, walks a ladder of gates cheapest-first, stops at the first
gate that goes red, and records which one it was. The output is a detection
rate, the mean tier at which detection happens, and -- the part that actually
matters -- the list of defects nothing caught.

Three verdicts, not two
-----------------------
``DETECTED``    a gate went red, and we know which one and how long it took.
``ESCAPED``     the mutant changed output and every gate stayed green.
``UNREACHABLE`` the mutant applied cleanly but changed no observable output.

The third category is not bookkeeping. Mutating the rulepack's
``output_floor_pct_full`` from 0.725 to 0.100 once left 52/52 floor properties
passing, which read as proof they were vacuous -- they were not, the scalar is
only consumed under an election no test makes. Without a reachability probe that
mutant scores as an escape and the headline rate is fiction in the pessimistic
direction. So every mutant must be shown to move an output BEFORE any gate runs,
and the catalogue carries two deliberate controls (one reachable, one not) whose
verdicts prove the probe still works.

``TIMEOUT`` is its own outcome and is never counted as a pass.

Two ladders from one build
--------------------------
``--ladder legacy`` runs only the gates that existed before this project;
``--ladder full`` adds the oracle, the property suite, the coverage report and
the impact report. Running both gives a before/after detection rate without
building anything twice.

Safety
------
This script edits files under ``src/``. It refuses to start if any target file
is dirty in git, so recovery is always ``git checkout -- <file>`` and no
uncommitted work can be destroyed. Restoration is belt-and-braces: a context
manager with ``try/finally``, an ``atexit`` hook, and a post-restore verification
that the bytes really came back.

Run:
    uv run python scripts/defect_injection.py --self-test          # applies nothing
    uv run python scripts/defect_injection.py --reachability-only  # probe, no gates
    uv run python scripts/defect_injection.py --ladder legacy      # full campaign

Every pytest gate carries ``-n 0``: the machine this runs on has ~2.7 GB free
and ``-n auto`` would spawn sixteen workers each building session fixtures.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.defect_catalogue import CATALOGUE, Mutant, select, targets  # noqa: E402

DEFAULT_OUT = _REPO_ROOT / "scripts" / "defect_scorecard.json"

VERDICT_DETECTED = "DETECTED"
VERDICT_ESCAPED = "ESCAPED"
VERDICT_UNREACHABLE = "UNREACHABLE"
VERDICT_ERROR = "ERROR"

OUTCOME_RED = "RED"
OUTCOME_GREEN = "GREEN"
OUTCOME_TIMEOUT = "TIMEOUT"


# =============================================================================
# The ladder
# =============================================================================


@dataclass(frozen=True)
class Gate:
    """One rung. Adding a gate is one entry here; the runner never changes.

    ``legacy`` marks gates that existed before the independent-validation work,
    so one campaign yields both the before and the after rate.

    ``baseline_cmd`` runs once on the clean tree and prepares whatever the gate
    compares against (the impact report needs a captured snapshot). ``{baseline}``
    in either command is substituted with a per-run scratch path.
    """

    name: str
    tier: int
    cmd: tuple[str, ...]
    legacy: bool
    #: Minutes. A gate that hangs is a finding, not a pass.
    timeout_minutes: float = 30.0
    baseline_cmd: tuple[str, ...] | None = None


#: Cheapest first. A mutant stops at the first red rung, so the tier of
#: detection is a real measure of how early the estate notices.
LADDER: tuple[Gate, ...] = (
    Gate(
        "arch_check",
        0,
        ("uv", "run", "python", "scripts/arch_check.py"),
        legacy=True,
        timeout_minutes=10,
    ),
    Gate(
        "oracle",
        1,
        ("uv", "run", "pytest", "tests/oracle", "-q", "-n", "0"),
        legacy=False,
        timeout_minutes=10,
    ),
    Gate(
        "properties",
        2,
        ("uv", "run", "pytest", "tests/properties", "-q", "-n", "0"),
        legacy=False,
        timeout_minutes=20,
    ),
    Gate("unit", 3, ("uv", "run", "pytest", "tests/unit", "-q", "-x", "-n", "0"), legacy=True),
    Gate(
        "contracts",
        4,
        ("uv", "run", "pytest", "tests/contracts", "-q", "-x", "-n", "0"),
        legacy=True,
    ),
    Gate(
        "acceptance",
        5,
        (
            "uv",
            "run",
            "pytest",
            "tests/acceptance",
            "-q",
            "-x",
            "-n",
            "0",
            "-m",
            "not slow and not stress and not benchmark",
        ),
        legacy=True,
        timeout_minutes=45,
    ),
    Gate(
        "reporting",
        6,
        ("uv", "run", "pytest", "tests/acceptance/reporting", "-q", "-x", "-n", "0"),
        legacy=True,
        timeout_minutes=30,
    ),
    Gate(
        "coverage_report",
        7,
        ("uv", "run", "python", "scripts/coverage_report.py", "--out", "{baseline}/coverage.json"),
        legacy=False,
        timeout_minutes=15,
    ),
    Gate(
        "impact_report",
        8,
        (
            "uv",
            "run",
            "python",
            "scripts/impact_report.py",
            "compare",
            "--baseline",
            "{baseline}/impact",
        ),
        legacy=False,
        timeout_minutes=45,
        baseline_cmd=(
            "uv",
            "run",
            "python",
            "scripts/impact_report.py",
            "capture",
            "--out",
            "{baseline}/impact",
        ),
    ),
)


def ladder_for(name: str) -> tuple[Gate, ...]:
    """``legacy`` = the gates that predate this project; ``full`` = all of them."""
    if name == "full":
        return LADDER
    if name == "legacy":
        return tuple(gate for gate in LADDER if gate.legacy)
    if name == "fast":
        return tuple(gate for gate in LADDER if gate.tier <= 2)
    raise SystemExit(f"unknown ladder {name!r}; choose legacy, full or fast")


# =============================================================================
# Safety: apply and restore
# =============================================================================


class DirtyTree(SystemExit):
    """Refuse to mutate a file that already has uncommitted work in it."""


def assert_targets_clean() -> None:
    """Refuse to start unless every catalogue target is committed and clean.

    With this guaranteed, crash recovery is ``git checkout -- <file>`` and the
    worst case is a lost campaign, never lost work.
    """
    proc = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty = {
        line[3:].strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()
    }
    conflicts = sorted(dirty & targets())
    if conflicts:
        raise DirtyTree(
            "refusing to run: these mutation targets have uncommitted changes, "
            "and injecting into them would put your work at risk.\n  "
            + "\n  ".join(conflicts)
            + "\nCommit or stash them first."
        )


@contextmanager
def injected(mutant: Mutant) -> Iterator[None]:
    """Apply one mutant, guaranteeing restoration.

    Three independent guarantees, because a half-restored ``src/`` is the worst
    thing this script could leave behind: ``finally``, an ``atexit`` hook armed
    for the duration, and a byte-comparison after restoring.
    """
    path = _REPO_ROOT / mutant.target
    if mutant.target not in targets():
        raise SystemExit(f"{mutant.id}: {mutant.target} is not a declared target")

    original = path.read_text(encoding="utf-8")
    occurrences = original.count(mutant.old)
    if occurrences != 1:
        raise SystemExit(
            f"{mutant.id}: its 'old' string occurs {occurrences} times in "
            f"{mutant.target} (expected exactly 1). The code moved under the "
            f"catalogue; fix the entry rather than the source."
        )

    def _restore() -> None:
        if path.read_text(encoding="utf-8") != original:
            path.write_text(original, encoding="utf-8")

    atexit.register(_restore)
    try:
        path.write_text(original.replace(mutant.old, mutant.new), encoding="utf-8")
        yield
    finally:
        _restore()
        atexit.unregister(_restore)
        if path.read_text(encoding="utf-8") != original:
            raise SystemExit(
                f"{mutant.id}: FAILED TO RESTORE {mutant.target}. "
                f"Run: git checkout -- {mutant.target}"
            )


# =============================================================================
# Reachability
# =============================================================================


def output_digest() -> str:
    """A stable digest of what the estate produces, engine and reporting alike.

    Runs one portfolio through both regimes and hashes every generated template
    cell. Two regimes because a Basel-3.1-only mutant moves nothing under CRR,
    and the whole point is to avoid mistaking "wrong regime" for "dead path".

    Imported lazily and re-imported per call: the mutants edit modules that are
    already loaded, so a cached import would measure the pre-mutation code.
    """
    for name in [key for key in sys.modules if key.startswith(("rwa_calc", "tests."))]:
        del sys.modules[name]

    from tests.acceptance.reporting.test_supervisory_validations import RUNS

    from rwa_calc.engine.pipeline import PipelineOrchestrator
    from rwa_calc.reporting.corep.generator import COREPGenerator
    from rwa_calc.reporting.pillar3.generator import Pillar3Generator
    from rwa_calc.reporting.validations.scope import build_template_index

    digest = hashlib.sha256()
    for run in RUNS:
        if run.portfolio != "rich":
            continue
        result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
        corep = COREPGenerator().generate_from_lazyframe(result.results, framework=run.framework)
        pillar3 = Pillar3Generator().generate_from_lazyframe(
            result.results, framework=run.framework
        )
        index = build_template_index(corep, pillar3, run.framework)
        for attribute in sorted(index.frames):
            for sheet in sorted(index.frames[attribute]):
                frame = index.frames[attribute][sheet]
                digest.update(f"{run.regime}/{attribute}/{sheet}".encode())
                for column in sorted(frame.columns):
                    digest.update(str(frame.get_column(column).to_list()).encode())
    return digest.hexdigest()


def probe_reachable(mutant: Mutant, baseline: str) -> tuple[bool, str, float]:
    """Does this mutant move any output at all? Returns (reachable, digest, secs)."""
    started = time.perf_counter()
    with injected(mutant):
        digest = output_digest()
    return digest != baseline, digest, round(time.perf_counter() - started, 1)


# =============================================================================
# Running the ladder
# =============================================================================


@dataclass
class GateResult:
    gate: str
    tier: int
    outcome: str
    exit_code: int | None
    seconds: float
    excerpt: str = ""


@dataclass
class MutantResult:
    mutant_id: str
    category: str
    summary: str
    verdict: str
    reachable: bool | None = None
    reachability_seconds: float = 0.0
    caught_by: str | None = None
    caught_at_tier: int | None = None
    gates: list[GateResult] = field(default_factory=list)
    note: str = ""


def run_gate(gate: Gate, baseline_dir: Path) -> GateResult:
    """One rung. A non-zero exit is a detection; a timeout is neither."""
    cmd = tuple(part.format(baseline=baseline_dir.as_posix()) for part in gate.cmd)
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=gate.timeout_minutes * 60,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            gate.name,
            gate.tier,
            OUTCOME_TIMEOUT,
            None,
            round(time.perf_counter() - started, 1),
            f"exceeded {gate.timeout_minutes} minutes",
        )
    seconds = round(time.perf_counter() - started, 1)
    outcome = OUTCOME_GREEN if proc.returncode == 0 else OUTCOME_RED
    excerpt = ""
    if outcome == OUTCOME_RED:
        tail = (proc.stdout or "") + (proc.stderr or "")
        excerpt = "\n".join(tail.strip().splitlines()[-12:])
    return GateResult(gate.name, gate.tier, outcome, proc.returncode, seconds, excerpt)


def run_campaign(
    mutants: list[Mutant],
    gates: tuple[Gate, ...],
    baseline_dir: Path,
    baseline_digest: str,
    *,
    reachability_only: bool,
) -> list[MutantResult]:
    """Probe, then ladder, one mutant at a time."""
    results: list[MutantResult] = []
    for position, mutant in enumerate(mutants, start=1):
        print(f"\n[{position}/{len(mutants)}] {mutant.id} ({mutant.category})", flush=True)
        result = MutantResult(mutant.id, mutant.category, mutant.summary, VERDICT_ERROR)

        reachable, _, seconds = probe_reachable(mutant, baseline_digest)
        result.reachable = reachable
        result.reachability_seconds = seconds
        print(f"      reachability: {'REACHABLE' if reachable else 'UNREACHABLE'} ({seconds}s)")

        if mutant.expect_unreachable and reachable:
            result.note = (
                "catalogue expected this mutant to be unreachable but it moved "
                "output; the expectation or the code has changed"
            )
        elif not mutant.expect_unreachable and not reachable:
            result.note = (
                "catalogue expected this mutant to be reachable but it moved "
                "nothing; either the probe is too narrow or the path is dead"
            )

        if not reachable:
            result.verdict = VERDICT_UNREACHABLE
            results.append(result)
            continue

        if reachability_only:
            result.verdict = "PROBED"
            results.append(result)
            continue

        with injected(mutant):
            for gate in gates:
                outcome = run_gate(gate, baseline_dir)
                result.gates.append(outcome)
                print(
                    f"      tier {gate.tier} {gate.name:<16} {outcome.outcome} ({outcome.seconds}s)"
                )
                if outcome.outcome == OUTCOME_RED:
                    result.verdict = VERDICT_DETECTED
                    result.caught_by = gate.name
                    result.caught_at_tier = gate.tier
                    break
            else:
                result.verdict = VERDICT_ESCAPED
        results.append(result)
    return results


# =============================================================================
# Self-test
# =============================================================================


def self_test() -> int:
    """Verify every mutant is applicable, applying nothing.

    Checks that each ``old`` string is present and unique, that every target is
    declared, and that applying the replacement would actually change the file.
    Cheap enough to run on every commit, and it is what stops the catalogue
    rotting silently as the code moves underneath it.
    """
    failures: list[str] = []
    for mutant in CATALOGUE:
        path = _REPO_ROOT / mutant.target
        if not path.exists():
            failures.append(f"{mutant.id}: target {mutant.target} does not exist")
            continue
        source = path.read_text(encoding="utf-8")
        occurrences = source.count(mutant.old)
        if occurrences == 0:
            failures.append(f"{mutant.id}: 'old' string not found in {mutant.target}")
        elif occurrences > 1:
            failures.append(
                f"{mutant.id}: 'old' string occurs {occurrences} times in "
                f"{mutant.target}; it must be unique"
            )
        elif source.replace(mutant.old, mutant.new) == source:
            failures.append(f"{mutant.id}: replacement is a no-op")

    ids = [mutant.id for mutant in CATALOGUE]
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    if duplicates:
        failures.append(f"duplicate mutant ids: {duplicates}")

    print(f"Self-test over {len(CATALOGUE)} mutants across {len(targets())} files")
    for failure in failures:
        print(f"  FAIL {failure}")
    if not failures:
        print("  all mutants applicable, all 'old' strings unique, nothing applied")
    return 1 if failures else 0


# =============================================================================
# Scorecard
# =============================================================================


def scorecard(results: list[MutantResult]) -> dict[str, Any]:
    """Detection rate overall and by category, plus the escape list."""
    scored = [r for r in results if r.verdict in (VERDICT_DETECTED, VERDICT_ESCAPED)]
    detected = [r for r in scored if r.verdict == VERDICT_DETECTED]
    unreachable = [r for r in results if r.verdict == VERDICT_UNREACHABLE]

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({r.category for r in results}):
        pool = [r for r in scored if r.category == category]
        hits = [r for r in pool if r.verdict == VERDICT_DETECTED]
        by_category[category] = {
            "scored": len(pool),
            "detected": len(hits),
            "rate": round(len(hits) / len(pool), 4) if pool else None,
        }

    tiers = [r.caught_at_tier for r in detected if r.caught_at_tier is not None]
    return {
        "mutants_total": len(results),
        "scored": len(scored),
        "detected": len(detected),
        "escaped": len(scored) - len(detected),
        "unreachable": len(unreachable),
        "detection_rate": round(len(detected) / len(scored), 4) if scored else None,
        "mean_tier_of_detection": round(sum(tiers) / len(tiers), 2) if tiers else None,
        "by_category": by_category,
        "escaped_list": [
            {"id": r.mutant_id, "category": r.category, "summary": r.summary}
            for r in scored
            if r.verdict == VERDICT_ESCAPED
        ],
        "unreachable_list": [
            {"id": r.mutant_id, "summary": r.summary, "note": r.note} for r in unreachable
        ],
        "expectation_mismatches": [{"id": r.mutant_id, "note": r.note} for r in results if r.note],
    }


def print_scorecard(payload: dict[str, Any]) -> None:
    board = payload["scorecard"]
    print()
    print("=" * 78)
    print("DEFECT-INJECTION SCORECARD")
    print("=" * 78)
    print(f"  ladder            {payload['ladder']}")
    print(f"  mutants           {board['mutants_total']}")
    print(f"  scored            {board['scored']}  (unreachable excluded)")
    print(f"  detected          {board['detected']}")
    print(f"  escaped           {board['escaped']}")
    print(f"  unreachable       {board['unreachable']}")
    if board["detection_rate"] is not None:
        print(f"  DETECTION RATE    {board['detection_rate']:.1%}")
    if board["mean_tier_of_detection"] is not None:
        print(f"  mean tier         {board['mean_tier_of_detection']}")

    print("\n  by category")
    for category, stats in board["by_category"].items():
        rate = "n/a" if stats["rate"] is None else f"{stats['rate']:.1%}"
        print(f"    {category:<14} {stats['detected']}/{stats['scored']}  {rate}")

    if board["escaped_list"]:
        print("\n  ESCAPED — the actual deliverable:")
        for entry in board["escaped_list"]:
            print(f"    {entry['id']:<40} {entry['summary']}")
    else:
        print("\n  no escapes")

    if board["unreachable_list"]:
        print("\n  UNREACHABLE (not counted either way):")
        for entry in board["unreachable_list"]:
            print(f"    {entry['id']:<40} {entry['summary']}")

    if board["expectation_mismatches"]:
        print("\n  EXPECTATION MISMATCHES — the probe or the catalogue is stale:")
        for entry in board["expectation_mismatches"]:
            print(f"    {entry['id']}: {entry['note']}")


# =============================================================================
# Entry point
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Defect-injection scorecard (C6)")
    parser.add_argument(
        "--self-test", action="store_true", help="verify the catalogue, apply nothing"
    )
    parser.add_argument("--reachability-only", action="store_true", help="probe, run no gates")
    parser.add_argument("--mutants", nargs="*", default=None, help="mutant ids to run")
    parser.add_argument("--categories", nargs="*", default=None, help="categories to run")
    parser.add_argument("--ladder", default="legacy", help="legacy | full | fast")
    parser.add_argument(
        "--timeout", type=float, default=None, help="override every gate timeout, minutes"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--resume", action="store_true", help="skip mutants already in --out")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    assert_targets_clean()

    mutants = select(args.mutants, args.categories)
    if args.resume and args.out.exists():
        done = {
            entry["mutant_id"]
            for entry in json.loads(args.out.read_text(encoding="utf-8")).get("results", [])
        }
        mutants = [mutant for mutant in mutants if mutant.id not in done]
        print(f"resuming: {len(done)} already scored, {len(mutants)} to go")

    gates = ladder_for(args.ladder)
    if args.timeout is not None:
        gates = tuple(
            Gate(g.name, g.tier, g.cmd, g.legacy, args.timeout, g.baseline_cmd) for g in gates
        )

    baseline_dir = _REPO_ROOT / ".claude" / "state" / "defect-injection"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    print("Capturing the unmutated baseline digest ...", flush=True)
    baseline_digest = output_digest()
    print(f"  baseline {baseline_digest[:16]}")

    if not args.reachability_only:
        for gate in gates:
            if gate.baseline_cmd is None:
                continue
            print(f"Preparing baseline for {gate.name} ...", flush=True)
            subprocess.run(
                tuple(p.format(baseline=baseline_dir.as_posix()) for p in gate.baseline_cmd),
                cwd=_REPO_ROOT,
                check=False,
            )

    results = run_campaign(
        mutants,
        gates,
        baseline_dir,
        baseline_digest,
        reachability_only=args.reachability_only,
    )

    payload = {
        "ladder": args.ladder,
        "gates": [g.name for g in gates],
        "runtime_seconds": round(time.perf_counter() - started, 1),
        "baseline_digest": baseline_digest,
        "scorecard": scorecard(results),
        "results": [asdict(result) for result in results],
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_scorecard(payload)
    print(f"\nWrote {args.out.name} in {payload['runtime_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
