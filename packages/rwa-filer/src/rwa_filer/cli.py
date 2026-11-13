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
        Validate a return (.parquet / .csv / .xlsx, or an XBRL instance .xbrl /
        .zip): structure against the taxonomy, then the published rules.
    rwa-filer build FILE --out DIR [--monetary-decimals N] [--zip] [--force]
        Validate a return and write its filing package: the .xbrl instance, a
        .zip where required, and a manifest.
        With --adjustments FILE --author NAME, apply cell overrides first and
        record them in the manifest and the audit ledger.
    rwa-filer signoff MANIFEST --approver NAME --role ROLE
        Record an approval of a built package, bound to the file's checksum.
    rwa-filer verify MANIFEST
        Check that a package on disk is the one that was built and signed off.
    rwa-filer diff PREVIOUS CURRENT
        What changed between two versions of a return, cell by cell.
    rwa-filer referee INSTANCE --taxonomy-package ZIP [--arelle-python PYTHON]
        A second opinion on a written instance: run the Arelle XBRL processor
        on it against the publisher's taxonomy package, and set its verdict on
        every rule beside this package's own. Needs Arelle (rwa-filer[arelle]).
    rwa-filer template --module CODE --reference-date DATE --out FILE [--tables ...]
        Write a blank workbook to fill in and validate.
    rwa-filer taxonomy list
        The packaged taxonomy packs and the dates they apply to.
    rwa-filer taxonomy compile ... --out DIR
        Build a taxonomy pack from the publisher's DPM files.
    rwa-filer rulebook list
        The packaged Bank of England rule books: modules, rules, rules enforced.
    rwa-filer rulebook import WORKBOOK --out DIR [--taxonomy-version V] [--taxonomy-package ZIP]
        Build a rule book from one of the Bank's validation-rule workbooks.
    rwa-filer rulebook check WORKBOOK [--taxonomy-version V] [--taxonomy-package ZIP]
        Fail if the packaged rule book is not exactly what the workbook yields.
    rwa-filer rules list
        The packaged rule extracts: framework, publisher, version and counts.
    rwa-filer rules import --publisher {eba,boe} WORKBOOK --out FILE
        Rebuild an extract from a publisher's rule workbook.
    rwa-filer rules check --publisher {eba,boe} WORKBOOK [--against FILE]
        Fail if the extract (the packaged one by default) is not exactly what
        the workbook yields.

Exit codes:
    0  success — for ``validate`` and ``build``, nothing blocks submission;
       for ``referee``, Arelle accepts the instance and the engines agree
    1  the command ran and the answer is "no" (a blocking finding, a stale
       extract, a missing file)
    2  usage error (argparse's own convention)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from rwa_filer import __version__
from rwa_filer.boe import importer as boe_importer
from rwa_filer.boe.catalogue import RULEBOOKS_DIRECTORY, available_rulebooks, load_rulebook
from rwa_filer.filing import BLOCKED_BY_STRUCTURE, build_filing
from rwa_filer.model import LEI_SCHEME, CanonicalReturn, ReturnHeader
from rwa_filer.readers import INSTANCE_SUFFIXES, SUPPORTED_SUFFIXES, SourceReading, load_source
from rwa_filer.referee import RefereePlanError, RefereeUnavailableError, run_referee
from rwa_filer.referee import report as referee_report
from rwa_filer.referee.differential import compare
from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES, extract_resource, load_rules
from rwa_filer.taxonomy.pack import PackNotFoundError, available_packs, resolve_pack, write_pack
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import validate_return
from rwa_filer.workflow import ledger as audit
from rwa_filer.workflow.adjustments import apply_adjustments, read_adjustments
from rwa_filer.workflow.diff import diff_returns
from rwa_filer.workflow.signoff import SignOffError, read_signoff, sign_off, verify_package
from rwa_filer.xbrl.writer import InstanceOptions

EXIT_OK = 0
EXIT_FAILED = 1

#: Changed cells listed by ``diff`` in text form; the JSON form lists them all.
_DIFF_ROWS_SHOWN = 40

_SOURCE_DESCRIPTION = (
    "{verb} FILE is a long-format fact table (.parquet or .csv), a workbook in the "
    "template layout (.xlsx), or an XBRL instance (.xbrl, or a .zip holding one). A fact "
    "table carries no header, so --entity, --reference-date and --module are required "
    "with it; a workbook or an instance carries its own, and any of them given here "
    "overrides it."
)

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
    _add_build_command(commands)
    _add_workflow_commands(commands)
    _add_referee_command(commands)
    _add_template_command(commands)
    _add_taxonomy_commands(commands)
    _add_rulebook_commands(commands)
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
        description=_SOURCE_DESCRIPTION.format(verb="Validate a return."),
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
    try:
        source = _load(args)
        validation = validate_return(source.ret, source.pack, source_findings=source.findings)
    except (ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))

    record = to_record(source.ret, validation)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _out(
        json.dumps(record, indent=2)
        if args.format == "json"
        else render_text(source.ret, validation)
    )
    return EXIT_OK if validation.is_submittable else EXIT_FAILED


