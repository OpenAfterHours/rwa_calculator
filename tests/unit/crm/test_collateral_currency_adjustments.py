"""
Reviews CL-09 and CL-14: the currency-mismatch volatility adjustment H_fx.

CL-09 — Basel 3.1 F-IRB applies H_fx to NON-financial collateral.
    PS1/26 Art. 230(1), verbatim: "ES = the current value of the collateral
    received after the application of: (a) the volatility adjustment applicable
    for the type of collateral (HC), as specified in paragraph 2; (b) a
    volatility adjustment for any currency mismatch between the exposure and the
    collateral (Hfx) in accordance with Articles 224, 226, and 227; (c) an
    adjustment for any maturity mismatch calculated in accordance with Articles
    237 to 239." Paragraph 2: HC 40% and LGDS 20% for immovable property. No
    limit to financial collateral, so a EUR property securing a GBP loan takes
    the 8% Table 4 adjustment (10-day liquidation period) on top of HC. CRR
    Art. 230(1) compares "the value of the collateral (C)" with C* / C** and
    names no currency adjustment, so CRR is unchanged. Pack Feature
    ``fcm_hfx_applies_to_non_financial`` (B31 enabled, CRR disabled).

    Hand calculation (F-IRB, GBP loan 100,000, commercial property 100,000,
    EUR at 1.0, liquidation period 10 days):
        Basel 3.1: ES = 100,000 x (1 - 0.40 - 0.08) = 52,000;
            LGD* = (0.20 x 52,000 + 0.40 x 48,000) / 100,000 = 0.296
            (pre-fix 0.28, the GBP twin's value: ES 60,000).
        CRR: C / E = 1.0 >= C* 30%; ES = 100,000 / 1.4 (C**) = 71,428.57;
            LGD* = 0.35 x 0.714286 + 0.45 x 0.285714 = 0.378571, both currencies.

CL-14 — a collateral row with NO currency is treated as mismatched.
    CRR Art. 223(2) / PS1/26 Art. 230(1)(b) apply H_fx for "any currency
    mismatch between the exposure and the collateral"; an unknown denomination
    cannot establish that there is none. Before CL-14 ``null != x`` was null and
    H_fx was switched off silently. Now it applies and CRM023 records it.

    Hand calculation (SA, EUR loan 100,000 at EUR/GBP 0.85 = 85,000; cash
    50,000 with a null currency, liquidation period 10 days, both regimes):
        H_fx = 8%; C_VA = 50,000 x 0.92 = 46,000; E* = 85,000 - 46,000 = 39,000
        (pre-fix 35,000: the full 50,000 counted with no H_fx).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.unit.crm import _pipeline_harness as harness

from rwa_calc.rulebook.resolve import resolve

_EUR_AT_PAR = pl.DataFrame([{"currency_from": "EUR", "currency_to": "GBP", "rate": 1.0}])
_EUR_AT_085 = pl.DataFrame([{"currency_from": "EUR", "currency_to": "GBP", "rate": 0.85}])


def _firb_property_lgd(regime: str, currency: str) -> float:
    pledge = {
        "collateral_reference": "P1",
        "collateral_type": "real_estate",
        "market_value": 100_000.0,
        "currency": currency,
        "property_type": "commercial",
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "is_qualifying_re": True,
        "is_eligible_irb_collateral": True,
    }
    results, _errors = harness.run(
        regime,
        firb=True,
        loans=harness.loans(
            [{"loan_reference": "L1", "counterparty_reference": "CP1", "drawn_amount": 100_000.0}]
        ),
        collateral=harness.collateral([pledge]),
        fx_rates=_EUR_AT_PAR,
    )
    result = harness.row(results, "L1")
    assert result["approach_applied"] == "foundation_irb"
    return result["lgd_post_crm"]


class TestBasel31FcmHfxOnNonFinancialCollateral:
    """CL-09: PS1/26 Art. 230(1)(b) H_fx on property; CRR Art. 230 without it."""

    def test_feature_is_enabled_under_basel_3_1_only(self) -> None:
        # Act / Assert
        assert resolve("b31", date(2027, 6, 30)).feature("fcm_hfx_applies_to_non_financial")
        assert not resolve("crr", date(2026, 6, 30)).feature("fcm_hfx_applies_to_non_financial")

    def test_basel_3_1_eur_property_takes_hfx(self) -> None:
        # Act
        lgd = _firb_property_lgd("b31", "EUR")

        # Assert: (0.20 x 52,000 + 0.40 x 48,000) / 100,000.
        assert lgd == pytest.approx(0.296, rel=1e-9)

    def test_basel_3_1_gbp_property_takes_none(self) -> None:
        # Act
        lgd = _firb_property_lgd("b31", "GBP")

        # Assert: (0.20 x 60,000 + 0.40 x 40,000) / 100,000 — the matched control.
        assert lgd == pytest.approx(0.28, rel=1e-9)

    @pytest.mark.parametrize("currency", ["EUR", "GBP"])
    def test_crr_property_is_unchanged_by_currency(self, currency: str) -> None:
        # Act
        lgd = _firb_property_lgd("crr", currency)

        # Assert: 0.35 x (1 / 1.4) + 0.45 x (1 - 1 / 1.4).
        assert lgd == pytest.approx(0.35 / 1.4 + 0.45 * (1 - 1 / 1.4), rel=1e-9)


class TestUnknownCollateralCurrencyIsAMismatch:
    """CL-14: a null collateral currency takes H_fx and raises CRM023."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        ("currency", "expected_ead", "expect_crm023"),
        [
            (None, 39_000.0, True),  # unknown -> H_fx 8%: 85,000 - 46,000
            ("EUR", 42_500.0, False),  # matched: 85,000 - 50,000 x 0.85
            ("GBP", 39_000.0, False),  # known mismatch: 85,000 - 50,000 x 0.92
        ],
    )
    def test_sa_exposure_value(
        self, regime: str, currency: str | None, expected_ead: float, expect_crm023: bool
    ) -> None:
        # Arrange
        pledge = {
            "collateral_reference": "C1",
            "collateral_type": "cash",
            "market_value": 50_000.0,
            "currency": currency,
            "beneficiary_type": "loan",
            "beneficiary_reference": "L1",
            "is_eligible_financial_collateral": True,
        }

        # Act
        results, errors = harness.run(
            regime,
            loans=harness.loans(
                [
                    {
                        "loan_reference": "L1",
                        "counterparty_reference": "CP1",
                        "drawn_amount": 100_000.0,
                        "currency": "EUR",
                    }
                ]
            ),
            collateral=harness.collateral([pledge]),
            fx_rates=_EUR_AT_085,
        )

        # Assert
        result = harness.row(results, "L1")
        assert result["ead_final"] == pytest.approx(expected_ead, rel=1e-9)
        assert ("CRM023" in harness.codes(errors)) is expect_crm023

    def test_crm023_names_the_item_once(self) -> None:
        # Arrange: one currency-less pledge on a GBP loan.
        pledge = {
            "collateral_reference": "NOCCY",
            "collateral_type": "cash",
            "market_value": 10_000.0,
            "currency": None,
            "beneficiary_type": "loan",
            "beneficiary_reference": "L1",
            "is_eligible_financial_collateral": True,
        }

        # Act
        _results, errors = harness.run(
            "b31",
            loans=harness.loans(
                [
                    {
                        "loan_reference": "L1",
                        "counterparty_reference": "CP1",
                        "drawn_amount": 100_000.0,
                    }
                ]
            ),
            collateral=harness.collateral([pledge]),
        )

        # Assert
        records = [e for e in errors if e.code == "CRM023"]
        assert len(records) == 1
        assert "NOCCY" in records[0].message
