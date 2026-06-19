"""
P8.46 / CVA-A2 fixture builder: BA-CVA reduced-K two-counterparty diversification.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_cva_a2_ba_cva_diversification.py)
    -> engine-implementer (engine/cva/ba_cva.py::compute_ba_cva_rwa)

Scenario design:
    Two counterparties CP_CVA_A2_1 / CP_CVA_A2_2, each with one netting set and
    one GBP vanilla IR swap.  Both are GB institutions, CQS 2 (Financials IG,
    RW = 5.0%), unmargined.

    Counterparty 1: T_CVA_A2_1 / NS_CVA_A2_1 — 3-year swap, M = 3.0 years.
    Counterparty 2: T_CVA_A2_2 / NS_CVA_A2_2 — 5-year swap, M = 5.0 years.

    With two counterparties the K_reduced cross-term (ρ=0.5) produces a result
    that differs from the single-counterparty identity:

        sqrt[(ρ·(SCVA_1+SCVA_2))² + (1−ρ²)·(SCVA_1²+SCVA_2²)]

    This is strictly less than SCVA_1 + SCVA_2 (diversification benefit) and
    strictly greater than sqrt(SCVA_1² + SCVA_2²) (systematic term dominates
    over full independence).

    Green-on-arrival regression pin: the fixture pins against the already-shipped
    BA-CVA engine (engine/cva/ba_cva.py::compute_ba_cva_rwa).  The acceptance
    test materialises EAD for each netting set from the live CCR pipeline and
    passes them to compute_cva_a2_golden to build the comparison target.

Source-verified (ps126app1.pdf — effective from 1 January 2027):
    - DSBA-CVA = 0.65                             [page 399, section 4.2]
    - rho = 50%                                   [page 399, section 4.2]
    - DF_NS = (1 - e^(-0.05*M)) / (0.05*M)       [page 400, section 4.3]
    - rate = 0.05 (supervisory discount rate)      [page 400, section 4.3]
    - alpha = 1.4 (from CCR Part, Art. 274)       [page 400, section 4.3]
    - RW_c (Financials IG) = 5.0%                 [page 401, section 4.4 table]
    - RWEA = OFR_CVA x 12.5 (Art. 92(4)(b))      [page 15, section 4]

K_reduced formula (two counterparties, n=2):
    K_reduced = sqrt[(ρ·(SCVA_1+SCVA_2))² + (1−ρ²)·(SCVA_1²+SCVA_2²)]

    Diversification invariant (strictly holds for SCVA_1 > 0, SCVA_2 > 0):
        sqrt(SCVA_1²+SCVA_2²) < K_reduced < SCVA_1+SCVA_2

References:
    - PS1/26 App.1 CVA Part 4.2  (BA-CVA reduced formula, DSBA-CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3  (SCVA_c formula, DF formula, alpha)
    - PS1/26 App.1 CVA Part 4.4  (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 Own Funds Part 4(b)  (x12.5 multiplier, page 15)
    - CRR Art. 274(2) (SA-CCR EAD = alpha * (RC + PFE))
    - src/rwa_calc/data/schemas.py (TRADE_SCHEMA, NETTING_SET_SCHEMA,
      COUNTERPARTY_SCHEMA, CVA_COUNTERPARTY_SCHEMA)
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
from tests.fixtures.raw_bundle import make_raw_bundle

from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import NettingSet, create_netting_sets
from tests.fixtures.ccr.trade_builder import Trade, create_trades, make_trade

# Import the fixed regulatory scalars from the CVA-A1 builder so the two
# pins can never drift.  All arithmetic constants (DS, rho, rate, alpha, RW,
# multiplier) are owned by CVA-A1; CVA-A2 reads them by name.
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_ALPHA,
    CVA_COUNTERPARTY_SCHEMA_DTYPES,
    CVA_DS_BA_CVA,
    CVA_RW_FINANCIALS_IG,
    CVA_RWEA_MULTIPLIER,
    CVA_SUPERVISORY_CORRELATION_RHO,
    CVA_SUPERVISORY_DISCOUNT_RATE,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CVA_A2_CP1_REF: str = "CP_CVA_A2_1"
CVA_A2_CP2_REF: str = "CP_CVA_A2_2"

CVA_A2_NS1_ID: str = "NS_CVA_A2_1"
CVA_A2_NS2_ID: str = "NS_CVA_A2_2"

CVA_A2_TRADE1_ID: str = "T_CVA_A2_1"
CVA_A2_TRADE2_ID: str = "T_CVA_A2_2"

# Trade economics: GBP vanilla IR swaps, both at-par, delta=1.0.
CVA_A2_NOTIONAL: float = 100_000_000.0   # GBP 100m (same for both trades)
CVA_A2_CURRENCY: str = "GBP"
CVA_A2_ASSET_CLASS: str = "interest_rate"
CVA_A2_TRANSACTION_TYPE: str = "derivative"
CVA_A2_MTM: float = 0.0
CVA_A2_DELTA: float = 1.0
CVA_A2_IS_LONG: bool = True
CVA_A2_START_DATE: _date = _date(2027, 1, 15)

# Trade 1: 3-year swap (M = 3.0 years).
CVA_A2_MATURITY_DATE_1: _date = _date(2030, 1, 15)

# Trade 2: 5-year swap (M = 5.0 years).
CVA_A2_MATURITY_DATE_2: _date = _date(2032, 1, 15)

CVA_A2_IS_LEGALLY_ENFORCEABLE: bool = True
CVA_A2_IS_MARGINED: bool = False

# Counterparty attributes: GB institutions, CQS 2.
CVA_A2_CP_ENTITY_TYPE: str = "institution"
CVA_A2_CP_COUNTRY_CODE: str = "GB"
CVA_A2_RATING_TYPE: str = "external"
CVA_A2_RATING_AGENCY: str = "S&P"
CVA_A2_RATING_VALUE: str = "A"     # S&P "A" = CQS 2
CVA_A2_RATING_CQS: int = 2
CVA_A2_RATING_DATE: _date = _date(2027, 1, 15)

# CVA counterparty attributes.
CVA_A2_CVA_RW_SECTOR: str = "FINANCIAL"   # Financials IG row in 4.4 table
CVA_A2_CVA_RW_RATING_BAND: str = "IG"
CVA_A2_CVA_EFFECTIVE_MATURITY_1: float = 3.0
CVA_A2_CVA_EFFECTIVE_MATURITY_2: float = 5.0
CVA_A2_CVA_IN_SCOPE: bool = True

# ---------------------------------------------------------------------------
# Confirmed DF values at the two maturities (for documentation / sanity check).
# DF_NS = (1 - e^(-rate * M)) / (rate * M), rate=0.05.
# ---------------------------------------------------------------------------
#   M=3: DF = 0.9286134905
#   M=5: DF = 0.8847905680
# ---------------------------------------------------------------------------


def compute_cva_a2_golden(ead1: float, ead2: float) -> dict[str, float]:
    """
    Compute the CVA-A2 golden values from confirmed EADs for the two netting sets.

    Implements the BA-CVA reduced-K formula for two counterparties.  The result
    strictly satisfies the diversification invariant:

        sqrt(scva_1² + scva_2²) < k_reduced < scva_1 + scva_2

    Uses regulatory scalars from the CVA-A1 builder (single source of truth).

    Args:
        ead1: Materialised EAD from the CCR pipeline for NS_CVA_A2_1 (3-year swap).
        ead2: Materialised EAD from the CCR pipeline for NS_CVA_A2_2 (5-year swap).

    Returns:
        Dict with keys:
            df1       -- supervisory discount factor for M=3.0
            df2       -- supervisory discount factor for M=5.0
            scva_1    -- SCVA for counterparty 1
            scva_2    -- SCVA for counterparty 2
            k_reduced -- diversified capital requirement
            ofr_cva   -- own-funds requirement = DSBA-CVA * K_reduced
            cva_rwa   -- RWEA = ofr_cva * 12.5

    References:
        - PS1/26 App.1 CVA Part 4.2 (K_reduced, DSBA-CVA=0.65, rho=50%)
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c, DF formula)
        - PS1/26 App.1 CVA Part 4.4 (RW_c Financials IG = 5%)
        - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    """
    rate = CVA_SUPERVISORY_DISCOUNT_RATE   # 0.05
    rho = CVA_SUPERVISORY_CORRELATION_RHO  # 0.50
    rw_c = CVA_RW_FINANCIALS_IG            # 0.05
    alpha = CVA_ALPHA                      # 1.4

    m1 = CVA_A2_CVA_EFFECTIVE_MATURITY_1  # 3.0
    m2 = CVA_A2_CVA_EFFECTIVE_MATURITY_2  # 5.0

    # DF_NS = (1 - e^(-rate * M)) / (rate * M)
    df1 = (1.0 - math.exp(-rate * m1)) / (rate * m1)
    df2 = (1.0 - math.exp(-rate * m2)) / (rate * m2)

    # SCVA_c = (1/alpha) * RW_c * M * EAD * DF
    scva_1 = (1.0 / alpha) * rw_c * m1 * ead1 * df1
    scva_2 = (1.0 / alpha) * rw_c * m2 * ead2 * df2

    # K_reduced (two-counterparty form):
    # sqrt[(rho * (SCVA_1 + SCVA_2))^2 + (1 - rho^2) * (SCVA_1^2 + SCVA_2^2)]
    systematic = (rho * (scva_1 + scva_2)) ** 2
    idiosyncratic = (1.0 - rho**2) * (scva_1**2 + scva_2**2)
    k_reduced = math.sqrt(systematic + idiosyncratic)

    # OFR_CVA = DSBA-CVA * K_reduced
    ofr_cva = CVA_DS_BA_CVA * k_reduced

    # RWEA_CVA = OFR_CVA * 12.5
    cva_rwa = ofr_cva * CVA_RWEA_MULTIPLIER

    return {
        "df1": df1,
        "df2": df2,
        "scva_1": scva_1,
        "scva_2": scva_2,
        "k_reduced": k_reduced,
        "ofr_cva": ofr_cva,
        "cva_rwa": cva_rwa,
    }


# ---------------------------------------------------------------------------
# CVA counterparty DataFrame builder.
# ---------------------------------------------------------------------------


def create_cva_a2_counterparty_frame() -> pl.DataFrame:
    """
    Return the two-row CVA counterparty input DataFrame for CVA-A2.

    Columns match CVA_COUNTERPARTY_SCHEMA:
        counterparty_reference       String   — FK to netting set's counterparty_reference
        cva_rw_sector                String   — "FINANCIAL"
        cva_rw_rating_band           String   — "IG"
        cva_effective_maturity_years Float64  — 3.0 (CP1) / 5.0 (CP2)
        cva_in_scope                 Boolean  — True for both

    Uses CVA_COUNTERPARTY_SCHEMA_DTYPES imported from the CVA-A1 builder to
    ensure column types are byte-identical to the CVA-A1 fixture.

    References:
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c inputs: M_NS, EAD_NS, DF_NS)
        - PS1/26 App.1 CVA Part 4.4 (sector / rating-band RW table)
    """
    rows: list[dict[str, object]] = [
        {
            "counterparty_reference": CVA_A2_CP1_REF,
            "cva_rw_sector": CVA_A2_CVA_RW_SECTOR,
            "cva_rw_rating_band": CVA_A2_CVA_RW_RATING_BAND,
            "cva_effective_maturity_years": CVA_A2_CVA_EFFECTIVE_MATURITY_1,
            "cva_in_scope": CVA_A2_CVA_IN_SCOPE,
        },
        {
            "counterparty_reference": CVA_A2_CP2_REF,
            "cva_rw_sector": CVA_A2_CVA_RW_SECTOR,
            "cva_rw_rating_band": CVA_A2_CVA_RW_RATING_BAND,
            "cva_effective_maturity_years": CVA_A2_CVA_EFFECTIVE_MATURITY_2,
            "cva_in_scope": CVA_A2_CVA_IN_SCOPE,
        },
    ]
    return pl.DataFrame(rows, schema=CVA_COUNTERPARTY_SCHEMA_DTYPES)


# ---------------------------------------------------------------------------
# CCR domain builders.
# ---------------------------------------------------------------------------


def _cva_a2_trade1() -> Trade:
    """Return the 3-year GBP IR swap for CP_CVA_A2_1."""
    return make_trade(
        trade_id=CVA_A2_TRADE1_ID,
        netting_set_id=CVA_A2_NS1_ID,
        asset_class=CVA_A2_ASSET_CLASS,
        transaction_type=CVA_A2_TRANSACTION_TYPE,
        notional=CVA_A2_NOTIONAL,
        currency=CVA_A2_CURRENCY,
        maturity_date=CVA_A2_MATURITY_DATE_1,
        start_date=CVA_A2_START_DATE,
        delta=CVA_A2_DELTA,
        is_long=CVA_A2_IS_LONG,
        mtm_value=CVA_A2_MTM,
    )


def _cva_a2_trade2() -> Trade:
    """Return the 5-year GBP IR swap for CP_CVA_A2_2."""
    return make_trade(
        trade_id=CVA_A2_TRADE2_ID,
        netting_set_id=CVA_A2_NS2_ID,
        asset_class=CVA_A2_ASSET_CLASS,
        transaction_type=CVA_A2_TRANSACTION_TYPE,
        notional=CVA_A2_NOTIONAL,
        currency=CVA_A2_CURRENCY,
        maturity_date=CVA_A2_MATURITY_DATE_2,
        start_date=CVA_A2_START_DATE,
        delta=CVA_A2_DELTA,
        is_long=CVA_A2_IS_LONG,
        mtm_value=CVA_A2_MTM,
    )


def _cva_a2_netting_set1() -> NettingSet:
    """Return the netting set for CP_CVA_A2_1 (3-year trade)."""
    return NettingSet(
        netting_set_id=CVA_A2_NS1_ID,
        counterparty_reference=CVA_A2_CP1_REF,
        is_legally_enforceable=CVA_A2_IS_LEGALLY_ENFORCEABLE,
        is_margined=CVA_A2_IS_MARGINED,
    )


def _cva_a2_netting_set2() -> NettingSet:
    """Return the netting set for CP_CVA_A2_2 (5-year trade)."""
    return NettingSet(
        netting_set_id=CVA_A2_NS2_ID,
        counterparty_reference=CVA_A2_CP2_REF,
        is_legally_enforceable=CVA_A2_IS_LEGALLY_ENFORCEABLE,
        is_margined=CVA_A2_IS_MARGINED,
    )


def create_cva_a2_trades() -> pl.DataFrame:
    """Return the two-row trades DataFrame for CVA-A2."""
    return create_trades([_cva_a2_trade1(), _cva_a2_trade2()])


def create_cva_a2_netting_sets() -> pl.DataFrame:
    """Return the two-row netting-sets DataFrame for CVA-A2."""
    return create_netting_sets([_cva_a2_netting_set1(), _cva_a2_netting_set2()])


def create_cva_a2_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CVA-A2: no CSA)."""
    return create_margin_agreements([])


