"""
CCR-WWR-1 orchestrator-ready fixture (P8.53 / scenario CCR-WWR-1).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_wwr1.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/wwr.py + pipeline orchestrator)

Scenario design:
    Counterparty CP_WWR_01 is a GB institution (entity_type="institution",
    institution_cqs=2).  CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA RW.

    Netting set NS_WWR_01: counterparty=CP_WWR_01, legally enforceable,
    unmargined, has_general_wwr_flag=False, wwr_lgd_override=null.

    Two trades in NS_WWR_01:
        T_WWR_01:    equity derivative, notional GBP 10m, maturity 2028-01-01,
                     mtm=0.0, is_specific_wwr=True,
                     underlying_reference="CP_WWR_01_EQUITY".
                     CRR Art. 291(1)(b): the issuer of the reference equity
                     *is* the counterparty → specific WWR condition met.
        T_NORMAL_01: IR derivative, notional GBP 50m, maturity 2031-01-01,
                     mtm=0.0, is_specific_wwr=False.

    Empty margin-agreement and CCR-collateral frames (unmargined, no posted
    collateral) — mirrors make_p827_margin_agreements() / make_p827_collateral().

Difference from P8.27 (wwr_builder.py):
    P8.27 exposes bare LazyFrame factories consumed by narrow apply_wwr_gate
    unit tests.  Those tests do not require counterparty data.

    CCR-WWR-1 adds the full orchestrator context:
    - ``build_raw_data_bundle_ccr_wwr1()`` returns a complete ``RawDataBundle``
      that ``PipelineOrchestrator.run_with_data`` can consume end-to-end.
    - The CP_WWR_01 counterparty row (entity_type="institution", CQS 2) lets
      the SA Classifier route the two CCR-derived synthetic exposures (pre-gate:
      ccr__NS_WWR_01; post-gate: ccr__NS_WWR_01__wwr__T_WWR_01) through the
      Institution risk-weight table.
    - A matching external rating row (S&P "A", CQS 2, institution) feeds the
      rating-inheritance pipeline so ``external_cqs`` resolves correctly.

    The CCR trade/NS data *reuses* the P8.27 ``make_p827_*`` factories verbatim
    (constants NS_WWR_01_ID, T_WWR_01_ID, etc. are re-exported from here for
    test-writer convenience — test-writers need not import from two modules).

Expected post-gate structure (assertions for test-writer):
    NS frame: 2 rows after apply_wwr_gate —
        NS_WWR_01                      (residual, wwr_lgd_override=null)
        NS_WWR_01__wwr__T_WWR_01       (synthetic, wwr_lgd_override=1.0)
    Exposure frame: 2 CCR rows in aggregated output —
        exposure_reference = "ccr__NS_WWR_01"
        exposure_reference = "ccr__NS_WWR_01__wwr__T_WWR_01"
    Error frame: exactly 1 CCR010 (WARNING); 0 CCR011.

EAD/RWA magnitudes are OUT OF SCOPE for assertions — equity add-on engine
only partially shipped (P8.15/P8.34).  Assert structure (row count, IDs,
override flag value), not magnitude.

Exported public names
---------------------
    CCR_WWR1_COUNTERPARTY_REF       : str — "CP_WWR_01"
    CCR_WWR1_ENTITY_TYPE            : str — "institution"
    CCR_WWR1_COUNTRY_CODE           : str — "GB"
    CCR_WWR1_RATING_CQS             : int — 2
    CCR_WWR1_EXPECTED_INSTITUTION_RW: float — 0.50
    CCR_WWR1_RATING_REF             : str — "RTG_CCR_WWR1_CP_WWR_01"
    CCR_WWR1_RATING_AGENCY          : str — "S&P"
    CCR_WWR1_RATING_VALUE           : str — "A"

    Re-exported from wwr_builder (single source of truth for test assertions):
    NS_WWR_01_ID, SYNTHETIC_NS_ID, T_WWR_01_ID, T_NORMAL_01_ID,
    WWR_LGD_OVERRIDE_VALUE, EXPECTED_CCR010_COUNT, EXPECTED_CCR011_COUNT,
    CCR010_ERROR_CODE, CCR011_ERROR_CODE

    build_raw_data_bundle_ccr_wwr1() -> RawDataBundle
        Full orchestrator-ready bundle for PipelineOrchestrator.run_with_data.
    save_ccr_wwr1_fixtures()        -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - CRR Art. 291(1)(b)  — specific WWR definition (issuer = counterparty)
    - CRR Art. 291(5)(a)  — separate netting-set carve-out for specific WWR
    - CRR Art. 291(5)(c)  — LGD = 100% for IRB / Chapter 3
    - CRR Art. 291(5)(d)  — SA risk weight = unsecured transaction
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW
    - BCBS CRE53.3 / CRE53.7 — WWR definitions and treatment
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      COUNTERPARTY_SCHEMA, RATINGS_SCHEMA
    - tests/fixtures/ccr/wwr_builder.py  — P8.27 LazyFrame factories (reused)
    - tests/fixtures/ccr/golden_ccr_a1.py — orchestrator bundle pattern
"""

