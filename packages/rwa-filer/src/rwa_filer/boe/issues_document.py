"""
The shareable write-up of the known issues with the published rules — one Markdown text.

Pipeline position:
    boe/data/issues/<release>.json  ->  boe.issues.load_issues  ->  render_document
        ->  ``rwa-filer rulebook issues --format markdown``
        ->  the repository's scripts/generate_publisher_issues.py
            ->  docs/rwa-filer/publisher-issues.md (with Arelle's counts: the copy to send)

Key responsibilities:
- Render each release's register as one Markdown document a reader at the Bank
  can follow without this package: what was checked and against what (the
  taxonomy release, the rule book, the Bank's known-issues log and deny list,
  the reference processor), a summary, then the issues grouped by kind —
  defects, clarification questions, and issues the Bank has already
  acknowledged — and the register's appendices.
- For each issue: the rules and their severity (each rule's expression and
  scope read from the SAME release's rule book, never copied into the
  register), what the rule requires, what the instructions say (quoted, with
  the PDF page), why a correct return fails (or, for a clarification, the
  question), a worked example with its figures and Arelle's result on it, the
  other ways of reporting considered, the proposed change, EBA precedent, who
  is affected, and what a firm can do meanwhile.
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
from datetime import date
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_NO_RULE_EFFECT,
    EFFECT_PASSES_WRONG_RETURNS,
    KIND_ACKNOWLEDGED,
    KIND_CLARIFICATION,
    KIND_DEFECT,
    KINDS,
    LOG_ACKNOWLEDGES,
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
    from rwa_filer.boe.issues import Appendix, IssueRegister, IssueRule, PublisherIssue

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
#: Each cause, in words.
CAUSE_TEXT: Final = {
    "contradicts_instructions": "contradicts the reporting instructions",
    "contradicts_ps126_rules": "contradicts the PRA Rulebook as amended by PS1/26",
    "contradicts_other_rule": "conflicts with another published rule",
    "contradicts_template": "conflicts with the template",
    "plausibility_not_identity": "states as a rule what holds only as a tendency",
    "text_differs_from_formula": "the published text and the rule as run differ",
    "instructions_gap": "the instructions leave a gap",
    "taxonomy_data_type": "a data type in the taxonomy contradicts the instructions",
    "taxonomy_cells_missing": "the taxonomy lacks cells the instructions ask for",
    "too_permissive": "the rule allows more values than the requirement it checks",
    "rounding_allowance": "the rounding allowance the rule gives",
    "restates_deactivated_eba_rule": "it restates an EBA rule the EBA has deactivated",
}
#: Each role, in the rules table.
ROLE_TEXT: Final = {
    ROLE_SUBJECT: "the rule at issue",
    ROLE_CONTRADICTS: "cannot hold together with it",
    ROLE_CONTROL: "holds on the example (control)",
    ROLE_RELATED: "related",
}
#: Each kind's group: its heading and what it holds.
KIND_GROUP: Final = {
    KIND_DEFECT: (
        "Defects",
        "A return that follows the reporting instructions and the PRA Rulebook fails the rule, "
        "the rule accepts figures the rules do not permit, or it never runs; or, where no rule "
        "result shows it, the published taxonomy or rule workbook is wrong. Each issue proposes "
        "a change.",
    ),
    KIND_CLARIFICATION: (
        "Clarification questions",
        "The rule, or the text it rests on, can be read in more than one way, and a return "
        "that complies on one reading fails it. A compliant return that passes does exist, so "
        "each of these is put as a question.",
    ),
    KIND_ACKNOWLEDGED: (
        "Already acknowledged by the Bank",
        "The Bank's own known-issues log already records these. They are listed for "
        "completeness, with what the log says and any point it does not cover.",
    ),
}
#: The heading of the argument, by effect (a clarification's is "The question").
_WHY: Final = {
    EFFECT_FAILS_CORRECT_RETURNS: "Why a correct return fails",
    EFFECT_PASSES_WRONG_RETURNS: "Why a wrong return passes",
    EFFECT_NEVER_RUNS: "Why the rule never runs",
    EFFECT_NO_RULE_EFFECT: "Why it matters",
}
#: A stated example outcome, in words.
_OUTCOME_TEXT: Final = {
    "unsatisfied": "fails",
    "satisfied": "holds",
    "not_evaluated": "not evaluated",
}

_TITLE: Final = "Known issues with the Bank of England's published validation rules"
_INTRO: Final = """\
The validation rules the Bank of England publishes with its banking taxonomy are
what its gateway runs on a submitted return. This document sets out the rules
that, on the evidence given, do not match the reporting instructions or the PRA
Rulebook: a return that follows the instructions fails them, they accept figures
the rules do not permit, they never run, or they can be read in more than one
way. Each issue quotes the rule, the instructions and the rules with their page,
and gives a worked example - a small return, with its figures, that the
reference XBRL processor Arelle has evaluated against the Bank's own taxonomy
package.

