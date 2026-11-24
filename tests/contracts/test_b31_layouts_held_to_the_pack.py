"""
Every Basel 3.1 template's layout, held to the PRA001 taxonomy pack in one place.

Why this file exists: each Basel 3.1 template's layout was held to the Bank of
England's taxonomy only after it escaped — OF 07.00 (2026-11-13), OF 02.00, the
OF 08 sheet axis and OF 08.01's cells, rows and columns each have a contract test
of their own. The rest were held by nothing fast. OF 08.02 generates columns 0275
/ 0276 where its table has 0105 / 0106, and carries OF 08.01's slotting
financial-collateral meaning on 0101-0104, codes its table uses for the
conversion-factor breakdown; OF 08.06 is laid out on the CRR row grid; OF 09.02
had a row its table does not (row 0010, removed by P5.60); C 08.04 is generated per
class against a table with no sheet axis. The slow filing-mapping ratchet sees part
of this, but as counts, for non-zero figures only, and each figure under the first
reason that applies — so an open-row or open-key reason hides every row and column
error behind it.
Holding them all at once found one more: our four C 34 templates carry the
published codes with other templates' meanings (``_C34_REASON``).

The population is the binding table (``filing/bindings.py``): every bundle member
a Basel 3.1 table is bound to is held, so a new binding is held from the day it is
written. The limbs, each in both directions where the direction exists:

(a) columns — our declared column codes are the union of the member's published
    tables' columns; an open-row table's key column (OF 08.02 0005, the obligor
    grade) is part of that axis, as the table's ``entry_columns`` has it;
(b) rows — our declared fixed rows are the published fixed rows; a template
    whose tables are all open-row declares none;
(c) sheet axis — the binding's shape is the table's: a fixed axis is read through
    a sheet map naming exactly the codes the member's tables publish, a table
    with no axis is one frame, an open axis is keyed by its members; and every
    sheet a book generates has a published place (open axes are held that way
    only: a member we have no exposure for is rightly absent);
(d) cells — no generated figure, a zero included, sits where its published sheet
    has no cell (a zero is a fact the gateway evaluates; Filing Manual v1.0.1
    rule 2.19 asks for none);
(e) meaning — where a code could carry another template's meaning, our label
    states what the published label states (``MEANINGS``; every anchor is itself
    held to the pack's label). A code-set test passes OF 08.02 0101-0104 today.

Two more hold the generated estate to the declaration: a book generates only
declared rows and columns, and the book reaches every bound member — a member
that generates nothing passes (c) and (d) with nothing to check.

What is wrong today is in ``KNOWN_DIVERGENCES``, each entry naming the plan item
that owns its fix (``OWNER: P<n>.<n>``, the grammar of
``scripts/tolerated_findings.py``). The comparison is exact: a new divergence
fails, and so does an entry its fix has made stale — shrink the entry in the
fix's own change.

Scope:
- CRR is not held: the repository holds no EBA taxonomy to hold it to.
- ``NOT_GENERATED``: OF 08.05.1 is bound but is not a template we generate.
- ``PUBLISHED_ROWS_NOT_GENERATED``: OF 02.00's rows for what the engine does not
  compute (market risk by approach, SA-CVA, AA-CVA, the 0690 of-which rows, the
  investment-firm rows). Its settlement/delivery rows 0500 / 0510 and BA-CVA row
  0642 are not scope: the engine computes both, so they are a divergence
  (``KNOWN_DIVERGENCES``). The DvP failed trades are reported, but as SA credit
  risk (rows 0040 / 0050 / 0060, the obligor's class row, C 07.00) where 0490 /
  0500 / 0510 belong; the free deliveries rightly stay there; BA-CVA is in no row.
- The templates with a contract test of their own keep it: those hold more than
  the layout (labels, populations, tie-outs, per-sheet declarations).

References:
- Bank of England Banking Taxonomy v4.1.1, module PRA001 — every table bound in
  ``filing/bindings.py``; where Annex II and the taxonomy disagree, the taxonomy
  is what the gateway files against
- PRA PS1/26 Annex I (templates) and Annex II (instructions)
- Bank of England XBRL Filing Manual v1.0.1, rule 2.19
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from scripts.tolerated_findings import owner_of
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import COMMON_LEGS, Leg, b31_frame

from rwa_calc.reporting.corep import templates as ct
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.filing.bindings import build_template_index
from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.release import resolve_release
from rwa_filer.validate.evaluate import GEOGRAPHY_TOTAL_SHEET
from rwa_filer.validate.index import SINGLE_SHEET
from rwa_filer.validate.structure import local_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_filer.taxonomy.pack import Table, TaxonomyPack
    from rwa_filer.validate.index import TableBinding

FRAMEWORK = "BASEL_3_1"

#: The open-axis member that is the all-geographies total (OF 09.01 / 09.02),
#: which our per-country bundles key ``GEOGRAPHY_TOTAL_SHEET``.
GEOGRAPHY_TOTAL_MEMBER = "x1"

#: The two structural columns every generated frame leads with.
STRUCTURAL_COLUMNS = frozenset({"row_ref", "row_name"})

# The limbs a divergence is recorded against.
COLUMNS_OURS = "columns: ours only"
COLUMNS_PUBLISHED = "columns: published only"
ROWS_OURS = "rows: ours only"
ROWS_PUBLISHED = "rows: published only"
SHEET_AXIS = "sheet axis"
SHEETS = "sheets: no published place"
CELLS = "cells: no published cell"
MEANING = "meaning"
LIMBS = (
    COLUMNS_OURS,
    COLUMNS_PUBLISHED,
    ROWS_OURS,
    ROWS_PUBLISHED,
    SHEET_AXIS,
    SHEETS,
    CELLS,
    MEANING,
)


class Layout(NamedTuple):
    """One member's declared layout: ``(code, label)`` pairs.

    ``rows`` is None for a template whose rows are keyed, not fixed (OF 08.02).
    """

    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple[str, str], ...] | None


class Known(NamedTuple):
    """A divergence measured today: the codes, and why, with the owning item."""

    codes: frozenset[str]
    reason: str


class Scope(NamedTuple):
    """Published rows a member leaves out because it does not compute them."""

    rows: Callable[[str], bool]
    reason: str


def _span(first: str, last: str) -> frozenset[str]:
    """Every code from ``first`` to ``last`` in steps of ten, both included."""
    return frozenset(f"{code:04d}" for code in range(int(first), int(last) + 1, 10))


def _sections(sections: list[ct.RowSection]) -> tuple[tuple[str, str], ...]:
    return tuple((row.ref, row.name) for section in sections for row in section.rows)


def _named(items: list[ct.COREPColumn] | list[ct.COREPRow]) -> tuple[tuple[str, str], ...]:
    return tuple((item.ref, item.name) for item in items)


def _pd_scale() -> tuple[tuple[str, str], ...]:
    """The PD-range rows OF 08.03 and OF 08.05 are banded on (``corep/pd_scale.py``)."""
    return tuple((ref, label) for _low, _high, ref, label in ct.get_c08_03_pd_ranges(FRAMEWORK))


#: Each bound member's declared layout, read from the declarations its generator
#: reads. A member bound in ``filing/bindings.py`` and missing here fails
#: ``test_every_bound_member_has_a_declared_layout``.
DECLARED: dict[str, Callable[[], Layout]] = {
    "c_02_00": lambda: Layout(
        _named(ct.get_c02_00_columns(FRAMEWORK)), _sections(ct.get_c02_00_row_sections(FRAMEWORK))
    ),
    "of_02_01": lambda: Layout(_named(ct.OF_02_01_COLUMNS), _sections(ct.OF_02_01_ROW_SECTIONS)),
    "c07_00": lambda: Layout(
        _named(ct.get_c07_columns(FRAMEWORK)), _sections(ct.get_sa_row_sections(FRAMEWORK))
    ),
    "c08_01": lambda: Layout(
        _named(ct.get_c08_columns(FRAMEWORK)), _sections(ct.get_irb_row_sections(FRAMEWORK))
    ),
    "c08_02": lambda: Layout(_named(ct.get_c08_02_columns(FRAMEWORK)), None),
    "c08_03": lambda: Layout(_named(ct.get_c08_03_columns(FRAMEWORK)), _pd_scale()),
    "c08_04": lambda: Layout(_named(ct.get_c08_04_columns(FRAMEWORK)), _named(ct.C08_04_ROWS)),
    "c08_05": lambda: Layout(_named(ct.get_c08_05_columns(FRAMEWORK)), _pd_scale()),
    "c08_06": lambda: Layout(
        _named(ct.get_c08_06_columns(FRAMEWORK)),
        tuple((ref, label) for ref, label, _short, _rw in ct.get_c08_06_rows(FRAMEWORK)),
    ),
    "c08_07": lambda: Layout(
        _named(ct.get_c08_07_columns(FRAMEWORK)),
        tuple((ref, label) for ref, label, _class in ct.get_c08_07_rows(FRAMEWORK)),
    ),
    "c09_01": lambda: Layout(
        _named(ct.get_c09_01_columns(FRAMEWORK)), _named(ct.get_c09_01_rows(FRAMEWORK))
    ),
    "c09_02": lambda: Layout(
        _named(ct.get_c09_02_columns(FRAMEWORK)), _named(ct.get_c09_02_rows(FRAMEWORK))
    ),
    "c34_01": lambda: Layout(_named(ct.get_c34_01_columns()), _named(ct.C34_01_ROWS)),
    "c34_02": lambda: Layout(_named(ct.get_c34_02_columns()), _named(ct.C34_02_ROWS)),
    "c34_04": lambda: Layout(_named(ct.get_c34_04_columns()), _named(ct.C34_04_ROWS)),
    "c34_08": lambda: Layout(_named(ct.get_c34_08_columns()), _named(ct.C34_08_ROWS)),
}

#: Tables bound to a member that are not a template we generate. Each reason is
#: checked: the table is bound, keyed by open rows, and our member declares
#: none of its key columns.
NOT_GENERATED: dict[str, str] = {
    "OF08.05.01.01": (
        "OF 08.05.1, PD back-testing for estimates mapped to an external rating scale "
        "(PS1/26 Annex II para 81): a separate, conditional template whose rows are keyed "
        "by the firm's own PD ranges (key 0005). Our OF 08.05 is the fixed-scale "
        "OF08.05.00.01. bindings.py binds both tables to c08_05, so the template-level "
        "engine evaluates OF 08.05.1's three rules (boe_b0318 / b0354 / b0446) on our "
        "OF 08.05 frame, and all three PASS on the book below - a binding finding, not a "
        "layout one. OWNER: P2.110 - unbind OF08.05.01.01 from c08_05 and bank the "
        "binding-rule drop in the coverage ratchet."
    ),
}

#: Published rows a member does not generate by scope, not by defect: each scope
#: a predicate on the row code and its reason, and each must still leave out a
#: published row. A row for something the engine computes is not a scope, even
#: outside credit risk: it is a divergence (OF 02.00 0500 / 0510 / 0642).
PUBLISHED_ROWS_NOT_GENERATED: dict[str, tuple[Scope, ...]] = {
    "c_02_00": (
        Scope(
            lambda code: code in {"0020", "0030"},
            "the investment-firm of-which rows (Art. 95(2) / 98, Art. 96(2) / 97): not "
            "an entity type this calculator runs (test_of02_published_cells.py::NOT_COMPUTED)",
        ),
        Scope(
            lambda code: "0530" <= code <= "0585" or "5860" <= code <= "5896",
            "position, foreign exchange and commodities risk by approach (SSA, ASA, IMA): "
            "the engine computes no market risk (the 0520 total is laid out, empty)",
        ),
        Scope(
            lambda code: code == "0641",
            "SA-CVA (Annex II row 0641: CVA Risk Part Chapter 5): not computed - deferred "
            "to v2.0 under P8.61 (the CCR epic's scope decision 2 ships BA-CVA only)",
        ),
        Scope(
            lambda code: code == "0643",
            "AA-CVA (Annex II row 0643: CVA Risk Part Chapter 6, the alternative approach): "
            "not computed - engine/cva implements the Basic Approach (Chapter 4) only",
        ),
        Scope(
            lambda code: "0710" <= code <= "0760",
            "the of-which rows of 0690: stricter prudential requirements under Art. 458 / "
            "459 and the Article 3 CRR add-on, none of which the engine models",
        ),
    ),
}

_C34_REASON = (
    "OWNER: P2.101 - our C 34.01 / .02 / .04 / .08 are not the published templates "
    "under those codes. PRA001's C34.01 is the size of the derivative business (CCR 1), "
    "C34.02 CCR exposures by approach (CCR 2), C34.04 the original exposure method "
    "(CCR 4) and C34.08 the composition of collateral (CCR 8); ours are SA-CCR by "
    "approach, EAD per netting set, CVA capital and CCP exposures. Every figure of "
    "c34_01 / 04 / 08 is placed - and would be filed - on a cell that means something "
    "else (c34_04 r0010 c0010, our CVA RWEA, is the published 'Number of transactions'); "
    "P2.101 records only the symptom (partial rows and columns). The fix re-targets the "
    "figures: relabelling our rows and columns to the published labels clears every "
    "MEANING entry here while the figures still mean something else, and adding the "
    "missing rows and columns builds on the wrong templates."
)

#: What diverges today, by (member, limb). Exact: a divergence not listed here
#: fails, and so does a listed one that has gone.
KNOWN_DIVERGENCES: dict[tuple[str, str], Known] = {
    # --- OF 02.00 -----------------------------------------------------------
    ("c_02_00", ROWS_PUBLISHED): Known(
        frozenset({"0500", "0510", "0642"}),
        "OWNER: P2.109 (to be filed with this test) - c02.py lays settlement/delivery and "
        "CVA risk out empty: totals 0490 and 0640 are null, and their breakdown rows 0500 / "
        "0510 (settlement/delivery risk in the non-trading / trading book) and 0642 "
        "(BA-CVA) are not declared. Settlement: engine/ccr/failed_trades.py's Article 378 "
        "DvP rows (regulatory_band dvp_*) reach the exposure frame as SA own-funds lines, "
        "so they are reported as SA credit risk - rows 0040 / 0050 / 0060 and the "
        "obligor's class row, and C 07.00's class sheet - where Annex II puts them in 0490 "
        "(Article 92(3)(c)(ii)) and 0500 / 0510 (CR SETT). Measured on the CCR-C1/C2/C3 "
        "book (three DvP legs, both regimes): 13.85m in 0010 / 0040 / 0050 / 0060 / 0130 "
        "and on C 07.00's corporate sheet, 0490 null. The Article 379 free deliveries the "
        "module also computes rightly stay in credit risk (row 0040 '... AND FREE "
        "DELIVERIES'; Annex II CR SETT para 105), and a Table 2 Column 4 one carries the "
        "same risk_type as a DvP leg. So the fix moves the DvP legs, by band, out of the "
        "credit-risk rows and C 07.00 into 0490 / 0500 / 0510; adding failed_trades_rwa to "
        "0490 as a roll-up would count the DvP RWEA twice and take the free deliveries out "
        "of credit risk. The inputs carry no trading-book flag, so which of 0500 / 0510 a "
        "DvP leg goes on is the fix's to decide. CVA: engine/cva/ba_cva.py computes the "
        "Basic Approach (CVA Risk Part Chapter 4; AggregatedResultBundle.cva_rwa), and no "
        "OF 02.00 row reports it: row 0010 is 6096.0 on this book, whose 7.0 of CVA RWEA "
        "only our C 34.04 reports, on a cell that means something else (P2.101).",
    ),
    # --- OF 08.02 -----------------------------------------------------------
    ("c08_02", COLUMNS_OURS): Known(
        frozenset({"0275", "0276"}),
        "OWNER: P2.71 (with P2.1's OF 08.02 sub-bullet) - OF 08.02 takes OF 08.01's "
        "column list whole (templates.py B31_C08_02_COLUMNS), so it carries OF 08.01's "
        "output-floor columns, which OF08.02.01.01 does not have.",
    ),
    ("c08_02", COLUMNS_PUBLISHED): Known(
        frozenset({"0105", "0106"}),
        "OWNER: P2.71 - OF08.02.01.01's conversion-factor breakdown ends in 0105 (100%) "
        "and 0106 (own estimate); OF 08.01 has neither, so the inherited list lacks both.",
    ),
    ("c08_02", MEANING): Known(
        frozenset({"column 0101", "column 0102", "column 0103", "column 0104"}),
        "OWNER: P2.71 - the published 0101-0104 are the 10% / 20% / 40% / 50% "
        "conversion-factor buckets; ours are OF 08.01's slotting financial-collateral "
        "columns, and 0104 files the after-all-CRM exposure. Unseen today only because "
        "OF 08.02's rows are not placed (open_rows_not_mapped).",
    ),
    # --- OF 08.06 -----------------------------------------------------------
    ("c08_06", COLUMNS_OURS): Known(
        frozenset({"0070"}),
        "OWNER: P2.72 - OF08.06.01.01 has no column 0070; it is the CRR template's "
        "printed slotting risk weight, which we still generate (0.5, 0.7, ...).",
    ),
    ("c08_06", ROWS_OURS): Known(
        _span("0010", "0120"),
        "OWNER: P2.72 - our Basel 3.1 OF 08.06 is built on the CRR row grid "
        "(category x maturity, 0010-0120, plus 0015 / 0025).",
    ),
    ("c08_06", ROWS_PUBLISHED): Known(
        frozenset({"0005", "0035", "0045", "0055", "0065", "0075", "0085", "0095"}),
        "OWNER: P2.72 - the published rows are 0005-0095; of them only 0015 / 0025 "
        "share a code with our CRR grid.",
    ),
    ("c08_06", MEANING): Known(
        frozenset({"row 0025"}),
        "OWNER: P2.72 - published row 0025 is 'Of which: less than 2.5 years remaining "
        "until maturity' (under Strong); ours is 'Category 2 (Good) - substantially "
        "stronger'. A code-set fix would pass it with the wrong population.",
    ),
    ("c08_06", SHEETS): Known(
        frozenset({"commodities_finance", "hvcre", "ipre", "object_finance", "project_finance"}),
        "OWNER: P2.72 - our OF 08.06 sheets are keyed by sl_type; the table's open axis "
        "(eba_dim:TSL) takes its own members, none of which is one of our keys.",
    ),
    # --- C 08.04 ------------------------------------------------------------
    ("c08_04", SHEET_AXIS): Known(
        frozenset({"C08.04.01.01: no sheet axis, bound per sheet"}),
        "OWNER: P2.73 - C08.04.01.01 has no z-axis; bindings.py binds it per sheet with "
        "the OF 08 sheet map.",
    ),
    ("c08_04", SHEETS): Known(
        frozenset(
            {
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
                "retail_other",
                "retail_qrre",
                "specialised_lending",
            }
        ),
        "OWNER: P2.73 - one frame per exposure class, none of which the table can place.",
    ),
    # --- OF 09.01 / OF 09.02 ------------------------------------------------
    ("c09_01", CELLS): Known(
        frozenset({"r0100 c0020"}),
        "OWNER: P2.108 (to be filed with this test) - OF09.01.01.01's row 0100 "
        "(exposures in default) has no column 0020; c09.py declares that memo on every "
        "row, and on row 0100 its predicate (the raw exposure_class 'defaulted', which a "
        "sealed leg never carries) matches nothing, so the zero-fill writes 0.0.",
    ),
    ("c09_02", CELLS): Known(
        frozenset({"r0045 c0080", "r0045 c0090", "r0045 c0100"}),
        "OWNER: P2.85 - row 0045 (specialised lending under slotting) has no PD or LGD "
        "cells; c09.py::_wavg_or_null averages every leg of a row, slotting included "
        "(the weight P2.85 replaces), so the slotting-only row reports a PD of 0.0 (its "
        "legs carry none and are averaged in as zero) and the slotting legs' LGD (the "
        "b31 golden: 0.0 and 0.45).",
    ),
    # --- C 34 ---------------------------------------------------------------
    ("c34_01", COLUMNS_PUBLISHED): Known(_span("0030", "0090"), _C34_REASON),
    ("c34_01", ROWS_PUBLISHED): Known(_span("0020", "0050"), _C34_REASON),
    ("c34_01", MEANING): Known(frozenset({"row 0010", "column 0010", "column 0020"}), _C34_REASON),
    ("c34_02", COLUMNS_PUBLISHED): Known(_span("0020", "0220"), _C34_REASON),
    ("c34_02", ROWS_PUBLISHED): Known(_span("0020", "0140"), _C34_REASON),
    ("c34_02", SHEET_AXIS): Known(
        frozenset({"C34.02.01.01: a fixed sheet axis, bound without a sheet map"}),
        _C34_REASON + " C34.02's two sheets are all CCR / all but CCPs (P2.72 holds the keys).",
    ),
    ("c34_02", SHEETS): Known(frozenset({"CCP1", "NS1"}), _C34_REASON),
    ("c34_02", CELLS): Known(frozenset({"r0010 c0010"}), _C34_REASON),
    ("c34_02", MEANING): Known(frozenset({"row 0010", "column 0010"}), _C34_REASON),
    ("c34_04", COLUMNS_PUBLISHED): Known(_span("0020", "0050"), _C34_REASON),
    ("c34_04", ROWS_PUBLISHED): Known(_span("0020", "0070"), _C34_REASON),
    ("c34_04", MEANING): Known(frozenset({"column 0010"}), _C34_REASON),
    ("c34_08", COLUMNS_PUBLISHED): Known(_span("0030", "0180"), _C34_REASON),
    ("c34_08", ROWS_PUBLISHED): Known(_span("0040", "0090"), _C34_REASON),
    ("c34_08", MEANING): Known(
        frozenset({"row 0010", "row 0020", "row 0030", "column 0010", "column 0020"}),
        _C34_REASON,
    ),
}

#: (member, axis, code) -> words the published label states, which our label for
#: that code must state too. Only a code we declare is compared; one we do not is
#: held by the code-set limbs, and its anchor waits for the fix that adds it.
MEANINGS: dict[tuple[str, str, str], str] = {
    # OF 08.01 and OF 08.02 share 0101-0104 and mean different things by them.
    ("c08_01", "column", "0101"): "volatility adjustment to the exposure",
    ("c08_01", "column", "0102"): "adjusted value cvam",
    ("c08_01", "column", "0103"): "volatility and maturity",
    ("c08_01", "column", "0104"): "after all crm",
    ("c08_02", "column", "0101"): "10%",
    ("c08_02", "column", "0102"): "20%",
    ("c08_02", "column", "0103"): "40%",
    ("c08_02", "column", "0104"): "50%",
    ("c08_02", "column", "0105"): "100%",
    ("c08_02", "column", "0106"): "own estimate",
    # OF 08.06's rows are not the CRR grid; two of its codes are CRR codes. Each
    # anchor states as much of the published label as tells it from a CRR row:
    # 0005 is the preferential subset of Strong, not all of it, and 0045 the
    # short-maturity subset of Good - "Category 1 (Strong)" or "Category 2
    # (Good)" moved onto them would pass a bare "strong" / "good".
    ("c08_06", "row", "0005"): "strong preferential",
    ("c08_06", "row", "0015"): "substantially stronger",
    ("c08_06", "row", "0025"): "less than 2.5 years",
    ("c08_06", "row", "0035"): "other",
    ("c08_06", "row", "0045"): "good less than 2.5 years",
    ("c08_06", "row", "0055"): "other",
    ("c08_06", "row", "0065"): "satisfactory",
    ("c08_06", "row", "0075"): "weak",
    ("c08_06", "row", "0085"): "default",
    ("c08_06", "row", "0095"): "total",
    # The C 34 family.
    ("c34_01", "row", "0010"): "size of the derivative business",
    ("c34_01", "column", "0010"): "long derivative positions",
    ("c34_01", "column", "0020"): "short derivative positions",
    ("c34_02", "row", "0010"): "original exposure method",
    ("c34_02", "column", "0010"): "number of counterparties",
    ("c34_04", "column", "0010"): "number of transactions",
    ("c34_08", "row", "0010"): "domestic currency",
    ("c34_08", "row", "0020"): "other currencies",
    ("c34_08", "row", "0030"): "domestic sovereign debt",
    ("c34_08", "column", "0010"): "initial margin",
    ("c34_08", "column", "0020"): "variation margin",
}

#: (member, axis, code) -> words our label for that code must NOT state: where the
#: published label alone cannot tell a row from its sibling, the sibling's block
#: is what it must not claim. OF 08.06 0035 and 0055 are both "Other" - 0035 the
#: rest of Strong, 0055 the rest of Good - so a 0035 that says "good", or a 0055
#: that says "strong", is the other row. Each is held to the pack: the published
#: label does not state the words, and another published label of the table does.
EXCLUDED_MEANINGS: dict[tuple[str, str, str], str] = {
    ("c08_06", "row", "0035"): "good",
    ("c08_06", "row", "0055"): "strong",
}

#: The sealed-shape defaulted SA leg: an obligor class, a defaulted applied class
#: (LESSONS C11(c) - a defaulted SA leg's applied class is never its obligor's).
SA_DEFAULT = Leg("SA_DEF_CORP", "standardised", "corporate", 24.0, 24.0)
#: A defaulted slotting leg, so the default rows and "of which: defaulted" cells
#: of the IRB templates carry a figure.
SL_DEFAULT = Leg(
    "SL_DEF", "slotting", "specialised_lending", 450.0, 550.0, sl_type="project_finance"
)
#: SA-CCR netting sets (a bilateral one and one with a qualifying CCP) and a
#: default-fund contribution, so every C 34 member generates a frame.
CCR_LEGS = (
    Leg("ccr__NS1", "standardised", "institution", 31.0, 31.0),
    Leg("ccr__CCP1", "standardised", "institution", 32.0, 32.0),
    Leg("DF1", "standardised", "institution", 33.0, 33.0),
)
ESTATE_LEGS = (
    *(leg for leg in COMMON_LEGS if leg.exposure_class != "defaulted"),
    SA_DEFAULT,
    SL_DEFAULT,
    *CCR_LEGS,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


@pytest.fixture(scope="module")
def bindings() -> dict[str, TableBinding]:
    """Every Basel 3.1 table binding, from the filing adapter's own index."""
    empty = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={}, framework=FRAMEWORK)
    return dict(build_template_index(empty, None, FRAMEWORK).bindings)


