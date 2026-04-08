"""Unit tests for Art. 123A Basel 3.1 retail qualifying criteria enforcement.

Art. 123A defines two-path qualifying criteria for retail classification:
- Art. 123A(1)(a): SME entities auto-qualify (no conditions 1/3 needed)
- Art. 123A(1)(b): Non-SME natural persons must satisfy:
    (i)   Product type (revolving credits, personal term loans, etc.)
    (ii)  Aggregated exposure ≤ GBP 880k threshold
    (iii) Managed as part of a retail pool (cp_is_managed_as_retail)

Tests cover:
- Condition 3 enforcement: non-SME with cp_is_managed_as_retail=False → not retail
- SME auto-qualification: SME with cp_is_managed_as_retail=False → still retail
- Null handling: cp_is_managed_as_retail=null → qualifies (backward compat)
- CRR unchanged: condition 3 not applied under CRR
- Warning emission when pool management data is absent
- Impact on risk weights (75% qualifying retail vs 100% non-qualifying)
- Edge cases: threshold + condition 3 interaction

References:
- PRA PS1/26 Art. 123A(1)(a)-(b)
- CRR Art. 123 (retail qualifying criteria, no pool management requirement)
- P1.91: Art. 123A retail qualifying criteria enforcement
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_RETAIL_POOL_MGMT_MISSING
from rwa_calc.domain.enums import (
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
)
from rwa_calc.engine.classifier import ExposureClassifier

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _counterparties(
    *,
    revenue: float = 0.0,
    is_managed_as_retail: bool | None = None,
    include_managed_as_retail: bool = True,
    entity_type: str = "individual",
) -> pl.LazyFrame:
    """Create counterparties with configurable retail management flag."""
    data: dict[str, list[object]] = {
        "counterparty_reference": ["CP_001"],
        "counterparty_name": ["Test CP"],
        "entity_type": [entity_type],
        "country_code": ["GB"],
        "annual_revenue": [revenue],
        "total_assets": [0.0],
        "default_status": [False],
        "sector_code": ["RETAIL"],
        "apply_fi_scalar": [False],
    }
    if include_managed_as_retail:
        data["is_managed_as_retail"] = [is_managed_as_retail]
    return pl.DataFrame(data).lazy()


def _exposures(
    *,
    drawn_amount: float = 10_000.0,
    lending_group_total: float = 10_000.0,
) -> pl.LazyFrame:
    """Create a single retail exposure under the threshold."""
    return pl.DataFrame(
        {
            "exposure_reference": ["EXP_001"],
            "exposure_type": ["loan"],
            "product_type": ["PERSONAL"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["CP_001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [drawn_amount],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [lending_group_total],
        }
    ).lazy()


def _make_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
) -> ResolvedHierarchyBundle:
    """Create a ResolvedHierarchyBundle for testing."""
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )

    exp_schema = exposures.collect_schema()
    if "residential_collateral_value" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.lit(0.0).alias("residential_collateral_value"),
        )
    if "exposure_for_retail_threshold" not in exp_schema.names():
        exposures = exposures.with_columns(
            (
                pl.col("drawn_amount")
                + pl.col("nominal_amount")
                - pl.col("residential_collateral_value")
            ).alias("exposure_for_retail_threshold"),
        )
    if "lending_group_adjusted_exposure" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
        )

    return ResolvedHierarchyBundle(
        exposures=exposures,
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
        counterparty_lookup=CounterpartyLookup(
            counterparties=enriched_cp,
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
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        hierarchy_errors=[],
    )


# =============================================================================
# Art. 123A(1)(b)(iii) — Condition 3: Pool management
# =============================================================================


class TestCondition3PoolManagement:
    """Non-SME retail must be managed as part of a retail pool under B31."""

    def test_b31_not_managed_as_retail_fails_qualification(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Non-SME with cp_is_managed_as_retail=False → qualifies_as_retail=False."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is False

    def test_b31_managed_as_retail_passes_qualification(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Non-SME with cp_is_managed_as_retail=True → qualifies_as_retail=True."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=True),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_null_managed_as_retail_defaults_to_qualifying(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Null cp_is_managed_as_retail → qualifies (backward compat)."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=None),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_not_managed_reclassified_to_corporate(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying retail (condition 3 fail) → reclassified to corporate."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        # Non-qualifying retail with no SME revenue → CORPORATE
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value


# =============================================================================
# Art. 123A(1)(a) — SME auto-qualification
# =============================================================================


class TestSMEAutoQualification:
    """SME entities auto-qualify for retail under B31 regardless of condition 3."""

    def test_b31_sme_auto_qualifies_even_without_pool_management(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """SME (revenue < 44m) with is_managed_as_retail=False → still qualifies."""
        bundle = _make_bundle(
            _exposures(),
            # Revenue 1m = SME, but not managed as retail
            _counterparties(revenue=1_000_000.0, is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_sme_with_null_pool_management_qualifies(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """SME with null is_managed_as_retail → still qualifies."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(revenue=500_000.0, is_managed_as_retail=None),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_sme_near_threshold_still_qualifies(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """SME just below GBP 44m threshold → auto-qualifies."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(revenue=43_999_999.0, is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_non_sme_above_threshold_no_auto_qualification(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Revenue >= 44m → not SME, condition 3 check applies."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(revenue=44_000_001.0, is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        # Not SME and not managed as retail → fails condition 3
        assert df["qualifies_as_retail"][0] is False

    def test_b31_zero_revenue_not_sme(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Zero revenue (natural person) → not SME, condition 3 applies."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(revenue=0.0, is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        # Zero revenue = not SME, condition 3 fails
        assert df["qualifies_as_retail"][0] is False


# =============================================================================
# CRR — unchanged behavior
# =============================================================================


class TestCRRUnchanged:
    """CRR has no Art. 123A — only threshold check, no condition 3."""

    def test_crr_not_managed_as_retail_still_qualifies(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR: cp_is_managed_as_retail=False has no effect on qualification."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, crr_config)
        df = result.all_exposures.collect()
        # Under threshold → qualifies regardless of pool management
        assert df["qualifies_as_retail"][0] is True

    def test_crr_null_managed_as_retail_qualifies(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR: null cp_is_managed_as_retail still qualifies."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=None),
        )
        result = classifier.classify(bundle, crr_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True


# =============================================================================
# Warning emission
# =============================================================================


class TestPoolManagementWarning:
    """Warning when cp_is_managed_as_retail is absent under B31."""

    def test_b31_warning_when_column_absent(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """B31 emits CLS005 when is_managed_as_retail not in counterparty data."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(include_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert len(cls_errors) == 1

    def test_b31_warning_severity(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """CLS005 has WARNING severity."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(include_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert cls_errors[0].severity == ErrorSeverity.WARNING

    def test_b31_warning_category(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """CLS005 has CLASSIFICATION category."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(include_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert cls_errors[0].category == ErrorCategory.CLASSIFICATION

    def test_b31_warning_regulatory_reference(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """CLS005 references Art. 123A(1)(b)(iii)."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(include_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert "123A" in (cls_errors[0].regulatory_reference or "")

    def test_b31_no_warning_when_column_present(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """No CLS005 when is_managed_as_retail column exists."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=True),
        )
        result = classifier.classify(bundle, b31_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert len(cls_errors) == 0

    def test_crr_no_warning_even_when_absent(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR: no CLS005 warning regardless of column presence."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(include_managed_as_retail=False),
        )
        result = classifier.classify(bundle, crr_config)
        cls_errors = [
            e for e in result.classification_errors if e.code == ERROR_RETAIL_POOL_MGMT_MISSING
        ]
        assert len(cls_errors) == 0


# =============================================================================
# Threshold + condition 3 interaction
# =============================================================================


class TestThresholdAndCondition3Interaction:
    """Threshold takes precedence — condition 3 only matters below threshold."""

    def test_b31_above_threshold_fails_regardless_of_pool_management(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Above lending group threshold → not retail even if managed as retail."""
        bundle = _make_bundle(
            _exposures(drawn_amount=900_000.0, lending_group_total=900_000.0),
            _counterparties(is_managed_as_retail=True),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is False

    def test_b31_below_threshold_with_pool_management_qualifies(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Below threshold + managed as retail → qualifies."""
        bundle = _make_bundle(
            _exposures(drawn_amount=500_000.0, lending_group_total=500_000.0),
            _counterparties(is_managed_as_retail=True),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is True

    def test_b31_below_threshold_without_pool_management_fails(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Below threshold + NOT managed as retail + non-SME → fails."""
        bundle = _make_bundle(
            _exposures(drawn_amount=500_000.0, lending_group_total=500_000.0),
            _counterparties(is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["qualifies_as_retail"][0] is False


# =============================================================================
# Risk weight impact
# =============================================================================


class TestRiskWeightImpact:
    """Art. 123A condition 3 affects downstream SA risk weights."""

    def test_b31_qualifying_retail_gets_75pct(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Qualifying retail → classified as RETAIL_OTHER (eligible for 75% RW)."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=True),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.RETAIL_OTHER.value

    def test_b31_non_qualifying_retail_gets_corporate(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """Non-qualifying retail (condition 3 fail) → CORPORATE (100% RW)."""
        bundle = _make_bundle(
            _exposures(),
            _counterparties(is_managed_as_retail=False),
        )
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value
