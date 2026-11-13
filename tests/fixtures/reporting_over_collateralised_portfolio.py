"""
Over-collateralised standardised loans beside ordinary ones — the portfolio that
can tell a per-exposure collateral cap from a sheet-wide one.

Pipeline position:
    build_over_collateralised_bundle(reporting_date) -> RawDataBundle
        -> PipelineOrchestrator -> AggregatedResultBundle -> COREPGenerator

Why it exists. The engine floors each SA exposure at zero after its own
collateral (CRR / PS1/26 Art. 223(5): E* = max{0, ...}, per exposure), so a loan
secured by more collateral than it owes has an exposure value of zero and the
EXCESS is simply unused. C 07.00 / OF 07.00 summed the whole collateral carrier
into column 0130 and floored only the CELL (``0150 = max(0, 0110 - 0130)`` over
the sheet's totals), so one over-collateralised loan took its unused collateral
off every OTHER loan on the sheet: column 0150 fell below column 0200, breaking
``boe_b0471`` / ``boe_b0556`` (Basel 3.1) and the EBA equivalents (CRR). No
registered portfolio held an over-collateralised SA loan, so no gate could see
it (LESSONS B5).

Four obligors, every one an unrated corporate above the SME ceiling (one flat
100% risk weight in both regimes), each one leg of the question. LESSONS B5's
two-leg rule: a figure that only ever MOVES cannot be told from one that was
zeroed, so one leg's collateral must survive the fix untouched.

    OC-A  — the leg that MOVES, and its victim. LN-A1 owes 100,000 and is
            secured by 300,000 of matched GBP cash; LN-A2 owes 1,000,000 and is
            unsecured. Uncapped, column 0130 takes 300,000 and the 200,000 the
            loan does not need comes off LN-A2.
    OC-B  — the leg that SURVIVES. 500,000 secured by 200,000 of matched cash:
            collateral below the exposure, so the cap must not touch it.
    OC-C  — over-collateralised WITH an adjustment, which is what pins the
            reading of column 0140. 100,000 secured by 500,000 of cash with a
            two-year residual against a loan maturing in ten (Art. 238(1) caps T
            at five), so Art. 239(2) scales the cash by (t - t*)/(T - t*):
            Cvam = 184,210.53, still above the exposure. Capped, column 0130
            takes 100,000; column 0140 keeps the joint adjustment AS CALCULATED,
            315,789.47 — EBA Q&A 2015_2010's reading (capping column 0130 and
            leaving column 0140 at its calculated value). A design that scaled
            column 0140 down with the cap would report 171,428.57 here instead.
    OC-D  — the CRR form of the same defect: a 300,000 deposit netted against a
            100,000 loan (Art. 219), maturities matched. CRR reports the deposit
            as financial collateral in column 0130, so it over-runs exactly as
            OC-A does. Basel 3.1 reports it in column 0035, which was already
            capped at the exposure (``_netting_reduction_expr``) — its column
            0130 share is zero there.

Hand calculation (all GBP, everything drawn). Dates are relative to the
reporting date, so the figures are the same in both regimes:

    f    = (2 - 0.25) / (5 - 0.25)              = 0.36842105   (OC-C pledge)
    Cvam(OC-C) = 500,000 x f                    =   184,210.53
    adjustment(OC-C) = 500,000 - 184,210.53     =   315,789.47

    exposure value   A1 0 | A2 1,000,000 | B 300,000 | C 0 | D 0
                                              total = 1,300,000.00

C 07.00 (CRR), corporate sheet, total row:

                        before the fix     after the fix
    0010 / 0040           1,800,000.00      1,800,000.00
    0130 (-) Cvam          -984,210.53       -500,000.00   (100k + 200k + 100k + 100k)
    0140 (-) of which      -315,789.47       -315,789.47   (OC-C only; as calculated)
    0150                    815,789.47      1,300,000.00
    0200                  1,300,000.00      1,300,000.00

OF 07.00 (Basel 3.1), corporate sheet, total row:

    0010                  1,800,000.00      1,800,000.00
    0035 (-) netting       -100,000.00       -100,000.00   (OC-D, already capped)
    0040                  1,700,000.00      1,700,000.00
    0130 (-) Cvam          -684,210.53       -400,000.00   (100k + 200k + 100k)
    0140 (-) of which      -315,789.47       -315,789.47
    0150                  1,015,789.47      1,300,000.00
    0200                  1,300,000.00      1,300,000.00

Assembled IN MEMORY (as ``reporting_netting_mismatch_portfolio`` is), so there
is no parquet to register in ``generate_all.py``. Registered in the supervisory
``RUNS`` matrix under both regimes through ``functools.partial``.

References:
- CRR / PS1/26 Art. 219 (on-balance-sheet netting), Art. 223(5) (E*, floored
  at zero per exposure), Art. 238(1) / 239(2) (maturity mismatch)
- COREP Annex II / PS1/26 Annex II, C 07.00 / OF 07.00 columns 0130, 0140,
  0150, 0200; the block heading over columns 0050-0100 ("Collateral that has
  an effect on the exposure value ... shall be capped at the exposure value")
- EBA Q&A 2015_2010 (C 07.00 column 0130 capped at the volatility-adjusted
  exposure value, in line with v0307_m; column 0150 floored at zero)
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

CP_A: str = "OC-CP-A"
CP_B: str = "OC-CP-B"
CP_C: str = "OC-CP-C"
CP_D: str = "OC-CP-D"

LN_A1: str = "OC-LN-A1"
LN_A2: str = "OC-LN-A2"
LN_B: str = "OC-LN-B"
LN_C: str = "OC-LN-C"
LN_D: str = "OC-LN-D"
DEP_D: str = "OC-DEP-D"

DRAWN: dict[str, float] = {
    LN_A1: 100_000.0,
    LN_A2: 1_000_000.0,
    LN_B: 500_000.0,
    LN_C: 100_000.0,
    LN_D: 100_000.0,
}
DEPOSIT_D: float = 300_000.0

#: Cash pledged per loan (market value). OC-D's "collateral" is its deposit.
PLEDGE: dict[str, float] = {LN_A1: 300_000.0, LN_B: 200_000.0, LN_C: 500_000.0}

#: Day counts relative to the reporting date.
_LOAN_AGE_DAYS: int = 366
_LOAN_RESIDUAL_DAYS: int = 3_653

#: The OC-C pledge's stated residual and original terms (years).
_PLEDGE_C_RESIDUAL_YEARS: float = 2.0
_PLEDGE_C_ORIGINAL_YEARS: float = 3.0

#: Art. 238(1) cap on the exposure maturity, and the Art. 239(2) quarter-year term.
_T_CAP: float = 5.0
_T_STAR: float = 0.25
MISMATCH_FACTOR: float = (_PLEDGE_C_RESIDUAL_YEARS - _T_STAR) / (_T_CAP - _T_STAR)

#: The collateral's adjusted value (Cvam) per loan, uncapped, as the engine seals it.
CVAM: dict[str, float] = {
    LN_A1: PLEDGE[LN_A1],
    LN_B: PLEDGE[LN_B],
    LN_C: PLEDGE[LN_C] * MISMATCH_FACTOR,
    LN_D: DEPOSIT_D,
}

#: The engine's exposure value per loan: max(0, drawn - Cvam), Art. 223(5).
EXPOSURE_VALUE: dict[str, float] = {
    ref: max(0.0, drawn - CVAM.get(ref, 0.0)) for ref, drawn in DRAWN.items()
}

GROSS: float = sum(DRAWN.values())
TOTAL_EXPOSURE_VALUE: float = sum(EXPOSURE_VALUE.values())

#: Column 0140's magnitude: the OC-C pledge's joint adjustment (C - Cvam). The
#: other pledges are matched cash, and OC-D's deposit is matched too.
VOL_MAT_ADJUSTMENT: float = PLEDGE[LN_C] - CVAM[LN_C]

#: The loans whose collateral EXCEEDS the exposure — the legs the cap moves.
OVER_COLLATERALISED: tuple[str, ...] = tuple(ref for ref, cvam in CVAM.items() if cvam > DRAWN[ref])


def capped_collateral(*, deposit_in_column_0130: bool) -> float:
    """Column 0130's magnitude after the cap: each loan's Cvam, no more than it owes.

    ``deposit_in_column_0130`` is True under CRR (no column 0035, so the netted
    deposit is financial collateral) and False under Basel 3.1 (column 0035
    reports it and column 0130 leaves it out).
    """
    loans = CVAM if deposit_in_column_0130 else {k: v for k, v in CVAM.items() if k != LN_D}
    return sum(min(cvam, DRAWN[ref]) for ref, cvam in loans.items())


def uncapped_collateral(*, deposit_in_column_0130: bool) -> float:
    """Column 0130's magnitude BEFORE the fix: the whole collateral carrier."""
    loans = CVAM if deposit_in_column_0130 else {k: v for k, v in CVAM.items() if k != LN_D}
    return sum(loans.values())


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_over_collateralised_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the portfolio, with every date set relative to ``reporting_date``.

    Run it under either regime with ``PermissionMode.STANDARDISED`` and the SAME
    ``reporting_date`` passed here — the OC-C maturity mismatch, and so every
    figure in the module docstring, is stated from it.
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
    """Four unrated corporates above the SME ceiling — one flat SA risk weight."""
    rows: list[dict] = [
        {
            "counterparty_reference": cp,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
        }
        for cp in (CP_A, CP_B, CP_C, CP_D)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _loans(reporting_date: date) -> pl.DataFrame:
    """Five loans and one deposit, all long-dated so the OC-C mismatch binds."""
    common: dict = {
        "product_type": "term_loan",
        "currency": "GBP",
        "value_date": reporting_date - timedelta(days=_LOAN_AGE_DAYS),
        "maturity_date": reporting_date + timedelta(days=_LOAN_RESIDUAL_DAYS),
        "seniority": "senior",
        "interest": 0.0,
    }

    def _row(ref: str, cp: str, drawn: float, agreement: str | None = None) -> dict:
        return {
            "loan_reference": ref,
            "counterparty_reference": cp,
            "drawn_amount": drawn,
            "netting_agreement_reference": agreement,
            **common,
        }

    return pl.DataFrame(
        [
            _row(LN_A1, CP_A, DRAWN[LN_A1]),
            _row(LN_A2, CP_A, DRAWN[LN_A2]),
            _row(LN_B, CP_B, DRAWN[LN_B]),
            _row(LN_C, CP_C, DRAWN[LN_C]),
            # OC-D: the deposit and the loan it nets mature together — no mismatch.
            _row(DEP_D, CP_D, -DEPOSIT_D, "OC-AGR-D"),
            _row(LN_D, CP_D, DRAWN[LN_D], "OC-AGR-D"),
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )


def _collateral() -> pl.DataFrame:
    """Three cash pledges: two matched, one with a maturity mismatch."""

    def _pledge(ref: str, loan: str, **extra: float) -> dict:
        return {
            "collateral_reference": ref,
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": PLEDGE[loan],
            "beneficiary_type": "loan",
            "beneficiary_reference": loan,
            "is_eligible_financial_collateral": True,
            **extra,
        }

    return pl.DataFrame(
        [
            _pledge("OC-PLEDGE-A1", LN_A1),
            _pledge("OC-PLEDGE-B", LN_B),
            _pledge(
                "OC-PLEDGE-C",
                LN_C,
                residual_maturity_years=_PLEDGE_C_RESIDUAL_YEARS,
                original_maturity_years=_PLEDGE_C_ORIGINAL_YEARS,
            ),
        ],
        schema_overrides=dtypes_of(COLLATERAL_SCHEMA),
    )
