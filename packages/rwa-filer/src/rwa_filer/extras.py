"""
Optional extras — import what an extra installs, or say in one line how to get it.

Pipeline position:
    readers.excel / rules.importer / boe.importer / taxonomy._workbook
        -> import_openpyxl -> openpyxl, or MissingExtraError
        -> cli.main -> one ``rwa-filer: ...`` line on stderr, exit 1

Key responsibilities:
- Import ``openpyxl`` (the ``rwa-filer[excel]`` extra) for every module that
  reads or writes a workbook. It is imported when a workbook is first opened,
  never at module import, so nothing on the validation path needs it.
- Give one message when the extra is missing, built in one place so the call
  sites cannot drift: what needed it, and the uv commands that supply it.
  ``pip install`` is deliberately not offered — a command run with ``uvx`` has
  no lasting environment to install into.
- Raise ``MissingExtraError``. It is a ``ModuleNotFoundError``, so a caller
  that catches that keeps working; and it is its own type, so the command line
  can report a missing extra as the user's to fix without also swallowing an
  import error in the package itself, whose traceback is the report.

References:
- packages/rwa-filer/pyproject.toml ``[project.optional-dependencies]``
"""

from __future__ import annotations

from typing import Any

#: The extra that installs openpyxl.
EXCEL_EXTRA = "excel"


class MissingExtraError(ModuleNotFoundError):
    """An optional extra the operation needs is not installed.

    The message is one line, ready for the command line to print as it is.
    """


def import_openpyxl(*, needed_for: str, command: str) -> Any:
    """Import openpyxl, or raise ``MissingExtraError`` saying how to install it.

    Args:
        needed_for: What needs it, as the start of a sentence, e.g.
            ``"Reading a rule workbook"``.
        command: The ``rwa-filer`` command to show in the remedy, e.g.
            ``"rules import"``, or ``"<command>"`` where several reach it.

    Returns:
        The ``openpyxl`` package, with ``openpyxl.styles`` loaded.

    Raises:
        MissingExtraError: openpyxl cannot be imported.
    """
    try:
        import openpyxl
        import openpyxl.styles  # noqa: F401 - the styles submodule is used via the package
    except ModuleNotFoundError as exc:
        raise MissingExtraError(
            _missing_extra_message(needed_for, "openpyxl", EXCEL_EXTRA, command),
            name="openpyxl",
        ) from exc
    return openpyxl


# =============================================================================
# Private helpers
# =============================================================================


def _missing_extra_message(needed_for: str, package: str, extra: str, command: str) -> str:
    """The one-line message: what needed ``package``, and the uv commands that add it."""
    return (
        f"{needed_for} needs {package}, from the rwa-filer[{extra}] extra. "
        f'Run the command with it: uvx "rwa-filer[{extra}]@latest" {command} ... '
        f'(in a uv project: uv add "rwa-filer[{extra}]")'
    )
