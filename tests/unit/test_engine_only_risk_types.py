"""CC-19: engine-only risk types on a lending table draw DQ023 and are disregarded.

``CCR_DERIVATIVE`` / ``CCR_SFT`` / ``CCR_DEFAULT_FUND`` tag the rows the
counterparty-credit-risk stages mint. On a loans / contingents / facilities row
they used to be accepted silently (the first two were in the accepted
``risk_type`` domain) and routed the row to the CCR treatment: the SA branch
relabelled it ``standardised_ccr``, the F-IRB maturity took the repo-style
0.5 years, and C 07.00 reported it on its CCR rows — while the exposure value
was still nominal x the residual CCF (review finding CC-19, re-measured by the
verifier: CCF 100% CRR / 50% B31, approach ``standardised_ccr``, no DQ006).

Rule text the fix relies on (quoted, not paraphrased):

- CRR Art. 111(2): "The exposure value of a derivative instrument listed in
  Annex II shall be determined in accordance with Chapter 6 ... The exposure
  value of repurchase transaction, securities or commodities lending or
  borrowing transactions, long settlement transactions and margin lending
  transactions may be determined either in accordance with Chapter 6 ... or
  Chapter 4."
- PS1/26 Art. 111(2): "The exposure value of a derivative instrument listed in
  Annex II of CRR shall be determined in accordance with Chapter 6 of Title II
  of Part Three of CRR and Sections 3 to 5 of Chapter 3 of Counterparty Credit
  Risk (CRR) Part."

So a lending row can never BE one of those exposures; the tag is malformed
input. The engine keeps the row's CCF exactly as before (an explicit but
unrecognised risk type takes the residual and outranks ``obs_product``) and
removes only the CCR routing, so no RWA can fall through the CCF.

Hand calculation (unrated non-SME corporate, SA RW 100% both regimes):
contingent nominal 10,000,000, issued item (``is_obs_commitment`` False):
CRR Annex I 1(k) residual 100% -> EAD = RWA = 10,000,000; PS1/26 Table A1
Row 3 residual 50% -> EAD = RWA = 5,000,000.
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_ENGINE_ONLY_RISK_TYPE,
    ERROR_INVALID_COLUMN_VALUE,
)
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.domain.enums import ErrorSeverity, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.integration.conftest import (
    make_contingent,
    make_counterparty,
    make_facility,
    make_model_permission,
    make_rating,
    make_raw_data_bundle,
)

_REGIMES = ("CRR", "B31")
_NOMINAL = 10_000_000.0
#: Residual CCF of an unrecognised issued-item risk type, per regime.
_RESIDUAL_CCF = {"CRR": 1.0, "B31": 0.5}


def _config(regime: str, **kwargs: Any) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), **kwargs)
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30), **kwargs)


def _bundle(*, risk_type: str | None, irb: bool = False) -> Any:
    facility = make_facility(facility_reference="F1", limit=0.0)
    contingent = make_contingent(
        contingent_reference="C1", nominal_amount=_NOMINAL, risk_type=risk_type
    )
    if not irb:
        return make_raw_data_bundle(
            facilities=[facility], contingents=[contingent], facility_mappings=[]
        )
    return make_raw_data_bundle(
        counterparties=[make_counterparty(annual_revenue=200e6, total_assets=500e6)],
        facilities=[facility],
        contingents=[contingent],
        facility_mappings=[],
        ratings=[make_rating(pd=0.01, model_id="M1")],
        model_permissions=[make_model_permission(model_id="M1")],
    )


@cache
def _run(regime: str, risk_type: str | None, irb: bool = False) -> AggregatedResultBundle:
    config = _config(regime, permission_mode=PermissionMode.IRB) if irb else _config(regime)
    return PipelineOrchestrator().run_with_data(_bundle(risk_type=risk_type, irb=irb), config)


def _contingent_row(result: AggregatedResultBundle) -> dict[str, Any]:
    ledger = result.results.collect().filter(pl.col("exposure_reference") == "C1")
    assert ledger.height == 1, "fixture adequacy: exactly one C1 ledger row"
    return ledger.row(0, named=True)


def _codes(result: AggregatedResultBundle, code: str) -> list[Any]:
    return [e for e in result.errors if e.code == code]


class TestInputGate:
    """The engine-only tags are outside the lending domain and report as DQ023."""

    @pytest.mark.parametrize(
        ("table", "column", "value"),
        [
            ("contingents", "risk_type", "CCR_SFT"),
            ("contingents", "risk_type", "ccr_derivative"),
            ("contingents", "underlying_risk_type", "CCR_DEFAULT_FUND"),
            ("facilities", "risk_type", "CCR_DERIVATIVE"),
        ],
    )
    def test_engine_only_value_is_one_dq023_error(
        self, table: str, column: str, value: str
    ) -> None:
        contingent = make_contingent(contingent_reference="C1")
        facility = make_facility(facility_reference="F1")
        if table == "contingents":
            contingent[column] = value
        else:
            facility[column] = value
        bundle = make_raw_data_bundle(
            facilities=[facility], contingents=[contingent], facility_mappings=[]
        )

        errors = validate_bundle_values(bundle)

        found = [e for e in errors if e.code == ERROR_ENGINE_ONLY_RISK_TYPE]
        assert len(found) == 1
        assert found[0].severity == ErrorSeverity.ERROR
        assert (found[0].field_name, found[0].actual_value) == (column, value)
        assert table in found[0].message
        assert not [
            e for e in errors if e.code == ERROR_INVALID_COLUMN_VALUE and e.field_name == column
        ], "an engine-only tag is reported once, as DQ023, never also as DQ006"

    def test_an_unknown_value_is_still_dq006_not_dq023(self) -> None:
        bundle = make_raw_data_bundle(
            contingents=[make_contingent(contingent_reference="C1", risk_type="XYZ")],
            facility_mappings=[],
        )

        errors = validate_bundle_values(bundle)

        assert [e.actual_value for e in errors if e.code == ERROR_INVALID_COLUMN_VALUE] == ["XYZ"]
        assert not [e for e in errors if e.code == ERROR_ENGINE_ONLY_RISK_TYPE]

    @pytest.mark.parametrize("value", ["FR", "full_risk", "MR_ISSUED", "low_risk", "OC"])
    def test_lending_risk_types_raise_nothing(self, value: str) -> None:
        bundle = make_raw_data_bundle(
            contingents=[make_contingent(contingent_reference="C1", risk_type=value)],
            facility_mappings=[],
        )

        errors = validate_bundle_values(bundle)

        assert not [
            e for e in errors if e.code in {ERROR_ENGINE_ONLY_RISK_TYPE, ERROR_INVALID_COLUMN_VALUE}
        ]


@pytest.mark.parametrize("regime", _REGIMES)
class TestPipelineDisregardsTheTag:
    """End to end: the row keeps its residual CCF and loses the CCR routing."""

    def test_sa_row_is_not_relabelled_standardised_ccr(self, regime: str) -> None:
        row = _contingent_row(_run(regime, "CCR_SFT"))

        assert row["approach_applied"] == "standardised"

    def test_ccf_and_rwa_are_the_unchanged_residual(self, regime: str) -> None:
        # CRR: 10,000,000 x 100% (Annex I 1(k)) x 100% RW = 10,000,000.
        # B31: 10,000,000 x 50% (Table A1 Row 3) x 100% RW = 5,000,000.
        row = _contingent_row(_run(regime, "CCR_SFT"))
        expected = _NOMINAL * _RESIDUAL_CCF[regime]

        assert row["ccf"] == pytest.approx(_RESIDUAL_CCF[regime])
        assert row["risk_weight"] == pytest.approx(1.0), "fixture adequacy: 100% RW"
        assert row["ead_final"] == pytest.approx(expected)
        assert row["rwa_final"] == pytest.approx(expected)

    def test_the_ccf_equals_that_of_any_unrecognised_value(self, regime: str) -> None:
        tagged = _contingent_row(_run(regime, "CCR_SFT"))
        unknown = _contingent_row(_run(regime, "XYZ"))

        assert tagged["ead_final"] == pytest.approx(unknown["ead_final"])

    def test_dq023_reaches_the_result(self, regime: str) -> None:
        found = _codes(_run(regime, "CCR_SFT"), ERROR_ENGINE_ONLY_RISK_TYPE)

        assert [(e.field_name, e.actual_value) for e in found] == [("risk_type", "CCR_SFT")]


class TestIrbMaturityIsNotRepoStyle:
    """CRR F-IRB: a lending row tagged CCR_SFT no longer takes the repo-style M.

    CRR Art. 162(1): F-IRB "shall assign ... 0.5 years to exposures arising from
    repurchase transactions or securities or commodities lending or borrowing
    transactions". A contingent is none of those; the 0.5 came only from the
    CCR_SFT tag (``irb/transforms.py::_repo_style_expr``). After the fix the row
    takes exactly the M of an identical ``FR`` contingent (dates-based here,
    1,279 / 365 = 3.504 years), which is larger, so RWA cannot fall.
    """

    def test_contingent_tagged_ccr_sft_takes_the_lending_maturity(self) -> None:
        tagged = _contingent_row(_run("CRR", "CCR_SFT", irb=True))
        lending = _contingent_row(_run("CRR", "FR", irb=True))

        assert tagged["approach_applied"] == "foundation_irb", "fixture adequacy: F-IRB row"
        assert lending["irb_maturity_m"] > 0.5, "fixture adequacy: lending M is not 0.5"
        assert tagged["irb_maturity_m"] == pytest.approx(lending["irb_maturity_m"])
        assert tagged["rwa_final"] == pytest.approx(lending["rwa_final"])
