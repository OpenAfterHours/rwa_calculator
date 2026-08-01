"""
Scope resolution — publisher table/sheet coordinates onto our generated frames.

Pipeline position:
    COREPTemplateBundle  ->  build_template_index  ->  TemplateIndex
    ValidationRule + TemplateIndex  ->  expand_rule  ->  [Coordinate] + [Skip]

Key responsibilities:
- Bind a publisher TABLE code (``C 07.00.a`` / ``OF08.01.01.01``) to the bundle
  member that carries it, and answer "is this template emitted at all?".
- Map the publisher SHEET (z-axis) codes — EBA ``s0001``..``s0017``, BoE
  ``z:0001``.. — onto our per-exposure-class sheet keys, through an explicit,
  cited table. Where a code's meaning could not be established the map holds
  nothing and the rule is skipped: a wrong sheet mapping silently produces wrong
  findings, which is far worse than a skip.
- Expand a rule into the concrete (sheet, row, column) coordinates it must be
  evaluated at, and record — never collapse — every coordinate that could not be
  formed. "Row not emitted" is NOT "row emitted as zero".

Why the sheet map is the hard part: the supervisory z-axis is a positional index
into the regulation's exposure-class list, while our bundles key sheets by class
NAME. Our classes are also a COARSER partition than the DPM's in places (one
``retail_mortgage`` sheet against the DPM's SME / non-SME pair), so a scoped
subset of z-codes is only safe to evaluate when the set is CLOSED under the
mapping — see ``resolve_sheet_codes``.

References:
- CRR Art. 112(1)(a)-(q) — the SA exposure classes indexed by the C 07.00 z-axis
- CRR Art. 147(2) / COREP Annex II §3.3.2 — the CR IRB sub-exposure-class list
  indexed by the C 08.01 z-axis
- PRA PS1/26 Annex II (OF 07.00 / OF 08.01 / OF 09.01 / OF 09.02 instructions)
- docs/reference/validation-rules/index.md — the rule grammar
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field, replace
from functools import cache
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_calc.reporting.validations.rules import (
    FRAMEWORK_BASEL_3_1,
    SCOPE_ALL,
    SCOPE_LIST,
    RuleScope,
    load_rules,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
    from rwa_calc.reporting.validations.rules import ValidationRule

logger = logging.getLogger(__name__)

# =============================================================================
# Skip reasons — every one is a NOT_EVALUATED outcome, never a break
# =============================================================================

SKIP_TABLE_NOT_EMITTED: Final = "table_not_emitted"
SKIP_SHEET_NOT_EMITTED: Final = "sheet_not_emitted"
SKIP_SHEET_INDEX_MAP_UNKNOWN: Final = "sheet_index_map_unknown"
SKIP_SHEET_SCOPE_NOT_CLOSED: Final = "sheet_scope_not_closed"
SKIP_ROW_NOT_EMITTED: Final = "row_not_emitted"
SKIP_COLUMN_NOT_EMITTED: Final = "column_not_emitted"
SKIP_NO_COORDINATES: Final = "no_coordinates"
SKIP_PREREQUISITE_TABLE_ABSENT: Final = "prerequisite_table_absent"

# =============================================================================
# The sheet (z-axis) index map
# =============================================================================


@dataclass(frozen=True)
class SheetCode:
    """One publisher sheet code and what it addresses in our bundles.

    Attributes:
        code: The publisher's z-axis id, e.g. ``"0008"``.
        label: The regulatory exposure class the code indexes.
        bundle_keys: Our sheet keys that carry those exposures. EMPTY means the
            code is understood but has no analogue in this project's output
            (the ``Total`` sheet, or a class we do not model) — a skip, never a
            zero. A code ABSENT from the map is one whose meaning could not be
            established; it is reported as ``sheet_index_map_unknown``.
        source: How the entry was established.
    """

    code: str
    label: str
    bundle_keys: tuple[str, ...]
    source: str


# ── C 07.00 (CRR / EBA) ──────────────────────────────────────────────────────
# The z-axis is Article 112(1)(a)-(q) in order, prefixed by a Total sheet, with
# (m) "securitisation positions" omitted (COREP Annex II §3.2.2 para 48(a) puts
# it out of scope of CR SA). 1 + 16 = the 17 codes the rule set actually uses.
#
# Corroborated three independent ways against the live rule set:
#   * v7477_m forces row 0040 ("of which: Secured by mortgages on immovable
#     property", Annex II: "Only reported in exposure class 'Secured by
#     mortgages on immovable property'") to be empty on every sheet EXCEPT 0001
#     and 0010  ->  s0010 = Article 112(1)(i).
#   * v4721_m / v4728_m force row 0015 (Annex II: "shall only be reported in
#     exposure classes 'Items associated with a particular high risk' and
#     'Equity exposures'") empty everywhere except 0001, 0012 and 0016
#     ->  s0012 = 112(1)(k), s0016 = 112(1)(p), s0001 = Total.
#   * v09743_m applies the CIU look-through/mandate/fall-back decomposition
#     (rows 0281-0283) on sheet 0015 only  ->  s0015 = 112(1)(o).
_C07_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode("0001", "Total (all SA exposure classes)", (), "COREP Annex II C 07.00; v4728_m"),
    SheetCode(
        "0002",
        "Art. 112(1)(a) central governments or central banks",
        ("central_govt_central_bank",),
        "CRR Art. 112(1)(a); v0383_m family ordering",
    ),
    SheetCode(
        "0003",
        "Art. 112(1)(b) regional governments or local authorities",
        ("rgla",),
        "CRR Art. 112(1)(b)",
    ),
    SheetCode("0004", "Art. 112(1)(c) public sector entities", ("pse",), "CRR Art. 112(1)(c)"),
    SheetCode(
        "0005", "Art. 112(1)(d) multilateral development banks", ("mdb",), "CRR Art. 112(1)(d)"
    ),
    SheetCode(
        "0006",
        "Art. 112(1)(e) international organisations",
        ("international_organisation",),
        "CRR Art. 112(1)(e)",
    ),
    SheetCode("0007", "Art. 112(1)(f) institutions", ("institution",), "CRR Art. 112(1)(f)"),
    SheetCode(
        "0008",
        "Art. 112(1)(g) corporates (incl. SME of-which)",
        ("corporate", "corporate_sme"),
        "CRR Art. 112(1)(g); v4240_i vs C 02.00 r0130",
    ),
    SheetCode(
        "0009",
        "Art. 112(1)(h) retail (incl. QRRE of-which)",
        ("retail_other", "retail_qrre"),
        "CRR Art. 112(1)(h); v4241_i vs C 02.00 r0140",
    ),
    # All THREE real-estate class keys, not just the retail one. Art. 112(1)(i)
    # is defined by the security, so it holds residential AND commercial: row
    # 0040 is an "of which: ... Residential property" of this sheet, which only
    # parses if the sheet is the wider set. ``commercial_mortgage`` /
    # ``residential_mortgage`` reach it from the applied-class overlay and from
    # the SA loan-splitter's secured legs respectively.
    SheetCode(
        "0010",
        "Art. 112(1)(i) secured by mortgages on immovable property",
        ("retail_mortgage", "residential_mortgage", "commercial_mortgage"),
        "COREP Annex II C 07.00 row 0040 + para 62 rank 6; v7477_m",
    ),
    SheetCode("0011", "Art. 112(1)(j) exposures in default", ("defaulted",), "CRR Art. 112(1)(j)"),
    SheetCode(
        "0012",
        "Art. 112(1)(k) items associated with particularly high risk",
        (),
        "COREP Annex II C 07.00 row 0015; v4728_m",
    ),
    SheetCode("0013", "Art. 112(1)(l) covered bonds", ("covered_bond",), "CRR Art. 112(1)(l)"),
    SheetCode(
        "0014",
        "Art. 112(1)(n) institutions/corporates with a short-term credit assessment",
        (),
        "CRR Art. 112(1)(n)",
    ),
    SheetCode(
        "0015",
        "Art. 112(1)(o) collective investment undertakings",
        (),
        "COREP Annex II C 07.00 rows 0281-0283; v09743_m",
    ),
    SheetCode(
        "0016",
        "Art. 112(1)(p) equity exposures",
        ("equity",),
        "COREP Annex II C 07.00 row 0015; v4728_m",
    ),
    SheetCode("0017", "Art. 112(1)(q) other items", ("other",), "CRR Art. 112(1)(q)"),
)

# ── OF 07.00 (Basel 3.1 / BoE) ───────────────────────────────────────────────
# PS1/26 keeps the Article 112(1) letters, so the z-axis keeps the C 07.00
# positions; class (n) is withdrawn, which is exactly why no BoE scope in the
# extract ever lists z:0014. Read off the PS1/26 Annex II OF 09.01 row list
# (rows 0010..0120 = (a)..(l), then 0140 = (o) — no row for (n) — 0150 = (p),
# 0160 = (q), 0170 = Total) and confirmed cell-for-cell by the OF 09.01 <-> OF
# 07.00 rule family (boe_b0216: OF09.01 r0050 "International organisations" =
# OF07.00 z:0006; boe_b0985/b0987: OF09.01 r0093/r0094 real-estate of-whiches =
# OF07.00 z:0010).
_OF07_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode("0001", "Total (all SA exposure classes)", (), "PS1/26 Annex II OF 09.01 row 0170"),
    SheetCode(
        "0002",
        "Art. 112(1)(a) central governments or central banks",
        ("central_govt_central_bank",),
        "PS1/26 Annex II OF 09.01 row 0010; boe_b0190",
    ),
    SheetCode(
        "0003",
        "Art. 112(1)(b) regional governments or local authorities",
        ("rgla",),
        "PS1/26 Annex II OF 09.01 row 0020",
    ),
    SheetCode(
        "0004",
        "Art. 112(1)(c) public sector entities",
        ("pse",),
        "PS1/26 Annex II OF 09.01 row 0030",
    ),
    SheetCode(
        "0005",
        "Art. 112(1)(d) multilateral development banks",
        ("mdb",),
        "PS1/26 Annex II OF 09.01 row 0040",
    ),
    SheetCode(
        "0006",
        "Art. 112(1)(e) international organisations",
        ("international_organisation",),
        "PS1/26 Annex II OF 09.01 row 0050; boe_b0216",
    ),
    SheetCode(
        "0007", "Art. 112(1)(f) institutions", ("institution",), "PS1/26 Annex II OF 09.01 row 0060"
    ),
    SheetCode(
        "0008",
        "Art. 112(1)(g) corporates (incl. SME of-which)",
        ("corporate", "corporate_sme"),
        "PS1/26 Annex II OF 09.01 row 0070; boe_b0973",
    ),
    SheetCode(
        "0009",
        "Art. 112(1)(h) retail (incl. QRRE of-which)",
        ("retail_other", "retail_qrre"),
        "PS1/26 Annex II OF 09.01 row 0080",
    ),
    # Under PS1/26 real estate is a STANDALONE class (Art. 112(2) Table A2 row
    # (7), criteria "Articles 124 to 124L"), outranking retail (14) and
    # corporates (15) — so all three real-estate class keys belong here, exactly
    # as they already key OF 09.01 row 0090 (``corep/c09.py::_C09_01_RE_CLASSES``).
    SheetCode(
        "0010",
        "Art. 112(1)(i) real estate exposures",
        ("retail_mortgage", "residential_mortgage", "commercial_mortgage"),
        "PS1/26 Art. 112(2) Table A2 row (7); Annex II OF 09.01 row 0090; boe_b0985/b0987",
    ),
    SheetCode(
        "0011",
        "Art. 112(1)(j) exposures in default",
        ("defaulted",),
        "PS1/26 Annex II OF 09.01 row 0100",
    ),
    SheetCode(
        "0012",
        "Art. 112(1)(k) exposures associated with particularly high risk",
        (),
        "PS1/26 Annex II OF 09.01 row 0110",
    ),
    SheetCode(
        "0013",
        "Art. 112(1)(l) eligible covered bonds",
        ("covered_bond",),
        "PS1/26 Annex II OF 09.01 row 0120",
    ),
    SheetCode(
        "0015",
        "Art. 112(1)(o) collective investment undertakings",
        (),
        "PS1/26 Annex II OF 09.01 row 0140",
    ),
    SheetCode(
        "0016",
        "Art. 112(1)(p) subordinated debt, equity and other own funds instruments",
        ("equity",),
        "PS1/26 Annex II OF 09.01 row 0150",
    ),
    SheetCode(
        "0017", "Art. 112(1)(q) other items", ("other",), "PS1/26 Annex II OF 09.01 row 0160"
    ),
)

# ── C 08.01 / C 08.02 / C 08.03 / C 08.05 (CRR / EBA) ────────────────────────
# COREP Annex II §3.3.2 lists the CR IRB reporting classes as Total, then
# Art. 147(2)(a)-(d) split into 10 sub-classes. The z-axis pairs each non-retail
# class (F-IRB, A-IRB) and gives retail — where own estimates are mandatory —
# one code each: 6 pairs + 5 retail = the 17 codes in use.
#
# Read off the C 09.02 <-> C 08.01 rule family, which states the identity for
# every C 09.02 exposure-class row (v0415_m r0010 = s0003-0004; v0420_m r0020 =
# s0005-0006; v0425_m r0030 = s0007-0012; v0430_m r0042 "of which specialised
# lending" <= s0009-0010; v0435_m r0050 "of which SME" = s0007-0008; v0440_m
# r0060 retail = s0013-0017; v0450_m/v0455_m r0080/r0090 = s0013/s0014;
# v0460_m r0100 QRRE = s0015; v0470_m/v0475_m r0120/r0130 = s0016/s0017).
# Independently corroborated by v10670_m, which imposes the Art. 160(1) 0.03%
# PD floor on s0005-0017 but not s0001-0004 — sovereign exposures are the one
# IRB class without it.
_C08_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode("0001", "Total, F-IRB", (), "COREP Annex II §3.3.2 item 1"),
    SheetCode("0002", "Total, A-IRB", (), "COREP Annex II §3.3.2 item 1"),
    SheetCode(
        "0003",
        "Art. 147(2)(a) central banks and central governments, F-IRB",
        ("central_govt_central_bank",),
        "v0415_m (C 09.02 row 0010)",
    ),
    SheetCode(
        "0004",
        "Art. 147(2)(a) central banks and central governments, A-IRB",
        ("central_govt_central_bank",),
        "v0415_m (C 09.02 row 0010)",
    ),
    SheetCode(
        "0005", "Art. 147(2)(b) institutions, F-IRB", ("institution",), "v0420_m (C 09.02 row 0020)"
    ),
    SheetCode(
        "0006", "Art. 147(2)(b) institutions, A-IRB", ("institution",), "v0420_m (C 09.02 row 0020)"
    ),
    SheetCode(
        "0007",
        "Art. 147(2)(c) corporates - SME, F-IRB",
        ("corporate_sme",),
        "v0435_m (C 09.02 row 0050)",
    ),
    SheetCode(
        "0008",
        "Art. 147(2)(c) corporates - SME, A-IRB",
        ("corporate_sme",),
        "v0435_m (C 09.02 row 0050)",
    ),
    SheetCode(
        "0009",
        "Art. 147(8) corporates - specialised lending, F-IRB",
        ("specialised_lending",),
        "v0430_m (C 09.02 row 0042)",
    ),
    SheetCode(
        "0010",
        "Art. 147(8) corporates - specialised lending, A-IRB",
        ("specialised_lending",),
        "v0430_m (C 09.02 row 0042)",
    ),
    SheetCode(
        "0011",
        "Art. 147(2)(c) corporates - other, F-IRB",
        ("corporate",),
        "v0425_m less v0430_m/v0435_m",
    ),
    SheetCode(
        "0012",
        "Art. 147(2)(c) corporates - other, A-IRB",
        ("corporate",),
        "v0425_m less v0430_m/v0435_m",
    ),
    SheetCode(
        "0013",
        "Art. 147(2)(d) retail - secured by immovable property, SME",
        ("retail_mortgage",),
        "v0450_m (C 09.02 row 0080)",
    ),
    SheetCode(
        "0014",
        "Art. 147(2)(d) retail - secured by immovable property, non-SME",
        ("retail_mortgage",),
        "v0455_m (C 09.02 row 0090)",
    ),
    SheetCode(
        "0015",
        "Art. 154(4) retail - qualifying revolving",
        ("retail_qrre",),
        "v0460_m (C 09.02 row 0100)",
    ),
    SheetCode(
        "0016",
        "Art. 147(2)(d) retail - other, SME",
        ("retail_other",),
        "v0470_m (C 09.02 row 0120)",
    ),
    SheetCode(
        "0017",
        "Art. 147(2)(d) retail - other, non-SME",
        ("retail_other",),
        "v0475_m (C 09.02 row 0130)",
    ),
)

# ── OF 08.01 / OF 08.02 / OF 08.03 (Basel 3.1 / BoE) ─────────────────────────
# A DIFFERENT axis from the CRR one: PS1/26 withdraws the IRB approach for
# sovereigns (the PS1/26 Annex II OF 09.02 row list starts at 0020 Institutions,
# and boe_b0786 states Total = Institutions + Corporates + Retail with no
# sovereign term) and re-cuts corporates and retail. Read off the OF 09.02 <->
# OF 08.01 rule family (boe_b0287 and siblings) against the PS1/26 Annex II
# OF 09.02 row instructions.
#
# Only 17 codes ever appear in the extract — 0001, 0002, 0006, 0009-0012 and
# 0015-0024 — so 0003-0005, 0007, 0008, 0013 and 0014 are DELIBERATELY absent
# here rather than mapped on a guess; a reference to one of them is reported as
# ``sheet_index_map_unknown``.
_OF08_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode(
        "0001", "Total (IRB), first approach dimension", (), "PS1/26 Annex II OF 09.02 row 0150"
    ),
    SheetCode(
        "0002", "Total (IRB), second approach dimension", (), "PS1/26 Annex II OF 09.02 row 0150"
    ),
    SheetCode(
        "0006", "Art. 147(2)(b) institutions", ("institution",), "PS1/26 Annex II OF 09.02 row 0020"
    ),
    SheetCode(
        "0009",
        "Art. 147(2)(c)(i) specialised lending (excl. slotting), 1st approach",
        ("specialised_lending",),
        "PS1/26 Annex II OF 09.02 row 0042; boe_b0287",
    ),
    SheetCode(
        "0010",
        "Art. 147(2)(c)(i) specialised lending (excl. slotting), 2nd approach",
        ("specialised_lending",),
        "PS1/26 Annex II OF 09.02 row 0042; boe_b0287",
    ),
    SheetCode(
        "0011",
        "Art. 147(4E) other general corporates non-SME, 1st approach",
        ("corporate",),
        "PS1/26 Annex II OF 09.02 row 0055",
    ),
    SheetCode(
        "0012",
        "Art. 147(4E) other general corporates non-SME, 2nd approach",
        ("corporate",),
        "PS1/26 Annex II OF 09.02 row 0055",
    ),
    SheetCode(
        "0015",
        "Art. 147(2D) retail - qualifying revolving",
        ("retail_qrre",),
        "PS1/26 Annex II OF 09.02 row 0100",
    ),
    SheetCode(
        "0016",
        "Art. 147(5C) retail - other SME",
        ("retail_other",),
        "PS1/26 Annex II OF 09.02 row 0120",
    ),
    SheetCode(
        "0017",
        "Art. 147(5C) retail - other non-SME",
        ("retail_other",),
        "PS1/26 Annex II OF 09.02 row 0130",
    ),
    SheetCode(
        "0018",
        "Art. 147(2)(d)(ii) retail - secured by commercial immovable property, SME",
        ("retail_mortgage",),
        "PS1/26 Annex II OF 09.02 row 0073",
    ),
    SheetCode(
        "0019",
        "Art. 147(2)(d)(ii) retail - secured by commercial immovable property, non-SME",
        ("retail_mortgage",),
        "PS1/26 Annex II OF 09.02 row 0074",
    ),
    SheetCode(
        "0020",
        "Art. 147(2)(d)(ii) retail - secured by residential immovable property, SME",
        ("retail_mortgage",),
        "PS1/26 Annex II OF 09.02 row 0071",
    ),
    SheetCode(
        "0021",
        "Art. 147(2)(d)(ii) retail - secured by residential immovable property, non-SME",
        ("retail_mortgage",),
        "PS1/26 Annex II OF 09.02 row 0072",
    ),
    SheetCode(
        "0022",
        "Art. 147(4C) financial corporates and large corporates",
        ("corporate",),
        "PS1/26 Annex II OF 09.02 row 0048",
    ),
    SheetCode(
        "0023",
        "Art. 147(4E)(c) other general corporates SME, 1st approach",
        ("corporate_sme",),
        "PS1/26 Annex II OF 09.02 row 0050",
    ),
    SheetCode(
        "0024",
        "Art. 147(4E)(c) other general corporates SME, 2nd approach",
        ("corporate_sme",),
        "PS1/26 Annex II OF 09.02 row 0050",
    ),
)

#: Named sheet-index maps. A template whose sheet dict is keyed by something the
#: publisher does not index positionally (country code, specialised-lending type,
#: netting set) has NO map: it can only be iterated wholesale via an ``(All)``
#: scope, never addressed by a specific code.
SHEET_INDEX_MAPS: Final[Mapping[str, Mapping[str, SheetCode]]] = {
    "c07": {entry.code: entry for entry in _C07_SHEETS},
    "of07": {entry.code: entry for entry in _OF07_SHEETS},
    "c08": {entry.code: entry for entry in _C08_SHEETS},
    "of08": {entry.code: entry for entry in _OF08_SHEETS},
}


# =============================================================================
# Table bindings — publisher table code -> bundle member
# =============================================================================


@dataclass(frozen=True)
class TableBinding:
    """Binds one publisher table code to the bundle member that carries it.

    ``sheet_map`` names the entry of ``SHEET_INDEX_MAPS`` that indexes the
    member's sheet dict, or is ``None`` when the dict is keyed by something the
    publisher never addresses positionally.

    ``columns`` restricts the binding to one DPM variant's own columns. Several
    table codes bind to the SAME frame — our single C 09.01 carries the union of
    ``C 09.01.a`` and ``C 09.01.b`` — and without this a rule scoped
    ``columns: (All)`` on one variant would iterate the other variant's columns
    and report breaks against cells it does not govern. ``None`` means "the whole
    frame", which is correct for a code that is the sole binding for its member,
    and is also the recorded fallback where the variants do NOT split by column
    (see ``derive_variant_columns``).
    """

    attribute: str
    per_sheet: bool
    sheet_map: str | None = None
    columns: frozenset[str] | None = None

    def owns_column(self, column: str) -> bool:
        """Whether ``column`` belongs to this variant."""
        return self.columns is None or column in self.columns


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
    "C 08.06": TableBinding("c08_06", per_sheet=True),
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
# The generated-frame index
# =============================================================================

#: Sentinel sheet key for a single-frame (no z-axis) template.
SINGLE_SHEET: Final = "__single__"


@dataclass(frozen=True)
class CellValue:
    """One resolved cell: present with a value, present but null, or absent.

    ``absent`` is emphatically NOT ``0.0``. A row, column or sheet our estate
    never emitted carries no assertion at all; collapsing it to zero manufactures
    a figure and turns a structural gap into an arithmetic break.
    """

    present: bool
    value: float | None

    @property
    def is_null(self) -> bool:
        """Present in the frame but carrying no value."""
        return self.present and self.value is None


ABSENT_CELL: Final = CellValue(present=False, value=None)


@dataclass(frozen=True)
class TemplateIndex:
    """Every generated frame, addressable by publisher table code.

    ``frames`` maps a bundle attribute name to ``{sheet key: DataFrame}``, using
    ``SINGLE_SHEET`` for templates with no z-axis. A table code with no entry
    (or an empty one) was NOT produced by this run.
    """

    framework: str
    frames: Mapping[str, Mapping[str, pl.DataFrame]]
    bindings: Mapping[str, TableBinding] = field(default_factory=dict)
    #: Lazily-built ``{row_ref: {column: value}}`` per (attribute, sheet). A rule
    #: estate reads the same handful of frames tens of thousands of times — an
    #: aggregate over an unbound axis touches every row of a template per
    #: coordinate — and a Polars ``filter`` per cell makes that quadratic. The
    #: dict is a read-through cache of frames that never change during a run, so
    #: it cannot drift from ``frames``; it is excluded from equality and repr so
    #: the dataclass still compares by its declared content.
    _cells: dict[tuple[str, str], dict[str, dict[str, float | None]]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def binding(self, table: str) -> TableBinding | None:
        """The binding for a publisher table code, or ``None`` if unbindable."""
        return self.bindings.get(table)

    def is_emitted(self, table: str) -> bool:
        """Whether this run produced any frame for ``table``."""
        binding = self.binding(table)
        return bool(binding and self.frames.get(binding.attribute))

    def sheet_keys(self, table: str) -> tuple[str, ...]:
        """Every sheet key emitted for ``table`` (``(SINGLE_SHEET,)`` if flat)."""
        binding = self.binding(table)
        if binding is None:
            return ()
        return tuple(self.frames.get(binding.attribute, {}))

    def frame(self, table: str, sheet: str) -> pl.DataFrame | None:
        """The DataFrame at ``(table, sheet)``, or ``None`` when not emitted."""
        binding = self.binding(table)
        if binding is None:
            return None
        return self.frames.get(binding.attribute, {}).get(sheet)

    def row_refs(self, table: str, sheet: str) -> tuple[str, ...]:
        """Row references present on a frame, in emitted order."""
        frame = self.frame(table, sheet)
        if frame is None or "row_ref" not in frame.columns:
            return ()
        return tuple(str(value) for value in frame["row_ref"].to_list())

    def column_refs(self, table: str, sheet: str) -> tuple[str, ...]:
        """Numeric column references this table code governs on a frame.

        Restricted to the variant's own columns when the binding carries a set,
        so a ``columns: (All)`` rule iterates the columns of the table it is
        scoped to rather than everything its sibling variants share the frame
        with.
        """
        frame = self.frame(table, sheet)
        if frame is None:
            return ()
        binding = self.binding(table)
        return tuple(
            name
            for name in frame.columns
            if name not in _NON_DATA_COLUMNS and (binding is None or binding.owns_column(name))
        )

    def cell(self, table: str, sheet: str, row: str, column: str) -> CellValue:
        """Read one cell, distinguishing "absent" from "present but null"."""
        binding = self.binding(table)
        if binding is None or not binding.owns_column(column):
            return ABSENT_CELL
        by_row = self._cell_map(binding.attribute, sheet)
        cells = by_row.get(row)
        if cells is None or column not in cells:
            return ABSENT_CELL
        value = cells[column]
        if value is None:
            return CellValue(present=True, value=None)
        return CellValue(present=True, value=value)

    def _cell_map(self, attribute: str, sheet: str) -> dict[str, dict[str, float | None]]:
        """Materialise (once) the ``{row_ref: {column: value}}`` map for a frame.

        Only numeric columns are kept, and a non-numeric cell is stored as
        ``None`` — "present but not a figure" reads the same as "present but
        null", and neither may become a zero.
        """
        key = (attribute, sheet)
        cached = self._cells.get(key)
        if cached is not None:
            return cached

        by_row: dict[str, dict[str, float | None]] = {}
        frame = self.frames.get(attribute, {}).get(sheet)
        if frame is not None and "row_ref" in frame.columns:
            columns = [name for name in frame.columns if name not in _NON_DATA_COLUMNS]
            for record in frame.select("row_ref", *columns).iter_rows(named=True):
                by_row[str(record["row_ref"])] = {name: _as_float(record[name]) for name in columns}
        self._cells[key] = by_row
        return by_row


#: Frame columns that are labels, not reportable cells.
_NON_DATA_COLUMNS: Final[frozenset[str]] = frozenset({"row_ref", "row_name", "row_label", "label"})

#: ``{C 08.01.a, r0070, c0020}`` / ``{t: OF08.01.01.01, r: 0070, c: 0020}`` — a
#: reference whose FIRST part names a table, so its columns are attributable to
#: that table rather than to the rule's home.
_QUALIFIED_REF = re.compile(r"\{\s*(?:t:\s*)?([A-Za-z][A-Za-z0-9. ]*?)\s*,([^{}]*)\}")
#: A column id in either grammar (``c0020`` / ``c: 0020``).
_COLUMN_ID = re.compile(r"\bc[:\s]*(\d{3,5})\b")


@cache
def derive_variant_columns(framework: str) -> Mapping[str, frozenset[str]]:
    """Derive each DPM variant's own column set FROM THE RULE EXTRACT.

    Several publisher table codes bind to one of our frames (``C 09.01.a`` and
    ``C 09.01.b`` are column partitions of one CR GB 1 template, and our frame
    carries the union). A rule scoped ``columns: (All)`` on one variant must
    iterate only that variant's columns; without this it evaluates against its
    sibling's and reports breaks on cells it does not govern.

    The sets are derived, never hand-written: a variant owns every column a rule
    attributes to it explicitly — a reference qualified with the table name, or
    any column reference / column scope on a rule naming that table alone. A
    hand-maintained table would rot at the next taxonomy refresh, exactly as a
    pinned must-run rule-id list would.

    A group is scoped ONLY when its variants' derived sets are non-empty and
    PAIRWISE DISJOINT — the signature of a genuine column partition. Where they
    overlap, the variants are split by something else and a column set is the
    wrong model, so the group is left unscoped and behaves as before. Today that
    correctly scopes ``C 09.01``, ``C 08.01``, ``C 34.01``, ``C 34.08``,
    ``OF08.01``, ``OF02.01`` and ``C34.08.01``, and correctly declines the
    ``C 07.00`` / ``OF07.00`` family, whose ``.c`` / ``.d`` variants are the
    memorandum ROWS (0290-0320) over the same column space as ``.a``.

    Returns:
        ``{table code: columns}`` for the codes that could be scoped. A code
        absent from the mapping is deliberately unrestricted.
    """
    attributed = _attributed_columns(framework)
    by_attribute: dict[str, list[str]] = {}
    for table, binding in _base_bindings(framework).items():
        by_attribute.setdefault(binding.attribute, []).append(table)

    scoped: dict[str, frozenset[str]] = {}
    for tables in by_attribute.values():
        if len(tables) < 2:
            continue  # sole binding for its frame: the frame IS that table
        sets = {table: attributed.get(table, frozenset()) for table in tables}
        if not all(sets.values()):
            continue  # a variant we have no column evidence for
        if any(sets[a] & sets[b] for a, b in itertools.combinations(sorted(sets), 2)):
            continue  # not a column partition — see the docstring
        scoped.update(sets)
    return scoped


def _attributed_columns(framework: str) -> Mapping[str, frozenset[str]]:
    """Columns each table code is explicitly credited with by the enforced rules.

    Only ENFORCED rules contribute: a withdrawn rule may reference a retired
    column, which would widen a variant's set and quietly weaken the partition.
    """
    collected: dict[str, set[str]] = {}
    for rule in load_rules(framework).enforced:
        expression = rule.expression or ""
        for table, body in _QUALIFIED_REF.findall(expression):
            if table in rule.tables:
                collected.setdefault(table, set()).update(_COLUMN_ID.findall(body))
        if len(rule.tables) != 1:
            continue  # an unqualified reference on a multi-table rule is ambiguous
        table = rule.tables[0]
        unqualified = _QUALIFIED_REF.sub(" ", expression)
        collected.setdefault(table, set()).update(_COLUMN_ID.findall(unqualified))
        columns = rule.scope_for(table).columns
        if columns.kind == SCOPE_LIST:
            collected[table].update(columns.ids)
    return {table: frozenset(values) for table, values in collected.items()}


def _base_bindings(framework: str) -> Mapping[str, TableBinding]:
    """The literal table map for a framework, before column scoping."""
    return _B31_TABLES if framework == FRAMEWORK_BASEL_3_1 else _CRR_TABLES


@cache
def _bindings_for(framework: str) -> Mapping[str, TableBinding]:
    """The table map with each variant restricted to its own derived columns."""
    variant_columns = derive_variant_columns(framework)
    return {
        table: (
            binding
            if table not in variant_columns
            else replace(binding, columns=variant_columns[table])
        )
        for table, binding in _base_bindings(framework).items()
    }


def _as_float(value: object) -> float | None:
    """Coerce a cell to a float, or ``None`` when it carries no figure.

    A template cell can legitimately hold a non-numeric label (a PD band such as
    ``"0.75% - 2.50%"`` on the C 08.02 row axis). Such a cell is not a figure, so
    it reads as unreported rather than being forced to a number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


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
    return TemplateIndex(framework=framework, frames=frames, bindings=bindings)


