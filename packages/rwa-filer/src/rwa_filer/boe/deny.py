"""
The Bank's validations deny list — rules its gateway no longer runs, or runs as warnings.

Pipeline position:
    boe/data/deny/<release>.json (built by ``boe.deny_importer`` from the Bank's
    workbook)  ->  load_deny_list  ->  DenyList
        ->  rwa_filer.release (each release carries its own)
        ->  validate.execution.apply_deny_list (the gateway engine's results)
        ->  rules.catalogue.load_rules (the template-level engine's liveness)

Key responsibilities:
- Load the deny list packaged for one taxonomy release and present each entry:
  the rule, the module it applies to, what the Bank did (deactivated, or
  downgraded to a warning), the date the change was applied at the gateway,
  and the known-issues log entry that explains it.
- Say which entries are IN FORCE on a date. An entry is in force from its
  "Date Applied"; one with no date has been identified by the Bank but is not
  yet applied, and is listed as pending — never applied.
- Say it in words, one way, for every surface that reports a rule
  (``DenyEntry.describe``).

What the deny list is, in the Bank's words (its ``Note`` sheet): "These
validation execution amendments are applied post-taxonomy publication and
therefore override the information provided in the relevant taxonomy and the
taxonomy validations spreadsheet. Validation logic and scope will never be
altered in this document, only their execution configuration (severity)."
A deactivated rule "will not be executed in the data collection system and
reporters are not expected to meet the requirements of this rule"; a downgraded
one is an Error the gateway now treats as a Warning: "submissions that fail
this rule will be accepted in the system."

So the deny list is the gateway's configuration on the day a return is
submitted, not a property of the return: an entry is matched to the run (or
submission) date, never to the return's reference date — the same date a
release is chosen by. The rule itself is unchanged: its logic, scope and
``Rule.fingerprint`` are the taxonomy's, whatever the deny list says.

A rule is identified by its module AND its code: the same code names different
rules in different rule books (``boe_b1022`` is deactivated for PRA115 only,
and is a different, enforced rule of PRA001).

References:
- Bank of England, "Banking validations deny list" (boe-banking-validations-
  deny-list-<month>-<year>.xlsx), sheet "Note" and one sheet per taxonomy release
- Bank of England, Banking taxonomy known-issues log (boe-banking-known-issues-
  <month>-<year>.xlsx), sheet "Known Issues"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.catalogue import canonical_sha256

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Where the packaged deny lists live: ``boe/data/deny/<release>.json``. A
#: subdirectory, so ``boe.catalogue.available_rulebooks`` (which lists
#: ``boe/data/*.json``) never reads one as a rule book.
DENY_PACKAGE: Final = "rwa_filer.boe"
DENY_DIRECTORY: Final = ("data", "deny")
DENY_FORMAT: Final = 1
DENY_SUFFIX: Final = ".json"

#: What the Bank did to a rule — the workbook's "Deny Type".
DENY_DEACTIVATED: Final = "deactivated"
DENY_DOWNGRADED: Final = "downgraded"
DENY_TYPES: Final = (DENY_DEACTIVATED, DENY_DOWNGRADED)

#: Who publishes the list, as every sentence about it names them.
PUBLISHER: Final = "the Bank of England"


class DenyListNotFoundError(LookupError):
    """No deny list is packaged for the requested release."""


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class DenyEntry:
    """One rule the Bank has deactivated, or downgraded to a warning, at its gateway.

    Attributes:
        rule_id: The rule's code in the release's rule book.
        module: The reporting module the change applies to.
        deny_type: ``deactivated`` or ``downgraded``.
        date_applied: The day the change took effect at the gateway; ``None``
            for one the Bank has identified but not yet applied.
        known_issue: The number of the known-issues log entry that explains it,
            where the log names the rule.
        published_code: The code as the Bank's workbook spells it, where that
            differs from ``rule_id`` (a typo the importer resolved — see
            ``boe.deny_importer``); ``None`` otherwise.
    """

    rule_id: str
    module: str
    deny_type: str
    date_applied: date | None = None
    known_issue: int | None = None
    published_code: str | None = None

    @property
    def is_pending(self) -> bool:
        """Whether the Bank has identified the change but not yet applied it."""
        return self.date_applied is None

    @property
    def is_deactivation(self) -> bool:
        return self.deny_type == DENY_DEACTIVATED

    def in_force_on(self, day: date) -> bool:
        """Whether the change applies at the gateway on ``day``: applied on or before it."""
        return self.date_applied is not None and self.date_applied <= day

    def describe(self) -> str:
        """What the Bank did, when, and why — the one wording every surface uses.

        For example ``deactivated by the Bank of England on 19 October 2026
        (validations deny list; known issues log #22)``.
        """
        action = "deactivated" if self.is_deactivation else "downgraded from Error to Warning"
        when = (
            f"on {_long_date(self.date_applied)}"
            if self.date_applied is not None
            else "— identified, not yet applied at the gateway"
        )
        sources = ["validations deny list"]
        if self.known_issue is not None:
            sources.append(f"known issues log #{self.known_issue}")
        if self.published_code is not None:
            sources.append(f"listed as {self.published_code}")
        return f"{action} by {PUBLISHER} {when} ({'; '.join(sources)})"

    def record(self) -> dict[str, Any]:
        """The entry as JSON-ready data: the packaged file's own shape."""
        record: dict[str, Any] = {
            "rule_id": self.rule_id,
            "module": self.module,
            "deny_type": self.deny_type,
            "date_applied": self.date_applied.isoformat() if self.date_applied else None,
            "known_issue": self.known_issue,
        }
        if self.published_code is not None:
            record["published_code"] = self.published_code
        return record


@dataclass(frozen=True)
class UnmatchedCode:
    """A code the Bank's deny list names that no rule of the release has.

    Kept in the packaged file, never dropped: it is either a typo in the Bank's
    list or a rule this package does not ship, and either is worth knowing.
    """

    code: str
    module: str
    deny_type: str
    date_applied: date | None
    reason: str

    def record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "module": self.module,
            "deny_type": self.deny_type,
            "date_applied": self.date_applied.isoformat() if self.date_applied else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DenyList:
    """The deny list of one taxonomy release.

    Attributes:
        release: The taxonomy release, e.g. ``"4.1.1"``.
        entries: Every entry that names a rule of the release.
        unmatched: Every code the workbook lists that names no rule of it.
        source: Where it came from: the workbook's file name, SHA-256, sheet,
            publication date and address, and the known-issues log joined.
        file: The packaged file it was loaded from; ``None`` for one built in
            memory or for an empty list.
        content_sha256: SHA-256 of the file's content in canonical JSON.
    """

    release: str
    entries: tuple[DenyEntry, ...] = ()
    unmatched: tuple[UnmatchedCode, ...] = ()
    source: Mapping[str, Any] = field(default_factory=dict)
    file: str | None = None
    content_sha256: str = ""

    @classmethod
    def empty(cls, release: str = "") -> DenyList:
        """A deny list with nothing on it — for a release that ships none."""
        return cls(release=release)

    def entry(self, module: str, rule_id: str) -> DenyEntry | None:
        """The entry for ``rule_id`` in ``module``, or ``None``."""
        wanted = module.upper()
        return next(
            (
                item
                for item in self.entries
                if item.rule_id == rule_id and item.module.upper() == wanted
            ),
            None,
        )

    def for_module(self, module: str) -> tuple[DenyEntry, ...]:
        """Every entry for ``module``, applied or not."""
        wanted = module.upper()
        return tuple(item for item in self.entries if item.module.upper() == wanted)

    def in_force(self, module: str, day: date) -> dict[str, DenyEntry]:
        """The entries for ``module`` that apply at the gateway on ``day``, by rule code."""
        return {item.rule_id: item for item in self.for_module(module) if item.in_force_on(day)}

    def not_in_force(self, module: str, day: date) -> tuple[DenyEntry, ...]:
        """The entries for ``module`` that do not apply on ``day``: pending, or applied later."""
        return tuple(item for item in self.for_module(module) if not item.in_force_on(day))

    def to_payload(self) -> dict[str, Any]:
        """The list as its packaged file holds it."""
        return {
            "format": DENY_FORMAT,
            "release": self.release,
            "source": dict(self.source),
            "entries": [item.record() for item in self.entries],
            "unmatched": [item.record() for item in self.unmatched],
        }


def available_deny_lists() -> tuple[str, ...]:
    """The releases a deny list is packaged for, sorted by file name."""
    root = _root()
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name.removesuffix(DENY_SUFFIX)
            for entry in root.iterdir()
            if entry.name.endswith(DENY_SUFFIX)
        )
    )


