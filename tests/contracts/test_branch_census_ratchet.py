"""
Branch-census gates (Phase 3): a fast integrity test and a slow ratchet.

Mirrors ``tests/contracts/test_template_cell_coverage.py`` deliberately, because
the failure mode is the same one: a census that measures something real, banked
into a baseline nobody re-measures, is prose with extra steps.

- The INTEGRITY test runs in the dev loop, performs no pipeline run, and still
  catches the cheap failure (a limb renamed or deleted out from under the
  baseline) and the expensive one (a dead branch banked with no reason anybody
  can review).
- The RATCHET test re-runs the whole 28-run matrix (~45s) and is marked
  ``slow``, so it is excluded from the dev loop and needs its own CI job.

References:
- scripts/check_branch_census.py — the census and its two ratchets
- scripts/branch_census_baseline.json — the banked population
- docs/plans/test-space-correctness-proposal.md — Phase 3
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from rwa_calc.domain.branch_reasons import BRANCH_REASON_VOCABULARIES, UNKNOWN_FALLBACK

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_branch_census.py"
BASELINE_PATH = REPO_ROOT / "scripts" / "branch_census_baseline.json"

REGENERATE = "  uv run python scripts/check_branch_census.py --update-baseline"


def _baseline() -> dict[str, Any]:
    assert BASELINE_PATH.exists(), f"No branch-census baseline at {BASELINE_PATH}.\n{REGENERATE}"
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _declared_ids() -> set[str]:
    """Every ``<column>::<reason>`` the registry declares, from the vocabularies."""
    return {
        f"{column}::{member.value}"
        for column, vocabulary in BRANCH_REASON_VOCABULARIES.items()
        for member in vocabulary
    }


class TestBaselineIntegrity:
    """Cheap checks that need no pipeline run — these belong in the dev loop."""

    def test_baseline_partitions_the_declared_limbs_exactly(self) -> None:
        """Every declared limb is banked exactly once, as reached or as dead.

        A limb in neither list is one the ratchet is silently not guarding; a
        limb in both is a baseline that cannot be reasoned about. Both are
        invisible without this check, because the ratchet only ever diffs the
        two lists against a fresh census — never against the vocabulary.

        Arrange: the committed baseline and the registry.
        Act:     partition the banked ids.
        Assert:  reached and dead are disjoint and jointly exhaust declared.
        """
        # Arrange
        payload = _baseline()
        reached = set(payload["reached"])
        dead = {entry["id"] for entry in payload["dead"]}
        declared = _declared_ids()

        # Act
        overlap = sorted(reached & dead)
        unbanked = sorted(declared - (reached | dead))
        orphaned = sorted((reached | dead) - declared)

        # Assert
        assert not overlap, f"limb(s) banked as both reached and dead: {overlap}\n{REGENERATE}"
        assert not unbanked, (
            f"{len(unbanked)} declared limb(s) appear in neither list, so the ratchet "
            f"guards nothing for them: {unbanked}\n{REGENERATE}"
        )
        assert not orphaned, (
            f"{len(orphaned)} banked limb(s) no longer exist in any vocabulary — they "
            "were renamed or deleted, so the ratchet has been guarding a ghost: "
            f"{orphaned}\n{REGENERATE}"
        )

    def test_counts_foot_to_the_lists(self) -> None:
        """A count that disagrees with its list means the baseline was hand-edited badly.

        Arrange: the committed baseline.
        Act:     compare the recorded counts against the list lengths.
        Assert:  both foot, and no id is duplicated.
        """
        payload = _baseline()
        reached: list[str] = payload["reached"]
        dead_ids = [entry["id"] for entry in payload["dead"]]

        assert len(set(reached)) == len(reached), "duplicate id in reached"
        assert len(set(dead_ids)) == len(dead_ids), "duplicate id in dead"
        assert payload["reached_count"] == len(reached), f"reached_count is stale\n{REGENERATE}"
        assert payload["dead_count"] == len(dead_ids), f"dead_count is stale\n{REGENERATE}"

    def test_every_dead_branch_carries_a_reviewable_reason(self) -> None:
        """A dead limb with no written reason is an unreviewable number.

        This is the check that stops the register becoming a resting place
        (`.claude/LESSONS.md` B7): a tolerated finding must say why it is
        tolerated and who owns it, or it has only aged.

        Arrange: the committed baseline's dead entries.
        Act:     read each reason.
        Assert:  every one is non-empty and names an owning plan bullet.
        """
        # Arrange
        dead: list[dict[str, str]] = _baseline()["dead"]

        # Act
        unreasoned = [e["id"] for e in dead if not str(e.get("reason", "")).strip()]
        unowned = [e["id"] for e in dead if "OWNER:" not in str(e.get("reason", ""))]

        # Assert
        assert not unreasoned, (
            f"{len(unreasoned)} dead branch(es) carry no reason. Say whether the limb "
            "is unreachable (delete it) or untested (owe it a fixture):\n  "
            + "\n  ".join(unreasoned)
        )
        assert not unowned, (
            f"{len(unowned)} dead branch(es) name no owning plan bullet. Add "
            "`OWNER: P<tier>.<n>`:\n  " + "\n  ".join(unowned)
        )

    def test_the_unknown_fallback_limb_is_banked_for_every_instrumented_column(self) -> None:
        """The limb the whole phase exists for must be under the ratchet.

        If an ``UNKNOWN_FALLBACK`` id were missing from both lists, rows could
        start landing on it with nothing failing — which is the silence Phase 3
        was built to end.

        Arrange: the baseline and the registry.
        Act:     collect the banked ids.
        Assert:  each column's UNKNOWN_FALLBACK id is banked.
        """
        payload = _baseline()
        banked = set(payload["reached"]) | {entry["id"] for entry in payload["dead"]}
        for column in BRANCH_REASON_VOCABULARIES:
            key = f"{column}::{UNKNOWN_FALLBACK}"
            assert key in banked, f"{key} is not under the ratchet\n{REGENERATE}"


@pytest.mark.slow
def test_branch_census_matches_the_committed_baseline() -> None:
    """Re-measure the estate and fail either way.

    Excluded from the dev loop (~45s of pipeline runs) and therefore run by its
    own CI job — see ``.github/workflows/ci.yml``. A ratchet nothing runs is
    not a ratchet.

    Arrange: the census script and its baseline.
    Act:     run ``--check``.
    Assert:  exit 0, with the script's own diagnosis on failure.
    """
    # Arrange / Act
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    # Assert
    assert completed.returncode == 0, (
        "Branch census disagrees with the committed baseline.\n\n"
        f"{completed.stderr}\n{completed.stdout}"
    )
