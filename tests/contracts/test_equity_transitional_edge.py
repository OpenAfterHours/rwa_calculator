"""
Contract tests: the three equity-transitional carriers are sealed on the aggregator exit.

``engine/equity/calculator.py`` writes ``equity_transitional_approach``,
``equity_higher_risk`` and ``risk_weight_pre_equity_transitional`` on a leg
whose weight PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.2 / 4.3
set, and typed nulls everywhere else, under Basel 3.1 only. OF 07.00 needs all
three: the risk-weight row is the Article 133 weight the rules replaced (PS1/26
Annex II p.95: "reported against the risk weights set out in Article 133 [...]
disregarding the transitional provisions") and memorandum rows 0371-0374 key the
label and the higher-risk flag. A column the seal does not declare is stripped
by its ``select``, so without these declarations every one of those rows
reported null for the template's whole life with no error.

Like ``equity_method`` / ``ciu_approach``, the carriers are CONDITIONAL
(``inject=False``): an equity-free or CRR run never produces them, and injecting
them would add a node over the eager-backed seal. They are equity-calculator
output, so they belong on no SA / IRB / slotting branch edge.

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.3
- PS1/26 Art. 133(3)-(4); Annex II OF 07.00 rows 0250 / 0261 / 0371-0374
- tests/contracts/test_r6_equity_method_edge.py (the shape this mirrors)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_equity_transitional_portfolio import (
    ALL_EQUITY_REFERENCES,
    TRANSITIONAL_REFERENCES,
    build_reporting_equity_transitional_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CALC_BRANCH_EDGES
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_CARRIERS: dict[str, pl.DataType] = {
    "equity_transitional_approach": pl.String(),
    "equity_higher_risk": pl.Boolean(),
    "risk_weight_pre_equity_transitional": pl.Float64(),
}


@pytest.mark.parametrize(("column", "dtype"), list(_CARRIERS.items()))
def test_aggregator_exit_declares_the_carrier_as_conditional(
    column: str, dtype: pl.DataType
) -> None:
    assert column in AGGREGATOR_EXIT_EDGE.columns, f"{column} is not sealed on the exit"
    declared = AGGREGATOR_EXIT_EDGE.columns[column]
    assert declared.dtype == dtype
    assert declared.required is False
    assert declared.inject is False


@pytest.mark.parametrize("column", list(_CARRIERS))
def test_the_carrier_is_on_no_calculator_branch_edge(column: str) -> None:
    for branch in ("sa_branch", "irb_branch", "slotting_branch"):
        assert column not in CALC_BRANCH_EDGES[branch].columns


@pytest.fixture(scope="module")
def sealed_results() -> pl.DataFrame:
    """The registered standardised-firm equity book, Basel 3.1, 2027-06-01."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )
    result = PipelineOrchestrator().run_with_data(
        build_reporting_equity_transitional_bundle(), config
    )
    return result.results.collect()


def test_the_carriers_survive_the_seal_on_a_basel_3_1_equity_run(
    sealed_results: pl.DataFrame,
) -> None:
    missing = set(_CARRIERS) - set(sealed_results.columns)

    assert not missing, f"stripped by the aggregator-exit seal: {sorted(missing)}"


def test_the_carriers_are_set_on_the_transitional_legs_and_null_elsewhere(
    sealed_results: pl.DataFrame,
) -> None:
    """Set on the two legs whose weight rule 4.2 / 4.3 assigned; null on every other row.

    Adequacy first: the book holds both kinds of equity leg, or the null half is vacuous.
    """
    references = set(sealed_results["exposure_reference"].to_list())
    assert set(ALL_EQUITY_REFERENCES) <= references
    assert set(TRANSITIONAL_REFERENCES) < set(ALL_EQUITY_REFERENCES)

    labelled = sealed_results.filter(pl.col("equity_transitional_approach").is_not_null())

    assert sorted(labelled["exposure_reference"].to_list()) == sorted(TRANSITIONAL_REFERENCES)
    assert labelled["risk_weight_pre_equity_transitional"].null_count() == 0
    unlabelled = sealed_results.filter(pl.col("equity_transitional_approach").is_null())
    assert unlabelled["equity_higher_risk"].null_count() == unlabelled.height
    assert unlabelled["risk_weight_pre_equity_transitional"].null_count() == unlabelled.height


def test_the_carriers_are_not_injected_on_a_crr_run() -> None:
    """CRR has no ``equity_transitional`` Feature, so the calculator emits none of them."""
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
    )
    result = PipelineOrchestrator().run_with_data(
        build_reporting_equity_transitional_bundle(), config
    )

    present = set(_CARRIERS) & set(result.results.collect_schema().names())

    assert not present, f"injected on a CRR run: {sorted(present)}"
