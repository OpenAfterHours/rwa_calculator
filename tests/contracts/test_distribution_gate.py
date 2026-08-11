"""
Contract tests for the pre-publish distribution gate.

Pipeline position:
    uv build -> scripts/check_distribution.py -> gh-action-pypi-publish

Key responsibilities:
- The gate rejects a distribution whose core metadata outruns the pinned publisher
- The gate refuses to pass when there is nothing to check
- The release script and CI both still *invoke* the gate

The last one exists because this project has already shipped an inert ratchet
once: a check that is present but never called reports success forever. Asserting
the call sites is what turns the script into a gate.

References:
- docs/development/escape-log.md — 2026-08-11 entry on the metadata 2.5 escape
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_distribution.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Imported rather than driven through the CLI on purpose. The gate deliberately
# exposes no path-typed command-line argument — an operator-supplied string must
# never construct a path there — so passing test fixtures means calling the
# function, which is also what gives these tests real coverage of it.
from check_distribution import (  # noqa: E402
    check_distributions,
    read_pinned_action_version,
)


def _write_wheel(dist_dir: Path, metadata_version: str) -> Path:
    """Write a minimal wheel declaring the given core-metadata version."""
    dist_dir.mkdir(parents=True, exist_ok=True)
    wheel = dist_dir / "sample_pkg-1.0-py3-none-any.whl"
    metadata = f"Metadata-Version: {metadata_version}\nName: sample-pkg\nVersion: 1.0\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("sample_pkg-1.0.dist-info/METADATA", metadata)
    return wheel


def test_pinned_publisher_version_is_readable() -> None:
    """The workflow pin must stay machine-readable or the gate goes blind."""
    # Arrange / Act
    version = read_pinned_action_version(WORKFLOW)

    # Assert
    assert version.count(".") == 2, (
        "The pypa/gh-action-pypi-publish pin must carry a trailing '# vX.Y.Z' comment; "
        "without it this gate cannot tell which publisher the release will use."
    )


def test_gate_exposes_no_path_typed_cli_argument() -> None:
    """The taint source stays removed — a guard here was tried twice and failed.

    Commit a5d34c0d records that a resolve-then-contain guard did not satisfy the
    taint engine; removing the source did. Reintroducing a `type=Path` argument
    would reintroduce `pythonsecurity:S8707` and fail the quality gate.
    """
    # Arrange / Act
    source = SCRIPT.read_text(encoding="utf-8")

    # Assert
    assert "type=Path" not in source, (
        "scripts/check_distribution.py must not accept a path from the command "
        "line. Callers needing another location import check_distributions() and "
        "pass it directly."
    )


def test_gate_rejects_metadata_newer_than_the_pinned_publisher(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A distribution ahead of the pinned publisher must fail before upload."""
    # Arrange
    _write_wheel(tmp_path / "dist", "9.9")

    # Act
    exit_code = check_distributions(tmp_path / "dist", WORKFLOW)

    # Assert
    assert exit_code == 1
    assert "newer than the pinned publisher accepts" in capsys.readouterr().err


def test_gate_accepts_metadata_within_publisher_support(tmp_path: Path) -> None:
    """A distribution the pinned publisher can accept must pass."""
    # Arrange
    _write_wheel(tmp_path / "dist", "2.1")

    # Act
    exit_code = check_distributions(tmp_path / "dist", WORKFLOW)

    # Assert
    assert exit_code == 0


def test_gate_fails_when_there_is_nothing_to_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty dist/ is a failure, not a pass — silence must not read as success."""
    # Arrange
    empty = tmp_path / "dist"
    empty.mkdir()

    # Act
    exit_code = check_distributions(empty, WORKFLOW)

    # Assert
    assert exit_code == 1
    assert "No distributions found" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("path", "label"),
    [
        (DEPLOY_SCRIPT, "the release script"),
        (WORKFLOW, "the publish workflow"),
    ],
)
def test_gate_is_actually_invoked(path: Path, label: str) -> None:
    """A gate nothing calls is not a gate — assert both call sites survive."""
    # Arrange / Act
    content = path.read_text(encoding="utf-8")

    # Assert
    assert "check_distribution.py" in content, (
        f"{label} ({path.relative_to(REPO_ROOT)}) no longer invokes "
        "scripts/check_distribution.py. Removing the call silently disarms the "
        "gate — the distribution would go unchecked until PyPI rejects it."
    )
