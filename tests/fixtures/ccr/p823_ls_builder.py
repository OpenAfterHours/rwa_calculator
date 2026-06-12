"""
P8.23 fixture: long-settlement transaction regression pin — CCR-LS-1 / CCR-LS-1-CTRL.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_ls_invariant.py)
    -> NO engine change required (flag is inert under SA-CCR)

Scenario design:
    Two orchestrator-ready RawDataBundles that are byte-identical in every economic
    parameter, differing ONLY in the ``is_long_settlement`` flag on the single trade.
    The load-bearing assertion is:

        EAD(is_long_settlement=True) == EAD(is_long_settlement=False)

    This regression pin documents and enforces the deliberate no-op decision.

    | Scenario        | is_long_settlement | Notes                                 |
    |-----------------|--------------------|---------------------------------------|
    | CCR-LS-1        | True               | long-settlement trade per Art. 272(2) |
    | CCR-LS-1-CTRL   | False              | matched control (identical economics) |

Regulatory basis for the no-op decision:
    CRR Art. 271 — long-settlement transactions MAY use Chapter 6 (SA-CCR) instead
    of Chapter 4. Art. 271 grants an election; it does not prescribe a bespoke MPOR.

    CRR Art. 272(2) — defines a long-settlement transaction as one whose settlement
    is contractually later than the lower of: (a) market standard for the instrument
    type, and (b) 5 business days after trade date.  The flag records this status
    but carries no SA-CCR formula consequence.

    CRR Art. 285 — prescribes MPOR floors (5 / 10 / 20 BD) keyed solely on the
    NETTING-SET margining status (unmargined / margined / dispute-prone).  Long
    settlement is not mentioned.  Unmargined netting sets always take the
    Art. 279c(1) maturity factor: MF = sqrt(min(M, 1y) / 1y).

    Conclusion: ``is_long_settlement`` is INERT under SA-CCR.  An acceptance test
    verifying EAD(LS=True) == EAD(LS=False) for identical economics constitutes a
    sufficient regression pin for this policy decision.

Trade economics (reused from CCR-A1 golden path):
    asset_class        = "interest_rate"
    transaction_type   = "derivative"
    notional           = GBP 100m
    currency           = "GBP"
    start_date         = 2026-01-15
    maturity_date      = 2026-04-15   (3-month tenor — interior MF, no floor binding)
    delta              = 1.0
    is_long            = True
    mtm_value          = 0.0 (at-par)

    The short 3-month tenor is chosen so that:
        M = maturity_date - calculation_date = a few months < 1y
        MF = sqrt(M / 1y)  — a clean interior value well within the unmargined path
    The exact MF value is irrelevant for the invariant: both bundles share it.

Netting set (CCR-A1 shape — unmargined, legally enforceable):
    is_margined            = False
    is_legally_enforceable = True

Counterparty:
    entity_type     = "institution"   (matches CCR-A1 CP_001)
    institution_cqs = 2               (CRR Art. 120(1) Table 3 → 50% RW)
    country_code    = "GB"

Exported public names
---------------------
    P823_TRADE_LS_ID        : str — "T-LS-001"       (CCR-LS-1, is_long_settlement=True)
    P823_TRADE_CTRL_ID      : str — "T-LS-CTRL-001"  (CCR-LS-1-CTRL, is_long_settlement=False)
    P823_NS_LS_ID           : str — "NS-LS-001"
    P823_NS_CTRL_ID         : str — "NS-LS-CTRL-001"
    P823_CP_REF             : str — "CP-LS-001"
    P823_NOTIONAL           : float — 100_000_000.0
    P823_CURRENCY           : str — "GBP"
    P823_START_DATE         : date — 2026-01-15
    P823_MATURITY_DATE      : date — 2026-04-15
    P823_INSTITUTION_CQS    : int — 2

    build_p823_bundle(is_long_settlement: bool) -> RawDataBundle
        Full orchestrator-ready bundle.
        is_long_settlement=True  → CCR-LS-1      (T-LS-001)
        is_long_settlement=False → CCR-LS-1-CTRL (T-LS-CTRL-001)
        The two bundles are economically identical: the only difference is the
        trade_id and the is_long_settlement flag.

    save_p823_fixtures() -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - CRR Art. 271 — long-settlement transactions may use SA-CCR
    - CRR Art. 272(2) — long-settlement transaction definition
    - CRR Art. 279c(1) — unmargined maturity factor MF = sqrt(min(M,1y)/1y)
    - CRR Art. 285 — MPOR floors (no mention of long-settlement)
    - tests/fixtures/ccr/golden_ccr_a1.py — CCR-A1 economics reference
    - tests/expected_outputs/ccr/CCR-A1.json — authoritative EAD / RWA anchors
"""