@pytest.fixture(scope="module")
def tables_of(bindings: dict[str, TableBinding], pack: TaxonomyPack) -> dict[str, list[Table]]:
    """Bundle member -> the published tables it carries (``NOT_GENERATED`` left out)."""
    grouped: dict[str, list[Table]] = {}
    for code, binding in bindings.items():
        if code not in NOT_GENERATED:
            grouped.setdefault(binding.attribute, []).append(pack.tables[code])
    return grouped


@pytest.fixture(scope="module")
def cells_of(pack: TaxonomyPack) -> dict[str, set[tuple[str | None, str | None, str]]]:
    """Table code -> every (sheet, row, column) it has a cell at.

    ``sheet`` is None for a table with no fixed axis, ``row`` for an open-row one."""
    cells: dict[str, set[tuple[str | None, str | None, str]]] = {}
    for table, sheet, row, column in pack.cells.select(
        "table", "sheet", "row", "column"
    ).iter_rows():
        cells.setdefault(table, set()).add((sheet, row, column))
    return cells


@pytest.fixture(scope="module")
def estate() -> COREPTemplateBundle:
    """A Basel 3.1 book with a leg for every bound member to report.

    Beyond the hand-built legs: the PD / LGD carriers OF 08.02 / 08.03 / 08.05 /
    09.02 read, the slotting category OF 08.06 needs, a country for OF 09.0x, the
    defaulted flag, and the SA-CCR / CCP / default-fund / CVA carriers of C 34.
    """
    ref = pl.col("exposure_reference")
    slotting = pl.col("approach_applied") == "slotting"
    frame = b31_frame(ESTATE_LEGS).with_columns(
        pl.when(ref == SA_DEFAULT.reference)
        .then(pl.lit("defaulted"))
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class_applied"),
        ref.is_in([SA_DEFAULT.reference, SL_DEFAULT.reference]).alias("is_defaulted"),
        pl.when(ref == SL_DEFAULT.reference)
        .then(pl.lit("default"))
        .when(slotting)
        .then(pl.lit("strong"))
        .otherwise(None)
        .alias("slotting_category"),
        pl.lit("GB").alias("cp_country_code"),
        pl.when(ref.str.starts_with("ccr__"))
        .then(pl.lit("CCR_DERIVATIVE"))
        .when(ref == "DF1")
        .then(pl.lit("CCR_DEFAULT_FUND"))
        .otherwise(None)
        .alias("risk_type"),
        pl.when(ref == "ccr__CCP1")
        .then(pl.lit("ccp"))
        .otherwise(pl.lit("institution"))
        .alias("cp_entity_type"),
        pl.when(ref == "ccr__CCP1").then(pl.lit(value=True)).otherwise(None).alias("cp_is_qccp"),
        pl.lit(7.0).alias("cva_rwa"),
        # A slotting leg carries no PD (the sealed ledger's shape); its LGD it does.
        pl.when(slotting).then(None).otherwise(pl.lit(0.01)).alias("pd_floored"),
        pl.when(slotting).then(None).otherwise(pl.lit(0.01)).alias("pd"),
        pl.lit(0.45).alias("lgd_floored"),
        pl.lit(0.45).alias("lgd_post_crm"),
        ref.alias("counterparty_reference"),
    )
    return LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=FRAMEWORK)


