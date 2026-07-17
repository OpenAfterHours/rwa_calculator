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
    CCR_SFT_IRB_INTERNAL_PD,
    CCR_SFT_IRB_MODELLED_LGD,
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
# P1.215: A-IRB routing for synthetic CCR rows.
#
# The classifier's model-permission AIRB branch requires
# ``has_modelled_lgd = pl.col("lgd").is_not_null()``
# (engine/stages/classify/permissions.py:340); the FCCM SFT producer previously
# emitted no modelled LGD on the synthetic ``ccr__<NS>`` row, so AIRB routing
# was unreachable end-to-end (the row fell to ``standardised`` or, with a
# FIRB permission also present, to ``foundation_irb`` — never ``advanced_irb``).
#
# The fixture now carries ``ccr_modelled_lgd`` (P1.215) on the SFT trade row
# (tests/fixtures/ccr/golden_ccr_sft_irb_maturity.py::_sft_irb_trade_df), which
# is the new carrier the engine-implementer wires through to the classifier's
# AIRB gate. Until that wiring lands, the five AIRB anchors below (A0-1, A0-4,
# A0-5, A0-5b, A0-6) FAIL on their own assertions (approach / M mismatches) —
# there is no xfail here; a red run on these five is the expected, tracked
# pre-fix state.
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
        assert row["lgd"] == pytest.approx(CCR_SFT_IRB_MODELLED_LGD, abs=1e-6), (
            f"A0-1: expected lgd={CCR_SFT_IRB_MODELLED_LGD} (P1.215 ccr_modelled_lgd "
            f"carrier; CRR A-IRB applies no per-exposure LGD floor), got {row['lgd']}."
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
        assert row["lgd"] == pytest.approx(CCR_SFT_IRB_MODELLED_LGD, abs=1e-6), (
            f"A0-4: expected lgd={CCR_SFT_IRB_MODELLED_LGD} (P1.215 ccr_modelled_lgd "
            f"carrier; CRR A-IRB applies no per-exposure LGD floor), got {row['lgd']}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_4_EXPECTED_M, abs=1e-6), (
            f"A0-4: expected irb_maturity_m={CCR_SFT_IRB_A0_4_EXPECTED_M} "
            f"(CRR Art. 162(3) one-day floor), got {row['irb_maturity_m']}."
        )

    def test_a0_5_two_day_mna_nondaily_crr_airb_five_bd(self) -> None:
        """A0-5 [USER CASE]: 2-day repo, MNA, non-daily, CRR AIRB -> M = 5/365 (162(2)(d)).

        Flagship anchor — strengthened (P1.215) with the full Basel IRB
        capital-formula parameter chain, not just M, so a routing fix that
        gets ``approach``/``irb_maturity_m`` right but silently drops the
        modelled LGD or mis-floors the PD is still caught here.

        Hand-calc (corporate, non-retail, PD=0.0150, LGD=0.45, M=5/365):
            R  = 0.12*w + 0.24*(1-w), w = (1-e^(-50*PD))/(1-e^(-50))
               = 0.176684
            b  = (0.11852 - 0.05478*ln(PD))^2 = 0.121508
            MA = (1 + (M-2.5)*b) / (1-1.5*b) = 0.853445
            N^-1(PD)     = -2.170090
            N^-1(0.999)  =  3.090232
            inner = (N^-1(PD) + sqrt(R)*N^-1(0.999)) / sqrt(1-R) = -0.960083
            N(inner) = 0.168507

            IMPORTANT — the engine's ``k`` column is the BASE capital
            requirement BEFORE the maturity adjustment; MA is a SEPARATE
            ``maturity_adjustment`` column multiplied in downstream for RWA
            (engine/irb/formulas.py: ``rwa = k * 12.5 * scaling_factor *
            ead_final * maturity_adjustment``). So:
                k = LGD*(N(inner)-PD) = 0.45*(0.168507-0.015) = 0.069078
                maturity_adjustment = MA = 0.853445
            (LGD*(N(inner)-PD)*MA = 0.058954 is the FULL, MA-inclusive K —
            that is what ``k * maturity_adjustment`` equals, not the ``k``
            column alone.)

        Tolerance rel=1e-3 on k/MA — polars-normal-stats' CDF/PPF vs this
        hand-computed erf-based reference may differ at that scale.
        """
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_5,
            regime="crr",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] == "advanced_irb", (
            f"A0-5: expected advanced_irb (only an AIRB model permission is "
            f"granted in this fixture), got {row['approach_applied']!r}."
        )
        assert row["lgd"] == pytest.approx(CCR_SFT_IRB_MODELLED_LGD, abs=1e-6), (
            f"A0-5: expected lgd={CCR_SFT_IRB_MODELLED_LGD} (P1.215 ccr_modelled_lgd "
            f"carrier; CRR A-IRB applies no per-exposure LGD floor), got {row['lgd']}."
        )
        assert row["pd_floored"] == pytest.approx(CCR_SFT_IRB_INTERNAL_PD, abs=1e-6), (
            f"A0-5: expected pd_floored={CCR_SFT_IRB_INTERNAL_PD} (well above the "
            f"CRR Art. 163 0.03% PD floor, so it does not bind), got {row['pd_floored']}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_5_EXPECTED_M, abs=1e-6), (
            f"A0-5 (USER CASE): expected irb_maturity_m={CCR_SFT_IRB_A0_5_EXPECTED_M} "
            f"(CRR Art. 162(2)(d) 5BD = clip(2/365, 5/365, 5)), got {row['irb_maturity_m']}."
        )
        assert row["maturity_adjustment"] == pytest.approx(0.853445, rel=1e-3), (
            f"A0-5: expected maturity_adjustment≈0.853445 (MA at M=5/365, "
            f"b=0.121508 — see docstring derivation), got {row['maturity_adjustment']}."
        )
        assert row["k"] == pytest.approx(0.069078, rel=1e-3), (
            f"A0-5: expected k≈0.069078 (base capital requirement BEFORE the "
            f"maturity adjustment — see docstring derivation), got {row['k']}."
        )

    def test_a0_5b_two_day_mna_nondaily_b31_airb_daily_gate(self) -> None:
        """A0-5b: same inputs, B31 AIRB, no daily-gate -> M = 1.0 (162(2A)(d) gate).

        NOTE: CP_SFT_IRB is a plain corporate (entity_type="corporate", no
        large-corporate / financial-institution markers) — that is exactly
        why B31 A-IRB is reachable here (PS1/26 restricts A-IRB eligibility
        for large corporates/FIs, but not for this counterparty profile).
        Do NOT "fix" this fixture to an institution/large-corporate — that
        would break AIRB eligibility and silently re-route this anchor to
        SA or FIRB, defeating the point of the test.
        """
        row = _run_sft_irb_anchor(
            build_sft_bundle_a0_5,
            regime="b31",
            approach=CCR_SFT_IRB_APPROACH_AIRB,
            exposure_reference=CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE,
        )
        assert row["approach_applied"] in _IRB_APPROACHES, (
            f"A0-5b: expected an IRB approach, got {row['approach_applied']!r}."
        )
        assert row["lgd"] == pytest.approx(CCR_SFT_IRB_MODELLED_LGD, abs=1e-6), (
            f"A0-5b: expected lgd={CCR_SFT_IRB_MODELLED_LGD} (P1.215 ccr_modelled_lgd "
            f"carrier; B31 A-IRB corporate unsecured floor is 25%, well below "
            f"45%, so it does not bind), got {row['lgd']}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_5B_EXPECTED_M, abs=1e-6), (
            f"A0-5b: expected irb_maturity_m={CCR_SFT_IRB_A0_5B_EXPECTED_M} "
            f"(PS1/26 Art. 162(2A)(d) daily gate absent -> 162(2A)(f) 1y catch-all), "
            f"got {row['irb_maturity_m']}."
        )

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
        assert row["lgd"] == pytest.approx(CCR_SFT_IRB_MODELLED_LGD, abs=1e-6), (
            f"A0-6: expected lgd={CCR_SFT_IRB_MODELLED_LGD} (P1.215 ccr_modelled_lgd "
            f"carrier; CRR A-IRB applies no per-exposure LGD floor), got {row['lgd']}."
        )
        assert row["irb_maturity_m"] == pytest.approx(CCR_SFT_IRB_A0_6_EXPECTED_M, abs=1e-6), (
            f"A0-6: expected irb_maturity_m={CCR_SFT_IRB_A0_6_EXPECTED_M} "
            f"(CRR Art. 162(2)(f); 5BD floor inert at ~0.8y residual), got {row['irb_maturity_m']}."
        )
