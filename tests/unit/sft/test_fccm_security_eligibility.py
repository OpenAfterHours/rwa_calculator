"""
CC-13: Art. 197/198 eligibility of the securities an SFT lends and receives.

Two defects, measured pre-fix through ``sft_bundle_to_exposures``:

1. Exposure side. A security lent that is NOT eligible collateral (an unrated
   or CQS 4+ corporate bond, a CQS 5+ government bond) made the haircut lookup
   return ``None``, which the engine read as HE = 0. Repo lending an unrated
   corporate bond 100m against 95m cash gave E* = 5,000,000 in both regimes.

   CRR Art. 224(4): "For non-eligible securities or for commodities lent or sold
   under repurchase transactions or securities or commodities lending or
   borrowing transactions, the volatility adjustment is the same as for
   non-main index equities listed on a recognised exchange." PS1/26 Art. 224(4)
   (App. 1 p.205): "For non-eligible securities and commodities lent or sold
   under securities financing transactions, the institution shall apply the same
   volatility adjustment as it would for equities which are not equities
   included in a main index but are listed on a recognised exchange." That is
   25% (CRR) / 30% (PS1/26) at 10 days, x sqrt(5/10) for an SFT.

2. Collateral side. Real estate, receivables, other physical and unknown
   collateral types were priced by the lending-side fall-through (0% for real
   estate, the table value for receivables, 40% for anything else) and
   RECOGNISED in E*: cash lent 100m against 100m property gave E* = 0.

   CRR Art. 223(1) / PS1/26 Art. 223(1): volatility adjustments apply "when
   valuing financial collateral"; the eligible items are those of Art. 197 /
   198. On the SFT path only the types the Art. 224 Tables 1 and 3 price are
   recognised (data/schemas.py SFT_FCCM_HAIRCUT_LOOKUP_TYPES); every other row
   contributes nothing and raises CCR027.

Covered bonds are debt securities issued by institutions, PS1/26 Art. 197(1)(c)
"debt securities issued by: (i) institutions ... where the securities have a
credit assessment by an ECAI which is associated with credit quality step 3 or
above", and price in the Table 1 column for "debt securities issued by entities
described in points (c) and (d)". Pre-fix they took the 40% fall-through; the
fix prices them in that column (CQS 1, 1-5y CRR 4%, 1-3y PS1/26 3%), which
LOWERS E* for an eligible covered bond (LESSONS A2: the quote above is the
basis). A non-eligible type lent keeps any higher pre-existing haircut: the
Art. 224(4) value is applied as a floor, so an unknown / other-physical string
lent stays at 40% rather than being reduced.

References:
    CRR / PS1/26 Art. 197(1), 198, 223(1), 223(5), 224(1) Tables 1/3, 224(4).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from rwa_calc.contracts.errors import ERROR_SFT_COLLATERAL_NOT_RECOGNISED
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.ccr.sft_fccm_review_builder import (
    SFT_REVIEW_NOTIONAL,
    build_sft_bundle,
    sft_collateral,
    sft_trade,
)

_PACKS = {
    "crr": resolve("crr", date(2026, 6, 30)),
    "b31": resolve("b31", date(2027, 6, 30)),
}
_REPORTING_DATE = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}
#: Art. 224(4) value: Table 3 "other equities listed on a recognised exchange".
_NON_ELIGIBLE_H10 = {"crr": 0.25, "b31": 0.30}
_SQRT_HALF = math.sqrt(5 / 10)
_REL = 1e-12


def _run(regime: str, trades: list[dict], collateral: list[dict] | None) -> tuple[float, list]:
    rows, errors = sft_bundle_to_exposures(
        build_sft_bundle(trades, collateral), _REPORTING_DATE[regime], rulepack=_PACKS[regime]
    )
    frame = rows.collect()
    return float(frame["ead_ccr"].sum()), errors


# ---------------------------------------------------------------------------
# Exposure side — Art. 224(4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(
    ("security_type", "cqs"),
    [
        ("corp_bond", None),  # unrated corporate: Art. 197(1)(d) needs CQS <= 3
        ("corp_bond", 4),
        ("govt_bond", 5),  # Art. 197(1)(b) needs CQS <= 4
        ("govt_bond", None),
    ],
)
def test_ineligible_security_lent_takes_non_main_index_equity_haircut(
    regime: str, security_type: str, cqs: int | None
) -> None:
    """Ineligible bond lent 100m vs 95m cash: E* = 100m(1 + H) - 95m, H = Art. 224(4)."""
    # Arrange
    trades = [
        sft_trade(
            "R1",
            "S1",
            exposure_collateral_type=security_type,
            exposure_security_cqs=cqs,
            exposure_security_residual_maturity_years=3.0,
        )
    ]
    collateral = [sft_collateral("C1", "S1", "cash", 95_000_000.0)]
    expected = SFT_REVIEW_NOTIONAL * (1 + _NON_ELIGIBLE_H10[regime] * _SQRT_HALF) - 95_000_000.0

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(expected, rel=_REL)
    assert expected > 5_000_000.0, "pre-fix value was 5,000,000 (HE = 0)"
    assert errors == []


@pytest.mark.parametrize(
    ("regime", "expected"),
    [("crr", 22_677_669.529663697), ("b31", 26_213_203.43559642)],
)
def test_unrated_corp_bond_lent_matches_review_hand_calc(regime: str, expected: float) -> None:
    """The review's hand-calc: CRR 22,677,669.53; PS1/26 26,213,203.44."""
    # Arrange
    trades = [
        sft_trade(
            "R1",
            "S1",
            exposure_collateral_type="corp_bond",
            exposure_security_residual_maturity_years=3.0,
        )
    ]
    collateral = [sft_collateral("C1", "S1", "cash", 95_000_000.0)]

    # Act
    estar, _errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(expected, rel=_REL)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_real_estate_lent_takes_non_main_index_equity_haircut(regime: str) -> None:
    """Pre-fix real estate lent took the lending-side 0%; Art. 224(4) floors it."""
    # Arrange
    trades = [sft_trade("R1", "S1", exposure_collateral_type="real_estate")]

    # Act
    estar, _errors = _run(regime, trades, None)

    # Assert
    assert estar == pytest.approx(
        SFT_REVIEW_NOTIONAL * (1 + _NON_ELIGIBLE_H10[regime] * _SQRT_HALF), rel=_REL
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_unknown_type_lent_keeps_higher_fall_through_haircut(regime: str) -> None:
    """The Art. 224(4) value is a floor: an unrecognised type keeps its 40% fall-through."""
    # Arrange
    trades = [sft_trade("R1", "S1", exposure_collateral_type="other_physical")]

    # Act
    estar, _errors = _run(regime, trades, None)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL * (1 + 0.40 * _SQRT_HALF), rel=_REL)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cash_lent_takes_no_exposure_haircut(regime: str) -> None:
    """A null exposure_collateral_type is cash lent: HE = 0 (unchanged anchor)."""
    # Arrange
    trades = [sft_trade("R1", "S1")]

    # Act
    estar, errors = _run(regime, trades, None)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL, rel=_REL)
    assert errors == []