# =============================================================================
# The population and the register
# =============================================================================


def test_every_bound_member_has_a_declared_layout(tables_of: dict[str, list[Table]]) -> None:
    # Arrange
    bound = set(tables_of)

    # Act
    declared = set(DECLARED)

    # Assert
    assert sorted(bound - declared) == [], "bound members with no layout getter here"
    assert sorted(declared - bound) == [], "layouts declared for a member nothing binds"


def test_every_table_left_out_is_bound_keyed_by_open_rows_and_not_declared(
    bindings: dict[str, TableBinding], pack: TaxonomyPack
) -> None:
    """The reason ``NOT_GENERATED`` gives is a claim: check it."""
    # Arrange / Act
    wrong = {}
    for code in NOT_GENERATED:
        table = pack.tables[code]
        declared = {ref for ref, _ in DECLARED[bindings[code].attribute]().columns}
        if not table.open_rows or not table.key_codes or declared & set(table.key_codes):
            wrong[code] = (table.open_rows, table.key_codes)

    # Assert
    assert set(NOT_GENERATED) <= set(bindings), "a table left out that nothing binds"
    assert wrong == {}
    unowned = sorted(code for code, reason in NOT_GENERATED.items() if owner_of(reason) is None)
    assert unowned == [], f"tables left out with no OWNER token in their reason: {unowned}"