# =============================================================================
# Rule expansion
# =============================================================================


@dataclass(frozen=True)
class Coordinate:
    """One concrete cell address a rule is evaluated at.

    ``row`` / ``column`` are ``None`` when the rule's formula addresses that axis
    itself (every reference is fully qualified), so there is nothing to iterate.

    ``sheet_is_representative`` marks a sheet the rule does not actually address:
    when every reference names its own sheet, the axis is collapsed to one
    arbitrary emitted sheet so the grid is not multiplied. Such a sheet must not
    be shown in a finding — quoting ``[GB]`` on a cross-table identity that is
    not GB-specific would send a reader to the wrong place.
    """

    table: str
    sheet: str
    row: str | None
    column: str | None
    sheet_is_representative: bool = False

    def describe(self) -> str:
        """Compact human address, e.g. ``C 07.00.a[corporate][r0010][c0090]``."""
        hide_sheet = self.sheet == SINGLE_SHEET or self.sheet_is_representative
        sheet = "" if hide_sheet else f"[{self.sheet}]"
        row = f"[r{self.row}]" if self.row else ""
        column = f"[c{self.column}]" if self.column else ""
        return f"{self.table}{sheet}{row}{column}"


@dataclass(frozen=True)
class SheetResolution:
    """The outcome of mapping a set of publisher sheet codes onto our sheets."""

    sheets: tuple[str, ...]
    skip_reason: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Expansion:
    """A rule's concrete coordinates, plus why anything was left out."""

    home_table: str | None
    coordinates: tuple[Coordinate, ...]
    skip_reason: str | None = None
    detail: str = ""


