"""
Pipeline reachability of the payroll-over-transactor precedence (P1.350).

Pipeline position:
    Loader seal -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator

Why this test matters:
    PS1/26 Art. 123(3) is "Subject to paragraph 4", so a payroll / pension loan
    meeting Art. 123(4) takes 35% even where it is also a regulatory-retail
    transactor exposure (45% under Art. 123(3)(a)). The unit grid in
    ``tests/unit/sa/test_payroll_transactor_precedence.py`` drives
    ``SACalculator.calculate_branch`` on hand-built rows; this test shows the
    cell is reachable from ordinary, schema-valid input through
    ``PipelineOrchestrator``, by two routes:

    - Route B: the payroll flag is on the LOAN only, and the loan is a drawing
      under a transactor credit-card facility. The hierarchy coalesces the
      facility's ``is_qrre_transactor`` onto the child loan, so the loan carries
      both flags without any input row setting both.
    - Route A: the facility itself carries both flags, so its undrawn row
      (``<facility>_UNDRAWN``) carries both as well.

    The borrower is a natural person managed as part of a retail pool
    (``is_managed_as_retail=True``) so that each leg is REGULATORY retail
    (Art. 123A). Without that flag the loader default leaves the leg outside
    regulatory retail, where it was already 35% before the fix and the test
    would prove nothing; the adequacy assertions pin it.

    The transactor-only undrawn row of route B is the guard leg: it carries no
    payroll flag, so it keeps the Basel 3.1 transactor 45% (CRR 75%, which has
    no transactor weight).

References:
- PRA PS1/26 Art. 123(3) chapeau "Subject to paragraph 4"; Art. 123(4)
- CRR Art. 123 final subparagraph (payroll / pension loans, 35%)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_PAYROLL_RW = 0.35  # PS1/26 Art. 123(4); CRR Art. 123 final subparagraph
_TRANSACTOR_RW = 0.45  # PS1/26 Art. 123(3)(a)
_REGULATORY_RETAIL_RW = 0.75  # PS1/26 Art. 123(3)(b); CRR Art. 123 first subparagraph

_VALUE_DATE = date(2026, 1, 15)
_MATURITY_DATE = date(2031, 1, 15)  # 5 years: condition (d) of Art. 123(4) met

# Route -> does the FACILITY carry the payroll flag (route A) or only its loan (B)?
_FACILITY_PAYROLL = {"A": True, "B": False}

# exposure reference -> (is_payroll_loan on the leg, {regime: expected risk weight})
_LEGS: dict[str, tuple[bool, dict[str, float]]] = {
    "LN_PAY_A": (True, {"crr": _PAYROLL_RW, "b31": _PAYROLL_RW}),
    "FAC_CARD_A_UNDRAWN": (True, {"crr": _PAYROLL_RW, "b31": _PAYROLL_RW}),
    "LN_PAY_B": (True, {"crr": _PAYROLL_RW, "b31": _PAYROLL_RW}),
    "FAC_CARD_B_UNDRAWN": (False, {"crr": _REGULATORY_RETAIL_RW, "b31": _TRANSACTOR_RW}),
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
    """Two natural-person card holders, each with a transactor card and a payroll drawing."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": f"CP_{route}",
                "counterparty_name": f"Payroll card holder {route}",
                "entity_type": "individual",
                "country_code": "GB",
                "is_natural_person": True,
                "is_managed_as_retail": True,
                "borrower_income_currency": "GBP",
                "apply_fi_scalar": False,
                "default_status": False,
            }
            for route in _FACILITY_PAYROLL
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    facilities = pl.DataFrame(
        [
            {
                "facility_reference": f"FAC_CARD_{route}",
                "product_type": "CREDIT_CARD",
                "counterparty_reference": f"CP_{route}",
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "currency": "GBP",
                "limit": 10_000.0,
                "committed": True,
                "is_revolving": True,
                "seniority": "senior",
                "risk_type": "MR",
                "is_qrre_transactor": True,
                "is_payroll_loan": facility_payroll,
            }
            for route, facility_payroll in _FACILITY_PAYROLL.items()
        ],
        schema=dtypes_of(FACILITY_SCHEMA),
    )
    loans = pl.DataFrame(
        [
            {
                "loan_reference": f"LN_PAY_{route}",
                "product_type": "CREDIT_CARD",
                "counterparty_reference": f"CP_{route}",
                "currency": "GBP",
                "drawn_amount": 4_000.0,
                "interest": 0.0,
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "seniority": "senior",
                "is_payroll_loan": True,
                "is_buy_to_let": False,
                "is_under_construction": False,
            }
            for route in _FACILITY_PAYROLL
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )
    facility_mappings = pl.DataFrame(
        [
            {
                "parent_facility_reference": f"FAC_CARD_{route}",
                "child_reference": f"LN_PAY_{route}",
                "child_type": "loan",
            }
            for route in _FACILITY_PAYROLL
        ],
        schema=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )
    return make_raw_bundle(
        facilities=facilities.lazy(),
        loans=loans.lazy(),
        counterparties=counterparties.lazy(),
        facility_mappings=facility_mappings.lazy(),
    )


@pytest.fixture(scope="module", params=["crr", "b31"])
def sa_rows(request: pytest.FixtureRequest) -> tuple[str, dict[str, dict]]:
    """Run both card holders through the full pipeline once per regime."""
    regime: str = request.param
    results = PipelineOrchestrator().run_with_data(_bundle(), _config(regime))
    assert results.sa_results is not None, f"{regime}: no SA results"
    frame = results.sa_results.collect()
    rows = {row["exposure_reference"]: row for row in frame.to_dicts()}
    return regime, rows


@pytest.mark.parametrize("exposure_reference", list(_LEGS))
def test_payroll_flag_outranks_transactor_weight_end_to_end(
    sa_rows: tuple[str, dict[str, dict]], exposure_reference: str
) -> None:
    """A regulatory-retail transactor leg takes 35% where it is a payroll loan."""
    # Arrange
    regime, rows = sa_rows
    payroll, expected_by_regime = _LEGS[exposure_reference]
    expected_rw = expected_by_regime[regime]
    assert exposure_reference in rows, f"{regime}: {exposure_reference} has no SA row"
    row = rows[exposure_reference]
    assert row["exposure_class"].upper().startswith("RETAIL"), (
        f"{regime}: adequacy - {exposure_reference} must reach the retail limb, "
        f"got class {row['exposure_class']!r}"
    )
    assert row["qualifies_as_retail"] is True, (
        f"{regime}: adequacy - {exposure_reference} must be regulatory retail, or it "
        "is the non-qualifying cell, which took 35% before the fix as well"
    )
    assert row["is_qrre_transactor"] is True, (
        f"{regime}: adequacy - the facility's transactor flag must reach {exposure_reference}"
    )
    assert row["is_payroll_loan"] is payroll, (
        f"{regime}: adequacy - {exposure_reference} must carry is_payroll_loan={payroll}"
    )
    assert row["ead_final"] > 0.0, f"{regime}: adequacy - {exposure_reference} has no EAD"

    # Act
    risk_weight = row["risk_weight"]

    # Assert
    assert risk_weight == pytest.approx(expected_rw), (
        f"{regime}: {exposure_reference} expected RW {expected_rw}, got {risk_weight}"
    )
    assert row["rwa_final"] == pytest.approx(row["ead_final"] * expected_rw)
