"""Mirror `.claude/skills/` into `.agents/skills/` so non-Claude agents see the skills.

Purpose:
    The project's agent knowledge — the `basel31` and `crr` regulatory skills —
    lives in `.claude/skills/`. That path is Claude Code's, and only Claude
    Code's. OpenAI Codex CLI 0.151.0 is also run against this repo and does not
    read it: probed with `codex debug prompt-input`, Codex discovers project
    skills from exactly two repo-local roots, `<repo>/.codex/skills` and
    `<repo>/.agents/skills`. We standardise on `.agents/skills/` because it is
    vendor-neutral and pairs with the `AGENTS.md` convention.

Why a copy and not a symlink:
    `git config core.symlinks` is `false` in this repo, so a committed symlink
    materialises as a text file holding a path. The mirror has to be a real,
    committed copy — a fresh clone must give every agent working skills, and a
    silently-absent skill is precisely the failure mode this closes.

Why byte-for-byte, with no generated-file header:
    `.claude/skills/` stays canonical. `scripts/generate_regulatory_tables.py`
    writes pack-derived values into `<!-- BEGIN/END GENERATED -->` regions there,
    and `scripts/check_skill_values.py` bans regulatory values in the prose
    around them. Neither script looks at the mirror. Byte-identity is what makes
    the mirror inherit both guarantees instead of becoming a fourth home for a
    drifting value (see `.claude/LESSONS.md` A4 and the 2026-08-08 graduation).

Usage:
    uv run python scripts/sync_agent_skills.py            # write the mirror
    uv run python scripts/sync_agent_skills.py --check    # verify only, never write

Exit codes:
    0 = mirror matches the source (or was just written)
    1 = `--check` found drift
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / ".claude" / "skills"
MIRROR_ROOT = REPO_ROOT / ".agents" / "skills"

#: How the mirror is rebuilt, quoted into every drift report.
REGEN_COMMAND = "uv run python scripts/sync_agent_skills.py"

#: What makes a directory a skills tree rather than an empty shell. Both
#: `basel31/` and `crr/` carry one, and a Claude Code skill is not discoverable
#: without it, so its absence means the source is not what this script mirrors.
SOURCE_SENTINEL = "SKILL.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror .claude/skills into .agents/skills for non-Claude agents."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit non-zero without writing anything",
    )
    args = parser.parse_args(argv)

    problem = source_problem()
    if problem is not None:
        sys.stderr.write(f"refusing to run: {problem}\n")
        sys.stderr.write(
            "An absent or empty source is not an instruction to delete the mirror. "
            "Restore .claude/skills, or repoint SOURCE_ROOT if the tree really moved.\n"
        )
        return 1

    drift = diff_mirror()

    if args.check:
        if drift.is_clean:
            sys.stderr.write(f"{MIRROR_ROOT.name} mirror is in sync ({drift.checked} files)\n")
            return 0
        sys.stderr.write(drift.report())
        return 1

    sync_mirror(drift)
    sys.stderr.write(
        f"mirrored {drift.checked} file(s) to .agents/skills "
        f"({len(drift.missing)} added, {len(drift.differing)} updated, "
        f"{len(drift.extra)} removed)\n"
    )
    return 0


@dataclass(frozen=True)
class Drift:
    """What separates the committed mirror from a fresh sync.

    Paths are relative to their root, so the same value names a file on both
    sides. `checked` is the source population, which is what the caller wants to
    report on a clean run.
    """

    missing: tuple[Path, ...]
    differing: tuple[Path, ...]
    extra: tuple[Path, ...]
    checked: int

    @property
    def is_clean(self) -> bool:
        return not (self.missing or self.differing or self.extra)

    def report(self) -> str:
        lines = [
            ".agents/skills has drifted from .claude/skills. The mirror is generated - "
            "edit the source, never the mirror:\n",
            f"  {REGEN_COMMAND}\n\n",
        ]
        lines += [f"  missing from mirror:  {p.as_posix()}\n" for p in self.missing]
        lines += [f"  differs from source:  {p.as_posix()}\n" for p in self.differing]
        lines += [f"  extra in mirror:      {p.as_posix()}\n" for p in self.extra]
        return "".join(lines)


def source_problem() -> str | None:
    """Why `SOURCE_ROOT` cannot be trusted as the mirror's origin, or `None`.

    This exists because "the source has no files" and "delete every skill" are
    the same input to a naive diff: `_relative_files` returns nothing, every
    mirrored file lands in `Drift.extra`, and the write path prunes the entire
    mirror at exit 0 with no warning. Measured on a throwaway tree before this
    guard existed — a source root left standing but emptied (a renamed subtree,
    a typo in a refactor) took a 2-file mirror to 0 and reported success. Codex
    would then silently have no skills at all, which is the precise failure this
    script was written to prevent.

    The write path is the one that needed this: `--check` exited non-zero on the
    same input even before the guard, because an emptied source reads as drift.
    It is guarded anyway, because what it *printed* was twenty `extra in mirror`
    lines — a report that names the fix as "prune the mirror" when the fault is
    entirely on the source side.
    """
    if not SOURCE_ROOT.is_dir():
        return f"source skills root does not exist: {SOURCE_ROOT}"
    if not any(SOURCE_ROOT.rglob(SOURCE_SENTINEL)):
        return (
            f"source skills root holds no {SOURCE_SENTINEL}, "
            f"so it is not a skills tree: {SOURCE_ROOT}"
        )
    return None


def diff_mirror() -> Drift:
    """Compare the two trees by content, writing nothing."""
    source = _relative_files(SOURCE_ROOT)
    mirror = _relative_files(MIRROR_ROOT)

    missing = tuple(rel for rel in source if rel not in mirror)
    differing = tuple(
        rel
        for rel in source
        if rel in mirror and (SOURCE_ROOT / rel).read_bytes() != (MIRROR_ROOT / rel).read_bytes()
    )
    extra = tuple(rel for rel in mirror if rel not in source)
    return Drift(missing=missing, differing=differing, extra=extra, checked=len(source))


def sync_mirror(drift: Drift) -> None:
    """Bring the mirror to byte-identity with the source, then prune.

    Pruning is confined to `MIRROR_ROOT`: `.agents/README.md` and anything else
    a future agent puts under `.agents/` is out of scope, and `_inside_mirror`
    refuses any path that escapes it.

    The `source_problem` guard is re-checked here rather than left to `main`, so
    that an importer — or a later edit that moves the CLI check — cannot reach
    the prune with nothing to mirror from. See `source_problem` for what that
    costs when it is missed.
    """
    problem = source_problem()
    if problem is not None:
        raise ValueError(f"refusing to sync: {problem}")

    for rel in (*drift.missing, *drift.differing):
        destination = _inside_mirror(MIRROR_ROOT / rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_ROOT / rel, destination)

    for rel in drift.extra:
        _inside_mirror(MIRROR_ROOT / rel).unlink()

    _prune_empty_directories()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _relative_files(root: Path) -> list[Path]:
    """Every file under `root`, as sorted paths relative to it."""
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def _prune_empty_directories() -> None:
    """Drop directories the source no longer has. `MIRROR_ROOT` itself stays."""
    if not MIRROR_ROOT.is_dir():
        return
    for directory in sorted(
        (p for p in MIRROR_ROOT.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        if not any(directory.iterdir()):
            _inside_mirror(directory).rmdir()


def _inside_mirror(path: Path) -> Path:
    """Guard every destructive write: nothing outside `MIRROR_ROOT` is ours."""
    resolved = path.resolve()
    if resolved != MIRROR_ROOT.resolve() and not resolved.is_relative_to(MIRROR_ROOT.resolve()):
        raise ValueError(f"refusing to touch {resolved}: outside {MIRROR_ROOT}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
