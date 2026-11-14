"""
Unit tests for the every-package release mode of scripts/deploy.py.

Pipeline position:
    scripts/deploy.py --package all
        -> plan (versions, dependency order) -> range check -> confirm once
        -> every tag's pre-flight -> every package's suite
        -> per package: its own release flow -> wait on PyPI before its dependents

Key responsibilities:
- The set of packages and their order come from the workspace itself (the
  member table plus each package's declared dependencies), so a new package
  joins the release, in the right place, without this mode being edited.
- Everything that can refuse is asked before the first package changes, so a
  failed check or suite publishes nothing.
- A package that a later package depends on must be ON PyPI — the exact version
  just released — before that later package starts.
- A version the rest of the workspace has not declared it accepts is refused
  before anything changes: ``uv lock`` accepts a workspace member at any
  version, so nothing else would notice.

Every subprocess and network seam is faked; nothing here touches a real
repository, GitHub or PyPI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import deploy  # noqa: E402  # ty: ignore[unresolved-import]

BRANCH = "master"


def _args(**overrides: object) -> argparse.Namespace:
    """Parsed ``--package all`` args with test-friendly defaults (tests skipped)."""
    base: dict[str, object] = {
        "version": None,
        "bump": None,
        "set_version": [],
        "package": "all",
        "publish": False,
        "dry_run": False,
        "skip_tests": True,
        "no_git": False,
        "no_push": False,
        "no_github_release": False,
        "yes": True,
        "skip_filer_check": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _plan(filer: str = "0.1.0", calc: str = "0.3.35") -> list[deploy.PlannedRelease]:
    return [
        deploy.PlannedRelease(name="rwa-filer", current="0.1.0", new=filer),
        deploy.PlannedRelease(name="rwa-calc", current="0.3.34", new=calc),
    ]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace: a root that depends on the member, and the member."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "rwa-calc"\n'
        'version = "0.3.34"\n'
        'dependencies = ["polars>=1.0", "rwa-filer>=0.1,<0.2"]\n',
        encoding="utf-8",
    )
    package = tmp_path / "packages" / "rwa-filer"
    (package / "src" / "rwa_filer").mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[project]\nname = "rwa-filer"\nversion = "0.1.0"\ndependencies = ["polars>=1.0"]\n',
        encoding="utf-8",
    )
    (package / "src" / "rwa_filer" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    monkeypatch.setattr(deploy, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestWorkspaceGraph:
    def test_the_real_root_depends_on_the_member_with_its_declared_range(self):
        # Act
        dependencies = deploy.workspace_dependencies("rwa-calc")

        # Assert
        assert dependencies == {"rwa-filer": deploy.required_range("rwa-filer")}

    def test_the_real_member_depends_on_no_workspace_package(self):
        assert deploy.workspace_dependencies("rwa-filer") == {}

    def test_the_real_release_order_puts_the_member_before_the_root(self):
        assert deploy.release_order(deploy.workspace_packages()) == ["rwa-filer", "rwa-calc"]

    def test_an_extra_counts_and_names_are_normalised(self, workspace):
        # Arrange — the dependency spelled with underscores, in an extra only.
        (workspace / "pyproject.toml").write_text(
            "[project]\n"
            'name = "rwa-calc"\n'
            'version = "0.3.34"\n'
            'dependencies = ["polars>=1.0"]\n'
            "[project.optional-dependencies]\n"
            "filing = [\"RWA_Filer[excel]>=0.1 ; python_version >= '3.13'\"]\n",
            encoding="utf-8",
        )

        # Act / Assert
        assert deploy.workspace_dependencies("rwa-calc") == {"rwa-filer": ">=0.1"}

    def test_ranges_named_in_two_places_are_joined(self, workspace):
        # Arrange
        (workspace / "pyproject.toml").write_text(
            "[project]\n"
            'name = "rwa-calc"\n'
            'version = "0.3.34"\n'
            'dependencies = ["rwa-filer>=0.1"]\n'
            "[project.optional-dependencies]\n"
            'all = ["rwa-filer<0.2"]\n',
            encoding="utf-8",
        )

        # Act / Assert
        assert deploy.workspace_dependencies("rwa-calc") == {"rwa-filer": ">=0.1,<0.2"}

    def test_order_follows_dependencies_whatever_order_they_are_listed_in(self, monkeypatch):
        # Arrange — a three-package chain listed back to front: c needs b, b needs a.
        graph = {"c": {"b": ""}, "b": {"a": ""}, "a": {}}
        monkeypatch.setattr(deploy, "workspace_dependencies", lambda name: graph[name])

        # Act / Assert
        assert deploy.release_order(["c", "b", "a"]) == ["a", "b", "c"]

    def test_independent_packages_keep_their_listed_order(self, monkeypatch):
        # Arrange
        graph = {"x": {}, "y": {}, "root": {"x": "", "y": ""}}
        monkeypatch.setattr(deploy, "workspace_dependencies", lambda name: graph[name])

        # Act / Assert
        assert deploy.release_order(["y", "x", "root"]) == ["y", "x", "root"]

    def test_a_dependency_cycle_is_a_programming_error(self, monkeypatch):
        # Arrange
        graph = {"a": {"b": ""}, "b": {"a": ""}}
        monkeypatch.setattr(deploy, "workspace_dependencies", lambda name: graph[name])

        # Act / Assert
        with pytest.raises(ValueError, match="cycle"):
            deploy.release_order(["a", "b"])


class TestDependentsAdmit:
    def test_a_version_inside_the_declared_range_is_admitted(self, workspace):
        assert deploy.check_dependents_admit("rwa-filer", "0.1.7") is True

    def test_a_version_outside_the_declared_range_is_refused(self, workspace, capsys):
        # Act
        ok = deploy.check_dependents_admit("rwa-filer", "0.2.0")

        # Assert
        assert ok is False
        assert "rwa-calc requires 'rwa-filer>=0.1,<0.2'" in capsys.readouterr().out

    def test_a_package_nothing_depends_on_is_always_admitted(self, workspace):
        assert deploy.check_dependents_admit("rwa-calc", "99.0.0") is True

    def test_a_single_member_release_is_refused_before_its_dry_run(self, workspace, capsys):
        # Arrange
        member = deploy.MEMBER_RELEASES["rwa-filer"]

        # Act
        rc = deploy.main_member(_args(package="rwa-filer", version="0.2.0", dry_run=True), member)

        # Assert
        out = capsys.readouterr().out
        assert rc == 1
        assert "excludes rwa-filer 0.2.0" in out
        assert "[DRY RUN]" not in out


class TestPlan:
    def test_unnamed_packages_take_the_bump_in_dependency_order(self, workspace):
        # Act
        plan = deploy.plan_all_releases(_args(bump="minor"))

        # Assert
        assert plan == [
            deploy.PlannedRelease(name="rwa-filer", current="0.1.0", new="0.2.0"),
            deploy.PlannedRelease(name="rwa-calc", current="0.3.34", new="0.4.0"),
        ]

    def test_the_default_bump_is_patch(self, workspace):
        # Act
        plan = deploy.plan_all_releases(_args())

        # Assert
        assert plan is not None
        assert [release.new for release in plan] == ["0.1.1", "0.3.35"]

    def test_set_version_pins_one_package_and_the_rest_take_the_bump(self, workspace):
        # Act
        plan = deploy.plan_all_releases(_args(set_version=["rwa-filer=0.1.0"]))

        # Assert
        assert plan is not None
        assert [(r.name, r.new, r.tag) for r in plan] == [
            ("rwa-filer", "0.1.0", "rwa-filer-v0.1.0"),
            ("rwa-calc", "0.3.35", "v0.3.35"),
        ]

    def test_a_positional_version_is_refused(self, workspace):
        # A single version means nothing across independently versioned packages.
        assert deploy.plan_all_releases(_args(version="1.0.0")) is None

    @pytest.mark.parametrize("item", ["rwa-filer", "not-a-package=1.0.0", "=1.0.0"])
    def test_a_set_version_that_names_no_workspace_package_is_refused(self, workspace, item):
        assert deploy.plan_all_releases(_args(set_version=[item])) is None

    def test_a_package_named_twice_is_refused(self, workspace):
        # Act
        plan = deploy.plan_all_releases(_args(set_version=["rwa-filer=0.1.0", "rwa-filer=0.1.1"]))

        # Assert
        assert plan is None

    def test_a_malformed_version_is_a_usage_error(self, workspace):
        # Arrange
        args = _args(set_version=["rwa-filer=0.1"])

        # Act / Assert
        with pytest.raises(SystemExit):
            deploy.plan_all_releases(args)


class TestWaitForPypi:
    @pytest.fixture
    def clock(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        """A fake clock that advances only when the wait sleeps."""
        now = [0.0]
        monkeypatch.setattr(deploy, "_clock", lambda: now[0])
        monkeypatch.setattr(deploy, "_sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
        return now

    def test_returns_once_the_version_is_listed(self, monkeypatch, clock):
        # Arrange — PyPI unreachable once, then not yet listed, then listed.
        answers = iter([None, ["0.0.9"], ["0.0.9", "0.1.0"]])
        monkeypatch.setattr(deploy, "_pypi_versions", lambda name: next(answers))

        # Act
        ok = deploy.wait_for_pypi("rwa-filer", "0.1.0", timeout=600, interval=30)

        # Assert
        assert ok is True
        assert clock[0] == 60

    def test_gives_up_at_the_deadline(self, monkeypatch, clock):
        # Arrange
        monkeypatch.setattr(deploy, "_pypi_versions", lambda name: ["0.0.9"])

        # Act
        ok = deploy.wait_for_pypi("rwa-filer", "0.1.0", timeout=90, interval=30)

        # Assert
        assert ok is False
        assert clock[0] == 90

    def test_another_version_satisfying_the_range_does_not_count(self, monkeypatch, clock):
        # Arrange — 0.1.0 is published, 0.1.1 is the one being released.
        monkeypatch.setattr(deploy, "_pypi_versions", lambda name: ["0.1.0"])

        # Act / Assert
        assert deploy.wait_for_pypi("rwa-filer", "0.1.1", timeout=30, interval=30) is False


class TestRunAllRelease:
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
            deploy, "run_command", lambda cmd, desc: events.append(f"tests:{desc}") or True
        )
        monkeypatch.setattr(
            deploy,
            "run_member_release",
            lambda args, member, new: (
                events.append(f"release:{member.name}:{new}:skip_tests={args.skip_tests}") or 0
            ),
        )
        monkeypatch.setattr(
            deploy,
            "run_release",
            lambda args, new, current: (
                events.append(f"release:rwa-calc:{new}:skip_tests={args.skip_tests}") or 0
            ),
        )
        monkeypatch.setattr(
            deploy,
            "wait_for_pypi",
            lambda name, version: events.append(f"wait:{name}:{version}") or True,
        )
        return events

    def test_checks_everything_first_then_releases_dependencies_first(self, trace):
        # Act
        rc = deploy.run_all_release(_args(skip_tests=False), _plan())

        # Assert
        assert rc == 0
        assert trace == [
            "preflight:rwa-filer-v0.1.0",
            "preflight:v0.3.35",
            "tests:Running rwa-filer tests",
            "tests:Running rwa-calc tests",
            "release:rwa-filer:0.1.0:skip_tests=True",
            "wait:rwa-filer:0.1.0",
            "release:rwa-calc:0.3.35:skip_tests=True",
        ]

    def test_a_refused_preflight_releases_nothing(self, monkeypatch, trace):
        # Arrange — the second tag already exists on the remote.
        monkeypatch.setattr(
            deploy,
            "check_release_preflight",
            lambda branch, tag, github_release=False: tag != "v0.3.35",
        )

        # Act
        rc = deploy.run_all_release(_args(skip_tests=False), _plan())

        # Assert
        assert rc == 1
        assert trace == []

    def test_a_failing_suite_releases_nothing(self, monkeypatch, trace):
        # Arrange — the root suite fails after the member's has passed.
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: "rwa-calc" not in desc)

        # Act
        rc = deploy.run_all_release(_args(skip_tests=False), _plan())

        # Assert
        assert rc == 1
        assert not any(event.startswith("release:") for event in trace)

    def test_a_failed_member_release_stops_before_its_dependents(self, monkeypatch, trace, capsys):
        # Arrange
        monkeypatch.setattr(deploy, "run_member_release", lambda args, member, new: 1)

        # Act
        rc = deploy.run_all_release(_args(), _plan())

        # Assert
        out = capsys.readouterr().out
        assert rc == 1
        assert not any(event.startswith(("wait:", "release:rwa-calc")) for event in trace)
        assert "rwa-filer 0.1.0 did not finish" in out
        assert "deploy.py --package rwa-calc 0.3.35" in out

    def test_a_dependency_that_never_reaches_pypi_stops_the_release(
        self, monkeypatch, trace, capsys
    ):
        # Arrange
        monkeypatch.setattr(deploy, "wait_for_pypi", lambda name, version: False)

        # Act
        rc = deploy.run_all_release(_args(), _plan())

        # Assert
        out = capsys.readouterr().out
        assert rc == 1
        assert "release:rwa-calc:0.3.35:skip_tests=True" not in trace
        assert "Released before the stop:\n  rwa-filer 0.1.0 (rwa-filer-v0.1.0)" in out
        assert "deploy.py --package rwa-calc 0.3.35" in out

    @pytest.mark.parametrize("flag", ["no_github_release", "no_push"])
    def test_a_run_that_publishes_nothing_does_not_wait(self, trace, flag):
        # Act
        rc = deploy.run_all_release(_args(**{flag: True}), _plan())

        # Assert
        assert rc == 0
        assert not any(event.startswith("wait:") for event in trace)
        assert trace[-1] == "release:rwa-calc:0.3.35:skip_tests=True"

    def test_a_local_upload_still_waits(self, trace):
        # Act
        deploy.run_all_release(_args(publish=True), _plan())

        # Assert
        assert "wait:rwa-filer:0.1.0" in trace


class TestMainAll:
    def test_dry_run_names_the_wait_between_the_packages(self, workspace, capsys):
        # Act
        rc = deploy.main_all(_args(set_version=["rwa-filer=0.1.0"], dry_run=True))

        # Assert
        out = capsys.readouterr().out
        assert rc == 0
        assert out.index("git tag rwa-filer-v0.1.0") < out.index("git tag v0.3.35")
        assert "Wait for rwa-filer 0.1.0 on PyPI before releasing rwa-calc" in out

    def test_a_version_a_dependent_excludes_is_refused_before_the_dry_run(self, workspace, capsys):
        # Act
        rc = deploy.main_all(_args(bump="minor", dry_run=True))

        # Assert
        out = capsys.readouterr().out
        assert rc == 1
        assert "excludes rwa-filer 0.2.0" in out
        assert "[DRY RUN]" not in out

    def test_one_confirmation_names_every_release(self, workspace, monkeypatch, capsys):
        # Arrange
        monkeypatch.setattr(deploy, "confirm_irreversible", lambda: False)

        # Act
        rc = deploy.main_all(_args(yes=False))

        # Assert
        out = capsys.readouterr().out
        assert rc == 1
        assert "create GitHub Release rwa-filer-v0.1.1" in out
        assert "create GitHub Release v0.3.35" in out


class TestParser:
    def test_package_accepts_all(self):
        assert deploy.build_parser().parse_args(["--package", "all"]).package == "all"

    def test_set_version_is_repeatable_and_defaults_empty(self):
        # Act
        on = deploy.build_parser().parse_args(
            ["--package", "all", "--set-version", "a=1.0.0", "--set-version", "b=2.0.0"]
        )
        off = deploy.build_parser().parse_args([])

        # Assert
        assert on.set_version == ["a=1.0.0", "b=2.0.0"]
        assert off.set_version == []
