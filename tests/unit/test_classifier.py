"""Unit tests for the exposure classifier module.

Tests cover:
- Exposure class determination based on counterparty type
- SME classification and thresholds
- Retail classification and aggregate exposure thresholds
- Default identification
- Approach assignment based on IRB permissions
- Exposure splitting by approach
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import (
    ClassificationError,
    ExposureClassifier,
    create_exposure_classifier,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration with SA only."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crr_config_with_irb() -> CalculationConfig:
    """Return a CRR configuration with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def corporate_counterparties() -> pl.LazyFrame:
    """Counterparties with various corporate types."""
    return pl.DataFrame({
        "counterparty_reference": [
            "CORP_LARGE",  # Large corporate
            "CORP_SME",  # SME corporate
            "CORP_MICRO",  # Micro SME
            "CORP_UNRATED",  # Unrated corporate
        ],
        "counterparty_name": [
            "Large Corp Ltd",
            "SME Corp Ltd",
            "Micro Corp Ltd",
            "Unrated Corp Ltd",
        ],
        "entity_type": ["corporate", "corporate", "corporate", "corporate"],
        "country_code": ["GB", "GB", "GB", "GB"],
        "annual_revenue": [
            100000000.0,  # GBP 100m - above SME threshold
            30000000.0,   # GBP 30m - SME
            1000000.0,    # GBP 1m - Micro SME
            20000000.0,   # GBP 20m - SME
        ],
        "total_assets": [500000000.0, 150000000.0, 5000000.0, 100000000.0],
        "default_status": [False, False, False, False],
        "sector_code": ["MANU", "MANU", "SERV", "TECH"],
        "is_regulated": [True, True, True, True],
        "is_managed_as_retail": [False, False, False, False],
    }).lazy()


@pytest.fixture
def mixed_counterparties() -> pl.LazyFrame:
    """Counterparties with various entity types."""
    return pl.DataFrame({
        "counterparty_reference": [
            "SOV_UK",      # Sovereign
            "INST_UK",     # Institution (bank)
            "CORP_UK",     # Corporate
            "RETAIL_IND",  # Individual (retail)
            "PSE_UK",      # PSE (with institution IRB treatment)
            "MDB_001",     # MDB
        ],
        "counterparty_name": [
            "UK Government",
            "Barclays Bank",
            "UK Corp Ltd",
            "John Smith",
            "NHS Trust",
            "World Bank",
        ],
        "entity_type": [
            "sovereign",
            "bank",
            "corporate",
            "individual",
            "pse_institution",  # PSE with institution IRB treatment
            "mdb",              # MDB entity type
        ],
        "country_code": ["GB", "GB", "GB", "GB", "GB", "INT"],
        "annual_revenue": [0.0, 5000000000.0, 50000000.0, 0.0, 0.0, 0.0],
        "total_assets": [0.0, 100000000000.0, 250000000.0, 0.0, 0.0, 0.0],
        "default_status": [False, False, False, False, False, False],
        "sector_code": ["GOVT", "BANK", "MANU", "RETAIL", "HEALTH", "MDB"],
        "is_regulated": [True, True, True, True, True, True],
        "is_managed_as_retail": [False, False, False, False, False, False],
    }).lazy()


@pytest.fixture
def retail_counterparties() -> pl.LazyFrame:
    """Counterparties for retail classification testing."""
    return pl.DataFrame({
        "counterparty_reference": [
            "RTL_SMALL",   # Small retail exposure
            "RTL_LARGE",   # Large retail (exceeds threshold)
            "RTL_MTG",     # Mortgage customer
        ],
        "counterparty_name": ["Small Borrower", "Large Borrower", "Mortgage Customer"],
        "entity_type": ["individual", "individual", "individual"],
        "country_code": ["GB", "GB", "GB"],
        "annual_revenue": [0.0, 0.0, 0.0],
        "total_assets": [0.0, 0.0, 0.0],
        "default_status": [False, False, False],
        "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
        "is_regulated": [True, True, True],
        "is_managed_as_retail": [False, False, False],
    }).lazy()


