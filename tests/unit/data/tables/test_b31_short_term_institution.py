"""
Unit tests for B31_ECRA_SHORT_TERM_RISK_WEIGHTS data table.

Verifies that CQS 4 and CQS 5 carry the correct 50% risk weight for rated
institution exposures with residual maturity ≤ 3 months under Basel 3.1
Art. 120(2) Table 4, not the erroneous 20% that CQS 1-3 receive.

Why this matters:
    PRA PS1/26 Art. 120(2) Table 4 draws a clear boundary between CQS 1-3
    (all 20%) and CQS 4-5 (50%).  The current data table assigns 20% to every
    CQS from 1 to 5, understating capital by 30 percentage points for CQS 4
    and 5 counterparties on all short-term institution exposures.

References:
    - PRA PS1/26 Art. 120(2), Table 4: ECRA short-term institution risk weights
    - BCBS CRE20.17: short-term rated institution weights
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rwa_calc.engine.sa.b31_risk_weight_tables import B31_ECRA_SHORT_TERM_RISK_WEIGHTS

# =============================================================================
# CQS 4 AND CQS 5 — MUST BE 50% (the bug)
# =============================================================================


class TestB31ECRAShortTermRiskWeights:
    """Data-table unit tests for B31_ECRA_SHORT_TERM_RISK_WEIGHTS.

    PRA PS1/26 Art. 120(2) Table 4 splits into three bands:
        - CQS 1-3: 20%
        - CQS 4-5: 50%   <- currently wrong (bug assigns 20%)
        - CQS 6:   150%
    """

    # -------------------------------------------------------------------------
    # B31-D1: CQS 4 short-term must be 50%
    # -------------------------------------------------------------------------

    def test_b31_ecra_short_term_cqs4_risk_weight_is_50pct(self) -> None:
        """Art. 120(2) Table 4: CQS 4 short-term institution RW = 50%.

        Arrange: import the published data-table constant.
        Act:     look up key 4.
        Assert:  value equals Decimal("0.50").
        """
        # Arrange / Act
        rw = B31_ECRA_SHORT_TERM_RISK_WEIGHTS[4]

        # Assert
        assert rw == Decimal("0.50"), (
            f"Expected CQS 4 short-term RW = 0.50 (50%) per Art. 120(2) Table 4, got {rw}"
        )

    # -------------------------------------------------------------------------
    # B31-D2: CQS 5 short-term must be 50%
    # -------------------------------------------------------------------------

    def test_b31_ecra_short_term_cqs5_risk_weight_is_50pct(self) -> None:
        """Art. 120(2) Table 4: CQS 5 short-term institution RW = 50%.

        Arrange: import the published data-table constant.
        Act:     look up key 5.
        Assert:  value equals Decimal("0.50").
        """
        # Arrange / Act
        rw = B31_ECRA_SHORT_TERM_RISK_WEIGHTS[5]

        # Assert
        assert rw == Decimal("0.50"), (
            f"Expected CQS 5 short-term RW = 0.50 (50%) per Art. 120(2) Table 4, got {rw}"
        )

    # -------------------------------------------------------------------------
    # Regression pins — CQS 1, CQS 6 must not be disturbed by the fix
    # -------------------------------------------------------------------------

    def test_b31_ecra_short_term_cqs1_risk_weight_is_20pct(self) -> None:
        """Art. 120(2) Table 4: CQS 1 short-term institution RW = 20% (regression pin)."""
        # Arrange / Act
        rw = B31_ECRA_SHORT_TERM_RISK_WEIGHTS[1]

        # Assert
        assert rw == Decimal("0.20"), f"CQS 1 short-term RW must remain 0.20, got {rw}"

    def test_b31_ecra_short_term_cqs6_risk_weight_is_150pct(self) -> None:
        """Art. 120(2) Table 4: CQS 6 short-term institution RW = 150% (regression pin)."""
        # Arrange / Act
        rw = B31_ECRA_SHORT_TERM_RISK_WEIGHTS[6]

        # Assert
        assert rw == Decimal("1.50"), f"CQS 6 short-term RW must remain 1.50, got {rw}"

    @pytest.mark.parametrize(
        ("cqs", "expected"),
        [
            (1, Decimal("0.20")),
            (2, Decimal("0.20")),
            (3, Decimal("0.20")),
            (4, Decimal("0.50")),
            (5, Decimal("0.50")),
            (6, Decimal("1.50")),
        ],
        ids=["cqs1_20pct", "cqs2_20pct", "cqs3_20pct", "cqs4_50pct", "cqs5_50pct", "cqs6_150pct"],
    )
    def test_b31_ecra_short_term_full_table(self, cqs: int, expected: Decimal) -> None:
        """Art. 120(2) Table 4: complete CQS band check (three-way split).

        CQS 1-3 = 20%, CQS 4-5 = 50%, CQS 6 = 150%.
        """
        # Arrange / Act
        rw = B31_ECRA_SHORT_TERM_RISK_WEIGHTS[cqs]

        # Assert
        assert rw == expected, f"CQS {cqs} short-term RW: expected {expected}, got {rw}"
