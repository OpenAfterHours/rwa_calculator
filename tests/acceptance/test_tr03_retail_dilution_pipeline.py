"""TR-03 through the real pipeline: retail dilution risk takes the Art. 153(1) formula.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> AggregatedResultBundle (IRB rows)

Rule text (verbatim):
    CRR Art. 157(1) (CRR): "Institutions shall calculate the risk-weighted exposure
    amounts for dilution risk of purchased corporate and retail receivables in
    accordance with the formula set out in Article 153(1)."
    PS1/26 Art. 157(1) (Basel 3.1): "An institution shall calculate the
    risk-weighted exposure amounts for dilution risk of purchased corporate and
    retail receivables in accordance with the formula set out in Article 153(1)."

Scenarios (PD 2%, EAD 100,000, residual maturity 1.0y so the Art. 153(1) maturity
adjustment is exactly 1):
    CRR  — the P1.351 fixture (F-IRB retail, supervisory dilution LGD 75%, x1.06):
           retail dilution RWA 169,194.90   (retail curve pre-fix: 102,442.72)
           retail senior   RWA  61,465.63   (unchanged — retail formula)
    B31  — A-IRB retail, own LGD 100% (Art. 164(1)(b) dilution floor at most):
           retail dilution RWA 212,823.78   (retail curve pre-fix: 128,858.76)

Both re-derived with ``tests/oracle/derivations/formulas.py`` (no ``rwa_calc`` import):
R(Art. 153(1)) = 0.164146 vs R(retail other) = 0.094556 at PD 2%.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.p1_351.p1_351 import (
    LOAN_REF_RETAIL_DILUTION,
    LOAN_REF_RETAIL_SENIOR,
    REPORTING_DATE,
    create_p1351_counterparty,
    create_p1351_loans,
    create_p1351_model_permissions,
    create_p1351_rating,
)
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.oracle.derivations import formulas as oracle

_PD = 0.02
_EAD = 100_000.0


def _rows(bundle, config) -> dict[str, dict]:
    df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
    return {r["exposure_reference"]: r for r in df.to_dicts()}


@pytest.fixture(scope="module")
def crr_rows() -> dict[str, dict]:
    bundle = make_raw_bundle(
        counterparties=create_p1351_counterparty(),
        loans=create_p1351_loans(),
        ratings=create_p1351_rating(),
        model_permissions=create_p1351_model_permissions(),
    )
    return _rows(bundle, CalculationConfig.crr(reporting_date=REPORTING_DATE))


@pytest.fixture(scope="module")
def b31_rows() -> dict[str, dict]:
    reporting_date = date(2027, 12, 31)
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP_TR03_RETAIL",
                "counterparty_name": "TR-03 retail receivables pool",
                "entity_type": "individual",
                "country_code": "GB",
                "default_status": False,
                # PS1/26 Art. 123A(1)(b)(ii): managed as part of a retail pool.
                "is_managed_as_retail": True,
            }
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": ref,
                "counterparty_reference": "CP_TR03_RETAIL",
                "currency": "GBP",
                "value_date": date(2027, 1, 1),
                "maturity_date": date(2028, 12, 30),  # 2028 is a leap year: 1.0y
                "drawn_amount": _EAD,
                "interest": 0.0,
                "seniority": "senior",
                "lgd": 1.00,
                "purchased_receivables_subtype": subtype,
            }
            for ref, subtype in (
                ("LN_TR03_B31_DILUTION", "dilution_risk"),
                ("LN_TR03_B31_SENIOR", "senior"),
            )
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )
    ratings = pl.DataFrame(
        [
            {
                "rating_reference": "RTG_TR03",
                "counterparty_reference": "CP_TR03_RETAIL",
                "rating_type": "internal",
                "pd": _PD,
                "rating_date": reporting_date,
                "model_id": "TEST_FULL_IRB",
            }
        ],
        schema_overrides=dtypes_of(RATINGS_SCHEMA),
    )
    bundle = make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        ratings=ratings,
        model_permissions=create_full_irb_model_permissions(),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=reporting_date, permission_mode=PermissionMode.IRB
    )
    return _rows(bundle, config)


class TestCrr:
    def test_retail_dilution_row_takes_the_art_153_1_formula(
        self, crr_rows: dict[str, dict]
    ) -> None:
        row = crr_rows[LOAN_REF_RETAIL_DILUTION]
        r_corp = oracle.correlation_corporate(_PD)
        expected_rw = oracle.irb_risk_weight_corporate(
            pd_value=_PD,
            lgd=0.75,
            maturity=1.0,
            correlation=r_corp,
            scaling_factor=oracle.CRR_IRB_SCALING_FACTOR,
        )

        assert row["exposure_class"] == "retail_other"
        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)
        assert row["correlation"] == pytest.approx(r_corp, abs=1e-12)
        assert row["rwa_final"] == pytest.approx(expected_rw * _EAD, abs=0.01)
        assert row["rwa_final"] == pytest.approx(169_194.90, abs=0.01)

    def test_retail_senior_row_keeps_the_retail_formula(self, crr_rows: dict[str, dict]) -> None:
        row = crr_rows[LOAN_REF_RETAIL_SENIOR]

        assert row["correlation"] == pytest.approx(oracle.correlation_retail(_PD), abs=1e-12)
        assert row["rwa_final"] == pytest.approx(61_465.63, abs=0.01)


class TestBasel31:
    def test_adequacy_rows_are_advanced_irb_retail(self, b31_rows: dict[str, dict]) -> None:
        """The scenario only means something on an A-IRB retail row at LGD 100%."""
        for ref in ("LN_TR03_B31_DILUTION", "LN_TR03_B31_SENIOR"):
            row = b31_rows[ref]
            assert row["approach_applied"] == "advanced_irb"
            assert row["exposure_class"] == "retail_other"
            assert row["lgd_floored"] == pytest.approx(1.0, abs=1e-12)

    def test_retail_dilution_row_takes_the_art_153_1_formula(
        self, b31_rows: dict[str, dict]
    ) -> None:
        row = b31_rows["LN_TR03_B31_DILUTION"]
        r_corp = oracle.correlation_corporate(_PD)
        expected_rw = oracle.irb_risk_weight_corporate(
            pd_value=_PD,
            lgd=1.0,
            maturity=1.0,
            correlation=r_corp,
            scaling_factor=oracle.B31_IRB_SCALING_FACTOR,
        )

        assert row["maturity"] == pytest.approx(1.0, abs=1e-12)
        assert row["correlation"] == pytest.approx(r_corp, abs=1e-12)
        assert row["rwa_pre_floor"] == pytest.approx(expected_rw * _EAD, abs=0.01)
        assert row["rwa_pre_floor"] == pytest.approx(212_823.78, abs=0.01)

    def test_retail_senior_row_keeps_the_retail_formula(self, b31_rows: dict[str, dict]) -> None:
        row = b31_rows["LN_TR03_B31_SENIOR"]
        expected_rw = oracle.irb_risk_weight_retail(
            pd_value=_PD,
            lgd=1.0,
            correlation=oracle.correlation_retail(_PD),
            scaling_factor=oracle.B31_IRB_SCALING_FACTOR,
        )

        assert row["correlation"] == pytest.approx(oracle.correlation_retail(_PD), abs=1e-12)
        assert row["rwa_pre_floor"] == pytest.approx(expected_rw * _EAD, abs=0.01)
