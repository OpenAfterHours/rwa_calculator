"""
Unit tests for the reconciliation view helpers (ui/views/reconciliation.py).

Pipeline position:
    ReconciliationResponse -> ui.views.reconciliation -> dicts / DataFrames

Covers the four-tier presentation helpers (headline stats, chart-item builders,
the projected/​filtered forensic table), the wide-frame column projection, and
that the default TOML template the page ships actually parses.

The response is built directly from a synthetic ``ReconciliationBundle`` via
``ReconciliationRunner`` (no engine calculation), mirroring the engine unit-test
fixtures, so these stay fast and isolated.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.analysis.reconciliation import ReconciliationRunner
from rwa_calc.api.models import ReconciliationResponse
from rwa_calc.api.reconciliation import loads_reconciliation_config
from rwa_calc.ui.views import reconciliation as rv

# =============================================================================
# Fixtures
# =============================================================================


def _response() -> ReconciliationResponse:
    """A small reconciliation: EAD ties out, L3's RWA breaks (+20%)."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3"],
            "exposure_class": ["corporate", "retail", "corporate"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [100.0, 200.0, 500.0],
            "rwa_final": [50.0, 150.0, 250.0],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3"],
            "legacy_ead": [100.0, 200.0, 500.0],
            "legacy_rwa": [50.0, 150.0, 300.0],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


@pytest.fixture(scope="module")
def response() -> ReconciliationResponse:
    return _response()


# =============================================================================
# Tier 1 — headline
# =============================================================================


def test_headline_stats_one_row_per_additive_component(response: ReconciliationResponse) -> None:
    stats = rv.headline_stats(response)
    assert {s["component"] for s in stats} == {"ead", "rwa"}


def test_headline_stats_carry_our_and_legacy_totals(response: ReconciliationResponse) -> None:
    rwa = next(s for s in rv.headline_stats(response) if s["component"] == "rwa")
    assert rwa["our_total"] == pytest.approx(450.0)
    assert rwa["legacy_total"] == pytest.approx(500.0)


def test_abs_delta_chart_items_sorted_desc_nonnull(response: ReconciliationResponse) -> None:
    items = rv.abs_delta_chart_items(response)
    values = [v for _, v in items]
    assert values == sorted(values, reverse=True)
    # rwa has Σ|Δ| = |250-300| = 50; ead ties out at 0.
    assert items[0][0] == "RWA"
    assert items[0][1] == pytest.approx(50.0)


def test_tie_out_chart_items_are_triples(response: ReconciliationResponse) -> None:
    items = rv.tie_out_chart_items(response)
    assert all(len(it) == 3 for it in items)
    assert all(isinstance(it[1], float) and isinstance(it[2], float) for it in items)


# =============================================================================
# Tier 2 — asset-class allocation
# =============================================================================


def _response_with_class() -> ReconciliationResponse:
    """Like ``_response`` but with the class mapped, so allocation is populated."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3"],
            "exposure_class": ["corporate", "retail", "corporate"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [100.0, 200.0, 500.0],
            "rwa_final": [50.0, 150.0, 250.0],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3"],
            "legacy_ead": [100.0, 200.0, 500.0],
            "legacy_rwa": [50.0, 150.0, 300.0],
            "legacy_exposure_class": ["corporate", "retail", "corporate"],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={
            "ead": ComponentMapping("EAD"),
            "rwa": ComponentMapping("RWA"),
            "exposure_class": ComponentMapping("legacy_exposure_class"),
        },
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    return ReconciliationResponse.from_bundle(
        bundle, legacy_file=Path("legacy.csv"), framework="CRR"
    )


def test_class_allocation_table_totals_per_class() -> None:
    df = rv.class_allocation_table(_response_with_class())
    corp = df.filter(pl.col("exposure_class") == "corporate").row(0, named=True)
    assert corp["our_rwa"] == pytest.approx(300.0)  # L1 50 + L3 250
    assert corp["legacy_rwa"] == pytest.approx(350.0)  # L1 50 + L3 300


def test_class_allocation_chart_items_are_triples() -> None:
    items = rv.class_allocation_chart_items(_response_with_class())
    assert items
    assert all(len(it) == 3 for it in items)


def test_class_allocation_empty_when_unmapped(response: ReconciliationResponse) -> None:
    # The base fixture maps no class -> empty allocation table and no chart items.
    assert rv.class_allocation_table(response).height == 0
    assert rv.class_allocation_chart_items(response) == []


# =============================================================================
# Tier 4 — forensic table projection + filter
# =============================================================================


def test_forensic_break_filter_returns_only_break_rows(response: ReconciliationResponse) -> None:
    columns, rows, total = rv.forensic_table(response, rv.BUCKET_BREAK)
    assert total == 1  # only L3 breaks
    assert all(row["row_bucket"] == rv.BUCKET_BREAK for row in rows)
    assert "row_bucket" in columns


def test_forensic_all_returns_every_key(response: ReconciliationResponse) -> None:
    _, _, total = rv.forensic_table(response, rv.ALL_BUCKETS)
    assert total == 3


def test_forensic_limit_caps_rows_but_not_total(response: ReconciliationResponse) -> None:
    _, rows, total = rv.forensic_table(response, rv.ALL_BUCKETS, limit=1)
    assert len(rows) == 1
    assert total == 3


def test_forensic_columns_exclude_wide_detail(response: ReconciliationResponse) -> None:
    columns, _, _ = rv.forensic_table(response, rv.ALL_BUCKETS)
    assert "our_rwa" in columns and "legacy_rwa" in columns and "rwa_bucket" in columns
    assert not any(c.startswith("rel_delta_") for c in columns)


# =============================================================================
# Column projection (pure)
# =============================================================================


def test_readable_recon_columns_drops_rel_delta_and_explain() -> None:
    df = pl.DataFrame(
        {
            "_recon_key": ["a"],
            "our_rwa": [1.0],
            "legacy_rwa": [1.5],
            "rwa_bucket": ["break"],
            "abs_delta_rwa": [-0.5],
            "rel_delta_rwa": [-0.33],
            "irb_pd_original": ["0.01"],
            "worst_component": ["rwa"],
            "row_bucket": ["break"],
        }
    )
    cols = rv._readable_recon_columns(df)
    assert "rel_delta_rwa" not in cols
    assert "irb_pd_original" not in cols
    assert cols[0] == "_recon_key"
    assert cols[-1] == "row_bucket"


# =============================================================================
# Defaults
# =============================================================================


def test_default_mapping_toml_parses() -> None:
    settings = loads_reconciliation_config(rv.DEFAULT_MAPPING_TOML, base_dir=".")
    assert set(settings.mapping.components) == {"ead", "rwa", "exposure_class"}


def test_bucket_choices_lead_with_all_then_break() -> None:
    assert rv.BUCKET_CHOICES[0] == rv.ALL_BUCKETS
    assert rv.BUCKET_CHOICES[1] == rv.BUCKET_BREAK
