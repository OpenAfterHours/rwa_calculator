"""
P1.244 acceptance twins — the Art. 147(5A)(a)-(b) QRRE assignment gates end-to-end.

End-to-end (RawDataBundle -> PipelineOrchestrator) demonstration of
CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b): a revolving retail credit
line to an individual is admitted to the qualifying revolving retail exposures
(QRRE) sub-class ONLY when it is unsecured and — to the extent undrawn —
unconditionally cancellable. The gate survives the full pipeline (loader ->
hierarchy -> classifier -> ... -> aggregator):

    unsecured, LR (unconditionally cancellable) -> RETAIL_QRRE  (control)
    secured (is_secured=True)                    -> RETAIL_OTHER (unsecured gate)
    undrawn, MR (not unconditionally cancellable)-> RETAIL_OTHER (cancellable gate)

The same conditions apply under CRR Art. 154(4), so the CRR twin classifies
identically — the gates are NOT regime-Featured (only the (c) aggregate-nominal
limit value differs). Demotion to RETAIL_OTHER is the conservative direction:
QRRE's fixed 0.04 correlation is below the retail-other correlation at the low
PDs typical of performing revolving retail, so leaving a secured or
non-cancellable line as QRRE would understate IRB RWA.

References:
- CRR Art. 154(4)(a)-(c); PRA PS1/26 Art. 147(5A)(a)-(c).
- IMPLEMENTATION_PLAN.md: P1.244.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows, first
from tests.fixtures.p1_244.p1_244 import (
    EXP_CONTROL,
    EXP_NOT_CANCELLABLE,
    EXP_SECURED,
    build_p1_244_raw_bundle,
)

_CRR_DATE = date(2026, 12, 31)
_B31_DATE = date(2027, 6, 30)

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value


def _run(config: CalculationConfig):
    return PipelineOrchestrator().run_with_data(build_p1_244_raw_bundle(), config)


@pytest.fixture(scope="module")
def crr_result():
    return _run(CalculationConfig.crr(reporting_date=_CRR_DATE))


@pytest.fixture(scope="module")
def b31_result():
    return _run(CalculationConfig.basel_3_1(reporting_date=_B31_DATE))


def _class(result, exposure_ref: str) -> str:
    rows = find_loan_rows(result, exposure_ref)
    assert rows, f"no result row for {exposure_ref!r}"
    return first(rows, "exposure_class")


# =============================================================================
# Basel 3.1 twin — the gates apply end-to-end
# =============================================================================


class TestB31QRREGatesEndToEnd:
    def test_b31_unsecured_control_is_qrre(self, b31_result) -> None:
        assert _class(b31_result, EXP_CONTROL) == _QRRE

    def test_b31_secured_revolving_retail_demoted_to_retail_other(self, b31_result) -> None:
        assert _class(b31_result, EXP_SECURED) == _RETAIL_OTHER

    def test_b31_non_cancellable_undrawn_demoted_to_retail_other(self, b31_result) -> None:
        assert _class(b31_result, EXP_NOT_CANCELLABLE) == _RETAIL_OTHER


# =============================================================================
# CRR control — QRRE exists under Art. 154(4) and the same gates apply
# =============================================================================


class TestCRRQRREGatesEndToEnd:
    def test_crr_unsecured_control_is_qrre(self, crr_result) -> None:
        assert _class(crr_result, EXP_CONTROL) == _QRRE

    def test_crr_secured_revolving_retail_demoted_to_retail_other(self, crr_result) -> None:
        assert _class(crr_result, EXP_SECURED) == _RETAIL_OTHER

    def test_crr_non_cancellable_undrawn_demoted_to_retail_other(self, crr_result) -> None:
        assert _class(crr_result, EXP_NOT_CANCELLABLE) == _RETAIL_OTHER
