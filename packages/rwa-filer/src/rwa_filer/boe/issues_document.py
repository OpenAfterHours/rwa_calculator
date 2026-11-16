"""
The shareable write-up of the known issues with the published rules — one Markdown text.

Pipeline position:
    boe/data/issues/<release>.json  ->  boe.issues.load_issues  ->  render_document
        ->  ``rwa-filer rulebook issues --format markdown`` (to send to the Bank)
        ->  the repository's scripts/generate_publisher_issues.py
            ->  docs/rwa-filer/publisher-issues.md (with Arelle's counts)

Key responsibilities:
- Render each release's register as one Markdown document a reader at the Bank
  can follow without this package: a summary table, then one section per issue
  with where it stands, the rules it names (each rule's expression and scope
  read from the SAME release's rule book, never copied into the register),
  what the rule requires, what the instructions say (quoted, with the PDF
  page), why a correct return fails, the minimal correct return as a table of
  facts (and Arelle's counts on it, where given), the alternatives considered,
  the proposed fix, EBA precedent, reach, and what a firm can do meanwhile.
- Say, for every rule an issue names, what the Bank's validations deny list
  does to it today: a rule the gateway no longer runs is said to be so.
- Render one issue in full, and a one-line-per-issue listing, for the command
  line.
- Write nothing: the caller decides where the text goes. The same input gives
  the same text, so a generated copy can be checked for staleness.

References:
- rwa_filer.boe.issues — the register
- rwa_filer.boe.deny — the Bank's validations deny list
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_NO_RULE_EFFECT,
    EFFECT_PASSES_WRONG_RETURNS,
    ROLE_CONTRADICTS,
    ROLE_CONTROL,
    ROLE_RELATED,
    ROLE_SUBJECT,
    long_date,
)
from rwa_filer.release import release_deny_list, release_rulebook

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.boe.deny import DenyList
    from rwa_filer.boe.issues import IssueRegister, IssueRule, PublisherIssue

logger = logging.getLogger(__name__)

#: Arelle's counts per release, issue and rule: ``[satisfied, unsatisfied]``.
type ArelleCounts = Mapping[str, Mapping[str, Mapping[str, Sequence[int]]]]

#: What each effect means, as a reader at the Bank reads it.
EFFECT_TEXT: Final = {
    EFFECT_FAILS_CORRECT_RETURNS: "a return that follows the reporting instructions fails it",
    EFFECT_PASSES_WRONG_RETURNS: "it accepts figures the rules do not permit",
    EFFECT_NEVER_RUNS: "as published it never runs, so it checks nothing",
    EFFECT_NO_RULE_EFFECT: "no rule result shows it; the instructions or the taxonomy do",
}
#: Each role, in the rules table.
ROLE_TEXT: Final = {
    ROLE_SUBJECT: "the rule at issue",
    ROLE_CONTRADICTS: "cannot hold together with it",
    ROLE_CONTROL: "holds on the example (control)",
    ROLE_RELATED: "related",
}

_TITLE: Final = "Known issues with the published validation rules"
_INTRO: Final = """\
The validation rules the Bank of England publishes with its banking taxonomy are
what its gateway runs on a submitted return. This document lists the rules that
are, as far as the evidence below shows, wrong: a return that follows the
reporting instructions fails them, they pass figures the rules do not permit,
or they never run. Each issue gives the rule, the instructions and rules
quoted with their page, why a correct return fails, and the smallest correct
return that shows it - a return the reference XBRL processor, Arelle, has
evaluated against the Bank's own taxonomy package, with the counts below.

Where an issue stands with the Bank:

- **draft** - identified by rwa-filer, not yet raised with the Bank of England;
- **raised** - raised with the Bank, on the date given;
- **acknowledged** - in the Bank's own known-issues log;
- **fixed** - fixed by the Bank in a later taxonomy release.

