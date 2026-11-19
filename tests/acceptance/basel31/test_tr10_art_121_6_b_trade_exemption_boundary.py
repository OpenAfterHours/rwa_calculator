"""TR-10 through the real pipeline: the Art. 121(6)(b) trade exemption is "less than one year".

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> SA risk weights (sovereign_floor.py)

Rule text (PS1/26 Art. 121(6), Basel 3.1, verbatim): "the risk weight assigned to an
exposure to an institution for which a credit assessment by a nominated ECAI is not
available may not be less than the risk weight applicable to exposures to the
central government of the jurisdiction where the institution is incorporated as set
out in Article 114(1) and (2) if: (a) the exposure: (i) is not in the local currency
of the jurisdiction of incorporation of the debtor institution; ... and (b) the
exposure is not a self-liquidating, trade-related contingent item arising from the
movement of goods with an original maturity of less than one year."

Defect (review TR-10, Basel 3.1 only, RWA understated at the boundary): the
exemption was coded ``original_maturity_years <= 1.0``. Original maturity is derived
as days / 365, so a 365-day letter of credit is exactly 1.0 and was exempted.

Scenario: unrated SCRA Grade A bank incorporated in Turkey (sovereign CQS 4 ->
Art. 114(2) 100%, local currency TRY), USD documentary-credit contingents of
1,000,000 flagged as self-liquidating trade, 20% CCF -> EAD 200,000.

Hand calculation:
    365-day LC (original maturity 1.0y): NOT exempt -> floor binds
        RW max(40% SCRA A, 100% sovereign) = 100%, RWA 200,000  (pre-fix 40%: 80,000)
    364-day LC (original maturity 0.9973y): exempt -> SCRA Grade A long-term
        RW 40%, RWA 80,000  (> six months, so no Art. 121(4) Table 5A)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CONTINGENTS_SCHEMA, COUNTERPARTY_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_VALUE_DATE = date(2027, 1, 15)


@pytest.fixture(scope="module")
def rows() -> dict[str, dict]:
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP_TR10_BANK",
                "counterparty_name": "TR-10 unrated foreign bank",
                "entity_type": "bank",
                "country_code": "TR",
                "default_status": False,
                "scra_grade": "A",
                "sovereign_cqs": 4,
                "local_currency": "TRY",
            }
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    contingents = pl.DataFrame(
        [
            {
                "contingent_reference": ref,
                "counterparty_reference": "CP_TR10_BANK",
                "value_date": _VALUE_DATE,
                "maturity_date": maturity_date,
                "currency": "USD",
                "nominal_amount": 1_000_000.0,
                "risk_type": "MLR",
                "is_short_term_trade_lc": True,
            }
            for ref, maturity_date in (
                ("LC_TR10_365D", date(2028, 1, 15)),
                ("LC_TR10_364D", date(2028, 1, 14)),
            )
        ],
        schema_overrides=dtypes_of(CONTINGENTS_SCHEMA),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 31), permission_mode=PermissionMode.STANDARDISED
    )
    bundle = make_raw_bundle(counterparties=counterparties, contingents=contingents)
    df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
    return {r["exposure_reference"]: r for r in df.to_dicts()}


def test_adequacy_both_rows_are_fx_trade_lcs_at_ead_200k(rows: dict[str, dict]) -> None:
    """The boundary only means something on a flagged, FX, unrated-institution row."""
    for ref in ("LC_TR10_365D", "LC_TR10_364D"):
        row = rows[ref]
        assert row["is_short_term_trade_lc"] is True
        assert row["currency"] == "USD"
        assert row["ead_final"] == pytest.approx(200_000.0, abs=0.01)


def test_365_day_trade_lc_is_not_exempt_and_takes_the_sovereign_floor(
    rows: dict[str, dict],
) -> None:
    """Original maturity exactly 1.0y is not "less than one year"."""
    row = rows["LC_TR10_365D"]

    assert row["risk_weight"] == pytest.approx(1.0, abs=1e-12), (
        "a 365-day trade LC escaped the PS1/26 Art. 121(6) sovereign floor through a "
        "'<= 1.0' boundary; Art. 121(6)(b) exempts only 'less than one year'"
    )
    assert row["rwa_final"] == pytest.approx(200_000.0, abs=0.01)


def test_364_day_trade_lc_is_exempt(rows: dict[str, dict]) -> None:
    """Control: one day shorter is inside the exemption; SCRA Grade A 40% stands."""
    row = rows["LC_TR10_364D"]

    assert row["risk_weight"] == pytest.approx(0.40, abs=1e-12)
    assert row["rwa_final"] == pytest.approx(80_000.0, abs=0.01)