from __future__ import annotations

from datetime import date as _date

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
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# Re-import the P8.27 LazyFrame factories and scenario constants so test-writers
# can import everything from one module.  These are intentionally *not* shadowed
# here — they remain the single source of truth in wwr_builder.py.  The
# redundant `X as X` aliases mark each name as a deliberate re-export (F401).
from .wwr_builder import (
    CCR010_ERROR_CODE as CCR010_ERROR_CODE,
)
from .wwr_builder import (
    CCR011_ERROR_CODE as CCR011_ERROR_CODE,
)
from .wwr_builder import (
    CP_WWR_01_REF as CP_WWR_01_REF,
)
from .wwr_builder import (
    EXPECTED_CCR010_COUNT as EXPECTED_CCR010_COUNT,
)
from .wwr_builder import (
    EXPECTED_CCR011_COUNT as EXPECTED_CCR011_COUNT,
)
from .wwr_builder import (
    NS_WWR_01_ID as NS_WWR_01_ID,
)
from .wwr_builder import (
    SYNTHETIC_NS_ID as SYNTHETIC_NS_ID,
)
from .wwr_builder import (
    T_NORMAL_01_ID as T_NORMAL_01_ID,
)
from .wwr_builder import (
    T_WWR_01_ID as T_WWR_01_ID,
)
from .wwr_builder import (
    WWR_LGD_OVERRIDE_VALUE as WWR_LGD_OVERRIDE_VALUE,
)
from .wwr_builder import (
    make_p827_collateral as make_p827_collateral,
)
from .wwr_builder import (
    make_p827_margin_agreements as make_p827_margin_agreements,
)
from .wwr_builder import (
    make_p827_netting_sets as make_p827_netting_sets,
)
from .wwr_builder import (
    make_p827_trades as make_p827_trades,
)

# Public surface re-exported for the orchestrator-gate test-writers. The WWR-gate
# constants (SYNTHETIC_NS_ID, WWR_LGD_OVERRIDE_VALUE, EXPECTED_CCR0xx_COUNT,
# CCR0xx_ERROR_CODE) keep their single source of truth in wwr_builder; listing
# them here marks them as intentional re-exports (not unused imports).
__all__ = [
    "CCR010_ERROR_CODE",
    "CCR011_ERROR_CODE",
    "CCR_WWR1_COUNTERPARTY_REF",
    "CCR_WWR1_COUNTRY_CODE",
    "CCR_WWR1_ENTITY_TYPE",
    "CCR_WWR1_EXPECTED_INSTITUTION_RW",
    "CCR_WWR1_RATING_AGENCY",
    "CCR_WWR1_RATING_CQS",
    "CCR_WWR1_RATING_DATE",
    "CCR_WWR1_RATING_REF",
    "CCR_WWR1_RATING_TYPE",
    "CCR_WWR1_RATING_VALUE",
    "CP_WWR_01_REF",
    "EXPECTED_CCR010_COUNT",
    "EXPECTED_CCR011_COUNT",
    "NS_WWR_01_ID",
    "SYNTHETIC_NS_ID",
    "T_NORMAL_01_ID",
    "T_WWR_01_ID",
    "WWR_LGD_OVERRIDE_VALUE",
    "build_raw_data_bundle_ccr_wwr1",
    "save_ccr_wwr1_fixtures",
]

# ---------------------------------------------------------------------------
# CCR-WWR-1-specific counterparty / rating constants.
# ---------------------------------------------------------------------------

