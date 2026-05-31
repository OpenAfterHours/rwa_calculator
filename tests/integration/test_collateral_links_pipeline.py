"""
Integration tests: collateral_links M:N allocation through the pipeline.

Validates the finite-collateral split end-to-end across the real
HierarchyResolver → ExposureClassifier → CRMProcessor stages:
- One collateral item linked to two loans of different SA risk weight is
  allocated greedily to the higher-RWA-density loan (most beneficial impact).
- The split is driven by the SA-equivalent ranking metric computed inside the
  CRM stage — NOT by lexical fall-back (the low-RW loan is named first).
- A bundle with no collateral_links table is unaffected (additive feature).

References:
- CRR Art. 193/194/207: CRM eligibility and recognition
- CRR Art. 230-231: substitution / sequential allocation of collateral
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import COLLATERAL_LINK_SCHEMA, COLLATERAL_SCHEMA
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)


def _run_to_crm(bundle, config: CalculationConfig):
    """Drive a RawDataBundle through hierarchy → classifier → CRM (unified)."""
    resolved = HierarchyResolver().resolve(bundle, config)
    classified = ExposureClassifier().classify(resolved, config)
    return CRMProcessor().get_crm_unified_bundle(classified, config)


def _two_loan_bundle(*, collateral, collateral_links):
    """Sovereign loan LN_A (0% RW) + corporate loan LN_B (100% RW), equal EAD.

    LN_A sorts lexically before LN_B, so an RWA-driven split must override the
    tie-break to land collateral on LN_B.
    """
    counterparties = [
        make_counterparty(
            counterparty_reference="CP_A", entity_type="sovereign", country_code="GB"
        ),
        make_counterparty(counterparty_reference="CP_B", entity_type="corporate"),
    ]
    facilities = [
        make_facility(facility_reference="FAC_A", counterparty_reference="CP_A"),
        make_facility(facility_reference="FAC_B", counterparty_reference="CP_B"),
    ]
    loans = [
        make_loan(loan_reference="LN_A", counterparty_reference="CP_A", drawn_amount=1_000_000.0),
        make_loan(loan_reference="LN_B", counterparty_reference="CP_B", drawn_amount=1_000_000.0),
    ]
    bundle = make_raw_data_bundle(counterparties=counterparties, facilities=facilities, loans=loans)
    return replace(bundle, collateral=collateral, collateral_links=collateral_links)


def _collateral_lf(beneficiary_reference: str) -> pl.LazyFrame:
    return _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": 1_000_000.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": beneficiary_reference,
                "is_eligible_financial_collateral": True,
            }
        ],
        COLLATERAL_SCHEMA,
    )


def _links_lf(refs: list[str]) -> pl.LazyFrame:
    return _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "beneficiary_type": "loan",
                "beneficiary_reference": ref,
            }
            for ref in refs
        ],
        COLLATERAL_LINK_SCHEMA,
    )


@pytest.fixture
def config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestCollateralLinksPipeline:
    def test_collateral_lands_on_higher_rw_loan(self, config: CalculationConfig) -> None:
        # Arrange — one £1m cash item linked to both loans; only enough for one.
        bundle = _two_loan_bundle(
            collateral=_collateral_lf("LN_A"),
            collateral_links=_links_lf(["LN_A", "LN_B"]),
        )

        # Act
        crm = _run_to_crm(bundle, config)
        audit = crm.collateral_link_allocation.collect()
        alloc = {r["beneficiary_reference"]: r["allocated_value"] for r in audit.to_dicts()}

        # Assert — RWA-driven: all collateral on the 100% RW corporate loan LN_B,
        # none on the 0% RW sovereign loan LN_A (which sorts first lexically).
        assert alloc.get("LN_B") == pytest.approx(1_000_000.0)
        assert alloc.get("LN_A", 0.0) == pytest.approx(0.0)

    def test_corporate_loan_ead_reduced_by_split(self, config: CalculationConfig) -> None:
        # Arrange
        bundle = _two_loan_bundle(
            collateral=_collateral_lf("LN_A"),
            collateral_links=_links_lf(["LN_A", "LN_B"]),
        )

        # Act
        crm = _run_to_crm(bundle, config)
        exposures = crm.exposures.collect()
        ead = {
            r["exposure_reference"]: r["ead_final"]
            for r in exposures.select("exposure_reference", "ead_final").to_dicts()
        }

        # Assert — corporate loan EAD (£1.005m incl. accrued interest) is covered
        # by the £1m cash, leaving the £5k interest residual; sovereign untouched.
        assert ead["LN_B"] == pytest.approx(5_000.0, abs=1.0)
        assert ead["LN_A"] == pytest.approx(1_005_000.0, abs=1.0)

    def test_no_links_table_is_unaffected(self, config: CalculationConfig) -> None:
        # Arrange — collateral attached directly to LN_B, no links table.
        bundle = _two_loan_bundle(
            collateral=_collateral_lf("LN_B"),
            collateral_links=None,
        )

        # Act
        crm = _run_to_crm(bundle, config)
        exposures = crm.exposures.collect()
        ead = {
            r["exposure_reference"]: r["ead_final"]
            for r in exposures.select("exposure_reference", "ead_final").to_dicts()
        }

        # Assert — single-beneficiary path unchanged, and no link audit emitted.
        assert crm.collateral_link_allocation is None
        assert ead["LN_B"] == pytest.approx(5_000.0, abs=1.0)
        assert ead["LN_A"] == pytest.approx(1_005_000.0, abs=1.0)
