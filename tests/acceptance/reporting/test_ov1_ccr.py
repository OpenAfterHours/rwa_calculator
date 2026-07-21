"""
Pillar 3 OV1 — "Credit risk (excluding CCR)" must actually exclude CCR, and the
CCR block (rows 6 / 7 / 8 / UK8a / 9) must exist.

Pipeline position:
    reporting portfolio (rich | ccr) -> PipelineOrchestrator -> Pillar3Generator
        -> OV1 (+ CCR1 and CCR8, the two templates it must tie to)

The defect this file drives out (docs/plans/c07-ccr-derivatives.md §4 D1):

- **Row 1 lies.** It is labelled "Credit risk (excluding CCR)" and its cells are
  an unpredicated ``Sum(rwa_final)`` — the whole ledger. So it INCLUDES the CCR
  legs. Verbatim from the OV1 instructions: "RWEAs for securitisation exposures
  in the non-trading book and **for CCR are excluded and disclosed in rows 6 and
  16 of this template**."
- **Row 2 lies under CRR.** It keys ``approaches_origin=("standardised",
  "equity")``, and under CRR the CCR legs carry ``approach_origin ==
  "standardised"`` — so they are admitted. Under Basel 3.1 the output-floor
  relabel moves them to ``standardised_ccr`` and they drop out *by accident*,
  which is why an approach-based rule cannot be the fix: **key on ``risk_type``,
  never on the approach label** (docs/plans/c07-ccr-derivatives.md §4 D4 — the
  same trap that leaks CCR into CRR's CR4/CR5).
- **There is no CCR block at all.** Rows 6, 7, 8, UK8a and 9 are absent from both
  regimes' row lists, so the CCR RWEA the label promises to disclose "in row 6"
  is disclosed nowhere. This is a template-structure change (new ``P3Row``s), not
  a predicate tweak.

The CCR block, from the instructions (the UKB OV1 carries the identical block, so
BOTH regimes get it):

    row 6      "Counterparty credit risk - CCR" ... "in accordance with Chapter 6"
               -> a POPULATION: risk_type in {CCR_DERIVATIVE, CCR_SFT,
                  CCR_DEFAULT_FUND}. NOT Formula(7+8+UK8a+9) — defining the parent
                  as the sum of its children would make the footing test below a
                  tautology instead of an assertion.
    row 7      "Of which the standardised approach ... Section 3"  -> SA-CCR: a
               derivative NOT faced to a CCP (Art. 274-280f)
    row 8      "Of which internal model method (IMM) ... Section 6" -> NULL always;
               IMM is not implemented (CCR1 row 2 sets the precedent)
    row UK8a   "Of which exposures to a central counterparty (CCP) ... Section 9"
               -> cp_entity_type == "ccp". Section 9 is Art. 300-311 in full, so
                  it takes EVERY leg faced to a CCP: the cleared derivative, the
                  CCP-faced SFT (Art. 301(1)(b) — the section's material scope
                  reaches SFTs, not only derivatives) and the CCP default-fund
                  contribution (Art. 307-309, which sits INSIDE Section 9).
    row 9      "Of which other CCR ... RWEAs ... **that are not disclosed under
               rows 7, 8 and UK 8a**" -> the residual: a CCR leg that is none of
                  rows 7 / 8 / UK8a, which today means an SFT faced to a NON-CCP
                  counterparty. Its text settles the partition: 7/8/UK8a/9
                  partition row 6.
               NOT default-fund contributions — those are CCP exposures (UK8a).
               The routing is pinned leg-by-leg in
               tests/unit/reporting/pillar3/test_ov1_ccr_routing.py; no fixture
               carries a CCR_DEFAULT_FUND leg, so it is unreachable from here.

Row 29 (Total) and Basel 3.1's row 4a (Total RWEAs pre-floor) are ALL-RISK-TYPE
totals: they must NOT move. The fix is a re-cut of the row axis, not a change to
the book.

The tie-outs at the foot of this file are the point of the exercise — OV1, CCR1
and CCR8 describe the same netting sets, and any of them would have caught D1 on
day one:

    OV1 row 7   == CCR1 row 1 column b   (SA-CCR RWEA — the bilateral leg only)
    OV1 row UK8a == CCR8 row 1 column a  (the QCCP RWEA)
    OV1 row 6   == sum(rwa_final) over the CCR risk types (the WHOLE CCR book)
    OV1 row UK8a == CCR8 row 21 column a  (CCR8 is CCP-scoped: its Total is the
                 CCP population — a subset of the whole-CCR row 6, CRR Art. 439(i);
                 the bilateral derivative that sits in row 6 is NOT in CCR8's Total)
    OV1 row 1 + row 6 == row 29          (the footing row 1's label promised)
    OV1 row 1  != row 29 on a book with CCR  (the regression pin for D1 itself)

No CVA row (10) is asserted: the engine's BA-CVA charge is not a per-row
``rwa_final``, and is recorded as a separate gap.

References:
- CRR Part 8 Art. 438; PRA PS1/26 Annex XX (UKB OV1) — rows 1, 6, 7, 8, UK 8a, 9
- CRR Art. 274-280f (SA-CCR, Section 3); Art. 283 (IMM, Section 6);
  Art. 300-311 (exposures to a CCP, Section 9 — incl. Art. 301 material scope,
  which reaches SFTs, and Art. 307-309 default-fund contributions)
- docs/plans/c07-ccr-derivatives.md §4 D1
- tests/acceptance/reporting/test_cms1_ccr.py, test_of02_output_floor.py
  (the same defect family — a CCR row that was never bound)
- tests/unit/reporting/pillar3/test_ov1_ccr_routing.py (the leg-by-leg routing
  pin: which Chapter 6 section each CCR leg lands in)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_ccr_golden import _config as _ccr_config
from tests.acceptance.reporting.test_reporting_golden import _GOLDEN_ROOT
from tests.acceptance.reporting.test_reporting_golden import _REGIMES as _RICH_REGIMES
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# Phase 2 parity convention: group-by float sums are not bit-reproducible.
_REL = 1e-9
_ABS = 1e-6

# The three OV1 columns. Column b (T-1) is null throughout — no prior period.
_COLS: tuple[str, ...] = ("a", "b", "c")

# The CCR block, in regulatory order. ``UK8a`` follows the row list's own
# existing convention for a UK-specific insert (``UK4a``, the equity row) — no
# space, so that ``P3Row.ref`` stays a bare token.
_ROW_CCR = "6"
_ROW_SA_CCR = "7"
_ROW_IMM = "8"
_ROW_CCP = "UK8a"
_ROW_OTHER_CCR = "9"
_CCR_BLOCK: tuple[str, ...] = (_ROW_CCR, _ROW_SA_CCR, _ROW_IMM, _ROW_CCP, _ROW_OTHER_CCR)

# Rows 7 / UK8a / 9 partition row 6 (row 8 is IMM, permanently null here).
_CCR_CHILDREN: tuple[str, ...] = (_ROW_SA_CCR, _ROW_CCP, _ROW_OTHER_CCR)

# Row 1's population is the COMPLEMENT of row 6's, keyed by ``risk_type`` — never
# by the approach label. Under CRR the CCR legs carry ``approach_origin ==
# "standardised"``, so an approach-based rule no-ops exactly where the CRR defect
# lives. THREE types, not two: ``CCR_DEFAULT_FUND`` (CCP default-fund
# contributions, Art. 307-309) is a bare string literal emitted by
# ``engine/stages/ccr.py``, not a ``RiskType`` enum member.
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_DERIVATIVE", "CCR_SFT", "CCR_DEFAULT_FUND")

# (regime key, framework) — OV1 exists in BOTH regimes, unlike CMS1 / OF 02.01.
_FRAMEWORKS: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

# The rich golden subdirectory per regime (the "nothing moved" oracle).
_RICH_GOLDEN_DIR: dict[str, str] = {"crr": "crr", "b31": "b31"}


@dataclass(frozen=True)
class _Run:
    """One pipeline run: OV1, the two CCR templates it ties to, and the ledger."""

    ov1: pl.DataFrame
    ccr1: pl.DataFrame | None
    ccr8: pl.DataFrame | None
    ledger: pl.DataFrame

    def ov1_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.ov1, ref, "OV1")

    def rwa_final(self, *, ccr: bool | None = None) -> float:
        """Sum of ``rwa_final`` over a row's population (None = the whole book)."""
        data = self.ledger
        if ccr is not None:
            mask = pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
            data = data.filter(mask if ccr else ~mask)
        return float(data["rwa_final"].sum()) if data.height else 0.0


