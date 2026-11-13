"""
CRR — Art. 219 recognises on-balance-sheet netting only within one currency.

UK CRR Art. 219 (legislation.gov.uk, onshored text): *"Loans to and deposits with
the lending institution subject to on-balance sheet netting are to be treated by
that institution as cash collateral for the purpose of calculating the effect of
funded credit protection for those loans and deposits of the lending institution
subject to on-balance sheet netting which are denominated in the same
currency."*

So under CRR a netted deposit offsets only loans DENOMINATED in its own currency,
with no currency haircut; a deposit in another currency is not cash collateral
for that loan at all, and contributes nothing to it. (Basel 3.1 differs — PS1/26
Art. 219(2) recognises the mismatch net of Table 4 at 10 days; see the twin
test.) The denomination is the ``original_currency`` that ``FXConverter``
preserves when it rebases ``currency`` to the reporting currency. Every scenario
runs through the full pipeline with an ``fx_rates`` table (all rates 1.0), once
without and once with an ordinary collateral file in the bundle. See
``tests/fixtures/netting_currency/`` for the scenario shapes and the hand-calc.

    pair           deposit  loan   recognised   EAD (= RWA)
    gbp_gbp        GBP 300  GBP    300          700
    eur_gbp        EUR 300  GBP    0            1,000
    gbp_eur        GBP 300  EUR    0            1,000
    eur_eur        EUR 300  EUR    300          700
    mixed_pool     GBP 200  GBP    200          800
                 + EUR 100

References:
    - UK CRR Art. 219: same-currency on-B/S netting treated as cash collateral.
    - UK CRR Art. 195: on-B/S netting of reciprocal cash balances.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - docs/development/escape-log.md: 2026-11-13 netting currency entry.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.netting_currency.netting_currency import (
    BASE_CURRENCY,
    OTHER_COLLATERAL_VALUE,
    OTHER_LOAN,
    OTHER_LOAN_DRAWN,
    PLAIN_LABELS,
    SCENARIOS,
    WITH_COLLATERAL_LABELS,
    build_netting_currency_bundle,
)

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REGIME = "crr"
REPORTING_DATE = date(2026, 6, 30)

# Rows whose correct figure needs the Art. 219 same-currency restriction.
# Strict, so each flips to a hard failure the moment it starts passing early.
_PENDING_SAME_CURRENCY = pytest.mark.xfail(
    strict=True,
    reason="CRR Art. 219 same-currency restriction not yet applied to netted deposits",
)
_NEEDS_SAME_CURRENCY: frozenset[str] = frozenset(
    {"eur_gbp", "gbp_eur", "mixed_pool", "eur_gbp_coll", "gbp_eur_coll"}
)


def _params(labels: tuple[str, ...]) -> list:
    return [
        pytest.param(label, marks=_PENDING_SAME_CURRENCY)
        if label in _NEEDS_SAME_CURRENCY
        else label
        for label in labels
    ]


def _run(labels: tuple[str, ...]) -> pl.DataFrame:
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    bundle = build_netting_currency_bundle(labels, REPORTING_DATE)
    result: AggregatedResultBundle = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


@pytest.fixture(scope="module")
def plain() -> pl.DataFrame:
    """Scenarios in a bundle WITHOUT a collateral file."""
    return _run(PLAIN_LABELS)


@pytest.fixture(scope="module")
def with_collateral() -> pl.DataFrame:
    """The same pairs in a bundle that also carries an ordinary collateral file."""
    return _run(WITH_COLLATERAL_LABELS)


def _row(results: pl.DataFrame, reference: str) -> dict:
    rows = results.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"expected one result row for {reference}, got {len(rows)}"
    return rows[0]


def _frame(request: pytest.FixtureRequest, label: str) -> pl.DataFrame:
    name = "with_collateral" if label in WITH_COLLATERAL_LABELS else "plain"
    return request.getfixturevalue(name)


def _recognised_deposits(label: str) -> float:
    """Sum of the scenario's deposits denominated in the loan's own currency."""
    s = SCENARIOS[label]
    return sum(balance for currency, balance in s.deposits if currency == s.loan_currency)


class TestCRRNettingCurrencyAdequacy:
    """The fixture can express the defect: conversion ran, the collateral file is live."""

    @pytest.mark.parametrize("label", PLAIN_LABELS + WITH_COLLATERAL_LABELS)
    def test_loan_was_rebased_and_kept_its_denomination(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        """Without this, ``currency`` would still be the denomination and no
        currency-carrier defect could show."""
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert (row["currency"], row["original_currency"]) == (BASE_CURRENCY, s.loan_currency)

    def test_collateral_file_is_present_and_applied(self, with_collateral: pl.DataFrame) -> None:
        """The ``*_coll`` bundle only differs if its collateral file is really in play."""
        row = _row(with_collateral, OTHER_LOAN)
        assert row["ead_final"] == pytest.approx(OTHER_LOAN_DRAWN - OTHER_COLLATERAL_VALUE)


class TestCRRNettingSameCurrencyOnly:
    """Art. 219: only a deposit in the loan's own currency is cash collateral for it."""

    @pytest.mark.parametrize("label", _params(PLAIN_LABELS + WITH_COLLATERAL_LABELS))
    def test_loan_ead_reflects_the_deposit_denomination(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["ead_final"] == pytest.approx(s.expected_ead(REGIME), rel=1e-9)

    @pytest.mark.parametrize("label", _params(PLAIN_LABELS + WITH_COLLATERAL_LABELS))
    def test_loan_rwa_is_ead_at_the_unrated_corporate_weight(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["rwa_final"] == pytest.approx(s.expected_ead(REGIME), rel=1e-9)

    @pytest.mark.parametrize("label", _params(PLAIN_LABELS + WITH_COLLATERAL_LABELS))
    def test_only_same_currency_deposits_are_reported_as_netted(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        """The netting allocation carrier must not report a deposit Art. 219 does
        not recognise for this loan."""
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["on_bs_netting_amount"] == pytest.approx(_recognised_deposits(label))

    def test_mixed_pool_sits_between_its_two_currency_bounds(self, plain: pl.DataFrame) -> None:
        """Pins the two-pool split end to end, independently of how a mismatch is
        treated: a GBP loan offset by GBP 200 + EUR 100 must net strictly MORE than
        an all-EUR 300 deposit and strictly LESS than an all-GBP one. Merging the two
        deposits into one pool on the rebased currency collapses it onto the GBP
        bound (700); merging on either denomination collapses it onto one bound."""
        ead = {
            label: _row(plain, SCENARIOS[label].loan_ref)["ead_final"]
            for label in ("gbp_gbp", "mixed_pool", "eur_gbp")
        }
        assert ead["gbp_gbp"] < ead["mixed_pool"] < ead["eur_gbp"], ead

    @pytest.mark.parametrize(
        ("mismatch", "control"),
        [
            ("eur_gbp", "gbp_gbp"),
            ("gbp_eur", "eur_eur"),
            ("eur_gbp_coll", "gbp_gbp_coll"),
            ("gbp_eur_coll", "eur_eur_coll"),
        ],
    )
    def test_mismatched_deposit_nets_less_than_matched_deposit(
        self, request: pytest.FixtureRequest, mismatch: str, control: str
    ) -> None:
        """Isolates WHICH currencies are compared, independently of how a mismatch is
        then treated: the same 300 deposit must relieve a loan in another currency by
        strictly less than a loan in its own. Comparing the reporting currency
        instead of the denomination inverts this on ``eur_gbp`` and erases it with a
        collateral file."""
        frame = _frame(request, mismatch)
        mismatched = _row(frame, SCENARIOS[mismatch].loan_ref)["ead_final"]
        matched = _row(frame, SCENARIOS[control].loan_ref)["ead_final"]
        assert mismatched > matched
