"""
RC-12 — a null counterparty ``entity_type`` is no longer silent (CLS013).

``entity_type`` is the single source of the exposure class (PS1/26 Art. 112(2): "An
institution shall assign exposures to the exposure classes listed in Column A of
Table A2 according to the criteria in the corresponding row of Column B"; CRR
Art. 112). A null value matches no row of the class map, so the classifier's
``replace_strict(..., default=OTHER)`` files the exposure under ``other`` at 100% and
discards the obligor's ECAI rating — measured before this change on a CQS 6 rated
corporate: RWA 1,000,000 instead of 1,500,000, with an EMPTY error list. An
unrecognised non-null string already draws DQ006; a null drew nothing.

Orchestrator decision: the fallback class stays ``other`` (changing it is an owner
decision — the right class is unknowable, and the direction of error depends on it:
a CQS 6 corporate is understated, a CQS 1 corporate or an individual overstated).
What changes is that the run now says so: one CLS013 warning naming the counterparty.

End-to-end through ``PipelineOrchestrator.run_with_data``, both regimes (C7).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_NULL_ENTITY_TYPE, ErrorSeverity
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_EMPTY_FACILITY_MAPPINGS = pl.DataFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)
_CP = "RC12_CP"
_LOAN = "RC12_LOAN"


def _run(regime: str, entity_type: str | None) -> tuple[dict[str, Any], list[Any]]:
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": [_CP],
            "counterparty_name": ["RC12 obligor"],
            "entity_type": [entity_type],
            "country_code": ["GB"],
            "default_status": [False],
        },
        schema_overrides={"entity_type": pl.String},
    )
    loans = pl.DataFrame(
        {
            "loan_reference": [_LOAN],
            "product_type": ["term_loan"],
            "book_code": ["CORP"],
            "counterparty_reference": [_CP],
            "value_date": [date(2026, 1, 1)],
            "maturity_date": [date(2030, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1_000_000.0],
            "interest": [0.0],
            "seniority": ["senior"],
        }
    )
    bundle = make_raw_bundle(
        counterparties=counterparties, loans=loans, facility_mappings=_EMPTY_FACILITY_MAPPINGS
    )
    if regime == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 3, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=date(2026, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    row = result.results.collect().filter(pl.col("exposure_reference") == _LOAN).to_dicts()[0]
    return row, list(result.errors)


@pytest.mark.parametrize("regime", ["b31", "crr"])
def test_null_entity_type_raises_one_cls013_naming_the_counterparty(regime: str) -> None:
    row, errors = _run(regime, None)

    cls013 = [e for e in errors if e.code == ERROR_NULL_ENTITY_TYPE]
    assert len(cls013) == 1, f"expected one CLS013, got {[e.code for e in errors]}"
    assert cls013[0].severity == ErrorSeverity.WARNING
    assert _CP in cls013[0].message
    assert cls013[0].field_name == "entity_type"


@pytest.mark.parametrize("regime", ["b31", "crr"])
def test_null_entity_type_fallback_class_and_weight_unchanged(regime: str) -> None:
    """The decision keeps the OTHER / 100% fallback: 1,000,000 x 100%."""
    row, _ = _run(regime, None)

    assert row["exposure_class"] == "other"
    assert row["risk_weight"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)


@pytest.mark.parametrize("regime", ["b31", "crr"])
def test_populated_entity_type_raises_no_cls013(regime: str) -> None:
    """Control: the warning keys on the null, not on the class it lands in."""
    _, errors = _run(regime, "corporate")

    assert [e for e in errors if e.code == ERROR_NULL_ENTITY_TYPE] == []
