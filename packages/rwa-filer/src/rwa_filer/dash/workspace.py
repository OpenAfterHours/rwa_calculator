"""
The dashboard's workspace — the returns opened in one ``rwa-filer dash`` session.

Pipeline position:
    uploaded file / local path  ->  Workspace.open
        ->  readers.open_source  ->  validate.validate_return
        ->  OpenedReturn  ->  Workspace.working  ->  the dashboard's pages

Key responsibilities:
- Hold each opened return with the validation it was given, so that drawing a
  page never re-validates.
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
- Open a return again against another taxonomy release, beside the first.
- Keep uploaded files under the one directory the session owns, under names a
  browser cannot steer outside it.
- Be safe to call from the server's worker threads.

References:
- rwa_filer.readers.open_source — how a named file is read, as the CLI reads it
- rwa_filer.validate.returns.validate_return — what "validated" means
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from rwa_filer.readers import HeaderFields, SourceReading, open_source
from rwa_filer.validate.identity import source_identity
from rwa_filer.validate.returns import validate_return
from rwa_filer.workflow.adjustments import AdjustmentError, apply_adjustments
from rwa_filer.workflow.compare import compare_returns
from rwa_filer.workflow.explain import Names

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.filing import FilingPackage
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.returns import ReturnValidation
    from rwa_filer.workflow.adjustments import Adjustment, AppliedAdjustment
    from rwa_filer.workflow.compare import ReturnComparison

#: A cell's full address: table, sheet, open-axis key, row, column.
Cell = tuple[str, str | None, str | None, str, str]

logger = logging.getLogger(__name__)

#: Characters an uploaded file's name may keep; any other run becomes ``_``.
_UNSAFE: Final = re.compile(r"[^A-Za-z0-9._-]+")
#: The name an upload is given when nothing of its own name survives.
_FALLBACK_NAME: Final = "upload"


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
        self._lock = threading.Lock()

    def open(
        self,
        path: Path,
        fields: HeaderFields | None = None,
        *,
        name: str | None = None,
        taxonomy: str | None = None,
    ) -> OpenedReturn:
        """Read and validate ``path``, and keep it under a new id.

        Args:
            path: The file.
            fields: Header fields given beside it.
            name: The name to show it under; defaults to the file's.
            taxonomy: The release to validate it against, by version; defaults
                to the workspace's, else the default release for the module.

        Raises:
            ValueError: the file is missing, unsupported, lacks a header it
                needs, or is not readable as what its suffix says it is.
            ReleaseNotFoundError: the taxonomy release could not be resolved.
        """
        reading = open_source(path, fields, taxonomy=taxonomy or self.taxonomy)
        validation = validate_return(
            reading.ret,
            release=reading.release,
            source_findings=reading.findings,
            source=source_identity(path),
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

    def reopen(self, opened: OpenedReturn, taxonomy: str) -> OpenedReturn:
        """Open ``opened``'s file again, against another taxonomy release.

        The return keeps its header — the one it was opened with, overrides
        included — and is kept under a new id beside the first, so the two can
        be compared. Drafted overrides are not carried across: a cell one
        release accepts may not exist in another.

        Raises:
            ValueError: the file can no longer be read.
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
        return self.open(opened.path, fields, name=opened.name, taxonomy=taxonomy)

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

    def working(self, opened: OpenedReturn) -> WorkingReturn:
        """``opened`` with its drafted overrides applied, validated once per change of them.

        A page drawn after the drafts last changed gets the same object back,
        so only the first page drawn after a change pays for the validation.
        """
        return_id = opened.return_id
        with self._lock:
            revision = self._revisions.get(return_id, 0)
            drafts = tuple(self._adjustments.get(return_id, {}).values())
            kept = self._working.get(return_id)
        if kept is not None and kept[0] == revision:
            return kept[1]
        made = _work_out(opened, drafts)
        with self._lock:
            if self._revisions.get(return_id, 0) == revision:
                self._working[return_id] = (revision, made)
        return made

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
        pair's comparison holds for the session.
        """
        key = (baseline.return_id, candidate.return_id)
        with self._lock:
            found = self._comparisons.get(key)
        if found is not None:
            return found
        names = (
            Names(baseline.name, candidate.name)
            if baseline.name != candidate.name
            else Names(f"{baseline.name} (earlier)", f"{candidate.name} (later)")
        )
        made = compare_returns(_reading(baseline), _reading(candidate), names=names)
        with self._lock:
            return self._comparisons.setdefault(key, made)


def _work_out(opened: OpenedReturn, drafts: tuple[Adjustment, ...]) -> WorkingReturn:
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
    )
    current = replace(opened, reading=replace(opened.reading, ret=ret), validation=validation)
    logger.info("validated %s with %d override(s)", opened.name, len(applied))
    return WorkingReturn(
        opened=opened, current=current, drafts=drafts, applied=applied, problem=None
    )


def _reading(opened: OpenedReturn) -> SourceReading:
    """What reading the return established, with the release it was validated against."""
    return SourceReading(
        ret=opened.reading.ret, release=opened.release, findings=opened.reading.findings
    )


def safe_file_name(filename: str) -> str:
    """``filename`` reduced to a bare name that cannot leave its folder.

    The browser sends the name it likes; only its last path component is kept,
    and only characters that need no quoting anywhere.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("_", base).strip("._")
    return cleaned or _FALLBACK_NAME
