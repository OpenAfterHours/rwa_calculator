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


def _decision(status: str, reason: str = "") -> Decision:
    return Decision(status=status, reason=reason, decided_at="2026-06-27T10:00:00")


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
    progress = rv.breaks_signoff_progress(response, {l3: _decision("accepted", "ok")})
    assert progress["total"] == 1
    assert progress["reviewed"] == 1
    assert progress["open"] == 0
    assert progress["accepted"] == 1
    assert progress["rejected"] == 0
