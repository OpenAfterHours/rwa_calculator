"""Unit tests for the aggregator securitisation helpers.

Covers ``apply_residual_multiplier``, ``generate_securitisation_summary``,
and ``generate_securitisation_audit`` -- the three helpers wired into
OutputAggregator.aggregate() to produce the on-balance-sheet view, the
per-pool summary, and the per-exposure reconciliation report.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._securitisation import (
    MONEY_COLS,
    apply_residual_multiplier,
    generate_securitisation_audit,
    generate_securitisation_summary,
)


def _row(allocs: list[dict] | None = None, residual: float = 1.0) -> dict:
    """Build a single per-row dict with the canonical money columns."""
    return {
        "exposure_reference": "L001",
        "exposure_type": "loan",
        "exposure_class": "corporate",
        "ead_final": 1_000_000.0,
        "rwa_final": 610_000.0,
        "expected_loss": 0.0,
        "sa_rwa": 1_000_000.0,
        "rwa_post_factor": 610_000.0,
        "securitisation_residual_pct": residual,
        "securitisation_pool_allocations": allocs or [],
    }


class TestApplyResidualMultiplier:
    def test_noop_when_residual_pct_missing(self) -> None:
        df = pl.LazyFrame({"ead_final": [1000.0], "rwa_final": [500.0]})
        out = apply_residual_multiplier(df).collect()
        assert out["ead_final"][0] == 1000.0
        assert out["rwa_final"][0] == 500.0

    def test_noop_when_residual_pct_is_one(self) -> None:
        df = pl.LazyFrame([_row(residual=1.0)])
        out = apply_residual_multiplier(df).collect()
        assert out["ead_final"][0] == pytest.approx(1_000_000.0)
        assert out["rwa_final"][0] == pytest.approx(610_000.0)

    def test_scales_every_money_column(self) -> None:
        df = pl.LazyFrame([_row(residual=0.4)])
        out = apply_residual_multiplier(df).collect()
        assert out["ead_final"][0] == pytest.approx(400_000.0)
        assert out["rwa_final"][0] == pytest.approx(244_000.0)
        assert out["sa_rwa"][0] == pytest.approx(400_000.0)
        assert out["rwa_post_factor"][0] == pytest.approx(244_000.0)

    def test_null_residual_pct_treated_as_one(self) -> None:
        df = pl.LazyFrame(
            {
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "securitisation_residual_pct": [None],
            },
            schema={
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
                "securitisation_residual_pct": pl.Float64,
            },
        )
        out = apply_residual_multiplier(df).collect()
        assert out["ead_final"][0] == pytest.approx(1000.0)

    def test_money_cols_constant_includes_critical_columns(self) -> None:
        for col in ("ead_final", "rwa_final", "expected_loss", "sa_rwa"):
            assert col in MONEY_COLS


class TestGenerateSecuritisationSummary:
    def test_returns_none_when_no_allocations(self) -> None:
        df = pl.LazyFrame([_row(residual=1.0)])
        assert generate_securitisation_summary(df) is None

    def test_per_pool_grouping(self) -> None:
        df = pl.LazyFrame(
            [
                _row(
                    allocs=[
                        {"pool_reference": "POOL_A", "allocation_pct": 0.3},
                        {"pool_reference": "POOL_B", "allocation_pct": 0.3},
                    ],
                    residual=0.4,
                )
            ]
        )
        summary_lf = generate_securitisation_summary(df)
        assert summary_lf is not None
        summary = summary_lf.collect()
        assert summary.height == 2
        rows = {r["pool_reference"]: r for r in summary.iter_rows(named=True)}
        # 1m EAD x 30% = 300k for each pool
        assert rows["POOL_A"]["total_ead"] == pytest.approx(300_000.0)
        assert rows["POOL_B"]["total_ead"] == pytest.approx(300_000.0)
        # 610k RWA x 30% = 183k for each pool (placeholder; not regulatory)
        assert rows["POOL_A"]["total_rwa_placeholder"] == pytest.approx(183_000.0)
        assert rows["POOL_A"]["exposure_count"] == 1

    def test_aggregates_across_multiple_exposures(self) -> None:
        df = pl.LazyFrame(
            [
                _row(allocs=[{"pool_reference": "POOL_A", "allocation_pct": 0.5}], residual=0.5),
                {
                    **_row(
                        allocs=[{"pool_reference": "POOL_A", "allocation_pct": 0.4}],
                        residual=0.6,
                    ),
                    "exposure_reference": "L002",
                    "ead_final": 500_000.0,
                    "rwa_final": 250_000.0,
                },
            ]
        )
        summary_lf = generate_securitisation_summary(df)
        assert summary_lf is not None
        summary = summary_lf.collect()
        row = summary.row(0, named=True)
        # L001 contributes 500k, L002 contributes 200k -> total 700k
        assert row["total_ead"] == pytest.approx(700_000.0)
        assert row["exposure_count"] == 2


class TestGenerateSecuritisationAudit:
    def test_returns_none_when_no_resolved_lookup(self) -> None:
        df = pl.LazyFrame([_row()])
        assert generate_securitisation_audit(df, None) is None

    def test_reconciliation_balances(self) -> None:
        """parent_ead - residual_ead - securitised_ead must be 0."""
        df = pl.LazyFrame(
            [
                _row(
                    allocs=[
                        {"pool_reference": "POOL_A", "allocation_pct": 0.4},
                        {"pool_reference": "POOL_B", "allocation_pct": 0.3},
                    ],
                    residual=0.3,
                )
            ]
        )
        resolved = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "securitisation_residual_pct": [0.3],
                "securitisation_pool_allocations": [
                    [
                        {"pool_reference": "POOL_A", "allocation_pct": 0.4},
                        {"pool_reference": "POOL_B", "allocation_pct": 0.3},
                    ]
                ],
                "total_allocated_pct": [0.7],
                "audit_status": ["ok"],
            }
        )
        audit_lf = generate_securitisation_audit(df, resolved)
        assert audit_lf is not None
        audit = audit_lf.collect()
        row = audit.row(0, named=True)
        assert row["parent_ead"] == pytest.approx(1_000_000.0)
        assert row["residual_ead"] == pytest.approx(300_000.0)
        assert row["securitised_ead"] == pytest.approx(700_000.0)
        assert row["reconciliation_delta"] == pytest.approx(0.0, abs=1e-6)
        assert row["audit_status"] == "ok"

    def test_audit_status_propagates_from_resolved(self) -> None:
        df = pl.LazyFrame([_row(residual=1.0)])
        resolved = pl.LazyFrame(
            {
                "exposure_reference": ["L001"],
                "exposure_type": ["loan"],
                "securitisation_residual_pct": [1.0],
                "securitisation_pool_allocations": [
                    [{"pool_reference": "POOL_A", "allocation_pct": 1.2}]
                ],
                "total_allocated_pct": [1.2],
                "audit_status": ["over_allocated"],
            }
        )
        audit_lf = generate_securitisation_audit(df, resolved)
        assert audit_lf is not None
        audit = audit_lf.collect()
        assert audit.row(0, named=True)["audit_status"] == "over_allocated"
