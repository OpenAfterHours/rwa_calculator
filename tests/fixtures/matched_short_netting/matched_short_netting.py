"""
Matched short-dated on-B/S netting under F-IRB: the 2026-09-05 escape shape.

An interbank loan and an interbank deposit (a negative-drawn loan) to the same
institution, under one netting agreement, in one currency, sharing ONE maturity
date. CRR Art. 219 turns the deposit into cash collateral; the funded-protection
maturity rules (Art. 237-239) then apply. Equal residual maturities are not a
mismatch (Art. 237(1) needs the protection to be SHORTER than the exposure), so
the deposit must net in full whatever the shared tenor — seven days, sixty days,
six months, or a contractual date that has already passed on a rolled position.

The engine floored the EXPOSURE residual at 0.25 years before comparing it with
the (unfloored) deposit residual, so every matched pair inside three months of
the reporting date compared as "protection shorter than exposure", tripped the
Art. 237(1) three-month gate, and lost all protection: LGD* stayed at the
unsecured 45% and the loan carried full RWA. Interbank money is exactly this
tenor, and the report came from an F-IRB institution book.

Scenarios (label -> shared tenor in days after the reporting date; negative =
already matured):

    matched_7d, matched_60d, matched_89d  — inside the three-month window
    matched_past                          — matured ten days before reporting
    matched_6m                            — control outside the window
    mismatch_30d_vs_2y                    — control: a REAL mismatch under three
                                            months (deposit 30 days, loan 2 years)
                                            must still zero the protection

Hand-calc (F-IRB, LGDS 0% for cash, E = 1,000,000, C = 1,000,000):
    matched_*     LGD* = (0.00 x 1,000,000 + LGDU x 0) / 1,000,000 = 0.00 -> RW 0, RWA 0
    mismatch_*    C = 0 -> LGD* = LGDU (45%: CRR senior; PS1/26 FSE senior) -> RWA > 0

The bundle is assembled IN MEMORY (no parquet dependency).

References:
    - CRR Art. 219 / PS1/26 Art. 219: on-B/S netting treated as cash collateral.
    - CRR Art. 237(1) / PS1/26 Art. 237(1): mismatch = protection residual LESS
      THAN exposure residual; sub-three-month protection ineligible only then.
    - CRR Art. 238(1) / PS1/26 Art. 238(1): exposure maturity capped at 5y, no floor.
    - CRR Art. 161(1)(a) / PS1/26 Art. 161(1)(a): 45% senior unsecured LGD (FSE).
    - docs/development/escape-log.md: 2026-09-05 matched short-dated pair entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

LOAN_DRAWN: float = 1_000_000.00
DEPOSIT_BALANCE: float = -1_000_000.00
MODEL_ID = "MSN-FIRB-INST"
INTERNAL_PD = 0.01

_RATING_SCHEMA: dict[str, pl.DataType] = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,
    "rating_agency": pl.String,
    "rating_value": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "rating_date": pl.Date,
    "is_solicited": pl.Boolean,
    "model_id": pl.String,
}


@dataclass(frozen=True)
class Scenario:
    """One matched-short-dated netting scenario."""

    label: str
    deposit_tenor_days: int
    loan_tenor_days: int

    @property
    def counterparty(self) -> str:
        return f"MSN-BANK-{self.label}"

    @property
    def deposit_ref(self) -> str:
        return f"MSN-DEP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"MSN-LN-{self.label}"

    @property
    def agreement_ref(self) -> str:
        # Scoped per scenario so a multi-scenario bundle cannot pool across them.
        return f"MSN-AGR-{self.label}"

    @property
    def is_matched(self) -> bool:
        return self.deposit_tenor_days == self.loan_tenor_days

    def deposit_maturity(self, reporting_date: date) -> date:
        return reporting_date + timedelta(days=self.deposit_tenor_days)

    def loan_maturity(self, reporting_date: date) -> date:
        return reporting_date + timedelta(days=self.loan_tenor_days)

    def deposit_value_date(self, reporting_date: date) -> date:
        # Opened thirty days before it matures: a short ORIGINAL term, which
        # Art. 237(2)(a) may only hold against the deposit where a mismatch exists.
        return self.deposit_maturity(reporting_date) - timedelta(days=30)


SCENARIOS: dict[str, Scenario] = {
    "matched_7d": Scenario("matched_7d", 7, 7),
    "matched_60d": Scenario("matched_60d", 60, 60),
    "matched_89d": Scenario("matched_89d", 89, 89),
    "matched_past": Scenario("matched_past", -10, -10),
    "matched_6m": Scenario("matched_6m", 182, 182),
    "mismatch_30d_vs_2y": Scenario("mismatch_30d_vs_2y", 30, 730),
}


def _counterparty(cp_ref: str) -> dict:
    return {
        "counterparty_reference": cp_ref,
        "counterparty_name": f"Matched-short netting bank ({cp_ref})",
        "entity_type": "institution",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": True,
        "total_assets": 200_000_000_000.0,
        "institution_cqs": 2,
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


def _rating(cp_ref: str, reporting_date: date) -> dict:
    return {
        "rating_reference": f"RAT-{cp_ref}",
        "counterparty_reference": cp_ref,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": INTERNAL_PD,
        "rating_date": reporting_date - timedelta(days=90),
        "is_solicited": True,
        "model_id": MODEL_ID,
    }


def build_matched_short_netting_bundle(
    scenario_labels: list[str], reporting_date: date
) -> RawDataBundle:
    """Assemble an in-memory F-IRB institution bundle for the named scenarios."""
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
                min(reporting_date, s.loan_maturity(reporting_date)) - timedelta(days=365),
                s.loan_maturity(reporting_date),
                s.agreement_ref,
            )
        )
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))
    ratings = pl.DataFrame(
        [_rating(s.counterparty, reporting_date) for s in scenarios], schema=_RATING_SCHEMA
    )
    model_permissions = pl.DataFrame(
        [{"model_id": MODEL_ID, "exposure_class": "institution", "approach": "foundation_irb"}],
        schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
    )

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        ratings=ratings,
        model_permissions=model_permissions,
    )
