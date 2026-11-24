"""
IRB specialised-lending coverage portfolio — the Basel 3.1 A-IRB specialised-lending
sheet no other registered run reaches.

Pipeline position:
    build_reporting_irb_specialised_lending_bundle() -> RawDataBundle
        -> PipelineOrchestrator -> AggregatedResultBundle -> COREPGenerator

Why it exists (P5.81, LESSONS B5). Basel 3.1 OF 08.01 sheet 0009 ("Corporates -
Specialised Lending (AIRB approach)") was emitted by no registered run: every
specialised-lending leg in the estate had no internal PD and fell to slotting.

Composition — two specialised-lending obligors that differ only in whether they
carry an internal PD, so the PD is what separates the two sheets:

    ref          | obligor                                     | approach | B31 sheet
    -------------|---------------------------------------------|----------|----------
    LN_SL_AIRB   | object finance, internal PD + own LGD       | A-IRB    | 0009
    LN_SL_SLOT   | project finance, strong, no PD, long-dated  | slotting | 0010

The slotting leg is the control (LESSONS B5's two-leg rule): a change that sent the
A-IRB leg to slotting would darken 0009 AND grow 0010, and one that sent every
specialised-lending leg to A-IRB would do the reverse. It matures in 2031, long
under both regimes, so it is on the same C 08.06 / OF 08.06 row in every state of
PS1/26 Art. 153(5)(c)-(d). The short-maturity slotting rows are NOT this book's
job: ``reporting_slotting_maturity_portfolio`` (P1.204) is registered in all three
states of the band — CRR, Basel 3.1 without the Art. 153(5)(d) election and with
it — and owns them.

Sheet 0009 is held ALONE among the non-retail A-IRB sheets: a second one reporting
a maturity would break the Bank's ``boe_b0748`` on a correct return (publisher
issue PI-31) — that pairing lives in ``reporting_irb_pairings_portfolio``.

References:
- CRR Art. 153(1)-(4) / PS1/26 Art. 147A(1)(c): specialised lending under A-IRB
  (object finance is not IPRE / HVCRE, so not slotting-only)
- CRR Art. 153(5) Table 1; PS1/26 Art. 153(5)(c): the slotting control's weight
- PRA PS1/26 Annex II OF 08.01 sheet list (para 76)
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

CP_SL_AIRB: str = "ISL-CP-SL-AIRB"
CP_SL_SLOT: str = "ISL-CP-SL-SLOT"

LN_SL_AIRB: str = "ISL-LN-SL-AIRB"
LN_SL_SLOT: str = "ISL-LN-SL-SLOT"

#: The A-IRB leg's internal PD and own-estimate LGD.
PD_SL_AIRB: float = 0.0150
LGD_SL_AIRB: float = 0.30

#: Drawn amounts, in GBP — distinct, neither a multiple of the other.
DRAWN_SL_AIRB: float = 5_200_000.0
DRAWN_SL_SLOT: float = 4_800_000.0

_VALUE_DATE: date = date(2020, 1, 1)
#: More than 2.5 years out under both regimes (from 2025-12-31 and 2027-06-01).
_MATURITY: date = date(2031, 12, 31)

#: The approach each leg must resolve to: (CRR, Basel 3.1). None diverges.
IRB_SL_EXPECTED_APPROACH: dict[str, tuple[str, str]] = {
    LN_SL_AIRB: ("advanced_irb", "advanced_irb"),
    LN_SL_SLOT: ("slotting", "slotting"),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_irb_specialised_lending_bundle() -> RawDataBundle:
    """Assemble the specialised-lending coverage portfolio as a sealed bundle.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        specialised_lending=_specialised_lending(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One specialised-lending obligor per leg (the category is per obligor)."""
    rows: list[dict] = [
        {"counterparty_reference": ref, "entity_type": "specialised_lending", "country_code": "GB"}
        for ref in (CP_SL_AIRB, CP_SL_SLOT)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """An internal PD for the A-IRB obligor; a model id alone for the slotting one.

    With no internal PD the F-IRB / A-IRB specialised-lending branches are
    unavailable, so the obligor falls to slotting (CRR Art. 153(5)).
    """
    rows: list[dict] = [_internal(CP_SL_AIRB, pd=PD_SL_AIRB), _internal(CP_SL_SLOT, pd=None)]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The two drawn legs. The A-IRB one carries an own-estimate LGD."""
    rows: list[dict] = [
        {**_loan(LN_SL_AIRB, CP_SL_AIRB, DRAWN_SL_AIRB), "lgd": LGD_SL_AIRB},
        _loan(LN_SL_SLOT, CP_SL_SLOT, DRAWN_SL_SLOT),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _specialised_lending() -> pl.DataFrame:
    """The specialised-lending rows: object finance for A-IRB, project finance slotted."""
    return pl.DataFrame(
        [
            _sl_row(CP_SL_AIRB, "object_finance", "strong"),
            _sl_row(CP_SL_SLOT, "project_finance", "strong"),
        ]
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    """One drawn senior term loan, long-dated under both regimes."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": True,
    }


def _sl_row(counterparty_reference: str, sl_type: str, category: str) -> dict:
    """One specialised-lending attribute row (never HVCRE)."""
    return {
        "counterparty_reference": counterparty_reference,
        "sl_type": sl_type,
        "slotting_category": category,
        "is_hvcre": False,
    }


def _internal(counterparty_reference: str, *, pd: float | None) -> dict:
    """Internal rating row: model id always, PD only where given."""
    row: dict = {
        "rating_reference": f"ISL-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
    if pd is not None:
        row["pd"] = pd
    return row