rwa-filer labels a validation result an issue explains - in its text and JSON
reports, the evidence export, the dashboard and the filing manifest - and never
changes the verdict: a rule that breaks still breaks, with the same severity."""


# =============================================================================
# Public entry points
# =============================================================================


def render_document(
    registers: Iterable[IssueRegister],
    *,
    arelle: ArelleCounts | None = None,
    rulebook_for: Callable[[str, str], RuleBook | None] = release_rulebook,
    deny_list_for: Callable[[str], DenyList] = release_deny_list,
    preamble: str = "",
) -> str:
    """Every register as one Markdown document, newest release first as given.

    Args:
        registers: The registers to render, one section per release.
        arelle: Arelle's counts on each issue's example, by release and issue;
            leave out to render without them.
        rulebook_for: The rule book of a release and module (the expression and
            scope of each rule come from it).
        deny_list_for: The Bank's deny list of a release.
        preamble: Text placed before the title (a generated-file notice).
    """
    lines: list[str] = [preamble] if preamble else []
    lines += [f"# {_TITLE}", "", _INTRO, ""]
    for register in registers:
        lines += _release_section(
            register,
            (arelle or {}).get(register.release, {}),
            rulebook_for,
            deny_list_for(register.release),
        )
    return "\n".join(lines).rstrip() + "\n"


def render_issue(
    issue: PublisherIssue,
    register: IssueRegister,
    *,
    arelle: Mapping[str, Sequence[int]] | None = None,
    rulebook_for: Callable[[str, str], RuleBook | None] = release_rulebook,
    deny_list_for: Callable[[str], DenyList] = release_deny_list,
) -> str:
    """One issue in full, as its section of the document renders it."""
    lines = _issue_section(
        issue, register, arelle or {}, rulebook_for, deny_list_for(register.release)
    )
    return "\n".join(lines).rstrip() + "\n"


def render_listing(register: IssueRegister) -> list[str]:
    """One line per issue: id, status, effect, the rules it is about, and the title."""
    lines = [
        f"Taxonomy {register.release}: {len(register.issues)} known issue(s) with the published "
        f"rules ({register.file or 'built in memory'})"
    ]
    for issue in register.issues:
        rules = ", ".join(entry.rule_id for entry in issue.subject_rules) or "-"
        lines.append(f"  {issue.id:<7}{issue.status:<13}{issue.effect:<23}{rules}")
        lines.append(f"         {issue.title}")
    return lines


# =============================================================================
# Private helpers
# =============================================================================


def _release_section(
    register: IssueRegister,
    arelle: Mapping[str, Mapping[str, Sequence[int]]],
    rulebook_for: Callable[[str, str], RuleBook | None],
    deny_list: DenyList,
) -> list[str]:
    checked = "; ".join(
        f"{register.documents[item.document].title if item.document in register.documents else item.document}"
        f" (as at {long_date(item.as_at)})"
        for item in register.checked_against
    )
    lines = [
        f"## Taxonomy {register.release} ({register.publisher} banking taxonomy)",
        "",
        f"{len(register.issues)} issue(s). Every issue was checked against: {checked or 'nothing'}"
        "; an issue the Bank's publications do not mention says so by having no entry from them.",
        "",
        "| Issue | Status | Effect | Rules at issue | Title |",
        "|---|---|---|---|---|",
    ]
    for issue in register.issues:
        rules = ", ".join(entry.rule_id for entry in issue.subject_rules) or "-"
        lines.append(
            f"| [{issue.id}](#{issue.id.lower()}) | {issue.status} | "
            f"{EFFECT_TEXT[issue.effect]} | {rules} | {_cell(issue.title)} |"
        )
    lines.append("")
    for issue in register.issues:
        lines += _issue_section(issue, register, arelle.get(issue.id, {}), rulebook_for, deny_list)
    return lines


def _issue_section(
    issue: PublisherIssue,
    register: IssueRegister,
    arelle: Mapping[str, Sequence[int]],
    rulebook_for: Callable[[str, str], RuleBook | None],
    deny_list: DenyList,
) -> list[str]:
    lines = [
        f'<a id="{issue.id.lower()}"></a>',
        "",
        f"### {issue.id} - {issue.title}",
        "",
        f"**Status:** {issue.status} - {issue.status_text}.",
        "",
        f"**Effect:** {EFFECT_TEXT[issue.effect]}. **Why:** {', '.join(issue.causes)}.",
        "",
    ]
    for entry in issue.publisher_log:
        lines += [
            f"**The Bank's known-issues log, #{entry.entry}** ({long_date(entry.published)}, "
            f"{'acknowledges this issue' if entry.relation == 'acknowledges' else 'related'}):",
            "",
            f"> {entry.statement}",
            "",
        ]
    lines += _rules_table(issue, register, rulebook_for, deny_list)
    lines += _text("What the rule requires", issue.requirement)
    lines += _authority(issue, register)
    lines += _text("Why a correct return fails", issue.why_correct_return_fails)
    lines += _example(issue, arelle)
    lines += _text("Alternatives considered", issue.alternatives_considered)
    lines += _text("Proposed fix", issue.proposed_fix)
    lines += _text("EBA precedent", issue.eba_precedent)
    lines += _text("Reach", issue.reach)
    lines += _text("Meanwhile", issue.meanwhile)
    return lines


def _rules_table(
    issue: PublisherIssue,
    register: IssueRegister,
    rulebook_for: Callable[[str, str], RuleBook | None],
    deny_list: DenyList,
) -> list[str]:
    lines = [
        "#### The rules",
        "",
        "| Rule | Module | Severity | Part in the issue | Where the issue applies | At the gateway |",
        "|---|---|---|---|---|---|",
    ]
    for entry in issue.rules:
        denied = deny_list.entry(entry.module, entry.rule_id)
        gateway = denied.describe() if denied is not None else "run as published"
        hedge = (
            " (may be: a break there can also be the return's own)"
            if (entry.is_subject and entry.attribution == "possible")
            else ""
        )
        lines.append(
            f"| {entry.rule_id} | {entry.module} | {entry.severity} | "
            f"{ROLE_TEXT[entry.role]} | {_cell(entry.where()) if entry.is_subject else '-'}"
            f"{hedge} | {_cell(gateway)} |"
        )
    lines.append("")
    for entry in issue.subject_rules:
        lines += _expression(entry, register.release, rulebook_for)
    return lines


def _expression(
    entry: IssueRule, release: str, rulebook_for: Callable[[str, str], RuleBook | None]
) -> list[str]:
    book = rulebook_for(release, entry.module)
    rule = book.rule(entry.rule_id) if book is not None else None
    if rule is None:
        return [f"{entry.rule_id}: not in the {release} rule book for {entry.module}.", ""]
    lines = [
        f"{entry.rule_id}, as published in taxonomy {release}:",
        "",
        "```text",
        rule.expression,
    ]
    if rule.scope:
        lines.append(rule.scope)
    lines += ["```", ""]
    return lines


def _authority(issue: PublisherIssue, register: IssueRegister) -> list[str]:
    if not issue.authority:
        return []
    lines = ["#### What the instructions and rules say", ""]
    for item in issue.authority:
        document = register.documents.get(item.document)
        title = document.title if document is not None else item.document
        if item.pdf_page is None:
            page = ""
        elif item.pdf_page_end is not None:
            page = f", PDF pages {item.pdf_page}-{item.pdf_page_end}"
        else:
            page = f", PDF page {item.pdf_page}"
        where = f", {item.locator}" if item.locator else ""
        lines += [f"> {item.quote}", ">", f"> - {title}{where}{page}", ""]
    return lines


def _example(issue: PublisherIssue, arelle: Mapping[str, Sequence[int]]) -> list[str]:
    example = issue.example
    if example is None:
        return []
    lines = ["#### A minimal correct return", "", example.description, ""]
    if arelle:
        lines += [
            "Arelle's verdict on it (evaluations satisfied / unsatisfied):",
            "",
            "| Rule | Satisfied | Unsatisfied |",
            "|---|---|---|",
            *(f"| {rule} | {counts[0]} | {counts[1]} |" for rule, counts in sorted(arelle.items())),
            "",
        ]
    lines += [
        "<details>",
        f"<summary>The return's {len(example.facts)} facts</summary>",
        "",
        "| Table | Sheet | Key | Row | Column | Value |",
        "|---|---|---|---|---|---|",
    ]
    for table, sheet, key, row, column, value, text, decimals in example.facts:
        shown = text if value is None else _number(value, decimals)
        lines.append(
            f"| {table} | {sheet or ''} | {key or ''} | {row} | {column} | {_cell(str(shown))} |"
        )
    lines += ["", "</details>", ""]
    return lines


def _text(heading: str, body: str) -> list[str]:
    if not body.strip():
        return []
    return [f"#### {heading}", "", body.strip(), ""]


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _number(value: float | int, decimals: int | None) -> str:
    if decimals is not None and decimals <= 0 and float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,}" if isinstance(value, int) else str(value)
