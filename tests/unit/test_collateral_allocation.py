"""Unit tests for collateral allocation to undrawn exposures.

Tests cover:
- Facility-level collateral allocation to undrawn amounts
- Counterparty-level collateral pro-rata allocation by EAD
- has_facility_property_collateral flag propagation
- Property collateral detection for mortgage classification of undrawn
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.hierarchy import HierarchyResolver


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def resolver() -> HierarchyResolver:
    """Return a HierarchyResolver instance."""
    return HierarchyResolver()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return CRR config."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
    )


def create_raw_bundle(
    loans_data: dict,
    facilities_data: dict,
    facility_mappings_data: dict,
    counterparties_data: dict,
    collateral_data: dict | None = None,
) -> RawDataBundle:
    """Create a test RawDataBundle from data dicts."""
    loans = pl.DataFrame(loans_data).lazy()
    facilities = pl.DataFrame(facilities_data).lazy()
    facility_mappings = pl.DataFrame(facility_mappings_data).lazy()
    counterparties = pl.DataFrame(counterparties_data).lazy()

    collateral = None
    if collateral_data:
        collateral = pl.DataFrame(collateral_data).lazy()

    return RawDataBundle(
        counterparties=counterparties,
        loans=loans,
        contingents=None,
        facilities=facilities,
        facility_mappings=facility_mappings,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        org_mappings=None,
        lending_mappings=pl.DataFrame({
            "parent_counterparty_reference": pl.Series([], dtype=pl.String),
            "child_counterparty_reference": pl.Series([], dtype=pl.String),
        }).lazy(),
        ratings=None,
        fx_rates=None,
    )


# =============================================================================
# Facility Undrawn Linkage Tests
# =============================================================================


class TestFacilityUndrawnLinkage:
    """Tests for facility undrawn exposure creation and collateral linkage."""

    def test_facility_undrawn_has_parent_facility_reference(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn exposures should have parent_facility_reference set."""
        bundle = create_raw_bundle(
            loans_data={
                "loan_reference": ["LOAN001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "product_type": ["MORTGAGE"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
            },
            facilities_data={
                "facility_reference": ["FAC001"],
                "counterparty_reference": ["CP001"],
                "limit": [1000000.0],
                "product_type": ["MORTGAGE_FACILITY"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
                "risk_type": ["revolver"],
            },
            facility_mappings_data={
                "parent_facility_reference": ["FAC001"],
                "child_reference": ["LOAN001"],
                "child_type": ["loan"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["individual"],
                "country_code": ["GB"],
                "annual_revenue": [0.0],
                "total_assets": [0.0],
                "default_status": [False],
                "is_regulated": [False],
                "is_managed_as_retail": [False],
            },
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Find facility_undrawn exposure
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")

        assert len(undrawn) == 1
        assert undrawn["parent_facility_reference"][0] == "FAC001"
        assert undrawn["undrawn_amount"][0] == 500000.0  # 1M limit - 500k drawn

    def test_facility_level_property_collateral_detected_for_undrawn(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Undrawn exposures should detect facility-level property collateral."""
        bundle = create_raw_bundle(
            loans_data={
                "loan_reference": ["LOAN001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500000.0],
                "product_type": ["SECURED_LOAN"],  # Not a mortgage by name
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
            },
            facilities_data={
                "facility_reference": ["FAC001"],
                "counterparty_reference": ["CP001"],
                "limit": [1000000.0],
                "product_type": ["SECURED_FACILITY"],  # Not a mortgage by name
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
                "risk_type": ["revolver"],
            },
            facility_mappings_data={
                "parent_facility_reference": ["FAC001"],
                "child_reference": ["LOAN001"],
                "child_type": ["loan"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["individual"],
                "country_code": ["GB"],
                "annual_revenue": [0.0],
                "total_assets": [0.0],
                "default_status": [False],
                "is_regulated": [False],
                "is_managed_as_retail": [False],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["FAC001"],  # Linked at facility level
                "beneficiary_type": ["facility"],
                "collateral_type": ["real_estate"],
                "property_type": ["residential"],
                "market_value": [800000.0],
                "property_ltv": [0.625],  # 500k/800k
                "currency": ["GBP"],
                "residual_maturity_years": [5.0],
            },
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Find facility_undrawn exposure
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")

        assert len(undrawn) == 1
        # Undrawn should have the flag indicating facility has property collateral
        assert undrawn["has_facility_property_collateral"][0] is True


class TestPropertyCollateralFlagForUndrawn:
    """Tests for has_facility_property_collateral flag on undrawn exposures."""

    def test_undrawn_inherits_property_flag_from_facility(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Undrawn should have has_facility_property_collateral=True if facility has RE."""
        bundle = create_raw_bundle(
            loans_data={
                "loan_reference": ["LOAN001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [200000.0],
                "product_type": ["TERM_LOAN"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
            },
            facilities_data={
                "facility_reference": ["FAC001"],
                "counterparty_reference": ["CP001"],
                "limit": [500000.0],
                "product_type": ["FACILITY"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.35],
                "seniority": ["senior"],
                "risk_type": ["revolver"],
            },
            facility_mappings_data={
                "parent_facility_reference": ["FAC001"],
                "child_reference": ["LOAN001"],
                "child_type": ["loan"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["individual"],
                "country_code": ["GB"],
                "annual_revenue": [0.0],
                "total_assets": [0.0],
                "default_status": [False],
                "is_regulated": [False],
                "is_managed_as_retail": [False],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["FAC001"],
                "beneficiary_type": ["facility"],
                "collateral_type": ["real_estate"],
                "property_type": ["commercial"],
                "market_value": [600000.0],
                "property_ltv": [None],
                "currency": ["GBP"],
                "residual_maturity_years": [5.0],
            },
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Both drawn and undrawn should have the flag
        drawn = df.filter(pl.col("exposure_type") == "loan")
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")

        assert len(drawn) == 1
        assert len(undrawn) == 1

        # Drawn gets property collateral via pro-rata allocation
        assert drawn["has_facility_property_collateral"][0] is True

        # Undrawn also gets the flag (even though drawn_amount=0)
        assert undrawn["has_facility_property_collateral"][0] is True

    def test_no_property_collateral_flag_when_no_re_collateral(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures without RE collateral should have has_facility_property_collateral=False."""
        bundle = create_raw_bundle(
            loans_data={
                "loan_reference": ["LOAN001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [200000.0],
                "product_type": ["TERM_LOAN"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.45],
                "seniority": ["senior"],
            },
            facilities_data={
                "facility_reference": ["FAC001"],
                "counterparty_reference": ["CP001"],
                "limit": [500000.0],
                "product_type": ["FACILITY"],
                "book_code": ["BOOK1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "lgd": [0.45],
                "seniority": ["senior"],
                "risk_type": ["revolver"],
            },
            facility_mappings_data={
                "parent_facility_reference": ["FAC001"],
                "child_reference": ["LOAN001"],
                "child_type": ["loan"],
            },
            counterparties_data={
                "counterparty_reference": ["CP001"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [10000000.0],
                "total_assets": [5000000.0],
                "default_status": [False],
                "is_regulated": [False],
                "is_managed_as_retail": [False],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["FAC001"],
                "beneficiary_type": ["facility"],
                "collateral_type": ["cash"],  # Financial collateral, not RE
                "property_type": [""],  # Empty string instead of None for consistent type
                "market_value": [100000.0],
                "property_ltv": [None],
                "currency": ["GBP"],
                "residual_maturity_years": [1.0],
            },
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Both should have False for property flag since collateral is cash
        drawn = df.filter(pl.col("exposure_type") == "loan")
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")

        assert drawn["has_facility_property_collateral"][0] is False
        assert undrawn["has_facility_property_collateral"][0] is False
