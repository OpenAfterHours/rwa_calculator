"""
P8.34 unit tests: SA-CCR hedging-set extension for credit, equity, and commodity.

Verifies that ``assign_hedging_set`` produces correct ``hedging_set_id`` values
for credit, equity, and commodity asset classes, in addition to the pre-existing
IR and FX branches.

Composition rules under test:
    credit   → "CR-{netting_set_id}"         (CRR Art. 277(2)(c); CRE52.60)
    equity   → "EQ-{netting_set_id}"         (CRR Art. 277(2)(d); CRE52.65)
    commodity → "CO-{netting_set_id}-{commodity_type}"  (CRR Art. 277(3)(b); CRE52.67)

Key design notes:
- Credit and equity produce ONE hedging set per netting set regardless of whether
  the trade is single-name or index (reference_entity / is_index do NOT partition
  the hedging set at this step — correlation lives at the aggregation step per
  Art. 277a + 280a/b).
- Commodity is partitioned into five fixed buckets matching
  COLUMN_VALUE_CONSTRAINTS["trades"]["commodity_type"]: ELECTRICITY, OIL_GAS,
  METALS, AGRICULTURAL, OTHER.
- The short code for commodity is "CO" (from ASSET_CLASS_SHORT_CODE at
  schemas.py:952), NOT "CM".
- Pre-existing IR and FX branches must remain unmodified (regression tests 8 & 9).

References:
    CRR Art. 277(1)   — hedging-set definition
    CRR Art. 277(2)(c)-(d) — credit and equity one-HS-per-NS rule
    CRR Art. 277(3)(b) — commodity 5-bucket partition
    BCBS CRE52.60-69  — parallel BCBS references
    src/rwa_calc/data/schemas.py:947-953 — ASSET_CLASS_SHORT_CODE ("CO" is SSoT)
    src/rwa_calc/data/schemas.py:1317    — COLUMN_VALUE_CONSTRAINTS commodity_type enum
    tests/acceptance/ccr/test_p8_15_hedging_sets_ir.py — pre-existing IR tests (must stay green)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Subject under test — lazy guard so the test fails at assertion, not import.
# ---------------------------------------------------------------------------

try:
    from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
except (ImportError, ModuleNotFoundError):
    assign_hedging_set = None  # ty: ignore[invalid-assignment]

# ---------------------------------------------------------------------------
# Shared scenario constants
# ---------------------------------------------------------------------------

_NS_CR_01 = "NS_CR_01"
_NS_EQ_01 = "NS_EQ_01"
_NS_CO_01 = "NS_CO_01"

_REFERENCE_DATE = date(2026, 5, 26)
_MATURITY_DATE = date(2028, 5, 26)

# Expected hedging_set_id values — single source of truth for all assertions.
_EXPECTED_CREDIT_HSID = f"CR-{_NS_CR_01}"
_EXPECTED_EQUITY_HSID = f"EQ-{_NS_EQ_01}"
_EXPECTED_CO_ELECTRICITY = f"CO-{_NS_CO_01}-ELECTRICITY"
_EXPECTED_CO_OIL_GAS = f"CO-{_NS_CO_01}-OIL_GAS"
_EXPECTED_CO_METALS = f"CO-{_NS_CO_01}-METALS"
_EXPECTED_CO_AGRICULTURAL = f"CO-{_NS_CO_01}-AGRICULTURAL"
_EXPECTED_CO_OTHER = f"CO-{_NS_CO_01}-OTHER"

# ---------------------------------------------------------------------------
# Helper builders — construct minimal LazyFrames inline (no fixture files).
# Columns mirror TRADE_SCHEMA; only the subset required by assign_hedging_set
# is provided.  assign_ir_maturity_bucket needs: asset_class, years_to_maturity.
# assign_hedging_set additionally needs: netting_set_id, currency, currency_leg2,
# commodity_type.
# ---------------------------------------------------------------------------


def _credit_trade(
    trade_id: str,
    netting_set_id: str = _NS_CR_01,
    reference_entity: str | None = "ACME LEI 123",
    is_index: bool | None = False,
) -> pl.LazyFrame:
    """Single credit derivative trade, minimal columns for assign_hedging_set."""
    return pl.DataFrame(
        {
            "trade_id": [trade_id],
            "netting_set_id": [netting_set_id],
            "asset_class": ["credit"],
            "currency": ["USD"],
            "currency_leg2": [None],
            "years_to_maturity": [2.0],
            "reference_entity": [reference_entity],
            "is_index": [is_index],
            "commodity_type": [None],
        },
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "currency": pl.String,
            "currency_leg2": pl.String,
            "years_to_maturity": pl.Float64,
            "reference_entity": pl.String,
            "is_index": pl.Boolean,
            "commodity_type": pl.String,
        },
    ).lazy()


def _equity_trade(
    trade_id: str,
    netting_set_id: str = _NS_EQ_01,
    reference_entity: str | None = "WIDGET PLC",
    is_index: bool | None = False,
) -> pl.LazyFrame:
    """Single equity derivative trade, minimal columns for assign_hedging_set."""
    return pl.DataFrame(
        {
            "trade_id": [trade_id],
            "netting_set_id": [netting_set_id],
            "asset_class": ["equity"],
            "currency": ["GBP"],
            "currency_leg2": [None],
            "years_to_maturity": [1.5],
            "reference_entity": [reference_entity],
            "is_index": [is_index],
            "commodity_type": [None],
        },
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "currency": pl.String,
            "currency_leg2": pl.String,
            "years_to_maturity": pl.Float64,
            "reference_entity": pl.String,
            "is_index": pl.Boolean,
            "commodity_type": pl.String,
        },
    ).lazy()


def _commodity_trade(
    trade_id: str,
    commodity_type: str | None,
    netting_set_id: str = _NS_CO_01,
) -> pl.LazyFrame:
    """Single commodity derivative trade, minimal columns for assign_hedging_set."""
    return pl.DataFrame(
        {
            "trade_id": [trade_id],
            "netting_set_id": [netting_set_id],
            "asset_class": ["commodity"],
            "currency": ["USD"],
            "currency_leg2": [None],
            "years_to_maturity": [0.5],
            "reference_entity": [None],
            "is_index": [None],
            "commodity_type": [commodity_type],
        },
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "currency": pl.String,
            "currency_leg2": pl.String,
            "years_to_maturity": pl.Float64,
            "reference_entity": pl.String,
            "is_index": pl.Boolean,
            "commodity_type": pl.String,
        },
    ).lazy()


def _ir_trade(
    trade_id: str,
    netting_set_id: str = "NS_IR_01",
    years_to_maturity: float = 7.0,
) -> pl.LazyFrame:
    """Minimal IR trade for regression tests — must keep its existing hedging_set_id format.

    ``years_to_maturity`` defaults to 7.0 (GT_5Y bucket).  Pass 0.5 to get the
    LT_1Y bucket and produce a second distinct hedging_set_id in the mixed-portfolio
    test (test 10).
    """
    return pl.DataFrame(
        {
            "trade_id": [trade_id],
            "netting_set_id": [netting_set_id],
            "asset_class": ["interest_rate"],
            "currency": ["GBP"],
            "currency_leg2": [None],
            "years_to_maturity": [years_to_maturity],
            "reference_entity": [None],
            "is_index": [None],
            "commodity_type": [None],
        },
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "currency": pl.String,
            "currency_leg2": pl.String,
            "years_to_maturity": pl.Float64,
            "reference_entity": pl.String,
            "is_index": pl.Boolean,
            "commodity_type": pl.String,
        },
    ).lazy()


def _fx_trade(trade_id: str, netting_set_id: str = "NS_FX_01") -> pl.LazyFrame:
    """Minimal FX trade for regression tests — must keep its existing hedging_set_id format."""
    return pl.DataFrame(
        {
            "trade_id": [trade_id],
            "netting_set_id": [netting_set_id],
            "asset_class": ["fx"],
            "currency": ["USD"],
            "currency_leg2": ["GBP"],
            "years_to_maturity": [0.75],
            "reference_entity": [None],
            "is_index": [None],
            "commodity_type": [None],
        },
        schema={
            "trade_id": pl.String,
            "netting_set_id": pl.String,
            "asset_class": pl.String,
            "currency": pl.String,
            "currency_leg2": pl.String,
            "years_to_maturity": pl.Float64,
            "reference_entity": pl.String,
            "is_index": pl.Boolean,
            "commodity_type": pl.String,
        },
    ).lazy()


# ===========================================================================
# 1. Credit single-name emits CR prefix
# ===========================================================================


def test_credit_single_name_emits_cr_prefix() -> None:
    """Credit single-name trade must produce hedging_set_id == "CR-{netting_set_id}".

    Arrange:
        One credit trade, asset_class="credit", is_index=False,
        reference_entity="ACME LEI 123", netting_set_id="NS_CR_01".

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        hedging_set_id == "CR-NS_CR_01".

    References: CRR Art. 277(2)(c); CRE52.60.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = _credit_trade("CR-SN-001", reference_entity="ACME LEI 123", is_index=False)

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    actual = result["hedging_set_id"][0]
    assert actual == _EXPECTED_CREDIT_HSID, (
        f"Credit single-name trade: expected hedging_set_id={_EXPECTED_CREDIT_HSID!r}, "
        f"got {actual!r}. "
        "CRR Art. 277(2)(c): one hedging set per netting set for credit."
    )


