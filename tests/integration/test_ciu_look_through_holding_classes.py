"""
IV-05 through the real pipeline: look-through CIU holdings weighted by class.

Pipeline position:
    RawDataBundle (equity_exposures + ciu_holdings) -> input-domain gate (SA008)
        -> ... -> EquityCalculator._resolve_look_through_rw -> aggregator exit

One look-through CIU per holding class, carrying value 100, each fund holding a
single underlying of value 100, so the fund's look-through weight IS the
holding's weight and RWA = 100 x RW. Pre-fix every row below except the
corporate control returned RW 1.00 / RWA 100 in both regimes (reviewer's
``t_ciu.py``, re-run by the verifier on CRR 2026-06-30 and Basel 3.1
2027-06-30 / 2030-06-30).

Rule text (PS1/26 Appendix 1, quoted in full in
``tests/unit/test_ciu_look_through_holding_classes.py``): Art. 132A(1) weights
"all underlying exposures of the CIU as if they were directly held"; Art. 132(5)
sends a level 2 CIU without look-through data to the fall-back "In any other
scenario"; Art. 132(2) sets the fall-back at 1,250%; Art. 128(1) (Basel 3.1)
weights high-risk items 150%, omitted from UK CRR by SI 2021/1078.

Hand calculation (RWA = 100 x RW):

    holding class        CRR 2026-06-30      Basel 3.1 2030-06-30
    corporate, CQS 5     150  (control)      150  (control)
    high_risk            100  (Art.128 off)  150  (pre-fix 100)
    ciu (nested)         1,250 (pre 100)     1,250 (pre 100)
    securitisation       1,250 (pre 100)     1,250 (pre 100)  + SA008
    subordinated_debt    1,250 (pre 100)     1,250 (pre 100)  + SA008
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CIU_HOLDING_CLASS_UNSUPPORTED
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_FUNDS: dict[str, tuple[str, int | None]] = {
    "F_CORP": ("corporate", 5),
    "F_HR": ("high_risk", None),
    "F_CIU": ("ciu", None),
    "F_SEC": ("securitisation", None),
    "F_SUB": ("subordinated_debt", None),
}

_EXPECTED_RWA: dict[str, dict[str, float]] = {
    "CRR": {
        "F_CORP": 150.0,
        "F_HR": 100.0,
        "F_CIU": 1_250.0,
        "F_SEC": 1_250.0,
        "F_SUB": 1_250.0,
    },
    "BASEL_3_1": {
        "F_CORP": 150.0,
        "F_HR": 150.0,
        "F_CIU": 1_250.0,
        "F_SEC": 1_250.0,
        "F_SUB": 1_250.0,
    },
}

_CONFIGS = {
    "CRR": CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "BASEL_3_1": CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30)),
}

_CACHE: dict[str, tuple[pl.DataFrame, set[str]]] = {}


def _run(framework: str) -> tuple[pl.DataFrame, set[str]]:
    """Run the five funds through the pipeline; return (results, error codes)."""
    if framework in _CACHE:
        return _CACHE[framework]
    funds = list(_FUNDS)
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["FUNDMGR"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [500_000_000.0],
        }
    )
    equity = pl.DataFrame(
        {
            "exposure_reference": [f"EQ_{fund}" for fund in funds],
            "counterparty_reference": ["FUNDMGR"] * len(funds),
            "equity_type": ["ciu"] * len(funds),
            "currency": ["GBP"] * len(funds),
            "carrying_value": [100.0] * len(funds),
            "fair_value": [100.0] * len(funds),
            "ciu_approach": ["look_through"] * len(funds),
            "fund_reference": funds,
        }
    )
    holdings = pl.DataFrame(
        {
            "fund_reference": funds,
            "holding_reference": [f"H_{fund}" for fund in funds],
            "exposure_class": [_FUNDS[fund][0] for fund in funds],
            "cqs": [_FUNDS[fund][1] for fund in funds],
            "holding_value": [100.0] * len(funds),
        },
        schema_overrides={"cqs": pl.Int8},
    )
    bundle = make_raw_bundle(
        counterparties=counterparties, equity_exposures=equity, ciu_holdings=holdings
    )
    result = PipelineOrchestrator().run_with_data(bundle, _CONFIGS[framework])
    assert not [e for e in result.errors if "contract violated" in e.message]
    frame = result.results.collect()
    _CACHE[framework] = (frame, {e.code for e in result.errors})
    return _CACHE[framework]


@pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
@pytest.mark.parametrize("fund", list(_FUNDS))
def test_look_through_rwa_by_holding_class(framework: str, fund: str) -> None:
    # Act
    frame, _ = _run(framework)

    # Assert
    row = frame.filter(pl.col("exposure_reference") == f"EQ_{fund}").row(0, named=True)
    assert row["ead_final"] == pytest.approx(100.0)
    assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA[framework][fund])


@pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
def test_unidentified_holding_class_is_warned(framework: str) -> None:
    # Act
    _, codes = _run(framework)

    # Assert
    assert ERROR_CIU_HOLDING_CLASS_UNSUPPORTED in codes
