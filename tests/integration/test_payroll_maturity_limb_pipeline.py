"""
Pipeline reachability of the payroll / pension loan maturity condition (P1.365).

Pipeline position:
    Loader seal -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator

Why this test matters:
    The unit tests under ``tests/unit/sa/`` drive ``SACalculator.calculate_branch``
    directly, so they cannot show that a LOAN input's ``value_date`` and
    ``maturity_date`` survive the hierarchy, classifier and CRM seals to reach
    the risk-weight chain. A loan input has no ``original_maturity_years``
    column, so the dates are the only route by which condition (d) -- "the
    maximum original maturity of the loan is equal to or less than 10 years" --
    can be seen in production. This test runs three flagged payroll loans
    through ``PipelineOrchestrator`` under each regime: one exactly 10 calendar
    years (35% stands), one 10 years and a day, and one 15 years (both fail (d)
    and take the 75% regulatory retail weight).

References:
- PRA PS1/26 Art. 123(4)(d)
- CRR Art. 123 final subparagraph point (d) (inserted by Reg. (EU) 2019/876)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_DRAWN = 20_000.0
_PAYROLL_RW = 0.35
_REGULATORY_RETAIL_RW = 0.75

# loan reference -> (value_date, maturity_date, expected risk weight)
_LOANS: dict[str, tuple[date, date, float]] = {
    "PAY_10Y_EXACT": (date(2026, 1, 15), date(2036, 1, 15), _PAYROLL_RW),
    "PAY_10Y_1D": (date(2026, 1, 15), date(2036, 1, 16), _REGULATORY_RETAIL_RW),
    "PAY_15Y": (date(2026, 1, 15), date(2041, 1, 15), _REGULATORY_RETAIL_RW),
}


def _config(regime: str) -> CalculationConfig:
    """Standardised-only config for the regime, built through its factory."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2026, 6, 30),
            base_currency="GBP",
            permission_mode=PermissionMode.STANDARDISED,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        base_currency="GBP",
        permission_mode=PermissionMode.STANDARDISED,
    )


def _bundle() -> RawDataBundle:
    """One natural-person borrower per loan; every loan flagged ``is_payroll_loan``."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": f"CP_{ref}",
                "counterparty_name": f"Payroll borrower {ref}",
                "entity_type": "individual",
                "country_code": "GB",
                "is_natural_person": True,
                "is_managed_as_retail": True,
                "apply_fi_scalar": False,
                "default_status": False,
            }
            for ref in _LOANS
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": ref,
                "product_type": "personal_loan",
                "counterparty_reference": f"CP_{ref}",
                "currency": "GBP",
                "drawn_amount": _DRAWN,
                "interest": 0.0,
                "value_date": value_date,
                "maturity_date": maturity_date,
                "seniority": "senior",
                "is_payroll_loan": True,
                "is_buy_to_let": False,
                "is_under_construction": False,
            }
            for ref, (value_date, maturity_date, _) in _LOANS.items()
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    return make_raw_bundle(loans=loans.lazy(), counterparties=counterparties.lazy())


@pytest.fixture(scope="module", params=["crr", "b31"])
def sa_rows(request: pytest.FixtureRequest) -> tuple[str, dict[str, dict]]:
    """Run the three payroll loans through the full pipeline once per regime."""
    regime: str = request.param
    results = PipelineOrchestrator().run_with_data(_bundle(), _config(regime))
    assert results.sa_results is not None, f"{regime}: no SA results"
    frame = results.sa_results.collect()
    rows = {row["exposure_reference"]: row for row in frame.to_dicts()}
    return regime, rows


@pytest.mark.parametrize("loan_reference", list(_LOANS))
def test_payroll_loan_risk_weight_follows_original_maturity(
    sa_rows: tuple[str, dict[str, dict]], loan_reference: str
) -> None:
    """Each flagged loan takes 35% only where its dated term is at most 10 years."""
    # Arrange
    regime, rows = sa_rows
    expected_rw = _LOANS[loan_reference][2]
    assert loan_reference in rows, f"{regime}: {loan_reference} has no SA row"
    row = rows[loan_reference]
    assert row["exposure_class"].upper().startswith("RETAIL"), (
        f"{regime}: adequacy - {loan_reference} must reach the retail limb, "
        f"got class {row['exposure_class']!r}"
    )
    assert row["is_payroll_loan"] is True, (
        f"{regime}: adequacy - the payroll flag must survive to the SA stage"
    )

    # Act
    risk_weight = row["risk_weight"]

    # Assert
    assert risk_weight == pytest.approx(expected_rw), (
        f"{regime}: {loan_reference} expected RW {expected_rw}, got {risk_weight}"
    )
    assert row["rwa_final"] == pytest.approx(_DRAWN * expected_rw)
