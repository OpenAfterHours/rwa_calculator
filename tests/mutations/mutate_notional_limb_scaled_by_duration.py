"""Isolating mutation: the equity / commodity notional limb scaled by max(1, SD(S, E)).

Changes exactly one thing — where a trade has no market price x units (the Art.
279b(1)(c) notional limb), its ``notional`` is multiplied by
``max(1, SD(S, E))`` before the ORIGINAL ``compute_adjusted_notional_equity`` /
``_commodity`` run, and restored afterwards. That is the other-risks shape in
``engine/ccr/risk_categories.py`` (``|notional| x max(1, SD)``), which the P1.406
design chain cited as the precedent for this limb. At one year SD is about 0.93,
so the mutant is invisible there; at five years SD is about 4.38.

``SD`` is read off the ``years_to_maturity`` column the SA-CCR adapter adds
before the adjusted-notional chain; a frame without it (a unit test calling the
function directly) gets ``SD`` null, ``max(1, null) = 1``, and is unchanged —
the unit level cannot see this mutation, by construction.

Run with::

    PYTHONPATH=<this dir>:.:src uv run pytest <tests> -p mutate_notional_limb_scaled_by_duration

The plugin prints each application and fails the session when it applied to no
frame carrying ``years_to_maturity`` (README rule 3).
"""

from __future__ import annotations

import polars as pl
import pytest

_APPLIED = {"dated": 0}


@pytest.fixture(autouse=True)
def _duration_scaled_notional_limb():
    import rwa_calc.engine.ccr.adjusted_notional as module
    import rwa_calc.engine.ccr.pipeline_adapter as adapter

    originals = {
        name: getattr(module, name)
        for name in ("compute_adjusted_notional_equity", "compute_adjusted_notional_commodity")
    }

    def _wrap(original):  # noqa: ANN001, ANN202
        def _scaled(trades: pl.LazyFrame) -> pl.LazyFrame:
            names = trades.collect_schema().names()
            if "years_to_maturity" not in names:
                return original(trades)
            _APPLIED["dated"] += 1
            rate = module._SUPERVISORY_DURATION_RATE
            years_to_start = pl.col("years_to_maturity") - (
                (pl.col("maturity_date") - pl.col("start_date")).dt.total_days() / 365.25
            )
            s = pl.max_horizontal(years_to_start, pl.lit(module._START_FLOOR_YEARS))
            sd = ((-rate * s).exp() - (-rate * pl.col("years_to_maturity")).exp()) / rate
            no_units = (pl.col("market_price") * pl.col("number_of_units")).is_null()
            scaled = trades.with_columns(
                pl.col("notional").alias("_mutant_notional"),
                pl.when(no_units)
                .then(pl.col("notional") * pl.max_horizontal(pl.lit(1.0), sd))
                .otherwise(pl.col("notional"))
                .alias("notional"),
            )
            return (
                original(scaled)
                .with_columns(pl.col("_mutant_notional").alias("notional"))
                .drop("_mutant_notional")
            )

        return _scaled

    for name, original in originals.items():
        mutant = _wrap(original)
        assert mutant is not original
        setattr(module, name, mutant)
        setattr(adapter, name, mutant)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(module, name, original)
            setattr(adapter, name, original)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """Report the dated applications; fail closed when there were none."""
    applied = _APPLIED["dated"]
    session.config.get_terminal_writer().line(
        f"mutate_notional_limb_scaled_by_duration: applied to {applied} dated frame(s)"
    )
    if applied == 0:
        session.exitstatus = pytest.ExitCode.USAGE_ERROR
