"""
The ``rwa-filer`` command line.

Pipeline position:
    shell  ->  rwa_filer.cli.main  ->  the package's public API

Key responsibilities:
- Parse the command line and dispatch to a subcommand.
- Write results to stdout and diagnostics to stderr, and return a process exit
  code. This module holds no validation or filing logic of its own.

Commands:
    rwa-filer validate FILE [--entity ID --reference-date DATE --module CODE]
        Validate a return (.parquet / .csv / .xlsx): structure against the
        taxonomy, then the published rules.
    rwa-filer template --module CODE --reference-date DATE --out FILE [--tables ...]
        Write a blank workbook to fill in and validate.
    rwa-filer taxonomy list
        The packaged taxonomy packs and the dates they apply to.
    rwa-filer taxonomy compile ... --out DIR
        Build a taxonomy pack from the publisher's DPM files.
    rwa-filer rules list
        The packaged rule extracts: framework, publisher, version and counts.
    rwa-filer rules import --publisher {eba,boe} WORKBOOK --out FILE
        Rebuild an extract from a publisher's rule workbook.
    rwa-filer rules check --publisher {eba,boe} WORKBOOK [--against FILE]
        Fail if the extract (the packaged one by default) is not exactly what
        the workbook yields.

Exit codes:
    0  success — for ``validate``, nothing blocks submission
    1  the command ran and the answer is "no" (a blocking finding, a stale
       extract, a missing file)
    2  usage error (argparse's own convention)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

from rwa_filer import __version__
from rwa_filer.model import LEI_SCHEME, CanonicalReturn, ReturnHeader
from rwa_filer.readers import SUPPORTED_SUFFIXES, read_return
from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES, extract_resource, load_rules
from rwa_filer.taxonomy.pack import PackNotFoundError, available_packs, resolve_pack, write_pack
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import validate_return

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
    _add_validate_command(commands)
    _add_template_command(commands)
    _add_taxonomy_commands(commands)
    _add_rules_commands(commands)
    return parser


# =============================================================================
# validate
# =============================================================================


def _add_validate_command(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer validate``."""
    validate = commands.add_parser(
        "validate",
        help="validate a return against the taxonomy and the published rules",
        description=(
            "Validate a return. FILE is a long-format fact table (.parquet or .csv) or a "
            "workbook in the template layout (.xlsx). A fact table carries no header, so "
            "--entity, --reference-date and --module are required with it; a workbook "
            "carries its own, and any of them given here overrides it."
        ),
    )
    validate.add_argument("file", type=Path, metavar="FILE", help="the return to validate")
    _add_header_arguments(validate)
    validate.add_argument(
        "--format", choices=["text", "json"], default="text", help="how to print the result"
    )
    validate.add_argument(
        "--report", type=Path, metavar="FILE", help="also write the full JSON report here"
    )
    validate.set_defaults(handler=_validate)


def _add_header_arguments(parser: argparse.ArgumentParser) -> None:
    """The return-header options shared by the commands that need one."""
    parser.add_argument("--entity", metavar="ID", help="the reporting entity's identifier (LEI)")
    parser.add_argument(
        "--entity-scheme",
        metavar="URI",
        default=None,
        help=f"the identifier scheme (default: the LEI scheme, {LEI_SCHEME})",
    )
    parser.add_argument(
        "--reference-date", type=date.fromisoformat, metavar="YYYY-MM-DD", help="the as-at date"
    )
    parser.add_argument("--module", metavar="CODE", help="the reporting module, e.g. PRA001")
    parser.add_argument("--currency", metavar="CCY", help="the reporting currency (default GBP)")


def _validate(args: argparse.Namespace) -> int:
    """``rwa-filer validate`` — read, validate, report."""
    path: Path = args.file
    if not path.is_file():
        return _fail(f"file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return _fail(
            f"unsupported file type {path.suffix!r}; expected one of {', '.join(SUPPORTED_SUFFIXES)}"
        )
    try:
        ret = read_return(path, _header_from_args(args, required=path.suffix.lower() != ".xlsx"))
        ret = _apply_header_overrides(ret, args)
        validation = validate_return(ret)
    except (ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))

    record = to_record(ret, validation)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _out(json.dumps(record, indent=2) if args.format == "json" else render_text(ret, validation))
    return EXIT_OK if validation.is_submittable else EXIT_FAILED


def _header_from_args(args: argparse.Namespace, *, required: bool) -> ReturnHeader | None:
    """A header from the command line, or ``None`` when the file supplies its own.

    Raises:
        ValueError: the file needs a header and the three required options were
            not all given.
    """
    given = (args.entity, args.reference_date, args.module)
    if not all(given):
        if required:
            raise ValueError(
                "a fact table carries no header: --entity, --reference-date and --module "
                "are all required"
            )
        return None
    return ReturnHeader(
        entity_identifier=args.entity,
        reference_date=args.reference_date,
        module=args.module,
        currency=args.currency or "GBP",
        entity_scheme=args.entity_scheme or LEI_SCHEME,
    )


