"""
P8.60 / CVA-A1 fixture builder: BA-CVA reduced-K vertical slice.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_cva_a1_ba_cva_reduced.py)
    -> engine-implementer (engine/cva/ba_cva.py)

Scenario design:
    Single counterparty CP_CVA_001 / single netting set NS_CVA_001.
    The CCR trade is a 3-year GBP vanilla IR swap identical in economic structure
    to CCR-A1 but with a 3-year maturity (effective maturity M = 3.0 years) so
    that DF_NS != 1.0, exercising the supervisory discount-factor formula.

    The CCR fixture reuses the existing CCR-A1 trade/netting-set builders with
    overridden IDs and maturity, so ead_ccr is computed by the live SA-CCR
    pipeline (not hand-coded). The CCR-A1 golden gives:

        EAD (10y) = 5,480,017.519  (alpha x (RC + PFE_addon) = 1.4 x 3,914,298.228)

    For a 3-year GBP IR swap with the same notional GBP 100m, the supervisory
    duration SD(S, E) = (e^(-0.05*1) - e^(-0.05*3)) / 0.05 = 1.8534 and the
    adjusted notional = 100m x 1.8534 = 185,337,188.  However, the EAD for
    the 3-year trade must be computed by running the pipeline.  The fixture
    provides a CCR input bundle for the 3-year trade; tests must materialise
    ead_ccr from the pipeline and feed it to the CVA computation.

    For the acceptance test golden:
        EAD_NS (anchor) = value produced by the 3-year CCR pipeline run

    The CVA hand-calc uses the confirmed regulatory parameters:

    Source-verified (ps126app1.pdf - this document is effective from 1 Jan 2027):
        - DSBA-CVA = 0.65                                 [page 399, section 4.2]
        - rho = 50%                                       [page 399, section 4.2]
        - DF_NS = (1 - e^(-0.05*M)) / (0.05*M)           [page 400, section 4.3]
        - rate = 0.05 (supervisory discount rate)          [page 400, section 4.3]
        - alpha = 1.4 (from CCR Part, Art. 274)           [page 400, section 4.3]
        - RW_c (Financials IG) = 5.0%                     [page 401, section 4.4 table]
        - RWEA = OFR_CVA x 12.5 (Art. 92(4)(b))          [page 15, section 4]

    K_reduced formula (single counterparty, n=1):
        K_reduced = sqrt[(rho * SCVA_c)^2 + (1-rho^2) * SCVA_c^2]
                  = SCVA_c * sqrt[rho^2 + 1 - rho^2]
                  = SCVA_c    (collapses to identity for n=1)

    SCVA_c = (1/alpha) * RW_c * M_NS * EAD_NS * DF_NS

    IMPORTANT CORRECTION vs the scenario-architect proposal:
        The proposal omitted the DSBA-CVA = 0.65 scalar.  The PRA CVA Part
        section 4.2 is explicit: the own-funds requirement is DSBA-CVA * K_reduced.
        The RWEA is therefore: 0.65 * K_reduced * 12.5 (NOT K_reduced * 12.5).
        The architect's cva_rwa=12,436,787.81 used EAD=10,000,000 AND omitted
        DSBA-CVA.  Both must be corrected.

    Hand-calc with actual CCR-A1 EAD (10y) = 5,480,017.519 (for reference):
        DF_NS = (1 - e^(-0.05 * 3.0)) / (0.05 * 3.0) = 0.9286134905
        SCVA_c = (1/1.4) * 0.05 * 3.0 * 5,480,017.519 * 0.9286134905 = 545,230.521
        K_reduced = 545,230.521   (single-CP identity)
        OFR_CVA = 0.65 * 545,230.521 = 354,399.839
        RWEA_CVA = 354,399.839 * 12.5 = 4,429,997.983

    Note: tests must compute RWEA_CVA from the ACTUAL ead_ccr the pipeline emits
    for the 3-year trade, not from the 10-year CCR-A1 golden.

CVA counterparty input schema (CVA_COUNTERPARTY_SCHEMA):
    counterparty_reference  String   FK to netting set's counterparty_reference
    cva_rw_sector           String   "FINANCIAL" (maps to RW 5.0% IG per table)
    cva_rw_rating_band      String   "IG" (investment grade)
    cva_effective_maturity_years Float64  3.0
    cva_in_scope            Boolean  True

References:
    - PS1/26 App.1 CVA Part section 4.2  (BA-CVA reduced formula, DSBA-CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part section 4.3  (SCVA_c formula, DF formula, alpha)
    - PS1/26 App.1 CVA Part section 4.4  (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 Own Funds Part 4(b)   (x12.5 multiplier, page 15)
    - CRR Art. 274(2) (SA-CCR EAD = alpha * (RC + PFE))
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 279b(1)(a) (interest-rate PFE add-on)
    - src/rwa_calc/data/schemas.py (TRADE_SCHEMA, NETTING_SET_SCHEMA, COUNTERPARTY_SCHEMA)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import NettingSet, create_netting_sets
from tests.fixtures.ccr.trade_builder import Trade, create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CVA_A1_COUNTERPARTY_REF: str = "CP_CVA_001"
CVA_A1_NETTING_SET_ID: str = "NS_CVA_001"
CVA_A1_TRADE_ID: str = "T_CVA_001"

# Trade economics: 3-year GBP vanilla IR swap.
# Effective maturity = 3.0 years drives DF_NS != 1.0 and exercises the DF formula.
CVA_A1_NOTIONAL: float = 100_000_000.0  # GBP 100m
CVA_A1_CURRENCY: str = "GBP"
CVA_A1_ASSET_CLASS: str = "interest_rate"
CVA_A1_TRANSACTION_TYPE: str = "derivative"
CVA_A1_MTM: float = 0.0  # at-par
CVA_A1_DELTA: float = 1.0  # non-option directional long
CVA_A1_IS_LONG: bool = True
CVA_A1_START_DATE: _date = _date(2027, 1, 15)  # Basel 3.1 effective date
CVA_A1_MATURITY_DATE: _date = _date(2030, 1, 15)  # 3 years -> M_NS = 3.0

CVA_A1_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
CVA_A1_IS_MARGINED: bool = False  # unmargined

# Counterparty: institution (financial), CQS 2, GB.
# entity_type="institution" routes CCR exposure through SA-Institution RW lookup.
CVA_A1_CP_ENTITY_TYPE: str = "institution"
CVA_A1_CP_COUNTRY_CODE: str = "GB"
CVA_A1_RATING_REF: str = "RTG_CVA_A1_CP"
CVA_A1_RATING_TYPE: str = "external"
CVA_A1_RATING_AGENCY: str = "S&P"
CVA_A1_RATING_VALUE: str = "A"  # S&P "A" = CQS 2
CVA_A1_RATING_CQS: int = 2
CVA_A1_RATING_DATE: _date = _date(2027, 1, 15)

# ---------------------------------------------------------------------------
# CVA counterparty input constants (CVA_COUNTERPARTY_SCHEMA).
# ---------------------------------------------------------------------------

# Sector maps to PS1/26 App.1 CVA Part 4.4 table row:
#   "Financials including government-backed financials, excluding pension funds"
CVA_A1_CVA_RW_SECTOR: str = "FINANCIAL"

# IG = investment grade; maps to RW_c = 5.0% (0.05) per 4.4 table.
CVA_A1_CVA_RW_RATING_BAND: str = "IG"

# Effective maturity (years) — inputs the DF_NS formula.
CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS: float = 3.0

# In-scope for BA-CVA calculation.
CVA_A1_CVA_IN_SCOPE: bool = True

# ---------------------------------------------------------------------------
# Confirmed regulatory scalars (source-verified against ps126app1.pdf).
# ---------------------------------------------------------------------------

# PS1/26 App.1 CVA Part 4.2, page 399.
CVA_DS_BA_CVA: float = 0.65
CVA_SUPERVISORY_CORRELATION_RHO: float = 0.50

# PS1/26 App.1 CVA Part 4.3, page 400.
CVA_SUPERVISORY_DISCOUNT_RATE: float = 0.05
CVA_ALPHA: float = 1.4  # from CCR Part Art. 274(2)

# PS1/26 App.1 CVA Part 4.4, page 401 — Financials IG.
CVA_RW_FINANCIALS_IG: float = 0.05  # 5.0%

# RWEA multiplier: PS1/26 App.1 Own Funds Part 4(b), page 15.
CVA_RWEA_MULTIPLIER: float = 12.5


def compute_cva_a1_golden(ead_ccr: float) -> dict[str, float]:
    """
    Compute the CVA-A1 golden values from a confirmed EAD.

    Uses source-verified scalars from ps126app1.pdf.

    Args:
        ead_ccr: The materialised EAD from the CCR pipeline for NS_CVA_001.

    Returns:
        Dict with keys: df_ns, scva_c, k_reduced, ofr_cva, rwea_cva.

    References:
        - PS1/26 App.1 CVA Part 4.2 (K_reduced, DSBA-CVA, rho)
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c, DF formula)
        - PS1/26 App.1 CVA Part 4.4 (RW_c Financials IG = 5%)
        - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    """
    m_ns = CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS
    rate = CVA_SUPERVISORY_DISCOUNT_RATE
    rho = CVA_SUPERVISORY_CORRELATION_RHO
    rw_c = CVA_RW_FINANCIALS_IG
    alpha = CVA_ALPHA

    # DF_NS = (1 - e^(-rate * M)) / (rate * M)
    df_ns = (1.0 - math.exp(-rate * m_ns)) / (rate * m_ns)

    # SCVA_c = (1/alpha) * RW_c * M_NS * EAD_NS * DF_NS
    scva_c = (1.0 / alpha) * rw_c * m_ns * ead_ccr * df_ns

    # K_reduced collapses to SCVA_c for single counterparty (n=1):
    # sqrt[(rho * SCVA_c)^2 + (1 - rho^2) * SCVA_c^2]
    # = SCVA_c * sqrt[rho^2 + 1 - rho^2] = SCVA_c * 1.0
    k_reduced = math.sqrt((rho * scva_c) ** 2 + (1.0 - rho**2) * scva_c**2)

    # OFR_CVA = DSBA-CVA * K_reduced  (own-funds requirement, not yet RWEA)
    ofr_cva = CVA_DS_BA_CVA * k_reduced

    # RWEA_CVA = OFR_CVA * 12.5  (Art. 92(4)(b))
    rwea_cva = ofr_cva * CVA_RWEA_MULTIPLIER

    return {
        "df_ns": df_ns,
        "scva_c": scva_c,
        "k_reduced": k_reduced,
        "ofr_cva": ofr_cva,
        "rwea_cva": rwea_cva,
    }


# ---------------------------------------------------------------------------
# CVA counterparty DataFrame builder.
# ---------------------------------------------------------------------------

# Explicit schema for the CVA counterparty input table.
# This schema mirrors the CVA_COUNTERPARTY_SCHEMA the engine-implementer will
# register in src/rwa_calc/data/schemas.py; defined here explicitly so tests
# can run before the schema is wired into the engine.
CVA_COUNTERPARTY_SCHEMA_DTYPES: dict[str, type[pl.DataType]] = {
    "counterparty_reference": pl.String,
    "cva_rw_sector": pl.String,
    "cva_rw_rating_band": pl.String,
    "cva_effective_maturity_years": pl.Float64,
    "cva_in_scope": pl.Boolean,
}


def create_cva_a1_counterparty_frame() -> pl.DataFrame:
    """
    Return the single-row CVA counterparty input DataFrame for CVA-A1.

    Columns match CVA_COUNTERPARTY_SCHEMA as specified in the P8.60 proposal:
        counterparty_reference  String   — FK to netting set's counterparty_reference
        cva_rw_sector           String   — sector key for RW lookup (Art. 4.4 table)
        cva_rw_rating_band      String   — "IG" or "HY_NR"
        cva_effective_maturity_years Float64 — M_NS in years (inputs DF formula)
        cva_in_scope            Boolean  — flags exposure as BA-CVA in-scope

    References:
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c inputs: M_NS, EAD_NS, DF_NS)
        - PS1/26 App.1 CVA Part 4.4 (sector / rating-band RW table)
    """
    row: dict[str, object] = {
        "counterparty_reference": CVA_A1_COUNTERPARTY_REF,
        "cva_rw_sector": CVA_A1_CVA_RW_SECTOR,
        "cva_rw_rating_band": CVA_A1_CVA_RW_RATING_BAND,
        "cva_effective_maturity_years": CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS,
        "cva_in_scope": CVA_A1_CVA_IN_SCOPE,
    }
    return pl.DataFrame([row], schema=CVA_COUNTERPARTY_SCHEMA_DTYPES)


# ---------------------------------------------------------------------------
# CCR domain builders for the 3-year trade.
# ---------------------------------------------------------------------------


def _cva_a1_trade() -> Trade:
    """Return the 3-year GBP IR swap for CVA-A1."""
    return make_trade(
        trade_id=CVA_A1_TRADE_ID,
        netting_set_id=CVA_A1_NETTING_SET_ID,
        asset_class=CVA_A1_ASSET_CLASS,
        transaction_type=CVA_A1_TRANSACTION_TYPE,
        notional=CVA_A1_NOTIONAL,
        currency=CVA_A1_CURRENCY,
        maturity_date=CVA_A1_MATURITY_DATE,
        start_date=CVA_A1_START_DATE,
        delta=CVA_A1_DELTA,
        is_long=CVA_A1_IS_LONG,
        mtm_value=CVA_A1_MTM,
    )


def _cva_a1_netting_set() -> NettingSet:
    """Return the single netting set for CVA-A1."""
    return NettingSet(
        netting_set_id=CVA_A1_NETTING_SET_ID,
        counterparty_reference=CVA_A1_COUNTERPARTY_REF,
        is_legally_enforceable=CVA_A1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CVA_A1_IS_MARGINED,
    )


def create_cva_a1_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CVA-A1."""
    return create_trades([_cva_a1_trade()])


