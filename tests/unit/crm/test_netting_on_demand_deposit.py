"""
Review NT-03: a netted deposit with no maturity date is repayable on demand.

Why this matters:
    A current-account credit balance usually reaches the calculator with a null
    ``maturity_date``. Before NT-03 the netting pool's ``min(maturity_date)``
    skipped the null and its residual stayed null, which the mismatch step reads
    as a 10-year protection, so the deposit netted in full against a term loan
    (loan EAD 2,000 below) — while the SAME deposit given its true overnight
    date lost the relief to the Art. 237(1) gate (EAD 6,000, CRM002). The null
    was the most favourable input there was.

Rule (quoted, verbatim):
    PS1/26 Art. 238(1): "the institution shall take the maturity of the credit
    protection to be the time to the earliest date at which the protection may
    terminate or be terminated; except that, solely in the case of point (a) of
    paragraph 1A [on-balance sheet netting], this shall be the time to the
    earlier of (a) the date when the netting agreement may terminate or be
    terminated and (b) the date when the deposit with the institution can be
    withdrawn or the loan to the institution called." CRR Art. 238(1): "the
    maturity of the credit protection shall be the time to the earliest date at
    which the protection may terminate or be terminated". Art. 237(1) (both):
    "Where protection has a residual maturity of less than three months and the
    maturity of the protection is less than the maturity of the underlying
    exposure an institution shall not use that protection as eligible credit
    protection."

Hand calculation (same counterparty, agreement AGR1, loan 6,000 maturing
2032-01-01, deposit 4,000, SA RW 100%, both regimes):
    deposit maturity null  -> t = 0 < T, 237(1) gate -> loan EAD 6,000, CRM024
        (pre-fix 2,000);
    deposit and loan both null (on-demand pair, both callable today) -> no
        mismatch -> EAD 6,000 - 4,000 = 2,000, no CRM024;
    deposit dated 2032-01-01 (t = T) -> no mismatch -> EAD 2,000.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.unit.crm import _pipeline_harness as harness

from rwa_calc.engine.crm.netting import generate_netting_collateral
from rwa_calc.rulebook.resolve import resolve

_LOAN_MATURITY = date(2032, 1, 1)


def _run(regime: str, deposit_maturity: date | None, loan_maturity: date | None):
    results, errors = harness.run(
        regime,
        loans=harness.loans(
            [
                {
                    "loan_reference": "L1",
                    "counterparty_reference": "CP1",
                    "drawn_amount": 6_000.0,
                    "maturity_date": loan_maturity,
                    "netting_agreement_reference": "AGR1",
                },
                {
                    "loan_reference": "D1",
                    "counterparty_reference": "CP1",
                    "drawn_amount": -4_000.0,
                    "maturity_date": deposit_maturity,
                    "netting_agreement_reference": "AGR1",
                },
            ]
        ),
    )
    return harness.row(results, "L1"), errors


class TestOnDemandDepositAgainstATermLoan:
    """End to end, both regimes."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_null_maturity_deposit_does_not_net_against_a_later_loan(self, regime: str) -> None:
        # Act
        result, errors = _run(regime, None, _LOAN_MATURITY)

        # Assert: pre-fix 2,000 with no record.
        assert result["ead_final"] == pytest.approx(6_000.0)
        codes = harness.codes(errors)
        assert {"CRM002", "CRM024"} <= codes
        records = [e for e in errors if e.code == "CRM024"]
        assert len(records) == 1
        assert "AGR1" in records[0].message

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_on_demand_pair_still_nets(self, regime: str) -> None:
        # Act
        result, errors = _run(regime, None, None)

        # Assert
        assert result["ead_final"] == pytest.approx(2_000.0)
        assert "CRM024" not in harness.codes(errors)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_matched_dated_deposit_still_nets(self, regime: str) -> None:
        # Act
        result, errors = _run(regime, _LOAN_MATURITY, _LOAN_MATURITY)

        # Assert
        assert result["ead_final"] == pytest.approx(2_000.0)
        assert "CRM024" not in harness.codes(errors)


class TestSyntheticRowResidual:
    """The generator itself: an on-demand pool carries t = 0, a dated one its date."""

    def test_on_demand_deposit_in_a_dated_pool_sets_t_to_zero(self) -> None:
        # Arrange: two deposits under one agreement, one dated, one on demand.
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "D1", "D2"],
                "counterparty_reference": ["CP1", "CP1", "CP1"],
                "netting_agreement_reference": ["AGR1"] * 3,
                "exposure_type": ["loan"] * 3,
                "drawn_amount": [6_000.0, -2_000.0, -2_000.0],
                "ead_gross": [6_000.0, 0.0, 0.0],
                "currency": ["GBP"] * 3,
                "maturity_date": [_LOAN_MATURITY, date(2030, 1, 1), None],
            }
        )

        # Act
        synthetic = generate_netting_collateral(
            exposures, pack=resolve("b31", date(2027, 6, 30)), reporting_date=date(2027, 6, 30)
        )

        # Assert: min() skipped the null before NT-03 and returned 2030-01-01.
        assert synthetic is not None
        out = synthetic.collect()
        assert out["residual_maturity_years"].to_list() == [0.0]
        assert out["maturity_date"].to_list() == [None]
        assert out["market_value"].to_list() == [pytest.approx(4_000.0)]
