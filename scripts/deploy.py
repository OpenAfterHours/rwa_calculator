#!/usr/bin/env python3
"""
Deployment script for rwa-calc package.

Automates version updates, the release commit, tag and push, and PyPI publishing:
1. Checks the remote state the final push needs (fails fast, before the tests)
2. Runs the test suite
3. Updates version in pyproject.toml, __init__.py, docs
4. Updates changelog with new version section
5. Regenerates generated docs pages (citation matrix from @cites; module dependency graph via curfew)
6. Syncs uv.lock
7. Builds the package and checks the distribution metadata
8. Commits the version bump and creates a git tag
9. Pushes the branch and the release tag to origin in one atomic push
10. Optionally publishes to PyPI

After it runs, the release is on the remote. Pushing the tag does not by itself
publish: `.github/workflows/publish.yml` runs on a published GitHub Release, so
either pass `--publish` here or create a release from the tag afterwards.

Usage:
    python scripts/deploy.py 0.1.4
    python scripts/deploy.py 0.1.4 --publish
    python scripts/deploy.py 0.1.4 --no-push
    python scripts/deploy.py --bump patch
    python scripts/deploy.py --bump minor --publish
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# Make the sibling helper importable when this script is invoked directly.
sys.path.insert(0, str(Path(__file__).parent))

from _deploy_changelog import promote_unreleased, update_version_table  # noqa: E402
from _validate import validate_semver  # noqa: E402

# Project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent

# Files that need version updates
VERSION_FILES = {
    "pyproject.toml": r'version = "(\d+\.\d+\.\d+)"',
    "src/rwa_calc/__init__.py": r'__version__ = "(\d+\.\d+\.\d+)"',
    "docs/overview.md": r"\| Calculator \| (\d+\.\d+\.\d+) \|",
    "docs/overrides/main.html": r">v(\d+\.\d+\.\d+) &middot;",
}

CHANGELOG_PATH = PROJECT_ROOT / "docs" / "appendix" / "changelog.md"

# Remote the release commit and tag are pushed to. Every clone has `origin`, and
# on this project it points at OpenAfterHours/rwa_calculator.
RELEASE_REMOTE = "origin"

# Files to stage in the release commit. Versioned files + changelog + the lockfile
# touched by `uv sync`. Listed explicitly to avoid accidentally sweeping in untracked
# scratch files via `git add -A`.
GIT_STAGE_FILES = [
    *VERSION_FILES.keys(),
    "docs/appendix/changelog.md",
    "docs/development/citation-matrix.md",
    "tests/contracts/data/citation_snapshot.json",
    "docs/development/module-dependencies.md",
    # Version-stamped: these embed `Package version` / `package_version`, so a
    # bump alone makes them stale and their freshness contract tests fail.
    "docs/data-model/regulatory-tables.md",
    "docs/development/confidence-matrix.md",
    "tests/contracts/data/confidence_snapshot.json",
    "uv.lock",
]


def get_current_version() -> str:
    """Get current version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version = "(\d+\.\d+\.\d+)"', content)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def bump_version(current: str, bump_type: str) -> str:
    """Bump version based on type (major, minor, patch)."""
    major, minor, patch = map(int, current.split("."))

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Unknown bump type: {bump_type}")


def update_version_in_file(file_path: Path, pattern: str, new_version: str) -> bool:
    """Update version in a single file."""
    if not file_path.exists():
        print(f"  WARNING: {file_path} not found, skipping")
        return False

    content = file_path.read_text(encoding="utf-8")

    # Find and replace version
    def replacer(match: re.Match) -> str:
        full_match = match.group(0)
        old_version = match.group(1)
        return full_match.replace(old_version, new_version)

    new_content, count = re.subn(pattern, replacer, content, count=1)

    if count == 0:
        print(f"  WARNING: Pattern not found in {file_path}")
        return False

    file_path.write_text(new_content, encoding="utf-8")
    print(f"  Updated {file_path.relative_to(PROJECT_ROOT)}")
    return True


