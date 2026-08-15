"""
P1.314 (ADDENDUM) — reshaped end-to-end leg P1: the Art. 114(7) EU CGCB funded-
currency limb must be evaluated against the PRE-FX denomination currency, not
the post-FX reporting currency.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/eu_sovereign.funding_currency_expr / denomination_currency_expr;
    consumed by engine/sa/risk_weights.py::_apply_crr_risk_weight_overrides /
    _apply_b31_risk_weight_overrides)

Why this bundle exists (and why the unit helper cannot substitute for it):
``calculate_single_sa_exposure`` (``tests/fixtures/single_exposure.py``) builds
no ``original_currency`` column, so ``denomination_currency_expr`` collapses
to ``pl.col("currency")`` on that frame — a wrong implementation that compares
the funding currency against ``pl.col("currency")`` instead of the pre-FX
denomination is INDISTINGUISHABLE from the correct one on any unit leg. Only a
frame that has actually been through the FX converter (real ``currency`` ==
reporting currency, ``original_currency`` == the true denomination) can
discriminate the two. Reporting currency defaults to GBP
(``CalculationConfig.base_currency``), so both loans below are converted.

Scenario (both rows report in GBP; the FX converter overwrites ``currency``
with GBP and preserves the EUR denomination in ``original_currency`` — exactly
the shape a ``currency``-column comparison cannot see):

    Counterparty CP_P314_DE_SOV: DE sovereign (central govt), external CQS 6
                                  -> cgcb_risk_weights[CQS6] = 1.50 when the
                                  Art. 114(7) 0% extension is denied. CQS 6 is
                                  the furthest rung from 0% on the ladder, so
                                  the leg cannot pass by landing on a
                                  neighbouring branch.

    Two EUR-denominated, GBP-reporting loans to CP_P314_DE_SOV, differing only
    in funding currency:

    | loan                | funding_currency | funded-in-domestic? | RW (post-fix) |
    |---------------------|-------------------|----------------------|---------------|
    | LN_P314_EU_FUNDEUR  | "EUR"             | YES (EUR == EUR)     | 0.00          |
    | LN_P314_EU_FUNDUSD  | "USD"             | NO  (USD != EUR)     | 1.50          |

    LN_P314_EU_FUNDEUR is the SURVIVOR that a ``currency``-column
    implementation gets WRONG post-FX: ``currency`` is GBP after conversion,
    so ``funding.eq(pl.col("currency"))`` compares "EUR" == "GBP" -> False,
    wrongly denying the 0% extension and reporting 1.50 where 0.00 is due.
    LN_P314_EU_FUNDUSD stays 1.50 either way (funding genuinely mismatches the
    domestic currency) and confirms the mover leg cannot mask the mistake.

    Pre-fix (denomination limb only, no funding limb applied at all): BOTH
    loans get the unconditional 0% extension -> RW 0.00, RWA 0.00. Neither row
    moves until the funding limb lands, which is why LN_P314_EU_FUNDUSD is
    still needed alongside the survivor -- see the module docstring on
    ``tests/fixtures/p1_229/p1_229.py`` for the general "one that moves, one
    that stays" pattern (LESSONS B5).

References:
    - CRR Art. 114(7) / PS1/26 Art. 114(1)(b) (cross-references CRR Art.
      114(7), which survives Basel 3.1 unchanged): EU member-state CGCB 0%
      risk weight when denominated AND funded in that state's domestic
      currency.
    - src/rwa_calc/engine/eu_sovereign.py (funding_currency_expr,
      denomination_currency_expr).
    - .claude/state/outputs/P1.314-scenario.md, ADDENDUM "RESHAPED P1".
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_DE_SOV_REF = "CP_P314_DE_SOV"  # DE sovereign, external CQS 6 -> 150% CGCB RW

LOAN_FUNDEUR_REF = "LN_P314_EU_FUNDEUR"  # funded EUR -> survivor (0.00, post-fix)
LOAN_FUNDUSD_REF = "LN_P314_EU_FUNDUSD"  # funded USD -> mover (1.50, post-fix)

VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE = date(2032, 1, 1)

DRAWN_AMOUNT = 10_000_000.0  # EUR, matches the Leg F / F2 EAD in the design doc

CQS_SOVEREIGN = 6  # CP_P314_DE_SOV external rating -> cgcb_risk_weights[CQS6]

LOAN_CURRENCY = "EUR"  # denomination = DE domestic currency (denomination limb passes)

# Expected risk weights (identical under CRR and Basel 3.1 — both override
# chains read the same cgcb_risk_weights pack entry).
EXPECTED_RW_FUNDEUR = 0.00  # funded EUR -> 0% extension applies
EXPECTED_RW_FUNDUSD = 1.50  # funded USD -> 0% extension denied, cgcb_risk_weights[CQS6]


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def create_p314_counterparties() -> pl.DataFrame:
    """Return the single DE sovereign direct-exposure counterparty."""
    rows = [
        {
            "counterparty_reference": CP_DE_SOV_REF,
            "counterparty_name": "P1.314 DE Sovereign (external CQS 6)",
            "entity_type": "sovereign",
            "country_code": "DE",
            "annual_revenue": 0.0,
            "total_assets": 0.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p314_loans() -> pl.DataFrame:
    """Return the two EUR loans to the DE sovereign, differing only in funding_currency."""
    base = {
        "counterparty_reference": CP_DE_SOV_REF,
        "currency": LOAN_CURRENCY,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
    }
    rows = [
        {**base, "loan_reference": LOAN_FUNDEUR_REF, "funding_currency": "EUR"},
        {**base, "loan_reference": LOAN_FUNDUSD_REF, "funding_currency": "USD"},
    ]
    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


def create_p314_ratings() -> pl.DataFrame:
    """Return the external rating: DE sovereign CQS 6."""
    rows = [
        {
            "rating_reference": "RTG_P314_DE_SOV",
            "counterparty_reference": CP_DE_SOV_REF,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "CCC",
            "cqs": CQS_SOVEREIGN,
            "pd": None,
            "rating_date": VALUE_DATE,
            "is_solicited": True,
            "model_id": None,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(RATINGS_SCHEMA))


def create_p314_fx_rates() -> pl.DataFrame:
    """FX rates to the GBP reporting base.

    EUR converts the loan amounts; USD is a funding-currency LABEL only (it
    never appears as a denomination in this bundle) but a rate is supplied
    defensively, matching the P1.229 precedent.
    """
    rows = [
        {"currency_from": "EUR", "currency_to": "GBP", "rate": 0.86},
        {"currency_from": "USD", "currency_to": "GBP", "rate": 0.78},
        {"currency_from": "GBP", "currency_to": "GBP", "rate": 1.0},
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FX_RATES_SCHEMA))


def build_p314_bundle() -> RawDataBundle:
    """Assemble the P1.314 reshaped end-to-end leg P1 RawDataBundle (loan-scoped)."""
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=create_p314_loans().lazy(),
        counterparties=create_p314_counterparties().lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=create_p314_ratings().lazy(),
        fx_rates=create_p314_fx_rates().lazy(),
    )
