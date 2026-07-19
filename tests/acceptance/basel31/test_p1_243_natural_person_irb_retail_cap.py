"""
P1.243 acceptance twins — the IRB retail monetary cap conditions the SME limb only.

End-to-end (RawDataBundle -> PipelineOrchestrator) demonstration of
CRR Art. 147(5)(a) / PS1/26 Art. 147(5)(a): a natural person owing more than the
retail cap (EUR 1,000,000 / GBP 880,000) stays in the IRB retail class and is
priced with the retail A-IRB formula, while an SME owing the same amount is held
out of retail (Art. 147(5)(a)(ii) — the cap conditions the SME limb).

Both counterparties carry an internal PD and A-IRB permission for their IRB
class, so approach routing is driven by the exposure class, not permission
scarcity:

    natural person (2,000,000 > cap) -> exposure_class=retail_other, A-IRB
    SME            (2,000,000 > cap) -> exposure_class=corporate_sme, A-IRB

The natural person's retail-other A-IRB risk weight (~0.615 CRR incl. the 1.06
scaling factor; ~0.580 B31) is materially below the corporate weight the buggy
engine assigned when it expelled the individual to CORPORATE, confirming the
number moves in the regulatorily-correct (down) direction.

References:
- CRR Art. 147(5)(a)(i)/(ii); PRA PS1/26 Art. 147(5)(a)(i)/(ii).
- IMPLEMENTATION_PLAN.md: P1.243.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows, first
from tests.fixtures.p1_243.p1_243 import (
    LOAN_NATURAL_PERSON,
    LOAN_SME,
    build_p1_243_raw_bundle,
)

_CRR_DATE = date(2026, 12, 31)
_B31_DATE = date(2027, 6, 30)


def _run(config: CalculationConfig):
    return PipelineOrchestrator().run_with_data(build_p1_243_raw_bundle(), config)


@pytest.fixture(scope="module")
def crr_result():
    return _run(CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=PermissionMode.IRB))


@pytest.fixture(scope="module")
def b31_result():
    return _run(
        CalculationConfig.basel_3_1(reporting_date=_B31_DATE, permission_mode=PermissionMode.IRB)
    )


# =============================================================================
# Natural person over the cap -> retail A-IRB (Art. 147(5)(a)(i), both regimes)
# =============================================================================


class TestNaturalPersonRoutesToRetailIRB:
    def test_crr_natural_person_is_retail_airb(self, crr_result) -> None:
        rows = find_loan_rows(crr_result, LOAN_NATURAL_PERSON)
        assert rows, "natural-person exposure produced no result row"
        assert first(rows, "exposure_class") == ExposureClass.RETAIL_OTHER.value
        assert first(rows, "approach") == ApproachType.AIRB.value

    def test_b31_natural_person_is_retail_airb(self, b31_result) -> None:
        rows = find_loan_rows(b31_result, LOAN_NATURAL_PERSON)
        assert rows, "natural-person exposure produced no result row"
        assert first(rows, "exposure_class") == ExposureClass.RETAIL_OTHER.value
        assert first(rows, "approach") == ApproachType.AIRB.value

    def test_crr_natural_person_retail_rwa_below_corporate(self, crr_result) -> None:
        """The retail A-IRB weight is well below the 100% corporate SA weight."""
        rows = find_loan_rows(crr_result, LOAN_NATURAL_PERSON)
        rw = first(rows, "risk_weight")
        assert rw == pytest.approx(0.6147, abs=1e-3)

    def test_b31_natural_person_retail_rwa_below_corporate(self, b31_result) -> None:
        rows = find_loan_rows(b31_result, LOAN_NATURAL_PERSON)
        rw = first(rows, "risk_weight")
        assert rw == pytest.approx(0.5799, abs=1e-3)


# =============================================================================
# SME over the cap -> corporate (Art. 147(5)(a)(ii), the cap binds the SME limb)
# =============================================================================


class TestSMEOverCapStaysCorporate:
    def test_crr_sme_is_corporate_not_retail(self, crr_result) -> None:
        rows = find_loan_rows(crr_result, LOAN_SME)
        assert rows, "SME exposure produced no result row"
        assert first(rows, "exposure_class") == ExposureClass.CORPORATE_SME.value

    def test_b31_sme_is_corporate_not_retail(self, b31_result) -> None:
        rows = find_loan_rows(b31_result, LOAN_SME)
        assert rows, "SME exposure produced no result row"
        assert first(rows, "exposure_class") == ExposureClass.CORPORATE_SME.value
