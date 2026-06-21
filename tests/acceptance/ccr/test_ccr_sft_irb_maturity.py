"""
CCR-SFT-IRB-* acceptance: FCCM SFTs routed to IRB receive the Art. 162
effective maturity M, asserted DIRECTLY on the synthetic ``ccr__<NS>`` row.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> sft_fccm
    -> IRBCalculator (maturity chain) -> OutputAggregator

Scenario (CCR/SFT IRB effective-maturity fix, Phase 5 — A0 anchors):
    An internally-rated corporate counterparty (CP_SFT_IRB, internal_pd=0.0150,
    model_id=MOD_CORP_IRB) holds an IRB model permission (corporate, GB). A single
    FCCM SFT against it routes to FIRB/AIRB under PermissionMode.IRB and hits the
    IRB maturity chain, which reads the producer-emitted ``ccr_effective_maturity``
    carrier (the full Art. 162 M).

    The headline anchor is A0-5 (the user's repo): a 2-day-residual repo under a
    master netting agreement, non-daily, CRR AIRB -> M = 5/365 ≈ 0.0137.

Key responsibilities:
- Confirm a CCR_SFT synthetic row routes to IRB (approach_applied in {firb, airb}).
- Confirm ``irb_maturity_m`` equals the regulatorily-correct Art. 162 M for each
  anchor, under BOTH regimes — asserting M DIRECTLY (NOT full RWA, since Polars
  group-by float sums are non-process-deterministic per project MEMORY).

References:
    - CRR Art. 162(1): F-IRB fixed supervisory M = 0.5y (repo-style SFTs).
    - CRR Art. 162(2)(d): 5BD floor for repos/sec-lending under an MNA.
    - CRR Art. 162(2)(f): 1-year catch-all (no MNA / not calculable).
    - CRR Art. 162(3): 1-day floor (daily re-margin AND revaluation AND prompt liq).
    - PS1/26 Art. 162(1): F-IRB 0.5y supervisory M DELETED under B31.
    - PS1/26 Art. 162(2A)(d): 5BD floor requires the daily documentation condition.
    - tests/fixtures/ccr/golden_ccr_sft_irb_maturity.py — fixture builder.
"""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_sft_irb_maturity import (
    CCR_SFT_IRB_A0_1_EXPECTED_M,
    CCR_SFT_IRB_A0_1_EXPOSURE_REFERENCE,
    CCR_SFT_IRB_A0_2_EXPECTED_M,
    CCR_SFT_IRB_A0_3_EXPECTED_M,
    CCR_SFT_IRB_A0_4_EXPECTED_M,
    CCR_SFT_IRB_A0_4_EXPOSURE_REFERENCE,
    CCR_SFT_IRB_A0_5_EXPECTED_M,
    CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE,
    CCR_SFT_IRB_A0_5B_EXPECTED_M,
    CCR_SFT_IRB_A0_6_EXPECTED_M,
    CCR_SFT_IRB_A0_6_EXPOSURE_REFERENCE,
    CCR_SFT_IRB_APPROACH_AIRB,
    CCR_SFT_IRB_APPROACH_FIRB,
    CCR_SFT_IRB_REPORTING_DATE,
    build_raw_data_bundle_ccr_sft_irb,
    build_sft_bundle_a0_1,
    build_sft_bundle_a0_4,
    build_sft_bundle_a0_5,
    build_sft_bundle_a0_6,
    create_ccr_sft_irb_model_permission,
)
from tests.fixtures.raw_bundle import seal_raw_table

# ---------------------------------------------------------------------------
# Regime config factories.
# ---------------------------------------------------------------------------

_CONFIG_FACTORIES = {
    "crr": CalculationConfig.crr,
    "b31": CalculationConfig.basel_3_1,
}

_IRB_APPROACHES: set[str] = {"foundation_irb", "advanced_irb"}

