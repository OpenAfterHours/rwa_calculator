"""
Unit tests for the push and GitHub Release steps of scripts/deploy.py.

Pipeline position:
    scripts/deploy.py::run_release
        -> pre-flight -> tests -> bump -> build -> commit + tag
        -> PUSH -> GITHUB RELEASE (fires publish.yml -> PyPI) -> optional local publish

Key responsibilities:
- The push is one atomic `git push` of the release branch and the single release
  tag — never `--tags`, never `--force`
- The GitHub Release is created from the pushed tag (`--verify-tag`) with the
  promoted changelog section as its notes; it is the CI publish trigger, so
  `--publish` (a local upload) replaces it rather than doubling it
- Both run after commit + tag; the release runs after the push
- `--no-push`, `--no-git` and `--no-github-release` skip what they name, and a
  failed push or release leaves the local state alone and prints the manual
  command
- A pre-flight fails fast, BEFORE the multi-minute test run, on any remote state
  the final steps could not land on: no remote, a fetch failure, the tag already
  on the remote, the local branch behind its upstream, or `gh` not logged in
- The irreversible steps are named up front and confirmed unless `--yes`

The subprocess seams are `deploy._git` and `deploy._gh`; every test here fakes
them and asserts on the argv, so nothing touches a real repository.
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
NOTES = Path("notes.md")
PUSH_ARGV = ["git", "push", "--atomic", "origin", BRANCH, f"refs/tags/{TAG}"]
RELEASE_ARGV = [
    "gh",
    "release",
    "create",
    TAG,
    "--verify-tag",
    "--title",
    TAG,
    "--notes-file",
    str(NOTES),
    "--generate-notes",
]


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
        "no_github_release": False,
        "yes": False,
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


class TestGithubRelease:
    def test_creates_the_release_from_the_pushed_tag_with_the_notes_file(self, monkeypatch):
        # Arrange
        calls: list[list[str]] = []
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: calls.append(cmd) or True)

        # Act
        ok = deploy.create_github_release(TAG, NOTES)

        # Assert
        assert ok is True
        assert calls == [RELEASE_ARGV]

    def test_verify_tag_binds_the_release_to_a_tag_already_on_the_remote(self):
        # Act
        argv = deploy.github_release_command(TAG, NOTES)

        # Assert
        assert "--verify-tag" in argv
        assert "--draft" not in argv, "a draft does not fire publish.yml"

    def test_failed_creation_says_the_tag_is_pushed_and_prints_the_manual_command(
        self, monkeypatch, capsys
    ):
        # Arrange
        monkeypatch.setattr(deploy, "run_command", lambda cmd, desc: False)

        # Act
        ok = deploy.create_github_release(TAG, NOTES)

        # Assert
        out = capsys.readouterr().out
        assert ok is False
        assert " ".join(RELEASE_ARGV) in out
        assert "pushed" in out


class TestReleaseNotes:
    @pytest.fixture
    def project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        changelog = tmp_path / "docs" / "appendix" / "changelog.md"
        changelog.parent.mkdir(parents=True)
        changelog.write_text(
            "# Changelog\n\n"
            "## [Unreleased]\n\n### Added\n- (Next release changes will go here)\n\n---\n\n"
            f"## [{NEW}] - 2026-09-05\n\n### Fixed\n- The thing.\n  Wrapped line.\n\n---\n\n"
            f"## [{OLD}] - 2026-09-01\n\n### Added\n- Older thing.\n\n---\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(deploy, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(deploy, "CHANGELOG_PATH", changelog)
        return tmp_path

    def test_notes_are_the_promoted_changelog_section_beside_the_build(self, project):
        # Act
        path = deploy.write_release_notes(NEW)

        # Assert
        assert path == project / "dist" / f"release_notes_v{NEW}.md"
        text = path.read_text(encoding="utf-8")
        assert text.startswith("### Fixed\n- The thing.\n  Wrapped line.")
        assert "Older thing" not in text
        assert "Next release changes" not in text

    def test_notes_fall_back_to_a_stub_when_the_section_is_missing(self, project):
        # Act
        path = deploy.write_release_notes("7.7.7")

        # Assert
        assert "7.7.7" in path.read_text(encoding="utf-8")


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

    @staticmethod
    def _fake_gh(monkeypatch: pytest.MonkeyPatch, *, logged_in: bool) -> list[tuple[str, ...]]:
        seen: list[tuple[str, ...]] = []

        def fake(*args: str) -> subprocess.CompletedProcess[str]:
            seen.append(args)
            return _completed(args, 0 if logged_in else 1, stderr="not logged in")

        monkeypatch.setattr(deploy, "_gh", fake)
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

    def test_checks_gh_login_when_a_github_release_will_follow(self, monkeypatch):
        # Arrange
        self._fake_git(monkeypatch)
        seen_gh = self._fake_gh(monkeypatch, logged_in=True)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG, github_release=True)

        # Assert
        assert ok is True
        assert ("auth", "status") in seen_gh

    def test_fails_before_the_tests_when_gh_is_not_logged_in(self, monkeypatch, capsys):
        # Arrange
        self._fake_git(monkeypatch)
        self._fake_gh(monkeypatch, logged_in=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG, github_release=True)

        # Assert
        assert ok is False
        assert "--no-github-release" in capsys.readouterr().out

    def test_does_not_touch_gh_when_no_github_release_will_follow(self, monkeypatch):
        # Arrange
        self._fake_git(monkeypatch)
        seen_gh = self._fake_gh(monkeypatch, logged_in=False)

        # Act
        ok = deploy.check_release_preflight(BRANCH, TAG, github_release=False)

        # Assert
        assert ok is True
        assert seen_gh == []


class TestRunReleaseFlow:
    @pytest.fixture
    def trace(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Stub every side-effecting step and record the order they run in."""
        events: list[str] = []
        monkeypatch.setattr(deploy, "current_branch", lambda: BRANCH)
        monkeypatch.setattr(
            deploy,
            "check_release_preflight",
            lambda b, t, **kw: (
                events.append(f"preflight(github_release={kw['github_release']})") or True
            ),
        )
        monkeypatch.setattr(deploy, "update_versioned_files", lambda n, c: events.append("bump"))
        monkeypatch.setattr(deploy, "build_release", lambda n: events.append("build") or True)
        monkeypatch.setattr(
            deploy, "write_release_notes", lambda n: events.append("notes") or NOTES
        )
        monkeypatch.setattr(
            deploy, "commit_and_tag", lambda n: events.append("commit_and_tag") or True
        )
        monkeypatch.setattr(deploy, "push_release", lambda b, t: events.append("push") or True)
        monkeypatch.setattr(
            deploy,
            "create_github_release",
            lambda t, p: events.append("github_release") or True,
        )

        def run_command(cmd: list[str], description: str) -> bool:
            events.append(" ".join(cmd))
            return True

        monkeypatch.setattr(deploy, "run_command", run_command)
        return events

    def test_default_run_ends_push_then_github_release(self, trace):
        # Act
        rc = deploy.run_release(_args(), NEW, OLD)

        # Assert
        assert rc == 0
        assert trace.index("commit_and_tag") < trace.index("push") < trace.index("github_release")
        assert "uv publish" not in trace

    def test_release_notes_are_written_after_the_changelog_is_promoted(self, trace):
        # Act
        deploy.run_release(_args(), NEW, OLD)

        # Assert
        assert trace.index("bump") < trace.index("notes") < trace.index("github_release")

    def test_local_publish_replaces_the_github_release(self, trace):
        # Act
        rc = deploy.run_release(_args(publish=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert trace.index("commit_and_tag") < trace.index("push") < trace.index("uv publish")
        assert "github_release" not in trace, (
            "a release would fire publish.yml onto the same version"
        )

    def test_preflight_runs_before_the_test_suite(self, trace):
        # Act
        deploy.run_release(_args(skip_tests=False), NEW, OLD)

        # Assert
        assert trace.index("preflight(github_release=True)") < trace.index("uv run pytest -x -q")

    def test_preflight_is_told_when_no_github_release_will_follow(self, trace):
        # Act
        deploy.run_release(_args(no_github_release=True), NEW, OLD)

        # Assert
        assert "preflight(github_release=False)" in trace

    def test_failed_preflight_stops_before_anything_is_changed(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(
            deploy,
            "check_release_preflight",
            lambda b, t, **kw: trace.append("preflight") or False,
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

    def test_no_github_release_pushes_without_creating_the_release(self, trace):
        # Act
        rc = deploy.run_release(_args(no_github_release=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "push" in trace
        assert "github_release" not in trace

    def test_no_push_skips_push_and_release_but_still_commits(self, trace):
        # Act
        rc = deploy.run_release(_args(no_push=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "commit_and_tag" in trace
        assert not any(e.startswith("preflight") for e in trace)
        assert "push" not in trace
        assert "github_release" not in trace

    def test_no_git_implies_no_push_and_no_release(self, trace):
        # Act
        rc = deploy.run_release(_args(no_git=True), NEW, OLD)

        # Assert
        assert rc == 0
        assert "commit_and_tag" not in trace
        assert not any(e.startswith("preflight") for e in trace)
        assert "push" not in trace
        assert "github_release" not in trace

    def test_failed_push_returns_nonzero_and_creates_no_release(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(deploy, "push_release", lambda b, t: trace.append("push") or False)

        # Act
        rc = deploy.run_release(_args(publish=True), NEW, OLD)

        # Assert
        assert rc == 1
        assert "push" in trace
        assert "github_release" not in trace
        assert "uv publish" not in trace

    def test_failed_github_release_returns_nonzero(self, monkeypatch, trace):
        # Arrange
        monkeypatch.setattr(
            deploy,
            "create_github_release",
            lambda t, p: trace.append("github_release") or False,
        )

        # Act
        rc = deploy.run_release(_args(), NEW, OLD)

        # Assert
        assert rc == 1
        assert "github_release" in trace


class TestIrreversibleSteps:
    def test_default_run_names_the_github_release_as_the_pypi_publish(self):
        # Act
        steps = deploy.irreversible_steps(_args(), TAG)

        # Assert
        assert len(steps) == 1
        assert TAG in steps[0]
        assert "PyPI" in steps[0]

    def test_local_publish_is_named_instead(self):
        # Act
        steps = deploy.irreversible_steps(_args(publish=True), TAG)

        # Assert
        assert len(steps) == 1
        assert "uv publish" in steps[0]

    @pytest.mark.parametrize(
        "overrides",
        [{"no_github_release": True}, {"no_push": True}, {"no_git": True}],
        ids=["no-github-release", "no-push", "no-git"],
    )
    def test_nothing_irreversible_without_a_release_or_upload(self, overrides):
        # Act / Assert
        assert deploy.irreversible_steps(_args(**overrides), TAG) == []


class TestCommandLine:
    @pytest.mark.parametrize("flag", ["--no-push", "--no-github-release", "--yes"])
    def test_parser_accepts_the_new_flags_and_they_default_off(self, flag):
        # Act
        on = deploy.build_parser().parse_args([NEW, flag])
        off = deploy.build_parser().parse_args([NEW])

        # Assert
        attr = flag.lstrip("-").replace("-", "_")
        assert getattr(on, attr) is True
        assert getattr(off, attr) is False

    def test_dry_run_lists_the_push_and_the_release(self, capsys):
        # Act
        deploy.print_dry_run(_args(), NEW)

        # Assert
        out = capsys.readouterr().out
        assert "git push" in out
        assert "gh release create" in out

    def test_dry_run_omits_the_release_under_no_github_release(self, capsys):
        # Act
        deploy.print_dry_run(_args(no_github_release=True), NEW)

        # Assert
        out = capsys.readouterr().out
        assert "git push" in out
        assert "gh release create" not in out

    def test_dry_run_omits_both_under_no_push(self, capsys):
        # Act
        deploy.print_dry_run(_args(no_push=True), NEW)

        # Assert
        out = capsys.readouterr().out
        assert "git push" not in out
        assert "gh release create" not in out