The issues are grouped as defects, clarification questions, and issues the
Bank's known-issues log already records."""
_COUNTS: Final = """\
Arelle's result on an example is given as the number of evaluations of each rule
that are satisfied and unsatisfied: a rule is evaluated once for each set of
cells it applies to, so "1 unsatisfied" is one failing check. In the text the
same pair is written [satisfied, unsatisfied]: [0,2] is two failing checks and
none passing. "What the example shows" is the outcome the issue states, which
Arelle's counts confirm.

Each example is the smallest return that shows its issue, and Arelle evaluated it
on the rules listed with it, not on the whole rule book: an example need not carry
every template that other rules tie it to, and its description says where it is a
complete return."""


# =============================================================================
# Public entry points
# =============================================================================


def render_document(
    registers: Iterable[IssueRegister],
    *,
    arelle: ArelleCounts | None = None,
    processor: str = "",
    rulebook_for: Callable[[str, str], RuleBook | None] = release_rulebook,
    deny_list_for: Callable[[str], DenyList] = release_deny_list,
    preamble: str = "",
) -> str:
    """Every register as one Markdown document, one part per release, in the order given.

    Args:
        registers: The registers to render.
        arelle: Arelle's counts on each issue's example, by release and issue;
            leave out to render without them.
        processor: The reference processor the counts were measured with, e.g.
            ``arelle-release 2.47.5``; said in the document's header.
        rulebook_for: The rule book of a release and module (the expression and
            scope of each rule come from it).
        deny_list_for: The Bank's deny list of a release.
        preamble: Text placed before the title (a generated-file notice).
    """
    lines: list[str] = [preamble] if preamble else []
    for register in registers:
        lines += _release_part(
            register,
            (arelle or {}).get(register.release, {}),
            processor,
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
    """One line per issue: id, kind, status, the rules it is about, and the title."""
    lines = [
        f"Taxonomy {register.release}: {len(register.issues)} known issue(s) with the published "
        f"rules ({register.file or 'built in memory'})"
    ]
    for issue in register.issues:
        rules = ", ".join(entry.rule_id for entry in issue.subject_rules) or "-"
        lines.append(f"  {issue.id:<7}{issue.kind:<15}{issue.status:<13}{rules}")
        lines.append(f"         {issue.title}")
    return lines


# =============================================================================
# Private helpers
# =============================================================================


def _release_part(
    register: IssueRegister,
    arelle: Mapping[str, Mapping[str, Sequence[int]]],
    processor: str,
    rulebook_for: Callable[[str, str], RuleBook | None],
    deny_list: DenyList,
) -> list[str]:
    lines = [f"# {_TITLE} (taxonomy {register.release})", "", _INTRO, ""]
    lines += _about(register, processor, rulebook_for, deny_list)
    lines += _summary(register)
    for kind in KINDS:
        issues = [issue for issue in register.issues if issue.kind == kind]
        if not issues:
            continue
        heading, text = KIND_GROUP[kind]
        lines += [f"## {heading}", "", text, ""]
        for issue in issues:
            lines += _issue_section(
                issue, register, arelle.get(issue.id, {}), rulebook_for, deny_list
            )
    for appendix in register.appendices:
        lines += _appendix(appendix)
    return lines


def _about(
    register: IssueRegister,
    processor: str,
    rulebook_for: Callable[[str, str], RuleBook | None],
    deny_list: DenyList,
) -> list[str]:
    modules = sorted({entry.module for issue in register.issues for entry in issue.rules})
    lines = [
        "## What was checked",
        "",
        f"- **Taxonomy:** {register.publisher} Banking Taxonomy v{register.release}, "
        f"module{'s' if len(modules) != 1 else ''} {', '.join(modules) or '-'}.",
    ]
    for module in modules:
        book = rulebook_for(register.release, module)
        if book is None:
            continue
        workbook = book.source.get("workbook")
        folder = (book.source.get("formulas") or {}).get("folder")
        source = f'the Bank\'s workbook "{workbook}"' if workbook else "the Bank's rules"
        formulas = (
            f", with each rule as its XBRL formula in the taxonomy package ({folder})"
            if folder
            else ""
        )
        lines.append(
            f"- **Rule book ({module}):** {source}{formulas}; "
            f"{len(book.enforced(module)):,} rules run on a {module} return."
        )
    checked = [_checked(register, item.document, item.as_at) for item in register.checked_against]
    if deny_list.source:
        published = deny_list.source.get("published")
        checked.append(
            f"the Bank's validations deny list ({deny_list.source.get('file')}, sheet "
            f'"{deny_list.source.get("sheet")}"'
            + (f", published {_iso_date(str(published))}" if published else "")
            + ")"
        )
    if checked:
        lines.append(
            "- **The Bank's own documents checked:** "
            + "; ".join(checked)
            + ". Each issue says where these mention it; an issue that cites neither is not in "
            "them."
        )
    if processor:
        lines.append(
            f"- **Reference processor:** every example was evaluated with Arelle "
            f"{processor.removeprefix('arelle-release ')} against the Bank's "
            f"v{register.release} taxonomy package; the counts shown are Arelle's."
        )
    lines += ["", _COUNTS, ""]
    return lines


def _checked(register: IssueRegister, document: str, as_at: date) -> str:
    known = register.documents.get(document)
    title = known.title if known is not None else document
    when = long_date(as_at)
    return title if when in title else f"{title} (as at {when})"


def _summary(register: IssueRegister) -> list[str]:
    lines = ["## Summary", ""]
    for kind in KINDS:
        issues = [issue for issue in register.issues if issue.kind == kind]
        if not issues:
            continue
        heading, _text = KIND_GROUP[kind]
        lines += [
            f"**{heading}** ({len(issues)})",
            "",
            "| Issue | Rules | Severity | Title |",
            "|---|---|---|---|",
        ]
        for issue in issues:
            rules = ", ".join(entry.rule_id for entry in issue.subject_rules) or "-"
            lines.append(
                f"| [{issue.id}](#{issue.id.lower()}) | {rules} | "
                f"{_severity_words(issue) or '-'} | {_cell(issue.title)} |"
            )
        lines.append("")
    for appendix in register.appendices:
        lines.append(
            f"Appendix {appendix.id}: [{appendix.title}](#appendix-{appendix.id.lower()})."
        )
    if register.appendices:
        lines.append("")
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
        f"**Status:** {issue.status_text}.",
        "",
    ]
    severities = _severities(issue)
    if severities:
        lines += [f"**Severity:** {severities}.", ""]
    causes = "; ".join(CAUSE_TEXT.get(cause, cause) for cause in issue.causes)
    lines += [f"**Effect:** {EFFECT_TEXT[issue.effect]}. **Cause:** {causes}.", ""]
    for entry in issue.publisher_log:
        relation = "records this issue" if entry.relation == LOG_ACKNOWLEDGES else "related"
        lines += [
            f"**The Bank's known-issues log, entry {entry.entry}** (published "
            f"{long_date(entry.published)}; {relation}):",
            "",
            *_quoted(entry.statement),
            "",
        ]
    lines += _rules_table(issue, register, rulebook_for, deny_list)
    lines += _text("What the rule requires", issue.requirement)
    lines += _authority(issue, register)
    why = "The question" if issue.kind == KIND_CLARIFICATION else _WHY[issue.effect]
    lines += _text(why, issue.why_correct_return_fails)
    lines += _example(issue, arelle)
    lines += _text("Other ways of reporting considered", issue.alternatives_considered)
    lines += _text("Proposed change", issue.proposed_fix)
    lines += _text("EBA precedent", issue.eba_precedent)
    lines += _text("Who is affected", issue.reach)
    lines += _text("What a firm can do meanwhile", issue.meanwhile)
    return lines