@pytest.fixture
def defaulted_counterparties() -> pl.LazyFrame:
    """Counterparties in default status."""
    return pl.DataFrame({
        "counterparty_reference": ["DEFAULT_CORP", "PERFORMING_CORP"],
        "counterparty_name": ["Defaulted Corp", "Performing Corp"],
        "entity_type": ["corporate", "corporate"],
        "country_code": ["GB", "GB"],
        "annual_revenue": [10000000.0, 10000000.0],
        "total_assets": [50000000.0, 50000000.0],
        "default_status": [True, False],  # First one is in default
        "sector_code": ["MANU", "MANU"],
        "is_regulated": [True, True],
        "is_managed_as_retail": [False, False],
    }).lazy()


@pytest.fixture
def simple_exposures() -> pl.LazyFrame:
    """Simple exposures for testing."""
    return pl.DataFrame({
        "exposure_reference": ["EXP001", "EXP002", "EXP003", "EXP004"],
        "exposure_type": ["loan", "loan", "loan", "contingent"],
        "product_type": ["TERM_LOAN", "TERM_LOAN", "MORTGAGE", "LC"],
        "book_code": ["CORP", "SME", "RETAIL", "CORP"],
        "counterparty_reference": ["CORP_LARGE", "CORP_SME", "RTL_MTG", "CORP_UNRATED"],
        "value_date": [date(2023, 1, 1)] * 4,
        "maturity_date": [date(2028, 1, 1)] * 4,
        "currency": ["GBP", "GBP", "GBP", "GBP"],
        "drawn_amount": [5000000.0, 1000000.0, 300000.0, 0.0],
        "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
        "nominal_amount": [0.0, 0.0, 0.0, 500000.0],
        "lgd": [0.45, 0.45, 0.15, 0.45],
        "seniority": ["senior", "senior", "senior", "senior"],
                "exposure_has_parent": [False, False, False, False],
        "root_facility_reference": [None, None, None, None],
        "facility_hierarchy_depth": [1, 1, 1, 1],
        "counterparty_has_parent": [False, False, False, False],
        "parent_counterparty_reference": [None, None, None, None],
        "rating_inherited": [False, False, False, False],
        "rating_source_counterparty": [None, None, None, None],
        "rating_inheritance_reason": ["own_rating", "own_rating", "unrated", "unrated"],
        "ultimate_parent_reference": [None, None, None, None],
        "counterparty_hierarchy_depth": [1, 1, 1, 1],
        "lending_group_reference": [None, None, None, None],
        "lending_group_total_exposure": [0.0, 0.0, 0.0, 0.0],
    }).lazy()


@pytest.fixture
def mixed_exposures() -> pl.LazyFrame:
    """Exposures for various counterparty types."""
    return pl.DataFrame({
        "exposure_reference": [
            "SOV_EXP", "INST_EXP", "CORP_EXP", "RTL_EXP", "PSE_EXP", "MDB_EXP"
        ],
        "exposure_type": ["loan"] * 6,
        "product_type": ["GOVT_BOND", "INTERBANK", "TERM_LOAN", "PERSONAL", "LOAN", "LOAN"],
        "book_code": ["GOVT", "FI", "CORP", "RETAIL", "PSE", "MDB"],
        "counterparty_reference": [
            "SOV_UK", "INST_UK", "CORP_UK", "RETAIL_IND", "PSE_UK", "MDB_001"
        ],
        "value_date": [date(2023, 1, 1)] * 6,
        "maturity_date": [date(2028, 1, 1)] * 6,
        "currency": ["GBP"] * 6,
        "drawn_amount": [10000000.0, 5000000.0, 2000000.0, 50000.0, 1000000.0, 500000.0],
        "undrawn_amount": [0.0] * 6,
        "nominal_amount": [0.0] * 6,
        "lgd": [0.45] * 6,
        "seniority": ["senior"] * 6,
                "exposure_has_parent": [False] * 6,
        "root_facility_reference": [None] * 6,
        "facility_hierarchy_depth": [1] * 6,
        "counterparty_has_parent": [False] * 6,
        "parent_counterparty_reference": [None] * 6,
        "rating_inherited": [False] * 6,
        "rating_source_counterparty": [None] * 6,
        "rating_inheritance_reason": ["own_rating"] * 6,
        "ultimate_parent_reference": [None] * 6,
        "counterparty_hierarchy_depth": [1] * 6,
        "lending_group_reference": [None] * 6,
        "lending_group_total_exposure": [0.0] * 6,
    }).lazy()


