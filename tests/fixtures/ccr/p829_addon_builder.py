"""
P8.29 fixture: orchestrator-ready transitional alpha add-on — CCR-ALPHA-ADDON-1..4.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_addon.py)
    -> engine-implementer (engine/ccr/pipeline_adapter.py — transitional_add_on column)

Scenario design:
    Four acceptance scenarios covering the transitional alpha add-on introduced by
    PRA PS1/26 Art. 274(2A)-(2B) (effective 1 Jan 2027).  All four share identical
    CCR-A1 trade economics (10y GBP IR swap, notional GBP 100m, MtM=0, delta=1.0,
    unmargined, no collateral — one trade, one netting set each).  They differ only
    in ``counterparty_type`` (from P8.28) and the new ``is_legacy_cva_exempt``
    boolean on the trade frame.

    | Scenario   | CP ref          | counterparty_type | is_legacy_cva_exempt | α base |
    |------------|-----------------|-------------------|----------------------|--------|
    | ADDON-1/4  | CP-NFC-ADDON-01 | non_financial     | True                 | 1.0    |
    | ADDON-2    | CP-NFC-ADDON-02 | non_financial     | False                | 1.0    |
    | ADDON-3    | CP-FIN-ADDON-01 | financial         | True                 | 1.4    |

    ADDON-1: non_financial + legacy=True → add-on FIRES under Basel 3.1 per year in schedule.
    ADDON-2: non_financial + legacy=False → add-on does NOT fire (non-legacy).
    ADDON-3: financial + legacy=True → gate FALSE (alpha_applied≠1.0) → add-on does NOT fire.
    ADDON-4: non_financial + legacy=True under CRR → transitional never fires (CRR gate).

    NOTE: reporting_date and framework (CRR vs Basel 3.1) are CalculationConfig settings
    that the TEST controls.  ``build_p829_bundle`` is parameterised ONLY by
    (counterparty_type, is_legacy_cva_exempt).

Hand-calculated EAD (anchored to tests/expected_outputs/ccr/CCR-A1.json):
    RC    = max(0 - 0, 0) = 0                               (Art. 275(1))
    PFE multiplier = 1.0  (V-C = 0 → not under-collateralised)
    addon_aggregate = 3_914_298.228  (SF_IR=0.005, 10y tenor)
    pfe_addon       = 1.0 × 3_914_298.228 = 3_914_298.228

    EAD(α=1.0) = 1.0 × (0 + 3_914_298.228) = 3_914_298.228   ← P829_EAD_ALPHA1
    EAD(α=1.4) = 1.4 × (0 + 3_914_298.228) = 5_480_017.519   ← P829_EAD_ALPHA14
    alpha_add_on(full) = 0.4 × 3_914_298.228 = 1_565_719.2912 ← P829_ADDON_FULL

    Transitional EAD = EAD(α=1) × (1 + 0.4 × phase):
        2027 (phase=0.6) → 3_914_298.228 × 1.24 = 4_853_729.80272
        2028 (phase=0.4) → 3_914_298.228 × 1.16 = 4_540_585.94448
        2029 (phase=0.2) → 3_914_298.228 × 1.08 = 4_227_442.08624
        2030 (phase=0.0) → 3_914_298.228 × 1.00 = 3_914_298.228

    transitional_add_on = phase × P829_ADDON_FULL:
        2027 → 0.6 × 1_565_719.2912 = 939_431.57472
        2028 → 0.4 × 1_565_719.2912 = 626_287.71648
        2029 → 0.2 × 1_565_719.2912 = 313_143.85824
        2030 → 0

Schema-strictness confirmation for ``is_legacy_cva_exempt``:
    ``is_legacy_cva_exempt`` is placed on the trade frame via ``with_columns``
    (a pl.lit(…) column appended after the base schema is typed).  The Python-bundle
    path (PipelineOrchestrator.run_with_data) bypasses the file-based loader entirely,
    so the literal column is never subject to the ``enforce_schema`` select guard.
    It will be visible in the trades LazyFrame exactly as written.
    This mirrors the P8.28 pattern for ``counterparty_type`` on the counterparty frame.
    The engine-implementer adds the ColumnSpec to TRADE_SCHEMA; no schema edit here.

Keyed-join / fan-out guard:
    ``build_p829_two_ns_book()`` provides a 2-NS bundle (one legacy NFC NS +
    one non-legacy NFC NS) to regression-guard the per-trade→per-NS collapse of
    ``any(is_legacy_cva_exempt)`` against cross-join fan-out.

Exported public names
---------------------
    P829_CP_NFC_ADDON1_REF  : str — "CP-NFC-ADDON-01"   (ADDON-1/-4: legacy NFC)
    P829_CP_NFC_ADDON2_REF  : str — "CP-NFC-ADDON-02"   (ADDON-2: non-legacy NFC)
    P829_CP_FIN_ADDON3_REF  : str — "CP-FIN-ADDON-01"   (ADDON-3: legacy financial)

    P829_NS_NFC_LEGACY_ID   : str — "NS-NFC-ADDON-01"
    P829_NS_NFC_NONLEG_ID   : str — "NS-NFC-ADDON-02"
    P829_NS_FIN_LEGACY_ID   : str — "NS-FIN-ADDON-01"

    P829_TRADE_NFC_LEGACY_ID  : str — "T-NFC-ADDON-01"
    P829_TRADE_NFC_NONLEG_ID  : str — "T-NFC-ADDON-02"
    P829_TRADE_FIN_LEGACY_ID  : str — "T-FIN-ADDON-01"

    P829_PFE_ADDON      : float — 3_914_298.228
    P829_EAD_ALPHA1     : float — 3_914_298.228   (α=1.0, RC=0)
    P829_EAD_ALPHA14    : float — 5_480_017.519   (α=1.4, RC=0)
    P829_ADDON_FULL     : float — 1_565_719.2912  (= 0.4 × pfe_addon)
    P829_EAD_2027       : float — 4_853_729.80272 (1.24 × EAD(α=1))
    P829_EAD_2028       : float — 4_540_585.94448 (1.16 × EAD(α=1))
    P829_EAD_2029       : float — 4_227_442.08624 (1.08 × EAD(α=1))
    P829_EAD_2030       : float — 3_914_298.228   (1.00 × EAD(α=1))
    P829_ADDON_2027     : float — 939_431.57472
    P829_ADDON_2028     : float — 626_287.71648
    P829_ADDON_2029     : float — 313_143.85824

    build_p829_bundle(counterparty_type, is_legacy_cva_exempt) -> RawDataBundle
        Full orchestrator-ready bundle for one scenario combo.

    build_p829_two_ns_book() -> RawDataBundle
        2-NS regression bundle: one legacy NFC NS + one non-legacy NFC NS.

    save_p829_fixtures() -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - PRA PS1/26 Art. 274(2A) — transitional alpha add-on (60%/40%/20% phases)
    - PRA PS1/26 Art. 274(2B) — leverage-ratio exclusion (out of engine scope)
    - CRR Art. 274(2) — EAD = α × (RC + PFE); α=1.4 default
    - CRR Art. 274(2) second sub-paragraph — α=1.0 for EMIR non-financial / pension
    - EMIR Art. 2(9) — non-financial counterparty definition
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW
    - tests/expected_outputs/ccr/CCR-A1.json — authoritative pfe_addon / EAD anchors
"""

