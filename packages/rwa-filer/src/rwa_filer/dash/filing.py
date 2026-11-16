"""
Building, signing off and verifying a filing from the dashboard.

Pipeline position:
    dash.filing_pages  ->  draft_adjustment / build_package / filing_page
        ->  workflow.adjustments, filing.build_filing, workflow.acts
        ->  dash/templates/filing.html

Key responsibilities:
- Draft a cell override from the template grid, checked as a batch with the
  ones already drafted, so a draft that could never be applied is refused when
  it is made rather than when the package is built.
- Say what the drafted overrides change, rule by rule, whenever any is drafted:
  the breaks they fix, the ones they newly cause, and — never counted as fixed
  — the breaks that stop because the overrides left a rule nothing to read.
- Build a package exactly as ``rwa-filer build`` does — the same validation,
  the same refusal while a structure finding stands, the same manifest — and
  record it in the audit ledger through the same call the command uses.
- Lay out one build's state for the page: its files, its sign-off, its ledger,
  and on request whether the files on disk still agree with all three.

References:
- rwa_filer.filing.build_filing — what a build is
- rwa_filer.workflow.acts — what each act records
"""

from __future__ import annotations

import getpass
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.catalogue import SEVERITY_ERROR
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS
from rwa_filer.dash.views import REASON_TEXT, rule_label
from rwa_filer.dash.workspace import FilingRecord
from rwa_filer.filing import BLOCKED_BY_STRUCTURE, build_filing
from rwa_filer.workflow.acts import ledger_beside, ledger_for_instance, record_build, verify_filing
from rwa_filer.workflow.adjustments import Adjustment, apply_adjustments
from rwa_filer.workflow.ledger import read_ledger, verify_ledger
from rwa_filer.workflow.signoff import read_signoff, signoff_path
from rwa_filer.xbrl.writer import InstanceOptions

if TYPE_CHECKING:
    from datetime import datetime

    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.dash.workspace import OpenedReturn, WorkingReturn, Workspace
    from rwa_filer.progress import ProgressCallback
    from rwa_filer.validate.returns import RuleReport
    from rwa_filer.workflow.adjustments import AppliedAdjustment
    from rwa_filer.workflow.ledger import LedgerEntry
    from rwa_filer.workflow.signoff import SignOff

logger = logging.getLogger(__name__)

#: Data types whose facts are numbers; any other cell holds text.
NUMERIC_TYPES: Final = frozenset({"monetary", "percentage", "integer", "decimal"})
#: The files of a build a page may offer, by the name its address uses.
FILE_KINDS: Final = ("instance", "zip", "manifest", "ledger", "signoff")
#: Where packages go when the return was uploaded rather than opened in place.
DEFAULT_FOLDER: Final = "filing"
#: How the overrides change a rule: it held as opened and holds now, and so on.
CHANGE_FIXED: Final = "fixed"
CHANGE_STOPPED: Final = "stopped"
CHANGE_BROKEN: Final = "broken"


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class BuildOptions:
    """What the build form asks for — the options ``rwa-filer build`` takes."""

    directory: Path
    name: str | None = None
    monetary_decimals: int = -3
    percentage_decimals: int = 4
    declare_unreported: bool = False
    always_zip: bool = False
    reproducible: bool = False
    force: bool = False
    author: str | None = None


@dataclass(frozen=True)
class RuleEffect:
    """A rule whose standing the drafted overrides change.

    Attributes:
        rule_id: The rule's code.
        severity: ``ERROR`` or ``WARNING``.
        label: The publisher's short description, or empty.
        change: ``fixed`` (broken as opened, holds now), ``stopped`` (broken as
            opened, does not run now) or ``broken`` (broken now, not as opened).
        status: Its status with the overrides applied.
        reason: Why it does not run now, in words; empty when it runs.
    """

    rule_id: str
    severity: str
    label: str
    change: str
    status: str
    reason: str

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR


@dataclass(frozen=True)
class OverrideEffect:
    """What the drafted overrides change: the verdict, and each rule they move.

    ``no_longer_run`` counts the rules that held as opened and do not run with
    the overrides — checks the return loses, though none of them was broken.
    """

    blocking_before: int
    blocking_after: int
    breaks_before: int
    breaks_after: int
    structure_after: int
    submittable: bool
    fixed: tuple[RuleEffect, ...]
    stopped: tuple[RuleEffect, ...]
    broken: tuple[RuleEffect, ...]
    no_longer_run: int


@dataclass(frozen=True)
class BuildFile:
    """One file a build wrote, as the page offers it."""

    kind: str
    label: str
    path: Path


@dataclass(frozen=True)
class BuildView:
    """One build, with what has been done with it since."""

    index: int
    record: FilingRecord
    sha256: str | None
    files: tuple[BuildFile, ...]
    signoff: SignOff | None
    ledger: tuple[LedgerEntry, ...]
    ledger_problems: tuple[str, ...]
    verification: tuple[str, ...] | None

    @property
    def manifest(self) -> Path | None:
        return self.record.package.manifest_path


@dataclass(frozen=True)
class FilingPage:
    """The Build & sign off page."""

    drafts: tuple[AppliedAdjustment, ...]
    draft_problem: str | None
    effect: OverrideEffect | None
    latest: BuildView | None
    builds: int
    default_directory: Path
    default_author: str


def draft_adjustment(  # noqa: PLR0913 - one keyword per field of the override form
    workspace: Workspace,
    opened: OpenedReturn,
    *,
    cell: tuple[str, str | None, str | None, str, str],
    value: str,
    remove: bool,
    reason: str,
    data_type: str,
) -> Adjustment:
    """Draft an override of ``cell`` for ``opened``, after checking it applies.

    Raises:
        ValueError: the value is not of the cell's type, or the override —
            together with those already drafted — could not be applied
            (``AdjustmentError`` is a ``ValueError``).
    """
    table, sheet, open_key, row, column = cell
    number, text = (None, None) if remove else parse_value(value, data_type)
    adjustment = Adjustment(
        table=table,
        row=row,
        column=column,
        reason=reason.strip(),
        sheet=sheet,
        open_key=open_key,
        value=number,
        text_value=text,
        remove=remove,
    )
    others = [item for item in workspace.adjustments(opened.return_id) if item.cell != cell]
    apply_adjustments(opened.ret, [*others, adjustment])
    workspace.set_adjustment(opened.return_id, adjustment)
    return adjustment


def parse_value(text: str, data_type: str) -> tuple[float | None, str | None]:
    """A typed value from what a person typed: a number for a numeric cell, else text.

    ``1,250,000`` reads as a number; ``0.45%`` in a percentage cell reads as
    ``0.0045``, the way the taxonomy states percentages.

    Raises:
        ValueError: a numeric cell was given something that is not a number,
            or any cell was given nothing.
    """
    given = text.strip()
    if not given:
        raise ValueError("Give the value the cell should hold, or choose to remove it.")
    if data_type not in NUMERIC_TYPES:
        return None, given
    scale = 1.0
    if data_type == "percentage" and given.endswith("%"):
        given, scale = given[:-1].strip(), 0.01
    try:
        return float(given.replace(",", "")) * scale, None
    except ValueError:
        raise ValueError(f"{text.strip()!r} is not a number, and this cell holds one.") from None


