"""Unit tests for the CRM Polars namespace.

Tests cover:
- Namespace registration and availability
- EAD waterfall initialization
- Collateral application (SA and IRB approaches)
- Guarantee application
- Provision application
- EAD finalization
- Full pipeline (apply_all_crm)
- Method chaining
- Audit trail generation

References:
- CRR Art. 110: Provision deduction
- CRR Art. 111: CCF application
- CRR Art. 213-217: Guarantee substitution
- CRR Art. 223-224: Collateral haircuts
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm import CRMLazyFrame  # noqa: F401 - imports register namespace


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basic_exposures() -> pl.LazyFrame:
    """Return basic exposures with EAD."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003"],
        "counterparty_reference": ["CP001", "CP002", "CP003"],
        "parent_facility_reference": ["FAC001", "FAC002", "FAC003"],
        "drawn_amount": [1_000_000.0, 500_000.0, 250_000.0],
        "interest": [0.0, 0.0, 0.0],
        "nominal_amount": [0.0, 0.0, 0.0],
        "ead_pre_crm": [1_000_000.0, 500_000.0, 250_000.0],
        "approach": [ApproachType.SA.value, ApproachType.SA.value, ApproachType.FIRB.value],
        "lgd": [0.45, 0.45, 0.45],
    })


@pytest.fixture
def collateral_data() -> pl.LazyFrame:
    """Return collateral data."""
    return pl.LazyFrame({
        "collateral_reference": ["COLL001", "COLL002"],
        "beneficiary_reference": ["EXP001", "EXP002"],
        "collateral_type": ["cash", "govt_bond"],
        "market_value": [200_000.0, 150_000.0],
        "value_after_haircut": [200_000.0, 145_000.0],
        "value_after_maturity_adj": [200_000.0, 140_000.0],
        "is_eligible_financial_collateral": [True, True],
    })


@pytest.fixture
def guarantee_data() -> pl.LazyFrame:
    """Return guarantee data."""
    return pl.LazyFrame({
        "guarantee_reference": ["GUAR001", "GUAR002"],
        "beneficiary_reference": ["EXP001", "EXP002"],
        "guarantor": ["CP100", "CP101"],
        "amount_covered": [300_000.0, 200_000.0],
    })


@pytest.fixture
def counterparty_lookup() -> pl.LazyFrame:
    """Return counterparty lookup data."""
    return pl.LazyFrame({
        "counterparty_reference": ["CP100", "CP101"],
        "entity_type": ["SOVEREIGN", "INSTITUTION"],
    })


@pytest.fixture
def rating_inheritance() -> pl.LazyFrame:
    """Return rating inheritance data."""
    return pl.LazyFrame({
        "counterparty_reference": ["CP100", "CP101"],
        "cqs": [1, 2],
    })


