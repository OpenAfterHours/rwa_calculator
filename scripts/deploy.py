#!/usr/bin/env python3
"""
Deployment script for rwa-calc package.

Automates version updates and PyPI publishing:
1. Updates version in pyproject.toml, __init__.py, docs
2. Updates changelog with new version section
3. Syncs uv.lock
4. Builds the package
5. Optionally publishes to PyPI

Usage:
    python scripts/deploy.py 0.1.4
    python scripts/deploy.py 0.1.4 --publish
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

# Project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent

# Files that need version updates
VERSION_FILES = {
    "pyproject.toml": r'version = "(\d+\.\d+\.\d+)"',
    "src/rwa_calc/__init__.py": r'__version__ = "(\d+\.\d+\.\d+)"',
    "docs/overview.md": r"\| Calculator \| (\d+\.\d+\.\d+) \|",
}

CHANGELOG_PATH = PROJECT_ROOT / "docs" / "appendix" / "changelog.md"


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
    """Update changelog with new version section."""
    if not CHANGELOG_PATH.exists():
        print(f"  WARNING: {CHANGELOG_PATH} not found, skipping")
        return False

    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    today = date.today().strftime("%Y-%m-%d")

    # Check if version already exists
    if f"## [{new_version}]" in content:
        print(f"  Changelog already has version {new_version}")
        return True

    # Replace [Unreleased] section with new version
    unreleased_pattern = "## [Unreleased]\n\n### Added\n- (Next release changes will go here)\n\n### Changed\n- (Next release changes will go here)\n\n---"

    new_unreleased = f"""## [Unreleased]

### Added
- (Next release changes will go here)

### Changed
- (Next release changes will go here)

---

## [{new_version}] - {today}

### Changed
- Version bump for PyPI release"""

    if unreleased_pattern in content:
        content = content.replace(unreleased_pattern, new_unreleased)
    else:
        # Fallback: insert after [Unreleased] header
        unreleased_simple = r"(## \[Unreleased\].*?)(## \[\d)"
        match = re.search(unreleased_simple, content, re.DOTALL)
        if match:
            insert_point = match.start(2)
            new_section = f"\n## [{new_version}] - {today}\n\n### Changed\n- Version bump for PyPI release\n\n---\n\n"
            content = content[:insert_point] + new_section + content[insert_point:]
        else:
            print("  WARNING: Could not find insertion point in changelog")
            return False

    # Update version table
    table_pattern = rf"\| {re.escape(old_version)} \| [\d-]+ \| Current \|"
    table_replacement = (
        f"| {new_version} | {today} | Current |\n| {old_version} | {today} | Previous |"
    )

    if re.search(table_pattern, content):
        # Also update the old "Previous" to just "-"
        content = re.sub(r"\| Previous \|$", "| - |", content, flags=re.MULTILINE)
        content = re.sub(table_pattern, table_replacement, content)

    CHANGELOG_PATH.write_text(content, encoding="utf-8")
    print(f"  Updated {CHANGELOG_PATH.relative_to(PROJECT_ROOT)}")
    return True


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deploy rwa-calc to PyPI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/deploy.py 0.1.4           # Set specific version
  python scripts/deploy.py --bump patch    # Bump patch version (0.1.3 -> 0.1.4)
  python scripts/deploy.py --bump minor    # Bump minor version (0.1.3 -> 0.2.0)
  python scripts/deploy.py 0.1.4 --publish # Update and publish to PyPI
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

    args = parser.parse_args()

    # Determine new version
    current_version = get_current_version()
    print(f"Current version: {current_version}")

    if args.version and args.bump:
        print("ERROR: Cannot specify both version and --bump")
        return 1

    if args.bump:
        new_version = bump_version(current_version, args.bump)
    elif args.version:
        new_version = args.version
    else:
        # Default to patch bump
        new_version = bump_version(current_version, "patch")

    print(f"New version: {new_version}")

    if args.dry_run:
        print("\n[DRY RUN] Would perform the following:")
        print(f"  - Update version to {new_version} in:")
        for file_path in VERSION_FILES:
            print(f"    - {file_path}")
        print(f"  - Update changelog")
        print(f"  - Run: uv sync")
        print(f"  - Run: uv build")
        if args.publish:
            print(f"  - Run: uv publish")
        return 0

    # Confirm
    if args.publish:
        print(f"\nThis will publish version {new_version} to PyPI.")
        response = input("Continue? [y/N]: ").strip().lower()
        if response != "y":
            print("Aborted.")
            return 1

    # Run tests first (unless skipped)
    if not args.skip_tests:
        if not run_command(["uv", "run", "pytest", "-x", "-q"], "Running tests"):
            print("\nTests failed. Fix tests before deploying.")
            print("Use --skip-tests to bypass (not recommended).")
            return 1

    # Update version in all files
    print("\nUpdating version numbers...")
    for file_path, pattern in VERSION_FILES.items():
        full_path = PROJECT_ROOT / file_path
        update_version_in_file(full_path, pattern, new_version)

    # Update changelog
    print("\nUpdating changelog...")
    update_changelog(new_version, current_version)

    # Sync uv.lock
    if not run_command(["uv", "sync"], "Syncing uv.lock"):
        return 1

    # Build package
    if not run_command(["uv", "build"], "Building package"):
        return 1

    # Show built files
    dist_dir = PROJECT_ROOT / "dist"
    if dist_dir.exists():
        print("\nBuilt packages:")
        for f in sorted(dist_dir.glob(f"*{new_version}*")):
            print(f"  {f.name}")

    # Publish if requested
    if args.publish:
        if not run_command(["uv", "publish"], "Publishing to PyPI"):
            return 1
        print(f"\nSuccessfully published rwa-calc {new_version} to PyPI!")
        print(f"View at: https://pypi.org/project/rwa-calc/{new_version}/")
    else:
        print(f"\nVersion {new_version} ready for deployment.")
        print("Run with --publish to upload to PyPI:")
        print(f"  python scripts/deploy.py {new_version} --publish")

    # Remind about git
    print("\nDon't forget to commit and tag:")
    print(f"  git add -A")
    print(f'  git commit -m "chore: release v{new_version}"')
    print(f"  git tag v{new_version}")
    print(f"  git push origin master --tags")

    return 0


if __name__ == "__main__":
    sys.exit(main())