from __future__ import annotations

from typing import Any

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

from .golden_ccr_a1 import (
    CCR_A1_ASSET_CLASS,
    CCR_A1_CURRENCY,
    CCR_A1_DELTA,
    CCR_A1_IS_LEGALLY_ENFORCEABLE,
    CCR_A1_IS_LONG,
    CCR_A1_IS_MARGINED,
    CCR_A1_MATURITY_DATE,
    CCR_A1_MTM,
    CCR_A1_NOTIONAL,
    CCR_A1_RATING_CQS,
    CCR_A1_START_DATE,
    CCR_A1_TRANSACTION_TYPE,
)
from .margin_builder import create_margin_agreements
from .netting_set_builder import create_netting_sets, make_netting_set
from .trade_builder import create_trades, make_trade

# ---------------------------------------------------------------------------
# Counterparty references — distinct from P8.28 to avoid ID collision.
# ---------------------------------------------------------------------------

#: Non-financial counterparty, legacy CVA-exempt (ADDON-1/-4).
P829_CP_NFC_ADDON1_REF: str = "CP-NFC-ADDON-01"

#: Non-financial counterparty, NOT legacy CVA-exempt (ADDON-2).
P829_CP_NFC_ADDON2_REF: str = "CP-NFC-ADDON-02"

