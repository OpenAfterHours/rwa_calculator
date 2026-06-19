"""
P8.49 fixture builder: default-fund-contribution capital stack (CRR Art. 308/309).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_p8_49_default_fund.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/default_fund.py — pipeline wiring)

Scenario design:
    Three independent DF-contribution rows, each exercising a distinct Art. 308/309
    regulatory branch.  All counterparty references are distinct (CCR-B2 / B3 / B4
    are independent scenarios that may also be combined into a 3-row portfolio).

    CCR-B2: QCCP pre-funded (Art. 308)
        DFC_B2  is_qccp_ccp=True
                K_CCP=50,000,000; DF_i=2,000,000; DF_CM=100,000,000
                K_CM = 50,000,000 × (2,000,000 / 100,000,000) = 1,000,000
                RWEA = 1,000,000 × 12.5 = 12,500,000
                regulatory_band = "dfc_qccp_prefunded"

    CCR-B3: non-QCCP pre-funded (Art. 309)
        DFC_B3  is_qccp_ccp=False, is_unfunded_commitment=False
                K_CCP=30,000,000; DF_i=1,500,000; DF_CM=60,000,000
                K_CM = 30,000,000 × (1,500,000 / 60,000,000) = 750,000
                RWEA = 750,000 × 12.5 = 9,375,000
                regulatory_band = "dfc_non_qccp_prefunded"

    CCR-B4: non-QCCP unfunded (Art. 309 unfunded)
        DFC_B4  is_qccp_ccp=False, is_unfunded_commitment=True
                K_CCP=20,000,000; DF_i=800,000; DF_CM=40,000,000
                K_CM = 20,000,000 × (800,000 / 40,000,000) = 400,000
                RWEA = 400,000 × 12.5 = 5,000,000
                regulatory_band = "dfc_non_qccp_unfunded"

    Portfolio total RWEA (B2 + B3 + B4) = 12,500,000 + 9,375,000 + 5,000,000 = 26,875,000

Module-level constants are the single source of truth for test-writer assertions.
No persistent parquet files are written — the test-writer imports these constants
and the builder functions directly.

DEPENDENCY NOTE:
    ``DF_CONTRIBUTION_SCHEMA`` does NOT yet exist in ``rwa_calc.data.schemas`` —
    the engine-implementer adds it in Wave 4.  This module defines the column dtypes
    directly (matching the proposal's schema table) so the builder is self-contained
    and importable before the engine wave lands.  Once ``DF_CONTRIBUTION_SCHEMA`` is
    added, this module may be updated to import and enforce it.

    ``RawCCRBundle.default_fund_contributions`` does NOT yet exist in
    ``contracts/bundles.py``.  Rather than constructing a RawCCRBundle with a
    non-existent field, this module returns the ``default_fund_contributions``
    LazyFrame SEPARATELY from the bundle (alongside a minimal RawCCRBundle with
    the standard 4 leaf-bundles).  The test-writer wires both together once the
    engine-implementer has landed the field.  This mirrors the note in the
    reviewer Wave 1 guidance.

References:
    - CRR Art. 308(2) (K_CCP hypothetical capital + K_CM allocation)
    - CRR Art. 308(3) (QCCP pre-funded own-funds → RWEA = K_CM × 12.5)
    - CRR Art. 309(1)/(2) (non-QCCP / unfunded treatment)
    - CRR Art. 92(3)(ca) (own_funds_to_rwa_factor = 12.5; pack value reused by engine)
    - BCBS CRE54.18-54.32
    - src/rwa_calc/data/schemas.py — FAILED_TRADE_SCHEMA (pattern reference)
    - src/rwa_calc/contracts/bundles.py — RawCCRBundle
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
)

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

# ---------------------------------------------------------------------------
# DF_CONTRIBUTION_SCHEMA column dtype dict.
# Defined here (not imported from rwa_calc.data.schemas) because the engine-
# implementer adds it in Wave 4.  Matches the proposal's §3 schema table exactly.
# ---------------------------------------------------------------------------

#: Column dtype mapping for ``default_fund_contributions`` LazyFrames.
#: Once ``DF_CONTRIBUTION_SCHEMA`` lands in ``data/schemas.py`` this can be
#: replaced with ``dtypes_of(DF_CONTRIBUTION_SCHEMA)`` and the dict removed.
DF_CONTRIBUTION_DTYPES: dict[str, PolarsDataType] = {
    "contribution_id": pl.String,
    "ccp_reference": pl.String,
    "is_qccp_ccp": pl.Boolean,
    "df_i_contribution_amount": pl.Float64,
    "df_cm_total_contributions": pl.Float64,
    "k_ccp_published": pl.Float64,
    "is_unfunded_commitment": pl.Boolean,
}

# ---------------------------------------------------------------------------
# Regulatory constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

#: CRR Art. 92(3)(ca) own_funds_to_rwa_factor = 12.5 (reused from pack).
#: Engine reads this from the rulepack; fixture constants reproduce it for
#: hand-calc verification only.
OWN_FUNDS_TO_RWA_FACTOR: float = 12.5

# ---------------------------------------------------------------------------
# CCR-B2: QCCP pre-funded (Art. 308)
# ---------------------------------------------------------------------------

DFC_B2_ID: str = "DFC_B2"
DFC_B2_CCP_REF: str = "CP_CCP_B2"
DFC_B2_IS_QCCP: bool = True
DFC_B2_IS_UNFUNDED: bool = False
DFC_B2_K_CCP: float = 50_000_000.0
DFC_B2_DF_I: float = 2_000_000.0
DFC_B2_DF_CM: float = 100_000_000.0

#: K_CM = K_CCP × (DF_i / DF_CM) per CRR Art. 308(2)
DFC_B2_K_CM: float = 1_000_000.0  # 50,000,000 × (2,000,000 / 100,000,000)

#: RWEA = K_CM × 12.5 per CRR Art. 308(3)
DFC_B2_RWEA: float = 12_500_000.0  # 1,000,000 × 12.5

DFC_B2_REGULATORY_BAND: str = "dfc_qccp_prefunded"

# ---------------------------------------------------------------------------
# CCR-B3: non-QCCP pre-funded (Art. 309)
# ---------------------------------------------------------------------------

DFC_B3_ID: str = "DFC_B3"
DFC_B3_CCP_REF: str = "CP_CCP_B3"
DFC_B3_IS_QCCP: bool = False
DFC_B3_IS_UNFUNDED: bool = False
DFC_B3_K_CCP: float = 30_000_000.0
DFC_B3_DF_I: float = 1_500_000.0
DFC_B3_DF_CM: float = 60_000_000.0

#: K_CM = 30,000,000 × (1,500,000 / 60,000,000) per CRR Art. 308(2)
DFC_B3_K_CM: float = 750_000.0

#: RWEA = K_CM × 12.5 per CRR Art. 309(2)
DFC_B3_RWEA: float = 9_375_000.0

DFC_B3_REGULATORY_BAND: str = "dfc_non_qccp_prefunded"

# ---------------------------------------------------------------------------
# CCR-B4: non-QCCP unfunded (Art. 309 unfunded)
# ---------------------------------------------------------------------------

DFC_B4_ID: str = "DFC_B4"
DFC_B4_CCP_REF: str = "CP_CCP_B4"
DFC_B4_IS_QCCP: bool = False
DFC_B4_IS_UNFUNDED: bool = True
DFC_B4_K_CCP: float = 20_000_000.0
DFC_B4_DF_I: float = 800_000.0
DFC_B4_DF_CM: float = 40_000_000.0

#: K_CM = 20,000,000 × (800,000 / 40,000,000) per CRR Art. 308(2)
DFC_B4_K_CM: float = 400_000.0

#: RWEA = K_CM × 12.5 per CRR Art. 309(2) unfunded
DFC_B4_RWEA: float = 5_000_000.0

DFC_B4_REGULATORY_BAND: str = "dfc_non_qccp_unfunded"

# ---------------------------------------------------------------------------
# Portfolio aggregate (B2 + B3 + B4).
# ---------------------------------------------------------------------------

#: Sum of RWEA for the combined B2 + B3 + B4 portfolio.
PORTFOLIO_TOTAL_RWEA: float = 26_875_000.0  # 12,500,000 + 9,375,000 + 5,000,000


# ---------------------------------------------------------------------------
# Dataclass — mirrors DF_CONTRIBUTION_SCHEMA field for field.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DFContribution:
    """
    One default-fund-contribution record (P8.49 CCR-B2/B3/B4).

    Fields mirror the ``DF_CONTRIBUTION_SCHEMA`` that the engine-implementer
    will add to ``src/rwa_calc/data/schemas.py``.

    References:
        - CRR Art. 308(2) (K_CCP + K_CM clearing-member allocation)
        - CRR Art. 308(3) (QCCP pre-funded: RWEA = K_CM × 12.5)
        - CRR Art. 309(1)/(2) (non-QCCP / unfunded: same arithmetic)
    """

    contribution_id: str
    ccp_reference: str
    is_qccp_ccp: bool
    df_i_contribution_amount: float
    df_cm_total_contributions: float
    k_ccp_published: float
    is_unfunded_commitment: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``pl.DataFrame`` construction."""
        return {
            "contribution_id": self.contribution_id,
            "ccp_reference": self.ccp_reference,
            "is_qccp_ccp": self.is_qccp_ccp,
            "df_i_contribution_amount": self.df_i_contribution_amount,
            "df_cm_total_contributions": self.df_cm_total_contributions,
            "k_ccp_published": self.k_ccp_published,
            "is_unfunded_commitment": self.is_unfunded_commitment,
        }


