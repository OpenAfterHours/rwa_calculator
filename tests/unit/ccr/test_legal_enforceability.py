"""
Unit tests for apply_legal_enforceability_gate (P8.18).

Pins the expected behaviour of the legal-enforceability gate per
CRR Art. 272(4) second subparagraph + Art. 295-297:

    When a netting set's ``is_legally_enforceable`` flag is ``False``,
    each trade in that netting set must be expanded into its own
    single-trade synthetic netting set (suffix ``__split__<trade_id>``),
    and ONE ``CalculationError(code="CCR001", severity=WARNING,
    category=ErrorCategory.CCR_LEGAL)`` must be appended to
    ``RawCCRBundle.errors`` per affected original netting set.

Scenario (P8.18 fixture):
    NS_Q1  (CP_XX, is_legally_enforceable=False, unmargined)
    ├── T_A  mtm=+100, delta=+1, notional=100 m
    └── T_B  mtm=-60,  delta=-1, notional=80 m

After gate expansion:
    trades netting_set_id  → {NS_Q1__split__T_A, NS_Q1__split__T_B}
    netting_sets            → 2 rows (one per split)
    bundle.errors           → 1 error (one per original NS)

References:
    - CRR Art. 272(4): netting set definition and legal-enforceability gate
    - CRR Art. 295-297: conditions for contractual netting recognition
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
# The gate does not exist yet — engine-implementer adds it in Wave 4.
# If the import fails we set the name to None so tests fail with TypeError
# (on the call site), not ImportError (at collection time).
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.sa_ccr import apply_legal_enforceability_gate
except ImportError:
    apply_legal_enforceability_gate = None  # ty: ignore[invalid-assignment]

# ---------------------------------------------------------------------------
# Fixture constants (single source of truth from fixture module)
# ---------------------------------------------------------------------------
from tests.fixtures.ccr.p8_18_non_enforceable import (
    CCR_ERROR_ACTUAL_VALUE,
    CCR_ERROR_CODE,
    CCR_ERROR_EXPECTED_VALUE,
    CCR_ERROR_FIELD,
    CCR_ERROR_REGULATORY_REF,
    CP_XX_REF,
    NS_Q1_ID,
    SPLIT_NS_ID_T_A,
    SPLIT_NS_ID_T_B,
    create_p818_collateral,
    create_p818_margin_agreements,
    create_p818_netting_sets,
    create_p818_trades,
)

# ---------------------------------------------------------------------------
# Shared bundle factory
# ---------------------------------------------------------------------------


def _make_bundle() -> RawCCRBundle:
    """Build a RawCCRBundle from P8.18 fixture frames.

    Wraps each ``pl.DataFrame`` with ``.lazy()`` to satisfy the
    ``LazyFrame`` typing on the leaf bundles.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_p818_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_p818_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_p818_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_p818_collateral().lazy()),
    )


# ===========================================================================
# 1. Trade netting_set_id split correctness
# ===========================================================================


def test_gate_splits_trades_into_synthetic_netting_sets() -> None:
    """Gate must reassign each trade to its own synthetic netting set id.

    Arrange:
        RawCCRBundle with 2 trades (T_A, T_B) in NS_Q1 (not legally enforceable).

    Act:
        apply_legal_enforceability_gate(bundle)

    Assert:
        Unique netting_set_id values in trades == {SPLIT_NS_ID_T_A, SPLIT_NS_ID_T_B}.

    References: CRR Art. 272(4) second subparagraph.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    ids = result.trades.trades.collect()["netting_set_id"].unique().sort().to_list()
    assert ids == sorted([SPLIT_NS_ID_T_A, SPLIT_NS_ID_T_B]), (
        f"Expected synthetic netting_set_ids {sorted([SPLIT_NS_ID_T_A, SPLIT_NS_ID_T_B])!r}, "
        f"got {ids!r}. "
        "CRR Art. 272(4): non-enforceable NS expands each trade into its own single-trade NS."
    )


# ===========================================================================
# 2. Trade row count preserved
# ===========================================================================


def test_gate_preserves_trade_row_count() -> None:
    """Gate must not add or drop trade rows; only netting_set_id changes.

    Arrange:
        RawCCRBundle with 2 trades.

    Act:
        apply_legal_enforceability_gate(bundle)

    Assert:
        trades LazyFrame row count == 2.

    References: CRR Art. 272(4).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    row_count = result.trades.trades.collect().height
    assert row_count == 2, (
        f"Expected 2 trade rows after gate expansion (T_A + T_B), got {row_count}. "
        "Gate must only remap netting_set_id, not filter or duplicate trades."
    )


# ===========================================================================
# 3. Netting-set row count expansion
# ===========================================================================


def test_gate_expands_netting_sets_per_trade() -> None:
    """Gate must produce one synthetic netting-set row per split trade.

    Arrange:
        1-row netting_sets LazyFrame (NS_Q1).

    Act:
        apply_legal_enforceability_gate(bundle)

    Assert:
        netting_sets LazyFrame row count == 2 (one per trade in NS_Q1).

    References: CRR Art. 272(4): each trade becomes its own single-trade NS.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    ns_count = result.netting_sets.netting_sets.collect().height
    assert ns_count == 2, (
        f"Expected 2 synthetic netting-set rows (one per trade in NS_Q1), got {ns_count}. "
        "CRR Art. 272(4): 1 original NS with 2 trades → 2 single-trade synthetic NSs."
    )


# ===========================================================================
# 4. Error count — one per affected original netting set
# ===========================================================================


def test_gate_emits_one_warning_per_affected_netting_set() -> None:
    """Gate must append exactly one CalculationError per non-enforceable NS.

    Arrange:
        1 non-enforceable netting set (NS_Q1).

    Act:
        apply_legal_enforceability_gate(bundle)

    Assert:
        len(bundle.errors) == 1.

    References: CRR Art. 272(4): one error emitted per affected original NS.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    assert len(result.errors) == 1, (
        f"Expected exactly 1 CalculationError for NS_Q1 (not legally enforceable), "
        f"got {len(result.errors)}. "
        "Gate emits one CCR001 warning per original non-enforceable netting set."
    )