def create_resolved_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    residential_collateral_value: float = 0.0,
    lending_group_adjusted_exposure: float | None = None,
) -> ResolvedHierarchyBundle:
    """Helper to create a ResolvedHierarchyBundle for testing.

    Args:
        exposures: Exposures LazyFrame
        counterparties: Counterparties LazyFrame
        residential_collateral_value: Optional residential collateral value per exposure
        lending_group_adjusted_exposure: Optional adjusted exposure for lending group
            (defaults to lending_group_total_exposure if not specified)
    """
    # Add hierarchy columns to counterparties
    enriched_cp = counterparties.with_columns([
        pl.lit(False).alias("counterparty_has_parent"),
        pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
        pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
        pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
        pl.lit(False).alias("rating_inherited"),
        pl.lit(None).cast(pl.String).alias("rating_source_counterparty"),
        pl.lit("own_rating").alias("rating_inheritance_reason"),
        pl.lit(None).cast(pl.Int8).alias("cqs"),
        pl.lit(None).cast(pl.String).alias("rating_value"),
        pl.lit(None).cast(pl.String).alias("rating_agency"),
    ])

    # Add residential property exclusion columns to exposures if not present
    exp_schema = exposures.collect_schema()
    if "residential_collateral_value" not in exp_schema.names():
        exposures = exposures.with_columns([
            pl.lit(residential_collateral_value).alias("residential_collateral_value"),
        ])
    if "exposure_for_retail_threshold" not in exp_schema.names():
        exposures = exposures.with_columns([
            (pl.col("drawn_amount") + pl.col("nominal_amount") -
             pl.col("residential_collateral_value")).alias("exposure_for_retail_threshold"),
        ])
    if "lending_group_adjusted_exposure" not in exp_schema.names():
        # Default to lending_group_total_exposure if adjusted not specified
        if lending_group_adjusted_exposure is not None:
            exposures = exposures.with_columns([
                pl.lit(lending_group_adjusted_exposure).alias("lending_group_adjusted_exposure"),
            ])
        else:
            exposures = exposures.with_columns([
                pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
            ])

    return ResolvedHierarchyBundle(
        exposures=exposures,
        counterparty_lookup=CounterpartyLookup(
            counterparties=enriched_cp,
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
                "rating_value": pl.String,
                "inherited": pl.Boolean,
                "source_counterparty": pl.String,
                "inheritance_reason": pl.String,
            }),
        ),
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        lending_group_totals=pl.LazyFrame(schema={
            "lending_group_reference": pl.String,
            "total_drawn": pl.Float64,
            "total_nominal": pl.Float64,
            "total_exposure": pl.Float64,
            "adjusted_exposure": pl.Float64,
            "total_residential_coverage": pl.Float64,
            "exposure_count": pl.UInt32,
        }),
    )


# =============================================================================
# Exposure Class Determination Tests
# =============================================================================


