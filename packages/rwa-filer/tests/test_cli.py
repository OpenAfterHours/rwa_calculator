"""The ``rwa-filer`` command: version, help and exit codes."""

from __future__ import annotations

import pytest

from rwa_filer import __version__
from rwa_filer.cli import EXIT_OK, build_parser, main


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange / Act
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    # Assert
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"rwa-filer {__version__}"


def test_no_command_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange / Act
    code = main([])

    # Assert
    assert code == EXIT_OK
    assert "usage: rwa-filer" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error() -> None:
    # Arrange / Act
    with pytest.raises(SystemExit) as exit_info:
        main(["no-such-command"])

    # Assert
    assert exit_info.value.code == 2


def test_parser_program_name_matches_the_console_script() -> None:
    assert build_parser().prog == "rwa-filer"
