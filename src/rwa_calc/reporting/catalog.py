"""
Template catalogue — one uniform view over the COREP and Pillar 3 bundles.

Pipeline position:
    {COREPGenerator, Pillar3Generator} -> {COREPTemplateBundle,
    Pillar3TemplateBundle} -> catalog -> {api/rest, ui/views}

Key responsibilities:
- Index the two bundles as one ordered list of ``TemplateInfo`` (id, title,
  family, sheet keys), so a consumer renders every template without knowing
  which bundle field it lives on, or whether it is a per-sheet dict or a
  single frame.
- Resolve one template sheet to its frame plus readable ``ColumnHeader``s
  (ref, name, group) from the frozen per-template column definitions.

The template **ids are the bundle field names** — exactly the ids the rulepack's
``ReportingTemplateSet`` carries (``c07_00``, ``cr5``, …). That is the key space
a report cell is addressed by: ``(template_id, sheet, row_ref, col_ref)``.

What this module does NOT do: it never recomputes a cell. Frames are taken
verbatim from the generators, including their post-passes (Annex II §1.3 "(-)"
negation; all-null inert rows). A consumer renders what the generator produced.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
- docs/plans/report-cell-lineage.md §3 (Phase A — the template viewer)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import polars as pl

from rwa_calc.reporting.corep import templates as ct
from rwa_calc.reporting.pillar3 import templates as pt

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

logger = logging.getLogger(__name__)

# The two structural columns every template frame leads with (see
# reporting/kernel/excel.py). Not regulatory column refs — never rendered as
# value cells, and never addressable as a report cell.
STRUCTURAL_COLS: tuple[str, ...] = ("row_ref", "row_name")

type Family = Literal["corep", "pillar3"]

# Sheet-axis labels (what the per-sheet dict key means).
_CLASS = "Exposure class"
_COUNTRY = "Country"
_NETTING_SET = "Netting set"
_SUBTEMPLATE = "Sub-template"


class RefNamed(Protocol):
    """Structural view of a column definition — ``COREPColumn`` / ``P3Column``."""

    @property
    def ref(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def group(self) -> str: ...


@dataclass(frozen=True)
class ColumnHeader:
    """A template value column: regulatory ref, readable name, logical group."""

    ref: str
    name: str
    group: str = ""


@dataclass(frozen=True)
class TemplateInfo:
    """One template available for a run.

    ``sheets`` is empty for a single-frame template and carries the sheet keys
    for a per-sheet template; ``sheet_label`` names that axis.
    """

    id: str
    title: str
    family: Family
    sheets: tuple[str, ...] = ()
    sheet_label: str = ""


@dataclass(frozen=True)
class TemplateSheet:
    """One rendered sheet: the generator's frame plus its column headers."""

    info: TemplateInfo
    sheet: str | None
    columns: tuple[ColumnHeader, ...]
    frame: pl.DataFrame


@dataclass(frozen=True)
class _TemplateDef:
    """Static catalogue entry: where a template lives and how it is labelled."""

    id: str
    title: str
    family: Family
    columns: Callable[[str], Sequence[RefNamed]]
    sheet_label: str = ""


def _fixed(columns: Sequence[RefNamed]) -> Callable[[str], Sequence[RefNamed]]:
    """Adapt a framework-invariant column constant to the resolver signature."""

    def resolve(_framework: str) -> Sequence[RefNamed]:
        return columns

    return resolve