# =============================================================================
# The oracle — hand-derived expected cells (column a; column c == a x 0.08)
# =============================================================================

# (regime, portfolio) -> row_ref -> column a. A ``None`` means the cell stays
# null; every other row's column c is asserted as a x 0.08 (the own-funds shim).
#
# ccr book: one SA corporate loan (2,500,000 RWEA) + two SA-CCR netting sets — a
#   bilateral institution derivative and a QCCP-cleared one at the Art. 306 2% RW.
#   Row 1 today reports the WHOLE book; it must report the loan alone.
# rich book: 14 loans + 1 equity, NO CCR — so the CCR block is a populated ZERO
#   ("this book has no CCR" is a claim the calculator can make) and NOTHING ELSE
#   MOVES. The rich expectations are asserted against the committed goldens
#   rather than restated here (test_ov1_rich_book_changes_shape_only_never_a_number).
_EXPECTED: dict[tuple[str, str], dict[str, float | None]] = {
    ("crr", "ccr"): {
        # Credit risk EXCLUDING CCR: the term loan alone. Today: 5,358,279.37.
        "1": 2_500_000.0,
        # Of which SA: the same loan. Today: 5,358,279.37 — the CRR-specific limb
        # of the defect, because the CCR legs carry approach_origin "standardised".
        "2": 2_500_000.0,
        "3": 0.0,
        "4": 0.0,
        "UK4a": 0.0,
        "5": 0.0,
        # The CCR block — absent from the template today.
        _ROW_CCR: 2_858_279.372710047,
        _ROW_SA_CCR: 2_748_345.5506827375,
        _ROW_IMM: None,
        _ROW_CCP: 109_933.8220273095,
        _ROW_OTHER_CCR: 0.0,
        "24": None,
        # The all-risk-type total: UNCHANGED.
        "29": 5_358_279.372710047,
    },
    ("b31", "ccr"): {
        "1": 2_500_000.0,
        # UNCHANGED: the output-floor relabel already excluded the CCR legs here,
        # by accident. Row 2 must stay 2,500,000 once the exclusion is deliberate.
        "2": 2_500_000.0,
        "3": 0.0,
        "4": 0.0,
        # The pre-floor total: an all-risk-type total, UNCHANGED.
        "4a": 4_060_296.719974031,
        "5": 0.0,
        _ROW_CCR: 1_560_296.719974031,
        _ROW_SA_CCR: 1_462_778.174975654,
        _ROW_IMM: None,
        _ROW_CCP: 97_518.54499837695,
        _ROW_OTHER_CCR: 0.0,
        "24": None,
        # UNCHANGED.
        "29": 4_060_296.719974031,
    },
}

