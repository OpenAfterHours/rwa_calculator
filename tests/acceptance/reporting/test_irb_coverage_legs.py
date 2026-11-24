"""
IRB template-coverage legs — every published Basel 3.1 OF 08.01 class sheet, the
10% / 20% conversion-factor rows, the inflow-only sheet and the Bank-fault sheet
pairings, each reached by a REGISTERED run.

Pipeline position:
    RUNS (tests/acceptance/reporting/test_supervisory_validations.py)
        -> PipelineOrchestrator -> COREPGenerator
        -> filing.build_canonical_return -> rwa_filer trace_return (gateway engine)

Why this exists (P5.81, LESSONS B4 / B5). Until these portfolios were registered,
Basel 3.1 OF 08.01 lit only class sheets 0006, 0010, 0012, 0015, 0017, 0021 and 0023
on every run of the gated estate; OF 09.02 r0048 and r0120 were empty; no IRB
off-balance-sheet item sat in the 10% or 20% Table A1 rows; no Basel 3.1 class sheet
existed only because of a guarantor's inflow; and no off-balance-sheet leg was
substituted onto an IRB guarantor in either regime. Every published rule over those
cells was NOT_EVALUATED or vacuous — indistinguishable from a clean estate. (The
short-maturity slotting rows are not this module's: P1.204's ``slotting-maturity``
runs own them, in all three states of PS1/26 Art. 153(5)(c)-(d) —
``test_of08_06_slotting_maturity_rows.py``.)

Every test here reads its run out of ``RUNS``, so it fails until the leg is in the
gated population: a fixture that is built but not registered is the trap B5 names.

The assertions:

1. **Every published class sheet has a registered owner** whose run emits it with
   original exposure — anchored to ``irb_sheets.B31_CLASS_SHEETS`` (held to the
   taxonomy by ``tests/contracts/test_of08_published_sheets.py``), never to a list
   written here (LESSONS B3).
2. **Hand values** for each new sheet, row and cross-template tie, so a leg that
   lands on the wrong sheet or row fails by its amount, not only by its presence.
3. **The inflow-only sheet** carries the guarantor's inflow and nothing native, in
   BOTH regimes, with a non-zero crossing RWEA (LESSONS C2).
4. **The substitution columns on Annex II's basis, in both regimes** — strict xfails,
   one defect each, each naming the plan item that owns it, so the fix turns them
   XPASS and cannot land unseen:

   - **R0**: C 08.01 / OF 08.01 c0040 (Basel 3.1), c0070-c0080 and c0090 split an
     exposure "prior to the application of conversion factors" and report "the
     covered part of the original exposure pre-conversion factors". Ours read the
     guarantee's covered EXPOSURE VALUE (``guaranteed_portion``, after the 20%
     conversion factor), so the trade item's covered part files as 96,000 where
     Annex II asks for 480,000, and the SME keeps 704,000 where 320,000 remains.
   - **R1**: c0100 ("of which: off balance sheet items", an of-which of c0090) leaves
     the substitution inflow out on C 08.01 and C 08.02 in both regimes, while c0090
     carries it. The Total row's c0100 is row 0030's c0090 by identity: one PRA001
     data point under Basel 3.1, the EBA's live ``v3354_i``-``v3370_i`` under CRR.
     Its control, on every sheet with an off-balance-sheet item and no inflow, passes.

   ``boe_b0735`` (OF 08.01 r0010 c0100 against the sum of OF 08.03 c0020) is not
   pinned here. Its breaks on this book are an open reading, not a defect of ours:
   OF 08.03 c0020 reads the obligor's pre-substitution population (the recorded
   decision in ``corep/c08.py``: Annex II allocates OF 08.03 to PD rows "without
   considering ... any substitution effects due to CRM", and EBA Q&A 2023_6718's
   resultant-obligor columns leave 0020 out), so the rule also fails a return on
   Annex II's basis wherever an off-balance-sheet item's covered part changes sheet.
   The RUNS comment in ``test_supervisory_validations.py`` records it.
5. **The pairings**: our OF 09.02 r0055 is sheet 0011 PLUS sheet 0012, and the A-IRB
   Total averages maturity by exposure — while the Bank's ``boe_b1053``-``b1055``
   (publisher issue PI-02) and ``boe_b0748`` (PI-31) fail that correct return and
   pass the coverage book, which holds sheet 0011 alone.

References:
- PRA PS1/26 Annex II: OF 08.01 c0040 (p.103), c0070-c0080, c0090 and c0100 (p.104),
  rows 0031 / 0032 (p.116), c0250 (p.111); OF 09.02 rows 0048, 0055, 0120, 0130
  (pp.143-145)
- PRA PS1/26 Art. 147(4C), Art. 147A(1), Art. 166C(1)
- CRR Annex II C 08.01 c0040 and c0070-c0100 (pp.99-100), row 0030 (p.106)
- EBA validation rules ``v0333_m`` (the C 08.01.b rows carrying c0100) and
  ``v3354_i``-``v3370_i`` (C 08.01.a r0030 c0090 = C 08.01.b r0010 c0100)
- Bank of England publisher issues PI-02 and PI-31
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.reporting_irb_coverage_portfolio import (
    DRAWN_CORP_AIRB,
    DRAWN_FSE,
    DRAWN_LARGE,
    DRAWN_RET_NP,
    DRAWN_RET_NP_CRE,
    DRAWN_RET_SME,
    DRAWN_RET_SME_CRE,
    DRAWN_RET_SME_RRE,
    DRAWN_SME_FIRB,
    IRB_COVERAGE_EXPECTED_APPROACH,
    LIMIT_LARGE_UCC,
    LN_RET_NP_CRE,
    LN_RET_SME,
    LN_RET_SME_CRE,
    LN_RET_SME_RRE,
    NOMINAL_SME_TRADE,
    PCT_COVERED_SME_TRADE,
)
from tests.fixtures.reporting_irb_pairings_portfolio import (
    DRAWN_PAIR_AIRB,
    DRAWN_PAIR_FIRB,
    DRAWN_PAIR_SME_AIRB,
    IRB_PAIRINGS_EXPECTED_APPROACH,
)
from tests.fixtures.reporting_irb_specialised_lending_portfolio import (
    DRAWN_SL_AIRB,
    DRAWN_SL_SLOT,
    IRB_SL_EXPECTED_APPROACH,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.irb_sheets import B31_CLASS_SHEETS
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import RuleTrace
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)

CRR = "CRR"
B31 = "BASEL_3_1"
FRAMEWORKS = (CRR, B31)

IRB_CLASSES = "irb-classes"
IRB_COVERAGE = "irb-coverage"
IRB_SL = "irb-specialised-lending"
IRB_PAIRINGS = "irb-pairings"

TOTAL_ROW = "0010"
ON_BS_ROW = "0020"
TEN_PERCENT_ROW = "0031"
TWENTY_PERCENT_ROW = "0032"

#: Table A1 conversion factors of the two buckets (PS1/26 Art. 111(1), applied to
#: F-IRB by Art. 166C(1)).
UCC_CCF = 0.10
TRADE_CCF = 0.20

#: The 20% trade item split as Annex II splits it for the substitution columns —
#: "prior to the application of conversion factors, into a covered part and an
#: uncovered part" (OF 08.01 c0040), the outflow and inflow being "the covered part of
#: the original exposure pre-conversion factors" (c0070-c0080, both regimes): the
#: institution covers 480,000 of the nominal and the SME keeps 320,000.
COVERED_PRE_CCF = NOMINAL_SME_TRADE * PCT_COVERED_SME_TRADE
RETAINED_PRE_CCF = NOMINAL_SME_TRADE - COVERED_PRE_CCF
#: Their exposure values (c0110), after the item's 20% conversion factor.
COVERED_EXPOSURE_VALUE = COVERED_PRE_CCF * TRADE_CCF
RETAINED_EXPOSURE_VALUE = RETAINED_PRE_CCF * TRADE_CCF
#: Sheet 0002's off-balance-sheet items, pre-conversion factors: the outflow and the
#: inflow both stay on the FIRB-and-slotting Total, so substitution nets to nothing.
OFF_BS_NOMINAL_FIRB = LIMIT_LARGE_UCC + NOMINAL_SME_TRADE

#: The defects registering this book found (P5.81). Each is a reporting defect with no
#: RWA effect (exposure value c0110 and RWEA are right), owned by its own plan item;
#: each strict xfail below names the one it waits on, and turns XPASS when it lands.
R0_OWNER = "P1.490"
R1_OWNER = "P1.491"
R0_COVERED_POST_CCF = (
    f"OWNER: {R0_OWNER} (R0) - the IRB substitution columns c0040 / c0070 / c0080 / c0090 "
    "of C 08.01 and C 08.02 (both regimes) bind reporting/corep/crm_substitution.py"
    "::irb_protection_exprs, which reads guaranteed_portion - 'EAD covered by guarantee' "
    "(data/schemas.py), the covered part AFTER the conversion factor (96,000 on the trade "
    "item). Annex II (PS1/26 OF 08.01 c0040 p.103, c0070-c0080 and c0090 p.104; CRR "
    "C 08.01 c0070-c0090 p.100) asks for the covered part of the original exposure "
    "pre-conversion factors: 480,000. C 07.00 reads the same carrier (corep/c07.py)."
)
R1_MEMO_DROPS_INFLOW = (
    f"OWNER: {R1_OWNER} (R1) - C 08.01 / OF 08.01 and C 08.02 / OF 08.02 c0100 ('of "
    "which: off balance sheet items', an of-which of c0090, so post-substitution and "
    "pre-conversion factors; CRR Annex II p.100, PS1/26 p.104) leave the off-balance "
    "-sheet substitution INFLOW out in both regimes (corep/postpass.py::"
    "c08_off_bs_pre_ccf, recorded decision) while c0090 carries it. PRA001 makes "
    "OF08.01.01.02 r0010 c0100 and OF08.01.01.01 r0030 c0090 ONE data point, so the "
    "Basel 3.1 return files two values (STR007) and boe_b0307 fails on sheets 0002 "
    "and 0006. Sheet 0002 waits on R1 alone (outflow and inflow both land there); "
    f"every inflow sheet waits on R1 AND R0 ({R0_OWNER}) - adding today's post-CCF "
    "96,000 inflow would still be 384,000 short of 480,000."
)

#: The registered portfolio that lights each published class sheet with original
#: exposure, and that exposure where this item wrote it by hand. ``None`` marks a
#: sheet an existing portfolio already owned (its amount is pinned there).
SHEET_OWNER: dict[str, tuple[str, float | None]] = {
    "0006": (IRB_CLASSES, None),
    "0009": (IRB_SL, DRAWN_SL_AIRB),
    "0010": (IRB_SL, DRAWN_SL_SLOT),
    "0011": (IRB_COVERAGE, DRAWN_CORP_AIRB),
    "0012": (IRB_PAIRINGS, DRAWN_PAIR_FIRB),
    "0015": (IRB_CLASSES, None),
    "0016": (IRB_COVERAGE, DRAWN_RET_SME),
    "0017": (IRB_COVERAGE, DRAWN_RET_NP),
    "0018": (IRB_COVERAGE, DRAWN_RET_SME_CRE),
    "0019": (IRB_COVERAGE, DRAWN_RET_NP_CRE),
    "0020": (IRB_COVERAGE, DRAWN_RET_SME_RRE),
    "0021": (IRB_CLASSES, None),
    "0022": (IRB_COVERAGE, DRAWN_LARGE + DRAWN_FSE + LIMIT_LARGE_UCC),
    "0023": (IRB_PAIRINGS, DRAWN_PAIR_SME_AIRB),
    "0024": (IRB_COVERAGE, DRAWN_SME_FIRB + NOMINAL_SME_TRADE),
}

#: Our C 08.01 / C 08.02 keys of the class sheet each side of the guarantee lands on:
#: the institution guarantor's inflow, and the SME obligor's outflow.
INFLOW_SHEET = {CRR: "institution", B31: "institution_firb"}
OUTFLOW_SHEET = {CRR: "corporate_sme", B31: "corporate_sme_firb"}
#: Basel 3.1 only: the FIRB-and-slotting Total (published sheet 0002), where the
#: outflow and the inflow both land. CRR C 08.01 has no IRB Total sheet.
B31_FIRB_TOTAL = "total_firb_slotting"
#: Every sheet with an off-balance-sheet item and no substitution inflow.
NO_INFLOW_SHEETS = {
    CRR: ("corporate", "corporate_sme"),
    B31: ("corporate_financial_large_firb", "corporate_sme_firb"),
}
#: The off-balance-sheet row of C 08.01 / OF 08.01 (Annex II row 0030, both regimes).
OFF_BS_ROW = "0030"

#: The Bank rules a correct return with sheets 0011 and 0012, or with two
#: non-retail A-IRB sheets that report a maturity, fails (publisher issues).
PI_02_RULES = ("boe_b1053", "boe_b1054", "boe_b1055")
PI_31_RULE = "boe_b0748"

EXPECTED_APPROACH: dict[str, dict[str, tuple[str, str]]] = {
    IRB_COVERAGE: IRB_COVERAGE_EXPECTED_APPROACH,
    IRB_SL: IRB_SL_EXPECTED_APPROACH,
    IRB_PAIRINGS: IRB_PAIRINGS_EXPECTED_APPROACH,
}


class _Generated(NamedTuple):
    """One registered run, through the pipeline and the COREP generator."""

    ledger: pl.DataFrame
    corep: COREPTemplateBundle


# ---------------------------------------------------------------------------
# Every published class sheet has a registered owner
# ---------------------------------------------------------------------------


def test_every_published_class_sheet_has_an_owner() -> None:
    """The owner table covers the published axis exactly: no sheet is left dark."""
    # Arrange
    published = {sheet.code for sheet in B31_CLASS_SHEETS}

    # Act
    owned = set(SHEET_OWNER)

    # Assert
    assert owned == published


@pytest.mark.parametrize("code", sorted(SHEET_OWNER))
def test_each_published_class_sheet_is_lit_by_a_registered_run(code: str) -> None:
    # Arrange
    portfolio, expected = SHEET_OWNER[code]

    # Act
    original_exposure = _cell(_b31_sheet(portfolio, code), TOTAL_ROW, "0020")

    # Assert
    assert original_exposure is not None and original_exposure > 0.0, (
        f"sheet {code} carries no original exposure on {portfolio}"
    )
    if expected is not None:
        assert original_exposure == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("portfolio", sorted(EXPECTED_APPROACH))
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_leg_routes_to_its_designed_approach(framework: str, portfolio: str) -> None:
    """Fixture adequacy (LESSONS C11): a leg that quietly changed approach would
    land on another sheet and leave the one it was built for dark again."""
    # Arrange
    ledger = _generated(framework, portfolio).ledger
    expected = {
        reference: approaches[FRAMEWORKS.index(framework)]
        for reference, approaches in EXPECTED_APPROACH[portfolio].items()
    }

    # Act
    routed = {
        row["exposure_reference"]: row["approach_applied"]
        for row in ledger.filter(pl.col("exposure_reference").is_in(list(expected))).iter_rows(
            named=True
        )
    }

    # Assert
    assert routed == expected


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_sme_retail_legs_take_the_classifier_sme_flag(framework: str) -> None:
    """LESSONS C11(c): the SME retail sheets must be reached by the sealed ledger's
    own reclassification (managed-as-retail SME -> retail, ``is_sme`` kept), not by a
    flag the fixture sets."""
    # Arrange
    ledger = _generated(framework, IRB_COVERAGE).ledger
    expected = {
        LN_RET_SME: ("retail_other", True, None),
        LN_RET_SME_CRE: ("retail_mortgage", True, "commercial"),
        LN_RET_SME_RRE: ("retail_mortgage", True, "residential"),
        LN_RET_NP_CRE: ("retail_mortgage", False, "commercial"),
    }

    # Act
    sealed = {
        row["exposure_reference"]: (row["exposure_class"], row["is_sme"], row["property_type"])
        for row in ledger.filter(pl.col("exposure_reference").is_in(list(expected))).iter_rows(
            named=True
        )
    }

    # Assert
    assert sealed == expected


# ---------------------------------------------------------------------------
# The 10% / 20% rows and the guarantee inflow by bucket (Basel 3.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "row", "column", "expected"),
    [
        ("0022", TEN_PERCENT_ROW, "0020", LIMIT_LARGE_UCC),
        ("0022", TEN_PERCENT_ROW, "0110", LIMIT_LARGE_UCC * UCC_CCF),
        ("0002", TEN_PERCENT_ROW, "0020", LIMIT_LARGE_UCC),
        ("0024", TWENTY_PERCENT_ROW, "0020", NOMINAL_SME_TRADE),
        ("0024", TWENTY_PERCENT_ROW, "0110", RETAINED_EXPOSURE_VALUE),
        ("0006", TWENTY_PERCENT_ROW, "0110", COVERED_EXPOSURE_VALUE),
        ("0002", TWENTY_PERCENT_ROW, "0020", NOMINAL_SME_TRADE),
    ],
)
def test_coverage_files_each_off_balance_sheet_item_in_its_conversion_factor_row(
    code: str, row: str, column: str, expected: float
) -> None:
    # Arrange
    sheet = _b31_sheet(IRB_COVERAGE, code)

    # Act
    reported = _cell(sheet, row, column)

    # Assert
    assert reported == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_guarantor_sheet_holds_the_inflow_and_nothing_native(framework: str) -> None:
    """The inflow-only sheet ``d588294`` retired with the natural-person guarantor,
    restored by an Art. 201(1)(f) institution with no exposure of its own — fed by an
    off-balance-sheet leg (CRR's ``irb-mdb`` corporate sheet is fed by a drawn one).

    Every limb here holds on either basis of the substitution columns; the inflow's
    AMOUNT is pinned by the R0 xfail below."""
    # Arrange
    generated = _generated(framework, IRB_COVERAGE)
    sheet = generated.corep.c08_01[INFLOW_SHEET[framework]]
    native = generated.ledger.filter(pl.col("exposure_class") == "institution")

    # Act
    inflow = _cell(sheet, TOTAL_ROW, "0080")
    exposure_value = _cell(sheet, TOTAL_ROW, "0110")
    rwea = _cell(sheet, TOTAL_ROW, "0260")

    # Assert
    assert native.height == 0, "the guarantor has an exposure of its own: not inflow-only"
    assert _cell(sheet, ON_BS_ROW, "0020") is None
    assert inflow is not None and inflow > 0.0, "the sheet exists for no inflow"
    assert exposure_value == pytest.approx(COVERED_EXPOSURE_VALUE, rel=1e-12)
    assert rwea is not None and rwea > 0.0, "a zero crossing RWEA cannot verify a basis move"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=R0_COVERED_POST_CCF)
@pytest.mark.parametrize("column", ["0080", "0090"])
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_guarantor_sheet_inflow_is_the_covered_part_pre_conversion_factors(
    framework: str, column: str
) -> None:
    """Annex II c0070-c0080 (both regimes): the inflow is "the covered part of the
    original exposure pre-conversion factors", and c0090 on a sheet with nothing
    native is that inflow alone."""
    # Arrange
    sheet = _generated(framework, IRB_COVERAGE).corep.c08_01[INFLOW_SHEET[framework]]

    # Act
    reported = _cell(sheet, TOTAL_ROW, column)

    # Assert
    assert reported == pytest.approx(COVERED_PRE_CCF, rel=1e-12)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=R0_COVERED_POST_CCF)
@pytest.mark.parametrize(
    ("framework", "side", "row", "column", "expected"),
    [
        (B31, "outflow", TWENTY_PERCENT_ROW, "0040", -COVERED_PRE_CCF),
        (B31, "outflow", TWENTY_PERCENT_ROW, "0070", -COVERED_PRE_CCF),
        (B31, "outflow", TWENTY_PERCENT_ROW, "0090", RETAINED_PRE_CCF),
        (B31, "outflow", TOTAL_ROW, "0100", RETAINED_PRE_CCF),
        (B31, "inflow", TWENTY_PERCENT_ROW, "0080", COVERED_PRE_CCF),
        (B31, "inflow", TWENTY_PERCENT_ROW, "0090", COVERED_PRE_CCF),
        (CRR, "outflow", OFF_BS_ROW, "0070", -COVERED_PRE_CCF),
        (CRR, "outflow", OFF_BS_ROW, "0090", RETAINED_PRE_CCF),
        (CRR, "outflow", TOTAL_ROW, "0100", RETAINED_PRE_CCF),
        (CRR, "inflow", OFF_BS_ROW, "0080", COVERED_PRE_CCF),
    ],
)
def test_the_substitution_columns_split_the_trade_item_before_conversion_factors(
    framework: str, side: str, row: str, column: str, expected: float
) -> None:
    """The guarantee's covered part leaves the SME's sheet and arrives on the
    institution's at its pre-conversion-factor amount, and what stays with the SME
    (c0090, and the off-balance-sheet memo c0100) is the uncovered nominal, 320,000 —
    not the 704,000 a post-CCF outflow leaves. Basel 3.1 on the 20% row; CRR, which
    has no conversion-factor rows, on the off-balance-sheet row 0030. CRR c0040 is
    left out: CRR Annex II p.99 makes it the Art. 236(3) adjusted value GA."""
    # Arrange
    keys = INFLOW_SHEET if side == "inflow" else OUTFLOW_SHEET
    sheet = _generated(framework, IRB_COVERAGE).corep.c08_01[keys[framework]]

    # Act
    reported = _cell(sheet, row, column)

    # Assert
    assert reported == pytest.approx(expected, rel=1e-12)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=R1_MEMO_DROPS_INFLOW)
@pytest.mark.parametrize(
    ("framework", "key", "expected"),
    [
        (B31, B31_FIRB_TOTAL, OFF_BS_NOMINAL_FIRB),
        (B31, INFLOW_SHEET[B31], COVERED_PRE_CCF),
        (CRR, INFLOW_SHEET[CRR], COVERED_PRE_CCF),
    ],
)
def test_the_off_balance_sheet_memo_counts_the_inflow(
    framework: str, key: str, expected: float
) -> None:
    """C 08.01 c0100 is an of-which of c0090 (both regimes), so where an
    off-balance-sheet inflow arrives the Total row's c0100 counts it, and equals row
    0030's c0090: under Basel 3.1 the two are one PRA001 data point (OF08.01.01.02
    r0010 c0100 = OF08.01.01.01 r0030 c0090), and under CRR the EBA's live identities
    ``v3354_i``-``v3370_i`` hold C 08.01.b r0010 c0100 equal to C 08.01.a r0030 c0090
    on every sheet. Only the Total row is pinned: the published C 08.01.b carries
    c0100 on rows 0010 / 0015 / 0016 / 0070 / 0080 / 0160 / 0170 (EBA ``v0333_m``),
    not on row 0030 (LESSONS B4). Pinned to Annex II's AMOUNT rather than to row
    0030's c0090 alone: a c0100 that matched today's c0090 on the inflow sheet
    (96,000, the R0 basis) would still be wrong. Sheet 0002 waits on R1 alone; the
    others on R0 too."""
    # Arrange
    sheet = _generated(framework, IRB_COVERAGE).corep.c08_01[key]

    # Act
    memo, row_0030 = _cell(sheet, TOTAL_ROW, "0100"), _cell(sheet, OFF_BS_ROW, "0090")

    # Assert
    assert memo == pytest.approx(expected, rel=1e-12)
    assert row_0030 == pytest.approx(expected, rel=1e-12)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=R1_MEMO_DROPS_INFLOW)
@pytest.mark.parametrize(
    ("framework", "key", "expected"),
    [
        (B31, B31_FIRB_TOTAL, OFF_BS_NOMINAL_FIRB),
        (B31, INFLOW_SHEET[B31], COVERED_PRE_CCF),
        (CRR, INFLOW_SHEET[CRR], COVERED_PRE_CCF),
    ],
)
def test_the_grade_breakdown_memo_counts_the_inflow(
    framework: str, key: str, expected: float
) -> None:
    """C 08.02 / OF 08.02 share C 08.01's column block, c0100 included, so the
    grade breakdown's off-balance-sheet memo also counts the inflow. Summed over the
    sheet's grade rows: which row the inflow lands on is a separate recorded decision
    (``corep/c08.py`` ``_C08_02_INFLOW_ROW``), not what this pins."""
    # Arrange
    sheet = _generated(framework, IRB_COVERAGE).corep.c08_02[key]

    # Act
    memo = sheet["0100"].fill_null(0.0).sum()
    after_substitution = sheet["0090"].fill_null(0.0).sum()

    # Assert
    assert memo == pytest.approx(expected, rel=1e-12)
    assert after_substitution >= memo


@pytest.mark.parametrize(
    ("framework", "key"),
    [(framework, key) for framework in FRAMEWORKS for key in NO_INFLOW_SHEETS[framework]],
)
def test_the_off_balance_sheet_memo_holds_where_no_inflow_arrives(framework: str, key: str) -> None:
    """The control for the R1 xfails above (LESSONS B5), in both regimes: on a sheet
    with no inflow the memo is row 0030's exposure after substitution, outflow netted
    on the SME's sheet.

    A consistency check, true on either basis: the SME sheet's AMOUNT (320,000 pre
    -conversion factors) is pinned by the R0 xfail above."""
    # Arrange
    sheet = _generated(framework, IRB_COVERAGE).corep.c08_01[key]

    # Act
    memo, row_0030 = _cell(sheet, TOTAL_ROW, "0100"), _cell(sheet, OFF_BS_ROW, "0090")

    # Assert
    assert memo is not None and memo > 0.0
    assert memo == pytest.approx(row_0030, rel=1e-12)


# ---------------------------------------------------------------------------
# OF 09.02 sub-class rows against their OF 08.01 sheets (Basel 3.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "code", "expected_original"),
    [
        ("0048", "0022", DRAWN_LARGE + DRAWN_FSE + LIMIT_LARGE_UCC),
        ("0120", "0016", DRAWN_RET_SME),
        ("0130", "0017", DRAWN_RET_NP),
    ],
)
def test_the_of09_sub_class_row_is_its_of08_sheet(
    row: str, code: str, expected_original: float
) -> None:
    """``boe_b1034`` / ``b1051`` / ``b1052`` (r0048 = sheet 0022), ``boe_b0297`` -
    ``b0299`` (r0120 = sheet 0016) and ``boe_b0300`` - ``b0302`` (r0130 = sheet
    0017), with the SME and non-SME retail legs side by side so each row must
    pick its own."""
    # Arrange
    totals = _generated(B31, IRB_COVERAGE).corep.c09_02["TOTAL"]
    sheet = _b31_sheet(IRB_COVERAGE, code)

    # Act
    pairs = {
        column_09: (_cell(totals, row, column_09), _cell(sheet, TOTAL_ROW, column_08))
        for column_09, column_08 in (("0010", "0020"), ("0105", "0110"), ("0110", "0260"))
    }

    # Assert
    assert pairs["0010"][0] == pytest.approx(expected_original, rel=1e-12)
    for column, (of09, of08) in pairs.items():
        assert of09 == pytest.approx(of08, rel=1e-12), f"OF 09.02 r{row} c{column}"


# ---------------------------------------------------------------------------
# The pairings (Basel 3.1): our figures, and the Bank's rules on them
# ---------------------------------------------------------------------------


def test_the_other_general_corporates_row_is_both_approaches_sheets() -> None:
    """OF 09.02 r0055 (Annex II p.143) covers the general non-SME corporates of
    both approaches: sheet 0011 PLUS sheet 0012."""
    # Arrange
    totals = _generated(B31, IRB_PAIRINGS).corep.c09_02["TOTAL"]
    airb, firb = _b31_sheet(IRB_PAIRINGS, "0011"), _b31_sheet(IRB_PAIRINGS, "0012")

    # Act
    pairs = {
        column_09: (
            _cell(totals, "0055", column_09),
            (_cell(airb, TOTAL_ROW, column_08) or 0.0) + (_cell(firb, TOTAL_ROW, column_08) or 0.0),
        )
        for column_09, column_08 in (("0010", "0020"), ("0105", "0110"), ("0110", "0260"))
    }

    # Assert
    assert pairs["0010"][0] == pytest.approx(DRAWN_PAIR_AIRB + DRAWN_PAIR_FIRB, rel=1e-12)
    for column, (of09, both) in pairs.items():
        assert of09 == pytest.approx(both, rel=1e-12), f"OF 09.02 r0055 c{column}"


def test_the_airb_total_averages_maturity_by_exposure() -> None:
    """Sheet 0001 c0250 is the exposure-weighted mean of 0011 and 0023 — which the
    pairing's distinct exposures and maturities tell from a simple mean or a pick."""
    # Arrange
    airb, sme = _b31_sheet(IRB_PAIRINGS, "0011"), _b31_sheet(IRB_PAIRINGS, "0023")
    total = _b31_sheet(IRB_PAIRINGS, "0001")
    m_airb, m_sme = _cell(airb, TOTAL_ROW, "0250"), _cell(sme, TOTAL_ROW, "0250")
    e_airb, e_sme = _cell(airb, TOTAL_ROW, "0110"), _cell(sme, TOTAL_ROW, "0110")
    assert m_airb is not None and m_sme is not None and e_airb and e_sme
    assert m_airb != m_sme and e_airb != e_sme, "equal legs cannot tell the readings apart"

    # Act
    reported = _cell(total, TOTAL_ROW, "0250")

    # Assert
    assert reported == pytest.approx((m_airb * e_airb + m_sme * e_sme) / (e_airb + e_sme))
    assert reported != pytest.approx((m_airb + m_sme) / 2)


