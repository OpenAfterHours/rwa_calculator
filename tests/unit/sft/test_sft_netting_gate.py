"""
CC-14: an SFT netting set is netted into one E* only under an ELIGIBLE master
netting agreement with ONE counterparty.

Pre-fix, ``engine/sft/fccm.py`` summed E(1+HE) and the collateral over every
trade sharing a ``netting_set_id`` with no eligibility test, and booked the set
against ``counterparty_reference.first()``. Measured: T1 cash 100m vs 150m gilts
plus T2 cash 100m uncollateralised in one set with no master netting agreement
gave E* = 52,121,320 (T1's surplus gilts offset T2); two counterparties in one
set booked 200m against the first one.

Rule text:
- CRR Art. 220(1) / PS1/26 Art. 220(1): the netted E* is calculated "for the
  exposures subject to an eligible master netting agreement covering securities
  financing transactions".
- PS1/26 Art. 206(1): master netting agreements are an eligible form of credit
  risk mitigation where "(a) they are legally effective and enforceable in all
  relevant jurisdictions, including in the event of the bankruptcy or insolvency
  of the counterparty; (b) they give the non-defaulting party the right to
  terminate and close-out ...; (c) they provide for the netting of gains and
  losses ...; and (d) they allow for the prompt liquidation or set-off of
  collateral upon the event of default." (CRR Art. 206 is the same.)
- PS1/26 Art. 111(2A): "where the institution takes into account a master
  netting agreement in relation to a set of securities financing transactions,
  it shall calculate the exposure value for all transactions covered by that
  master netting agreement as a single exposure value at netting set level" —
  otherwise per transaction, Art. 223(5).
- CRR / PS1/26 Art. 220(4): E* is "the exposure value of the exposure to the
  counterparty" — one counterparty per agreement.

Eligibility is attested per trade by ``under_master_netting_agreement`` AND
``is_legally_enforceable`` (both default False); a set nets only when every
trade carries both and the set has one counterparty. Otherwise each trade is its
own exposure (``<ns>__split__<trade_id>``), collateral follows its trade through
the optional ``trade_id`` link, and an unlinked row is not recognised. The
eligible-MNA case keeps the existing gross sum (Sum E(1+HE) - Sum C(1-HC-HFX)),
which is never below the Art. 220(3) net formula; that formula is deferred.

References:
    CRR / PS1/26 Art. 206(1), 220(1), 220(4), 223(5); PS1/26 Art. 111(2A).
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.errors import (
    ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET,
    ERROR_SFT_NETTING_NOT_RECOGNISED,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.ccr.sft_fccm_review_builder import (
    SFT_REVIEW_CP_CQS2,
    SFT_REVIEW_CP_CQS4,
    build_sft_bundle,
    sft_collateral,
    sft_trade,
)

_PACKS = {
    "crr": resolve("crr", date(2026, 6, 30)),
    "b31": resolve("b31", date(2027, 6, 30)),
}
_REPORTING_DATE = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}
_SQRT_HALF = math.sqrt(5 / 10)
#: 150m CQS 1 gilts, 2y residual: H_10 2% in both regimes (CRR 1-5y, PS1/26 1-3y).
_GILT_CVA = 150_000_000.0 * (1 - 0.02 * _SQRT_HALF)
_NETTED_ESTAR = 200_000_000.0 - _GILT_CVA  # 52,121,320.34
_REL = 1e-12
_MNA = {"under_master_netting_agreement": True, "is_legally_enforceable": True}


def _gilts(netting_set_id: str = "S1", **kw: object) -> dict:
    return sft_collateral(
        "C_GILT",
        netting_set_id,
        "gilt",
        150_000_000.0,
        issuer_cqs=1,
        residual_maturity_years=2.0,
        **kw,
    )


def _run(
    regime: str, trades: list[dict], collateral: list[dict] | None
) -> tuple[pl.DataFrame, list]:
    rows, errors = sft_bundle_to_exposures(
        build_sft_bundle(trades, collateral), _REPORTING_DATE[regime], rulepack=_PACKS[regime]
    )
    return rows.collect().sort("exposure_reference"), errors


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_set_without_eligible_mna_is_split_per_trade(regime: str) -> None:
    """No MNA flags: T1 (gilts linked) E* = 0, T2 E* = 100m; total 100m, not 52.1m."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R2", "S1")]
    collateral = [_gilts(trade_id="R1")]
    assert _GILT_CVA > 100_000_000.0, "T1 must be over-collateralised for the offset to show"

    # Act
    frame, errors = _run(regime, trades, collateral)

    # Assert
    assert frame["exposure_reference"].to_list() == ["ccr__S1__split__R1", "ccr__S1__split__R2"]
    assert frame["ead_ccr"].to_list() == pytest.approx([0.0, 100_000_000.0], rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_NETTING_NOT_RECOGNISED]
    assert errors[0].severity is ErrorSeverity.WARNING
    assert errors[0].category is ErrorCategory.CCR_LEGAL


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_set_under_eligible_mna_nets_into_one_exposure(regime: str) -> None:
    """Both flags on every trade: one row, E* = 200m - 150m(1 - 2% x sqrt(0.5))."""
    # Arrange
    trades = [sft_trade("R1", "S1", **_MNA), sft_trade("R2", "S1", **_MNA)]

    # Act
    frame, errors = _run(regime, trades, [_gilts()])

    # Assert
    assert frame["exposure_reference"].to_list() == ["ccr__S1"]
    assert float(frame["ead_ccr"][0]) == pytest.approx(_NETTED_ESTAR, rel=_REL)
    assert errors == []


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(
    ("r1_flags", "r2_flags"),
    [
        ({"under_master_netting_agreement": True}, {"under_master_netting_agreement": True}),
        ({"is_legally_enforceable": True}, {"is_legally_enforceable": True}),
        (_MNA, {}),
    ],
    ids=["mna-without-art206", "art206-without-mna", "one-trade-unattested"],
)
def test_netting_needs_both_attestations_on_every_trade(
    regime: str, r1_flags: dict, r2_flags: dict
) -> None:
    """A set nets only when every trade carries both flags; anything less splits it."""
    # Arrange
    trades = [sft_trade("R1", "S1", **r1_flags), sft_trade("R2", "S1", **r2_flags)]

    # Act
    frame, errors = _run(regime, trades, [_gilts(trade_id="R1")])

    # Assert
    assert frame.height == 2
    assert float(frame["ead_ccr"].sum()) == pytest.approx(100_000_000.0, rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_NETTING_NOT_RECOGNISED]


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_unlinked_collateral_on_a_split_set_is_not_recognised(regime: str) -> None:
    """Netting-set-level gilts with no trade_id cannot follow one trade: E* = 200m."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R2", "S1")]

    # Act
    frame, errors = _run(regime, trades, [_gilts()])

    # Assert
    assert float(frame["ead_ccr"].sum()) == pytest.approx(200_000_000.0, rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_NETTING_NOT_RECOGNISED]
    assert "1 collateral row" in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_collateral_linked_to_a_trade_of_another_set_is_not_recognised(regime: str) -> None:
    """A trade_id naming a trade outside the split set does not attach the row to it."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R2", "S1"), sft_trade("R9", "S9")]

    # Act
    frame, _errors = _run(regime, trades, [_gilts(trade_id="R9")])

    # Assert
    split = frame.filter(pl.col("exposure_reference").str.starts_with("ccr__S1__split__"))
    assert float(split["ead_ccr"].sum()) == pytest.approx(200_000_000.0, rel=_REL)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_multi_counterparty_set_is_split_with_each_trade_on_its_own_counterparty(
    regime: str,
) -> None:
    """Two counterparties under one id: CCR029 ERROR; each leg keeps its counterparty."""
    # Arrange
    trades = [
        sft_trade("R1", "S1", **_MNA),
        sft_trade("R2", "S1", counterparty_reference=SFT_REVIEW_CP_CQS4, **_MNA),
    ]

    # Act
    frame, errors = _run(regime, trades, None)

    # Assert
    assert frame["counterparty_reference"].to_list() == [SFT_REVIEW_CP_CQS2, SFT_REVIEW_CP_CQS4]
    assert frame["ead_ccr"].to_list() == pytest.approx([100_000_000.0, 100_000_000.0], rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET]
    assert errors[0].severity is ErrorSeverity.ERROR
    assert SFT_REVIEW_CP_CQS4 in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_single_trade_set_without_flags_is_unchanged(regime: str) -> None:
    """The documented single-trade scope: no split, no warning, collateral NS-keyed."""
    # Arrange
    trades = [sft_trade("R1", "S1")]

    # Act
    frame, errors = _run(regime, trades, [_gilts()])

    # Assert
    assert frame["exposure_reference"].to_list() == ["ccr__S1"]
    assert float(frame["ead_ccr"][0]) == 0.0
    assert errors == []


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_duplicated_trade_id_does_not_re_net_a_split_set(regime: str) -> None:
    """Two trades sharing trade_id R1, no MNA: still two exposures, 100m each.

    Keying the split set by ``trade_id`` alone folded both trades back into
    ``S1__split__R1`` and netted them against cash linked to "R1" (E* = 50m) -
    exactly the pooling the gate exists to stop. The link is ambiguous (two
    trades carry the id), so the cash cannot be attributed to one transaction
    and is not recognised.
    """
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R1", "S1")]
    collateral = [sft_collateral("C_CASH", "S1", "cash", 150_000_000.0, trade_id="R1")]

    # Act
    frame, errors = _run(regime, trades, collateral)

    # Assert
    references = frame["exposure_reference"].to_list()
    assert len(references) == 2
    assert len(set(references)) == 2
    assert frame["ead_ccr"].to_list() == pytest.approx([100_000_000.0, 100_000_000.0], rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_NETTING_NOT_RECOGNISED]
    assert "C_CASH" in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_null_trade_id_in_a_split_set_keeps_a_non_null_reference(regime: str) -> None:
    """A null trade_id on a split set must not yield a null netting set / exposure id."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade(None, "S1"), sft_trade(None, "S1")]

    # Act
    frame, _errors = _run(regime, trades, None)

    # Assert
    references = frame["exposure_reference"].to_list()
    assert None not in references
    assert len(set(references)) == 3
    assert frame["ead_ccr"].to_list() == pytest.approx([100_000_000.0] * 3, rel=_REL)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_split_conserves_exposure_against_the_unnetted_sum(regime: str) -> None:
    """With no collateral the split legs sum to the gross notional the pooled set showed."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R2", "S1"), sft_trade("R3", "S1")]

    # Act
    frame, _errors = _run(regime, trades, None)

    # Assert
    assert frame.height == 3
    assert float(frame["ead_ccr"].sum()) == pytest.approx(300_000_000.0, rel=_REL)