#: Counterparty reference — matches CP_WWR_01_REF in wwr_builder.
CCR_WWR1_COUNTERPARTY_REF: str = CP_WWR_01_REF  # "CP_WWR_01"

#: entity_type drives Classifier → ExposureClass.INSTITUTION.
CCR_WWR1_ENTITY_TYPE: str = "institution"

#: Jurisdiction.
CCR_WWR1_COUNTRY_CODE: str = "GB"

#: CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_WWR1_RATING_CQS: int = 2

#: Expected SA risk weight (institution, CQS 2, CRR Table 3).
CCR_WWR1_EXPECTED_INSTITUTION_RW: float = 0.50

# External rating row constants.
CCR_WWR1_RATING_REF: str = "RTG_CCR_WWR1_CP_WWR_01"
CCR_WWR1_RATING_TYPE: str = "external"
CCR_WWR1_RATING_AGENCY: str = "S&P"
#: S&P "A" maps to CQS 2 under CRR ECRA for institutions.
CCR_WWR1_RATING_VALUE: str = "A"
CCR_WWR1_RATING_DATE: _date = _date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Private counterparty / rating builders.
# ---------------------------------------------------------------------------


def _build_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_WWR_01.

    entity_type="institution" → Classifier routes to ExposureClass.INSTITUTION.
    institution_cqs=2 so SA risk-weight look-up resolves to 50% even when the
    rating-inheritance pipeline is bypassed in narrow unit tests.
    The matching external rating (_build_rating()) carries the same CQS 2 so
    the full pipeline also resolves correctly.
    """
    row = {
        "counterparty_reference": CCR_WWR1_COUNTERPARTY_REF,
        "counterparty_name": "CCR-WWR-1 Test Institution (CQS 2)",
        "entity_type": CCR_WWR1_ENTITY_TYPE,
        "country_code": CCR_WWR1_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_WWR1_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_WWR_01.

    S&P "A" = CQS 2 under CRR ECRA mapping for institutions.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    """
    row = {
        "rating_reference": CCR_WWR1_RATING_REF,
        "counterparty_reference": CCR_WWR1_COUNTERPARTY_REF,
        "rating_type": CCR_WWR1_RATING_TYPE,
        "rating_agency": CCR_WWR1_RATING_AGENCY,
        "rating_value": CCR_WWR1_RATING_VALUE,
        "cqs": CCR_WWR1_RATING_CQS,
        "pd": None,
        "rating_date": CCR_WWR1_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


# ---------------------------------------------------------------------------
# Private empty lending-stub builders (CCR-only portfolio — no traditional loans).
# ---------------------------------------------------------------------------


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame (no traditional lending in this bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame (no facility hierarchy)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame (no retail lending groups)."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Private CCR bundle builder.
# ---------------------------------------------------------------------------


def _build_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the P8.27 LazyFrame factories.

    Composition:
        trades           — 2 rows: T_WWR_01 (equity, is_specific_wwr=True)
                                   T_NORMAL_01 (IR, is_specific_wwr=False)
        netting_sets     — 1 row:  NS_WWR_01 (CP_WWR_01, enforceable, unmargined,
                                   has_general_wwr_flag=False, wwr_lgd_override=null)
        margin_agreements — 0 rows (unmargined — no CSA)
        ccr_collateral    — 0 rows (no posted/received collateral)

    The P8.27 factories are the authoritative source of these frames; this
    builder wraps them into the four-leaf RawCCRBundle expected by PipelineOrchestrator.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=make_p827_trades()),
        netting_sets=NettingSetBundle(netting_sets=make_p827_netting_sets()),
        margin_agreements=MarginAgreementBundle(margin_agreements=make_p827_margin_agreements()),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=make_p827_collateral()),
    )


