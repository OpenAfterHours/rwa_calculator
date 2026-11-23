"""
The dashboard's workspace — the returns opened in one ``rwa-filer dash`` session.

Pipeline position:
    uploaded file / local path  ->  Workspace.open
        ->  readers.open_source  ->  validate.validate_return
        ->  OpenedReturn  ->  Workspace.working  ->  the dashboard's pages

Key responsibilities:
- Hold each opened return with the validation it was given, so that drawing a
  page never re-validates. The validation records every break of every rule,
  not the first few a report shows: the template grid marks each cell a broken
  evaluation read, and a cell left unmarked would read as one no rule faults.
- Hold, per return, the cell overrides a preparer has drafted and the filing
  packages built from it — the session's working state, which the files on
  disk (manifest, ledger, sign-off) then record for good.
- Work out once per change of a return's drafted overrides what the return is
  with them applied — the return a build would file now, which the overview,
  the rules, the grid, the Build & sign off page and the top-bar verdict draw —
  so an override that clears a break clears it on each of them. Only the first
  page drawn after a change validates; every later one reuses its result.
- Compare two opened returns once per pair: a comparison evaluates every rule
  on both, and a page redrawn to filter its cells must not do that again.
- Attribute a return's breaks to the members of a breakdown column once per
  change of its drafted overrides (``workflow.attribution``): it runs the rules
  again on every member's rows, and the Investigate page is drawn many times
  from one such run.
- Write the evidence behind a validation's verdict once, and hand out that file
  for every later download of it. A file handed out is never removed while the
  session runs, so no download loses the file it was given.
- Do each of those three — a validation, a comparison, an evidence file — once
  however many requests ask for it at the same moment: the first asker does the
  work, and the others wait for it and take its result instead of doing the same
  work beside it. A page asked for while its return is validated again, a second
  tab, a second click: each would otherwise repeat seconds of work, and two
  evidence downloads at once rewrote one file while it was being sent.
- Open a return again against another taxonomy release, beside the first.
- Keep uploaded files under the one directory the session owns, under names a
  browser cannot steer outside it.
- Be safe to call from the server's worker threads.

References:
- rwa_filer.readers.open_source — how a named file is read, as the CLI reads it
- rwa_filer.validate.returns.validate_return — what "validated" means
- rwa_filer.evidence — the evidence file, as ``rwa-filer validate --evidence`` writes it
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.evidence import collect_evidence, write_evidence
from rwa_filer.readers import HeaderFields, SourceReading, open_source
from rwa_filer.validate.identity import source_identity
from rwa_filer.validate.returns import validate_return
from rwa_filer.workflow.adjustments import AdjustmentError, apply_adjustments
from rwa_filer.workflow.attribution import attribute
from rwa_filer.workflow.compare import compare_returns
from rwa_filer.workflow.explain import Names

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from rwa_filer.filing import FilingPackage
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.progress import ProgressCallback
    from rwa_filer.readers import DetailSpec, ReturnDetail
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.returns import ReturnValidation
    from rwa_filer.workflow.adjustments import Adjustment, AppliedAdjustment
    from rwa_filer.workflow.attribution import Attribution
    from rwa_filer.workflow.compare import ReturnComparison

#: A cell's full address: table, sheet, open-axis key, row, column.
Cell = tuple[str, str | None, str | None, str, str]
#: What an attribution is kept under: the return's id, its drafts, the column.
type _AttributionKey = tuple[str, tuple["Adjustment", ...], str]

logger = logging.getLogger(__name__)

#: How many of each rule's breaks a validation here records: all of them
#: (``validate_return``'s ``max_failures``), so the grid can mark every one.
_EVERY_FAILURE: Final = None
#: Characters an uploaded file's name may keep; any other run becomes ``_``.
_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")
#: The name an upload is given when nothing of its own name survives.
_FALLBACK_NAME: Final = "upload"
#: The folder of the workspace the evidence files are written to.
_EVIDENCE_FOLDER: Final = "evidence"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class OpenedReturn:
    """One return opened in the dashboard, with what validating it established.

    Attributes:
        return_id: The session's id for it, used in every page address.
        name: The name the person knows the file by.
        path: Where the file is on this machine.
        reading: What reading the file produced.
        validation: The validation, run once when the file was opened.
        opened_at: When it was opened.
    """

    return_id: str
    name: str
    path: Path
    reading: SourceReading
    validation: ReturnValidation
    opened_at: datetime

    @property
    def ret(self) -> CanonicalReturn:
        """The return itself."""
        return self.reading.ret

    @property
    def release(self) -> Release:
        """The taxonomy release the return was validated against, and why."""
        return self.validation.release

    @property
    def pack(self) -> TaxonomyPack:
        """The taxonomy the return was validated against."""
        return self.validation.pack

    @property
    def detail(self) -> ReturnDetail | None:
        """The rows the return was summed from, when it was opened as a detail."""
        return self.reading.detail


@dataclass(frozen=True)
class WorkingReturn:
    """A return as a build would file it now: as opened, with its drafted overrides applied.

    Every page of a return draws ``current``, so the verdict, the rules and the
    marks on the grid answer for what would be filed, not for the file alone.

    Attributes:
        opened: The return as it was opened.
        current: ``opened`` itself while nothing is drafted or the drafts cannot
            be applied; otherwise the same return with the drafts applied and
            validated again, as ``rwa-filer build`` validates it.
        drafts: The overrides drafted, in the order they were made.
        applied: What applying them did, cell by cell; empty unless they apply.
        problem: Why the drafts cannot be applied, or ``None``.
    """

    opened: OpenedReturn
    current: OpenedReturn
    drafts: tuple[Adjustment, ...] = ()
    applied: tuple[AppliedAdjustment, ...] = ()
    problem: str | None = None

    @property
    def adjusted(self) -> bool:
        """Whether ``current`` differs from the return as opened."""
        return bool(self.applied)


@dataclass(frozen=True)
class FilingRecord:
    """One filing package built from the dashboard.

    Attributes:
        built_at: When it was built.
        package: What ``build_filing`` produced — written or not, and why.
        applied: The overrides applied before it was built.
        author: Who prepared it, or ``None`` (then nothing is in a ledger).
        ledger: The audit ledger its build was recorded in, if any.
        forced: Whether it was written despite a broken rule.
    """

    built_at: datetime
    package: FilingPackage
    applied: tuple[AppliedAdjustment, ...]
    author: str | None
    ledger: Path | None
    forced: bool


class Workspace:
    """The returns opened in this session, and the directory its files live in.

    ``taxonomy`` is the release a return is opened against when none is named
    for it (``rwa-filer dash --taxonomy``); ``None`` for the default release.
    """

    def __init__(self, directory: Path, *, taxonomy: str | None = None) -> None:
        self.directory = directory
        self.taxonomy = taxonomy
        self._returns: dict[str, OpenedReturn] = {}
        self._adjustments: dict[str, dict[Cell, Adjustment]] = {}
        #: Bumped on every change of a return's drafts; the key its working return is kept under.
        self._revisions: dict[str, int] = {}
        self._working: dict[str, tuple[int, WorkingReturn]] = {}
        self._builds: dict[str, list[FilingRecord]] = {}
        self._comparisons: dict[tuple[str, str], ReturnComparison] = {}
        #: Per return, the evidence files later downloads are served (``evidence``).
        self._evidence: dict[str, tuple[_KeptEvidence, ...]] = {}
        #: The work under way, by what it makes; a second asker waits on it (``_once``).
        self._flights: dict[tuple[object, ...], _Flight[Any]] = {}
        #: Keyed by return, the drafts applied to it, and the breakdown column.
        self._attributions: dict[_AttributionKey, Attribution] = {}
        self._lock = threading.Lock()

    def open(
        self,
        path: Path,
        fields: HeaderFields | None = None,
        *,
        name: str | None = None,
        taxonomy: str | None = None,
        progress: ProgressCallback | None = None,
        detail: DetailSpec | None = None,
    ) -> OpenedReturn:
        """Read and validate ``path``, and keep it under a new id.

        Args:
            path: The file.
            fields: Header fields given beside it.
            name: The name to show it under; defaults to the file's.
            taxonomy: The release to validate it against, by version; defaults
                to the workspace's, else the default release for the module.
            progress: Told how far the reading and the validation have got.
            detail: Read a fact table as a detail, its rows summed and kept
                (``readers.detail``); ``None`` to read it as a return.

        Raises:
            ValueError: the file is missing, unsupported, lacks a header it
                needs, or is not readable as what its suffix says it is; or its
                rows cannot be summed as the detail asks.
            ReleaseNotFoundError: the taxonomy release could not be resolved.
        """
        reading = open_source(
            path,
            fields,
            taxonomy=taxonomy or self.taxonomy,
            progress=progress,
            detail=detail,
        )
        validation = validate_return(
            reading.ret,
            release=reading.release,
            source_findings=reading.findings,
            source=source_identity(path),
            progress=progress,
            max_failures=_EVERY_FAILURE,
        )
        opened = OpenedReturn(
            return_id=secrets.token_hex(4),
            name=name or path.name,
            path=path,
            reading=reading,
            validation=validation,
            opened_at=datetime.now(UTC),
        )
        with self._lock:
            self._returns[opened.return_id] = opened
        logger.info("opened %s as %s", opened.name, opened.return_id)
        return opened

    def reopen(
        self,
        opened: OpenedReturn,
        taxonomy: str,
        *,
        progress: ProgressCallback | None = None,
        detail: DetailSpec | None = None,
    ) -> OpenedReturn:
        """Open ``opened``'s file again, against another taxonomy release or another breakdown.

        The return keeps its header — the one it was opened with, overrides
        included — and is kept under a new id beside the first, so the two can
        be compared. Drafted overrides are not carried across: a cell one
        release accepts may not exist in another.

        ``detail`` is the breakdown to read the file with this time; ``None``
        keeps the one it was opened with (none, for a return opened as one).

        Raises:
            ValueError: the file can no longer be read, or not with that breakdown.
            ReleaseNotFoundError: the release cannot read it.
        """
        header = opened.ret.header
        fields = HeaderFields(
            entity=header.entity_identifier,
            reference_date=header.reference_date,
            module=header.module,
            currency=header.currency,
            entity_scheme=header.entity_scheme,
        )
        kept = opened.detail.spec if opened.detail is not None else None
        return self.open(
            opened.path,
            fields,
            name=opened.name,
            taxonomy=taxonomy,
            progress=progress,
            detail=detail if detail is not None else kept,
        )

    def save_upload(self, filename: str, content: bytes) -> Path:
        """Write an uploaded file into the workspace and return where it went.

        Each upload gets a folder of its own, so two files of the same name
        never overwrite each other.
        """
        folder = self.directory / "uploads" / secrets.token_hex(4)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_file_name(filename)
        path.write_bytes(content)
        return path

    def get(self, return_id: str) -> OpenedReturn | None:
        """The return opened under ``return_id``, if there is one."""
        with self._lock:
            return self._returns.get(return_id)

    def returns(self) -> list[OpenedReturn]:
        """Every return opened in this session, the most recent first."""
        with self._lock:
            opened = list(self._returns.values())
        return sorted(opened, key=lambda item: item.opened_at, reverse=True)

    # -- drafted overrides --------------------------------------------------------

    def adjustments(self, return_id: str) -> tuple[Adjustment, ...]:
        """The overrides drafted for a return, in the order they were made."""
        with self._lock:
            return tuple(self._adjustments.get(return_id, {}).values())

    def set_adjustment(self, return_id: str, adjustment: Adjustment) -> None:
        """Draft an override, replacing any already drafted for the same cell."""
        with self._lock:
            drafted = self._adjustments.setdefault(return_id, {})
            drafted.pop(adjustment.cell, None)
            drafted[adjustment.cell] = adjustment
            self._revisions[return_id] = self._revisions.get(return_id, 0) + 1

    def drop_adjustment(self, return_id: str, cell: Cell) -> None:
        """Withdraw the override drafted for ``cell``, if there is one."""
        with self._lock:
            if self._adjustments.get(return_id, {}).pop(cell, None) is not None:
                self._revisions[return_id] = self._revisions.get(return_id, 0) + 1

    def working(
        self, opened: OpenedReturn, *, progress: ProgressCallback | None = None
    ) -> WorkingReturn:
        """``opened`` with its drafted overrides applied, validated once per change of them.

        A page drawn after the drafts last changed gets the same object back,
        so only the first page drawn after a change pays for the validation.
        One asked for while that validation runs — a page drawn while a drafted
        override is validated, the open page listing the return — waits for it
        and gets its result, rather than validating the same drafts beside it.
        ``progress`` is told how far that validation has got, when this call is
        the one that runs it.
        """
        return_id = opened.return_id
        with self._lock:
            revision = self._revisions.get(return_id, 0)
            drafts = tuple(self._adjustments.get(return_id, {}).values())

        def kept() -> WorkingReturn | None:
            found = self._working.get(return_id)
            return found[1] if found is not None and found[0] == revision else None

        def keep(made: WorkingReturn) -> None:
            # A validation of drafts changed since it started is not kept: no page shows it.
            if self._revisions.get(return_id, 0) == revision:
                self._working[return_id] = (revision, made)

        return self._once(
            ("working", return_id, revision),
            kept,
            lambda: _work_out(opened, drafts, progress),
            keep,
        )

    # -- evidence -----------------------------------------------------------------

    def evidence(self, current: OpenedReturn) -> Path:
        """The evidence file behind ``current``'s verdict, collected and written once for it.

        ``current`` is a return as its pages draw it — as opened, or with its
        drafted overrides applied (``WorkingReturn.current``) — and the file is
        what ``rwa-filer validate --evidence`` writes for it. It is kept per
        validation, not per return: a second download is served the file the
        first wrote, and withdrawing every override is served the as-opened file
        again rather than writing it a second time. Each file is written whole,
        under a name of its own, before it is first handed out, and never
        written again: no download can read a file while it is being written.

        Which files are kept for later downloads follows the return as it now
        stands, not the order collections end in: the as-opened validation's,
        the current drafts' (``working``), and the one just written. A file no
        longer kept stays where it is, in the session's folder, and is never
        removed while the session runs: a download may have been handed it and
        not yet opened it.
        """
        validation, return_id = current.validation, current.return_id

        def kept() -> Path | None:
            found = self._evidence.get(return_id, ())
            return next((item.path for item in found if item.validation is validation), None)

        def keep(path: Path) -> None:
            wanted = (*self._validations_drawn(return_id), validation)
            listed = (*self._evidence.get(return_id, ()), _KeptEvidence(validation, path))
            self._evidence[return_id] = tuple(
                item for item in listed if any(item.validation is each for each in wanted)
            )

        # Keyed on the validation itself: the flight keeps ``current`` alive, so the id is its own.
        return self._once(
            ("evidence", id(validation)),
            kept,
            lambda: _write_evidence(current, self.directory / _EVIDENCE_FOLDER),
            keep,
        )

    # -- attributions ---------------------------------------------------------------

    def attribution(
        self,
        working: WorkingReturn,
        dimension: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> Attribution:
        """``working``'s breaks attributed to the members of ``dimension``, worked out once.

        Kept per return, per set of drafted overrides and per column: an
        override moves the return's figures but not the detail's, so another
        set of drafts is another attribution. The search for breaks the total
        hides is included.

        Raises:
            KeyError: the return has no detail, or ``dimension`` is not one of
                its breakdown columns.
        """
        detail = working.opened.detail
        if detail is None:
            raise KeyError(f"{working.opened.name} was not opened with breakdown columns")
        key = _attribution_key(working, dimension)
        with self._lock:
            found = self._attributions.get(key)
        if found is not None:
            return found
        made = attribute(
            working.current.ret, working.current.validation, detail, dimension, progress=progress
        )
        with self._lock:
            return self._attributions.setdefault(key, made)

    def kept_attribution(self, working: WorkingReturn, dimension: str) -> Attribution | None:
        """The attribution ``attribution`` would return, if it has been worked out; else ``None``."""
        key = _attribution_key(working, dimension)
        with self._lock:
            return self._attributions.get(key)

    # -- builds -------------------------------------------------------------------

    def add_build(self, return_id: str, record: FilingRecord) -> int:
        """Keep a build of a return; its index among the return's builds."""
        with self._lock:
            builds = self._builds.setdefault(return_id, [])
            builds.append(record)
            return len(builds) - 1

    def builds(self, return_id: str) -> tuple[FilingRecord, ...]:
        """Every build of a return, the first first."""
        with self._lock:
            return tuple(self._builds.get(return_id, ()))

    # -- comparisons ----------------------------------------------------------------

    def comparison(self, baseline: OpenedReturn, candidate: OpenedReturn) -> ReturnComparison:
        """``candidate`` compared with ``baseline``, worked out once for the pair.

        An opened return never changes — overrides are drafted beside it — so a
        pair's comparison holds for the session. Asked for again while it is
        being worked out, it is waited for, not worked out a second time.
        """
        key = (baseline.return_id, candidate.return_id)
        names = (
            Names(baseline.name, candidate.name)
            if baseline.name != candidate.name
            else Names(f"{baseline.name} (earlier)", f"{candidate.name} (later)")
        )

        def keep(made: ReturnComparison) -> None:
            self._comparisons[key] = made

        return self._once(
            ("comparison", *key),
            lambda: self._comparisons.get(key),
            lambda: compare_returns(_reading(baseline), _reading(candidate), names=names),
            keep,
        )

    def kept_comparison(
        self, baseline: OpenedReturn, candidate: OpenedReturn
    ) -> ReturnComparison | None:
        """The pair's comparison if it has been worked out; never works it out."""
        with self._lock:
            return self._comparisons.get((baseline.return_id, candidate.return_id))

    # -- helpers ------------------------------------------------------------------

    def _validations_drawn(self, return_id: str) -> tuple[ReturnValidation, ...]:
        """The validations a page of the return can draw now; call it under the lock.

        The as-opened one, which withdrawing every override draws again, and the
        one of the drafts as they now stand, once ``working`` has it. A
        validation of drafts since changed is neither: no page draws it again.
        """
        drawn: list[ReturnValidation] = []
        opened = self._returns.get(return_id)
        if opened is not None:
            drawn.append(opened.validation)
        found = self._working.get(return_id)
        if found is not None and found[0] == self._revisions.get(return_id, 0):
            drawn.append(found[1].current.validation)
        return tuple(drawn)

    def _once[T](
        self,
        key: tuple[object, ...],
        kept: Callable[[], T | None],
        make: Callable[[], T],
        keep: Callable[[T], None],
    ) -> T:
        """What ``kept`` finds; else ``make``'s result, made once for all who ask meanwhile.

        The first thread to ask for ``key`` makes it and hands it to ``keep``;
        any other asking for ``key`` while it does waits for it and gets the
        same result, kept or not. If ``make`` raises, the exception goes to the
        thread that made it and no one is left waiting: a thread that was
        waiting makes its own. ``kept`` and ``keep`` run under the workspace's
        lock, ``make`` outside it.
        """
        while True:
            with self._lock:
                found = kept()
                if found is not None:
                    return found
                flight = self._flights.get(key)
                if flight is None:
                    flight = self._flights[key] = _Flight[T]()
                    break
            flight.ended.wait()
            if flight.made is not None:
                return flight.made
        try:
            made = make()
            flight.made = made
            with self._lock:
                keep(made)
            return made
        finally:
            with self._lock:
                del self._flights[key]
            flight.ended.set()


