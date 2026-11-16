"""
Deny-list importer — the Bank's validations deny list, as one packaged file per release.

Pipeline position:
    boe-banking-validations-deny-list-<month>-<year>.xlsx (+ the known-issues log)
        ->  import_deny_list(workbook, release)  ->  DenyImport
        ->  write_deny_list  ->  boe/data/deny/<release>.json  ->  boe.deny.load_deny_list
    ``scripts/build_filer_release.py <release> --deny-list`` is the repository's
    command; ``rwa-filer rulebook deny-list import`` is the package's.

Key responsibilities:
- Read the release's own sheet ("Version 4.1.1"; the Bank's sheet names can
  carry a trailing space) by its column NAMES: Validation Code, Date Applied,
  Deny Type, Module.
- Match every code to a rule of the release: the module's rule book must have
  a rule of that code in that module. A code that matches none is REPORTED and
  kept in the file under ``unmatched`` — never silently dropped.
- Resolve exactly one kind of typo, by a rule stated here and tested: the
  Bank's rule numbers have four digits, so a code whose number has MORE than
  four with surplus leading zeros (``boe_b04006_1``) is read as the four-digit
  code (``boe_b4006_1``) — only when the code as written names no rule of the
  module and the four-digit code names one. The code as written is kept on the
  entry (``published_code``). Anything else stays unmatched.
- Where the known-issues log is given, give each entry the number of the log
  entry that explains it: the highest-numbered issue whose title names the rule
  (as resolved or as written) and whose entry point names the module, or "All".
- Write deterministic bytes, so ``--check`` can compare a rebuild with the
  packaged file exactly.

References:
- Bank of England, "Banking validations deny list" — sheet "Note": "Date
  Applied - the date the change was applied in the data collection system. If
  it is blank then rules have been identified for execution modification but
  this has not been implemented yet."
- Bank of England, Banking taxonomy known-issues log — sheet "Known Issues"
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.deny import (
    DENY_DEACTIVATED,
    DENY_DOWNGRADED,
    DenyEntry,
    DenyList,
    UnmatchedCode,
    deny_list_from,
)
from rwa_filer.inputs import load_workbook
from rwa_filer.release import release_rulebook

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The deny list has one sheet per taxonomy release, named "Version <release>".
SHEET_PREFIX: Final = "Version "
#: The columns read, by the header the Bank gives them.
COLUMN_CODE: Final = "Validation Code"
COLUMN_DATE: Final = "Date Applied"
COLUMN_TYPE: Final = "Deny Type"
COLUMN_MODULE: Final = "Module"

#: The known-issues log's sheet for the banking taxonomy, and the columns read.
KNOWN_ISSUES_SHEET: Final = "Known Issues"
ISSUE_NUMBER: Final = "#"
ISSUE_ENTRY_POINT: Final = "Entry point"
ISSUE_TITLE: Final = "Issue title"
ISSUE_LAST_UPDATED: Final = "Last updated:"
#: An entry point the log uses for an issue that concerns every module.
ENTRY_POINT_ALL: Final = "ALL"

#: How a code that names no rule was resolved (``resolved_by`` in a report).
RESOLVED_LEADING_ZERO: Final = "leading_zero"
#: The number of digits in a Bank rule code's number (``boe_b0710``).
RULE_NUMBER_DIGITS: Final = 4

#: The Bank's words for each deny type, lower-cased, onto the packaged value.
_DENY_TYPE_WORDS: Final[Mapping[str, str]] = {
    "deactivated": DENY_DEACTIVATED,
    "deactivate": DENY_DEACTIVATED,
    "downgraded": DENY_DOWNGRADED,
    "downgrade to warning": DENY_DOWNGRADED,
    "downgraded to warning": DENY_DOWNGRADED,
}
#: ``boe_b04006_1`` -> head ``boe_b``, number ``04006``, tail ``_1``.
_CODE: Final = re.compile(r"(?P<head>[A-Za-z]+_[A-Za-z]+)(?P<number>\d+)(?P<tail>.*)")
#: A rule code as the known-issues log writes it in an issue's title.
_TITLE_CODE: Final = re.compile(r"boe[_-][A-Za-z0-9][A-Za-z0-9_\-]*")
_TOKEN: Final = re.compile(r"[A-Za-z0-9_]+")
_DOTTED_DATE: Final = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class KnownIssue:
    """One entry of the Bank's known-issues log, as far as the join needs it."""

    number: int
    entry_points: frozenset[str]
    rule_ids: frozenset[str]
    title: str