# The ordered catalogue. Titles carry the regulatory code so the picker reads
# like the submission pack. Column resolvers are the frozen template
# definitions — framework-variant where the regime changes the column set
# (e.g. CRR C 07.00 has 24 columns; Basel 3.1 OF 07.00 has 22).
_TEMPLATES: tuple[_TemplateDef, ...] = (
    _TemplateDef("c_02_00", "C 02.00 — Own funds requirements", "corep", ct.get_c02_00_columns),
    _TemplateDef("c07_00", "C 07.00 — SA credit risk", "corep", ct.get_c07_columns, _CLASS),
    _TemplateDef("c08_01", "C 08.01 — IRB totals", "corep", ct.get_c08_columns, _CLASS),
    _TemplateDef("c08_02", "C 08.02 — IRB by PD grade", "corep", ct.get_c08_02_columns, _CLASS),
    _TemplateDef("c08_03", "C 08.03 — IRB PD ranges", "corep", ct.get_c08_03_columns, _CLASS),
    _TemplateDef("c08_04", "C 08.04 — IRB RWEA flow", "corep", ct.get_c08_04_columns, _CLASS),
    _TemplateDef("c08_05", "C 08.05 — IRB PD backtesting", "corep", ct.get_c08_05_columns, _CLASS),
    _TemplateDef("c08_06", "C 08.06 — IRB slotting", "corep", ct.get_c08_06_columns, _CLASS),
    _TemplateDef("c08_07", "C 08.07 — IRB scope of use", "corep", ct.get_c08_07_columns),
    _TemplateDef("of_02_01", "OF 02.01 — Output floor", "corep", _fixed(ct.OF_02_01_COLUMNS)),
    _TemplateDef(
        "c09_01", "C 09.01 — Geo breakdown (SA)", "corep", ct.get_c09_01_columns, _COUNTRY
    ),
    _TemplateDef(
        "c09_02", "C 09.02 — Geo breakdown (IRB)", "corep", ct.get_c09_02_columns, _COUNTRY
    ),
    _TemplateDef("c34_01", "C 34.01 — CCR by approach", "corep", _fixed(ct.C34_01_COLUMNS)),
    _TemplateDef(
        "c34_02",
        "C 34.02 — SA-CCR by netting set",
        "corep",
        _fixed(ct.C34_02_COLUMNS),
        _NETTING_SET,
    ),
    _TemplateDef("c34_04", "C 34.04 — CVA capital", "corep", _fixed(ct.C34_04_COLUMNS)),
    _TemplateDef("c34_08", "C 34.08 — CCP exposures", "corep", _fixed(ct.C34_08_COLUMNS)),
    _TemplateDef("ov1", "OV1 — RWEA overview", "pillar3", _fixed(pt.OV1_COLUMNS)),
    _TemplateDef("cr4", "CR4 — SA exposure and CRM effects", "pillar3", pt.get_cr4_columns),
    _TemplateDef("cr5", "CR5 — SA exposures by risk weight", "pillar3", pt.get_cr5_columns),
    _TemplateDef("cr6", "CR6 — IRB by PD range", "pillar3", pt.get_cr6_columns, _CLASS),
    _TemplateDef("cr6a", "CR6-A — IRB scope of use", "pillar3", _fixed(pt.CR6A_COLUMNS)),
    _TemplateDef("cr7", "CR7 — IRB CRM effect on RWEA", "pillar3", _fixed(pt.CR7_COLUMNS)),
    _TemplateDef("cr7a", "CR7-A — IRB CRM techniques", "pillar3", pt.get_cr7a_columns, _CLASS),
    _TemplateDef("cr8", "CR8 — IRB RWEA flow", "pillar3", _fixed(pt.CR8_COLUMNS)),
    _TemplateDef("cr9", "CR9 — IRB PD backtesting", "pillar3", _fixed(pt.CR9_COLUMNS), _CLASS),
    _TemplateDef(
        "cr9_1", "CR9.1 — IRB PD backtesting (ECAI)", "pillar3", _fixed(pt.CR9_1_COLUMNS), _CLASS
    ),
    _TemplateDef("cr10", "CR10 — Slotting", "pillar3", pt.get_cr10_columns, _SUBTEMPLATE),
    _TemplateDef("cms1", "CMS1 — Output floor comparison", "pillar3", _fixed(pt.CMS1_COLUMNS)),
    _TemplateDef("cms2", "CMS2 — Output floor by risk type", "pillar3", _fixed(pt.CMS2_COLUMNS)),
    _TemplateDef("ccr1", "CCR1 — CCR by approach", "pillar3", _fixed(pt.CCR1_COLUMNS)),
    _TemplateDef("ccr2", "CCR2 — CVA capital", "pillar3", _fixed(pt.CCR2_COLUMNS)),
    _TemplateDef("ccr3", "CCR3 — CCR by risk weight", "pillar3", _fixed(pt.CCR3_COLUMNS)),
    _TemplateDef("ccr8", "CCR8 — CCP exposures", "pillar3", _fixed(pt.CCR8_COLUMNS)),
)

