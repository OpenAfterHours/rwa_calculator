"""
Contract tests: every workspace package is wired into the release flow.

Pipeline position:
    pyproject.toml [tool.uv.workspace] -> scripts/deploy.py (MEMBER_RELEASES,
    --package all) -> scripts/check_distribution.py (DIST_DIRS)
    -> .github/workflows/publish.yml (tag prefix -> package)

Key responsibilities:
- A new workspace member is either releasable end to end or fails here. Without
  this, a member the release table does not know about is silently left out of
  ``deploy.py --package all`` — which reports success for the packages it did
  release — and a member publish.yml cannot select is a tag that publishes
  nothing.
- Each member's tag prefix in ``deploy.py`` is the one publish.yml dispatches on
  and strips, for every member, not only the first.

Adding a workspace package means: an entry in ``deploy.MEMBER_RELEASES``, one in
``check_distribution.DIST_DIRS``, a case arm and a version-check step in
publish.yml, and a trusted publisher on PyPI for the new project. The first
three are asserted here; the last cannot be seen from the repository.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_distribution  # noqa: E402  # ty: ignore[unresolved-import]
import deploy  # noqa: E402  # ty: ignore[unresolved-import]

PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"


def _workspace_members() -> dict[str, Path]:
    """Every workspace member on disk, by project name -> its pyproject.toml."""
    root = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members: dict[str, Path] = {}
    for pattern in root["tool"]["uv"]["workspace"]["members"]:
        for directory in sorted(REPO_ROOT.glob(pattern)):
            pyproject = directory / "pyproject.toml"
            if pyproject.is_file():
                project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
                members[project["name"]] = pyproject
    return members


MEMBERS = _workspace_members()


def test_the_workspace_has_members_to_check() -> None:
    # A glob that silently matches nothing would make every test below vacuous.
    assert MEMBERS, "no workspace members found from [tool.uv.workspace] members"


@pytest.mark.parametrize("name", sorted(MEMBERS))
def test_every_member_is_in_the_release_table(name: str) -> None:
    # Act
    member = deploy.MEMBER_RELEASES.get(name)

    # Assert
    assert member is not None, f"{name} is a workspace member but not in deploy.MEMBER_RELEASES"
    assert (REPO_ROOT / member.pyproject).resolve() == MEMBERS[name].resolve()


def test_the_release_table_names_no_package_that_is_not_a_member() -> None:
    assert set(deploy.MEMBER_RELEASES) <= set(MEMBERS)


def test_release_all_covers_every_package_once() -> None:
    # Act
    order = deploy.release_order(deploy.workspace_packages())

    # Assert
    assert sorted(order) == sorted([*MEMBERS, deploy.ROOT_PACKAGE])


def test_release_all_puts_every_package_after_its_workspace_dependencies() -> None:
    # Act
    order = deploy.release_order(deploy.workspace_packages())

    # Assert
    for position, name in enumerate(order):
        for dependency in deploy.workspace_dependencies(name):
            assert order.index(dependency) < position, f"{name} is released before {dependency}"


@pytest.mark.parametrize("name", [deploy.ROOT_PACKAGE, *sorted(MEMBERS)])
def test_every_package_has_a_distribution_directory(name: str) -> None:
    assert name in check_distribution.DIST_DIRS


@pytest.mark.parametrize("name", [deploy.ROOT_PACKAGE, *sorted(MEMBERS)])
def test_publish_workflow_can_build_every_package(name: str) -> None:
    # Arrange
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    # Act — the case arm that maps the package to its build directory.
    arm = re.search(rf"^\s*{re.escape(name)}\)\s+DIST_DIR=", workflow, re.MULTILINE)

    # Assert
    assert arm is not None, f"publish.yml has no DIST_DIR arm for {name}"


@pytest.mark.parametrize("name", sorted(MEMBERS))
def test_publish_workflow_selects_and_checks_every_member_by_its_tag_prefix(name: str) -> None:
    # Arrange
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    prefix = deploy.MEMBER_RELEASES[name].tag_prefix

    # Act
    selects = re.search(
        rf"^\s*{re.escape(prefix)}\[0-9\]\*\)\s+PACKAGE={re.escape(name)}\b",
        workflow,
        re.MULTILINE,
    )
    strips = re.search(rf'TAG_VERSION="\$\{{GITHUB_REF_NAME#{re.escape(prefix)}\}}"', workflow)

    # Assert
    assert selects is not None, f"publish.yml does not select {name} from a {prefix}* tag"
    assert strips is not None, f"publish.yml does not check {name}'s version against its tag"
