"""
P8.46 / CVA-A3 fixture builder: BA-CVA reduced-K one-counterparty / two-netting-set SCVA aggregation.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_ba_cva_a3.py)
    -> engine-implementer (engine/cva/ba_cva.py::compute_ba_cva_rwa)

Scenario design:
    ONE counterparty CP_CVA_A3, TWO netting sets NS_CVA_A3_1 / NS_CVA_A3_2, each
    with a GBP vanilla IR swap at a different tenor (3-year vs 5-year).  Both NS
    carry the SAME counterparty_reference — this is the structural crux of A3.

    CVA-A1 had one CP / one NS (trivial sum).
    CVA-A2 had two CPs / one NS each (inter-CP ρ cross-term).
    CVA-A3 isolates the INNER SUM_NS: one CP whose SCVA_c is the sum of per-NS
    contributions.  Because n=1 (single CP), the portfolio K collapses:

        K_reduced = sqrt[(ρ·SCVA_c)² + (1−ρ²)·SCVA_c²] = SCVA_c

    The engine join is keyed by counterparty_reference, so both NS rows inherit
    M=4.0 and DF from the single CVA-counterparty row.

    EAD_NS1 != EAD_NS2 (different tenors → different SA-CCR adjusted notionals).

Source-verified (ps126app1.pdf — effective from 1 January 2027):
    - DSBA-CVA = 0.65                             [page 399, section 4.2]
    - rho = 50%                                   [page 399, section 4.2]
    - DF_NS = (1 - e^(-0.05*M)) / (0.05*M)       [page 400, section 4.3]
    - rate = 0.05 (supervisory discount rate)      [page 400, section 4.3]
    - alpha = 1.4 (from CCR Part, Art. 274)       [page 400, section 4.3]
    - RW_c (Financials IG) = 5.0%                 [page 401, section 4.4 table]
    - RWEA = OFR_CVA x 12.5 (Art. 92(4)(b))      [page 15, section 4]

SCVA_c formula (one counterparty, two NS):
    SCVA_c = (1/alpha) * RW_c * M * DF * (EAD_NS1 + EAD_NS2)
           = SCVA_NS1 + SCVA_NS2            (additivity invariant)

K_reduced formula (single counterparty, n=1):
    K_reduced = sqrt[(rho * SCVA_c)^2 + (1 - rho^2) * SCVA_c^2]
              = SCVA_c * sqrt[rho^2 + 1 - rho^2]
              = SCVA_c                      (identity invariant)

References:
    - PS1/26 App.1 CVA Part 4.2  (BA-CVA reduced formula, DSBA-CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3  (SCVA_c formula, DF_NS formula, alpha, SUM_NS)
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

# Import the fixed regulatory scalars from the CVA-A1 builder so the three
# scenario pins can never drift.  All arithmetic constants (DS, rho, rate, alpha,
# RW, multiplier) are owned by CVA-A1; CVA-A3 reads them by name.
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_ALPHA,
    CVA_COUNTERPARTY_SCHEMA_DTYPES,
    CVA_DS_BA_CVA,
    CVA_RW_FINANCIALS_IG,
    CVA_RWEA_MULTIPLIER,
    CVA_SUPERVISORY_DISCOUNT_RATE,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CVA_A3_CP_REF: str = "CP_CVA_A3"   # ONE counterparty for both netting sets

CVA_A3_NS1_ID: str = "NS_CVA_A3_1"
CVA_A3_NS2_ID: str = "NS_CVA_A3_2"

CVA_A3_TRADE1_ID: str = "T_CVA_A3_1"
CVA_A3_TRADE2_ID: str = "T_CVA_A3_2"

# Trade economics: GBP vanilla IR swaps, both at-par, delta=1.0.
CVA_A3_NOTIONAL: float = 100_000_000.0   # GBP 100m (same for both trades)
CVA_A3_CURRENCY: str = "GBP"
CVA_A3_ASSET_CLASS: str = "interest_rate"
CVA_A3_TRANSACTION_TYPE: str = "derivative"
CVA_A3_MTM: float = 0.0
CVA_A3_DELTA: float = 1.0
CVA_A3_IS_LONG: bool = True
CVA_A3_START_DATE: _date = _date(2027, 1, 15)

# Trade 1: 3-year swap (maturity 2030-01-15).
CVA_A3_MATURITY_DATE_1: _date = _date(2030, 1, 15)

# Trade 2: 5-year swap (maturity 2032-01-15).  Different tenor => EAD_NS1 != EAD_NS2.
CVA_A3_MATURITY_DATE_2: _date = _date(2032, 1, 15)

CVA_A3_IS_LEGALLY_ENFORCEABLE: bool = True
CVA_A3_IS_MARGINED: bool = False

# Counterparty attributes: GB institution, CQS 2.
CVA_A3_CP_ENTITY_TYPE: str = "institution"
CVA_A3_CP_COUNTRY_CODE: str = "GB"
CVA_A3_RATING_TYPE: str = "external"
CVA_A3_RATING_AGENCY: str = "S&P"
CVA_A3_RATING_VALUE: str = "A"     # S&P "A" = CQS 2
CVA_A3_RATING_CQS: int = 2
CVA_A3_RATING_DATE: _date = _date(2027, 1, 15)

# CVA counterparty attributes — ONE row, shared M=4.0 applied to BOTH NS.
CVA_A3_CVA_RW_SECTOR: str = "FINANCIAL"   # Financials IG row in 4.4 table
CVA_A3_CVA_RW_RATING_BAND: str = "IG"
CVA_A3_CVA_EFFECTIVE_MATURITY: float = 4.0   # shared M; both NS inherit this
CVA_A3_CVA_IN_SCOPE: bool = True

# ---------------------------------------------------------------------------
# Confirmed DF value at M=4.0 (for documentation / sanity check).
# DF_NS = (1 - e^(-rate * M)) / (rate * M), rate=0.05.
#   M=4: DF = (1 - e^(-0.20)) / 0.20 = 0.906346234...
# ---------------------------------------------------------------------------


def compute_cva_a3_golden(ead_ns1: float, ead_ns2: float) -> dict[str, float]:
    """
    Compute the CVA-A3 golden values from confirmed EADs for the two netting sets.

    Implements the BA-CVA reduced-K formula for one counterparty with two netting
    sets.  The per-NS SCVA contributions are additive (shared M and DF), and the
    single-CP K collapse produces:

        K_reduced = SCVA_c  (exactly, by algebraic identity for n=1)

    Structural invariants:
        1. scva_c == scva_ns1 + scva_ns2   (cross-NS additivity)
        2. k_reduced == scva_c              (single-CP K collapse)
        3. scva_ns1 / scva_ns2 == ead_ns1 / ead_ns2  (shared M*DF => EAD ratio preserved)

    Uses regulatory scalars from the CVA-A1 builder (single source of truth).

    Args:
        ead_ns1: Materialised EAD from the CCR pipeline for NS_CVA_A3_1 (3-year swap).
        ead_ns2: Materialised EAD from the CCR pipeline for NS_CVA_A3_2 (5-year swap).

    Returns:
        Dict with keys:
            df_ns     -- supervisory discount factor for M=4.0 (shared by both NS)
            scva_ns1  -- SCVA contribution from NS_CVA_A3_1
            scva_ns2  -- SCVA contribution from NS_CVA_A3_2
            scva_c    -- total SCVA for counterparty CP_CVA_A3 (= scva_ns1 + scva_ns2)
            k_reduced -- diversified capital requirement (= scva_c for n=1)
            ofr_cva   -- own-funds requirement = DSBA-CVA * K_reduced
            cva_rwa   -- RWEA = ofr_cva * 12.5

    References:
        - PS1/26 App.1 CVA Part 4.2 (K_reduced single-CP collapse, DSBA-CVA=0.65)
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c = (1/alpha)*RW_c*SUM_NS[M*EAD*DF])
        - PS1/26 App.1 CVA Part 4.4 (RW_c Financials IG = 5%)
        - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    """
    rate = CVA_SUPERVISORY_DISCOUNT_RATE   # 0.05
    rw_c = CVA_RW_FINANCIALS_IG            # 0.05
    alpha = CVA_ALPHA                      # 1.4
    m = CVA_A3_CVA_EFFECTIVE_MATURITY     # 4.0 — shared by both NS

    # DF_NS = (1 - e^(-rate * M)) / (rate * M)
    df_ns = (1.0 - math.exp(-rate * m)) / (rate * m)

    # Per-NS SCVA contributions: (1/alpha) * RW_c * M * EAD_NS * DF_NS
    scva_ns1 = (1.0 / alpha) * rw_c * m * ead_ns1 * df_ns
    scva_ns2 = (1.0 / alpha) * rw_c * m * ead_ns2 * df_ns

    # SCVA_c = sum of per-NS terms (additivity invariant)
    scva_c = scva_ns1 + scva_ns2

    # K_reduced — single-CP collapse (n=1 identity):
    # sqrt[(rho*SCVA_c)^2 + (1-rho^2)*SCVA_c^2] = SCVA_c
    k_reduced = scva_c

    # OFR_CVA = DSBA-CVA * K_reduced
    ofr_cva = CVA_DS_BA_CVA * k_reduced

    # RWEA_CVA = OFR_CVA * 12.5
    cva_rwa = ofr_cva * CVA_RWEA_MULTIPLIER

    return {
        "df_ns": df_ns,
        "scva_ns1": scva_ns1,
        "scva_ns2": scva_ns2,
        "scva_c": scva_c,
        "k_reduced": k_reduced,
        "ofr_cva": ofr_cva,
        "cva_rwa": cva_rwa,
    }


# ---------------------------------------------------------------------------
# CVA counterparty DataFrame builder.
# ---------------------------------------------------------------------------


def create_cva_a3_counterparty_frame() -> pl.DataFrame:
    """
    Return the ONE-row CVA counterparty input DataFrame for CVA-A3.

    LOAD-BEARING: exactly ONE row keyed by CP_CVA_A3.  The engine joins M and
    RW_c by counterparty_reference, so both NS_CVA_A3_1 and NS_CVA_A3_2 inherit
    M=4.0 and RW_c=5.0%.

    Columns match CVA_COUNTERPARTY_SCHEMA:
        counterparty_reference       String   — FK to both netting set rows
        cva_rw_sector                String   — "FINANCIAL"
        cva_rw_rating_band           String   — "IG"
        cva_effective_maturity_years Float64  — 4.0 (applied to both NS)
        cva_in_scope                 Boolean  — True

    Uses CVA_COUNTERPARTY_SCHEMA_DTYPES imported from the CVA-A1 builder to
    ensure column types are byte-identical to the CVA-A1 / CVA-A2 fixtures.

    References:
        - PS1/26 App.1 CVA Part 4.3 (SCVA_c inputs: M_NS, EAD_NS, DF_NS; engine
          applies M_NS from the counterparty row to every NS row via join)
        - PS1/26 App.1 CVA Part 4.4 (sector / rating-band RW table)
    """
    rows: list[dict[str, object]] = [
        {
            "counterparty_reference": CVA_A3_CP_REF,
            "cva_rw_sector": CVA_A3_CVA_RW_SECTOR,
            "cva_rw_rating_band": CVA_A3_CVA_RW_RATING_BAND,
            "cva_effective_maturity_years": CVA_A3_CVA_EFFECTIVE_MATURITY,
            "cva_in_scope": CVA_A3_CVA_IN_SCOPE,
        },
    ]
    return pl.DataFrame(rows, schema=CVA_COUNTERPARTY_SCHEMA_DTYPES)


# ---------------------------------------------------------------------------
# CCR domain builders.
# ---------------------------------------------------------------------------


def _cva_a3_trade1() -> Trade:
    """Return the 3-year GBP IR swap in NS_CVA_A3_1."""
    return make_trade(
        trade_id=CVA_A3_TRADE1_ID,
        netting_set_id=CVA_A3_NS1_ID,
        asset_class=CVA_A3_ASSET_CLASS,
        transaction_type=CVA_A3_TRANSACTION_TYPE,
        notional=CVA_A3_NOTIONAL,
        currency=CVA_A3_CURRENCY,
        maturity_date=CVA_A3_MATURITY_DATE_1,
        start_date=CVA_A3_START_DATE,
        delta=CVA_A3_DELTA,
        is_long=CVA_A3_IS_LONG,
        mtm_value=CVA_A3_MTM,
    )


def _cva_a3_trade2() -> Trade:
    """Return the 5-year GBP IR swap in NS_CVA_A3_2."""
    return make_trade(
        trade_id=CVA_A3_TRADE2_ID,
        netting_set_id=CVA_A3_NS2_ID,
        asset_class=CVA_A3_ASSET_CLASS,
        transaction_type=CVA_A3_TRANSACTION_TYPE,
        notional=CVA_A3_NOTIONAL,
        currency=CVA_A3_CURRENCY,
        maturity_date=CVA_A3_MATURITY_DATE_2,
        start_date=CVA_A3_START_DATE,
        delta=CVA_A3_DELTA,
        is_long=CVA_A3_IS_LONG,
        mtm_value=CVA_A3_MTM,
    )


def _cva_a3_netting_set1() -> NettingSet:
    """Return NS_CVA_A3_1 — linked to CP_CVA_A3 (3-year trade)."""
    return NettingSet(
        netting_set_id=CVA_A3_NS1_ID,
        counterparty_reference=CVA_A3_CP_REF,
        is_legally_enforceable=CVA_A3_IS_LEGALLY_ENFORCEABLE,
        is_margined=CVA_A3_IS_MARGINED,
    )


def _cva_a3_netting_set2() -> NettingSet:
    """Return NS_CVA_A3_2 — linked to CP_CVA_A3 (5-year trade). Same CP as NS1."""
    return NettingSet(
        netting_set_id=CVA_A3_NS2_ID,
        counterparty_reference=CVA_A3_CP_REF,
        is_legally_enforceable=CVA_A3_IS_LEGALLY_ENFORCEABLE,
        is_margined=CVA_A3_IS_MARGINED,
    )


def create_cva_a3_trades() -> pl.DataFrame:
    """Return the two-row trades DataFrame for CVA-A3."""
    return create_trades([_cva_a3_trade1(), _cva_a3_trade2()])


def create_cva_a3_netting_sets() -> pl.DataFrame:
    """Return the two-row netting-sets DataFrame for CVA-A3 (both linked to CP_CVA_A3)."""
    return create_netting_sets([_cva_a3_netting_set1(), _cva_a3_netting_set2()])


def create_cva_a3_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CVA-A3: no CSA)."""
    return create_margin_agreements([])