def expand_rule(
    rule: ValidationRule,
    index: TemplateIndex,
    *,
    needs_row_axis: bool,
    needs_column_axis: bool,
    needs_sheet_axis: bool = True,
) -> Expansion:
    """Expand a rule into the coordinates it must be evaluated at.

    The publisher's doctrine is that the SCOPED axis is the loop and the formula
    addresses the other one. That generalises to all three axes: an axis is
    iterated when the rule scopes it, or when the formula carries at least one
    reference that does not qualify it (the ``needs_*_axis`` flags, derived from
    the parsed expression). Otherwise the axis collapses to a single value.

    Args:
        rule: The rule to expand.
        index: The generated frames.
        needs_row_axis: The expression has a reference with no explicit row.
        needs_column_axis: The expression has a reference with no explicit column.
        needs_sheet_axis: The expression has a reference that names neither a
            sheet nor a dimensional filter selecting one. When False the sheet
            axis collapses to one representative sheet: every reference resolves
            its own, so iterating would re-evaluate the identical comparison once
            per sheet and count each verdict several times.

    Returns:
        An ``Expansion``; ``skip_reason`` is set (and ``coordinates`` empty) when
        the rule cannot be placed on this run's output at all.
    """
    missing_prerequisite = next(
        (table for table in rule.prerequisites if not index.is_emitted(table)), None
    )
    if missing_prerequisite is not None:
        return Expansion(None, (), SKIP_PREREQUISITE_TABLE_ABSENT, missing_prerequisite)

    home = next((table for table in rule.tables if index.is_emitted(table)), None)
    if home is None:
        return Expansion(None, (), SKIP_TABLE_NOT_EMITTED, ", ".join(rule.tables))

    scope = rule.scope_for(home)
    binding = index.binding(home)
    assert binding is not None  # is_emitted() already proved the binding resolves

    resolution = _resolve_sheet_axis(rule, home, index, binding)
    if resolution.skip_reason is not None:
        return Expansion(home, (), resolution.skip_reason, resolution.detail)
    # Every reference names its own sheet, so the axis carries no information:
    # keep one real key (references still fall back to it) but mark it so no
    # finding quotes a sheet the rule does not address.
    representative = not needs_sheet_axis and len(resolution.sheets) > 1
    if representative:
        resolution = SheetResolution(resolution.sheets[:1])

    coordinates: list[Coordinate] = []
    dropped_rows = scope.rows.kind == SCOPE_LIST
    dropped_columns = scope.columns.kind == SCOPE_LIST
    for sheet in resolution.sheets:
        rows = _axis_values(scope.rows, index.row_refs(home, sheet), iterate=needs_row_axis)
        columns = _axis_values(
            scope.columns, index.column_refs(home, sheet), iterate=needs_column_axis
        )
        dropped_rows = dropped_rows and not rows
        dropped_columns = dropped_columns and not columns
        coordinates.extend(
            Coordinate(home, sheet, row, column, sheet_is_representative=representative)
            for row in rows
            for column in columns
        )

    if coordinates:
        return Expansion(home, tuple(coordinates))
    # Name the axis that emptied the grid: a scoped row / column this estate
    # never emits is a structural gap, and saying which one is the difference
    # between a triageable skip and an opaque one.
    if dropped_rows:
        return Expansion(home, (), SKIP_ROW_NOT_EMITTED, ", ".join(scope.rows.ids))
    if dropped_columns:
        return Expansion(home, (), SKIP_COLUMN_NOT_EMITTED, ", ".join(scope.columns.ids))
    return Expansion(home, (), SKIP_NO_COORDINATES, "scope resolved to no emitted cell")


