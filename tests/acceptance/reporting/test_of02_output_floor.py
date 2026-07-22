"""
COREP OF 02.01 — the output-floor comparison must PARTITION the book, not double it.

Pipeline position:
    reporting portfolio (rich | ccr) -> PipelineOrchestrator -> COREPGenerator
        -> OF 02.01 (U-TREA vs S-TREA) + C 02.00 (the roll-up it must tie to)

The defect this file drives out (docs/plans/c07-ccr-derivatives.md §4 D3):

- **Columns.** PS1/26 Annex II scopes column 0010 to "portfolios where RWAs are
  calculated using **modelled approaches only**" and column 0020 to "portfolios
  ... using **standardised approaches only**" — the two columns PARTITION the
  book, and column 0030 ("a sum of 0010 and 0020, i.e. the complete current
  portfolio") only reconstitutes the portfolio because they do. Today both
  columns are computed over the WHOLE ledger with no predicate at all, so column
  0030 reports U-TREA + S-TREA: 299,105,797.25 against a 137,449,963.91
  portfolio, **2.18x**. The output floor compares U-TREA to S-TREA, so this is a
  capital misstatement, not a presentation nit.
- **Carriers.** Column 0020 must sum ``rwa_pre_floor`` over the standardised
  partition, NOT ``sa_rwa``: ``sa_rwa`` is null on equity rows (equity bypasses
  the SA calculator), so ``Sum(sa_rwa)`` would silently drop equity's RWA from
  the standardised side. Column 0040 (the S-TREA leg) keeps summing ``sa_rwa``
  over the whole row population — that is what S-TREA is.
- **Rows.** Row 0010 is "Credit risk (excluding CCR)" and row 0020 is
  "Counterparty credit risk". Today row 0010 carries the CCR legs and row 0020
  is forced null, while row 0080 (Total) merely duplicates row 0010.

The partition:

    column 0010 MODELLED      = approach_applied in {foundation_irb, advanced_irb, slotting}
                                (slotting is Art. 153(5) — an IRB-chapter approach,
                                 reported in the CR IRB templates)
    column 0020 STANDARDISED  = everything else ({standardised, standardised_ccr, equity})

Rows 0030-0070 (CVA / securitisation / market / operational / other) stay all-null:
they are genuinely out of scope for a credit-risk calculator, and are NOT 0.0.

OF 02.01 is Basel-3.1-only (CRR returns ``None``), so this file parametrises over
the two Basel 3.1 portfolios — the rich book (IRB + slotting + equity + SA, no CCR)
and the CCR book (100% standardised: one SA loan + two SA-CCR netting sets) — not
over regimes. The CCR book is the sharper oracle: a book with no models must report
**zero** modelled RWA in column 0010. Today's golden claims 4,060,296.72 of it.

References:
- PRA PS1/26 Annex II, OF 02.01 columns 0010/0020/0030/0040; Art. 92(3)/(5A)
- CRR Art. 153(5) (supervisory slotting — an IRB approach)
- docs/plans/c07-ccr-derivatives.md §4 D3
- tests/acceptance/reporting/test_c02_ccr_footing.py (the C 02.00 oracle)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_ccr_golden import _config as _ccr_config
from tests.acceptance.reporting.test_reporting_golden import _REGIMES as _RICH_REGIMES
from tests.fixtures.reporting_ccr_portfolio import build_reporting_ccr_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.domain.enums import RiskType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

# Phase 2 parity convention: group-by float sums are not bit-reproducible.
_REL = 1e-9
_ABS = 1e-6

# The four OF 02.01 columns.
_COLS: tuple[str, ...] = ("0010", "0020", "0030", "0040")

# The risk types that belong on row 0020 ("Counterparty credit risk").
_CCR_RISK_TYPES: tuple[str, ...] = (RiskType.CCR_DERIVATIVE.value, RiskType.CCR_SFT.value)

# Out of scope for a credit-risk calculator — null, not zero.
_NULL_ROWS: tuple[str, ...] = ("0030", "0040", "0050", "0060", "0070")


@dataclass(frozen=True)
class _Run:
    """One Basel 3.1 pipeline run: the two templates plus the ledger behind them."""

    of02: pl.DataFrame
    c02: pl.DataFrame
    ledger: pl.DataFrame

    def of02_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.of02, ref, "OF 02.01")

    def c02_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.c02, ref, "C 02.00")

    @property
    def total_pre_floor_rwa(self) -> float:
        """Sum of ``rwa_pre_floor`` over the WHOLE ledger — the complete portfolio."""
        return float(self.ledger["rwa_pre_floor"].sum())

    @property
    def ccr_pre_floor_rwa(self) -> float:
        """Sum of ``rwa_pre_floor`` over the CCR risk types (row 0020's population)."""
        ccr = self.ledger.filter(pl.col("risk_type").is_in(_CCR_RISK_TYPES))
        return float(ccr["rwa_pre_floor"].sum()) if ccr.height else 0.0


# =============================================================================
# The oracle — hand-derived expected cells
# =============================================================================

# portfolio -> row_ref -> column_ref -> value.
#
# rich: 14 loans + 1 equity, NO CCR. Modelled = F-IRB 48,244,060.92 + A-IRB
#   14,625,069.66 + slotting 52,500,000.00 = 115,369,130.58 (== C 02.00 row 0220);
#   standardised = the SA book + equity = 22,080,833.33 (== C 02.00 row 0060).
#   They sum to the whole portfolio, 137,449,963.91 (== C 02.00 row 0010).
#   S-TREA (column 0040) = whole-book sa_rwa = 164,155,833.33, INCLUDING equity's
#   own 2,500,000 standardised-equivalent RWA (B31 equity is SA-only, Art. 147A;
#   the aggregator now populates equity's sa_rwa — R4).
# ccr: one SA corporate loan (2,500,000 RWEA) + two SA-CCR netting sets
#   (1,560,296.72 RWEA). No models at all -> column 0010 is 0.0 EVERYWHERE.
_EXPECTED: dict[str, dict[str, dict[str, float]]] = {
    "rich": {
        # Credit risk excluding CCR — the whole book (this portfolio has no CCR).
        "0010": {
            "0010": 115_369_130.58029616,
            "0020": 22_080_833.333333332,
            "0030": 137_449_963.9136295,
            "0040": 164_155_833.3333333,
        },
        # Counterparty credit risk — populated, and empty because the book has none.
        "0020": {"0010": 0.0, "0020": 0.0, "0030": 0.0, "0040": 0.0},
        # Total — 0010 + 0020, which here equals row 0010.
        "0080": {
            "0010": 115_369_130.58029616,
            "0020": 22_080_833.333333332,
            "0030": 137_449_963.9136295,
            "0040": 164_155_833.3333333,
        },
    },
    "ccr": {
        # The plain corporate term loan.
        "0010": {
            "0010": 0.0,
            "0020": 2_500_000.0,
            "0030": 2_500_000.0,
            "0040": 2_500_000.0,
        },
        # The two SA-CCR netting sets (bilateral institution + QCCP at 2%).
        "0020": {
            "0010": 0.0,
            "0020": 1_560_296.719974031,
            "0030": 1_560_296.719974031,
            "0040": 1_560_296.719974031,
        },
        # Total — a 100%-standardised book: no modelled RWA anywhere.
        "0080": {
            "0010": 0.0,
            "0020": 4_060_296.719974031,
            "0030": 4_060_296.719974031,
            "0040": 4_060_296.719974031,
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
@pytest.mark.parametrize("row_ref", ("0010", "0020", "0080"))
def test_of02_populated_rows_report_the_modelled_standardised_partition(
    portfolio: str, row_ref: str, runs: dict[str, _Run]
) -> None:
    """Every populated OF 02.01 cell equals its hand-derived value.

    Column 0010 (modelled) and column 0020 (standardised) partition the row's
    population; column 0030 sums them back to the complete portfolio; column 0040
    is S-TREA (``sa_rwa``) over the same population.

    Arrange: a Basel 3.1 reporting portfolio (rich | ccr).
    Act:     run the pipeline -> COREP OF 02.01.
    Assert:  all four cells of the row match the oracle.
    """
    # Arrange + Act
    run = runs[portfolio]
    expected = _EXPECTED[portfolio][row_ref]
    row = run.of02_row(row_ref)

    # Assert
    for col in _COLS:
        actual = row[col]
        assert actual is not None, (
            f"[{portfolio}] OF 02.01 row {row_ref} column {col} is NULL — it must "
            f"report {expected[col]:,.6f}. Rows 0010 (credit risk excl. CCR), 0020 "
            "(counterparty credit risk) and 0080 (total) are all populated rows."
        )
        assert actual == pytest.approx(expected[col], rel=_REL, abs=_ABS), (
            f"[{portfolio}] OF 02.01 row {row_ref} column {col}: expected "
            f"{expected[col]:,.6f}, got {actual:,.6f}. Column 0010 is the MODELLED "
            "partition (F-IRB + A-IRB + slotting), column 0020 the STANDARDISED "
            "partition (SA + SA-CCR + equity, on rwa_pre_floor — the actual "
            "own-approach RWA); 0030 = 0010 + 0020; 0040 = sa_rwa (S-TREA), which "
            "now includes equity's standardised-equivalent RWA."
        )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_out_of_scope_rows_stay_null(portfolio: str, runs: dict[str, _Run]) -> None:
    """Rows 0030-0070 (CVA, securitisation, market, op risk, other) stay all-null.

    A credit-risk calculator has nothing to say about them — null means "not
    reported here", which is not the same claim as 0.0.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> COREP OF 02.01.
    Assert:  every cell of rows 0030-0070 is null.
    """
    # Arrange + Act
    run = runs[portfolio]

    # Assert
    for row_ref in _NULL_ROWS:
        row = run.of02_row(row_ref)
        assert all(row[col] is None for col in _COLS), (
            f"[{portfolio}] OF 02.01 row {row_ref} must be all-null (out of scope for "
            f"a credit-risk calculator), got {[row[col] for col in _COLS]}."
        )


# =============================================================================
# The unconditional tie-outs — the lasting guard
# =============================================================================


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_total_utrea_is_the_complete_portfolio(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0080 column 0030 == the sum of ``rwa_pre_floor`` over the WHOLE ledger.

    This is the partition-completeness test, and the one that fails today: Annex II
    defines column 0030 as "a sum of 0010 and 0020, i.e. the complete current
    portfolio". If 0010 and 0020 both sum the whole book, 0030 is 2x the portfolio.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> COREP OF 02.01 + the ledger it was built from.
    Assert:  row 0080 column 0030 == sum(rwa_pre_floor) over every ledger row.
    """
    # Arrange + Act
    run = runs[portfolio]
    ledger_total = run.total_pre_floor_rwa
    reported = _num(run.of02_row("0080"), "0030")

    # Assert
    assert reported == pytest.approx(ledger_total, rel=_REL, abs=_ABS), (
        f"[{portfolio}] OF 02.01 row 0080 column 0030 (U-TREA, 'the complete current "
        f"portfolio') reports {reported} but the ledger's total pre-floor RWA is "
        f"{ledger_total:,.6f} (ratio {(reported or 0.0) / ledger_total:.4f}). Columns "
        "0010 (modelled) and 0020 (standardised) must PARTITION the book — if both sum "
        "the whole book, column 0030 double-counts it."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_row_axis_foots_to_the_total(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0010 + row 0020 == row 0080, in every column.

    "Credit risk (excluding CCR)" and "Counterparty credit risk" partition the
    credit-risk book, so the Total row is their sum — it is not a copy of row 0010.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> COREP OF 02.01.
    Assert:  for every column, 0010 + 0020 == 0080.
    """
    # Arrange + Act
    run = runs[portfolio]
    non_ccr, ccr, total = (run.of02_row(ref) for ref in ("0010", "0020", "0080"))

    # Assert
    for col in _COLS:
        assert non_ccr[col] is not None and ccr[col] is not None, (
            f"[{portfolio}] OF 02.01 rows 0010/0020 column {col} must both be "
            f"populated to foot to the total (got {non_ccr[col]}, {ccr[col]})."
        )
        assert _num(non_ccr, col) + _num(ccr, col) == pytest.approx(
            total[col], rel=_REL, abs=_ABS
        ), (
            f"[{portfolio}] OF 02.01 does not foot on column {col}: row 0010 "
            f"({non_ccr[col]}) + row 0020 ({ccr[col]}) != row 0080 ({total[col]})."
        )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_ccr_row_carries_the_ccr_book(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0020 column 0030 == sum(``rwa_pre_floor``) over the CCR risk types.

    Row 0020 is "Counterparty credit risk". The CCR legs (CCR_DERIVATIVE, CCR_SFT)
    belong there and nowhere else — today they sit on row 0010 ("Credit risk
    EXCLUDING CCR") while row 0020 is forced null.

    Arrange: a Basel 3.1 reporting portfolio (the CCR book has two netting sets;
             the rich book has none, so the row is a populated zero).
    Act:     run the pipeline -> COREP OF 02.01 + the ledger.
    Assert:  row 0020 column 0030 == the ledger's CCR pre-floor RWA.
    """
    # Arrange + Act
    run = runs[portfolio]
    expected = run.ccr_pre_floor_rwa
    reported = run.of02_row("0020")["0030"]

    # Assert
    assert reported is not None, (
        f"[{portfolio}] OF 02.01 row 0020 (Counterparty credit risk) is NULL — the CCR "
        f"legs carry {expected:,.6f} of pre-floor RWA and are being reported on row "
        "0010 ('Credit risk EXCLUDING CCR') instead."
    )
    assert reported == pytest.approx(expected, rel=_REL, abs=_ABS), (
        f"[{portfolio}] OF 02.01 row 0020 column 0030 must equal the pre-floor RWA of "
        f"risk types {_CCR_RISK_TYPES}: expected {expected:,.6f}, got {reported}."
    )


def test_of02_standardised_only_book_reports_no_modelled_rwa(runs: dict[str, _Run]) -> None:
    """A 100%-standardised book has ZERO modelled RWA, and U-TREA == S-TREA.

    The CCR portfolio holds one SA loan and two SA-CCR netting sets — no IRB model,
    no slotting. So column 0010 (modelled) must be 0.0 on every row, and the floor
    comparison is degenerate: U-TREA (0030) == S-TREA (0040), so it can never bind.
    Today's golden claims 4,060,296.72 of "modelled" RWA against a book with no models.

    Arrange: the Basel 3.1 CCR portfolio (SA only).
    Act:     run the pipeline -> COREP OF 02.01.
    Assert:  column 0010 is 0.0 on rows 0010/0020/0080, and row 0080 0030 == 0040.
    """
    # Arrange + Act
    run = runs["ccr"]
    rows = {ref: run.of02_row(ref) for ref in ("0010", "0020", "0080")}

    # Assert
    for ref, row in rows.items():
        assert row["0010"] == pytest.approx(0.0, abs=_ABS), (
            f"OF 02.01 row {ref} column 0010 (MODELLED approaches only) reports "
            f"{row['0010']} on a portfolio with no IRB model and no slotting — "
            "the whole book is standardised, so the modelled column is empty."
        )
    total = rows["0080"]
    assert total["0030"] == pytest.approx(total["0040"], rel=_REL, abs=_ABS), (
        "OF 02.01: on a 100%-standardised book U-TREA (row 0080 column 0030) must equal "
        f"S-TREA (column 0040) — the floor cannot bind. Got {total['0030']} vs "
        f"{total['0040']}."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_strea_ties_to_c02_sa_equivalent_total(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0080 column 0040 == C 02.00 row 0010 column 0020 — both are sum(``sa_rwa``).

    S-TREA is a single number and the two templates must agree on it, unconditionally:
    neither side reads the post-floor carrier.

    Arrange: a Basel 3.1 reporting portfolio.
    Act:     run the pipeline -> COREP OF 02.01 + C 02.00.
    Assert:  OF 02.01 row 0080 col 0040 == C 02.00 row 0010 col 0020.
    """
    # Arrange + Act
    run = runs[portfolio]
    of02_strea = run.of02_row("0080")["0040"]
    c02_strea = run.c02_row("0010")["0020"]

    # Assert
    assert of02_strea == pytest.approx(c02_strea, rel=_REL, abs=_ABS), (
        f"[{portfolio}] S-TREA disagrees across templates: OF 02.01 row 0080 column "
        f"0040 reports {of02_strea}, C 02.00 row 0010 column 0020 (SA-equivalent TREA) "
        f"reports {c02_strea}. Both are the sum of sa_rwa over the whole book."
    )


# =============================================================================
# The floor-dependent tie-outs — guarded on a non-binding floor
# =============================================================================
#
# C 02.00 reads ``rwa_final`` (POST-floor) while OF 02.01 reads ``rwa_pre_floor``.
# The two agree only while the floor is not activated (C 02.00 row 0034 == 0.0),
# which is true of both goldens. Asserting them unconditionally would fail
# spuriously the first time someone builds a binding-floor fixture — so the guard
# is explicit, and skips rather than lying.


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_modelled_total_ties_to_c02_irb_row(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0080 column 0010 == C 02.00 row 0220 ("Of which: IRB Approach").

    The modelled partition IS the IRB estate as C 02.00 already defines it —
    F-IRB + A-IRB + supervisory slotting (Art. 153(5)). If the two disagree, one
    of them has mis-scoped "modelled".

    Arrange: a Basel 3.1 reporting portfolio with a non-binding output floor.
    Act:     run the pipeline -> COREP OF 02.01 + C 02.00.
    Assert:  OF 02.01 row 0080 col 0010 == C 02.00 row 0220 col 0010.
    """
    # Arrange + Act
    run = runs[portfolio]
    _require_non_binding_floor(run, portfolio)
    modelled = run.of02_row("0080")["0010"]
    c02_irb = run.c02_row("0220")["0010"]

    # Assert
    assert modelled == pytest.approx(c02_irb, rel=_REL, abs=_ABS), (
        f"[{portfolio}] OF 02.01 row 0080 column 0010 (modelled approaches only) "
        f"reports {modelled}, but C 02.00 row 0220 ('Of which: IRB Approach', which "
        f"includes supervisory slotting) reports {c02_irb}. The modelled column must "
        "cover exactly {foundation_irb, advanced_irb, slotting}."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_standardised_total_ties_to_c02_sa_row(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0080 column 0020 == C 02.00 row 0060 ("Of which: Standardised Approach").

    The standardised partition is everything that is not modelled — SA, SA-CCR AND
    equity. The carrier is ``rwa_pre_floor`` (the actual own-approach RWA), not
    ``sa_rwa`` (the S-TREA leg reported in column 0040). Equity bypasses the SA
    calculator, so the aggregator now populates equity's ``sa_rwa`` as its own
    pre-floor RWA (R4) — column 0020 still reports the actual RWA here.

    Arrange: a Basel 3.1 reporting portfolio with a non-binding output floor.
    Act:     run the pipeline -> COREP OF 02.01 + C 02.00.
    Assert:  OF 02.01 row 0080 col 0020 == C 02.00 row 0060 col 0010.
    """
    # Arrange + Act
    run = runs[portfolio]
    _require_non_binding_floor(run, portfolio)
    standardised = run.of02_row("0080")["0020"]
    c02_sa = run.c02_row("0060")["0010"]

    # Assert
    assert standardised == pytest.approx(c02_sa, rel=_REL, abs=_ABS), (
        f"[{portfolio}] OF 02.01 row 0080 column 0020 (standardised approaches only) "
        f"reports {standardised}, but C 02.00 row 0060 ('Of which: Standardised "
        f"Approach') reports {c02_sa}."
    )


@pytest.mark.parametrize("portfolio", _PORTFOLIOS)
def test_of02_utrea_ties_to_c02_trea(portfolio: str, runs: dict[str, _Run]) -> None:
    """Row 0080 column 0030 == C 02.00 row 0010 ("TOTAL RISK EXPOSURE AMOUNT").

    With a non-binding floor, ``rwa_final == rwa_pre_floor``, so the complete
    portfolio reported by OF 02.01 and the TREA reported by C 02.00 are the same
    number. Today OF 02.01 reports 2.18x it on the rich book.

    Arrange: a Basel 3.1 reporting portfolio with a non-binding output floor.
    Act:     run the pipeline -> COREP OF 02.01 + C 02.00.
    Assert:  OF 02.01 row 0080 col 0030 == C 02.00 row 0010 col 0010.
    """
    # Arrange + Act
    run = runs[portfolio]
    _require_non_binding_floor(run, portfolio)
    u_trea = run.of02_row("0080")["0030"]
    c02_trea = run.c02_row("0010")["0010"]

    # Assert
    assert u_trea == pytest.approx(c02_trea, rel=_REL, abs=_ABS), (
        f"[{portfolio}] OF 02.01 row 0080 column 0030 (U-TREA, 'the complete current "
        f"portfolio') reports {u_trea}, but C 02.00 row 0010 (TOTAL RISK EXPOSURE "
        f"AMOUNT) reports {c02_trea} — and the floor is not binding, so the two must "
        "agree."
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
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework="BASEL_3_1")

    assert corep.of_02_01 is not None, f"[{portfolio}] OF 02.01 was not generated"
    assert corep.c_02_00 is not None, f"[{portfolio}] C 02.00 was not generated"
    return _Run(of02=corep.of_02_01, c02=corep.c_02_00, ledger=result.results.collect())


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
    """Skip when the output floor binds — C 02.00 is post-floor, OF 02.01 is pre-floor.

    Both reporting portfolios are non-binding today, so this never skips; it exists so
    that a future binding-floor fixture does not make these tie-outs fail spuriously.
    """
    activated = run.c02_row("0034")["0010"]
    if activated not in (0.0, None):
        pytest.skip(
            f"[{portfolio}] output floor is activated (C 02.00 row 0034 = {activated}); "
            "C 02.00 reports post-floor RWA while OF 02.01 reports pre-floor, so the "
            "cross-template tie-outs do not hold by construction."
        )
