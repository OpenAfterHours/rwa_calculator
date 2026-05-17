#!/usr/bin/env python3
"""
Developer git-worktree helper for the rwa-calc repo.

Wraps the same conventions that `/next-items` uses internally (sibling
worktree paths, shared main `.venv` via `UV_PROJECT_ENVIRONMENT`) so that a
developer can spin up a parallel Claude Code session by hand with one command.

Branch namespace is `wt/<name>` — kept separate from the orchestrator's
`batch/*` namespace so the two never collide.

Subcommands:
    create <name> [--from <base-ref>] [--force]
    remove <name> [--delete-branch] [--force]
    list

Usage:
    uv run python scripts/worktree.py create feature-x
    uv run python scripts/worktree.py create spike-y --from master
    uv run python scripts/worktree.py list
    uv run python scripts/worktree.py remove feature-x
    uv run python scripts/worktree.py remove feature-x --delete-branch
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BRANCH_PREFIX = "wt/"
WORKTREE_PATH_PREFIX = "rwa_calculator-"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MERGE_TARGET_DEFAULT = "master"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="worktree.py",
        description="Manage developer git worktrees for parallel Claude Code sessions.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a new wt/<name> worktree")
    p_create.add_argument("name", help="Worktree name (lowercase, digits, dashes)")
    p_create.add_argument(
        "--from",
        dest="base_ref",
        default="HEAD",
        help="Base ref for the new branch (default: HEAD)",
    )
    p_create.add_argument(
        "--force",
        action="store_true",
        help="Remove an existing path/branch with the same name before creating",
    )

    p_remove = sub.add_parser("remove", help="Remove a wt/<name> worktree")
    p_remove.add_argument("name", help="Worktree name")
    p_remove.add_argument(
        "--delete-branch",
        action="store_true",
        help="Also delete the wt/<name> branch (default: keep)",
    )
    p_remove.add_argument(
        "--force",
        action="store_true",
        help="Skip dirty-state check and pass --force to git worktree remove",
    )

    sub.add_parser("list", help="List all wt/* worktrees with status")

    args = parser.parse_args(argv)

    if args.cmd == "create":
        return cmd_create(args.name, args.base_ref, args.force)
    if args.cmd == "remove":
        return cmd_remove(args.name, args.delete_branch, args.force)
    if args.cmd == "list":
        cmd_list()
        return 0
    parser.error(f"unknown command: {args.cmd}")
    return 2


def cmd_create(name: str, base_ref: str, force: bool) -> int:
    _validate_name(name)
    branch = _branch_for(name)
    worktree_path = _worktree_path_for(name)

    if worktree_path.exists():
        if not force:
            print(
                f"error: path already exists: {worktree_path}\n"
                f"       pass --force to remove it first, or pick a different name.",
                file=sys.stderr,
            )
            return 1
        print(f"--force: removing existing worktree at {worktree_path}")
        _run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            check=False,
        )

    existing = _run(["git", "branch", "--list", branch]).stdout.strip()
    if existing:
        if not force:
            print(
                f"error: branch already exists: {branch}\n"
                f"       pass --force to delete it first, or pick a different name.",
                file=sys.stderr,
            )
            return 1
        print(f"--force: deleting existing branch {branch}")
        _run(["git", "branch", "-D", branch], check=False)

    result = _run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), base_ref],
        check=False,
    )
    if result.returncode != 0:
        print(
            f"error: git worktree add failed:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
        return result.returncode

    venv_path = PROJECT_ROOT / ".venv"
    print("\nCreated worktree:")
    print(f"  Path:   {worktree_path}")
    print(f"  Branch: {branch}")
    print(f"  Base:   {base_ref}")
    print()
    if venv_path.exists():
        print("To use the main .venv from this worktree (saves disk + sync time):")
        print()
        print("  PowerShell:")
        print(f'    $env:UV_PROJECT_ENVIRONMENT = "{venv_path}"')
        print(f'    cd "{worktree_path}"')
        print()
        print("  bash/zsh:")
        print(f'    export UV_PROJECT_ENVIRONMENT="{venv_path}"')
        print(f'    cd "{worktree_path}"')
        print()
        print("Then start a new Claude Code session in that directory.")
    else:
        print(f"No main .venv found at {venv_path} — run `uv sync` in either tree to create one.")
    return 0


def cmd_remove(name: str, delete_branch: bool, force: bool) -> int:
    _validate_name(name)
    branch = _branch_for(name)
    worktree_path = _worktree_path_for(name)
    registered = _worktree_registered(worktree_path)

    precheck = _precheck_remove(worktree_path, registered, force)
    if precheck != 0:
        return precheck

    if registered:
        rc = _remove_worktree_path(worktree_path, force)
        if rc != 0:
            return rc

    _handle_branch_after_remove(branch, delete_branch)
    return 0


def _precheck_remove(worktree_path: Path, registered: bool, force: bool) -> int:
    if force:
        return 0
    if not registered:
        print(
            f"error: no worktree registered at {worktree_path}\n"
            f"       (run `worktree.py list` to see active worktrees)",
            file=sys.stderr,
        )
        return 1
    dirty = _run(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        check=False,
    ).stdout.strip()
    if dirty:
        print(
            f"error: worktree {worktree_path} has uncommitted changes:\n"
            f"{dirty}\n"
            f"       commit them first, or pass --force to remove anyway.",
            file=sys.stderr,
        )
        return 1
    return 0


def _remove_worktree_path(worktree_path: Path, force: bool) -> int:
    remove_cmd = ["git", "worktree", "remove", str(worktree_path)]
    if force:
        remove_cmd.insert(3, "--force")
    result = _run(remove_cmd, check=False)
    if result.returncode != 0:
        print(
            f"error: git worktree remove failed:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
        return result.returncode
    print(f"Removed worktree: {worktree_path}")
    return 0


def _handle_branch_after_remove(branch: str, delete_branch: bool) -> None:
    if not delete_branch:
        print(f"Kept branch:      {branch}  (delete with: git branch -D {branch})")
        return
    result = _run(["git", "branch", "-D", branch], check=False)
    if result.returncode != 0:
        print(
            f"warning: could not delete branch {branch}:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
    else:
        print(f"Deleted branch:   {branch}")


def cmd_list() -> None:
    porcelain = _run(["git", "worktree", "list", "--porcelain"]).stdout
    entries = [
        e
        for e in _parse_worktree_list(porcelain)
        if e.get("branch", "").startswith(f"refs/heads/{BRANCH_PREFIX}")
    ]
    if not entries:
        print(
            f"No developer worktrees ({BRANCH_PREFIX}*). "
            f"Use 'worktree.py create <name>' to add one."
        )
        return

    rows: list[tuple[str, str, str, int, int, int]] = []
    for e in entries:
        path = Path(e["worktree"])
        branch = e["branch"].removeprefix("refs/heads/")
        name = branch.removeprefix(BRANCH_PREFIX)
        dirty_out = _run(["git", "-C", str(path), "status", "--porcelain"], check=False).stdout
        dirty = sum(1 for line in dirty_out.splitlines() if line.strip())
        ahead, behind = _ahead_behind(path)
        rows.append((name, branch, str(path), dirty, ahead, behind))

    name_w = max(len("NAME"), *(len(r[0]) for r in rows))
    branch_w = max(len("BRANCH"), *(len(r[1]) for r in rows))
    path_w = max(len("PATH"), *(len(r[2]) for r in rows))
    header = f"{'NAME':<{name_w}}  {'BRANCH':<{branch_w}}  {'PATH':<{path_w}}  DIRTY  AHEAD  BEHIND"
    print(header)
    for name, branch, path, dirty, ahead, behind in rows:
        print(
            f"{name:<{name_w}}  {branch:<{branch_w}}  {path:<{path_w}}  "
            f"{dirty:>5}  {ahead:>5}  {behind:>6}"
        )


def _validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise SystemExit(
            f"error: invalid name {name!r}. "
            f"Use lowercase letters, digits, and dashes (must start with a letter or digit)."
        )


def _branch_for(name: str) -> str:
    return f"{BRANCH_PREFIX}{name}"


def _worktree_path_for(name: str) -> Path:
    return (PROJECT_ROOT.parent / f"{WORKTREE_PATH_PREFIX}{name}").resolve()


def _worktree_registered(path: Path) -> bool:
    porcelain = _run(["git", "worktree", "list", "--porcelain"]).stdout
    target = path.resolve()
    for entry in _parse_worktree_list(porcelain):
        if Path(entry["worktree"]).resolve() == target:
            return True
    return False


def _parse_worktree_list(porcelain: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in porcelain.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def _ahead_behind(path: Path) -> tuple[int, int]:
    result = _run(
        [
            "git",
            "-C",
            str(path),
            "rev-list",
            "--left-right",
            "--count",
            f"{MERGE_TARGET_DEFAULT}...HEAD",
        ],
        check=False,
    )
    if result.returncode != 0:
        return (0, 0)
    parts = result.stdout.split()
    if len(parts) != 2:
        return (0, 0)
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemExit(f"error: command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result


if __name__ == "__main__":
    sys.exit(main())
