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


# =============================================================================
# Phase 2 — progressive-disclosure explorer / loan helpers
# =============================================================================


def test_biggest_breaks_ranked_and_capped(response: ReconciliationResponse) -> None:
    df = rv.biggest_breaks(response, limit=10)
    # Only L3's RWA breaks in the base fixture.
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["_recon_key"] == "L3"
    assert row["component"] == "rwa"


def test_biggest_breaks_limit_caps_rows() -> None:
    # A fixture with two breaks, then ask for only the largest one.
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["A", "B"],
            "exposure_class": ["corporate", "retail"],
            "approach_applied": ["SA", "SA"],
            "ead_final": [100.0, 100.0],
            "rwa_final": [10.0, 10.0],
        }
    )
    legacy = pl.LazyFrame(
        {"exposure_reference": ["A", "B"], "legacy_ead": [100.0, 100.0], "legacy_rwa": [40.0, 20.0]}
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    resp = ReconciliationResponse.from_bundle(bundle, legacy_file=Path("legacy.csv"))

    top = rv.biggest_breaks(resp, limit=1)
    assert top.height == 1
    assert top.row(0, named=True)["_recon_key"] == "A"  # |Δ|=30 ranks above B's 10


def test_forensic_page_returns_all_keys_unfiltered(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters())
    assert page.total == 3
    assert len(page.rows) == 3
    assert page.page == 1
    assert page.pages == 1
    assert "_recon_key" in page.columns


def test_forensic_page_bucket_filter(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(bucket=rv.BUCKET_BREAK))
    assert page.total == 1
    assert all(row["row_bucket"] == rv.BUCKET_BREAK for row in page.rows)


def test_forensic_page_key_query_is_literal(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(query="L3"))
    assert page.total == 1
    assert page.rows[0]["_recon_key"] == "L3"


def test_forensic_page_paginates(response: ReconciliationResponse) -> None:
    first = rv.forensic_page(response, rv.ForensicFilters(page=1, page_size=2))
    assert len(first.rows) == 2
    assert first.total == 3
    assert first.pages == 2
    second = rv.forensic_page(response, rv.ForensicFilters(page=2, page_size=2))
    assert len(second.rows) == 1
    assert second.offset == 2


def test_forensic_page_page_clamped_to_last(response: ReconciliationResponse) -> None:
    # Asking past the end returns the last page, not an empty slice.
    page = rv.forensic_page(response, rv.ForensicFilters(page=99, page_size=2))
    assert page.page == 2
    assert page.rows


def test_forensic_page_sort_by_known_column(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(sort="abs_delta_rwa", descending=True))
    deltas = [row["abs_delta_rwa"] for row in page.rows if row["abs_delta_rwa"] is not None]
    assert deltas == sorted(deltas, reverse=True)


def test_forensic_page_unknown_sort_column_raises(response: ReconciliationResponse) -> None:
    with pytest.raises(ValueError, match="unknown sort column"):
        rv.forensic_page(response, rv.ForensicFilters(sort="not_a_column"))


def test_forensic_page_size_clamped_to_max(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(page_size=10_000_000))
    assert page.page_size == rv.MAX_PAGE_SIZE


def test_forensic_filter_options_from_summaries(response: ReconciliationResponse) -> None:
    options = rv.forensic_filter_options(response)
    assert rv.BUCKET_BREAK in options["bucket"]
    assert "corporate" in options["exposure_class"]
    assert options["approach"]  # at least the SA approach is present


def test_loan_detail_surfaces_components_and_breaks(response: ReconciliationResponse) -> None:
    detail = rv.loan_detail(response, "L3")
    assert detail is not None
    assert detail["recon_key"] == "L3"
    assert detail["row_bucket"] == rv.BUCKET_BREAK
    rwa_panel = next(p for p in detail["panels"] if p["component"] == "rwa")
    assert rwa_panel["legacy"] == pytest.approx(300.0)
    assert rwa_panel["ours"] == pytest.approx(250.0)
    assert rwa_panel["bucket"] == rv.BUCKET_BREAK
    assert detail["breaks"]["rows"]  # the L3 rwa break row


def test_loan_detail_unknown_key_returns_none(response: ReconciliationResponse) -> None:
    assert rv.loan_detail(response, "NOPE") is None


# =============================================================================
# Phase 5A — RWA-driver chain (ordered steps + grouped drivers)
# =============================================================================


def _response_with_drivers() -> ReconciliationResponse:
    """One loan with risk_weight mapped and our-side RW drivers populated."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["SA"],
            "ead_final": [100.0],
            "rwa_final": [75.0],
            "risk_weight": [0.75],
            "external_cqs": [3],
            "property_ltv": [0.8],
            "ltv_band": ["60-80%"],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "legacy_ead": [100.0],
            "legacy_rwa": [75.0],
            "legacy_risk_weight": [0.75],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={
            "ead": ComponentMapping("EAD"),
            "rwa": ComponentMapping("RWA"),
            "risk_weight": ComponentMapping("RW"),
        },
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    return ReconciliationResponse.from_bundle(bundle, legacy_file=Path("legacy.csv"))


def test_loan_detail_steps_follow_rwa_chain_order(response: ReconciliationResponse) -> None:
    detail = rv.loan_detail(response, "L3")
    assert detail is not None
    # Only ead + rwa are mapped in the base fixture; the chain order puts ead first.
    assert [s["step"] for s in detail["steps"]] == ["ead", "rwa"]


def test_loan_detail_step_carries_legacy_ours_and_bucket(response: ReconciliationResponse) -> None:
    detail = rv.loan_detail(response, "L3")
    assert detail is not None
    rwa_step = next(s for s in detail["steps"] if s["step"] == "rwa")
    assert rwa_step["legacy"] == pytest.approx(300.0)
    assert rwa_step["ours"] == pytest.approx(250.0)
    assert rwa_step["bucket"] == rv.BUCKET_BREAK


def test_loan_detail_groups_drivers_under_owning_component() -> None:
    detail = rv.loan_detail(_response_with_drivers(), "L1")
    assert detail is not None
    rw_step = next(s for s in detail["steps"] if s["step"] == "risk_weight")
    driver_names = {d["name"] for d in rw_step["drivers"]}
    assert {"external_cqs", "property_ltv", "ltv_band"} <= driver_names


def test_loan_detail_drivers_are_our_side_only() -> None:
    detail = rv.loan_detail(_response_with_drivers(), "L1")
    assert detail is not None
    rw_step = next(s for s in detail["steps"] if s["step"] == "risk_weight")
    cqs = next(d for d in rw_step["drivers"] if d["name"] == "external_cqs")
    assert cqs["ours"] == 3
    assert cqs["legacy_available"] is False
    assert cqs["legacy"] is None


# =============================================================================
# Phase 5B — collateral / guarantee / cqs promoted to reconcilable components
# =============================================================================


def _response_with_crm_components() -> ReconciliationResponse:
    """A loan whose collateral, guarantee and CQS are mapped legacy-vs-ours."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["SA"],
            "ead_final": [100.0],
            "rwa_final": [75.0],
            "collateral_adjusted_value": [40.0],
            "guaranteed_portion": [10.0],
            "sa_cqs": [3],
        }
    )
    legacy = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "legacy_ead": [100.0],
            "legacy_rwa": [75.0],
            "legacy_collateral": [35.0],
            "legacy_guarantee": [10.0],
            "legacy_cqs": [3],
        }
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={
            "ead": ComponentMapping("EAD"),
            "rwa": ComponentMapping("RWA"),
            "collateral": ComponentMapping("Collateral_Value"),
            "guarantee": ComponentMapping("Guarantee_Benefit"),
            "cqs": ComponentMapping("CQS"),
        },
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    return ReconciliationResponse.from_bundle(bundle, legacy_file=Path("legacy.csv"))


