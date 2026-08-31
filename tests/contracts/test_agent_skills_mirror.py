"""
Agent-skills mirror gate.

`.claude/skills/` is canonical and Claude-specific. `.agents/skills/` is a
committed, byte-for-byte mirror of it, because OpenAI Codex CLI discovers
project skills only from `<repo>/.codex/skills` and `<repo>/.agents/skills` —
without the mirror it runs against this repo with no regulatory skills at all,
and a silently-absent skill is indistinguishable from a skill that had nothing
to say.

The gates here:

- the committed mirror matches a fresh sync (`--check` exits 0);
- every source file has a byte-identical counterpart, asserted directly rather
  than only through the script, so the test cannot pass by sharing a bug with
  the thing it checks;
- the mirror holds nothing the source does not, so a deleted or renamed skill
  cannot linger;
- and `--check` can actually *fail* — the drift detector is exercised against a
  synthetic tree for each of its three drift kinds, so it is not a gate that is
  green in both states (`.claude/LESSONS.md` C1.11).

References:
- scripts/sync_agent_skills.py — the generator this pins
- .agents/README.md — why a copy rather than a symlink
- CLAUDE.md "The learning loop" — a mirror with no freshness gate is drift
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Imported as well as driven through the CLI: the drift kinds below are about
# the comparison itself, which the CLI only ever reports the verdict of.
from sync_agent_skills import (  # noqa: E402
    MIRROR_ROOT,
    SOURCE_ROOT,
    _inside_mirror,
    diff_mirror,
    main,
    sync_mirror,
)


def _run_sync(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sync_agent_skills.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _relative_files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def test_committed_mirror_matches_a_fresh_sync() -> None:
    """The mirror is generated, so the committed copy must equal a fresh render."""
    # Arrange / Act
    result = _run_sync("--check")

    # Assert
    assert result.returncode == 0, (
        ".agents/skills has drifted from .claude/skills. The mirror is what "
        "non-Claude agents read, so drift silently hands them stale skills. "
        "Regenerate (never hand-edit the mirror):\n"
        "  uv run python scripts/sync_agent_skills.py\n"
        f"{result.stderr}"
    )


def test_every_source_skill_has_a_byte_identical_counterpart() -> None:
    """Byte-identity is the contract that makes the mirror inherit the skill gates."""
    # Arrange
    sources = sorted(_relative_files(SOURCE_ROOT))
    assert sources, f"no skill files under {SOURCE_ROOT} — the mirror gate would be vacuous"

    # Act
    absent = [rel for rel in sources if not (MIRROR_ROOT / rel).is_file()]
    differing = [
        rel
        for rel in sources
        if (MIRROR_ROOT / rel).is_file()
        and (MIRROR_ROOT / rel).read_bytes() != (SOURCE_ROOT / rel).read_bytes()
    ]

    # Assert
    assert not absent, (
        "a .claude/skills file has no .agents/skills counterpart, so Codex cannot "
        f"see it: {[p.as_posix() for p in absent]}"
    )
    assert not differing, (
        "a mirrored file differs from its source. scripts/check_skill_values.py and "
        "scripts/generate_regulatory_tables.py only read .claude/skills, so the "
        "mirror inherits their guarantees only while it is byte-identical: "
        f"{[p.as_posix() for p in differing]}"
    )


def test_mirror_holds_no_file_absent_from_the_source() -> None:
    """A deleted or renamed skill must not linger in the mirror."""
    # Arrange / Act
    extra = sorted(_relative_files(MIRROR_ROOT) - _relative_files(SOURCE_ROOT))

    # Assert
    assert not extra, (
        "a file exists under .agents/skills with no .claude/skills source. A stale "
        "mirrored skill is worse than a missing one — it reads as current: "
        f"{[p.as_posix() for p in extra]}"
    )


@pytest.mark.parametrize(
    ("perturb", "expected_kind", "expected_line"),
    [
        (
            lambda mirror: (mirror / "a" / "one.md").write_bytes(b"tampered"),
            "differing",
            "differs from source:  a/one.md",
        ),
        (
            lambda mirror: (mirror / "a" / "one.md").unlink(),
            "missing",
            "missing from mirror:  a/one.md",
        ),
        (
            lambda mirror: (mirror / "a" / "stale.md").write_bytes(b"orphan"),
            "extra",
            "extra in mirror:      a/stale.md",
        ),
    ],
    ids=["differing", "missing", "extra"],
)
def test_drift_detector_reports_each_drift_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    perturb: Callable[[Path], object],
    expected_kind: str,
    expected_line: str,
) -> None:
    """A gate green in both states guards nothing — prove each kind reddens.

    Run against a synthetic tree rather than the real one: the repo is shared
    with other agents, so a test that perturbs `.agents/skills/` in place would
    hand whoever else is running a mirror that is briefly, invisibly wrong.
    """
    # Arrange
    _source, mirror = _synthetic_pair(tmp_path, monkeypatch)
    assert diff_mirror().is_clean, "the synthetic pair started drifted"
    perturb(mirror)

    # Act
    drift = diff_mirror()

    # Assert
    assert not drift.is_clean, f"{expected_kind} drift went undetected"
    assert [p.as_posix() for p in getattr(drift, expected_kind)], (
        f"drift was detected but not as {expected_kind}: {drift}"
    )
    assert expected_line in drift.report(), (
        "the report must name the drifted file and what is wrong with it, or the "
        f"failure is not actionable: {drift.report()}"
    )


def test_sync_restores_the_mirror_and_prunes_what_the_source_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writing is idempotent, and pruning is what stops a renamed skill lingering."""
    # Arrange
    _source, mirror = _synthetic_pair(tmp_path, monkeypatch)
    (mirror / "a" / "one.md").write_bytes(b"tampered")
    (mirror / "a" / "stale.md").write_bytes(b"orphan")
    (mirror / "gone").mkdir()
    (mirror / "gone" / "old.md").write_bytes(b"renamed away")

    # Act
    sync_mirror(diff_mirror())

    # Assert
    assert diff_mirror().is_clean, "sync left the mirror drifted"
    assert not (mirror / "a" / "stale.md").exists(), "an orphaned file survived the prune"
    assert not (mirror / "gone").exists(), "an emptied directory survived the prune"
    assert (mirror / "a" / "one.md").read_bytes() == (_source / "a" / "one.md").read_bytes()

    # Act again — a second sync must be a no-op.
    sync_mirror(diff_mirror())
    assert diff_mirror().is_clean, "sync is not idempotent"


