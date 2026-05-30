"""
Golden CCR-A13 scenario: single 10-year GBP vanilla IR swap, margined netting set.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (SA-CCR margined replacement cost — P8.19 fix)

Scenario design (plan item P8.19, scenario CCR-A13):
    One trade (T_MGN_001): 10-year GBP vanilla IR swap, notional GBP 100m,
    MtM = -4_000_000.0 (out-of-the-money), delta = 1.0 (non-option directional long).
    One netting set (NS_MGN_001): counterparty CP_001, legally enforceable (Art. 295),
    margined with TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10 days.
    One margin agreement (MA_MGN_001): matching the netting-set margin parameters.
    Zero CCR collateral: c_net = 0.0.

Regulatory hand-calc (margined RC formula, CRR Art. 275(2)):
    V = v_net = -4_000_000  (trade MtM, single trade so v_net equals mtm_value)
    C = c_net = 0           (no CCR collateral)
    V - C = -4_000_000
    TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000
    rc_margined = max(V - C,  TH + MTA - NICA,  0)
                = max(-4_000_000,  2_250_000,  0) = 2_250_000  [floor arm binds]
    rc_unmargined (buggy pre-fix) = max(V - C, 0) = max(-4_000_000, 0) = 0

PFE add-on: same IR-swap inputs as CCR-A1 (identical trade parameters),
so addon_aggregate, pfe_multiplier, pfe_addon are identical to CCR-A1.
The margined maturity factor (P8.14 scope) is NOT yet wired; PFE still
uses the unmargined MF path.  Engine-precise values extracted from the
current (unfixed) engine:
    addon_aggregate = 3_914_298.2277279915
    pfe_multiplier  = 0.6048083569079303   (V < 0 so cap does not bind)
    pfe_addon       = 2_367_400.27955979

Post-fix golden targets (P8.19 engine fix restores rc_margined):
    EAD = alpha * (rc_margined + pfe_addon)
        = 1.4 * (2_250_000.0 + 2_367_400.27955979)
        = 1.4 * 4_617_400.27955979
        = 6_464_360.391383706
    RWA = EAD * risk_weight = 6_464_360.391383706 * 0.50 = 3_232_180.195691853

Pre-fix degenerate (rc = 0 bug):
    buggy_EAD = 1.4 * (0.0 + pfe_addon) = 3_314_360.391383706
    buggy_RWA = 1_657_180.195691853
    These are the values the CURRENT engine produces — the acceptance test
    will be RED until P8.19 fix is applied.

Counterparty / rating: reuse CCR-A1 CP_001 stubs verbatim.
    CP_001: institution, CQS 2, GB.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.

References:
    - CRR Art. 272(4) (netting set definition)
    - CRR Art. 272(7) (margin agreement / CSA definition)
    - CRR Art. 274(2) (EAD = alpha * (RC + PFE), alpha = 1.4)
    - CRR Art. 275(2) (margined RC = max(V - C, TH + MTA - NICA, 0))
    - CRR Art. 279b (PFE add-on — interest rate asset class)
    - CRR Art. 285(2)(b) (10-day minimum MPOR)
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

from .margin_builder import Margin, create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CCR_A13_TRADE_ID: str = "T_MGN_001"
CCR_A13_NETTING_SET_ID: str = "NS_MGN_001"
CCR_A13_COUNTERPARTY_REF: str = "CP_001"
CCR_A13_MARGIN_AGREEMENT_ID: str = "MA_MGN_001"

CCR_A13_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A13_CURRENCY: str = "GBP"
CCR_A13_ASSET_CLASS: str = "interest_rate"
CCR_A13_TRANSACTION_TYPE: str = "derivative"
CCR_A13_MTM: float = -4_000_000.0  # out-of-the-money; drives floor arm in RC
CCR_A13_DELTA: float = 1.0
CCR_A13_IS_LONG: bool = True

# 10-year tenor: same as CCR-A1 (PFE inputs identical).
CCR_A13_START_DATE: _date = _date(2026, 1, 15)
CCR_A13_MATURITY_DATE: _date = _date(2036, 1, 15)

CCR_A13_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A13_IS_MARGINED: bool = True

# Margin / CSA parameters (CRR Art. 272(7) / Art. 285(2)(b)).
# TH + MTA - NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000 [floor arm]
CCR_A13_MARGIN_THRESHOLD: float = 2_000_000.0
CCR_A13_MINIMUM_TRANSFER_AMOUNT: float = 500_000.0
CCR_A13_NICA: float = 250_000.0
CCR_A13_MPOR_DAYS: int = 10  # regulatory minimum per Art. 285(2)(b)
CCR_A13_IS_SEGREGATED_IM: bool = False
CCR_A13_REMARGINING_FREQUENCY_DAYS: int = 1
CCR_A13_DISPUTE_COUNT_QTR: int = 0
CCR_A13_NUMBER_OF_TRADES: int = 1
CCR_A13_HAS_ILLIQUID_COLLATERAL: bool = False

# ---------------------------------------------------------------------------
# P8.20 portfolio-stub constants — reused verbatim from CCR-A1.
# ---------------------------------------------------------------------------

# CP_001: institution, CQS 2, GB.
# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A13_CP_ENTITY_TYPE: str = "institution"
CCR_A13_CP_COUNTRY_CODE: str = "GB"

# External rating: S&P "A" = CQS 2.
CCR_A13_RATING_REF: str = "RTG_CCR_A1_CP_001"
CCR_A13_RATING_TYPE: str = "external"
CCR_A13_RATING_AGENCY: str = "S&P"
CCR_A13_RATING_VALUE: str = "A"
CCR_A13_RATING_CQS: int = 2
CCR_A13_RATING_DATE: _date = _date(2026, 1, 15)

# ---------------------------------------------------------------------------
# Golden expected values — engine-precise, post P8.19 fix.
# ---------------------------------------------------------------------------

# PFE inputs: identical to CCR-A1 (same trade parameters, unmargined MF path).
# Extracted from the current engine prior to P8.19 fix:
CCR_A13_ADDON_AGGREGATE: float = 3_914_298.2277279915
CCR_A13_PFE_MULTIPLIER: float = 0.6048083569079303  # V < 0 → cap does not bind
CCR_A13_PFE_ADDON: float = 2_367_400.27955979

# Margined RC — post-fix golden (P8.19 restores this computation).
# CRR Art. 275(2): RC = max(V-C, TH+MTA-NICA, 0).
# max(-4_000_000, 2_250_000, 0) = 2_250_000  [TH+MTA-NICA floor arm binds]
CCR_A13_RC_MARGINED: float = 2_250_000.0

# Unmargined RC: pre-fix buggy value is 0 (max(-4_000_000, 0) = 0).
# The engine currently places this in rc_unmargined. Post-fix, rc_unmargined
# remains 0 since NS_MGN_001 is margined (the unmargined path is skipped).
CCR_A13_RC_UNMARGINED: float = 0.0

# alpha = 1.4 (CRR Art. 274(2)).
# EAD = alpha * (rc_margined + pfe_addon)
CCR_A13_ALPHA: float = 1.4
CCR_A13_EAD: float = CCR_A13_ALPHA * (CCR_A13_RC_MARGINED + CCR_A13_PFE_ADDON)
# = 1.4 * (2_250_000.0 + 2_367_400.27955979)
# = 1.4 * 4_617_400.27955979
# = 6_464_360.391383706

# Risk weight: institution CQS 2, CRR Art. 120(1) Table 3.
CCR_A13_RISK_WEIGHT: float = 0.50
CCR_A13_RWA: float = CCR_A13_EAD * CCR_A13_RISK_WEIGHT
# = 3_232_180.195691853

# Pre-fix degenerate values (current engine output — test will be RED until fix):
#   buggy_rc = 0.0  (max(-4_000_000, 0) used instead of margined formula)
#   buggy_ead = 1.4 * (0.0 + 2_367_400.27955979) = 3_314_360.391383706
#   buggy_rwa = 1_657_180.195691853

# Exposure reference identifier for the CCR pipeline adapter.
CCR_A13_EXPOSURE_REFERENCE: str = "ccr__NS_MGN_001"


# ---------------------------------------------------------------------------
# Private scenario builders (CCR domain)
# ---------------------------------------------------------------------------


def _ccr_a13_trade() -> Trade:
    """Return the single CCR-A13 trade instance (margined, MtM=-4m)."""
    return make_trade(
        trade_id=CCR_A13_TRADE_ID,
        netting_set_id=CCR_A13_NETTING_SET_ID,
        asset_class=CCR_A13_ASSET_CLASS,
        transaction_type=CCR_A13_TRANSACTION_TYPE,
        notional=CCR_A13_NOTIONAL,
        currency=CCR_A13_CURRENCY,
        maturity_date=CCR_A13_MATURITY_DATE,
        start_date=CCR_A13_START_DATE,
        delta=CCR_A13_DELTA,
        is_long=CCR_A13_IS_LONG,
        mtm_value=CCR_A13_MTM,
    )


def _ccr_a13_netting_set() -> NettingSet:
    """Return the single CCR-A13 netting set instance (margined, TH=2m, MTA=0.5m, NICA=0.25m)."""
    return NettingSet(
        netting_set_id=CCR_A13_NETTING_SET_ID,
        counterparty_reference=CCR_A13_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A13_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A13_IS_MARGINED,
        margin_threshold=CCR_A13_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_A13_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_A13_NICA,
        mpor_days=CCR_A13_MPOR_DAYS,
        margin_agreement_id=CCR_A13_MARGIN_AGREEMENT_ID,
        number_of_trades=CCR_A13_NUMBER_OF_TRADES,
        has_illiquid_collateral_or_hard_to_replace_otc=CCR_A13_HAS_ILLIQUID_COLLATERAL,
    )


def _ccr_a13_margin() -> Margin:
    """Return the CCR-A13 margin agreement (MA_MGN_001)."""
    return Margin(
        margin_agreement_id=CCR_A13_MARGIN_AGREEMENT_ID,
        counterparty_reference=CCR_A13_COUNTERPARTY_REF,
        margin_threshold=CCR_A13_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_A13_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_A13_NICA,
        mpor_days=CCR_A13_MPOR_DAYS,
        is_segregated_im=CCR_A13_IS_SEGREGATED_IM,
        remargining_frequency_days=CCR_A13_REMARGINING_FREQUENCY_DAYS,
        dispute_count_qtr=CCR_A13_DISPUTE_COUNT_QTR,
    )


# ---------------------------------------------------------------------------
# DataFrame factories (CCR domain)
# ---------------------------------------------------------------------------


def create_ccr_a13_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A13."""
    return create_trades([_ccr_a13_trade()])


