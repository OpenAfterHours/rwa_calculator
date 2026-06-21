"""
Unit tests for the FCCM SFT IRB effective-maturity carrier helper.

Drives :func:`_derive_ccr_sft_maturity_years` — the pure, approach-independent
derivation of the Art. 162 effective maturity M for a synthetic ``CCR_SFT``
exposure row. The carrier is the FULL M = ``clip(remaining_years, floor, 5.0)``
(the floor is a MINIMUM on the remaining maturity, never a fixed replacement),
read from the Phase-1b cited pack scalars / feature via the RUN rulepack.

Anchors (reporting_date 2026-01-01, /365 calendar day-count):

    under_mna=False                                              -> None  (162(2)(f))
    under_mna, qualifies_one_day, remaining=0       (CRR)        -> 1/365  (162(3))
    under_mna, qualifies_one_day, remaining=2/365   (CRR)        -> 2/365  (floor inert)
    under_mna, !one_day, remaining=2/365            (CRR)        -> 5/365  (162(2)(d), A0-5)
    under_mna, !one_day, remaining=0.8              (CRR)        -> 0.8    (floor inert)
    under_mna, !one_day, remaining=6.0              (CRR)        -> 5.0    (cap)
    under_mna, !one_day, remaining=2/365  B31 !mna_inter        -> None   (B31 daily gate)
    under_mna, !one_day, remaining=2/365  B31  mna_inter        -> 5/365

References:
    CRR Art. 162(2)(d) — 5-day repo/SFT M floor under an MNA.
    CRR Art. 162(3) — one-day (~1/365 y) floor (daily re-margin AND revaluation).
    PS1/26 Art. 162(2A)(c)/(d) — B31 daily-condition gate on the 5BD/10BD floors.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.engine.sft.fccm import _derive_ccr_sft_maturity_years
from rwa_calc.rulebook.resolve import resolve

_D = date(2026, 1, 1)
_CRR_PACK = resolve("crr", _D)
_B31_PACK = resolve("b31", _D)

_ONE_DAY = 1.0 / 365.0
_FIVE_DAY = 5.0 / 365.0
_TWO_DAY = 2.0 / 365.0

_REL_TOL = 1e-12


def test_not_under_mna_returns_none() -> None:
    """No master netting agreement -> date-derived 1y catch-all (carrier None)."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=2.0 / 365.0,
        under_mna=False,
        qualifies_one_day_floor=True,
        qualifies_mna_intermediate_floor=True,
        pack=_CRR_PACK,
    )
    assert result is None


def test_remaining_none_returns_none() -> None:
    """A null maturity_date (remaining_years None) -> carrier None."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=None,
        under_mna=True,
        qualifies_one_day_floor=True,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result is None


def test_one_day_floor_binds_at_zero_remaining() -> None:
    """Overnight daily-MNA repo (162(3)) -> one-day floor 1/365."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=0.0,
        under_mna=True,
        qualifies_one_day_floor=True,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result == pytest.approx(_ONE_DAY, rel=_REL_TOL)


def test_one_day_floor_inert_above_one_day() -> None:
    """One-day floor does not bite when remaining exceeds it (M = remaining)."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=_TWO_DAY,
        under_mna=True,
        qualifies_one_day_floor=True,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result == pytest.approx(_TWO_DAY, rel=_REL_TOL)


def test_crr_repo_intermediate_floor_binds() -> None:
    """A0-5: CRR MNA repo, non-daily, short -> 5BD = 5/365 floor binds."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=_TWO_DAY,
        under_mna=True,
        qualifies_one_day_floor=False,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result == pytest.approx(_FIVE_DAY, rel=_REL_TOL)


def test_crr_repo_intermediate_floor_inert_when_long() -> None:
    """CRR MNA repo, 0.8y remaining -> 5BD floor inert, M = 0.8."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=0.8,
        under_mna=True,
        qualifies_one_day_floor=False,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result == pytest.approx(0.8, rel=_REL_TOL)


def test_crr_repo_caps_at_five_years() -> None:
    """CRR MNA repo, 6y remaining -> capped at 5.0y."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=6.0,
        under_mna=True,
        qualifies_one_day_floor=False,
        qualifies_mna_intermediate_floor=False,
        pack=_CRR_PACK,
    )
    assert result == pytest.approx(5.0, rel=_REL_TOL)


def test_b31_intermediate_floor_gated_off_without_daily_condition() -> None:
    """B31 MNA repo lacking the daily condition -> 162(2A)(f) 1y catch-all (None)."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=_TWO_DAY,
        under_mna=True,
        qualifies_one_day_floor=False,
        qualifies_mna_intermediate_floor=False,
        pack=_B31_PACK,
    )
    assert result is None


def test_b31_intermediate_floor_binds_with_daily_condition() -> None:
    """B31 MNA repo with the daily condition -> 5BD = 5/365 floor binds."""
    result = _derive_ccr_sft_maturity_years(
        remaining_years=_TWO_DAY,
        under_mna=True,
        qualifies_one_day_floor=False,
        qualifies_mna_intermediate_floor=True,
        pack=_B31_PACK,
    )
    assert result == pytest.approx(_FIVE_DAY, rel=_REL_TOL)
