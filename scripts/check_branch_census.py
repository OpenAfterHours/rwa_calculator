"""
Branch census — which regulatory limbs does the fixture estate actually reach?

Pipeline position:
    (not a pipeline stage) — a gate. Run by
    ``tests/contracts/test_branch_census_ratchet.py`` against the committed
    baseline, and available standalone:

        uv run python scripts/check_branch_census.py            # the histogram
        uv run python scripts/check_branch_census.py --check    # the gate
        uv run python scripts/check_branch_census.py --update-baseline

Key responsibilities:
- Run the whole portfolio x regime matrix and count, per ``*_branch_reason``
  column, how many rows took each limb.
- Ratchet the REACHED ``(column, reason)`` set so coverage cannot fall.
- Ratchet the DEAD set — limbs the entire estate reaches with zero rows — so a
  new one cannot appear unnoticed.

The two registers, and why they ratchet in opposite directions
--------------------------------------------------------------
Both go through the one shared set-diff in ``scripts/tolerated_findings.py``,
and both key on ``<column>::<reason>``. They are mirror images:

- **reached** is a COVERAGE population, like
  ``scripts/check_input_domains.py``'s declared domains. A limb some portfolio
  used to exercise and no longer does is coverage going backwards, so a
  REMOVAL is a hard failure and ``--update-baseline`` refuses to make one.
  Additions are the outcome we want and must still be banked, because banking
  is what makes the next removal visible.

- **dead** is a TOLERATED-FINDINGS population, like the parked registers. A
  declared limb no row reaches is either dead code or an untested path — the
  proposal's words — and both are findings. So an ADDITION is a hard failure
  and removals are free: a limb that becomes live is the outcome the register
  exists to provoke, and a gate that reddens on a fix teaches people to stop
  fixing.

Ratchet the accumulator, never a ratio (`.claude/LESSONS.md` B8). Neither
register is a count: "42 limbs reached" is satisfiable by gaining an easy limb
while losing a hard one, and the whole point is that a *named* limb went quiet.
Nor is ``dead`` merely the complement of ``reached`` — the declared population
moves too, so a vocabulary member added and never reached shows up in ``dead``
while leaving ``reached`` untouched. Gating only the accumulator would miss it,
which is why both are gated.

Where the declared population comes from
----------------------------------------
Off the frame's own ``pl.Enum`` dtype, not from a list in this file. A limb
nobody reached leaves no value in the data, so a ``String`` column could not
report one at all; the Enum carries its categories in the dtype, so the
declared set is readable even when the reached set is empty. That also anchors
the census to something that cannot drift with the code under test
(`.claude/LESSONS.md` B3).

Failing loudly is load-bearing
------------------------------
A portfolio that raises produces no rows, and a census that skipped it would
record every limb that portfolio feeds as DEAD — turning a broken run into a
wall of false findings, or (worse, after ``--update-baseline``) into a quietly
banked one. So a raising run is a hard exit, and the run count is asserted
against ``EXPECTED_RUNS`` rather than inferred. Same discipline as
``scripts/check_template_cell_coverage.py``, from which this borrows its
matrix outright rather than declaring a second one.

Exit codes:
    0 = census printed, or --check passed
    1 = --check found a regression, an unbanked change, or a failed run

References:
- docs/plans/test-space-correctness-proposal.md — Phase 3
- rwa_calc.domain.branch_reasons — the vocabularies being counted
- scripts/tolerated_findings.py — the shared set-diff
- scripts/check_input_domains.py — the coverage-direction ratchet this mirrors
- .claude/LESSONS.md B3, B8
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import polars as pl  # noqa: E402
from check_template_cell_coverage import EXPECTED_RUNS, run_specs  # noqa: E402
from tolerated_findings import diff  # noqa: E402

from rwa_calc.domain.branch_reasons import (  # noqa: E402
    BRANCH_REASON_VOCABULARIES,
    UNKNOWN_FALLBACK,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402

if TYPE_CHECKING:
    from check_template_cell_coverage import RunSpec

BASELINE_PATH = REPO_ROOT / "scripts" / "branch_census_baseline.json"

_BASELINE_COMMENT = (
    "Branch census ratchet (scripts/check_branch_census.py --check). Ids are "
    "<column>::<reason>. `reached` is a COVERAGE population: REMOVALS ARE A "
    "HARD FAILURE and --update-baseline refuses to make one, because a limb "
    "the estate stops exercising is coverage going backwards. `dead` is a "
    "TOLERATED-FINDINGS population: ADDITIONS ARE A HARD FAILURE and must be "
    "hand-edited into this file, because a declared limb no row reaches is "
    "either dead code or an untested path. "
    "docs/plans/test-space-correctness-proposal.md Phase 3."
)


class Census(NamedTuple):
    """What the whole matrix reached, and what it never did."""

    #: ``<column>::<reason>`` for every limb declared by a vocabulary.
    declared: frozenset[str]
    #: Limbs at least one row of at least one run took. The accumulator.
    reached: frozenset[str]
    #: Row counts per limb, summed across runs — reported, never gated.
    counts: dict[str, int]
    #: Rows carrying a non-null reason, per column. Denominator for the report.
    totals: dict[str, int]
    runs: int

    @property
    def dead(self) -> frozenset[str]:
        """Declared limbs no row reached — the finding."""
        return self.declared - self.reached


def census(limit: int | None = None) -> Census:
    """Run the matrix and accumulate which limbs the estate reaches.

    Raises:
        SystemExit: a run raised, or the matrix was short. Either makes limbs
            look dead that are not, so neither may be absorbed.
    """
    specs = run_specs()[:limit] if limit else run_specs()
    declared = {
        f"{column}::{member.value}"
        for column, vocabulary in BRANCH_REASON_VOCABULARIES.items()
        for member in vocabulary
    }
    reached: set[str] = set()
    counts: dict[str, int] = dict.fromkeys(declared, 0)
    totals: dict[str, int] = dict.fromkeys(BRANCH_REASON_VOCABULARIES, 0)

    for index, spec in enumerate(specs, start=1):
        sys.stderr.write(f"  [{index}/{len(specs)}] {spec.describe()} ...\n")
        try:
            frame = _results(spec)
        except Exception as exc:  # noqa: BLE001 — a broken run must not be absorbed
            sys.stderr.write(
                f"\nFAILED: {spec.describe()} raised {type(exc).__name__}: {exc}\n"
                "A run that produces no rows makes every limb it feeds look dead, "
                "so this is a hard error rather than a skip.\n"
            )
            raise SystemExit(1) from exc

        for column in BRANCH_REASON_VOCABULARIES:
            if column not in frame.columns:
                continue
            series = frame[column]
            totals[column] += int(series.is_not_null().sum())
            for row in series.value_counts().iter_rows(named=True):
                reason = row[column]
                if reason is None:
                    continue
                key = f"{column}::{reason}"
                counts[key] = counts.get(key, 0) + row["count"]
                if row["count"]:
                    reached.add(key)
        del frame
        gc.collect()

    if limit is None and len(specs) != EXPECTED_RUNS:
        sys.stderr.write(
            f"\nFAILED: matrix ran {len(specs)} of {EXPECTED_RUNS} expected runs.\n"
            "A short matrix records every limb its missing portfolios feed as dead.\n"
        )
        raise SystemExit(1)

    return Census(frozenset(declared), frozenset(reached), counts, totals, len(specs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run-level branch census over the portfolio estate, with a two-way ratchet."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="ratchet against the baseline")
    mode.add_argument("--update-baseline", action="store_true", help="bank the current census")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N runs")
    args = parser.parse_args(argv)

    result = census(limit=args.limit)

    if args.update_baseline:
        return _update_baseline(result)
    if args.check:
        return _check(result)

    _report(result)
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _results(spec: RunSpec) -> pl.DataFrame:
    """The collected results frame for one run, reason columns only.

    Projects to the instrumented columns before collecting: the census needs
    three narrow columns out of ~300, and materialising the rest would make the
    gate cost what a full reporting run costs for no added signal.
    """
    config = spec.build_config()
    outcome = PipelineOrchestrator().run_with_data(spec.build_bundle(), config)
    present = [
        c for c in BRANCH_REASON_VOCABULARIES if c in outcome.results.collect_schema().names()
    ]
    return outcome.results.select(present).collect() if present else pl.DataFrame()


def _report(result: Census) -> None:
    for column, vocabulary in BRANCH_REASON_VOCABULARIES.items():
        total = result.totals.get(column, 0)
        sys.stdout.write(f"\n{column}  ({total:,} rows carry a reason)\n")
        for member in vocabulary:
            key = f"{column}::{member.value}"
            count = result.counts.get(key, 0)
            share = f"{count / total:>7.2%}" if total else "      -"
            flag = "" if count else "   <-- DEAD: no row in the estate reaches this limb"
            sys.stdout.write(f"  {member.value:<28} {count:>10,}  {share}{flag}\n")
    sys.stderr.write(
        f"\n{result.runs} runs | {len(result.reached)} of {len(result.declared)} "
        f"declared limbs reached | {len(result.dead)} dead\n"
    )


def _load_baseline() -> tuple[list[str], dict[str, str]]:
    """The banked reached ids, and the banked dead ids mapped to their reasons."""
    if not BASELINE_PATH.exists():
        return [], {}
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    dead = {entry["id"]: entry["reason"] for entry in payload["dead"]}
    return list(payload["reached"]), dead


def _write_baseline(result: Census, dead_reasons: dict[str, str]) -> None:
    """Bank the census, carrying every dead entry's written reason forward.

    A dead branch keeps its reason across re-banks. A dead branch with no
    reason is an unreviewable number — the same argument
    ``template_cell_coverage_baseline.json`` makes for its ``reason_code`` —
    so ``--update-baseline`` cannot mint one, and a new dead branch is a hand
    edit that has to say why in the diff.
    """
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": _BASELINE_COMMENT,
                "runs": result.runs,
                "reached_count": len(result.reached),
                "reached": sorted(result.reached),
                "dead_count": len(result.dead),
                "dead": [
                    {"id": dead_id, "reason": dead_reasons[dead_id]}
                    for dead_id in sorted(result.dead)
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _update_baseline(result: Census) -> int:
    banked_reached, banked_dead = _load_baseline()
    lost = diff(result.reached, banked_reached).removed
    if lost:
        sys.stderr.write(
            "REFUSED: --update-baseline will not drop a reached branch.\n"
            + "".join(f"  gone: {i}\n" for i in lost)
            + "A limb the estate stops exercising is coverage going backwards. "
            "Restore the coverage, or hand-edit the baseline so the loss is a "
            "reviewable diff in its own right.\n"
        )
        return 1
    new_dead = diff(result.dead, banked_dead).added
    if new_dead:
        sys.stderr.write(
            "REFUSED: --update-baseline will not bank a NEW dead branch.\n"
            + "".join(f"  dead: {i}\n" for i in new_dead)
            + "A declared limb no row reaches is either dead code or an untested "
            "path. Give it a fixture, delete it, or hand-edit the baseline with "
            "the reason it is tolerated.\n"
        )
        return 1
    _write_baseline(result, banked_dead)
    sys.stderr.write(f"baseline banked: {len(result.reached)} reached, {len(result.dead)} dead\n")
    return 0


def _check(result: Census) -> int:
    banked_reached, banked_dead = _load_baseline()
    failed = False

    moved = diff(result.reached, banked_reached)
    if moved.removed:
        sys.stderr.write(
            f"REGRESSION: {len(moved.removed)} branch(es) the estate no longer reaches.\n"
            + "".join(f"  gone: {i}\n" for i in moved.removed)
            + "A limb that goes quiet is either a fixture that stopped exercising "
            "it or a predicate that stopped firing. Both are findings — do not "
            "clear this by re-banking.\n\n"
        )
        failed = True
    if moved.added:
        sys.stderr.write(
            f"UNBANKED: {len(moved.added)} newly reached branch(es). Bank them:\n"
            + "".join(f"  new: {i}\n" for i in moved.added)
            + "  uv run python scripts/check_branch_census.py --update-baseline\n\n"
        )
        failed = True

    dead_moved = diff(result.dead, banked_dead)
    if dead_moved.added:
        sys.stderr.write(
            f"DEAD BRANCH: {len(dead_moved.added)} declared limb(s) no row reaches.\n"
            + "".join(f"  dead: {i}\n" for i in dead_moved.added)
            + "Either the limb is unreachable (delete it) or no fixture exercises "
            "it (build one). Both are findings; banking is a hand edit.\n\n"
        )
        failed = True
    if dead_moved.removed:
        # A limb leaving the dead set is normally the outcome we want. It is
        # NOT when the limb is UNKNOWN_FALLBACK: rows newly landing there are
        # rows the engine newly cannot justify, and reading that as an
        # improvement is the ratchet-direction mistake `.claude/LESSONS.md` B8
        # is about. Both cases still fail — the difference is what to do next.
        newly_unjustified = [i for i in dead_moved.removed if i.endswith(f"::{UNKNOWN_FALLBACK}")]
        newly_live = [i for i in dead_moved.removed if i not in set(newly_unjustified)]
        if newly_unjustified:
            sys.stderr.write(
                f"UNJUSTIFIED: {len(newly_unjustified)} branch(es) started taking "
                "UNKNOWN_FALLBACK rows.\n"
                + "".join(f"  now live: {i}\n" for i in newly_unjustified)
                + "Rows are being priced on a predicate the engine could not evaluate, "
                "or on a value substituted for absent input. This is a LOSS, not an "
                "improvement — find the rows (they carry BR001) before banking.\n\n"
            )
        if newly_live:
            sys.stderr.write(
                f"IMPROVED: {len(newly_live)} branch(es) are no longer dead. Bank them:\n"
                + "".join(f"  live: {i}\n" for i in newly_live)
                + "  uv run python scripts/check_branch_census.py --update-baseline\n\n"
            )
        failed = True

    if failed:
        return 1
    sys.stderr.write(
        f"[OK] {len(result.reached)} reached / {len(result.dead)} dead == baseline "
        f"over {result.runs} runs\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