def resolve_sheet_codes(
    codes: Iterable[str], sheet_map: Mapping[str, SheetCode], emitted: Iterable[str]
) -> SheetResolution:
    """Map publisher sheet codes onto our emitted sheet keys.

    Three ways this refuses, each a skip rather than a break:

    - a code absent from the map -> ``sheet_index_map_unknown``;
    - a code whose class this estate does not produce -> ``sheet_not_emitted``;
    - a code set that is not CLOSED under the mapping -> ``sheet_scope_not_closed``.

    Closure is the load-bearing test. Our sheets are in places a COARSER
    partition than the publisher's z-axis (one ``retail_mortgage`` sheet against
    the DPM's SME / non-SME pair), so a sheet we would evaluate may carry
    exposures the rule was never scoped to. The set is safe only when every code
    mapping into the selected sheets is itself in the requested set.
    """
    requested = tuple(codes)
    unknown = [code for code in requested if code not in sheet_map]
    if unknown:
        return SheetResolution((), SKIP_SHEET_INDEX_MAP_UNKNOWN, ", ".join(sorted(set(unknown))))

    selected: list[str] = []
    for code in requested:
        for key in sheet_map[code].bundle_keys:
            if key not in selected:
                selected.append(key)
    if not selected:
        labels = ", ".join(sheet_map[code].label for code in requested)
        return SheetResolution((), SKIP_SHEET_NOT_EMITTED, labels)

    requested_set = set(requested)
    leaking = sorted(
        code
        for code, entry in sheet_map.items()
        if code not in requested_set and set(entry.bundle_keys) & set(selected)
    )
    if leaking:
        return SheetResolution(
            (),
            SKIP_SHEET_SCOPE_NOT_CLOSED,
            f"our sheet(s) {', '.join(selected)} also carry sheet code(s) {', '.join(leaking)}",
        )

    emitted_set = set(emitted)
    present = tuple(key for key in selected if key in emitted_set)
    if not present:
        return SheetResolution((), SKIP_SHEET_NOT_EMITTED, ", ".join(selected))
    return SheetResolution(present)