def create_cva_a2_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CVA-A2: no CCR collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Portfolio-stub builders (for full RawDataBundle assembly).
# ---------------------------------------------------------------------------


def _build_cva_cp_counterparty(
    cp_ref: str,
    name: str,
    rating_cqs: int,
) -> pl.DataFrame:
    """
    Return a one-row counterparty DataFrame for the given CP reference.

    Both CVA-A2 counterparties are GB institutions, CQS 2, apply_fi_scalar=False,
    default_status=False — mirrors the _build_cva_cp_counterparty pattern from
    the CVA-A1 builder.
    """
    row: dict[str, object] = {
        "counterparty_reference": cp_ref,
        "counterparty_name": name,
        "entity_type": CVA_A2_CP_ENTITY_TYPE,
        "country_code": CVA_A2_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": rating_cqs,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def _build_cva_cp_rating(cp_ref: str, rating_ref: str) -> pl.DataFrame:
    """
    Return a one-row external ratings DataFrame for the given CP reference.

    S&P "A" = CQS 2 under CRR ECRA for institutions.  Maps to "Financials IG"
    in the CVA Part 4.4 RW table (RW_c = 5.0%).
    """
    row: dict[str, object] = {
        "rating_reference": rating_ref,
        "counterparty_reference": cp_ref,
        "rating_type": CVA_A2_RATING_TYPE,
        "rating_agency": CVA_A2_RATING_AGENCY,
        "rating_value": CVA_A2_RATING_VALUE,
        "cqs": CVA_A2_RATING_CQS,
        "pd": None,
        "rating_date": CVA_A2_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA))


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


