"""
Unit tests for apply_wwr_gate (P8.27).

Pins the expected behaviour of the wrong-way risk identification gate per
CRR Art. 291(4)-(5):

    When a netting set contains ≥1 trade with ``is_specific_wwr=True``,
    each such trade is broken out into its own synthetic netting set
    (id format: ``<original_ns_id>__wwr__<trade_id>``), the synthetic NS
    receives ``wwr_lgd_override = 1.0`` (Art. 291(5)(c) LGD = 100%),
    and ONE ``CalculationError(code="CCR010", severity=WARNING,
    category=ErrorCategory.CCR_WWR_SPECIFIC)`` is appended to
    ``RawCCRBundle.errors`` per affected original netting set.

Scenario (P8.27 fixture):
    NS_WWR_01  (CP_WWR_01, is_legally_enforceable=True, unmargined,
                has_general_wwr_flag=False)
    ├── T_WWR_01     equity derivative, is_specific_wwr=True
    └── T_NORMAL_01  IR derivative,    is_specific_wwr=False

After WWR gate:
    trades:
        T_WWR_01    → netting_set_id = "NS_WWR_01__wwr__T_WWR_01"  (synthetic)
        T_NORMAL_01 → netting_set_id = "NS_WWR_01"                  (unchanged)
    netting_sets (2 rows):
        NS_WWR_01                  — wwr_lgd_override = null
        NS_WWR_01__wwr__T_WWR_01  — wwr_lgd_override = 1.0
    bundle.errors:
        1 × CCR010 (WARNING, CCR_WWR_SPECIFIC, CP_WWR_01)
        0 × CCR011 (has_general_wwr_flag=False)

References:
    - CRR Art. 291(1)(a)/(1)(b)/(4)/(5)(a)/(5)(c)/(6) — WWR definitions
    - CRR Art. 272(4) — netting set definition
    - CRR Art. 274(2) — netting set membership
"""

from __future__ import annotations

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorSeverity

# ---------------------------------------------------------------------------
# Subject under test
# wwr.py does not exist yet — engine-implementer adds it in Wave 4.
# Import failure is the expected failing signal for this item (operator-relaxed
# C3.4): ImportError / ModuleNotFoundError is an acceptable failing mode.
# ---------------------------------------------------------------------------
from rwa_calc.engine.ccr.wwr import apply_wwr_gate  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture constants (single source of truth from fixture module)
# ---------------------------------------------------------------------------
from tests.fixtures.ccr.wwr_builder import (
    CCR010_ERROR_CODE,
    CCR010_REGULATORY_REF,
    CCR011_ERROR_CODE,
    CP_WWR_01_REF,
    EXPECTED_CCR010_COUNT,
    EXPECTED_CCR011_COUNT,
    NS_WWR_01_ID,
    SYNTHETIC_NS_ID,
    WWR_LGD_OVERRIDE_VALUE,
    make_p827_collateral,
    make_p827_margin_agreements,
    make_p827_netting_sets,
    make_p827_trades,
)

# ---------------------------------------------------------------------------
# Shared bundle factory
# ---------------------------------------------------------------------------