def build_package(
    workspace: Workspace,
    opened: OpenedReturn,
    options: BuildOptions,
    *,
    at: datetime,
    progress: ProgressCallback | None = None,
) -> int:
    """Build a filing package from ``opened`` and its drafted overrides; the build's index.

    The package is written only as ``rwa-filer build`` would write it; a build
    that is refused is kept too, so the page can say why. ``progress`` is told
    how far the build's validation, then its writing, has got.

    Raises:
        ValueError: overrides are drafted but no author is given — an override
            is recorded against a name — or the ledger cannot be written.
    """
    drafts = workspace.adjustments(opened.return_id)
    author = (options.author or "").strip() or None
    if drafts and author is None:
        raise ValueError("Overrides are recorded against a name: say who is preparing the filing.")
    ret, applied = apply_adjustments(opened.ret, drafts) if drafts else (opened.ret, ())
    package = build_filing(
        ret,
        options.directory,
        release=opened.release,
        options=InstanceOptions(
            monetary_decimals=options.monetary_decimals,
            percentage_decimals=options.percentage_decimals,
            created_at=None if options.reproducible else at,
            declare_unreported=options.declare_unreported,
        ),
        name=options.name or None,
        allow_rule_breaks=options.force,
        always_zip=options.always_zip,
        source_findings=opened.reading.findings,
        adjustments=applied,
        source=opened.validation.source,
        progress=progress,
    )
    ledger = None
    if package.written and author is not None and package.instance_path is not None:
        ledger = ledger_for_instance(package.instance_path)
        record_build(ledger, package, applied=applied, forced=options.force, author=author, at=at)
    record = FilingRecord(
        built_at=at,
        package=package,
        applied=applied,
        author=author,
        ledger=ledger,
        forced=options.force,
    )
    logger.info("built %s: written=%s", opened.name, package.written)
    return workspace.add_build(opened.return_id, record)


def filing_page(
    workspace: Workspace, working: WorkingReturn, *, verify: bool = False
) -> FilingPage:
    """The Build & sign off page for ``working``, with what its drafted overrides change."""
    opened = working.opened
    builds = workspace.builds(opened.return_id)
    latest = _build_view(len(builds) - 1, builds[-1], verify=verify) if builds else None
    return FilingPage(
        drafts=working.applied,
        draft_problem=working.problem,
        effect=override_effect(working),
        latest=latest,
        builds=len(builds),
        default_directory=default_directory(workspace, opened),
        default_author=_user(),
    )


def override_effect(working: WorkingReturn) -> OverrideEffect | None:
    """What the drafted overrides change, or ``None`` while none is applied.

    A broken rule the overrides leave nothing to read is ``stopped``, never
    ``fixed``: it no longer runs, so nothing checks the figures it read.
    """
    if not working.adjusted:
        return None
    before = working.opened.validation
    after = working.current.validation
    was = _results(before.report)
    now = _results(after.report)
    info = working.opened.pack.info
    effects: dict[str, list[RuleEffect]] = {CHANGE_FIXED: [], CHANGE_STOPPED: [], CHANGE_BROKEN: []}
    no_longer_run = 0
    for rule_id, result in sorted({**was, **now}.items()):
        held = was[rule_id].status if rule_id in was else STATUS_NOT_EVALUATED
        holds = now[rule_id].status if rule_id in now else STATUS_NOT_EVALUATED
        change = _change(held, holds)
        if change is None:
            no_longer_run += held == STATUS_PASS and holds == STATUS_NOT_EVALUATED
            continue
        effects[change].append(
            RuleEffect(
                rule_id=rule_id,
                severity=result.severity,
                label=rule_label(info, rule_id),
                change=change,
                status=holds,
                reason=_reason(now.get(rule_id)) if holds == STATUS_NOT_EVALUATED else "",
            )
        )
    return OverrideEffect(
        blocking_before=len(before.blocking),
        blocking_after=len(after.blocking),
        breaks_before=_breaks(before.report),
        breaks_after=_breaks(after.report),
        structure_after=len(after.structure),
        submittable=after.is_submittable,
        fixed=_ranked(effects[CHANGE_FIXED]),
        stopped=_ranked(effects[CHANGE_STOPPED]),
        broken=_ranked(effects[CHANGE_BROKEN]),
        no_longer_run=no_longer_run,
    )