class TestExposureClassDetermination:
    """Tests for exposure class assignment."""

    def test_sovereign_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Sovereign counterparty should be classified as SOVEREIGN."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        sov = df.filter(pl.col("exposure_reference") == "SOV_EXP")

        assert sov["exposure_class"][0] == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value

    def test_institution_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Bank counterparty should be classified as INSTITUTION."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        inst = df.filter(pl.col("exposure_reference") == "INST_EXP")

        assert inst["exposure_class"][0] == ExposureClass.INSTITUTION.value

    def test_corporate_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Corporate counterparty should be classified as CORPORATE."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        corp = df.filter(pl.col("exposure_reference") == "CORP_EXP")

        # Large corporate (revenue > threshold) stays as CORPORATE
        assert corp["exposure_class"][0] == ExposureClass.CORPORATE.value

    def test_retail_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Individual counterparty should be classified as RETAIL_OTHER."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        retail = df.filter(pl.col("exposure_reference") == "RTL_EXP")

        assert retail["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value

    def test_pse_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """PSE counterparty should be classified as PSE."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        pse = df.filter(pl.col("exposure_reference") == "PSE_EXP")

        assert pse["exposure_class"][0] == ExposureClass.PSE.value

    def test_mdb_classification(
        self,
        classifier: ExposureClassifier,
        mixed_exposures: pl.LazyFrame,
        mixed_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """MDB counterparty should be classified as MDB."""
        bundle = create_resolved_bundle(mixed_exposures, mixed_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        mdb = df.filter(pl.col("exposure_reference") == "MDB_EXP")

        assert mdb["exposure_class"][0] == ExposureClass.MDB.value


# =============================================================================
# SME Classification Tests
# =============================================================================


class TestSMEClassification:
    """Tests for SME classification."""

    def test_large_corporate_not_sme(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Corporate with revenue > EUR 50m should NOT be SME."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["LARGE_CORP"],
            "counterparty_name": ["Large Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [60000000.0],  # GBP 60m > threshold
            "total_assets": [300000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["LARGE_CORP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [5000000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["own_rating"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
        assert df["is_sme"][0] is False

    def test_sme_corporate_classified_correctly(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Corporate with revenue < EUR 50m (GBP 44m) should be SME."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["SME_CORP"],
            "counterparty_name": ["SME Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [30000000.0],  # GBP 30m < 44m threshold
            "total_assets": [150000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["SME"],
            "counterparty_reference": ["SME_CORP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1000000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["own_rating"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["is_sme"][0] is True

    def test_sme_threshold_boundary(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Corporate at exactly EUR 50m (GBP 44m) should NOT be SME."""
        threshold_gbp = float(Decimal("50000000") * Decimal("0.88"))  # 44m

        counterparties = pl.DataFrame({
            "counterparty_reference": ["BOUNDARY_CORP"],
            "counterparty_name": ["Boundary Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [threshold_gbp],  # Exactly at threshold
            "total_assets": [200000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["BOUNDARY_CORP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [2000000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["own_rating"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        # At exactly the threshold, should NOT be SME (< threshold required)
        assert df["is_sme"][0] is False


# =============================================================================
# Retail Classification Tests
# =============================================================================


class TestRetailClassification:
    """Tests for retail classification and threshold checks."""

    def test_mortgage_classified_as_retail_mortgage(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Mortgage product should be classified as RETAIL_MORTGAGE."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["MTG_CUST"],
            "counterparty_name": ["Mortgage Customer"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "annual_revenue": [0.0],
            "total_assets": [0.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["MTG001"],
            "exposure_type": ["loan"],
            "product_type": ["RESIDENTIAL_MORTGAGE"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["MTG_CUST"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2048, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [300000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.15],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["unrated"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["is_mortgage"][0] is True

    def test_retail_within_threshold_qualifies(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Retail exposure within threshold should qualify as retail."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["RTL_SMALL"],
            "counterparty_name": ["Small Borrower"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "annual_revenue": [0.0],
            "total_assets": [0.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["RTL001"],
            "exposure_type": ["loan"],
            "product_type": ["PERSONAL_LOAN"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["RTL_SMALL"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [50000.0],  # Well below 880k threshold
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["unrated"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_residential_property_excluded_from_threshold(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Residential property collateral should be excluded from EUR 1m threshold.

        Per CRR Art. 123(c), exposures secured by residential property (SA treatment)
        are excluded from the retail threshold aggregation.

        Scenario: EUR 2m total exposure, EUR 1.2m secured by residential property
        Adjusted exposure = EUR 2m - EUR 1.2m = EUR 0.8m (< EUR 1m threshold)
        Result: Should qualify as retail
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["SME_RES_PROP"],
            "counterparty_name": ["SME with Residential Collateral"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "annual_revenue": [0.0],
            "total_assets": [0.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_regulated": [True],
            "is_managed_as_retail": [True],
        }).lazy()

        # Total exposure = 1,760,000 GBP (2m EUR equivalent)
        # Residential collateral = 1,056,000 GBP (1.2m EUR equivalent)
        # Adjusted exposure = 704,000 GBP (< 880k threshold)
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP_RES_PROP"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["SME_RES_PROP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1760000.0],  # 2m EUR equivalent - above threshold raw
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["unrated"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            # Residential property exclusion columns
            "residential_collateral_value": [1056000.0],  # 1.2m EUR equivalent
            "exposure_for_retail_threshold": [704000.0],  # Below 880k threshold
            "lending_group_adjusted_exposure": [0.0],  # Standalone
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True
        assert df["retail_threshold_exclusion_applied"][0] is True
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value

    def test_sme_exceeding_threshold_moves_to_corporate_sme(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """SME exceeding retail threshold should be reclassified to CORPORATE_SME.

        Scenario: SME with EUR 1.5m exposure, no residential property collateral
        Adjusted exposure = EUR 1.5m (> EUR 1m threshold)
        Result: Should be reclassified to CORPORATE_SME (retains firm-size adjustment)
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["SME_OVER_THRESHOLD"],
            "counterparty_name": ["SME Over Threshold"],
            "entity_type": ["retail"],  # Small business managed as retail
            "country_code": ["GB"],
            "annual_revenue": [20000000.0],  # 20m GBP - qualifies as SME
            "total_assets": [50000000.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_regulated": [True],
            "is_managed_as_retail": [True],
        }).lazy()

        # Total exposure = 1,320,000 GBP (1.5m EUR equivalent)
        # No residential collateral - exceeds threshold
        exposures = pl.DataFrame({
            "exposure_reference": ["SME_OVER"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["SME_OVER_THRESHOLD"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1320000.0],  # 1.5m EUR equivalent - above threshold
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["unrated"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            # No residential property exclusion
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [1320000.0],  # Above 880k threshold
            "lending_group_adjusted_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is False
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value
        assert df["is_sme"][0] is True

    def test_mortgage_stays_retail_regardless_of_threshold(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """SA residential mortgage should stay as RETAIL_MORTGAGE even if exceeding threshold.

        Per CRR Art. 112(i), residential mortgages are assigned to the residential
        property exposure class and are excluded from the EUR 1m aggregation.
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["MTG_LARGE"],
            "counterparty_name": ["Large Mortgage Customer"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "annual_revenue": [0.0],
            "total_assets": [0.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        # Large mortgage - EUR 1.5m equivalent
        exposures = pl.DataFrame({
            "exposure_reference": ["MTG_LARGE_001"],
            "exposure_type": ["loan"],
            "product_type": ["RESIDENTIAL_MORTGAGE"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["MTG_LARGE"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2048, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1320000.0],  # Above EUR 1m threshold
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.15],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["unrated"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            "residential_collateral_value": [1320000.0],  # Fully secured
            "exposure_for_retail_threshold": [0.0],  # Excluded from threshold
            "lending_group_adjusted_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()
        # Mortgage stays as RETAIL_MORTGAGE regardless of threshold
        assert df["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value
        assert df["is_mortgage"][0] is True

    def test_lending_group_with_residential_property_exclusion(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Lending group threshold should use adjusted exposure excluding residential RE.

        Scenario: Lending group with EUR 2.5m total exposure
        - Member 1: EUR 1m term loan (no residential collateral)
        - Member 2: EUR 1.5m mortgage (fully secured by residential RE)
        Adjusted exposure = EUR 2.5m - EUR 1.5m = EUR 1m (at threshold)
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["LG_MEMBER_1", "LG_MEMBER_2"],
            "counterparty_name": ["LG Member 1", "LG Member 2"],
            "entity_type": ["individual", "individual"],
            "country_code": ["GB", "GB"],
            "annual_revenue": [0.0, 0.0],
            "total_assets": [0.0, 0.0],
            "default_status": [False, False],
            "sector_code": ["RETAIL", "RETAIL"],
            "is_regulated": [True, True],
            "is_managed_as_retail": [True, True],
        }).lazy()

        # Lending group total = EUR 2.5m in GBP at 0.8732 rate
        # Member 1: EUR 1m = 873,200 GBP (term loan, no residential)
        # Member 2: EUR 1.5m = 1,309,800 GBP (mortgage, fully secured by residential RE)
        # Adjusted = 873,200 GBP (at threshold) after excluding residential
        exposures = pl.DataFrame({
            "exposure_reference": ["LG_EXP_1", "LG_EXP_2"],
            "exposure_type": ["loan", "loan"],
            "product_type": ["TERM_LOAN", "RESIDENTIAL_MORTGAGE"],
            "book_code": ["RETAIL", "RETAIL"],
            "counterparty_reference": ["LG_MEMBER_1", "LG_MEMBER_2"],
            "value_date": [date(2023, 1, 1), date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1), date(2048, 1, 1)],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [873200.0, 1309800.0],  # EUR 1m + EUR 1.5m at 0.8732
            "undrawn_amount": [0.0, 0.0],
            "nominal_amount": [0.0, 0.0],
            "lgd": [0.45, 0.15],
            "seniority": ["senior", "senior"],
                        "exposure_has_parent": [False, False],
            "root_facility_reference": [None, None],
            "facility_hierarchy_depth": [1, 1],
            "counterparty_has_parent": [False, False],
            "parent_counterparty_reference": [None, None],
            "rating_inherited": [False, False],
            "rating_source_counterparty": [None, None],
            "rating_inheritance_reason": ["unrated", "unrated"],
            "ultimate_parent_reference": [None, None],
            "counterparty_hierarchy_depth": [1, 1],
            "lending_group_reference": ["LG_PARENT", "LG_PARENT"],
            "lending_group_total_exposure": [2183000.0, 2183000.0],  # EUR 2.5m at 0.8732
            # Residential exclusion: mortgage fully secured
            "residential_collateral_value": [0.0, 1309800.0],
            "exposure_for_retail_threshold": [873200.0, 0.0],
            "lending_group_adjusted_exposure": [873200.0, 873200.0],  # At threshold
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()

        # Term loan should qualify as retail (adjusted group exposure at threshold)
        term_loan = df.filter(pl.col("exposure_reference") == "LG_EXP_1")
        assert term_loan["qualifies_as_retail"][0] is True
        assert term_loan["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value

        # Mortgage should be RETAIL_MORTGAGE
        mortgage = df.filter(pl.col("exposure_reference") == "LG_EXP_2")
        assert mortgage["exposure_class"][0] == ExposureClass.RETAIL_MORTGAGE.value


# =============================================================================
# Default Classification Tests
# =============================================================================


class TestDefaultClassification:
    """Tests for defaulted exposure identification."""

    def test_defaulted_counterparty_flagged(
        self,
        classifier: ExposureClassifier,
        defaulted_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty in default should flag exposure as defaulted."""
        exposures = pl.DataFrame({
            "exposure_reference": ["DEF_EXP", "PERF_EXP"],
            "exposure_type": ["loan", "loan"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["DEFAULT_CORP", "PERFORMING_CORP"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "drawn_amount": [1000000.0, 1000000.0],
            "undrawn_amount": [0.0, 0.0],
            "nominal_amount": [0.0, 0.0],
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
                        "exposure_has_parent": [False, False],
            "root_facility_reference": [None, None],
            "facility_hierarchy_depth": [1, 1],
            "counterparty_has_parent": [False, False],
            "parent_counterparty_reference": [None, None],
            "rating_inherited": [False, False],
            "rating_source_counterparty": [None, None],
            "rating_inheritance_reason": ["own_rating", "own_rating"],
            "ultimate_parent_reference": [None, None],
            "counterparty_hierarchy_depth": [1, 1],
            "lending_group_reference": [None, None],
            "lending_group_total_exposure": [0.0, 0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, defaulted_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()

        # Defaulted exposure
        defaulted = df.filter(pl.col("exposure_reference") == "DEF_EXP")
        assert defaulted["is_defaulted"][0] is True
        assert defaulted["exposure_class_for_sa"][0] == ExposureClass.DEFAULTED.value

        # Performing exposure
        performing = df.filter(pl.col("exposure_reference") == "PERF_EXP")
        assert performing["is_defaulted"][0] is False


# =============================================================================
# Approach Assignment Tests
# =============================================================================


class TestApproachAssignment:
    """Tests for calculation approach assignment."""

    def test_sa_only_config_assigns_sa(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """SA-only config should assign SA approach to all exposures."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.collect()

        # All exposures should have SA approach
        assert (df["approach"] == ApproachType.SA.value).all()

    def test_irb_config_assigns_irb(
        self,
        classifier: ExposureClassifier,
        crr_config_with_irb: CalculationConfig,
    ) -> None:
        """IRB config should assign appropriate IRB approach."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["CORP001"],
            "counterparty_name": ["Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [100000000.0],
            "total_assets": [500000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [True],
            "is_managed_as_retail": [False],
        }).lazy()

        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CORP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [5000000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
                        "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "rating_inherited": [False],
            "rating_source_counterparty": [None],
            "rating_inheritance_reason": ["own_rating"],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
        }).lazy()

        bundle = create_resolved_bundle(exposures, counterparties)
        result = classifier.classify(bundle, crr_config_with_irb)

        df = result.all_exposures.collect()

        # With full IRB permissions, corporate should get A-IRB
        assert df["approach"][0] == ApproachType.AIRB.value


# =============================================================================
# Exposure Splitting Tests
# =============================================================================


class TestExposureSplitting:
    """Tests for splitting exposures by approach."""

    def test_sa_exposures_filtered_correctly(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """SA exposures should be correctly filtered."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        sa_df = result.sa_exposures.collect()

        # All exposures should be in SA (SA-only config)
        assert len(sa_df) == 4

    def test_irb_exposures_empty_for_sa_only(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """IRB exposures should be empty for SA-only config."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        irb_df = result.irb_exposures.collect()

        # No IRB exposures with SA-only config
        assert len(irb_df) == 0


# =============================================================================
# Classification Audit Tests
# =============================================================================


class TestClassificationAudit:
    """Tests for classification audit trail."""

    def test_audit_trail_populated(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Classification audit trail should be populated."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        audit_df = result.classification_audit.collect()

        # Audit should have same number of rows as exposures
        assert len(audit_df) == 4

        # Audit should have required columns
        assert "exposure_reference" in audit_df.columns
        assert "exposure_class" in audit_df.columns
        assert "approach" in audit_df.columns
        assert "classification_reason" in audit_df.columns


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateExposureClassifier:
    """Tests for the factory function."""

    def test_creates_instance(self) -> None:
        """Factory should create an ExposureClassifier instance."""
        classifier = create_exposure_classifier()
        assert isinstance(classifier, ExposureClassifier)


# =============================================================================
# Return Type Tests
# =============================================================================


class TestReturnTypes:
    """Tests for correct return types."""

    def test_classify_returns_bundle(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """classify() should return ClassifiedExposuresBundle."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        assert isinstance(result, ClassifiedExposuresBundle)

    def test_bundle_has_required_fields(
        self,
        classifier: ExposureClassifier,
        simple_exposures: pl.LazyFrame,
        corporate_counterparties: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Returned bundle should have all required fields."""
        bundle = create_resolved_bundle(simple_exposures, corporate_counterparties)
        result = classifier.classify(bundle, crr_config)

        assert result.all_exposures is not None
        assert result.sa_exposures is not None
        assert result.irb_exposures is not None
        assert result.classification_audit is not None
        assert isinstance(result.classification_errors, list)
