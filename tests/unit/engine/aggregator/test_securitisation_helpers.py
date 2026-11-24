"""Unit tests for the aggregator securitisation helpers.

Covers ``apply_residual_multiplier``, ``generate_securitisation_summary``,
and ``generate_securitisation_audit`` -- the three helpers wired into
OutputAggregator.aggregate() to produce the on-balance-sheet view, the
per-pool summary, and the per-exposure reconciliation report -- plus the
residual view's hand-off to the expected-loss summary (P1.210: the
Art. 159(1) 'D' carrier is scaled with the provision it is part of).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
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
        # ``provision_specific_allocated`` is the Art. 159(1) 'D' carrier: it
        # must scale with ``provision_allocated``, which it is a part of.
        for col in (
            "ead_final",
            "rwa_final",
            "expected_loss",
            "sa_rwa",
            "provision_allocated",
            "provision_specific_allocated",
        ):
            assert col in MONEY_COLS


class TestResidualMultiplierKeepsTheArt159Split:
    """The residual view feeds the EL summary a 'D' scaled with its provision.

    The aggregator passes ``apply_residual_multiplier(irb_results)`` to
    ``compute_el_portfolio_summary``, which takes 'D' as the defaulted
    ``provision_specific_allocated`` and 'B' as the rest of Pool B. If the
    specific carrier were not scaled, an unscaled 'D' would be taken out of a
    scaled provision.

    References:
        PS1/26 Art. 159(1)/(3); CRR Art. 244(1) / 245(1).
    """

    def test_securitised_defaulted_row_splits_on_the_residual(self) -> None:
        """Shortfall 16,000 and excess 8,000 on the on-balance-sheet residual.

        Non-defaulted row (residual 1.0): EL 100,000 = A; provisions 80,000,
            all specific -> 'B' 80,000.
        Defaulted row (residual 0.4): EL 50,000 -> C = 20,000; provisions
            80,000 of which 70,000 specific -> 'D' = 0.4 x 70,000 = 28,000 and
            general 0.4 x 10,000 = 4,000 to 'B'.
        B = 84,000 < A and D > C -> Art. 159(3)(a)/(b): 16,000 / 8,000.
        An unscaled carrier gives 58,000 / 50,000 (B = 80,000 + 32,000 - 70,000).
        """
        # Arrange
        rows = pl.LazyFrame(
            {
                "exposure_reference": ["ND", "D"],
                "approach_applied": ["AIRB", "AIRB"],
                "rwa_final": [5_000_000.0, 5_000_000.0],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "expected_loss": [100_000.0, 50_000.0],
                "provision_allocated": [80_000.0, 80_000.0],
                "provision_specific_allocated": [80_000.0, 70_000.0],
                "ava_amount": [0.0, 0.0],
                "other_own_funds_reductions": [0.0, 0.0],
                "el_shortfall": [20_000.0, 0.0],
                "el_excess": [0.0, 30_000.0],
                "is_defaulted": [False, True],
                "securitisation_residual_pct": [1.0, 0.4],
            }
        )

        # Act
        summary = compute_el_portfolio_summary(apply_residual_multiplier(rows))

        # Assert
        assert summary is not None
        assert summary.art_159_3_applies is True
        assert float(summary.total_el_shortfall) == pytest.approx(16_000.0)
        assert float(summary.total_el_excess) == pytest.approx(8_000.0)


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
