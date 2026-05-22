"""
Generate minimal CCR parquet fixtures for P8.5 loader integration tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/) -> engine-implementer (P8.5)

Scope (P8.5 only):
    Four CCR parquet files sufficient to verify that:
    1. A loader finding all four files constructs RawCCRBundle with all four
       leaf bundles populated.
    2. A loader finding zero CCR files leaves bundle.ccr = None.
    3. Schema dtypes round-trip through parquet correctly.

    Rich dataclass builders (trade_builder.py) are out of scope for P8.5 and
    will be added in P8.40.

Files produced:
    trades.parquet          -- 1 row: 10y GBP vanilla IR swap, asset_class="interest_rate"
    netting_sets.parquet    -- 1 row: NS_001, CP_001, legally enforceable, unmargined
    margin_agreements.parquet -- 0 rows, full MARGIN_AGREEMENT_SCHEMA column set
    ccr_collateral.parquet  -- 0 rows, full CCR_COLLATERAL_SCHEMA column set

Column shapes match the TRADE_SCHEMA / NETTING_SET_SCHEMA / MARGIN_AGREEMENT_SCHEMA /
CCR_COLLATERAL_SCHEMA tables in the P8.5 architect's proposal, which are also
reflected in the TradeBundle / NettingSetBundle / MarginAgreementBundle /
CCRCollateralBundle docstrings in src/rwa_calc/contracts/bundles.py.

Conservative defaults applied (from architect's spec):
    is_legally_enforceable = False (Art. 295 — conservative; the fixture row explicitly sets True)
    mpor_days              = 10    (Art. 285(2) — minimum MPOR for standard margined sets)
    is_margined            = False (unmargined single-trade set for CCR-A1)
    mtm_value              = 0.0   (at-par trade; RC = max(V - C, 0) = 0)
    delta                  = 1.0   (non-option directional trade)

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement), 272(9) (MPOR)
    - CRR Art. 275(1)-(2) (replacement cost)
    - CRR Art. 285(2) (MPOR 10-day minimum)
    - CRR Art. 295-297 (contractual netting recognition)
    - src/rwa_calc/contracts/bundles.py (TradeBundle, NettingSetBundle,
      MarginAgreementBundle, CCRCollateralBundle, RawCCRBundle)

Usage:
    uv run python tests/fixtures/ccr/generate_p8_5_minimal.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

TRADE_ID: str = "T_001"
NETTING_SET_ID: str = "NS_001"
COUNTERPARTY_REF: str = "CP_001"

TRADE_NOTIONAL: float = 100_000_000.0  # GBP 100m
TRADE_CURRENCY: str = "GBP"
TRADE_ASSET_CLASS: str = "interest_rate"
TRADE_TRANSACTION_TYPE: str = "derivative"
TRADE_MTM: float = 0.0  # at-par vanilla swap
TRADE_DELTA: float = 1.0  # non-option — directional long
TRADE_IS_LONG: bool = True

TRADE_START_DATE: date = date(2026, 1, 15)
TRADE_MATURITY_DATE: date = date(2036, 1, 15)  # 10-year tenor

NETTING_SET_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
NETTING_SET_IS_MARGINED: bool = False  # unmargined (CCR-A1 case)

# ---------------------------------------------------------------------------
# Inline schema dtypes
#
# These replicate the column/dtype/required/default tables from the P8.5
# architect's proposal.  When the engine-implementer adds the schemas to
# data/schemas.py, the test-writer's schema round-trip test will validate
# that these dtypes agree with the canonical ColumnSpec declarations.
# ---------------------------------------------------------------------------

#: TRADE_SCHEMA columns and dtypes (required columns present; optional nulled)
TRADE_DTYPES: dict[str, pl.DataType] = {
    # Required
    "trade_id": pl.String,
    "netting_set_id": pl.String,
    "asset_class": pl.String,  # "interest_rate" | "fx" | "credit" | "equity" | "commodity"
    "transaction_type": pl.String,  # "derivative" | "sft"
    "notional": pl.Float64,
    "currency": pl.String,
    "maturity_date": pl.Date,
    "start_date": pl.Date,
    "delta": pl.Float64,  # default 1.0 (non-option)
    "is_long": pl.Boolean,
    "mtm_value": pl.Float64,  # default 0.0 (Art. 275: V)
    # Optional
    "underlying_reference": pl.String,  # null for vanilla swap
    "option_strike": pl.Float64,  # null for non-option
    "payment_leg_index_id": pl.String,  # null — floating leg index reference
}

#: NETTING_SET_SCHEMA columns and dtypes
NETTING_SET_DTYPES: dict[str, pl.DataType] = {
    # Required
    "netting_set_id": pl.String,
    "counterparty_reference": pl.String,
    "is_legally_enforceable": pl.Boolean,  # default False (Art. 295 conservative)
    "is_margined": pl.Boolean,  # default False
    # Optional — margined RC / MF columns (null in CCR-A1 unmargined case)
    "threshold": pl.Float64,
    "minimum_transfer_amount": pl.Float64,
    "independent_collateral_amount": pl.Float64,
    "mpor_days": pl.Int32,  # default 10 (Art. 285(2))
}

#: MARGIN_AGREEMENT_SCHEMA columns and dtypes
MARGIN_AGREEMENT_DTYPES: dict[str, pl.DataType] = {
    # Required
    "margin_agreement_id": pl.String,
    "netting_set_id": pl.String,
    # Optional
    "threshold": pl.Float64,
    "minimum_transfer_amount": pl.Float64,
    "independent_collateral_amount": pl.Float64,
    "mpor_days": pl.Int32,  # default 10 (Art. 285(2))
    "is_segregated_im": pl.Boolean,  # default False (Art. 285(3a))
}

#: CCR_COLLATERAL_SCHEMA columns and dtypes
CCR_COLLATERAL_DTYPES: dict[str, pl.DataType] = {
    # Required
    "ccr_collateral_id": pl.String,
    "netting_set_id": pl.String,
    "collateral_type": pl.String,  # haircut routing key (e.g. "cash", "govt_bond")
    "market_value": pl.Float64,
    "currency": pl.String,
    # Optional
    "is_posted": pl.Boolean,  # True = collateral posted by firm; False = received
    "issuer_cqs": pl.Int32,
    "residual_maturity_years": pl.Float64,
}


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def create_trades() -> pl.DataFrame:
    """
    Return the single-row trades DataFrame.

    Row design:
        T_001: 10-year GBP vanilla IR swap, notional GBP 100m, MtM=0, delta=1,
        asset_class="interest_rate", transaction_type="derivative".
        Optional columns (underlying_reference, option_strike, payment_leg_index_id)
        are null, exercising the empty-optional-column path in the loader.
    """
    data = {
        "trade_id": [TRADE_ID],
        "netting_set_id": [NETTING_SET_ID],
        "asset_class": [TRADE_ASSET_CLASS],
        "transaction_type": [TRADE_TRANSACTION_TYPE],
        "notional": [TRADE_NOTIONAL],
        "currency": [TRADE_CURRENCY],
        "maturity_date": [TRADE_MATURITY_DATE],
        "start_date": [TRADE_START_DATE],
        "delta": [TRADE_DELTA],
        "is_long": [TRADE_IS_LONG],
        "mtm_value": [TRADE_MTM],
        "underlying_reference": [None],
        "option_strike": [None],
        "payment_leg_index_id": [None],
    }
    return pl.DataFrame(data, schema=TRADE_DTYPES)


def create_netting_sets() -> pl.DataFrame:
    """
    Return the single-row netting-sets DataFrame.

    Row design:
        NS_001: counterparty CP_001, legally enforceable (Art. 295 condition met),
        unmargined (CCR-A1 scope). The four margined-RC/MF columns (threshold,
        minimum_transfer_amount, independent_collateral_amount, mpor_days) are
        null to exercise the empty-optional-column path in the loader and to
        confirm that the margined Replacement Cost formula (P8.11) correctly
        no-ops on unmargined netting sets.
    """
    data = {
        "netting_set_id": [NETTING_SET_ID],
        "counterparty_reference": [COUNTERPARTY_REF],
        "is_legally_enforceable": [NETTING_SET_IS_LEGALLY_ENFORCEABLE],
        "is_margined": [NETTING_SET_IS_MARGINED],
        "threshold": [None],
        "minimum_transfer_amount": [None],
        "independent_collateral_amount": [None],
        "mpor_days": [None],
    }
    return pl.DataFrame(data, schema=NETTING_SET_DTYPES)


def create_margin_agreements() -> pl.DataFrame:
    """
    Return an empty margin-agreements DataFrame with full schema present.

    CCR-A1 scope: no margin agreements (all netting sets are unmargined).
    The empty-frame path is a first-class scenario per the architect's spec —
    the loader must construct a valid MarginAgreementBundle from a zero-row
    parquet without emitting DQ errors.
    """
    return pl.DataFrame(schema=MARGIN_AGREEMENT_DTYPES)


def create_ccr_collateral() -> pl.DataFrame:
    """
    Return an empty CCR-collateral DataFrame with full schema present.

    CCR-A1 scope: no posted or received collateral (clean netting set, no CSA).
    The empty-frame path exercises the same loader zero-row tolerance as
    margin_agreements.
    """
    return pl.DataFrame(schema=CCR_COLLATERAL_DTYPES)


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p85_minimal_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four P8.5 CCR parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the directory containing this
            script (``tests/fixtures/ccr/``).

    Returns:
        dict mapping artefact name to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("trades", create_trades()),
        ("netting_sets", create_netting_sets()),
        ("margin_agreements", create_margin_agreements()),
        ("ccr_collateral", create_ccr_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


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