def test_every_known_divergence_names_its_owner_and_a_bound_member(
    tables_of: dict[str, list[Table]],
) -> None:
    # Arrange
    register = {
        f"{member} / {limb}": known.reason for (member, limb), known in KNOWN_DIVERGENCES.items()
    }

    # Act
    unowned = sorted(key for key, reason in register.items() if owner_of(reason) is None)
    stray = sorted(
        f"{member} / {limb}"
        for member, limb in KNOWN_DIVERGENCES
        if member not in tables_of or limb not in LIMBS
    )

    # Assert
    assert unowned == [], "a known divergence must name the plan item that owns its fix"
    assert stray == []
    assert all(known.codes for known in KNOWN_DIVERGENCES.values()), "an empty entry"


def test_the_book_reaches_every_bound_member(
    estate: COREPTemplateBundle, tables_of: dict[str, list[Table]]
) -> None:
    """Adequacy: a member with no frame passes the sheet and cell limbs vacuously,
    and one whose frames carry no non-zero figure has not seen the book's legs."""
    # Arrange
    keys = {
        member: {code for t in tables for code in t.key_codes}
        for member, tables in tables_of.items()
    }

    # Act
    empty = sorted(
        member
        for member in tables_of
        if not any(
            _figures(frame, keys[member], nonzero=True)
            for frame in _frames(estate, member).values()
        )
    )

    # Assert
    assert empty == [], f"the book reports no non-zero figure for {empty}: {estate.errors}"


