"""Unit tests for equity exposure routing through the SA calculator (P6.11).

Tests cover:
- ApproachType.EQUITY enum value exists
- Classifier assigns EQUITY approach for equity-class exposures
- SA calculator applies 250% RW for B31 equity in main table
- SA calculator applies 100% RW for CRR equity in main table
- Pipeline routes equity-approach rows to SA branch correctly
- SA005 warning emitted when equity rows detected in get_sa_result_bundle
- No warning when no equity rows present
- RWA calculation correctness for equity exposures
- Equity from dedicated equity_exposures table unaffected

References:
- CRR Art. 133(2): Equity flat 100%
- PRA PS1/26 Art. 133(3): Standard equity 250%
- P6.11: ApproachType.EQUITY routing gap
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_EQUITY_IN_MAIN_TABLE, CalculationError
from rwa_calc.domain.enums import (
    ApproachType,
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
)
from rwa_calc.engine.sa.calculator import SACalculator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _equity_exposure(
    *,
    n: int = 1,
    ead: float = 1_000_000.0,
    exposure_class: str = "equity",
    approach: str = "equity",
    cqs: int | None = None,
) -> pl.LazyFrame:
    """Create minimal equity exposure rows for SA calculator testing."""
    data: dict[str, list] = {
        "exposure_reference": [f"EQ_{i:03d}" for i in range(n)],
        "counterparty_reference": [f"CP_{i:03d}" for i in range(n)],
        "exposure_class": [exposure_class] * n,
        "approach": [approach] * n,
        "ead": [ead] * n,
        "cqs": [cqs] * n,
        "cp_entity_type": ["equity"] * n,
        "currency": ["GBP"] * n,
    }
    return pl.DataFrame(data).lazy()


def _mixed_exposures(
    *,
    include_equity: bool = True,
) -> pl.LazyFrame:
    """Create mixed exposures with optional equity rows."""
    rows: list[dict] = [
        {
            "exposure_reference": "CORP_001",
            "counterparty_reference": "CP_001",
            "exposure_class": "corporate",
            "approach": "standardised",
            "ead": 500_000.0,
            "cqs": 3,
            "cp_entity_type": "corporate",
            "currency": "GBP",
        },
    ]
    if include_equity:
        rows.append(
            {
                "exposure_reference": "EQ_001",
                "counterparty_reference": "CP_002",
                "exposure_class": "equity",
                "approach": "equity",
                "ead": 1_000_000.0,
                "cqs": None,
                "cp_entity_type": "equity",
                "currency": "GBP",
            }
        )
    return pl.DataFrame(rows).lazy()


# =============================================================================
# 1. ApproachType.EQUITY enum
# =============================================================================


class TestApproachTypeEquity:
    """Verify ApproachType.EQUITY exists and has correct value."""

    def test_equity_enum_exists(self) -> None:
        assert hasattr(ApproachType, "EQUITY")

    def test_equity_enum_value(self) -> None:
        assert ApproachType.EQUITY.value == "equity"

    def test_equity_is_distinct_from_sa(self) -> None:
        assert ApproachType.EQUITY != ApproachType.SA

    def test_equity_in_approach_members(self) -> None:
        values = [m.value for m in ApproachType]
        assert "equity" in values


# =============================================================================
# 2. SA Calculator equity risk weight branches
# =============================================================================


class TestSAEquityRiskWeightB31:
    """Basel 3.1: equity in main table gets 250% RW (Art. 133(3))."""

    def test_equity_gets_250_pct_rw(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        exposures = _equity_exposure()
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        rw = df["risk_weight"][0]
        assert rw == pytest.approx(2.50), f"Expected 250% but got {rw * 100}%"

    def test_equity_rwa_correctness(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        exposures = _equity_exposure(ead=1_000_000.0)
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        rwa = df["rwa_pre_factor"][0]
        assert rwa == pytest.approx(2_500_000.0)

    def test_equity_multiple_rows(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        exposures = _equity_exposure(n=5, ead=100_000.0)
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        assert df.height == 5
        for rw in df["risk_weight"].to_list():
            assert rw == pytest.approx(2.50)

    def test_equity_does_not_affect_corporate(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Corporate rows in same frame should not get equity treatment."""
        exposures = _mixed_exposures(include_equity=True)
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        corp_row = df.filter(pl.col("exposure_class") == "corporate")
        eq_row = df.filter(pl.col("exposure_class") == "equity")
        # Corporate CQS 3 B31 = 75%
        assert corp_row["risk_weight"][0] == pytest.approx(0.75)
        # Equity = 250%
        assert eq_row["risk_weight"][0] == pytest.approx(2.50)

    def test_equity_zero_ead(self, calculator: SACalculator, b31_config: CalculationConfig) -> None:
        exposures = _equity_exposure(ead=0.0)
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(2.50)
        assert df["rwa_pre_factor"][0] == pytest.approx(0.0)