# ===========================================================================
# 2. Credit index produces SAME hedging_set_id as single-name in same NS
# ===========================================================================


def test_credit_index_emits_same_cr_prefix_as_single_name() -> None:
    """Credit index trade must produce same hedging_set_id as single-name in the same NS.

    LOAD-BEARING: proves that reference_entity / is_index do NOT partition the
    hedging set at this step.  Art. 277(2)(c) defines one HS per asset class per NS;
    the correlation/SF step (Art. 277a + 280a) distinguishes single-name vs index.

    Arrange:
        Two trades in NS_CR_01: one is_index=False, one is_index=True.

    Act:
        assign_hedging_set(concatenated_lf).collect()

    Assert:
        Both rows have identical hedging_set_id == "CR-NS_CR_01".

    References: CRR Art. 277(2)(c); CRE52.60-61.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = pl.concat(
        [
            _credit_trade("CR-SN-001", reference_entity="ACME LEI 123", is_index=False),
            _credit_trade("CR-IDX-001", reference_entity="CDX.NA.IG.40", is_index=True),
        ]
    )

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    hsids = result["hedging_set_id"].to_list()
    assert all(h == _EXPECTED_CREDIT_HSID for h in hsids), (
        f"Credit: both single-name and index trades must share hedging_set_id="
        f"{_EXPECTED_CREDIT_HSID!r}. "
        f"Got {hsids!r}. "
        "CRR Art. 277(2)(c): reference_entity does not partition the hedging set."
    )


# ===========================================================================
# 3. Equity single-name emits EQ prefix
# ===========================================================================


def test_equity_emits_eq_prefix() -> None:
    """Equity trade must produce hedging_set_id == "EQ-{netting_set_id}".

    Arrange:
        One equity trade, asset_class="equity", is_index=False,
        reference_entity="WIDGET PLC", netting_set_id="NS_EQ_01".

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        hedging_set_id == "EQ-NS_EQ_01".

    References: CRR Art. 277(2)(d); CRE52.65.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = _equity_trade("EQ-SN-001", reference_entity="WIDGET PLC", is_index=False)

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    actual = result["hedging_set_id"][0]
    assert actual == _EXPECTED_EQUITY_HSID, (
        f"Equity single-name trade: expected hedging_set_id={_EXPECTED_EQUITY_HSID!r}, "
        f"got {actual!r}. "
        "CRR Art. 277(2)(d): one hedging set per netting set for equity."
    )