@pytest.mark.parametrize("rule_id", [*PI_02_RULES, PI_31_RULE])
def test_the_banks_faulty_rules_fail_the_pairings_and_hold_on_the_lone_sheet(
    rule_id: str,
) -> None:
    """PI-02 and PI-31 reached on the gateway engine: the pairing book fails each
    rule on a return the two tests above show is correct, and the coverage book
    (sheet 0011 alone, one non-retail A-IRB sheet) does not."""
    # Arrange / Act
    pairings = _verdicts(IRB_PAIRINGS, rule_id)
    coverage = _verdicts(IRB_COVERAGE, rule_id)

    # Assert
    assert False in pairings, f"{rule_id} holds on {IRB_PAIRINGS}: the pairing is not reached"
    assert coverage and False not in coverage, f"{rule_id} on {IRB_COVERAGE}: {coverage}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@cache
def _generated(framework: str, portfolio: str) -> _Generated:
    """The registered run of ``portfolio`` under ``framework``, generated."""
    runs = [r for r in RUNS if r.framework == framework and r.portfolio == portfolio]
    assert runs, (
        f"{framework}/{portfolio} is not registered in RUNS: its legs are outside the "
        "gated population (LESSONS B5)"
    )
    (run,) = runs
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    return _Generated(result.results.collect(), corep)


def _b31_sheet(portfolio: str, code: str) -> pl.DataFrame:
    """Published OF 08.01 sheet ``code`` of a registered Basel 3.1 run."""
    (key,) = SHEET_INDEX_MAPS["of08"][code].bundle_keys
    sheets = _generated(B31, portfolio).corep.c08_01
    assert key in sheets, f"sheet {code} ({key}) is not emitted on {portfolio}"
    return sheets[key]


def _cell(sheet: pl.DataFrame, row: str, column: str) -> float | None:
    matched = sheet.filter(pl.col("row_ref") == row)
    if matched.height == 0:
        return None
    value = matched[column][0]
    return None if value is None else float(value)


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


@cache
def _trace(portfolio: str) -> RuleTrace:
    canonical = build_canonical_return(
        _generated(B31, portfolio).corep, HEADER, pack=_pack()
    ).canonical
    validation, trace = trace_return(canonical, _pack())
    assert validation.report is not None and trace is not None, "no rule book for PRA001"
    return trace


def _verdicts(portfolio: str, rule_id: str) -> list[bool]:
    """Every place the gateway engine evaluated ``rule_id`` on ``portfolio``: holds?"""
    return [ev.holds for ev in _trace(portfolio).evaluations if ev.rule_id == rule_id]
