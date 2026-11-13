"""
Generate the Art. 219 on-balance-sheet netting CURRENCY fixtures (in-memory).

A netted deposit is treated as cash collateral for the loans it offsets
(Art. 219). Whether the deposit and the loan are in the same currency decides
whether — and how — that cash protection is recognised, and the two regimes
answer differently:

- **UK CRR Art. 219** (legislation.gov.uk, onshored text, read verbatim):
  *"Loans to and deposits with the lending institution subject to on-balance
  sheet netting are to be treated by that institution as cash collateral for the
  purpose of calculating the effect of funded credit protection for those loans
  and deposits of the lending institution subject to on-balance sheet netting
  which are denominated in the same currency."* A deposit in a different
  currency from the loan is NOT recognised as netting for that loan at all.
- **PS1/26 Art. 219(2)** (ps126app1.pdf, page 191 of 492, read verbatim with
  pymupdf): *"Where there is a currency mismatch between the exposure referred to
  in point (b)(i) of paragraph 1 and the loans and deposits referred to in point
  (b)(ii) of paragraph 1, the institution shall reflect the mismatch by applying
  the appropriate volatility adjustment specified in Table 4 in paragraph 1 of
  Article 224 to the value of the protection. The institution shall apply a 10
  business day liquidation period."* Art. 224(1) Table 4 gives 8% at 10 days
  (11.314% at 20, 5.657% at 5).

The currency that decides a mismatch is the currency each leg is DENOMINATED in.
By the time the CRM stage runs, ``FXConverter`` has rebased every amount to the
reporting currency and rewritten ``currency`` to it; the denomination survives
only in ``original_currency``. These scenarios therefore run through the full
``PipelineOrchestrator`` with an ``fx_rates`` table, so the conversion actually
happens — a CRM-unit frame with ``currency == original_currency`` cannot see the
difference. Every rate is 1.0 so the ONLY thing that moves a number is the
currency treatment.

Each scenario has its own unrated corporate counterparty (100% SA risk weight,
so RWA == EAD) and its own netting agreement, so scenarios assembled into one
bundle never pool together. A 1,000 loan is offset by a 300 deposit (a
negative-drawn loan) under that agreement; ``mixed_pool`` offsets the GBP loan
with a GBP 200 deposit AND a EUR 100 deposit, which must stay two pools.
``eur_gbp_sft`` is ``eur_gbp`` with the netted loan flagged ``is_sft``: the
haircut stage defaults an SFT beneficiary's collateral to the 5-day repo period
(Art. 224(2)), and Art. 219(2)'s 10 days must still win for the netted deposit.

The ``*_coll`` scenarios are the same pairs built into a bundle that ALSO carries
an ordinary collateral file (cash pledged to an unrelated loan). That is the
common production shape: ``FXConverter.convert_collateral`` adds
``original_currency`` to the user collateral, and the CRM stage
diagonal-concatenates the synthetic netting rows onto it — so a synthetic row
that does not carry ``original_currency`` itself gets a null there.

Base currency is GBP.

References:
    - UK CRR Art. 219: same-currency on-B/S netting treated as cash collateral.
    - PS1/26 Art. 219(1)-(2): cross-currency netting with Table 4 H_fx at 10 days.
    - CRR / PS1/26 Art. 224(1) Table 4: currency-mismatch volatility adjustment.
    - CRR / PS1/26 Art. 122: unrated corporate 100% risk weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FX_RATES_SCHEMA,
    LOAN_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

BASE_CURRENCY = "GBP"
LOAN_DRAWN: float = 1_000.00
DEPOSIT_ABS: float = 300.00

# Art. 224(1) Table 4, 10-day liquidation-period column — the period PS1/26
# Art. 219(2) prescribes for a netted deposit. Stated here from the article
# text, NOT read from the rulepack, so the hand-calc cannot share an engine
# assumption (LESSONS B3).
HFX_10_DAY: float = 0.08

# Unrelated user collateral for the ``*_coll`` bundles: GBP cash against a GBP
# loan of its own, so it nets nothing in any scenario and changes no figure the
# tests read.
OTHER_COUNTERPARTY = "NCCY-CP-OTHER"
OTHER_LOAN = "NCCY-LN-OTHER"
OTHER_LOAN_DRAWN: float = 500.00
OTHER_COLLATERAL_VALUE: float = 100.00


@dataclass(frozen=True)
class Scenario:
    """One netting pair (or mixed pool) under its own agreement.

    ``deposits`` is a tuple of (currency, absolute balance) — each becomes a
    negative-drawn loan under the scenario's agreement.
    """

    label: str
    loan_currency: str
    deposits: tuple[tuple[str, float], ...]
    loan_is_sft: bool = False

    @property
    def counterparty(self) -> str:
        return f"NCCY-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"NCCY-LN-{self.label}"

    @property
    def agreement_ref(self) -> str:
        return f"NCCY-AGR-{self.label}"

    def deposit_ref(self, index: int) -> str:
        return f"NCCY-DEP-{self.label}-{index}"

    def expected_relief(self, regime: str) -> float:
        """Regulator hand-calc of the netted deposits' value against the loan.

        CRR: only deposits denominated in the loan's currency are recognised
        (Art. 219), and they carry no currency haircut. Basel 3.1: every deposit
        is recognised; a mismatched one takes Table 4 at 10 days (Art. 219(2)).
        Cash has a 0% Table 3 haircut and every rate is 1.0, so nothing else moves.
        """
        relief = 0.0
        for currency, balance in self.deposits:
            if currency == self.loan_currency:
                relief += balance
            elif regime == "b31":
                relief += balance * (1.0 - HFX_10_DAY)
        return relief

    def expected_ead(self, regime: str) -> float:
        """Post-netting EAD of the loan (= RWA at the 100% unrated-corporate RW)."""
        return LOAN_DRAWN - self.expected_relief(regime)

    @property
    def total_deposits(self) -> float:
        return sum(balance for _, balance in self.deposits)


def _pair(label: str, deposit_currency: str, loan_currency: str) -> Scenario:
    return Scenario(label, loan_currency, ((deposit_currency, DEPOSIT_ABS),))


SCENARIOS: dict[str, Scenario] = {
    s.label: s
    for s in (
        _pair("gbp_gbp", "GBP", "GBP"),
        _pair("eur_gbp", "EUR", "GBP"),
        _pair("gbp_eur", "GBP", "EUR"),
        _pair("eur_eur", "EUR", "EUR"),
        Scenario("mixed_pool", "GBP", (("GBP", 200.00), ("EUR", 100.00))),
        Scenario("eur_gbp_sft", "GBP", (("EUR", DEPOSIT_ABS),), loan_is_sft=True),
        _pair("gbp_gbp_coll", "GBP", "GBP"),
        _pair("eur_gbp_coll", "EUR", "GBP"),
        _pair("gbp_eur_coll", "GBP", "EUR"),
        _pair("eur_eur_coll", "EUR", "EUR"),
    )
}

# The two bundles: the collateral-file variants must not share a bundle with the
# plain ones, because the presence of ANY collateral file is the condition.
PLAIN_LABELS: tuple[str, ...] = (
    "gbp_gbp",
    "eur_gbp",
    "gbp_eur",
    "eur_eur",
    "mixed_pool",
    "eur_gbp_sft",
)
WITH_COLLATERAL_LABELS: tuple[str, ...] = (
    "gbp_gbp_coll",
    "eur_gbp_coll",
    "gbp_eur_coll",
    "eur_eur_coll",
)


def build_netting_currency_bundle(labels: tuple[str, ...], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named scenarios.

    A bundle whose labels are the ``*_coll`` set also carries the unrelated user
    collateral file (see the module docstring).
    """
    scenarios = [SCENARIOS[label] for label in labels]
    with_collateral = any(label.endswith("_coll") for label in labels)

    counterparty_refs = [s.counterparty for s in scenarios]
    if with_collateral:
        counterparty_refs.append(OTHER_COUNTERPARTY)
    counterparties = pl.DataFrame(
        [_counterparty(ref) for ref in counterparty_refs],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )

    loan_rows: list[dict] = []
    for s in scenarios:
        for index, (currency, balance) in enumerate(s.deposits):
            loan_rows.append(
                _loan(s.deposit_ref(index), s.counterparty, currency, -balance, s.agreement_ref)
            )
        loan_rows.append(
            _loan(
                s.loan_ref,
                s.counterparty,
                s.loan_currency,
                LOAN_DRAWN,
                s.agreement_ref,
                is_sft=s.loan_is_sft,
            )
        )
    if with_collateral:
        loan_rows.append(
            _loan(OTHER_LOAN, OTHER_COUNTERPARTY, BASE_CURRENCY, OTHER_LOAN_DRAWN, None)
        )
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))

    extra: dict[str, pl.DataFrame] = {}
    if with_collateral:
        extra["collateral"] = _unrelated_collateral()

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        fx_rates=_fx_rates(),
        **extra,
    )


