"""
Unit tests for the release-ordering check in scripts/deploy.py.

Pipeline position:
    scripts/deploy.py::run_release
        -> pre-flight -> RELEASE-ORDER CHECK -> tests -> bump -> build -> ...

Why this exists: inside the workspace rwa-calc resolves rwa-filer from the
checkout, so every gate passes whatever is on PyPI. An installed rwa-calc
resolves the same requirement from PyPI, and if no published rwa-filer satisfies
it the release is uninstallable for everyone. The check is the only place that
gap is visible before the publish.

Key responsibilities:
- The required range is read from the root pyproject.toml, not restated.
- A satisfying published version passes; none, or a project that is not on PyPI
  at all, refuses the release and names the fix.
- "PyPI could not be reached" is UNKNOWN, and unknown refuses — it must never
  read as published.
- Only a run that publishes is gated, and it is gated before the test run.

The network seam is ``deploy._pypi_versions``; every test fakes it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import deploy  # noqa: E402  # ty: ignore[unresolved-import]

NEW = "9.9.9"
OLD = "9.9.8"


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "version": NEW,
        "bump": None,
        "package": "rwa-calc",
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


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway project root whose pyproject declares the rwa-filer range."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "rwa-calc"\nversion = "0.3.34"\n'
        'dependencies = [\n    "polars>=1.0.0",\n    "rwa-filer>=0.1,<0.2",\n]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _publish(monkeypatch: pytest.MonkeyPatch, versions: list[str] | None) -> list[str]:
    asked: list[str] = []

    def fake(distribution: str) -> list[str] | None:
        asked.append(distribution)
        return versions

    monkeypatch.setattr(deploy, "_pypi_versions", fake)
    return asked


class TestRequiredRange:
    def test_reads_the_range_the_root_project_declares(self, project):
        assert deploy.required_range("rwa-filer") == ">=0.1,<0.2"

    def test_the_real_pyproject_declares_a_range_for_rwa_filer(self):
        # Adequacy: if the real requirement vanished, the check would pass
        # vacuously on every release.
        assert deploy.required_range(deploy.FILER_DISTRIBUTION) is not None

    def test_an_undeclared_distribution_has_no_range(self, project):
        assert deploy.required_range("not-a-dependency") is None


class TestVersionSatisfies:
    @pytest.mark.parametrize(
        ("version", "spec", "expected"),
        [
            ("0.1.0", ">=0.1,<0.2", True),
            ("0.1.7", ">=0.1,<0.2", True),
            ("0.2.0", ">=0.1,<0.2", False),
            ("0.0.9", ">=0.1,<0.2", False),
            ("1.0.0", ">=0.1,<0.2", False),
            ("0.10.0", ">=0.9,<0.11", True),
            ("0.9.0", ">0.9", False),
            ("0.3.1", "==0.3.1", True),
            ("0.3.1", "<=0.3.1", True),
        ],
    )
    def test_plain_versions_against_a_range(self, version: str, spec: str, expected: bool):
        assert deploy.version_satisfies(version, spec) is expected

    def test_a_pre_release_never_satisfies(self):
        assert deploy.version_satisfies("0.1.0rc1", ">=0.1,<0.2") is False

    def test_an_unsupported_operator_fails_closed(self):
        assert deploy.version_satisfies("0.1.0", "~=0.1") is False


class TestCheckFilerDependencyPublished:
    def test_passes_when_a_satisfying_version_is_published(self, project, monkeypatch, capsys):
        # Arrange
        asked = _publish(monkeypatch, ["0.0.1", "0.1.0", "0.1.2", "0.2.0"])

        # Act
        ok = deploy.check_filer_dependency_published()

        # Assert
        assert ok is True
        assert asked == ["rwa-filer"]
        assert "rwa-filer 0.1.2 is published" in capsys.readouterr().out

    def test_refuses_when_no_published_version_satisfies(self, project, monkeypatch, capsys):
        # Arrange
        _publish(monkeypatch, ["0.0.1", "0.2.0"])

        # Act
        ok = deploy.check_filer_dependency_published()

        # Assert
        out = capsys.readouterr().out
        assert ok is False
        assert "no published rwa-filer satisfies" in out
        assert "--package rwa-filer" in out

    def test_refuses_when_the_project_is_not_on_pypi_at_all(self, project, monkeypatch, capsys):
        # Arrange
        _publish(monkeypatch, [])

        # Act
        ok = deploy.check_filer_dependency_published()

        # Assert
        assert ok is False
        assert "not on PyPI" in capsys.readouterr().out

    def test_an_unreachable_pypi_refuses_rather_than_assumes(self, project, monkeypatch, capsys):
        # Arrange
        _publish(monkeypatch, None)

        # Act
        ok = deploy.check_filer_dependency_published()

        # Assert — unknown is not published.
        assert ok is False
        assert "could not reach PyPI" in capsys.readouterr().out

    def test_no_declared_dependency_means_nothing_to_order(self, tmp_path, monkeypatch):
        # Arrange
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "rwa-calc"\ndependencies = ["polars>=1.0.0"]\n', encoding="utf-8"
        )
        monkeypatch.setattr(deploy, "PROJECT_ROOT", tmp_path)
        asked = _publish(monkeypatch, None)

        # Act / Assert
        assert deploy.check_filer_dependency_published() is True
        assert asked == []


class TestReleaseFlowGating:
    @pytest.fixture
    def trace(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        events: list[str] = []
        monkeypatch.setattr(deploy, "current_branch", lambda: "master")
        monkeypatch.setattr(
            deploy, "check_release_preflight", lambda b, t, **kw: events.append("preflight") or True
        )
        monkeypatch.setattr(deploy, "update_versioned_files", lambda n, c: events.append("bump"))
        monkeypatch.setattr(deploy, "build_release", lambda n: events.append("build") or True)
        monkeypatch.setattr(
            deploy, "write_release_notes", lambda n: events.append("notes") or Path("n.md")
        )
        monkeypatch.setattr(deploy, "commit_and_tag", lambda n: events.append("commit") or True)
        monkeypatch.setattr(deploy, "push_release", lambda b, t: events.append("push") or True)
        monkeypatch.setattr(
            deploy, "create_github_release", lambda t, p: events.append("release") or True
        )
        monkeypatch.setattr(
            deploy, "run_command", lambda cmd, desc: events.append(f"run:{cmd[1]}") or True
        )
        return events

    def test_an_unpublished_filer_stops_the_release_before_anything_changes(
        self, monkeypatch, trace
    ):
        # Arrange
        monkeypatch.setattr(deploy, "check_filer_dependency_published", lambda: False)

        # Act
        rc = deploy.run_release(_args(skip_tests=False), NEW, OLD)

        # Assert — after the remote pre-flight, before the tests and the bump.
        assert rc == 1
        assert trace == ["preflight"]

    def test_a_published_filer_lets_the_release_proceed(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(
            deploy, "check_filer_dependency_published", lambda: trace.append("order") or True
        )

        # Act
        rc = deploy.run_release(_args(), NEW, OLD)

        # Assert
        assert rc == 0
        assert trace[:3] == ["preflight", "order", "bump"]
        assert trace[-1] == "release"

    def test_a_local_only_run_is_not_gated(self, monkeypatch, trace):
        """--no-push publishes nothing, so there is nothing to order."""
        # Arrange
        monkeypatch.setattr(
            deploy, "check_filer_dependency_published", lambda: trace.append("order") or False
        )

        # Act
        rc = deploy.run_release(_args(no_push=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "order" not in trace

    def test_a_local_upload_is_gated_too(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(deploy, "check_filer_dependency_published", lambda: False)

        # Act
        rc = deploy.run_release(_args(publish=True), NEW, OLD)

        # Assert
        assert rc == 1
        assert "bump" not in trace

    def test_the_skip_flag_bypasses_the_check(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(
            deploy, "check_filer_dependency_published", lambda: trace.append("order") or False
        )

        # Act
        rc = deploy.run_release(_args(skip_filer_check=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "order" not in trace

    def test_parser_exposes_the_skip_flag_off_by_default(self):
        assert deploy.build_parser().parse_args([NEW]).skip_filer_check is False
        assert deploy.build_parser().parse_args([NEW, "--skip-filer-check"]).skip_filer_check