def _make_bundle() -> RawCCRBundle:
    """Build a RawCCRBundle from P8.27 fixture frames.

    Uses pre-gate input data: NS_WWR_01 with both T_WWR_01 (specific WWR)
    and T_NORMAL_01 (clean IR derivative).  Wraps each frame with ``.lazy()``
    where the builder returns a ``pl.DataFrame``.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=make_p827_trades()),
        netting_sets=NettingSetBundle(netting_sets=make_p827_netting_sets()),
        margin_agreements=MarginAgreementBundle(margin_agreements=make_p827_margin_agreements()),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=make_p827_collateral()),
    )


# ===========================================================================
# 1. Trade-frame partition — §4a assertions
# ===========================================================================


def test_p827_wwr_trade_reassigned_to_synthetic_ns() -> None:
    """WWR gate must reassign T_WWR_01 to the synthetic netting-set id.

    Arrange:
        RawCCRBundle with T_WWR_01 (is_specific_wwr=True) in NS_WWR_01.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        Row for T_WWR_01 has netting_set_id == SYNTHETIC_NS_ID.

    References: CRR Art. 291(5)(a).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    trades_df = result.trades.trades.collect()
    wwr_row = trades_df.filter(trades_df["trade_id"] == "T_WWR_01")
    actual_ns_id = wwr_row["netting_set_id"][0]
    assert actual_ns_id == SYNTHETIC_NS_ID, (
        f"Expected T_WWR_01.netting_set_id == {SYNTHETIC_NS_ID!r}, "
        f"got {actual_ns_id!r}. "
        "CRR Art. 291(5)(a): each specific-WWR trade must be broken out into "
        "its own synthetic netting set."
    )


def test_p827_normal_trade_netting_set_id_unchanged() -> None:
    """WWR gate must leave T_NORMAL_01.netting_set_id unchanged.

    Arrange:
        RawCCRBundle with T_NORMAL_01 (is_specific_wwr=False) in NS_WWR_01.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        Row for T_NORMAL_01 has netting_set_id == NS_WWR_01_ID.

    References: CRR Art. 291(5)(a) — only WWR trades are broken out.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    trades_df = result.trades.trades.collect()
    normal_row = trades_df.filter(trades_df["trade_id"] == "T_NORMAL_01")
    actual_ns_id = normal_row["netting_set_id"][0]
    assert actual_ns_id == NS_WWR_01_ID, (
        f"Expected T_NORMAL_01.netting_set_id == {NS_WWR_01_ID!r}, "
        f"got {actual_ns_id!r}. "
        "Non-WWR trades must remain in the original netting set."
    )


def test_p827_trade_row_count_preserved() -> None:
    """WWR gate must not add or drop trade rows; only netting_set_id changes.

    Arrange:
        RawCCRBundle with 2 trades (T_WWR_01 + T_NORMAL_01).

    Act:
        apply_wwr_gate(bundle)

    Assert:
        trades LazyFrame row count == 2.

    References: CRR Art. 291(5)(a) — break-out, not duplication.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    row_count = result.trades.trades.collect().height
    assert row_count == 2, (
        f"Expected 2 trade rows after WWR gate (T_WWR_01 + T_NORMAL_01), got {row_count}. "
        "Gate must only remap netting_set_id, not filter or duplicate trades."
    )


# ===========================================================================
# 2. NS-frame split — §4b assertions
# ===========================================================================


def test_p827_ns_frame_has_two_rows() -> None:
    """WWR gate must produce 2 netting-set rows: residual + synthetic.

    Arrange:
        1-row netting_sets LazyFrame (NS_WWR_01, pre-gate).

    Act:
        apply_wwr_gate(bundle)

    Assert:
        netting_sets LazyFrame row count == 2.

    References: CRR Art. 291(5)(a): one synthetic NS per broken-out trade.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ns_count = result.netting_sets.netting_sets.collect().height
    assert ns_count == 2, (
        f"Expected 2 netting-set rows (residual NS_WWR_01 + synthetic), got {ns_count}. "
        "CRR Art. 291(5)(a): WWR trade break-out creates one synthetic NS per trade."
    )


def test_p827_synthetic_ns_wwr_lgd_override_is_one() -> None:
    """Synthetic NS must have wwr_lgd_override == 1.0 (Art. 291(5)(c) LGD=100%).

    Arrange:
        RawCCRBundle with T_WWR_01 (is_specific_wwr=True).

    Act:
        apply_wwr_gate(bundle)

    Assert:
        netting_set row SYNTHETIC_NS_ID has wwr_lgd_override == 1.0.

    References: CRR Art. 291(5)(c): specific WWR → LGD = 100%.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ns_df = result.netting_sets.netting_sets.collect()
    synthetic_row = ns_df.filter(ns_df["netting_set_id"] == SYNTHETIC_NS_ID)
    actual_override = synthetic_row["wwr_lgd_override"][0]
    assert actual_override == WWR_LGD_OVERRIDE_VALUE, (
        f"Expected synthetic NS wwr_lgd_override == {WWR_LGD_OVERRIDE_VALUE!r} "
        f"(Art. 291(5)(c) LGD = 100%), got {actual_override!r}."
    )


