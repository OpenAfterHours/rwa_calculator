"""
Table bindings — publisher table codes onto our generated template bundles.

Pipeline position:
    COREPTemplateBundle  ->  build_template_index  ->  rwa_filer TemplateIndex
        ->  rwa_filer.validate (the rule engine)

Key responsibilities:
- Bind a publisher TABLE code (``C 07.00.a`` / ``OF08.01.01.01``) to the bundle
  member that carries it.
- Build the ``TemplateIndex`` the ``rwa-filer`` rule engine reads a return
  through, from whatever a run actually produced: our frames, these bindings and
  the cited sheet maps (``sheet_maps.SHEET_INDEX_MAPS``).
- Restrict each DPM variant to its own columns, derived from the rule extract
  rather than hand-written (``derive_variant_columns``). The one hand-written
  restriction is CRR ``C 08.06``, a sole binding whose frame also carries the
  printed Table 1 risk weights in column 0070, which is not a data point
  (``_C08_06_DATA_POINT_COLUMNS``).

This module is the adapter boundary. Everything that knows about this
calculator's bundles, sheet names or exposure classes is on this side of it;
everything that knows how to read and evaluate a published rule is in
``rwa_filer``, which never imports ``rwa_calc``.

References:
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1) — the templates bound
- docs/reference/validation-rules/index.md — the rule grammar
"""

from __future__ import annotations

import logging
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1, load_rules
from rwa_filer.validate import index as filer_index
from rwa_filer.validate.index import SINGLE_SHEET, TableBinding, TemplateIndex

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

logger = logging.getLogger(__name__)

#: CRR C 08.06's reported columns: every column of the template except 0070.
#: Column 0070 is Art. 153(5) Table 1 printed onto the template. Annex II (p.115)
#: says: "This is a fixed column for information purposes. It shall not be
#: altered." It is therefore not a DPM data point, and the EBA's ``(All)``-column
#: rules never reach it. The evidence is indirect, because the EBA DPM is not
#: held here: the EBA's generated sign rules on C 08.06 (``v10309_s`` >= 0,
#: ``v10310_s`` <= 0) list every column except 0070, while the same rule family
#: covers percentage and parameter columns on other templates, and no EBA rule
#: in any release addresses C 08.06 c0070. Left in, it made ``v09782_m`` and
#: ``v09783_m`` compare a Total row against a sum of fixed weights (4.85 / 5.25),
#: which no Total value can meet. ``derive_variant_columns`` scopes only shared
#: frames, so this sole binding carries its set by hand.
_C08_06_DATA_POINT_COLUMNS: Final = frozenset(
    {"0010", "0020", "0030", "0040", "0050", "0060", "0080", "0090", "0100"}
)

#: The CRR (EBA) table codes. C 07.00 is split a/b/c/d and C 08.01 a/b in the
#: DPM purely as row/column partitions of ONE template (a: the main body; b: the
#: pre-supporting-factor columns 0210/0211; c/d: the memorandum rows 0290-0320),
#: and our single frame carries the union — so all four bind to the same member.
_CRR_TABLES: Final[Mapping[str, TableBinding]] = {
    "C 02.00": TableBinding("c_02_00", per_sheet=False),
    "C 07.00.a": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.b": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.c": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 07.00.d": TableBinding("c07_00", per_sheet=True, sheet_map="c07"),
    "C 08.01.a": TableBinding("c08_01", per_sheet=True, sheet_map="c08"),
    "C 08.01.b": TableBinding("c08_01", per_sheet=True, sheet_map="c08"),
    "C 08.02": TableBinding("c08_02", per_sheet=True, sheet_map="c08"),
    "C 08.03": TableBinding("c08_03", per_sheet=True, sheet_map="c08"),
    "C 08.04": TableBinding("c08_04", per_sheet=True, sheet_map="c08"),
    "C 08.05": TableBinding("c08_05", per_sheet=True, sheet_map="c08"),
    "C 08.06": TableBinding("c08_06", per_sheet=True, columns=_C08_06_DATA_POINT_COLUMNS),
    "C 08.07": TableBinding("c08_07", per_sheet=False),
    "C 09.01.a": TableBinding("c09_01", per_sheet=True),
    "C 09.01.b": TableBinding("c09_01", per_sheet=True),
    "C 09.02": TableBinding("c09_02", per_sheet=True),
    "C 34.01.a": TableBinding("c34_01", per_sheet=False),
    "C 34.01.b": TableBinding("c34_01", per_sheet=False),
    "C 34.02": TableBinding("c34_02", per_sheet=True),
    "C 34.04": TableBinding("c34_04", per_sheet=False),
    "C 34.08.a": TableBinding("c34_08", per_sheet=False),
    "C 34.08.b": TableBinding("c34_08", per_sheet=False),
}

