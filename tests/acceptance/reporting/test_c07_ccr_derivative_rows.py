"""
COREP C 07.00 — SA-CCR derivatives in the exposure-type breakdown (rows 0100-0130).

Pipeline position:
    reporting_ccr_portfolio -> PipelineOrchestrator -> COREPGenerator
        -> C 07.00 per-obligor-class sheets

Key responsibilities (the oracle for docs/plans/c07-ccr-derivatives.md steps 3-4):
- Row 0110 ("Derivatives & Long Settlement Transactions netting sets") carries
  EVERY derivative netting set — including the QCCP-cleared one. 0110 is the
  additive parent; 0120 is its "of which" subset, not its complement.
- Row 0120 ("of which: centrally cleared through a QCCP") carries the cleared
  subset OF ROW 0110. Row 0100 is the same "of which" for SFTs (row 0090) — this
  portfolio has no SFTs, so it stays null; row 0130 (contractual cross-product
  netting) is not modelled and stays null.
- CCR exposures stay OUT of rows 0070/0080. Annex II: "Exposures that are subject
  to counterparty credit risk shall be reported in rows 0090 - 0130, and
  therefore shall not be reported in this row."
- Col 0210 ("Of which: Arising from Counterparty Credit Risk") is the CCR
  exposure value; col 0211 excludes exposures cleared through a CCP (Art. 301(1)).
- Under CRR the fix is PURELY ADDITIVE to section 2: the total row 0010 must not
  move. Under Basel 3.1 the institution sheet does not exist today (the
  ``standardised_ccr`` output-floor relabel drops derivatives off the C 07.00
  population); the fix creates it, and its total must equal C 34.01.
- C 34.01 is untouched in both regimes — C 07.00 and C 34 are NOT alternatives.
  A derivative belongs in both (C 34 analyses CCR by approach; C 07.00
  risk-weights those same exposures under SA).

References:
- COREP Annex II, C 07.00 rows 0090-0130 (exposure-type breakdown); cols 0010,
  0200, 0210, 0211 (Art. 111(2): the original exposure of a derivative IS its
  CCR exposure value; Art. 301(1): the CCP-cleared exclusion)
- CRR Art. 274(2) (SA-CCR EAD); Art. 120(1) (institution 50% RW under CRR);
  Art. 306(1)(a) (QCCP 2% RW); PS1/26 ECRA CQS 2 (institution 30% RW)
- docs/plans/c07-ccr-derivatives.md (steps 3-4)
- tests/fixtures/reporting_ccr_portfolio.py (the portfolio); the frozen goldens
  in tests/expected_outputs/reporting/ccr_{crr,b31}/
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_ccr_golden import _REGIMES, _generate_frames

_REL = 1e-9

_INSTITUTION_SHEET = "corep__c07_00__institution"
_CORPORATE_SHEET = "corep__c07_00__corporate"
_C02_FRAME = "corep__c_02_00"

# Section 2 partitions the sheet by exposure type. Rows 0100 / 0120 are "of which"
# sub-rows (of 0090 and 0110) and are deliberately NOT addends.
_C07_SECTION_2_ADDENDS: tuple[str, ...] = ("0070", "0080", "0090", "0110", "0130")

# The CCF columns (Art. 111(2): no conversion factor applies to a CCR exposure).
# Structural null in THIS portfolio — ``ccf_applied`` is not sealed on the
# ledger, so no C 07.00 sheet reports a CCF bucket at all. This is a portfolio
# fact, not a general "CCF is always null for CCR" rule.
_CCF_COLS: tuple[str, ...] = ("0160", "0170", "0171", "0180", "0190")


@dataclass(frozen=True)
class _Expected:
    """Hand-derived expectations for one regime (see the module docstring)."""

    netting_set_ead: float  # SA-CCR EAD, identical for both netting sets
    bilateral_rwea: float  # institution RW x EAD
    qccp_rwea: float  # 2% x EAD (Art. 306(1)(a))
    total_ead: float  # rows 0110 / 0010: BOTH netting sets
    total_rwea: float

    @property
    def corporate_ead(self) -> float:
        return 5_000_000.0

    @property
    def corporate_rwea(self) -> float:
        return 2_500_000.0


_EXPECTED: dict[str, _Expected] = {
    # CRR: institution RW 50% (Art. 120(1), CQS 2); QCCP RW 2% (Art. 306(1)(a)).
    "crr": _Expected(
        netting_set_ead=5_496_691.101365475,
        bilateral_rwea=2_748_345.5506827375,
        qccp_rwea=109_933.8220273095,
        total_ead=10_993_382.20273095,
        total_rwea=2_858_279.372710047,
    ),
    # Basel 3.1: institution RW 30% (PS1/26 ECRA, CQS 2); QCCP RW 2%.
    "b31": _Expected(
        netting_set_ead=4_875_927.249918847,
        bilateral_rwea=1_462_778.174975654,
        qccp_rwea=97_518.54499837695,
        total_ead=9_751_854.499837695,
        total_rwea=1_560_296.719974031,
    ),
}


@pytest.fixture(scope="module")
def ccr_frames() -> dict[str, dict[str, pl.DataFrame]]:
    """The flattened COREP/Pillar 3 frames for both regimes (one run each)."""
    return {regime_key: _generate_frames(regime_key)[0] for regime_key in _REGIMES}


# =============================================================================
# Section 2 — the exposure-type breakdown
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_row_0110_carries_every_derivative_netting_set(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Row 0110 reports ALL derivative netting sets — bilateral AND QCCP-cleared.

    Annex II row 0110 is the additive parent of the "of which" row 0120: if it
    were written as "derivative AND NOT cleared", 0120 would stop being an
    "of which" and the breakdown would not foot.

    Arrange: the CCR portfolio (one bilateral swap, one QCCP-cleared swap).
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  row 0110 cols 0010/0200 == both netting sets' EAD, 0220 == both RWEA.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    row = _row(_institution_sheet(ccr_frames[regime_key], regime_key), "0110")

    # Assert
    assert row["0010"] == pytest.approx(expected.total_ead, rel=_REL), (
        "C 07.00 row 0110 col 0010 (original exposure pre-CCF) must be the SA-CCR "
        "exposure value of BOTH derivative netting sets (Annex II col 0010, "
        f"Art. 111(2)) — expected {expected.total_ead:,.6f}, got {row['0010']}."
    )
    assert row["0200"] == pytest.approx(expected.total_ead, rel=_REL), (
        "C 07.00 row 0110 col 0200 (exposure value) must be the SA-CCR exposure "
        f"value of BOTH derivative netting sets — expected {expected.total_ead:,.6f}, "
        f"got {row['0200']}."
    )
    assert row["0220"] == pytest.approx(expected.total_rwea, rel=_REL), (
        "C 07.00 row 0110 col 0220 (RWEA) must cover BOTH derivative netting sets "
        f"— expected {expected.total_rwea:,.6f}, got {row['0220']}."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_row_0120_is_the_qccp_cleared_subset(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Row 0120 ("of which: centrally cleared through a QCCP") = the cleared set.

    Arrange: the CCR portfolio — exactly one of the two netting sets faces a QCCP.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  row 0120 carries one netting set's EAD at the 2% QCCP RW.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    row = _row(_institution_sheet(ccr_frames[regime_key], regime_key), "0120")

    # Assert
    assert row["0010"] == pytest.approx(expected.netting_set_ead, rel=_REL)
    assert row["0200"] == pytest.approx(expected.netting_set_ead, rel=_REL), (
        "C 07.00 row 0120 col 0200 must be the QCCP-cleared netting set's SA-CCR "
        f"exposure value — expected {expected.netting_set_ead:,.6f}, got {row['0200']}."
    )
    assert row["0220"] == pytest.approx(expected.qccp_rwea, rel=_REL), (
        "C 07.00 row 0120 col 0220 must be the cleared set's RWEA at the 2% QCCP "
        f"risk weight (Art. 306(1)(a)) — expected {expected.qccp_rwea:,.6f}, "
        f"got {row['0220']}."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_row_0110_contains_row_0120(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """0110 >= 0120, and the difference is exactly the bilateral netting set.

    The "of which" relation, stated as arithmetic: row 0110 minus row 0120 leaves
    the non-cleared derivative business.

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  0110 - 0120 == the bilateral netting set's EAD and RWEA.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)
    parent, of_which = _row(sheet, "0110"), _row(sheet, "0120")

    # Assert
    assert parent["0200"] >= of_which["0200"], (
        "C 07.00 row 0110 must CONTAIN row 0120 — 0120 is an 'of which' sub-row, not a sibling."
    )
    assert parent["0220"] >= of_which["0220"]
    assert parent["0200"] - of_which["0200"] == pytest.approx(expected.netting_set_ead, rel=_REL), (
        "0110 - 0120 must leave exactly the bilateral netting set's exposure value."
    )
    assert parent["0220"] - of_which["0220"] == pytest.approx(expected.bilateral_rwea, rel=_REL), (
        "0110 - 0120 must leave exactly the bilateral netting set's RWEA."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_ccr_exposures_stay_out_of_the_balance_sheet_rows(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Rows 0070/0080 exclude CCR — Annex II says so in terms.

    "Exposures that are subject to counterparty credit risk shall be reported in
    rows 0090 - 0130, and therefore shall not be reported in this row."

    Arrange: the CCR portfolio — the institution sheet holds ONLY derivatives.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  rows 0070 and 0080 are all-null (empty subsets).
    """
    # Arrange + Act
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)

    # Assert
    _assert_row_all_null(sheet, "0070", "on-balance-sheet")
    _assert_row_all_null(sheet, "0080", "off-balance-sheet")


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_sft_and_cross_product_rows_stay_null(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Rows 0090/0100 (SFTs) and 0130 (cross-product) have nothing to report.

    The portfolio has no SFTs, and contractual cross-product netting sets are not
    modelled — so populating the derivative rows must not spill into them.

    Arrange: the CCR portfolio (derivatives only, no SFTs).
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  rows 0090, 0100 and 0130 are all-null.
    """
    # Arrange + Act
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)

    # Assert
    _assert_row_all_null(sheet, "0090", "SFT netting sets (none in this portfolio)")
    _assert_row_all_null(sheet, "0100", "SFT QCCP 'of which' (no SFTs to clear)")
    _assert_row_all_null(sheet, "0130", "contractual cross-product netting (not modelled)")


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_ccf_columns_are_null_for_the_derivative_rows(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Rows 0110/0120 report no CCF bucket for THIS portfolio.

    ``ccf_applied`` is not sealed on the ledger here, so the CCF columns render
    structural null across the sheet. (Art. 111(2) means no CCF applies to a CCR
    exposure anyway — but that general rule is not what this test measures.)

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  cols 0160-0190 are null on rows 0110 and 0120.
    """
    # Arrange + Act
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)

    # Assert
    for ref in ("0110", "0120"):
        row = _row(sheet, ref)
        for col in _CCF_COLS:
            if col not in row:
                continue  # 0171 is Basel 3.1 only
            assert row[col] is None, (
                f"C 07.00 row {ref} col {col} (CCF bucket) must be null — no CCF "
                f"carrier is sealed for a CCR row (got {row[col]})."
            )


# =============================================================================
# The totals — CRR must not move; Basel 3.1 gains the sheet it was missing
# =============================================================================


def test_c07_crr_total_row_does_not_move(
    ccr_frames: dict[str, dict[str, pl.DataFrame]],
) -> None:
    """CRR: populating section 2 is PURELY ADDITIVE — the total row 0010 is fixed.

    Under CRR the derivative rows already reach C 07.00 (they carry
    ``approach_applied == "standardised"``), landing in the total and the 50% RW
    band but in no exposure-type row. Giving them their row must not change a
    single total. If a CRR total moves, the fix is wrong.

    Arrange: the CCR portfolio under CRR.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  row 0010 cols 0010/0200/0220 hold their frozen golden values.
    """
    # Arrange + Act
    expected = _EXPECTED["crr"]
    total = _row(_institution_sheet(ccr_frames["crr"], "crr"), "0010")

    # Assert
    assert total["0010"] == pytest.approx(expected.total_ead, rel=_REL)
    assert total["0200"] == pytest.approx(expected.total_ead, rel=_REL), (
        "The CRR C 07.00 total exposure value must NOT move when section 2 is "
        f"populated (expected {expected.total_ead:,.6f}, got {total['0200']})."
    )
    assert total["0220"] == pytest.approx(expected.total_rwea, rel=_REL), (
        "The CRR C 07.00 total RWEA must NOT move when section 2 is populated "
        f"(expected {expected.total_rwea:,.6f}, got {total['0220']})."
    )


def test_c07_basel31_institution_sheet_exists_and_totals_correctly(
    ccr_frames: dict[str, dict[str, pl.DataFrame]],
) -> None:
    """Basel 3.1: the derivatives are readmitted to C 07.00, so the sheet exists.

    The ``standardised_ccr`` output-floor relabel currently moves derivative rows
    off the ``"standardised"`` population filter and they vanish from C 07.00
    entirely — the SA EAD and RWEA are understated. Admitting them by
    ``risk_type`` (the precedent SFTs already set) creates the institution sheet.

    Arrange: the CCR portfolio under Basel 3.1.
    Act:     run the pipeline -> COREP C 07.00.
    Assert:  the institution sheet exists and its total row 0010 carries the full
             SA-CCR EAD and RWEA.
    """
    # Arrange + Act
    expected = _EXPECTED["b31"]
    total = _row(_institution_sheet(ccr_frames["b31"], "b31"), "0010")

    # Assert
    assert total["0200"] == pytest.approx(expected.total_ead, rel=_REL), (
        "The Basel 3.1 C 07.00 institution total exposure value must carry both "
        f"derivative netting sets (expected {expected.total_ead:,.6f}, got "
        f"{total['0200']})."
    )
    assert total["0220"] == pytest.approx(expected.total_rwea, rel=_REL), (
        "The Basel 3.1 C 07.00 institution total RWEA must carry both derivative "
        f"netting sets (expected {expected.total_rwea:,.6f}, got {total['0220']})."
    )


# =============================================================================
# Cols 0210 / 0211 — the CCR exposure value, and the CCP-cleared exclusion
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_col_0210_reports_the_ccr_exposure_value(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Col 0210 ("of which: arising from CCR") is the SA-CCR exposure value.

    Hard-coded null today. Annex II col 0200: "Exposure values for CCR business
    shall be the same as reported in column 0210".

    Arrange: the CCR portfolio — every row on the institution sheet is CCR.
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  col 0210 == the total SA-CCR EAD on the total row and on row 0110.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)

    # Assert
    for ref in ("0010", "0110"):
        assert _row(sheet, ref)["0210"] == pytest.approx(expected.total_ead, rel=_REL), (
            f"C 07.00 row {ref} col 0210 must report the CCR exposure value "
            f"(expected {expected.total_ead:,.6f}, got {_row(sheet, ref)['0210']})."
        )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_col_0211_excludes_ccp_cleared_exposures(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """Col 0211 = col 0210 minus the CCP-cleared exposures (Art. 301(1)).

    Half the derivative book is cleared through the QCCP, so 0211 must fall back
    to the bilateral netting set alone.

    Arrange: the CCR portfolio (one bilateral set, one QCCP-cleared set).
    Act:     run the pipeline -> COREP C 07.00 institution sheet.
    Assert:  col 0211 == the bilateral netting set's EAD on the total row and 0110.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    sheet = _institution_sheet(ccr_frames[regime_key], regime_key)

    # Assert
    for ref in ("0010", "0110"):
        assert _row(sheet, ref)["0211"] == pytest.approx(expected.netting_set_ead, rel=_REL), (
            f"C 07.00 row {ref} col 0211 must exclude the QCCP-cleared netting set "
            f"(Art. 301(1)) — expected the bilateral EAD "
            f"{expected.netting_set_ead:,.6f}, got {_row(sheet, ref)['0211']}."
        )


# =============================================================================
# Nothing else moves — the plain SA loan, and C 34
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c07_corporate_sheet_is_untouched(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """The plain corporate loan stays in row 0070 and keeps its numbers.

    The loan is not CCR, so the exposure-type rows 0090-0130 must stay empty on
    its sheet and the on-balance-sheet row must still carry it.

    Arrange: the CCR portfolio — one 5m drawn corporate term loan at 50% RW.
    Act:     run the pipeline -> COREP C 07.00 corporate sheet.
    Assert:  rows 0010 and 0070 carry 5,000,000 EAD / 2,500,000 RWEA; rows
             0090-0130 are all-null.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    frames = ccr_frames[regime_key]
    assert _CORPORATE_SHEET in frames, "the plain SA loan must still produce its sheet"
    sheet = frames[_CORPORATE_SHEET]

    # Assert — the loan's numbers are unchanged
    for ref in ("0010", "0070"):
        row = _row(sheet, ref)
        assert row["0010"] == pytest.approx(expected.corporate_ead, rel=_REL)
        assert row["0200"] == pytest.approx(expected.corporate_ead, rel=_REL), (
            f"C 07.00 corporate row {ref} col 0200 must be unchanged at "
            f"{expected.corporate_ead:,.2f} (got {row['0200']})."
        )
        assert row["0220"] == pytest.approx(expected.corporate_rwea, rel=_REL), (
            f"C 07.00 corporate row {ref} col 0220 must be unchanged at "
            f"{expected.corporate_rwea:,.2f} (got {row['0220']})."
        )

    # Assert — no CCR row leaked onto the corporate sheet
    for ref in ("0090", "0100", "0110", "0120", "0130"):
        _assert_row_all_null(sheet, ref, "the corporate loan is not a CCR exposure")


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c34_01_is_untouched_by_the_c07_fix(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """C 34.01 keeps the full SA-CCR EAD and RWEA — C 07.00 is not an alternative.

    C 34 analyses CCR by approach; C 07.00 risk-weights those same exposures under
    SA. A derivative belongs in BOTH, and no roll-up sums the two templates
    together, so admitting them to C 07.00 must move nothing in C 34.

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 34.01.
    Assert:  the SA-CCR row still carries the full EAD (col 0010) and RWEA (0020).
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    c34_01 = ccr_frames[regime_key]["corep__c34_01"]
    row = _row(c34_01, "0010")

    # Assert
    assert row["0010"] == pytest.approx(expected.total_ead, rel=_REL), (
        f"C 34.01 SA-CCR EAD must be unchanged at {expected.total_ead:,.6f} (got {row['0010']})."
    )
    assert row["0020"] == pytest.approx(expected.total_rwea, rel=_REL), (
        f"C 34.01 SA-CCR RWEA must be unchanged at {expected.total_rwea:,.6f} (got {row['0020']})."
    )


# =============================================================================
# Tie-outs — the cross-template arithmetic that would have caught all of this
#
# The C 07.00 defect survived because nothing tied the templates to each other:
# C 07.00 could drop a whole netting set and no other test noticed. These three
# are the lasting guard (docs/plans/c07-ccr-derivatives.md step 6).
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_tieout_c07_total_equals_c02_standardised_row(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """TIE-OUT: sum(C 07.00 row 0010 col 0220) == C 02.00 row 0060.

    Annex II defines C 02.00's "Of which: Standardised Approach (SA)" row as the
    "CR SA and SEC SA templates at the level of total exposures" — so the SA row
    IS the C 07.00 total, summed over every exposure-class sheet. This portfolio
    has no securitisations and no equity, so C 07.00 alone must account for it.

    This is the tie-out whose absence let the defect live: under Basel 3.1 the
    derivatives are on C 07.00 (steps 3-4) but not in C 02.00's SA row, and no
    test compared the two.

    Arrange: the CCR portfolio (SA-only — no SEC, no equity, no IRB).
    Act:     run the pipeline -> COREP C 07.00 (all sheets) + C 02.00.
    Assert:  the C 07.00 RWEA total across sheets == C 02.00 row 0060.
    """
    # Arrange + Act
    frames = ccr_frames[regime_key]
    c07_rwea = sum(float(_row(sheet, "0010")["0220"] or 0.0) for sheet in _c07_sheets(frames))
    c02_sa_rwea = float(_row(frames[_C02_FRAME], "0060")["0010"] or 0.0)

    # Assert
    assert c07_rwea == pytest.approx(c02_sa_rwea, rel=_REL), (
        f"[{regime_key}] TIE-OUT BROKEN: C 07.00 reports {c07_rwea:,.6f} of SA RWEA "
        f"across its sheets, but C 02.00 row 0060 ('Of which: SA') reports "
        f"{c02_sa_rwea:,.6f}. Annex II defines that row as the CR SA template at the "
        "level of total exposures — they must be the same number."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_tieout_c34_derivative_rwea_is_conserved_in_c07_row_0110(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """TIE-OUT: C 34.01 RWEA (col 0020) == sum(C 07.00 row 0110 col 0220).

    A CONSERVATION check, not an exclusivity one: a derivative belongs in BOTH
    templates. C 34 analyses CCR by approach; C 07.00 risk-weights those same
    exposures under SA. Every pound of SA-CCR RWEA reported in C 34.01 must
    therefore also appear in C 07.00's derivative row — no loss, no invention.

    (The mirror of tests/acceptance/reporting/test_reporting_sft_c07_0090.py,
    which makes the same check for FCCM SFTs — those are EXCLUSIVE to C 07.00
    row 0090, which is why that test asserts C 34 is empty and this one does not.)

    Arrange: the CCR portfolio (two SA-CCR derivative netting sets).
    Act:     run the pipeline -> COREP C 34.01 + C 07.00.
    Assert:  the two templates report the same derivative RWEA.
    """
    # Arrange + Act
    frames = ccr_frames[regime_key]
    c34_rwea = float(frames["corep__c34_01"]["0020"].fill_null(0.0).sum())
    c07_0110_rwea = sum(float(_row(sheet, "0110")["0220"] or 0.0) for sheet in _c07_sheets(frames))

    # Assert
    assert c34_rwea > 0.0, "Precondition: C 34.01 must report the SA-CCR derivatives."
    assert c07_0110_rwea == pytest.approx(c34_rwea, rel=_REL), (
        f"[{regime_key}] CONSERVATION BROKEN: C 34.01 reports {c34_rwea:,.6f} of "
        f"SA-CCR derivative RWEA, but C 07.00 row 0110 reports {c07_0110_rwea:,.6f} "
        "across its sheets. A derivative belongs in both templates — C 07.00 and "
        "C 34 are not alternatives."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_tieout_c07_section_2_foots_to_the_total_row(
    regime_key: str, ccr_frames: dict[str, dict[str, pl.DataFrame]]
) -> None:
    """TIE-OUT: on every sheet, rows 0070+0080+0090+0110+0130 == row 0010.

    Section 2 is the exposure-type breakdown of the total: on-balance-sheet,
    off-balance-sheet, SFT netting sets, derivative netting sets, and contractual
    cross-product netting sets. They partition the sheet, so they must foot to it.
    (0100 and 0120 are "of which" sub-rows of 0090 and 0110 — they are NOT
    addends, and including them would double-count.)

    This is the check that was silently false before steps 3-4: row 0110 was inert,
    so a sheet of pure derivatives footed to zero against a non-zero total.

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 07.00 (every sheet).
    Assert:  the section-2 addends sum to row 0010, for exposure value (col 0200)
             and RWEA (col 0220).
    """
    # Arrange + Act
    sheets = {
        key: sheet
        for key, sheet in ccr_frames[regime_key].items()
        if key.startswith("corep__c07_00__")
    }
    assert sheets, f"[{regime_key}] no C 07.00 sheet was produced at all."

    # Assert
    for key, sheet in sorted(sheets.items()):
        total = _row(sheet, "0010")
        for col, what in (("0200", "exposure value"), ("0220", "RWEA")):
            addends = {ref: _row(sheet, ref)[col] or 0.0 for ref in _C07_SECTION_2_ADDENDS}
            breakdown = sum(float(value) for value in addends.values())
            assert breakdown == pytest.approx(float(total[col] or 0.0), rel=_REL), (
                f"[{regime_key}] {key} does not foot: the section-2 breakdown of "
                f"{what} (col {col}) sums to {breakdown:,.6f} but the total row 0010 "
                f"reports {total[col]}. Addends: {addends}."
            )


# =============================================================================
# Helpers
# =============================================================================


def _c07_sheets(frames: dict[str, pl.DataFrame]) -> list[pl.DataFrame]:
    """Every C 07.00 exposure-class sheet (the SA template, in full)."""
    return [sheet for key, sheet in sorted(frames.items()) if key.startswith("corep__c07_00__")]


def _institution_sheet(frames: dict[str, pl.DataFrame], regime_key: str) -> pl.DataFrame:
    """The C 07.00 institution sheet — where every derivative netting set lands."""
    assert _INSTITUTION_SHEET in frames, (
        f"[{regime_key}] no C 07.00 institution sheet was produced — the SA-CCR "
        "derivative netting sets never reached C 07.00. Annex II requires them in "
        f"rows 0090-0130. Sheets present: {sorted(k for k in frames if 'c07' in k)}"
    )
    return frames[_INSTITUTION_SHEET]


def _row(sheet: pl.DataFrame, ref: str) -> dict[str, float | str | None]:
    """The single template row with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"expected exactly one row {ref}, got {rows.height}"
    return rows.row(0, named=True)


def _assert_row_all_null(sheet: pl.DataFrame, ref: str, why: str) -> None:
    """Every value cell of the row is null (the empty/inert-row contract)."""
    row = _row(sheet, ref)
    populated = {
        col: value
        for col, value in row.items()
        if col not in ("row_ref", "row_name") and value is not None
    }
    assert not populated, f"C 07.00 row {ref} must be all-null ({why}) — got {populated}"