# =============================================================================
# (a) Columns and (b) rows, both ways
# =============================================================================


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_the_declared_columns_are_the_published_columns(
    tables_of: dict[str, list[Table]], member: str
) -> None:
    # Arrange
    published = {code for table in tables_of[member] for code, _ in table.entry_columns}

    # Act
    ours = {code for code, _ in DECLARED[member]().columns}

    # Assert
    assert frozenset(ours - published) == _known(member, COLUMNS_OURS)
    assert frozenset(published - ours) == _known(member, COLUMNS_PUBLISHED)


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_the_declared_rows_are_the_published_rows(
    tables_of: dict[str, list[Table]], member: str
) -> None:
    # Arrange
    tables = tables_of[member]
    published = {code for table in tables if not table.open_rows for code in table.row_codes}
    rows = DECLARED[member]().rows
    scopes = PUBLISHED_ROWS_NOT_GENERATED.get(member, ())

    # Act
    ours = set() if rows is None else {code for code, _ in rows}
    missing = {code for code in published - ours if not any(scope.rows(code) for scope in scopes)}

    # Assert
    assert (rows is None) == all(table.open_rows for table in tables), (
        "a member declares fixed rows exactly when one of its tables has them"
    )
    assert frozenset(ours - published) == _known(member, ROWS_OURS)
    assert frozenset(missing) == _known(member, ROWS_PUBLISHED)


