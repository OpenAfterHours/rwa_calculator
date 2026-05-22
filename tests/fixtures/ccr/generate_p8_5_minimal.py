"""
P8.5 CCR minimal fixture shim — delegates to golden_ccr_a1.

This module preserves the public surface used by
``tests/integration/test_ccr_loader.py`` so that test file requires no edits:

    - Constants: TRADE_ID, NETTING_SET_ID, COUNTERPARTY_REF (and detail aliases)
    - Function:  save_p85_minimal_fixtures(output_dir)

All fixture construction is now delegated to ``golden_ccr_a1.save_golden_fixtures``,
which uses the canonical ``TRADE_SCHEMA`` / ``NETTING_SET_SCHEMA`` /
``MARGIN_AGREEMENT_SCHEMA`` / ``CCR_COLLATERAL_SCHEMA`` column names from
``src/rwa_calc/data/schemas.py``.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 295-297 (contractual netting recognition)
    - tests/fixtures/ccr/golden_ccr_a1.py (canonical constants and builders)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .golden_ccr_a1 import (
    CCR_A1_ASSET_CLASS,
    CCR_A1_COUNTERPARTY_REF,
    CCR_A1_CURRENCY,
    CCR_A1_DELTA,
    CCR_A1_IS_LEGALLY_ENFORCEABLE,
    CCR_A1_IS_LONG,
    CCR_A1_IS_MARGINED,
    CCR_A1_MATURITY_DATE,
    CCR_A1_MTM,
    CCR_A1_NETTING_SET_ID,
    CCR_A1_NOTIONAL,
    CCR_A1_START_DATE,
    CCR_A1_TRADE_ID,
    CCR_A1_TRANSACTION_TYPE,
    save_golden_fixtures,
)

# ---------------------------------------------------------------------------
# Legacy public constants — keep names stable for test_ccr_loader.py
# ---------------------------------------------------------------------------

TRADE_ID: str = CCR_A1_TRADE_ID
NETTING_SET_ID: str = CCR_A1_NETTING_SET_ID
COUNTERPARTY_REF: str = CCR_A1_COUNTERPARTY_REF

TRADE_NOTIONAL: float = CCR_A1_NOTIONAL
TRADE_CURRENCY: str = CCR_A1_CURRENCY
TRADE_ASSET_CLASS: str = CCR_A1_ASSET_CLASS
TRADE_TRANSACTION_TYPE: str = CCR_A1_TRANSACTION_TYPE
TRADE_MTM: float = CCR_A1_MTM
TRADE_DELTA: float = CCR_A1_DELTA
TRADE_IS_LONG: bool = CCR_A1_IS_LONG

TRADE_START_DATE = CCR_A1_START_DATE
TRADE_MATURITY_DATE = CCR_A1_MATURITY_DATE

NETTING_SET_IS_LEGALLY_ENFORCEABLE: bool = CCR_A1_IS_LEGALLY_ENFORCEABLE
NETTING_SET_IS_MARGINED: bool = CCR_A1_IS_MARGINED


# ---------------------------------------------------------------------------
# Legacy public function
# ---------------------------------------------------------------------------


def save_p85_minimal_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four P8.5 CCR parquet files and return a mapping of name to path.

    Delegates entirely to ``golden_ccr_a1.save_golden_fixtures``.  The parquets
    produced are schema-correct against the canonical ColumnSpec declarations in
    ``src/rwa_calc/data/schemas.py``.

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        dict mapping artefact name to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    return save_golden_fixtures(output_dir)


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P8.5 CCR minimal fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        schema_summary = {col: str(dtype) for col, dtype in df.schema.items()}
        print(f"  {name:<25} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
        for col, dtype in schema_summary.items():
            print(f"       {col:<35} {dtype}")
    print("-" * 70)
    print("Scenario: CCR-A1 — single 10y GBP IR swap, unmargined, no collateral")
    print(
        f"  Trade:       {TRADE_ID} (asset_class={TRADE_ASSET_CLASS!r},"
        f" notional={TRADE_NOTIONAL:,.0f} {TRADE_CURRENCY})"
    )
    print(
        f"  Netting set: {NETTING_SET_ID} -> {COUNTERPARTY_REF}"
        f" (enforceable={NETTING_SET_IS_LEGALLY_ENFORCEABLE},"
        f" margined={NETTING_SET_IS_MARGINED})"
    )
    print("  Margin agreements: 0 rows (unmargined CCR-A1)")
    print("  CCR collateral:    0 rows (no posted/received collateral)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p85_minimal_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