#: Financial counterparty, legacy CVA-exempt (ADDON-3, α=1.4 control).
P829_CP_FIN_ADDON3_REF: str = "CP-FIN-ADDON-01"

# ---------------------------------------------------------------------------
# Netting-set and trade identifiers (one per scenario combo).
# ---------------------------------------------------------------------------

P829_NS_NFC_LEGACY_ID: str = "NS-NFC-ADDON-01"
P829_NS_NFC_NONLEG_ID: str = "NS-NFC-ADDON-02"
P829_NS_FIN_LEGACY_ID: str = "NS-FIN-ADDON-01"

P829_TRADE_NFC_LEGACY_ID: str = "T-NFC-ADDON-01"
P829_TRADE_NFC_NONLEG_ID: str = "T-NFC-ADDON-02"
P829_TRADE_FIN_LEGACY_ID: str = "T-FIN-ADDON-01"

# ---------------------------------------------------------------------------
# Economic constants — anchored to tests/expected_outputs/ccr/CCR-A1.json.
# ---------------------------------------------------------------------------

#: PFE add-on (pfe_multiplier=1.0 × addon_aggregate=3_914_298.228).
P829_PFE_ADDON: float = 3_914_298.228

#: EAD at α=1.0 (RC=0).  ADDON-1/-2/-4 base (before transitional uplift).
P829_EAD_ALPHA1: float = 3_914_298.228

#: EAD at α=1.4 (RC=0).  ADDON-3 control (financial counterparty).
P829_EAD_ALPHA14: float = 5_480_017.519

#: Full alpha add-on = (1.4 − 1.0) × (RC + PFE) = 0.4 × 3_914_298.228.
P829_ADDON_FULL: float = 1_565_719.2912

# Transitional EAD values for ADDON-1 (legacy NFC) under Basel 3.1:
#   transitional_EAD = EAD(α=1) × (1 + 0.4 × phase)
P829_EAD_2027: float = 4_853_729.80272  # phase=0.6, factor=1.24
P829_EAD_2028: float = 4_540_585.94448  # phase=0.4, factor=1.16
P829_EAD_2029: float = 4_227_442.08624  # phase=0.2, factor=1.08
P829_EAD_2030: float = 3_914_298.228  # phase=0.0, factor=1.00

# Transitional add-on amounts = phase × P829_ADDON_FULL:
P829_ADDON_2027: float = 939_431.57472  # 0.6 × 1_565_719.2912
P829_ADDON_2028: float = 626_287.71648  # 0.4 × 1_565_719.2912
P829_ADDON_2029: float = 313_143.85824  # 0.2 × 1_565_719.2912

#: Institution CQS for the financial control counterparty (CQS 2 → 50% RW).
_P829_INSTITUTION_CQS: int = CCR_A1_RATING_CQS  # 2

# ---------------------------------------------------------------------------
# Internal scenario dispatch table.
# ---------------------------------------------------------------------------