# ===========================================================================
# 5-10. Error field assertions (each tests one field on the single error)
# ===========================================================================


def test_gate_error_code_ccr001() -> None:
    """Error code must be CCR001.

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].code == "CCR001".
    References: CRR Art. 272(4).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.code == CCR_ERROR_CODE, (
        f"Expected error code {CCR_ERROR_CODE!r}, got {error.code!r}."
    )


def test_gate_error_severity_warning() -> None:
    """Error severity must be WARNING (non-fatal; calculation continues).

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].severity == ErrorSeverity.WARNING.
    References: CRR Art. 272(4).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.severity == ErrorSeverity.WARNING, (
        f"Expected severity WARNING, got {error.severity!r}. "
        "Legal-enforceability failure is non-fatal — gate falls back to single-trade NS."
    )


def test_gate_error_category_ccr_legal() -> None:
    """Error category must be ErrorCategory.CCR_LEGAL (new enum value).

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].category == ErrorCategory.CCR_LEGAL.
    References: CRR Art. 272(4); Art. 295-297.
    """
    from rwa_calc.domain.enums import ErrorCategory  # deferred to catch missing value

    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.category == ErrorCategory.CCR_LEGAL, (
        f"Expected category ErrorCategory.CCR_LEGAL, got {error.category!r}. "
        "Engine-implementer must add CCR_LEGAL to ErrorCategory enum in domain/enums.py."
    )


def test_gate_error_counterparty_cp_xx() -> None:
    """Error must carry the counterparty_reference of the original netting set.

    Arrange/Act: apply gate on P8.18 bundle (NS_Q1, counterparty CP_XX).
    Assert: errors[0].counterparty_reference == CP_XX_REF.
    References: CRR Art. 272(4).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.counterparty_reference == CP_XX_REF, (
        f"Expected counterparty_reference {CP_XX_REF!r}, got {error.counterparty_reference!r}."
    )


def test_gate_error_regulatory_reference_art_272_4() -> None:
    """Error must cite CRR Art. 272(4) and Art. 295-297.

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].regulatory_reference == "CRR Art. 272(4); Art. 295-297".
    References: CRR Art. 272(4); Art. 295-297.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.regulatory_reference == CCR_ERROR_REGULATORY_REF, (
        f"Expected regulatory_reference {CCR_ERROR_REGULATORY_REF!r}, "
        f"got {error.regulatory_reference!r}."
    )


def test_gate_error_message_contains_netting_set_id() -> None:
    """Error message must contain the original netting_set_id (NS_Q1).

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: NS_Q1_ID in errors[0].message.
    References: CRR Art. 272(4).
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert NS_Q1_ID in error.message, (
        f"Expected netting_set_id {NS_Q1_ID!r} to appear in the error message, "
        f"got {error.message!r}."
    )


# ===========================================================================
# 11-13. Error field-level attribute assertions (C3.5)
# ===========================================================================


def test_gate_error_field_name_is_legally_enforceable() -> None:
    """Error field_name must be the name of the offending column.

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].field_name == CCR_ERROR_FIELD  (i.e. "is_legally_enforceable").
    References: CRR Art. 272(4); Art. 295-297.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.field_name == CCR_ERROR_FIELD, (
        f"Expected field_name {CCR_ERROR_FIELD!r}, got {error.field_name!r}. "
        "Engine must record the offending column name on the CalculationError."
    )


def test_gate_error_expected_value() -> None:
    """Error expected_value must describe the compliant state per Art. 295.

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].expected_value == CCR_ERROR_EXPECTED_VALUE
            (i.e. "True (Art. 295 conditions met)").
    References: CRR Art. 272(4); Art. 295-297.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.expected_value == CCR_ERROR_EXPECTED_VALUE, (
        f"Expected expected_value {CCR_ERROR_EXPECTED_VALUE!r}, "
        f"got {error.expected_value!r}. "
        "Engine must record the compliant expected value on the CalculationError."
    )


def test_gate_error_actual_value() -> None:
    """Error actual_value must record the observed flag value ("False").

    Arrange/Act: apply gate on P8.18 bundle.
    Assert: errors[0].actual_value == CCR_ERROR_ACTUAL_VALUE  (i.e. "False").
    References: CRR Art. 272(4); Art. 295-297.
    """
    # Arrange
    bundle = _make_bundle()

    # Act
    result = apply_legal_enforceability_gate(bundle)

    # Assert
    error: CalculationError = result.errors[0]
    assert error.actual_value == CCR_ERROR_ACTUAL_VALUE, (
        f"Expected actual_value {CCR_ERROR_ACTUAL_VALUE!r}, "
        f"got {error.actual_value!r}. "
        "Engine must record the observed actual value on the CalculationError."
    )