def _severities(issue: PublisherIssue) -> str:
    """``ERROR (boe_b1016, boe_b1031); WARNING (boe_b0491)`` over the subject rules."""
    grouped: dict[str, list[str]] = {}
    for entry in issue.subject_rules:
        grouped.setdefault(entry.severity, []).append(entry.rule_id)
    return "; ".join(
        f"{severity} ({', '.join(rules)})" for severity, rules in sorted(grouped.items())
    )


def _severity_words(issue: PublisherIssue) -> str:
    """The subject rules' severities alone, e.g. ``ERROR, WARNING``."""
    return ", ".join(sorted({entry.severity for entry in issue.subject_rules}))


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
            " (a break there may also be the return's own)"
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
    label = f" (label: {_label(rule.label)})" if rule.label else ""
    lines = [
        f"{entry.rule_id}, as published in taxonomy {release}{label}:",
        "",
        "```text",
        rule.expression,
    ]
    if rule.scope:
        lines.append(rule.scope)
    lines += ["```", ""]
    return lines


def _label(text: str) -> str:
    """A rule's published label, quoted; as code where it holds what Markdown reads as a link.

    Some labels are expressions themselves (``[boe_b0903];[matches(...)]``):
    left as prose, ``[...](...)`` in them would be read as a link.
    """
    if "[" not in text:
        return f'"{text}"'
    fence = "``" if "`" in text else "`"
    return f"{fence}{text}{fence}"


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
        lines += [*_quoted(item.quote), ">", f"> - {title}{where}{page}", ""]
    return lines