#: Maps (counterparty_type, is_legacy_cva_exempt) → (cp_ref, ns_id, trade_id, entity_type, name).
_SCENARIO_MAP: dict[tuple[str, bool], tuple[str, str, str, str, str]] = {
    ("non_financial", True): (
        P829_CP_NFC_ADDON1_REF,
        P829_NS_NFC_LEGACY_ID,
        P829_TRADE_NFC_LEGACY_ID,
        "corporate",
        "Non-Financial Corporate — legacy CVA-exempt (ADDON-1/-4)",
    ),
    ("non_financial", False): (
        P829_CP_NFC_ADDON2_REF,
        P829_NS_NFC_NONLEG_ID,
        P829_TRADE_NFC_NONLEG_ID,
        "corporate",
        "Non-Financial Corporate — non-legacy (ADDON-2)",
    ),
    ("financial", True): (
        P829_CP_FIN_ADDON3_REF,
        P829_NS_FIN_LEGACY_ID,
        P829_TRADE_FIN_LEGACY_ID,
        "institution",
        "Financial Institution — legacy CVA-exempt (ADDON-3, α=1.4 control)",
    ),
}


# ---------------------------------------------------------------------------
# Private helpers.
# ---------------------------------------------------------------------------


def _build_counterparty(counterparty_type: str, is_legacy_cva_exempt: bool) -> pl.DataFrame:
    """
    Return a single-row counterparty DataFrame with ``counterparty_type`` appended.

    The column is added via ``with_columns(pl.lit(...))`` — identical to the P8.28
    pattern — so it survives through PipelineOrchestrator.run_with_data without
    being stripped by the ``enforce_schema`` ``with_columns`` call.

    institution_cqs is set to CQS 2 for the financial control and left null for
    corporate counterparties (carve-out).
    """
    key = (counterparty_type, is_legacy_cva_exempt)
    if key not in _SCENARIO_MAP:
        raise ValueError(
            f"Unknown (counterparty_type, is_legacy_cva_exempt)={key!r}; "
            f"must be one of {sorted(_SCENARIO_MAP)}"
        )
    cp_ref, _ns_id, _trade_id, entity_type, name = _SCENARIO_MAP[key]

    is_financial = counterparty_type == "financial"
    institution_cqs: int | None = _P829_INSTITUTION_CQS if is_financial else None

    row: dict[str, Any] = {
        "counterparty_reference": cp_ref,
        "counterparty_name": name,
        "entity_type": entity_type,
        "country_code": "GB",
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": None,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": institution_cqs,
    }
    base = pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(pl.lit(counterparty_type).alias("counterparty_type"))


def _build_trade(
    trade_id: str,
    netting_set_id: str,
    is_legacy_cva_exempt: bool,
) -> pl.DataFrame:
    """
    Return a single-row trades DataFrame using CCR-A1 golden economics.

    ``is_legacy_cva_exempt`` is appended as a ``pl.lit(...)`` boolean column after
    the base schema is constructed — identical pattern to P8.28's
    ``counterparty_type`` on the counterparty frame.  The engine-implementer will
    declare the matching ColumnSpec in TRADE_SCHEMA; no schema edit here.
    """
    trade = make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        asset_class=CCR_A1_ASSET_CLASS,
        transaction_type=CCR_A1_TRANSACTION_TYPE,
        notional=CCR_A1_NOTIONAL,
        currency=CCR_A1_CURRENCY,
        maturity_date=CCR_A1_MATURITY_DATE,
        start_date=CCR_A1_START_DATE,
        delta=CCR_A1_DELTA,
        is_long=CCR_A1_IS_LONG,
        mtm_value=CCR_A1_MTM,
    )
    trades_df = create_trades([trade])
    return trades_df.with_columns(pl.lit(is_legacy_cva_exempt).alias("is_legacy_cva_exempt"))


