"""
P8.28 fixture: orchestrator-ready α=1.0 carve-out — CCR-ALPHA-1 / CCR-ALPHA-2 / CCR-ALPHA-3.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_alpha_carve_out.py)
    -> engine-implementer (engine/ccr/pipeline_adapter.py  — per-row alpha join)

Scenario design:
    Three acceptance scenarios sharing identical CCR-A1 trade economics (10y GBP
    IR swap, notional GBP 100m, MtM=0, delta=1.0, unmargined, no collateral —
    one trade, one netting set each), differing ONLY in ``counterparty_type``.

    | Scenario     | CP ref         | counterparty_type   | entity_type   | α   |
    |--------------|----------------|---------------------|---------------|-----|
    | CCR-ALPHA-1  | CP-NFC-01      | non_financial       | corporate     | 1.0 |
    | CCR-ALPHA-2  | CP-PENSION-01  | pension_scheme      | corporate     | 1.0 |
    | CCR-ALPHA-3  | CP-FIN-01      | financial           | institution   | 1.4 |

    CCR-ALPHA-3 is the anti-degenerate control: it reproduces the live CCR-A1
    EAD (institution CQS 2, α=1.4, RW=50%) and confirms that the unfixed
    pipeline would erroneously apply α=1.4 to all three rows.

Hand-calculated EAD (anchored to tests/expected_outputs/ccr/CCR-A1.json):
    RC    = max(0 - 0, 0) = 0                                (Art. 275(1))
    PFE multiplier = 1.0  (V-C = 0 → not under-collateralised)
    addon_aggregate = 3_914_298.228  (SF_IR=0.005, 10y tenor)
    pfe_addon       = 1.0 × 3_914_298.228 = 3_914_298.228

    CCR-ALPHA-1 (non_financial, α=1.0):
        EAD = 1.0 × (0 + 3_914_298.228) = 3_914_298.228  ← P828_EAD_CARVE_OUT
    CCR-ALPHA-2 (pension_scheme, α=1.0):
        EAD = 1.0 × (0 + 3_914_298.228) = 3_914_298.228  ← P828_EAD_CARVE_OUT
    CCR-ALPHA-3 (financial, α=1.4):
        EAD = 1.4 × (0 + 3_914_298.228) = 5_480_017.519  ← P828_EAD_FINANCIAL
        RWA = 5_480_017.519 × 0.50 = 2_740_008.759        ← live CCR-A1 rwa_final

    Canary assertion: ead(ALPHA-1) < ead(ALPHA-3) STRICT — if the engine
    still applies α=1.4 uniformly, all three will equal 5_480_017.519.

Load-bearing assertions for test-writer:
    1.  ead(ALPHA-1) == ead(ALPHA-2)                  rel=1e-9
    2.  ead(ALPHA-1) < ead(ALPHA-3)                   STRICT (canary)
    3.  ead(ALPHA-1) / ead(ALPHA-3) ≈ 1.0/1.4         rel=1e-9
    4.  alpha_applied(ALPHA-1) == 1.0                 exact
    5.  alpha_applied(ALPHA-3) == 1.4                 exact
    6.  pfe_addon ≈ 3_914_298.228 all three            rel=1e-6
    7.  rwa_final(ALPHA-3) ≈ 2_740_008.759             rel=1e-6

Keyed-join guard:
    ``build_p828_two_counterparty_book()`` provides a 2-CP, 2-NS, 2-trade
    bundle (one non_financial + one financial) to regression-guard the
    counterparty→NS join against cross-join fan-out (4 rows instead of 2).

Schema-strictness finding:
    ``enforce_schema`` in ``loader.py`` uses ``with_columns`` (not ``select``),
    so extra columns on an in-memory LazyFrame are NOT dropped.  The
    ``counterparty_type`` column added here via ``pl.lit(...).alias("counterparty_type")``
    will survive through the CCR pipeline as-is.  No schema-select barrier
    exists in the Python-bundle path (fixture → PipelineOrchestrator.run_with_data
    feeds the bundle directly, bypassing the file-based loader entirely).
    This builder is therefore schema-safe for the engine-implementer's join.

Exported public names
---------------------
    P828_CP_NFC_REF         : str — "CP-NFC-01"
    P828_CP_PENSION_REF     : str — "CP-PENSION-01"
    P828_CP_FIN_REF         : str — "CP-FIN-01"
    P828_NS_NFC_ID          : str — "NS-NFC-01"
    P828_NS_PENSION_ID      : str — "NS-PENSION-01"
    P828_NS_FIN_ID          : str — "NS-FIN-01"
    P828_TRADE_NFC_ID       : str — "T-NFC-01"
    P828_TRADE_PENSION_ID   : str — "T-PENSION-01"
    P828_TRADE_FIN_ID       : str — "T-FIN-01"
    P828_CP_TYPE_NON_FINANCIAL   : str — "non_financial"
    P828_CP_TYPE_PENSION         : str — "pension_scheme"
    P828_CP_TYPE_FINANCIAL       : str — "financial"
    P828_PFE_ADDON               : float — 3_914_298.228
    P828_EAD_CARVE_OUT           : float — 3_914_298.228  (α=1.0 scenarios)
    P828_EAD_FINANCIAL           : float — 5_480_017.519  (α=1.4 control)
    P828_ALPHA_CARVE_OUT         : float — 1.0
    P828_ALPHA_STANDARD          : float — 1.4
    P828_RATIO                   : float — 1.0 / 1.4  ≈ 0.714286
    P828_INSTITUTION_CQS         : int — 2  (CQS for CP-FIN-01; RW=50%)
    P828_ANTI_DEGENERATE_RW      : float — 0.50
    P828_RWA_FINANCIAL           : float — 2_740_008.759

    build_p828_bundle(counterparty_type: str) -> RawDataBundle
        Full orchestrator-ready bundle.  Accepted counterparty_type values:
          "non_financial"  → CCR-ALPHA-1  (CP-NFC-01, corporate, α=1.0)
          "pension_scheme" → CCR-ALPHA-2  (CP-PENSION-01, corporate, α=1.0)
          "financial"      → CCR-ALPHA-3  (CP-FIN-01, institution CQS 2, α=1.4)

    build_p828_two_counterparty_book() -> RawDataBundle
        2-counterparty, 2-NS, 2-trade bundle: one non_financial + one financial.
        Regression-guards the keyed counterparty→NS alpha join.

    save_p828_fixtures() -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - CRR Art. 274(2) — EAD = α × (RC + PFE); α=1.4 default
    - CRR Art. 274(2) second sub-paragraph — α=1.0 for EMIR non-financial / pension
    - EMIR Art. 2(9) — non-financial counterparty definition
    - EMIR Art. 2(10) — pension scheme arrangement definition
    - BCBS CRE52.1 — supervisory α=1.4 (1.0 carve-out for qualifying CPs)
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW
    - tests/expected_outputs/ccr/CCR-A1.json — authoritative EAD / RWA anchors
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
# Counterparty references.
# ---------------------------------------------------------------------------

#: Non-financial counterparty — CCR-ALPHA-1 (EMIR Art. 2(9) carve-out, α=1.0).
P828_CP_NFC_REF: str = "CP-NFC-01"

#: Pension-scheme counterparty — CCR-ALPHA-2 (EMIR Art. 2(10) carve-out, α=1.0).
P828_CP_PENSION_REF: str = "CP-PENSION-01"

#: Financial counterparty — CCR-ALPHA-3 (standard α=1.4, anti-degenerate control).
P828_CP_FIN_REF: str = "CP-FIN-01"

# ---------------------------------------------------------------------------
# Netting-set and trade identifiers (one per scenario).
# ---------------------------------------------------------------------------

P828_NS_NFC_ID: str = "NS-NFC-01"
P828_NS_PENSION_ID: str = "NS-PENSION-01"
P828_NS_FIN_ID: str = "NS-FIN-01"

P828_TRADE_NFC_ID: str = "T-NFC-01"
P828_TRADE_PENSION_ID: str = "T-PENSION-01"
P828_TRADE_FIN_ID: str = "T-FIN-01"

# ---------------------------------------------------------------------------
# counterparty_type string constants (mirrors the COLUMN_VALUE_CONSTRAINTS set
# that engine-implementer will add to schemas.py).
# ---------------------------------------------------------------------------

#: α=1.0 carve-out — EMIR Art. 2(9) non-financial counterparty.
P828_CP_TYPE_NON_FINANCIAL: str = "non_financial"

#: α=1.0 carve-out — EMIR Art. 2(10) pension-scheme arrangement.
P828_CP_TYPE_PENSION: str = "pension_scheme"

#: Standard α=1.4 — financial counterparty (default).
P828_CP_TYPE_FINANCIAL: str = "financial"

# ---------------------------------------------------------------------------
# Economic constants — anchored to tests/expected_outputs/ccr/CCR-A1.json.
# ---------------------------------------------------------------------------

#: PFE add-on (pfe_multiplier=1.0 × addon_aggregate=3_914_298.228).
#: All three scenarios share this value (same trade economics).
P828_PFE_ADDON: float = 3_914_298.228

#: EAD for α=1.0 carve-out scenarios (CCR-ALPHA-1, CCR-ALPHA-2).
#: EAD = 1.0 × (RC=0 + pfe_addon) = 3_914_298.228
P828_EAD_CARVE_OUT: float = 3_914_298.228  # = P828_PFE_ADDON (RC=0)

#: EAD for α=1.4 financial counterparty (CCR-ALPHA-3, anti-degenerate control).
#: EAD = 1.4 × (RC=0 + pfe_addon) = 5_480_017.519  — equals live CCR-A1 ead_ccr.
P828_EAD_FINANCIAL: float = 5_480_017.519

#: Supervisory alpha carve-out value (non-financial / pension / pension-default-comp).
P828_ALPHA_CARVE_OUT: float = 1.0

#: Standard supervisory alpha (CRR Art. 274(2), BCBS CRE52.1).
P828_ALPHA_STANDARD: float = 1.4

#: EAD ratio: carve-out / standard = 1.0 / 1.4 ≈ 0.714286.
P828_RATIO: float = P828_ALPHA_CARVE_OUT / P828_ALPHA_STANDARD

#: Institution CQS for the financial control counterparty (CRR Art. 120(1) Table 3 → 50% RW).
P828_INSTITUTION_CQS: int = CCR_A1_RATING_CQS  # 2

#: SA risk weight for the financial control (institution CQS 2 → 50%).
P828_ANTI_DEGENERATE_RW: float = 0.50

#: Expected RWA for the financial control: EAD_FINANCIAL × 0.50 = 2_740_008.759.
P828_RWA_FINANCIAL: float = 2_740_008.759

# ---------------------------------------------------------------------------
# Private helpers — scenario-specific counterparty / entity-type mapping.
# ---------------------------------------------------------------------------

_CARVE_OUT_TYPES: frozenset[str] = frozenset({P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_PENSION})

_SCENARIO_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # counterparty_type → (cp_ref, ns_id, trade_id, entity_type, name)
    P828_CP_TYPE_NON_FINANCIAL: (
        P828_CP_NFC_REF,
        P828_NS_NFC_ID,
        P828_TRADE_NFC_ID,
        "corporate",
        "Non-Financial Corporate (EMIR Art. 2(9))",
    ),
    P828_CP_TYPE_PENSION: (
        P828_CP_PENSION_REF,
        P828_NS_PENSION_ID,
        P828_TRADE_PENSION_ID,
        "corporate",
        "Pension Scheme (EMIR Art. 2(10))",
    ),
    P828_CP_TYPE_FINANCIAL: (
        P828_CP_FIN_REF,
        P828_NS_FIN_ID,
        P828_TRADE_FIN_ID,
        "institution",
        "Financial Institution (CQS 2, α=1.4 control)",
    ),
}


def _build_counterparty(counterparty_type: str) -> pl.DataFrame:
    """
    Return a single-row counterparty DataFrame with the ``counterparty_type`` column.

    The base columns are typed via ``dtypes_of(COUNTERPARTY_SCHEMA)``; the
    ``counterparty_type`` literal is appended with ``with_columns`` (identical
    to the ``is_qccp`` pattern in p839_ccp_builder).

    ``counterparty_type`` is not yet in COUNTERPARTY_SCHEMA (that schema
    addition is engine-implementer's job).  The column is carried as an extra
    literal and will survive through PipelineOrchestrator.run_with_data because
    ``enforce_schema`` uses ``with_columns`` — it does NOT issue a ``select``
    that would drop unknown columns.

    institution_cqs is populated for the financial control (CQS 2 → 50% RW
    per CRR Art. 120(1) Table 3) and left null for the two corporate carve-out
    counterparties (they receive the corporate SA risk weight).
    """
    if counterparty_type not in _SCENARIO_MAP:
        raise ValueError(
            f"Unknown counterparty_type {counterparty_type!r}; "
            f"must be one of {sorted(_SCENARIO_MAP)}"
        )
    cp_ref, _ns_id, _trade_id, entity_type, name = _SCENARIO_MAP[counterparty_type]

    is_financial = counterparty_type == P828_CP_TYPE_FINANCIAL
    institution_cqs: int | None = P828_INSTITUTION_CQS if is_financial else None

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


def _build_trade(trade_id: str, netting_set_id: str) -> pl.DataFrame:
    """Return a single-row trades DataFrame using CCR-A1 golden economics."""
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
    return create_trades([trade])


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
    """Return a zero-row CCR-collateral DataFrame (CCR-ALPHA: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_raw_ccr_bundle(trades_df: pl.DataFrame, netting_sets_df: pl.DataFrame) -> RawCCRBundle:
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


def build_p828_bundle(counterparty_type: str) -> RawDataBundle:
    """
    Build a complete orchestrator-ready RawDataBundle for one P8.28 scenario.

    All three scenarios share CCR-A1 trade economics (10y GBP IR swap,
    GBP 100m notional, MtM=0, delta=1.0, unmargined, no collateral).
    They differ only in the ``counterparty_type`` column on the counterparty
    frame, which the engine-implementer will join onto the NS frame to select
    the per-row α scalar.

    Args:
        counterparty_type: One of "non_financial", "pension_scheme", "financial".
            "non_financial" → CCR-ALPHA-1 (CP-NFC-01, corporate, α=1.0)
            "pension_scheme" → CCR-ALPHA-2 (CP-PENSION-01, corporate, α=1.0)
            "financial"     → CCR-ALPHA-3 (CP-FIN-01, institution CQS 2, α=1.4)

    Returns:
        Complete RawDataBundle suitable for PipelineOrchestrator.run_with_data.

    Raises:
        ValueError: If counterparty_type is not one of the three known values.

    Usage::

        from tests.fixtures.ccr.p828_alpha_builder import build_p828_bundle
        # CCR-ALPHA-1: non-financial carve-out
        data_alpha1 = build_p828_bundle("non_financial")
        # CCR-ALPHA-2: pension-scheme carve-out
        data_alpha2 = build_p828_bundle("pension_scheme")
        # CCR-ALPHA-3: financial control (α=1.4)
        data_alpha3 = build_p828_bundle("financial")
        result = pipeline_orchestrator.run_with_data(data_alpha1, config)

    References:
        - CRR Art. 274(2) — α=1.4 default, 1.0 carve-out
        - EMIR Art. 2(9) — non-financial counterparty
        - EMIR Art. 2(10) — pension scheme arrangement
    """
    if counterparty_type not in _SCENARIO_MAP:
        raise ValueError(
            f"Unknown counterparty_type {counterparty_type!r}; "
            f"must be one of {sorted(_SCENARIO_MAP)}"
        )
    cp_ref, ns_id, trade_id, _entity_type, _name = _SCENARIO_MAP[counterparty_type]

    counterparty_df = _build_counterparty(counterparty_type)
    trades_df = _build_trade(trade_id, ns_id)
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


def build_p828_two_counterparty_book() -> RawDataBundle:
    """
    Build a 2-counterparty, 2-NS, 2-trade bundle for keyed-join regression testing.

    Purpose:
        A single-trade / single-NS fixture (1×1×1) passes under either a cross-join
        or a keyed join in the counterparty→NS alpha lookup.  This 2-counterparty
        book has two CPs, two NSs, and two trades so that a cross-join fan-out
        would produce 4 rows instead of 2.  Test-writer can assert:
            result.height == 2
        to pin the keyed-join invariant.

    Composition:
        CP-NFC-01   (non_financial, corporate)    — NS-NFC-01    — T-NFC-01
        CP-FIN-01   (financial,     institution)  — NS-FIN-01    — T-FIN-01

    Expected per-row alpha_applied after the engine-implementer's join:
        NS-NFC-01:  alpha_applied = 1.0  (non-financial carve-out)
        NS-FIN-01:  alpha_applied = 1.4  (financial default)

    References:
        - CRR Art. 274(2) — α per counterparty_type
        - EMIR Art. 2(9) — non-financial counterparty (α=1.0)
    """
    nfc_cp = _build_counterparty(P828_CP_TYPE_NON_FINANCIAL)
    fin_cp = _build_counterparty(P828_CP_TYPE_FINANCIAL)
    counterparties_df = pl.concat([nfc_cp, fin_cp])

    nfc_trade = _build_trade(P828_TRADE_NFC_ID, P828_NS_NFC_ID)
    fin_trade = _build_trade(P828_TRADE_FIN_ID, P828_NS_FIN_ID)
    trades_df = pl.concat([nfc_trade, fin_trade])

    nfc_ns = _build_netting_set(P828_NS_NFC_ID, P828_CP_NFC_REF)
    fin_ns = _build_netting_set(P828_NS_FIN_ID, P828_CP_FIN_REF)
    netting_sets_df = pl.concat([nfc_ns, fin_ns])

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


def save_p828_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all P8.28 bundles and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as p839_ccp_builder.py).  All load-bearing invariants are validated; raises
    ``AssertionError`` with a descriptive message if any is violated.

    Invariants checked (single-counterparty bundles):
        1.  All three bundles: ccr not None.
        2.  Each bundle: 1 trade row; correct trade_id.
        3.  Each bundle: 1 netting-set row; correct netting_set_id.
        4.  Each bundle: 1 counterparty row; counterparty_type column present.
        5.  CCR-ALPHA-1: counterparty_type == "non_financial"; entity_type == "corporate".
        6.  CCR-ALPHA-2: counterparty_type == "pension_scheme"; entity_type == "corporate".
        7.  CCR-ALPHA-3: counterparty_type == "financial"; entity_type == "institution";
            institution_cqs == P828_INSTITUTION_CQS.
        8.  Each bundle: 0 margin-agreement rows; 0 CCR-collateral rows.

    Invariants checked (2-counterparty book):
        9.  2 counterparty rows; both counterparty_type values present.
        10. 2 trade rows; 2 netting-set rows.
        11. No duplicate netting_set_ids (cross-join fan-out guard).
        12. 0 margin-agreement rows; 0 CCR-collateral rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    scenarios = [
        (
            P828_CP_TYPE_NON_FINANCIAL,
            "CCR-ALPHA-1",
            P828_CP_NFC_REF,
            P828_NS_NFC_ID,
            P828_TRADE_NFC_ID,
            "corporate",
        ),
        (
            P828_CP_TYPE_PENSION,
            "CCR-ALPHA-2",
            P828_CP_PENSION_REF,
            P828_NS_PENSION_ID,
            P828_TRADE_PENSION_ID,
            "corporate",
        ),
        (
            P828_CP_TYPE_FINANCIAL,
            "CCR-ALPHA-3",
            P828_CP_FIN_REF,
            P828_NS_FIN_ID,
            P828_TRADE_FIN_ID,
            "institution",
        ),
    ]
    for (
        cp_type,
        scenario,
        expected_cp_ref,
        expected_ns_id,
        expected_trade_id,
        expected_entity,
    ) in scenarios:
        bundle = build_p828_bundle(cp_type)
        _check_p828_single(
            bundle,
            scenario=scenario,
            expected_cp_ref=expected_cp_ref,
            expected_ns_id=expected_ns_id,
            expected_trade_id=expected_trade_id,
            expected_cp_type=cp_type,
            expected_entity_type=expected_entity,
        )

    book = build_p828_two_counterparty_book()
    _check_p828_two_cp(book)

    return [("(python-only builder — no parquet)", 0)]


def _check_p828_single(
    bundle: RawDataBundle,
    scenario: str,
    expected_cp_ref: str,
    expected_ns_id: str,
    expected_trade_id: str,
    expected_cp_type: str,
    expected_entity_type: str,
) -> None:
    """Verify invariants for a single-counterparty P8.28 bundle."""
    if bundle.ccr is None:
        raise AssertionError(f"P8.28 {scenario}: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()

    # Trade checks.
    if trades_df.height != 1:
        raise AssertionError(f"P8.28 {scenario}: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != expected_trade_id:
        raise AssertionError(
            f"P8.28 {scenario}: trade_id must be {expected_trade_id!r} "
            f"(got {trades_df['trade_id'][0]!r})"
        )

    # Netting-set checks.
    if ns_df.height != 1:
        raise AssertionError(f"P8.28 {scenario}: expected 1 NS row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != expected_ns_id:
        raise AssertionError(
            f"P8.28 {scenario}: netting_set_id must be {expected_ns_id!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["counterparty_reference"][0] != expected_cp_ref:
        raise AssertionError(
            f"P8.28 {scenario}: NS counterparty_reference must be {expected_cp_ref!r} "
            f"(got {ns_df['counterparty_reference'][0]!r})"
        )

    # Counterparty checks.
    if cp_df.height != 1:
        raise AssertionError(f"P8.28 {scenario}: expected 1 counterparty row, got {cp_df.height}")
    if "counterparty_type" not in cp_df.columns:
        raise AssertionError(
            f"P8.28 {scenario}: counterparty_type column must be present on counterparty frame"
        )
    if cp_df["counterparty_type"][0] != expected_cp_type:
        raise AssertionError(
            f"P8.28 {scenario}: counterparty_type must be {expected_cp_type!r} "
            f"(got {cp_df['counterparty_type'][0]!r})"
        )
    if cp_df["entity_type"][0] != expected_entity_type:
        raise AssertionError(
            f"P8.28 {scenario}: entity_type must be {expected_entity_type!r} "
            f"(got {cp_df['entity_type'][0]!r})"
        )
    if (
        expected_cp_type == P828_CP_TYPE_FINANCIAL
        and cp_df["institution_cqs"][0] != P828_INSTITUTION_CQS
    ):
        raise AssertionError(
            f"P8.28 {scenario}: institution_cqs must be {P828_INSTITUTION_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )

    # Empty frame checks.
    if margin_df.height != 0:
        raise AssertionError(
            f"P8.28 {scenario}: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(
            f"P8.28 {scenario}: ccr_collateral must be empty (got {coll_df.height})"
        )


def _check_p828_two_cp(bundle: RawDataBundle) -> None:
    """Verify invariants for the 2-counterparty regression book."""
    if bundle.ccr is None:
        raise AssertionError("P8.28 2-CP book: bundle.ccr must not be None")

    cp_df = bundle.counterparties.collect()
    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()

    if cp_df.height != 2:
        raise AssertionError(f"P8.28 2-CP book: expected 2 counterparty rows, got {cp_df.height}")

    if "counterparty_type" not in cp_df.columns:
        raise AssertionError("P8.28 2-CP book: counterparty_type column must be present")

    cp_types = set(cp_df["counterparty_type"].to_list())
    for expected_type in [P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_FINANCIAL]:
        if expected_type not in cp_types:
            raise AssertionError(
                f"P8.28 2-CP book: counterparty_type {expected_type!r} not found in {cp_types}"
            )

    if trades_df.height != 2:
        raise AssertionError(f"P8.28 2-CP book: expected 2 trade rows, got {trades_df.height}")
    if ns_df.height != 2:
        raise AssertionError(f"P8.28 2-CP book: expected 2 netting-set rows, got {ns_df.height}")

    # Cross-join fan-out guard.
    ns_ids = ns_df["netting_set_id"].to_list()
    if len(ns_ids) != len(set(ns_ids)):
        raise AssertionError(
            f"P8.28 2-CP book: duplicate netting_set_id detected (cross-join fan-out?): {ns_ids}"
        )

    if margin_df.height != 0:
        raise AssertionError(
            f"P8.28 2-CP book: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(
            f"P8.28 2-CP book: ccr_collateral must be empty (got {coll_df.height})"
        )
