"""
Pillar 3 CMS1 — the Total must be a total: the CCR legs belong in the comparison.

Pipeline position:
    reporting portfolio (rich | ccr) -> PipelineOrchestrator -> Pillar3Generator
        -> CMS1 (+ CMS2 and C 02.00, the two oracles it must tie to)

The defect this file drives out (docs/plans/c07-ccr-derivatives.md §4 D2):

- **Columns.** ``cms1.py`` splits the book with TWO allow-lists —
  ``MODELLED_APPROACHES = (foundation_irb, advanced_irb, slotting)`` and
  ``STANDARDISED_APPROACHES = (standardised, equity)``. The second one omits
  ``standardised_ccr``, so every SA-CCR leg (derivatives, FCCM SFTs) matches
  NEITHER column a NOR column b — and column c, defined by Annex II as "the sum
  of cells 0010/a and 0010/b", silently drops them. Column b must be the
  COMPLEMENT of the modelled set, not an allow-list: that is the only shape in
  which a + b is the whole book, and an allow-list is exactly how this bug got in.
- **Rows.** Row 0010 is scoped "excludes ... capital requirements relating to a
  counterparty credit risk charge, **which are reported in row 0020**". Today
  row 0010 and row 0080 (Total) are given IDENTICAL cell specs and row 0020 is
  never bound, so the CCR row renders null and the "Total" is not a total.
- **Column d.** "RWA as would result from applying the ... standardised approach
  to **all** exposures giving rise to the RWA reported in cell 0010/c" — the
  SA-equivalent of *that row's* population. Today it is ``Sum(sa_rwa)`` with no
  predicate at all: the whole book, on every row. Measured on the CCR portfolio,
  row 0010 reports column c = 2,500,000 against column d = 4,060,296.72 — the row
  compares its own RWA against the SA-equivalent of a book it does not contain.

The internal oracle, and why no PDF is needed to know CMS1 is the wrong one:
**CMS1 Total column c = 2,500,000 while CMS2 Total column c = 4,060,296.72** on
the same book — a 1,560,296.72 disagreement, exactly the derivative RWEA. CMS2
computes its total over the whole ledger with no approach filter, so it is right;
CMS1's allow-list is what loses the legs. ``test_cms1_total_ties_to_cms2_total``
is that oracle, made permanent.

The partition:

    column a  MODELLED     = reporting_approach_origin in
                             {foundation_irb, advanced_irb, slotting}
    column b  STANDARDISED = everything else ({standardised, standardised_ccr, equity})
                             — equity included: "exposures calculated according to
                             the SA for credit risk include equity exposures
                             subject to the IRB Equity Transitional"
    row 0010  risk_type NOT IN {CCR_DERIVATIVE, CCR_SFT, CCR_DEFAULT_FUND}
    row 0020  risk_type     IN {CCR_DERIVATIVE, CCR_SFT, CCR_DEFAULT_FUND}
    row 0080  the whole book — and therefore rows 0010 + 0020

Columns a/b keep ``rwa_final`` (their existing carrier — the pre/post-floor
question is a separate recorded item, and is not what this file is about).

Rows 0030-0070 (CVA / securitisation / market / operational / residual) stay
all-null: genuinely out of scope for a credit-risk calculator, and null is not
the same claim as 0.0.

CMS1 is Basel-3.1-only (CRR returns ``None``), so this file parametrises over the
two Basel 3.1 portfolios — the rich book (F-IRB + A-IRB + slotting + SA + equity,
no CCR) and the CCR book (one SA loan + two SA-CCR netting sets, no models at
all). The CCR book is the sharper oracle: a book with no models must report zero
in column a, and its Total must carry all 4,060,296.72 of RWA, not 2,500,000.

References:
- PRA PS1/26 Annex II (UKB CMS1 instructions), rows 0010/0020/0080, cells a-d;
  Art. 456(1)(a)
- CRR Art. 153(5) (supervisory slotting — an IRB-chapter approach)
- docs/plans/c07-ccr-derivatives.md §4 D2
- tests/acceptance/reporting/test_of02_output_floor.py (the same defect family)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_ccr_golden import _config as _ccr_config
from tests.acceptance.reporting.test_reporting_golden import _REGIMES as _RICH_REGIMES
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.domain.enums import ExposureClass, RiskType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# Phase 2 parity convention: group-by float sums are not bit-reproducible.
_REL = 1e-9
_ABS = 1e-6

# The four CMS1 columns.
_COLS: tuple[str, ...] = ("a", "b", "c", "d")

# The three CMS1 rows that are populated in all four columns.
_ROWS: tuple[str, ...] = ("0010", "0020", "0080")

# Out of scope for a credit-risk calculator — null, not zero.
#
# Row 0070 ("Residual RWA") left this set with P2.54: it is where PS1/26 puts "the
# RWA arising from equity investments in funds (rows 12 to 14 in Template OV1)",
# which IS in a credit-risk calculator's scope. It is not in ``_ROWS`` either,
# because its column a is legitimately null — see
# ``test_cms1_residual_row_carries_the_equity_investments_in_funds``, which owns it
# and asserts the published 0080 = 0010 + ... + 0070 footing over it.
_NULL_ROWS: tuple[str, ...] = ("0030", "0040", "0050", "0060")

#: The published row 0080 decomposition: "The total sum of cells 0010/c, 0020/c,
#: 0030/c, 0040/c, 0050/c, 0060/c and 0070/c".
_TOTAL_TERMS: tuple[str, ...] = ("0010", "0020", "0030", "0040", "0050", "0060", "0070")

#: Row 0070 on each portfolio, columns b/c/d. ``rich`` carries the two
#: Art. 112(1)(o) CIU legs (2,000,000 at the Art. 132(2) 1,250% fall-back +
#: 4,000,000 at a 75% mandate weight); ``ccr`` holds no equity investments in funds
#: at all, so the row is null rather than a populated zero — "not reported here",
#: which is a different claim from "nil". Column a is null on BOTH: a CIU is never
#: modelled, and the published 0080/a formula omits 0070/a.
_RESIDUAL_BCD: dict[str, float | None] = {"rich": 28_000_000.0, "ccr": None}

# Row 0020's population ("Counterparty credit risk"). Keyed by risk_type, never by
# the approach label: under CRR the CCR legs carry ``standardised`` and under Basel
# 3.1 ``standardised_ccr``, so an approach-based row rule would no-op.
#
# THREE types, not two: ``"CCR_DEFAULT_FUND"`` (CCP default-fund contributions,
# Art. 307-309 — a Chapter 6 counterparty-credit-risk charge) is a bare string
# literal emitted by ``engine/stages/ccr.py``, not a ``RiskType`` enum member, so it
# cannot be written as ``RiskType.CCR_DEFAULT_FUND.value``. Do not "tidy" this back
# to two enum members — that is the exact oracle/implementation drift this file was
# written to catch (mirrors ``src/rwa_calc/reporting/pillar3/cms1.py``).
_CCR_RISK_TYPES: tuple[str, ...] = (
    RiskType.CCR_DERIVATIVE.value,
    RiskType.CCR_SFT.value,
    "CCR_DEFAULT_FUND",
)


@dataclass(frozen=True)
class _Run:
    """One Basel 3.1 pipeline run: CMS1 plus the two oracles and the ledger."""

    cms1: pl.DataFrame
    cms2: pl.DataFrame
    c02: pl.DataFrame
    ledger: pl.DataFrame

    def cms1_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.cms1, ref, "CMS1")

    def cms2_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.cms2, ref, "CMS2")

    def c02_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.c02, ref, "C 02.00")

    def rwa_final(self, *, ccr: bool | None = None, residual: bool | None = None) -> float:
        """Sum of ``rwa_final`` over a row's population (None = the whole book)."""
        return self._sum("rwa_final", ccr=ccr, residual=residual)

    def sa_rwa(self, *, ccr: bool | None = None, residual: bool | None = None) -> float:
        """Sum of ``sa_rwa`` over a row's population (None = the whole book)."""
        return self._sum("sa_rwa", ccr=ccr, residual=residual)

    def _sum(self, col: str, *, ccr: bool | None, residual: bool | None) -> float:
        """``ccr`` selects row 0020's risk types; ``residual`` selects row 0070's class.

        The CMS1 row axis cuts the book on BOTH, and on different carriers: row
        0020 on ``risk_type`` and row 0070 on the Art. 112(1)(o) exposure class
        (PS1/26 row 0070 = "the RWA arising from equity investments in funds").
        Row 0010 is the complement of both — ``ccr=False, residual=False`` — and
        reading it as the complement of the risk types alone over-counts it by the
        whole CIU book, which is what P2.54 made observable.
        """
        data = self.ledger
        if ccr is not None:
            mask = pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
            data = data.filter(mask if ccr else ~mask)
        if residual is not None:
            is_ciu = (pl.col("exposure_class") == ExposureClass.CIU.value).fill_null(value=False)
            data = data.filter(is_ciu if residual else ~is_ciu)
        return float(data[col].sum()) if data.height else 0.0