_CCR_CASES: tuple[str, ...] = ("crr", "b31")
_ALL_CASES: tuple[tuple[str, str], ...] = (
    ("crr", "rich"),
    ("crr", "ccr"),
    ("b31", "rich"),
    ("b31", "ccr"),
)


@pytest.fixture(scope="module")
def runs() -> dict[tuple[str, str], _Run]:
    """One pipeline run per (regime, portfolio) — four in all."""
    return {case: _run(*case) for case in _ALL_CASES}


# =============================================================================
# The expected cells
# =============================================================================


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_ccr_book_reports_every_row_at_its_hand_derived_value(
    regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Every OV1 row of the CCR book equals its hand-derived value.

    Column a is the RWEA, column c the 8% own-funds requirement (a x 0.08), and
    column b (T-1) is null throughout — there is no prior period.

    Arrange: the CCR reporting portfolio (one SA loan + two SA-CCR netting sets).
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  every asserted row's columns a/b/c match the oracle.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    expected = _EXPECTED[(regime, "ccr")]

    # Assert
    for ref, want_a in expected.items():
        row = run.ov1_row(ref)
        assert row["b"] is None, (
            f"[{regime}] OV1 row {ref} column b (RWEAs T-1) must stay null — there is "
            f"no prior period; got {row['b']}."
        )
        if want_a is None:
            assert row["a"] is None and row["c"] is None, (
                f"[{regime}] OV1 row {ref} must stay NULL, got a={row['a']}, "
                f"c={row['c']}. Row 8 is the internal model method (IMM), which this "
                "engine does not implement — null means 'not reported here', which is "
                "not the same claim as 0.0 (CCR1 row 2 sets the precedent)."
            )
            continue
        assert row["a"] is not None, (
            f"[{regime}] OV1 row {ref} column a is NULL — it must report "
            f"{want_a:,.6f}. The CCR block (rows {_CCR_BLOCK}) must be bound, and "
            "zero-fills on a book with no CCR."
        )
        assert row["a"] == pytest.approx(want_a, rel=_REL, abs=_ABS), (
            f"[{regime}] OV1 row {ref} column a: expected {want_a:,.6f}, got "
            f"{row['a']:,.6f}. Rows 1-5 are 'Credit risk (EXCLUDING CCR)' and its "
            f"of-which rows — they must exclude risk_type in {_CCR_RISK_TYPES}; the "
            "CCR RWEA is disclosed in row 6 and its of-which rows 7 / 8 / UK8a / 9."
        )
        assert row["c"] == pytest.approx(want_a * 0.08, rel=_REL, abs=_ABS), (
            f"[{regime}] OV1 row {ref} column c (own funds) must be 8% of column a: "
            f"expected {want_a * 0.08:,.6f}, got {row['c']}."
        )


def test_ov1_rich_book_changes_shape_only_never_a_number(
    runs: dict[tuple[str, str], _Run],
) -> None:
    """On a book with NO CCR, every pre-existing OV1 cell is byte-identical.

    The rich portfolio (14 loans + 1 equity, no derivatives, no SFTs) is the
    control: re-cutting the row axis by ``risk_type`` must move nothing at all
    there. The new CCR rows appear as populated zeros (row 8 null), and every row
    that already existed keeps the value in the committed golden.

    Arrange: the rich reporting portfolio, both regimes, and their OV1 goldens.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  every golden row_ref keeps its exact a/b/c; the CCR block is
             0.0 / 0.0 / null / 0.0 / 0.0.
    """
    for regime in _CCR_CASES:
        # Arrange
        run = runs[(regime, "rich")]
        golden = _read_ov1_golden(_RICH_GOLDEN_DIR[regime])

        # Act + Assert — nothing that already existed may move.
        for ref, want in golden.items():
            row = run.ov1_row(ref)
            for col in _COLS:
                if want[col] is None:
                    assert row[col] is None, (
                        f"[{regime}/rich] OV1 row {ref} column {col} was null in the "
                        f"golden and now reports {row[col]}. The rich book has no CCR: "
                        "the CCR re-cut must change the template's SHAPE, never a number."
                    )
                    continue
                assert row[col] == pytest.approx(want[col], rel=_REL, abs=_ABS), (
                    f"[{regime}/rich] OV1 row {ref} column {col} moved: golden "
                    f"{want[col]}, now {row[col]}. The rich book carries no CCR legs, so "
                    "excluding CCR from rows 1-5 cannot change any of its numbers."
                )

        # Assert — the new block, on a book with no CCR at all.
        for ref in (_ROW_CCR, _ROW_SA_CCR, _ROW_CCP, _ROW_OTHER_CCR):
            row = run.ov1_row(ref)
            assert row["a"] == pytest.approx(0.0, abs=_ABS), (
                f"[{regime}/rich] OV1 row {ref} must be a populated ZERO on a book with "
                f"no CCR ('this book has no counterparty credit risk' is a claim the "
                f"calculator can make), got {row['a']}."
            )
            assert row["c"] == pytest.approx(0.0, abs=_ABS), (
                f"[{regime}/rich] OV1 row {ref} column c must be 0.0, got {row['c']}."
            )
        imm = run.ov1_row(_ROW_IMM)
        assert all(imm[col] is None for col in _COLS), (
            f"[{regime}/rich] OV1 row {_ROW_IMM} (IMM) must be all-null — the internal "
            f"model method is not implemented, got {[imm[col] for col in _COLS]}."
        )


# =============================================================================
# The regression pin — the exact defect
# =============================================================================


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_row_1_excludes_the_ccr_legs(regime: str, runs: dict[tuple[str, str], _Run]) -> None:
    """Row 1 == sum(``rwa_final``) over the NON-CCR risk types, and != the Total.

    Row 1 is labelled "Credit risk (excluding CCR)" and the instructions are
    explicit: "RWEAs ... for CCR are excluded and disclosed in rows 6 and 16 of
    this template." Today row 1 is an unpredicated ``Sum(rwa_final)`` — the whole
    ledger — so on a book that HAS CCR it equals the Total, which is precisely the
    misstatement. The inequality is the pin: it can only pass if the exclusion is real.

    Arrange: the CCR reporting portfolio (a book that HAS CCR).
    Act:     run the pipeline -> Pillar 3 OV1 + the ledger behind it.
    Assert:  row 1 == the ledger's non-CCR rwa_final, and row 1 != row 29.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    non_ccr = run.rwa_final(ccr=False)
    ccr = run.rwa_final(ccr=True)
    row_1 = run.ov1_row("1")["a"]
    total = run.ov1_row("29")["a"]

    # Assert
    assert ccr > 0.0, (
        f"[{regime}] the CCR portfolio must carry CCR RWEA for this test to mean "
        "anything — the fixture has no rows with risk_type in {_CCR_RISK_TYPES}."
    )
    assert row_1 == pytest.approx(non_ccr, rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row 1 ('Credit risk EXCLUDING CCR') reports {row_1}, but the "
        f"ledger's non-CCR rwa_final is {non_ccr:,.6f} (the CCR legs carry a further "
        f"{ccr:,.6f}). Exclude by risk_type, NEVER by the approach label: under CRR the "
        "CCR legs carry approach_origin 'standardised'."
    )
    assert row_1 != pytest.approx(total, rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row 1 ({row_1}) equals row 29, the Total ({total}) — on a book "
        "that HAS counterparty credit risk. A row labelled 'excluding CCR' that equals "
        "the whole book is not excluding anything."
    )


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_standardised_of_which_row_excludes_the_ccr_legs(
    regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Row 2 ("Of which: standardised approach") is a subset of row 1, not of the book.

    Row 2 is an "of which" of row 1, so it can never exceed it. Under CRR it does
    today: it keys ``approaches_origin=("standardised", "equity")`` and the CCR legs
    carry ``"standardised"``, so row 2 reports the whole 5,358,279.37 book against a
    row-1 population that must be 2,500,000. Under Basel 3.1 the ``standardised_ccr``
    relabel already excludes them — by accident, which is exactly why the exclusion
    must be re-keyed on ``risk_type`` to hold in both regimes.

    Arrange: the CCR reporting portfolio.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  row 2 <= row 1, and row 2 carries no CCR RWEA.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    row_1 = _num(run.ov1_row("1"), "a")
    row_2 = _num(run.ov1_row("2"), "a")

    # Assert
    assert row_2 <= row_1 + _ABS, (
        f"[{regime}] OV1 row 2 ('Of which: standardised approach') reports {row_2}, "
        f"more than row 1 ({row_1}) of which it is a subset. Under CRR the CCR legs "
        "carry approach_origin 'standardised', so an approach-keyed of-which row "
        "silently re-admits everything row 1 excluded."
    )
    assert row_2 == pytest.approx(run.rwa_final(ccr=False), rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row 2 reports {row_2}; the whole non-CCR book is standardised "
        f"in this portfolio, so row 2 must equal {run.rwa_final(ccr=False):,.6f}."
    )


# =============================================================================
# The footings — the conservation the labels promise
# =============================================================================


@pytest.mark.parametrize(("regime", "portfolio"), _ALL_CASES)
def test_ov1_credit_risk_plus_ccr_foots_to_the_total(
    regime: str, portfolio: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Row 1 + row 6 == row 29, in columns a and c.

    "Credit risk (excluding CCR)" and "Counterparty credit risk - CCR" partition
    the credit-risk book by ``risk_type``, so together they ARE the Total. Row 29
    is an all-risk-type total and must not move; row 1 shrinks and row 6 appears.

    Arrange: a reporting portfolio (rich | ccr), either regime.
    Act:     run the pipeline -> Pillar 3 OV1 + the ledger.
    Assert:  row 1 + row 6 == row 29 == the ledger's whole-book rwa_final.
    """
    # Arrange + Act
    run = runs[(regime, portfolio)]
    non_ccr, ccr, total = (run.ov1_row(ref) for ref in ("1", _ROW_CCR, "29"))
    book = run.rwa_final()

    # Assert
    assert total["a"] == pytest.approx(book, rel=_REL, abs=_ABS), (
        f"[{regime}/{portfolio}] OV1 row 29 (Total) reports {total['a']} against a "
        f"ledger carrying {book:,.6f} of rwa_final. The Total is an ALL-risk-type "
        "total — the CCR re-cut must not move it."
    )
    for col in ("a", "c"):
        assert non_ccr[col] is not None and ccr[col] is not None, (
            f"[{regime}/{portfolio}] OV1 rows 1 and {_ROW_CCR} column {col} must both "
            f"be populated to foot to the Total (got {non_ccr[col]}, {ccr[col]})."
        )
        assert _num(non_ccr, col) + _num(ccr, col) == pytest.approx(
            total[col], rel=_REL, abs=_ABS
        ), (
            f"[{regime}/{portfolio}] OV1 does not foot on column {col}: row 1 "
            f"({non_ccr[col]}) + row {_ROW_CCR} ({ccr[col]}) != row 29 ({total[col]}). "
            "That footing is what row 1's label — 'excluding CCR ... disclosed in "
            "row 6' — promises."
        )


@pytest.mark.parametrize(("regime", "portfolio"), _ALL_CASES)
def test_ov1_ccr_of_which_rows_partition_the_ccr_row(
    regime: str, portfolio: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Row 7 + row UK8a + row 9 == row 6, and row 8 (IMM) is null.

    Row 9 is defined as "CCR RWEAs and own funds requirements **that are not
    disclosed under rows 7, 8 and UK 8a**" — an explicit residual, which settles
    the partition. The assertion is only meaningful because row 6 is a POPULATION
    (``risk_type`` in the CCR set) and not ``Formula(7 + 8 + UK8a + 9)``; defining
    the parent as the sum of its children turns this test into a tautology.

    Arrange: a reporting portfolio (rich | ccr), either regime.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  the three populated of-which rows sum to row 6; row 8 stays null.
    """
    # Arrange + Act
    run = runs[(regime, portfolio)]
    parent = run.ov1_row(_ROW_CCR)
    children = [run.ov1_row(ref) for ref in _CCR_CHILDREN]
    imm = run.ov1_row(_ROW_IMM)

    # Assert
    assert all(imm[col] is None for col in _COLS), (
        f"[{regime}/{portfolio}] OV1 row {_ROW_IMM} (internal model method) must be "
        f"all-null — IMM is not implemented, and null is not the same claim as 0.0 "
        f"(CCR1 row 2 is the precedent). Got {[imm[col] for col in _COLS]}."
    )
    for col in ("a", "c"):
        assert all(child[col] is not None for child in children), (
            f"[{regime}/{portfolio}] OV1 rows {_CCR_CHILDREN} column {col} must all be "
            f"populated to partition row {_ROW_CCR} (got "
            f"{[child[col] for child in children]})."
        )
        got = sum(child[col] for child in children)
        assert got == pytest.approx(parent[col], rel=_REL, abs=_ABS), (
            f"[{regime}/{portfolio}] the CCR block does not foot on column {col}: row 7 "
            f"(SA-CCR) + row UK8a (CCP) + row 9 (other CCR) = {got}, but row "
            f"{_ROW_CCR} (the CCR population) reports {parent[col]}. Rows 7/8/UK8a/9 "
            "partition row 6, with row 9 as the explicit residual."
        )


# =============================================================================
# The cross-template tie-outs — OV1, CCR1 and CCR8 describe the same netting sets
# =============================================================================


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_ccr_row_ties_to_the_ledger_and_ccr8_total_ties_to_the_ccp_row(
    regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Row 6 == the whole CCR book; CCR8 row 21 == OV1 row UK8a (the CCP subset).

    OV1 row 6 ("Counterparty credit risk - CCR") is the WHOLE CCR book and must
    tie to the sealed ledger's rwa_final over the CCR risk types. CCR8 discloses
    "Exposures to central counterparties" (CRR Art. 439(i)), so its Total (row 21)
    is the CCP population ONLY — a strict subset of row 6 — and ties to OV1's CCP
    of-which row UK8a, NOT to row 6. The bilateral (non-CCP) derivative that lives
    in row 6 must NOT appear in CCR8's Total: that over-inclusion was the R5 defect.

    Arrange: the CCR reporting portfolio (one bilateral swap + one QCCP swap).
    Act:     run the pipeline -> Pillar 3 OV1 + CCR8 + the ledger.
    Assert:  OV1 row 6 == ledger whole-CCR; CCR8 Total == OV1 UK8a < OV1 row 6.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    assert run.ccr8 is not None, f"[{regime}] CCR8 was not generated for the CCR book"
    ov1_ccr = run.ov1_row(_ROW_CCR)["a"]
    ov1_ccp = run.ov1_row(_ROW_CCP)["a"]
    ccr8_total = _one_row(run.ccr8, "21", "CCR8")["a"]
    ledger_ccr = run.rwa_final(ccr=True)

    # Assert — OV1 row 6 is the whole CCR book (unchanged by the CCR8 fix).
    assert ov1_ccr == pytest.approx(ledger_ccr, rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row {_ROW_CCR} ('Counterparty credit risk - CCR') reports "
        f"{ov1_ccr}, but the ledger carries {ledger_ccr:,.6f} of rwa_final on risk "
        f"types {_CCR_RISK_TYPES}."
    )
    # CCR8's Total is CCP-scoped: it ties to OV1's CCP row, not the whole-CCR row.
    assert ccr8_total == pytest.approx(ov1_ccp, rel=_REL, abs=_ABS), (
        f"[{regime}] CCR8 row 21 (Total) reports {ccr8_total} while OV1 row {_ROW_CCP} "
        f"('Of which exposures to a CCP') reports {ov1_ccp}. CCR8 is "
        "'Exposures to central counterparties' (Art. 439(i)) — its Total is the CCP "
        "population, which is exactly OV1's UK8a of-which row."
    )
    # The regression pin for R5: the bilateral (non-CCP) derivative sits in row 6
    # but must be EXCLUDED from CCR8's Total, so on this book CCR8 Total < row 6.
    assert ccr8_total != pytest.approx(ov1_ccr, rel=_REL, abs=_ABS), (
        f"[{regime}] CCR8 row 21 (Total, {ccr8_total}) equals OV1 row {_ROW_CCR} "
        f"(whole CCR, {ov1_ccr}) — but this book carries a bilateral (non-CCP) "
        "derivative that belongs in CCR1/CCR2, not in the CCP-exposures template. "
        "CCR8's Total swept in the whole CCR book: that is the R5 defect."
    )


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_sa_ccr_row_ties_to_ccr1(regime: str, runs: dict[tuple[str, str], _Run]) -> None:
    """Row 7 ("Of which the standardised approach") == CCR1 row 1 column b.

    Row 7 is scoped to Section 3 of Chapter 6 — SA-CCR (Art. 274-280f) — which is
    the bilateral derivative leg. CCR1 row 1 ("SA-CCR (for derivatives)") already
    publishes exactly that RWEA in column b, and deliberately EXCLUDES the
    QCCP-cleared leg (which is computed under Section 9 and belongs in row UK8a).
    Booking the QCCP trade into row 7 would make OV1 contradict CCR1 on one book.

    Arrange: the CCR reporting portfolio.
    Act:     run the pipeline -> Pillar 3 OV1 + CCR1.
    Assert:  OV1 row 7 column a == CCR1 row 1 column b.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    assert run.ccr1 is not None, f"[{regime}] CCR1 was not generated for the CCR book"
    ov1_sa_ccr = run.ov1_row(_ROW_SA_CCR)["a"]
    ccr1_sa_ccr = _one_row(run.ccr1, "1", "CCR1")["b"]

    # Assert
    assert ov1_sa_ccr == pytest.approx(ccr1_sa_ccr, rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row {_ROW_SA_CCR} ('CCR - Of which the standardised approach', "
        f"Section 3 = SA-CCR) reports {ov1_sa_ccr}, but CCR1 row 1 ('SA-CCR (for "
        f"derivatives)') column b reports {ccr1_sa_ccr}. Row 7 is the bilateral "
        "derivative RWEA only — the QCCP-cleared leg is Section 9 and belongs in UK8a."
    )


@pytest.mark.parametrize("regime", _CCR_CASES)
def test_ov1_ccp_row_ties_to_ccr8_qccp(regime: str, runs: dict[tuple[str, str], _Run]) -> None:
    """Row UK8a ("Of which exposures to a CCP") == CCR8 row 1 column a.

    Row UK8a is scoped to Section 9 of Chapter 6 (Art. 300-311 — exposures to
    CCPs), which is exactly CCR8's QCCP population: the aggregator already splits
    ``rwa_ccr_qccp_trade`` from ``rwa_ccr_default`` with those citations.

    Arrange: the CCR reporting portfolio.
    Act:     run the pipeline -> Pillar 3 OV1 + CCR8.
    Assert:  OV1 row UK8a column a == CCR8 row 1 ("Exposures to QCCPs") column a.
    """
    # Arrange + Act
    run = runs[(regime, "ccr")]
    assert run.ccr8 is not None, f"[{regime}] CCR8 was not generated for the CCR book"
    ov1_ccp = run.ov1_row(_ROW_CCP)["a"]
    ccr8_qccp = _one_row(run.ccr8, "1", "CCR8")["a"]

    # Assert
    assert ov1_ccp == pytest.approx(ccr8_qccp, rel=_REL, abs=_ABS), (
        f"[{regime}] OV1 row {_ROW_CCP} ('CCR - Of which exposures to a central "
        f"counterparty (CCP)', Section 9) reports {ov1_ccp}, but CCR8 row 1 ('Exposures "
        f"to QCCPs (total)') column a reports {ccr8_qccp} on the same book."
    )


# =============================================================================
# Helpers
# =============================================================================


def _run(regime: str, portfolio: str) -> _Run:
    """Run one reporting portfolio through one regime; keep OV1, CCR1/8, ledger."""
    if portfolio == "rich":
        bundle, config = build_reporting_bundle(), _RICH_REGIMES[regime][2]()
    else:
        bundle, config = build_reporting_ccr_bundle(), _ccr_config(regime)

    result = PipelineOrchestrator().run_with_data(bundle, config)
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        result.results, framework=_FRAMEWORKS[regime]
    )

    assert pillar3.ov1 is not None, f"[{regime}/{portfolio}] OV1 was not generated"
    return _Run(
        ov1=pillar3.ov1,
        ccr1=pillar3.ccr1,
        ccr8=pillar3.ccr8,
        ledger=result.results.collect(),
    )


def _one_row(sheet: pl.DataFrame, ref: str, label: str) -> dict[str, float | str | None]:
    """The single row of ``sheet`` with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, (
        f"expected exactly one {label} row {ref!r}, got {rows.height}. The OV1 CCR "
        f"block is rows {_CCR_BLOCK} (row 8 = IMM, permanently null) and must be added "
        "to BOTH regimes' row lists — the UKB OV1 carries the identical block."
    )
    return rows.row(0, named=True)


def _num(row: dict[str, float | str | None], col: str) -> float:
    """The cell at ``col``, asserted numeric — a reported figure, not a label or a null."""
    value = row[col]
    assert isinstance(value, int | float), f"cell {col} must be numeric, got {value!r}"
    return float(value)


def _read_ov1_golden(subdir: str) -> dict[str, dict[str, float | None]]:
    """The committed OV1 golden for a rich-portfolio regime: row_ref -> cells.

    Read-only: this file never regenerates a golden. It uses the rich goldens as
    the "nothing moved" oracle — the CCR goldens are a snapshot of the DEFECT and
    are deliberately not used as an oracle here.
    """
    path = Path(_GOLDEN_ROOT) / subdir / "pillar3__ov1.ndjson"
    rows: dict[str, dict[str, float | None]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        rows[record["row_ref"]] = {col: record[col] for col in _COLS}
    assert rows, f"OV1 golden {path} is empty"
    return rows
