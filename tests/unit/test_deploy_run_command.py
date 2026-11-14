"""
Unit tests for how scripts/deploy.py reports a failed step.

Pipeline position:
    scripts/deploy.py::run_release
        -> run_command (tests, version sync, build, commit, tag, push, ...)

Key responsibilities:
- A failed step shows what the command said. pytest writes its failure report
  to stdout and nothing to stderr, so a report built from stderr alone printed a
  blank ``ERROR:`` for a failed test run and hid which test had failed
- The stdout shown is bounded to its last lines, where a test runner puts its
  failure summary; stderr is shown in full
- A successful step still prints only the head of its stdout

Each test runs a real child Python process, so the capture and decoding the
release depends on is exercised, not faked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import deploy  # noqa: E402  # ty: ignore[unresolved-import]


def _python(code: str) -> list[str]:
    """The argv that runs ``code`` in a child interpreter.

    ``run_command`` echoes the argv before it runs it, so a test that looks for a
    child's output must have the child assemble that text at run time (``'A' +
    'B'``); text written out whole in ``code`` would be found in the echo and pass
    against a report that shows nothing of what the child said.
    """
    return [sys.executable, "-c", code]


class TestAFailedStep:
    def test_a_failure_reported_only_on_stdout_is_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange — pytest's shape: the report on stdout, nothing on stderr.
        cmd = _python("print('FAILED ' + 'tests/test_x.py::test_y'); raise SystemExit(1)")

        # Act
        ok = deploy.run_command(cmd, "Running tests")

        # Assert
        assert ok is False
        assert "FAILED tests/test_x.py::test_y" in capsys.readouterr().out

    def test_the_exit_code_is_named(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Arrange — a step that fails without a word on either stream.
        cmd = _python("raise SystemExit(1 + 2)")

        # Act
        deploy.run_command(cmd, "Silent step")

        # Assert
        assert "exit code 3" in capsys.readouterr().out

    def test_stderr_is_still_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Arrange — git's shape: the error on stderr.
        cmd = _python("import sys; sys.stderr.write('fatal: ' + 'remote hung up'); sys.exit(128)")

        # Act
        deploy.run_command(cmd, "Pushing")

        # Assert
        assert "fatal: remote hung up" in capsys.readouterr().out

    def test_only_the_tail_of_a_long_stdout_is_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange — more lines than the tail keeps, the summary last.
        total = deploy.FAILURE_STDOUT_TAIL_LINES + 50
        cmd = _python(
            f"[print(f'line {{i}}') for i in range({total})]; print('SUM' + 'MARY'); raise SystemExit(1)"
        )

        # Act
        deploy.run_command(cmd, "Running tests")

        # Assert
        out = capsys.readouterr().out
        assert "SUMMARY" in out
        assert "line 0\n" not in out


class TestASuccessfulStep:
    def test_only_the_head_of_stdout_is_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Arrange
        cmd = _python("[print(f'line {i}') for i in range(10)]")

        # Act
        ok = deploy.run_command(cmd, "Building")

        # Assert
        out = capsys.readouterr().out
        assert ok is True
        assert "line 4" in out
        assert "line 5" not in out