def _example(issue: PublisherIssue, arelle: Mapping[str, Sequence[int]]) -> list[str]:
    example = issue.example
    if example is None:
        return []
    lines = ["#### Worked example", "", example.description.strip(), ""]
    if arelle:
        lines += [
            "Arelle's result on it:",
            "",
            "| Rule | Satisfied | Unsatisfied | What the example shows |",
            "|---|---|---|---|",
            *(
                f"| {rule} | {counts[0]} | {counts[1]} | "
                f"{_OUTCOME_TEXT.get(example.outcome.get(rule, ''), '-')} |"
                for rule, counts in sorted(arelle.items())
            ),
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


def _appendix(appendix: Appendix) -> list[str]:
    lines = [
        f'<a id="appendix-{appendix.id.lower()}"></a>',
        "",
        f"## Appendix {appendix.id} - {appendix.title}",
        "",
    ]
    if appendix.text.strip():
        lines += [appendix.text.strip(), ""]
    if appendix.columns:
        lines += [
            "| " + " | ".join(appendix.columns) + " |",
            "|" + "---|" * len(appendix.columns),
            *("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in appendix.rows),
            "",
        ]
    return lines


def _text(heading: str, body: str) -> list[str]:
    if not body.strip():
        return []
    return [f"#### {heading}", "", body.strip(), ""]


def _quoted(text: str) -> list[str]:
    """A block quote, one ``>`` line per line of ``text``."""
    return [f"> {line}".rstrip() for line in text.strip().splitlines()]


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _number(value: float | int, decimals: int | None) -> str:
    if decimals is not None and decimals <= 0 and float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _iso_date(text: str) -> str:
    """``2026-11-16`` as ``16 November 2026``; anything else as given."""
    try:
        return long_date(date.fromisoformat(text))
    except ValueError:
        return text
