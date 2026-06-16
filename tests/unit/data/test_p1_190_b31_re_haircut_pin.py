"""
P1.190: Pin BASEL31_COLLATERAL_HAIRCUTS["real_estate"] == Decimal("0.40").

Bug (c): src/rwa_calc/data/tables/haircuts.py currently sets
    BASEL31_COLLATERAL_HAIRCUTS["real_estate"] = Decimal("0.00")
with a comment "Handled via LTV, not HC haircut".

PS1/26 Art. 230(2) tabulates HC = 40% for immovable property under the
Foundation Collateral Method (FCM). The current value of 0.00 causes the engine
to skip the haircut on RE collateral under Basel 3.1, overstating the effective
secured portion and understating LGD*.

Three regression guards also lock existing correct values:
  - BASEL31_COLLATERAL_HAIRCUTS["receivables"] == Decimal("0.40")  (already correct)
  - BASEL31_COLLATERAL_HAIRCUTS["other_physical"] == Decimal("0.40")  (already correct)
  - COLLATERAL_HAIRCUTS["real_estate"] == Decimal("0.00")  (CRR must stay at 0)

References:
    - PRA PS1/26 Art. 230(2): HC table — 40% for immovable property under FCM
    - PRA PS1/26 Art. 230(2): HC table — 40% for receivables under FCM
    - CRR Art. 230: no HC term; OC ratio (1.4x/1.25x) is the sole credit-quality mechanism
    - IMPLEMENTATION_PLAN.md: P1.190 — bug (c)
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.engine.crm.haircut_tables import BASEL31_COLLATERAL_HAIRCUTS, COLLATERAL_HAIRCUTS


class TestP1190B31RealEstateHaircutPin:
    """
    P1.190: Assert the PS1/26 Art. 230(2) real_estate haircut constant and
    regression-guard the three neighbouring values.
    """

    def test_b31_real_estate_haircut_is_40_pct(self) -> None:
        """
        P1.190 LOAD-BEARING (bug c): BASEL31_COLLATERAL_HAIRCUTS["real_estate"] == Decimal("0.40").

        PRA PS1/26 Art. 230(2) explicitly lists HC = 40% for immovable property
        (real estate / physical property) under the Foundation Collateral Method.
        The pre-fix value Decimal("0.00") is incorrect — the comment "Handled via LTV"
        confuses the SA LTV-based risk weight mechanism with the IRB FCM HC mechanism.

        Arrange: import BASEL31_COLLATERAL_HAIRCUTS.
        Act:     read BASEL31_COLLATERAL_HAIRCUTS["real_estate"].
        Assert:  value == Decimal("0.40").

        Pre-fix: Decimal("0.00") — test FAILS here with AssertionError.
        Post-fix: Decimal("0.40").
        """
        # Arrange / Act
        actual = BASEL31_COLLATERAL_HAIRCUTS["real_estate"]

        # Assert
        assert actual == Decimal("0.40"), (
            f"P1.190 bug (c): BASEL31_COLLATERAL_HAIRCUTS['real_estate'] must be "
            f"Decimal('0.40') per PRA PS1/26 Art. 230(2) HC table (immovable property). "
            f"Got {actual!r}. "
            f"Pre-fix value Decimal('0.00') is wrong — 'Handled via LTV' applies to "
            f"SA risk weights, not the F-IRB Foundation Collateral Method HC term."
        )

    def test_b31_receivables_haircut_regression_guard(self) -> None:
        """
        REGRESSION GUARD: BASEL31_COLLATERAL_HAIRCUTS["receivables"] must stay at Decimal("0.40").

        This value is already correct (PS1/26 Art. 230(2): HC=40% for receivables).
        This test locks it so the engine-implementer cannot accidentally regress it.

        Arrange: import BASEL31_COLLATERAL_HAIRCUTS.
        Act:     read BASEL31_COLLATERAL_HAIRCUTS["receivables"].
        Assert:  value == Decimal("0.40").
        """
        # Arrange / Act
        actual = BASEL31_COLLATERAL_HAIRCUTS["receivables"]

        # Assert
        assert actual == Decimal("0.40"), (
            f"P1.190 regression guard: BASEL31_COLLATERAL_HAIRCUTS['receivables'] "
            f"must remain Decimal('0.40') (PRA PS1/26 Art. 230(2)). Got {actual!r}."
        )

    def test_b31_other_physical_haircut_regression_guard(self) -> None:
        """
        REGRESSION GUARD: BASEL31_COLLATERAL_HAIRCUTS["other_physical"] must stay at Decimal("0.40").

        This value is already correct (PS1/26 Art. 230(2): HC=40% for other physical assets).
        This test locks it so the engine-implementer cannot accidentally regress it.

        Arrange: import BASEL31_COLLATERAL_HAIRCUTS.
        Act:     read BASEL31_COLLATERAL_HAIRCUTS["other_physical"].
        Assert:  value == Decimal("0.40").
        """
        # Arrange / Act
        actual = BASEL31_COLLATERAL_HAIRCUTS["other_physical"]

        # Assert
        assert actual == Decimal("0.40"), (
            f"P1.190 regression guard: BASEL31_COLLATERAL_HAIRCUTS['other_physical'] "
            f"must remain Decimal('0.40') (PRA PS1/26 Art. 230(2)). Got {actual!r}."
        )

    def test_crr_real_estate_haircut_regression_guard(self) -> None:
        """
        REGRESSION GUARD: COLLATERAL_HAIRCUTS["real_estate"] must remain Decimal("0.00") (CRR).

        Under CRR Art. 230 there is no HC term — the only credit-quality mechanism for
        non-financial collateral is the overcollateralisation ratio (1.4x RE / 1.25x
        receivables). The CRR table value must not change when bug (c) is fixed.

        Arrange: import COLLATERAL_HAIRCUTS.
        Act:     read COLLATERAL_HAIRCUTS["real_estate"].
        Assert:  value == Decimal("0.00").
        """
        # Arrange / Act
        actual = COLLATERAL_HAIRCUTS["real_estate"]

        # Assert
        assert actual == Decimal("0.00"), (
            f"P1.190 regression guard: COLLATERAL_HAIRCUTS['real_estate'] "
            f"must remain Decimal('0.00') for CRR (no HC term in CRR Art. 230). "
            f"Got {actual!r}."
        )
