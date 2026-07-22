"""
Cell-fact export — the flat, machine-mappable feed for vendor filing tools.

Pipeline position:
    {COREPTemplateBundle, Pillar3TemplateBundle} -> reporting.catalog
        -> facts.build_fact_frame -> parquet / ndjson (api/export.py)

Key responsibilities:
- Flatten every populated cell across both bundles into ONE long DataFrame,
  keyed by ``(template_id, sheet, row_ref, col_ref)`` — the address a vendor
  filing tool maps against, rather than a merged-header spreadsheet built for
  a human reader.
- Carry ``FilingMetadata`` (reporting date, framework, entity identifier, run
  id, generator version) for a run: stamped onto the fact frame as constant
  columns, rendered as a workbook metadata sheet, and used to name export
  files. See ``api/export.py`` (fact export methods) and ``api/rest.py``
  (the ``/export/{fmt}`` endpoint) for the call sites.

Traversal reuses ``reporting.catalog.template_index`` / ``template_sheet``
rather than re-walking the two bundles: the catalogue is already the one
place that knows how to resolve a bundle field to its frame plus readable
column headers (ref, name, group), across single-frame and per-sheet
templates, CRR and Basel 3.1 column-set variants alike. This module never
recomputes a cell — same rule as ``catalog``.

Design decisions:
- ``value`` is Float64 and NEVER filled. A null cell (e.g. a memorandum row
  with no applicable population under this run) stays null, distinct from an
  explicit 0.0 (a genuine reported zero) — collapsing that distinction would
  discard a fact a filing validator needs. Non-finite floats (NaN / +-Inf,
  which can appear in a ratio over a zero denominator) are also nulled, for
  the same reason ``kernel.excel._finite_only`` nulls them for the workbook
  export: neither is a reportable regulatory figure.
- A handful of template columns are String, not numeric (C 08.02 col 0005 —
  the PD-grade label, injected post-execute per ``corep/c08.py``; Pillar 3
  CR9 cols a/b — the class / PD-range display labels, ``pillar3/cr9.py``).
  Those cells populate ``text_value`` instead of ``value`` (both columns are
  always present on every row; exactly one of the two is non-null) rather
  than being silently dropped or coerced to a number.
- Sign convention (COREP Annex II Section 1.3 "(-)"-labelled deduction
  columns, e.g. C 07.00 col 0030) is SKIPPED for v1. The bundle frames
  already carry the correctly-signed magnitude — each template's own
  post-execute pass applies the negation (e.g.
  ``corep/c07.py::_negate_deduction_cols``) before the frame ever reaches the
  bundle, so no figure here is wrong or missing. A ``sign`` tag ("this cell is
  a deduction line" semantics, independent of the number's own sign) lives on a
  template's ``SheetPlan.negative_cols`` (``reporting/plans.py``) and is read by
  the lineage drill-down — but reaching it needs the run's raw results LazyFrame
  to rebuild the ``SheetPlan``, which this module's bundle-only signature does
  not have (by design — see the traversal note above). Today only the
  lineage-instrumented templates expose a ``SheetPlan``; wiring the sign tag
  here for the other ~29 would mean exposing one from every generator (the
  per-template plan extraction is now cheap, but a bundle-only sign source does
  not yet exist). Left for a follow-up.

Integrator note: ``sheet``, ``value``, ``text_value`` and ``entity_identifier``
are all SPARSE columns — each is null for a large fraction of rows by design
(``sheet`` is null for every single-frame template; ``value``/``text_value``
are mutually exclusive; ``entity_identifier`` is null whenever no
``FilingMetadata`` was supplied). A row-sampling ndjson reader (including
Polars' own ``read_ndjson`` with its default ``infer_schema_length=100``) can
type such a column ``Null`` from an early null-only sample and then fail on a
later non-null row — pass an unbounded/large ``infer_schema_length`` (or
declare an explicit schema) when reading this feed back as ndjson. Parquet is
unaffected (columnar, not row-sampled).

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc import __version__ as _GENERATOR_VERSION
from rwa_calc.reporting import catalog

if TYPE_CHECKING:
    from datetime import date

    from polars._typing import PolarsDataType

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

logger = logging.getLogger(__name__)

# The fact frame's schema, in column order. `text_value` carries the small set
# of String-typed template cells (see module docstring); exactly one of
# `value` / `text_value` is non-null per row.
_FACT_SCHEMA: dict[str, PolarsDataType] = {
    "template_id": pl.String,
    "sheet": pl.String,
    "row_ref": pl.String,
    "row_name": pl.String,
    "col_ref": pl.String,
    "col_name": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
    "framework": pl.String,
}

# The shape of one sheet's unpivoted-but-not-yet-labelled facts, before the
# template_id / sheet / framework / col_name columns are stamped on.
_LONG_SCHEMA: dict[str, PolarsDataType] = {
    "row_ref": pl.String,
    "row_name": pl.String,
    "col_ref": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}


# =============================================================================
# Filing metadata
# =============================================================================


@dataclass(frozen=True)
class FilingMetadata:
    """Filing context for one run, stamped onto the fact export and workbooks.

    ``entity_identifier`` (e.g. an LEI) is firm configuration the caller
    supplies — never a rulepack value; the rulepack carries regulatory
    parameters, not a filer's own identity. ``entity_name`` and
    ``consolidation_basis`` are the multi-entity submission's display name and
    reporting basis (individual / sub_consolidated / consolidated), likewise
    caller-supplied. ``generator_version`` defaults to the installed
    ``rwa_calc`` package version so a downstream vendor tool can tell which
    release produced the feed.
    """

    reporting_date: date
    framework: str
    run_id: str
    entity_identifier: str | None = None
    generator_version: str = _GENERATOR_VERSION
    consolidation_basis: str | None = None
    entity_name: str | None = None

    def as_sheet_fields(self) -> dict[str, str]:
        """Ordered ``{label: value}`` pairs for the workbook metadata sheet.

        ``Entity name`` / ``Consolidation basis`` are emitted only when set, so
        an un-scoped run's metadata sheet is unchanged from before multi-entity
        reporting existed.
        """
        fields = {
            "Reporting date": self.reporting_date.isoformat(),
            "Framework": self.framework,
            "Entity identifier": self.entity_identifier or "",
        }
        if self.entity_name is not None:
            fields["Entity name"] = self.entity_name
        if self.consolidation_basis is not None:
            fields["Consolidation basis"] = self.consolidation_basis
        fields["Run ID"] = self.run_id
        fields["Generator version"] = self.generator_version
        return fields

    def stamped_filename(self, prefix: str, suffix: str) -> str:
        """``{prefix}_{framework}_{reporting_date}[_{entity}_{basis}].{suffix}`` —
        a filing-identifiable download name (see ``api/rest.py``'s
        ``/export/{fmt}`` endpoint).

        The optional ``_<entity_identifier>_<basis>`` scope tokens are appended
        (filesystem-safe, lowercase) only when set, so an un-scoped run keeps
        exactly the ``{prefix}_{framework}_{reporting_date}.{suffix}`` name.
        """
        base = f"{prefix}_{self.framework}_{self.reporting_date.isoformat()}"
        # Filter on the SLUG, not the raw value: an all-unsafe token (e.g. "***")
        # is truthy but slugs to "", which would otherwise emit a dangling "_".
        tokens = [
            s for t in (self.entity_identifier, self.consolidation_basis) if t and (s := _slug(t))
        ]
        scope = f"_{'_'.join(tokens)}" if tokens else ""
        return f"{base}{scope}.{suffix}"


# =============================================================================
# Fact frame
# =============================================================================


def build_fact_frame(
    corep: COREPTemplateBundle | None,
    pillar3: Pillar3TemplateBundle | None,
    *,
    metadata: FilingMetadata | None = None,
) -> pl.DataFrame:
    """Flatten every populated cell of *corep* / *pillar3* into one long DataFrame.

    One row per ``(template_id, sheet, row_ref, col_ref)`` cell that exists in
    a generated template frame — never a cell absent from that frame's row/
    column grid. A template that did not apply to this run's regime or
    portfolio is already excluded upstream by ``catalog.template_index``, so
    it contributes no rows here either. Pass ``corep=None`` / ``pillar3=None``
    to export only the other family.

    Supply *metadata* to stamp ``reporting_date`` / ``entity_identifier`` /
    ``run_id`` / ``generator_version`` as constant columns; omit it for a bare
    cell feed with no run context.
    """
    sheets: list[pl.DataFrame] = []
    for info in catalog.template_index(corep, pillar3):
        bundle = corep if info.family == "corep" else pillar3
        framework = _framework(bundle)
        for sheet_key in info.sheets or (None,):
            view = catalog.template_sheet(corep, pillar3, info.id, sheet_key)
            if view is not None:
                sheets.append(_sheet_facts(view, framework))

    frame = pl.concat(sheets, how="vertical") if sheets else pl.DataFrame(schema=_FACT_SCHEMA)
    return _stamp_metadata(frame, metadata) if metadata is not None else frame


# =============================================================================
# Private helpers
# =============================================================================


def _framework(bundle: COREPTemplateBundle | Pillar3TemplateBundle | None) -> str:
    """The bundle's own framework tag — mirrors ``catalog``'s internal resolution."""
    return getattr(bundle, "framework", "CRR")


def _sheet_facts(view: catalog.TemplateSheet, framework: str) -> pl.DataFrame:
    """Unpivot one resolved template sheet into the long fact shape.

    Value columns split by dtype before unpivoting — Polars' ``unpivot``
    needs a uniform value dtype per call, and a handful of template columns
    are String display labels rather than numeric cells (see module
    docstring). Non-finite numeric cells (NaN / +-Inf) are nulled, matching
    ``kernel.excel``'s workbook treatment of the same values.
    """
    if not view.columns:
        return pl.DataFrame(schema=_FACT_SCHEMA)

    frame = view.frame
    numeric_refs = [c.ref for c in view.columns if frame.schema[c.ref].is_numeric()]
    text_refs = [c.ref for c in view.columns if c.ref not in numeric_refs]

    parts: list[pl.DataFrame] = []
    if numeric_refs:
        parts.append(_numeric_part(frame, numeric_refs))
    if text_refs:
        parts.append(_text_part(frame, text_refs))
    long = pl.concat(parts, how="vertical") if parts else pl.DataFrame(schema=_LONG_SCHEMA)

    name_map = pl.DataFrame(
        {"col_ref": [c.ref for c in view.columns], "col_name": [c.name for c in view.columns]}
    )
    return (
        long.join(name_map, on="col_ref", how="left")
        .with_columns(
            pl.lit(view.info.id).alias("template_id"),
            pl.lit(view.sheet, dtype=pl.String).alias("sheet"),
            pl.lit(framework).alias("framework"),
        )
        .select(list(_FACT_SCHEMA))
    )


def _numeric_part(frame: pl.DataFrame, numeric_refs: list[str]) -> pl.DataFrame:
    """Unpivot the numeric value columns into the long ``value`` shape."""
    long = (
        frame.select("row_ref", "row_name", *numeric_refs)
        .unpivot(
            index=("row_ref", "row_name"),
            on=numeric_refs,
            variable_name="col_ref",
            value_name="value",
        )
        .cast({"value": pl.Float64})
    )
    finite = pl.when(pl.col("value").is_finite()).then(pl.col("value")).otherwise(None)
    return long.with_columns(
        finite.alias("value"), pl.lit(None, dtype=pl.String).alias("text_value")
    ).select(list(_LONG_SCHEMA))


def _text_part(frame: pl.DataFrame, text_refs: list[str]) -> pl.DataFrame:
    """Unpivot the String value columns into the long ``text_value`` shape."""
    long = (
        frame.select("row_ref", "row_name", *text_refs)
        .unpivot(
            index=("row_ref", "row_name"),
            on=text_refs,
            variable_name="col_ref",
            value_name="text_value",
        )
        .cast({"text_value": pl.String})
    )
    return long.with_columns(pl.lit(None, dtype=pl.Float64).alias("value")).select(
        list(_LONG_SCHEMA)
    )


def _stamp_metadata(frame: pl.DataFrame, metadata: FilingMetadata) -> pl.DataFrame:
    """Stamp reporting_date / entity_identifier / entity_name /
    consolidation_basis / run_id / generator_version.

    ``framework`` is already a per-row column (each cell carries the framework
    of the bundle it came from), so ``metadata.framework`` is not re-stamped
    as a second column — the two are expected to agree for one run. The scope
    columns ``entity_name`` / ``consolidation_basis`` are stamped as null when
    unset, matching ``entity_identifier``'s existing null-when-None treatment.
    """
    return frame.with_columns(
        pl.lit(metadata.reporting_date).alias("reporting_date"),
        pl.lit(metadata.entity_identifier, dtype=pl.String).alias("entity_identifier"),
        pl.lit(metadata.entity_name, dtype=pl.String).alias("entity_name"),
        pl.lit(metadata.consolidation_basis, dtype=pl.String).alias("consolidation_basis"),
        pl.lit(metadata.run_id).alias("run_id"),
        pl.lit(metadata.generator_version).alias("generator_version"),
    )


# Filesystem-safe scope tokens: lowercase, alphanumerics / ``_`` / ``-`` kept,
# any other run of characters collapsed to a single ``-`` (leading/trailing
# ``-`` stripped). Keeps the already-safe basis strings ("sub_consolidated")
# intact while making a free-form entity identifier safe for a download name.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^a-z0-9_-]+")


def _slug(value: str) -> str:
    """Lowercase, filesystem-safe form of *value* for a stamped download name."""
    return _UNSAFE_FILENAME_CHARS.sub("-", value.strip().lower()).strip("-")
