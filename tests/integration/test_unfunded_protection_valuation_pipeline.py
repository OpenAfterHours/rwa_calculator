"""
Integration tests: valuation and eligibility of unfunded protection, end to end.

Each case runs the full pipeline (``PipelineOrchestrator.run_with_data``, SA
permission mode) under CRR (2026-06-01) and Basel 3.1 (2027-06-01) and asserts
the hand-calculated portfolio RWA. The probe portfolio:

- ``CP-A`` / ``CP-B``: unrated corporates — 100% in both regimes.
- ``CP-INST``: institution, external CQS 2 — 50% (CRR) / 30% (Basel 3.1).
- Loans are 5-year GBP term loans; guarantees are GBP, 5-year, so neither the
  Art. 233(3) FX haircut nor the Art. 239 maturity adjustment applies.

Rule text (PS1/26 Appendix 1; CRR Art. 233-235 read the same in substance):

- Art. 233(1): G is "the amount that the protection provider has undertaken to
  pay in the event of the default or non-payment of the borrower".
- Art. 233(2)(a)/(b): a credit derivative without restructuring as a credit
  event is cut "by 40%" where G is not higher than the exposure value, and is
  "no higher than 60% of the exposure value" where G is higher.
- Art. 234(1): "Where an institution transfers a part of the risk of a loan in
  one or more tranches, the institution shall comply with the requirements set
  out in Chapter 5"; Art. 235(2): substitution "only where the protected and
  unprotected parts of the exposure are of equal seniority".
- Art. 215(1)(b): "the guarantee is an explicitly documented obligation assumed
  by the guarantor".

Pre-fix figures (guarantees review, measured on 9824d8a) are quoted per case so
the size of each correction is on record.

References:
    GT-01, GT-02, GT-03, GT-05 (P1.202), GT-06 (P1.201), GT-07.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
    ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,
    ERROR_PROTECTION_TYPE_MISMATCH,
    ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_DATES = {"crr": date(2026, 6, 1), "b31": date(2027, 6, 1)}
_CRM_CODES = (
    ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,
    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
    ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,
    ERROR_PROTECTION_TYPE_MISMATCH,
)


@dataclass(frozen=True)
class _Case:
    """One scenario: loans, guarantee rows and the expected (CRR, B31) figures."""

    loans: tuple[tuple[str, str, float], ...]
    guarantees: tuple[dict[str, Any], ...]
    rwa: dict[str, float]
    guaranteed: float
    codes: tuple[str, ...] = field(default=())


def _guarantee(**fields: Any) -> dict[str, Any]:
    """A loan-level GBP guarantee from CP-INST on L1, overridden by ``fields``."""
    return {
        "guarantee_reference": "G1",
        "guarantee_type": "guarantee",
        "guarantor": "CP-INST",
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "currency": "GBP",
        "maturity_date": date(2031, 6, 1),
        "original_maturity_years": 5.0,
        "amount_covered": None,
        "percentage_covered": None,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "attachment_amount": None,
        "detachment_amount": None,
        **fields,
    }


def _cds(**fields: Any) -> dict[str, Any]:
    """A credit derivative that does not include restructuring as a credit event."""
    return _guarantee(protection_type="credit_derivative", includes_restructuring=False, **fields)


_ONE_LOAN = (("L1", "CP-A", 8.0),)
_TWO_LOANS = (("L1", "CP-A", 8.0), ("L2", "CP-B", 6.0))

CASES: dict[str, _Case] = {
    # Control: the guarantor is recognised and beneficial in both regimes.
    # 8 x 0.5 = 4.0 (CRR); 8 x 0.3 = 2.4 (B31).
    "control-full-guarantee": _Case(
        _ONE_LOAN, (_guarantee(amount_covered=8.0),), {"crr": 4.0, "b31": 2.4}, 8.0
    ),
    # GT-05: 100% CDS as a percentage. G = 8 <= E -> 0.6 x 8 = 4.8 covered.
    # CRR 4.8 x 0.5 + 3.2 = 5.6; B31 4.8 x 0.3 + 3.2 = 4.64. Pre-fix 4.0 / 2.4.
    "gt05-percentage-cds": _Case(
        _ONE_LOAN, (_cds(percentage_covered=1.0),), {"crr": 5.6, "b31": 4.64}, 4.8
    ),
    # GT-06: CDS notional 16 on E = 8: no higher than 0.6 x 8 = 4.8. Pre-fix 4.0 / 2.4.
    "gt06-oversized-cds": _Case(
        _ONE_LOAN, (_cds(amount_covered=16.0),), {"crr": 5.6, "b31": 4.64}, 4.8
    ),
    # GT-02: 50% up to 5 on E = 8 undertakes 4. CRR 4 x 0.5 + 4 = 6.0;
    # B31 4 x 0.3 + 4 = 5.2. Pre-fix (amount won) 5.5 / 4.5.
    "gt02-percentage-with-cap": _Case(
        _ONE_LOAN,
        (_guarantee(amount_covered=5.0, percentage_covered=0.5),),
        {"crr": 6.0, "b31": 5.2},
        4.0,
    ),
    # GT-03: band [2, 6) of a 10 loan is tranched: not recognised, 10 x 100%.
    # Pre-fix 8.0 / 7.2 (substitution on the mezzanine band).
    "gt03-tranched": _Case(
        (("L1", "CP-A", 10.0),),
        (_guarantee(amount_covered=4.0, attachment_amount=2.0, detachment_amount=6.0),),
        {"crr": 10.0, "b31": 10.0},
        0.0,
        (ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,),
    ),
    # GT-01: one contract (cap 5) over L1 = 8 and L2 = 6 of different obligors.
    # 5 covered in total: CRR 5 x 0.5 + 9 = 11.5; B31 5 x 0.3 + 9 = 10.5.
    # Pre-fix 9.0 / 7.0 (the cap counted once per row).
    "gt01-pool-cap": _Case(
        _TWO_LOANS,
        (
            _guarantee(guarantee_reference="POOL", amount_covered=5.0),
            _guarantee(guarantee_reference="POOL", beneficiary_reference="L2", amount_covered=5.0),
        ),
        {"crr": 11.5, "b31": 10.5},
        5.0,
    ),
    # GT-01 with GT-02: 50% up to 5 per contract: 4 + 3 = 7 scaled to 5.
    "gt01-pool-cap-percentage": _Case(
        _TWO_LOANS,
        (
            _guarantee(guarantee_reference="POOL", amount_covered=5.0, percentage_covered=0.5),
            _guarantee(
                guarantee_reference="POOL",
                beneficiary_reference="L2",
                amount_covered=5.0,
                percentage_covered=0.5,
            ),
        ),
        {"crr": 11.5, "b31": 10.5},
        5.0,
    ),
    # GT-01: rows of one contract disagree (5 vs 4): cap 5 used, CRM028.
    "gt01-inconsistent-rows": _Case(
        _TWO_LOANS,
        (
            _guarantee(guarantee_reference="POOL", amount_covered=5.0),
            _guarantee(guarantee_reference="POOL", beneficiary_reference="L2", amount_covered=4.0),
        ),
        {"crr": 11.5, "b31": 10.5},
        5.0,
        (ERROR_GUARANTEE_REFERENCE_INCONSISTENT,),
    ),
    # GT-07: a letter of comfort is not a guarantee: 8 x 100%. Pre-fix 4.0 / 2.4.
    "gt07-letter-of-comfort": _Case(
        _ONE_LOAN,
        (_guarantee(amount_covered=8.0, guarantee_type="letter_of_comfort"),),
        {"crr": 8.0, "b31": 8.0},
        0.0,
        (ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,),
    ),
    # GT-07: guarantee_type says CDS, protection_type left null; no restructuring.
    # Treated as a credit derivative: 0.6 x 8 = 4.8 covered. Pre-fix 4.0 / 2.4.
    "gt07-cds-by-guarantee-type": _Case(
        _ONE_LOAN,
        (
            _guarantee(
                amount_covered=8.0,
                guarantee_type="credit_derivative",
                protection_type=None,
                includes_restructuring=False,
            ),
        ),
        {"crr": 5.6, "b31": 4.64},
        4.8,
        (ERROR_PROTECTION_TYPE_MISMATCH,),
    ),
}


def _bundle(case: _Case) -> Any:
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["CP-A", "CP-B", "CP-INST"],
            "counterparty_name": ["CP-A", "CP-B", "CP-INST"],
            "entity_type": ["corporate", "corporate", "institution"],
            "country_code": ["GB"] * 3,
            "default_status": [False] * 3,
            "apply_fi_scalar": [False] * 3,
        }
    )
    ratings = pl.DataFrame(
        {
            "rating_reference": ["R-INST"],
            "counterparty_reference": ["CP-INST"],
            "rating_type": ["external"],
            "rating_agency": ["S&P"],
            "rating_value": ["A"],
            "cqs": pl.Series([2], dtype=pl.Int8),
            "rating_date": [date(2026, 1, 2)],
            "is_solicited": [True],
        }
    )
    loans = pl.DataFrame(
        {
            "loan_reference": [ref for ref, _, _ in case.loans],
            "counterparty_reference": [cp for _, cp, _ in case.loans],
            "value_date": [date(2026, 1, 2)] * len(case.loans),
            "maturity_date": [date(2031, 1, 2)] * len(case.loans),
            "currency": ["GBP"] * len(case.loans),
            "drawn_amount": [amount for _, _, amount in case.loans],
            "interest": [0.0] * len(case.loans),
            "seniority": ["senior"] * len(case.loans),
        }
    )
    guarantees = pl.DataFrame(
        list(case.guarantees),
        schema_overrides={
            "amount_covered": pl.Float64,
            "percentage_covered": pl.Float64,
            "attachment_amount": pl.Float64,
            "detachment_amount": pl.Float64,
            "protection_type": pl.String,
            "original_maturity_years": pl.Float64,
        },
    )
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans.lazy(),
        counterparties=counterparties.lazy(),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=ratings.lazy(),
        guarantees=guarantees.lazy(),
    )


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_DATES["crr"], permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_DATES["b31"], permission_mode=PermissionMode.STANDARDISED
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize("name", list(CASES))
def test_portfolio_rwa_matches_hand_calculation(name: str, regime: str) -> None:
    """Portfolio RWA, covered amount and the cluster's CRM warnings, per regime."""
    # Arrange
    case = CASES[name]

    # Act
    result = PipelineOrchestrator().run_with_data(_bundle(case), _config(regime))
    assert result.sa_results is not None
    frame = result.sa_results.collect()

    # Assert
    assert frame["rwa_final"].sum() == pytest.approx(case.rwa[regime], abs=1e-9)
    assert frame["guaranteed_portion"].fill_null(0.0).sum() == pytest.approx(
        case.guaranteed, abs=1e-9
    )
    assert frame["ead_final"].sum() == pytest.approx(sum(a for _, _, a in case.loans), abs=1e-9)
    raised = tuple(e.code for e in result.errors if e.code in _CRM_CODES)
    assert raised == case.codes
