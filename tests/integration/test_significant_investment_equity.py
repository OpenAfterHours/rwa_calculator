"""
IV-06 through the real pipeline: a CRR significant investment takes 250%.

Pipeline position:
    RawDataBundle (equity_exposures) -> ... -> EquityCalculator -> aggregator exit

Rule text (verbatim, onshored UK CRR):

- Art. 133(2): "Equity exposures shall be assigned a risk weight of 100 %,
  unless they are required to be deducted in accordance with Part Two, assigned
  a 250 % risk weight in accordance with Article 48(4), assigned a 1 250 % risk
  weight in accordance with Article 89(3) or treated as high risk items in
  accordance with Article 128."
- Art. 155(1): "Institutions shall determine their risk-weighted exposure
  amounts for equity exposures, excluding those deducted in accordance with
  Part Two or subject to a 250 % risk weight in accordance with Article 48, in
  accordance with the approaches set out in paragraphs 2, 3 and 4 of this
  Article."

So the 250% overrides the SA 100% (RWA-increasing) and the IRB simple 290% /
370% and the PD/LGD K formula (RWA-REDUCING on those paths -- LESSONS A2; the
rule text above is what licenses it).

Hand calculation (carrying value = EAD = 100, institution counterparty):

    leg                              CRR SA     CRR IRB simple   CRR PD/LGD   B31 2030
    SIG  listed, exchange-traded     250 (100)  250 (290)        250 (287.8)  250 (250)
    PLAIN listed, exchange-traded    100        290              287.8        250
    SIG_OTHER  other, unlisted       250 (100)  250 (370)        250 (418.8)  250 (250)

(pre-fix values in brackets). Basel 3.1 is a NON-MOVING control and its SIG legs
CANNOT be reddened by this change (LESSONS C7 finding, recorded rather than
dropped): its Art. 133(3) 250% for standard-risk equity already equals the
Art. 48(4) 250%, so even the CRR significant-investment branch leaking into the
Basel 3.1 chain would leave them at 250 (PS1/26 Art. 133(6)(c) / higher-risk
interplay is P1.393, not changed here). What the Basel 3.1 run does detect is the
whole CRR chain leaking into it: PLAIN would fall from 250 to 100.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_IRB = CalculationConfig.crr(reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB)
_CONFIGS: dict[str, CalculationConfig] = {
    "crr_sa": CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "crr_irb_simple": _IRB,
    "crr_pd_lgd": dataclasses.replace(_IRB, equity_pd_lgd=True),
    "b31": CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30)),
}

#: (expected RWA, expected sealed equity_method) per leg per run.
_EXPECTED: dict[str, dict[str, tuple[float, str]]] = {
    "crr_sa": {"SIG": (250.0, "sa"), "PLAIN": (100.0, "sa"), "SIG_OTHER": (250.0, "sa")},
    "crr_irb_simple": {
        "SIG": (250.0, "sa"),
        "PLAIN": (290.0, "irb_simple"),
        "SIG_OTHER": (250.0, "sa"),
    },
    "crr_pd_lgd": {"SIG": (250.0, "sa"), "SIG_OTHER": (250.0, "sa")},
    "b31": {"SIG": (250.0, "sa"), "PLAIN": (250.0, "sa"), "SIG_OTHER": (250.0, "sa")},
}

_CACHE: dict[str, pl.DataFrame] = {}


def _run(run: str) -> pl.DataFrame:
    if run in _CACHE:
        return _CACHE[run]
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["BANKX"],
            "entity_type": ["institution"],
            "country_code": ["GB"],
        }
    )
    equity = pl.DataFrame(
        {
            "exposure_reference": ["SIG", "PLAIN", "SIG_OTHER"],
            "counterparty_reference": ["BANKX"] * 3,
            "equity_type": ["listed", "listed", "other"],
            "currency": ["GBP"] * 3,
            "carrying_value": [100.0] * 3,
            "fair_value": [100.0] * 3,
            "is_exchange_traded": [True, True, False],
            "is_significant_investment": [True, False, True],
        }
    )
    result = PipelineOrchestrator().run_with_data(
        make_raw_bundle(counterparties=counterparties, equity_exposures=equity), _CONFIGS[run]
    )
    assert not [e for e in result.errors if "contract violated" in e.message]
    _CACHE[run] = result.results.collect()
    return _CACHE[run]


@pytest.mark.parametrize(
    ("run", "leg"), [(run, leg) for run, legs in _EXPECTED.items() for leg in legs]
)
def test_significant_investment_rwa_and_method(run: str, leg: str) -> None:
    # Act
    frame = _run(run)

    # Assert
    row = frame.filter(pl.col("exposure_reference") == leg).row(0, named=True)
    expected_rwa, expected_method = _EXPECTED[run][leg]
    assert row["ead_final"] == pytest.approx(100.0)
    assert row["rwa_final"] == pytest.approx(expected_rwa)
    assert row["equity_method"] == expected_method


def test_pd_lgd_significant_leg_keeps_the_equity_class() -> None:
    """The PD/LGD path stamps CORPORATE for its K formula; a 250% leg is still equity."""
    # Act
    frame = _run("crr_pd_lgd")

    # Assert
    row = frame.filter(pl.col("exposure_reference") == "SIG").row(0, named=True)
    plain = frame.filter(pl.col("exposure_reference") == "PLAIN").row(0, named=True)
    assert plain["equity_method"] == "pd_lgd", "control must take the PD/LGD approach"
    assert row["exposure_class"] == "equity"
    assert row["expected_loss"] is None