def test_p827_residual_ns_wwr_lgd_override_is_null() -> None:
    """Residual NS must have wwr_lgd_override == null (not a WWR trade set).

    Arrange:
        RawCCRBundle with T_NORMAL_01 remaining in NS_WWR_01.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        netting_set row NS_WWR_01_ID has wwr_lgd_override IS NULL.

    References: CRR Art. 291(5)(a) — residual NS inherits original NS attrs.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ns_df = result.netting_sets.netting_sets.collect()
    residual_row = ns_df.filter(ns_df["netting_set_id"] == NS_WWR_01_ID)
    actual_override = residual_row["wwr_lgd_override"][0]
    assert actual_override is None, (
        f"Expected residual NS_WWR_01 wwr_lgd_override IS NULL, got {actual_override!r}. "
        "Only the synthetic WWR NS carries the LGD override."
    )


def test_p827_both_ns_rows_carry_counterparty_reference() -> None:
    """Both residual and synthetic NS rows must carry counterparty_reference CP_WWR_01.

    Arrange:
        RawCCRBundle; original NS_WWR_01 belongs to CP_WWR_01.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        All netting_set rows have counterparty_reference == CP_WWR_01_REF.

    References: CRR Art. 291(5)(a) — synthetic NS inherits counterparty from
        original.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ns_df = result.netting_sets.netting_sets.collect()
    counterparty_refs = ns_df["counterparty_reference"].to_list()
    assert all(ref == CP_WWR_01_REF for ref in counterparty_refs), (
        f"Expected all NS rows to have counterparty_reference == {CP_WWR_01_REF!r}, "
        f"got {counterparty_refs!r}."
    )


# ===========================================================================
# 3. Error emission — §4c assertions
# ===========================================================================


def test_p827_error_count_exactly_one_ccr010() -> None:
    """WWR gate must emit exactly one CCR010 error for NS_WWR_01.

    Arrange:
        1 original netting set with ≥1 specific-WWR trade.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        len(result.errors) == EXPECTED_CCR010_COUNT (== 1).

    References: CRR Art. 291(4)-(5): one warning per original NS with specific WWR.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr010_errors = [e for e in result.errors if e.code == CCR010_ERROR_CODE]
    assert len(ccr010_errors) == EXPECTED_CCR010_COUNT, (
        f"Expected exactly {EXPECTED_CCR010_COUNT} CCR010 error(s) "
        f"(one per original NS with specific-WWR trades), got {len(ccr010_errors)}. "
        "CCR010 aggregation key is original netting_set_id (here NS_WWR_01)."
    )


def test_p827_zero_ccr011_errors() -> None:
    """WWR gate must emit zero CCR011 errors (has_general_wwr_flag=False).

    Arrange:
        NS_WWR_01 with has_general_wwr_flag=False.

    Act:
        apply_wwr_gate(bundle)

    Assert:
        No CCR011 errors in result.errors.

    References: CRR Art. 291(1)(a)/(6) — CCR011 fires on general WWR flag only.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr011_errors = [e for e in result.errors if e.code == CCR011_ERROR_CODE]
    assert len(ccr011_errors) == EXPECTED_CCR011_COUNT, (
        f"Expected {EXPECTED_CCR011_COUNT} CCR011 errors (has_general_wwr_flag=False), "
        f"got {len(ccr011_errors)}. "
        "CCR011 must only fire when has_general_wwr_flag=True."
    )