@dataclass(frozen=True)
class DenyImport:
    """What importing one release's sheet of the deny list established.

    Attributes:
        deny_list: The list as it would be packaged.
        rows: The codes the sheet lists.
        resolved: Entries whose code as written named no rule, resolved by the
            leading-zero rule (see the module docstring).
        without_issue: Entries no known-issues log entry names — only when a
            log was given.
    """

    deny_list: DenyList
    rows: int
    resolved: tuple[DenyEntry, ...] = ()
    without_issue: tuple[DenyEntry, ...] = ()

    @property
    def payload(self) -> dict[str, Any]:
        """The packaged file's content."""
        return self.deny_list.to_payload()

    def lines(self) -> tuple[str, ...]:
        """What the import found, one line each, for a command to print."""
        deny_list = self.deny_list
        pending = [item for item in deny_list.entries if item.is_pending]
        lines = [
            f"taxonomy {deny_list.release}: {self.rows} code(s) on sheet "
            f"{deny_list.source.get('sheet')!r} — {len(deny_list.entries)} matched "
            f"({len(self.resolved)} resolved), {len(deny_list.unmatched)} unmatched, "
            f"{len(pending)} pending"
        ]
        lines += [
            f"  resolved   {item.module} {item.published_code} -> {item.rule_id} "
            "(a surplus leading zero in the rule number)"
            for item in self.resolved
        ]
        lines += [
            f"  UNMATCHED  {item.module} {item.code}: {item.reason}" for item in deny_list.unmatched
        ]
        lines += [
            f"  pending    {item.module} {item.rule_id} ({item.deny_type}; no date applied)"
            for item in pending
        ]
        lines += [
            f"  no issue   {item.module} {item.rule_id}: no known-issues entry names it"
            for item in self.without_issue
        ]
        return tuple(lines)


def import_deny_list(
    workbook: Path,
    release: str,
    *,
    known_issues: Path | None = None,
    published: date | None = None,
    url: str | None = None,
) -> DenyImport:
    """Import release ``release``'s sheet of the Bank's deny-list workbook.

    Args:
        workbook: The Bank's ``.xlsx``.
        release: The taxonomy release, e.g. ``"4.1.1"``. Codes are matched to
            the rule books this package ships for it.
        known_issues: The Bank's known-issues log, to give each entry its issue
            number. Optional.
        published: When the list was published. Defaults to the newest Date
            Applied the sheet records — the last change it shows.
        url: Where the workbook was downloaded from, recorded in the file.

    Raises:
        MissingExtraError: ``openpyxl`` is not installed (``rwa-filer[excel]``).
        ValueError: the workbook is not readable, has no sheet for the release,
            lacks one of the columns read, gives a deny type this package does
            not know, or lists one code twice with different settings.
    """
    sheet_title, rows = _read_sheet(workbook, release)
    issues = read_known_issues(known_issues) if known_issues is not None else None
    entries: list[DenyEntry] = []
    unmatched: list[UnmatchedCode] = []
    resolved: list[DenyEntry] = []
    for code, module, deny_type, applied in rows:
        codes = _rule_codes(release, module)
        if codes is None:
            reason = f"no rule book of taxonomy {release} covers module {module}"
            unmatched.append(UnmatchedCode(code, module, deny_type, applied, reason))
            continue
        rule_id, resolution = resolve_code(code, codes)
        if rule_id is None:
            reason = f"no rule of module {module} in taxonomy {release} has this code"
            unmatched.append(UnmatchedCode(code, module, deny_type, applied, reason))
            continue
        entry = DenyEntry(
            rule_id=rule_id,
            module=module,
            deny_type=deny_type,
            date_applied=applied,
            known_issue=_issue_for((rule_id, code), module, issues) if issues else None,
            published_code=code if resolution is not None else None,
        )
        entries.append(entry)
        if resolution is not None:
            resolved.append(entry)
    entries.sort(key=lambda item: (item.module, item.rule_id))
    unmatched.sort(key=lambda item: (item.module, item.code))
    dates = [applied for *_rest, applied in rows if applied is not None]
    stated = published or (max(dates) if dates else None)
    source = {
        "publisher": "Bank of England",
        "file": workbook.name,
        "sha256": _sha256(workbook),
        "sheet": sheet_title,
        "published": stated.isoformat() if stated else None,
        "url": url,
        "known_issues": None if known_issues is None else _issues_source(known_issues),
    }
    payload = DenyList(
        release=release, entries=tuple(entries), unmatched=tuple(unmatched), source=source
    ).to_payload()
    deny_list = deny_list_from(payload)
    imported = DenyImport(
        deny_list=deny_list,
        rows=len(rows),
        resolved=tuple(resolved),
        without_issue=tuple(
            item for item in entries if issues is not None and item.known_issue is None
        ),
    )
    for line in imported.lines():
        logger.info("%s", line)
    return imported