def _load(args: argparse.Namespace) -> SourceReading:
    """Read the command's FILE, applying any header option given with it.

    Raises:
        ValueError: the file is missing, of an unsupported type, lacks a header
            it needs, or is not readable as what its suffix says it is.
    """
    path: Path = args.file
    suffix = path.suffix.lower()
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    if suffix not in (*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES):
        accepted = ", ".join((*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES))
        raise ValueError(f"unsupported file type {path.suffix!r}; expected one of {accepted}")
    carries_header = suffix == ".xlsx" or suffix in INSTANCE_SUFFIXES
    source = load_source(path, _header_from_args(args, required=not carries_header))
    return replace(source, ret=_apply_header_overrides(source.ret, args))


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
# build
# =============================================================================


def _add_build_command(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer build``."""
    build = commands.add_parser(
        "build",
        help="validate a return and write its filing package (.xbrl, manifest)",
        description=(
            _SOURCE_DESCRIPTION.format(verb="Validate a return and write its filing package.")
            + " Nothing is written while a structure finding stands, or — unless --force is "
            "given — while a published rule is broken."
        ),
    )
    build.add_argument("file", type=Path, metavar="FILE", help="the return to file")
    build.add_argument(
        "--out", type=Path, required=True, metavar="DIR", help="where the files are written"
    )
    _add_header_arguments(build)
    build.add_argument("--name", metavar="NAME", help="the files' base name")
    build.add_argument(
        "--monetary-decimals",
        type=int,
        default=InstanceOptions.monetary_decimals,
        metavar="N",
        help="the accuracy monetary figures are stated to: -3 thousands (default), "
        "0 units, 2 pence",
    )
    build.add_argument(
        "--percentage-decimals",
        type=int,
        default=InstanceOptions.percentage_decimals,
        metavar="N",
        help="the accuracy percentages and ratios are stated to (default 4, the minimum)",
    )
    build.add_argument(
        "--declare-unreported",
        action="store_true",
        help="also declare every template the return does not report as not reported",
    )
    build.add_argument("--zip", action="store_true", help="write a .zip whatever the size")
    build.add_argument(
        "--force",
        action="store_true",
        help="write the instance even though a published rule is broken",
    )
    build.add_argument(
        "--no-timestamp",
        action="store_true",
        help="omit the creation time, so the same return always gives the same bytes",
    )
    build.add_argument(
        "--adjustments",
        type=Path,
        metavar="FILE",
        help="cell overrides to apply first (.csv or .parquet: the fact columns plus "
        "`reason`, and optionally `remove`); needs --author",
    )
    build.add_argument("--author", metavar="NAME", help="who is preparing the filing")
    build.add_argument(
        "--ledger",
        type=Path,
        metavar="FILE",
        help="the audit ledger to append to (default: <name>.ledger.jsonl beside the files, "
        "when --author is given)",
    )
    build.set_defaults(handler=_build)


def _build(args: argparse.Namespace) -> int:
    """``rwa-filer build`` — read, validate, write the filing package."""
    now = datetime.now(UTC)
    if args.adjustments is not None and not args.author:
        return _fail("--adjustments needs --author: an override is recorded against a name")
    try:
        source = _load(args)
        ret, applied = source.ret, ()
        if args.adjustments is not None:
            if not args.adjustments.is_file():
                return _fail(f"file not found: {args.adjustments}")
            ret, applied = apply_adjustments(ret, read_adjustments(args.adjustments))
        options = InstanceOptions(
            monetary_decimals=args.monetary_decimals,
            percentage_decimals=args.percentage_decimals,
            created_at=None if args.no_timestamp else now,
            declare_unreported=args.declare_unreported,
        )
        package = build_filing(
            ret,
            args.out,
            pack=source.pack,
            options=options,
            name=args.name,
            allow_rule_breaks=args.force,
            always_zip=args.zip,
            source_findings=source.findings,
            adjustments=applied,
        )
    except (ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))
    source = replace(source, ret=ret)

    _out(render_text(source.ret, package.validation))
    if not package.written:
        reason = (
            "the return cannot be expressed in the taxonomy until the structure findings are fixed"
            if package.blocked_by == BLOCKED_BY_STRUCTURE
            else "the rule checks do not pass (--force writes the file anyway)"
        )
        _out(f"\nNOT WRITTEN: {reason}.")
        return EXIT_FAILED

    instance = package.instance
    assert instance is not None and package.instance_path is not None  # noqa: S101
    _out(
        f"\nWrote {package.instance_path}: {instance.facts} fact(s) from {instance.cells} "
        f"cell(s), {len(instance.filing_indicators)} template(s) reported, "
        f"{len(instance.content):,} bytes."
    )
    if package.zip_path is not None:
        _out(f"Wrote {package.zip_path} — this is the file to upload.")
    _out(f"Wrote {package.manifest_path}")
    if applied:
        _out(f"Applied {len(applied)} adjustment(s); each is recorded in the manifest.")
    if args.author:
        ledger = args.ledger or package.instance_path.with_name(
            f"{package.instance_path.stem}{audit.LEDGER_SUFFIX}"
        )
        try:
            if applied:
                audit.append_entry(
                    ledger,
                    audit.EVENT_ADJUSTMENT,
                    {"adjustments": [item.as_record() for item in applied]},
                    author=args.author,
                    at=now,
                )
            audit.append_entry(
                ledger,
                audit.EVENT_BUILD,
                {
                    "instance": package.instance_path.name,
                    "sha256": hashlib.sha256(instance.content).hexdigest(),
                    "facts": instance.facts,
                    "submittable": package.validation.is_submittable,
                    "forced": bool(args.force),
                },
                author=args.author,
                at=now,
            )
        except ValueError as exc:
            return _fail(str(exc))
        _out(f"Recorded in {ledger}")
    return EXIT_OK if package.validation.is_submittable else EXIT_FAILED


# =============================================================================
# signoff / verify / diff
# =============================================================================


def _add_workflow_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register ``rwa-filer signoff``, ``verify`` and ``diff``."""
    signing = commands.add_parser(
        "signoff",
        help="record an approval of a built package, bound to the file's checksum",
        description=(
            "Record who approved a filing package, in what capacity and when, against the "
            "SHA-256 of the instance. A file changed afterwards no longer verifies. A package "
            "the validation found not submittable is signed only with --acknowledge-findings."
        ),
    )
    signing.add_argument("manifest", type=Path, metavar="MANIFEST", help="<name>.manifest.json")
    signing.add_argument("--approver", required=True, metavar="NAME", help="who approves")
    signing.add_argument("--role", required=True, metavar="ROLE", help="in what capacity")
    signing.add_argument("--statement", metavar="TEXT", help="the approver's own words")
    signing.add_argument(
        "--acknowledge-findings",
        action="store_true",
        help="sign although the validation found something that blocks submission",
    )
    signing.add_argument(
        "--ledger", type=Path, metavar="FILE", help="the audit ledger (default: beside the files)"
    )
    signing.set_defaults(handler=_signoff)

    verifying = commands.add_parser(
        "verify",
        help="check a package on disk is the one that was built and signed off",
        description=(
            "Check that the instance and zip are the files the manifest describes, that the "
            "sign-off was given for exactly them, and that the audit ledger is intact."
        ),
    )
    verifying.add_argument("manifest", type=Path, metavar="MANIFEST", help="<name>.manifest.json")
    verifying.add_argument(
        "--ledger", type=Path, metavar="FILE", help="the audit ledger (default: beside the files)"
    )
    verifying.add_argument(
        "--unsigned", action="store_true", help="do not require a sign-off to be present"
    )
    verifying.set_defaults(handler=_verify)

    diffing = commands.add_parser(
        "diff",
        help="what changed between two versions of a return",
        description=(
            "Compare two returns cell by cell. Each may be any file `validate` reads; the "
            "header options apply to a fact table, which carries no header of its own."
        ),
    )
    diffing.add_argument("previous", type=Path, metavar="PREVIOUS", help="the earlier version")
    diffing.add_argument("current", type=Path, metavar="CURRENT", help="the later version")
    _add_header_arguments(diffing)
    diffing.add_argument(
        "--format", choices=["text", "json"], default="text", help="how to print the result"
    )
    diffing.set_defaults(handler=_diff)


def _ledger_beside(manifest: Path) -> Path:
    """The default ledger of the package ``manifest`` describes."""
    base = manifest.name.removesuffix(".manifest.json")
    return manifest.with_name(f"{base}{audit.LEDGER_SUFFIX}")


def _signoff(args: argparse.Namespace) -> int:
    """``rwa-filer signoff`` — record an approval and note it in the ledger."""
    manifest: Path = args.manifest
    ledger = args.ledger or _ledger_beside(manifest)
    now = datetime.now(UTC)
    try:
        if ledger.is_file() and (problems := audit.verify_ledger(ledger)):
            return _fail(f"the audit ledger does not verify: {problems[0]}")
        entry = None
        if ledger.is_file():
            approval_record = {
                "manifest": manifest.name,
                "approver": args.approver,
                "role": args.role,
            }
            entry = audit.append_entry(
                ledger, audit.EVENT_SIGNOFF, approval_record, author=args.approver, at=now
            )
        approval = sign_off(
            manifest,
            approver=args.approver,
            role=args.role,
            at=now,
            statement=args.statement,
            acknowledge_findings=args.acknowledge_findings,
            ledger_head=entry.hash if entry is not None else None,
        )
    except (SignOffError, ValueError) as exc:
        return _fail(str(exc))
    noted = " although the validation found blocking findings" if not approval.submittable else ""
    _out(
        f"Signed off by {approval.approver} ({approval.role}) at {approval.at}{noted}.\n"
        f"Instance SHA-256 {approval.instance_sha256}"
    )
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    """``rwa-filer verify`` — the package, its sign-off and its ledger."""
    manifest: Path = args.manifest
    problems = verify_package(manifest, require_signoff=not args.unsigned)
    ledger = args.ledger or _ledger_beside(manifest)
    if args.ledger is not None or ledger.is_file():
        problems += audit.verify_ledger(ledger)
        try:
            approval = read_signoff(manifest)
        except ValueError:
            approval = None
        if approval is not None and approval.ledger_head is not None and not problems:
            hashes = {entry.hash for entry in audit.read_ledger(ledger)}
            if approval.ledger_head not in hashes:
                problems.append("the audit ledger is not the one the sign-off was recorded in")
    if problems:
        for problem in problems:
            _out(f"FAILED  {problem}")
        return EXIT_FAILED
    _out(f"ok      {manifest.name}: the files, the sign-off and the ledger agree")
    return EXIT_OK


def _diff(args: argparse.Namespace) -> int:
    """``rwa-filer diff`` — two versions of a return, cell by cell."""
    try:
        previous = _load(argparse.Namespace(**{**vars(args), "file": args.previous})).ret
        current = _load(argparse.Namespace(**{**vars(args), "file": args.current})).ret
    except (ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))
    difference = diff_returns(previous, current)
    if args.format == "json":
        _out(json.dumps(difference.as_record(), indent=2))
        return EXIT_OK if difference.is_identical else EXIT_FAILED

    counts = difference.counts()
    _out(
        f"{'IDENTICAL' if difference.is_identical else 'DIFFERENT'}: {counts['changed']} changed, "
        f"{counts['added']} added, {counts['removed']} removed, {difference.unchanged} unchanged"
    )
    for name, (before, after) in difference.header.items():
        _out(f"  header  {name}: {before} -> {after}")
    for row in difference.changes.head(_DIFF_ROWS_SHOWN).iter_rows(named=True):
        sheet = f"[z{row['sheet']}]" if row["sheet"] else ""
        key = f"[{row['open_key']}]" if row["open_key"] else ""
        cell = f"{row['table']}{sheet}{key}[r{row['row']}][c{row['column']}]"
        before = row["before"] if row["before"] is not None else row["before_text"]
        after = row["after"] if row["after"] is not None else row["after_text"]
        _out(f"  {row['change']:<8}{cell}: {before} -> {after}")
    if difference.changes.height > _DIFF_ROWS_SHOWN:
        _out(f"  ... and {difference.changes.height - _DIFF_ROWS_SHOWN} more (use --format json)")
    return EXIT_OK if difference.is_identical else EXIT_FAILED


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