def _build_cva_a2_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CVA-A2.

    Composition:
        trades           — 2 rows (T_CVA_A2_1 3y, T_CVA_A2_2 5y, each in own NS)
        netting_sets     — 2 rows (NS_CVA_A2_1 → CP1, NS_CVA_A2_2 → CP2)
        margin_agreements — 0 rows (no CSA)
        ccr_collateral   — 0 rows (no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_cva_a2_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_cva_a2_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_cva_a2_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_cva_a2_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_cva_a2() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for the CVA-A2 scenario.

    Key responsibilities:
    - Provides CP_CVA_A2_1 and CP_CVA_A2_2 as GB institution counterparties
      (CQS 2) so the Classifier routes the CCR-derived synthetic exposures
      through SA-Institution.
    - Provides matching external ratings (CQS 2, S&P "A") for both CPs so the
      full rating-inheritance pipeline resolves external_cqs correctly.
    - Zero-row facility / loan / contingent / mapping frames — only CCR-derived
      synthetic rows appear in the pipeline.
    - ccr is populated with two GBP IR swaps in separate netting sets.

    The acceptance test must:
    1. Run this bundle through the CCR pipeline to materialise ead1 (NS_CVA_A2_1)
       and ead2 (NS_CVA_A2_2).
    2. Feed (ead1, ead2, cva_counterparty_frame) to the CVA engine.
    3. Assert cva_rwa matches compute_cva_a2_golden(ead1, ead2)["cva_rwa"].
    4. Assert the diversification invariant:
           sqrt(scva_1^2 + scva_2^2) < k_reduced < scva_1 + scva_2

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced)
        - CRR Art. 274(2) (SA-CCR EAD for CCR step)
    """
    # Build combined counterparty and ratings frames for the two CPs.
    cp1_df = _build_cva_cp_counterparty(
        CVA_A2_CP1_REF,
        "CVA-A2 CP1 Financial Institution (CQS 2, 3y)",
        CVA_A2_RATING_CQS,
    )
    cp2_df = _build_cva_cp_counterparty(
        CVA_A2_CP2_REF,
        "CVA-A2 CP2 Financial Institution (CQS 2, 5y)",
        CVA_A2_RATING_CQS,
    )
    counterparties_lf = pl.concat([cp1_df, cp2_df]).lazy()

    rating1_df = _build_cva_cp_rating(CVA_A2_CP1_REF, "RTG_CVA_A2_CP1")
    rating2_df = _build_cva_cp_rating(CVA_A2_CP2_REF, "RTG_CVA_A2_CP2")
    ratings_lf = pl.concat([rating1_df, rating2_df]).lazy()

    return make_raw_bundle(
        counterparties=counterparties_lf,
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=ratings_lf,
        ccr=_build_cva_a2_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Parquet save helpers.
# ---------------------------------------------------------------------------


def save_cva_a2_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CVA-A2 parquet files to output_dir.

    Files produced:
        cva_a2_trades.parquet              — 2 rows (T_CVA_A2_1 3y, T_CVA_A2_2 5y)
        cva_a2_netting_sets.parquet        — 2 rows (NS_CVA_A2_1 / NS_CVA_A2_2)
        cva_a2_margin_agreements.parquet   — 0 rows
        cva_a2_ccr_collateral.parquet      — 0 rows
        cva_a2_cva_counterparties.parquet  — 2 rows (CP1 M=3.0, CP2 M=5.0)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/p8_46/``).

    Returns:
        Dict mapping artefact name to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("cva_a2_trades", create_cva_a2_trades()),
        ("cva_a2_netting_sets", create_cva_a2_netting_sets()),
        ("cva_a2_margin_agreements", create_cva_a2_margin_agreements()),
        ("cva_a2_ccr_collateral", create_cva_a2_collateral()),
        ("cva_a2_cva_counterparties", create_cva_a2_counterparty_frame()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


@dataclass
class CvaA2Inputs:
    """
    Named fixture bundle for the CVA-A2 acceptance test.

    Attributes:
        raw_data_bundle: Complete RawDataBundle for the CCR pipeline.
        cva_counterparty_frame: Two-row CVA counterparty input DataFrame.
        cp1_ref: Reference key for counterparty 1 (3-year swap).
        cp2_ref: Reference key for counterparty 2 (5-year swap).
        ns1_id: Netting set identifier for counterparty 1.
        ns2_id: Netting set identifier for counterparty 2.
    """

    raw_data_bundle: RawDataBundle
    cva_counterparty_frame: pl.DataFrame
    cp1_ref: str
    cp2_ref: str
    ns1_id: str
    ns2_id: str


def build_cva_a2_inputs() -> CvaA2Inputs:
    """
    Return the named bundle the acceptance test feeds the pipeline.

    Usage in acceptance test::

        from tests.fixtures.p8_46.cva_a2_builder import (
            build_cva_a2_inputs,
            compute_cva_a2_golden,
        )

        inputs = build_cva_a2_inputs()
        # Run CCR pipeline to get ead1 (NS_CVA_A2_1) and ead2 (NS_CVA_A2_2) ...
        golden = compute_cva_a2_golden(ead1, ead2)
        assert abs(result.cva_rwa - golden["cva_rwa"]) < 1.0
        # Diversification invariant
        low = math.sqrt(golden["scva_1"]**2 + golden["scva_2"]**2)
        high = golden["scva_1"] + golden["scva_2"]
        assert low < golden["k_reduced"] < high
    """
    return CvaA2Inputs(
        raw_data_bundle=build_raw_data_bundle_cva_a2(),
        cva_counterparty_frame=create_cva_a2_counterparty_frame(),
        cp1_ref=CVA_A2_CP1_REF,
        cp2_ref=CVA_A2_CP2_REF,
        ns1_id=CVA_A2_NS1_ID,
        ns2_id=CVA_A2_NS2_ID,
    )


def save_p846_fixtures(output_dir: Path | None = None) -> list[tuple[str, int]]:
    """
    Smoke-check the CVA-A2 bundle and persist parquet files to output_dir.

    Invariants checked:
        1.  RawCCRBundle is present and non-None.
        2.  Trades frame has exactly 2 rows with correct trade IDs and maturities.
        3.  Netting-sets frame has 2 rows, both legally enforceable, unmargined.
        4.  Margin-agreements frame has 0 rows.
        5.  CCR-collateral frame has 0 rows.
        6.  CVA counterparty frame has 2 rows with correct column values.
        7.  Counterparty frame has 2 rows with entity_type=institution, CQS 2.
        8.  Ratings frame has 2 rows, both CQS 2, S&P "A", solicited.
        9.  compute_cva_a2_golden returns self-consistent values for illustrative EADs.
        10. Diversification invariant strictly holds (k_reduced strictly between
            the per-CP sum and the Euclidean norm) for positive EADs.

    Returns:
        List of (filename, row_count) tuples for the master report.
    """
    saved = save_cva_a2_fixtures(output_dir)

    inputs = build_cva_a2_inputs()
    bundle = inputs.raw_data_bundle

    # Invariant 1: CCR bundle present.
    if bundle.ccr is None:
        raise AssertionError("CVA-A2: bundle.ccr must not be None")

    # Invariant 2: trades frame.
    trades_df = bundle.ccr.trades.trades.collect()
    if len(trades_df) != 2:
        raise AssertionError(f"CVA-A2: expected 2 trade rows, got {len(trades_df)}")
    trade_ids = set(trades_df["trade_id"].to_list())
    if trade_ids != {CVA_A2_TRADE1_ID, CVA_A2_TRADE2_ID}:
        raise AssertionError(f"CVA-A2: trade IDs {trade_ids!r} mismatch")
    maturity_dates = set(trades_df["maturity_date"].to_list())
    if maturity_dates != {CVA_A2_MATURITY_DATE_1, CVA_A2_MATURITY_DATE_2}:
        raise AssertionError(f"CVA-A2: maturity dates {maturity_dates!r} mismatch")

    # Invariant 3: netting-sets frame.
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    if len(ns_df) != 2:
        raise AssertionError(f"CVA-A2: expected 2 NS rows, got {len(ns_df)}")
    if not ns_df["is_legally_enforceable"].all():
        raise AssertionError("CVA-A2: all netting sets must be legally enforceable")
    if ns_df["is_margined"].any():
        raise AssertionError("CVA-A2: all netting sets must be unmargined")

    # Invariant 4: margin-agreements frame.
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    if len(margin_df) != 0:
        raise AssertionError(f"CVA-A2: expected 0 margin rows, got {len(margin_df)}")

    # Invariant 5: CCR-collateral frame.
    collateral_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    if len(collateral_df) != 0:
        raise AssertionError(f"CVA-A2: expected 0 collateral rows, got {len(collateral_df)}")

    # Invariant 6: CVA counterparty frame.
    cva_cp = inputs.cva_counterparty_frame
    if len(cva_cp) != 2:
        raise AssertionError(f"CVA-A2: expected 2 CVA CP rows, got {len(cva_cp)}")
    cp_refs_cva = set(cva_cp["counterparty_reference"].to_list())
    if cp_refs_cva != {CVA_A2_CP1_REF, CVA_A2_CP2_REF}:
        raise AssertionError(f"CVA-A2: CVA CP counterparty_references {cp_refs_cva!r} mismatch")
    if not cva_cp["cva_in_scope"].all():
        raise AssertionError("CVA-A2: cva_in_scope must be True for both CPs")
    sectors = set(cva_cp["cva_rw_sector"].to_list())
    if sectors != {CVA_A2_CVA_RW_SECTOR}:
        raise AssertionError(f"CVA-A2: cva_rw_sector must be {CVA_A2_CVA_RW_SECTOR!r} for all CPs")
    bands = set(cva_cp["cva_rw_rating_band"].to_list())
    if bands != {CVA_A2_CVA_RW_RATING_BAND}:
        raise AssertionError(
            f"CVA-A2: cva_rw_rating_band must be {CVA_A2_CVA_RW_RATING_BAND!r} for all CPs"
        )
    maturities = set(cva_cp["cva_effective_maturity_years"].to_list())
    if maturities != {CVA_A2_CVA_EFFECTIVE_MATURITY_1, CVA_A2_CVA_EFFECTIVE_MATURITY_2}:
        raise AssertionError(f"CVA-A2: CVA effective maturities {maturities!r} mismatch")

    # Invariant 7: counterparty frame.
    cp_df = bundle.counterparties.collect()
    if len(cp_df) != 2:
        raise AssertionError(f"CVA-A2: expected 2 CP rows, got {len(cp_df)}")
    entity_types = set(cp_df["entity_type"].to_list())
    if entity_types != {CVA_A2_CP_ENTITY_TYPE}:
        raise AssertionError(f"CVA-A2: entity_type must be {CVA_A2_CP_ENTITY_TYPE!r} for all CPs")

    # Invariant 8: ratings frame.
    if bundle.ratings is None:
        raise AssertionError("CVA-A2: bundle.ratings must not be None")
    rating_df = bundle.ratings.collect()
    if len(rating_df) != 2:
        raise AssertionError(f"CVA-A2: expected 2 rating rows, got {len(rating_df)}")
    if not all(cqs == CVA_A2_RATING_CQS for cqs in rating_df["cqs"].to_list()):
        raise AssertionError(f"CVA-A2: all CQS must be {CVA_A2_RATING_CQS}")

    # Invariant 9: golden computation self-consistent.
    test_ead1 = 5_480_000.0  # illustrative 3y EAD
    test_ead2 = 8_000_000.0  # illustrative 5y EAD
    golden = compute_cva_a2_golden(test_ead1, test_ead2)

    for key in ("df1", "df2"):
        val = golden[key]
        if not (0.0 < val <= 1.0):
            raise AssertionError(f"CVA-A2: {key}={val} must be in (0,1]")
    if golden["scva_1"] <= 0:
        raise AssertionError(f"CVA-A2: scva_1 must be positive, got {golden['scva_1']}")
    if golden["scva_2"] <= 0:
        raise AssertionError(f"CVA-A2: scva_2 must be positive, got {golden['scva_2']}")

    # Invariant 10: diversification invariant strictly holds.
    low = math.sqrt(golden["scva_1"] ** 2 + golden["scva_2"] ** 2)
    high = golden["scva_1"] + golden["scva_2"]
    k_red = golden["k_reduced"]
    if not (low < k_red < high):
        raise AssertionError(
            f"CVA-A2: diversification invariant violated: "
            f"sqrt(SCVA^2)={low:.6f} < K_reduced={k_red:.6f} < sum(SCVA)={high:.6f}"
        )

    return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]


def main() -> None:
    """Entry point for standalone fixture generation and verification."""
    import sys

    saved = save_cva_a2_fixtures()
    print("CVA-A2 fixture generation complete (P8.46)")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<40} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)

    # Verify bundle constructs cleanly.
    inputs = build_cva_a2_inputs()
    ccr = inputs.raw_data_bundle.ccr
    assert ccr is not None, "RawCCRBundle must be present"
    trades = ccr.trades.trades.collect()
    ns = ccr.netting_sets.netting_sets.collect()
    print(f"  Trades:       {trades['trade_id'].to_list()}")
    print(f"  Maturities:   {trades['maturity_date'].to_list()}")
    print(f"  NS -> CP:     {list(zip(ns['netting_set_id'].to_list(), ns['counterparty_reference'].to_list()))}")
    print(f"  CVA CP frame: {len(inputs.cva_counterparty_frame)} row(s)")

    # Demonstrate the golden computation with illustrative EADs.
    ead1 = 5_480_000.0
    ead2 = 8_000_000.0
    golden = compute_cva_a2_golden(ead1, ead2)

    print()
    print(f"Illustrative golden (EAD1={ead1:,.0f}, EAD2={ead2:,.0f}):")
    print(f"  DF1       = {golden['df1']:.10f}  (M=3.0)")
    print(f"  DF2       = {golden['df2']:.10f}  (M=5.0)")
    print(f"  SCVA_1    = {golden['scva_1']:.4f}")
    print(f"  SCVA_2    = {golden['scva_2']:.4f}")
    print(f"  K_reduced = {golden['k_reduced']:.4f}")
    print(f"  OFR_CVA   = {golden['ofr_cva']:.4f}  (= 0.65 * K_reduced)")
    print(f"  CVA_RWA   = {golden['cva_rwa']:.4f}  (= OFR_CVA * 12.5)")

    low = math.sqrt(golden["scva_1"] ** 2 + golden["scva_2"] ** 2)
    high = golden["scva_1"] + golden["scva_2"]
    print()
    print("Diversification invariant:")
    print(f"  sqrt(SCVA_1^2+SCVA_2^2) = {low:.4f}")
    print(f"  K_reduced               = {golden['k_reduced']:.4f}")
    print(f"  SCVA_1+SCVA_2           = {high:.4f}")
    assert low < golden["k_reduced"] < high, "Diversification invariant violated"
    print("  PASSED: sqrt(SCVA^2) < K_reduced < sum(SCVA)")

    sys.exit(0)


if __name__ == "__main__":
    main()
