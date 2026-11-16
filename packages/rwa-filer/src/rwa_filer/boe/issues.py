"""
Publisher issues — published rules known to be wrong, and the evidence for each.

Pipeline position:
    boe/data/issues/<release>.json (curated by hand from evidence; never built
    from the Bank's files)  ->  load_issues  ->  IssueRegister
        ->  rwa_filer.release (each release carries its own)
        ->  validate.issue_labels (a label on the verdict; the verdict never changes)
        ->  boe.issues_document (the shareable Markdown) and ``rwa-filer rulebook issues``

Key responsibilities:
- Load the register packaged for one taxonomy release and present each issue:
  what is wrong with which published rules, what the reporting instructions
  say (quoted, with the page), why a return that follows them still fails, a
  minimal correct return that shows it, what the Bank could change, and where
  the issue stands with the Bank (``status``).
- Say which issues name a rule, and whether a rule in hand IS the rule an issue
  names: by its fingerprint (``Rule.fingerprint``), never by its code alone —
  the same code can carry a changed expression in another release.
- Say where on a rule an issue applies (its ``footprint``), so a break the
  issue does not explain is never excused by it: an unsatisfied evaluation is
  inside the footprint when any cell it read matches any selector; an issue
  with no footprint covers the whole rule.
- Say each status in words one way, for every surface that labels a rule.

What an issue's EFFECT means, and so which results it labels:
- ``fails_correct_returns``: a return that follows the instructions breaks
  the rule; labels a FAIL.
- ``passes_wrong_returns``: the rule accepts figures the rules do not permit;
  labels a PASS (a pass is no evidence).
- ``never_runs``: the rule as published never runs on any return; labels a
  rule not evaluated because its formula cannot fire.
- ``no_rule_effect``: the issue is in the instructions or the taxonomy and no
  rule result shows it; it is listed, never labelled.

The register is curated, not imported: what is wrong with a rule is a finding,
with evidence, and the Bank's publications do not list it until the Bank
acknowledges it. A rule the Bank has deactivated at its gateway is told by the
deny list (``boe.deny``), not here: a label never stands in for a status.

References:
- docs/rwa-filer/publisher-issues.md — the register, rendered for sharing
- Bank of England, Banking taxonomy known-issues log — the Bank's own record
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.catalogue import canonical_sha256

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import CellAddress

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Where the packaged registers live: ``boe/data/issues/<release>.json``. A
#: subdirectory, so ``boe.catalogue.available_rulebooks`` (which lists
#: ``boe/data/*.json``) never reads one as a rule book.
ISSUES_PACKAGE: Final = "rwa_filer.boe"
ISSUES_DIRECTORY: Final = ("data", "issues")
ISSUES_FORMAT: Final = 1
ISSUES_SUFFIX: Final = ".json"

#: An issue's id: stable across releases, never reused.
ISSUE_ID_PATTERN: Final = re.compile(r"^PI-[0-9]{2}[a-z]?$")

#: Where an issue stands with the Bank.
STATUS_DRAFT: Final = "draft"
STATUS_RAISED: Final = "raised"
STATUS_ACKNOWLEDGED: Final = "acknowledged"
STATUS_FIXED: Final = "fixed"
STATUS_WITHDRAWN: Final = "withdrawn"
STATUSES: Final = (
    STATUS_DRAFT,
    STATUS_RAISED,
    STATUS_ACKNOWLEDGED,
    STATUS_FIXED,
    STATUS_WITHDRAWN,
)
#: The statuses of an issue still open in the release it is recorded for.
OPEN_STATUSES: Final = (STATUS_DRAFT, STATUS_RAISED, STATUS_ACKNOWLEDGED)

#: What the issue does to a rule's result (see the module docstring).
EFFECT_FAILS_CORRECT_RETURNS: Final = "fails_correct_returns"
EFFECT_PASSES_WRONG_RETURNS: Final = "passes_wrong_returns"
EFFECT_NEVER_RUNS: Final = "never_runs"
EFFECT_NO_RULE_EFFECT: Final = "no_rule_effect"
EFFECTS: Final = (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_PASSES_WRONG_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_NO_RULE_EFFECT,
)
#: The effects that put a label on a rule's result.
LABELLING_EFFECTS: Final = (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_PASSES_WRONG_RETURNS,
    EFFECT_NEVER_RUNS,
)

#: Why the rule is wrong — every cause that applies.
CAUSES: Final = (
    "contradicts_instructions",
    "contradicts_ps126_rules",
    "contradicts_other_rule",
    "contradicts_template",
    "plausibility_not_identity",
    "text_differs_from_formula",
    "instructions_gap",
    "taxonomy_data_type",
    "taxonomy_cells_missing",
    "too_permissive",
    "rounding_allowance",
    "restates_deactivated_eba_rule",
)

#: A rule's part in an issue: the rule that is wrong (``subject``), one it
#: cannot hold together with (``contradicts``), one that shows the example is
#: otherwise correct (``control``), or one that bears on it (``related``).
ROLE_SUBJECT: Final = "subject"
ROLE_CONTRADICTS: Final = "contradicts"
ROLE_CONTROL: Final = "control"
ROLE_RELATED: Final = "related"
ROLES: Final = (ROLE_SUBJECT, ROLE_CONTRADICTS, ROLE_CONTROL, ROLE_RELATED)

#: Whether a break inside a footprint IS the issue (``certain``), or may be the
#: issue or a defect in the return the footprint cannot tell apart (``possible``).
ATTRIBUTION_CERTAIN: Final = "certain"
ATTRIBUTION_POSSIBLE: Final = "possible"
ATTRIBUTIONS: Final = (ATTRIBUTION_CERTAIN, ATTRIBUTION_POSSIBLE)

#: How a publisher-log entry bears on an issue.
LOG_ACKNOWLEDGES: Final = "acknowledges"
LOG_RELATED: Final = "related"
LOG_RELATIONS: Final = (LOG_ACKNOWLEDGES, LOG_RELATED)

#: The selector keys: ``table`` is required, the rest narrow it.
_SELECTOR_LISTS: Final = (
    "rows",
    "columns",
    "sheets",
    "rows_except",
    "columns_except",
    "sheets_except",
)


class IssueRegisterNotFoundError(LookupError):
    """No issue register is packaged for the requested release."""


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class CellSelector:
    """Cells of one table an issue applies to.

    A cell matches when it is in ``table``, its row / column / sheet is in the
    corresponding list where one is given, and in none of the ``*_except``
    lists. A table without a sheet axis has no sheet: a selector listing sheets
    never matches it.
    """

    table: str
    rows: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    rows_except: tuple[str, ...] = ()
    columns_except: tuple[str, ...] = ()
    sheets_except: tuple[str, ...] = ()

    def matches(self, address: CellAddress) -> bool:
        """Whether ``address`` is one of the cells this selector names."""
        if address.table != self.table:
            return False
        return (
            _listed(address.row, self.rows, self.rows_except)
            and _listed(address.column, self.columns, self.columns_except)
            and _listed(address.sheet, self.sheets, self.sheets_except)
        )

    def record(self) -> dict[str, Any]:
        """The selector as the register file holds it: only the keys it uses."""
        record: dict[str, Any] = {"table": self.table}
        for name in _SELECTOR_LISTS:
            codes = getattr(self, name)
            if codes:
                record[name] = list(codes)
        return record

    def describe(self) -> str:
        """In words, e.g. ``OF07.00.01.01 rows other than 0080``."""
        parts = [self.table]
        for name, words in (
            ("rows", "rows"),
            ("columns", "columns"),
            ("sheets", "sheets"),
            ("rows_except", "rows other than"),
            ("columns_except", "columns other than"),
            ("sheets_except", "sheets other than"),
        ):
            codes = getattr(self, name)
            if codes:
                parts.append(f"{words} {', '.join(codes)}")
        return " ".join(parts)


@dataclass(frozen=True)
class IssueRule:
    """One published rule an issue names, as it was when the issue was recorded.

    Attributes:
        module: The reporting module the rule is checked for.
        rule_id: The rule's code.
        role: ``subject``, ``contradicts``, ``control`` or ``related``.
        severity: The rule's severity for the module.
        rule_sha256: ``Rule.fingerprint(module)`` of the rule the issue is
            about. A rule with another fingerprint is another rule.
        footprint: Where on the rule the issue applies; ``None`` for all of it.
        attribution: ``certain`` when a break inside the footprint is the
            issue; ``possible`` when it may instead be the return's own.
    """

    module: str
    rule_id: str
    role: str
    severity: str
    rule_sha256: str
    footprint: tuple[CellSelector, ...] | None = None
    attribution: str = ATTRIBUTION_CERTAIN

    @property
    def is_subject(self) -> bool:
        return self.role == ROLE_SUBJECT

    def applies_to(self, rule: Rule, module: str) -> bool:
        """Whether ``rule``, checked for ``module``, is the rule this entry pinned."""
        return (
            rule.rule_id == self.rule_id
            and module.upper() == self.module.upper()
            and rule.fingerprint(module) == self.rule_sha256
        )

    def inside(self, addresses: Iterable[CellAddress]) -> bool:
        """Whether an evaluation that read ``addresses`` is where the issue applies."""
        if self.footprint is None:
            return True
        return any(
            selector.matches(address) for address in addresses for selector in self.footprint
        )

    def where(self) -> str:
        """Where the issue applies on the rule, in words."""
        if self.footprint is None:
            return "every evaluation"
        return "; ".join(selector.describe() for selector in self.footprint)

    def record(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "rule_id": self.rule_id,
            "role": self.role,
            "severity": self.severity,
            "rule_sha256": self.rule_sha256,
            "footprint": (
                None
                if self.footprint is None
                else [selector.record() for selector in self.footprint]
            ),
            "attribution": self.attribution,
        }


@dataclass(frozen=True)
class Authority:
    """One passage of a published document an issue rests on, quoted verbatim.

    Attributes:
        document: The key of the document in the register's ``documents``.
        quote: The words, exactly as the document has them.
        pdf_page: The 1-based page of the PDF the quote starts on; ``None``
            for a document that is not a PDF.
        pdf_page_end: The page it ends on, where it runs over a page break.
        locator: Where in the document, as a reader finds it (a template and
            column, an article and paragraph).
    """

    document: str
    quote: str
    pdf_page: int | None = None
    pdf_page_end: int | None = None
    locator: str = ""

    def record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "document": self.document,
            "pdf_page": self.pdf_page,
            "locator": self.locator,
            "quote": self.quote,
        }
        if self.pdf_page_end is not None:
            record["pdf_page_end"] = self.pdf_page_end
        return record


@dataclass(frozen=True)
class IssueExample:
    """A minimal return that follows the instructions and shows the issue.

    Attributes:
        description: What the return reports, and why.
        rules: A pattern over rule codes: the rules the example is measured on.
        facts: One row per fact: ``table, sheet, open_key, row, column, value,
            text_value, decimals`` — the canonical return's columns.
    """

    description: str
    rules: str
    facts: tuple[tuple[Any, ...], ...]

    def record(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "rules": self.rules,
            "facts": [list(fact) for fact in self.facts],
        }


@dataclass(frozen=True)
class Raised:
    """When and how an issue was raised with the Bank."""

    date: date
    channel: str

    def record(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "channel": self.channel}


@dataclass(frozen=True)
class PublisherLogEntry:
    """An entry in the Bank's known-issues log that bears on an issue.

    Attributes:
        entry: Its number in the log.
        published: The publication date the log gives it.
        relation: ``acknowledges`` (the Bank records this issue) or
            ``related`` (it records something else about the same rules).
        statement: What the Bank says, verbatim.
    """

    entry: int
    published: date
    relation: str
    statement: str

    def record(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "published": self.published.isoformat(),
            "relation": self.relation,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class Document:
    """A published document an issue quotes."""

    key: str
    title: str
    file: str | None = None
    url: str | None = None

    def record(self) -> dict[str, Any]:
        return {"title": self.title, "file": self.file, "url": self.url}


@dataclass(frozen=True)
class CheckedAgainst:
    """A publication of the Bank's every issue of a register was checked against.

    An issue with no ``publisher_log`` entry is not in it, as at ``as_at``.
    """

    document: str
    as_at: date

    def record(self) -> dict[str, Any]:
        return {"document": self.document, "as_at": self.as_at.isoformat()}


@dataclass(frozen=True)
class PublisherIssue:
    """One known issue with the published rules, and the evidence for it."""

    id: str
    title: str
    status: str
    effect: str
    causes: tuple[str, ...]
    rules: tuple[IssueRule, ...]
    requirement: str
    why_correct_return_fails: str
    authority: tuple[Authority, ...] = ()
    example: IssueExample | None = None
    alternatives_considered: str = ""
    proposed_fix: str = ""
    eba_precedent: str = ""
    reach: str = ""
    meanwhile: str = ""
    raised: Raised | None = None
    publisher_reference: str | None = None
    publisher_log: tuple[PublisherLogEntry, ...] = ()
    fixed_in: str | None = None
    publisher: str = "Bank of England"

    @property
    def subject_rules(self) -> tuple[IssueRule, ...]:
        """The rules the issue is about."""
        return tuple(item for item in self.rules if item.is_subject)

    @property
    def is_open(self) -> bool:
        """Whether the issue is still open in the release it is recorded for."""
        return self.status in OPEN_STATUSES

    @property
    def labels(self) -> bool:
        """Whether the issue puts a label on a rule's result at all."""
        return self.effect in LABELLING_EFFECTS and self.status != STATUS_WITHDRAWN

    @property
    def status_text(self) -> str:
        """Where the issue stands with the Bank, in the words every surface uses."""
        bank = f"the {self.publisher}"
        if self.status == STATUS_RAISED and self.raised is not None:
            return f"raised with {bank} on {long_date(self.raised.date)}"
        if self.status == STATUS_ACKNOWLEDGED:
            reference = f" ({self.publisher_reference})" if self.publisher_reference else ""
            return f"acknowledged by {bank}{reference}"
        if self.status == STATUS_FIXED:
            return (
                f"fixed by {bank} in taxonomy {self.fixed_in}; this release still contains "
                "the published rule"
            )
        if self.status == STATUS_WITHDRAWN:
            return "withdrawn: no longer considered an issue"
        return f"identified by rwa-filer, not yet raised with {bank}"

    def rule(self, module: str, rule_id: str) -> IssueRule | None:
        """The entry for ``rule_id`` of ``module``, whatever its role, or ``None``."""
        wanted = module.upper()
        return next(
            (
                item
                for item in self.rules
                if item.rule_id == rule_id and item.module.upper() == wanted
            ),
            None,
        )

    def record(self) -> dict[str, Any]:
        """The issue as the register file holds it."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "raised": self.raised.record() if self.raised is not None else None,
            "publisher_reference": self.publisher_reference,
            "publisher_log": [entry.record() for entry in self.publisher_log],
            "fixed_in": self.fixed_in,
            "effect": self.effect,
            "causes": list(self.causes),
            "rules": [item.record() for item in self.rules],
            "requirement": self.requirement,
            "authority": [item.record() for item in self.authority],
            "why_correct_return_fails": self.why_correct_return_fails,
            "example": self.example.record() if self.example is not None else None,
            "alternatives_considered": self.alternatives_considered,
            "proposed_fix": self.proposed_fix,
            "eba_precedent": self.eba_precedent,
            "reach": self.reach,
            "meanwhile": self.meanwhile,
        }


@dataclass(frozen=True)
class IssueRegister:
    """The publisher issues recorded for one taxonomy release.

    Attributes:
        release: The taxonomy release, e.g. ``"4.1.1"``.
        issues: Every issue, in the file's order.
        documents: The documents the issues quote, by key.
        checked_against: The Bank's publications every issue was checked against.
        publisher: Who publishes the rules.
        file: The packaged file it was loaded from; ``None`` for one built in
            memory or for an empty register.
        content_sha256: SHA-256 of the file's content in canonical JSON.
    """

    release: str
    issues: tuple[PublisherIssue, ...] = ()
    documents: Mapping[str, Document] = field(default_factory=dict)
    checked_against: tuple[CheckedAgainst, ...] = ()
    publisher: str = "Bank of England"
    file: str | None = None
    content_sha256: str = ""

    @classmethod
    def empty(cls, release: str = "") -> IssueRegister:
        """A register with no issue — for a release that ships none."""
        return cls(release=release)

    def issue(self, issue_id: str) -> PublisherIssue | None:
        """The issue with this id, or ``None``."""
        return next((issue for issue in self.issues if issue.id == issue_id), None)

    def for_rule(self, module: str, rule_id: str) -> tuple[PublisherIssue, ...]:
        """Every issue that names ``rule_id`` of ``module`` as a rule it is about."""
        return tuple(
            issue
            for issue in self.issues
            if (entry := issue.rule(module, rule_id)) is not None and entry.is_subject
        )

    def to_payload(self) -> dict[str, Any]:
        """The register as its packaged file holds it."""
        return {
            "format": ISSUES_FORMAT,
            "release": self.release,
            "publisher": self.publisher,
            "documents": {key: item.record() for key, item in self.documents.items()},
            "checked_against": [item.record() for item in self.checked_against],
            "issues": [issue.record() for issue in self.issues],
        }


def available_issue_registers() -> tuple[str, ...]:
    """The releases an issue register is packaged for, sorted by file name."""
    root = _root()
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name.removesuffix(ISSUES_SUFFIX)
            for entry in root.iterdir()
            if entry.name.endswith(ISSUES_SUFFIX)
        )
    )


@cache
def load_issues(release: str) -> IssueRegister:
    """The issue register packaged for ``release``. Cached: package data never changes.

    Raises:
        IssueRegisterNotFoundError: none is packaged for the release.
        ValueError: the file is not a register this version reads.
    """
    resource = _root().joinpath(issue_register_file(release))
    if not resource.is_file():
        raise IssueRegisterNotFoundError(f"No issue register is packaged for taxonomy {release}")
    register = issues_from(json.loads(resource.read_text(encoding="utf-8")), file=resource.name)
    if register.release != release:
        raise ValueError(
            f"{resource.name} holds the issue register of taxonomy {register.release}, "
            f"not {release}"
        )
    return register


def issues_from(payload: Mapping[str, Any], *, file: str | None = None) -> IssueRegister:
    """Build an ``IssueRegister`` from a register file's content.

    Raises:
        ValueError: the format is not one this version reads; an id, status,
            effect, cause, role or attribution is not one it knows; two issues
            share an id; one issue names a rule twice; a selector has no table.
    """
    if payload.get("format") != ISSUES_FORMAT:
        raise ValueError(
            f"Issue register format {payload.get('format')!r} is not supported "
            f"(expected {ISSUES_FORMAT})"
        )
    publisher = str(payload.get("publisher") or "Bank of England")
    issues = tuple(_issue(item, publisher) for item in payload.get("issues", ()))
    seen: set[str] = set()
    for issue in issues:
        if issue.id in seen:
            raise ValueError(f"issue id {issue.id} is used twice")
        seen.add(issue.id)
    documents = {
        str(key): Document(
            key=str(key),
            title=str(item["title"]),
            file=item.get("file"),
            url=item.get("url"),
        )
        for key, item in payload.get("documents", {}).items()
    }
    return IssueRegister(
        release=str(payload["release"]),
        issues=issues,
        documents=documents,
        checked_against=tuple(
            CheckedAgainst(
                document=str(item["document"]), as_at=date.fromisoformat(str(item["as_at"]))
            )
            for item in payload.get("checked_against", ())
        ),
        publisher=publisher,
        file=file,
        content_sha256=canonical_sha256(payload),
    )


def issue_register_file(release: str) -> str:
    """The packaged file name of ``release``'s register, e.g. ``4.1.1.json``."""
    return f"{release}{ISSUES_SUFFIX}"