@pytest.fixture
def provision_data() -> pl.LazyFrame:
    """Return provision data."""
    return pl.LazyFrame({
        "provision_reference": ["PROV001", "PROV002"],
        "beneficiary_reference": ["EXP001", "EXP003"],
        "amount": [50_000.0, 25_000.0],
        "provision_type": ["specific", "specific"],
    })


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestCRMNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, basic_exposures: pl.LazyFrame) -> None:
        """LazyFrame should have .crm namespace available."""
        assert hasattr(basic_exposures, "crm")

    def test_namespace_methods_available(self, basic_exposures: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        crm = basic_exposures.crm
        expected_methods = [
            "initialize_ead_waterfall",
            "apply_collateral",
            "apply_collateral_to_lgd",
            "apply_guarantees",
            "resolve_provisions",
            "finalize_ead",
            "apply_all_crm",
            "build_ead_audit",
        ]
        for method in expected_methods:
            assert hasattr(crm, method), f"Missing method: {method}"


# =============================================================================
# EAD Waterfall Initialization Tests
# =============================================================================


class TestInitializeEADWaterfall:
    """Tests for EAD waterfall initialization."""

    def test_adds_waterfall_columns(self, basic_exposures: pl.LazyFrame) -> None:
        """initialize_ead_waterfall should add all EAD tracking columns."""
        result = basic_exposures.crm.initialize_ead_waterfall().collect()

        expected_columns = [
            "ead_gross",
            "ead_after_collateral",
            "ead_after_guarantee",
            "ead_final",
            "collateral_allocated",
            "collateral_adjusted_value",
            "guarantee_amount",
            "provision_allocated",
            "lgd_pre_crm",
            "lgd_post_crm",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_initializes_ead_from_ead_pre_crm(self, basic_exposures: pl.LazyFrame) -> None:
        """EAD columns should be initialized from ead_pre_crm."""
        result = basic_exposures.crm.initialize_ead_waterfall().collect()

        # All EAD columns should equal ead_pre_crm initially
        for col in ["ead_gross", "ead_after_collateral", "ead_after_guarantee", "ead_final"]:
            for i in range(len(result)):
                assert result[col][i] == pytest.approx(result["ead_pre_crm"][i])

    def test_initializes_collateral_guarantee_to_zero(self, basic_exposures: pl.LazyFrame) -> None:
        """Collateral and guarantee amounts should be initialized to zero."""
        result = basic_exposures.crm.initialize_ead_waterfall().collect()

        for col in ["collateral_allocated", "collateral_adjusted_value", "guarantee_amount", "provision_allocated"]:
            for value in result[col]:
                assert value == pytest.approx(0.0)


# =============================================================================
# Collateral Application Tests
# =============================================================================


class TestApplyCollateral:
    """Tests for collateral application."""

    def test_sa_ead_reduced_by_collateral(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """SA approach should have EAD reduced by collateral."""
        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_data, crr_config)
            .collect()
        )

        # EXP001 has SA approach and 200,000 collateral (after maturity adj)
        # EAD should be 1,000,000 - 200,000 = 800,000
        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["ead_after_collateral"][0] == pytest.approx(800_000.0)

    def test_irb_ead_not_reduced(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """IRB approach should not have EAD reduced by collateral."""
        # Add collateral for IRB exposure
        collateral_with_irb = collateral_data.with_columns([
            pl.when(pl.col("beneficiary_reference") == "EXP001")
            .then(pl.lit("EXP003"))  # Change to IRB exposure
            .otherwise(pl.col("beneficiary_reference"))
            .alias("beneficiary_reference")
        ])

        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_with_irb, crr_config)
            .collect()
        )

        # EXP003 has FIRB approach, EAD should remain unchanged
        exp003 = result.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["ead_after_collateral"][0] == pytest.approx(250_000.0)

    def test_exposure_without_collateral_unchanged(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposures without collateral should have unchanged EAD."""
        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_data, crr_config)
            .collect()
        )

        # EXP003 has no collateral
        exp003 = result.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["ead_after_collateral"][0] == pytest.approx(250_000.0)


# =============================================================================
# Guarantee Application Tests
# =============================================================================


class TestApplyGuarantees:
    """Tests for guarantee application."""

    def test_guarantee_columns_added(
        self,
        basic_exposures: pl.LazyFrame,
        guarantee_data: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        rating_inheritance: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_guarantees should add guarantee-related columns."""
        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_guarantees(guarantee_data, counterparty_lookup, crr_config, rating_inheritance)
            .collect()
        )

        assert "guarantee_amount" in result.columns
        assert "guaranteed_portion" in result.columns
        assert "unguaranteed_portion" in result.columns
        assert "guarantor_entity_type" in result.columns
        assert "guarantor_cqs" in result.columns

    def test_guaranteed_portion_calculated(
        self,
        basic_exposures: pl.LazyFrame,
        guarantee_data: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        rating_inheritance: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Guaranteed portion should be calculated correctly."""
        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_guarantees(guarantee_data, counterparty_lookup, crr_config, rating_inheritance)
            .collect()
        )

        # EXP001 has 300,000 guarantee on 1,000,000 EAD
        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["guaranteed_portion"][0] == pytest.approx(300_000.0)
        assert exp001["unguaranteed_portion"][0] == pytest.approx(700_000.0)

    def test_guarantee_capped_at_ead(
        self,
        basic_exposures: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        rating_inheritance: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Guaranteed portion should be capped at EAD."""
        # Create guarantee larger than EAD
        large_guarantee = pl.LazyFrame({
            "guarantee_reference": ["GUAR001"],
            "beneficiary_reference": ["EXP003"],  # EAD = 250,000
            "guarantor": ["CP100"],
            "amount_covered": [500_000.0],  # Larger than EAD
        })

        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_guarantees(large_guarantee, counterparty_lookup, crr_config, rating_inheritance)
            .collect()
        )

        exp003 = result.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["guaranteed_portion"][0] == pytest.approx(250_000.0)  # Capped at EAD


# =============================================================================
# Provision Application Tests
# =============================================================================


