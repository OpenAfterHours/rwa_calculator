"""C 07.00 resolves what to split only when a row will actually be split.

``rw_parts.summed_columns`` refuses a spec holding a binding a split would change
(a Count, a Mean, a weighted average, a ratio, a prior-period read). ``c07_plans``
calls it only after ``rw_parts.has_two_part_rows`` says some row will be split, so
a non-Sum C 07.00 binding cannot stop C 07.00 on a CRR frame (no loan-split
carriers) or on a Basel 3.1 frame with nothing to split — only on a frame where
the split would corrupt that cell.

No C 07.00 binding is non-Sum today, so nothing else in the suite exercises the
order: moving ``summed_columns(spec)`` back above the gate leaves every other test
green. These tests add a Count cell to the real spec and check both sides of the
gate; the second side is the adequacy check that the stub reaches
``summed_columns`` at all.

References:
- src/rwa_calc/reporting/corep/c07.py::c07_plans
- src/rwa_calc/reporting/kernel/rw_parts.py::has_two_part_rows / summed_columns
- PS1/26 Art. 124F(1); Annex II OF 07.00 rows 0140-0280 (p.94)
"""

from __future__ import annotations

import dataclasses
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    LOAN_SPLIT_CARRIERS,
    LOAN_SPLIT_RESIDUAL_RW_COL,
    LOAN_SPLIT_SECURED_RW_COL,
    LOAN_SPLIT_SECURED_SHARE_COL,
)
from rwa_calc.reporting.cellspec import CellSpec, Count, TemplateSpec
from rwa_calc.reporting.corep import c07
from tests.fixtures.recon_ledger import with_reporting_ledger

#: A natural-person mortgage at 60% LTV: Art. 124F(1) 20% up to 55% of the
#: property value, the Art. 124L(1)(a) 75% on the rest.
_SHARE = 0.55 / 0.60
_SECURED_RW = 0.20
_RESIDUAL_RW = 0.75
_BLEND = _SECURED_RW * _SHARE + _RESIDUAL_RW * (1.0 - _SHARE)
_EAD = 400_000.0


def _leg(reference: str, exposure_class: str, risk_weight: float, **carriers: Any) -> dict:
    return {
        "exposure_reference": reference,
        "approach_applied": "standardised",
        "exposure_type": "loan",
        "exposure_class": exposure_class,
        "exposure_class_applied": exposure_class,
        "is_defaulted": False,
        "risk_weight": risk_weight,
        "drawn_amount": _EAD,
        "ead_final": _EAD,
        "rwa_final": _EAD * risk_weight,
        **carriers,
    }


def _carriers() -> dict[str, float]:
    return {
        LOAN_SPLIT_SECURED_SHARE_COL: _SHARE,
        LOAN_SPLIT_SECURED_RW_COL: _SECURED_RW,
        LOAN_SPLIT_RESIDUAL_RW_COL: _RESIDUAL_RW,
    }


def _frame(*legs: dict) -> pl.LazyFrame:
    return with_reporting_ledger(pl.LazyFrame(list(legs)))


#: (framework, frame) pairs on which no row is two-part.
_NOTHING_TO_SPLIT = {
    "crr-no-carriers": ("CRR", lambda: _frame(_leg("CORP", "corporate", 1.0))),
    "b31-no-carriers": ("BASEL_3_1", lambda: _frame(_leg("CORP", "corporate", 1.0))),
    "b31-stale-carriers": (
        "BASEL_3_1",
        # Art. 127 re-weighted the row to 100% after the dispatcher recorded the parts.
        lambda: _frame(_leg("RRE", "residential_mortgage", 1.0, **_carriers())),
    ),
}


@pytest.fixture
def spec_with_a_count_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real C 07.00 spec plus one Count cell, which ``summed_columns`` refuses."""
    real_build_spec = c07._build_spec

    def build_spec(*args: Any, **kwargs: Any) -> TemplateSpec:
        spec = real_build_spec(*args, **kwargs)
        cells = {**spec.cells, ("0010", "9999"): CellSpec(binding=Count("ead_final"))}
        return dataclasses.replace(spec, cells=cells)

    monkeypatch.setattr(c07, "_build_spec", build_spec)


@pytest.mark.usefixtures("spec_with_a_count_cell")
@pytest.mark.parametrize("case", sorted(_NOTHING_TO_SPLIT))
def test_a_frame_with_nothing_to_split_never_resolves_the_summed_columns(case: str) -> None:
    # Arrange
    framework, build = _NOTHING_TO_SPLIT[case]
    results = build()
    cols = set(results.collect_schema().names())
    errors: list[str] = []

    # Act
    plans = c07.c07_plans(results, cols, framework, errors)

    # Assert
    assert plans, f"{case}: no C 07.00 sheet planned ({errors})"


@pytest.mark.usefixtures("spec_with_a_count_cell")
def test_a_frame_with_a_two_part_row_does_resolve_them() -> None:
    """Adequacy: the stub reaches ``summed_columns`` once a row is split, and it refuses."""
    # Arrange
    results = _frame(_leg("RRE", "residential_mortgage", _BLEND, **_carriers()))
    cols = set(results.collect_schema().names())
    assert set(LOAN_SPLIT_CARRIERS) <= cols

    # Act / Assert
    with pytest.raises(ValueError, match="Count binding would change"):
        c07.c07_plans(results, cols, "BASEL_3_1", [])