@dataclass(frozen=True, eq=False)
class _KeptEvidence:
    """An evidence file written for one validation of a return.

    Attributes:
        validation: The validation whose verdict the file answers for.
        path: Where it was written, whole, before it was first handed out.
    """

    validation: ReturnValidation
    path: Path


class _Flight[T]:
    """One piece of work under way in the workspace, and what it made once it has."""

    def __init__(self) -> None:
        self.ended = threading.Event()
        #: Set before ``ended``; still ``None`` when the work raised.
        self.made: T | None = None


def _attribution_key(working: WorkingReturn, dimension: str) -> _AttributionKey:
    """What an attribution is kept under: the return, its drafts and the column.

    The drafts themselves, not a count of changes: the same drafts give the
    same return, however they came to be drafted.
    """
    return (working.opened.return_id, working.drafts, dimension)


def _work_out(
    opened: OpenedReturn,
    drafts: tuple[Adjustment, ...],
    progress: ProgressCallback | None = None,
) -> WorkingReturn:
    """``opened`` with ``drafts`` applied and validated, as a build would validate it."""
    if not drafts:
        return WorkingReturn(opened=opened, current=opened)
    try:
        ret, applied = apply_adjustments(opened.ret, drafts)
    except AdjustmentError as exc:
        return WorkingReturn(opened=opened, current=opened, drafts=drafts, problem=str(exc))
    validation = validate_return(
        ret,
        release=opened.release,
        source_findings=opened.reading.findings,
        source=opened.validation.source,
        progress=progress,
        max_failures=_EVERY_FAILURE,
    )
    current = replace(opened, reading=replace(opened.reading, ret=ret), validation=validation)
    logger.info("validated %s with %d override(s)", opened.name, len(applied))
    return WorkingReturn(
        opened=opened, current=current, drafts=drafts, applied=applied, problem=None
    )


def _write_evidence(current: OpenedReturn, folder: Path) -> Path:
    """Collect ``current``'s evidence as ``rwa-filer validate --evidence`` does, into a new file."""
    collected = collect_evidence(
        current.ret,
        release=current.release,
        source_findings=current.reading.findings,
        source=current.validation.source,
    )
    path = folder / f"{current.return_id}.{secrets.token_hex(4)}.evidence.jsonl"
    return write_evidence(collected, path).path


def _reading(opened: OpenedReturn) -> SourceReading:
    """What reading the return established, with the release it was validated against."""
    return SourceReading(
        ret=opened.reading.ret,
        release=opened.release,
        findings=opened.reading.findings,
        detail=opened.reading.detail,
    )


def safe_file_name(filename: str) -> str:
    """``filename`` reduced to a bare name that cannot leave its folder.

    The browser sends the name it likes; only its last path component is kept,
    and only characters that need no quoting anywhere.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("_", base).strip("._")
    return cleaned or _FALLBACK_NAME