def resolve_code(code: str, codes: Iterable[str]) -> tuple[str | None, str | None]:
    """The rule ``code`` names among ``codes``, and how it was resolved.

    Returns ``(code, None)`` when it names a rule as written;
    ``(resolved, RESOLVED_LEADING_ZERO)`` when only the four-digit reading of a
    longer, zero-padded number does (``boe_b04006_1`` -> ``boe_b4006_1``);
    ``(None, None)`` otherwise.
    """
    known = set(codes)
    if code in known:
        return code, None
    match = _CODE.fullmatch(code)
    if match is None:
        return None, None
    number = match.group("number")
    if len(number) <= RULE_NUMBER_DIGITS or not number.startswith("0"):
        return None, None
    shortened = number.lstrip("0").zfill(RULE_NUMBER_DIGITS)
    if len(shortened) != RULE_NUMBER_DIGITS:
        return None, None
    candidate = f"{match.group('head')}{shortened}{match.group('tail')}"
    return (candidate, RESOLVED_LEADING_ZERO) if candidate in known else (None, None)


def read_known_issues(path: Path) -> tuple[KnownIssue, ...]:
    """The banking taxonomy's known issues, from the Bank's log.

    Raises:
        MissingExtraError: ``openpyxl`` is not installed.
        ValueError: the log has no "Known Issues" sheet, or no header row.
    """
    rows = _sheet_rows(path, KNOWN_ISSUES_SHEET, command="rulebook deny-list import")
    header_at = next(
        (index for index, row in enumerate(rows) if row and _text(row[0]) == ISSUE_NUMBER), None
    )
    if header_at is None:
        raise ValueError(f"{path.name}: sheet {KNOWN_ISSUES_SHEET!r} has no '#' header row")
    columns = _columns(rows[header_at], (ISSUE_NUMBER, ISSUE_ENTRY_POINT, ISSUE_TITLE), path)
    issues: list[KnownIssue] = []
    for row in rows[header_at + 1 :]:
        number = _cell(row, columns[ISSUE_NUMBER])
        if not isinstance(number, int | float) or isinstance(number, bool):
            continue
        title = _text(_cell(row, columns[ISSUE_TITLE]))
        issues.append(
            KnownIssue(
                number=int(number),
                entry_points=frozenset(
                    token.upper()
                    for token in _TOKEN.findall(_text(_cell(row, columns[ISSUE_ENTRY_POINT])))
                ),
                rule_ids=frozenset(code.rstrip("_-") for code in _TITLE_CODE.findall(title)),
                title=title,
            )
        )
    return tuple(issues)