from __future__ import annotations

from datetime import date

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
    CCR_A1_RATING_AGENCY,
    CCR_A1_RATING_CQS,
    CCR_A1_RATING_DATE,
    CCR_A1_RATING_TYPE,
    CCR_A1_RATING_VALUE,
)
from .margin_builder import create_margin_agreements
from .netting_set_builder import create_netting_sets, make_netting_set
from .trade_builder import create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario identifiers — one per variant.
# ---------------------------------------------------------------------------

#: Trade ID for the long-settlement trade (CCR-LS-1, is_long_settlement=True).
P823_TRADE_LS_ID: str = "T-LS-001"

#: Trade ID for the matched control trade (CCR-LS-1-CTRL, is_long_settlement=False).
P823_TRADE_CTRL_ID: str = "T-LS-CTRL-001"

#: Netting-set ID for the long-settlement scenario.
P823_NS_LS_ID: str = "NS-LS-001"

#: Netting-set ID for the matched control scenario.
P823_NS_CTRL_ID: str = "NS-LS-CTRL-001"

#: Shared counterparty reference (both bundles use the same counterparty).
P823_CP_REF: str = "CP-LS-001"

# ---------------------------------------------------------------------------
# Shared economic constants — identical across both variants.
# ---------------------------------------------------------------------------

#: Notional: GBP 100m (CCR-A1 canonical value).
P823_NOTIONAL: float = 100_000_000.0

#: Currency: GBP (CCR-A1 canonical value).
P823_CURRENCY: str = "GBP"

#: Trade start date (CCR-A1 canonical start date).
P823_START_DATE: date = date(2026, 1, 15)

#: Maturity date: 3-month tenor.  Short tenor chosen so MF is an interior value
#: well within the unmargined Art. 279c(1) path; the floor does not bind.
P823_MATURITY_DATE: date = date(2026, 4, 15)

#: Institution CQS — CRR Art. 120(1) Table 3: CQS 2 → 50% SA risk weight.
P823_INSTITUTION_CQS: int = CCR_A1_RATING_CQS  # 2


# ---------------------------------------------------------------------------
# Private helpers.
# ---------------------------------------------------------------------------


