"""
Structural invariants that hold for any portfolio, at every sealed edge.

Pipeline position:
    corpus / generated portfolio -> PipelineOrchestrator -> AggregatedResultBundle
        -> every sealed frame the bundle exposes

What this proves:
- No output figure is non-finite. A `NaN` is not a wrong number, it is a number
  that silently poisons every aggregate it reaches: a recorded incident had
  non-finite INPUT amounts spread portfolio-wide through the Basel 3.1 output
  floor, because the floor's pro-rata distribution divides by a portfolio total.
- No risk weight is negative, and none exceeds the recorded ceiling. Neither
  framework defines a negative risk weight anywhere; a negative one would be an
  exposure that releases capital.
- Zero exposure carries zero capital. RWEA = EAD x RW under both frameworks
  (CRR Art. 113(1), Art. 153(1)), so the product is zero whenever EAD is.

Cost shape: each property is checked against the whole deterministic corpus
(cheap — the runs are memoised and shared with every other module) and against a
generated sweep (the part that explores portfolios nobody built).

References:
- CRR Art. 92(3)(a), Art. 113(1): RWEA = exposure value x risk weight
- CRR Art. 153(1) / CRE31: the IRB risk-weight function
- PRA PS1/26 Art. 92 para 2A: the output floor, and its pro-rata distribution
"""

from __future__ import annotations

import math

import polars as pl
import pytest
from hypothesis import given

from tests.properties.corpus import CORPUS
from tests.properties.portfolios import ExposureSpec, results_df, run
from tests.properties.strategies import portfolios

#: The bundle fields that are sealed frames — every one is an edge a consumer
#: reads, so a non-finite value in any of them is a published non-finite value.
SEALED_FRAME_FIELDS: tuple[str, ...] = (
    "results",
    "sa_results",
    "irb_results",
    "slotting_results",
    "equity_results",
    "floor_impact",
    "supporting_factor_impact",
    "summary_by_class",
    "summary_by_approach",
    "summary_by_class_method",
)

#: Highest risk weight either framework can produce, as a ratio.
#:
#: 1250% is the securitisation / deduction-equivalent ceiling and the value the
#: reporting templates are laid out against. The IRB function is NOT capped there
#: by the regulation — K = LGD x N[...] - PD x LGD can exceed it for a near-1 LGD
#: at a high PD — so this is a RECORDED ceiling with the exceptions listed below,
#: not a regulatory identity.
MAX_RISK_WEIGHT = 12.5

#: Exposure classes exempted from the ceiling, each with the article that permits
#: it. Empty: nothing generated so far has exceeded 1250%, and the highest weight
#: measured on this engine is 281% (an F-IRB corporate at the IRB curve's peak).
#: If a portfolio ever exceeds the ceiling the entry belongs HERE with its
#: justification — never in a widened bound.
RISK_WEIGHT_EXCEPTIONS: frozenset[str] = frozenset()

#: The two live regimes. ``B31_FLOORED`` is exercised by the output-floor module,
#: which is the only place its later reporting date changes anything.
REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

_CORPUS_CASES = [(name, regime) for name in CORPUS for regime in REGIME_NAMES]


# ---------------------------------------------------------------------------
# Finiteness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_no_non_finite_value_at_any_sealed_edge(portfolio_name: str, regime: str):
    """No `NaN` and no `Inf` in any Float column of any sealed frame.

    Asserted per frame rather than on ``results`` alone because the summaries and
    the floor-impact view are separately sealed edges with their own consumers
    (the UI cards, the results cache, reconciliation) — a non-finite value that
    only ever appears in a summary is still a published one.
    """
    # Arrange
    bundle = run(CORPUS[portfolio_name], regime)

    # Act
    offences = [
        f"{field}.{column}"
        for field in SEALED_FRAME_FIELDS
        for column in _non_finite_columns(getattr(bundle, field, None))
    ]

    # Assert
    assert offences == [], f"non-finite values at sealed edges under {regime}: {offences}"


# ---------------------------------------------------------------------------
# Risk-weight bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_risk_weight_within_recorded_bounds(portfolio_name: str, regime: str):
    """``0 <= rwa_final / ead_final <= 1250%`` on every leg with exposure.

    The lower bound is a regulatory identity: no article in either framework
    assigns a negative risk weight, so a negative one means an exposure that
    RELEASES capital. The upper bound is the recorded ceiling — see
    :data:`RISK_WEIGHT_EXCEPTIONS`.
    """
    # Arrange
    df = results_df(CORPUS[portfolio_name], regime)

    # Act
    breaches = [
        breach
        for breach in _risk_weight_breaches(df)
        if breach["exposure_class"] not in RISK_WEIGHT_EXCEPTIONS
    ]

    # Assert
    assert breaches == [], (
        f"implied risk weight outside [0, {MAX_RISK_WEIGHT}] under {regime}: {breaches}"
    )


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_no_negative_exposure_or_capital(portfolio_name: str, regime: str):
    """No leg carries negative ``ead_final`` or negative ``rwa_final``.

    An exposure value is an amount at risk (CRR Art. 111(1) / Art. 166(1)); a
    negative one is not a smaller exposure but a sign error, and it nets against
    real exposure in every total it reaches.
    """
    # Arrange
    df = results_df(CORPUS[portfolio_name], regime)

    # Act
    negatives = _negative_amounts(df)

    # Assert
    assert negatives == [], f"negative EAD or RWA under {regime}: {negatives}"