def build_file(record: FilingRecord, kind: str) -> Path | None:
    """The file of ``kind`` a build wrote, if it wrote one and it is still there."""
    package = record.package
    manifest = package.manifest_path
    paths = {
        "instance": package.instance_path,
        "zip": package.zip_path,
        "manifest": manifest,
        "ledger": record.ledger,
        "signoff": signoff_path(manifest) if manifest else None,
    }
    path = paths.get(kind)
    return path if path is not None and path.is_file() else None


def default_directory(workspace: Workspace, opened: OpenedReturn) -> Path:
    """Where a package goes by default: beside the return, or a ``filing`` folder here.

    A return uploaded through the browser lives in the session's temporary
    folder, which is no place for the file a firm files.
    """
    source = opened.path.resolve()
    if source.is_relative_to(workspace.directory.resolve()):
        return Path.cwd() / DEFAULT_FOLDER
    return source.parent / DEFAULT_FOLDER


def blocked_reason(record: FilingRecord) -> str | None:
    """Why a build wrote nothing, in words, or ``None`` when it wrote its files."""
    package = record.package
    if package.written:
        return None
    if package.blocked_by == BLOCKED_BY_STRUCTURE:
        return (
            "The taxonomy cannot express part of the return, so no XBRL file can be written "
            "until the structure findings are fixed."
        )
    return (
        "A published rule is broken, so nothing was written. Choose to write it anyway to "
        "investigate it, and the manifest will record that you did."
    )


# =============================================================================
# Private helpers
# =============================================================================


def _build_view(index: int, record: FilingRecord, *, verify: bool) -> BuildView:
    package = record.package
    manifest = package.manifest_path
    labels = {
        "instance": "XBRL instance",
        "zip": "Zip for upload",
        "manifest": "Manifest",
        "ledger": "Audit ledger",
        "signoff": "Sign-off",
    }
    files = tuple(
        BuildFile(kind, labels[kind], path)
        for kind in FILE_KINDS
        if (path := build_file(record, kind)) is not None
    )
    try:
        approval = read_signoff(manifest) if manifest else None
    except ValueError:
        approval = None
    ledger = record.ledger or (ledger_beside(manifest) if manifest else None)
    entries: tuple[LedgerEntry, ...] = ()
    ledger_problems: tuple[str, ...] = ()
    if ledger is not None and ledger.is_file():
        ledger_problems = tuple(verify_ledger(ledger))
        if not ledger_problems:
            entries = tuple(read_ledger(ledger))
    verification = None
    if verify and manifest is not None:
        verification = tuple(verify_filing(manifest, ledger=record.ledger))
    instance = package.instance
    return BuildView(
        index=index,
        record=record,
        sha256=hashlib.sha256(instance.content).hexdigest() if instance else None,
        files=files,
        signoff=approval,
        ledger=entries,
        ledger_problems=ledger_problems,
        verification=verification,
    )


def _results(report: RuleReport | None) -> dict[str, RuleResult]:
    return {result.rule_id: result for result in (report.results if report else ())}


def _change(held: str, holds: str) -> str | None:
    """How a rule's status as opened and with the overrides differ, if it matters."""
    if held == STATUS_FAIL and holds == STATUS_PASS:
        return CHANGE_FIXED
    if held == STATUS_FAIL and holds == STATUS_NOT_EVALUATED:
        return CHANGE_STOPPED
    if holds == STATUS_FAIL and held != STATUS_FAIL:
        return CHANGE_BROKEN
    return None


def _reason(result: RuleResult | None) -> str:
    """Why a rule does not run, in words."""
    if result is None:
        return "it is not in the report on the return with the overrides"
    return REASON_TEXT.get(result.reason, result.reason)


def _ranked(effects: list[RuleEffect]) -> tuple[RuleEffect, ...]:
    """Error rules first, then by code."""
    return tuple(sorted(effects, key=lambda item: (not item.is_error, item.rule_id)))


def _breaks(report: RuleReport | None) -> int:
    return report.status_counts()[STATUS_FAIL] if report else 0


def _user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # pragma: no cover - no user name in this environment
        return ""
