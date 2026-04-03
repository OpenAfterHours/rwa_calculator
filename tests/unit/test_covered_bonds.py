"""
Unit tests for Covered Bond exposure class (CRR Art. 129, PRA PS1/26 Art. 129).

Tests cover:
- CQS-based risk weight lookup (CQS 1-6)
- Unrated derivation from issuer institution risk weight
- Classifier mapping from entity_type
- COREP template row presence
- IRBPermissions SA-only for covered bonds

References:
- CRR Art. 129: Covered bond risk weights
- Art. 129(5): Unrated derivation from issuer RW
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.tables.crr_risk_weights import (
    COVERED_BOND_RISK_WEIGHTS,
    COVERED_BOND_UNRATED_DERIVATION,
    get_all_risk_weight_tables,
    get_combined_cqs_risk_weights,
)
from rwa_calc.domain.enums import ApproachType, CQS, ExposureClass
from rwa_calc.engine.classifier import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
    ExposureClassifier,
)
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.reporting.corep.templates import SA_EXPOSURE_CLASS_ROWS


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


# =============================================================================
# RISK WEIGHT TABLE TESTS
# =============================================================================


class TestCoveredBondRiskWeightTable:
    """Test covered bond CQS-based risk weight tables (Art. 129)."""

    def test_cqs1_ten_percent(self):
        """CQS 1 covered bond gets 10% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS1] == Decimal("0.10")

    def test_cqs2_twenty_percent(self):
        """CQS 2 covered bond gets 20% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS2] == Decimal("0.20")

    def test_cqs3_twenty_percent(self):
        """CQS 3 covered bond gets 20% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS3] == Decimal("0.20")

    def test_cqs4_fifty_percent(self):
        """CQS 4 covered bond gets 50% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS4] == Decimal("0.50")

    def test_cqs5_fifty_percent(self):
        """CQS 5 covered bond gets 50% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS5] == Decimal("0.50")

    def test_cqs6_hundred_percent(self):
        """CQS 6 covered bond gets 100% RW."""
        assert COVERED_BOND_RISK_WEIGHTS[CQS.CQS6] == Decimal("1.00")

    def test_no_unrated_in_table(self):
        """Covered bond table has no unrated entry — derivation handles it."""
        assert CQS.UNRATED not in COVERED_BOND_RISK_WEIGHTS


class TestCoveredBondUnratedDerivation:
    """Test unrated covered bond derivation from issuer institution RW (Art. 129(5))."""

    @pytest.mark.parametrize(
        ("issuer_rw", "expected_cb_rw"),
        [
            (Decimal("0.20"), Decimal("0.10")),
            (Decimal("0.30"), Decimal("0.15")),
            (Decimal("0.40"), Decimal("0.20")),
            (Decimal("0.50"), Decimal("0.25")),
            (Decimal("0.75"), Decimal("0.35")),
            (Decimal("1.00"), Decimal("0.50")),
            (Decimal("1.50"), Decimal("1.00")),
        ],
    )
    def test_derivation_mapping(self, issuer_rw: Decimal, expected_cb_rw: Decimal):
        """Issuer institution RW maps to correct covered bond RW."""
        assert COVERED_BOND_UNRATED_DERIVATION[issuer_rw] == expected_cb_rw


# =============================================================================
# TABLE INTEGRATION TESTS
# =============================================================================


class TestCoveredBondTableIntegration:
    """Test covered bonds are included in combined risk weight tables."""

    def test_in_all_risk_weight_tables(self):
        """Covered bond table is included in get_all_risk_weight_tables()."""
        tables = get_all_risk_weight_tables()
        assert "covered_bond" in tables

    def test_in_combined_cqs_risk_weights(self):
        """Covered bond CQS entries are in get_combined_cqs_risk_weights()."""
        combined = get_combined_cqs_risk_weights()
        cb_rows = combined.filter(pl.col("exposure_class") == "COVERED_BOND")
        assert len(cb_rows) == 6  # CQS 1-6, no unrated


# =============================================================================
# CLASSIFIER TESTS
# =============================================================================


class TestCoveredBondClassification:
    """Test covered bond entity_type classification."""

    def test_sa_class_mapping(self):
        """entity_type 'covered_bond' maps to COVERED_BOND SA class."""
        assert ENTITY_TYPE_TO_SA_CLASS["covered_bond"] == ExposureClass.COVERED_BOND.value

    def test_irb_class_mapping(self):
        """entity_type 'covered_bond' maps to COVERED_BOND IRB class."""
        assert ENTITY_TYPE_TO_IRB_CLASS["covered_bond"] == ExposureClass.COVERED_BOND.value


# =============================================================================
# IRB PERMISSIONS TESTS
# =============================================================================


class TestCoveredBondPermissions:
    """Test covered bonds are SA-only in all IRBPermissions configurations."""

    @pytest.mark.parametrize(
        "factory_name",
        ["full_irb", "firb_only", "airb_only", "retail_airb_corporate_firb"],
    )
    def test_sa_only_in_all_irb_configs(self, factory_name: str):
        """Covered bonds are SA-only regardless of IRB permissions."""
        factory = getattr(IRBPermissions, factory_name)
        perms = factory()
        assert perms.get_permitted_approaches(ExposureClass.COVERED_BOND) == {ApproachType.SA}


# =============================================================================
# COREP TEMPLATE TESTS
# =============================================================================


class TestCoveredBondCOREP:
    """Test covered bond COREP template integration."""

    def test_sa_exposure_class_row_exists(self):
        """Covered bond has a row in SA_EXPOSURE_CLASS_ROWS."""
        assert "covered_bond" in SA_EXPOSURE_CLASS_ROWS
        row_ref, name = SA_EXPOSURE_CLASS_ROWS["covered_bond"]
        assert name == "Covered bonds"


# =============================================================================
# SA CALCULATOR TESTS — CRR
# =============================================================================


class TestCoveredBondSACRR:
    """Test covered bond risk weights in SA calculator (CRR)."""

    @pytest.mark.parametrize(
        ("cqs", "expected_rw"),
        [
            (1, 0.10),
            (2, 0.20),
            (3, 0.20),
            (4, 0.50),
            (5, 0.50),
            (6, 1.00),
        ],
    )
    def test_rated_covered_bond(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        cqs: int,
        expected_rw: float,
    ):
        """Rated covered bond gets correct CQS-based risk weight."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=cqs,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)

    def test_unrated_covered_bond_crr(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ):
        """Unrated covered bond under CRR derives 20% from 40% institution RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)


# =============================================================================
# SA CALCULATOR TESTS — Basel 3.1
# =============================================================================


class TestCoveredBondSABasel31:
    """Test covered bond risk weights in SA calculator (Basel 3.1)."""

    @pytest.mark.parametrize(
        ("cqs", "expected_rw"),
        [
            (1, 0.10),
            (2, 0.20),
            (3, 0.20),
            (4, 0.50),
            (5, 0.50),
            (6, 1.00),
        ],
    )
    def test_rated_covered_bond_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        cqs: int,
        expected_rw: float,
    ):
        """Rated covered bond under Basel 3.1 gets correct CQS-based risk weight."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=cqs,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)

    @pytest.mark.parametrize(
        ("scra_grade", "expected_rw"),
        [
            ("A", 0.20),
            ("B", 0.35),
            ("C", 1.00),
        ],
    )
    def test_unrated_covered_bond_scra_derivation(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        scra_grade: str,
        expected_rw: float,
    ):
        """Unrated covered bond under Basel 3.1 derives from SCRA grade."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            scra_grade=scra_grade,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)