# ===========================================================================
# 4. Equity index and single-name share the same hedging_set_id
# ===========================================================================


def test_equity_index_and_single_name_share_hedging_set() -> None:
    """Equity index and single-name must share hedging_set_id within the same NS.

    LOAD-BEARING: mirrors test 2 for the equity asset class.

    Arrange:
        Two equity trades in NS_EQ_01: is_index=False and is_index=True.

    Act:
        assign_hedging_set(concatenated_lf).collect()

    Assert:
        Both rows have identical hedging_set_id == "EQ-NS_EQ_01".

    References: CRR Art. 277(2)(d); CRE52.65-66.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = pl.concat(
        [
            _equity_trade("EQ-SN-001", reference_entity="WIDGET PLC", is_index=False),
            _equity_trade("EQ-IDX-001", reference_entity="FTSE 100", is_index=True),
        ]
    )

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    hsids = result["hedging_set_id"].to_list()
    assert all(h == _EXPECTED_EQUITY_HSID for h in hsids), (
        f"Equity: both single-name and index trades must share hedging_set_id="
        f"{_EXPECTED_EQUITY_HSID!r}. "
        f"Got {hsids!r}. "
        "CRR Art. 277(2)(d): is_index does not partition the hedging set."
    )


# ===========================================================================
# 5. Commodity — each bucket produces a distinct hedging_set_id
# ===========================================================================


def test_commodity_each_bucket_distinct() -> None:
    """Five commodity trades (one per bucket) in the same NS must produce 5 distinct HSIDs.

    Arrange:
        5 commodity trades in NS_CO_01, commodity_type cycling through all
        5 COLUMN_VALUE_CONSTRAINTS buckets: ELECTRICITY, OIL_GAS, METALS,
        AGRICULTURAL, OTHER.

    Act:
        assign_hedging_set(5-row LazyFrame).collect()

    Assert:
        n_unique(hedging_set_id) == 5 and each expected HSID is present.

    References: CRR Art. 277(3)(b); CRE52.67.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = pl.concat(
        [
            _commodity_trade("CO-ELEC-001", commodity_type="ELECTRICITY"),
            _commodity_trade("CO-OIL-001", commodity_type="OIL_GAS"),
            _commodity_trade("CO-MET-001", commodity_type="METALS"),
            _commodity_trade("CO-AGR-001", commodity_type="AGRICULTURAL"),
            _commodity_trade("CO-OTH-001", commodity_type="OTHER"),
        ]
    )

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert distinct count.
    n_distinct = result["hedging_set_id"].n_unique()
    assert n_distinct == 5, (
        f"Expected 5 distinct commodity hedging_set_id values (one per bucket), "
        f"got {n_distinct}. "
        "CRR Art. 277(3)(b): each commodity bucket is a separate hedging set."
    )

    # Assert each expected ID is present.
    actual_hsids = set(result["hedging_set_id"].to_list())
    expected = {
        _EXPECTED_CO_ELECTRICITY,
        _EXPECTED_CO_OIL_GAS,
        _EXPECTED_CO_METALS,
        _EXPECTED_CO_AGRICULTURAL,
        _EXPECTED_CO_OTHER,
    }
    assert actual_hsids == expected, (
        f"Commodity hedging_set_id values mismatch.\n"
        f"  Expected:  {sorted(expected)}\n"
        f"  Got:       {sorted(str(h) for h in actual_hsids)}\n"
        "CRR Art. 277(3)(b): format must be 'CO-{netting_set_id}-{commodity_type}'."
    )


