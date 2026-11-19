"""
Golden B31-CCR-FLOOR-2 scenario: FCCM SFT — output floor S-TREA/U-TREA inclusion.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_floor2_sft_output_floor.py)
    -> engine/stages/calc.py (FCCM SFT floor tag) + engine/aggregator (S-TREA inclusion)

Scenario design (SFT/FCCM separation Phase 7a):
    The CRR sibling of B31-CCR-FLOOR-1, but with an FCCM SFT instead of an
    SA-CCR derivative. The SFT is supplied via ``RawDataBundle.sft`` (the lean
    ``RawSFTBundle``) and priced by the peer ``sft_fccm`` stage; the emitted
    synthetic row carries ``risk_type = "CCR_SFT"`` / ``ccr_method = "fccm_sft"``.

    One SFT trade (T_SFT_001, GBP 60.7m corp bond CQS 1 residual 7y) in netting
    set NS_SFT_001 against CP_INST_001 (institution, CQS 2, GB). No IRB model
    permission -> the U-TREA leg also routes through SA, so for this pure-SA
    portfolio S-TREA == U-TREA.

    Reporting date: 2030-01-01 (Basel 3.1, fully-phased 72.5% output floor).

The behaviour change under test (Phase 7a, operator decision Q1):
    Before Phase 7a, ``engine/stages/calc.py`` tagged only
    ``risk_type == "CCR_DERIVATIVE"`` rows with the floor-eligible
    ``approach_applied = "standardised_ccr"`` label. FCCM SFTs kept the plain
    ``"standardised"`` tag and were therefore EXCLUDED from the output-floor
    S-TREA / U-TREA numerators (``s_trea == 0.0``).

    After Phase 7a, the predicate also matches ``risk_type == "CCR_SFT"``, so the
    FCCM SFT row receives the ``"standardised_ccr"`` tag and ENTERS the floor
    numerator: ``s_trea == u_trea == sft_rwa`` (PS1/26 Art. 92(3A) — SFTs are
    NOT on the S-TREA exclusion list).

Hand-calculated golden values (run reporting_date=2030-01-01, Basel 3.1):
    The FCCM haircut follows the RUN regime's Art. 224 table (review item CC-12;
    before it the lookup was pinned to the CRR table and this golden carried the
    CRR value 64,133,710.53). PS1/26 Art. 224(1) Table 1, 10-day column, debt
    securities issued by entities in points (c) and (d) of Art. 197(1), CQS 1,
    "> 5 <= 10 years": 6 (the CRR table has one "> 5 years" band at 8). So
        HE  = 0.06 x sqrt(5/10)                       (Art. 224(2)(b) repo 5 BD)
        EAD = 60,700,000 x (1 + HE) = 63,275,282.897081405
        RWA = EAD x 20% (B3.1 short-term institution) = 12,655,056.579416282
    The CRR A11 EAD is unchanged (64,133,710.53, HE = 0.08 x sqrt(0.5)).

References:
    - CRR Art. 271(2) — SFT EAD computed via FCCM (not SA-CCR Art. 274).
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
    - PS1/26 Art. 224(1) Table 1 — H_10 = 0.06 for corp bond CQS 1 residual
      > 5 <= 10y (CRR Art. 224 Table 1: 0.08 for > 5y).
    - CRR Art. 226(2) — H_m = H_10 × √(T_m / 10) haircut scaling.
    - PS1/26 Art. 92(2A) — output floor TREA = max(U-TREA, 0.725 × S-TREA + OF-ADJ).
    - PS1/26 Art. 92(3A) — SFTs are NOT on the S-TREA exclusion list.
    - tests/fixtures/ccr/golden_ccr_a11_a12.py — shared SFT scenario constants.
    - tests/fixtures/ccr/sft_bundle_builder.py — RawSFTBundle builder.
"""

from __future__ import annotations

import math
from datetime import date as _date

from rwa_calc.contracts.bundles import RawDataBundle
from tests.fixtures.ccr.golden_ccr_a11_a12 import (
    _build_cp_inst_001_counterparty,
    _build_cp_inst_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
)
from tests.fixtures.ccr.sft_bundle_builder import build_sft_bundle_ccr_a11
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

# Reporting date under test — Basel 3.1 output floor at 72.5% (fully phased).
CCR_FLOOR2_REPORTING_DATE: _date = _date(2030, 1, 1)

# The single FCCM SFT synthetic exposure reference (ccr__<netting_set_id>).
CCR_FLOOR2_EXPOSURE_REFERENCE: str = "ccr__NS_SFT_001"

# Hand-calculated golden values for the Basel 3.1 pipeline run (2030-01-01).
# HE uses the PS1/26 Art. 224(1) Table 1 corp-bond CQS 1 "> 5 <= 10 years" value
# (6%, 10-day) at the 5-BD repo liquidation period; the B3.1 short-term
# institution SA risk weight is 20%. (Pre-CC-12 the CRR table's 8% gave
# EAD 64,133,710.53 / RWA 12,826,742.11 here.)
CCR_FLOOR2_B31_H10: float = 0.06
CCR_FLOOR2_GOLDEN_EAD: float = 60_700_000.0 * (1.0 + CCR_FLOOR2_B31_H10 * math.sqrt(5 / 10))
CCR_FLOOR2_GOLDEN_RISK_WEIGHT: float = 0.20
CCR_FLOOR2_GOLDEN_SFT_RWA: float = CCR_FLOOR2_GOLDEN_EAD * CCR_FLOOR2_GOLDEN_RISK_WEIGHT

# OutputFloorSummary expectations after Phase 7a (the SFT RWA enters S-TREA).
# Pre-Phase-7a these were 0.0 (the bug being closed): FCCM SFTs carried the
# plain "standardised" tag and were excluded from the floor numerator.
CCR_FLOOR2_GOLDEN_S_TREA: float = CCR_FLOOR2_GOLDEN_SFT_RWA
CCR_FLOOR2_GOLDEN_U_TREA: float = CCR_FLOOR2_GOLDEN_SFT_RWA
# Floor does not bind: 0.725 × 12.66m ≈ 9.17m < u_trea 12.66m.
CCR_FLOOR2_GOLDEN_TOTAL_RWA_POST_FLOOR: float = CCR_FLOOR2_GOLDEN_SFT_RWA


def build_raw_data_bundle_ccr_floor2_sft() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for the B31-CCR-FLOOR-2 SFT scenario.

    Reuses the CCR-A11 portfolio stubs (CP_INST_001 institution counterparty +
    external rating) and the CCR-A11 SFT bundle (one uncollateralised GBP 60.7m
    corp-bond SFT via ``raw.sft``). The only difference from CCR-A11 is the run
    config: Basel 3.1 at reporting_date 2030-01-01 (72.5% output floor), which
    exercises the FCCM SFT floor-tag path added in Phase 7a.

    No IRB model permission is supplied, so the U-TREA leg also routes through
    SA — S-TREA == U-TREA for this pure-SA SFT portfolio.

    References:
        - PS1/26 Art. 92(2A)/(3A) (output floor; SFTs not on S-TREA exclusion).
        - CRR Art. 271(2), 223(5) (FCCM SFT EAD).
    """
    return make_raw_bundle(
        counterparties=_build_cp_inst_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_inst_001_rating(),
        sft=build_sft_bundle_ccr_a11(),
    )