def test_every_row_scope_still_leaves_out_a_published_row(
    tables_of: dict[str, list[Table]],
) -> None:
    """A scope that no longer leaves out any published row is stale, and so is one
    that leaves out a row we declare (the row is generated, not out of scope)."""
    # Arrange / Act
    stale = []
    for member, scopes in PUBLISHED_ROWS_NOT_GENERATED.items():
        published = {code for table in tables_of[member] for code in table.row_codes}
        ours = {code for code, _ in DECLARED[member]().rows or ()}
        stale += [
            f"{member}: {scope.reason[:40]}"
            for scope in scopes
            if not any(scope.rows(code) for code in published - ours)
            or any(scope.rows(code) for code in ours)
        ]

    # Assert
    assert stale == []


# =============================================================================
# (c) The sheet axis
# =============================================================================


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_each_binding_has_the_shape_of_its_tables_sheet_axis(
    tables_of: dict[str, list[Table]], bindings: dict[str, TableBinding], member: str
) -> None:
    # Arrange
    tables = tables_of[member]
    published = {code for table in tables for code in table.sheet_codes}
    maps = {bindings[table.code].sheet_map for table in tables if table.fixed_axis} - {None}

    # Act
    findings = {_axis_finding(table, bindings[table.code]) for table in tables} - {None}
    findings |= {
        f"{name}: names sheets no table of {member} publishes"
        for name in maps
        if set(SHEET_INDEX_MAPS[name]) - published
    }

    # Assert
    assert frozenset(findings) == _known(member, SHEET_AXIS)


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_every_generated_sheet_has_a_published_place(
    estate: COREPTemplateBundle,
    tables_of: dict[str, list[Table]],
    bindings: dict[str, TableBinding],
    member: str,
) -> None:
    # Arrange
    tables = tables_of[member]

    # Act
    homeless = {
        key
        for key in _frames(estate, member)
        if not any(_place(key, table, bindings[table.code])[0] for table in tables)
    }

    # Assert
    assert frozenset(homeless) == _known(member, SHEETS)


