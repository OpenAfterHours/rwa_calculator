"""
Unit tests — P1.180: covered-bond unrated-derivation table split CRR vs B31.

Pins the *shape* and *values* of the two new constants that the engine-implementer
will introduce in the next wave:

  COVERED_BOND_UNRATED_DERIVATION_CRR  — 4-key dict, CRR Art. 129(5)(a)-(d)
  COVERED_BOND_UNRATED_DERIVATION_B31  — 7-key dict, PRA PS1/26 Art. 129(5)

Also pins the nested CRR bug: today's shared dict maps 0.50 → 0.25 (the B31
Art. 129(5)(b) value); CRR Art. 129(5)(b) requires 0.50 → 0.20.

The behavioural test (Step E) exercises the _crr_unrated_cb_rw_expr() helper
with a one-row LazyFrame (cp_institution_cqs=3), confirming it resolves to
0.20 under CRR once the split is applied. Today the helper returns 0.25.

References:
    CRR Art. 129(5)(a)-(d): docs/assets/crr.pdf p.129
    PRA PS1/26 Art. 129(5)(a)/(aa)/(ab)/(b)/(ba)/(c)/(d): docs/assets/ps126app1.pdf
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

import rwa_calc.engine.sa.crr_risk_weight_tables as _crr_mod
from rwa_calc.engine.sa.crr_risk_weight_tables import INSTITUTION_RISK_WEIGHTS_CRR
from rwa_calc.engine.sa.risk_weights import _crr_unrated_cb_rw_expr


def _get_crr_table() -> dict:
    """Return COVERED_BOND_UNRATED_DERIVATION_CRR, failing with AssertionError if absent."""
    tbl = getattr(_crr_mod, "COVERED_BOND_UNRATED_DERIVATION_CRR", None)
    assert tbl is not None, (
        "COVERED_BOND_UNRATED_DERIVATION_CRR not found in rwa_calc.engine.sa.crr_risk_weight_tables — "
        "engine-implementer must add this constant (P1.180)"
    )
    return tbl


def _get_b31_table() -> dict:
    """Return COVERED_BOND_UNRATED_DERIVATION_B31, failing with AssertionError if absent.

    The symbol may live in crr_risk_weights or b31_risk_weights; we check both.
    """
    # Check crr_risk_weights first (re-export location per scenario §2)
    tbl = getattr(_crr_mod, "COVERED_BOND_UNRATED_DERIVATION_B31", None)
    if tbl is None:
        import rwa_calc.data.tables.b31_risk_weights as _b31_mod

        tbl = getattr(_b31_mod, "COVERED_BOND_UNRATED_DERIVATION_B31", None)
    assert tbl is not None, (
        "COVERED_BOND_UNRATED_DERIVATION_B31 not found in crr_risk_weights or b31_risk_weights — "
        "engine-implementer must add this constant (P1.180)"
    )
    return tbl


# =============================================================================
# CRR TABLE — CONSTANT-SHAPE PINS
# =============================================================================


class TestCRRDerivationTableShape:
    """CRR Art. 129(5)(a)-(d) mandates exactly four domain values."""

    def test_crr_table_has_four_keys(self) -> None:
        """COVERED_BOND_UNRATED_DERIVATION_CRR must have exactly 4 keys.

        Arrange: import the CRR derivation constant via _get_crr_table().
        Act:     count keys and compare key-set.
        Assert:  len == 4 and key-set == {0.20, 0.50, 1.00, 1.50}.
        """
        # Arrange
        _CRR = _get_crr_table()

        # Act
        n_keys = len(_CRR)
        keys = set(_CRR.keys())

        # Assert
        assert n_keys == 4, f"Expected 4 CRR keys, got {n_keys}: {keys}"
        assert keys == {
            Decimal("0.20"),
            Decimal("0.50"),
            Decimal("1.00"),
            Decimal("1.50"),
        }, f"CRR key-set mismatch: {keys}"

    def test_crr_table_art_129_5_a_d_values(self) -> None:
        """CRR Art. 129(5)(a)-(d) value mapping must match verbatim text.

        (a) 0.20 → 0.10
        (b) 0.50 → 0.20  ← BUG TODAY: shared dict returns 0.25
        (c) 1.00 → 0.50
        (d) 1.50 → 1.00

        Arrange: import the CRR derivation constant.
        Act:     look up each key.
        Assert:  each maps to the regulatory value.
        """
        # Arrange
        _CRR = _get_crr_table()

        # Act / Assert
        assert _CRR[Decimal("0.20")] == Decimal("0.10"), (
            f"Art. 129(5)(a): expected 0.10, got {_CRR.get(Decimal('0.20'))}"
        )
        assert _CRR[Decimal("0.50")] == Decimal("0.20"), (
            f"Art. 129(5)(b): expected 0.20, got {_CRR.get(Decimal('0.50'))} "
            "(bug: shared dict has 0.25 — this is the nested CRR/B31 divergence)"
        )
        assert _CRR[Decimal("1.00")] == Decimal("0.50"), (
            f"Art. 129(5)(c): expected 0.50, got {_CRR.get(Decimal('1.00'))}"
        )
        assert _CRR[Decimal("1.50")] == Decimal("1.00"), (
            f"Art. 129(5)(d): expected 1.00, got {_CRR.get(Decimal('1.50'))}"
        )

    def test_crr_table_excludes_b31_only_keys(self) -> None:
        """B31-only institution RWs must not appear in the CRR derivation table.

        Keys 0.30 (ECRA CQS2 B31), 0.40 (SCRA A) and 0.75 (SCRA B) are only
        reachable under PRA PS1/26 — they must be absent from the CRR table.

        Arrange: import the CRR derivation constant.
        Act:     test membership for each B31-only key.
        Assert:  each key is absent.
        """
        # Arrange
        _CRR = _get_crr_table()

        # Act / Assert
        assert Decimal("0.30") not in _CRR, "0.30 is a B31-only key; must not appear in _CRR"
        assert Decimal("0.40") not in _CRR, "0.40 is a B31-only key; must not appear in _CRR"
        assert Decimal("0.75") not in _CRR, "0.75 is a B31-only key; must not appear in _CRR"


# =============================================================================
# B31 TABLE — CONSTANT-SHAPE PINS
# =============================================================================


class TestB31DerivationTableShape:
    """PRA PS1/26 Art. 129(5) mandates exactly seven domain values."""

    def test_b31_table_has_seven_keys(self) -> None:
        """COVERED_BOND_UNRATED_DERIVATION_B31 must have exactly 7 keys.

        Arrange: import the B31 derivation constant.
        Act:     count keys.
        Assert:  len == 7 and key-set matches PS1/26 sub-paragraphs.
        """
        # Arrange
        _B31 = _get_b31_table()

        # Act
        n_keys = len(_B31)
        keys = set(_B31.keys())

        # Assert
        assert n_keys == 7, f"Expected 7 B31 keys, got {n_keys}: {keys}"
        assert keys == {
            Decimal("0.20"),
            Decimal("0.30"),
            Decimal("0.40"),
            Decimal("0.50"),
            Decimal("0.75"),
            Decimal("1.00"),
            Decimal("1.50"),
        }, f"B31 key-set mismatch: {keys}"

    def test_b31_table_art_129_5_b_value(self) -> None:
        """PRA PS1/26 Art. 129(5)(b): 0.50 → 0.25 (unchanged from the shared dict).

        Arrange: import the B31 derivation constant.
        Act:     look up key Decimal("0.50").
        Assert:  value equals Decimal("0.25").
        """
        # Arrange
        _B31 = _get_b31_table()

        # Act
        value = _B31[Decimal("0.50")]

        # Assert
        assert value == Decimal("0.25"), f"PS1/26 Art. 129(5)(b): expected 0.25, got {value}"


# =============================================================================
# IMAGE-SUBSET INVARIANT
# =============================================================================


class TestCRRDerivationCoverage:
    """Every reachable CRR institution RW must map to a CRR derivation key."""

    def test_crr_image_subset_of_institution_rws(self) -> None:
        """Institution RW image (incl. UNRATED) is a subset of CRR derivation domain.

        INSTITUTION_RISK_WEIGHTS_CRR image = {0.20, 0.50, 1.00, 1.50}.
        The UNRATED key resolves to 1.00 which is already covered by CQS4/CQS5.
        Every value in that image must have a matching key in _CRR.

        Arrange: collect unique CRR institution RWs.
        Act:     check membership in COVERED_BOND_UNRATED_DERIVATION_CRR.
        Assert:  every CRR institution RW has a derivation entry.
        """
        # Arrange
        _CRR = _get_crr_table()
        unique_rws = set(INSTITUTION_RISK_WEIGHTS_CRR.values())

        # Act / Assert
        for rw in unique_rws:
            assert rw in _CRR, (
                f"CRR institution RW {rw} is reachable (via INSTITUTION_RISK_WEIGHTS_CRR) "
                "but absent from COVERED_BOND_UNRATED_DERIVATION_CRR"
            )


# =============================================================================
# BEHAVIOURAL PIN — STEP E: _crr_unrated_cb_rw_expr() for CQS3 issuer
# =============================================================================


class TestCRRUnratedCBHelperExpression:
    """_crr_unrated_cb_rw_expr() must resolve CQS3 issuer to 20% CB RW under CRR.

    Chain (CRR Art. 120 Table 3 / Art. 129(5)):
        cp_institution_cqs = 3
          → INSTITUTION_RISK_WEIGHTS_CRR[CQS3] = 0.50
          → COVERED_BOND_UNRATED_DERIVATION_CRR[0.50] = 0.20

    Today the helper uses the shared dict (0.50 → 0.25) so returns 0.25.
    After the split it must return 0.20.
    """

    def test_crr_unrated_cb_rw_expr_cqs3_returns_0_20(self) -> None:
        """_crr_unrated_cb_rw_expr() for CQS3 institution issuer must return 0.20.

        Arrange: one-row LazyFrame with cp_institution_cqs = 3.
        Act:     evaluate _crr_unrated_cb_rw_expr() as column 'rw'.
        Assert:  rw == 0.20 (Art. 129(5)(b) correct value, not 0.25 bug value).
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "cp_institution_cqs": pl.Series([3], dtype=pl.Int8),
            }
        )

        # Act
        result = lf.with_columns(_crr_unrated_cb_rw_expr().alias("rw")).collect()

        # Assert
        actual = result.get_column("rw")[0]
        assert actual == pytest.approx(0.20), (
            f"CRR Art. 129(5)(b): expected CB RW = 0.20 for CQS3 issuer, "
            f"got {actual} (bug: shared dict maps 0.50 → 0.25 instead of 0.20)"
        )
