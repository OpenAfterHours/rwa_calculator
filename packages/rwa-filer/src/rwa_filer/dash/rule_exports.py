"""Render a shareable report from the Rules tab's selected evaluations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from html import escape
from io import BytesIO
from typing import TYPE_CHECKING

import xlsxwriter

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from xlsxwriter.worksheet import Worksheet

    from rwa_filer.boe.engine import CellAddress
    from rwa_filer.dash.views import RuleDetail
    from rwa_filer.workflow.attribution import Attribution, TracedBreak


@dataclass(frozen=True)
class FailureReport:
    """A filtered snapshot shared by the preview and both download formats."""

    summary: dict[str, str]
    rules: tuple[RuleDetail, ...]
    dimension: str
    attribution: Attribution | None

    @property
    def occurrences(self) -> int:
        return sum(len(rule.failures) for rule in self.rules)


def matched_traces(
    rules: tuple[RuleDetail, ...], attribution: Attribution | None
) -> dict[tuple[str, int], TracedBreak]:
    """Pair visible occurrences in evaluation order, as Attribution.reviewed does.

    The selected rule card may display just the first few visible occurrences.
    Verify the full count and the individual place before attaching a member's figures.
    """
    found: dict[tuple[str, int], TracedBreak] = {}
    if attribution is None:
        return found
    by_rule: dict[str, list[TracedBreak]] = defaultdict(list)
    for trace in attribution.broken:
        by_rule[trace.rule_id].append(trace)
    for rule in rules:
        traces = by_rule[rule.row.rule_id]
        if len(traces) != rule.row.unsatisfied - rule.row.hidden:
            continue
        for index, failure in enumerate(rule.failures, 1):
            trace = traces[index - 1]
            if failure.place == trace.place_text:
                found[rule.row.rule_id, index] = trace
    return found


def _address(cell: CellAddress) -> str:
    parts = [
        cell.table,
        f"z{cell.sheet}" if cell.sheet else "",
        cell.open_key or "",
        f"r{cell.row} c{cell.column}",
        "" if cell.reported else "(read at default)",
    ]
    return " ".join(part for part in parts if part)


def _notes(rule: RuleDetail) -> str:
    lines = [rule.row.deny, rule.published]
    for item in rule.issues:
        lines.extend(
            (
                item.note.issue_id,
                item.note.title,
                item.note.sentence,
                item.quote,
                item.issue.meanwhile,
            )
        )
    return "\n".join(filter(None, lines))


def _members(
    attribution: Attribution, trace: TracedBreak
) -> Iterable[tuple[str, str, float | None, float | None, float | None]]:
    for member in trace.standings:
        if member.evaluated or attribution.group_code is not None:
            verdict = (
                "Insufficient detail"
                if not member.evaluated
                else "Breaks"
                if member.breaks
                else "Meets rule"
            )
            yield (
                attribution.label(member.member),
                verdict,
                member.left,
                member.right,
                member.gap if member.evaluated else None,
            )


def _md(value: object) -> str:
    """Keep return-supplied text literal in the rendered Markdown."""
    text = escape(str(value), quote=False).replace("\\", "\\\\")
    for char in "*[]`_|#!~":
        text = text.replace(char, "\\" + char)
    return " ".join(text.splitlines())


def markdown(report: FailureReport) -> str:
    """Write a reading copy with the filter context, published rule and each break."""
    lines = [
        "# Failed validation rules",
        "",
        f"{len(report.rules)} {'rule' if len(report.rules) == 1 else 'rules'} · "
        f"{report.occurrences} {'occurrence' if report.occurrences == 1 else 'occurrences'}",
        "",
    ]
    lines.extend(f"- **{label}** · {_md(value)}" for label, value in report.summary.items())
    traces = matched_traces(report.rules, report.attribution)
    for rule in report.rules:
        row = rule.row
        lines.extend(
            (
                "",
                f"## `{row.rule_id}` · {_md(row.label or 'No label published')}",
                "",
                f"{row.severity} · Templates {_md(', '.join(row.templates))} · "
                f"Evaluations that hold: {row.satisfied} · Visible breaks: {len(rule.failures)}",
            )
        )
        for field, value in (
            ("Published rule", rule.expression),
            ("Scope", rule.scope),
            ("Publisher notes", _notes(rule)),
        ):
            if value:
                lines.extend(
                    ("", f"**{field}**", "", *("    " + line for line in value.splitlines()))
                )
        for index, failure in enumerate(rule.failures, 1):
            lines.extend(("", f"### {index}. {_md(failure.place or 'Whole template')}", ""))
            lines.extend(f"- {_md(cell)}" for cell in failure.cells)
            if failure.addresses:
                lines.extend(("", "**Template cells**", ""))
                lines.extend(f"- {_md(_address(cell))}" for cell in failure.addresses)
            if not report.dimension:
                continue
            trace = traces.get((row.rule_id, index))
            if trace is None or report.attribution is None:
                lines.extend(("", "Reporting-unit breakdown unavailable."))
                continue
            lines.extend(
                (
                    "",
                    f"**Reporting units · {_md(report.dimension)}**",
                    "",
                    "| Member | Result | Left | Right | Gap |",
                    "|---|---|---:|---:|---:|",
                )
            )
            for values in _members(report.attribution, trace):
                lines.append(
                    "| " + " | ".join(_md(v) if v is not None else "—" for v in values) + " |"
                )
            total = (trace.left, trace.right, trace.gap)
            lines.append(
                "| The return | Breaks | "
                + " | ".join(str(v) if v is not None else "—" for v in total)
                + " |"
            )
            if trace.unexplained:
                lines.append(f"\nUnexplained gap · {trace.unexplained}")
    return "\n".join(lines) + "\n"


def workbook(report: FailureReport) -> bytes:
    """Write filterable Excel sheets, keeping identifiers literal and numbers numeric."""
    output = BytesIO()
    with xlsxwriter.Workbook(
        output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}
    ) as book:
        heading = book.add_format({"bold": True, "font_color": "white", "bg_color": "#294766"})
        text_cell = book.add_format({"text_wrap": True, "valign": "top"})

        def sheet(name: str, headers: Sequence[str], widths: Sequence[int]) -> Worksheet:
            ws = book.add_worksheet(name)
            for col, label in enumerate(headers):
                ws.write_string(0, col, label, heading)
            ws.freeze_panes(1, 0)
            for col, width in enumerate(widths):
                ws.set_column(col, col, width, text_cell)
            return ws

        def append(ws: Worksheet, values: Sequence[object]) -> None:
            row = (ws.dim_rowmax or 0) + 1
            for col, value in enumerate(values):
                # Even Excel array-formula syntax in a file or member name is literal text.
                status = (
                    ws.write_string(row, col, value)
                    if isinstance(value, str)
                    else ws.write(row, col, value)
                )
                if status != 0:
                    raise ValueError(
                        "These results exceed an Excel sheet or cell limit. Choose Markdown."
                    )

        summary = sheet("Summary", ("Field", "Value"), (28, 72))
        for key, value in report.summary.items():
            append(summary, (key, value))
        append(summary, ("Rules", len(report.rules)))
        append(summary, ("Occurrences", report.occurrences))
        rules = sheet(
            "Rules",
            (
                "Rule ID",
                "Description",
                "Severity",
                "Templates",
                "Evaluations that hold",
                "Visible breaks",
                "Published rule",
                "Scope",
                "Publisher notes",
            ),
            (18, 65, 12, 26, 23, 16, 72, 48, 64),
        )
        columns = ["Rule ID", "Occurrence", "Place", "Values read", "Template cells"]
        if report.dimension:
            columns += ["Breakdown", "Return left", "Return right", "Unexplained gap"]
        failures = sheet("Failures", columns, [18, 14, 32, 72, 72, 24, 18, 18, 22][: len(columns)])
        members = (
            sheet(
                "Reporting units",
                ("Rule ID", "Occurrence", report.dimension, "Result", "Left", "Right", "Gap"),
                (18, 14, 26, 22, 18, 18, 18),
            )
            if report.dimension
            else None
        )
        traces = matched_traces(report.rules, report.attribution)
        for rule in report.rules:
            row = rule.row
            append(
                rules,
                (
                    row.rule_id,
                    row.label or "No label published",
                    row.severity,
                    ", ".join(row.templates),
                    row.satisfied,
                    len(rule.failures),
                    rule.expression,
                    rule.scope,
                    _notes(rule),
                ),
            )
            for index, failure in enumerate(rule.failures, 1):
                values = [
                    row.rule_id,
                    index,
                    failure.place or "Whole template",
                    "\n".join(failure.cells),
                    "\n".join(_address(cell) for cell in failure.addresses),
                ]
                if members is not None:
                    trace = traces.get((row.rule_id, index))
                    if trace is not None and report.attribution is not None:
                        values.extend(
                            (report.dimension, trace.left, trace.right, trace.unexplained)
                        )
                        for standing in _members(report.attribution, trace):
                            append(members, (row.rule_id, index, *standing))
                    else:
                        values.append("Breakdown unavailable")
                append(failures, values)
        for ws in (rules, failures, members):
            if ws is not None:
                ws.autofilter(0, 0, ws.dim_rowmax, ws.dim_colmax)
    return output.getvalue()