def _fx_rates() -> pl.DataFrame:
    """Unit rates to the GBP base: conversion runs, values do not move."""
    rows = [
        {"currency_from": "EUR", "currency_to": BASE_CURRENCY, "rate": 1.0},
        {"currency_from": "GBP", "currency_to": BASE_CURRENCY, "rate": 1.0},
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FX_RATES_SCHEMA))


def _unrelated_collateral() -> pl.DataFrame:
    row = {
        "collateral_reference": "NCCY-COLL-OTHER",
        "collateral_type": "cash",
        "currency": BASE_CURRENCY,
        "market_value": OTHER_COLLATERAL_VALUE,
        "beneficiary_type": "loan",
        "beneficiary_reference": OTHER_LOAN,
        "is_eligible_financial_collateral": True,
    }
    schema = dtypes_of(COLLATERAL_SCHEMA)
    return pl.DataFrame([row], schema={name: schema[name] for name in row})


def _counterparty(cp_ref: str) -> dict:
    return {
        "counterparty_reference": cp_ref,
        "counterparty_name": f"Netting currency SA corporate ({cp_ref})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(
    ref: str,
    cp_ref: str,
    currency: str,
    drawn: float,
    agreement_ref: str | None,
    *,
    is_sft: bool = False,
) -> dict:
    # Deposit and loan share one six-year maturity, so no Art. 237-239 maturity
    # mismatch can arise and the currency treatment is the only adjustment.
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "currency": currency,
        "value_date": date(2026, 1, 1),
        "maturity_date": date(2032, 1, 1),
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "netting_agreement_reference": agreement_ref,
        "is_sft": is_sft,
    }
