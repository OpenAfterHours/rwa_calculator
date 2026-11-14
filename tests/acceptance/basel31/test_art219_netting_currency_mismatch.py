"""
Basel 3.1 — Art. 219(2) currency mismatch on on-balance-sheet netting.

PS1/26 Art. 219(2) (ps126app1.pdf, page 191 of 492): *"Where there is a currency
mismatch between the exposure referred to in point (b)(i) of paragraph 1 and the
loans and deposits referred to in point (b)(ii) of paragraph 1, the institution
shall reflect the mismatch by applying the appropriate volatility adjustment
specified in Table 4 in paragraph 1 of Article 224 to the value of the
protection. The institution shall apply a 10 business day liquidation period."*

So under Basel 3.1 a netted deposit in a different currency from the loan IS
recognised, net of Table 4's 10-day 8%; a same-currency deposit takes no currency
haircut. The currency that decides it is each leg's DENOMINATION — the
``original_currency`` that ``FXConverter`` preserves when it rebases ``currency``
to the reporting currency. Every scenario runs through the full pipeline with an
``fx_rates`` table (all rates 1.0), once without and once with an ordinary
collateral file in the bundle. See ``tests/fixtures/netting_currency/`` for the
scenario shapes and the hand-calc.

    pair           deposit  loan   relief          EAD (= RWA)
    gbp_gbp        GBP 300  GBP    300             700
    eur_gbp        EUR 300  GBP    300 x 0.92      724
    gbp_eur        GBP 300  EUR    300 x 0.92      724
    eur_eur        EUR 300  EUR    300             700
    mixed_pool     GBP 200  GBP    200 + 100x0.92  708
                 + EUR 100
    eur_gbp_sft    EUR 300  GBP    300 x 0.92      724   (SFT loan: 10 days, not 5)

References:
    - PS1/26 Art. 219(1)-(2): on-B/S netting, currency mismatch at 10 days.
    - PS1/26 Art. 224(1) Table 4: 8% at a 10-day liquidation period.
    - PS1/26 Art. 122: unrated corporate 100% risk weight.
    - docs/development/escape-log.md: 2026-11-13 netting currency entry.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CURRENCY_MISMATCH
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.netting_currency.netting_currency import (
    BASE_CURRENCY,
    DEPOSIT_ABS,
    OTHER_COLLATERAL_VALUE,
    OTHER_LOAN,
    OTHER_LOAN_DRAWN,
    PLAIN_LABELS,
    SCENARIOS,
    WITH_COLLATERAL_LABELS,
    build_netting_currency_bundle,
)

REGIME = "b31"
REPORTING_DATE = date(2027, 1, 1)


def _run(labels: tuple[str, ...]) -> AggregatedResultBundle:
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    bundle = build_netting_currency_bundle(labels, REPORTING_DATE)
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def plain_result() -> AggregatedResultBundle:
    """Scenarios in a bundle WITHOUT a collateral file."""
    return _run(PLAIN_LABELS)


@pytest.fixture(scope="module")
def with_collateral_result() -> AggregatedResultBundle:
    """The same pairs in a bundle that also carries an ordinary collateral file."""
    return _run(WITH_COLLATERAL_LABELS)


@pytest.fixture(scope="module")
def plain(plain_result: AggregatedResultBundle) -> pl.DataFrame:
    return plain_result.results.collect()


@pytest.fixture(scope="module")
def with_collateral(with_collateral_result: AggregatedResultBundle) -> pl.DataFrame:
    return with_collateral_result.results.collect()


def _currency_warnings(*results: AggregatedResultBundle) -> list[str]:
    return [e.message for r in results for e in r.errors if e.code == ERROR_CURRENCY_MISMATCH]


def _row(results: pl.DataFrame, reference: str) -> dict:
    rows = results.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"expected one result row for {reference}, got {len(rows)}"
    return rows[0]


def _frame(request: pytest.FixtureRequest, label: str) -> pl.DataFrame:
    name = "with_collateral" if label in WITH_COLLATERAL_LABELS else "plain"
    return request.getfixturevalue(name)


class TestB31NettingCurrencyAdequacy:
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


class TestB31NettingCurrencyMismatch:
    """Art. 219(2): a mismatched netted deposit is recognised net of Table 4 at 10 days."""

    @pytest.mark.parametrize("label", PLAIN_LABELS + WITH_COLLATERAL_LABELS)
    def test_loan_ead_reflects_the_deposit_denomination(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["ead_final"] == pytest.approx(s.expected_ead(REGIME), rel=1e-9)

    @pytest.mark.parametrize("label", PLAIN_LABELS + WITH_COLLATERAL_LABELS)
    def test_loan_rwa_is_ead_at_the_unrated_corporate_weight(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["rwa_final"] == pytest.approx(s.expected_ead(REGIME), rel=1e-9)

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
        """Isolates WHICH currencies are compared, independently of the haircut size:
        the same 300 deposit must relieve a loan in another currency by strictly less
        than a loan in its own. Comparing the reporting currency instead of the
        denomination inverts this on ``eur_gbp`` and erases it with a collateral file."""
        frame = _frame(request, mismatch)
        mismatched = _row(frame, SCENARIOS[mismatch].loan_ref)["ead_final"]
        matched = _row(frame, SCENARIOS[control].loan_ref)["ead_final"]
        assert mismatched > matched

    @pytest.mark.parametrize("label", PLAIN_LABELS + WITH_COLLATERAL_LABELS)
    def test_netting_allocation_is_the_full_deposit_before_haircut(
        self, request: pytest.FixtureRequest, label: str
    ) -> None:
        """Basel 3.1 recognises every deposit under the agreement, so the pre-haircut
        allocation carrier holds the whole balance in every currency case."""
        s = SCENARIOS[label]
        row = _row(_frame(request, label), s.loan_ref)
        assert row["on_bs_netting_amount"] == pytest.approx(s.total_deposits)
        assert s.total_deposits == pytest.approx(DEPOSIT_ABS)


class TestB31MismatchIsAdjustedNotRefused:
    """Basel 3.1 recognises every deposit (Art. 219(2)), so nothing is unrecognised."""

    def test_no_currency_netting_warning(
        self,
        plain_result: AggregatedResultBundle,
        with_collateral_result: AggregatedResultBundle,
    ) -> None:
        assert _currency_warnings(plain_result, with_collateral_result) == []