def test_sync_refuses_to_delete_outside_the_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.agents/README.md` and every future sibling must be out of the prune's reach."""
    # Arrange
    _synthetic_pair(tmp_path, monkeypatch)
    sibling = tmp_path / "agents" / "README.md"

    # Act / Assert
    with pytest.raises(ValueError, match="outside"):
        _inside_mirror(sibling)


@pytest.mark.parametrize(
    ("break_source", "expected_message"),
    [
        (shutil.rmtree, "does not exist"),
        (lambda source: (source / "a" / "SKILL.md").unlink(), "SKILL.md"),
    ],
    ids=["absent", "no-skill-md"],
)
def test_sync_refuses_to_empty_the_mirror_when_the_source_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_source: Callable[[Path], object],
    expected_message: str,
) -> None:
    """An absent source is not an instruction to delete every skill.

    Without a guard, `_relative_files` returns nothing, every mirrored file
    becomes `extra`, and a plain write run prunes the whole mirror and exits 0 —
    Codex silently loses every skill, which is the failure mode this whole
    change exists to prevent. `--check` happens to fail closed here; the write
    path is the one that matters, so this asserts the files are still there
    afterwards rather than only that something was raised.
    """
    # Arrange
    source, mirror = _synthetic_pair(tmp_path, monkeypatch)
    before = sorted(p.relative_to(mirror) for p in mirror.rglob("*") if p.is_file())
    assert before, "the synthetic mirror is empty, so this test could not detect a prune"
    break_source(source)

    # Act / Assert
    with pytest.raises(ValueError, match=expected_message):
        sync_mirror(diff_mirror())

    after = sorted(p.relative_to(mirror) for p in mirror.rglob("*") if p.is_file())
    assert after == before, (
        "the mirror was pruned against a source that is not a skills tree: "
        f"{[p.as_posix() for p in sorted(set(before) - set(after))]} deleted"
    )


@pytest.mark.parametrize("argv", [[], ["--check"]], ids=["write", "check"])
@pytest.mark.parametrize(
    "break_source",
    [shutil.rmtree, lambda source: shutil.rmtree(source / "a")],
    ids=["absent", "emptied"],
)
def test_cli_exits_non_zero_and_names_the_path_when_the_source_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    break_source: Callable[[Path], object],
    argv: list[str],
) -> None:
    """Both modes refuse explicitly, and the message says which path is at fault.

    `emptied` is the case that was live: the root survives a renamed subtree, so
    the absent-directory check never fired and a write run reported
    `mirrored 0 file(s) ... 2 removed` at exit 0.
    """
    # Arrange
    source, mirror = _synthetic_pair(tmp_path, monkeypatch)
    before = sorted(p.relative_to(mirror) for p in mirror.rglob("*") if p.is_file())
    break_source(source)

    # Act
    exit_code = main(argv)

    # Assert
    stderr = capsys.readouterr().err
    assert exit_code != 0, f"a broken source root exited {exit_code} for argv={argv}"
    assert str(source) in stderr, f"the refusal must name the path at fault:\n{stderr}"
    after = sorted(p.relative_to(mirror) for p in mirror.rglob("*") if p.is_file())
    assert after == before, "the CLI pruned the mirror instead of refusing to run"


def _synthetic_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A two-file source tree with an in-sync mirror, wired into the script's roots.

    Content is written as bytes with a CRLF in it deliberately: the mirror must
    survive on Windows without a newline translation quietly making every file
    differ from its source. The `SKILL.md` mirrors the real tree's shape and is
    what the source-root guard keys on.
    """
    source = tmp_path / "claude" / "skills"
    mirror = tmp_path / "agents" / "skills"
    (source / "a").mkdir(parents=True)
    (source / "a" / "SKILL.md").write_bytes(b"# skill\n")
    (source / "a" / "one.md").write_bytes(b"# one\r\nbody\n")
    (source / "two.md").write_bytes(b"# two\n")

    monkeypatch.setattr("sync_agent_skills.SOURCE_ROOT", source)
    monkeypatch.setattr("sync_agent_skills.MIRROR_ROOT", mirror)
    sync_mirror(diff_mirror())
    return source, mirror
