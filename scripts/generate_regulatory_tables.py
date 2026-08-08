"""Regenerate ``docs/data-model/regulatory-tables.md`` from the resolved rulepacks.

The regulatory-tables docs page used to be hand-written prose that restated the
pack values — and hand-maintained copies of machine-knowable facts drift. This
script makes drift impossible instead of detected: it resolves both regime
packs (``crr`` at its 2026 reporting date, ``b31`` at commencement) and renders
every cited entry — features, scalars, lookup / banded / decision tables,
schedules, formula bundles — into one deterministic markdown reference.
Entries identical in both regimes render once; regime-divergent entries render
side by side, which is exactly the CRR↔B31 delta a reader wants.

Determinism is load-bearing: the output embeds the package version and each
pack's content hash but no timestamps, so re-running on an unchanged tree is
byte-identical and ``tests/contracts/test_docs_generated.py`` can gate
freshness by simple string equality. A pack edit that skips regeneration turns
that test red.

Usage:
    uv run python scripts/generate_regulatory_tables.py           # rewrite the page
    uv run python scripts/generate_regulatory_tables.py --check   # exit 1 if stale

Exit codes:
    0 = page written (or already fresh under --check)
    1 = --check found the page stale
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import fields, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rwa_calc.rulebook.model import (  # noqa: E402
    BandedTable,
    CategoryMap,
    DateParam,
    DecisionTable,
    Feature,
    FormulaParams,
    IntParam,
    LookupTable,
    ScalarParam,
    Schedule,
)
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "docs" / "data-model" / "regulatory-tables.md"

#: The canonical resolution date per regime: CRR as currently in force, B31 at
#: its PS1/26 commencement. Changing a date changes every date-gated entry, so
#: these are deliberately fixed rather than "today".
REGIME_DATES: tuple[tuple[str, date], ...] = (
    ("crr", date(2026, 1, 1)),
    ("b31", date(2027, 1, 1)),
)

REGIME_LABELS = {"crr": "CRR", "b31": "Basel 3.1"}

#: Section order on the page: behaviour switches first, simple values next,
#: structured tables after.
SECTIONS: tuple[tuple[str, type, str], ...] = (
    ("Regime features", Feature, "On/off behaviour switches (`Feature`)."),
    (
        "Scalar parameters",
        ScalarParam,
        "Decimal-valued parameters (`ScalarParam`). "
        "Risk weights and factors are decimal fractions (0.20 = 20%).",
    ),
    (
        "Integer parameters",
        IntParam,
        "Integer counts — day floors, thresholds, band bounds (`IntParam`).",
    ),
    ("Date parameters", DateParam, "Calendar-date parameters (`DateParam`)."),
    ("Lookup tables", LookupTable, "Exact-match key → value tables (`LookupTable`)."),
    ("Category maps", CategoryMap, "Label → label classification maps (`CategoryMap`)."),
    (
        "Banded tables",
        BandedTable,
        "Ordered threshold tables over a numeric input (`BandedTable`).",
    ),
    ("Schedules", Schedule, "Date-stepped values with carry-forward (`Schedule`)."),
    ("Decision tables", DecisionTable, "Multi-key decision tables (`DecisionTable`)."),
    (
        "Formula parameter bundles",
        FormulaParams,
        "Named parameter sets for one formula (`FormulaParams`).",
    ),
)


def render() -> str:
    """Render the whole page from freshly resolved packs."""
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    lines = _header(packs)
    for title, shape, blurb in SECTIONS:
        lines.extend(_render_section(title, shape, blurb, packs))
    lines.extend(_render_other_shapes(packs))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate docs/data-model/regulatory-tables.md from the resolved rulepacks."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed page differs from a fresh render",
    )
    args = parser.parse_args()

    content = render()
    if args.check:
        on_disk = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if on_disk != content:
            sys.stderr.write(
                f"{OUTPUT_PATH.relative_to(REPO_ROOT)} is stale — regenerate with\n"
                "  uv run python scripts/generate_regulatory_tables.py\n"
            )
            return 1
        return 0

    OUTPUT_PATH.write_text(content, encoding="utf-8")
    sys.stderr.write(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}\n")
    return 0


# ---------------------------------------------------------------------------
# Private helpers — page assembly
# ---------------------------------------------------------------------------


def _header(packs: dict[str, ResolvedRulepack]) -> list[str]:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    lines = [
        "# Regulatory Tables",
        "",
        "<!-- GENERATED FILE — DO NOT EDIT."
        " Regenerate: uv run python scripts/generate_regulatory_tables.py -->",
        "",
        "Every cited regulatory value in the rulepack packs"
        " `src/rwa_calc/rulebook/packs/{common,crr,b31}.py`, rendered from"
        " `rwa_calc.rulebook.resolve.resolve(regime, date)`. **This page is"
        " generated** — a wrong value here is a rulepack finding, never a docs"
        " edit. Entries identical under both regimes appear once; divergent"
        " entries appear per regime.",
        "",
        f"Package version `{version}`. Resolved packs:",
        "",
    ]
    for regime, on in REGIME_DATES:
        pack = packs[regime]
        lines.append(
            f"- **{REGIME_LABELS[regime]}** (`{regime}` @ {on.isoformat()}) — "
            f"{len(pack.entries)} entries, content hash `{pack.content_hash[:16]}`"
        )
    lines.append("")
    return lines


def _render_section(
    title: str, shape: type, blurb: str, packs: dict[str, ResolvedRulepack]
) -> list[str]:
    names = sorted(
        {
            name
            for pack in packs.values()
            for name, entry in pack.entries.items()
            if type(entry) is shape
        }
    )
    if not names:
        return []
    lines = [f"## {title}", "", blurb, ""]
    if shape in (Feature, ScalarParam, IntParam, DateParam):
        lines.extend(_render_simple_table(names, shape, packs))
    else:
        for name in names:
            lines.extend(_render_structured_entry(name, packs))
    return lines


def _render_simple_table(
    names: list[str], shape: type, packs: dict[str, ResolvedRulepack]
) -> list[str]:
    lines = [
        "| Name | CRR | Basel 3.1 | Citation |",
        "|---|---|---|---|",
    ]
    for name in names:
        crr = packs["crr"].entries.get(name)
        b31 = packs["b31"].entries.get(name)
        crr_value = _simple_value(crr) if type(crr) is shape else "—"
        b31_value = _simple_value(b31) if type(b31) is shape else "—"
        lines.append(f"| `{name}` | {crr_value} | {b31_value} | {_citations(crr, b31)} |")
    lines.append("")
    return lines


def _render_structured_entry(name: str, packs: dict[str, ResolvedRulepack]) -> list[str]:
    crr = packs["crr"].entries.get(name)
    b31 = packs["b31"].entries.get(name)
    lines = [f"### `{name}`", ""]
    if crr is not None and crr == b31:
        lines.extend(_entry_block(crr, "Both regimes"))
    else:
        if crr is not None:
            lines.extend(_entry_block(crr, "CRR"))
        if b31 is not None:
            lines.extend(_entry_block(b31, "Basel 3.1" if crr is not None else "Basel 3.1 only"))
    return lines


def _entry_block(entry: Any, scope: str) -> list[str]:
    lines = [f"**{scope}** — {_md(str(entry.citation))}"]
    if getattr(entry.citation, "note", ""):
        lines.append(f" *({_md(entry.citation.note)})*")
    lines.append("")
    match entry:
        case LookupTable() | CategoryMap():
            lines.append(f"Key column: `{entry.key}`" + _default_suffix(entry.default))
            lines.append("")
            lines.append("| Key | Value |")
            lines.append("|---|---|")
            lines.extend(f"| {_md_key(k)} | {_md_value(v)} |" for k, v in entry.entries.items())
        case BandedTable():
            bound_op = "<=" if entry.right_closed else "<"
            lines.append(
                f"Input column: `{entry.input}` (band applies when input {bound_op} bound)"
            )
            lines.append("")
            lines.append("| Upper bound | Value |")
            lines.append("|---|---|")
            lines.extend(
                f"| {'—' if bound is None else _md_value(bound)} | {_md_value(value)} |"
                for bound, value in entry.bands
            )
        case Schedule():
            lines.append(f"Before first step: {_md_value(entry.before_first)}")
            lines.append("")
            lines.append("| Effective date | Value |")
            lines.append("|---|---|")
            lines.extend(
                f"| {step_date.isoformat()} | {_md_value(value)} |"
                for step_date, value in entry.steps
            )
        case DecisionTable():
            key_header = " , ".join(f"`{k}`" for k in entry.key_names)
            lines.append(f"Keys: {key_header}" + _default_suffix(entry.default))
            lines.append("")
            lines.append("| Keys | Value |")
            lines.append("|---|---|")
            lines.extend(f"| {_md_key(keys)} | {_md_value(value)} |" for keys, value in entry.rows)
        case FormulaParams():
            lines.append("| Parameter | Value |")
            lines.append("|---|---|")
            lines.extend(f"| `{k}` | {_md_value(v)} |" for k, v in entry.params.items())
        case _:
            lines.extend(_generic_fields(entry))
    lines.append("")
    return lines


def _render_other_shapes(packs: dict[str, ResolvedRulepack]) -> list[str]:
    """Any entry shape not named in ``SECTIONS`` (e.g. ``ReportingTemplateSet``).

    Rendered generically from dataclass fields so a future shape cannot be
    silently omitted from the page.
    """
    known = {shape for _, shape, _ in SECTIONS}
    names = sorted(
        {
            name
            for pack in packs.values()
            for name, entry in pack.entries.items()
            if type(entry) not in known
        }
    )
    if not names:
        return []
    lines = [
        "## Other entries",
        "",
        "Shapes outside the standard vocabulary, rendered field-by-field.",
        "",
    ]
    for name in names:
        lines.extend(_render_structured_entry(name, packs))
    return lines


def _generic_fields(entry: Any) -> list[str]:
    if not is_dataclass(entry):
        return [f"`{_md(repr(entry))}`"]
    lines = ["| Field | Value |", "|---|---|"]
    lines.extend(
        f"| `{f.name}` | {_md_value(getattr(entry, f.name))} |"
        for f in fields(entry)
        if f.name not in ("name", "citation")
    )
    return lines


# ---------------------------------------------------------------------------
# Private helpers — formatting
# ---------------------------------------------------------------------------


def _simple_value(entry: Any) -> str:
    match entry:
        case Feature():
            return "on" if entry.enabled else "off"
        case ScalarParam() | IntParam():
            return _md_value(entry.value)
        case DateParam():
            return entry.value.isoformat()
        case _:
            return "—"


def _citations(*entries: Any) -> str:
    cited = [str(e.citation) for e in entries if e is not None]
    unique = list(dict.fromkeys(cited))
    return _md(" / ".join(unique)) if unique else "—"


def _default_suffix(default: Any) -> str:
    return "" if default is None else f"; default {_md_value(default)}"


def _md_key(key: Any) -> str:
    if isinstance(key, tuple):
        return ", ".join(f"`{_md(str(part))}`" for part in key)
    return f"`{_md(str(key))}`"


def _md_value(value: Any) -> str:
    return f"`{_md(str(value))}`"


def _md(text: str) -> str:
    """Escape the one character that breaks a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
