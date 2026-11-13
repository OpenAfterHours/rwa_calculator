"""
On-balance-sheet netting WITH a mismatch, beside genuine collateral — the
portfolio that can tell a netted deposit's adjusted value from its allocation.

Pipeline position:
    build_netting_mismatch_bundle(reporting_date) -> RawDataBundle
        -> PipelineOrchestrator -> AggregatedResultBundle -> COREPGenerator

Why a NEW portfolio (rather than the registered ``netting`` one): every leg of
``reporting_netting_portfolio`` is in one currency and matures on one date, so
there the adjusted value of a netted deposit EQUALS its pro-rata allocation and
no test over it can say which of the two a template column carries. It also has
no collateral table at all, so "financial collateral" and "netting" are the same
money on every row. Both are deliberate there (it isolates the perimeter
question) and both make it blind to the defect this portfolio is for: OF 07.00
deducting the netted deposit in column 0035 and again inside column 0130
(escape log, 2026-09-05). Extending that portfolio would move its committed
goldens in BOTH regimes for a reason unrelated to its purpose; CRR must not move
at all for this fix.

Three obligors, each one leg of the question (LESSONS B5 — a figure that only
ever moves cannot be told from one that was zeroed):

    CP-M  — the leg that DIFFERS. A GBP 200,000 deposit maturing two years out
            nets a GBP 1,000,000 loan maturing in ten (Art. 238(1) caps T at
            five), so Art. 219(3) scales the netting by (t - 0.25) / (T - 0.25).
            The loan ALSO carries GBP 100,000 of ordinary cash collateral with no
            mismatch. Allocation 200,000; adjusted 73,626.57; collateral 100,000.
    CP-N  — the leg that AGREES. A GBP 100,000 deposit and a GBP 500,000 loan
            maturing together: no mismatch, adjusted == allocation == 100,000.
    CP-P  — collateral WITHOUT netting. A GBP 300,000 loan secured by GBP 50,000
            cash with a two-year residual: an ordinary Art. 239(2) mismatch, so
            columns 0130 and 0140 carry a figure that owes nothing to netting.

Hand calculation (all GBP, unrated corporates, everything drawn). The dates are
set RELATIVE to the reporting date so the figures are the same in both regimes:

    t   = 730 days / 365.25                 = 1.99863107 years   (deposit residual)
    T   = min(3,653 days / 365.25, 5)       = 5                  (Art. 238(1) cap)
    f   = (t - 0.25) / (T - 0.25)           = 1.74863107 / 4.75  = 0.36813286
    deposit original term 1,096 days / 365  = 3.003 years >= 1   (Art. 237(2)(a) passed)

    CP-M netting, adjusted   = 200,000 x f              =    73,626.57
    CP-N netting, adjusted   = 100,000 (no mismatch)    =   100,000.00
    CP-M pledge, adjusted    = 100,000 (cash, matched)  =   100,000.00
    CP-P pledge, adjusted    = 50,000 x (2 - 0.25)/4.75 =    18,421.05
    CP-P pledge, adjustment  = 50,000 - 18,421.05       =    31,578.95

    exposure value  CP-M = 1,000,000 - 73,626.57 - 100,000 =   826,373.43
                    CP-N =   500,000 - 100,000             =   400,000.00
                    CP-P =   300,000 - 18,421.05           =   281,578.95
                                                    total  = 1,507,952.38

OF 07.00 (Basel 3.1), corporate sheet, total row — netting reported ONCE:

    0010 gross                              1,800,000.00
    0035 (-) on-balance-sheet netting        -173,626.57   (73,626.57 + 100,000)
    0040 net of adjustments and netting     1,626,373.43
    0130 (-) financial collateral, adjusted  -118,421.05   (100,000 + 18,421.05)
    0140 (-) of which vol./maturity adj.      -31,578.95   (the CP-P pledge only)
    0150 fully adjusted exposure value      1,507,952.38
    0200 exposure value                     1,507,952.38

C 07.00 (CRR) has no column 0035; the deposit is financial collateral there:

    0040                                    1,800,000.00
    0130                                     -292,047.62   (173,626.57 + 118,421.05)
    0140                                     -157,952.38   (31,578.95 + 126,373.43)
    0150 = 0200                             1,507,952.38

NOT YET registered in the supervisory ``RUNS`` matrix, and LESSONS B5 says it
should be: it is the only portfolio in which a Basel 3.1 SA exposure carries
genuine financial collateral in column 0130 and a live column 0140. Registration
changes the run matrix and so re-banks the validation register and three ratchet
baselines, which was kept apart from the fix this portfolio was built for; the
debt is recorded, with what registering it buys, in
``scripts/coverage_report.py::EXCLUDED_PORTFOLIOS``. It is assembled IN MEMORY,
so there is no parquet to register in ``generate_all.py``.

References:
- CRR Art. 219 / PS1/26 Art. 219(1)-(3): on-balance-sheet netting, adjusted for
  currency and maturity mismatches
- CRR Art. 237-239: maturity mismatch; Art. 238(1) five-year cap on T
- PS1/26 Annex II, OF 07.00 columns 0035, 0040, 0130, 0140, 0150, 0200
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LOAN_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_M: str = "NMM-CP-M"
CP_N: str = "NMM-CP-N"
CP_P: str = "NMM-CP-P"

DEP_M: str = "NMM-DEP-M"
LN_M: str = "NMM-LN-M"
DEP_N: str = "NMM-DEP-N"
LN_N: str = "NMM-LN-N"
LN_P: str = "NMM-LN-P"

DRAWN_M: float = 1_000_000.0
DRAWN_N: float = 500_000.0
DRAWN_P: float = 300_000.0
DEPOSIT_M: float = 200_000.0
DEPOSIT_N: float = 100_000.0
PLEDGE_M: float = 100_000.0
PLEDGE_P: float = 50_000.0

#: Day counts relative to the reporting date.
_DEPOSIT_RESIDUAL_DAYS: int = 730
_DEPOSIT_AGE_DAYS: int = 366
_LOAN_RESIDUAL_DAYS: int = 3_653

#: The CP-P pledge's stated residual and original terms (years).
_PLEDGE_RESIDUAL_YEARS: float = 2.0
_PLEDGE_ORIGINAL_YEARS: float = 3.0

#: Art. 238(1) cap on the exposure maturity, and the Art. 239(2) quarter-year term.
_T_CAP: float = 5.0
_T_STAR: float = 0.25

_DEPOSIT_T: float = _DEPOSIT_RESIDUAL_DAYS / 365.25
MISMATCH_FACTOR: float = (_DEPOSIT_T - _T_STAR) / (_T_CAP - _T_STAR)
_PLEDGE_FACTOR: float = (_PLEDGE_RESIDUAL_YEARS - _T_STAR) / (_T_CAP - _T_STAR)

#: Netting per loan: the pre-haircut ALLOCATION and the ADJUSTED value.
NETTING_ALLOCATION: dict[str, float] = {LN_M: DEPOSIT_M, LN_N: DEPOSIT_N, LN_P: 0.0}
NETTING_ADJUSTED: dict[str, float] = {
    LN_M: DEPOSIT_M * MISMATCH_FACTOR,
    LN_N: DEPOSIT_N,
    LN_P: 0.0,
}

#: Genuine collateral per loan: market value and adjusted value.
PLEDGE_MARKET: dict[str, float] = {LN_M: PLEDGE_M, LN_N: 0.0, LN_P: PLEDGE_P}
PLEDGE_ADJUSTED: dict[str, float] = {LN_M: PLEDGE_M, LN_N: 0.0, LN_P: PLEDGE_P * _PLEDGE_FACTOR}

GROSS: float = DRAWN_M + DRAWN_N + DRAWN_P
TOTAL_NETTING_ALLOCATION: float = sum(NETTING_ALLOCATION.values())
TOTAL_NETTING_ADJUSTED: float = sum(NETTING_ADJUSTED.values())
TOTAL_PLEDGE_ADJUSTED: float = sum(PLEDGE_ADJUSTED.values())
#: Market value less adjusted value, genuine collateral only / netting only.
PLEDGE_ADJUSTMENT: float = sum(PLEDGE_MARKET.values()) - TOTAL_PLEDGE_ADJUSTED
NETTING_ADJUSTMENT: float = TOTAL_NETTING_ALLOCATION - TOTAL_NETTING_ADJUSTED
EXPOSURE_VALUE: float = GROSS - TOTAL_NETTING_ADJUSTED - TOTAL_PLEDGE_ADJUSTED


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_netting_mismatch_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the portfolio, with every date set relative to ``reporting_date``.

    Run it under either regime with ``PermissionMode.STANDARDISED`` and the SAME
    ``reporting_date`` passed here — the residual maturities, and so every
    figure in the module docstring, are stated from it.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(reporting_date),
        facility_mappings=pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        collateral=_collateral(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Three unrated corporates above the SME ceiling — one flat SA risk weight."""
    rows: list[dict] = [
        {
            "counterparty_reference": cp,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
        }
        for cp in (CP_M, CP_N, CP_P)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _loans(reporting_date: date) -> pl.DataFrame:
    """Two deposits (negative drawn balances) and three loans."""
    opened = reporting_date - timedelta(days=_DEPOSIT_AGE_DAYS)
    long_dated = reporting_date + timedelta(days=_LOAN_RESIDUAL_DAYS)
    short_dated = reporting_date + timedelta(days=_DEPOSIT_RESIDUAL_DAYS)
    common: dict = {
        "product_type": "term_loan",
        "currency": "GBP",
        "value_date": opened,
        "seniority": "senior",
        "interest": 0.0,
    }

    def _row(ref: str, cp: str, drawn: float, maturity: date, agreement: str | None) -> dict:
        return {
            "loan_reference": ref,
            "counterparty_reference": cp,
            "drawn_amount": drawn,
            "maturity_date": maturity,
            "netting_agreement_reference": agreement,
            **common,
        }

    rows = [
        # CP-M: the deposit matures before the loan it nets — Art. 219(3).
        _row(DEP_M, CP_M, -DEPOSIT_M, short_dated, "NMM-AGR-M"),
        _row(LN_M, CP_M, DRAWN_M, long_dated, "NMM-AGR-M"),
        # CP-N: deposit and loan mature together — no mismatch.
        _row(DEP_N, CP_N, -DEPOSIT_N, long_dated, "NMM-AGR-N"),
        _row(LN_N, CP_N, DRAWN_N, long_dated, "NMM-AGR-N"),
        # CP-P: no agreement at all; collateral only.
        _row(LN_P, CP_P, DRAWN_P, long_dated, None),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _collateral() -> pl.DataFrame:
    """Two ordinary cash pledges, one matched and one with a maturity mismatch."""
    rows: list[dict] = [
        {
            "collateral_reference": "NMM-PLEDGE-M",
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": PLEDGE_M,
            "beneficiary_type": "loan",
            "beneficiary_reference": LN_M,
            "is_eligible_financial_collateral": True,
        },
        {
            "collateral_reference": "NMM-PLEDGE-P",
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": PLEDGE_P,
            "beneficiary_type": "loan",
            "beneficiary_reference": LN_P,
            "residual_maturity_years": _PLEDGE_RESIDUAL_YEARS,
            "original_maturity_years": _PLEDGE_ORIGINAL_YEARS,
            "is_eligible_financial_collateral": True,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))
