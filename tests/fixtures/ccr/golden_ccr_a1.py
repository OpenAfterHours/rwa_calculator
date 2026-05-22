"""
Golden CCR-A1 scenario: single 10-year GBP vanilla IR swap, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (SA-CCR replacement cost + PFE add-on)

Scenario design:
    One trade (T_001): 10-year GBP vanilla IR swap, notional GBP 100m,
    MtM = 0.0 (at-par), delta = 1.0 (non-option directional long).
    One netting set (NS_001): counterparty CP_001, legally enforceable
    (Art. 295 condition met), unmargined (CCR-A1 scope).
    Zero margin agreements: no CSA in place.
    Zero CCR collateral: no posted or received collateral.

Regulatory hand-calc reference (unmargined RC formula, Art. 275(1)):
    RC = max(V - C, 0) = max(0.0 - 0.0, 0) = 0.0

Module-level constants are the single source of truth for test-writer
assertions and are re-exported by ``generate_p8_5_minimal.py`` under the
legacy names (TRADE_ID, NETTING_SET_ID, COUNTERPARTY_REF) so that
``tests/integration/test_ccr_loader.py`` continues to work without edits.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 279b (PFE add-on — interest rate asset class)
    - CRR Art. 285(2)(b) (10-day minimum MPOR)
    - CRR Art. 295-297 (contractual netting recognition)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      MARGIN_AGREEMENT_SCHEMA, CCR_COLLATERAL_SCHEMA
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CCR_A1_TRADE_ID: str = "T_001"
CCR_A1_NETTING_SET_ID: str = "NS_001"
CCR_A1_COUNTERPARTY_REF: str = "CP_001"

CCR_A1_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A1_CURRENCY: str = "GBP"
CCR_A1_ASSET_CLASS: str = "interest_rate"
CCR_A1_TRANSACTION_TYPE: str = "derivative"
CCR_A1_MTM: float = 0.0  # at-par vanilla swap
CCR_A1_DELTA: float = 1.0  # non-option directional long
CCR_A1_IS_LONG: bool = True

# 10-year tenor: 2026-01-15 start, 2036-01-15 maturity.
from datetime import date as _date

CCR_A1_START_DATE: _date = _date(2026, 1, 15)
CCR_A1_MATURITY_DATE: _date = _date(2036, 1, 15)

CCR_A1_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
CCR_A1_IS_MARGINED: bool = False  # unmargined (CCR-A1 scope)


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _ccr_a1_trade() -> Trade:
    """Return the single CCR-A1 trade instance."""
    return make_trade(
        trade_id=CCR_A1_TRADE_ID,
        netting_set_id=CCR_A1_NETTING_SET_ID,
        asset_class=CCR_A1_ASSET_CLASS,
        transaction_type=CCR_A1_TRANSACTION_TYPE,
        notional=CCR_A1_NOTIONAL,
        currency=CCR_A1_CURRENCY,
        maturity_date=CCR_A1_MATURITY_DATE,
        start_date=CCR_A1_START_DATE,
        delta=CCR_A1_DELTA,
        is_long=CCR_A1_IS_LONG,
        mtm_value=CCR_A1_MTM,
    )


def _ccr_a1_netting_set() -> NettingSet:
    """Return the single CCR-A1 netting set instance."""
    return NettingSet(
        netting_set_id=CCR_A1_NETTING_SET_ID,
        counterparty_reference=CCR_A1_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A1_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def create_ccr_a1_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A1."""
    return create_trades([_ccr_a1_trade()])


def create_ccr_a1_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A1."""
    return create_netting_sets([_ccr_a1_netting_set()])


def create_ccr_a1_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CCR-A1: no CSA)."""
    return create_margin_agreements([])


def create_ccr_a1_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A1: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_golden_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A1 golden parquet files to *output_dir*.

    Files produced:
        trades.parquet              — 1 row  (T_001, 10y GBP IR swap)
        netting_sets.parquet        — 1 row  (NS_001, CP_001, enforceable, unmargined)
        margin_agreements.parquet   — 0 rows (CCR-A1: no CSA)
        ccr_collateral.parquet      — 0 rows (CCR-A1: no collateral)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("trades", create_ccr_a1_trades()),
        ("netting_sets", create_ccr_a1_netting_sets()),
        ("margin_agreements", create_ccr_a1_margin_agreements()),
        ("ccr_collateral", create_ccr_a1_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_golden_fixtures()
    print("CCR-A1 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A1 — single 10y GBP IR swap, unmargined, no collateral")
    print(
        f"  Trade:       {CCR_A1_TRADE_ID} (asset_class={CCR_A1_ASSET_CLASS!r},"
        f" notional={CCR_A1_NOTIONAL:,.0f} {CCR_A1_CURRENCY})"
    )
    print(
        f"  Netting set: {CCR_A1_NETTING_SET_ID} -> {CCR_A1_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A1_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A1_IS_MARGINED})"
    )
    print("  Margin agreements: 0 rows (unmargined CCR-A1)")
    print("  CCR collateral:    0 rows (no posted/received collateral)")


if __name__ == "__main__":
    main()
