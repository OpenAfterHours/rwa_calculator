"""
Generate P1.241 fixtures: Art. 219 on-B/S netting maturity mismatch (Art. 237-239).

On-balance-sheet netting treats a deposit as cash collateral (CRR Art. 219), so
the funded-protection maturity-mismatch rules (Art. 237-239) then apply. Each
Scenario's rows carry their OWN `netting_agreement_reference`
(`f"{AGREEMENT_REF}-{label}"`, via `Scenario.agreement_ref`), rather than the
single module-level `AGREEMENT_REF` value: under the on-B/S netting
agreement-perimeter reading (see `tests/fixtures/p1_238/p1_238.py`), ALL rows
sharing one agreement reference pool together regardless of counterparty, so a
shared literal reference across scenarios would let a multi-scenario bundle
pool deposits/loans across scenarios — and this fixture is maturity-sensitive,
so pooling would corrupt the maturity-mismatch calculation by taking the
minimum deposit residual across scenarios rather than each scenario's own.
Scoping the reference per scenario keeps scenarios independent no matter how
many are assembled into one bundle. `AGREEMENT_REF` remains exported as the
shared PREFIX for callers that need it.

Each scenario carries a £200k deposit (a negative-drawn loan) and a £1m
positive loan under its own netting agreement (`AGR1-<label>`) and the SAME
counterparty (Art. 195):

    <regime>_matched   — 6-year deposit nets a 5-year loan (no mismatch): the full
                         £200k nets → EAD £800k (control).
    <regime>_partial   — deposit with 3-year ORIGINAL term but 6-month RESIDUAL
                         (value_date 2.5y before reporting) nets a 7-year loan
                         (T caps at 5y): original >= 1y so it is eligible, and the
                         £200k benefit is scaled by (t - 0.25)/(5 - 0.25).
    <regime>_short_orig — 6-month-ORIGINAL deposit (value_date = reporting) nets a
                         7-year loan: a mismatch with original < 1y → Art. 237(2)(a)
                         zeroes the protection → NO netting benefit → EAD £1m.
    <regime>_matched_short — deposit AND loan both mature 60 days out (deposit
                         opened 30 days before that): equal residuals are NOT a
                         mismatch (Art. 237(1)), so the short original term never
                         comes into it → full £200k nets → EAD £800k. Escape log
                         2026-09-05: the exposure residual used to be floored at
                         0.25y before the comparison, which zeroed this pair.
    <regime>_matched_past — both contractual dates passed 10 days before the
                         reporting date (a rolled position): still matched → EAD £800k.

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
from datetime import date, timedelta

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

    @property
    def agreement_ref(self) -> str:
        """Scenario-scoped netting agreement reference.

        Scoped per scenario (rather than the shared `AGREEMENT_REF` constant)
        so that assembling more than one scenario into a single bundle cannot
        pool their deposits/loans together under the agreement-perimeter
        reading — see the module docstring. This fixture is maturity-sensitive,
        so pooling would corrupt the mismatch calculation, not just the amount.
        """
        return f"{AGREEMENT_REF}-{self.label}"

    def deposit_value_date(self, reporting_date: date) -> date:
        # partial: 2.5y before reporting → 3y original term (>= 1y, eligible).
        # matched_short / matched_past: opened 30 days before maturity (short
        # original term that Art. 237(2)(a) may only hold against a MISMATCH).
        # matched / short_orig: value_date = reporting → original = residual.
        if self.kind == "partial":
            return reporting_date - relativedelta(years=2, months=6)
        if self.kind in ("matched_short", "matched_past"):
            return self.deposit_maturity(reporting_date) - timedelta(days=30)
        return reporting_date

    def deposit_maturity(self, reporting_date: date) -> date:
        # matched: 6-year deposit (longer than the 5-year loan → no mismatch).
        # matched_short: 60 days; matched_past: 10 days AGO (rolled position).
        # partial / short_orig: 6-month residual (short protection).
        if self.kind == "matched":
            return reporting_date + relativedelta(years=6)
        if self.kind == "matched_short":
            return reporting_date + timedelta(days=60)
        if self.kind == "matched_past":
            return reporting_date - timedelta(days=10)
        return reporting_date + relativedelta(months=6)

    def loan_maturity(self, reporting_date: date) -> date:
        # matched: 5-year loan. matched_short / matched_past: the deposit's own
        # date (equal residuals). partial / short_orig: 7-year loan → T caps at 5y.
        if self.kind == "matched":
            return reporting_date + relativedelta(years=5)
        if self.kind in ("matched_short", "matched_past"):
            return self.deposit_maturity(reporting_date)
        return reporting_date + relativedelta(years=7)

    def expected_loan_rwa(self, reporting_date: date) -> float:
        """Regulator hand-calc: post-netting EAD = 100% RWA (unrated corporate)."""
        dep_mat = self.deposit_maturity(reporting_date)
        # t = deposit residual (Art. 238), engine /365.25 basis (matches the
        # exposure-side T in HaircutCalculator.apply_maturity_mismatch).
        t = (dep_mat - reporting_date).days / 365.25
        # T = min(loan residual /365.25, 5.0) — Art. 238(1) caps T at five years
        # and does NOT floor it: the 0.25 term belongs to the scaling formula only.
        loan_days = (self.loan_maturity(reporting_date) - reporting_date).days
        big_t = min(loan_days / 365.25, 5.0)
        if t >= big_t:  # no maturity mismatch (Art. 237(1)) → full netting
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
    "crr_matched_short": Scenario("crr_matched_short", "matched_short"),
    "crr_matched_past": Scenario("crr_matched_past", "matched_past"),
    "b31_matched_short": Scenario("b31_matched_short", "matched_short"),
    "b31_matched_past": Scenario("b31_matched_past", "matched_past"),
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


def _loan(
    ref: str,
    cp_ref: str,
    drawn: float,
    value_date: date,
    maturity: date,
    agreement_ref: str,
) -> dict:
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "currency": "GBP",
        "value_date": value_date,
        "maturity_date": maturity,
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "netting_agreement_reference": agreement_ref,
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
                s.agreement_ref,
            )
        )
        loan_rows.append(
            _loan(
                s.loan_ref,
                s.counterparty,
                LOAN_DRAWN,
                reporting_date,
                s.loan_maturity(reporting_date),
                s.agreement_ref,
            )
        )
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
