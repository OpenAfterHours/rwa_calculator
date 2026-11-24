"""
IRB sheet-PAIRINGS portfolio — the two Basel 3.1 OF 08.01 sheet combinations on
which the Bank of England's own rules fail a correct return.

Pipeline position:
    build_reporting_irb_pairings_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / filing.build_canonical_return

Why it exists (P5.81, the operator-approved second slice). Of the 39 runs
registered before it (2026-11-24), only ``declined-guarantee`` (P1.398, built for
another purpose) reported the non-SME corporates of both approaches, and none held
more than one non-retail A-IRB sheet. Two published rules are only reachable from a
book that breaks that pattern, and both are faulty — the publisher-issue register
records each with Arelle's verdict:

- **PI-02 — ``boe_b1053`` / ``b1054`` / ``b1055``.** OF 09.02 row 0055 ("Other
  corporate exposures", Annex II p.143) covers the general non-SME corporates of
  BOTH approaches, so it equals sheet 0011 (A-IRB) PLUS sheet 0012 (F-IRB). The
  rules test ``r0055 = z:0011`` and ``r0055 = z:0012`` as two separate equalities,
  so a return with figures on both sheets fails them however correct it is.
- **PI-31 — ``boe_b0748``.** The A-IRB Total sheet 0001 is tested against the
  SUM of the A-IRB class sheets on every column, maturity (c0250) included. An
  exposure-weighted average maturity is below the sum of the sheets' maturities
  whenever two sheets report one, so a correct return with two non-retail A-IRB
  sheets fails it.

This book therefore holds an A-IRB non-SME corporate (sheet 0011), an F-IRB
non-SME corporate (sheet 0012) and an A-IRB SME corporate (sheet 0023). The two
A-IRB legs differ in BOTH exposure and maturity, so the Total's c0250 tells an
exposure-weighted mean from a simple mean or a first-sheet pick (LESSONS C11) —
equal maturities would leave all three readings the same number.

What the pairings buy beyond the Bank's breaks: they show our OF 09.02 r0055 =
A + F through the real pipeline, and they are the only registered place where the
A-IRB Total averages c0250 over more than one non-retail sheet.

This book is kept SEPARATE from ``reporting_irb_coverage_portfolio`` on purpose:
its breaks are the Bank's, banked with publisher-issue reasons, and removing its
two ``RUNS`` entries reverses this half of P5.81 without touching the coverage
the other books give.

References:
- PRA PS1/26 Annex II: OF 09.02 r0055 (p.143); OF 08.01 c0250 (p.111)
- PRA PS1/26 Art. 147A(1)(e)/(f): the corporate sub-classes
- Bank of England publisher issues PI-02 (b1053-b1055) and PI-31 (b0748)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions``, or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_PAIR_AIRB: str = "IRP-CP-AIRB"
CP_PAIR_FIRB: str = "IRP-CP-FIRB"
CP_PAIR_SME_AIRB: str = "IRP-CP-SME-AIRB"

LN_PAIR_AIRB: str = "IRP-LN-AIRB"
LN_PAIR_FIRB: str = "IRP-LN-FIRB"
LN_PAIR_SME_AIRB: str = "IRP-LN-SME-AIRB"

#: Revenues, in GBP: two between the SME ceiling and the GBP 440m large-corporate
#: threshold (sheets 0011 / 0012), one below the SME ceiling (sheet 0023).
REVENUE_PAIR_AIRB: float = 150_000_000.0
REVENUE_PAIR_FIRB: float = 160_000_000.0
REVENUE_PAIR_SME_AIRB: float = 25_000_000.0

PD_PAIR_AIRB: float = 0.0110
PD_PAIR_FIRB: float = 0.0130
PD_PAIR_SME_AIRB: float = 0.0220

LGD_PAIR_AIRB: float = 0.32
LGD_PAIR_SME_AIRB: float = 0.38

#: Drawn amounts, in GBP — the two A-IRB legs differ, so an exposure-weighted
#: average is not a simple mean.
DRAWN_PAIR_AIRB: float = 3_100_000.0
DRAWN_PAIR_FIRB: float = 2_600_000.0
DRAWN_PAIR_SME_AIRB: float = 1_700_000.0

_VALUE_DATE: date = date(2020, 1, 1)
#: The two A-IRB maturities differ, and both stay inside the five-year cap from
#: the Basel 3.1 reporting date (2.08 and 4.08 years from 2027-06-01), so the
#: sheets report two different c0250 figures.
MATURITY_PAIR_AIRB: date = date(2029, 6, 30)
MATURITY_PAIR_SME_AIRB: date = date(2031, 6, 30)
MATURITY_PAIR_FIRB: date = date(2031, 12, 31)

#: The approach each leg must resolve to: (CRR, Basel 3.1). None diverges.
IRB_PAIRINGS_EXPECTED_APPROACH: dict[str, tuple[str, str]] = {
    LN_PAIR_AIRB: ("advanced_irb", "advanced_irb"),
    LN_PAIR_FIRB: ("foundation_irb", "foundation_irb"),
    LN_PAIR_SME_AIRB: ("advanced_irb", "advanced_irb"),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_irb_pairings_bundle() -> RawDataBundle:
    """Assemble the sheet-pairings portfolio as a sealed bundle.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Three GB corporates, one per sheet."""
    rows: list[dict] = [
        _corporate(CP_PAIR_AIRB, REVENUE_PAIR_AIRB),
        _corporate(CP_PAIR_FIRB, REVENUE_PAIR_FIRB),
        _corporate(CP_PAIR_SME_AIRB, REVENUE_PAIR_SME_AIRB),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings — an internal PD plus a matching permission routes IRB."""
    rows: list[dict] = [
        _internal(CP_PAIR_AIRB, pd=PD_PAIR_AIRB),
        _internal(CP_PAIR_FIRB, pd=PD_PAIR_FIRB),
        _internal(CP_PAIR_SME_AIRB, pd=PD_PAIR_SME_AIRB),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The three drawn legs. An own-estimate LGD is what makes a leg A-IRB."""
    rows: list[dict] = [
        _loan(LN_PAIR_AIRB, CP_PAIR_AIRB, DRAWN_PAIR_AIRB, MATURITY_PAIR_AIRB, lgd=LGD_PAIR_AIRB),
        _loan(LN_PAIR_FIRB, CP_PAIR_FIRB, DRAWN_PAIR_FIRB, MATURITY_PAIR_FIRB),
        _loan(
            LN_PAIR_SME_AIRB,
            CP_PAIR_SME_AIRB,
            DRAWN_PAIR_SME_AIRB,
            MATURITY_PAIR_SME_AIRB,
            lgd=LGD_PAIR_SME_AIRB,
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _corporate(counterparty_reference: str, revenue: float) -> dict:
    """A GB corporate counterparty row of the given annual revenue."""
    return {
        "counterparty_reference": counterparty_reference,
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": revenue,
    }


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    maturity: date,
    *,
    lgd: float | None = None,
) -> dict:
    """One drawn term loan. ``lgd`` set means an own estimate, so A-IRB."""
    row: dict = {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": maturity,
        "seniority": "senior",
        "has_sufficient_collateral_data": lgd is not None,
    }
    if lgd is not None:
        row["lgd"] = lgd
    return row


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"IRP-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
