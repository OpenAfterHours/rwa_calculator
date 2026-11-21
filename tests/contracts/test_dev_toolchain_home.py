"""
Contract tests: the development toolchain has one home, the default-synced group.

Pipeline position:
    (no pipeline stage — a contract on the root ``pyproject.toml``)

Key responsibilities:
- Every tool the validation gate, CI or the documented dev workflow runs is in
  ``[dependency-groups].dev``, which a plain ``uv sync`` installs
- The ``dev`` group is still the default group, so ``uv sync`` really does
  install it
- No extra names a dev tool: an extra is published with the wheel, and
  ``uv sync`` installs none, so a tool kept there is advertised to every user
  and missing from every checkout synced the plain way
- No distribution is both a runtime dependency and a dev one: a dev tool listed
  as a runtime dependency ships to every installer

Why this exists
---------------
Until the change that added this file, ``pytest``, ``pytest-cov`` and ``ty``
lived only in a published ``dev`` extra, so a bare ``uv sync`` uninstalled them
and the gate failed on a missing tool. That was a standing trap in
``.claude/LESSONS.md`` (section G), the reason CI ran ``uv sync --extra dev``,
and the third time the extra/group split had bitten (``pytest-xdist``,
``watchfire`` and ``httpx`` were each moved into the group after one). In the
other direction, ``zensical`` (the docs site) and ``marimo`` (the workbooks,
which the wheel does not ship) were runtime dependencies that nothing under
``src/rwa_calc`` imports.

The missing-runtime-dependency direction is ``scripts/check_wheel_install.py``'s
job, not this file's: it installs the built wheel alone and imports every module.

References:
- docs/development/escape-log.md — 2026-11-14 entry (the watchfire escape)
- https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-groups
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each tool a gate or the documented dev workflow invokes, and where. A plain
#: ``uv sync`` must install every one of them.
REQUIRED_DEV_TOOLS: dict[str, str] = {
    "pytest": "the test runner",
    "pytest-xdist": "the root pytest addopts pass -n / --dist",
    "pytest-benchmark": "the root pytest addopts pass --benchmark-disable",
    "pytest-cov": "docs/development/testing.md's coverage commands",
    "hypothesis": "tests/properties/ runs in the default gate",
    "httpx": "FastAPI's TestClient in the REST and UI tests",
    "ruff": "the lint and format gates",
    "ty": "the type gate (`uv run ty check ...`)",
    "zensical": "the documentation build (`uv run zensical build`)",
    "marimo": "the expected-output workbooks under workbooks/",
}

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def test_every_gate_tool_is_in_the_dev_group() -> None:
    # Arrange
    dev_group = _names(_pyproject()["dependency-groups"]["dev"])

    # Act
    missing = sorted(set(REQUIRED_DEV_TOOLS) - dev_group)

    # Assert
    assert not missing, (
        f"not in [dependency-groups].dev, so a plain `uv sync` does not install them: "
        f"{', '.join(f'{name} ({REQUIRED_DEV_TOOLS[name]})' for name in missing)}"
    )


def test_dev_group_is_installed_by_a_plain_uv_sync() -> None:
    # Arrange
    uv_settings = _pyproject().get("tool", {}).get("uv", {})

    # Act
    default_groups = uv_settings.get("default-groups", ["dev"])

    # Assert
    assert default_groups == "all" or "dev" in default_groups, (
        "[tool.uv].default-groups drops `dev`, so `uv sync` no longer installs the toolchain"
    )


def test_no_extra_carries_a_dev_tool() -> None:
    # Arrange
    project = _pyproject()["project"]
    dev_group = _names(_pyproject()["dependency-groups"]["dev"])

    # Act
    in_extras = {
        f"{extra}: {name}"
        for extra, requirements in project.get("optional-dependencies", {}).items()
        for name in _names(requirements) & dev_group
    }

    # Assert
    assert not in_extras, (
        "a dev tool in a published extra is advertised to every installer and left out "
        f"of every plain `uv sync`; keep it in [dependency-groups].dev only: {sorted(in_extras)}"
    )


def test_no_distribution_is_both_runtime_and_dev() -> None:
    # Arrange
    project = _pyproject()["project"]
    dev_group = _names(_pyproject()["dependency-groups"]["dev"])

    # Act
    both = sorted(_names(project["dependencies"]) & dev_group)

    # Assert
    assert not both, (
        "listed as a runtime dependency AND a dev tool. A runtime dependency is in the "
        "dev environment already; if src/ does not import it, it is a dev tool and "
        f"ships to every installer from [project].dependencies: {both}"
    )


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _names(requirements: list[str]) -> set[str]:
    """Normalised distribution names (PEP 503) of ``requirements``."""
    names: set[str] = set()
    for requirement in requirements:
        match = _NAME_RE.match(requirement)
        if match is not None:
            names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names