# ---------------------------------------------------------------------------
# Public orchestrator-ready bundle factory.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_ccr_wwr1() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for the CCR-WWR-1 scenario.

    Key responsibilities:
    - Provides CP_WWR_01 as an institution counterparty (entity_type="institution",
      CQS 2, GB) so the SA Classifier routes the two CCR-derived exposures
      (pre-/post-gate) through SA-Institution (CRR Art. 120(1) Table 3 → 50% RW).
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves ``external_cqs`` correctly.
    - Zero-row facility / loan / contingent / mapping frames — the only exposures
      in the pipeline are the CCR-derived synthetic rows appended by the P8.20
      pipeline adapter.
    - ``ccr`` is populated with a RawCCRBundle containing:
        - T_WWR_01 (equity derivative, is_specific_wwr=True, notional GBP 10m)
        - T_NORMAL_01 (IR derivative, is_specific_wwr=False, notional GBP 50m)
        both in NS_WWR_01 (CP_WWR_01, legally enforceable, unmargined), with
        empty margin and CCR-collateral frames.

    Post-gate invariants for acceptance test:
        - Two NS rows: NS_WWR_01 (residual) + NS_WWR_01__wwr__T_WWR_01 (synthetic).
        - Synthetic NS has wwr_lgd_override=1.0 (Art. 291(5)(c)).
        - Two CCR exposure rows in aggregated output.
        - Exactly 1 CCR010 warning; 0 CCR011.

    Integration test usage::

        from tests.fixtures.ccr.ccr_wwr1_builder import build_raw_data_bundle_ccr_wwr1
        data = build_raw_data_bundle_ccr_wwr1()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 291 (WWR treatment)
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return make_raw_bundle(
        counterparties=_build_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_rating(),
        ccr=_build_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_ccr_wwr1_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check the CCR-WWR-1 bundle and return a generation report.

    No parquet files are written — this fixture is Python-only (same pattern
    as P8.27 / wwr_builder.py).  The function validates the invariants listed
    below and raises ``AssertionError`` with a descriptive message if any is
    violated.

    Invariants checked:
        1.  bundle.ccr is not None.
        2.  Trades frame has exactly 2 rows.
        3.  T_WWR_01 present: asset_class="equity", is_specific_wwr=True,
            underlying_reference="CP_WWR_01_EQUITY", netting_set_id=NS_WWR_01.
        4.  T_NORMAL_01 present: asset_class="interest_rate", is_specific_wwr=False.
        5.  Netting-set frame has exactly 1 row (NS_WWR_01).
        6.  NS_WWR_01: is_legally_enforceable=True, is_margined=False.
        7.  NS_WWR_01: has_general_wwr_flag=False.
        8.  NS_WWR_01: wwr_lgd_override=null (pre-gate input frame).
        9.  Counterparty frame has exactly 1 row (CP_WWR_01).
        10. CP_WWR_01: entity_type="institution", institution_cqs=2.
        11. Rating frame has exactly 1 row tied to CP_WWR_01, cqs=2.
        12. Margin-agreements frame has 0 rows.
        13. CCR-collateral frame has 0 rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``

    Raises:
        AssertionError: If any invariant is violated.
    """
    bundle = build_raw_data_bundle_ccr_wwr1()

    # --- Invariant 1: CCR bundle present ---
    if bundle.ccr is None:
        raise AssertionError("CCR-WWR-1: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    collateral_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()
    rating_df = bundle.ratings.collect() if bundle.ratings is not None else pl.DataFrame()

    # --- Invariant 2: 2 trade rows ---
    if trades_df.height != 2:
        raise AssertionError(f"CCR-WWR-1: expected 2 trade rows, got {trades_df.height}")

    # --- Invariant 3: T_WWR_01 checks ---
    wwr_row = trades_df.filter(pl.col("trade_id") == T_WWR_01_ID)
    if wwr_row.height != 1:
        raise AssertionError(f"CCR-WWR-1: trade {T_WWR_01_ID!r} not found")
    if wwr_row["asset_class"][0] != "equity":
        raise AssertionError(
            f"CCR-WWR-1: {T_WWR_01_ID} asset_class must be 'equity' "
            f"(got {wwr_row['asset_class'][0]!r})"
        )
    if wwr_row["is_specific_wwr"][0] is not True:
        raise AssertionError(f"CCR-WWR-1: {T_WWR_01_ID} is_specific_wwr must be True")
    if wwr_row["underlying_reference"][0] != "CP_WWR_01_EQUITY":
        raise AssertionError(
            f"CCR-WWR-1: {T_WWR_01_ID} underlying_reference must be 'CP_WWR_01_EQUITY' "
            f"(got {wwr_row['underlying_reference'][0]!r})"
        )
    if wwr_row["netting_set_id"][0] != NS_WWR_01_ID:
        raise AssertionError(f"CCR-WWR-1: {T_WWR_01_ID} netting_set_id must be {NS_WWR_01_ID!r}")

    # --- Invariant 4: T_NORMAL_01 checks ---
    normal_row = trades_df.filter(pl.col("trade_id") == T_NORMAL_01_ID)
    if normal_row.height != 1:
        raise AssertionError(f"CCR-WWR-1: trade {T_NORMAL_01_ID!r} not found")
    if normal_row["asset_class"][0] != "interest_rate":
        raise AssertionError(
            f"CCR-WWR-1: {T_NORMAL_01_ID} asset_class must be 'interest_rate' "
            f"(got {normal_row['asset_class'][0]!r})"
        )
    if normal_row["is_specific_wwr"][0] is not False:
        raise AssertionError(f"CCR-WWR-1: {T_NORMAL_01_ID} is_specific_wwr must be False")

    # --- Invariant 5: 1 netting-set row ---
    if ns_df.height != 1:
        raise AssertionError(f"CCR-WWR-1: expected 1 netting-set row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != NS_WWR_01_ID:
        raise AssertionError(
            f"CCR-WWR-1: netting_set_id must be {NS_WWR_01_ID!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )

    # --- Invariant 6: legally enforceable, unmargined ---
    if ns_df["is_legally_enforceable"][0] is not True:
        raise AssertionError("CCR-WWR-1: NS_WWR_01 is_legally_enforceable must be True")
    if ns_df["is_margined"][0] is not False:
        raise AssertionError("CCR-WWR-1: NS_WWR_01 is_margined must be False")

    # --- Invariant 7: no general WWR ---
    if ns_df["has_general_wwr_flag"][0] is not False:
        raise AssertionError("CCR-WWR-1: NS_WWR_01 has_general_wwr_flag must be False")

    # --- Invariant 8: wwr_lgd_override null (pre-gate) ---
    if ns_df["wwr_lgd_override"][0] is not None:
        raise AssertionError(
            f"CCR-WWR-1: NS_WWR_01 wwr_lgd_override must be null in pre-gate input frame "
            f"(got {ns_df['wwr_lgd_override'][0]!r})"
        )

    # --- Invariant 9: 1 counterparty row ---
    if cp_df.height != 1:
        raise AssertionError(f"CCR-WWR-1: expected 1 counterparty row, got {cp_df.height}")
    if cp_df["counterparty_reference"][0] != CCR_WWR1_COUNTERPARTY_REF:
        raise AssertionError(
            f"CCR-WWR-1: counterparty_reference must be {CCR_WWR1_COUNTERPARTY_REF!r}"
        )

    # --- Invariant 10: institution entity_type, CQS 2 ---
    if cp_df["entity_type"][0] != CCR_WWR1_ENTITY_TYPE:
        raise AssertionError(
            f"CCR-WWR-1: entity_type must be {CCR_WWR1_ENTITY_TYPE!r} "
            f"(got {cp_df['entity_type'][0]!r})"
        )
    if cp_df["institution_cqs"][0] != CCR_WWR1_RATING_CQS:
        raise AssertionError(
            f"CCR-WWR-1: institution_cqs must be {CCR_WWR1_RATING_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )

    # --- Invariant 11: 1 rating row, CQS 2 ---
    if rating_df.height != 1:
        raise AssertionError(f"CCR-WWR-1: expected 1 rating row, got {rating_df.height}")
    if rating_df["counterparty_reference"][0] != CCR_WWR1_COUNTERPARTY_REF:
        raise AssertionError("CCR-WWR-1: rating counterparty_reference mismatch")
    if rating_df["cqs"][0] != CCR_WWR1_RATING_CQS:
        raise AssertionError(
            f"CCR-WWR-1: rating cqs must be {CCR_WWR1_RATING_CQS} (got {rating_df['cqs'][0]!r})"
        )

    # --- Invariant 12: zero margin-agreements rows ---
    if margin_df.height != 0:
        raise AssertionError(
            f"CCR-WWR-1: margin_agreements must be empty (got {margin_df.height} rows)"
        )

    # --- Invariant 13: zero CCR-collateral rows ---
    if collateral_df.height != 0:
        raise AssertionError(
            f"CCR-WWR-1: ccr_collateral must be empty (got {collateral_df.height} rows)"
        )

    return [("(python-only builder — no parquet)", 0)]