# ---------------------------------------------------------------------------
# Row factories — one per scenario.
# ---------------------------------------------------------------------------


def _dfc_b2() -> DFContribution:
    """DFC_B2: QCCP pre-funded, K_CCP=50m, DF_i=2m, DF_CM=100m."""
    return DFContribution(
        contribution_id=DFC_B2_ID,
        ccp_reference=DFC_B2_CCP_REF,
        is_qccp_ccp=DFC_B2_IS_QCCP,
        df_i_contribution_amount=DFC_B2_DF_I,
        df_cm_total_contributions=DFC_B2_DF_CM,
        k_ccp_published=DFC_B2_K_CCP,
        is_unfunded_commitment=DFC_B2_IS_UNFUNDED,
    )


def _dfc_b3() -> DFContribution:
    """DFC_B3: non-QCCP pre-funded, K_CCP=30m, DF_i=1.5m, DF_CM=60m."""
    return DFContribution(
        contribution_id=DFC_B3_ID,
        ccp_reference=DFC_B3_CCP_REF,
        is_qccp_ccp=DFC_B3_IS_QCCP,
        df_i_contribution_amount=DFC_B3_DF_I,
        df_cm_total_contributions=DFC_B3_DF_CM,
        k_ccp_published=DFC_B3_K_CCP,
        is_unfunded_commitment=DFC_B3_IS_UNFUNDED,
    )