def update_changelog(new_version: str, old_version: str) -> bool:
    """Promote [Unreleased] bullets into a new version section."""
    if not CHANGELOG_PATH.exists():
        print(f"  WARNING: {CHANGELOG_PATH} not found, skipping")
        return False

    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    today = date.today().strftime("%Y-%m-%d")

    if f"## [{new_version}]" in content:
        print(f"  Changelog already has version {new_version}")
        return True

    new_content = promote_unreleased(content, new_version, today=today)
    new_content = update_version_table(new_content, new_version, old_version, today)

    if new_content == content:
        print("  WARNING: No changelog change made (no [Unreleased] block found)")
        return False

    CHANGELOG_PATH.write_text(new_content, encoding="utf-8")
    print(f"  Updated {CHANGELOG_PATH.relative_to(PROJECT_ROOT)}")
    return True


def git_tag_exists(tag: str) -> bool:
    """Return True if a git tag with this name already exists locally."""
    result = _git("tag", "--list", tag)
    return result.returncode == 0 and result.stdout.strip() == tag


def remote_tag_exists(tag: str) -> bool:
    """Return True if the release remote already carries this tag."""
    result = _git("ls-remote", "--tags", RELEASE_REMOTE, f"refs/tags/{tag}")
    return result.returncode == 0 and bool(result.stdout.strip())


def current_branch() -> str | None:
    """Return the checked-out branch name, or None on a detached HEAD."""
    result = _git("rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return None if name == "HEAD" else name


def check_release_preflight(branch: str, tag: str) -> bool:
    """Fail fast on any remote state the final push could not land on.

    Runs before the test suite, so a stale local branch or an already-published
    tag costs seconds rather than a full test run followed by a rejected push.
    """
    print(f"\nChecking {RELEASE_REMOTE} before releasing {tag} from {branch}...")

    if _git("remote", "get-url", RELEASE_REMOTE).returncode != 0:
        print(f"  ERROR: no '{RELEASE_REMOTE}' remote is configured.")
        print("  Pass --no-push to release without pushing.")
        return False

    fetch = _git("fetch", "--quiet", RELEASE_REMOTE)
    if fetch.returncode != 0:
        print(f"  ERROR: git fetch {RELEASE_REMOTE} failed: {fetch.stderr.strip()}")
        return False

    if remote_tag_exists(tag):
        print(f"  ERROR: tag {tag} already exists on {RELEASE_REMOTE}. Pick a new version.")
        return False

    upstream = f"{RELEASE_REMOTE}/{branch}"
    if _git("rev-parse", "--verify", "--quiet", upstream).returncode != 0:
        print(f"  {upstream} does not exist yet; the push will create it")
        return True

    if _git("merge-base", "--is-ancestor", upstream, "HEAD").returncode != 0:
        print(f"  ERROR: {branch} is behind {upstream}; the push would be rejected.")
        print(f"  Run `git pull --ff-only {RELEASE_REMOTE} {branch}` and re-run.")
        return False

    print(f"  {branch} is up to date with {upstream}; tag {tag} is free")
    return True


def commit_and_tag(new_version: str) -> bool:
    """Stage release files, commit, and create an annotated tag."""
    tag = f"v{new_version}"
    if git_tag_exists(tag):
        print(f"  ERROR: tag {tag} already exists. Aborting before commit.")
        return False

    existing_files = [f for f in GIT_STAGE_FILES if (PROJECT_ROOT / f).exists()]
    if not run_command(["git", "add", *existing_files], "Staging release files"):
        return False

    commit_msg = f"chore(release): bump version to {new_version}"
    if not run_command(["git", "commit", "-m", commit_msg], "Committing release"):
        return False

    return run_command(
        ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
        f"Creating tag {tag}",
    )


def push_release(branch: str, tag: str) -> bool:
    """Push the release commit and its tag together: both land, or neither does.

    The tag is named explicitly rather than pushed with `--tags`, which would
    sweep every stray local tag onto the remote with it.
    """
    push_cmd = ["git", "push", "--atomic", RELEASE_REMOTE, branch, f"refs/tags/{tag}"]
    if run_command(push_cmd, f"Pushing {branch} and {tag} to {RELEASE_REMOTE}"):
        return True

    print("\nPush failed. The release commit and tag exist locally and were left alone.")
    print("Resolve the remote state, then push by hand:")
    print(f"  {' '.join(push_cmd)}")
    return False


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status."""
    print(f"\n{description}...")
    print(f"  $ {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr}")
            return False
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n")[:5]:
                print(f"  {line}")
        return True
    except FileNotFoundError:
        print(f"  ERROR: Command not found: {cmd[0]}")
        return False


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run one git query in the project root with its output captured.

    The single subprocess seam for every git question the release asks, so the
    tests can fake it and assert on argv without touching a repository.
    """
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the deploy script."""
    parser = argparse.ArgumentParser(
        description="Deploy rwa-calc to PyPI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/deploy.py 0.1.4           # Set specific version
  python scripts/deploy.py --bump patch    # Bump patch version (0.1.3 -> 0.1.4)
  python scripts/deploy.py --bump minor    # Bump minor version (0.1.3 -> 0.2.0)
  python scripts/deploy.py 0.1.4 --publish # Update and publish to PyPI
  python scripts/deploy.py 0.1.4 --no-push # Commit and tag locally; push by hand
  python scripts/deploy.py --dry-run       # Show what would be done
        """,
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="New version number (e.g., 0.1.4)",
    )
    parser.add_argument(
        "--bump",
        choices=["major", "minor", "patch"],
        help="Bump version by type instead of setting explicitly",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish to PyPI after building",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests before deployment",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git commit and tag creation (leave changes uncommitted; implies --no-push)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit and tag locally but do not push to the remote",
    )
    return parser