# ===========================================================================
# 6. Commodity — same bucket collapses to one hedging_set_id
# ===========================================================================


def test_commodity_same_bucket_collapses() -> None:
    """Two ELECTRICITY trades in the same NS must map to the same hedging_set_id.

    Arrange:
        Two commodity trades in NS_CO_01, both commodity_type="ELECTRICITY".

    Act:
        assign_hedging_set(2-row LazyFrame).collect()

    Assert:
        n_unique(hedging_set_id) == 1 and value == "CO-NS_CO_01-ELECTRICITY".

    References: CRR Art. 277(3)(b); CRE52.67.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = pl.concat(
        [
            _commodity_trade("CO-ELEC-001", commodity_type="ELECTRICITY"),
            _commodity_trade("CO-ELEC-002", commodity_type="ELECTRICITY"),
        ]
    )

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    n_distinct = result["hedging_set_id"].n_unique()
    assert n_distinct == 1, (
        f"Expected 1 distinct hedging_set_id for two ELECTRICITY trades in same NS, "
        f"got {n_distinct}. "
        "CRR Art. 277(3)(b): same (NS, bucket) pair must share one hedging set."
    )
    actual = result["hedging_set_id"][0]
    assert actual == _EXPECTED_CO_ELECTRICITY, (
        f"ELECTRICITY hedging_set_id: expected {_EXPECTED_CO_ELECTRICITY!r}, got {actual!r}."
    )


# ===========================================================================
# 7. Commodity — null commodity_type returns null hedging_set_id
# ===========================================================================


def test_commodity_null_type_returns_null_hsid() -> None:
    """A commodity trade with commodity_type=None must produce hedging_set_id=None.

    This tests the null-in / null-out contract: malformed rows that lack a
    commodity bucket value must not produce a partial or corrupted ID.

    Arrange:
        One commodity trade, commodity_type=None.

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        hedging_set_id is None (null).

    References: CRR Art. 277(3)(b) — bucket is required for commodity hedging sets.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = _commodity_trade("CO-NULL-001", commodity_type=None)

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    hsid = result["hedging_set_id"][0]
    assert hsid is None, (
        f"Commodity trade with null commodity_type must produce null hedging_set_id. "
        f"Got {hsid!r}. "
        "CRR Art. 277(3)(b): no bucket → no hedging set."
    )


