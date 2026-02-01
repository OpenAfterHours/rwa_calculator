"""Unit tests for IRB LGD adjustment with collateral.

Tests cover:
- F-IRB effective LGD calculation with different collateral types
- Multi-level collateral allocation for LGD (direct, facility, counterparty)
- Weighted average LGD for partially secured exposures
- A-IRB exposures keep modelled LGD (no adjustment)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, CounterpartyLookup
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.crm.processor import CRMProcessor


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    """Return a CRMProcessor instance."""
    return CRMProcessor()


@pytest.fixture
def firb_config() -> CalculationConfig:
    """Return CRR config with FIRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture
def airb_config() -> CalculationConfig:
    """Return CRR config with full AIRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


def create_classified_bundle(
    exposures_data: dict,
    collateral_data: dict | None = None,
) -> ClassifiedExposuresBundle:
    """Create a test ClassifiedExposuresBundle from data dicts.

    Adds required columns with defaults if not provided.
    """
    # Add default columns required by CRM processor
    n = len(list(exposures_data.values())[0])
    defaults = {
        "exposure_type": ["loan"] * n,
        "nominal_amount": [0.0] * n,
        "interest": [0.0] * n,
        "undrawn_amount": [0.0] * n,
        "risk_type": [None] * n,
        "ccf_modelled": [None] * n,
        "is_short_term_trade_lc": [False] * n,
        "product_type": ["TERM_LOAN"] * n,
        "value_date": [date(2024, 1, 1)] * n,
        "book_code": ["BOOK1"] * n,
    }

    for key, value in defaults.items():
        if key not in exposures_data:
            exposures_data[key] = value

    exposures = pl.DataFrame(exposures_data).lazy()

    # Ensure parent_facility_reference is String type (not null type when all values are None)
    if "parent_facility_reference" in exposures.collect_schema().names():
        exposures = exposures.with_columns([
            pl.col("parent_facility_reference").cast(pl.String),
        ])

    collateral = None
    if collateral_data:
        # Add default collateral columns required by haircut calculator
        coll_n = len(list(collateral_data.values())[0])
        coll_defaults = {
            "issuer_type": [""] * coll_n,  # Empty string instead of None for type consistency
            "issuer_cqs": [1] * coll_n,  # Default CQS
            "is_main_index": [False] * coll_n,
            "is_eligible_financial_collateral": [True] * coll_n,  # Assume eligible by default
            "value_after_maturity_adj": [None] * coll_n,
        }
        for key, value in coll_defaults.items():
            if key not in collateral_data:
                collateral_data[key] = value
        collateral = pl.DataFrame(collateral_data).lazy()

    # Create empty CounterpartyLookup
    counterparty_lookup = CounterpartyLookup(
        counterparties=pl.LazyFrame(schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
        }),
        parent_mappings=pl.LazyFrame(schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }),
        ultimate_parent_mappings=pl.LazyFrame(schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }),
        rating_inheritance=pl.LazyFrame(schema={
            "counterparty_reference": pl.String,
            "cqs": pl.Int8,
            "pd": pl.Float64,
        }),
    )

    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=exposures.filter(pl.col("approach") == ApproachType.SA.value),
        irb_exposures=exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value) |
            (pl.col("approach") == ApproachType.AIRB.value)
        ),
        slotting_exposures=exposures.filter(pl.col("approach") == ApproachType.SLOTTING.value),
        equity_exposures=None,
        collateral=collateral,
        guarantees=None,
        provisions=None,
        counterparty_lookup=counterparty_lookup,
        classification_audit=None,
        classification_errors=[],
    )


# =============================================================================
# F-IRB LGD Tests
# =============================================================================


class TestFIRBLGDWithCollateral:
    """Tests for F-IRB effective LGD calculation with collateral."""

    def test_firb_financial_collateral_reduces_lgd_to_zero(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """F-IRB exposure fully secured by financial collateral should have LGD=0."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [None],  # F-IRB: supervisory LGD
                "seniority": ["senior"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["exposure"],
                "collateral_type": ["cash"],
                "market_value": [1200000.0],  # Over-collateralized
                "value_after_haircut": [1200000.0],  # Cash: 0% haircut
                "residual_maturity_years": [5.0],
                "currency": ["GBP"],
                "property_type": [None],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # Fully secured by cash: LGD should be 0%
        assert df["lgd_post_crm"][0] == pytest.approx(0.0, abs=0.01)

    def test_firb_real_estate_collateral_gives_35pct_lgd(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """F-IRB exposure fully secured by real estate should have LGD=35%."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [None],
                "seniority": ["senior"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["exposure"],
                "collateral_type": ["real_estate"],
                "market_value": [1500000.0],  # Over-collateralized
                "value_after_haircut": [1500000.0],
                "residual_maturity_years": [10.0],
                "currency": ["GBP"],
                "property_type": ["residential"],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # Fully secured by real estate: LGD should be 35%
        assert df["lgd_post_crm"][0] == pytest.approx(0.35, abs=0.01)

    def test_firb_partial_collateral_weighted_average_lgd(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """F-IRB partially secured exposure should have weighted average LGD."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [None],
                "seniority": ["senior"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["exposure"],
                "collateral_type": ["real_estate"],
                "market_value": [500000.0],  # 50% coverage
                "value_after_haircut": [500000.0],
                "residual_maturity_years": [10.0],
                "currency": ["GBP"],
                "property_type": ["residential"],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # 50% secured @ 35% LGD, 50% unsecured @ 45% LGD
        # Effective LGD = (0.35 * 500k + 0.45 * 500k) / 1M = 0.40
        assert df["lgd_post_crm"][0] == pytest.approx(0.40, abs=0.01)

    def test_firb_subordinated_unsecured_gets_75pct_lgd(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """F-IRB subordinated unsecured exposure should have LGD=75%."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [None],
                "seniority": ["subordinated"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            # No collateral
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # Subordinated unsecured: LGD should be 75%
        assert df["lgd_post_crm"][0] == pytest.approx(0.75, abs=0.01)


class TestAIRBLGDNoAdjustment:
    """Tests for A-IRB exposures keeping their modelled LGD."""

    def test_airb_keeps_modelled_lgd_with_collateral(
        self,
        processor: CRMProcessor,
        airb_config: CalculationConfig,
    ) -> None:
        """A-IRB exposure should keep modelled LGD even with collateral."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.AIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [0.25],  # A-IRB: modelled LGD
                "seniority": ["senior"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["exposure"],
                "collateral_type": ["cash"],
                "market_value": [1000000.0],
                "value_after_haircut": [1000000.0],
                "residual_maturity_years": [5.0],
                "currency": ["GBP"],
                "property_type": [None],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, airb_config)
        df = result.exposures.collect()

        # A-IRB should keep modelled LGD (0.25), not supervisory
        assert df["lgd_post_crm"][0] == pytest.approx(0.25, abs=0.01)


class TestMultiLevelCollateralForLGD:
    """Tests for multi-level collateral allocation for LGD calculation."""

    def test_facility_level_collateral_allocated_by_ead(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Facility-level collateral should be allocated pro-rata by EAD."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP001"],
                "parent_facility_reference": ["FAC001", "FAC001"],  # Same facility
                "exposure_class": [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value, ApproachType.FIRB.value],
                "drawn_amount": [600000.0, 400000.0],  # 60%/40% split
                "ead_pre_crm": [600000.0, 400000.0],
                "lgd": [None, None],
                "seniority": ["senior", "senior"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [date(2029, 1, 1), date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["FAC001"],  # Facility level
                "beneficiary_type": ["facility"],
                "collateral_type": ["cash"],
                "market_value": [500000.0],
                "value_after_haircut": [500000.0],
                "residual_maturity_years": [5.0],
                "currency": ["GBP"],
                "property_type": [None],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # EXP001: 600k EAD, gets 60% of 500k = 300k collateral
        # LGD = (0 * 300k + 0.45 * 300k) / 600k = 0.225
        exp1 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert exp1["lgd_post_crm"][0] == pytest.approx(0.225, abs=0.01)

        # EXP002: 400k EAD, gets 40% of 500k = 200k collateral
        # LGD = (0 * 200k + 0.45 * 200k) / 400k = 0.225
        exp2 = df.filter(pl.col("exposure_reference") == "EXP002")
        assert exp2["lgd_post_crm"][0] == pytest.approx(0.225, abs=0.01)

    def test_counterparty_level_collateral_allocated_by_ead(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Counterparty-level collateral should be allocated pro-rata by EAD."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP001"],  # Same counterparty
                "parent_facility_reference": [None, None],  # No facility
                "exposure_class": [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value, ApproachType.FIRB.value],
                "drawn_amount": [800000.0, 200000.0],  # 80%/20% split
                "ead_pre_crm": [800000.0, 200000.0],
                "lgd": [None, None],
                "seniority": ["senior", "senior"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [date(2029, 1, 1), date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["CP001"],  # Counterparty level
                "beneficiary_type": ["counterparty"],
                "collateral_type": ["real_estate"],
                "market_value": [500000.0],
                "value_after_haircut": [500000.0],
                "residual_maturity_years": [10.0],
                "currency": ["GBP"],
                "property_type": ["residential"],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # EXP001: 800k EAD, gets 80% of 500k = 400k collateral @ 35% LGD
        # LGD = (0.35 * 400k + 0.45 * 400k) / 800k = 0.40
        exp1 = df.filter(pl.col("exposure_reference") == "EXP001")
        assert exp1["lgd_post_crm"][0] == pytest.approx(0.40, abs=0.01)

        # EXP002: 200k EAD, gets 20% of 500k = 100k collateral @ 35% LGD
        # LGD = (0.35 * 100k + 0.45 * 100k) / 200k = 0.40
        exp2 = df.filter(pl.col("exposure_reference") == "EXP002")
        assert exp2["lgd_post_crm"][0] == pytest.approx(0.40, abs=0.01)


class TestCollateralCoverageAudit:
    """Tests for collateral coverage audit columns."""

    def test_collateral_coverage_percentage_calculated(
        self,
        processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """Collateral coverage percentage should be calculated for audit."""
        bundle = create_classified_bundle(
            exposures_data={
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "parent_facility_reference": [None],
                "exposure_class": [ExposureClass.CORPORATE.value],
                "approach": [ApproachType.FIRB.value],
                "drawn_amount": [1000000.0],
                "ead_pre_crm": [1000000.0],
                "lgd": [None],
                "seniority": ["senior"],
                "currency": ["GBP"],
                "maturity_date": [date(2029, 1, 1)],
            },
            collateral_data={
                "collateral_reference": ["COLL001"],
                "beneficiary_reference": ["EXP001"],
                "beneficiary_type": ["exposure"],
                "collateral_type": ["real_estate"],
                "market_value": [750000.0],  # 75% coverage
                "value_after_haircut": [750000.0],
                "residual_maturity_years": [10.0],
                "currency": ["GBP"],
                "property_type": ["residential"],
            },
        )

        result = processor.get_crm_adjusted_bundle(bundle, firb_config)
        df = result.exposures.collect()

        # Coverage should be 75%
        assert df["collateral_coverage_pct"][0] == pytest.approx(75.0, abs=0.1)
