"""
Golden CCR-A15..A18 scenarios: margined / non-daily SFT EAD via FCCM.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine sft_fccm FCCM stage (engine/stages/sft.py -> engine/sft/fccm.py)

Plan item: SFT/FCCM margined extension — end-to-end acceptance proof that the
FCCM margined / non-daily revaluation branch (CRR Art. 224(2) + Art. 226 +
Art. 285(2)-(5)) reproduces the verified hand-calcs at the FINAL RWA, not just
the haircut unit. The unmargined-daily anchor (A15D) and the three margined /
non-daily / FX variants (A15/A16/A17/A18) all share one minimal counterparty and
one E = C = 10,000,000 trade so the only moving part is the applied haircut.

Shared setup (mirrors CCR-A11/A12 for the counterparty + SA risk weight):
    Counterparty CP_INST_SFT_M01 — institution, external CQS 2, GB.
        SA risk weight = 0.50 (CRR Art. 120(1) Table 3: institution CQS 2 → 50%).
    Exposure side: CASH (exposure_collateral_type=None) ⇒ HE = 0 (no haircut on
        the lent leg). E = notional = 10,000,000.
    Collateral: govt_bond, CQS 1, residual 0.5y ⇒ H_10 = 0.005
        (CRR Art. 224 Table 1, govt_bond CQS 1, 0-1y band). market_value = C =
        10,000,000. Same currency (GBP/GBP) ⇒ HFX = 0 — EXCEPT A17 where the
        collateral is USD against a GBP exposure (FX mismatch).

Applied-haircut formula (the design's single source of truth):

    H = H_10 · √(T_M / 10) · √((N_R + T_M − 1) / T_M)

    - √(T_M/10): Art. 224(2) liquidation-period rescale.
    - √((N_R+T_M−1)/T_M): Art. 226 non-daily revaluation scale-up (collapses to
      1.0 at N_R = 1, e.g. daily revaluation OR the margined branch which sets
      N_R = 1 because the MPOR already encodes the remargin period N).

    E* = max(0, E·(1+HE) − C·(1−H_C−H_FX))   (Art. 223(5))
       = max(0, 10,000,000 − 10,000,000·(1−H_C−H_FX))   [HE = 0]
       = 10,000,000·(H_C + H_FX)

Two mutually-exclusive branches (never combined):

    (a) Unmargined / simply-collateralised (is_margined=False): T_M = 5-BD repo
        liquidation period (Art. 224(2)(b)); the Art. 226 non-daily term applies,
        driven by N_R = remargining_frequency_days.
    (b) Margined (is_margined=True, qualifying Art. 285(2)-(4) agreement):
        T_M = MPOR = F·mult + N − 1 (Art. 285(5)); the Art. 226 non-daily term is
        SUPPRESSED (N_R = 1). F = 5 for 'repo_only' (Art. 285(2)(a)); mult = 2
        when has_margin_dispute_doubling (Art. 285(4)).

Scenarios (E* / RWA reproduced from the verified design hand-calcs):

    CCR-A15D — unmargined daily repo (regression anchor, design row (i))
        is_margined=False, N_R=1, T_M=5.
        H_C = 0.005·√(5/10)·1.0 = 0.0035355339059327378
        E*  = 10,000,000·0.0035355339059327378 = 35,355.3390593268
        RWA = E*·0.50 = 17,677.6695296634

    CCR-A15 — unmargined 3-day remargin (design row (ii))
        is_margined=False, N_R=3, T_M=5.
        H_C = 0.005·√(5/10)·√((3+5−1)/5) = 0.005·√0.5·√1.4
        E*  = 41,833.0013267044
        RWA = E*·0.50 = 20,916.5006633522

    CCR-A16 — margined repo-only N=2 ⇒ MPOR=6 (design row (iii))
        is_margined=True, mpor_floor_category='repo_only', N=2 ⇒ MPOR=5+2−1=6.
        T_M=6, N_R suppressed (=1).
        H_C = 0.005·√(6/10) = 0.0038729833462074166
        E*  = 38,729.8334620744
        RWA = E*·0.50 = 19,364.9167310372

    CCR-A17 — unmargined daily repo + FX mismatch (design row (iv))
        is_margined=False, N_R=1, T_M=5, collateral USD vs exposure GBP.
        H_C  = 0.005·√(5/10) = 0.0035355339059327378
        H_FX = 0.08·√(5/10)  = 0.056568542494923804
        E*   = 10,000,000·(H_C + H_FX) = 601,040.7640085649
        RWA  = E*·0.50 = 300,520.38200428244

    CCR-A18 — margined repo-only N=2 + dispute-doubling ⇒ MPOR=11
        is_margined=True, mpor_floor_category='repo_only', N=2,
        has_margin_dispute_doubling=True ⇒ MPOR = 5·2 + 2 − 1 = 11.
        T_M=11, N_R suppressed (=1).
        H_C = 0.005·√(11/10) = 0.005244044240850769
        E*  = 10,000,000·H_C = 52,440.44240850769
        RWA = E*·0.50 = 26,220.221204253845

Cross-scenario ordering (design ordering (i) < (iii) < (ii)):
    A15D (35,355) < A16 (38,730) < A15 (41,833).
A17 (FX mismatch, 601,041) and A18 (MPOR=11, 52,440) sit above all three.

All constants below are computed with ``math.sqrt`` so they are the IEEE-754
ground truth; the test-writer references the module constants (never re-derives
literals) and asserts at 1 ppm relative tolerance, matching the other CCR golden
tests.

References:
    - CRR Art. 220(1)(a) — single-counterparty SFT / master-netting set scope.
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − C·(1−H_C−H_FX)).
    - CRR Art. 224(2)(b) — 5-BD repo liquidation period.
    - CRR Art. 224 Table 1 — H_10 = 0.005 (govt_bond CQS 1, 0-1y band).
    - CRR Art. 224 Table 4 — H_FX base 8% (FX mismatch).
    - CRR Art. 226 — H = H_10·√(T_M/10)·√((N_R+T_M−1)/T_M) non-daily scale-up.
    - CRR Art. 271(2) — SFT EAD via FCCM (not SA-CCR Art. 274).
    - CRR Art. 285(2)-(5) — margined MPOR floors / dispute doubling / F+N−1.
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA risk weight.
    - .claude/state/margined-sft-design.md — verified hand-calcs (source of truth).
    - tests/fixtures/ccr/sft_bundle_builder.py — RawSFTBundle builders.
"""