def dump_deny_list(payload: Mapping[str, Any]) -> str:
    """The file's text: the bytes ``write_deny_list`` writes and ``--check`` compares."""
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def write_deny_list(payload: Mapping[str, Any], path: Path) -> None:
    """Write a deny list to ``path``, through an open handle (S2083: see release_build)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(dump_deny_list(payload))


def is_deny_list_current(payload: Mapping[str, Any], committed: str | None) -> bool:
    """Whether ``committed`` (a packaged file's text) is exactly what ``payload`` writes."""
    return committed is not None and committed == dump_deny_list(payload)


# =============================================================================
# Private helpers
# =============================================================================


def _read_sheet(
    workbook: Path, release: str
) -> tuple[str, list[tuple[str, str, str, date | None]]]:
    """The release's sheet title and its rows as ``(code, module, deny type, date)``."""
    wanted = f"{SHEET_PREFIX}{release}"
    book = load_workbook(
        workbook, needed_for="Reading the Bank's deny list", command="rulebook deny-list import"
    )
    try:
        sheet = next((item for item in book.worksheets if item.title.strip() == wanted), None)
        if sheet is None:
            names = ", ".join(repr(item.title) for item in book.worksheets)
            raise ValueError(f"{workbook.name} has no sheet {wanted!r} (it has {names})")
        title = sheet.title
        raw = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()
    header_at = next(
        (index for index, row in enumerate(raw) if COLUMN_CODE in {_text(cell) for cell in row}),
        None,
    )
    if header_at is None:
        raise ValueError(f"{workbook.name}: sheet {title!r} has no {COLUMN_CODE!r} column")
    columns = _columns(
        raw[header_at], (COLUMN_CODE, COLUMN_DATE, COLUMN_TYPE, COLUMN_MODULE), workbook
    )
    rows: dict[tuple[str, str], tuple[str, str, str, date | None]] = {}
    for row in raw[header_at + 1 :]:
        code = _text(_cell(row, columns[COLUMN_CODE]))
        if not code:
            continue
        module = _text(_cell(row, columns[COLUMN_MODULE])).upper()
        parsed = (
            code,
            module,
            _deny_type(_cell(row, columns[COLUMN_TYPE]), workbook),
            _as_date(_cell(row, columns[COLUMN_DATE]), workbook),
        )
        earlier = rows.get((module, code))
        if earlier is not None and earlier != parsed:
            raise ValueError(f"{workbook.name}: {module} {code} is listed twice, differently")
        rows[(module, code)] = parsed
    return title, list(rows.values())


def _rule_codes(release: str, module: str) -> frozenset[str] | None:
    """The codes of ``module``'s rules in ``release``; ``None`` when no rule book covers it."""
    rulebook = release_rulebook(release, module)
    if rulebook is None:
        return None
    return frozenset(
        rule.rule_id
        for rule in rulebook.rules
        if module in (name.upper() for name in rule.severities)
    )


def _issue_for(codes: tuple[str, str], module: str, issues: tuple[KnownIssue, ...]) -> int | None:
    """The newest known issue naming the rule (as resolved or as written) for the module."""
    named = [
        issue.number
        for issue in issues
        if issue.rule_ids & set(codes)
        and (module.upper() in issue.entry_points or ENTRY_POINT_ALL in issue.entry_points)
    ]
    return max(named) if named else None


def _issues_source(path: Path) -> dict[str, Any]:
    """The known-issues log's identity: its name, checksum and "Last updated" date."""
    rows = _sheet_rows(path, KNOWN_ISSUES_SHEET, command="rulebook deny-list import")
    updated = next(
        (
            _as_date(next((cell for cell in row[1:] if cell is not None), None), path)
            for row in rows
            if row and _text(row[0]) == ISSUE_LAST_UPDATED
        ),
        None,
    )
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "last_updated": updated.isoformat() if updated else None,
    }


def _sheet_rows(path: Path, title: str, *, command: str) -> list[tuple[Any, ...]]:
    book = load_workbook(path, needed_for="Reading the Bank's known-issues log", command=command)
    try:
        sheet = next((item for item in book.worksheets if item.title.strip() == title), None)
        if sheet is None:
            raise ValueError(f"{path.name} has no sheet {title!r}")
        return [tuple(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def _columns(header: tuple[Any, ...], names: tuple[str, ...], path: Path) -> dict[str, int]:
    found = {_text(cell): index for index, cell in enumerate(header) if cell is not None}
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError(f"{path.name}: no column {', '.join(repr(name) for name in missing)}")
    return {name: found[name] for name in names}


def _deny_type(value: object, path: Path) -> str:
    text = _text(value).lower()
    if text not in _DENY_TYPE_WORDS:
        raise ValueError(f"{path.name}: deny type {_text(value)!r} is not one this package reads")
    return _DENY_TYPE_WORDS[text]


def _as_date(value: object, path: Path) -> date | None:
    """A Date Applied cell: a date, an ISO or ``dd.mm.yyyy`` text, or blank (``None``)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    dotted = _DOTTED_DATE.fullmatch(text)
    try:
        if dotted is not None:
            return date(int(dotted.group(3)), int(dotted.group(2)), int(dotted.group(1)))
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path.name}: {text!r} is not a date") from exc


def _cell(row: tuple[Any, ...], index: int) -> Any:  # noqa: ANN401 - a worksheet cell value
    return row[index] if index < len(row) else None


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