#: The Basel 3.1 (BoE) table codes. The trailing ``.01.0N`` segments are DPM
#: variants of one template, exactly as the EBA ``.a``/``.b`` suffixes are.
_B31_TABLES: Final[Mapping[str, TableBinding]] = {
    "OF02.00.01.01": TableBinding("c_02_00", per_sheet=False),
    "OF02.01.01.01": TableBinding("of_02_01", per_sheet=False),
    "OF02.01.01.02": TableBinding("of_02_01", per_sheet=False),
    "OF02.01.01.03": TableBinding("of_02_01", per_sheet=False),
    "OF07.00.01.01": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.02": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.03": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.04": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF07.00.01.05": TableBinding("c07_00", per_sheet=True, sheet_map="of07"),
    "OF08.01.01.01": TableBinding("c08_01", per_sheet=True, sheet_map="of08"),
    "OF08.01.01.02": TableBinding("c08_01", per_sheet=True, sheet_map="of08"),
    "OF08.02.01.01": TableBinding("c08_02", per_sheet=True, sheet_map="of08"),
    "OF08.03.01.01": TableBinding("c08_03", per_sheet=True, sheet_map="of08"),
    "C08.04.01.01": TableBinding("c08_04", per_sheet=True, sheet_map="of08"),
    "OF08.05.00.01": TableBinding("c08_05", per_sheet=True, sheet_map="of08"),
    "OF08.05.01.01": TableBinding("c08_05", per_sheet=True, sheet_map="of08"),
    "OF08.06.01.01": TableBinding("c08_06", per_sheet=True),
    "OF08.07.01.01": TableBinding("c08_07", per_sheet=False),
    "OF09.01.01.01": TableBinding("c09_01", per_sheet=True),
    "OF09.02.01.01": TableBinding("c09_02", per_sheet=True),
    "C34.01.01.01": TableBinding("c34_01", per_sheet=False),
    "C34.02.01.01": TableBinding("c34_02", per_sheet=True),
    "C34.04.01.01": TableBinding("c34_04", per_sheet=False),
    "C34.08.01.01": TableBinding("c34_08", per_sheet=False),
    "C34.08.01.02": TableBinding("c34_08", per_sheet=False),
}


# =============================================================================
# Public API
# =============================================================================


def build_template_index(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> TemplateIndex:
    """Index the generated bundles by publisher table code.

    ``pillar3`` is accepted (and carried on the project's public contract)
    because the estate is generated as a pair, but NO rule in either published
    extract addresses a Pillar 3 disclosure template — both rule sets scope
    COREP/OF tables only. It is therefore not indexed today; when the CCR /
    Pillar 3 rule families land it becomes the second source of frames.

    Args:
        corep: The generated COREP bundle.
        pillar3: The generated Pillar 3 bundle (unused; see above).
        framework: ``"CRR"`` or ``"BASEL_3_1"`` — selects the table code space.

    Returns:
        A ``TemplateIndex`` over whatever the run actually produced.
    """
    del pillar3  # see docstring: no published rule addresses a Pillar 3 template
    bindings = _bindings_for(framework)
    frames: dict[str, dict[str, pl.DataFrame]] = {}
    for binding in bindings.values():
        if binding.attribute in frames:
            continue
        member = getattr(corep, binding.attribute, None)
        if member is None:
            continue
        if isinstance(member, pl.DataFrame):
            frames[binding.attribute] = {SINGLE_SHEET: member}
        elif isinstance(member, dict) and member:
            frames[binding.attribute] = dict(member)
    return TemplateIndex(
        framework=framework,
        frames=frames,
        bindings=bindings,
        sheet_maps=SHEET_INDEX_MAPS,
    )


@cache
def derive_variant_columns(framework: str) -> Mapping[str, frozenset[str]]:
    """Each DPM variant's own column set for ``framework``, from the rule extract.

    Our single C 09.01 frame carries the union of ``C 09.01.a`` and
    ``C 09.01.b``; a rule scoped ``columns: (All)`` on one variant must iterate
    only that variant's columns. The derivation itself is
    ``rwa_filer.validate.index.derive_variant_columns``; this binds it to our
    table map and to the ENFORCED rules of the packaged extract (a withdrawn
    rule may reference a retired column, which would widen a variant's set and
    quietly weaken the partition).

    Returns:
        ``{table code: columns}`` for the codes that could be scoped. A code
        absent from the mapping is deliberately unrestricted.
    """
    return filer_index.derive_variant_columns(
        load_rules(framework).enforced, _base_bindings(framework)
    )


# =============================================================================
# Private helpers
# =============================================================================


def _base_bindings(framework: str) -> Mapping[str, TableBinding]:
    """The literal table map for a framework, before column scoping."""
    return _B31_TABLES if framework == FRAMEWORK_BASEL_3_1 else _CRR_TABLES


@cache
def _bindings_for(framework: str) -> Mapping[str, TableBinding]:
    """The table map with each variant restricted to its own derived columns.

    A binding the derivation does not scope keeps its literal ``columns`` (None,
    or the hand-written ``_C08_06_DATA_POINT_COLUMNS``)."""
    variant_columns = derive_variant_columns(framework)
    return {
        table: (
            binding
            if table not in variant_columns
            else replace(binding, columns=variant_columns[table])
        )
        for table, binding in _base_bindings(framework).items()
    }