# =============================================================================
# The oracle — hand-derived expected cells
# =============================================================================

# portfolio -> row_ref -> column_ref -> value.
#
# rich: 14 loans + 1 equity + 2 CIUs, NO CCR. Modelled = F-IRB 48,244,060.92 +
#   A-IRB 14,625,069.66 + slotting 52,500,000.00 = 115,369,130.58; standardised =
#   the SA book + equity + CIU = 50,080,833.33. They sum to the whole portfolio
#   (== C 02.00 row 0010 TREA). Column d is the book's whole sa_rwa:
#   192,155,833.33 — including equity's own 2,500,000 and the CIU legs' 28,000,000
#   standardised-equivalent RWA (B31 equity is SA-only, Art. 147A; the aggregator
#   populates an equity-table leg's sa_rwa as its rwa — R4).
#   Row 0020 is a populated ZERO — the book has no CCR, which is a claim the
#   calculator can make; Total therefore equals row 0010.
#
#   **P2.54 widened column b and the c/d TOTALS by 28,000,000 — and row 0010 did
#   NOT move.** The two Art. 112(1)(o) CIU legs land in row 0070 "Residual RWA",
#   not in row 0010, because PS1/26's row 0070 instruction reads "RWA not captured
#   within rows 0010 to 0060 (ie the RWA arising from equity investments in funds
#   (rows 12 to 14 in Template OV1), settlement risk ...)". Row 0080's published
#   formula is the sum of rows 0010 to 0070, so the Total keeps them. The COLUMN
#   partition is unaffected by either: a CIU is a standardised-approach exposure
#   (Art. 132/132A sit in the Credit Risk: Standardised Approach (CRR) Part), so
#   it is in b, not a. Column a of row 0070 is NULL rather than 0.00, which the
#   published 0080/a formula corroborates — it sums 0010/a, 0020/a, 0040/a and
#   0050/a and does not mention 0070/a at all.
# ccr: one SA corporate loan (2,500,000) + two SA-CCR netting sets (1,560,296.72).
#   No models at all -> column a is 0.0 EVERYWHERE, and every row is degenerate
#   (b == c == d) because a 100%-standardised book IS its own SA equivalent.
#   Today CMS1 reports Total c = 2,500,000: the derivative legs match neither
#   approach allow-list and vanish.
_EXPECTED: dict[str, dict[str, dict[str, float]]] = {
    "rich": {
        "0010": {
            "a": 115_369_130.58029616,
            "b": 22_080_833.333333332,
            "c": 137_449_963.9136295,
            "d": 164_155_833.3333333,
        },
        "0020": {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0},
        "0080": {
            "a": 115_369_130.58029616,
            "b": 50_080_833.33333333,
            "c": 165_449_963.91362947,
            "d": 192_155_833.3333333,
        },
    },
    "ccr": {
        "0010": {"a": 0.0, "b": 2_500_000.0, "c": 2_500_000.0, "d": 2_500_000.0},
        "0020": {
            "a": 0.0,
            "b": 1_560_296.719974031,
            "c": 1_560_296.719974031,
            "d": 1_560_296.719974031,
        },
        "0080": {
            "a": 0.0,
            "b": 4_060_296.719974031,
            "c": 4_060_296.719974031,
            "d": 4_060_296.719974031,
        },
    },
}