from __future__ import annotations

import math
from datetime import date as _date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Counterparty — institution, external CQS 2, GB (mirrors CCR-A11/A12 CP but a
# distinct reference so this module is self-contained).
# ---------------------------------------------------------------------------

CCR_A15_A18_COUNTERPARTY_REF: str = "CP_INST_SFT_M01"
CCR_A15_A18_CP_ENTITY_TYPE: str = "institution"
CCR_A15_A18_CP_COUNTRY_CODE: str = "GB"
CCR_A15_A18_CP_INSTITUTION_CQS: int = 2

CCR_A15_A18_RATING_REF: str = "RTG_INST_SFT_M01"
CCR_A15_A18_RATING_TYPE: str = "external"
CCR_A15_A18_RATING_AGENCY: str = "S&P"
CCR_A15_A18_RATING_VALUE: str = "A"
CCR_A15_A18_RATING_DATE: _date = _date(2026, 1, 15)

# ---------------------------------------------------------------------------
# Shared trade economics — E = C = 10,000,000; cash exposure side (HE = 0);
# govt_bond CQS 1 0.5y collateral (H_10 = 0.005).
# ---------------------------------------------------------------------------

CCR_A15_A18_NOTIONAL: float = 10_000_000.00
CCR_A15_A18_CURRENCY: str = "GBP"
CCR_A15_A18_START_DATE: _date = _date(2026, 6, 30)
CCR_A15_A18_MATURITY_DATE: _date = _date(2026, 9, 30)

# Exposure side is CASH ⇒ exposure_collateral_type=None ⇒ HE = 0 (no haircut on
# the lent leg). The three exposure-side HE columns are left null on the trade.
CCR_A15_A18_EXPOSURE_COLLATERAL_TYPE: None = None

# Collateral: govt_bond CQS 1, residual 0.5y ⇒ H_10 = 0.005 (Art. 224 Table 1).
CCR_A15_A18_COLLATERAL_TYPE: str = "govt_bond"
CCR_A15_A18_COLLATERAL_MARKET_VALUE: float = 10_000_000.00
CCR_A15_A18_COLLATERAL_ISSUER_CQS: int = 1
CCR_A15_A18_COLLATERAL_RESIDUAL_MATURITY_YEARS: float = 0.5
CCR_A15_A18_COLLATERAL_CURRENCY_GBP: str = "GBP"
CCR_A15_A18_COLLATERAL_CURRENCY_USD: str = "USD"

# ---------------------------------------------------------------------------
# Per-scenario trade / netting-set / collateral identifiers.
# ---------------------------------------------------------------------------

CCR_A15D_TRADE_ID: str = "T_SFT_A15D"
CCR_A15D_NETTING_SET_ID: str = "NS_SFT_A15D"
CCR_A15D_COLLATERAL_REF: str = "COLL_SFT_A15D"

CCR_A15_TRADE_ID: str = "T_SFT_A15"
CCR_A15_NETTING_SET_ID: str = "NS_SFT_A15"
CCR_A15_COLLATERAL_REF: str = "COLL_SFT_A15"

CCR_A16_TRADE_ID: str = "T_SFT_A16"
CCR_A16_NETTING_SET_ID: str = "NS_SFT_A16"
CCR_A16_COLLATERAL_REF: str = "COLL_SFT_A16"

CCR_A17_TRADE_ID: str = "T_SFT_A17"
CCR_A17_NETTING_SET_ID: str = "NS_SFT_A17"
CCR_A17_COLLATERAL_REF: str = "COLL_SFT_A17"

CCR_A18_TRADE_ID: str = "T_SFT_A18"
CCR_A18_NETTING_SET_ID: str = "NS_SFT_A18"
CCR_A18_COLLATERAL_REF: str = "COLL_SFT_A18"

# Emitted synthetic exposure references (pipeline_adapter format "ccr__<NS>").
CCR_A15D_EXPOSURE_REFERENCE: str = f"ccr__{CCR_A15D_NETTING_SET_ID}"
CCR_A15_EXPOSURE_REFERENCE: str = f"ccr__{CCR_A15_NETTING_SET_ID}"
CCR_A16_EXPOSURE_REFERENCE: str = f"ccr__{CCR_A16_NETTING_SET_ID}"
CCR_A17_EXPOSURE_REFERENCE: str = f"ccr__{CCR_A17_NETTING_SET_ID}"
CCR_A18_EXPOSURE_REFERENCE: str = f"ccr__{CCR_A18_NETTING_SET_ID}"

# FCCM provenance + SA outputs common to every scenario.
CCR_A15_A18_CCR_METHOD: str = "fccm_sft"
CCR_A15_A18_RISK_TYPE: str = "CCR_SFT"
CCR_A15_A18_RISK_WEIGHT: float = 0.50

# ---------------------------------------------------------------------------
# Hand-calculated expected outputs — single source of truth (IEEE-754 ground
# truth via math.sqrt, mirroring the engine's float arithmetic).
# ---------------------------------------------------------------------------

CCR_A15_A18_H10_COLLATERAL: float = 0.005  # govt_bond CQS 1, 0-1y (Art. 224 Table 1)
CCR_A15_A18_FX_HAIRCUT_BASE: float = 0.08  # Art. 224 Table 4 (10-BD base)
CCR_A15_A18_E: float = CCR_A15_A18_NOTIONAL  # HE = 0 ⇒ E·(1+HE) = E


def _liq(base: float, t_m: int) -> float:
    """Art. 224(2) liquidation-period rescale: H_10 · √(T_M/10) (1.0 at T_M=10)."""
    if t_m == 10 or math.isclose(base, 0.0, abs_tol=1e-10):
        return base
    return base * math.sqrt(t_m / 10.0)


def _non_daily(daily: float, n_r: int, t_m: int) -> float:
    """Art. 226 non-daily scale-up: ·√((N_R+T_M−1)/T_M) (identity at N_R=1)."""
    if n_r == 1 or t_m <= 0 or math.isclose(daily, 0.0, abs_tol=1e-10):
        return daily
    return daily * math.sqrt((n_r + t_m - 1) / t_m)


def _estar(t_m: int, n_r: int, *, fx_mismatch: bool = False) -> float:
    """E* = 10,000,000·(H_C + H_FX) with HE = 0 (cash exposure side)."""
    hc = _non_daily(_liq(CCR_A15_A18_H10_COLLATERAL, t_m), n_r, t_m)
    hfx = _non_daily(_liq(CCR_A15_A18_FX_HAIRCUT_BASE, t_m), n_r, t_m) if fx_mismatch else 0.0
    cva = CCR_A15_A18_COLLATERAL_MARKET_VALUE * (1.0 - hc - hfx)
    return max(0.0, CCR_A15_A18_E - cva)


# CCR-A15D — unmargined daily (T_M=5, N_R=1) — regression anchor / design (i).
CCR_A15D_EAD: float = _estar(5, 1)
# = 35_355.3390593268
CCR_A15D_RWA: float = CCR_A15D_EAD * CCR_A15_A18_RISK_WEIGHT
# = 17_677.6695296634

# CCR-A15 — unmargined 3-day remargin (T_M=5, N_R=3) — design (ii).
CCR_A15_EAD: float = _estar(5, 3)
# = 41_833.0013267044
CCR_A15_RWA: float = CCR_A15_EAD * CCR_A15_A18_RISK_WEIGHT
# = 20_916.5006633522

# CCR-A16 — margined repo-only N=2 ⇒ MPOR=6 (T_M=6, N_R=1) — design (iii).
CCR_A16_EAD: float = _estar(6, 1)
# = 38_729.8334620744
CCR_A16_RWA: float = CCR_A16_EAD * CCR_A15_A18_RISK_WEIGHT
# = 19_364.9167310372

# CCR-A17 — unmargined daily + FX mismatch (T_M=5, N_R=1, USD coll) — design (iv).
CCR_A17_EAD: float = _estar(5, 1, fx_mismatch=True)
# = 601_040.7640085649
CCR_A17_RWA: float = CCR_A17_EAD * CCR_A15_A18_RISK_WEIGHT
# = 300_520.38200428244

# CCR-A18 — margined repo-only N=2 + dispute-doubling ⇒ MPOR=11 (T_M=11, N_R=1).
CCR_A18_EAD: float = _estar(11, 1)
# = 52_440.44240850769
CCR_A18_RWA: float = CCR_A18_EAD * CCR_A15_A18_RISK_WEIGHT
# = 26_220.221204253845

# Monetary tolerance for acceptance assertions (1 ppm, consistent with goldens).
CCR_A15_A18_MONETARY_REL_TOLERANCE: float = 1e-6


# ---------------------------------------------------------------------------
# Portfolio-stub builders (counterparty + rating).
# ---------------------------------------------------------------------------


def _build_counterparty() -> pl.LazyFrame:
    """One-row counterparty LazyFrame for CP_INST_SFT_M01 (institution, CQS 2, GB).

    entity_type="institution" → Classifier → ExposureClass.INSTITUTION.
    CRR Art. 120(1) Table 3: CQS 2 → 50% SA risk weight. ``institution_cqs=2``
    lets narrow unit paths resolve the risk weight without the rating pipeline.
    """
    row = {
        "counterparty_reference": CCR_A15_A18_COUNTERPARTY_REF,
        "counterparty_name": "Margined-SFT Test Institution (CQS 2)",
        "entity_type": CCR_A15_A18_CP_ENTITY_TYPE,
        "country_code": CCR_A15_A18_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_A15_A18_CP_INSTITUTION_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_rating() -> pl.LazyFrame:
    """One-row external ratings LazyFrame for CP_INST_SFT_M01 (S&P "A" = CQS 2).

    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    pd=None — external ratings carry no PD.
    """
    row = {
        "rating_reference": CCR_A15_A18_RATING_REF,
        "counterparty_reference": CCR_A15_A18_COUNTERPARTY_REF,
        "rating_type": CCR_A15_A18_RATING_TYPE,
        "rating_agency": CCR_A15_A18_RATING_AGENCY,
        "rating_value": CCR_A15_A18_RATING_VALUE,
        "cqs": CCR_A15_A18_CP_INSTITUTION_CQS,
        "pd": None,
        "rating_date": CCR_A15_A18_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# RawDataBundle assembly helpers (one per scenario; SFT supplied via raw.sft).
#
# The RawSFTBundle builders (build_sft_bundle_ccr_a15d..a18) live in
# tests/fixtures/ccr/sft_bundle_builder.py and import this module's scenario
# constants; the bundle assemblers below import them lazily to avoid the cycle.
# ---------------------------------------------------------------------------


def _assemble(sft_bundle) -> RawDataBundle:  # type: ignore[no-untyped-def]
    """Wrap an already-built RawSFTBundle with the shared counterparty stub."""
    return make_raw_bundle(
        counterparties=_build_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_rating(),
        sft=sft_bundle,
    )


def build_raw_data_bundle_ccr_a15d() -> RawDataBundle:
    """CCR-A15D: unmargined daily repo SFT (regression anchor, design (i)).

    Cash exposure (HE=0), govt_bond CQS 1 0.5y collateral (H_10=0.005), GBP/GBP.
    is_margined=False, remargining_frequency_days=1 ⇒ T_M=5, N_R=1.
    E* = 35,355.3390593268; RWA = 17,677.6695296634.
    """
    from .sft_bundle_builder import build_sft_bundle_ccr_a15d

    return _assemble(build_sft_bundle_ccr_a15d())


def build_raw_data_bundle_ccr_a15() -> RawDataBundle:
    """CCR-A15: unmargined 3-day remargin SFT (design (ii)).

    is_margined=False, remargining_frequency_days=3 ⇒ T_M=5, N_R=3.
    E* = 41,833.0013267044; RWA = 20,916.5006633522.
    """
    from .sft_bundle_builder import build_sft_bundle_ccr_a15

    return _assemble(build_sft_bundle_ccr_a15())


def build_raw_data_bundle_ccr_a16() -> RawDataBundle:
    """CCR-A16: margined repo-only N=2 ⇒ MPOR=6 SFT (design (iii)).

    is_margined=True, mpor_floor_category='repo_only',
    remargining_frequency_days=2 ⇒ MPOR=6, N_R suppressed.
    E* = 38,729.8334620744; RWA = 19,364.9167310372.
    """
    from .sft_bundle_builder import build_sft_bundle_ccr_a16

    return _assemble(build_sft_bundle_ccr_a16())


def build_raw_data_bundle_ccr_a17() -> RawDataBundle:
    """CCR-A17: unmargined daily + FX mismatch SFT (design (iv)).

    is_margined=False, remargining_frequency_days=1, collateral USD vs GBP
    exposure ⇒ H_FX = 0.08·√0.5 applied on top of H_C.
    E* = 601,040.7640085649; RWA = 300,520.38200428244.
    """
    from .sft_bundle_builder import build_sft_bundle_ccr_a17

    return _assemble(build_sft_bundle_ccr_a17())


def build_raw_data_bundle_ccr_a18() -> RawDataBundle:
    """CCR-A18: margined repo-only N=2 + dispute-doubling ⇒ MPOR=11 SFT.

    is_margined=True, mpor_floor_category='repo_only',
    remargining_frequency_days=2, has_margin_dispute_doubling=True ⇒
    MPOR = 5·2 + 2 − 1 = 11, N_R suppressed.
    E* = 52,440.44240850769; RWA = 26,220.221204253845.
    """
    from .sft_bundle_builder import build_sft_bundle_ccr_a18

    return _assemble(build_sft_bundle_ccr_a18())


# ---------------------------------------------------------------------------
# Save helper — parquet generation for generate_all.py / standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a15_a18_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write the CCR-A15..A18 golden SFT parquet files to *output_dir*.

    One trade file + one collateral file per scenario (every scenario is
    collateralised). Returns a map of artefact name → saved absolute Path.
    """
    from .sft_bundle_builder import (
        build_sft_bundle_ccr_a15,
        build_sft_bundle_ccr_a15d,
        build_sft_bundle_ccr_a16,
        build_sft_bundle_ccr_a17,
        build_sft_bundle_ccr_a18,
    )

    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    bundles = {
        "a15d": build_sft_bundle_ccr_a15d(),
        "a15": build_sft_bundle_ccr_a15(),
        "a16": build_sft_bundle_ccr_a16(),
        "a17": build_sft_bundle_ccr_a17(),
        "a18": build_sft_bundle_ccr_a18(),
    }

    saved: dict[str, Path] = {}
    for tag, bundle in bundles.items():
        assert bundle.collateral is not None  # every scenario is collateralised
        artefacts: list[tuple[str, pl.DataFrame]] = [
            (f"sft_{tag}_trades", bundle.trades.sft_trades.collect()),
            (f"sft_{tag}_collateral", bundle.collateral.sft_collateral.collect()),
        ]
        for name, df in artefacts:
            path = output_dir / f"{name}.parquet"
            df.write_parquet(path)
            saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation + a printed hand-calc summary."""
    saved = save_ccr_a15_a18_fixtures()
    print("CCR-A15..A18 margined-SFT golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<28} {df.height:>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    rows = [
        ("A15D unmarg N1  ", CCR_A15D_EAD, CCR_A15D_RWA),
        ("A15  unmarg N3  ", CCR_A15_EAD, CCR_A15_RWA),
        ("A16  marg MPOR6 ", CCR_A16_EAD, CCR_A16_RWA),
        ("A17  unmarg USD ", CCR_A17_EAD, CCR_A17_RWA),
        ("A18  marg MPOR11", CCR_A18_EAD, CCR_A18_RWA),
    ]
    for label, ead, rwa in rows:
        print(f"  {label}  E* = {ead:>18.10f}   RWA = {rwa:>18.10f}")


if __name__ == "__main__":
    main()