# ===========================================================================
# 8. IR rows keep existing hedging_set_id format (regression guard)
# ===========================================================================


def test_unchanged_ir_rows_keep_existing_hsid_format() -> None:
    """IR trades must keep the existing 'IR-{ns}-{ccy}-{bucket}' format (regression).

    Arrange:
        One IR GBP trade, years_to_maturity=7.0 → GT_5Y bucket.

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        hedging_set_id == "IR-NS_IR_01-GBP-GT_5Y".

    References: CRR Art. 277(1)-(2); pre-existing P8.15 implementation.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    ns_id = "NS_IR_01"
    lf = _ir_trade("IR-001", netting_set_id=ns_id)

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    actual = result["hedging_set_id"][0]
    expected = f"IR-{ns_id}-GBP-GT_5Y"
    assert actual == expected, (
        f"IR regression: expected hedging_set_id={expected!r}, got {actual!r}. "
        "The P8.15 IR branch must remain unchanged after the P8.34 extension."
    )


# ===========================================================================
# 9. FX rows keep existing hedging_set_id format (regression guard)
# ===========================================================================


def test_unchanged_fx_rows_keep_existing_hsid_format() -> None:
    """FX trades must keep the existing 'FX-{ns}-{pair}' format (regression).

    Arrange:
        One FX trade, currency="USD", currency_leg2="GBP".
        Pair is order-independent: min("GBP","USD")="GBP", max=USD → "GBP/USD".

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        hedging_set_id == "FX-NS_FX_01-GBP/USD".

    References: CRR Art. 277(3)(a); pre-existing P8.15 FX implementation.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    ns_id = "NS_FX_01"
    lf = _fx_trade("FX-001", netting_set_id=ns_id)

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    actual = result["hedging_set_id"][0]
    expected = f"FX-{ns_id}-GBP/USD"
    assert actual == expected, (
        f"FX regression: expected hedging_set_id={expected!r}, got {actual!r}. "
        "The P8.15 FX branch must remain unchanged after the P8.34 extension."
    )