def create_cva_a1_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CVA-A1."""
    return create_netting_sets([_cva_a1_netting_set()])


def create_cva_a1_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CVA-A1: no CSA)."""
    return create_margin_agreements([])


def create_cva_a1_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CVA-A1: no CCR collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Portfolio-stub builders (for full RawDataBundle assembly).
# ---------------------------------------------------------------------------


def _build_cva_cp_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_CVA_001.

    CP_CVA_001: GB institution, CQS 2.  The entity_type="institution" routes
    the CCR-derived synthetic exposure through SA-Institution under both CRR
    and Basel 3.1.  The institution_cqs=2 field is set so the SA risk-weight
    lookup resolves even when the rating-inheritance pipeline is bypassed in
    narrow unit tests.
    """
    row: dict[str, object] = {
        "counterparty_reference": CVA_A1_COUNTERPARTY_REF,
        "counterparty_name": "CVA-A1 Test Financial Institution (CQS 2)",
        "entity_type": CVA_A1_CP_ENTITY_TYPE,
        "country_code": CVA_A1_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CVA_A1_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cva_cp_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_CVA_001.

    S&P "A" = CQS 2 under CRR ECRA for institutions.  The same CQS maps to
    the "Financials IG" band in the CVA Part 4.4 RW table (RW_c = 5.0%).
    """
    row: dict[str, object] = {
        "rating_reference": CVA_A1_RATING_REF,
        "counterparty_reference": CVA_A1_COUNTERPARTY_REF,
        "rating_type": CVA_A1_RATING_TYPE,
        "rating_agency": CVA_A1_RATING_AGENCY,
        "rating_value": CVA_A1_RATING_VALUE,
        "cqs": CVA_A1_RATING_CQS,
        "pd": None,
        "rating_date": CVA_A1_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_cva_a1_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for the CVA-A1 3-year IR swap.

    Composition:
        trades          — 1 row  (T_CVA_001, 3y GBP IR swap, NS_CVA_001)
        netting_sets    — 1 row  (NS_CVA_001, CP_CVA_001, enforceable, unmargined)
        margin_agreements — 0 rows (no CSA)
        ccr_collateral  — 0 rows (no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_cva_a1_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_cva_a1_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_cva_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_cva_a1_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_cva_a1() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for the CVA-A1 scenario.

    Key responsibilities:
    - Provides CP_CVA_001 as a GB institution counterparty (CQS 2) so the
      Classifier routes the CCR-derived synthetic exposure through SA-Institution.
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves external_cqs correctly.
    - Zero-row facility / loan / contingent / mapping frames so the only
      exposure in the pipeline is the CCR-derived synthetic row.
    - ccr is populated with the 3-year GBP IR swap bundle (T_CVA_001 / NS_CVA_001).

    The acceptance test must:
    1. Run this bundle through the CCR pipeline to materialise ead_ccr.
    2. Feed (ead_ccr, cva_counterparty_frame) to the CVA engine.
    3. Assert rwea_cva matches the formula output of compute_cva_a1_golden(ead_ccr).

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced)
        - CRR Art. 274(2) (SA-CCR EAD for CCR step)
    """
    return make_raw_bundle(
        counterparties=_build_cva_cp_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cva_cp_rating(),
        ccr=_build_cva_a1_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Parquet save helpers.
# ---------------------------------------------------------------------------


def save_cva_a1_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CVA-A1 parquet files to output_dir.

    Files produced:
        cva_a1_trades.parquet           — 1 row  (T_CVA_001, 3y GBP IR swap)
        cva_a1_netting_sets.parquet     — 1 row  (NS_CVA_001, CP_CVA_001)
        cva_a1_margin_agreements.parquet — 0 rows
        cva_a1_ccr_collateral.parquet   — 0 rows
        cva_a1_cva_counterparties.parquet — 1 row (CP_CVA_001, FINANCIAL, IG, M=3.0)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/p8_60/``).

    Returns:
        Dict mapping artefact name to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("cva_a1_trades", create_cva_a1_trades()),
        ("cva_a1_netting_sets", create_cva_a1_netting_sets()),
        ("cva_a1_margin_agreements", create_cva_a1_margin_agreements()),
        ("cva_a1_ccr_collateral", create_cva_a1_collateral()),
        ("cva_a1_cva_counterparties", create_cva_a1_counterparty_frame()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


@dataclass
class CvaA1Inputs:
    """
    Named fixture bundle for the CVA-A1 acceptance test.

    Attributes:
        raw_data_bundle: Complete RawDataBundle for the CCR pipeline.
        cva_counterparty_frame: Single-row CVA counterparty input DataFrame.
        counterparty_ref: Reference key for the single counterparty.
        netting_set_id: Netting set identifier.
    """

    raw_data_bundle: RawDataBundle
    cva_counterparty_frame: pl.DataFrame
    counterparty_ref: str
    netting_set_id: str


def build_cva_a1_inputs() -> CvaA1Inputs:
    """
    Return the named bundle the acceptance test feeds the pipeline.

    Usage in acceptance test:

        from tests.fixtures.p8_60.cva_a1_builder import (
            build_cva_a1_inputs,
            compute_cva_a1_golden,
            CVA_A1_NETTING_SET_ID,
        )

        inputs = build_cva_a1_inputs()
        # Run CCR pipeline to get ead_ccr ...
        golden = compute_cva_a1_golden(ead_ccr)
        assert abs(result.rwea_cva - golden['rwea_cva']) < 1.0
    """
    return CvaA1Inputs(
        raw_data_bundle=build_raw_data_bundle_cva_a1(),
        cva_counterparty_frame=create_cva_a1_counterparty_frame(),
        counterparty_ref=CVA_A1_COUNTERPARTY_REF,
        netting_set_id=CVA_A1_NETTING_SET_ID,
    )


def save_p860_fixtures(output_dir: Path | None = None) -> list[tuple[str, int]]:
    """
    Smoke-check the CVA-A1 bundle and persist parquet files to output_dir.

    Invariants checked:
        1. RawCCRBundle is present and non-None.
        2. Trades frame has exactly 1 row (T_CVA_001, 3-year GBP IR swap).
        3. Netting-sets frame has 1 row (NS_CVA_001, legally enforceable, unmargined).
        4. Margin-agreements frame has 0 rows.
        5. CCR-collateral frame has 0 rows.
        6. CVA counterparty frame has 1 row with expected column values.
        7. Counterparty frame has 1 row (CP_CVA_001, entity_type=institution, CQS 2).
        8. Ratings frame has 1 row (CQS 2, S&P A, solicited).
        9. compute_cva_a1_golden returns self-consistent values for test EAD.
        10. K_reduced == SCVA_c for single counterparty (identity invariant).

    Returns:
        List of (filename, row_count) tuples for the master report.
    """
    saved = save_cva_a1_fixtures(output_dir)

    # Build inputs and run invariant checks.
    inputs = build_cva_a1_inputs()
    bundle = inputs.raw_data_bundle

    # Invariant 1: CCR bundle present.
    if bundle.ccr is None:
        raise AssertionError("CVA-A1: bundle.ccr must not be None")

    # Invariant 2: trades frame.
    trades_df = bundle.ccr.trades.trades.collect()
    if len(trades_df) != 1:
        raise AssertionError(f"CVA-A1: expected 1 trade row, got {len(trades_df)}")
    if trades_df["trade_id"][0] != CVA_A1_TRADE_ID:
        raise AssertionError(
            f"CVA-A1: trade_id {trades_df['trade_id'][0]!r} != {CVA_A1_TRADE_ID!r}"
        )
    if trades_df["maturity_date"][0] != CVA_A1_MATURITY_DATE:
        raise AssertionError(
            f"CVA-A1: maturity_date {trades_df['maturity_date'][0]} != {CVA_A1_MATURITY_DATE}"
        )

    # Invariant 3: netting-sets frame.
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    if len(ns_df) != 1:
        raise AssertionError(f"CVA-A1: expected 1 NS row, got {len(ns_df)}")
    if not ns_df["is_legally_enforceable"][0]:
        raise AssertionError("CVA-A1: netting set must be legally enforceable")
    if ns_df["is_margined"][0]:
        raise AssertionError("CVA-A1: netting set must be unmargined")

    # Invariant 4: margin-agreements frame has 0 rows.
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    if len(margin_df) != 0:
        raise AssertionError(f"CVA-A1: expected 0 margin rows, got {len(margin_df)}")

    # Invariant 5: CCR-collateral frame has 0 rows.
    collateral_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    if len(collateral_df) != 0:
        raise AssertionError(f"CVA-A1: expected 0 collateral rows, got {len(collateral_df)}")

    # Invariant 6: CVA counterparty frame.
    cva_cp = inputs.cva_counterparty_frame
    if len(cva_cp) != 1:
        raise AssertionError(f"CVA-A1: expected 1 CVA CP row, got {len(cva_cp)}")
    if cva_cp["counterparty_reference"][0] != CVA_A1_COUNTERPARTY_REF:
        raise AssertionError("CVA-A1: CVA CP counterparty_reference mismatch")
    if cva_cp["cva_rw_sector"][0] != CVA_A1_CVA_RW_SECTOR:
        raise AssertionError("CVA-A1: cva_rw_sector mismatch")
    if cva_cp["cva_rw_rating_band"][0] != CVA_A1_CVA_RW_RATING_BAND:
        raise AssertionError("CVA-A1: cva_rw_rating_band mismatch")
    if abs(cva_cp["cva_effective_maturity_years"][0] - CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS) > 1e-9:
        raise AssertionError("CVA-A1: cva_effective_maturity_years mismatch")
    if not cva_cp["cva_in_scope"][0]:
        raise AssertionError("CVA-A1: cva_in_scope must be True")

    # Invariant 7: counterparty frame.
    cp_df = bundle.counterparties.collect()
    if len(cp_df) != 1:
        raise AssertionError(f"CVA-A1: expected 1 CP row, got {len(cp_df)}")
    if cp_df["counterparty_reference"][0] != CVA_A1_COUNTERPARTY_REF:
        raise AssertionError("CVA-A1: CP counterparty_reference mismatch")
    if cp_df["entity_type"][0] != CVA_A1_CP_ENTITY_TYPE:
        raise AssertionError("CVA-A1: entity_type mismatch")

    # Invariant 8: ratings frame.
    if bundle.ratings is None:
        raise AssertionError("CVA-A1: bundle.ratings must not be None")
    rating_df = bundle.ratings.collect()
    if len(rating_df) != 1:
        raise AssertionError(f"CVA-A1: expected 1 rating row, got {len(rating_df)}")
    if rating_df["cqs"][0] != CVA_A1_RATING_CQS:
        raise AssertionError(f"CVA-A1: rating cqs {rating_df['cqs'][0]} != {CVA_A1_RATING_CQS}")

    # Invariant 9: golden computation self-consistent.
    test_ead = 5_480_017.519  # CCR-A1 10y EAD (smoke-check only)
    golden = compute_cva_a1_golden(test_ead)
    if golden["df_ns"] < 0 or golden["df_ns"] > 1.0:
        raise AssertionError(f"CVA-A1: DF_NS must be in [0,1], got {golden['df_ns']}")
    if golden["scva_c"] <= 0:
        raise AssertionError(f"CVA-A1: SCVA_c must be positive, got {golden['scva_c']}")

    # Invariant 10: K_reduced == SCVA_c for single counterparty.
    if abs(golden["k_reduced"] - golden["scva_c"]) > 1e-6:
        raise AssertionError(
            f"CVA-A1: K_reduced {golden['k_reduced']} != SCVA_c {golden['scva_c']} "
            f"(single-CP identity must hold)"
        )

    return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]


def main() -> None:
    """Entry point for standalone fixture generation and verification."""
    import sys

    saved = save_cva_a1_fixtures()
    print("CVA-A1 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)

    # Verify the bundle constructs cleanly.
    inputs = build_cva_a1_inputs()
    ccr = inputs.raw_data_bundle.ccr
    assert ccr is not None, "RawCCRBundle must be present"
    trades = ccr.trades.trades.collect()
    ns = ccr.netting_sets.netting_sets.collect()
    print(f"  Trade:        {trades['trade_id'][0]}  maturity={trades['maturity_date'][0]}")
    print(f"  Netting set:  {ns['netting_set_id'][0]} -> {ns['counterparty_reference'][0]}")
    print(f"  CVA CP frame: {len(inputs.cva_counterparty_frame)} row(s)")

    # Demonstrate the golden computation with the CCR-A1 10y EAD as a reference.
    # The actual acceptance-test golden is derived from the materialised 3y EAD.
    ead_reference = 5_480_017.519  # CCR-A1 10y EAD (for demonstration only)
    golden_ref = compute_cva_a1_golden(ead_reference)
    print()
    print("Reference golden (using CCR-A1 10y EAD = 5,480,017.519 for illustration):")
    print(f"  DF_NS     = {golden_ref['df_ns']:.10f}")
    print(f"  SCVA_c    = {golden_ref['scva_c']:.4f}")
    print(f"  K_reduced = {golden_ref['k_reduced']:.4f}  (== SCVA_c, single-CP identity)")
    print(f"  OFR_CVA   = {golden_ref['ofr_cva']:.4f}  (= 0.65 * K_reduced)")
    print(f"  RWEA_CVA  = {golden_ref['rwea_cva']:.4f}  (= OFR_CVA * 12.5)")
    print()
    print("NOTE: acceptance tests must derive the golden from the ACTUAL ead_ccr")
    print("      the pipeline emits for the 3-year trade, not this 10-year reference.")

    sys.exit(0)


if __name__ == "__main__":
    main()
