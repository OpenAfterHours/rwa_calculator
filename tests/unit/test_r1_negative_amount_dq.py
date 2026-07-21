"""
Unit tests for DQ010 — negative on-balance amounts without a netting agreement.

A negative ``drawn_amount`` / ``interest`` is the on-balance-sheet netting
convention (CRR Art. 195/219): a deposit / credit balance nets the loans that
share its ``netting_agreement_reference``. A negative amount WITHOUT such a
reference cannot offset anything and is a data error — ``validate_bundle_values``
emits a DQ010 warning (non-blocking) so the gap is visible, and the value is
floored at 0 downstream (EAD and the gross-exposure reporting carriers).

References:
    - CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
    - CRR Art. 195/219 (on-balance-sheet netting)
    - src/rwa_calc/contracts/validation.py::_validate_negative_amounts_without_netting
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.errors import ERROR_NEGATIVE_AMOUNT_WITHOUT_NETTING
from rwa_calc.contracts.validation import validate_bundle_values
from tests.fixtures.raw_bundle import make_raw_bundle


@pytest.fixture
def bundle_with_loans() -> Callable[[pl.LazyFrame], RawDataBundle]:
    def _make(loans: pl.LazyFrame) -> RawDataBundle:
        return make_raw_bundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(),
            counterparties=pl.LazyFrame(
                {"counterparty_reference": ["C1"], "entity_type": ["corporate"]}
            ),
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
        )

    return _make


def _dq010(errors) -> list:
    return [e for e in errors if e.code == ERROR_NEGATIVE_AMOUNT_WITHOUT_NETTING]


class TestNegativeAmountWithoutNetting:
    """DQ010 flags a bare negative but not a netted deposit."""

    def test_bare_negative_drawn_emits_dq010(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["LN-BARE"],
                "counterparty_reference": ["C1"],
                "drawn_amount": [-50_000.0],
                "netting_agreement_reference": [None],
            },
            schema_overrides={"netting_agreement_reference": pl.String},
        )
        errors = _dq010(validate_bundle_values(bundle_with_loans(loans)))
        assert len(errors) == 1
        assert errors[0].field_name == "drawn_amount"

    def test_netted_deposit_does_not_emit_dq010(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["LN-POS", "LN-DEP"],
                "counterparty_reference": ["C1", "C1"],
                "drawn_amount": [1_000_000.0, -200_000.0],
                "netting_agreement_reference": ["NET_1", "NET_1"],
            }
        )
        assert _dq010(validate_bundle_values(bundle_with_loans(loans))) == []

    def test_bare_negative_interest_emits_dq010(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["LN-INT"],
                "counterparty_reference": ["C1"],
                "drawn_amount": [100.0],
                "interest": [-10.0],
                "netting_agreement_reference": [None],
            },
            schema_overrides={"netting_agreement_reference": pl.String},
        )
        errors = _dq010(validate_bundle_values(bundle_with_loans(loans)))
        assert len(errors) == 1
        assert errors[0].field_name == "interest"

    def test_positive_amounts_emit_nothing(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["LN-POS"],
                "counterparty_reference": ["C1"],
                "drawn_amount": [500_000.0],
                "interest": [1_000.0],
                "netting_agreement_reference": [None],
            },
            schema_overrides={"netting_agreement_reference": pl.String},
        )
        assert _dq010(validate_bundle_values(bundle_with_loans(loans))) == []