def issues_for(release: str, module: str, rule_id: str) -> tuple[PublisherIssue, ...]:
    """The issues packaged for ``release`` that name ``rule_id`` of ``module``.

    The one call a caller holding only a rule code needs — rwa-calc's
    supervisory register uses it to tie a tolerated break to its evidence.
    Empty for a release that packages no register.
    """
    if release not in available_issue_registers():
        return ()
    return load_issues(release).for_rule(module, rule_id)


def long_date(day: date) -> str:
    """``2 October 2026`` — as ``rwa_filer.release.long_date`` writes a date."""
    return f"{day.day} {day:%B} {day.year}"


# =============================================================================
# Private helpers
# =============================================================================


def _root() -> Any:  # noqa: ANN401 - an importlib.resources Traversable
    return resources.files(ISSUES_PACKAGE).joinpath(*ISSUES_DIRECTORY)


def _listed(code: str | None, wanted: tuple[str, ...], excluded: tuple[str, ...]) -> bool:
    if wanted and code not in wanted:
        return False
    return code not in excluded


def _one_of(value: object, allowed: tuple[str, ...], what: str, issue_id: str) -> str:
    text = str(value)
    if text not in allowed:
        raise ValueError(f"{issue_id}: {what} {text!r} is not one of {', '.join(allowed)}")
    return text