_PORTFOLIOS: tuple[str, ...] = tuple(_EXPECTED)


@pytest.fixture(scope="module")
def runs() -> dict[str, _Run]:
    """One Basel 3.1 pipeline run per portfolio (rich, ccr)."""
    return {portfolio: _run(portfolio) for portfolio in _PORTFOLIOS}


# =============================================================================
# The expected cells
# =============================================================================


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
@pytest.mark.parametrize("row_ref", _ROWS)
def test_cms1_populated_rows_report_the_modelled_standardised_partition(
    portfolio: str, row_ref: str, runs: dict[str, _Run]
) -> None:
    """Every populated CMS1 cell equals its hand-derived value.

    Column a (modelled) and column b (its complement) partition the row's
    population; column c = a + b; column d is the SA-equivalent of that same
    population — not of the whole book.

    Arrange: a Basel 3.1 reporting portfolio (rich | ccr).
    Act:     run the pipeline -> Pillar 3 CMS1.
    Assert:  all four cells of the row match the oracle.
    """
    # Arrange + Act
    run = runs[portfolio]
    expected = _EXPECTED[portfolio][row_ref]
    row = run.cms1_row(row_ref)

    # Assert
    for col in _COLS:
        actual = row[col]
        assert actual is not None, (
            f"[{portfolio}] CMS1 row {row_ref} column {col} is NULL — it must report "
            f"{expected[col]:,.6f}. Rows 0010 (credit risk excl. CCR), 0020 "
            "(counterparty credit risk — 'reported in row 0020') and 0080 (Total) are "
            "all populated rows; only 0030-0070 are out of scope."
        )
        assert actual == pytest.approx(expected[col], rel=_REL, abs=_ABS), (
            f"[{portfolio}] CMS1 row {row_ref} column {col}: expected "
            f"{expected[col]:,.6f}, got {actual:,.6f}. Column a is the MODELLED "
            "partition (F-IRB + A-IRB + slotting); column b is its COMPLEMENT (SA + "
            "SA-CCR + equity — not an allow-list, which is what drops the SA-CCR legs); "
            "c = a + b; d = sa_rwa over the row's own population."
        )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_out_of_scope_rows_stay_null(portfolio: str, runs: dict[str, _Run]) -> None:
    """Rows 0030-0070 (CVA, securitisation, market, op risk, residual) stay all-null.

    A credit-risk calculator has nothing to say about them — null means "not
    reported here", which is not the same claim as 0.0. Row 0020 is NOT in this
    set: "no CCR in this book" is a claim the calculator can make.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> Pillar 3 CMS1.
    Assert:  every cell of rows 0030-0060 is null.
    """
    # Arrange + Act
    run = runs[portfolio]

    # Assert
    for row_ref in _NULL_ROWS:
        row = run.cms1_row(row_ref)
        assert all(row[col] is None for col in _COLS), (
            f"[{portfolio}] CMS1 row {row_ref} must be all-null (out of scope for a "
            f"credit-risk calculator), got {[row[col] for col in _COLS]}."
        )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_residual_row_carries_the_equity_investments_in_funds(
    portfolio: str, runs: dict[str, _Run]
) -> None:
    """Row 0070 is where the Art. 112(1)(o) CIU RWA goes, and row 0080 keeps it.

    PS1/26, UKB CMS1 row 0070: "RWA not captured within rows 0010 to 0060 (ie the
    RWA arising from equity investments in funds (rows 12 to 14 in Template OV1),
    settlement risk (row 15 in Template OV1), ...)". So a CIU is NOT in row 0010 —
    which is why CMS2, whose population is "as in row 1 of Template CMS1", excludes
    it too — and IS in row 0080, whose published formula sums 0010/c to 0070/c.

    The footing is the assertion that makes the two halves inseparable: binding
    row 0070 without shedding the CIU from row 0010 double-counts it in the Total,
    and shedding it from 0010 without binding 0070 loses it altogether. Neither is
    visible from either cell alone.

    ``test_cms1_row_axis_foots_to_the_total`` holds the footing itself, over the
    published term list; this test holds the cell.

    Arrange: a Basel 3.1 reporting portfolio (rich carries two CIU legs, ccr none).
    Act:     run the pipeline -> Pillar 3 CMS1.
    Assert:  row 0070 b/c/d carry the CIU RWEA (null where the book has none) and
             column a is null.
    """
    # Arrange + Act
    run = runs[portfolio]
    residual = run.cms1_row("0070")
    expected = _RESIDUAL_BCD[portfolio]

    # Assert
    assert residual["a"] is None, (
        f"[{portfolio}] CMS1 row 0070 column a reports {residual['a']}; 'equity "
        "investments in funds' are never modelled, and the published 0080/a formula "
        "sums 0010/a, 0020/a, 0040/a and 0050/a without mentioning 0070/a."
    )
    for col in ("b", "c", "d"):
        if expected is None:
            assert residual[col] is None, (
                f"[{portfolio}] CMS1 row 0070 column {col} reports {residual[col]} on a "
                "book with no equity investments in funds — null is 'not reported here', "
                "which is not the same claim as 0.00."
            )
            continue
        assert residual[col] == pytest.approx(expected, rel=_REL, abs=_ABS), (
            f"[{portfolio}] CMS1 row 0070 column {col} reports {residual[col]}, expected "
            f"the Article 112(1)(o) CIU RWEA {expected:,.2f}."
        )