# --------------------------------------------------------------------------- #
# AIRB-routing blocker (CCR/SFT IRB effective-maturity fix, Phase 5).
#
# The ``ccr_effective_maturity`` carrier rung in the IRB maturity chain is gated
# to AIRB (``approach != FIRB``) — by regulation a FIRB repo-style SFT gets the
# fixed Art. 162(1) 0.5y (CRR) / date-derived (B31), never the sub-1y carrier
# floors. So the one-day (A0-4), 5BD (A0-5), and floor-inert (A0-6) carrier
# values, and the no-MNA 1y catch-all under AIRB (A0-1), can ONLY be observed on
# an AIRB-routed row.
#
# A CCR_SFT synthetic row CANNOT route to AIRB end-to-end under the (frozen this
# phase) engine: the classifier's model-permission AIRB branch requires
# ``has_modelled_lgd = pl.col("lgd").is_not_null()``
# (engine/stages/classify/permissions.py:340), and the FCCM SFT producer emits
# NO modelled ``lgd`` on the synthetic row (``lgd`` is a lending-input column,
# absent from SFT_TRADE_SCHEMA / RATINGS_SCHEMA / COUNTERPARTY_SCHEMA). Empirically
# the row falls to ``standardised``; with BOTH AIRB and FIRB permissions injected
# it falls to FIRB (M=0.5), never AIRB. There is no fixtures-only channel to give
# a CCR_SFT row a modelled LGD, so these anchors xfail end-to-end.
#
# The carrier rung itself IS verified at the expression level for AIRB rows in
# tests/unit/irb/test_ccr_maturity_rung.py (which sets ``lgd`` + ``approach``
# directly, bypassing the classifier LGD gate). Unblocking these end-to-end
# requires a production change OUT OF SCOPE this phase — either the FCCM producer
# emitting an own-modelled LGD onto AIRB-permissioned CCR/SFT rows, or the
# classifier's CCR-row AIRB gate not requiring a row-level modelled LGD.
_AIRB_CCR_ROUTING_BLOCKED = pytest.mark.xfail(
    reason=(
        "CCR_SFT synthetic rows cannot route to AIRB end-to-end: the classifier "
        "AIRB branch requires a row-level modelled lgd "
        "(engine/stages/classify/permissions.py:340) which the FCCM SFT producer "
        "does not emit. The AIRB-gated ccr_effective_maturity carrier rung is "
        "proven at the expression level in tests/unit/irb/test_ccr_maturity_rung.py. "
        "Unblocking is a production change out of scope for the fixtures-only Phase 5."
    ),
    strict=True,
)


def _run_sft_irb_anchor(
    sft_builder,
    *,
    regime: str,
    approach: str,
    exposure_reference: str,
) -> dict:
    """Run one CCR-SFT-IRB anchor through the full pipeline and return the row.

    Arrange: build the SFT bundle, attach the internally-rated counterparty +
    internal rating, inject the corporate/GB model permission (FIRB or AIRB),
    set PermissionMode.IRB under the requested regime.
    Act:     run the full pipeline.
    Assert (caller): irb_maturity_m on the single ``ccr__<NS>`` row.
    """
    base_bundle = build_raw_data_bundle_ccr_sft_irb(sft_builder())
    model_permissions_lf = seal_raw_table(
        create_ccr_sft_irb_model_permission(approach=approach).lazy(),
        "model_permissions",
    )
    bundle = dataclasses.replace(base_bundle, model_permissions=model_permissions_lf)

    config = _CONFIG_FACTORIES[regime](
        reporting_date=CCR_SFT_IRB_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )

    results = PipelineOrchestrator().run_with_data(bundle, config)
    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"CCR-SFT-IRB: expected exactly 1 result row for "
        f"exposure_reference={exposure_reference!r}, got {len(rows)}."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# A0 anchors — assert irb_maturity_m DIRECTLY (abs=1e-6).
# ---------------------------------------------------------------------------


