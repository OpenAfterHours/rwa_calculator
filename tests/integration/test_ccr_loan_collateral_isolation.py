"""
Reviews CL-04 / CC-07: loan-table collateral never reduces a CCR exposure value.

Pipeline position:
    RawDataBundle (CCR-A1 golden: one 10y GBP IR swap, netting set NS_001 at
    CP_001) -> CCR stage (synthetic ``ccr__NS_001`` row, SA-CCR EAD) ->
    CRMProcessor (loan-table collateral pools) -> SA calculator

Why this matters:
    The SA-CCR row flows through the CRM stage like a loan, and the
    counterparty-level collateral pool shared itself pro rata over every row of
    the counterparty, the derivative included. A 10,000,000 cash pledge in the
    LOAN collateral table at CP_001 took the netting set's EAD from 5,480,017.52
    to 0 under CRR (5,044,928.35 to 0 under Basel 3.1), on top of the SA-CCR
    calculation that already takes the netting set's own collateral into
    account. A 3,000,000 pledge shared with a 1,000,000 loan was split
    2,537,038 / 462,962 (CRR), stranding most of it on a row it cannot reduce.

Rule (quoted, verbatim):
    CRR Art. 223(5A): "For the purposes of the calculation under paragraph 5, in
    the case of OTC derivative transactions, institutions using the methods laid
    down in Sections 3, 4 and 5 of Chapter 3 of the Counterparty Credit Risk
    (CRR) Part of the PRA Rulebook shall take into account the risk-mitigating
    effects of collateral in accordance with the provisions laid down in
    Sections 3, 4 and 5 of Chapter 3 of the Counterparty Credit Risk (CRR) Part
    of the PRA Rulebook, as applicable." PS1/26 Art. 191A(4): Articles 192 to
    239 apply to "an institution taking into account funded credit protection
    covering an exposure arising from a derivative instrument listed in Annex
    II of CRR ... solely to the extent provisions elsewhere in this PRA Rulebook
    or CRR cross-refer to such article. Absent such cross-reference, such
    articles shall not apply".

Expected (both regimes):
    - counterparty-level pledge, no lending at CP_001: the netting set keeps its
      SA-CCR EAD exactly (CRR 5,480,017.52 / Basel 3.1 5,044,928.35); one CRM025.
    - a 1,000,000 loan beside it and a 3,000,000 counterparty-level cash pledge:
      the loan takes the whole pool (E* = max(0, 1,000,000 - 3,000,000) = 0;
      pre-fix 537,038.29 CRR / 503,716.20 Basel 3.1, measured), the netting set
      is unchanged, no CRM025.
    - a direct pledge on ``ccr__NS_001`` reduces nothing; one CRM025.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr import golden_ccr_a1 as golden
from tests.fixtures.raw_bundle import make_raw_bundle

_CONFIGS = {
    "crr": CalculationConfig.crr(reporting_date=date(2026, 1, 15)),
    "b31": CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 15)),
}
#: The CCR-A1 netting set's SA-CCR exposure value, as the golden banks it.
_SA_CCR_EAD = {"crr": 5_480_017.518819188, "b31": 5_044_928.350531201}
_NETTING_SET_ROW = "ccr__NS_001"


def _run(
    regime: str, *, collateral: list[dict] | None = None, loans: list[dict] | None = None
) -> tuple[pl.DataFrame, list[CalculationError]]:
    frames: dict[str, object] = {
        "counterparties": golden._build_cp_001_counterparty(),
        "facilities": golden._build_empty_facilities(),
        "loans": golden._build_empty_loans(),
        "facility_mappings": golden._build_empty_facility_mappings(),
        "lending_mappings": golden._build_empty_lending_mappings(),
        "ratings": golden._build_cp_001_rating(),
        "ccr": golden._build_ccr_a1_raw_ccr_bundle(),
    }
    if loans is not None:
        frames["loans"] = pl.DataFrame(
            [
                {
                    "counterparty_reference": "CP_001",
                    "product_type": "TERM_LOAN",
                    "book_code": "BANK",
                    "value_date": date(2025, 1, 1),
                    "maturity_date": date(2030, 1, 1),
                    "currency": "GBP",
                    "seniority": "senior",
                    "risk_type": "FR",
                    "interest": 0.0,
                    **row,
                }
                for row in loans
            ]
        )
    if collateral is not None:
        frames["collateral"] = pl.DataFrame(
            [
                {
                    "collateral_type": "cash",
                    "currency": "GBP",
                    "is_eligible_financial_collateral": True,
                    **row,
                }
                for row in collateral
            ]
        )
    result = PipelineOrchestrator().run_with_data(make_raw_bundle(**frames), _CONFIGS[regime])
    return result.results.collect(), list(result.errors)


def _ead(results: pl.DataFrame, reference: str) -> float:
    picked = results.filter(pl.col("exposure_reference") == reference)
    assert picked.height == 1, f"expected one row for {reference}"
    return picked["ead_final"][0]


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_counterparty_pool_with_no_lending_leaves_the_netting_set_whole(regime: str) -> None:
    # Arrange: the adequacy of the scenario — without the pledge the row carries
    # its banked SA-CCR EAD, so "unchanged" below is a real comparison.
    baseline, _ = _run(regime)
    assert _ead(baseline, _NETTING_SET_ROW) == pytest.approx(_SA_CCR_EAD[regime], rel=1e-12)

    # Act
    results, errors = _run(
        regime,
        collateral=[
            {
                "collateral_reference": "LOANCOLL1",
                "market_value": 10_000_000.0,
                "beneficiary_type": "counterparty",
                "beneficiary_reference": "CP_001",
            }
        ],
    )

    # Assert: pre-fix 0.0 in both regimes.
    assert _ead(results, _NETTING_SET_ROW) == pytest.approx(_SA_CCR_EAD[regime], rel=1e-12)
    records = [e for e in errors if e.code == "CRM025"]
    assert len(records) == 1
    assert "LOANCOLL1" in records[0].message


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_counterparty_pool_goes_wholly_to_the_lending_rows(regime: str) -> None:
    # Act
    results, errors = _run(
        regime,
        loans=[{"loan_reference": "LN1", "drawn_amount": 1_000_000.0}],
        collateral=[
            {
                "collateral_reference": "LOANCOLL1",
                "market_value": 3_000_000.0,
                "beneficiary_type": "counterparty",
                "beneficiary_reference": "CP_001",
            }
        ],
    )

    # Assert: the loan's E* = max(0, 1,000,000 - 3,000,000) = 0 (pre-fix it got
    # only 1,000,000 / (1,000,000 + SA-CCR EAD) of the pool); derivative unchanged.
    assert _ead(results, "LN1") == pytest.approx(0.0, abs=1e-6)
    assert _ead(results, _NETTING_SET_ROW) == pytest.approx(_SA_CCR_EAD[regime], rel=1e-12)
    assert "CRM025" not in {e.code for e in errors}


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_direct_pledge_on_the_netting_set_reduces_nothing(regime: str) -> None:
    # Act
    results, errors = _run(
        regime,
        collateral=[
            {
                "collateral_reference": "DIRECT1",
                "market_value": 2_000_000.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": _NETTING_SET_ROW,
            }
        ],
    )

    # Assert
    assert _ead(results, _NETTING_SET_ROW) == pytest.approx(_SA_CCR_EAD[regime], rel=1e-12)
    assert "CRM025" in {e.code for e in errors}
