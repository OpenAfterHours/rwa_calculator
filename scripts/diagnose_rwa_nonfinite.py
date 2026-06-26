#!/usr/bin/env python
"""
Find the exposures whose RWA is non-finite (NaN / inf) and show why.

A single NaN or inf in ``rwa_final`` poisons the portfolio total
(``Decimal('NaN')``) and any downstream reconciliation "ours" total, so a
handful of bad exposures can blank an otherwise-correct run. This read-only tool
runs a calculation, finds every row whose ``rwa_final`` / ``ead_final`` /
``risk_weight`` is non-finite, and prints those rows alongside the input/driver
columns that are present, flagging which of them are themselves non-finite — so
the culprit (a NaN input, a zero/low PD hitting the IRB maturity-adjustment
blow-up, a NaN EAD, ...) is visible at a glance.

Usage:
    .venv/bin/python scripts/diagnose_rwa_nonfinite.py \
        --data-path /path/to/data \
        --framework CRR \
        --permission-mode irb \
        --date 2025-01-01 \
        --format parquet

Exit code is 1 when any non-finite RWA is found (handy in CI), else 0.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import polars as pl

# Output columns whose non-finiteness is the symptom.
_RESULT_COLS = ("rwa_final", "ead_final", "risk_weight")

# Driver columns worth showing for a bad row (only those present are used). These
# are the usual IRB suspects plus the SA risk-weight inputs and EAD components.
_DRIVER_COLS = (
    "exposure_class",
    "approach_applied",
    "pd",
    "pd_floored",
    "lgd",
    "lgd_floored",
    "correlation",
    "maturity",
    "maturity_adjustment",
    "k",
    "drawn_amount",
    "undrawn_amount",
    "ccf_applied",
    "ead_final",
    "risk_weight",
    "rwa_final",
)


def main() -> int:
    args = _parse_args()

    from rwa_calc.api import CreditRiskCalc

    calc = CreditRiskCalc(
        data_path=args.data_path,
        framework=args.framework,
        reporting_date=date.fromisoformat(args.date),
        permission_mode=args.permission_mode,
        data_format=args.format,
    )
    response = calc.calculate()

    print(f"calculation success : {response.success}")
    print(f"total RWA           : {response.summary.total_rwa}")
    if response.errors:
        print(f"errors ({len(response.errors)}):")
        for err in response.errors[:20]:
            print(f"  - [{err.code}] {err.message}")

    df = response.collect_results()
    present_results = [c for c in _RESULT_COLS if c in df.columns]
    if not present_results:
        print("no rwa/ead/risk_weight columns on the results frame; nothing to check")
        return 0

    non_finite = pl.any_horizontal(
        [
            pl.col(c).cast(pl.Float64, strict=False).is_nan().fill_null(False)
            | pl.col(c).cast(pl.Float64, strict=False).is_infinite().fill_null(False)
            for c in present_results
        ]
    )
    bad = df.filter(non_finite)

    print(f"\nrows with non-finite {present_results}: {bad.height} of {df.height}")
    if bad.height == 0:
        print(
            "no non-finite RWA — your NaN total must come from elsewhere "
            "(check ead_final and any summary fields)."
        )
        return 0

    key = "exposure_reference" if "exposure_reference" in bad.columns else bad.columns[0]
    show_cols = [key, *[c for c in _DRIVER_COLS if c in bad.columns]]

    # Per-row, which driver columns are themselves non-finite (the likely cause).
    numeric_drivers = [
        c
        for c in show_cols
        if c != key and bad.schema[c] in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
    ]
    bad = bad.with_columns(
        pl.concat_str(
            [
                pl.when(
                    pl.col(c).cast(pl.Float64, strict=False).is_nan().fill_null(False)
                    | pl.col(c).cast(pl.Float64, strict=False).is_infinite().fill_null(False)
                )
                .then(pl.lit(c))
                .otherwise(pl.lit(None, dtype=pl.String))
                for c in numeric_drivers
            ],
            separator=",",
            ignore_nulls=True,
        ).alias("non_finite_drivers")
    )

    with pl.Config(tbl_width_chars=240, tbl_cols=-1, fmt_str_lengths=60):
        print(bad.select([*show_cols, "non_finite_drivers"]).head(args.limit))

    print(
        "\nReading this: 'non_finite_drivers' names the input/intermediate columns that "
        "are themselves NaN/inf for each bad row. If it is empty but rwa_final is NaN, the "
        "blow-up is in the IRB formula itself (e.g. very low/zero PD -> maturity-adjustment "
        "denominator (1 - 1.5b) crossing zero, or correlation >= 1) — check pd/lgd/maturity."
    )
    return 1


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-path", required=True)
    p.add_argument("--framework", default="CRR", choices=["CRR", "Basel 3.1"])
    p.add_argument("--permission-mode", default="standardised", choices=["standardised", "irb"])
    p.add_argument("--date", default="2025-01-01", help="reporting date (YYYY-MM-DD)")
    p.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    p.add_argument("--limit", type=int, default=50, help="max bad rows to print")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