# =============================================================================
# (d) Cells, and the estate against the declaration
# =============================================================================


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_no_generated_figure_sits_where_the_published_sheet_has_no_cell(
    estate: COREPTemplateBundle,
    tables_of: dict[str, list[Table]],
    bindings: dict[str, TableBinding],
    cells_of: dict[str, set[tuple[str | None, str | None, str]]],
    member: str,
) -> None:
    """A zero counts: under the gateway a reported 0.0 binds every rule over the
    data point. Codes the table lacks altogether are the column and row limbs';
    this one holds the cells of codes it has.

    A sheet is read against the tables that place it; one that no table places
    (the sheet limb's finding) is read against every sheet, so its cells are
    still held."""
    # Arrange
    tables = tables_of[member]
    columns = {code for table in tables for code in table.column_codes}
    rows = {code for table in tables for code in table.row_codes}
    keyed = all(table.open_rows for table in tables)
    keys = {code for table in tables for code in table.key_codes}

    # Act
    off: set[str] = set()
    for key, frame in _frames(estate, member).items():
        homes = [(table, _place(key, table, bindings[table.code])) for table in tables]
        anywhere = not any(placed for _table, (placed, _sheet) in homes)
        for row, column in _figures(frame, keys):
            if column not in columns or (not keyed and row not in rows):
                continue
            cell = (None if keyed else row, column)
            if not any(
                _has_cell(cells_of[table.code], place, cell, anywhere=anywhere)
                for table, place in homes
            ):
                off.add(f"c{column}" if keyed else f"r{row} c{column}")

    # Assert
    assert frozenset(off) == _known(member, CELLS)


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_the_book_generates_only_declared_rows_and_columns(
    estate: COREPTemplateBundle, member: str
) -> None:
    """Holds the generator to the declaration the code-set limbs read."""
    # Arrange
    layout = DECLARED[member]()
    columns = {code for code, _ in layout.columns}
    rows = None if layout.rows is None else {code for code, _ in layout.rows}

    # Act
    stray: set[str] = set()
    for frame in _frames(estate, member).values():
        stray |= {f"column {name}" for name in set(frame.columns) - STRUCTURAL_COLUMNS - columns}
        if rows is not None:
            stray |= {f"row {ref}" for ref in set(frame["row_ref"].cast(pl.String)) - rows}

    # Assert
    assert sorted(stray) == []


# =============================================================================
# (e) Meaning
# =============================================================================


