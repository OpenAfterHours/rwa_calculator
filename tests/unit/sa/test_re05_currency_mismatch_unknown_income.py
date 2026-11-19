"""
RE-05 — the PS1/26 Art. 123B(3) fallback when the borrower's income currency is unknown.

Rule text (PS1/26 Appendix 1, Art. 123B(3), verbatim):

    "Where: (a) an institution is unable to identify those exposures with a currency
    mismatch which are subject to paragraph 1; and (b) the exposure was incurred prior
    to 1 January 2027, the institution shall apply the risk weight multiplier of 1.5 to
    all unhedged retail exposures, and unhedged residential real estate exposures that
    are assigned to the exposure classes referred to in points (h) and (i) of Article
    112(1), except where the lending currency is the same as the domestic currency of
    the country of residence of the obligor or the country of employment of the
    obligor, subject to a maximum risk weight of 150%."

Orchestrator decision: wherever ``borrower_income_currency`` is null the engine
compares the lending currency with the obligor's domestic currency — the
counterparty's ``local_currency`` when supplied, else the domestic currency of its
``country_code`` (GB -> GBP, EU members from the pack) — and applies the 1.5x unless
they match. Unknown residence cannot establish the exception, so it does not.

"Lending currency" is the exposure's DENOMINATION. When FX conversion runs, the
converter overwrites ``currency`` with the reporting currency and keeps the
denomination in ``original_currency``; reading ``currency`` there compared GBP (the
reporting currency) with the income currency — measured before this change, a EUR
mortgage to a GBP earner with FX rates supplied took NO multiplier, and a EUR mortgage
to a EUR earner took one. Both limbs now read the denomination.

The multiplier is Basel-3.1-only (pack Feature ``sa_currency_mismatch_multiplier``), so
every leg here also asserts the CRR control (C7).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.rw_adjustments import apply_currency_mismatch_multiplier
from tests.fixtures.single_exposure import calculate_single_sa_exposure

_BASE_RW = 0.75  # PS1/26 Art. 123(3)(b) / CRR Art. 123 regulatory retail


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _rw(
    calculator: SACalculator,
    config: CalculationConfig,
    *,
    currency: str,
    country_code: str | None,
    local_currency: str | None = None,
    is_hedged: bool = False,
) -> float:
    result = calculate_single_sa_exposure(
        calculator,
        ead=Decimal("100000"),
        exposure_class="retail_other",
        currency=currency,
        country_code=country_code,
        local_currency=local_currency,
        borrower_income_currency=None,
        is_hedged=is_hedged,
        config=config,
    )
    return float(result["risk_weight"])


class TestUnknownIncomeCurrencyFallback:
    """Null income currency: multiplier unless the lending currency is domestic."""

    @pytest.mark.parametrize(
        ("currency", "country_code", "local_currency", "expected_rw"),
        [
            # GB resident, GBP loan: the 123B(3) exception — no multiplier.
            ("GBP", "GB", None, _BASE_RW),
            # GB resident, EUR loan: not domestic -> 75% x 1.5.
            ("EUR", "GB", None, _BASE_RW * 1.5),
            # FR resident (EU map from the pack), EUR loan: domestic -> no multiplier.
            ("EUR", "FR", None, _BASE_RW),
            # FR resident, GBP loan: not domestic -> multiplier.
            ("GBP", "FR", None, _BASE_RW * 1.5),
            # An explicit local_currency outranks the country map.
            ("EUR", "GB", "EUR", _BASE_RW),
            ("GBP", "GB", "EUR", _BASE_RW * 1.5),
            # Residence unknown to the engine (no map entry, no local currency):
            # the exception cannot be shown -> multiplier.
            ("USD", "US", None, _BASE_RW * 1.5),
            ("GBP", None, None, _BASE_RW * 1.5),
            # Local currency alone is enough to show the exception.
            ("USD", "US", "USD", _BASE_RW),
        ],
    )
    def test_b31_fallback(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        currency: str,
        country_code: str | None,
        local_currency: str | None,
        expected_rw: float,
    ) -> None:
        rw = _rw(
            sa_calculator,
            b31_config,
            currency=currency,
            country_code=country_code,
            local_currency=local_currency,
        )
        assert rw == pytest.approx(expected_rw)

    def test_b31_hedge_still_waives_the_fallback(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """123B(3) reaches only UNHEDGED exposures, as 123B(1) does."""
        rw = _rw(sa_calculator, b31_config, currency="EUR", country_code="GB", is_hedged=True)
        assert rw == pytest.approx(_BASE_RW)

    def test_crr_has_no_multiplier(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        rw = _rw(sa_calculator, crr_config, currency="EUR", country_code="GB")
        assert rw == pytest.approx(_BASE_RW)


class TestLendingCurrencyIsTheDenomination:
    """Both limbs compare the pre-FX denomination, not the reporting currency."""

    @staticmethod
    def _frame(income: str | None) -> pl.LazyFrame:
        # A EUR loan after FX conversion to a GBP reporting currency.
        return pl.LazyFrame(
            {
                "exposure_reference": ["FX_CONVERTED"],
                "exposure_class": ["retail_other"],
                "risk_weight": [_BASE_RW],
                "currency": ["GBP"],
                "original_currency": ["EUR"],
                "cp_borrower_income_currency": [income],
                "cp_country_code": ["GB"],
                "ead_final": [85_000.0],
            },
            schema_overrides={"cp_borrower_income_currency": pl.String},
        )

    @pytest.mark.parametrize(
        ("income", "expected_rw", "expected_applied"),
        [
            # EUR loan, GBP earner: a mismatch, whatever the reporting currency is.
            ("GBP", _BASE_RW * 1.5, True),
            # EUR loan, EUR earner: no mismatch.
            ("EUR", _BASE_RW, False),
            # EUR loan, unknown income, GB resident: 123B(3) fallback fires.
            (None, _BASE_RW * 1.5, True),
        ],
    )
    def test_b31_reads_original_currency(
        self,
        b31_config: CalculationConfig,
        income: str | None,
        expected_rw: float,
        expected_applied: bool,
    ) -> None:
        row = apply_currency_mismatch_multiplier(self._frame(income), b31_config).collect()
        assert row["risk_weight"][0] == pytest.approx(expected_rw)
        assert row["currency_mismatch_multiplier_applied"][0] is expected_applied