# =============================================================================
# The unconditional tie-outs — the lasting guard
# =============================================================================


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_total_ties_to_cms2_total(portfolio: str, runs: dict[str, _Run]) -> None:
    """CMS1 (row 0080 - row 0070) column c == CMS2 row 0070 column c — the oracle.

    CMS1 and CMS2 are the same book cut two ways (by risk type, by asset class), so
    the RWA in the scope they SHARE is ONE number. CMS2 sums ``rwa_final`` over its
    own population with no approach filter and is therefore right about the
    approach split; CMS1 sums two approach allow-lists whose union is not the book.
    On the CCR portfolio they disagree by 1,560,296.72 — exactly the derivative
    RWEA. This test is that disagreement, made permanent.

    **Why the subtraction, and why it is a TIGHTER claim than the bare Total.**
    This asserted ``CMS1 0080/c == CMS2 0070/c`` while CMS1 rows 0030-0070 were all
    empty, so the Total WAS the shared scope and the form did not matter. P2.54
    ended that: the Art. 112(1)(o) CIU legs populate CMS1 row 0070 ("Residual RWA"
    — PS1/26: "the RWA arising from equity investments in funds (rows 12 to 14 in
    Template OV1)"), which row 0080 includes by its published formula and which
    CMS2 excludes, because CMS2's population is "as in row 1 of Template CMS1". So
    the relation between the two disclosures is now CMS1's Total LESS the rows CMS2
    does not carry, and stating it that way keeps both halves honest: dropping a
    population from CMS1 alone, or from CMS2 alone, still breaks it.

    **The published form is ``CMS2 0070/c == CMS1 0010/c``, and the gap to it is
    ASSERTED rather than described.** CMS2 §1: "As in row 1 of Template CMS1, it
    excludes counterparty credit risk, credit valuation adjustments and
    securitisation exposures in the banking book." CMS2 implements the CIU half of
    that and not the CCR half: measured on the ``ccr`` book its row 0070 column c
    is 4,060,296.72 — the whole book, SA-CCR legs included — against CMS1 row
    0010's 2,500,000. So the published form holds exactly on a CCR-free book and
    is short by precisely the CCR charge on a CCR-bearing one, and both are
    asserted below, keyed on which kind of book this is. Pre-existing, masked by
    the old 0080 form, and owed its own item; when CMS2 narrows, the second branch
    goes red, the subtraction above becomes redundant, and both can collapse into
    the published equality.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> Pillar 3 CMS1 + CMS2.
    Assert:  CMS1 0080/c - CMS1 0070/c == CMS2 0070/c; and the published
             ``CMS2 0070/c == CMS1 0010/c`` exactly, less the CCR charge.
    """
    # Arrange + Act
    run = runs[portfolio]
    cms1_total = _num(run.cms1_row("0080"), "c")
    cms1_residual = run.cms1_row("0070")["c"] or 0.0
    cms1_credit_risk = _num(run.cms1_row("0010"), "c")
    ccr_charge = _num(run.cms1_row("0020"), "c")
    cms2_total = _num(run.cms2_row("0070"), "c")

    # Assert
    assert cms1_total - cms1_residual == pytest.approx(cms2_total, rel=_REL, abs=_ABS), (
        f"[{portfolio}] the two output-floor comparison disclosures disagree on the RWA "
        f"they share: CMS1 row 0080 column c reports {cms1_total} less row 0070's "
        f"{cms1_residual}, CMS2 row 0070 column c reports {cms2_total} (difference "
        f"{(cms2_total or 0.0) - (cms1_total - cms1_residual):,.6f}). Two known causes, "
        "and the sign tells them apart: CMS1 LOW means CMS1's two approach allow-lists "
        "omit standardised_ccr so the SA-CCR legs fall into neither column a nor column "
        "b; CMS1 HIGH by the Art. 112(1)(o) CIU RWEA means that population is counted "
        "in a CMS1 row other than 0070 while CMS2 excludes it."
    )
    assert (ccr_charge > 0.0) == (portfolio == "ccr"), (
        f"[{portfolio}] CMS1 row 0020 reports a CCR charge of {ccr_charge}; this test "
        "branches on whether the book HAS counterparty credit risk, and the two "
        "portfolios have swapped character"
    )
    assert cms2_total == pytest.approx(cms1_credit_risk + ccr_charge, rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS2 row 0070 column c reports {cms2_total} against CMS1 row "
        f"0010's {cms1_credit_risk} plus a {ccr_charge} CCR charge. On a CCR-free book "
        "these are the published equality; on a CCR-bearing one the difference is the "
        "unimplemented half of CMS2 §1's exclusion, and any OTHER difference is new."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
@pytest.mark.parametrize("row_ref", _ROWS)
def test_cms1_columns_partition_the_row(
    portfolio: str, row_ref: str, runs: dict[str, _Run]
) -> None:
    """Column a + column b == column c, on every populated row.

    Annex II: cell 0010/c is "the sum of cells 0010/a and 0010/b". The Formula is
    already correct — this test guards the thing the Formula depends on: that a and
    b PARTITION the row, so their sum is the row's whole RWA. Independently of the
    hand-derived oracle, column c must also equal the ledger's own ``rwa_final``
    over the row's population.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> Pillar 3 CMS1 + the ledger it was built from.
    Assert:  a + b == c == the ledger's rwa_final for that row's risk types.
    """
    # Arrange + Act
    run = runs[portfolio]
    row = run.cms1_row(row_ref)
    ccr_scope = {"0010": False, "0020": True, "0080": None}[row_ref]
    residual_scope = {"0010": False, "0020": None, "0080": None}[row_ref]
    ledger_rwa = run.rwa_final(ccr=ccr_scope, residual=residual_scope)

    # Assert
    assert row["a"] is not None and row["b"] is not None, (
        f"[{portfolio}] CMS1 row {row_ref}: columns a and b must both be populated to "
        f"sum to column c (got a={row['a']}, b={row['b']})."
    )
    assert _num(row, "a") + _num(row, "b") == pytest.approx(row["c"], rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS1 row {row_ref}: column a ({row['a']}) + column b "
        f"({row['b']}) != column c ({row['c']})."
    )
    assert row["c"] == pytest.approx(ledger_rwa, rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS1 row {row_ref} column c reports {row['c']} but the ledger "
        f"carries {ledger_rwa:,.6f} of rwa_final on that row's population. Columns a "
        "and b must PARTITION the population — if column b is an allow-list, whatever "
        "it forgets (standardised_ccr) is reported nowhere at all."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_row_axis_foots_to_the_total(portfolio: str, runs: dict[str, _Run]) -> None:
    """Rows 0010 to 0070 == row 0080, in every column.

    "Credit risk (excluding CCR)", "Counterparty credit risk" and the other risk
    categories partition the book, so the Total row is their SUM — it was once a
    byte-for-byte copy of row 0010's cell specs, which is only a total on a book
    with no CCR and nothing in row 0070.

    The term list is the published one ("The total sum of cells 0010/c, 0020/c,
    0030/c, 0040/c, 0050/c, 0060/c and 0070/c") rather than the two rows this
    estate happens to populate: P2.54 put the Art. 112(1)(o) CIU RWA in row 0070,
    and a footing written over 0010 + 0020 alone would have read that as a
    discrepancy in the Total.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> Pillar 3 CMS1.
    Assert:  for every column, rows 0010-0070 sum to row 0080.
    """
    # Arrange + Act
    run = runs[portfolio]
    non_ccr, ccr, total = (run.cms1_row(ref) for ref in _ROWS)

    # Assert
    for col in _COLS:
        assert non_ccr[col] is not None and ccr[col] is not None, (
            f"[{portfolio}] CMS1 rows 0010/0020 column {col} must both be populated to "
            f"foot to the Total (got {non_ccr[col]}, {ccr[col]})."
        )
        terms = sum(run.cms1_row(ref)[col] or 0.0 for ref in _TOTAL_TERMS)  # type: ignore[operator]
        assert terms == pytest.approx(total[col], rel=_REL, abs=_ABS), (
            f"[{portfolio}] CMS1 does not foot on column {col}: rows {_TOTAL_TERMS} sum "
            f"to {terms} against row 0080 ({total[col]}). The Total row must be a total, "
            "not a duplicate of row 0010."
        )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_ccr_row_carries_the_ccr_book(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0020 column c == the ledger's ``rwa_final`` over the CCR risk types.

    Row 0010 "excludes ... capital requirements relating to a counterparty credit
    risk charge, which are reported in row 0020". Today row 0020 is never bound and
    renders null, so the CCR charge is reported on NO row at all.

    Arrange: a Basel 3.1 reporting portfolio (the CCR book has two netting sets;
             the rich book has none, so the row is a populated zero).
    Act:     run the pipeline -> Pillar 3 CMS1 + the ledger.
    Assert:  row 0020 column c == the ledger's CCR rwa_final.
    """
    # Arrange + Act
    run = runs[portfolio]
    expected = run.rwa_final(ccr=True)
    reported = run.cms1_row("0020")["c"]

    # Assert
    assert reported is not None, (
        f"[{portfolio}] CMS1 row 0020 (Counterparty credit risk) is NULL — the CCR legs "
        f"carry {expected:,.6f} of RWA and row 0010 explicitly EXCLUDES them, so they "
        "are disclosed nowhere."
    )
    assert reported == pytest.approx(expected, rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS1 row 0020 column c must equal the RWA of risk types "
        f"{_CCR_RISK_TYPES}: expected {expected:,.6f}, got {reported}."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
@pytest.mark.parametrize("row_ref", _ROWS)
def test_cms1_full_sa_column_is_scoped_to_the_rows_population(
    portfolio: str, row_ref: str, runs: dict[str, _Run]
) -> None:
    """Column d == ``sa_rwa`` over the ROW's population, not over the whole book.

    Annex II: column d is "RWA as would result from applying the ... standardised
    approach to **all** exposures giving rise to the RWA reported in cell 0010/c" —
    the same population as column c. Today column d has no predicate at all, so on
    the CCR book row 0010 compares its own 2,500,000 of RWA against a 4,060,296.72
    SA-equivalent that includes the derivatives it does not contain.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> Pillar 3 CMS1 + the ledger.
    Assert:  column d == sum(sa_rwa) over the row's risk-type population.
    """
    # Arrange + Act
    run = runs[portfolio]
    ccr_scope = {"0010": False, "0020": True, "0080": None}[row_ref]
    residual_scope = {"0010": False, "0020": None, "0080": None}[row_ref]
    expected = run.sa_rwa(ccr=ccr_scope, residual=residual_scope)
    reported = run.cms1_row(row_ref)["d"]

    # Assert
    assert reported == pytest.approx(expected, rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS1 row {row_ref} column d reports {reported}, but the "
        f"SA-equivalent RWA of that row's own population is {expected:,.6f}. Column d "
        "is the standardised recomputation of the exposures giving rise to column c — "
        "an unpredicated Sum(sa_rwa) reports the whole book on every row."
    )


def test_cms1_standardised_only_book_reports_no_modelled_rwa(runs: dict[str, _Run]) -> None:
    """A 100%-standardised book has ZERO modelled RWA, and its own RWA IS its SA RWA.

    The CCR portfolio holds one SA loan and two SA-CCR netting sets — no IRB model,
    no slotting. Column a (modelled) must therefore be 0.0 on every row, and each
    row is degenerate: b == c == d. Under the allow-list this degeneracy is exactly
    what breaks — the Total reports c = 2,500,000 against d = 4,060,296.72.

    Arrange: the Basel 3.1 CCR portfolio (SA only).
    Act:     run the pipeline -> Pillar 3 CMS1.
    Assert:  column a == 0.0 on rows 0010/0020/0080, and b == c == d on each.
    """
    # Arrange + Act
    run = runs["ccr"]
    rows = {ref: run.cms1_row(ref) for ref in _ROWS}

    # Assert
    for ref, row in rows.items():
        assert row["a"] == pytest.approx(0.0, abs=_ABS), (
            f"CMS1 row {ref} column a (MODELLED approaches) reports {row['a']} on a "
            "portfolio with no IRB model and no slotting."
        )
        assert row["b"] == pytest.approx(row["c"], rel=_REL, abs=_ABS), (
            f"CMS1 row {ref}: with no modelled RWA, column b ({row['b']}) IS the row's "
            f"total actual RWA — but column c reports {row['c']}."
        )
        assert row["c"] == pytest.approx(row["d"], rel=_REL, abs=_ABS), (
            f"CMS1 row {ref}: on a 100%-standardised book the actual RWA (column c = "
            f"{row['c']}) is its own SA equivalent (column d = {row['d']}) — the floor "
            "cannot bind."
        )


# =============================================================================
# The floor-dependent tie-out — guarded on a non-binding floor
# =============================================================================
#
# CMS1 columns a/b read ``rwa_final`` (POST-floor) while C 02.00 row 0010 is TREA.
# The two agree only while the floor is not activated (C 02.00 row 0034 == 0.0),
# which is true of both goldens. Asserting it unconditionally would fail spuriously
# the first time someone builds a binding-floor fixture — so the guard is explicit,
# and skips rather than lying.


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_cms1_total_actual_rwa_ties_to_c02_trea(portfolio: str, runs: dict[str, _Run]) -> None:
    """CMS1 row 0080 column c == C 02.00 row 0010 (TOTAL RISK EXPOSURE AMOUNT).

    The "total actual RWA" of the whole book and the TREA are the same number when
    the floor is not binding. CMS1 reports 2,500,000 of a 4,060,296.72 TREA on the
    CCR book: the derivatives are simply gone.

    Arrange: a Basel 3.1 reporting portfolio with a non-binding output floor.
    Act:     run the pipeline -> Pillar 3 CMS1 + COREP C 02.00.
    Assert:  CMS1 0080/c == C 02.00 row 0010 column 0010.
    """
    # Arrange + Act
    run = runs[portfolio]
    _require_non_binding_floor(run, portfolio)
    cms1_total = run.cms1_row("0080")["c"]
    c02_trea = run.c02_row("0010")["0010"]

    # Assert
    assert cms1_total == pytest.approx(c02_trea, rel=_REL, abs=_ABS), (
        f"[{portfolio}] CMS1 row 0080 column c (total actual RWA) reports {cms1_total}, "
        f"but C 02.00 row 0010 (TOTAL RISK EXPOSURE AMOUNT) reports {c02_trea} — and "
        "the floor is not binding, so the two must agree."
    )


# =============================================================================
# Helpers
# =============================================================================


def _run(portfolio: str) -> _Run:
    """Run one reporting portfolio through Basel 3.1 and keep templates + ledger."""
    if portfolio == "rich":
        bundle, config = build_reporting_bundle(), _RICH_REGIMES["b31"][2]()
    else:
        bundle, config = build_reporting_ccr_bundle(), _ccr_config("b31")

    result = PipelineOrchestrator().run_with_data(bundle, config)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework="BASEL_3_1")
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework="BASEL_3_1")

    assert pillar3.cms1 is not None, f"[{portfolio}] CMS1 was not generated"
    assert pillar3.cms2 is not None, f"[{portfolio}] CMS2 was not generated"
    assert corep.c_02_00 is not None, f"[{portfolio}] C 02.00 was not generated"
    return _Run(
        cms1=pillar3.cms1,
        cms2=pillar3.cms2,
        c02=corep.c_02_00,
        ledger=result.results.collect(),
    )


def _one_row(sheet: pl.DataFrame, ref: str, label: str) -> dict[str, float | str | None]:
    """The single row of ``sheet`` with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"expected exactly one {label} row {ref}, got {rows.height}"
    return rows.row(0, named=True)


def _num(row: dict[str, float | str | None], col: str) -> float:
    """The cell at ``col``, asserted numeric — a reported figure, not a label or a null."""
    value = row[col]
    assert isinstance(value, int | float), f"cell {col} must be numeric, got {value!r}"
    return float(value)


def _require_non_binding_floor(run: _Run, portfolio: str) -> None:
    """Skip when the output floor binds — a floored ``rwa_final`` breaks the tie-out.

    Both reporting portfolios are non-binding today, so this never skips; it exists
    so that a future binding-floor fixture does not make the tie-out fail spuriously.
    """
    activated = run.c02_row("0034")["0010"]
    if activated not in (0.0, None):
        pytest.skip(
            f"[{portfolio}] output floor is activated (C 02.00 row 0034 = {activated}); "
            "the CMS1-to-C 02.00 tie-out does not hold by construction."
        )