def _build_netting_set(netting_set_id: str, cp_ref: str) -> pl.DataFrame:
    """Return a single-row netting-sets DataFrame (unmargined, legally enforceable)."""
    ns = make_netting_set(
        netting_set_id=netting_set_id,
        counterparty_reference=cp_ref,
        is_legally_enforceable=CCR_A1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A1_IS_MARGINED,
    )
    return create_netting_sets([ns])


def _build_empty_ccr_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (no collateral for these scenarios)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_raw_ccr_bundle(
    trades_df: pl.DataFrame,
    netting_sets_df: pl.DataFrame,
) -> RawCCRBundle:
    """Wrap DataFrames into a RawCCRBundle with empty margin and collateral frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=trades_df.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets_df.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral().lazy()),
    )


def _build_empty_lending_frames() -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    """Return zero-row facilities/loans/facility_mappings/lending_mappings LazyFrames."""
    return (
        pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
    )


# ---------------------------------------------------------------------------
# Public bundle factories.
# ---------------------------------------------------------------------------


def build_p829_bundle(
    counterparty_type: str,
    is_legacy_cva_exempt: bool,
) -> RawDataBundle:
    """
    Build a complete orchestrator-ready RawDataBundle for one P8.29 scenario.

    All combos share CCR-A1 trade economics (10y GBP IR swap, GBP 100m notional,
    MtM=0, delta=1.0, unmargined, no collateral).  They differ in:
      - ``counterparty_type`` on the counterparty frame (P8.28 column).
      - ``is_legacy_cva_exempt`` on the trade frame (new P8.29 column).

    Accepted (counterparty_type, is_legacy_cva_exempt) combinations:
        ("non_financial", True)   → ADDON-1/-4 (legacy NFC — add-on fires under B31)
        ("non_financial", False)  → ADDON-2    (non-legacy NFC — add-on does NOT fire)
        ("financial",     True)   → ADDON-3    (legacy financial — gate FALSE, α=1.4)

    NOTE: reporting_date and framework (CRR vs Basel 3.1) are CalculationConfig
    settings the TEST controls.  This factory does NOT accept them.

    Args:
        counterparty_type: One of "non_financial", "financial".
        is_legacy_cva_exempt: True if the trade was entered prior to 1 Jan 2027
            with a CVA Part 7.1(1)(a)/(b) counterparty (firm-supplied flag).

    Returns:
        Complete RawDataBundle suitable for PipelineOrchestrator.run_with_data.

    Raises:
        ValueError: If the (counterparty_type, is_legacy_cva_exempt) combo is unknown.

    References:
        - PRA PS1/26 Art. 274(2A) — transitional alpha add-on gating
        - CRR Art. 274(2) — α=1.4 default, 1.0 carve-out
        - EMIR Art. 2(9) — non-financial counterparty
    """
    key = (counterparty_type, is_legacy_cva_exempt)
    if key not in _SCENARIO_MAP:
        raise ValueError(
            f"Unknown (counterparty_type, is_legacy_cva_exempt)={key!r}; "
            f"must be one of {sorted(_SCENARIO_MAP)}"
        )
    cp_ref, ns_id, trade_id, _entity_type, _name = _SCENARIO_MAP[key]

    counterparty_df = _build_counterparty(counterparty_type, is_legacy_cva_exempt)
    trades_df = _build_trade(trade_id, ns_id, is_legacy_cva_exempt)
    netting_sets_df = _build_netting_set(ns_id, cp_ref)
    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=counterparty_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_build_raw_ccr_bundle(trades_df, netting_sets_df),
    )


def build_p829_two_ns_book() -> RawDataBundle:
    """
    Build a 2-NS, 2-trade bundle for per-NS ``any(is_legacy_cva_exempt)`` regression testing.

    Purpose:
        A single-NS fixture (1×1×1) passes regardless of whether the per-trade→per-NS
        ``any(is_legacy_cva_exempt)`` collapse is implemented as a keyed aggregation or
        a cross-join fan-out.  This 2-NS book has:
            NS-NFC-ADDON-01  (CP-NFC-ADDON-01, legacy=True)   — T-NFC-ADDON-01
            NS-NFC-ADDON-02  (CP-NFC-ADDON-02, legacy=False)  — T-NFC-ADDON-02
        so a cross-join fan-out would produce 4 NS-trade rows instead of 2.

    Expected post-collapse per-NS values:
        NS-NFC-ADDON-01:  any(is_legacy_cva_exempt) == True   → add-on FIRES under B31
        NS-NFC-ADDON-02:  any(is_legacy_cva_exempt) == False  → add-on suppressed

    Test-writer can assert:
        result rows == 2  (no fan-out)
        transitional_add_on(NS-01) > 0   and   transitional_add_on(NS-02) == 0

    References:
        - PRA PS1/26 Art. 274(2A) — per-NS add-on (NS = netting set)
    """
    # Two distinct legacy states sharing the same counterparty_type ("non_financial").
    legacy_cp = _build_counterparty("non_financial", True)
    nonleg_cp = _build_counterparty("non_financial", False)
    counterparties_df = pl.concat([legacy_cp, nonleg_cp])

    legacy_trade = _build_trade(P829_TRADE_NFC_LEGACY_ID, P829_NS_NFC_LEGACY_ID, True)
    nonleg_trade = _build_trade(P829_TRADE_NFC_NONLEG_ID, P829_NS_NFC_NONLEG_ID, False)
    trades_df = pl.concat([legacy_trade, nonleg_trade])

    legacy_ns = _build_netting_set(P829_NS_NFC_LEGACY_ID, P829_CP_NFC_ADDON1_REF)
    nonleg_ns = _build_netting_set(P829_NS_NFC_NONLEG_ID, P829_CP_NFC_ADDON2_REF)
    netting_sets_df = pl.concat([legacy_ns, nonleg_ns])

    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=counterparties_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_build_raw_ccr_bundle(trades_df, netting_sets_df),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p829_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all P8.29 bundles and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as p828_alpha_builder.py).  All load-bearing invariants are validated; raises
    ``AssertionError`` with a descriptive message if any is violated.

    Single-bundle invariants (checked for all three combos):
        1.  bundle.ccr is not None.
        2.  1 trade row; correct trade_id.
        3.  1 netting-set row; correct netting_set_id.
        4.  1 counterparty row; counterparty_type column present and correct.
        5.  is_legacy_cva_exempt column present on trades; value correct.
        6.  entity_type correct (corporate for NFC, institution for financial).
        7.  institution_cqs set for financial, null for corporate.
        8.  Economics identical across all three combos (same notional / mtm / dates).
        9.  0 margin-agreement rows; 0 CCR-collateral rows.

    2-NS book invariants:
        10. 2 counterparty rows; 2 trade rows; 2 netting-set rows.
        11. No duplicate netting_set_ids (cross-join fan-out guard).
        12. is_legacy_cva_exempt column present; True on T-NFC-ADDON-01, False on T-NFC-ADDON-02.
        13. 0 margin-agreement rows; 0 CCR-collateral rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    scenarios: list[tuple[str, bool, str, str, str, str, str, int | None]] = [
        # (cp_type, legacy, scenario_label, cp_ref, ns_id, trade_id, entity_type, institution_cqs)
        (
            "non_financial",
            True,
            "ADDON-1",
            P829_CP_NFC_ADDON1_REF,
            P829_NS_NFC_LEGACY_ID,
            P829_TRADE_NFC_LEGACY_ID,
            "corporate",
            None,
        ),
        (
            "non_financial",
            False,
            "ADDON-2",
            P829_CP_NFC_ADDON2_REF,
            P829_NS_NFC_NONLEG_ID,
            P829_TRADE_NFC_NONLEG_ID,
            "corporate",
            None,
        ),
        (
            "financial",
            True,
            "ADDON-3",
            P829_CP_FIN_ADDON3_REF,
            P829_NS_FIN_LEGACY_ID,
            P829_TRADE_FIN_LEGACY_ID,
            "institution",
            _P829_INSTITUTION_CQS,
        ),
    ]
    for (
        cp_type,
        legacy,
        label,
        exp_cp_ref,
        exp_ns_id,
        exp_trade_id,
        exp_entity,
        exp_cqs,
    ) in scenarios:
        bundle = build_p829_bundle(cp_type, legacy)
        _check_p829_single(
            bundle,
            scenario=label,
            expected_cp_ref=exp_cp_ref,
            expected_ns_id=exp_ns_id,
            expected_trade_id=exp_trade_id,
            expected_cp_type=cp_type,
            expected_legacy=legacy,
            expected_entity_type=exp_entity,
            expected_institution_cqs=exp_cqs,
        )

    book = build_p829_two_ns_book()
    _check_p829_two_ns(book)

    return [("(python-only builder — no parquet)", 0)]


def _check_p829_single(
    bundle: RawDataBundle,
    scenario: str,
    expected_cp_ref: str,
    expected_ns_id: str,
    expected_trade_id: str,
    expected_cp_type: str,
    expected_legacy: bool,
    expected_entity_type: str,
    expected_institution_cqs: int | None,
) -> None:
    """Verify invariants for a single-combo P8.29 bundle."""
    prefix = f"P8.29 {scenario}"

    if bundle.ccr is None:
        raise AssertionError(f"{prefix}: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()

    # Trade checks.
    if trades_df.height != 1:
        raise AssertionError(f"{prefix}: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != expected_trade_id:
        raise AssertionError(
            f"{prefix}: trade_id must be {expected_trade_id!r} (got {trades_df['trade_id'][0]!r})"
        )

    # is_legacy_cva_exempt column check.
    if "is_legacy_cva_exempt" not in trades_df.columns:
        raise AssertionError(
            f"{prefix}: is_legacy_cva_exempt column must be present on trades frame"
        )
    if trades_df["is_legacy_cva_exempt"][0] is not expected_legacy:
        raise AssertionError(
            f"{prefix}: is_legacy_cva_exempt must be {expected_legacy!r} "
            f"(got {trades_df['is_legacy_cva_exempt'][0]!r})"
        )

    # Economics check — notional and mtm must match CCR-A1 golden constants.
    if trades_df["notional"][0] != CCR_A1_NOTIONAL:
        raise AssertionError(
            f"{prefix}: notional must be {CCR_A1_NOTIONAL} (got {trades_df['notional'][0]})"
        )
    if trades_df["mtm_value"][0] != CCR_A1_MTM:
        raise AssertionError(
            f"{prefix}: mtm_value must be {CCR_A1_MTM} (got {trades_df['mtm_value'][0]})"
        )

    # Netting-set checks.
    if ns_df.height != 1:
        raise AssertionError(f"{prefix}: expected 1 NS row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != expected_ns_id:
        raise AssertionError(
            f"{prefix}: netting_set_id must be {expected_ns_id!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["counterparty_reference"][0] != expected_cp_ref:
        raise AssertionError(
            f"{prefix}: NS counterparty_reference must be {expected_cp_ref!r} "
            f"(got {ns_df['counterparty_reference'][0]!r})"
        )

    # Counterparty checks.
    if cp_df.height != 1:
        raise AssertionError(f"{prefix}: expected 1 counterparty row, got {cp_df.height}")
    if "counterparty_type" not in cp_df.columns:
        raise AssertionError(
            f"{prefix}: counterparty_type column must be present on counterparty frame"
        )
    if cp_df["counterparty_type"][0] != expected_cp_type:
        raise AssertionError(
            f"{prefix}: counterparty_type must be {expected_cp_type!r} "
            f"(got {cp_df['counterparty_type'][0]!r})"
        )
    if cp_df["entity_type"][0] != expected_entity_type:
        raise AssertionError(
            f"{prefix}: entity_type must be {expected_entity_type!r} "
            f"(got {cp_df['entity_type'][0]!r})"
        )
    if expected_institution_cqs is not None:
        if cp_df["institution_cqs"][0] != expected_institution_cqs:
            raise AssertionError(
                f"{prefix}: institution_cqs must be {expected_institution_cqs} "
                f"(got {cp_df['institution_cqs'][0]!r})"
            )
    else:
        if cp_df["institution_cqs"][0] is not None:
            raise AssertionError(
                f"{prefix}: institution_cqs must be null for non-financial CP "
                f"(got {cp_df['institution_cqs'][0]!r})"
            )

    # Empty frame checks.
    if margin_df.height != 0:
        raise AssertionError(f"{prefix}: margin_agreements must be empty (got {margin_df.height})")
    if coll_df.height != 0:
        raise AssertionError(f"{prefix}: ccr_collateral must be empty (got {coll_df.height})")


def _check_p829_two_ns(bundle: RawDataBundle) -> None:
    """Verify invariants for the 2-NS regression book."""
    prefix = "P8.29 2-NS book"

    if bundle.ccr is None:
        raise AssertionError(f"{prefix}: bundle.ccr must not be None")

    cp_df = bundle.counterparties.collect()
    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()

    if cp_df.height != 2:
        raise AssertionError(f"{prefix}: expected 2 counterparty rows, got {cp_df.height}")
    if trades_df.height != 2:
        raise AssertionError(f"{prefix}: expected 2 trade rows, got {trades_df.height}")
    if ns_df.height != 2:
        raise AssertionError(f"{prefix}: expected 2 NS rows, got {ns_df.height}")

    # Cross-join fan-out guard.
    ns_ids = ns_df["netting_set_id"].to_list()
    if len(ns_ids) != len(set(ns_ids)):
        raise AssertionError(
            f"{prefix}: duplicate netting_set_id detected (cross-join fan-out?): {ns_ids}"
        )

    # is_legacy_cva_exempt column must be present on trades.
    if "is_legacy_cva_exempt" not in trades_df.columns:
        raise AssertionError(f"{prefix}: is_legacy_cva_exempt must be present on trades frame")

    # Find legacy and non-legacy trades by trade_id.
    legacy_rows = trades_df.filter(pl.col("trade_id") == P829_TRADE_NFC_LEGACY_ID)
    nonleg_rows = trades_df.filter(pl.col("trade_id") == P829_TRADE_NFC_NONLEG_ID)
    if legacy_rows.height != 1:
        raise AssertionError(
            f"{prefix}: expected 1 row for {P829_TRADE_NFC_LEGACY_ID!r}, got {legacy_rows.height}"
        )
    if nonleg_rows.height != 1:
        raise AssertionError(
            f"{prefix}: expected 1 row for {P829_TRADE_NFC_NONLEG_ID!r}, got {nonleg_rows.height}"
        )
    if legacy_rows["is_legacy_cva_exempt"][0] is not True:
        raise AssertionError(
            f"{prefix}: {P829_TRADE_NFC_LEGACY_ID!r} is_legacy_cva_exempt must be True"
        )
    if nonleg_rows["is_legacy_cva_exempt"][0] is not False:
        raise AssertionError(
            f"{prefix}: {P829_TRADE_NFC_NONLEG_ID!r} is_legacy_cva_exempt must be False"
        )

    if margin_df.height != 0:
        raise AssertionError(f"{prefix}: margin_agreements must be empty (got {margin_df.height})")
    if coll_df.height != 0:
        raise AssertionError(f"{prefix}: ccr_collateral must be empty (got {coll_df.height})")
