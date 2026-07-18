"""
Generate P1.241 fixtures: Art. 219 on-B/S netting maturity mismatch (Art. 237-239).

On-balance-sheet netting treats a deposit as cash collateral (CRR Art. 219), so
the funded-protection maturity-mismatch rules (Art. 237-239) then apply. Each
scenario carries a £200k deposit (a negative-drawn loan) and a £1m positive loan
under the same netting agreement AGR1 and the SAME counterparty (Art. 195):

    <regime>_matched   — 6-year deposit nets a 5-year loan (no mismatch): the full
                         £200k nets → EAD £800k (control).
    <regime>_partial   — deposit with 3-year ORIGINAL term but 6-month RESIDUAL
                         (value_date 2.5y before reporting) nets a 7-year loan
                         (T caps at 5y): original >= 1y so it is eligible, and the
                         £200k benefit is scaled by (t - 0.25)/(5 - 0.25).
    <regime>_short_orig — 6-month-ORIGINAL deposit (value_date = reporting) nets a
                         7-year loan: a mismatch with original < 1y → Art. 237(2)(a)
                         zeroes the protection → NO netting benefit → EAD £1m.

Both counterparties are unrated corporates (100% SA risk weight), so the loan RWA
equals the post-netting EAD. The bundle is assembled IN MEMORY (no parquet
dependency), so the acceptance tests are reproducible on a fresh checkout.

References:
    - CRR Art. 219: on-B/S netting treated as cash collateral.
    - CRR Art. 237(1)/(2)(a): <3m residual / <1y original eligibility gates.
    - CRR Art. 238-239: (t - 0.25) / (T - 0.25) maturity-mismatch adjustment.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.241.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_MAPPING_SCHEMA, LOAN_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

DEPOSIT_BALANCE: float = -200_000.00
DEPOSIT_ABS: float = 200_000.00
LOAN_DRAWN: float = 1_000_000.00
AGREEMENT_REF = "P1241-AGR1"
RWA_NO_NETTING: float = 1_000_000.00  # £1m EAD × 100% (netting zeroed / absent)
RWA_MATCHED_NETTED: float = 800_000.00  # (£1m − £200k) × 100%, no mismatch


@dataclass(frozen=True)
class Scenario:
    """One P1.241 acceptance scenario."""

    label: str
    kind: str  # "matched" | "partial" | "short_orig"

    @property
    def counterparty(self) -> str:
        return f"P1241-CP-{self.label}"

    @property
    def deposit_ref(self) -> str:
        return f"P1241-DEP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1241-LN-{self.label}"

    def deposit_value_date(self, reporting_date: date) -> date:
        # partial: 2.5y before reporting → 3y original term (>= 1y, eligible).
        # matched / short_orig: value_date = reporting → original = residual.
        if self.kind == "partial":
            return reporting_date - relativedelta(years=2, months=6)
        return reporting_date

    def deposit_maturity(self, reporting_date: date) -> date:
        # matched: 6-year deposit (longer than the 5-year loan → no mismatch).
        # partial / short_orig: 6-month residual (short protection).
        if self.kind == "matched":
            return reporting_date + relativedelta(years=6)
        return reporting_date + relativedelta(months=6)

    def loan_maturity(self, reporting_date: date) -> date:
        # matched: 5-year loan. partial / short_orig: 7-year loan → T caps at 5y.
        if self.kind == "matched":
            return reporting_date + relativedelta(years=5)
        return reporting_date + relativedelta(years=7)

    def expected_loan_rwa(self, reporting_date: date) -> float:
        """Regulator hand-calc: post-netting EAD = 100% RWA (unrated corporate)."""
        dep_mat = self.deposit_maturity(reporting_date)
        # t = deposit residual (Art. 238), engine /365.25 basis (matches the
        # exposure-side T in HaircutCalculator.apply_maturity_mismatch).
        t = (dep_mat - reporting_date).days / 365.25
        # T = min(loan residual /365.25, 5.0), floored at 0.25.
        loan_days = (self.loan_maturity(reporting_date) - reporting_date).days
        big_t = max(min(loan_days / 365.25, 5.0), 0.25)
        if t >= big_t:  # no maturity mismatch → full netting
            return RWA_MATCHED_NETTED
        # original maturity (Art. 237(2)(a)) via /365 (engine enrich/risk_weights).
        orig = (dep_mat - self.deposit_value_date(reporting_date)).days / 365.0
        if t < 0.25 or orig < 1.0:  # Art. 237(1) / Art. 237(2)(a) → zeroed
            return RWA_NO_NETTING
        factor = (t - 0.25) / (big_t - 0.25)
        return LOAN_DRAWN - DEPOSIT_ABS * factor


SCENARIOS: dict[str, Scenario] = {
    "crr_matched": Scenario("crr_matched", "matched"),
    "crr_partial": Scenario("crr_partial", "partial"),
    "crr_short_orig": Scenario("crr_short_orig", "short_orig"),
    "b31_matched": Scenario("b31_matched", "matched"),
    "b31_partial": Scenario("b31_partial", "partial"),
    "b31_short_orig": Scenario("b31_short_orig", "short_orig"),
}


def _counterparty(cp_ref: str) -> dict:
    return {
        "counterparty_reference": cp_ref,
        "counterparty_name": f"P1.241 SA Corporate ({cp_ref})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(ref: str, cp_ref: str, drawn: float, value_date: date, maturity: date) -> dict:
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "currency": "GBP",
        "value_date": value_date,
        "maturity_date": maturity,
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "netting_agreement_reference": AGREEMENT_REF,
    }


def build_p1_241_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.241 scenarios."""
    scenarios = [SCENARIOS[label] for label in scenario_labels]

    counterparties = pl.DataFrame(
        [_counterparty(s.counterparty) for s in scenarios],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )

    loan_rows: list[dict] = []
    for s in scenarios:
        loan_rows.append(
            _loan(
                s.deposit_ref,
                s.counterparty,
                DEPOSIT_BALANCE,
                s.deposit_value_date(reporting_date),
                s.deposit_maturity(reporting_date),
            )
        )
        loan_rows.append(
            _loan(
                s.loan_ref,
                s.counterparty,
                LOAN_DRAWN,
                reporting_date,
                s.loan_maturity(reporting_date),
            )
        )
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