def _add_referee_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register ``rwa-filer referee``."""
    referee = commands.add_parser(
        "referee",
        help="have the Arelle XBRL processor check a written instance, rule by rule",
        description=(
            "Run Arelle on INSTANCE against the publisher's taxonomy package and report what "
            "it finds: XBRL validity, the filing rules, and a verdict on every published rule "
            "the instance's templates trigger. Unless --no-compare is given, this package's "
            "own rule engine is run on the same instance and the two are set side by side; a "
            "disagreement means one of them has misread a rule. Arelle is run as a "
            "subprocess, under --arelle-python, the RWA_FILER_ARELLE_PYTHON interpreter, or "
            "this one if it has arelle-release. A large module takes minutes and several GB."
        ),
    )
    referee.add_argument("instance", type=Path, metavar="INSTANCE", help="the .xbrl instance")
    referee.add_argument(
        "--taxonomy-package",
        required=True,
        type=Path,
        metavar="ZIP",
        help="the publisher's taxonomy package holding the instance's entry point",
    )
    referee.add_argument(
        "--arelle-python", type=Path, metavar="PYTHON", help="an interpreter that has Arelle"
    )
    referee.add_argument("--rules", metavar="REGEX", help="run only the rules whose id matches")
    referee.add_argument(
        "--workdir", type=Path, metavar="DIR", help="keep each worker's files here"
    )
    referee.add_argument("--chunk-mb", type=float, default=120.0, metavar="MB")
    referee.add_argument("--max-rss-gb", type=float, default=9.0, metavar="GB")
    referee.add_argument("--timeout", type=float, default=3600.0, metavar="SECONDS")
    referee.add_argument(
        "--no-filing-rules", action="store_true", help="skip the filing-rule plug-in"
    )
    referee.add_argument(
        "--no-compare", action="store_true", help="report Arelle alone, not the differential"
    )
    referee.add_argument("--format", choices=("text", "json"), default="text")
    referee.add_argument("--report", type=Path, metavar="FILE", help="also write the JSON here")
    referee.set_defaults(handler=_referee)


def _referee(args: argparse.Namespace) -> int:
    """``rwa-filer referee`` — Arelle's verdict, beside the native engine's."""
    instance: Path = args.instance
    package: Path = args.taxonomy_package
    for path, what in ((instance, "instance"), (package, "taxonomy package")):
        if not path.is_file():
            return _fail(f"{what} not found: {path}")
    if instance.suffix.lower() != ".xbrl":
        return _fail(f"the referee reads an .xbrl instance, not {instance.suffix!r}: {instance}")
    try:
        result = run_referee(
            instance,
            package,
            python=args.arelle_python,
            chunk_mb=args.chunk_mb,
            max_rss_gb=args.max_rss_gb,
            timeout=args.timeout,
            workdir=args.workdir,
            filing_rules=not args.no_filing_rules,
            rules=args.rules,
        )
        differential = None
        if not args.no_compare:
            source = load_source(instance)
            validation = validate_return(source.ret, source.pack, source_findings=source.findings)
            if validation.report is None:
                return _fail(f"no rule book is packaged for module {source.ret.header.module}")
            differential = compare(validation.report.results, result)
    except (RefereeUnavailableError, RefereePlanError, ValueError, PackNotFoundError) as exc:
        return _fail(str(exc))

    record = referee_report.to_record(result, differential)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _out(
        json.dumps(record, indent=2)
        if args.format == "json"
        else referee_report.render_text(instance.name, result, differential)
    )
    return EXIT_OK if referee_report.is_supported(result, differential) else EXIT_FAILED


def _add_rulebook_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register ``rwa-filer rulebook ...``."""
    rulebook = commands.add_parser(
        "rulebook", help="inspect and rebuild the packaged Bank of England rule books"
    )
    rulebook.set_defaults(handler=lambda _args: _print_help(rulebook))
    actions = rulebook.add_subparsers(dest="rulebook_command", metavar="<action>")

    listing = actions.add_parser("list", help="show the packaged rule books")
    listing.set_defaults(handler=_rulebook_list)

    for name, description, handler in (
        ("import", "build a rule book from a validation-rule workbook", _rulebook_import),
        (
            "check",
            "fail if the packaged rule book is not what the workbook yields",
            _rulebook_check,
        ),
    ):
        action = actions.add_parser(name, help=description)
        action.add_argument("workbook", type=Path, metavar="WORKBOOK", help="the workbook (.xlsx)")
        action.add_argument(
            "--taxonomy-version",
            metavar="V",
            help="the taxonomy release, e.g. 4.1.1 (default: the version in the file name)",
        )
        action.add_argument(
            "--taxonomy-package",
            type=Path,
            metavar="ZIP",
            help="the publisher's taxonomy package: also record which dimensions each "
            "rule's XBRL formula closes (the packaged rule books are built with it)",
        )
        if name == "import":
            action.add_argument(
                "--out", required=True, type=Path, metavar="DIR", help="where to write it"
            )
        action.set_defaults(handler=handler)


