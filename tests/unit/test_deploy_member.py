"""
Unit tests for the workspace-member release mode of scripts/deploy.py.

Pipeline position:
    scripts/deploy.py --package rwa-filer
        -> pre-flight -> member tests -> bump -> lock + build -> commit + tag
        -> push -> GitHub Release (publish.yml selects the package from the tag)

Key responsibilities:
- A member release touches ONLY the member's own version files and changelog,
  and tags with the member's prefix — never a bare ``v`` tag, which publish.yml
  reads as an rwa-calc release.
- The tag prefix here and the one ``publish.yml`` dispatches on are the same
  string. They live in two files, so the agreement is asserted, not assumed.
- The member builds into its own directory, so neither the distribution gate nor
  a local upload can pick up an rwa-calc artefact.
- Without ``--package`` the script still releases rwa-calc.

Every subprocess seam is faked; nothing here touches a real repository.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import deploy  # noqa: E402  # ty: ignore[unresolved-import]

PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
MEMBER = deploy.MEMBER_RELEASES["rwa-filer"]
NEW = "9.9.9"
TAG = f"rwa-filer-v{NEW}"
BRANCH = "master"


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "version": NEW,
        "bump": None,
        "package": "rwa-filer",
        "publish": False,
        "dry_run": False,
        "skip_tests": True,
        "no_git": False,
        "no_push": False,
        "no_github_release": False,
        "yes": True,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def member_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway project root holding the member's version files and changelog."""
    package = tmp_path / "packages" / "rwa-filer"
    (package / "src" / "rwa_filer").mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[project]\nname = "rwa-filer"\nversion = "0.1.0"\n\n[tool.other]\nversion = "5.5.5"\n',
        encoding="utf-8",
    )
    (package / "src" / "rwa_filer" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    (package / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- A member feature\n\n"
        "### Changed\n- (Next release changes will go here)\n\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "rwa-calc"\nversion = "0.3.34"\n', encoding="utf-8"
    )
    monkeypatch.setattr(deploy, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestMemberIdentity:
    def test_member_tag_carries_the_member_prefix(self):
        assert MEMBER.tag(NEW) == TAG

    def test_member_tag_is_never_a_bare_v_tag(self):
        # A bare v-tag is what publish.yml reads as an rwa-calc release.
        assert not re.match(r"^v\d", MEMBER.tag(NEW))

    def test_publish_workflow_dispatches_on_the_same_prefix(self):
        # Arrange
        workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

        # Act — the case arm that selects the member, and the prefix it strips.
        selects = re.search(r"^\s*(\S+)\[0-9\]\*\)\s+PACKAGE=rwa-filer", workflow, re.MULTILINE)
        strips = re.search(r'TAG_VERSION="\$\{GITHUB_REF_NAME#(rwa-filer-[^}]*)\}"', workflow)

        # Assert
        assert selects is not None, "publish.yml no longer has a case arm selecting rwa-filer"
        assert strips is not None, "publish.yml no longer strips a member tag prefix"
        assert selects.group(1) == MEMBER.tag_prefix
        assert strips.group(1) == MEMBER.tag_prefix

    def test_member_builds_into_its_own_directory(self):
        # Act
        build = list(MEMBER.build_command)

        # Assert — never the root dist/, which a local rwa-calc upload globs.
        assert MEMBER.dist_dir != "dist"
        assert MEMBER.dist_dir.startswith("dist/")
        assert build[build.index("-o") + 1] == MEMBER.dist_dir
        assert build[build.index("--package") + 1] == MEMBER.name

    def test_distribution_gate_is_pointed_at_the_member(self):
        check = list(MEMBER.check_command)
        assert check[check.index("--package") + 1] == MEMBER.name

    def test_stage_files_are_only_the_members_files_and_the_lockfile(self):
        assert set(MEMBER.stage_files) == {
            "packages/rwa-filer/pyproject.toml",
            "packages/rwa-filer/src/rwa_filer/__init__.py",
            "packages/rwa-filer/CHANGELOG.md",
            "uv.lock",
        }


class TestMemberBump:
    def test_current_version_is_read_from_the_members_pyproject(self, member_tree):
        assert deploy.get_member_version(MEMBER) == "0.1.0"

    def test_bump_updates_the_member_and_leaves_the_root_alone(self, member_tree):
        # Act
        ok = deploy.update_member_files(MEMBER, NEW)

        # Assert
        package = member_tree / "packages" / "rwa-filer"
        pyproject = (package / "pyproject.toml").read_text(encoding="utf-8")
        assert ok is True
        assert f'version = "{NEW}"' in pyproject
        assert 'version = "5.5.5"' in pyproject, "only the [project] version may move"
        assert f'__version__ = "{NEW}"' in (
            package / "src" / "rwa_filer" / "__init__.py"
        ).read_text(encoding="utf-8")
        assert 'version = "0.3.34"' in (member_tree / "pyproject.toml").read_text(encoding="utf-8")

    def test_bump_promotes_the_members_own_changelog(self, member_tree):
        # Act
        deploy.update_member_files(MEMBER, NEW)

        # Assert
        changelog = (member_tree / "packages" / "rwa-filer" / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
        assert f"## [{NEW}]" in changelog
        assert "- A member feature" in changelog.split(f"## [{NEW}]", 1)[1]

    def test_a_version_file_that_does_not_take_the_bump_is_reported(self, member_tree):
        # Arrange
        init = member_tree / "packages" / "rwa-filer" / "src" / "rwa_filer" / "__init__.py"
        init.write_text("# no version here\n", encoding="utf-8")

        # Act / Assert
        assert deploy.update_member_files(MEMBER, NEW) is False

    def test_release_notes_are_the_promoted_section(self, member_tree):
        # Arrange
        deploy.update_member_files(MEMBER, NEW)

        # Act
        path = deploy.write_member_release_notes(MEMBER, NEW)

        # Assert
        assert path.name == f"release_notes_{TAG}.md"
        assert "- A member feature" in path.read_text(encoding="utf-8")


class TestMemberReleaseOrder:
    @pytest.fixture
    def trace(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        events: list[str] = []
        monkeypatch.setattr(deploy, "current_branch", lambda: BRANCH)
        monkeypatch.setattr(
            deploy,
            "check_release_preflight",
            lambda branch, tag, github_release=False: events.append(f"preflight:{tag}") or True,
        )
        monkeypatch.setattr(
            deploy, "update_member_files", lambda m, n: events.append("bump") or True
        )
        monkeypatch.setattr(deploy, "build_member", lambda m: events.append("build") or True)
        monkeypatch.setattr(
            deploy,
            "write_member_release_notes",
            lambda m, n: events.append("notes") or Path("notes.md"),
        )
        monkeypatch.setattr(
            deploy, "commit_and_tag_member", lambda m, n: events.append("commit") or True
        )
        monkeypatch.setattr(deploy, "push_release", lambda b, t: events.append(f"push:{t}") or True)
        monkeypatch.setattr(
            deploy, "create_github_release", lambda t, p: events.append(f"release:{t}") or True
        )
        monkeypatch.setattr(deploy, "member_distributions", lambda m: [Path("a.whl")])
        monkeypatch.setattr(
            deploy, "run_command", lambda cmd, desc: events.append(f"run:{cmd[1]}") or True
        )
        return events

    def test_default_run_ends_push_then_github_release(self, trace):
        # Act
        rc = deploy.run_member_release(_args(), MEMBER, NEW)

        # Assert
        assert rc == 0
        assert trace == [
            f"preflight:{TAG}",
            "bump",
            "build",
            "notes",
            "commit",
            f"push:{TAG}",
            f"release:{TAG}",
        ]

    def test_member_tests_run_after_the_preflight_and_before_the_bump(self, trace):
        # Act
        deploy.run_member_release(_args(skip_tests=False), MEMBER, NEW)

        # Assert
        assert trace[:3] == [f"preflight:{TAG}", "run:run", "bump"]

    def test_local_publish_replaces_the_github_release(self, trace):
        # Act
        rc = deploy.run_member_release(_args(publish=True), MEMBER, NEW)

        # Assert
        assert rc == 0
        assert f"release:{TAG}" not in trace
        assert trace[-1] == "run:publish"

    def test_a_failed_bump_stops_before_the_build(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(deploy, "update_member_files", lambda m, n: False)

        # Act
        rc = deploy.run_member_release(_args(), MEMBER, NEW)

        # Assert
        assert rc == 1
        assert "build" not in trace and "commit" not in trace

    def test_no_push_commits_locally_and_publishes_nothing(self, trace):
        # Act
        rc = deploy.run_member_release(_args(no_push=True), MEMBER, NEW)

        # Assert
        assert rc == 0
        assert "commit" in trace
        assert not any(event.startswith(("push:", "release:", "preflight:")) for event in trace)


class TestParser:
    def test_package_defaults_to_rwa_calc(self):
        assert deploy.build_parser().parse_args([NEW]).package == "rwa-calc"

    def test_package_accepts_the_member(self):
        args = deploy.build_parser().parse_args(["--package", "rwa-filer", NEW])
        assert args.package == "rwa-filer"

    def test_an_unknown_package_is_a_usage_error(self):
        with pytest.raises(SystemExit):
            deploy.build_parser().parse_args(["--package", "not-a-package", NEW])

    def test_dry_run_names_the_member_tag_and_files(self, capsys):
        # Act
        deploy.print_member_dry_run(_args(), MEMBER, NEW)

        # Assert
        out = capsys.readouterr().out
        assert f"git tag {TAG}" in out
        assert "packages/rwa-filer/pyproject.toml" in out
        assert "uv build --package rwa-filer -o dist/rwa-filer" in out
