"""
Integration tests: facility-level collateral cascades down NESTED facilities.

Validates end-to-end through the real HierarchyResolver → ExposureClassifier →
CRMProcessor stages that collateral pledged at a grandparent facility flows to
exposures sitting under an intermediate child facility:

    FAC_1 (grandparent)
      └── FAC_2 (child facility)
            ├── LN_1, LN_2 (loans)
            └── CN_1 (contingent)

Before the multi-level fix, the CRM facility join matched only an exposure's
immediate ``parent_facility_reference`` (FAC_2), so a pledge at FAC_1 allocated
nothing. Now the HierarchyResolver emits ``ancestor_facilities`` (FAC_2 + FAC_1)
and the CRM stage cascades the pledge over the whole subtree.

References:
- CRR Art. 230-231: pooling / sequential allocation of collateral
- CRR Art. 223(4): off-balance-sheet items valued at 100% nominal for CRM
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import COLLATERAL_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import seal_raw_table

from .conftest import (
    _rows_to_lazyframe,
    make_contingent,
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


def _nested_bundle(collateral: pl.LazyFrame):
    """FAC_1 → FAC_2 → {LN_1, LN_2, CN_1}; plus a sibling tree FAC_OTHER → LN_X."""
    counterparties = [make_counterparty(counterparty_reference="CP_1", entity_type="corporate")]
    facilities = [
        make_facility(facility_reference="FAC_1", counterparty_reference="CP_1"),
        make_facility(facility_reference="FAC_2", counterparty_reference="CP_1"),
        make_facility(facility_reference="FAC_OTHER", counterparty_reference="CP_1"),
    ]
    loans = [
        make_loan(loan_reference="LN_1", counterparty_reference="CP_1", drawn_amount=600_000.0),
        make_loan(loan_reference="LN_2", counterparty_reference="CP_1", drawn_amount=400_000.0),
        make_loan(loan_reference="LN_X", counterparty_reference="CP_1", drawn_amount=500_000.0),
    ]
    contingents = [
        make_contingent(
            contingent_reference="CN_1", counterparty_reference="CP_1", nominal_amount=200_000.0
        )
    ]
    # Explicit facility mappings: loans/contingent under FAC_2, FAC_2 under FAC_1,
    # LN_X under a separate standalone facility (no link to FAC_1).
    facility_mappings = [
        {"parent_facility_reference": "FAC_2", "child_reference": "LN_1", "child_type": "loan"},
        {"parent_facility_reference": "FAC_2", "child_reference": "LN_2", "child_type": "loan"},
        {
            "parent_facility_reference": "FAC_2",
            "child_reference": "CN_1",
            "child_type": "contingent",
        },
        {
            "parent_facility_reference": "FAC_1",
            "child_reference": "FAC_2",
            "child_type": "facility",
        },
        {
            "parent_facility_reference": "FAC_OTHER",
            "child_reference": "LN_X",
            "child_type": "loan",
        },
    ]
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        facilities=facilities,
        loans=loans,
        contingents=contingents,
        facility_mappings=facility_mappings,
    )
    return replace(bundle, collateral=seal_raw_table(collateral, "collateral"))


def _facility_cash(
    beneficiary_reference: str,
    *,
    market_value: float | None = None,
    pledge_percentage: float | None = None,
) -> pl.LazyFrame:
    return _rows_to_lazyframe(
        [
            {
                "collateral_reference": "C1",
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": market_value,
                "pledge_percentage": pledge_percentage,
                "beneficiary_type": "facility",
                "beneficiary_reference": beneficiary_reference,
                "is_eligible_financial_collateral": True,
            }
        ],
        COLLATERAL_SCHEMA,
    )


@pytest.fixture
def config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31), permission_mode=PermissionMode.STANDARDISED
    )


class TestNestedFacilityCollateralPipeline:
    def test_grandparent_pledge_cascades_to_descendants(self, config: CalculationConfig) -> None:
        """A pledge at the grandparent FAC_1 reaches every descendant under FAC_2,
        but not a sibling tree (FAC_OTHER)."""
        # Arrange — over-collateralise at FAC_1 so reach is a clean binary signal.
        bundle = _nested_bundle(_facility_cash("FAC_1", market_value=10_000_000.0))

        # Act
        crm = _run_to_crm(bundle, config)
        exposures = crm.exposures.collect()
        coverage = {
            r["exposure_reference"]: r["collateral_coverage_pct"]
            for r in exposures.select("exposure_reference", "collateral_coverage_pct").to_dicts()
        }

        # Assert — descendants of FAC_1 are reached (fully covered); sibling is not.
        assert coverage["LN_1"] == pytest.approx(100.0, abs=0.5)
        assert coverage["LN_2"] == pytest.approx(100.0, abs=0.5)
        assert coverage["CN_1"] == pytest.approx(100.0, abs=0.5)
        assert coverage["LN_X"] == pytest.approx(0.0, abs=0.5)

    def test_grandparent_pct_pledge_fully_covers_descendants(
        self, config: CalculationConfig
    ) -> None:
        """The user's exact scenario: pledge_percentage=1.0 at the grandparent
        resolves against the whole subtree EAD and fully relieves descendants."""
        # Arrange
        bundle = _nested_bundle(_facility_cash("FAC_1", pledge_percentage=1.0))

        # Act
        crm = _run_to_crm(bundle, config)
        exposures = crm.exposures.collect()
        rows = {
            r["exposure_reference"]: r
            for r in exposures.select(
                "exposure_reference", "collateral_coverage_pct", "ead_after_collateral"
            ).to_dicts()
        }

        # Assert — every descendant of FAC_1 is fully covered (SA EAD → ~0).
        for ref in ("LN_1", "LN_2", "CN_1"):
            assert rows[ref]["collateral_coverage_pct"] == pytest.approx(100.0, abs=0.5), ref
            assert rows[ref]["ead_after_collateral"] == pytest.approx(0.0, abs=1.0), ref

    def test_grandparent_pledge_cascades_under_basel_3_1(self) -> None:
        """End-to-end under Basel 3.1: a grandparent pledge still reaches every
        descendant under FAC_2 and leaves the sibling tree untouched."""
        # Arrange
        b31_config = CalculationConfig.basel_3_1(
            reporting_date=date(2030, 6, 30), permission_mode=PermissionMode.STANDARDISED
        )
        bundle = _nested_bundle(_facility_cash("FAC_1", market_value=10_000_000.0))

        # Act
        crm = _run_to_crm(bundle, b31_config)
        exposures = crm.exposures.collect()
        coverage = {
            r["exposure_reference"]: r["collateral_coverage_pct"]
            for r in exposures.select("exposure_reference", "collateral_coverage_pct").to_dicts()
        }

        # Assert
        assert coverage["LN_1"] == pytest.approx(100.0, abs=0.5)
        assert coverage["LN_2"] == pytest.approx(100.0, abs=0.5)
        assert coverage["CN_1"] == pytest.approx(100.0, abs=0.5)
        assert coverage["LN_X"] == pytest.approx(0.0, abs=0.5)
