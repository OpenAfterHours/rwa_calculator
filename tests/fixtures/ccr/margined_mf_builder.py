"""
Margined maturity factor fixture builder for SA-CCR P8.14 tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_maturity_factor_margined.py)
    -> engine-implementer (engine/ccr/maturity_factor.py)

Scenario design (4 rows, all is_margined=True, all remargining_frequency_days=1):

    T1 / NS1 — derivative, 10 trades, no illiquid collateral, 0 disputes
        MPOR base = 10 (OTC derivative, < 5000 trades, no illiquid)
        MPOR_eff  = max(base + 1 - 1, mpor_days_input) = max(10, 5) = 10
        MF        = 1.5 × sqrt(10 / 250) = 0.3

    T2 / NS2 — sft (repo/margin-lending), 10 trades, no illiquid, 0 disputes
        MPOR base = 5  (all trades are SFT — Art. 285(2)(a))
        MPOR_eff  = max(5 + 1 - 1, 5) = max(5, 5) = 5
        MF        = 1.5 × sqrt(5 / 250) = 0.21213203435596426

    T3 / NS3 — derivative, 7000 trades, no illiquid, 0 disputes
        MPOR base = 20 (number_of_trades > 5000 — Art. 285(3)(b))
        MPOR_eff  = max(20 + 1 - 1, 10) = max(20, 10) = 20
        MF        = 1.5 × sqrt(20 / 250) = 0.42426406871192857

    T4 / NS4 — derivative, 10 trades, no illiquid, 3 disputes (> 2 threshold)
        MPOR base = 10 (OTC derivative, < 5000 trades)
        After dispute doubling (Art. 285(4)): base = 2 × 10 = 20
        MPOR_eff  = max(20 + 1 - 1, 10) = max(20, 10) = 20
        MF        = 1.5 × sqrt(20 / 250) = 0.42426406871192857

The MPOR cascade (Art. 285) implemented by ``compute_maturity_factor_margined``:
    Step 1 — base:     5  if ALL trades in NS are sft/repo/margin-lending else 10
    Step 2 — upgrade:  20 if number_of_trades > 5000
                       OR has_illiquid_collateral_or_hard_to_replace_otc
    Step 3 — dispute:  base × 2 if dispute_count_qtr > 2  (Art. 285(4))
    Step 4 — freq adj: MPOR_eff = base + remargining_frequency_days − 1
    Step 5 — floor:    MPOR_eff = max(MPOR_eff, mpor_days_input)

The fixture exposes:
    - ``MARGINED_MF_ROWS``        — list of dicts consumed by the hand-calc table
    - ``make_margined_mf_trades`` — pl.DataFrame typed by TRADE_SCHEMA
    - ``make_margined_mf_netting_sets`` — pl.DataFrame typed by NETTING_SET_SCHEMA
    - ``make_margined_mf_margin_agreements`` — pl.DataFrame typed by
      MARGIN_AGREEMENT_SCHEMA (one MA per NS, remargining_frequency_days=1)
    - ``EXPECTED_MF``             — dict[trade_id, expected maturity_factor]

References:
    - CRR Art. 279c(2): MF = (3/2) × sqrt(MPOR_eff / 250)
    - CRR Art. 285(2)(a): 5-BD MPOR floor for repo/SFT netting sets
    - CRR Art. 285(2)(b): 10-BD MPOR floor for OTC derivative netting sets
    - CRR Art. 285(3)(b): 20-BD floor for > 5000 trades or illiquid collateral
    - CRR Art. 285(4):    double MPOR_base when dispute_count_qtr > 2
    - CRR Art. 285(5):    MPOR_eff = base + remargining_frequency_days − 1
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      MARGIN_AGREEMENT_SCHEMA
    - src/rwa_calc/data/tables/sa_ccr_factors.py — MF_MARGINED_SCALAR,
      MF_MARGINED_FLOOR_DAYS_REPO_SFT, MF_MARGINED_FLOOR_DAYS_OTC,
      MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from .margin_builder import Margin, create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

# Margined MF scalar per Art. 279c(2): MF = 1.5 × sqrt(MPOR_eff / 250).
_MF_SCALAR: float = 1.5
_BD_YEAR: int = 250


def _mf(mpor_eff: int) -> float:
    """Compute expected MF = 1.5 × sqrt(MPOR_eff / 250)."""
    return _MF_SCALAR * math.sqrt(mpor_eff / _BD_YEAR)


# Hand-calculated MPOR_eff and expected MF for each test row.
# Keys match the trade_id / netting_set_id columns below.
EXPECTED_MF: dict[str, float] = {
    "T1": _mf(10),  # derivative, base=10, MPOR_eff=10
    "T2": _mf(5),  # sft, base=5,  MPOR_eff=5
    "T3": _mf(20),  # derivative, > 5000 trades → base=20, MPOR_eff=20
    "T4": _mf(20),  # derivative, dispute_count_qtr=3 > 2 → 2×base=20, MPOR_eff=20
}

# Fixed reference date for all trades — calculation date for the unit tests.
_CALC_DATE: date = date(2026, 5, 23)
_MATURITY_DATE: date = date(2031, 5, 23)  # 5-year residual maturity (>= 1y cap)

# ---------------------------------------------------------------------------
# Row definitions — one entry per trade / netting set / margin agreement.
# ---------------------------------------------------------------------------

#: Scenario rows as plain dicts; mirrors the proposal table.
MARGINED_MF_ROWS: list[dict[str, Any]] = [
    {
        "trade_id": "T1",
        "netting_set_id": "NS1",
        "transaction_type": "derivative",
        "mpor_days_input": 5,  # below OTC floor → floor=10 wins
        "number_of_trades": 10,
        "has_illiquid": False,
        "dispute_count_qtr": 0,
        "remargining_frequency_days": 1,
        "expected_mpor_eff": 10,
        "expected_mf": EXPECTED_MF["T1"],
    },
    {
        "trade_id": "T2",
        "netting_set_id": "NS2",
        "transaction_type": "sft",
        "mpor_days_input": 5,  # meets SFT floor exactly
        "number_of_trades": 10,
        "has_illiquid": False,
        "dispute_count_qtr": 0,
        "remargining_frequency_days": 1,
        "expected_mpor_eff": 5,
        "expected_mf": EXPECTED_MF["T2"],
    },
    {
        "trade_id": "T3",
        "netting_set_id": "NS3",
        "transaction_type": "derivative",
        "mpor_days_input": 10,  # below large-NS floor → floor=20 wins
        "number_of_trades": 7000,  # > 5000 → 20-day floor
        "has_illiquid": False,
        "dispute_count_qtr": 0,
        "remargining_frequency_days": 1,
        "expected_mpor_eff": 20,
        "expected_mf": EXPECTED_MF["T3"],
    },
    {
        "trade_id": "T4",
        "netting_set_id": "NS4",
        "transaction_type": "derivative",
        "mpor_days_input": 10,  # doubled base = 20 > 10 → floor=20 wins
        "number_of_trades": 10,
        "has_illiquid": False,
        "dispute_count_qtr": 3,  # > 2 → dispute doubling applies
        "remargining_frequency_days": 1,
        "expected_mpor_eff": 20,
        "expected_mf": EXPECTED_MF["T4"],
    },
]

# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def make_margined_mf_trades() -> pl.DataFrame:
    """
    Return a 4-row trades DataFrame for the P8.14 margined MF scenarios.

    Each row has a unique trade_id and netting_set_id.  The ``transaction_type``
    column exercises the SFT-base-5 branch (T2) and the OTC-base-10 branch
    (T1, T3, T4).  All other TRADE_SCHEMA columns use sensible defaults.

    Returns:
        ``pl.DataFrame`` with schema ``TRADE_SCHEMA``.
    """
    trades = [
        Trade(
            trade_id=row["trade_id"],
            netting_set_id=row["netting_set_id"],
            asset_class="interest_rate",
            transaction_type=row["transaction_type"],
            notional=10_000_000.0,
            currency="GBP",
            maturity_date=_MATURITY_DATE,
            start_date=_CALC_DATE,
        )
        for row in MARGINED_MF_ROWS
    ]
    return create_trades(trades)


def make_margined_mf_netting_sets() -> pl.DataFrame:
    """
    Return a 4-row netting-sets DataFrame for the P8.14 margined MF scenarios.

    Each netting set is margined (``is_margined=True``) and legally enforceable.
    The ``number_of_trades`` and ``has_illiquid_collateral_or_hard_to_replace_otc``
    columns exercise the Art. 285(3)(b) branches; ``mpor_days`` feeds the
    Art. 285(5) floor check.

    Returns:
        ``pl.DataFrame`` with schema ``NETTING_SET_SCHEMA``.
    """
    netting_sets = [
        NettingSet(
            netting_set_id=row["netting_set_id"],
            counterparty_reference=f"CP_{row['netting_set_id']}",
            is_legally_enforceable=True,
            is_margined=True,
            mpor_days=row["mpor_days_input"],
            margin_agreement_id=f"MA_{row['netting_set_id']}",
            number_of_trades=row["number_of_trades"],
            has_illiquid_collateral_or_hard_to_replace_otc=row["has_illiquid"],
        )
        for row in MARGINED_MF_ROWS
    ]
    return create_netting_sets(netting_sets)


def make_margined_mf_margin_agreements() -> pl.DataFrame:
    """
    Return a 4-row margin-agreements DataFrame for the P8.14 margined MF scenarios.

    One CSA per netting set.  ``dispute_count_qtr`` exercises Art. 285(4) dispute
    doubling (T4: 3 > 2 → double).  ``remargining_frequency_days=1`` keeps the
    MPOR_eff = base + 1 − 1 = base for all rows, isolating the MPOR cascade logic.

    Returns:
        ``pl.DataFrame`` with schema ``MARGIN_AGREEMENT_SCHEMA``.
    """
    margins = [
        Margin(
            margin_agreement_id=f"MA_{row['netting_set_id']}",
            counterparty_reference=f"CP_{row['netting_set_id']}",
            mpor_days=row["mpor_days_input"],
            remargining_frequency_days=row["remargining_frequency_days"],
            dispute_count_qtr=row["dispute_count_qtr"],
        )
        for row in MARGINED_MF_ROWS
    ]
    return create_margin_agreements(margins)


# ---------------------------------------------------------------------------
# Save helper — produces parquet files consumed by generate_all.py.
# ---------------------------------------------------------------------------


def save_margined_mf_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write the three P8.14 margined MF parquet files to *output_dir*.

    Files produced:
        margined_mf_trades.parquet          — 4 rows (T1-T4)
        margined_mf_netting_sets.parquet    — 4 rows (NS1-NS4, all margined)
        margined_mf_margin_agreements.parquet — 4 rows (MA_NS1-MA_NS4)

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
        ("margined_mf_trades", make_margined_mf_trades()),
        ("margined_mf_netting_sets", make_margined_mf_netting_sets()),
        ("margined_mf_margin_agreements", make_margined_mf_margin_agreements()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_margined_mf_fixtures()
    print("P8.14 margined MF fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols")
    print("-" * 70)
    print("Expected MF values:")
    for trade_id, mf in EXPECTED_MF.items():
        row = next(r for r in MARGINED_MF_ROWS if r["trade_id"] == trade_id)
        print(
            f"  {trade_id}: MPOR_eff={row['expected_mpor_eff']:>2}d "
            f"transaction_type={row['transaction_type']:<10}  "
            f"MF={mf:.17f}"
        )


if __name__ == "__main__":
    main()
