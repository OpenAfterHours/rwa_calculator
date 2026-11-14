"""
The sealed carrier for the ADJUSTED value of on-balance-sheet netting.

Pipeline position:
    ClassifiedExposuresBundle -> CRMProcessor -> ``on_bs_netting_adjusted_value``
    on the crm_exit frame -> (RE split, calculators, aggregator) -> reporting

Why the carrier exists. CRR Art. 219 turns a netted deposit into synthetic cash
collateral (``NETTING_<loan>`` rows) that the CRM stage merges into the ordinary
collateral frame, so its value lands inside ``collateral_adjusted_value``
together with every genuine pledge. A reader that needs the netting ALONE had
only ``on_bs_netting_amount``, and that is the PRE-haircut pro-rata allocation
of the pool: it equals what was actually deducted only when deposit and loan
share a currency and the deposit outlives the loan. PS1/26 Art. 219(1) defines
the netted exposure value against the deposit "adjusted for any currency and
maturity mismatches", so the amount the exposure value fell by is the ADJUSTED
one. OF 07.00 reported the allocation in column 0035 and the whole
``collateral_adjusted_value`` in column 0130, deducting the deposit twice
(escape log, 2026-09-05).

What these tests pin, at the level where it is cheapest to state exactly:

- the carrier is the netting part of ``collateral_adjusted_value`` and nothing
  else — never more than it, and exactly it on a row with no other collateral;
- it DIFFERS from the allocation under a currency mismatch (PS1/26 Art. 219(2);
  under CRR a cross-currency deposit is not netted at all, Art. 219) and
  under a maturity mismatch (Art. 219(3)) — the two cases the registered
  ``netting`` reporting portfolio cannot produce, because every leg of it is in
  one currency and matures on one date;
- a genuine pledge on the same loan is not counted, and neither is a supplied
  collateral row whose reference merely looks like a netting one;
- it is a number on every row (0.0, never null) and follows the Simple Method
  election, under which the comprehensive deduction is undone for SA.

References:
- CRR Art. 219 / PS1/26 Art. 219(1)-(3): on-balance-sheet netting
- PS1/26 Art. 224 Table 4: currency-mismatch volatility adjustment, by
  liquidation period
- CRR Art. 237-239: maturity mismatch
- CRR Art. 222: Financial Collateral Simple Method
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_classified_bundle
from tests.unit.crm._crm_bundles import empty_counterparty_lookup, normalise_collateral

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CRM_EXIT_EDGE, RE_SPLIT_EXIT_EDGE
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod, PermissionMode
from rwa_calc.engine.crm.expressions import COLLATERAL_VALUE_CARRIERS
from rwa_calc.engine.crm.guarantees import _apply_guarantee_splits
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value

CARRIER = "on_bs_netting_adjusted_value"
ALLOCATION = "on_bs_netting_amount"

_REPORTING_DATE = date(2024, 12, 31)

LOAN = "LN"
DEPOSIT = "DEP"
LOAN_DRAWN = 1_000.0
DEPOSIT_BALANCE = -300.0
POOL = 300.0  # the whole deposit lands on the one loan (Art. 219 pro-rata, one sibling)

#: A genuine cash pledge on the same loan — same currency, no maturity, so it
#: takes no haircut and its adjusted value is its market value.
PLEDGE = 150.0

_REGIMES = ("crr", "b31")


def _config(regime: str, **overrides: object) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
        **overrides,  # type: ignore[arg-type]
    )


def _exposure(
    ref: str,
    drawn: float,
    *,
    currency: str = "GBP",
    agreement: str | None = "AGR",
    approach: str = ApproachType.SA.value,
    maturity: date | None = None,
    value_date: date | None = None,
) -> dict:
    return {
        "exposure_reference": ref,
        "exposure_type": "loan",
        "counterparty_reference": "CP",
        "exposure_class": "corporate",
        "approach": approach,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "risk_type": "FR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": "FAC",
        "currency": currency,
        "original_currency": currency,
        "maturity_date": maturity,
        "value_date": value_date,
        "netting_agreement_reference": agreement,
    }


def _cash_pledge(reference: str, beneficiary: str, value: float) -> pl.LazyFrame:
    return normalise_collateral(
        pl.LazyFrame(
            {
                "collateral_reference": [reference],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [value],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": [beneficiary],
                "is_eligible_financial_collateral": [True],
            }
        )
    )


def _run(
    config: CalculationConfig, rows: list[dict], collateral: pl.LazyFrame | None = None
) -> pl.DataFrame:
    exposures = pl.LazyFrame(
        rows, schema_overrides={"maturity_date": pl.Date, "value_date": pl.Date}
    )
    bundle = make_classified_bundle(
        all_exposures=exposures,
        equity_exposures=None,
        counterparty_lookup=empty_counterparty_lookup(),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )
    return CRMProcessor().get_crm_unified_bundle(bundle, config).exposures.collect()


def _row(df: pl.DataFrame, ref: str) -> dict:
    rows = df.filter(pl.col("exposure_reference") == ref).to_dicts()
    assert len(rows) == 1, f"expected exactly one row for {ref}, got {len(rows)}"
    return rows[0]


def _assert_is_the_netting_part_of_the_collateral(row: dict) -> None:
    """The invariant every case shares: 0 <= carrier <= collateral_adjusted_value."""
    assert row[CARRIER] is not None, (
        "the carrier is null; a null and a legitimate zero are different claims"
    )
    assert 0.0 <= row[CARRIER] <= row["collateral_adjusted_value"] + 1e-9, row


# =============================================================================
# The carrier is declared wherever a sealed money column has to be
# =============================================================================


@pytest.mark.parametrize(
    "edge", [CRM_EXIT_EDGE, RE_SPLIT_EXIT_EDGE, AGGREGATOR_EXIT_EDGE], ids=lambda edge: edge.name
)
def test_carrier_is_a_required_float_on_every_edge_to_the_ledger(edge) -> None:
    """It rides CRM exit -> RE split -> aggregator exit as a required Float64.

    Required, like ``collateral_adjusted_value`` beside it: the CRM stage emits
    it on every path, so a reader never has to ask whether it is there.
    """
    assert CARRIER in edge.columns, f"{CARRIER} is not declared on edge '{edge.name}'"
    column = edge.columns[CARRIER]
    assert column.dtype == pl.Float64
    assert column.required


def test_both_netting_valuations_are_split_with_the_collateral_they_belong_to() -> None:
    """The allocation and its adjusted twin are collateral valuations.

    ``COLLATERAL_VALUE_CARRIERS`` is the list a guarantee row-split pro-rates.
    ``collateral_market_value`` and ``collateral_adjusted_value`` are on it; the
    netting part of each has to be too, or a split loan keeps the whole netting
    figure on every leg while the collateral it is part of is divided.
    """
    assert ALLOCATION in COLLATERAL_VALUE_CARRIERS
    assert CARRIER in COLLATERAL_VALUE_CARRIERS


# =============================================================================
# What the carrier holds
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
def test_matched_same_currency_deposit_adjusts_to_its_whole_allocation(regime: str) -> None:
    """The control: no mismatch, so adjusted value == allocation == the deposit.

    Arrange: a GBP 300 deposit and a GBP 1,000 loan under one agreement, no
             maturity on either side.
    Act:     run the CRM stage.
    Assert:  carrier 300 on the loan, 0.0 on the deposit, EAD 700.
    """
    # Arrange + Act
    df = _run(_config(regime), [_exposure(DEPOSIT, DEPOSIT_BALANCE), _exposure(LOAN, LOAN_DRAWN)])
    loan, deposit = _row(df, LOAN), _row(df, DEPOSIT)

    # Assert
    assert loan[ALLOCATION] == pytest.approx(POOL)
    assert loan[CARRIER] == pytest.approx(POOL)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN - POOL)
    assert deposit[CARRIER] == pytest.approx(0.0)
    _assert_is_the_netting_part_of_the_collateral(loan)


def test_currency_mismatch_carrier_is_the_haircut_value_not_the_allocation() -> None:
    """PS1/26 Art. 219(2): a EUR deposit against a GBP loan nets at its haircut value.

    Basel 3.1 only — under CRR the pair is not netted at all (next test).

    Hand calculation. The allocation is the whole EUR 300 pool. Art. 224 Table 4
    lists the currency-mismatch volatility adjustment per liquidation period;
    the pack holds its 10-day figure (entry ``fx_haircut``) and the engine scales
    it by sqrt(T_M / 10) to the period the synthetic netting row carries — entry
    ``on_bs_netting_liquidation_period``, which PS1/26 Art. 219(2) fixes for a
    netted deposit: "The institution shall apply a 10 business day liquidation
    period". Cash carries no adjustment of its own, so

        adjusted = 300 x (1 - H_fx x sqrt(T_M / 10))     = 276.00 at T_M = 10
        EAD      = 1,000 - adjusted

    The scalars are read from the pack rather than typed (LESSONS A4); the
    10-day value itself is pinned against the article by
    ``tests/unit/crm/test_collateral_submodules.py`` and the full-pipeline
    ``tests/acceptance/basel31/test_art219_netting_currency_mismatch.py``. The
    assertion that matters here does not depend on them: the carrier is strictly
    BELOW the allocation and is exactly what the exposure value fell by.

    Arrange: EUR 300 deposit, GBP 1,000 loan, one agreement.
    Act:     run the CRM stage.
    Assert:  allocation 300; carrier = the haircut value; EAD = 1,000 - carrier.
    """
    # Arrange
    config = _config("b31")
    pack = RulepackV0.from_config(config).pack
    h_fx = scalar_value(pack.scalar_param("fx_haircut"))
    period = pack.int_param("on_bs_netting_liquidation_period").value
    expected = POOL * (1.0 - h_fx * math.sqrt(period / 10.0))
    assert 0.0 < expected < POOL, (
        "the hand-calculated adjusted value equals the allocation, so this case "
        "cannot tell the two carriers apart and the test would prove nothing"
    )

    # Act
    df = _run(
        config,
        [_exposure(DEPOSIT, DEPOSIT_BALANCE, currency="EUR"), _exposure(LOAN, LOAN_DRAWN)],
    )
    loan = _row(df, LOAN)

    # Assert
    assert loan[ALLOCATION] == pytest.approx(POOL)
    assert loan[CARRIER] == pytest.approx(expected)
    assert loan[CARRIER] == pytest.approx(loan["collateral_adjusted_value"])
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN - expected)


def test_crr_cross_currency_deposit_is_not_netted_so_both_carriers_are_zero() -> None:
    """CRR Art. 219: netting is recognised only between loans and deposits
    "denominated in the same currency", so a EUR deposit is not cash collateral
    for a GBP loan at all — no allocation, no adjusted value, no deduction.

    Arrange: EUR 300 deposit, GBP 1,000 loan, one agreement, CRR.
    Act:     run the CRM stage.
    Assert:  allocation 0, carrier 0, EAD 1,000 (the whole loan).
    """
    # Arrange + Act
    df = _run(
        _config("crr"),
        [_exposure(DEPOSIT, DEPOSIT_BALANCE, currency="EUR"), _exposure(LOAN, LOAN_DRAWN)],
    )
    loan = _row(df, LOAN)

    # Assert
    assert loan[ALLOCATION] == pytest.approx(0.0)
    assert loan[CARRIER] == pytest.approx(0.0)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN)


@pytest.mark.parametrize("regime", _REGIMES)
def test_maturity_mismatch_carrier_is_the_scaled_value_not_the_allocation(regime: str) -> None:
    """Art. 219(3): a deposit shorter than the loan nets at its scaled value.

    Hand calculation (Art. 237-239). The deposit matures two years after the
    reporting date and was placed a year before it (original term three years,
    so the Art. 237(2)(a) one-year gate is passed); the loan matures six years
    out, and Art. 238(1) caps T at five.

        t        = 730 days / 365.25           = 1.998631 years
        T        = min(2,191 days / 365.25, 5) = 5
        factor   = (t - 0.25) / (T - 0.25)     = 1.748631 / 4.75 = 0.368133
        adjusted = 300 x 0.368133              = 110.4398
        EAD      = 1,000 - 110.4398            = 889.5602

    Arrange: GBP 300 deposit maturing in 2 years, GBP 1,000 loan maturing in 6.
    Act:     run the CRM stage.
    Assert:  allocation 300; carrier 110.44; EAD 889.56.
    """
    # Arrange
    deposit_maturity = date(2026, 12, 31)
    loan_maturity = date(2030, 12, 31)
    t = (deposit_maturity - _REPORTING_DATE).days / 365.25
    big_t = min((loan_maturity - _REPORTING_DATE).days / 365.25, 5.0)
    expected = POOL * (t - 0.25) / (big_t - 0.25)
    assert expected == pytest.approx(110.4398, abs=1e-4)

    # Act
    df = _run(
        _config(regime),
        [
            _exposure(
                DEPOSIT, DEPOSIT_BALANCE, maturity=deposit_maturity, value_date=date(2023, 12, 31)
            ),
            _exposure(LOAN, LOAN_DRAWN, maturity=loan_maturity, value_date=_REPORTING_DATE),
        ],
    )
    loan = _row(df, LOAN)

    # Assert
    assert loan[ALLOCATION] == pytest.approx(POOL)
    assert loan[CARRIER] == pytest.approx(expected)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN - expected)
    _assert_is_the_netting_part_of_the_collateral(loan)


@pytest.mark.parametrize("regime", _REGIMES)
def test_carrier_leaves_out_a_genuine_pledge_on_the_same_loan(regime: str) -> None:
    """Netting and a cash pledge on one loan: the carrier is the netting alone.

    The two-leg case (LESSONS B5). ``collateral_adjusted_value`` moves with BOTH
    the deposit and the pledge; the carrier must move with the deposit only, so
    that what is left over is the genuinely collateral part.

    Arrange: GBP 300 deposit, GBP 1,000 loan, and GBP 150 cash pledged to the loan.
    Act:     run the CRM stage.
    Assert:  collateral 450, carrier 300, remainder 150, EAD 550.
    """
    # Arrange + Act
    df = _run(
        _config(regime),
        [_exposure(DEPOSIT, DEPOSIT_BALANCE), _exposure(LOAN, LOAN_DRAWN)],
        collateral=_cash_pledge("PLEDGE-1", LOAN, PLEDGE),
    )
    loan = _row(df, LOAN)

    # Assert
    assert loan["collateral_adjusted_value"] == pytest.approx(POOL + PLEDGE)
    assert loan[CARRIER] == pytest.approx(POOL)
    assert loan["collateral_adjusted_value"] - loan[CARRIER] == pytest.approx(PLEDGE)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN - POOL - PLEDGE)


@pytest.mark.parametrize(
    "reference",
    ["PLEDGE-1", "NETTING_FUND_7", f"NETTING_{DEPOSIT}"],
    ids=["ordinary", "prefix-lookalike", "names-another-exposure"],
)
def test_a_supplied_pledge_is_never_counted_as_netting(reference: str) -> None:
    """Only the rows the netting step generated are netting.

    A firm's own collateral reference may start with the same prefix. The
    generated row is identified by its whole shape — its reference is the prefix
    followed by the loan it secures — so a supplied row is counted only if it
    is named exactly as one, which the third case shows it is not when it names
    a different exposure.

    Arrange: a GBP 1,000 loan with NO deposit, and GBP 150 cash pledged to it
             under each of three references.
    Act:     run the CRM stage.
    Assert:  collateral 150, carrier 0.0, EAD 850.
    """
    # Arrange + Act
    df = _run(
        _config("b31"),
        [_exposure(LOAN, LOAN_DRAWN, agreement=None)],
        collateral=_cash_pledge(reference, LOAN, PLEDGE),
    )
    loan = _row(df, LOAN)

    # Assert
    assert loan["collateral_adjusted_value"] == pytest.approx(PLEDGE)
    assert loan[CARRIER] == pytest.approx(0.0)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN - PLEDGE)


@pytest.mark.parametrize("regime", _REGIMES)
def test_carrier_is_zero_not_null_when_nothing_nets(regime: str) -> None:
    """No agreement, no collateral: 0.0 on every row.

    The no-collateral path never reaches the allocation step, so the carrier has
    to be initialised with the other collateral columns or the seal would see a
    missing column.
    """
    df = _run(_config(regime), [_exposure(LOAN, LOAN_DRAWN, agreement=None)])
    assert df[CARRIER].to_list() == [0.0]


def test_an_over_netted_loan_carries_the_whole_adjusted_value() -> None:
    """A pool larger than the loan: the carrier is the value, not the reduction.

    The carrier is a VALUATION, uncapped, exactly like ``collateral_adjusted_value``
    which it is a part of — the engine floors the exposure value at zero
    (Art. 219(1)(a)) after subtracting it. A reader reporting "the reduction in
    exposure value" caps it at the exposure; that is the reader's step, and
    stating the uncapped figure here is what makes the cap visible.

    Arrange: GBP 300 deposit against a GBP 100 loan.
    Act:     run the CRM stage.
    Assert:  carrier 300, EAD 0.
    """
    df = _run(_config("b31"), [_exposure(DEPOSIT, DEPOSIT_BALANCE), _exposure(LOAN, 100.0)])
    loan = _row(df, LOAN)
    assert loan[CARRIER] == pytest.approx(POOL)
    assert loan["ead_final"] == pytest.approx(0.0)


def test_a_foundation_irb_loan_carries_it_too() -> None:
    """Under F-IRB the deposit reduces LGD, not EAD — the valuation is the same.

    The carrier describes the netted deposit, not the approach that consumes it,
    so an IRB reader (C 08.01 column 0035) finds the same figure an SA one does.

    Arrange: the control pair, both rows Foundation IRB.
    Act:     run the CRM stage.
    Assert:  carrier 300; EAD untouched at 1,000; LGD below the unsecured value.
    """
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    df = _run(
        config,
        [
            _exposure(DEPOSIT, DEPOSIT_BALANCE, approach=ApproachType.FIRB.value),
            _exposure(LOAN, LOAN_DRAWN, approach=ApproachType.FIRB.value),
        ],
    )
    loan = _row(df, LOAN)
    assert loan[CARRIER] == pytest.approx(POOL)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN)
    assert loan["lgd_post_crm"] < loan["lgd_pre_crm"]


@pytest.mark.parametrize("regime", _REGIMES)
def test_simple_method_undoes_the_carrier_with_the_deduction_it_describes(regime: str) -> None:
    """Art. 222: no comprehensive deduction for SA, so no netting part of one.

    Under the Simple Method the engine recognises the deposit as Simple-Method
    cash collateral (a risk-weight substitution) and restores the SA exposure
    value. ``collateral_adjusted_value`` is zeroed with it; the carrier is the
    netting part of that column and must go to zero in the same step, or a
    reader subtracting one from the other reports a negative collateral value.

    Arrange: the control pair under the Simple Method election.
    Act:     run the CRM stage.
    Assert:  collateral 0, carrier 0, EAD back at 1,000, and the deposit showing
             as Simple-Method collateral instead.
    """
    df = _run(
        _config(regime, crm_collateral_method=CRMCollateralMethod.SIMPLE),
        [_exposure(DEPOSIT, DEPOSIT_BALANCE), _exposure(LOAN, LOAN_DRAWN)],
    )
    loan = _row(df, LOAN)
    assert loan["collateral_adjusted_value"] == pytest.approx(0.0)
    assert loan[CARRIER] == pytest.approx(0.0)
    assert loan["ead_final"] == pytest.approx(LOAN_DRAWN)
    assert loan["fcsm_collateral_value"] == pytest.approx(POOL)


# =============================================================================
# The carrier survives a guarantee row-split
# =============================================================================


@pytest.mark.parametrize("column", [ALLOCATION, CARRIER])
def test_a_guarantee_split_conserves_both_netting_valuations(column: str) -> None:
    """A partly guaranteed netted loan keeps ONE netting figure across its legs.

    ``_apply_guarantee_splits`` turns the loan into a guarantor leg and a
    remainder leg and pro-rates the collateral valuations between them. Measured
    before this change: ``on_bs_netting_amount`` stayed whole on BOTH legs (600
    against a 300 deposit), so column 0035 published the deposit twice on any
    netted loan that was also guaranteed.

    Arrange: a loan netted by 300 (adjusted 266), with 400 of it guaranteed.
    Act:     split it.
    Assert:  two legs; each valuation sums to its pre-split value, in the same
             proportion as the drawn balance.
    """
    # Arrange
    pre_split = {ALLOCATION: 300.0, CARRIER: 266.0}
    exposures = pl.LazyFrame(
        {
            "exposure_reference": ["EXP"],
            "parent_exposure_reference": ["EXP"],
            "ead_after_collateral": [734.0],
            "ead_pre_crm": [1_000.0],
            "drawn_amount": [1_000.0],
            "nominal_amount": [0.0],
            "counterparty_reference": ["CP"],
            "collateral_adjusted_value": [266.0],
            "collateral_market_value": [300.0],
            **{name: [value] for name, value in pre_split.items()},
        }
    )
    guarantees = pl.LazyFrame(
        {"beneficiary_reference": ["EXP"], "amount_covered": [400.0], "guarantor": ["G1"]}
    )

    # Act
    legs = _apply_guarantee_splits(guarantees, exposures).collect()

    # Assert
    assert legs.height == 2, "the guarantee did not split the loan, so nothing is tested"
    assert legs[column].sum() == pytest.approx(pre_split[column])
    shares = (legs[column] / legs["drawn_amount"]).to_list()
    assert shares == pytest.approx([pre_split[column] / 1_000.0] * 2)