class TestApplyProvisions:
    """Tests for provision application."""

    def test_provision_allocated_calculated(
        self,
        basic_exposures: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Provision allocated should be calculated."""
        result = (basic_exposures
            .crm.resolve_provisions(provision_data, crr_config)
            .collect()
        )

        # EXP001 has 50,000 provision
        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["provision_allocated"][0] == pytest.approx(50_000.0)

    def test_sa_provision_deducted(
        self,
        basic_exposures: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """SA approach should have provision deducted from EAD."""
        result = (basic_exposures
            .crm.resolve_provisions(provision_data, crr_config)
            .collect()
        )

        # EXP001 has SA approach and 50,000 provision
        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["provision_deducted"][0] == pytest.approx(50_000.0)

    def test_irb_provision_not_deducted(
        self,
        basic_exposures: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """IRB approach should not have provision deducted from EAD."""
        result = (basic_exposures
            .crm.resolve_provisions(provision_data, crr_config)
            .collect()
        )

        # EXP003 has FIRB approach and 25,000 provision
        exp003 = result.filter(pl.col("exposure_reference") == "EXP003")
        assert exp003["provision_deducted"][0] == pytest.approx(0.0)


# =============================================================================
# EAD Finalization Tests
# =============================================================================


class TestFinalizeEAD:
    """Tests for EAD finalization."""

    def test_ead_final_after_provision_deduction(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """ead_final should reflect provision deduction (provision baked into ead_pre_crm)."""
        # New pipeline order: resolve_provisions → initialize → collateral → finalize
        result = (basic_exposures
            .crm.resolve_provisions(provision_data, crr_config)
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_data, crr_config)
            .crm.finalize_ead()
            .collect()
        )

        # EXP001: drawn=1M, provision_on_drawn=50k → ead_pre_crm = 950k
        # collateral = 200k → ead_final = 950k - 200k = 750k
        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["ead_final"][0] == pytest.approx(750_000.0)

    def test_ead_final_non_negative(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """ead_final should not be negative even with large deductions."""
        exposures = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "ead_pre_crm": [100_000.0],
            "approach": [ApproachType.SA.value],
        })

        collateral = pl.LazyFrame({
            "collateral_reference": ["COLL001"],
            "beneficiary_reference": ["EXP001"],
            "collateral_type": ["cash"],
            "market_value": [150_000.0],  # More than EAD
            "value_after_haircut": [150_000.0],
            "is_eligible_financial_collateral": [True],
        })

        result = (exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral, crr_config)
            .crm.finalize_ead()
            .collect()
        )

        assert result["ead_final"][0] >= 0


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestApplyAllCRM:
    """Tests for full CRM pipeline."""

    def test_apply_all_crm_with_all_inputs(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        guarantee_data: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        rating_inheritance: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_all_crm should apply full CRM pipeline."""
        result = basic_exposures.crm.apply_all_crm(
            collateral=collateral_data,
            guarantees=guarantee_data,
            provisions=provision_data,
            counterparty_lookup=counterparty_lookup,
            config=crr_config,
            rating_inheritance=rating_inheritance,
        ).collect()

        # Check all expected columns exist
        expected_columns = [
            "ead_gross",
            "ead_after_collateral",
            "ead_final",
            "collateral_adjusted_value",
            "guarantee_amount",
            "provision_allocated",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_apply_all_crm_with_none_inputs(
        self,
        basic_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_all_crm should work with None inputs."""
        result = basic_exposures.crm.apply_all_crm(
            collateral=None,
            guarantees=None,
            provisions=None,
            counterparty_lookup=None,
            config=crr_config,
        ).collect()

        # EAD should remain unchanged
        for i in range(len(result)):
            assert result["ead_final"][i] == pytest.approx(result["ead_gross"][i])


# =============================================================================
# Method Chaining Tests
# =============================================================================


class TestMethodChaining:
    """Tests for method chaining."""

    def test_full_pipeline_chain(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        provision_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Full pipeline should work with method chaining."""
        result = (basic_exposures
            .crm.resolve_provisions(provision_data, crr_config)
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_data, crr_config)
            .crm.finalize_ead()
            .collect()
        )

        assert "ead_final" in result.columns
        assert "collateral_adjusted_value" in result.columns
        assert "provision_deducted" in result.columns


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestBuildEADAudit:
    """Tests for audit trail generation."""

    def test_build_ead_audit_includes_calculation_string(
        self,
        basic_exposures: pl.LazyFrame,
        collateral_data: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """build_ead_audit should include crm_calculation string."""
        result = (basic_exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral_data, crr_config)
            .crm.finalize_ead()
            .crm.build_ead_audit()
            .collect()
        )

        assert "crm_calculation" in result.columns
        calc_str = result["crm_calculation"][0]
        assert "EAD:" in calc_str
        assert "gross=" in calc_str
        assert "final=" in calc_str
