"""
Unit tests for the push step of scripts/deploy.py.

Pipeline position:
    scripts/deploy.py::run_release -> tests -> bump -> build -> commit + tag -> PUSH -> publish

Key responsibilities:
- The push is one atomic `git push` of the release branch and the single release
  tag — never `--tags`, never `--force`
- It runs after commit + tag and before `uv publish`, so a PyPI release always
  has its tag on the remote
- `--no-push` and `--no-git` both skip it, and a failed push leaves the local
  commit and tag alone and prints the manual command
- A pre-flight fails fast, BEFORE the multi-minute test run, on any remote state
  the final push could not land on: no remote, a fetch failure, the tag already
  on the remote, or the local branch behind its upstream

The subprocess seam is `deploy._git`; every test here fakes it and asserts on
the argv, so nothing touches a real repository.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import deploy  # noqa: E402  # ty: ignore[unresolved-import]

BRANCH = "master"
TAG = "v9.9.9"
NEW = "9.9.9"
OLD = "9.9.8"
PUSH_ARGV = ["git", "push", "--atomic", "origin", BRANCH, f"refs/tags/{TAG}"]


def _completed(
    args: tuple[str, ...], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout, stderr)


def _args(**overrides: object) -> argparse.Namespace:
    """A parsed-args namespace with the test-friendly defaults (tests skipped)."""
    base: dict[str, object] = {
        "version": NEW,
        "bump": None,
        "publish": False,
        "dry_run": False,
        "skip_tests": True,
        "no_git": False,
        "no_push": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestPushRelease:
    def test_pushes_branch_and_release_tag_in_one_atomic_push(self, monkeypatch):
        # Arrange
        calls: list[list[str]] = []
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: calls.append(cmd) or True)

        # Act
        ok = deploy.push_release(BRANCH, TAG)

        # Assert
        assert ok is True
        assert calls == [PUSH_ARGV]

    def test_never_pushes_every_local_tag_and_never_forces(self, monkeypatch):
        # Arrange
        calls: list[list[str]] = []
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: calls.append(cmd) or True)

        # Act
        deploy.push_release(BRANCH, TAG)

        # Assert
        (argv,) = calls
        assert "--tags" not in argv
        assert not any(flag.startswith("--force") for flag in argv)

    def test_failed_push_reports_and_prints_the_manual_command(self, monkeypatch, capsys):
        # Arrange
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: False)

        # Act
        ok = deploy.push_release(BRANCH, TAG)

        # Assert
        out = capsys.readouterr().out
        assert ok is False
        assert " ".join(PUSH_ARGV) in out
        assert "local" in out


class TestCurrentBranch:
    def test_returns_the_checked_out_branch(self, monkeypatch):
        # Arrange
        monkeypatch.setattr(deploy, "_git", lambda *a: _completed(a, stdout="master\n"))

        # Act / Assert
        assert deploy.current_branch() == "master"

    def test_detached_head_is_none(self, monkeypatch):
        # Arrange
        monkeypatch.setattr(deploy, "_git", lambda *a: _completed(a, stdout="HEAD\n"))

        # Act / Assert
        assert deploy.current_branch() is None


class TestReleasePreflight:
    @staticmethod
    def _fake_git(
        monkeypatch: pytest.MonkeyPatch,
        *,
        remote_ok: bool = True,
        fetch_ok: bool = True,
        remote_tag: str = "",
        upstream_exists: bool = True,
        is_ancestor: bool = True,
    ) -> list[tuple[str, ...]]:
        seen: list[tuple[str, ...]] = []

        def fake(*args: str) -> subprocess.CompletedProcess[str]:
            seen.append(args)
            match args:
                case ("remote", "get-url", _):
                    return _completed(args, 0 if remote_ok else 2)
                case ("fetch", "--quiet", _):
                    return _completed(args, 0 if fetch_ok else 128, stderr="could not read")
                case ("ls-remote", "--tags", _, _):
                    return _completed(args, 0, stdout=remote_tag)
                case ("rev-parse", "--verify", "--quiet", _):
                    return _completed(args, 0 if upstream_exists else 1)
                case ("merge-base", "--is-ancestor", _, "HEAD"):
                    return _completed(args, 0 if is_ancestor else 1)
            raise AssertionError(f"unexpected git call: {args}")

        monkeypatch.setattr(deploy, "_git", fake)
        return seen

    def test_passes_when_branch_is_current_and_tag_is_free(self, monkeypatch):
        # Arrange
        seen = self._fake_git(monkeypatch)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is True
        assert ("fetch", "--quiet", "origin") in seen, "the ancestry check must read a fresh remote"
        assert ("merge-base", "--is-ancestor", f"origin/{BRANCH}", "HEAD") in seen

    def test_fails_when_local_branch_is_behind_its_upstream(self, monkeypatch, capsys):
        # Arrange
        self._fake_git(monkeypatch, is_ancestor=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is False
        assert "behind" in capsys.readouterr().out

    def test_fails_when_the_tag_is_already_on_the_remote(self, monkeypatch, capsys):
        # Arrange
        self._fake_git(monkeypatch, remote_tag=f"abc123\trefs/tags/{TAG}\n")

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is False
        assert TAG in capsys.readouterr().out

    def test_fails_when_there_is_no_remote(self, monkeypatch, capsys):
        # Arrange
        seen = self._fake_git(monkeypatch, remote_ok=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is False
        assert "--no-push" in capsys.readouterr().out
        assert not any(call[0] == "fetch" for call in seen)

    def test_fails_when_fetch_fails(self, monkeypatch, capsys):
        # Arrange
        self._fake_git(monkeypatch, fetch_ok=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is False
        assert "fetch" in capsys.readouterr().out

    def test_passes_when_branch_has_never_been_pushed(self, monkeypatch):
        # Arrange — no upstream ref means nothing to be behind; the push creates it
        seen = self._fake_git(monkeypatch, upstream_exists=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG)

        # Assert
        assert ok is True
        assert not any(call[0] == "merge-base" for call in seen)


class TestRunReleaseFlow:
    @pytest.fixture
    def trace(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Stub every side-effecting step and record the order they run in."""
        events: list[str] = []
        monkeypatch.setattr(deploy, "current_branch", lambda: BRANCH)
        monkeypatch.setattr(
            deploy, "check_release_preflight", lambda b, t: events.append("preflight") or True
        )
        monkeypatch.setattr(deploy, "update_versioned_files", lambda n, c: events.append("bump"))
        monkeypatch.setattr(deploy, "build_release", lambda n: events.append("build") or True)
        monkeypatch.setattr(
            deploy, "commit_and_tag", lambda n: events.append("commit_and_tag") or True
        )
        monkeypatch.setattr(deploy, "push_release", lambda b, t: events.append("push") or True)

        def run_command(cmd: list[str], description: str) -> bool:
            events.append(" ".join(cmd))
            return True

        monkeypatch.setattr(deploy, "run_command", run_command)
        return events

    def test_push_runs_after_tag_and_before_publish(self, trace):
        # Act
        rc = deploy.run_release(_args(publish=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert trace.index("commit_and_tag") < trace.index("push") < trace.index("uv publish")

    def test_preflight_runs_before_the_test_suite(self, trace):
        # Act
        deploy.run_release(_args(skip_tests=False), NEW, OLD)

        # Assert
        assert trace.index("preflight") < trace.index("uv run pytest -x -q")

    def test_failed_preflight_stops_before_anything_is_changed(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(
            deploy, "check_release_preflight", lambda b, t: trace.append("preflight") or False
        )

        # Act
        rc = deploy.run_release(_args(skip_tests=False), NEW, OLD)

        # Assert
        assert rc == 1
        assert trace == ["preflight"]

    def test_detached_head_is_refused_before_anything_runs(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(deploy, "current_branch", lambda: None)

        # Act
        rc = deploy.run_release(_args(skip_tests=False), NEW, OLD)

        # Assert
        assert rc == 1
        assert trace == []

    def test_no_push_skips_preflight_and_push_but_still_commits(self, trace):
        # Act
        rc = deploy.run_release(_args(no_push=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "commit_and_tag" in trace
        assert "preflight" not in trace
        assert "push" not in trace

    def test_no_git_implies_no_push(self, trace):
        # Act
        rc = deploy.run_release(_args(no_git=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "commit_and_tag" not in trace
        assert "preflight" not in trace
        assert "push" not in trace

    def test_failed_push_returns_nonzero_and_does_not_publish(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(deploy, "push_release", lambda b, t: trace.append("push") or False)

        # Act
        rc = deploy.run_release(_args(publish=True), NEW, OLD)

        # Assert
        assert rc == 1
        assert "push" in trace
        assert "uv publish" not in trace


class TestCommandLine:
    def test_parser_accepts_no_push(self):
        # Act
        args = deploy.build_parser().parse_args([NEW, "--no-push"])

        # Assert
        assert args.no_push is True

    def test_no_push_defaults_off(self):
        # Act
        args = deploy.build_parser().parse_args([NEW])

        # Assert
        assert args.no_push is False

    def test_dry_run_lists_the_push(self, capsys):
        # Act
        deploy.print_dry_run(_args(), NEW)

        # Assert
        assert "git push" in capsys.readouterr().out

    def test_dry_run_omits_the_push_under_no_push(self, capsys):
        # Act
        deploy.print_dry_run(_args(no_push=True), NEW)

        # Assert
        assert "git push" not in capsys.readouterr().out
