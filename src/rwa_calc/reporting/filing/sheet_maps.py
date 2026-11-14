"""
The sheet (z-axis) index maps — publisher sheet codes onto our per-class sheets.

Pipeline position:
    SHEET_INDEX_MAPS  ->  bindings.build_template_index  ->  rwa_filer TemplateIndex

Key responsibilities:
- Map the publisher SHEET (z-axis) codes — EBA ``s0001``..``s0017``, BoE
  ``z:0001``.. — onto our per-exposure-class sheet keys, through an explicit,
  cited table. Where a code's meaning could not be established the map holds
  nothing and the rule is skipped: a wrong sheet mapping silently produces wrong
  findings, which is far worse than a skip.

Why this lives here and not in ``rwa-filer``: the supervisory z-axis is a
positional index into the regulation's exposure-class list, while OUR bundles
key sheets by class NAME. The mapping between the two is a fact about this
calculator's output, not about the published rules — so it stays with the
calculator, and the rule engine receives it as data on the ``TemplateIndex``.
Our CRR sheets are also a COARSER partition than the DPM's in places — on
``_C08_SHEETS``, one ``retail_mortgage`` sheet answers the DPM's SME (z0013) /
non-SME (z0014) pair — so a scoped subset of z-codes is only safe to evaluate
when the set is CLOSED under the mapping (``rwa_filer.validate.index
.resolve_sheet_codes``). The Basel 3.1 maps are one key per code and closed by
construction.

Every ``SheetCode`` here carries AT MOST ONE ``bundle_key`` (``arch_check``
check 22): a second key makes the evaluator sum the publisher's reference across
two of our sheets and assert against a figure that appears in no submitted
workbook.

References:
- CRR Art. 112(1)(a)-(q) — the SA exposure classes indexed by the C 07.00 z-axis
- CRR Art. 147(2) / COREP Annex II §3.3.2 — the CR IRB sub-exposure-class list
  indexed by the C 08.01 z-axis
- PRA PS1/26 Annex II (OF 07.00 / OF 08.01 / OF 09.01 / OF 09.02 instructions)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rwa_filer.validate.index import SheetCode

if TYPE_CHECKING:
    from collections.abc import Mapping

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
#     s0012's key is ``high_risk`` and s0016's is ``equity`` — the two sheet keys
#     ``templates.C07_00_SA_SHEET_MAP`` gives those classes. Declaring s0012 here
#     is a claim about the MAPPING, not about this regime: Art. 128 was omitted
#     from the onshored UK CRR by SI 2021/1078 reg. 6(3)(a), and
#     ``engine/classify/attributes.py`` demotes the class to OTHER whenever the
#     pack Feature ``b31_high_risk_class_applicable`` is off, so a CRR run emits
#     no ``high_risk`` sheet and every rule scoped to z0012 resolves to
#     ``sheet_not_emitted`` — now for the CORRECT reason (we have a sheet for the
#     code; this run produced none) rather than the false one an empty tuple
#     states (the code addresses nothing of ours, so it is unaddressable and the
#     supervisory gate fails open). Same shape as s0016, whose ``equity`` key is
#     declared though no portfolio in the estate emits an equity sheet (P1.371).
#   * v09743_m applies the CIU look-through/mandate/fall-back decomposition
#     (rows 0281-0283) on sheet 0015 only  ->  s0015 = 112(1)(o).
#
# s0014 and s0015 keep an EMPTY tuple and that is not the same defect: neither
# Art. 112(1)(n) (short-term credit assessment) nor (o) (CIUs) has an
# ``ExposureClass`` member or a ``C07_00_SA_SHEET_MAP`` value, so there is no
# sheet of ours for them to address. ``high_risk`` was the only key the estate
# can emit that no code named.
_C07_SHEETS: Final[tuple[SheetCode, ...]] = (
    # The Total sheet is the generator's ``total`` key
    # (``templates.C07_00_TOTAL_SHEET_KEY`` — spelt out here because arch_check
    # check 22 reads these tuples as literals; the two are held equal by
    # tests/contracts/test_of07_published_cells.py). Its tuple was EMPTY until
    # 2026-11-13 because no such sheet was generated, which left every rule
    # scoped to s0001 unaddressable.
    SheetCode(
        "0001",
        "Total (all SA exposure classes)",
        ("total",),
        "COREP Annex II C 07.00; v4728_m",
    ),
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
        ("corporate",),
        "CRR Art. 112(1)(g); v4240_i vs C 02.00 r0130",
    ),
    SheetCode(
        "0009",
        "Art. 112(1)(h) retail (incl. QRRE of-which)",
        ("retail",),
        "CRR Art. 112(1)(h); v4241_i vs C 02.00 r0140",
    ),
    # ONE key, and it covers residential AND commercial. Art. 112(1)(i) is
    # defined by the security, not the counterparty: row 0040 is an "of which:
    # ... Residential property" OF this sheet, which only parses if the sheet is
    # the wider set. ``corep/c07.py`` fans all three internal real-estate classes
    # onto this single key (``templates.C07_00_SA_SHEET_MAP``), so the sheet is
    # the class TOTAL the z-axis asks for rather than three partial sheets.
    SheetCode(
        "0010",
        "Art. 112(1)(i) secured by mortgages on immovable property",
        ("real_estate",),
        "COREP Annex II C 07.00 row 0040 + para 62 rank 6; v7477_m",
    ),
    SheetCode("0011", "Art. 112(1)(j) exposures in default", ("defaulted",), "CRR Art. 112(1)(j)"),
    SheetCode(
        "0012",
        "Art. 112(1)(k) items associated with particularly high risk",
        ("high_risk",),
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
        ("ciu",),
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
    SheetCode(
        "0001",
        "Total (all SA exposure classes)",
        ("total",),
        "PS1/26 Annex II §3.2.2 ¶47; OF 09.01 row 0170; boe_b0713",
    ),
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
        ("corporate",),
        "PS1/26 Annex II OF 09.01 row 0070; boe_b0973",
    ),
    SheetCode(
        "0009",
        "Art. 112(1)(h) retail (incl. QRRE of-which)",
        ("retail",),
        "PS1/26 Annex II OF 09.01 row 0080",
    ),
    # Under PS1/26 real estate is a STANDALONE class (Art. 112(2) Table A2 row
    # (7), criteria "Articles 124 to 124L"), outranking retail (14) and
    # corporates (15). ``corep/c07.py`` fans all three internal real-estate
    # classes onto the single ``real_estate`` key
    # (``templates.C07_00_SA_SHEET_MAP``), exactly as they already fan into OF
    # 09.01 row 0090 (``corep/c09.py::_C09_01_RE_CLASSES``).
    SheetCode(
        "0010",
        "Art. 112(1)(i) real estate exposures",
        ("real_estate",),
        "PS1/26 Art. 112(2) Table A2 row (7); Annex II OF 09.01 row 0090; boe_b0985/b0987",
    ),
    SheetCode(
        "0011",
        "Art. 112(1)(j) exposures in default",
        ("defaulted",),
        "PS1/26 Annex II OF 09.01 row 0100",
    ),
    # Reachable here, unlike on the CRR axis: Art. 128 is re-introduced under
    # PS1/26 (pack Feature ``b31_high_risk_class_applicable``), so a Basel 3.1 run
    # with a high-risk obligor emits a ``high_risk`` sheet and the 131 enforced
    # BoE rules listing z:0012 (112 of them ERROR, across 136 per-table scopes)
    # evaluate on it. With an empty tuple they all scored
    # NOT_EVALUATED / ``sheet_not_emitted`` instead — a silent loss of coverage,
    # and the emitted sheet was unaddressable by any published rule.
    SheetCode(
        "0012",
        "Art. 112(1)(k) exposures associated with particularly high risk",
        ("high_risk",),
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
        ("ciu",),
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

# ── OF 08.01 / OF 08.02 / OF 08.03 / OF 08.05 (Basel 3.1 / BoE) ──────────────
# A DIFFERENT axis from the CRR one: PS1/26 withdraws the IRB approach for
# sovereigns and A-IRB for institutions (Art. 147A), adds "financial corporates
# and large corporates", and splits retail real estate by property type. The
# seventeen sheets are the taxonomy's own (PRA001 v4.1.1, table
# ``OF08.01.01.01``; the same seventeen on ``OF08.01.01.02``, ``OF08.02.01.01``,
# ``OF08.03.01.01``, ``OF08.05.00.01`` and ``OF08.05.01.01``), with its labels:
# fifteen exposure sub-classes each under ONE approach (PS1/26 Annex II §3.3.2)
# and two Totals. Codes 0003-0005, 0007, 0008, 0013 and 0014 do not exist.
#
# EVERY CODE NAMES EXACTLY ONE KEY, and the keys are the sheets
# ``corep/irb_sheets.py`` declares and ``corep/c08_sheets.py`` generates —
# spelt out here because arch_check check 22 reads these tuples as literals;
# tests/contracts/test_of08_published_sheets.py holds the two equal, and holds
# both to the taxonomy. Until 2026-11-13 our sheets were keyed by exposure class
# alone, so this map sent two to four codes to one sheet ("1st approach / 2nd
# approach") and no figure on such a sheet could be filed
# (``sheet_coarser_than_published_axis``).
_OF08_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode(
        "0001",
        "Total (AIRB approach)",
        ("total_airb",),
        "PS1/26 Annex II §3.3.2 item 1; boe_b0748",
    ),
    SheetCode(
        "0002",
        "Total (FIRB approach and slotting approach)",
        ("total_firb_slotting",),
        "PS1/26 Annex II §3.3.2 item 1; boe_b0749",
    ),
    SheetCode(
        "0006",
        "Institutions (FIRB approach)",
        ("institution_firb",),
        "PS1/26 Annex II §3.3.2 item 2; boe_b0616",
    ),
    SheetCode(
        "0009",
        "Corporates - Specialised Lending (AIRB approach)",
        ("specialised_lending_airb",),
        "PS1/26 Annex II §3.3.2 item 3.1; boe_b0623",
    ),
    SheetCode(
        "0010",
        "Corporates - Specialised Lending (FIRB approach or slotting approach)",
        ("specialised_lending_firb_slotting",),
        "PS1/26 Annex II §3.3.2 item 3.1, §3.3.3 row 0080; boe_b0618, boe_b1041",
    ),
    SheetCode(
        "0011",
        "Corporates - Other general corporates - non-SME (AIRB approach)",
        ("corporate_non_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 3.4; boe_b0564",
    ),
    SheetCode(
        "0012",
        "Corporates - Other general corporates - non-SME (FIRB approach)",
        ("corporate_non_sme_firb",),
        "PS1/26 Annex II §3.3.2 item 3.4; boe_b0621",
    ),
    SheetCode(
        "0015",
        "Retail - Qualifying revolving (AIRB approach)",
        ("retail_qrre_airb",),
        "PS1/26 Annex II §3.3.2 item 4.5; boe_b0628",
    ),
    SheetCode(
        "0016",
        "Retail - Other SME (AIRB approach)",
        ("retail_other_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.6; boe_b0629",
    ),
    SheetCode(
        "0017",
        "Retail - Other non-SME (AIRB approach)",
        ("retail_other_non_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.7; boe_b0630",
    ),
    SheetCode(
        "0018",
        "Retail \u2013 Secured by commercial immovable property SME (AIRB approach)",
        ("retail_commercial_re_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.3; boe_b0626",
    ),
    SheetCode(
        "0019",
        "Retail \u2013 Secured by commercial immovable property non-SME (AIRB approach)",
        ("retail_commercial_re_non_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.4; boe_b0627",
    ),
    SheetCode(
        "0020",
        "Retail \u2013 Secured by residential immovable property - SME (AIRB approach)",
        ("retail_residential_re_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.1; boe_b0624",
    ),
    SheetCode(
        "0021",
        "Retail \u2013 Secured by residential immovable property non-SME (AIRB approach)",
        ("retail_residential_re_non_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 4.2; boe_b0625",
    ),
    SheetCode(
        "0022",
        "Corporates - Financial corporates and large corporates (FIRB approach)",
        ("corporate_financial_large_firb",),
        "PS1/26 Annex II §3.3.2 item 3.2; boe_b0619",
    ),
    SheetCode(
        "0023",
        "Corporates - Other general corporates - SME (AIRB approach)",
        ("corporate_sme_airb",),
        "PS1/26 Annex II §3.3.2 item 3.3; boe_b0563",
    ),
    SheetCode(
        "0024",
        "Corporates - Other general corporates - SME (FIRB approach)",
        ("corporate_sme_firb",),
        "PS1/26 Annex II §3.3.2 item 3.3; boe_b0620",
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