# ---------------------------------------------------------------------------
# Collateral side — Art. 223(1) financial collateral only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(
    "collateral_type",
    [
        "real_estate",
        "property",
        "receivables",
        "other_physical",
        "bond",
        "fund_units",
        "securitisation",
        "commercial_paper",
        None,
    ],
)
def test_non_financial_or_unpriceable_collateral_is_not_recognised(
    regime: str, collateral_type: str | None
) -> None:
    """Cash lent 100m vs 100m of the type: E* = 100m and one CCR027 warning."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [
        sft_collateral(
            "C1", "S1", collateral_type, 100_000_000.0, issuer_cqs=1, residual_maturity_years=2.0
        )
    ]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL, rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_COLLATERAL_NOT_RECOGNISED]
    assert errors[0].severity is ErrorSeverity.WARNING
    assert "C1" in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(
    ("collateral_type", "cqs"),
    [("corp_bond", 4), ("corp_bond", None), ("govt_bond", 5), ("covered_bond", 4)],
)
def test_cqs_ineligible_debt_collateral_is_not_recognised_and_named(
    regime: str, collateral_type: str, cqs: int | None
) -> None:
    """A debt security failing the Art. 197(1)(b)-(d) CQS test: zero CVA + CCR027."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [
        sft_collateral(
            "C1", "S1", collateral_type, 100_000_000.0, issuer_cqs=cqs, residual_maturity_years=2.0
        )
    ]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL, rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_COLLATERAL_NOT_RECOGNISED]


@pytest.mark.parametrize(
    ("regime", "h10"),
    [("crr", 0.04), ("b31", 0.03)],
)
def test_covered_bond_collateral_prices_in_institution_corporate_column(
    regime: str, h10: float
) -> None:
    """CQS 1, 2y covered bond: Table 1 (c)/(d) column — CRR 1-5y 4%, PS1/26 1-3y 3%."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [
        sft_collateral(
            "C1", "S1", "covered_bond", 100_000_000.0, issuer_cqs=1, residual_maturity_years=2.0
        )
    ]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(100_000_000.0 * h10 * _SQRT_HALF, rel=_REL)
    assert errors == []


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_only_eligible_rows_count_when_a_set_mixes_collateral(regime: str) -> None:
    """60m cash + 100m property against 100m lent: E* = 40m; property row named."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [
        sft_collateral("C_CASH", "S1", "cash", 60_000_000.0),
        sft_collateral("C_PROP", "S1", "real_estate", 100_000_000.0),
    ]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(40_000_000.0, rel=_REL)
    assert len(errors) == 1
    assert "C_PROP" in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_collateral_keyed_to_no_sft_netting_set_is_named_not_dropped(regime: str) -> None:
    """Cash on a set with no trade reduces nothing; CCR027 names it (pre-fix: KeyError)."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [sft_collateral("C_ORPHAN", "S_NO_TRADE", "cash", 50_000_000.0)]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL, rel=_REL)
    assert [e.code for e in errors] == [ERROR_SFT_COLLATERAL_NOT_RECOGNISED]
    assert "C_ORPHAN" in errors[0].message
    assert "holds no SFT trade" in errors[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("collateral_type", ["cash", "deposit", "gilt", "corporate_bond", "stock"])
def test_eligible_collateral_raises_no_warning(regime: str, collateral_type: str) -> None:
    """Eligible collateral is recognised silently (the alarm discriminates, LESSONS B9)."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [
        sft_collateral(
            "C1", "S1", collateral_type, 50_000_000.0, issuer_cqs=1, residual_maturity_years=2.0
        )
    ]

    # Act
    estar, errors = _run(regime, trades, collateral)

    # Assert
    assert errors == []
    assert estar < SFT_REVIEW_NOTIONAL, "eligible collateral must reduce E*"