def resolve_new_version(args: argparse.Namespace, current_version: str) -> str | None:
    """Resolve the target version from args, or None if the args are invalid."""
    if args.version and args.bump:
        print("ERROR: Cannot specify both version and --bump")
        return None

    if args.bump:
        return bump_version(current_version, args.bump)
    if args.version:
        return validate_semver(args.version)
    # Default to patch bump
    return bump_version(current_version, "patch")


def print_dry_run(args: argparse.Namespace, new_version: str) -> None:
    """Print the actions a real run would perform, without making changes."""
    print("\n[DRY RUN] Would perform the following:")
    print(f"  - Update version to {new_version} in:")
    for file_path in VERSION_FILES:
        print(f"    - {file_path}")
    print("  - Update changelog")
    print("  - Run: uv run python scripts/generate_citation_matrix.py")
    print("  - Run: uv sync")
    print("  - Run: uv build")
    if not args.no_git:
        print(f"  - git commit + git tag v{new_version}")
        if not args.no_push:
            print(f"  - git push --atomic {RELEASE_REMOTE} <branch> refs/tags/v{new_version}")
    if args.publish:
        print("  - Run: uv publish")


def confirm_publish() -> bool:
    """Prompt for interactive confirmation before publishing. Return True to proceed."""
    response = input("Continue? [y/N]: ").strip().lower()
    if response != "y":
        print("Aborted.")
        return False
    return True


def update_versioned_files(new_version: str, current_version: str) -> None:
    """Apply the version bump and changelog promotion across all tracked files."""
    print("\nUpdating version numbers...")
    for file_path, pattern in VERSION_FILES.items():
        full_path = PROJECT_ROOT / file_path
        update_version_in_file(full_path, pattern, new_version)

    print("\nUpdating changelog...")
    update_changelog(new_version, current_version)


def build_release(new_version: str) -> bool:
    """Regenerate generated docs, sync the lockfile, and build the package."""
    if not run_command(
        ["uv", "run", "python", "scripts/generate_citation_matrix.py"],
        "Regenerating citation matrix",
    ):
        return False

    if not run_command(
        ["uv", "run", "python", "scripts/generate_dependency_graph.py"],
        "Regenerating dependency graph",
    ):
        return False

    # Both embed the package version in their output, so the bump above has just
    # made them stale. Regenerating here is what keeps their freshness contract
    # tests green — the suite runs before the bump, so it cannot catch this.
    if not run_command(
        ["uv", "run", "python", "scripts/generate_regulatory_tables.py"],
        "Regenerating regulatory tables",
    ):
        return False

    if not run_command(
        ["uv", "run", "python", "scripts/generate_confidence_matrix.py"],
        "Regenerating confidence matrix",
    ):
        return False

    if not run_command(["uv", "sync"], "Syncing uv.lock"):
        return False

    if not run_command(["uv", "build"], "Building package"):
        return False

    # The build backend floats and the publisher is pinned, so a fresh build can
    # outrun the uploader with nothing in this repo having changed. Check that
    # here, while a bad build is still a local failure rather than a failed
    # publish against an already-tagged, already-announced release.
    if not run_command(
        ["uv", "run", "python", "scripts/check_distribution.py"],
        "Checking distribution metadata",
    ):
        return False

    dist_dir = PROJECT_ROOT / "dist"
    if dist_dir.exists():
        print("\nBuilt packages:")
        for f in sorted(dist_dir.glob(f"*{new_version}*")):
            print(f"  {f.name}")
    return True