def _dfc_b4() -> DFContribution:
    """DFC_B4: non-QCCP unfunded, K_CCP=20m, DF_i=0.8m, DF_CM=40m."""
    return DFContribution(
        contribution_id=DFC_B4_ID,
        ccp_reference=DFC_B4_CCP_REF,
        is_qccp_ccp=DFC_B4_IS_QCCP,
        df_i_contribution_amount=DFC_B4_DF_I,
        df_cm_total_contributions=DFC_B4_DF_CM,
        k_ccp_published=DFC_B4_K_CCP,
        is_unfunded_commitment=DFC_B4_IS_UNFUNDED,
    )


# ---------------------------------------------------------------------------
# Public LazyFrame factories.
# ---------------------------------------------------------------------------


def create_df_contributions(rows: list[DFContribution]) -> pl.DataFrame:
    """
    Convert a list of ``DFContribution`` instances into a Polars DataFrame.

    Schema is enforced via ``DF_CONTRIBUTION_DTYPES`` — the canonical dtype dict
    that matches the ``DF_CONTRIBUTION_SCHEMA`` the engine-implementer will add
    to ``src/rwa_calc/data/schemas.py``.

    Args:
        rows: One or more ``DFContribution`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``DF_CONTRIBUTION_DTYPES``.
    """
    return pl.DataFrame([r.to_dict() for r in rows], schema=DF_CONTRIBUTION_DTYPES)


def make_b2_frame() -> pl.LazyFrame:
    """
    Return a single-row ``LazyFrame`` for CCR-B2 (QCCP pre-funded, Art. 308).

    Hand-calc:
        K_CM = 50,000,000 × (2,000,000 / 100,000,000) = 1,000,000
        RWEA = 1,000,000 × 12.5 = 12,500,000

    Returns:
        ``pl.LazyFrame`` ready for ``compute_dfc_capital()`` (engine Wave 4).
    """
    return create_df_contributions([_dfc_b2()]).lazy()


def make_b3_frame() -> pl.LazyFrame:
    """
    Return a single-row ``LazyFrame`` for CCR-B3 (non-QCCP pre-funded, Art. 309).

    Hand-calc:
        K_CM = 30,000,000 × (1,500,000 / 60,000,000) = 750,000
        RWEA = 750,000 × 12.5 = 9,375,000

    Returns:
        ``pl.LazyFrame`` ready for ``compute_dfc_capital()`` (engine Wave 4).
    """
    return create_df_contributions([_dfc_b3()]).lazy()