@cache
def load_deny_list(release: str) -> DenyList:
    """The deny list packaged for ``release``. Cached: package data never changes.

    Raises:
        DenyListNotFoundError: none is packaged for the release.
        ValueError: the file is in a format this version cannot read.
    """
    resource = _root().joinpath(deny_list_file(release))
    if not resource.is_file():
        raise DenyListNotFoundError(f"No deny list is packaged for taxonomy {release}")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    deny_list = deny_list_from(payload, file=resource.name)
    if deny_list.release != release:
        raise ValueError(
            f"{resource.name} holds the deny list of taxonomy {deny_list.release}, not {release}"
        )
    return deny_list


def deny_list_from(payload: Mapping[str, Any], *, file: str | None = None) -> DenyList:
    """Build a ``DenyList`` from a deny-list file's content.

    Raises:
        ValueError: the format is not one this version reads, or an entry's
            deny type is not one of ``DENY_TYPES``.
    """
    if payload.get("format") != DENY_FORMAT:
        raise ValueError(
            f"Deny list format {payload.get('format')!r} is not supported (expected {DENY_FORMAT})"
        )
    entries = tuple(_entry(item) for item in payload.get("entries", ()))
    unmatched = tuple(
        UnmatchedCode(
            code=str(item["code"]),
            module=str(item["module"]),
            deny_type=_deny_type(item["deny_type"]),
            date_applied=_date(item.get("date_applied")),
            reason=str(item.get("reason", "")),
        )
        for item in payload.get("unmatched", ())
    )
    return DenyList(
        release=str(payload["release"]),
        entries=entries,
        unmatched=unmatched,
        source=dict(payload.get("source", {})),
        file=file,
        content_sha256=canonical_sha256(payload),
    )