# =============================================================================
# Private helpers
# =============================================================================


def _resolve_sheet_axis(
    rule: ValidationRule, home: str, index: TemplateIndex, binding: TableBinding
) -> SheetResolution:
    """Resolve the sheet axis a rule iterates over on its home table."""
    emitted = index.sheet_keys(home)
    if not binding.per_sheet:
        return SheetResolution((SINGLE_SHEET,))

    scope = rule.scope_for(home).sheets
    if scope.kind != SCOPE_LIST:
        # ``(All)`` and an unscoped axis both mean "every sheet". An unscoped
        # sheet axis is NOT "the total sheet": the publisher leaves it blank on
        # rules that hold identically on each sheet, and our estate emits no
        # total sheet at all.
        return SheetResolution(emitted)

    sheet_map = SHEET_INDEX_MAPS.get(binding.sheet_map or "")
    if sheet_map is None:
        return SheetResolution(
            (),
            SKIP_SHEET_INDEX_MAP_UNKNOWN,
            f"{home} sheets are not indexed positionally by the publisher",
        )
    return resolve_sheet_codes(scope.ids, sheet_map, emitted)


def _axis_values(
    scope: RuleScope, emitted: tuple[str, ...], *, iterate: bool
) -> tuple[str | None, ...]:
    """Resolve one axis of the coordinate grid.

    A listed scope keeps ONLY the ids the frame actually emitted — a scoped id we
    never produced is a structural gap, not a zero, and is dropped here so it can
    never contribute to an arithmetic assertion.
    """
    if scope.kind == SCOPE_LIST:
        return tuple(ref for ref in scope.ids if ref in emitted)
    if scope.kind == SCOPE_ALL or iterate:
        return emitted
    return (None,)