# ===========================================================================
# 10. Mixed portfolio — distinct hedging set count
# ===========================================================================


def test_distinct_hedging_set_count_for_mixed_portfolio() -> None:
    """An 11-row mixed portfolio must produce exactly 10 distinct hedging_set_id values.

    Portfolio composition:
        2 IR trades  — GT_5Y bucket (IR-001, 7.0y) and LT_1Y bucket (IR-002, 0.5y)
                       → 2 distinct HS (load-bearing: proves IR bucket partition)
        1 FX trade   — "FX-NS_FX_01-GBP/USD"                              → 1 HS
        1 credit SN  — "CR-NS_CR_01"                                       → 1 HS
        1 credit idx — "CR-NS_CR_01" (same HS as credit SN!)               → same HS (no extra)
        1 equity     — "EQ-NS_EQ_01"                                       → 1 HS
        5 commodity  — "CO-NS_CO_01-ELECTRICITY/OIL_GAS/METALS/AGRICULTURAL/OTHER" → 5 HS
    Total unique = 2 + 1 + 1 + 1 + 5 = 10 (the two credit rows share one HS).

    Arrange:
        11-row concatenated LazyFrame from all asset classes.

    Act:
        assign_hedging_set(lf).collect()

    Assert:
        n_unique(hedging_set_id) == 10.

    References:
        CRR Art. 277(1)-(3) — all hedging-set rules.
    """
    # Arrange
    if assign_hedging_set is None:
        pytest.fail(
            "assign_hedging_set not importable from rwa_calc.engine.ccr.hedging_sets "
            "— module not yet implemented (P8.34)."
        )
    lf = pl.concat(
        [
            # 2 IR trades — different maturity buckets → 2 distinct hedging sets.
            # IR-001: 7.0y → GT_5Y bucket  ("IR-NS_IR_01-GBP-GT_5Y")
            # IR-002: 0.5y → LT_1Y bucket  ("IR-NS_IR_01-GBP-LT_1Y")
            _ir_trade("IR-001", netting_set_id="NS_IR_01", years_to_maturity=7.0),
            _ir_trade("IR-002", netting_set_id="NS_IR_01", years_to_maturity=0.5),
            # 1 FX trade
            _fx_trade("FX-001", netting_set_id="NS_FX_01"),
            # 1 credit single-name + 1 credit index in same NS → 1 hedging set
            _credit_trade("CR-SN-001", netting_set_id=_NS_CR_01, is_index=False),
            _credit_trade("CR-IDX-001", netting_set_id=_NS_CR_01, is_index=True),
            # 1 equity trade
            _equity_trade("EQ-SN-001", netting_set_id=_NS_EQ_01),
            # 5 commodity trades (one per bucket)
            _commodity_trade("CO-ELEC-001", commodity_type="ELECTRICITY"),
            _commodity_trade("CO-OIL-001", commodity_type="OIL_GAS"),
            _commodity_trade("CO-MET-001", commodity_type="METALS"),
            _commodity_trade("CO-AGR-001", commodity_type="AGRICULTURAL"),
            _commodity_trade("CO-OTH-001", commodity_type="OTHER"),
        ]
    )

    # Act
    result = assign_hedging_set(lf).collect()

    # Assert
    assert result.height == 11, f"Expected 11 rows, got {result.height}."
    # Exclude nulls from distinct count (commodity_type=None rows would be null, but
    # none present here — all commodity rows have explicit bucket values).
    non_null_hsids = result["hedging_set_id"].drop_nulls()
    n_distinct = non_null_hsids.n_unique()
    assert n_distinct == 10, (
        f"Mixed 11-row portfolio: expected 10 distinct hedging_set_id values, "
        f"got {n_distinct}. "
        f"Unique IDs found: {sorted(non_null_hsids.unique().to_list())}. "
        "CRR Art. 277(1)-(3): "
        "2 IR (different buckets) + 1 FX + 2 credit (same NS) + 1 equity + 5 commodity = 10."
    )