def _issue(item: Mapping[str, Any], publisher: str) -> PublisherIssue:
    issue_id = str(item["id"])
    if not ISSUE_ID_PATTERN.match(issue_id):
        raise ValueError(f"issue id {issue_id!r} is not of the form PI-nn or PI-nnx")
    rules = tuple(_rule(entry, issue_id) for entry in item.get("rules", ()))
    named = [(entry.module.upper(), entry.rule_id) for entry in rules]
    twice = sorted({rule_id for module, rule_id in named if named.count((module, rule_id)) > 1})
    if twice:
        raise ValueError(f"{issue_id} names {', '.join(twice)} more than once")
    raised = item.get("raised")
    example = item.get("example")
    return PublisherIssue(
        id=issue_id,
        title=str(item["title"]),
        status=_one_of(item["status"], STATUSES, "status", issue_id),
        effect=_one_of(item["effect"], EFFECTS, "effect", issue_id),
        causes=tuple(_one_of(cause, CAUSES, "cause", issue_id) for cause in item["causes"]),
        rules=rules,
        requirement=str(item.get("requirement", "")),
        why_correct_return_fails=str(item.get("why_correct_return_fails", "")),
        authority=tuple(
            Authority(
                document=str(entry["document"]),
                quote=str(entry["quote"]),
                pdf_page=entry.get("pdf_page"),
                pdf_page_end=entry.get("pdf_page_end"),
                locator=str(entry.get("locator", "")),
            )
            for entry in item.get("authority", ())
        ),
        example=(
            IssueExample(
                description=str(example.get("description", "")),
                rules=str(example.get("rules", "")),
                facts=tuple(tuple(fact) for fact in example.get("facts", ())),
            )
            if example
            else None
        ),
        alternatives_considered=str(item.get("alternatives_considered", "")),
        proposed_fix=str(item.get("proposed_fix", "")),
        eba_precedent=str(item.get("eba_precedent", "")),
        reach=str(item.get("reach", "")),
        meanwhile=str(item.get("meanwhile", "")),
        raised=(
            Raised(date=date.fromisoformat(str(raised["date"])), channel=str(raised["channel"]))
            if raised
            else None
        ),
        publisher_reference=item.get("publisher_reference"),
        publisher_log=tuple(
            PublisherLogEntry(
                entry=int(entry["entry"]),
                published=date.fromisoformat(str(entry["published"])),
                relation=_one_of(entry["relation"], LOG_RELATIONS, "log relation", issue_id),
                statement=str(entry["statement"]),
            )
            for entry in item.get("publisher_log", ())
        ),
        fixed_in=item.get("fixed_in"),
        publisher=publisher,
    )


def _rule(entry: Mapping[str, Any], issue_id: str) -> IssueRule:
    footprint = entry.get("footprint")
    return IssueRule(
        module=str(entry["module"]),
        rule_id=str(entry["rule_id"]),
        role=_one_of(entry["role"], ROLES, "role", issue_id),
        severity=str(entry["severity"]),
        rule_sha256=str(entry["rule_sha256"]),
        footprint=(
            None
            if footprint is None
            else tuple(_selector(selector, issue_id) for selector in footprint)
        ),
        attribution=_one_of(
            entry.get("attribution", ATTRIBUTION_CERTAIN), ATTRIBUTIONS, "attribution", issue_id
        ),
    )


def _selector(entry: Mapping[str, Any], issue_id: str) -> CellSelector:
    if not entry.get("table"):
        raise ValueError(f"{issue_id}: a footprint selector names no table")
    unknown = set(entry) - {"table", *_SELECTOR_LISTS}
    if unknown:
        raise ValueError(f"{issue_id}: unknown footprint keys {sorted(unknown)}")
    lists = {name: tuple(str(code) for code in entry.get(name, ())) for name in _SELECTOR_LISTS}
    return CellSelector(table=str(entry["table"]), **lists)
