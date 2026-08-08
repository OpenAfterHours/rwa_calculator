"""
Conservation of exposure and capital across every sealed edge and every summary.

Pipeline position:
    corpus portfolio -> PipelineOrchestrator -> aggregator exit (the sealed ledger)
        -> summary frames -> COREPGenerator / Pillar3Generator

What this proves:
Exposure value and RWEA are quantities, not labels. Every re-presentation of the
book — the per-class summary, the per-approach summary, a template's in-scope
population — is a partition of the same total, so each must add back to it.
A defect that MOVES exposure between buckets is invisible to a golden file that
was captured after the move; a conservation identity sees it immediately, because
one side of the identity is the flat ledger sum, which no bucketing can change.

Why this shape rather than "assert the cell equals 12,345":
    A recorded incident (`.claude/LESSONS.md` B6) had ~2.0m of RWEA fall out of
    the C 02.00 breakdown rows while the parent total still counted it. No
    published rule objected, because published rules only check rows that exist.
    Only the residual — parent minus the sum of its parts — could see it.

References:
- CRR Art. 92(3)(a): total risk exposure amount
- COREP Annex II, C 07.00: the SA template and its exposure-value column 0200
- PS1/26 Annex II / Pillar 3 CR4: SA exposure and credit-risk-mitigation effects
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.properties.corpus import CORPUS
from tests.properties.portfolios import corep_bundle, pillar3_bundle, results_df, run

#: Absolute money tolerance. Template cells are group-by/sum aggregates and
#: Polars Float64 group-by sums are not process-deterministic in the last ulps,
#: so an exact comparison would flap. Half a penny is far below any real defect:
#: the recorded stranding incidents were millions.
MONEY_TOLERANCE = 0.005

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

#: Templates are generated for a subset of the corpus — generation costs an order
#: of magnitude more than a run, and these three between them carry every SA
#: class, both CCF sides, and the CRM substitution legs.
TEMPLATE_PORTFOLIOS: tuple[str, ...] = ("sa_broad", "off_balance_sheet", "mitigated")

_CORPUS_CASES = [(name, regime) for name in CORPUS for regime in REGIME_NAMES]
_TEMPLATE_CASES = [(name, regime) for name in TEMPLATE_PORTFOLIOS for regime in REGIME_NAMES]


# ---------------------------------------------------------------------------
# Ledger seal vs aggregator exit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_ledger_exposure_equals_aggregator_exit_exposure(portfolio_name: str, regime: str):
    """The sealed reporting ledger carries the same exposure value as the calculation.

    ``reporting_ead`` is the per-leg carrier every declarative template reads;
    ``ead_final`` is what the calculators produced. They are the same quantity
    seen from two sides of one seal, so a difference is a seal that dropped or
    re-derived a value rather than projecting it.
    """
    # Arrange
    df = results_df(CORPUS[portfolio_name], regime)

    # Act
    divergent = (
        df.with_columns(
            (pl.col("reporting_ead").fill_null(0.0) - pl.col("ead_final").fill_null(0.0))
            .abs()
            .alias("gap")
        )
        .filter(pl.col("gap") > MONEY_TOLERANCE)
        .select("exposure_reference", "ead_final", "reporting_ead", "gap")
        .to_dicts()
    )

    # Assert
    assert divergent == [], f"ledger seal diverges from aggregator exit under {regime}: {divergent}"


# ---------------------------------------------------------------------------
# Summary partitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_summaries_partition_the_portfolio_total(portfolio_name: str, regime: str):
    """Each summary frame re-presents the whole book, so each adds back to it.

    Three independent partitions of one population (by class, by approach, by
    class-and-method). A leg that falls out of one of them is a leg missing from
    a surface a consumer reads — the UI cards and the reconciliation engine both
    take their totals from these frames, not from ``results``.
    """
    # Arrange
    bundle = run(CORPUS[portfolio_name], regime)
    df = results_df(CORPUS[portfolio_name], regime)
    ledger_rwa = float(df["rwa_final"].fill_null(0.0).sum())
    ledger_ead = float(df["ead_final"].fill_null(0.0).sum())

    # Act
    gaps: dict[str, tuple[float, float]] = {}
    for field in ("summary_by_class", "summary_by_approach", "summary_by_class_method"):
        summary = getattr(bundle, field)
        if summary is None:
            continue
        collected = summary.collect()
        gaps[f"{field}.rwa"] = (
            ledger_rwa,
            float(collected["total_rwa"].fill_null(0.0).sum()),
        )
        gaps[f"{field}.ead"] = (
            ledger_ead,
            float(collected["total_ead"].fill_null(0.0).sum()),
        )

    # Assert
    broken = {
        key: (expected, actual)
        for key, (expected, actual) in gaps.items()
        if abs(expected - actual) > MONEY_TOLERANCE
    }
    assert broken == {}, f"summary does not partition the ledger under {regime}: {broken}"


# ---------------------------------------------------------------------------
# Template in-scope populations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_c07_exposure_value_equals_the_standardised_population(portfolio_name: str, regime: str):
    """C 07.00's exposure-value column, summed over its sheets, is the SA book.

    COREP Annex II makes C 07.00 the standardised template and publishes it per
    Art. 112(1) obligor class (one sheet per class), so the union of its sheets
    is exactly the standardised population and column 0200 is that population's
    exposure value. Summing row 0010 across every emitted sheet must therefore
    reproduce the ledger's standardised EAD — no more, and no less.
    """
    # Arrange
    portfolio = CORPUS[portfolio_name]
    df = results_df(portfolio, regime)
    expected = float(
        df.filter(pl.col("reporting_approach") == "standardised")["ead_final"].fill_null(0.0).sum()
    )

    # Act
    sheets = corep_bundle(portfolio, regime).c07_00 or {}
    published = sum(_c07_total_exposure_value(frame) for frame in sheets.values())

    # Assert
    assert abs(published - expected) <= MONEY_TOLERANCE, (
        f"C 07.00 col 0200 sums to {published:,.2f} but the standardised ledger population "
        f"is {expected:,.2f} under {regime} (residual {published - expected:,.2f})"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_cr4_exposure_after_crm_and_ccf_equals_the_standardised_population(
    portfolio_name: str, regime: str
):
    """Pillar 3 CR4's post-CCF post-CRM exposure is the whole standardised book.

    Columns c and d are the on- and off-balance-sheet halves of the exposure
    amount after conversion factors and credit risk mitigation, disclosed by
    exposure class. Their sum over the class rows is the standardised population's
    exposure value by definition — the template is a partition of it.
    """
    # Arrange
    portfolio = CORPUS[portfolio_name]
    df = results_df(portfolio, regime)
    expected = float(
        df.filter(pl.col("reporting_approach") == "standardised")["ead_final"].fill_null(0.0).sum()
    )

    # Act
    cr4 = pillar3_bundle(portfolio, regime).cr4
    assert cr4 is not None, "CR4 was not emitted at all"
    body = cr4.filter(pl.col("row_ref") != _CR4_TOTAL_ROW)
    published = _column_sum(body, "c") + _column_sum(body, "d")

    # Assert
    assert abs(published - expected) <= MONEY_TOLERANCE, (
        f"CR4 class rows carry {published:,.2f} of exposure but the standardised ledger "
        f"population is {expected:,.2f} under {regime} (residual {published - expected:,.2f})"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _TEMPLATE_CASES)
def test_cr4_rwea_equals_the_standardised_population(portfolio_name: str, regime: str):
    """CR4 column e is the standardised book's RWEA, disclosed by exposure class."""
    # Arrange
    portfolio = CORPUS[portfolio_name]
    df = results_df(portfolio, regime)
    expected = float(
        df.filter(pl.col("reporting_approach") == "standardised")["rwa_final"].fill_null(0.0).sum()
    )

    # Act
    cr4 = pillar3_bundle(portfolio, regime).cr4
    assert cr4 is not None, "CR4 was not emitted at all"
    published = _column_sum(cr4.filter(pl.col("row_ref") != _CR4_TOTAL_ROW), "e")

    # Assert
    assert abs(published - expected) <= MONEY_TOLERANCE, (
        f"CR4 class rows carry {published:,.2f} of RWEA but the standardised ledger population "
        f"is {expected:,.2f} under {regime} (residual {published - expected:,.2f})"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

#: CR4's footing row. Named rather than inlined because the whole point of the
#: residual tests is that they must not be written against the row LIST.
_CR4_TOTAL_ROW = "17"


def _column_sum(frame: pl.DataFrame, column: str) -> float:
    """Sum one numeric template column, treating an unpublished cell as zero."""
    return float(frame[column].fill_null(0.0).sum())


def _c07_total_exposure_value(frame: pl.DataFrame) -> float:
    """Row 0010 ("Total exposures"), column 0200 ("Exposure value") of one sheet."""
    row = frame.filter(pl.col("row_ref") == "0010")
    if row.height == 0:
        return 0.0
    value = row["0200"][0]
    return float(value) if value is not None else 0.0