def make_b4_frame() -> pl.LazyFrame:
    """
    Return a single-row ``LazyFrame`` for CCR-B4 (non-QCCP unfunded, Art. 309).

    Hand-calc:
        K_CM = 20,000,000 × (800,000 / 40,000,000) = 400,000
        RWEA = 400,000 × 12.5 = 5,000,000

    Returns:
        ``pl.LazyFrame`` ready for ``compute_dfc_capital()`` (engine Wave 4).
    """
    return create_df_contributions([_dfc_b4()]).lazy()


def make_combined_b2_b3_b4_frame() -> pl.LazyFrame:
    """
    Return a 3-row ``LazyFrame`` combining CCR-B2, CCR-B3, and CCR-B4.

    Row order:
        0 — DFC_B2 (QCCP pre-funded,    regulatory_band="dfc_qccp_prefunded")
        1 — DFC_B3 (non-QCCP pre-funded, regulatory_band="dfc_non_qccp_prefunded")
        2 — DFC_B4 (non-QCCP unfunded,   regulatory_band="dfc_non_qccp_unfunded")

    Portfolio RWEA (all three rows) = 26,875,000.

    Returns:
        ``pl.LazyFrame`` with 3 rows, schema matching ``DF_CONTRIBUTION_DTYPES``.
    """
    return create_df_contributions([_dfc_b2(), _dfc_b3(), _dfc_b4()]).lazy()


# ---------------------------------------------------------------------------
# Minimal bundle scaffolding.
# ---------------------------------------------------------------------------

#: Explicit EAD value for synthetic SA row exposed via drawn_amount.
#: Engine sets drawn_amount = k_cm on the synthetic exposure; these pin the
#: per-scenario EAD the test-writer should assert against.
DFC_B2_EAD: float = DFC_B2_K_CM  # 1,000,000
DFC_B3_EAD: float = DFC_B3_K_CM  # 750,000
DFC_B4_EAD: float = DFC_B4_K_CM  # 400,000