# ---------------------------------------------------------------------------
# Zero exposure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_zero_ead_implies_zero_rwa(portfolio_name: str, regime: str):
    """A leg with no exposure value carries no risk-weighted exposure amount.

    RWEA = EAD x RW is a product under both frameworks, so a non-zero RWEA on a
    zero-EAD leg can only come from an additive term that does not belong there.
    """
    # Arrange
    df = results_df(CORPUS[portfolio_name], regime)

    # Act
    offenders = _zero_ead_with_rwa(df)

    # Assert
    assert offenders == [], f"non-zero RWA on a zero-EAD leg under {regime}: {offenders}"


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_a_wholly_undrawn_book_produces_no_capital(regime: str):
    """The degenerate case, pinned deterministically: nothing lent, nothing weighted.

    Kept as a fixed portfolio alongside the generated sweep because a strategy
    that never happens to draw ``drawn=0`` would leave the boundary untested, and
    an untested boundary is the shape of every defect in `LESSONS.md` B5.
    """
    # Arrange
    portfolio = (
        ExposureSpec(entity_type="corporate", drawn=0.0, external_cqs=3),
        ExposureSpec(entity_type="institution", drawn=0.0, external_cqs=2),
        ExposureSpec(entity_type="individual", drawn=0.0, external_cqs=None),
    )

    # Act
    df = results_df(portfolio, regime)

    # Assert
    assert float(df["ead_final"].fill_null(0.0).sum()) == 0.0
    assert float(df["rwa_final"].fill_null(0.0).sum()) == 0.0


# ---------------------------------------------------------------------------
# The generated sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
@given(portfolio=portfolios())
def test_structural_invariants_hold_on_generated_portfolios(
    portfolio: tuple[ExposureSpec, ...], regime: str
):
    """Every structural invariant above, on portfolios nobody designed.

    One test rather than four so that one generated portfolio costs one pipeline
    run instead of four: the invariants are independent statements but they are
    all readable off a single output frame, and the failure message names which
    one broke.
    """
    # Arrange
    bundle = run(portfolio, regime)
    df = bundle.results.collect()

    # Act
    findings = {
        "non_finite": [
            f"{field}.{column}"
            for field in SEALED_FRAME_FIELDS
            for column in _non_finite_columns(getattr(bundle, field, None))
        ],
        "risk_weight_out_of_bounds": [
            breach
            for breach in _risk_weight_breaches(df)
            if breach["exposure_class"] not in RISK_WEIGHT_EXCEPTIONS
        ],
        "negative_amounts": _negative_amounts(df),
        "zero_ead_with_rwa": _zero_ead_with_rwa(df),
    }

    # Assert
    broken = {name: rows for name, rows in findings.items() if rows}
    assert broken == {}, f"structural invariant broken under {regime}: {broken}"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _non_finite_columns(frame: pl.LazyFrame | pl.DataFrame | None) -> list[str]:
    """Names of the Float columns of ``frame`` holding a `NaN` or an `Inf`."""
    if frame is None:
        return []
    df = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
    offenders: list[str] = []
    for name, dtype in df.schema.items():
        if dtype not in (pl.Float32, pl.Float64):
            continue
        series = df[name]
        if series.is_nan().any() or any(
            value is not None and math.isinf(value) for value in series.to_list()
        ):
            offenders.append(name)
    return offenders


def _risk_weight_breaches(df: pl.DataFrame) -> list[dict]:
    """Legs whose implied risk weight falls outside ``[0, MAX_RISK_WEIGHT]``."""
    return (
        df.filter(pl.col("ead_final").fill_null(0.0) > 0.0)
        .with_columns(
            (pl.col("rwa_final").fill_null(0.0) / pl.col("ead_final")).alias("implied_rw")
        )
        .filter((pl.col("implied_rw") < 0.0) | (pl.col("implied_rw") > MAX_RISK_WEIGHT))
        .select("exposure_reference", "exposure_class", "approach_applied", "implied_rw")
        .to_dicts()
    )


def _negative_amounts(df: pl.DataFrame) -> list[dict]:
    """Legs carrying a negative exposure value or a negative RWEA."""
    return (
        df.filter(
            (pl.col("ead_final").fill_null(0.0) < 0.0) | (pl.col("rwa_final").fill_null(0.0) < 0.0)
        )
        .select("exposure_reference", "ead_final", "rwa_final")
        .to_dicts()
    )


def _zero_ead_with_rwa(df: pl.DataFrame) -> list[dict]:
    """Legs with no exposure value but a non-zero RWEA (tolerance: half a penny)."""
    return (
        df.filter(
            (pl.col("ead_final").fill_null(0.0) == 0.0)
            & (pl.col("rwa_final").fill_null(0.0).abs() > 0.005)
        )
        .select("exposure_reference", "ead_final", "rwa_final", "approach_applied")
        .to_dicts()
    )
