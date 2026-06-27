"""
Unit tests for the sign-off layer of the reconciliation views.

Pipeline position:
    ReconciliationResponse + decisions -> ui.views.reconciliation
        -> annotated frame / filtered explorer page / worklist burndown

Covers:
- ``annotate_signoff`` derives ``signoff_status`` (matched / open / accepted /
  rejected) and carries the reason.
- ``forensic_page`` default-Open hides matched + dispositioned rows; the status
  filter returns them.
- ``biggest_breaks`` drops reviewed keys (worklist burndown).
- ``breaks_signoff_progress`` counts distinct breaking keys vs reviewed.

The response is the same tiny synthetic reconcile used by the sibling view tests:
EAD ties out, L3's RWA breaks; L1/L2 are exact matches.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.analysis.reconciliation import ReconciliationRunner
from rwa_calc.api.models import ReconciliationResponse
from rwa_calc.ui.app.recon_signoff import Decision
from rwa_calc.ui.views import reconciliation as rv


def _response() -> ReconciliationResponse:
    """EAD ties out; L3's RWA breaks (+20%); L1/L2 are exact matches."""
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


def _key_for(response: ReconciliationResponse, suffix: str) -> str:
    """The actual _recon_key whose value ends with *suffix* (e.g. 'L3')."""
    df = response.collect_component_reconciliation()
    keys = df.get_column("_recon_key").to_list()
    return next(k for k in keys if str(k).upper().endswith(suffix))


def _decision(status: str, reason: str = "", fingerprint: str = "") -> Decision:
    return Decision(
        status=status, reason=reason, decided_at="2026-06-27T10:00:00", fingerprint=fingerprint
    )


# =============================================================================
# annotate_signoff
# =============================================================================


def test_annotate_marks_exact_rows_matched_and_breaks_open(
    response: ReconciliationResponse,
) -> None:
    df = rv.annotate_signoff(response.collect_component_reconciliation(), {})
    by_key = {str(r["_recon_key"]).upper(): r["signoff_status"] for r in df.iter_rows(named=True)}
    assert by_key["L3"] == rv.SIGNOFF_OPEN
    assert by_key["L1"] == rv.SIGNOFF_MATCHED
    assert by_key["L2"] == rv.SIGNOFF_MATCHED