def create_ccr_a13_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A13."""
    return create_netting_sets([_ccr_a13_netting_set()])


def create_ccr_a13_margin_agreements() -> pl.DataFrame:
    """Return the single-row margin-agreements DataFrame for CCR-A13 (MA_MGN_001)."""
    return create_margin_agreements([_ccr_a13_margin()])


def create_ccr_a13_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A13: no CCR collateral, c_net=0)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Private portfolio-stub builders (P8.20 pattern)
# ---------------------------------------------------------------------------


def _build_cp_001_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_001.

    Reused verbatim from golden_ccr_a1._build_cp_001_counterparty().
    CP_001 is a GB institution with CQS 2 under CRR.  entity_type="institution"
    drives the Classifier to ExposureClass.INSTITUTION → SA risk weight lookup via
    CRR Art. 120(1) Table 3 (CQS 2 → 50%).
    """
    row = {
        "counterparty_reference": CCR_A13_COUNTERPARTY_REF,
        "counterparty_name": "CCR-A1 Test Institution (CQS 2)",
        "entity_type": CCR_A13_CP_ENTITY_TYPE,
        "country_code": CCR_A13_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_A13_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cp_001_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_001.

    Reused verbatim from golden_ccr_a1._build_cp_001_rating().
    S&P "A" = CQS 2 under CRR ECRA mapping for institutions.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    """
    row = {
        "rating_reference": CCR_A13_RATING_REF,
        "counterparty_reference": CCR_A13_COUNTERPARTY_REF,
        "rating_type": CCR_A13_RATING_TYPE,
        "rating_agency": CCR_A13_RATING_AGENCY,
        "rating_value": CCR_A13_RATING_VALUE,
        "cqs": CCR_A13_RATING_CQS,
        "pd": None,
        "rating_date": CCR_A13_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame (no traditional lending in CCR-A13 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame (no drawn loans in CCR-A13 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame (no facility hierarchy in CCR-A13 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame (no retail lending groups in CCR-A13 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_ccr_a13_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the four CCR-A13 domain frames.

    Composition:
        trades              — 1 row  (T_MGN_001, 10y GBP IR swap, NS_MGN_001, MtM=-4m)
        netting_sets        — 1 row  (NS_MGN_001, CP_001, enforceable, margined)
        margin_agreements   — 1 row  (MA_MGN_001, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d)
        ccr_collateral      — 0 rows (no CCR collateral, c_net=0.0)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a13_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a13_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a13_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a13_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helper
# ---------------------------------------------------------------------------


def build_raw_data_bundle_with_ccr_a13() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A13 data populated.

    Key responsibilities:
    - Provides CP_001 as an institution counterparty (entity_type="institution",
      CQS 2, GB) so the Classifier routes the CCR-derived synthetic exposure
      through SA-Institution (CRR Art. 120(1) Table 3 → 50% RW).
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves ``external_cqs`` correctly.
    - Zero-row facility / loan / contingent / mapping frames so the only
      exposure in the pipeline is the CCR-derived synthetic row.
    - ``ccr`` is populated with a RawCCRBundle containing:
        - trade T_MGN_001 (10y GBP IR swap, MtM=-4m) in netting set NS_MGN_001
        - NS_MGN_001: margined, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d
        - margin agreement MA_MGN_001 with identical margin parameters
        - zero-row CCR collateral (c_net=0)

    Degenerate behaviour under the CURRENT (unfixed) engine:
        The pre-fix engine uses rc_unmargined = max(V-C, 0) = max(-4m, 0) = 0
        instead of the Art. 275(2) margined formula, so EAD is understated.
        The acceptance test driven by CCR-A13.json will be RED until P8.19 fix.

    Post-fix assertion (from CCR-A13.json golden):
        rc_margined = 2_250_000.0  (TH+MTA-NICA floor arm)
        ead_ccr     = 6_464_360.391383706
        rwa_final   = 3_232_180.195691853

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_a13 import build_raw_data_bundle_with_ccr_a13
        data = build_raw_data_bundle_with_ccr_a13()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 274(2) (EAD = 1.4 × (RC + PFE))
        - CRR Art. 275(2) (margined RC = max(V−C, TH+MTA−NICA, 0))
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return RawDataBundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a13_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_golden_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A13 golden parquet files to *output_dir*.

    Files produced:
        ccr_a13_trades.parquet              — 1 row  (T_MGN_001, 10y GBP IR swap, MtM=-4m)
        ccr_a13_netting_sets.parquet        — 1 row  (NS_MGN_001, CP_001, margined)
        ccr_a13_margin_agreements.parquet   — 1 row  (MA_MGN_001, TH=2m, MTA=0.5m)
        ccr_a13_collateral.parquet          — 0 rows (no CCR collateral)

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
        ("ccr_a13_trades", create_ccr_a13_trades()),
        ("ccr_a13_netting_sets", create_ccr_a13_netting_sets()),
        ("ccr_a13_margin_agreements", create_ccr_a13_margin_agreements()),
        ("ccr_a13_collateral", create_ccr_a13_collateral()),
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
    print("CCR-A13 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A13 — single 10y GBP IR swap, MARGINED netting set")
    print(
        f"  Trade:          {CCR_A13_TRADE_ID} (asset_class={CCR_A13_ASSET_CLASS!r},"
        f" notional={CCR_A13_NOTIONAL:,.0f} {CCR_A13_CURRENCY}, MtM={CCR_A13_MTM:,.0f})"
    )
    print(
        f"  Netting set:    {CCR_A13_NETTING_SET_ID} -> {CCR_A13_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A13_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A13_IS_MARGINED})"
    )
    print(
        f"  Margin:         TH={CCR_A13_MARGIN_THRESHOLD:,.0f},"
        f" MTA={CCR_A13_MINIMUM_TRANSFER_AMOUNT:,.0f},"
        f" NICA={CCR_A13_NICA:,.0f},"
        f" MPOR={CCR_A13_MPOR_DAYS}d"
    )
    print("  CCR collateral: 0 rows (c_net=0)")
    print()
    print("Post-fix golden (CRR Art. 275(2)):")
    print(
        f"  rc_margined = max(-4m, TH+MTA-NICA={CCR_A13_MARGIN_THRESHOLD + CCR_A13_MINIMUM_TRANSFER_AMOUNT - CCR_A13_NICA:,.0f}, 0) = {CCR_A13_RC_MARGINED:,.1f}"
    )
    print(f"  pfe_addon   = {CCR_A13_PFE_ADDON:.8f}")
    print(
        f"  EAD         = 1.4 * ({CCR_A13_RC_MARGINED:,.1f} + {CCR_A13_PFE_ADDON:.3f}) = {CCR_A13_EAD:.6f}"
    )
    print(f"  RWA         = {CCR_A13_EAD:.6f} * {CCR_A13_RISK_WEIGHT} = {CCR_A13_RWA:.6f}")
    print()
    bundle = build_raw_data_bundle_with_ccr_a13()
    print(
        f"  build_raw_data_bundle_with_ccr_a13(): ccr={'present' if bundle.ccr is not None else 'absent'}"
    )


if __name__ == "__main__":
    main()