def create_cva_a3_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CVA-A3: no CCR collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Portfolio-stub builders (for full RawDataBundle assembly).
# ---------------------------------------------------------------------------


def _build_cva_a3_counterparty() -> pl.DataFrame:
    """
    Return a one-row counterparty DataFrame for CP_CVA_A3.

    CP_CVA_A3 is a GB institution, CQS 2, apply_fi_scalar=False,
    default_status=False — mirrors the pattern from the CVA-A1/A2 builders.
    """
    row: dict[str, object] = {
        "counterparty_reference": CVA_A3_CP_REF,
        "counterparty_name": "CVA-A3 Financial Institution (CQS 2, two-NS)",
        "entity_type": CVA_A3_CP_ENTITY_TYPE,
        "country_code": CVA_A3_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CVA_A3_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def _build_cva_a3_rating() -> pl.DataFrame:
    """
    Return a one-row external ratings DataFrame for CP_CVA_A3.

    S&P "A" = CQS 2 under CRR ECRA for institutions.  Maps to "Financials IG"
    in the CVA Part 4.4 RW table (RW_c = 5.0%).
    """
    row: dict[str, object] = {
        "rating_reference": "RTG_CVA_A3_CP",
        "counterparty_reference": CVA_A3_CP_REF,
        "rating_type": CVA_A3_RATING_TYPE,
        "rating_agency": CVA_A3_RATING_AGENCY,
        "rating_value": CVA_A3_RATING_VALUE,
        "cqs": CVA_A3_RATING_CQS,
        "pd": None,
        "rating_date": CVA_A3_RATING_DATE,
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


def _build_cva_a3_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CVA-A3.

    Composition:
        trades            — 2 rows (T_CVA_A3_1 3y in NS1, T_CVA_A3_2 5y in NS2)
        netting_sets      — 2 rows (NS_CVA_A3_1 → CP_CVA_A3, NS_CVA_A3_2 → CP_CVA_A3)
        margin_agreements — 0 rows (no CSA)
        ccr_collateral    — 0 rows (no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_cva_a3_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_cva_a3_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_cva_a3_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_cva_a3_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_cva_a3() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for the CVA-A3 scenario.

    Key responsibilities:
    - Provides CP_CVA_A3 as a GB institution counterparty (CQS 2) so the
      Classifier routes CCR-derived synthetic exposures through SA-Institution.
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves external_cqs correctly.
    - Zero-row facility / loan / contingent / mapping frames — only CCR-derived
      synthetic rows appear in the pipeline.
    - ccr bundle contains two GBP IR swaps in two netting sets, BOTH linked to
      the same counterparty_reference = CP_CVA_A3.

    The acceptance test must:
    1. Attach cva_counterparties (one-row frame from create_cva_a3_counterparty_frame)
       to the bundle via dataclasses.replace before running the pipeline.
    2. Run the full pipeline (Basel 3.1 config) to materialise ead_ns1 (NS_CVA_A3_1)
       and ead_ns2 (NS_CVA_A3_2) from result.results.
    3. Feed (ead_ns1, ead_ns2) to compute_cva_a3_golden.
    4. Assert cva_rwa matches golden["cva_rwa"] (rel=1e-6).
    5. Assert the structural invariants:
           golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"], rel=1e-9)
           golden["k_reduced"] == approx(golden["scva_c"], rel=1e-9)

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced)
        - CRR Art. 274(2) (SA-CCR EAD for CCR step)
    """
    counterparties_lf = _build_cva_a3_counterparty().lazy()
    ratings_lf = _build_cva_a3_rating().lazy()

    return make_raw_bundle(
        counterparties=counterparties_lf,
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=ratings_lf,
        ccr=_build_cva_a3_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Parquet save helpers.
# ---------------------------------------------------------------------------


def save_cva_a3_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CVA-A3 parquet files to output_dir.

    Files produced:
        cva_a3_trades.parquet              — 2 rows (T_CVA_A3_1 3y, T_CVA_A3_2 5y)
        cva_a3_netting_sets.parquet        — 2 rows (NS1 → CP_CVA_A3, NS2 → CP_CVA_A3)
        cva_a3_margin_agreements.parquet   — 0 rows
        cva_a3_ccr_collateral.parquet      — 0 rows
        cva_a3_cva_counterparties.parquet  — 1 row (CP_CVA_A3, M=4.0, FINANCIAL/IG)

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
        ("cva_a3_trades", create_cva_a3_trades()),
        ("cva_a3_netting_sets", create_cva_a3_netting_sets()),
        ("cva_a3_margin_agreements", create_cva_a3_margin_agreements()),
        ("cva_a3_ccr_collateral", create_cva_a3_collateral()),
        ("cva_a3_cva_counterparties", create_cva_a3_counterparty_frame()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


@dataclass
class CvaA3Inputs:
    """
    Named fixture bundle for the CVA-A3 acceptance test.

    Attributes:
        raw_data_bundle:        Complete RawDataBundle for the CCR pipeline
                                (without cva_counterparties — attach via
                                dataclasses.replace in the test).
        cva_counterparty_frame: One-row CVA counterparty input DataFrame
                                (CP_CVA_A3, M=4.0, FINANCIAL/IG).
        cp_ref:                 Reference key for the single counterparty.
        ns1_id:                 Netting set identifier for the 3-year trade.
        ns2_id:                 Netting set identifier for the 5-year trade.
    """

    raw_data_bundle: RawDataBundle
    cva_counterparty_frame: pl.DataFrame
    cp_ref: str
    ns1_id: str
    ns2_id: str


def build_cva_a3_inputs() -> CvaA3Inputs:
    """
    Return the named bundle the acceptance test feeds the pipeline.

    Usage in acceptance test::

        from tests.fixtures.p8_46.cva_a3_builder import (
            build_cva_a3_inputs,
            compute_cva_a3_golden,
        )

        inputs = build_cva_a3_inputs()
        # Attach CVA counterparty frame then run full pipeline ...
        golden = compute_cva_a3_golden(ead_ns1, ead_ns2)
        assert abs(result.cva_rwa - golden["cva_rwa"]) < 1.0
        # Structural invariants:
        assert golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"])
        assert golden["k_reduced"] == approx(golden["scva_c"])
    """
    return CvaA3Inputs(
        raw_data_bundle=build_raw_data_bundle_cva_a3(),
        cva_counterparty_frame=create_cva_a3_counterparty_frame(),
        cp_ref=CVA_A3_CP_REF,
        ns1_id=CVA_A3_NS1_ID,
        ns2_id=CVA_A3_NS2_ID,
    )


def save_p846_cva_a3_fixtures(output_dir: Path | None = None) -> list[tuple[str, int]]:
    """
    Smoke-check the CVA-A3 bundle and persist parquet files to output_dir.

    Invariants checked:
        1.  RawCCRBundle is present and non-None.
        2.  Trades frame has exactly 2 rows with correct trade IDs and maturities.
        3.  Netting-sets frame has 2 rows, BOTH legally enforceable, unmargined,
            and BOTH carrying counterparty_reference == CP_CVA_A3 (structural crux of A3).
        4.  Margin-agreements frame has 0 rows.
        5.  CCR-collateral frame has 0 rows.
        6.  CVA counterparty frame has EXACTLY 1 row with correct column values.
        7.  Counterparty frame has 1 row with entity_type=institution, CQS 2.
        8.  Ratings frame has 1 row, CQS 2, S&P "A", solicited.
        9.  compute_cva_a3_golden returns self-consistent values for illustrative EADs.
        10. Additivity invariant: scva_c == scva_ns1 + scva_ns2.
        11. Single-CP K collapse: k_reduced == scva_c (to floating-point precision).
        12. EAD-ratio invariant: scva_ns1 / scva_ns2 == ead_ns1 / ead_ns2
            (shared M*DF means ratio is preserved).

    Returns:
        List of (filename, row_count) tuples for the master report.
    """
    saved = save_cva_a3_fixtures(output_dir)

    inputs = build_cva_a3_inputs()
    bundle = inputs.raw_data_bundle

    # Invariant 1: CCR bundle present.
    if bundle.ccr is None:
        raise AssertionError("CVA-A3: bundle.ccr must not be None")

    # Invariant 2: trades frame.
    trades_df = bundle.ccr.trades.trades.collect()
    if len(trades_df) != 2:
        raise AssertionError(f"CVA-A3: expected 2 trade rows, got {len(trades_df)}")
    trade_ids = set(trades_df["trade_id"].to_list())
    if trade_ids != {CVA_A3_TRADE1_ID, CVA_A3_TRADE2_ID}:
        raise AssertionError(f"CVA-A3: trade IDs {trade_ids!r} mismatch")
    maturity_dates = set(trades_df["maturity_date"].to_list())
    if maturity_dates != {CVA_A3_MATURITY_DATE_1, CVA_A3_MATURITY_DATE_2}:
        raise AssertionError(f"CVA-A3: maturity dates {maturity_dates!r} mismatch")

    # Invariant 3: netting-sets frame — both rows must share the same CP ref.
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    if len(ns_df) != 2:
        raise AssertionError(f"CVA-A3: expected 2 NS rows, got {len(ns_df)}")
    if not ns_df["is_legally_enforceable"].all():
        raise AssertionError("CVA-A3: all netting sets must be legally enforceable")
    if ns_df["is_margined"].any():
        raise AssertionError("CVA-A3: all netting sets must be unmargined")
    cp_refs_ns = set(ns_df["counterparty_reference"].to_list())
    if cp_refs_ns != {CVA_A3_CP_REF}:
        raise AssertionError(
            f"CVA-A3: both NS must share counterparty_reference={CVA_A3_CP_REF!r}, "
            f"got {cp_refs_ns!r}"
        )

    # Invariant 4: margin-agreements frame.
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    if len(margin_df) != 0:
        raise AssertionError(f"CVA-A3: expected 0 margin rows, got {len(margin_df)}")

    # Invariant 5: CCR-collateral frame.
    collateral_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    if len(collateral_df) != 0:
        raise AssertionError(f"CVA-A3: expected 0 collateral rows, got {len(collateral_df)}")

    # Invariant 6: CVA counterparty frame — exactly ONE row.
    cva_cp = inputs.cva_counterparty_frame
    if len(cva_cp) != 1:
        raise AssertionError(f"CVA-A3: expected 1 CVA CP row, got {len(cva_cp)}")
    if cva_cp["counterparty_reference"][0] != CVA_A3_CP_REF:
        raise AssertionError(
            f"CVA-A3: CVA CP counterparty_reference must be {CVA_A3_CP_REF!r}, "
            f"got {cva_cp['counterparty_reference'][0]!r}"
        )
    if not cva_cp["cva_in_scope"].all():
        raise AssertionError("CVA-A3: cva_in_scope must be True")
    if cva_cp["cva_rw_sector"][0] != CVA_A3_CVA_RW_SECTOR:
        raise AssertionError(
            f"CVA-A3: cva_rw_sector must be {CVA_A3_CVA_RW_SECTOR!r}, "
            f"got {cva_cp['cva_rw_sector'][0]!r}"
        )
    if cva_cp["cva_rw_rating_band"][0] != CVA_A3_CVA_RW_RATING_BAND:
        raise AssertionError(
            f"CVA-A3: cva_rw_rating_band must be {CVA_A3_CVA_RW_RATING_BAND!r}, "
            f"got {cva_cp['cva_rw_rating_band'][0]!r}"
        )
    if cva_cp["cva_effective_maturity_years"][0] != CVA_A3_CVA_EFFECTIVE_MATURITY:
        raise AssertionError(
            f"CVA-A3: cva_effective_maturity_years must be {CVA_A3_CVA_EFFECTIVE_MATURITY}, "
            f"got {cva_cp['cva_effective_maturity_years'][0]}"
        )

    # Invariant 7: counterparty frame.
    cp_df = bundle.counterparties.collect()
    if len(cp_df) != 1:
        raise AssertionError(f"CVA-A3: expected 1 CP row, got {len(cp_df)}")
    if cp_df["entity_type"][0] != CVA_A3_CP_ENTITY_TYPE:
        raise AssertionError(
            f"CVA-A3: entity_type must be {CVA_A3_CP_ENTITY_TYPE!r}, "
            f"got {cp_df['entity_type'][0]!r}"
        )

    # Invariant 8: ratings frame.
    if bundle.ratings is None:
        raise AssertionError("CVA-A3: bundle.ratings must not be None")
    rating_df = bundle.ratings.collect()
    if len(rating_df) != 1:
        raise AssertionError(f"CVA-A3: expected 1 rating row, got {len(rating_df)}")
    if rating_df["cqs"][0] != CVA_A3_RATING_CQS:
        raise AssertionError(
            f"CVA-A3: CQS must be {CVA_A3_RATING_CQS}, got {rating_df['cqs'][0]}"
        )

    # Invariant 9 + 10 + 11 + 12: golden computation self-consistent.
    test_ead_ns1 = 5_200_000.0   # illustrative 3y EAD
    test_ead_ns2 = 7_800_000.0   # illustrative 5y EAD
    golden = compute_cva_a3_golden(test_ead_ns1, test_ead_ns2)

    df_val = golden["df_ns"]
    if not (0.0 < df_val <= 1.0):
        raise AssertionError(f"CVA-A3: df_ns={df_val} must be in (0,1]")

    # Invariant 10: additivity
    expected_scva_c = golden["scva_ns1"] + golden["scva_ns2"]
    if abs(golden["scva_c"] - expected_scva_c) > 1e-9 * abs(expected_scva_c):
        raise AssertionError(
            f"CVA-A3: additivity violated: scva_c={golden['scva_c']} != "
            f"scva_ns1+scva_ns2={expected_scva_c}"
        )

    # Invariant 11: single-CP K collapse
    if abs(golden["k_reduced"] - golden["scva_c"]) > 1e-9 * abs(golden["scva_c"]):
        raise AssertionError(
            f"CVA-A3: K collapse violated: k_reduced={golden['k_reduced']} != "
            f"scva_c={golden['scva_c']}"
        )

    # Invariant 12: EAD ratio preserved (shared M*DF)
    ratio_scva = golden["scva_ns1"] / golden["scva_ns2"]
    ratio_ead = test_ead_ns1 / test_ead_ns2
    if abs(ratio_scva - ratio_ead) > 1e-9 * abs(ratio_ead):
        raise AssertionError(
            f"CVA-A3: EAD-ratio invariant violated: scva ratio={ratio_scva} != "
            f"ead ratio={ratio_ead}"
        )

    return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]


def main() -> None:
    """Entry point for standalone fixture generation and verification."""
    import sys

    saved = save_cva_a3_fixtures()
    print("CVA-A3 fixture generation complete (P8.46)")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<40} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)

    # Verify bundle constructs cleanly.
    inputs = build_cva_a3_inputs()
    ccr = inputs.raw_data_bundle.ccr
    assert ccr is not None, "RawCCRBundle must be present"
    trades = ccr.trades.trades.collect()
    ns = ccr.netting_sets.netting_sets.collect()
    print(f"  Trades:       {trades['trade_id'].to_list()}")
    print(f"  Maturities:   {trades['maturity_date'].to_list()}")
    print(
        f"  NS -> CP:     "
        f"{list(zip(ns['netting_set_id'].to_list(), ns['counterparty_reference'].to_list()))}"
    )
    print(f"  CVA CP frame: {len(inputs.cva_counterparty_frame)} row(s)  (MUST be 1)")

    # Demonstrate the golden computation with illustrative EADs.
    ead_ns1 = 5_200_000.0
    ead_ns2 = 7_800_000.0
    golden = compute_cva_a3_golden(ead_ns1, ead_ns2)

    print()
    print(f"Illustrative golden (EAD_NS1={ead_ns1:,.0f}, EAD_NS2={ead_ns2:,.0f}):")
    print(f"  DF_NS     = {golden['df_ns']:.10f}  (M=4.0, rate=0.05)")
    print(f"  SCVA_NS1  = {golden['scva_ns1']:.4f}")
    print(f"  SCVA_NS2  = {golden['scva_ns2']:.4f}")
    print(f"  SCVA_c    = {golden['scva_c']:.4f}  (= SCVA_NS1 + SCVA_NS2)")
    print(f"  K_reduced = {golden['k_reduced']:.4f}  (= SCVA_c, single-CP identity)")
    print(f"  OFR_CVA   = {golden['ofr_cva']:.4f}  (= 0.65 * K_reduced)")
    print(f"  CVA_RWA   = {golden['cva_rwa']:.4f}  (= OFR_CVA * 12.5)")

    print()
    print("Structural invariants:")
    additivity_ok = abs(golden["scva_c"] - (golden["scva_ns1"] + golden["scva_ns2"])) < 1e-9
    k_collapse_ok = abs(golden["k_reduced"] - golden["scva_c"]) < 1e-9
    ratio_ok = abs(golden["scva_ns1"] / golden["scva_ns2"] - ead_ns1 / ead_ns2) < 1e-9
    print(f"  scva_c == scva_ns1+scva_ns2: {'PASS' if additivity_ok else 'FAIL'}")
    print(f"  k_reduced == scva_c:         {'PASS' if k_collapse_ok else 'FAIL'}")
    print(f"  scva ratio == ead ratio:     {'PASS' if ratio_ok else 'FAIL'}")
    assert additivity_ok, "Additivity invariant violated"
    assert k_collapse_ok, "K-collapse invariant violated"
    assert ratio_ok, "EAD-ratio invariant violated"

    sys.exit(0)


if __name__ == "__main__":
    main()