def test_new_components_are_registered() -> None:
    from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS_BY_NAME

    assert {"collateral", "guarantee", "cqs"} <= set(RECONCILABLE_COMPONENTS_BY_NAME)


def test_collateral_break_is_bucketed_legacy_vs_ours() -> None:
    detail = rv.loan_detail(_response_with_crm_components(), "L1")
    assert detail is not None
    coll = next(s for s in detail["steps"] if s["step"] == "collateral")
    assert coll["ours"] == pytest.approx(40.0)
    assert coll["legacy"] == pytest.approx(35.0)
    assert coll["bucket"] == rv.BUCKET_BREAK


def test_collateral_step_precedes_ead_in_chain() -> None:
    detail = rv.loan_detail(_response_with_crm_components(), "L1")
    assert detail is not None
    names = [s["step"] for s in detail["steps"]]
    assert names.index("collateral") < names.index("ead")
    assert names.index("guarantee") < names.index("ead")
    assert names.index("cqs") < names.index("ead")


def test_mapped_crm_driver_not_duplicated_under_ead() -> None:
    # When collateral/guarantee are mapped as their own steps they must NOT also
    # appear as EAD driver rows (the chain de-dup owns them at their own step).
    detail = rv.loan_detail(_response_with_crm_components(), "L1")
    assert detail is not None
    ead = next(s for s in detail["steps"] if s["step"] == "ead")
    ead_drivers = {d["name"] for d in ead["drivers"]}
    assert "collateral_adjusted_value" not in ead_drivers
    assert "guaranteed_portion" not in ead_drivers


def test_unmapped_crm_shows_as_ead_driver() -> None:
    # With collateral/guarantee NOT mapped, our-side values stay visible under EAD.
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "exposure_class": ["corporate"],
            "approach_applied": ["SA"],
            "ead_final": [100.0],
            "rwa_final": [75.0],
            "collateral_adjusted_value": [40.0],
            "guaranteed_portion": [10.0],
        }
    )
    legacy = pl.LazyFrame(
        {"exposure_reference": ["L1"], "legacy_ead": [100.0], "legacy_rwa": [75.0]}
    )
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components={"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")},
    )
    bundle = ReconciliationRunner().reconcile(ours, legacy, mapping)
    resp = ReconciliationResponse.from_bundle(bundle, legacy_file=Path("legacy.csv"))

    detail = rv.loan_detail(resp, "L1")
    assert detail is not None
    ead = next(s for s in detail["steps"] if s["step"] == "ead")
    coll = next(d for d in ead["drivers"] if d["name"] == "collateral_adjusted_value")
    assert coll["ours"] == pytest.approx(40.0)
    assert coll["legacy_available"] is False
