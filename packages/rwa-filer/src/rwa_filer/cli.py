"""
The ``rwa-filer`` command line.

Pipeline position:
    shell  ->  rwa_filer.cli.main  ->  the package's public API

Key responsibilities:
- Parse the command line and dispatch to a subcommand.
- Write results to stdout and diagnostics to stderr, and return a process exit
  code. This module holds no validation or filing logic of its own.

Commands:
    rwa-filer rules list
        The packaged rule extracts: framework, publisher, version and counts.
    rwa-filer rules import --publisher {eba,boe} WORKBOOK --out FILE
        Rebuild an extract from a publisher's rule workbook.
    rwa-filer rules check --publisher {eba,boe} WORKBOOK [--against FILE]
        Fail if the extract (the packaged one by default) is not exactly what
        the workbook yields.

Exit codes:
    0  success
    1  the command ran and the answer is "no" (a stale extract, a missing file)
    2  usage error (argparse's own convention)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from rwa_filer import __version__
from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES, extract_resource, load_rules

EXIT_OK = 0
EXIT_FAILED = 1

#: The framework each publisher's extract is packaged under.
_PUBLISHER_FRAMEWORK: dict[str, str] = {
    importer.PUBLISHER_EBA: "CRR",
    importer.PUBLISHER_BOE: "BASEL_3_1",
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``rwa-filer`` command and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stdout)
        return EXIT_OK
    return handler(args)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="rwa-filer",
        description=(
            "Validate regulatory returns against the published supervisory rules "
            "and write them for submission."
        ),
    )
    parser.add_argument("--version", action="version", version=f"rwa-filer {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    _add_rules_commands(commands)
    return parser


# =============================================================================
# rules
# =============================================================================


def _add_rules_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer rules ...``."""
    rules = commands.add_parser(
        "rules", help="inspect and rebuild the packaged supervisory rule extracts"
    )
    rules.set_defaults(handler=lambda _args: _print_help(rules))
    actions = rules.add_subparsers(dest="rules_command", metavar="<action>")

    listing = actions.add_parser("list", help="show the packaged rule extracts")
    listing.set_defaults(handler=_rules_list)

    importing = actions.add_parser(
        "import", help="rebuild an extract from a publisher's rule workbook"
    )
    _add_workbook_arguments(importing)
    importing.add_argument(
        "--out", required=True, type=Path, metavar="FILE", help="where to write the JSON extract"
    )
    importing.set_defaults(handler=_rules_import)

    checking = actions.add_parser(
        "check", help="fail if an extract is not exactly what the workbook yields"
    )
    _add_workbook_arguments(checking)
    checking.add_argument(
        "--against",
        type=Path,
        metavar="FILE",
        help="the extract to compare (default: the one packaged with rwa-filer)",
    )
    checking.set_defaults(handler=_rules_check)


def _add_workbook_arguments(parser: argparse.ArgumentParser) -> None:
    """The two arguments every workbook-reading action takes."""
    parser.add_argument(
        "--publisher",
        required=True,
        choices=sorted(_PUBLISHER_FRAMEWORK),
        help="whose rule workbook this is",
    )
    parser.add_argument("workbook", type=Path, metavar="WORKBOOK", help="the rule workbook (.xlsx)")


def _rules_list(_args: argparse.Namespace) -> int:
    """``rwa-filer rules list`` — one line per packaged extract."""
    _out(f"{'framework':<11}{'publisher':<11}{'version':<12}{'rules':>7}{'enforced':>10}  file")
    for framework in sorted(EXTRACT_FILES):
        ruleset = load_rules(framework)
        version = str(ruleset.source.get("framework_version", ""))
        _out(
            f"{framework:<11}{ruleset.publisher:<11}{version:<12}"
            f"{len(ruleset.rules):>7}{len(ruleset.enforced):>10}  {EXTRACT_FILES[framework]}"
        )
    return EXIT_OK


def _rules_import(args: argparse.Namespace) -> int:
    """``rwa-filer rules import`` — write a fresh extract."""
    workbook: Path = args.workbook
    if not workbook.is_file():
        return _fail(f"workbook not found: {workbook}")
    payload = importer.extract(args.publisher, workbook)
    importer.write_extract(payload, args.out)
    counts = payload["filter"]
    _out(f"wrote {args.out} ({counts['matched']} rules, {counts['live']} live)")
    return EXIT_OK


def _rules_check(args: argparse.Namespace) -> int:
    """``rwa-filer rules check`` — compare an extract against its workbook."""
    workbook: Path = args.workbook
    if not workbook.is_file():
        return _fail(f"workbook not found: {workbook}")

    against: Path | None = args.against
    if against is None:
        resource = extract_resource(_PUBLISHER_FRAMEWORK[args.publisher])
        label = f"packaged extract {resource.name}"
        committed = resource.read_text(encoding="utf-8") if resource.is_file() else None
    else:
        label = str(against)
        committed = against.read_text(encoding="utf-8") if against.is_file() else None

    payload = importer.extract(args.publisher, workbook)
    if importer.is_extract_current(payload, committed):
        _out(f"ok    {label}")
        return EXIT_OK
    state = "missing" if committed is None else "out of date"
    return _fail(f"{label} is {state}: it does not match {workbook.name}")


# =============================================================================
# Private helpers
# =============================================================================


def _print_help(parser: argparse.ArgumentParser) -> int:
    """Print a subcommand group's help when it is invoked with no action."""
    parser.print_help(sys.stdout)
    return EXIT_OK


def _out(line: str) -> None:
    """Write one line of command output to stdout."""
    sys.stdout.write(f"{line}\n")


def _fail(message: str) -> int:
    """Write a diagnostic to stderr and return the failure exit code."""
    sys.stderr.write(f"rwa-filer: {message}\n")
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