def print_next_steps(args: argparse.Namespace, new_version: str, branch: str | None) -> None:
    """Print what, if anything, is left for the maintainer to do after the script."""
    tag = f"v{new_version}"
    push_cmd = f"git push --atomic {RELEASE_REMOTE} {branch or '<branch>'} refs/tags/{tag}"

    if args.no_git:
        print("\nGit step skipped (--no-git). To commit, tag and push manually:")
        print(f"  git add {' '.join(GIT_STAGE_FILES)}")
        print(f'  git commit -m "chore(release): bump version to {new_version}"')
        print(f'  git tag -a {tag} -m "Release {tag}"')
        print(f"  {push_cmd}")
        return

    if args.no_push:
        print("\nRelease committed and tagged locally (--no-push). To finish, push:")
        print(f"  {push_cmd}")
        return

    print(f"\nRelease {tag} is on {RELEASE_REMOTE} ({branch}).")
    if not args.publish:
        print("PyPI publishes from a GitHub Release, not from the tag push. To publish:")
        print(f"  gh release create {tag} --generate-notes")


def run_release(args: argparse.Namespace, new_version: str, current_version: str) -> int:
    """Execute the full release flow: pre-flight, tests, bump, build, commit/tag, push, publish."""
    tag = f"v{new_version}"
    wants_push = not args.no_git and not args.no_push
    branch = current_branch()
    if wants_push and branch is None:
        print("\nERROR: HEAD is detached. Check out the release branch and re-run.")
        return 1
    push_target = branch if wants_push else None

    # The push is the last step and the one most likely to be rejected by state
    # outside this checkout, so check that state first, before the test run.
    if push_target is not None and not check_release_preflight(push_target, tag):
        return 1

    # Run tests first (unless skipped)
    if not args.skip_tests and not run_command(
        ["uv", "run", "pytest", "-x", "-q"], "Running tests"
    ):
        print("\nTests failed. Fix tests before deploying.")
        print("Use --skip-tests to bypass (not recommended).")
        return 1

    update_versioned_files(new_version, current_version)

    if not build_release(new_version):
        return 1

    # Commit + tag before publishing so a successful PyPI release always has a
    # matching git tag.
    if not args.no_git:
        print("\nCommitting release and creating tag...")
        if not commit_and_tag(new_version):
            print("\nGit commit/tag failed. Resolve manually before publishing.")
            return 1

    # Push before publishing so a PyPI release always has its tag on the remote.
    if push_target is not None and not push_release(push_target, tag):
        return 1

    # Publish if requested
    if args.publish:
        if not run_command(["uv", "publish"], "Publishing to PyPI"):
            return 1
        print(f"\nSuccessfully published rwa-calc {new_version} to PyPI!")
        print(f"View at: https://pypi.org/project/rwa-calc/{new_version}/")
    else:
        print(f"\nVersion {new_version} built and tagged; not published to PyPI.")

    print_next_steps(args, new_version, branch)
    return 0


def main() -> int:
    args = build_parser().parse_args()

    current_version = get_current_version()
    print(f"Current version: {current_version}")

    new_version = resolve_new_version(args, current_version)
    if new_version is None:
        return 1

    print(f"New version: {new_version}")

    if args.dry_run:
        print_dry_run(args, new_version)
        return 0

    if args.publish:
        print(f"\nThis will publish version {new_version} to PyPI.")
        if not confirm_publish():
            return 1

    return run_release(args, new_version, current_version)


if __name__ == "__main__":
    sys.exit(main())
