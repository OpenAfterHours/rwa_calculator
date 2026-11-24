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

The Basel 3.1 scalar is the Art. 133(3) END-STATE weight. PS1/26 General
Provisions rule 4.2 modifies Art. 133(3) to 160% / 190% / 220% in 2027-2029 for
a firm without IRB permission on 31 December 2026 (rule 4.1), and the engine
selects that weight in place of this scalar
(``engine/crm/simple_method.py::_fcsm_equity_collateral_rw``, P1.392; pinned by
tests/acceptance/basel31/test_p1_392_fcsm_equity_collateral_transitional.py).
The Basel 3.1 pack is therefore read here on an end-state date.

References:
- CRR Art. 222(3): Financial Collateral Simple Method, collateralised portion
- CRR Art. 133(2): equity SA risk weight (100%)
- PS1/26 Art. 133(3): equity SA risk weight (250%, end state)
- PS1/26 Credit Risk: General Provisions rules 4.1-4.2: the 2027-2029 weights
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.domain.enums import EquityType
from rwa_calc.rulebook.resolve import resolve

CRR_ON = date(2026, 1, 1)
#: The Art. 133(3) end state: after the rule 4.2 period (1 Jan 2027 - 31 Dec 2029).
B31_ON = date(2030, 1, 1)


def test_b31_fcsm_equity_collateral_rw_is_250_pct() -> None:
    """The Basel 3.1 end-state FCSM equity collateral weight is PS1/26 Art. 133(3)'s 250%.

    In 2027-2029 a firm without IRB permission on 31 December 2026 takes the
    rule 4.2 weight instead; the engine selects it, not this scalar (P1.392).
    """
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
    """Art. 222(3) DERIVES the weight, so the end-state scalar cannot drift from Chapter 2.

    Ties the FCSM scalar to the end-state ``equity_sa_risk_weights`` in each
    regime. Only main-index equity reaches the Simple Method (P1.330 gated it
    on Art. 197(1)(f)), and a main-index holding is listed / exchange-traded,
    so those are the rows the derivation must match. Without this, a later edit
    to the equity table would leave the FCSM scalar quietly stale — exactly how
    the 100% survived.

    Both are end-state weights: in 2027-2029 rule 4.2 modifies Art. 133(3) for
    a firm without IRB permission on 31 December 2026, for direct equity and so
    for the Art. 222(3) collateral weight alike (P1.392). That modification is
    applied in the engine and pinned by
    tests/acceptance/basel31/test_p1_392_fcsm_equity_collateral_transitional.py.
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