def _apply_header_overrides(ret: CanonicalReturn, args: argparse.Namespace) -> CanonicalReturn:
    """Apply any header option given on the command line over a workbook's own header."""
    overrides = {
        "entity_identifier": args.entity,
        "reference_date": args.reference_date,
        "module": args.module,
        "currency": args.currency,
        "entity_scheme": args.entity_scheme,
    }
    changed = {name: value for name, value in overrides.items() if value is not None}
    return replace(ret, header=replace(ret.header, **changed)) if changed else ret


# =============================================================================
# template
# =============================================================================


def _add_template_command(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer template``."""
    template = commands.add_parser(
        "template",
        help="write a blank workbook to fill in and validate",
        description=(
            "Write a blank workbook in the template layout: one worksheet per table and "
            "sheet, with the cells the taxonomy does not accept shaded grey."
        ),
    )
    template.add_argument("--module", required=True, metavar="CODE", help="e.g. PRA001")
    template.add_argument(
        "--reference-date",
        required=True,
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="selects the taxonomy version in force on that date",
    )
    template.add_argument(
        "--tables",
        nargs="+",
        metavar="TABLE",
        help="table codes to include (default: every table of the module)",
    )
    template.add_argument("--out", required=True, type=Path, metavar="FILE", help="the .xlsx")
    template.set_defaults(handler=_template)


def _template(args: argparse.Namespace) -> int:
    """``rwa-filer template`` — write a blank workbook."""
    from rwa_filer.readers.excel import write_workbook

    try:
        pack = resolve_pack(args.module, args.reference_date)
        written = write_workbook(pack, args.out, tables=args.tables)
    except (ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))
    _out(f"wrote {args.out} ({written} worksheet(s), {pack.info.module} {pack.info.version})")
    return EXIT_OK


# =============================================================================
# taxonomy
# =============================================================================


def _add_taxonomy_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer taxonomy ...``."""
    taxonomy = commands.add_parser("taxonomy", help="inspect and build taxonomy packs")
    taxonomy.set_defaults(handler=lambda _args: _print_help(taxonomy))
    actions = taxonomy.add_subparsers(dest="taxonomy_command", metavar="<action>")

    listing = actions.add_parser("list", help="show the packaged taxonomy packs")
    listing.set_defaults(handler=_taxonomy_list)

    compiling = actions.add_parser(
        "compile",
        help="build a taxonomy pack from the publisher's DPM files",
        description=(
            "Compile a taxonomy pack from the publisher's annotated-templates workbook, "
            "DPM dictionary and XBRL taxonomy package. Needs rwa-filer[excel]."
        ),
    )
    compiling.add_argument("--annotated", required=True, type=Path, metavar="XLSX")
    compiling.add_argument("--dictionary", required=True, type=Path, metavar="XLSX")
    compiling.add_argument(
        "--taxonomy", required=True, type=Path, metavar="ZIP_OR_DIR", help="the taxonomy package"
    )
    compiling.add_argument("--module", required=True, metavar="CODE", help="e.g. PRA001")
    compiling.add_argument(
        "--valid-from",
        required=True,
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="first reference date the pack applies to",
    )
    compiling.add_argument("--valid-to", type=date.fromisoformat, metavar="YYYY-MM-DD")
    compiling.add_argument(
        "--out", required=True, type=Path, metavar="DIR", help="the directory to write the pack to"
    )
    compiling.set_defaults(handler=_taxonomy_compile)


def _taxonomy_list(_args: argparse.Namespace) -> int:
    """``rwa-filer taxonomy list`` — one line per packaged pack."""
    _out(f"{'module':<10}{'version':<10}{'valid from':<13}{'valid to':<13}entry point")
    for info in available_packs():
        until = info.valid_to.isoformat() if info.valid_to else "-"
        _out(
            f"{info.module:<10}{info.version:<10}{info.valid_from.isoformat():<13}"
            f"{until:<13}{info.entry_point}"
        )
    return EXIT_OK


def _taxonomy_compile(args: argparse.Namespace) -> int:
    """``rwa-filer taxonomy compile`` — build and write a pack."""
    from rwa_filer.taxonomy.compiler import compile_pack

    for path in (args.annotated, args.dictionary, args.taxonomy):
        if not path.exists():
            return _fail(f"not found: {path}")
    compiled = compile_pack(args.annotated, args.dictionary, args.taxonomy, module=args.module)
    info = write_pack(compiled, args.out, valid_from=args.valid_from, valid_to=args.valid_to)
    cells = sum(len(table["cells"]) for table in compiled["tables"].values())
    _out(
        f"wrote {args.out} ({info.module} {info.version}: {len(compiled['tables'])} tables, "
        f"{cells} cells, {len(compiled['datapoints'])} data points)"
    )
    return EXIT_OK


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
