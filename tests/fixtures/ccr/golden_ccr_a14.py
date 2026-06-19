"""
Golden CCR-A14 scenario: single 10-year GBP vanilla IR swap, margined netting set,
126-day remargin frequency (the "EAD rises" branch).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_a14_long_remargin_mf.py)
    -> engine-implementer (SA-CCR margined maturity factor wiring — P8.54)

Scenario design (plan item P8.54, scenario CCR-A14):
    One trade (T_MGN_002): 10-year GBP vanilla IR swap, notional GBP 100m,
    MtM = -4_000_000.0 (out-of-the-money), delta = 1.0 (non-option directional long).
    One netting set (NS_MGN_002): counterparty CP_002 (institution CQS-2 GB stub;
    reuses the CCR-A13 CP_001 rating parameters verbatim), legally enforceable (Art. 295),
    margined with TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10 days.
    One margin agreement (MA_MGN_002): matching netting-set margin parameters, with
    remargining_frequency_days=126 (the single changed driver vs CCR-A13).
    Zero CCR collateral: c_net = 0.0.

Regulatory hand-calc (MPOR cascade — CRR Art. 285(2)-(5)):
    Step 1 base MPOR = 10 BD (mf_margined_floor_days_otc = 10, Art. 285(2)(b)).
    Step 2 number_of_trades = 1 < 5000, has_illiquid = False → no 20-BD upgrade.
    Step 3 dispute_count_qtr = 0 ≤ 2 → no doubling.
    Step 4 MPOR_eff_pre_floor = 10 + 126 − 1 = 135.
    Step 5 MPOR_eff = max(135, 10) = 135.
    MF_margined = 1.5 × √(135/250) = 1.5 × √0.54
                = 1.5 × 0.734846922834 = 1.102270384252

    Direction check: MF_margined = 1.10227 > 1.0 (unmargined cap), so this is the
    "EAD rises" branch — the margined path produces a HIGHER EAD than the
    unmargined path for long-remargin CSAs.

PFE add-on chain (CRR Art. 277a/280a, identical trade to CCR-A13):
    SF_IR = 0.5% (Art. 280a supervisory factor).
    addon_aggregate = SF_IR × |δ × EN × MF| (linear in MF for a single trade).
    Baseline addon_aggregate (MF=1.0) = 3_914_298.2277279915 (CCR-A13 unmargined baseline).
    CCR-A14 addon_aggregate = 3_914_298.2277279915 × 1.102270384252.

Margined RC (CRR Art. 275(2)):
    V = v_net = -4_000_000   (trade MtM, single trade)
    C = c_net = 0            (no CCR collateral)
    TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000
    rc_margined = max(-4_000_000, 2_250_000, 0) = 2_250_000  [floor arm binds]

EAD and RWA (hand-calc approximation; engine-precise bytes confirmed by engine-implementer):
    pfe_multiplier ≈ 0.633217   (V < 0 so multiplier < 1; exp() in Polars determines ulp)
    pfe_addon      ≈ 2_732_138  (engine-precise)
    EAD = 1.4 × (rc_margined + pfe_addon) ≈ 1.4 × (2_250_000 + 2_732_138) ≈ 6_974_993
    RWA = EAD × 0.50 ≈ 3_487_497

Load-bearing inequality (P8.54 "EAD rises" branch):
    ead_final > 6_464_360.391383706   (CCR-A13 unmargined-MF=1.0 EAD)
    This proves margined MF > 1.0 raised EAD above the unmargined-MF=1.0 baseline.

Counterparty / rating: reuse CCR-A13 CP_001 institution stub verbatim.
    CP_001 (referenced here as CP_002 netting-set assignment): institution, CQS 2, GB.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.

References:
    - CRR Art. 272(4) (netting set definition)
    - CRR Art. 272(7) (margin agreement / CSA definition)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(2) (margined RC = max(V - C, TH + MTA - NICA, 0))
    - CRR Art. 279c(2) (margined MF = 1.5 × sqrt(MPOR_eff / 250))
    - CRR Art. 280a (SF_IR = 0.5%)
    - CRR Art. 285(2)(b) (10-day minimum MPOR floor)
    - CRR Art. 285(5) (remargin adjustment: MPOR_eff = base + freq - 1)
    - CRR Art. 295-297 (contractual netting recognition)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      MARGIN_AGREEMENT_SCHEMA, CCR_COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA,
      RATINGS_SCHEMA
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import Margin, create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CCR_A14_TRADE_ID: str = "T_MGN_002"
CCR_A14_NETTING_SET_ID: str = "NS_MGN_002"
CCR_A14_COUNTERPARTY_REF: str = "CP_001"
CCR_A14_MARGIN_AGREEMENT_ID: str = "MA_MGN_002"

CCR_A14_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A14_CURRENCY: str = "GBP"
CCR_A14_ASSET_CLASS: str = "interest_rate"
CCR_A14_TRANSACTION_TYPE: str = "derivative"
CCR_A14_MTM: float = -4_000_000.0  # out-of-the-money; drives floor arm in RC
CCR_A14_DELTA: float = 1.0
CCR_A14_IS_LONG: bool = True

# 10-year tenor: same as CCR-A13 (PFE inputs structurally identical before MF).
CCR_A14_START_DATE: _date = _date(2026, 1, 15)
CCR_A14_MATURITY_DATE: _date = _date(2036, 1, 15)

CCR_A14_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A14_IS_MARGINED: bool = True

# Margin / CSA parameters (CRR Art. 272(7) / Art. 285(2)(b) / Art. 285(5)).
# TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000 [floor arm]
CCR_A14_MARGIN_THRESHOLD: float = 2_000_000.0
CCR_A14_MINIMUM_TRANSFER_AMOUNT: float = 500_000.0
CCR_A14_NICA: float = 250_000.0
CCR_A14_MPOR_DAYS: int = 10  # regulatory minimum per Art. 285(2)(b)
CCR_A14_IS_SEGREGATED_IM: bool = False
# The only changed driver vs CCR-A13: 126-day remargin frequency triggers long-MPOR.
# Art. 285(5): MPOR_eff_pre_floor = base + remargining_frequency_days - 1 = 10 + 126 - 1 = 135
# MF_margined = 1.5 * sqrt(135 / 250) = 1.102270384252  (> 1.0 → "EAD rises" branch)
CCR_A14_REMARGINING_FREQUENCY_DAYS: int = 126
CCR_A14_DISPUTE_COUNT_QTR: int = 0
CCR_A14_NUMBER_OF_TRADES: int = 1
CCR_A14_HAS_ILLIQUID_COLLATERAL: bool = False

# ---------------------------------------------------------------------------
# MPOR cascade constants (CRR Art. 285) — load-bearing for test assertions.
# ---------------------------------------------------------------------------

# MPOR cascade (Art. 285(2)(b) base=10, Art. 285(5) remargin adj):
# MPOR_eff = max(base + freq - 1, base) = max(10 + 126 - 1, 10) = 135
CCR_A14_MPOR_EFF: int = 135

# MF = 1.5 * sqrt(MPOR_eff / 250) = 1.5 * sqrt(135 / 250) = 1.5 * 0.734846922834
# = 1.102270384252  (> 1.0: "EAD rises" vs unmargined-MF=1.0 baseline)
CCR_A14_MF_MARGINED: float = 1.102270384252

# ---------------------------------------------------------------------------
# P8.20 portfolio-stub constants — reused verbatim from CCR-A1 / CCR-A13.
# ---------------------------------------------------------------------------

# CP_001: institution, CQS 2, GB.
# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A14_CP_ENTITY_TYPE: str = "institution"
CCR_A14_CP_COUNTRY_CODE: str = "GB"

# External rating: S&P "A" = CQS 2.
CCR_A14_RATING_REF: str = "RTG_CCR_A1_CP_001"
CCR_A14_RATING_TYPE: str = "external"
CCR_A14_RATING_AGENCY: str = "S&P"
CCR_A14_RATING_VALUE: str = "A"
CCR_A14_RATING_CQS: int = 2
CCR_A14_RATING_DATE: _date = _date(2026, 1, 15)

# ---------------------------------------------------------------------------
# Golden expected values — hand-calc (engine-precise bytes confirmed downstream).
# ---------------------------------------------------------------------------

# Baseline addon_aggregate (MF=1.0): 3_914_298.2277279915 (same trade as CCR-A13).
# CCR-A14 addon_aggregate scales linearly with MF (single trade, single bucket):
#   addon_aggregate = 3_914_298.2277279915 × 1.102270384252
CCR_A14_ADDON_AGGREGATE: float = 3_914_298.2277279915 * CCR_A14_MF_MARGINED
# ≈ 4_314_649.xxx (engine-precise bytes confirmed by engine-implementer)

# Margined RC (CRR Art. 275(2)): max(V-C, TH+MTA-NICA, 0) = max(-4m, 2_250_000, 0) = 2_250_000.
# MF-independent (same as CCR-A13).
CCR_A14_RC_MARGINED: float = 2_250_000.0

# Unmargined RC: NS_MGN_002 is margined, so unmargined path is skipped (= 0).
CCR_A14_RC_UNMARGINED: float = 0.0

# PFE multiplier (hand-calc approximation; exact value Polars-float-determined):
# F = 0.05, denom = 2 * 0.95 * addon_aggregate; exponent = V / denom
# uncapped = F + (1-F) * exp(exponent); pfe_multiplier = min(1.0, uncapped)
# V = -4_000_000, addon_aggregate ≈ 4_314_649
# denom ≈ 2 * 0.95 * 4_314_649 ≈ 8_197_833
# exponent ≈ -4_000_000 / 8_197_833 ≈ -0.487935
# uncapped ≈ 0.05 + 0.95 * exp(-0.487935) ≈ 0.05 + 0.95 * 0.613913 ≈ 0.633217
CCR_A14_PFE_MULTIPLIER: float = 0.633217  # hand-calc; engine bytes confirmed downstream

# pfe_addon = pfe_multiplier * addon_aggregate (hand-calc approximation):
# ≈ 0.633217 * 4_314_649 ≈ 2_732_138
CCR_A14_PFE_ADDON: float = 2_732_138.0  # hand-calc approximation

# alpha = 1.4 (CRR Art. 274(2)).
# EAD ≈ 1.4 * (rc_margined + pfe_addon) ≈ 1.4 * (2_250_000 + 2_732_138) ≈ 6_974_993
CCR_A14_ALPHA: float = 1.4
CCR_A14_EAD: float = 6_974_993.0  # hand-calc approximation (engine-precise confirmed downstream)

# Risk weight: institution CQS 2, CRR Art. 120(1) Table 3.
CCR_A14_RISK_WEIGHT: float = 0.50
CCR_A14_RWA: float = 3_487_497.0  # hand-calc approximation (engine-precise confirmed downstream)

# Load-bearing inequality: EAD must exceed CCR-A13 unmargined-MF=1.0 EAD.
# Proves the "EAD rises" branch of the margined MF wiring.
CCR_A14_EAD_LOWER_BOUND: float = 6_464_360.391383706  # CCR-A13 (MF=1.0) EAD

# Exposure reference identifier for the CCR pipeline adapter.
CCR_A14_EXPOSURE_REFERENCE: str = "ccr__NS_MGN_002"


# ---------------------------------------------------------------------------
# Private scenario builders (CCR domain)
# ---------------------------------------------------------------------------


def _ccr_a14_trade() -> Trade:
    """Return the single CCR-A14 trade instance (margined, MtM=-4m, 126-day remargin)."""
    return make_trade(
        trade_id=CCR_A14_TRADE_ID,
        netting_set_id=CCR_A14_NETTING_SET_ID,
        asset_class=CCR_A14_ASSET_CLASS,
        transaction_type=CCR_A14_TRANSACTION_TYPE,
        notional=CCR_A14_NOTIONAL,
        currency=CCR_A14_CURRENCY,
        maturity_date=CCR_A14_MATURITY_DATE,
        start_date=CCR_A14_START_DATE,
        delta=CCR_A14_DELTA,
        is_long=CCR_A14_IS_LONG,
        mtm_value=CCR_A14_MTM,
    )


def _ccr_a14_netting_set() -> NettingSet:
    """Return the single CCR-A14 netting set instance (margined, TH=2m, MTA=0.5m, NICA=0.25m)."""
    return NettingSet(
        netting_set_id=CCR_A14_NETTING_SET_ID,
        counterparty_reference=CCR_A14_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A14_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A14_IS_MARGINED,
        margin_threshold=CCR_A14_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_A14_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_A14_NICA,
        mpor_days=CCR_A14_MPOR_DAYS,
        margin_agreement_id=CCR_A14_MARGIN_AGREEMENT_ID,
        number_of_trades=CCR_A14_NUMBER_OF_TRADES,
        has_illiquid_collateral_or_hard_to_replace_otc=CCR_A14_HAS_ILLIQUID_COLLATERAL,
    )


def _ccr_a14_margin() -> Margin:
    """Return the CCR-A14 margin agreement (MA_MGN_002, remargining_frequency_days=126)."""
    return Margin(
        margin_agreement_id=CCR_A14_MARGIN_AGREEMENT_ID,
        counterparty_reference=CCR_A14_COUNTERPARTY_REF,
        margin_threshold=CCR_A14_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_A14_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_A14_NICA,
        mpor_days=CCR_A14_MPOR_DAYS,
        is_segregated_im=CCR_A14_IS_SEGREGATED_IM,
        remargining_frequency_days=CCR_A14_REMARGINING_FREQUENCY_DAYS,
        dispute_count_qtr=CCR_A14_DISPUTE_COUNT_QTR,
    )


# ---------------------------------------------------------------------------
# DataFrame factories (CCR domain)
# ---------------------------------------------------------------------------


def create_ccr_a14_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A14."""
    return create_trades([_ccr_a14_trade()])