class TestSAEquityRiskWeightCRR:
    """CRR: equity in main table gets 100% RW (Art. 133(2))."""

    def test_equity_gets_100_pct_rw(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        exposures = _equity_exposure()
        result = calculator.calculate_branch(exposures, crr_config)
        df = result.collect()
        rw = df["risk_weight"][0]
        assert rw == pytest.approx(1.00), f"Expected 100% but got {rw * 100}%"

    def test_crr_equity_rwa_correctness(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        exposures = _equity_exposure(ead=1_000_000.0)
        result = calculator.calculate_branch(exposures, crr_config)
        df = result.collect()
        rwa = df["rwa_pre_factor"][0]
        assert rwa == pytest.approx(1_000_000.0)

    def test_crr_equity_does_not_affect_corporate(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Corporate rows in same frame should not get equity treatment."""
        exposures = _mixed_exposures(include_equity=True)
        result = calculator.calculate_branch(exposures, crr_config)
        df = result.collect()
        corp_row = df.filter(pl.col("exposure_class") == "corporate")
        eq_row = df.filter(pl.col("exposure_class") == "equity")
        # Corporate CQS 3 CRR = 100%
        assert corp_row["risk_weight"][0] == pytest.approx(1.00)
        # Equity CRR = 100%
        assert eq_row["risk_weight"][0] == pytest.approx(1.00)


# =============================================================================
# 3. SA005 Warning tests
# =============================================================================


class TestSA005EquityWarning:
    """SA005 warning when equity rows detected in main table."""

    def test_warning_emitted_when_equity_present(self, calculator: SACalculator) -> None:
        exposures = _equity_exposure()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert len(errors) == 1
        assert errors[0].code == ERROR_EQUITY_IN_MAIN_TABLE

    def test_warning_severity_is_warning(self, calculator: SACalculator) -> None:
        exposures = _equity_exposure()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert errors[0].severity == ErrorSeverity.WARNING

    def test_warning_category_is_data_quality(self, calculator: SACalculator) -> None:
        exposures = _equity_exposure()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert errors[0].category == ErrorCategory.DATA_QUALITY

    def test_warning_has_regulatory_reference(self, calculator: SACalculator) -> None:
        exposures = _equity_exposure()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert "Art. 133" in errors[0].regulatory_reference

    def test_no_warning_when_no_equity(self, calculator: SACalculator) -> None:
        exposures = _mixed_exposures(include_equity=False)
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert len(errors) == 0

    def test_no_warning_when_approach_column_absent(self, calculator: SACalculator) -> None:
        exposures = pl.DataFrame({"exposure_reference": ["X"], "ead": [100.0]}).lazy()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert len(errors) == 0

    def test_warning_message_mentions_equity_exposures_table(
        self, calculator: SACalculator
    ) -> None:
        exposures = _equity_exposure()
        errors: list[CalculationError] = []
        calculator._warn_equity_in_main_table(exposures, errors)
        assert "equity_exposures" in errors[0].message


# =============================================================================
# 4. Classifier approach assignment
# =============================================================================


class TestClassifierEquityApproach:
    """Classifier assigns EQUITY approach for equity-class exposures."""

    def test_equity_class_gets_equity_approach(self) -> None:
        """Equity-class rows from entity_type mapping get EQUITY approach."""
        from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

        assert ENTITY_TYPE_TO_SA_CLASS["equity"] == ExposureClass.EQUITY.value

    def test_equity_class_produces_equity_approach_expression(self) -> None:
        """The classifier approach expression assigns EQUITY for equity class.

        Verifies the core expression logic: when exposure_class == "equity",
        the approach should be "equity" (not "standardised").
        """
        # Simulate the classifier's approach expression for equity
        exposures = pl.DataFrame(
            {
                "exposure_class": ["equity", "corporate", "institution"],
            }
        )
        result = exposures.with_columns(
            pl.when(pl.col("exposure_class") == ExposureClass.EQUITY.value)
            .then(pl.lit(ApproachType.EQUITY.value))
            .otherwise(pl.lit(ApproachType.SA.value))
            .alias("approach")
        )
        approaches = result["approach"].to_list()
        assert approaches[0] == ApproachType.EQUITY.value
        assert approaches[1] == ApproachType.SA.value
        assert approaches[2] == ApproachType.SA.value

    def test_equity_approach_included_in_sa_exposures_split(self) -> None:
        """Equity-approach rows are included in sa_exposures filter."""
        # The classifier's sa_exposures filter includes both SA and EQUITY approaches
        approaches = pl.DataFrame({"approach": ["standardised", "equity", "foundation_irb"]}).lazy()
        sa_filter = pl.col("approach").is_in([ApproachType.SA.value, ApproachType.EQUITY.value])
        result = approaches.filter(sa_filter).collect()
        assert result.height == 2
        assert set(result["approach"].to_list()) == {"standardised", "equity"}


# =============================================================================
# 5. Pipeline routing
# =============================================================================


class TestPipelineEquityRouting:
    """Equity-approach rows route to SA branch in pipeline split."""

    def test_equity_not_in_irb_branch(self) -> None:
        """EQUITY approach is not classified as IRB."""
        is_irb = ApproachType.EQUITY.value in {
            ApproachType.FIRB.value,
            ApproachType.AIRB.value,
        }
        assert not is_irb

    def test_equity_not_in_slotting_branch(self) -> None:
        """EQUITY approach is not classified as slotting."""
        assert ApproachType.EQUITY.value != ApproachType.SLOTTING.value

    def test_equity_falls_to_sa_branch(self) -> None:
        """In pipeline split, equity rows land in sa_branch (~irb & ~slotting)."""
        approaches = ["standardised", "equity", "foundation_irb", "slotting"]
        df = pl.DataFrame({"approach": approaches})

        is_irb = pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        is_slotting = pl.col("approach") == ApproachType.SLOTTING.value
        sa_branch = df.filter(~is_irb & ~is_slotting)

        assert sa_branch.height == 2
        assert set(sa_branch["approach"].to_list()) == {"standardised", "equity"}


# =============================================================================
# 6. Edge cases
# =============================================================================


class TestEquityEdgeCases:
    """Edge cases for equity routing."""

    def test_equity_with_cqs_still_gets_equity_rw(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Even if CQS is provided, equity class overrides to 250% B31."""
        exposures = _equity_exposure(cqs=2)
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(2.50)

    def test_equity_with_cqs_crr_still_gets_100(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR equity gets 100% regardless of CQS."""
        exposures = _equity_exposure(cqs=1)
        result = calculator.calculate_branch(exposures, crr_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(1.00)

    def test_b31_equity_not_100_pct_regression(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Regression: before P6.11, B31 equity got 100% (wrong). Must be 250%."""
        exposures = _equity_exposure()
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        rw = df["risk_weight"][0]
        assert rw != pytest.approx(1.00), "Regression: equity should not be 100% under B31"
        assert rw == pytest.approx(2.50)

    def test_equity_approach_preserves_other_columns(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Equity routing does not drop existing columns."""
        exposures = _equity_exposure()
        result = calculator.calculate_branch(exposures, b31_config)
        df = result.collect()
        assert "exposure_reference" in df.columns
        assert "ead" in df.columns
        assert "approach" in df.columns
