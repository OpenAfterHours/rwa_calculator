"""
Contract tests: the Basel 3.1 loan-split carriers survive every seal to the reporting ledger.

``engine/sa/b31_risk_weight_tables.py::with_b31_loan_split_parts`` writes, beside
the one blended weight it prices a PS1/26 Art. 124F(1) / 124H(1) exposure at, the
secured share and the two part weights:

- ``sa_loan_split_secured_share``
- ``sa_loan_split_secured_rw``
- ``sa_loan_split_residual_rw``

OF 07.00 reports such an exposure "in two parts, against the risk weight applied
to the portion up to 55% of the value of the property, and against the portion
above 55% of the value of the property" (PS1/26 Annex II p.94), and only the
engine knows the residual part's Art. 124L counterparty weight. A column an edge
does not declare is stripped by its seal with no error, so without these
declarations the template would silently report the blended weight again.

The carriers are produced by the SA risk-weight step, which also runs on the IRB
rows of an output-floor run (their SA-equivalent weight), so they are declared on
every calculator branch edge and on the aggregator exit, all three CONDITIONAL
(``required=False, inject=False``): a CRR run never produces them.

References:
- PS1/26 Art. 124F, 124H, 124L; Annex II OF 07.00 rows 0140-0280 (p.94)
- tests/contracts/test_equity_transitional_edge.py (the shape this mirrors)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.reporting_portfolio import LN_RRE, build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CALC_BRANCH_EDGES
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_CARRIERS: tuple[str, ...] = (
    "sa_loan_split_secured_share",
    "sa_loan_split_secured_rw",
    "sa_loan_split_residual_rw",
)
_EDGES = {
    "aggregator_exit": AGGREGATOR_EXIT_EDGE,
    **{name: CALC_BRANCH_EDGES[name] for name in ("sa_branch", "irb_branch")},
}


@pytest.mark.parametrize("edge_name", list(_EDGES))
@pytest.mark.parametrize("column", _CARRIERS)
def test_the_edge_declares_the_carrier_as_conditional(edge_name: str, column: str) -> None:
    edge = _EDGES[edge_name]
    assert column in edge.columns, f"{column} is not declared on {edge_name}"
    declared = edge.columns[column]

    assert declared.dtype == pl.Float64()
    assert declared.required is False
    assert declared.inject is False
    assert declared.null_meaning


@pytest.fixture(scope="module")
def sealed_b31() -> pl.DataFrame:
    """The rich reporting book, Basel 3.1, as the golden gate runs it."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )
    return PipelineOrchestrator().run_with_data(build_reporting_bundle(), config).results.collect()


def test_the_carriers_survive_the_seal_on_a_basel_3_1_run(sealed_b31: pl.DataFrame) -> None:
    missing = set(_CARRIERS) - set(sealed_b31.columns)

    assert not missing, f"stripped by a seal: {sorted(missing)}"


def test_the_loan_past_the_cap_carries_its_parts(sealed_b31: pl.DataFrame) -> None:
    """RP-LN-RRE: 400,000 at 60% LTV to a natural person — 0.55 / 0.60 at 20%, the rest at 75%."""
    loan = sealed_b31.filter(pl.col("exposure_reference") == LN_RRE).row(0, named=True)

    assert loan["sa_loan_split_secured_share"] == pytest.approx(0.55 / 0.60)
    assert loan["sa_loan_split_secured_rw"] == pytest.approx(0.20)
    assert loan["sa_loan_split_residual_rw"] == pytest.approx(0.75)


def test_every_standardised_carrier_reproduces_its_rows_weight(sealed_b31: pl.DataFrame) -> None:
    """Where a standardised row carries the parts, they are its weight — nowhere else."""
    standardised = sealed_b31.filter(
        (pl.col("approach_applied") == "standardised")
        & pl.col("sa_loan_split_secured_share").is_not_null()
    )
    assert standardised.height >= 1, "no standardised row carries the parts: vacuous"

    blend = pl.col("sa_loan_split_secured_rw") * pl.col("sa_loan_split_secured_share") + pl.col(
        "sa_loan_split_residual_rw"
    ) * (1.0 - pl.col("sa_loan_split_secured_share"))
    off = standardised.filter((blend - pl.col("risk_weight")).abs() > 1e-12)

    assert off.is_empty(), off.select("exposure_reference", "risk_weight", *_CARRIERS)


def test_the_carriers_are_not_produced_on_a_crr_run() -> None:
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)

    present = set(_CARRIERS) & set(result.results.collect_schema().names())

    assert not present, f"produced on a CRR run: {sorted(present)}"
