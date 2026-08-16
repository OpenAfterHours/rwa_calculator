"""P1.296 — FCSM equity collateral takes the regime's Chapter 2 equity weight.

CRR Art. 222(3) gives the collateralised portion "the risk weight that they
would assign under Chapter 2 of Title II ... where the lending institution had
a direct exposure to the collateral instrument". The weight is therefore
DERIVED from Chapter 2 rather than prescribed by Art. 222, and Chapter 2's
equity weight is regime-divergent: CRR Art. 133(2) gives 100%, PS1/26 Art. 133
gives 250%. ``fcsm_equity_collateral_rw`` was pinned regime-invariantly at
100% in the common pack, understating the blended FCSM weight under Basel 3.1.

Art. 222(1) — cited by the old entry and by the source comment this item
rewrote — is the *usage restriction* on electing the Simple Method and
prescribes no weight at all.

References:
- CRR Art. 222(3): Financial Collateral Simple Method, collateralised portion
- CRR Art. 133(2): equity SA risk weight (100%)
- PS1/26 Art. 133: equity SA risk weight (250%)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.domain.enums import EquityType
from rwa_calc.rulebook.resolve import resolve

CRR_ON = date(2026, 1, 1)
B31_ON = date(2027, 1, 1)


def test_b31_fcsm_equity_collateral_rw_is_250_pct() -> None:
    """Basel 3.1 FCSM equity collateral takes PS1/26 Art. 133's 250%."""
    # Arrange
    pack = resolve("b31", B31_ON)

    # Act
    value = pack.scalar("fcsm_equity_collateral_rw")

    # Assert — the moving value; 1.00 here is the pre-fix defect
    assert value == Decimal("2.50")


def test_crr_fcsm_equity_collateral_rw_stays_100_pct() -> None:
    """The CRR leg must NOT move — Art. 133(2) is still 100%.

    Load-bearing guard: a fix that simply retyped the scalar to 250% for both
    regimes would pass the Basel 3.1 assertion above while breaking CRR.
    """
    # Arrange
    pack = resolve("crr", CRR_ON)

    # Act
    value = pack.scalar("fcsm_equity_collateral_rw")

    # Assert
    assert value == Decimal("1.00")


def test_fcsm_equity_collateral_rw_is_regime_divergent() -> None:
    """The two regimes must disagree — the whole point of the move.

    Stated as an identity rather than two literals so that a future revaluation
    of either leg cannot silently collapse the entry back to regime-invariant,
    which is the defect this item fixed.
    """
    # Arrange
    crr = resolve("crr", CRR_ON)
    b31 = resolve("b31", B31_ON)

    # Act
    crr_value = crr.scalar("fcsm_equity_collateral_rw")
    b31_value = b31.scalar("fcsm_equity_collateral_rw")

    # Assert
    assert crr_value != b31_value
    assert b31_value > crr_value


def test_fcsm_equity_collateral_rw_tracks_chapter_2_equity_table() -> None:
    """Art. 222(3) DERIVES the weight, so it cannot drift from Chapter 2.

    Ties the FCSM scalar to ``equity_sa_risk_weights`` in each regime. Only
    main-index equity reaches the Simple Method (P1.330 gated it on
    Art. 197(1)(f)), and a main-index holding is listed / exchange-traded, so
    those are the rows the derivation must match. Without this, a later edit to
    the equity table would leave the FCSM scalar quietly stale — exactly how
    the 100% survived.
    """
    for regime, on in (("crr", CRR_ON), ("b31", B31_ON)):
        # Arrange
        pack = resolve(regime, on)
        equity_table = pack.lookup("equity_sa_risk_weights").entries

        # Act
        fcsm_rw = pack.scalar("fcsm_equity_collateral_rw")

        # Assert — both main-index-capable equity types agree with the scalar
        assert fcsm_rw == equity_table[EquityType.LISTED], regime
        assert fcsm_rw == equity_table[EquityType.EXCHANGE_TRADED], regime
