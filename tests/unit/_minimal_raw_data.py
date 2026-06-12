"""
Shared minimal RawDataBundle builder for comparison/transitional unit tests.

Provides a single, parameterised minimal portfolio (one facility, one loan, one
corporate counterparty) used by the DualFrameworkRunner and
TransitionalScheduleRunner integration tests. Extracted to remove the duplicated
``_make_minimal_raw_data`` builder that previously lived in both
``test_comparison.py`` and ``test_transitional_schedule.py``.

The only divergence between the two original clones is the loan ``maturity_date``;
it is exposed as a keyword argument so transitional-schedule tests can supply a
later maturity (2033-01-01) that survives the 2027-2030 timeline.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from tests.fixtures.raw_bundle import make_raw_bundle


def make_minimal_raw_data(*, maturity_date: date = date(2028, 1, 1)) -> RawDataBundle:
    """Create a minimal RawDataBundle for runner integration tests."""
    facilities = pl.LazyFrame(
        {
            "facility_reference": ["FAC001"],
            "counterparty_reference": ["CP001"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["BANK"],
            "currency": ["GBP"],
            "facility_limit": [1_000_000.0],
        }
    )

    loans = pl.LazyFrame(
        {
            "loan_reference": ["LN001"],
            "counterparty_reference": ["CP001"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["BANK"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [maturity_date],
            "currency": ["GBP"],
            "drawn_amount": [500_000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["FR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [None],
        }
    )

    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": ["CP001"],
            "counterparty_name": ["Test Corp"],
            "country_of_incorporation": ["GB"],
            "sector": ["CORPORATE"],
            "entity_type": ["corporate"],
            "is_sme": [False],
            "apply_fi_scalar": [True],
            "is_pse": [False],
            "cqs": [2],
            "pd": [0.01],
            "turnover_eur": [100_000_000.0],
        }
    )

    facility_mappings = pl.LazyFrame(
        {
            "facility_reference": ["FAC001"],
            "loan_reference": ["LN001"],
        }
    )

    lending_mappings = pl.LazyFrame(
        {
            "counterparty_reference": ["CP001"],
            "lending_group_id": ["LG001"],
        }
    )

    return make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )
