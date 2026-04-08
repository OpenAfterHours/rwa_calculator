"""
Unit tests for CRM collateral_allocation bundle population (P6.20).

Verifies that CRMAdjustedBundle.collateral_allocation is populated when
collateral data is present, containing per-exposure allocation details from
the Art. 231 sequential waterfall.

Why: collateral_allocation was always None, meaning downstream reporting
and audit could not access per-exposure allocation breakdowns without
parsing the full exposure frame. The allocation data was computed during
CRM processing but never surfaced through the bundle field. See
IMPLEMENTATION_PLAN.md P6.20.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.constants import CRM_ALLOC_COLUMNS
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture
def firb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Helpers
# =============================================================================


def _empty_counterparty_lookup() -> CounterpartyLookup:
    return CounterpartyLookup(
        counterparties=pl.LazyFrame(
            schema={"counterparty_reference": pl.String, "entity_type": pl.String}
        ),
        parent_mappings=pl.LazyFrame(
            schema={
                "child_counterparty_reference": pl.String,
                "parent_counterparty_reference": pl.String,
            }
        ),
        ultimate_parent_mappings=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        ),
        rating_inheritance=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "rating_type": pl.String,
            }
        ),
    )


def _make_bundle(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None = None,
) -> ClassifiedExposuresBundle:
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=pl.LazyFrame(),
        equity_exposures=None,
        counterparty_lookup=_empty_counterparty_lookup(),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _sa_exposure(
    ref: str,
    drawn: float,
    nominal: float = 0.0,
    cp_ref: str = "CP001",
) -> dict:
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": ApproachType.SA.value,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": nominal,
        "risk_type": "FR" if nominal == 0.0 else "MR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": "FAC_DEFAULT",
        "currency": "GBP",
        "maturity_date": None,
    }


def _firb_exposure(ref: str, drawn: float, cp_ref: str = "CP001") -> dict:
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": ApproachType.FIRB.value,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "risk_type": "FR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": "FAC_DEFAULT",
        "currency": "GBP",
        "maturity_date": None,
    }


def _collateral_schema() -> dict[str, type[pl.DataType]]:
    """Schema for collateral test data to avoid null-type inference errors."""
    return {
        "collateral_reference": pl.String,
        "beneficiary_reference": pl.String,
        "beneficiary_type": pl.String,
        "collateral_type": pl.String,
        "market_value": pl.Float64,
        "currency": pl.String,
        "issuer_cqs": pl.Int8,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "pledge_percentage": pl.Float64,
        "collateral_maturity_date": pl.Date,
    }


def _cash_collateral(
    beneficiary_ref: str,
    market_value: float,
    beneficiary_type: str = "exposure",
) -> dict:
    return {
        "collateral_reference": f"COLL_{beneficiary_ref}",
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": "cash",
        "market_value": market_value,
        "currency": "GBP",
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "is_eligible_financial_collateral": True,
        "pledge_percentage": None,
        "collateral_maturity_date": None,
    }


def _re_collateral(beneficiary_ref: str, market_value: float) -> dict:
    return {
        "collateral_reference": f"COLL_RE_{beneficiary_ref}",
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": "exposure",
        "collateral_type": "real_estate",
        "market_value": market_value,
        "currency": "GBP",
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "is_eligible_financial_collateral": False,
        "pledge_percentage": None,
        "collateral_maturity_date": None,
    }


def _make_collateral_frame(rows: list[dict]) -> pl.LazyFrame:
    """Build collateral LazyFrame with proper schema typing."""
    return pl.LazyFrame(rows, schema=_collateral_schema())


# =============================================================================
# Tests — collateral_allocation is populated
# =============================================================================


class TestCollateralAllocationPopulated:
    """Verify collateral_allocation is a LazyFrame when collateral exists."""

    def test_allocation_populated_with_collateral(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """When valid collateral is present, collateral_allocation should not be None."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        assert bundle.collateral_allocation is not None

    def test_allocation_is_lazyframe(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """collateral_allocation should be a Polars LazyFrame."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        assert isinstance(bundle.collateral_allocation, pl.LazyFrame)

    def test_allocation_none_without_collateral(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Without collateral, collateral_allocation should remain None."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, None), crr_config)

        assert bundle.collateral_allocation is None

    def test_allocation_none_with_invalid_collateral(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Collateral with missing required columns should leave allocation as None."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        bad_collateral = pl.LazyFrame({"some_column": [1.0]})

        bundle = processor.get_crm_adjusted_bundle(
            _make_bundle(exposures, bad_collateral), crr_config
        )

        assert bundle.collateral_allocation is None

    def test_allocation_row_count_matches_exposures(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Allocation frame should have one row per exposure."""
        exposures = pl.LazyFrame(
            [_sa_exposure("E1", 500_000), _sa_exposure("E2", 1_000_000, cp_ref="CP002")]
        )
        collateral = _make_collateral_frame([_cash_collateral("E1", 200_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        assert alloc.shape[0] == 2


# =============================================================================
# Tests — allocation frame columns
# =============================================================================


class TestCollateralAllocationColumns:
    """Verify the allocation frame has the expected schema."""

    def test_identifier_columns_present(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Allocation should contain exposure_reference, counterparty_reference, approach."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        cols = bundle.collateral_allocation.collect_schema().names()
        assert "exposure_reference" in cols
        assert "counterparty_reference" in cols
        assert "approach" in cols
        assert "ead_gross" in cols

    def test_waterfall_allocation_columns_present(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """All CRM_ALLOC_COLUMNS (crm_alloc_*) should be present."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        cols = bundle.collateral_allocation.collect_schema().names()
        for alloc_col in CRM_ALLOC_COLUMNS.values():
            assert alloc_col in cols, f"Missing allocation column: {alloc_col}"

    def test_coverage_columns_present(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """total_collateral_for_lgd and collateral_coverage_pct should be present."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        cols = bundle.collateral_allocation.collect_schema().names()
        assert "total_collateral_for_lgd" in cols
        assert "collateral_coverage_pct" in cols

    def test_value_columns_present(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Per-type collateral value columns should be present."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        cols = bundle.collateral_allocation.collect_schema().names()
        for col_name in [
            "collateral_adjusted_value",
            "collateral_market_value",
            "collateral_financial_value",
            "collateral_cash_value",
            "collateral_re_value",
            "collateral_receivables_value",
            "collateral_other_physical_value",
        ]:
            assert col_name in cols, f"Missing value column: {col_name}"

    def test_lgd_columns_present(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """LGD impact columns should be present."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        cols = bundle.collateral_allocation.collect_schema().names()
        assert "lgd_secured" in cols
        assert "lgd_unsecured" in cols
        assert "lgd_post_crm" in cols
        assert "ead_after_collateral" in cols

    def test_no_extra_columns(self, processor: CRMProcessor, crr_config: CalculationConfig) -> None:
        """Allocation frame should contain only the expected 23 columns."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        # 4 identifiers + 6 waterfall + 2 totals + 5 values + 2 financial + 4 LGD = 23
        assert alloc.shape[1] == 23


# =============================================================================
# Tests — allocation values correctness
# =============================================================================


class TestCollateralAllocationValues:
    """Verify allocation values are correct for known scenarios."""

    def test_cash_collateral_financial_allocation(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Cash collateral should show allocation in crm_alloc_financial."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 400_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        assert row["crm_alloc_financial"][0] == pytest.approx(400_000)
        assert row["crm_alloc_real_estate"][0] == pytest.approx(0.0)

    def test_cash_collateral_coverage_pct(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Coverage percentage should reflect collateral-to-EAD ratio."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        # 500k / 1M * 100 = 50%
        assert row["collateral_coverage_pct"][0] == pytest.approx(50.0)

    def test_sa_ead_after_collateral_reduced(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """SA EAD should be reduced by financial collateral adjusted value."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 300_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        assert row["ead_after_collateral"][0] == pytest.approx(700_000)

    def test_firb_lgd_post_crm_reflects_collateral(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ) -> None:
        """F-IRB LGD post-CRM should be lower than unsecured LGD when collateral covers exposure."""
        exposures = pl.LazyFrame([_firb_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 1_000_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), firb_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        # Fully collateralised with cash → lgd_secured ≈ 0 (LGDS_financial = 0%)
        # lgd_post_crm should be close to 0 since fully secured by cash
        assert row["lgd_post_crm"][0] < 0.10  # well below 0.45 unsecured

    def test_zero_collateral_exposure_shows_zero_allocation(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Exposure with no matching collateral should show zero allocations."""
        exposures = pl.LazyFrame(
            [_sa_exposure("E1", 500_000), _sa_exposure("E2", 500_000, cp_ref="CP002")]
        )
        # Collateral only for E1
        collateral = _make_collateral_frame([_cash_collateral("E1", 200_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        e2_row = alloc.filter(pl.col("exposure_reference") == "E2")
        assert e2_row["crm_alloc_financial"][0] == pytest.approx(0.0)
        assert e2_row["total_collateral_for_lgd"][0] == pytest.approx(0.0)

    def test_allocation_matches_exposure_frame(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Allocation values should match those on the main exposure frame."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 600_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        main = bundle.exposures.collect().filter(pl.col("exposure_reference") == "E1")

        alloc_row = alloc.filter(pl.col("exposure_reference") == "E1")
        assert alloc_row["crm_alloc_financial"][0] == pytest.approx(main["crm_alloc_financial"][0])
        assert alloc_row["total_collateral_for_lgd"][0] == pytest.approx(
            main["total_collateral_for_lgd"][0]
        )
        assert alloc_row["lgd_post_crm"][0] == pytest.approx(main["lgd_post_crm"][0])


# =============================================================================
# Tests — unified bundle path
# =============================================================================


class TestCollateralAllocationUnifiedBundle:
    """Verify collateral_allocation works through get_crm_unified_bundle."""

    def test_unified_allocation_populated(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Unified bundle should also populate collateral_allocation."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_unified_bundle(_make_bundle(exposures, collateral), crr_config)

        assert bundle.collateral_allocation is not None
        alloc = bundle.collateral_allocation.collect()
        assert alloc.shape[0] == 1

    def test_unified_allocation_none_without_collateral(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Unified bundle without collateral should have allocation as None."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])

        bundle = processor.get_crm_unified_bundle(_make_bundle(exposures, None), crr_config)

        assert bundle.collateral_allocation is None

    def test_unified_allocation_values_match(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Unified allocation values should match the exposure frame."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 400_000)])

        bundle = processor.get_crm_unified_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        main = bundle.exposures.collect().filter(pl.col("exposure_reference") == "E1")
        assert alloc["crm_alloc_financial"][0] == pytest.approx(main["crm_alloc_financial"][0])


# =============================================================================
# Tests — edge cases
# =============================================================================


class TestCollateralAllocationEdgeCases:
    """Edge cases for collateral allocation population."""

    def test_overcollateralised_capped_at_ead(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Allocation should not exceed EAD even when collateral exceeds exposure."""
        exposures = pl.LazyFrame([_sa_exposure("E1", 100_000)])
        collateral = _make_collateral_frame([_cash_collateral("E1", 500_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        # Waterfall caps at EAD
        assert row["total_collateral_for_lgd"][0] == pytest.approx(100_000)
        assert row["ead_after_collateral"][0] == pytest.approx(0.0)

    def test_multiple_collateral_types_waterfall(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ) -> None:
        """Mixed collateral should show allocation split across types."""
        exposures = pl.LazyFrame([_firb_exposure("E1", 1_000_000)])
        collateral = _make_collateral_frame(
            [
                _cash_collateral("E1", 300_000),
                _re_collateral("E1", 500_000),
            ]
        )

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), firb_config)

        alloc = bundle.collateral_allocation.collect()
        row = alloc.filter(pl.col("exposure_reference") == "E1")
        # Cash absorbs first (LGDS=0%), then RE (subject to 30% threshold)
        assert row["crm_alloc_financial"][0] == pytest.approx(300_000)
        assert row["total_collateral_for_lgd"][0] > 300_000

    def test_empty_exposures_with_collateral(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Empty exposure frame with collateral should produce empty allocation."""
        exposures = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "counterparty_reference": pl.String,
                "exposure_class": pl.String,
                "approach": pl.String,
                "drawn_amount": pl.Float64,
                "interest": pl.Float64,
                "nominal_amount": pl.Float64,
                "risk_type": pl.String,
                "lgd": pl.Float64,
                "seniority": pl.String,
                "parent_facility_reference": pl.String,
                "currency": pl.String,
                "maturity_date": pl.Date,
            }
        )
        collateral = _make_collateral_frame([_cash_collateral("E1", 100_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        assert bundle.collateral_allocation is not None
        alloc = bundle.collateral_allocation.collect()
        assert alloc.shape[0] == 0

    def test_allocation_preserves_exposure_reference(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Every exposure should be identifiable in the allocation frame."""
        exposures = pl.LazyFrame(
            [
                _sa_exposure("E1", 500_000),
                _sa_exposure("E2", 300_000, cp_ref="CP002"),
                _sa_exposure("E3", 200_000, cp_ref="CP003"),
            ]
        )
        collateral = _make_collateral_frame([_cash_collateral("E1", 100_000)])

        bundle = processor.get_crm_adjusted_bundle(_make_bundle(exposures, collateral), crr_config)

        alloc = bundle.collateral_allocation.collect()
        refs = set(alloc["exposure_reference"].to_list())
        assert refs == {"E1", "E2", "E3"}
