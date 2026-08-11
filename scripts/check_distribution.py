"""
Pre-publish distribution gate.

Pipeline position:
    uv build -> check_distribution.py -> pypa/gh-action-pypi-publish

Key responsibilities:
- Read ``Metadata-Version`` from every built wheel and sdist in ``dist/``
- Read the pinned ``pypa/gh-action-pypi-publish`` version from the publish workflow
- Fail when the build emits core metadata the pinned publisher cannot accept

Why this exists
---------------
Two components here float independently of each other:

- the **build backend**, which ``uv build`` resolves fresh on every run and which
  is free to start emitting a newer core-metadata version at any time; and
- the **publisher**, ``pypa/gh-action-pypi-publish``, which is pinned to a commit
  SHA and therefore frozen, along with the Twine it vendors.

Twine's pre-upload ``check`` rejects any core-metadata version its bundled
``packaging`` predates. So the two drifting apart is enough to break publishing
with no change in this repository at all — which is exactly how v0.3.25 failed:
the backend began emitting ``Metadata-Version: 2.5`` while the workflow was
pinned at v1.14.0, whose Twine 6 rejects it::

    InvalidDistribution: Invalid distribution metadata:
    '2.5' is not a valid metadata version

Running ``twine check`` locally does **not** catch this, because a current Twine
accepts 2.5 quite happily. The failure is not "the distribution is malformed",
it is "the distribution is newer than the pinned publisher" — a skew between two
versions, which is only visible when both are read together. That is what this
script does, and it is why it is not simply a call to ``twine check``.

References:
- https://github.com/pypa/gh-action-pypi-publish/releases/tag/v1.14.2
- https://packaging.python.org/en/latest/specifications/core-metadata/
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publish.yml"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"

# Highest core-metadata version each publisher release accepts, newest first.
# The publisher vendors Twine; Twine's `check` refuses any metadata version its
# bundled `packaging` predates. Add a row when bumping the action, not when a
# build starts failing.
PUBLISHER_METADATA_SUPPORT: tuple[tuple[str, str], ...] = (
    ("1.14.2", "2.5"),  # Twine 7 — pypa/gh-action-pypi-publish#416
    ("0.0.0", "2.4"),  # Twine 6 and earlier
)

ACTION_PIN_RE = re.compile(
    r"pypa/gh-action-pypi-publish@[0-9a-fA-F]{7,40}\s*#\s*v(?P<version>\d+\.\d+\.\d+)"
)
METADATA_VERSION_RE = re.compile(r"^Metadata-Version:\s*(?P<version>\S+)\s*$", re.MULTILINE)


def main() -> int:
    """Gate the built distributions against the pinned publisher."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a built distribution declares core metadata that the pinned "
            "pypa/gh-action-pypi-publish release cannot accept."
        )
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=DEFAULT_DIST_DIR,
        help="directory holding the built wheel/sdist (default: dist/)",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        default=WORKFLOW_PATH,
        help="publish workflow to read the action pin from",
    )
    args = parser.parse_args()

    try:
        action_version = read_pinned_action_version(args.workflow)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    ceiling = metadata_ceiling_for(action_version)

    distributions = sorted([*args.dist_dir.glob("*.whl"), *args.dist_dir.glob("*.tar.gz")])
    if not distributions:
        sys.stderr.write(
            f"No distributions found in {args.dist_dir}. Run `uv build` first — a gate "
            "with nothing to check must not report success.\n"
        )
        return 1

    offenders: list[tuple[Path, str]] = []
    for dist in distributions:
        declared = read_metadata_version(dist)
        if _as_tuple(declared) > _as_tuple(ceiling):
            offenders.append((dist, declared))

    if offenders:
        listing = "\n".join(f"  - {p.name} declares Metadata-Version {v}" for p, v in offenders)
        sys.stderr.write(
            "Built distributions declare core metadata newer than the pinned "
            "publisher accepts.\n"
            f"{listing}\n"
            f"  pypa/gh-action-pypi-publish is pinned at v{action_version}, which "
            f"accepts up to Metadata-Version {ceiling}.\n"
            "Uploading would fail in the publish job with 'InvalidDistribution: "
            "... is not a valid metadata version'.\n"
            "Fix: bump the action pin in .github/workflows/publish.yml (and add a row "
            "to PUBLISHER_METADATA_SUPPORT in this script).\n"
        )
        return 1

    for dist in distributions:
        print(f"  {dist.name}: Metadata-Version {read_metadata_version(dist)} OK")
    print(
        f"All distributions publishable by gh-action-pypi-publish v{action_version} (accepts <= {ceiling})"
    )
    return 0


def read_pinned_action_version(workflow: Path) -> str:
    """Return the pinned publisher version, taking the oldest when pins differ.

    The workflow pins the action at more than one call site (TestPyPI and PyPI).
    Taking the minimum keeps the gate honest if the two ever drift apart, since
    the release is only as publishable as its oldest publisher.
    """
    if not workflow.exists():
        raise ValueError(f"Publish workflow not found at {workflow}")

    versions = ACTION_PIN_RE.findall(workflow.read_text(encoding="utf-8"))
    if not versions:
        raise ValueError(
            f"No pinned pypa/gh-action-pypi-publish version found in {workflow}. "
            "The pin must carry a trailing '# vX.Y.Z' comment for this gate to read it."
        )
    return min(versions, key=_as_tuple)


def metadata_ceiling_for(action_version: str) -> str:
    """Return the highest core-metadata version that publisher release accepts."""
    target = _as_tuple(action_version)
    for min_action, ceiling in PUBLISHER_METADATA_SUPPORT:
        if target >= _as_tuple(min_action):
            return ceiling
    return PUBLISHER_METADATA_SUPPORT[-1][1]


def read_metadata_version(distribution: Path) -> str:
    """Return the ``Metadata-Version`` declared by a wheel or sdist."""
    if distribution.suffix == ".whl":
        return _metadata_version_from_wheel(distribution)
    return _metadata_version_from_sdist(distribution)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _metadata_version_from_wheel(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if not names:
            raise ValueError(f"{wheel.name} contains no .dist-info/METADATA")
        return _parse_metadata_version(archive.read(names[0]).decode("utf-8"), wheel)


def _metadata_version_from_sdist(sdist: Path) -> str:
    with tarfile.open(sdist) as archive:
        names = [n for n in archive.getnames() if n.endswith("PKG-INFO")]
        if not names:
            raise ValueError(f"{sdist.name} contains no PKG-INFO")
        member = archive.extractfile(min(names, key=len))
        if member is None:
            raise ValueError(f"{sdist.name} PKG-INFO is not a regular file")
        return _parse_metadata_version(member.read().decode("utf-8"), sdist)


def _parse_metadata_version(content: str, source: Path) -> str:
    match = METADATA_VERSION_RE.search(content)
    if match is None:
        raise ValueError(f"{source.name} declares no Metadata-Version")
    return match.group("version")


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


if __name__ == "__main__":
    sys.exit(main())