def test_every_meaning_anchor_is_what_the_published_label_states(
    tables_of: dict[str, list[Table]],
) -> None:
    # Arrange / Act
    wrong = {}
    for (member, axis, code), phrase in MEANINGS.items():
        labels = _published_labels(tables_of[member], axis)
        if code not in labels or not _states(labels[code], phrase):
            wrong[(member, axis, code)] = labels.get(code)
    for (member, axis, code), phrase in EXCLUDED_MEANINGS.items():
        labels = _published_labels(tables_of[member], axis)
        elsewhere = any(_states(label, phrase) for other, label in labels.items() if other != code)
        if code not in labels or _states(labels[code], phrase) or not elsewhere:
            wrong[(member, axis, code, f"not {phrase}")] = labels.get(code)

    # Assert
    assert wrong == {}


@pytest.mark.parametrize("member", sorted(DECLARED))
def test_a_shared_code_carries_its_published_meaning(member: str) -> None:
    # Arrange
    layout = DECLARED[member]()
    ours = {"column": dict(layout.columns), "row": dict(layout.rows or ())}

    # Act
    wrong = {
        f"{axis} {code}"
        for (anchored, axis, code), phrase in MEANINGS.items()
        if anchored == member and code in ours[axis] and not _states(ours[axis][code], phrase)
    }
    wrong |= {
        f"{axis} {code}"
        for (anchored, axis, code), phrase in EXCLUDED_MEANINGS.items()
        if anchored == member and code in ours[axis] and _states(ours[axis][code], phrase)
    }

    # Assert
    assert frozenset(wrong) == _known(member, MEANING)


# =============================================================================
# Private helpers
# =============================================================================


def _known(member: str, limb: str) -> frozenset[str]:
    known = KNOWN_DIVERGENCES.get((member, limb))
    return frozenset() if known is None else known.codes


def _frames(estate: COREPTemplateBundle, member: str) -> dict[str, pl.DataFrame]:
    """A member's generated frames by sheet key; a single frame keys ``SINGLE_SHEET``."""
    generated = getattr(estate, member, None)
    if isinstance(generated, pl.DataFrame):
        return {SINGLE_SHEET: generated}
    return {key: frame for key, frame in (generated or {}).items() if frame.height}


def _figures(frame: pl.DataFrame, keys: set[str], *, nonzero: bool = False) -> set[tuple[str, str]]:
    """The (row, column) of every numeric cell carrying a finite value - zero
    included unless ``nonzero``."""
    numeric = [
        name
        for name in frame.columns
        if name not in STRUCTURAL_COLUMNS and name not in keys and frame.schema[name].is_numeric()
    ]
    if not numeric:
        return set()
    long = (
        frame.select(pl.col("row_ref").cast(pl.String).alias("row"), *numeric)
        .unpivot(index="row", on=numeric, variable_name="column", value_name="value")
        .filter(pl.col("value").cast(pl.Float64).is_finite())
        .filter(pl.col("value") != 0 if nonzero else pl.lit(value=True))
    )
    return set(zip(long["row"].to_list(), long["column"].to_list(), strict=True))


def _axis_finding(table: Table, binding: TableBinding) -> str | None:
    """What is wrong with how ``table``'s sheet axis is bound, or None."""
    if table.fixed_axis is not None:
        if not binding.per_sheet or binding.sheet_map is None:
            return f"{table.code}: a fixed sheet axis, bound without a sheet map"
        if set(table.sheet_codes) - set(SHEET_INDEX_MAPS[binding.sheet_map]):
            return f"{table.code}: the sheet map leaves out a published sheet"
        return None
    if table.open_axis is not None:
        if not binding.per_sheet or binding.sheet_map is not None:
            return f"{table.code}: an open sheet axis, not keyed by its members"
        return None
    return f"{table.code}: no sheet axis, bound per sheet" if binding.per_sheet else None


def _place(key: str, table: Table, binding: TableBinding) -> tuple[bool, str | None]:
    """Whether ``table`` has a place for our sheet ``key``, and its sheet code there.

    The code is None where the table's cells carry none (no axis, or an open
    one, whose member is not a cell coordinate)."""
    if table.fixed_axis is not None:
        sheet_map = SHEET_INDEX_MAPS.get(binding.sheet_map or "", {})
        codes = [code for code, entry in sheet_map.items() if key in entry.bundle_keys]
        if len(codes) != 1 or codes[0] not in table.sheet_codes:
            return False, None
        return True, codes[0]
    if table.open_axis is not None:
        member = GEOGRAPHY_TOTAL_MEMBER if key == GEOGRAPHY_TOTAL_SHEET else key
        return any(local_name(qname) == member for qname in table.open_axis.members), None
    return key == SINGLE_SHEET, None


def _has_cell(
    cells: set[tuple[str | None, str | None, str]],
    place: tuple[bool, str | None],
    cell: tuple[str | None, str],
    *,
    anywhere: bool,
) -> bool:
    """Whether a table with ``cells`` has ``cell`` (row, column) where ``place`` puts it.

    ``place`` is ``_place``'s answer for the sheet. With ``anywhere`` (no table of
    the member places the sheet) any of the table's sheets will do."""
    placed, sheet = place
    row, column = cell
    if anywhere:
        return any(cell_row == row and cell_column == column for _s, cell_row, cell_column in cells)
    return placed and (sheet, row, column) in cells


def _published_labels(tables: list[Table], axis: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for table in tables:
        for code, label in table.columns if axis == "column" else table.rows:
            labels.setdefault(code, label)
    return labels


def _states(label: str, phrase: str) -> bool:
    """Whether ``label`` states ``phrase`` as whole words, case and punctuation aside."""
    return f" {_normalise(phrase)} " in f" {_normalise(label)} "


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9%.]+", " ", text.lower()).split())