class TestCCRSFTIRBEffectiveMaturity:
    """Each A0 anchor: a CCR_SFT row routes to IRB and gets the Art. 162 M."""

    @_AIRB_CCR_ROUTING_BLOCKED
    def test_a0_1_no_mna_airb_crr_floors_to_one_year(self) -> None:
        """A0-1: repo NOT under MNA, CRR AIRB -> carrier None -> M = 1.0 (162(2)(f))."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_1,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_1_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-1: expected an IRB approach, got {row['approach_applied']!r} — "
            "the CCR_SFT row must route to IRB for the maturity chain to fire."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_1_EXPECTED_M, abs=1e-6), (
            f"A0-1: expected irb_maturity_m={CCR_SFT_IRB_A0_1_EXPECTED_M} "
            f"(CRR Art. 162(2)(f) date-derived 1y floor; no MNA), got {row['irb_maturity_m']}."
        )

    def test_a0_2_firb_crr_supervisory_half_year(self) -> None:
        """A0-2: same repo, CRR FIRB -> Art. 162(1) fixed supervisory M = 0.5."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_1,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_FIRB,
            exposure_reference=CCR_SFT_IRB_A0_1_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] == "foundation_irb", (
            f"A0-2: expected foundation_irb, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_2_EXPECTED_M, abs=1e-6), (
            f"A0-2: expected irb_maturity_m={CCR_SFT_IRB_A0_2_EXPECTED_M} "
            f"(CRR Art. 162(1) F-IRB repo-style 0.5y), got {row['irb_maturity_m']}."
        )

    def test_a0_3_firb_b31_supervisory_deleted_falls_to_one_year(self) -> None:
        """A0-3: same repo, B31 FIRB -> 162(1) deleted -> date-derived M = 1.0."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_1,
            regime="b31",
            approach=CCR_SFT_IRB_APPROACH_FIRB,
            exposure_reference=CCR_SFT_IRB_A0_1_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] == "foundation_irb", (
            f"A0-3: expected foundation_irb, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_3_EXPECTED_M, abs=1e-6), (
            f"A0-3: expected irb_maturity_m={CCR_SFT_IRB_A0_3_EXPECTED_M} "
            f"(PS1/26 Art. 162(1) deleted -> date-derived 1y floor), got {row['irb_maturity_m']}."
        )

    @_AIRB_CCR_ROUTING_BLOCKED
    def test_a0_4_overnight_mna_qualifies_one_day_floor(self) -> None:
        """A0-4: overnight, MNA, qualifies one-day, CRR AIRB -> M = 1/365 (162(3))."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_4,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_4_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-4: expected an IRB approach, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_4_EXPECTED_M, abs=1e-6), (
            f"A0-4: expected irb_maturity_m={CCR_SFT_IRB_A0_4_EXPECTED_M} "
            f"(CRR Art. 162(3) one-day floor), got {row['irb_maturity_m']}."
        )

    @_AIRB_CCR_ROUTING_BLOCKED
    def test_a0_5_two_day_mna_nondaily_crr_airb_five_bd(self) -> None:
        """A0-5 [USER CASE]: 2-day repo, MNA, non-daily, CRR AIRB -> M = 5/365 (162(2)(d))."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_5,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-5: expected an IRB approach, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_5_EXPECTED_M, abs=1e-6), (
            f"A0-5 (USER CASE): expected irb_maturity_m={CCR_SFT_IRB_A0_5_EXPECTED_M} "
            f"(CRR Art. 162(2)(d) 5BD = clip(2/365, 5/365, 5)), got {row['irb_maturity_m']}."
        )

    @_AIRB_CCR_ROUTING_BLOCKED
    def test_a0_5b_two_day_mna_nondaily_b31_airb_daily_gate(self) -> None:
        """A0-5b: same inputs, B31 AIRB, no daily-gate -> M = 1.0 (162(2A)(d) gate)."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_5,
            regime="b31",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-5b: expected an IRB approach, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_5B_EXPECTED_M, abs=1e-6), (
            f"A0-5b: expected irb_maturity_m={CCR_SFT_IRB_A0_5B_EXPECTED_M} "
            f"(PS1/26 Art. 162(2A)(d) daily gate absent -> 162(2A)(f) 1y catch-all), "
            f"got {row['irb_maturity_m']}."
        )

    @_AIRB_CCR_ROUTING_BLOCKED
    def test_a0_6_long_mna_nondaily_floor_inert(self) -> None:
        """A0-6: ~0.8y repo, MNA, non-daily, CRR AIRB -> M = 0.8 (5BD floor inert)."""
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_6,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_6_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-6: expected an IRB approach, got {row['approach_applied']!r}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_6_EXPECTED_M, abs=1e-6), (
            f"A0-6: expected irb_maturity_m={CCR_SFT_IRB_A0_6_EXPECTED_M} "
            f"(CRR Art. 162(2)(f); 5BD floor inert at ~0.8y residual), got {row['irb_maturity_m']}."
        )