_BY_ID: dict[str, _TemplateDef] = {spec.id: spec for spec in _TEMPLATES}


def template_index(
    corep: COREPTemplateBundle | None, pillar3: Pillar3TemplateBundle | None
) -> tuple[TemplateInfo, ...]:
    """Every template with content for this run, in catalogue order.

    A template whose bundle field is ``None`` (single-frame) or ``{}``
    (per-sheet) did not apply to the portfolio or the regime and is omitted —
    the picker only offers templates that exist.
    """
    infos: list[TemplateInfo] = []
    for spec in _TEMPLATES:
        bundle = corep if spec.family == "corep" else pillar3
        if bundle is None:
            continue
        info = _info_for(spec, getattr(bundle, spec.id, None))
        if info is not None:
            infos.append(info)
    return tuple(infos)


def template_sheet(
    corep: COREPTemplateBundle | None,
    pillar3: Pillar3TemplateBundle | None,
    template_id: str,
    sheet: str | None = None,
) -> TemplateSheet | None:
    """Resolve one template sheet to its frame + column headers.

    ``sheet`` selects the key of a per-sheet template; ``None`` takes the first
    sheet (catalogue order) so a caller can link to a template without knowing
    its keys. Returns ``None`` for an unknown id, an unknown sheet, or a
    template absent from this run.
    """
    spec = _BY_ID.get(template_id)
    if spec is None:
        return None
    bundle = corep if spec.family == "corep" else pillar3
    if bundle is None:
        return None
    value = getattr(bundle, spec.id, None)
    info = _info_for(spec, value)
    if info is None:
        return None

    selected: str | None = None
    if isinstance(value, dict):
        selected = info.sheets[0] if sheet is None else sheet
        frame = value.get(selected)
    else:
        frame = value
    if not isinstance(frame, pl.DataFrame):
        return None

    framework = getattr(bundle, "framework", "CRR")
    return TemplateSheet(
        info=info,
        sheet=selected,
        columns=_headers(spec, framework, frame),
        frame=frame,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _info_for(spec: _TemplateDef, value: object) -> TemplateInfo | None:
    """The ``TemplateInfo`` for a bundle field, or None when it has no content."""
    if isinstance(value, dict):
        if not value:
            return None
        return TemplateInfo(
            id=spec.id,
            title=spec.title,
            family=spec.family,
            sheets=tuple(sorted(value)),
            sheet_label=spec.sheet_label,
        )
    if value is None:
        return None
    return TemplateInfo(id=spec.id, title=spec.title, family=spec.family)


def _headers(spec: _TemplateDef, framework: str, frame: pl.DataFrame) -> tuple[ColumnHeader, ...]:
    """Readable headers for the frame's value columns, in frame order.

    The FRAME is authoritative for which columns exist (regime variants, and the
    data-driven column sets); the definitions supply the readable name and
    group. A frame column with no definition falls back to its ref as its name
    rather than being dropped — a missing label must never hide a reported cell.
    """
    defined = {col.ref: col for col in spec.columns(framework)}
    headers: list[ColumnHeader] = []
    for ref in frame.columns:
        if ref in STRUCTURAL_COLS:
            continue
        col = defined.get(ref)
        headers.append(
            ColumnHeader(ref=ref, name=col.name, group=col.group)
            if col is not None
            else ColumnHeader(ref=ref, name=ref)
        )
    return tuple(headers)