def _build_counterparty() -> pl.DataFrame:
    """Return a single-row counterparty DataFrame (institution CQS 2, GB)."""
    row = {
        "counterparty_reference": P823_CP_REF,
        "counterparty_name": "P8.23 Long-Settlement Test Institution (CQS 2)",
        "entity_type": "institution",
        "country_code": "GB",
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": None,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": P823_INSTITUTION_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def _build_rating() -> pl.LazyFrame:
    """Return a one-row external ratings LazyFrame for CP-LS-001 (CQS 2, S&P A)."""
    row = {
        "rating_reference": "RTG-LS-001",
        "counterparty_reference": P823_CP_REF,
        "rating_type": CCR_A1_RATING_TYPE,
        "rating_agency": CCR_A1_RATING_AGENCY,
        "rating_value": CCR_A1_RATING_VALUE,
        "cqs": P823_INSTITUTION_CQS,
        "pd": None,
        "rating_date": CCR_A1_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_trade(trade_id: str, netting_set_id: str, is_long_settlement: bool) -> pl.DataFrame:
    """
    Return a single-row trades DataFrame.

    All economic parameters are identical between the two variants.  The ONLY
    differences are ``trade_id``, ``netting_set_id``, and ``is_long_settlement``.
    """
    trade = make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        asset_class="interest_rate",
        transaction_type="derivative",
        notional=P823_NOTIONAL,
        currency=P823_CURRENCY,
        maturity_date=P823_MATURITY_DATE,
        start_date=P823_START_DATE,
        delta=1.0,
        is_long=True,
        mtm_value=0.0,
        is_long_settlement=is_long_settlement,
    )
    return create_trades([trade])


def _build_netting_set(netting_set_id: str) -> pl.DataFrame:
    """Return a single-row netting-sets DataFrame (unmargined, legally enforceable)."""
    ns = make_netting_set(
        netting_set_id=netting_set_id,
        counterparty_reference=P823_CP_REF,
        is_legally_enforceable=True,
        is_margined=False,
    )
    return create_netting_sets([ns])


def _build_raw_ccr_bundle(trades_df: pl.DataFrame, netting_sets_df: pl.DataFrame) -> RawCCRBundle:
    """Wrap DataFrames into a RawCCRBundle with empty margin and collateral frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=trades_df.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets_df.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()
        ),
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
# Public bundle factory.
# ---------------------------------------------------------------------------


def build_p823_bundle(is_long_settlement: bool) -> RawDataBundle:
    """
    Build a complete orchestrator-ready RawDataBundle for one P8.23 scenario.

    The two bundles (is_long_settlement=True and False) are economically identical
    in every field except ``trade_id``, ``netting_set_id``, and ``is_long_settlement``.
    Passing both through the SA-CCR pipeline and asserting equal EAD is the
    regression pin for the policy decision that ``is_long_settlement`` is INERT
    under CRR Art. 279c(1) (unmargined maturity factor).

    Args:
        is_long_settlement:
            True  → CCR-LS-1      (T-LS-001, NS-LS-001):
                     trade.is_long_settlement == True
            False → CCR-LS-1-CTRL (T-LS-CTRL-001, NS-LS-CTRL-001):
                     trade.is_long_settlement == False

    Returns:
        Complete RawDataBundle suitable for PipelineOrchestrator.run_with_data.

    Regulatory references:
        - CRR Art. 271 — SA-CCR election for long-settlement transactions
        - CRR Art. 272(2) — long-settlement transaction definition
        - CRR Art. 279c(1) — MF = sqrt(min(M,1y)/1y) for unmargined NS
        - CRR Art. 285 — MPOR floors keyed on margining, NOT long-settlement
    """
    if is_long_settlement:
        trade_id = P823_TRADE_LS_ID
        ns_id = P823_NS_LS_ID
    else:
        trade_id = P823_TRADE_CTRL_ID
        ns_id = P823_NS_CTRL_ID

    counterparty_df = _build_counterparty()
    trades_df = _build_trade(trade_id, ns_id, is_long_settlement)
    netting_sets_df = _build_netting_set(ns_id)
    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=counterparty_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=_build_rating(),
        ccr=_build_raw_ccr_bundle(trades_df, netting_sets_df),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p823_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check both P8.23 bundles and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as p828_alpha_builder.py and p839_ccp_builder.py).

    Invariants verified:
        1.  Both bundles: bundle.ccr is not None.
        2.  Both bundles: exactly 1 trade row, 1 netting-set row, 1 counterparty row.
        3.  CCR-LS-1:      trade_id == P823_TRADE_LS_ID,   ns_id == P823_NS_LS_ID.
        4.  CCR-LS-1-CTRL: trade_id == P823_TRADE_CTRL_ID, ns_id == P823_NS_CTRL_ID.
        5.  CCR-LS-1:      trade.is_long_settlement == True.
        6.  CCR-LS-1-CTRL: trade.is_long_settlement == False.
        7.  Both bundles share the same counterparty reference (CP-LS-001).
        8.  Load-bearing parity: every field on trades_df EXCEPT trade_id,
            netting_set_id, and is_long_settlement is identical between the two
            variants.  This is the invariant the acceptance test depends on.
        9.  Both bundles: 0 margin-agreement rows, 0 CCR-collateral rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    bundle_ls = build_p823_bundle(is_long_settlement=True)
    bundle_ctrl = build_p823_bundle(is_long_settlement=False)

    _check_p823_single(
        bundle_ls,
        scenario="CCR-LS-1",
        expected_trade_id=P823_TRADE_LS_ID,
        expected_ns_id=P823_NS_LS_ID,
        expected_is_ls=True,
    )
    _check_p823_single(
        bundle_ctrl,
        scenario="CCR-LS-1-CTRL",
        expected_trade_id=P823_TRADE_CTRL_ID,
        expected_ns_id=P823_NS_CTRL_ID,
        expected_is_ls=False,
    )
    _check_p823_parity(bundle_ls, bundle_ctrl)

    return [("(python-only builder — no parquet)", 0)]


def _check_p823_single(
    bundle: RawDataBundle,
    scenario: str,
    expected_trade_id: str,
    expected_ns_id: str,
    expected_is_ls: bool,
) -> None:
    """Verify structural invariants for a single P8.23 bundle."""
    if bundle.ccr is None:
        raise AssertionError(f"P8.23 {scenario}: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()

    # Trade row count and identity.
    if trades_df.height != 1:
        raise AssertionError(f"P8.23 {scenario}: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != expected_trade_id:
        raise AssertionError(
            f"P8.23 {scenario}: trade_id must be {expected_trade_id!r} "
            f"(got {trades_df['trade_id'][0]!r})"
        )

    # is_long_settlement flag.
    actual_ls = trades_df["is_long_settlement"][0]
    if actual_ls != expected_is_ls:
        raise AssertionError(
            f"P8.23 {scenario}: is_long_settlement must be {expected_is_ls!r} (got {actual_ls!r})"
        )

    # Netting-set row count and identity.
    if ns_df.height != 1:
        raise AssertionError(f"P8.23 {scenario}: expected 1 netting-set row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != expected_ns_id:
        raise AssertionError(
            f"P8.23 {scenario}: netting_set_id must be {expected_ns_id!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["counterparty_reference"][0] != P823_CP_REF:
        raise AssertionError(
            f"P8.23 {scenario}: NS counterparty_reference must be {P823_CP_REF!r} "
            f"(got {ns_df['counterparty_reference'][0]!r})"
        )

    # Counterparty row count and identity.
    if cp_df.height != 1:
        raise AssertionError(f"P8.23 {scenario}: expected 1 counterparty row, got {cp_df.height}")
    if cp_df["counterparty_reference"][0] != P823_CP_REF:
        raise AssertionError(
            f"P8.23 {scenario}: counterparty_reference must be {P823_CP_REF!r} "
            f"(got {cp_df['counterparty_reference'][0]!r})"
        )
    if cp_df["entity_type"][0] != "institution":
        raise AssertionError(
            f"P8.23 {scenario}: entity_type must be 'institution' (got {cp_df['entity_type'][0]!r})"
        )
    if cp_df["institution_cqs"][0] != P823_INSTITUTION_CQS:
        raise AssertionError(
            f"P8.23 {scenario}: institution_cqs must be {P823_INSTITUTION_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )

    # Empty frames.
    if margin_df.height != 0:
        raise AssertionError(
            f"P8.23 {scenario}: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(
            f"P8.23 {scenario}: ccr_collateral must be empty (got {coll_df.height})"
        )


def _check_p823_parity(bundle_ls: RawDataBundle, bundle_ctrl: RawDataBundle) -> None:
    """
    Verify that the two bundles are identical in every trade/NS field
    except trade_id, netting_set_id, and is_long_settlement.

    This is the load-bearing invariant: the acceptance test depends on the two
    bundles being economically equivalent so that EAD equality is guaranteed by
    construction, not coincidence.
    """
    trades_ls = bundle_ls.ccr.trades.trades.collect()  # type: ignore[union-attr]
    trades_ctrl = bundle_ctrl.ccr.trades.trades.collect()  # type: ignore[union-attr]

    # Fields that are allowed to differ between the two variants.
    excluded_cols = frozenset({"trade_id", "netting_set_id", "is_long_settlement"})

    # Every other field on the trades frame must be equal.
    for col in trades_ls.columns:
        if col in excluded_cols:
            continue
        val_ls = trades_ls[col][0]
        val_ctrl = trades_ctrl[col][0]
        if val_ls != val_ctrl:
            raise AssertionError(
                f"P8.23 parity: trade column {col!r} differs between CCR-LS-1 and CCR-LS-1-CTRL "
                f"(ls={val_ls!r}, ctrl={val_ctrl!r}); this would break the EAD invariant"
            )

    ns_ls = bundle_ls.ccr.netting_sets.netting_sets.collect()  # type: ignore[union-attr]
    ns_ctrl = bundle_ctrl.ccr.netting_sets.netting_sets.collect()  # type: ignore[union-attr]

    ns_excluded = frozenset({"netting_set_id"})
    for col in ns_ls.columns:
        if col in ns_excluded:
            continue
        val_ls = ns_ls[col][0]
        val_ctrl = ns_ctrl[col][0]
        if val_ls != val_ctrl:
            raise AssertionError(
                f"P8.23 parity: netting_set column {col!r} differs between CCR-LS-1 and CCR-LS-1-CTRL "
                f"(ls={val_ls!r}, ctrl={val_ctrl!r}); this would break the EAD invariant"
            )