def create_ccr_a14_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A14."""
    return create_netting_sets([_ccr_a14_netting_set()])


def create_ccr_a14_margin_agreements() -> pl.DataFrame:
    """Return the single-row margin-agreements DataFrame for CCR-A14 (MA_MGN_002)."""
    return create_margin_agreements([_ccr_a14_margin()])


def create_ccr_a14_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A14: no CCR collateral, c_net=0)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Private portfolio-stub builders (P8.20 pattern, reused from CCR-A13)
# ---------------------------------------------------------------------------


def _build_cp_001_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_001.

    Reused verbatim from golden_ccr_a13._build_cp_001_counterparty().
    CP_001 is a GB institution with CQS 2 under CRR.  entity_type="institution"
    drives the Classifier to ExposureClass.INSTITUTION → SA risk weight lookup via
    CRR Art. 120(1) Table 3 (CQS 2 → 50%).
    """
    row = {
        "counterparty_reference": CCR_A14_COUNTERPARTY_REF,
        "counterparty_name": "CCR-A1 Test Institution (CQS 2)",
        "entity_type": CCR_A14_CP_ENTITY_TYPE,
        "country_code": CCR_A14_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_A14_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cp_001_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_001.

    Reused verbatim from golden_ccr_a13._build_cp_001_rating().
    S&P "A" = CQS 2 under CRR ECRA mapping for institutions.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    """
    row = {
        "rating_reference": CCR_A14_RATING_REF,
        "counterparty_reference": CCR_A14_COUNTERPARTY_REF,
        "rating_type": CCR_A14_RATING_TYPE,
        "rating_agency": CCR_A14_RATING_AGENCY,
        "rating_value": CCR_A14_RATING_VALUE,
        "cqs": CCR_A14_RATING_CQS,
        "pd": None,
        "rating_date": CCR_A14_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame (no traditional lending in CCR-A14 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame (no drawn loans in CCR-A14 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame (no facility hierarchy in CCR-A14 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame (no retail lending groups in CCR-A14 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_ccr_a14_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the four CCR-A14 domain frames.

    Composition:
        trades              — 1 row  (T_MGN_002, 10y GBP IR swap, NS_MGN_002, MtM=-4m)
        netting_sets        — 1 row  (NS_MGN_002, CP_001, enforceable, margined)
        margin_agreements   — 1 row  (MA_MGN_002, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d,
                                      remargining_frequency_days=126)
        ccr_collateral      — 0 rows (no CCR collateral, c_net=0.0)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a14_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a14_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a14_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a14_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helper
# ---------------------------------------------------------------------------


def build_raw_data_bundle_with_ccr_a14() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A14 data populated.

    Key responsibilities:
    - Provides CP_001 as an institution counterparty (entity_type="institution",
      CQS 2, GB) so the Classifier routes the CCR-derived synthetic exposure
      through SA-Institution (CRR Art. 120(1) Table 3 → 50% RW).
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves ``external_cqs`` correctly.
    - Zero-row facility / loan / contingent / mapping frames so the only
      exposure in the pipeline is the CCR-derived synthetic row.
    - ``ccr`` is populated with a RawCCRBundle containing:
        - trade T_MGN_002 (10y GBP IR swap, MtM=-4m) in netting set NS_MGN_002
        - NS_MGN_002: margined, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d
        - margin agreement MA_MGN_002: remargining_frequency_days=126 (the
          126-day remargin frequency produces MPOR_eff=135 and
          MF_margined=1.102270, which exceeds the unmargined MF=1.0 cap)
        - zero-row CCR collateral (c_net=0)

    The "EAD rises" assertion (P8.54 load-bearing):
        Under the pre-fix engine (MF wiring absent), CCR-A14 would produce EAD
        equivalent to CCR-A13 with unmargined MF=1.0 ≈ 6_464_360.
        After the P8.54 engine fix, CCR-A14 EAD ≈ 6_975_000 (MF=1.10227),
        demonstrating that a long-remargin CSA raises EAD above the unmargined cap.

    Post-fix assertion approximations (engine-precise bytes from CCR-A14.json golden):
        rc_margined ≈ 2_250_000.0
        addon_aggregate ≈ 3_914_298.228 × 1.102270
        ead_final > 6_464_360.391383706   (load-bearing inequality)

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_a14 import build_raw_data_bundle_with_ccr_a14
        data = build_raw_data_bundle_with_ccr_a14()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 274(2) (EAD = 1.4 × (RC + PFE))
        - CRR Art. 275(2) (margined RC = max(V−C, TH+MTA−NICA, 0))
        - CRR Art. 279c(2) (margined MF = 1.5 × sqrt(MPOR_eff / 250))
        - CRR Art. 285(5) (remargin adj: MPOR_eff = base + freq - 1)
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a14_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_golden_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A14 golden parquet files to *output_dir*.

    Files produced:
        ccr_a14_trades.parquet              — 1 row  (T_MGN_002, 10y GBP IR swap, MtM=-4m)
        ccr_a14_netting_sets.parquet        — 1 row  (NS_MGN_002, CP_001, margined)
        ccr_a14_margin_agreements.parquet   — 1 row  (MA_MGN_002, freq=126d)
        ccr_a14_collateral.parquet          — 0 rows (no CCR collateral)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a14_trades", create_ccr_a14_trades()),
        ("ccr_a14_netting_sets", create_ccr_a14_netting_sets()),
        ("ccr_a14_margin_agreements", create_ccr_a14_margin_agreements()),
        ("ccr_a14_collateral", create_ccr_a14_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_golden_fixtures()
    print("CCR-A14 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A14 — single 10y GBP IR swap, MARGINED NS, 126d remargin (EAD rises)")
    print(
        f"  Trade:          {CCR_A14_TRADE_ID} (asset_class={CCR_A14_ASSET_CLASS!r},"
        f" notional={CCR_A14_NOTIONAL:,.0f} {CCR_A14_CURRENCY}, MtM={CCR_A14_MTM:,.0f})"
    )
    print(
        f"  Netting set:    {CCR_A14_NETTING_SET_ID} -> {CCR_A14_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A14_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A14_IS_MARGINED})"
    )
    print(
        f"  Margin:         TH={CCR_A14_MARGIN_THRESHOLD:,.0f},"
        f" MTA={CCR_A14_MINIMUM_TRANSFER_AMOUNT:,.0f},"
        f" NICA={CCR_A14_NICA:,.0f},"
        f" MPOR={CCR_A14_MPOR_DAYS}d,"
        f" freq={CCR_A14_REMARGINING_FREQUENCY_DAYS}d"
    )
    print("  CCR collateral: 0 rows (c_net=0)")
    print()
    print("MPOR cascade (CRR Art. 285):")
    print(
        f"  MPOR_eff = max(10 + {CCR_A14_REMARGINING_FREQUENCY_DAYS} - 1, 10) = {CCR_A14_MPOR_EFF}"
    )
    print(
        f"  MF_margined = 1.5 × sqrt({CCR_A14_MPOR_EFF}/250)"
        f" = {CCR_A14_MF_MARGINED:.12f}  (> 1.0: EAD rises)"
    )
    print()
    print("Post-fix golden approximations (CRR Art. 279c(2) + Art. 275(2)):")
    print(
        f"  rc_margined = max(-4m, TH+MTA-NICA={CCR_A14_MARGIN_THRESHOLD + CCR_A14_MINIMUM_TRANSFER_AMOUNT - CCR_A14_NICA:,.0f}, 0)"
        f" = {CCR_A14_RC_MARGINED:,.1f}"
    )
    print(
        f"  addon_aggregate ≈ 3_914_298.228 × {CCR_A14_MF_MARGINED:.6f} ≈ {CCR_A14_ADDON_AGGREGATE:,.3f}"
    )
    print(
        f"  pfe_addon   ≈ {CCR_A14_PFE_ADDON:,.0f} (hand-calc; engine bytes confirmed downstream)"
    )
    print(
        f"  EAD         ≈ 1.4 × ({CCR_A14_RC_MARGINED:,.1f} + {CCR_A14_PFE_ADDON:,.0f})"
        f" ≈ {CCR_A14_EAD:,.0f}"
    )
    print(f"  RWA         ≈ {CCR_A14_EAD:,.0f} × {CCR_A14_RISK_WEIGHT} ≈ {CCR_A14_RWA:,.0f}")
    print(f"  EAD > {CCR_A14_EAD_LOWER_BOUND:.3f}  (load-bearing: margined MF > 1.0 raises EAD)")
    print()
    bundle = build_raw_data_bundle_with_ccr_a14()
    print(
        f"  build_raw_data_bundle_with_ccr_a14(): ccr={'present' if bundle.ccr is not None else 'absent'}"
    )


if __name__ == "__main__":
    main()