def _rulebook_list(_args: argparse.Namespace) -> int:
    """``rwa-filer rulebook list`` — one line per packaged rule book and module."""
    _out(f"{'framework version':<26}{'taxonomy':<10}{'rules':>7}  {'module':<10}{'enforced':>9}")
    for name in available_rulebooks():
        rulebook = load_rulebook(name)
        for module in rulebook.modules:
            _out(
                f"{rulebook.framework_version:<26}{rulebook.taxonomy:<10}"
                f"{len(rulebook.rules):>7}  {module:<10}{len(rulebook.enforced(module)):>9}"
            )
    return EXIT_OK


def _read_rulebook(args: argparse.Namespace) -> dict[str, Any]:
    """Import the command's WORKBOOK.

    Raises:
        ValueError: the workbook is missing or is not a rule workbook.
    """
    workbook: Path = args.workbook
    if not workbook.is_file():
        raise ValueError(f"workbook not found: {workbook}")
    package: Path | None = args.taxonomy_package
    if package is not None and not package.is_file():
        raise ValueError(f"taxonomy package not found: {package}")
    return boe_importer.import_workbook(
        workbook, taxonomy_version=args.taxonomy_version, taxonomy_package=package
    )


def _rulebook_import(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook import`` — write a rule book."""
    try:
        rulebook = _read_rulebook(args)
    except ValueError as exc:
        return _fail(str(exc))
    path = args.out / boe_importer.rulebook_file_name(rulebook)
    boe_importer.write_rulebook(rulebook, path)
    reach = (
        "with formula reach"
        if boe_importer.has_formula_reach(rulebook)
        else "WITHOUT formula reach: no --taxonomy-package"
    )
    _out(f"wrote {path} ({len(rulebook['rules'])} rules, {reach})")
    return EXIT_OK


def _rulebook_check(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook check`` — compare the packaged rule book with its workbook."""
    try:
        rulebook = _read_rulebook(args)
    except ValueError as exc:
        return _fail(str(exc))
    name = boe_importer.rulebook_file_name(rulebook)
    packaged = Path(str(boe_importer.__file__)).parent / RULEBOOKS_DIRECTORY / name
    if boe_importer.is_rulebook_current(rulebook, packaged):
        checked = (
            ""
            if boe_importer.has_formula_reach(rulebook)
            else " (workbook content only; formula reach not checked: no --taxonomy-package)"
        )
        _out(f"ok    packaged rule book {name}{checked}")
        return EXIT_OK
    state = "out of date" if packaged.is_file() else "missing"
    return _fail(f"packaged rule book {name} is {state}: it does not match {args.workbook.name}")


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