def deny_list_file(release: str) -> str:
    """The packaged file name of ``release``'s deny list, e.g. ``4.1.1.json``."""
    return f"{release}{DENY_SUFFIX}"


def deny_summary(deny_list: DenyList, module: str, day: date) -> dict[str, Any]:
    """What the deny list did for ``module`` on ``day``, as a JSON-ready record.

    The record the validation report's summary and the evidence identity carry:
    which rules were deactivated or downgraded, and which entries were not
    applied (pending, or applied after ``day``).
    """
    in_force = deny_list.in_force(module, day)
    return {
        "release": deny_list.release,
        "file": deny_list.file,
        "sha256": deny_list.content_sha256 or None,
        "applied_on": day.isoformat(),
        "deactivated": sorted(
            rule_id for rule_id, item in in_force.items() if item.is_deactivation
        ),
        "downgraded": sorted(
            rule_id for rule_id, item in in_force.items() if not item.is_deactivation
        ),
        "not_applied": [item.record() for item in deny_list.not_in_force(module, day)],
    }


# =============================================================================
# Private helpers
# =============================================================================


def _root() -> Any:  # noqa: ANN401 - an importlib.resources Traversable
    return resources.files(DENY_PACKAGE).joinpath(*DENY_DIRECTORY)


def _entry(item: Mapping[str, Any]) -> DenyEntry:
    known = item.get("known_issue")
    return DenyEntry(
        rule_id=str(item["rule_id"]),
        module=str(item["module"]),
        deny_type=_deny_type(item["deny_type"]),
        date_applied=_date(item.get("date_applied")),
        known_issue=int(known) if known is not None else None,
        published_code=item.get("published_code"),
    )


def _deny_type(value: object) -> str:
    text = str(value)
    if text not in DENY_TYPES:
        raise ValueError(f"deny type {text!r} is not one of {', '.join(DENY_TYPES)}")
    return text


def _date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _long_date(day: date) -> str:
    """``19 October 2026`` — as ``rwa_filer.release.long_date`` writes it."""
    return f"{day.day} {day:%B} {day.year}"