def make_minimal_counterparties_frame(scenario: str = "all") -> pl.LazyFrame:
    """
    Return a minimal counterparty ``LazyFrame`` for the P8.49 scenarios.

    Each scenario row represents a CCP entity.  ``entity_type="ccp"`` routes
    through the CCP logic in the classifier.  ``is_qccp`` on B2 is True
    (QCCP); B3 and B4 are non-QCCP (False).

    Args:
        scenario: One of ``"b2"``, ``"b3"``, ``"b4"``, or ``"all"`` (default).
                  ``"all"`` returns all 3 CCP counterparty rows for the combined
                  portfolio test.

    Returns:
        ``pl.LazyFrame`` with typed columns matching ``COUNTERPARTY_SCHEMA``.

    References:
        - CRR Art. 272 Def (88) — QCCP definition
        - COUNTERPARTY_SCHEMA ``is_qccp`` (ColumnSpec, required=False)
    """
    all_rows: list[dict[str, Any]] = [
        {
            "counterparty_reference": DFC_B2_CCP_REF,
            "counterparty_name": "P8.49 CCR-B2 QCCP (Art. 308)",
            "entity_type": "ccp",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": DFC_B3_CCP_REF,
            "counterparty_name": "P8.49 CCR-B3 non-QCCP pre-funded (Art. 309)",
            "entity_type": "ccp",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": DFC_B4_CCP_REF,
            "counterparty_name": "P8.49 CCR-B4 non-QCCP unfunded (Art. 309)",
            "entity_type": "ccp",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
    ]

    scenario_map: dict[str, list[dict[str, Any]]] = {
        "b2": [all_rows[0]],
        "b3": [all_rows[1]],
        "b4": [all_rows[2]],
        "all": all_rows,
    }
    if scenario not in scenario_map:
        raise ValueError(f"scenario must be one of 'b2', 'b3', 'b4', 'all'; got {scenario!r}")

    selected = scenario_map[scenario]
    is_qccp_values = [
        DFC_B2_IS_QCCP,
        DFC_B3_IS_QCCP,
        DFC_B4_IS_QCCP,
    ]
    qccp_flag_for_selected = [is_qccp_values[all_rows.index(row)] for row in selected]

    base = pl.DataFrame(selected, schema=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(pl.Series("is_qccp", qccp_flag_for_selected)).lazy()


def make_minimal_raw_ccr_bundle() -> RawCCRBundle:
    """
    Return a structurally valid ``RawCCRBundle`` with empty leaf frames.

    The default-fund-contribution leg does NOT require live derivative trades.
    This bundle satisfies the ``RawCCRBundle`` constructor (all four mandatory
    leaf bundles are present, each holding zero-row frames with correct schemas).

    NOTE: ``default_fund_contributions`` is NOT yet a field on ``RawCCRBundle``
    (the engine-implementer adds it in Wave 4).  The test-writer should call
    ``make_b2_frame()`` / ``make_combined_b2_b3_b4_frame()`` separately and
    wire the result onto the bundle once the field lands.

    Returns:
        ``RawCCRBundle`` with 0-row trades, netting_sets, margin_agreements,
        and ccr_collateral frames.  ``failed_trades`` is ``None``.
    """
    from rwa_calc.data.schemas import (  # noqa: PLC0415
        MARGIN_AGREEMENT_SCHEMA,
        NETTING_SET_SCHEMA,
        TRADE_SCHEMA,
    )

    empty_trades = pl.LazyFrame(schema=dtypes_of(TRADE_SCHEMA))
    empty_ns = pl.LazyFrame(schema=dtypes_of(NETTING_SET_SCHEMA))
    empty_margin = pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))
    empty_coll = pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))

    return RawCCRBundle(
        trades=TradeBundle(trades=empty_trades),
        netting_sets=NettingSetBundle(netting_sets=empty_ns),
        margin_agreements=MarginAgreementBundle(margin_agreements=empty_margin),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=empty_coll),
        failed_trades=None,
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p849_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all P8.49 frames and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as P8.43 / p843_failed_trade_builder.py).  Validates structural invariants
    listed below; raises ``AssertionError`` with a descriptive message if any
    is violated.

    Invariants checked:
        1.  B2 frame: 1 row; contribution_id == DFC_B2_ID; is_qccp_ccp == True.
        2.  B3 frame: 1 row; is_qccp_ccp == False; is_unfunded_commitment == False.
        3.  B4 frame: 1 row; is_qccp_ccp == False; is_unfunded_commitment == True.
        4.  Combined frame: 3 rows; all three contribution IDs present.
        5.  K_CM hand-calc: K_CCP × DF_i / DF_CM == constant (within float tolerance).
        6.  RWEA hand-calc: K_CM × 12.5 == constant (within float tolerance).
        7.  Portfolio RWEA == sum of per-row RWEAs.
        8.  Counterparties frame (all): 3 rows; is_qccp matches per-scenario flag.
        9.  Minimal RawCCRBundle constructs without raising.
        10. All required schema columns present in the combined frame.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    _tolerance = 0.01

    # --- Invariant 1: B2 frame ---
    b2_df = make_b2_frame().collect()
    if b2_df.height != 1:
        raise AssertionError(f"P8.49 B2: expected 1 row, got {b2_df.height}")
    if b2_df["contribution_id"][0] != DFC_B2_ID:
        raise AssertionError(
            f"P8.49 B2: contribution_id must be {DFC_B2_ID!r} (got {b2_df['contribution_id'][0]!r})"
        )
    if b2_df["is_qccp_ccp"][0] is not True:
        raise AssertionError("P8.49 B2: is_qccp_ccp must be True")
    if b2_df["is_unfunded_commitment"][0] is not False:
        raise AssertionError("P8.49 B2: is_unfunded_commitment must be False")

    # --- Invariant 2: B3 frame ---
    b3_df = make_b3_frame().collect()
    if b3_df.height != 1:
        raise AssertionError(f"P8.49 B3: expected 1 row, got {b3_df.height}")
    if b3_df["is_qccp_ccp"][0] is not False:
        raise AssertionError("P8.49 B3: is_qccp_ccp must be False")
    if b3_df["is_unfunded_commitment"][0] is not False:
        raise AssertionError("P8.49 B3: is_unfunded_commitment must be False")

    # --- Invariant 3: B4 frame ---
    b4_df = make_b4_frame().collect()
    if b4_df.height != 1:
        raise AssertionError(f"P8.49 B4: expected 1 row, got {b4_df.height}")
    if b4_df["is_qccp_ccp"][0] is not False:
        raise AssertionError("P8.49 B4: is_qccp_ccp must be False")
    if b4_df["is_unfunded_commitment"][0] is not True:
        raise AssertionError("P8.49 B4: is_unfunded_commitment must be True")

    # --- Invariant 4: combined frame ---
    combined_df = make_combined_b2_b3_b4_frame().collect()
    if combined_df.height != 3:
        raise AssertionError(f"P8.49 combined: expected 3 rows, got {combined_df.height}")
    ids_found = set(combined_df["contribution_id"].to_list())
    expected_ids = {DFC_B2_ID, DFC_B3_ID, DFC_B4_ID}
    if ids_found != expected_ids:
        raise AssertionError(
            f"P8.49 combined: expected contribution IDs {expected_ids}, got {ids_found}"
        )

    # --- Invariants 5-6: hand-calc verification for each scenario ---
    for label, k_ccp, df_i, df_cm, expected_k_cm, expected_rwea in [
        ("B2", DFC_B2_K_CCP, DFC_B2_DF_I, DFC_B2_DF_CM, DFC_B2_K_CM, DFC_B2_RWEA),
        ("B3", DFC_B3_K_CCP, DFC_B3_DF_I, DFC_B3_DF_CM, DFC_B3_K_CM, DFC_B3_RWEA),
        ("B4", DFC_B4_K_CCP, DFC_B4_DF_I, DFC_B4_DF_CM, DFC_B4_K_CM, DFC_B4_RWEA),
    ]:
        computed_k_cm = k_ccp * (df_i / df_cm)
        if abs(computed_k_cm - expected_k_cm) > _tolerance:
            raise AssertionError(
                f"P8.49 {label}: K_CM hand-calc mismatch: "
                f"{k_ccp} × ({df_i} / {df_cm}) = {computed_k_cm} != {expected_k_cm}"
            )
        computed_rwea = computed_k_cm * OWN_FUNDS_TO_RWA_FACTOR
        if abs(computed_rwea - expected_rwea) > _tolerance:
            raise AssertionError(
                f"P8.49 {label}: RWEA hand-calc mismatch: "
                f"{computed_k_cm} × {OWN_FUNDS_TO_RWA_FACTOR} = {computed_rwea} != {expected_rwea}"
            )

    # --- Invariant 7: portfolio total ---
    row_sum = DFC_B2_RWEA + DFC_B3_RWEA + DFC_B4_RWEA
    if abs(row_sum - PORTFOLIO_TOTAL_RWEA) > _tolerance:
        raise AssertionError(
            f"P8.49: PORTFOLIO_TOTAL_RWEA {PORTFOLIO_TOTAL_RWEA} != sum of per-row RWEAs {row_sum}"
        )

    # --- Invariant 8: counterparties frame ---
    cp_all = make_minimal_counterparties_frame(scenario="all").collect()
    if cp_all.height != 3:
        raise AssertionError(f"P8.49 counterparties (all): expected 3 rows, got {cp_all.height}")
    if "is_qccp" not in cp_all.columns:
        raise AssertionError("P8.49 counterparties: is_qccp column must be present")
    cp_b2 = cp_all.filter(pl.col("counterparty_reference") == DFC_B2_CCP_REF)
    if cp_b2["is_qccp"][0] is not True:
        raise AssertionError(f"P8.49: {DFC_B2_CCP_REF} is_qccp must be True")
    for ref in [DFC_B3_CCP_REF, DFC_B4_CCP_REF]:
        cp_row = cp_all.filter(pl.col("counterparty_reference") == ref)
        if cp_row["is_qccp"][0] is not False:
            raise AssertionError(f"P8.49: {ref} is_qccp must be False (non-QCCP)")

    # --- Invariant 9: minimal RawCCRBundle constructs without raising ---
    bundle = make_minimal_raw_ccr_bundle()
    if bundle.failed_trades is not None:
        raise AssertionError("P8.49: minimal bundle failed_trades must be None")
    if bundle.trades.trades.collect().height != 0:
        raise AssertionError("P8.49: minimal bundle must have 0 trade rows")
    if bundle.netting_sets.netting_sets.collect().height != 0:
        raise AssertionError("P8.49: minimal bundle must have 0 netting-set rows")

    # --- Invariant 10: schema columns ---
    required_cols = set(DF_CONTRIBUTION_DTYPES.keys())
    missing = required_cols - set(combined_df.columns)
    if missing:
        raise AssertionError(f"P8.49 combined frame: missing required columns {missing}")

    return [("(python-only builder — no parquet)", 0)]