def test_annotate_applies_decision_status_and_reason(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    df = rv.annotate_signoff(
        response.collect_component_reconciliation(),
        {l3: _decision("accepted", "FX timing")},
    )
    row = next(r for r in df.iter_rows(named=True) if r["_recon_key"] == l3)
    assert row["signoff_status"] == rv.SIGNOFF_ACCEPTED
    assert row["signoff_reason"] == "FX timing"


# =============================================================================
# forensic_page status filter
# =============================================================================


def test_forensic_page_open_hides_matched_and_dispositioned(
    response: ReconciliationResponse,
) -> None:
    l3 = _key_for(response, "L3")
    filters = rv.ForensicFilters(status=rv.SIGNOFF_OPEN)

    # No decisions: only the open break (L3) shows.
    open_only = rv.forensic_page(response, filters, {})
    assert {str(r["_recon_key"]).upper() for r in open_only.rows} == {"L3"}

    # Accept L3: the Open worklist is now empty.
    accepted = rv.forensic_page(response, filters, {l3: _decision("accepted", "ok")})
    assert accepted.rows == []


def test_forensic_page_status_filter_returns_accepted(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    page = rv.forensic_page(
        response,
        rv.ForensicFilters(status=rv.SIGNOFF_ACCEPTED),
        {l3: _decision("accepted", "ok")},
    )
    assert {str(r["_recon_key"]).upper() for r in page.rows} == {"L3"}


def test_forensic_page_all_status_shows_every_row(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(status=None), {})
    assert {str(r["_recon_key"]).upper() for r in page.rows} == {"L1", "L2", "L3"}


def test_forensic_page_exposes_signoff_columns(response: ReconciliationResponse) -> None:
    page = rv.forensic_page(response, rv.ForensicFilters(status=None), {})
    assert "signoff_status" in page.columns
    assert "signoff_reason" in page.columns


# =============================================================================
# worklist burndown
# =============================================================================


def test_biggest_breaks_drops_reviewed_keys(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    before = rv.biggest_breaks(response, {})
    after = rv.biggest_breaks(response, {l3: _decision("rejected", "real error")})
    assert before.height >= 1
    assert after.height == before.height - 1


def test_breaks_signoff_progress_counts_reviewed(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    current = rv.recon_fingerprint(response, l3)
    progress = rv.breaks_signoff_progress(
        response, {l3: _decision("accepted", "ok", current)}, {l3: current}
    )
    assert progress["total"] == 1
    assert progress["reviewed"] == 1
    assert progress["open"] == 0
    assert progress["accepted"] == 1
    assert progress["rejected"] == 0
    assert progress["changed"] == 0


# =============================================================================
# Staleness — a moved difference re-flags an old decision
# =============================================================================


def test_delta_band_absorbs_float_noise_but_catches_real_change() -> None:
    base = rv._delta_band(1234.0)
    assert rv._delta_band(1234.0 + 1e-6) == base  # sub-band noise -> unchanged
    assert rv._delta_band(1234.0 * 1.5) != base  # a real 50% move -> changed


def test_recon_fingerprint_is_deterministic(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    fp = rv.recon_fingerprint(response, l3)
    assert fp != ""
    assert fp == rv.recon_fingerprint(response, l3)


def test_is_signoff_stale_rules() -> None:
    no_fp = Decision(status="accepted", reason="x", decided_at="t")  # fingerprint=""
    assert rv.is_signoff_stale(no_fp, "anything") is False  # can't judge -> not stale
    fp = Decision(status="accepted", reason="x", decided_at="t", fingerprint="FP1")
    assert rv.is_signoff_stale(fp, "FP1") is False
    assert rv.is_signoff_stale(fp, "FP2") is True
    assert rv.is_signoff_stale(fp, None) is False  # row gone -> not stale


def test_annotate_flags_stale_decision_back_to_open(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    current = rv.recon_fingerprint(response, l3)
    moved = Decision(status="accepted", reason="old", decided_at="t", fingerprint=current + "X")
    df = rv.annotate_signoff(
        response.collect_component_reconciliation(), {l3: moved}, {l3: current}
    )
    row = next(r for r in df.iter_rows(named=True) if r["_recon_key"] == l3)
    assert row["signoff_status"] == rv.SIGNOFF_OPEN
    assert row["signoff_stale"] is True


def test_annotate_keeps_unchanged_decision(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    current = rv.recon_fingerprint(response, l3)
    fresh = Decision(status="accepted", reason="ok", decided_at="t", fingerprint=current)
    df = rv.annotate_signoff(
        response.collect_component_reconciliation(), {l3: fresh}, {l3: current}
    )
    row = next(r for r in df.iter_rows(named=True) if r["_recon_key"] == l3)
    assert row["signoff_status"] == rv.SIGNOFF_ACCEPTED
    assert row["signoff_stale"] is False


def test_biggest_breaks_keeps_stale_drops_unchanged(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    current = rv.recon_fingerprint(response, l3)
    fresh = Decision(status="accepted", reason="ok", decided_at="t", fingerprint=current)
    moved = Decision(status="accepted", reason="old", decided_at="t", fingerprint=current + "X")
    assert rv.biggest_breaks(response, {l3: fresh}, {l3: current}).height == 0
    assert rv.biggest_breaks(response, {l3: moved}, {l3: current}).height >= 1


def test_progress_counts_stale_as_open_and_changed(response: ReconciliationResponse) -> None:
    l3 = _key_for(response, "L3")
    current = rv.recon_fingerprint(response, l3)
    moved = Decision(status="accepted", reason="old", decided_at="t", fingerprint=current + "X")
    progress = rv.breaks_signoff_progress(response, {l3: moved}, {l3: current})
    assert progress["reviewed"] == 0
    assert progress["open"] == 1
    assert progress["changed"] == 1


# =============================================================================
# Staleness — the difference MOVING (not just growing), and resolution
# =============================================================================


def _build(
    *,
    our_rwa: float = 50.0,
    legacy_rwa: float = 50.0,
    our_ead: float = 100.0,
    legacy_ead: float = 100.0,
    our_class: str = "corporate",
    legacy_class: str | None = None,
) -> ReconciliationResponse:
    """A one-row reconciliation (key L1) with controllable per-component breaks."""
    ours = pl.LazyFrame(
        {
            "exposure_reference": ["L1"],
            "exposure_class": [our_class],
            "approach_applied": ["SA"],
            "ead_final": [our_ead],
            "rwa_final": [our_rwa],
        }
    )
    legacy_data: dict = {
        "exposure_reference": ["L1"],
        "legacy_ead": [legacy_ead],
        "legacy_rwa": [legacy_rwa],
    }
    components = {"ead": ComponentMapping("EAD"), "rwa": ComponentMapping("RWA")}
    if legacy_class is not None:
        legacy_data["legacy_exposure_class"] = [legacy_class]
        components["exposure_class"] = ComponentMapping("Asset_Class")
    mapping = LegacyColumnMapping(
        legacy_keys=("exposure_reference",),
        our_keys=("exposure_reference",),
        components=components,
    )
    bundle = ReconciliationRunner().reconcile(ours, pl.LazyFrame(legacy_data), mapping)
    return ReconciliationResponse.from_bundle(bundle, legacy_file=Path("l.csv"), framework="CRR")


def _signoff_status(resp: ReconciliationResponse, key: str, decision: Decision) -> tuple:
    current = rv.recon_fingerprint(resp, key)
    df = rv.annotate_signoff(
        resp.collect_component_reconciliation(), {key: decision}, {key: current}
    )
    row = next(r for r in df.iter_rows(named=True) if r["_recon_key"] == key)
    return row["signoff_status"], row["signoff_stale"]


def test_moved_categorical_break_is_flagged_stale() -> None:
    # The worst-case the feature exists to prevent: a class reclassification on an
    # already-accepted categorical break (abs_delta is null for categoricals).
    a = _build(legacy_class="retail")  # our corporate vs legacy retail -> break
    key = _key_for(a, "L1")
    fp_a = rv.recon_fingerprint(a, key)
    b = _build(legacy_class="sovereign")  # our corporate vs legacy sovereign -> moved
    fp_b = rv.recon_fingerprint(b, key)
    assert fp_a != fp_b  # the categorical value moved -> fingerprint changes
    accepted = Decision(status="accepted", reason="ok", decided_at="t", fingerprint=fp_a)
    assert rv.is_signoff_stale(accepted, fp_b) is True
    # It is NOT waved through: the moved break stays on the worklist.
    assert rv.biggest_breaks(b, {key: accepted}, {key: fp_b}).height >= 1


def test_break_moving_to_a_different_component_is_flagged_stale() -> None:
    a = _build(our_rwa=50.0, legacy_rwa=60.0)  # RWA breaks, EAD ties
    key = _key_for(a, "L1")
    fp_a = rv.recon_fingerprint(a, key)
    b = _build(our_ead=100.0, legacy_ead=130.0)  # now EAD breaks, RWA ties
    fp_b = rv.recon_fingerprint(b, key)
    assert fp_a != fp_b
    accepted = Decision(status="accepted", reason="ok", decided_at="t", fingerprint=fp_a)
    status, stale = _signoff_status(b, key, accepted)
    assert status == rv.SIGNOFF_OPEN
    assert stale is True


def test_fixed_row_with_lingering_decision_shows_matched_not_stale() -> None:
    resp = _build(our_rwa=50.0, legacy_rwa=50.0)  # everything ties out now
    key = _key_for(resp, "L1")
    old_break = Decision(
        status="accepted", reason="old", decided_at="t", fingerprint="break|rwa:break:5e1~6e1"
    )
    status, stale = _signoff_status(resp, key, old_break)
    assert status == rv.SIGNOFF_MATCHED
    assert stale is False


def test_within_tolerance_improvement_with_decision_is_not_stale() -> None:
    resp = _build(our_rwa=50.0, legacy_rwa=50.3)  # 0.6% < 1% rwa tol -> within_tolerance
    key = _key_for(resp, "L1")
    old_break = Decision(
        status="accepted", reason="old", decided_at="t", fingerprint="break|rwa:break:5e1~6e1"
    )
    status, stale = _signoff_status(resp, key, old_break)
    assert stale is False  # resolved into tolerance — not re-flagged
    assert status == rv.SIGNOFF_ACCEPTED


def test_delta_band_is_canonical_at_a_decade_boundary() -> None:
    # A value a hair below a power of ten must band identically to the power of ten,
    # so float-sum noise across the boundary cannot false-flag stale.
    assert rv._delta_band(1000.0) == rv._delta_band(999.999999999)
    assert rv._delta_band(1000.0) == "1.000e+03"


def test_fingerprints_are_safe_on_a_failed_empty_response() -> None:
    # A failed re-run with prior decisions must not raise (column-less wide frame).
    from rwa_calc.contracts.bundles import create_empty_reconciliation_bundle

    empty = ReconciliationResponse.from_bundle(
        create_empty_reconciliation_bundle(), legacy_file=Path("l.csv"), framework="CRR"
    )
    decisions = {"L1": Decision(status="accepted", reason="x", decided_at="t", fingerprint="fp")}
    assert rv.current_fingerprints(empty, decisions) == {}
    assert rv.recon_fingerprint(empty, "L1") == ""