def test_p827_ccr010_severity_is_warning() -> None:
    """CCR010 error must have severity WARNING (non-fatal; calculation continues).

    Arrange/Act: apply_wwr_gate on P8.27 bundle.
    Assert: CCR010 error.severity == ErrorSeverity.WARNING.

    References: CRR Art. 291(4)-(5); ErrorSeverity only defines
        WARNING | ERROR | CRITICAL — no INFO member.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr010_errors = [e for e in result.errors if e.code == CCR010_ERROR_CODE]
    assert len(ccr010_errors) >= 1, "No CCR010 error emitted — cannot check severity."
    error: CalculationError = ccr010_errors[0]
    assert error.severity == ErrorSeverity.WARNING, (
        f"Expected CCR010 severity == ErrorSeverity.WARNING, got {error.severity!r}. "
        "ErrorSeverity has no INFO member; WARNING is the lowest non-OK severity."
    )


def test_p827_ccr010_category_ccr_wwr_specific() -> None:
    """CCR010 error category must be ErrorCategory.CCR_WWR_SPECIFIC.

    Arrange/Act: apply_wwr_gate on P8.27 bundle.
    Assert: CCR010 error.category == ErrorCategory.CCR_WWR_SPECIFIC.

    References: CRR Art. 291(1)(b)/(5) — specific WWR sub-category.
    Engine-implementer must add CCR_WWR_SPECIFIC to ErrorCategory in domain/enums.py.
    """
    from rwa_calc.domain.enums import ErrorCategory  # deferred to catch missing value

    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr010_errors = [e for e in result.errors if e.code == CCR010_ERROR_CODE]
    assert len(ccr010_errors) >= 1, "No CCR010 error emitted — cannot check category."
    error: CalculationError = ccr010_errors[0]
    assert error.category == ErrorCategory.CCR_WWR_SPECIFIC, (
        f"Expected category ErrorCategory.CCR_WWR_SPECIFIC, got {error.category!r}. "
        "Engine-implementer must add CCR_WWR_SPECIFIC to ErrorCategory enum."
    )


def test_p827_ccr010_counterparty_reference_cp_wwr_01() -> None:
    """CCR010 error must carry counterparty_reference CP_WWR_01 (for context).

    Arrange/Act: apply_wwr_gate on P8.27 bundle.
    Assert: CCR010 error.counterparty_reference == CP_WWR_01_REF.

    References: CRR Art. 291(4)-(5) — §2c: counterparty_reference on error
        record is for context; aggregation key is original netting_set_id.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr010_errors = [e for e in result.errors if e.code == CCR010_ERROR_CODE]
    assert len(ccr010_errors) >= 1, "No CCR010 error emitted — cannot check counterparty."
    error: CalculationError = ccr010_errors[0]
    assert error.counterparty_reference == CP_WWR_01_REF, (
        f"Expected CCR010.counterparty_reference == {CP_WWR_01_REF!r}, "
        f"got {error.counterparty_reference!r}."
    )


def test_p827_ccr010_regulatory_reference() -> None:
    """CCR010 error must cite CRR Art. 291(4)-(5).

    Arrange/Act: apply_wwr_gate on P8.27 bundle.
    Assert: CCR010 error.regulatory_reference == "CRR Art. 291(4)-(5)".

    References: CRR Art. 291(4)-(5) — specific WWR identification and treatment.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_wwr_gate(bundle)

    # Assert
    ccr010_errors = [e for e in result.errors if e.code == CCR010_ERROR_CODE]
    assert len(ccr010_errors) >= 1, "No CCR010 error emitted — cannot check regulatory_reference."
    error: CalculationError = ccr010_errors[0]
    assert error.regulatory_reference == CCR010_REGULATORY_REF, (
        f"Expected regulatory_reference {CCR010_REGULATORY_REF!r}, "
        f"got {error.regulatory_reference!r}."
    )
