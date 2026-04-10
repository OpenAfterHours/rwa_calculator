"""
Git operations for workbench workbook sharing.

Pipeline position:
    Standalone — called by server.py API endpoints for team workspace git ops.

Key responsibilities:
- Query git status for team workbook files
- Publish (copy) workbooks from local/ to team/
- Stage, commit, and push team workbook changes
- Pull latest team changes from remote
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitFileStatus:
    """Git status for a single workbook file in the team workspace."""

    name: str
    folder: str
    status: str  # "new" | "modified" | "unmodified" | "conflict"


@dataclass(frozen=True)
class GitResult:
    """Result of a git operation."""

    success: bool
    message: str
    commit_hash: str = ""


_SKIP_DIRS = frozenset({"shared", "__marimo__", "__pycache__"})


def find_repo_root(start: Path) -> Path:
    """Walk up from *start* to find the directory containing ``.git``."""
    current = start.resolve()
    for _ in range(10):
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    msg = f"No git repository found above {start}"
    raise FileNotFoundError(msg)


def _run_git(
    *args: str,
    cwd: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_status(team_dir: Path, repo_root: Path) -> list[GitFileStatus]:
    """Return git status for every ``.py`` file in *team_dir*.

    Untracked files not yet added are reported as ``"new"``.
    """
    rel_team = team_dir.resolve().relative_to(repo_root.resolve())
    result = _run_git(
        "status",
        "--porcelain",
        "--",
        str(rel_team),
        cwd=repo_root,
    )
    if result.returncode != 0:
        return []

    statuses: list[GitFileStatus] = []

    # Parse porcelain output  (XY <path>)
    tracked_paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        file_path = line[3:].strip().strip('"')
        if not file_path.endswith(".py"):
            continue

        try:
            rel = Path(file_path).relative_to(rel_team)
        except ValueError:
            continue

        parts = rel.parts
        # Skip files inside _SKIP_DIRS
        if any(p in _SKIP_DIRS for p in parts):
            continue

        name = rel.stem
        folder = str(rel.parent) if len(parts) > 1 else ""
        if folder == ".":
            folder = ""
        tracked_paths.add(str(rel))

        if "U" in xy or (xy[0] == "D" and xy[1] == "D"):
            status = "conflict"
        elif "?" in xy:
            status = "new"
        else:
            status = "modified"

        statuses.append(GitFileStatus(name=name, folder=folder, status=status))

    # Also list committed (clean) .py files not in the porcelain output
    for py_file in team_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(team_dir)
        if any(p in _SKIP_DIRS for p in rel.parts):
            continue
        if str(rel) not in tracked_paths:
            name = rel.stem
            folder = str(rel.parent) if len(rel.parts) > 1 else ""
            if folder == ".":
                folder = ""
            statuses.append(GitFileStatus(name=name, folder=folder, status="unmodified"))

    return sorted(statuses, key=lambda s: (s.folder, s.name))


def publish(source: Path, team_dir: Path) -> Path:
    """Copy a workbook from the local workspace to team workspace.

    Preserves the relative folder structure (e.g. ``local/folder/book.py``
    becomes ``team/folder/book.py``).

    Returns the destination path.
    """
    dest = team_dir / source.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def publish_changes(
    team_dir: Path,
    repo_root: Path,
    files: list[Path],
    message: str,
    remote: str = "origin",
) -> GitResult:
    """Stage *files*, commit with *message*, and push to *remote*.

    Returns a :class:`GitResult` with the commit hash on success.
    """
    if not files:
        return GitResult(success=False, message="No files to commit")

    # Stage files
    rel_paths = [str(f.resolve().relative_to(repo_root.resolve())) for f in files]
    add_result = _run_git("add", "--", *rel_paths, cwd=repo_root)
    if add_result.returncode != 0:
        return GitResult(success=False, message=f"git add failed: {add_result.stderr}")

    # Commit
    commit_result = _run_git("commit", "-m", message, cwd=repo_root)
    if commit_result.returncode != 0:
        stderr = commit_result.stderr.strip()
        stdout = commit_result.stdout.strip()
        if "nothing to commit" in stdout or "nothing to commit" in stderr:
            return GitResult(success=True, message="Nothing to commit — already up to date")
        return GitResult(success=False, message=f"git commit failed: {stderr or stdout}")

    # Get commit hash
    hash_result = _run_git("rev-parse", "--short", "HEAD", cwd=repo_root)
    commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""

    # Push
    push_result = _run_git("push", remote, cwd=repo_root, timeout=60)
    if push_result.returncode != 0:
        return GitResult(
            success=False,
            message=f"Committed ({commit_hash}) but push failed: {push_result.stderr}",
            commit_hash=commit_hash,
        )

    return GitResult(
        success=True,
        message=f"Committed and pushed ({commit_hash})",
        commit_hash=commit_hash,
    )


def pull(repo_root: Path, remote: str = "origin") -> GitResult:
    """Pull latest changes from *remote*.

    Returns a :class:`GitResult` describing the outcome.
    """
    result = _run_git("pull", remote, cwd=repo_root, timeout=60)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        if "CONFLICT" in stdout or "CONFLICT" in stderr:
            return GitResult(
                success=False,
                message=f"Pull completed with merge conflicts: {stdout}",
            )
        return GitResult(success=False, message=f"git pull failed: {stderr or stdout}")

    if "Already up to date" in stdout:
        return GitResult(success=True, message="Already up to date")

    return GitResult(success=True, message=stdout)
