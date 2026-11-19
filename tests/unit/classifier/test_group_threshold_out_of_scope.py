"""
Classifier: the retail threshold counts debt owed to the whole reporting group.

On a solo / sub-consolidated run the hierarchy stage carries
``out_of_scope_group_adjusted_exposure`` — the retail-threshold amount the
obligor owes to the reporting group's OTHER entities (RC-07 / RG-02 / RE-12).
The classifier adds it to the run's own ``lending_group_adjusted_exposure`` for
the threshold limb only:

- CRR Art. 123(c): "the total amount owed to the institution and parent
  undertakings and its subsidiaries ... shall not ... exceed EUR 1 million".
- PS1/26 Art. 123A(1)(b)(ii): "the total amount (including defaulted exposures)
  owed to the institution, its parent undertakings, its subsidiaries and
  subsidiaries of its parent undertakings by the obligor ... does not exceed
  GBP 880,000".

The Art. 123A granularity limb (the engine's 0.2% reading of "one of a
significant number of exposures") keeps the run's OWN figure in numerator and
denominator: it measures the reporting entity's retail portfolio. Feeding it the
group-wide figure would let other entities' books dilute the denominator and
pass an obligor the run's own portfolio fails — an RWA-reducing side effect the
group-wide threshold rule does not authorise. ``test_granularity_limb_reads_the_runs_own_books``
pins that.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.classify import ExposureClassifier
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle


def _config(regime: str, *, granularity: bool = False, scoped: bool = True) -> CalculationConfig:
    """A solo (BANK_A individual) run unless ``scoped=False``.

    The classifier never reads the scope itself; the scope only tells the AGG004
    audit that a group increment can exist (an unscoped run skips its collect).
    """
    scope: dict[str, object] = (
        {"reporting_entity": "BANK_A", "reporting_basis": ReportingBasis.INDIVIDUAL}
        if scoped
        else {}
    )
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), **scope)
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), enforce_retail_granularity=granularity, **scope
    )


def _bundle(own: list[float], out_of_scope: list[float | None]):
    """One natural-person obligor per row, each with one personal loan."""
    n = len(own)
    refs = [f"IND{i:04d}" for i in range(n)]
    exposures = pl.DataFrame(
        {
            "exposure_reference": [f"L{i:04d}" for i in range(n)],
            "exposure_type": ["loan"] * n,
            "product_type": ["PERSONAL"] * n,
            "book_code": ["RETAIL"] * n,
            "counterparty_reference": refs,
            "value_date": [date(2025, 1, 1)] * n,
            "maturity_date": [date(2030, 1, 1)] * n,
            "currency": ["GBP"] * n,
            "drawn_amount": own,
            "undrawn_amount": [0.0] * n,
            "nominal_amount": [0.0] * n,
            "residential_collateral_value": [0.0] * n,
            "exposure_for_retail_threshold": own,
            "lending_group_adjusted_exposure": own,
            "out_of_scope_group_adjusted_exposure": out_of_scope,
        },
        schema_overrides={"out_of_scope_group_adjusted_exposure": pl.Float64},
    )
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": refs,
            "entity_type": ["individual"] * n,
            "country_code": ["GB"] * n,
            "is_managed_as_retail": [True] * n,
        }
    )
    return make_resolved_bundle(
        exposures=exposures,
        counterparty_lookup=make_counterparty_lookup(counterparties=counterparties),
        lending_group_totals=pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
    )


def _classify(bundle, config: CalculationConfig) -> tuple[pl.DataFrame, list[str]]:
    result = ExposureClassifier().classify(bundle, config)
    df = result.all_exposures.collect().sort("exposure_reference")
    return df, [e.code for e in result.classification_errors]


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_debt_owed_to_other_group_entities_fails_the_threshold(regime: str) -> None:
    """600,000 here + 600,000 elsewhere in the group = 1,200,000: not retail, AGG004."""
    df, codes = _classify(_bundle([600_000.0], [600_000.0]), _config(regime))

    assert df["qualifies_as_retail"].to_list() == [False]
    assert codes.count(ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES) == 1


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_null_increment_leaves_the_run_figure_alone(regime: str) -> None:
    """Unscoped / whole-group run: the column is null and 600,000 stays retail."""
    df, codes = _classify(_bundle([600_000.0], [None]), _config(regime, scoped=False))

    assert df["qualifies_as_retail"].to_list() == [True]
    assert ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES not in codes


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_no_agg004_when_the_own_books_already_fail(regime: str) -> None:
    """1,200,000 on the run's own books fails regardless of the group: no AGG004."""
    df, codes = _classify(_bundle([1_200_000.0], [100_000.0]), _config(regime))

    assert df["qualifies_as_retail"].to_list() == [False]
    assert ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES not in codes


def test_granularity_limb_reads_the_runs_own_books() -> None:
    """600 obligors of 1,000; one also owes 5,000 elsewhere in the group.

    On the run's own books every obligor is 1/600 = 0.167% of the retail
    portfolio, inside the 0.2% limb, so all 600 qualify. Had the group-wide
    figure fed the granularity limb, the flagged obligor would be
    6,000 / 605,000 = 0.99% and fail it.
    """
    own = [1_000.0] * 600
    out_of_scope: list[float | None] = [None] * 600
    out_of_scope[0] = 5_000.0
    group_basis_share = (own[0] + 5_000.0) / (sum(own) + 5_000.0)
    assert group_basis_share > 0.002, "the group basis must fail the limb or this proves nothing"
    assert own[0] / sum(own) < 0.002, "the own basis must pass the limb or this proves nothing"

    df, _codes = _classify(_bundle(own, out_of_scope), _config("B31", granularity=True))

    assert df["qualifies_as_retail"].all()
