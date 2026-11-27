"""
The ``rwa-filer`` command line.

Pipeline position:
    shell  ->  rwa_filer.entry.run  ->  rwa_filer.cli.main  ->  the package's public API

Key responsibilities:
- Parse the command line and dispatch to a subcommand. ``main(argv)`` is also
  the in-process way to run a command: it leaves the process it is called in
  as it found it. (While it loads a taxonomy pack or reads an XBRL instance the
  library pauses the cyclic collector for the whole interpreter and then puts it
  back - ``rwa_filer._gc.collector_paused``.) What is right only for a process
  that runs one command and ends — the garbage-collector policy — belongs to
  ``rwa_filer.entry``.
- Write results to stdout and diagnostics to stderr, and return a process exit
  code. This module holds no validation or filing logic of its own.
- Report a missing optional extra (``MissingExtraError``, from whichever
  command reached the workbook) as one diagnostic line, not a traceback.
- Report an input that is not what the command reads (``rwa_filer.inputs``
  raises a ``ValueError`` naming it) as one line, and refuse an output path
  that writing would certainly fail on before the command does its work.
- Say, on stderr, how far a long validation has got (``rwa_filer.progress``):
  a full return takes tens of seconds, and silence reads as a hang.

Commands:
    rwa-filer validate FILE [--entity ID --reference-date DATE --module CODE]
                       [--monetary-decimals N] [--evidence FILE] [--require-complete]
                       [--taxonomy VERSION] [--submission-date DATE]
                       [--breakdown COLUMNS [--group-code CODE] [--line-ref COLUMN]
                        [--on-repeat stop|keep-one]]
                       [--progress | --no-progress]
        Validate a return (.parquet / .csv / .xlsx, or an XBRL instance .xbrl /
        .zip): structure against the taxonomy, then the published rules, as the
        Bank's gateway runs them on the submission date (default today: its
        validations deny list switches some off, or makes them warnings). With
        --evidence, also write every rule outcome, evaluation and comparison
        behind the verdict as a JSON Lines file (.jsonl, or .jsonl.gz).
        --taxonomy names the release (default: the one live for the module);
        every command that reads a return takes it. --progress says on stderr
        which step the check is on and how many rules are done; it is on by
        default when stderr is a terminal (``validate``, ``build``, ``dash``).
        --breakdown reads a fact table of several rows per cell: the rows of a
        cell are added together, the named columns say where each came from,
        and after the report each broken rule is traced to the members that
        break it on their own figures. --line-ref names the column each line's
        reference is in; one given twice in a cell stops the run, or with
        --on-repeat keep-one an exact repeat is dropped. ``build`` takes the
        same options. With --group-code both commands use the named group's facts
        and keep the other units for investigation. The manifest records the selection.
    rwa-filer build FILE --out DIR [--monetary-decimals N] [--zip] [--force]
                    [--evidence FILE]
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
    rwa-filer compare BASELINE CANDIDATE [--tolerance AMOUNT] [--submission-date DATE]
        A return beside the one another system (or an earlier filing) produced:
        every cell categorised, and the material differences grouped into
        findings, each saying which return the Bank's rules point at — the
        rules as the gateway runs them on the submission date, as ``validate``.
    rwa-filer referee INSTANCE --taxonomy-package ZIP [--arelle-python PYTHON]
        A second opinion on a written instance: run the Arelle XBRL processor
        on it against the publisher's taxonomy package, and set its verdict on
        every rule beside this package's own. Needs Arelle (rwa-filer[arelle]).
    rwa-filer template --module CODE --out FILE [--taxonomy VERSION] [--tables ...]
        Write a blank workbook to fill in and validate.
    rwa-filer dash [FILE] [--port N] [--no-browser]
        Start the local web dashboard, and open FILE in it if one is given.
    rwa-filer taxonomy list [--module CODE]
        The shipped taxonomy releases: each module's status in each, its dates,
        and which release a run uses by default.
    rwa-filer taxonomy compile ... --out DIR
        Build a taxonomy pack from the publisher's DPM files.
    rwa-filer rulebook list
        The packaged Bank of England rule books: modules, rules, rules enforced.
    rwa-filer rulebook import WORKBOOK --out DIR [--taxonomy-version V] [--taxonomy-package ZIP]
        Build a rule book from one of the Bank's validation-rule workbooks.
    rwa-filer rulebook check WORKBOOK [--taxonomy-version V] [--taxonomy-package ZIP]
        Fail if the packaged rule book is not exactly what the workbook yields.
    rwa-filer rulebook deny-list [--taxonomy V] [--module CODE] [--on DATE] [--format F]
        The Bank's validations deny list packaged for each release: the rules
        its gateway no longer runs, or runs as warnings, from which date, and
        the known issue behind each.
    rwa-filer rulebook deny-list import WORKBOOK --release V [--known-issues XLSX] --out DIR
    rwa-filer rulebook deny-list check WORKBOOK --release V [--known-issues XLSX]
        Build a release's deny list from the Bank's workbook, or fail if the
        packaged one is not exactly what it yields. Codes that match no rule of
        the release are reported.
    rwa-filer rulebook issues [ISSUE] [--taxonomy V] [--module CODE] [--format F]
        The known issues with the published rules, packaged for each release:
        every issue on one line, or one in full; --format markdown renders the
        register as the write-up to share with the Bank, --format json as data.
        A validation labels each result an issue explains; the verdict is never
        changed by it.
    rwa-filer rules list
        The packaged rule extracts: framework, publisher, version and counts.
    rwa-filer rules import --publisher {eba,boe} WORKBOOK --out FILE
        Rebuild an extract from a publisher's rule workbook.
    rwa-filer rules check --publisher {eba,boe} WORKBOOK [--against FILE]
        Fail if the extract (the packaged one by default) is not exactly what
        the workbook yields.

Exit codes:
    0  success — for ``validate`` and ``build``, nothing blocks submission;
       for ``referee``, Arelle accepts the instance and the engines agree;
       for ``diff``, the returns are identical; for ``compare``, equivalent
    1  the command ran and the answer is "no" (a blocking finding, a stale
       extract, a missing file, a file that is not what the command reads, an
       output path in the way), or it needs an extra that is not installed
    2  usage error (argparse's own convention)
    3  ``validate --require-complete`` only: nothing blocks submission, but the
       check was INCOMPLETE — linked templates left out, rules this engine
       cannot evaluate, and so on (the report's ``completeness``)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rwa_filer import __version__
from rwa_filer.boe import deny_importer
from rwa_filer.boe import importer as boe_importer
from rwa_filer.boe.catalogue import RULEBOOKS_DIRECTORY, available_rulebooks, load_rulebook
from rwa_filer.boe.deny import DENY_DIRECTORY, deny_list_file
from rwa_filer.boe.engine import MAX_FAILURES, Accuracy
from rwa_filer.boe.issues_document import render_document, render_issue, render_listing
from rwa_filer.entry import keep_collecting, run
from rwa_filer.evidence import collect_evidence, write_evidence
from rwa_filer.extras import MissingExtraError
from rwa_filer.filing import BLOCKED_BY_STRUCTURE, build_filing
from rwa_filer.model import LEI_SCHEME, CanonicalReturn, ReturnHeader
from rwa_filer.progress import StreamProgress
from rwa_filer.readers import (
    SUPPORTED_SUFFIXES,
    DetailSpec,
    HeaderFields,
    SourceReading,
    carries_header,
    load_source,
    open_source,
)
from rwa_filer.readers.detail import ON_REPEAT_CHOICES, ON_REPEAT_STOP
from rwa_filer.referee import (
    RefereePlanError,
    RefereeUnavailableError,
    interrupt_on_sigterm,
    run_referee,
)
from rwa_filer.referee import report as referee_report
from rwa_filer.referee.differential import compare
from rwa_filer.release import (
    ReleaseNotFoundError,
    default_release_version,
    module_releases,
    release_choice,
    release_deny_list,
    release_issues,
    release_lines,
    release_packs,
    release_record,
    resolve_release,
    shipped_releases,
)
from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES, extract_resource, load_rules
from rwa_filer.taxonomy.pack import write_pack
from rwa_filer.validate.identity import source_identity
from rwa_filer.validate.report import render_text, to_record
from rwa_filer.validate.returns import VERDICT_INCOMPLETE, validate_return
from rwa_filer.validate.review import ReviewFilter
from rwa_filer.workflow.acts import (
    ledger_beside,
    ledger_for_instance,
    record_build,
    record_signoff,
    verify_filing,
)
from rwa_filer.workflow.adjustments import apply_adjustments, read_adjustments
from rwa_filer.workflow.attribution import as_record as attribution_record
from rwa_filer.workflow.attribution import attribute, describe
from rwa_filer.workflow.compare import compare_returns
from rwa_filer.workflow.compare import render_text as render_comparison
from rwa_filer.workflow.diff import diff_returns
from rwa_filer.workflow.explain import Names
from rwa_filer.workflow.signoff import SignOffError
from rwa_filer.xbrl.writer import InstanceOptions

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.validate.returns import ReturnValidation
    from rwa_filer.workflow.attribution import Attribution

EXIT_OK = 0
EXIT_FAILED = 1
#: ``validate --require-complete``: nothing blocks, but the check was incomplete.
EXIT_INCOMPLETE = 3

#: The port ``rwa-filer dash`` tries first. It listens on this machine only.
DASH_PORT = 8765

#: Changed cells listed by ``diff`` in text form; the JSON form lists them all.
_DIFF_ROWS_SHOWN = 40
#: The help of every command's ``--format`` option.
_FORMAT_HELP = "how to print the result"

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
    try:
        return handler(args)
    except MissingExtraError as exc:
        # Caught here, not per handler, so that every command which can reach a
        # workbook is covered, including one added later. Only this subclass: an
        # import error in the package itself is a defect, and its traceback is the
        # report.
        return _fail(str(exc))


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="rwa-filer",
        description=(
            "Validate regulatory returns against the published supervisory rules "
            "and write them for submission."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"rwa-filer {__version__} (taxonomy releases: {', '.join(shipped_releases())})",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    _add_validate_command(commands)
    _add_build_command(commands)
    _add_workflow_commands(commands)
    _add_referee_command(commands)
    _add_template_command(commands)
    _add_dash_command(commands)
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
    _add_detail_arguments(validate)
    _add_accuracy_arguments(validate)
    validate.add_argument(
        "--warning-materiality",
        default="",
        metavar="AMOUNT",
        help="hide monetary warning occurrences below this excess in reporting currency (text working list)",
    )
    validate.add_argument(
        "--warning-materiality-bps",
        default="",
        metavar="BPS",
        help="hide percentage warnings below this excess in basis points (text working list)",
    )
    validate.add_argument(
        "--hide-zero-null-errors",
        action="store_true",
        help="hide errors and warnings caused solely by a zero in a must-be-empty cell (text working list)",
    )
    validate.add_argument(
        "--errors-only",
        action="store_true",
        help="show only errors in the text working list and breakdown",
    )
    validate.add_argument("--format", choices=["text", "json"], default="text", help=_FORMAT_HELP)
    validate.add_argument(
        "--report", type=Path, metavar="FILE", help="also write the full JSON report here"
    )
    _add_evidence_argument(validate)
    _add_submission_date_argument(validate)
    validate.add_argument(
        "--require-complete",
        action="store_true",
        help="exit 3 when nothing blocks submission but the check was incomplete "
        "(linked templates left out, rules that could not be evaluated)",
    )
    validate.add_argument(
        "--no-timestamp",
        action="store_true",
        help="leave the creation time out of the evidence file, so the same inputs give "
        "the same bytes",
    )
    _add_progress_argument(validate)
    validate.set_defaults(handler=_validate)


def _add_detail_arguments(parser: argparse.ArgumentParser) -> None:
    """The options that read a fact table as a detail, shared by ``validate`` and ``build``."""
    parser.add_argument(
        "--breakdown",
        metavar="COLUMNS",
        help="columns identifying the parts of each cell (e.g. business_unit,source); "
        "monetary lines are added unless a supplied group is selected",
    )
    parser.add_argument(
        "--group-code",
        metavar="CODE",
        help="validate and file the rows bearing this code in the reporting-unit breakdown "
        "column; use the other units to investigate breaks",
    )
    parser.add_argument(
        "--line-ref",
        metavar="COLUMN",
        help="the column each line's own reference is in (a loan, a lease, a journal line): "
        "one given twice in a cell is the same line counted twice",
    )
    parser.add_argument(
        "--on-repeat",
        choices=ON_REPEAT_CHOICES,
        default=ON_REPEAT_STOP,
        help="a line reference given twice in one cell: stop (default), or keep-one to keep "
        "the first of rows that agree on everything and stop where they differ",
    )


def _add_accuracy_arguments(parser: argparse.ArgumentParser) -> None:
    """The accuracy options ``validate`` and ``build`` share.

    One definition, so the two cannot drift: the rules' rounding allowances for
    a fact that states no accuracy of its own come from these, and ``build``
    writes the file with them.
    """
    parser.add_argument(
        "--monetary-decimals",
        type=int,
        default=InstanceOptions.monetary_decimals,
        metavar="N",
        help="the accuracy monetary figures are stated to: -3 thousands (default), "
        "0 units, 2 pence",
    )
    parser.add_argument(
        "--percentage-decimals",
        type=int,
        default=InstanceOptions.percentage_decimals,
        metavar="N",
        help="the accuracy percentages and ratios are stated to (default 4, the minimum)",
    )


def _add_submission_date_argument(parser: argparse.ArgumentParser) -> None:
    """``--submission-date``: the day whose gateway configuration the rules run under."""
    parser.add_argument(
        "--submission-date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="the day the return will be submitted: the Bank's validations deny list in "
        "force that day decides which rules its gateway runs, and as what (default: today)",
    )


def _add_evidence_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evidence",
        type=Path,
        metavar="FILE",
        help="also write every rule outcome, evaluation and comparison behind the verdict "
        "here, as JSON Lines (.jsonl; .jsonl.gz to compress)",
    )


def _add_progress_argument(parser: argparse.ArgumentParser) -> None:
    """``--progress`` / ``--no-progress``: whether to say how far the check has got."""
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="say on stderr which step the check is on and how many rules are done "
        "(default: when stderr is a terminal)",
    )


def _watching(args: argparse.Namespace) -> contextlib.AbstractContextManager[StreamProgress | None]:
    """The progress printer the command's ``--progress`` asks for, or none.

    Asked for or not, it writes to stderr only — stdout carries the result, and
    is often piped into a file or another program. On a terminal it is one line
    rewritten in place and cleared before the result is printed; anywhere else
    (``--progress`` into a log) it is one line per step.
    """
    terminal = _is_terminal(sys.stderr)
    wanted = terminal if args.progress is None else args.progress
    if not wanted:
        return contextlib.nullcontext()
    return StreamProgress(sys.stderr, live=terminal)


def _accuracy(args: argparse.Namespace) -> Accuracy | None:
    """The accuracy the options ask for; ``None`` when both are the defaults."""
    asked = (args.monetary_decimals, args.percentage_decimals)
    default = Accuracy()
    if asked == (default.monetary_decimals, default.percentage_decimals):
        return None
    return Accuracy(*asked)


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
    _add_taxonomy_argument(parser)


def _add_taxonomy_argument(parser: argparse.ArgumentParser) -> None:
    """``--taxonomy VERSION``: the release a command reads the return against."""
    parser.add_argument(
        "--taxonomy",
        metavar="VERSION",
        help=(
            "the taxonomy release to use, e.g. 4.1.1 (default: the release live for the "
            "return's module; see `rwa-filer taxonomy list`)"
        ),
    )


def _validate(args: argparse.Namespace) -> int:
    """``rwa-filer validate`` — read, validate, report."""
    if problem := _unwritable(args.report, "--report") or _unwritable(args.evidence, "--evidence"):
        return _fail(problem)
    try:
        review = ReviewFilter.from_text(
            args.warning_materiality,
            args.warning_materiality_bps,
            args.hide_zero_null_errors,
            errors_only=args.errors_only,
        )
        limit = (
            None
            if review.active or args.report is not None or args.format == "json"
            else MAX_FAILURES
        )
        with _watching(args) as progress:
            source = _load(args, progress=progress)
            accuracy, identity = _accuracy(args), source_identity(args.file)
            # Tracing keeps every evaluation in memory: only when evidence is asked for.
            evidence = None
            if args.evidence is not None:
                evidence = collect_evidence(
                    source.ret,
                    max_failures=None,
                    release=source.release,
                    accuracy=accuracy,
                    source_findings=source.findings,
                    source=identity,
                    submission_date=args.submission_date,
                    progress=progress,
                )
                validation = evidence.validation
            else:
                validation = validate_return(
                    source.ret,
                    release=source.release,
                    accuracy=accuracy,
                    source_findings=source.findings,
                    source=identity,
                    max_failures=limit,
                    submission_date=args.submission_date,
                    progress=progress,
                )
    except (ValueError, ReleaseNotFoundError) as exc:
        return _fail(str(exc))

    breakdown = _attributions(source, validation)
    # The record costs a fingerprint per enforced rule and one of every fact, and
    # only --report and --format json read it: the text report is built from the
    # validation itself. A run that also writes evidence hands its identity block
    # along, so the facts are fingerprinted once for the record and the file.
    record: dict[str, Any] | None = None
    if args.report is not None or args.format == "json":
        record = to_record(
            source.ret, validation, identity=None if evidence is None else evidence.identity
        )
        if breakdown:
            record["breakdown"] = {
                "detail": source.detail.as_record() if source.detail else None,
                "by": [attribution_record(item) for item in breakdown],
            }
            if source.detail is not None and source.detail.spec.group_code is not None:
                record["breakdown"]["text_cells"] = source.detail.text_cells(source.ret)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if evidence is not None:
        written = write_evidence(
            evidence, args.evidence, generated_at=None if args.no_timestamp else datetime.now(UTC)
        )
        sys.stderr.write(
            f"Wrote {written.path}: {written.records['rule']} rule(s), "
            f"{written.records['evaluation']} evaluation(s), {written.records['cell']} cell(s)\n"
        )
    _out(
        json.dumps(record, indent=2)
        if args.format == "json"
        else render_text(source.ret, validation, review=review)
    )
    if breakdown and args.format != "json":
        if source.detail is not None and source.detail.spec.group_code is not None:
            _out(
                f"Validated group {source.detail.spec.group_code!r} in "
                f"{source.detail.dimensions[0]} ({source.detail.group_rows} group facts)."
            )
        labels = {
            rule.rule_id: (rule.label or "").rstrip("|").strip() for rule in _rules_of(validation)
        }
        for item in breakdown:
            _out("\n" + "\n".join(describe(item.reviewed(validation, review), labels=labels)))
    if not validation.is_submittable:
        return EXIT_FAILED
    if args.require_complete and validation.status == VERDICT_INCOMPLETE:
        return EXIT_INCOMPLETE
    return EXIT_OK


def _load(args: argparse.Namespace, *, progress: StreamProgress | None = None) -> SourceReading:
    """Read the command's FILE, applying any header option given with it.

    Raises:
        ValueError: the file is missing, of an unsupported type, lacks a header
            it needs, or is not readable as what its suffix says it is.
        ReleaseNotFoundError: the taxonomy release could not be resolved.
    """
    return open_source(
        args.file,
        _header_fields(args),
        taxonomy=args.taxonomy,
        progress=progress,
        detail=_detail_spec(args),
    )


def _detail_spec(args: argparse.Namespace) -> DetailSpec | None:
    """The detail ``--breakdown`` / ``--line-ref`` ask for; ``None`` for a command without them."""
    breakdown, line_ref = getattr(args, "breakdown", None), getattr(args, "line_ref", None)
    group_code = getattr(args, "group_code", None)
    if not breakdown and not line_ref and group_code is None:
        return None
    return DetailSpec.from_text(breakdown, line_ref, getattr(args, "on_repeat", None), group_code)


def _attributions(source: SourceReading, validation: ReturnValidation) -> list[Attribution]:
    """Each breakdown column's attribution of the return's breaks; none without a detail."""
    detail = source.detail
    if detail is None:
        return []
    return [attribute(source.ret, validation, detail, dimension) for dimension in detail.dimensions]


def _rules_of(validation: ReturnValidation) -> tuple[Rule, ...]:
    """The rules the validation ran, for their published labels."""
    if validation.rulebook is None:
        return ()
    return validation.rulebook.enforced(validation.pack.info.module)


def _header_fields(args: argparse.Namespace) -> HeaderFields:
    """The return-header options given on the command line."""
    return HeaderFields(
        entity=args.entity,
        reference_date=args.reference_date,
        module=args.module,
        currency=args.currency,
        entity_scheme=args.entity_scheme,
    )


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
    _add_detail_arguments(build)
    build.add_argument("--name", metavar="NAME", help="the files' base name")
    _add_accuracy_arguments(build)
    _add_evidence_argument(build)
    _add_submission_date_argument(build)
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
    _add_progress_argument(build)
    build.set_defaults(handler=_build)


def _build(args: argparse.Namespace) -> int:
    """``rwa-filer build`` — read, validate, write the filing package."""
    now = datetime.now(UTC)
    if args.adjustments is not None and not args.author:
        return _fail("--adjustments needs --author: an override is recorded against a name")
    problem = (
        _unwritable(args.out, "--out", directory=True)
        or _unwritable(args.ledger, "--ledger")
        or _unwritable(args.evidence, "--evidence")
    )
    if problem:
        return _fail(problem)
    if args.adjustments is not None and not args.adjustments.is_file():
        return _fail(f"file not found: {args.adjustments}")
    try:
        with _watching(args) as progress:
            source = _load(args, progress=progress)
            ret, applied = source.ret, ()
            if args.adjustments is not None:
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
                release=source.release,
                options=options,
                name=args.name,
                allow_rule_breaks=args.force,
                always_zip=args.zip,
                source_findings=source.findings,
                adjustments=applied,
                evidence=args.evidence,
                source=source_identity(args.file),
                submission_date=args.submission_date,
                progress=progress,
                detail=source.detail,
            )
    except (ValueError, ReleaseNotFoundError) as exc:
        return _fail(str(exc))
    source = replace(source, ret=ret)

    _out(render_text(source.ret, package.validation))
    if package.evidence is not None:
        _out(
            f"\nWrote {package.evidence.path}: the evidence behind this verdict "
            f"({package.evidence.records['evaluation']} evaluation(s))."
        )
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
        ledger = args.ledger or ledger_for_instance(package.instance_path)
        try:
            record_build(
                ledger,
                package,
                applied=applied,
                forced=bool(args.force),
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
    """Register ``rwa-filer signoff``, ``verify``, ``diff`` and ``compare``."""
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
    diffing.add_argument("--format", choices=["text", "json"], default="text", help=_FORMAT_HELP)
    diffing.set_defaults(handler=_diff)

    comparing = commands.add_parser(
        "compare",
        help="a return beside the one another system produced, and why they differ",
        description=(
            "Compare a return with a baseline: the filing already made, or the return your "
            "current system produces for the same entity and date. Every cell is put in one "
            "category - the same, within the rounding the files state, a zero against a blank, "
            "in a template only one reports, or material - and the material differences are "
            "grouped into findings, each saying which return the Bank's own rules point at. "
            "Each file may be any file `validate` reads; the header options apply to a fact "
            "table. Exit 0 only when the two are equivalent."
        ),
    )
    comparing.add_argument(
        "baseline", type=Path, metavar="BASELINE", help="the return already trusted"
    )
    comparing.add_argument(
        "candidate", type=Path, metavar="CANDIDATE", help="the return to check against it"
    )
    _add_header_arguments(comparing)
    comparing.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        metavar="AMOUNT",
        help=(
            "count figures this close as the same, on top of the rounding the files state "
            "(for sources that state none, e.g. a fact table rounded to thousands)"
        ),
    )
    _add_submission_date_argument(comparing)
    comparing.add_argument("--format", choices=["text", "json"], default="text", help=_FORMAT_HELP)
    comparing.set_defaults(handler=_compare)


def _signoff(args: argparse.Namespace) -> int:
    """``rwa-filer signoff`` — record an approval and note it in the ledger."""
    manifest: Path = args.manifest
    try:
        approval = record_signoff(
            manifest,
            ledger=args.ledger or ledger_beside(manifest),
            approver=args.approver,
            role=args.role,
            at=datetime.now(UTC),
            statement=args.statement,
            acknowledge_findings=args.acknowledge_findings,
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
    problems = verify_filing(manifest, ledger=args.ledger, require_signoff=not args.unsigned)
    if problems:
        for problem in problems:
            _out(f"FAILED  {problem}")
        return EXIT_FAILED
    _out(f"ok      {manifest.name}: the files, the sign-off and the ledger agree")
    return EXIT_OK


def _diff(args: argparse.Namespace) -> int:
    """``rwa-filer diff`` — two versions of a return, cell by cell."""
    try:
        previous = _diff_side(args, args.previous)
        current = _diff_side(args, args.current)
    except (ValueError, ReleaseNotFoundError) as exc:
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


def _diff_side(args: argparse.Namespace, path: Path) -> CanonicalReturn:
    """One of the two returns ``rwa-filer diff`` compares, read from ``path``.

    ``diff`` compares cells and headers and reads nothing of a taxonomy
    release, so a file that names no taxonomy — a fact table or a workbook — is
    read here without loading one: the pack, rule book, deny list and issue
    register were two thirds of the command. Its release is still chosen
    (``release_choice``), so a module or a version no shipped release has is
    refused in the words ``_load`` refuses it in.

    Everything else goes to ``_load``: an XBRL instance, whose reader places
    each fact with its pack, and every file ``open_source`` refuses before
    reading it (missing, of an unsupported type, a fact table without the three
    header options), so each refusal is the one it always was.

    The header options are applied as ``readers.open_source`` applies them: the
    three of entity, date and module together make the header the file is read
    with, and each option given then overrides that field of the header read.
    ``tests/test_cli_diff.py`` holds this reading to ``open_source``'s.

    Raises:
        ValueError: as ``_load`` raises it.
        ReleaseNotFoundError: as ``_load`` raises it.
    """
    fields = _header_fields(args)
    header = None
    if fields.entity and fields.reference_date and fields.module:
        # Currency and scheme take the header's defaults here; given, they are
        # set below with the other options, as open_source sets them.
        header = ReturnHeader(fields.entity, fields.reference_date, fields.module)
    if (
        path.suffix.lower() not in SUPPORTED_SUFFIXES
        or not path.is_file()
        or (header is None and not carries_header(path))
    ):
        return _load(argparse.Namespace(**{**vars(args), "file": path})).ret
    ret = load_source(path, header).ret
    options = {
        "entity_identifier": fields.entity,
        "reference_date": fields.reference_date,
        "module": fields.module,
        "currency": fields.currency,
        "entity_scheme": fields.entity_scheme,
    }
    given = {name: value for name, value in options.items() if value}
    if given:
        ret = replace(ret, header=replace(ret.header, **given))
    release_choice(ret.header.module, args.taxonomy)
    return ret


def _compare(args: argparse.Namespace) -> int:
    """``rwa-filer compare`` — a return beside a baseline, and why they differ."""
    try:
        baseline = _load(argparse.Namespace(**{**vars(args), "file": args.baseline}))
        candidate = _load(argparse.Namespace(**{**vars(args), "file": args.candidate}))
        names = _names(args.baseline, args.candidate)
        comparison = compare_returns(
            baseline,
            candidate,
            names=names,
            tolerance=args.tolerance,
            submission_date=args.submission_date,
        )
    except (ValueError, ReleaseNotFoundError) as exc:
        return _fail(str(exc))
    sides = {"baseline": baseline, "candidate": candidate}
    if args.format == "json":
        record = comparison.as_record()
        record["taxonomy"] = {
            side: release_record(reading.release, reading.ret.header.reference_date)
            for side, reading in sides.items()
            if reading.release is not None
        }
        _out(json.dumps(record, indent=2))
    else:
        verdict, _, body = render_comparison(comparison).partition("\n")
        _out(verdict)
        for side, reading in sides.items():
            if reading.release is None:
                continue
            first, *rest = release_lines(reading.release)
            _out(f"{side.capitalize()}: {first}")
            for line in rest:
                _out(f"  {line}")
        _out(body)
    return EXIT_OK if comparison.is_equivalent else EXIT_FAILED


def _names(baseline: Path, candidate: Path) -> Names:
    """The two files' names, or their paths where the names alone are the same."""
    if baseline.name != candidate.name:
        return Names(baseline.name, candidate.name)
    return Names(str(baseline), str(candidate))


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
    _add_taxonomy_argument(template)
    template.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="the date the return will be for: a warning is printed if the release does "
        "not cover it (it does not choose the release)",
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

    if problem := _unwritable(args.out, "--out"):
        return _fail(problem)
    try:
        release = resolve_release(args.module, args.taxonomy)
        written = write_workbook(release.pack, args.out, tables=args.tables)
    except (ValueError, ReleaseNotFoundError) as exc:
        return _fail(str(exc))
    for line in release_lines(release):
        _out(line)
    if args.reference_date is not None and not release.covers(args.reference_date):
        _out(
            f"warning: reference date {args.reference_date.isoformat()} is outside "
            f"{release.module}'s dates in taxonomy {release.version} ({release.summary})"
        )
    _out(f"wrote {args.out} ({written} worksheet(s), {release.module} {release.version})")
    return EXIT_OK


# =============================================================================
# dash
# =============================================================================


def _add_dash_command(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer dash``."""
    dash = commands.add_parser(
        "dash",
        help="start the local web dashboard",
        description=(
            "Start a dashboard on this machine and open it in the browser: open a return, "
            "see whether it can be filed, walk from a broken rule to the cells on the "
            "template that broke it. It listens on this machine only (127.0.0.1) and answers "
            "only the browser holding the address it prints, which carries this session's token."
        ),
    )
    dash.add_argument(
        "file", nargs="?", type=Path, metavar="FILE", help="a return to open straight away"
    )
    _add_header_arguments(dash)
    dash.add_argument(
        "--port",
        type=int,
        default=DASH_PORT,
        metavar="N",
        help=f"the port to try first (default {DASH_PORT}; the next free one if it is taken)",
    )
    dash.add_argument(
        "--no-browser", action="store_true", help="print the address but do not open a browser"
    )
    dash.add_argument(
        "--workdir",
        type=Path,
        metavar="DIR",
        help="where the dashboard keeps the files opened in it (default: a new temporary folder)",
    )
    _add_progress_argument(dash)
    dash.set_defaults(handler=_dash)


def _dash(args: argparse.Namespace) -> int:
    """``rwa-filer dash`` — open FILE if given, then serve until interrupted."""
    # The web stack is imported here, not at the top: no other command needs it.
    from rwa_filer.dash import Workspace, serve

    workdir: Path = args.workdir or Path(tempfile.mkdtemp(prefix="rwa-filer-dash-"))
    workdir.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(workdir, taxonomy=args.taxonomy)
    start = "/"
    if args.file is not None:
        try:
            with _watching(args) as progress:
                opened = workspace.open(
                    args.file, _header_fields(args), taxonomy=args.taxonomy, progress=progress
                )
        except (ValueError, ReleaseNotFoundError) as exc:
            return _fail(str(exc))
        start = f"/returns/{opened.return_id}"
    # From here the command does not end with its work. Opening the file above was
    # one-shot work, and the process entry runs that with the garbage collector
    # off; a server must have it back before it starts.
    keep_collecting()
    try:
        serve(
            workspace,
            port=args.port,
            open_browser=not args.no_browser,
            start_path=start,
            announce=_out,
        )
    except KeyboardInterrupt:
        _out("stopped")
    return EXIT_OK


# =============================================================================
# taxonomy
# =============================================================================


def _add_taxonomy_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer taxonomy ...``."""
    taxonomy = commands.add_parser("taxonomy", help="inspect and build taxonomy packs")
    taxonomy.set_defaults(handler=lambda _args: _print_help(taxonomy))
    actions = taxonomy.add_subparsers(dest="taxonomy_command", metavar="<action>")

    listing = actions.add_parser(
        "list",
        help="show the shipped taxonomy releases and each module's status in them",
        description=(
            "One line per shipped release and module: the module's status in the release "
            "today (live, future or superseded), its dates, and whether a run with no "
            "--taxonomy uses it."
        ),
    )
    listing.add_argument("--module", metavar="CODE", help="only this module")
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


def _taxonomy_list(args: argparse.Namespace) -> int:
    """``rwa-filer taxonomy list`` — one line per shipped release and module."""
    today = date.today()
    shipped = shipped_releases()
    modules = sorted({info.module for version in shipped for info in release_packs(version)})
    if args.module is not None:
        modules = [module for module in modules if module.upper() == args.module.upper()]
        if not modules:
            return _fail(f"no shipped taxonomy release has module {args.module}")
    _out(
        f"{'module':<10}{'release':<10}{'status':<12}{'applies from':<14}{'applies to':<14}"
        f"{'default':<9}entry point"
    )
    for module in modules:
        try:
            # Only the version is printed: the release itself (its pack, rule book,
            # deny list and issue register) is not loaded to name it.
            default = default_release_version(module, today=today)
        except ReleaseNotFoundError:
            default = None
        for option in module_releases(module, today=today):
            info = option.info
            until = info.valid_to.isoformat() if info.valid_to else "-"
            marker = "yes" if option.version == default else ""
            _out(
                f"{module:<10}{option.version:<10}{option.status:<12}"
                f"{info.valid_from.isoformat():<14}{until:<14}{marker:<9}{info.entry_point}"
            )
    _out(
        f"\n{len(shipped)} release(s) shipped: {', '.join(shipped)}. Status as of "
        f"{today.isoformat()}. A run with no --taxonomy uses the release marked default; "
        "`status` is the module's in that release, so one release can be live for one "
        "module and future for another."
    )
    return EXIT_OK


def _taxonomy_compile(args: argparse.Namespace) -> int:
    """``rwa-filer taxonomy compile`` — build and write a pack."""
    from rwa_filer.taxonomy.compiler import compile_pack

    for path in (args.annotated, args.dictionary, args.taxonomy):
        if not path.exists():
            return _fail(f"not found: {path}")
    if problem := _unwritable(args.out, "--out", directory=True):
        return _fail(problem)
    try:
        compiled = compile_pack(args.annotated, args.dictionary, args.taxonomy, module=args.module)
        info = write_pack(compiled, args.out, valid_from=args.valid_from, valid_to=args.valid_to)
    except ValueError as exc:
        return _fail(str(exc))
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
    _add_taxonomy_argument(referee)
    referee.add_argument(
        "--workdir", type=Path, metavar="DIR", help="keep each worker's files here"
    )
    referee.add_argument("--chunk-mb", type=float, default=120.0, metavar="MB")
    referee.add_argument("--max-rss-gb", type=float, default=9.0, metavar="GB")
    referee.add_argument(
        "--jobs",
        type=int,
        metavar="N",
        help="workers to run at once (default: as many as fit in the memory available at "
        "--max-rss-gb each, one per CPU at most)",
    )
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
        # A SIGTERM kills the running workers too, as Ctrl-C does.
        with interrupt_on_sigterm():
            result = run_referee(
                instance,
                package,
                python=args.arelle_python,
                chunk_mb=args.chunk_mb,
                max_rss_gb=args.max_rss_gb,
                jobs=args.jobs,
                timeout=args.timeout,
                workdir=args.workdir,
                filing_rules=not args.no_filing_rules,
                rules=args.rules,
            )
        differential = None
        if not args.no_compare:
            source = load_source(instance, taxonomy=args.taxonomy)
            validation = validate_return(
                source.ret, release=source.release, source_findings=source.findings
            )
            if validation.report is None:
                return _fail(f"no rule book is packaged for module {source.ret.header.module}")
            differential = compare(validation.report.results, result)
    except (RefereeUnavailableError, RefereePlanError, ValueError, ReleaseNotFoundError) as exc:
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
    _add_deny_list_commands(actions)
    _add_issues_command(actions)


def _add_issues_command(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``rwa-filer rulebook issues``."""
    issues = actions.add_parser(
        "issues",
        help="the known issues with the published rules: list them, show one, or render the "
        "register as Markdown to share",
    )
    issues.add_argument("issue", nargs="?", metavar="ISSUE", help="one issue, e.g. PI-05")
    issues.add_argument("--taxonomy", metavar="V", help="one release (default: every shipped one)")
    issues.add_argument("--module", metavar="CODE", help="only issues about this module's rules")
    issues.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="text (default), json, or markdown (the write-up to share)",
    )
    issues.set_defaults(handler=_issues_show)


def _add_deny_list_commands(
    actions: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register ``rwa-filer rulebook deny-list ...``."""
    deny = actions.add_parser(
        "deny-list",
        help="the Bank's validations deny list: rules its gateway no longer runs, or runs "
        "as warnings",
    )
    deny.add_argument("--taxonomy", metavar="V", help="one release (default: every shipped one)")
    deny.add_argument("--module", metavar="CODE", help="one module, e.g. PRA001")
    deny.add_argument(
        "--on",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="say which entries are in force on this day (default: today)",
    )
    deny.add_argument("--format", choices=["text", "json"], default="text", help=_FORMAT_HELP)
    deny.set_defaults(handler=_deny_list_show)
    steps = deny.add_subparsers(dest="deny_command", metavar="<action>")
    for name, description, handler in (
        ("import", "build a release's deny list from the Bank's workbook", _deny_list_import),
        (
            "check",
            "fail if the packaged deny list is not what the Bank's workbook yields",
            _deny_list_check,
        ),
    ):
        step = steps.add_parser(name, help=description)
        step.add_argument("workbook", type=Path, metavar="WORKBOOK", help="the deny list (.xlsx)")
        step.add_argument(
            "--release", required=True, metavar="V", help="the taxonomy release, e.g. 4.1.1"
        )
        step.add_argument(
            "--known-issues",
            type=Path,
            metavar="XLSX",
            help="the Bank's known-issues log: give each entry the number of its issue",
        )
        step.add_argument("--url", help="where the workbook was published (recorded)")
        step.add_argument(
            "--published",
            type=date.fromisoformat,
            metavar="YYYY-MM-DD",
            help="when it was published (default: the newest Date Applied it records)",
        )
        if name == "import":
            step.add_argument(
                "--out", required=True, type=Path, metavar="DIR", help="where to write it"
            )
        step.set_defaults(handler=handler)


def _rulebook_list(_args: argparse.Namespace) -> int:
    """``rwa-filer rulebook list`` — one line per packaged rule book and module.

    ``deny-listed`` counts the module's rules the Bank's validations deny list
    switches off or downgrades at its gateway today; ``enforced`` is what the
    rule book publishes.
    """
    today = date.today()
    _out(
        f"{'framework version':<26}{'taxonomy':<10}{'rules':>7}  {'module':<10}"
        f"{'enforced':>9}{'deny-listed':>13}"
    )
    for name in available_rulebooks():
        rulebook = load_rulebook(name)
        denied = release_deny_list(rulebook.taxonomy)
        for module in rulebook.modules:
            _out(
                f"{rulebook.framework_version:<26}{rulebook.taxonomy:<10}"
                f"{len(rulebook.rules):>7}  {module:<10}{len(rulebook.enforced(module)):>9}"
                f"{len(denied.in_force(module, today)):>13}"
            )
    _out("deny-listed: see `rwa-filer rulebook deny-list` for the rules and why")
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
    if problem := _unwritable(args.out, "--out", directory=True):
        return _fail(problem)
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


def _deny_list_show(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook deny-list`` — the packaged deny lists, entry by entry."""
    day: date = args.on or date.today()
    versions = shipped_releases() if args.taxonomy is None else (args.taxonomy,)
    if args.taxonomy is not None and args.taxonomy not in shipped_releases():
        return _fail(
            f"taxonomy {args.taxonomy} is not shipped (shipped: {', '.join(shipped_releases())})"
        )
    lists = [release_deny_list(version) for version in versions]
    module = args.module.upper() if args.module else None
    if args.format == "json":
        _out(
            json.dumps(
                [
                    {
                        **item.to_payload(),
                        "entries": [
                            {
                                **entry.record(),
                                "in_force": entry.in_force_on(day),
                                "description": entry.describe(),
                            }
                            for entry in item.entries
                            if module is None or entry.module.upper() == module
                        ],
                        "in_force_on": day.isoformat(),
                    }
                    for item in lists
                ],
                indent=2,
            )
        )
        return EXIT_OK
    for item in lists:
        source = item.source
        _out(
            f"Taxonomy {item.release}: validations deny list {source.get('file') or '(none)'}"
            f" (published {source.get('published') or 'unknown'}), as at {day.isoformat()}"
        )
        entries = [
            entry for entry in item.entries if module is None or entry.module.upper() == module
        ]
        if not entries:
            _out("  no entry")
        for entry in entries:
            state = "" if entry.in_force_on(day) else "  [not in force on this date]"
            _out(f"  {entry.module:<8}{entry.rule_id:<16}{entry.describe()}{state}")
        for unmatched in item.unmatched:
            _out(f"  UNMATCHED {unmatched.module} {unmatched.code}: {unmatched.reason}")
    return EXIT_OK


def _issues_show(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook issues`` — the packaged publisher-issue registers."""
    shipped = shipped_releases()
    if args.taxonomy is not None and args.taxonomy not in shipped:
        return _fail(f"taxonomy {args.taxonomy} is not shipped (shipped: {', '.join(shipped)})")
    versions = shipped if args.taxonomy is None else (args.taxonomy,)
    module = args.module.upper() if args.module else None
    registers = [
        replace(
            register,
            issues=tuple(
                issue
                for issue in register.issues
                if module is None or any(entry.module.upper() == module for entry in issue.rules)
            ),
        )
        for register in (release_issues(version) for version in versions)
    ]
    if args.issue is not None:
        found = next(
            (
                (register, issue)
                for register in registers
                if (issue := register.issue(args.issue)) is not None
            ),
            None,
        )
        if found is None:
            return _fail(f"no known issue {args.issue} in taxonomy {', '.join(versions)}")
        register, issue = found
        if args.format == "json":
            _out(json.dumps({"release": register.release, **issue.record()}, indent=2))
        else:
            _out(render_issue(issue, register).rstrip("\n"))
        return EXIT_OK
    if args.format == "json":
        _out(json.dumps([register.to_payload() for register in registers], indent=2))
    elif args.format == "markdown":
        _out(render_document(registers).rstrip("\n"))
    else:
        for register in registers:
            for line in render_listing(register):
                _out(line)
    return EXIT_OK


def _read_deny_list(args: argparse.Namespace) -> deny_importer.DenyImport:
    """Import the command's WORKBOOK for its release.

    Raises:
        ValueError: a file is missing or unreadable, or the release is not shipped.
    """
    if args.release not in shipped_releases():
        raise ValueError(
            f"taxonomy {args.release} is not shipped (shipped: {', '.join(shipped_releases())})"
        )
    for path in (args.workbook, args.known_issues):
        if path is not None and not path.is_file():
            raise ValueError(f"file not found: {path}")
    return deny_importer.import_deny_list(
        args.workbook,
        args.release,
        known_issues=args.known_issues,
        published=args.published,
        url=args.url,
    )


def _deny_list_import(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook deny-list import`` — write a release's deny list."""
    if problem := _unwritable(args.out, "--out", directory=True):
        return _fail(problem)
    try:
        imported = _read_deny_list(args)
    except ValueError as exc:
        return _fail(str(exc))
    path = args.out / deny_list_file(args.release)
    deny_importer.write_deny_list(imported.payload, path)
    for line in imported.lines():
        _out(line)
    _out(f"wrote {path}")
    return EXIT_OK


def _deny_list_check(args: argparse.Namespace) -> int:
    """``rwa-filer rulebook deny-list check`` — compare the packaged deny list with the workbook.

    The address and publication date are not in the workbook: unless given,
    they are taken from the packaged file. The known-issue numbers come from
    the known-issues log alone, so without ``--known-issues`` they are not
    compared (and the command says so); with it, the whole file is.
    """
    packaged = Path(str(deny_importer.__file__)).parent.joinpath(
        *DENY_DIRECTORY, deny_list_file(args.release)
    )
    committed = packaged.read_text(encoding="utf-8") if packaged.is_file() else None
    if committed is not None:
        source = json.loads(committed).get("source", {})
        if args.url is None:
            args.url = source.get("url")
        if args.published is None and source.get("published"):
            args.published = date.fromisoformat(source["published"])
    try:
        imported = _read_deny_list(args)
    except ValueError as exc:
        return _fail(str(exc))
    for line in imported.lines():
        _out(line)
    name = deny_list_file(args.release)
    with_log = args.known_issues is not None
    if not with_log:
        _out("note  known-issue numbers not checked: pass --known-issues XLSX to check them")
    if deny_importer.is_deny_list_current(imported.payload, committed, known_issues=with_log):
        _out(f"ok    packaged deny list {name}")
        return EXIT_OK
    state = "out of date" if committed is not None else "missing"
    return _fail(f"packaged deny list {name} is {state}: it does not match {args.workbook.name}")


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
    """``rwa-filer rules list`` — one line per packaged extract, then the deny-listed rules.

    ``enforced`` counts the rules in force at the gateway today: a rule the
    Bank's validations deny list deactivates is not among them, and each rule
    the list touches is named, with what the Bank did and when.
    """
    _out(f"{'framework':<11}{'publisher':<11}{'version':<12}{'rules':>7}{'enforced':>10}  file")
    rulesets = [load_rules(framework) for framework in sorted(EXTRACT_FILES)]
    for ruleset in rulesets:
        version = str(ruleset.source.get("framework_version", ""))
        _out(
            f"{ruleset.framework:<11}{ruleset.publisher:<11}{version:<12}"
            f"{len(ruleset.rules):>7}{len(ruleset.enforced):>10}  "
            f"{EXTRACT_FILES[ruleset.framework]}"
        )
    for ruleset in rulesets:
        denied = [(rule, entry) for rule in ruleset.rules if (entry := rule.deny) is not None]
        if denied:
            _out(f"{ruleset.framework}: the Bank's validations deny list, as at {date.today()}:")
        for rule, entry in denied:
            _out(f"  {rule.rule_id:<16}{entry.describe()}")
    return EXIT_OK


def _rules_import(args: argparse.Namespace) -> int:
    """``rwa-filer rules import`` — write a fresh extract."""
    workbook: Path = args.workbook
    if not workbook.is_file():
        return _fail(f"workbook not found: {workbook}")
    if problem := _unwritable(args.out, "--out"):
        return _fail(problem)
    try:
        payload = importer.extract(args.publisher, workbook)
    except ValueError as exc:
        return _fail(str(exc))
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

    try:
        payload = importer.extract(args.publisher, workbook)
    except ValueError as exc:
        return _fail(str(exc))
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


def _is_terminal(stream: object) -> bool:
    """Whether ``stream`` is a terminal a person is watching (not a file, pipe or capture)."""
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except ValueError:  # a closed stream
        return False


def _out(line: str) -> None:
    """Write one line of command output to stdout."""
    sys.stdout.write(f"{line}\n")


def _fail(message: str) -> int:
    """Write a diagnostic to stderr and return the failure exit code."""
    sys.stderr.write(f"rwa-filer: {message}\n")
    return EXIT_FAILED


def _unwritable(path: Path | None, option: str, *, directory: bool = False) -> str | None:
    """Why ``option``'s ``path`` cannot be written, or ``None`` (also when not given).

    Asked before the command does its work, so that a path in the way is refused
    in one line before a compile runs, rather than as the ``FileExistsError`` or
    ``IsADirectoryError`` of writing it afterwards. Only what writing would
    certainly fail on is refused; an existing file where a file is written is
    replaced, as it always was.

    Args:
        path: The option's value.
        option: The option, as the user typed it, e.g. ``"--out"``.
        directory: Whether the command writes a directory there, not a file.
    """
    if path is None:
        return None
    if directory and path.exists() and not path.is_dir():
        return f"{option} {path} is a file, not a directory"
    if not directory and path.is_dir():
        return f"{option} {path} is a directory, not a file"
    in_the_way = next((p for p in path.parents if p.exists() and not p.is_dir()), None)
    if in_the_way is not None:
        return f"{option} {path} cannot be written: {in_the_way} is a file, not a directory"
    return None


if __name__ == "__main__":
    # ``python -m rwa_filer.cli`` is a process started for one command, as the
    # console script is: it goes through the same entry.
    run()
