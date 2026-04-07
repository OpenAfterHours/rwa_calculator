"""
Unit tests for Covered Bond exposure class (CRR Art. 129, PRA PS1/26 Art. 129/129A).

Tests cover:
- CRR CQS-based risk weight lookup (CQS 1-6)
- Basel 3.1 CQS-based risk weight lookup (Art. 129A: CQS 2=15%)
- Unrated derivation from issuer institution risk weight (Art. 129(5))
- B31 unrated derivation via SCRA grade → institution RW → CB RW
- Classifier mapping from entity_type
- COREP template row presence
- IRBPermissions SA-only for covered bonds

References:
- CRR Art. 129: Covered bond risk weights
- PRA PS1/26 Art. 129A: Basel 3.1 revised covered bond weights
- Art. 129(5): Unrated derivation from issuer RW
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions, RegulatoryFramework
from rwa_calc.data.tables.b31_risk_weights import (
    B31_COVERED_BOND_RISK_WEIGHTS,
    B31_COVERED_BOND_UNRATED_FROM_SCRA,
    _create_b31_covered_bond_df,
    get_b31_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.crr_risk_weights import (
    COVERED_BOND_RISK_WEIGHTS,
    COVERED_BOND_UNRATED_DERIVATION,
    get_all_risk_weight_tables,
    get_combined_cqs_risk_weights,
)
from rwa_calc.domain.enums import CQS, ApproachType, ExposureClass
from rwa_calc.engine.classifier import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
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
        ["sa_only", "full_irb"],
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

    def test_unrated_covered_bond_crr_uk_default(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ):
        """Unrated CB with unrated institution under UK deviation → 20%.

        Art. 129(5): unrated institution (UK sovereign-derived 40%) → CB 20%.
        Backward-compatible: no cp_institution_cqs provided → null → unrated institution.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    @pytest.mark.parametrize(
        ("institution_cqs", "expected_cb_rw"),
        [
            # CRR Art. 129(5) derivation chain — UK deviation (base_currency=GBP):
            # Institution CQS → institution RW (Table 4) → CB RW (derivation table)
            (1, 0.10),  # inst 20% → CB 10%
            (2, 0.15),  # inst 30% (UK deviation) → CB 15%
            (3, 0.25),  # inst 50% → CB 25%
            (4, 0.50),  # inst 100% → CB 50%
            (5, 0.50),  # inst 100% → CB 50%
            (6, 1.00),  # inst 150% → CB 100%
        ],
    )
    def test_unrated_covered_bond_crr_uk_by_institution_cqs(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        institution_cqs: int,
        expected_cb_rw: float,
    ):
        """Art. 129(5): CRR unrated CB derives RW from issuing institution CQS (UK)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            config=crr_config,
            institution_cqs=institution_cqs,
        )
        assert result["risk_weight"] == pytest.approx(expected_cb_rw)

    @pytest.mark.parametrize(
        ("institution_cqs", "expected_cb_rw"),
        [
            # CRR Art. 129(5) derivation chain — standard (non-UK, base_currency≠GBP):
            # Institution CQS → institution RW (Table 3) → CB RW (derivation table)
            (1, 0.10),  # inst 20% → CB 10%
            (2, 0.25),  # inst 50% (standard) → CB 25%
            (3, 0.25),  # inst 50% → CB 25%
            (4, 0.50),  # inst 100% → CB 50%
            (5, 0.50),  # inst 100% → CB 50%
            (6, 1.00),  # inst 150% → CB 100%
        ],
    )
    def test_unrated_covered_bond_crr_standard_by_institution_cqs(
        self,
        sa_calculator: SACalculator,
        institution_cqs: int,
        expected_cb_rw: float,
    ):
        """Art. 129(5): CRR unrated CB derives RW from institution CQS (standard)."""
        config = CalculationConfig(
            framework=RegulatoryFramework.CRR,
            reporting_date=date(2025, 12, 31),
            base_currency="EUR",
        )
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            config=config,
            institution_cqs=institution_cqs,
        )
        assert result["risk_weight"] == pytest.approx(expected_cb_rw)

    def test_unrated_covered_bond_crr_standard_unrated_institution(
        self,
        sa_calculator: SACalculator,
    ):
        """Unrated CB with unrated institution under standard treatment → 50%.

        Art. 129(5): unrated institution (standard 100%) → CB 50%.
        """
        config = CalculationConfig(
            framework=RegulatoryFramework.CRR,
            reporting_date=date(2025, 12, 31),
            base_currency="EUR",
        )
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            config=config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_covered_bond_ignores_institution_cqs(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ):
        """Rated CB uses its own CQS, not the issuer institution CQS.

        Art. 129(4) rated table takes priority; Art. 129(5) derivation
        only applies to unrated covered bonds.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=1,
            config=crr_config,
            institution_cqs=6,  # Should be ignored — bond is rated
        )
        assert result["risk_weight"] == pytest.approx(0.10)

    def test_unrated_cb_rwa_standard_vs_uk(
        self,
        sa_calculator: SACalculator,
    ):
        """Unrated CB RWA is higher under standard than UK for same unrated institution.

        UK: unrated institution 40% → CB 20% → RWA = 200k
        Standard: unrated institution 100% → CB 50% → RWA = 500k
        """
        ead = Decimal("1000000")
        uk_config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        std_config = CalculationConfig(
            framework=RegulatoryFramework.CRR,
            reporting_date=date(2025, 12, 31),
            base_currency="EUR",
        )
        uk_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="COVERED_BOND",
            cqs=None,
            config=uk_config,
        )
        std_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="COVERED_BOND",
            cqs=None,
            config=std_config,
        )
        assert uk_result["risk_weight"] == pytest.approx(0.20)
        assert std_result["risk_weight"] == pytest.approx(0.50)
        assert std_result["rwa_post_factor"] > uk_result["rwa_post_factor"]


# =============================================================================
# DERIVATION TABLE CONSISTENCY
# =============================================================================


class TestCRRCoveredBondDerivationConsistency:
    """Cross-validate calculator expression against source data tables."""

    def test_uk_derivation_matches_tables(self):
        """Calculator's UK CQS → CB RW matches INSTITUTION_RISK_WEIGHTS_UK × DERIVATION."""
        from rwa_calc.data.tables.crr_risk_weights import (
            COVERED_BOND_UNRATED_DERIVATION,
            INSTITUTION_RISK_WEIGHTS_UK,
        )

        for cqs_val in [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
            inst_rw = INSTITUTION_RISK_WEIGHTS_UK[cqs_val]
            expected_cb_rw = COVERED_BOND_UNRATED_DERIVATION[inst_rw]
            assert inst_rw in COVERED_BOND_UNRATED_DERIVATION, (
                f"UK institution RW {inst_rw} for CQS {cqs_val} not in derivation table"
            )
            assert expected_cb_rw is not None

    def test_standard_derivation_matches_tables(self):
        """Calculator's standard CQS → CB RW matches INSTITUTION_RISK_WEIGHTS_STANDARD × DERIVATION."""
        from rwa_calc.data.tables.crr_risk_weights import (
            COVERED_BOND_UNRATED_DERIVATION,
            INSTITUTION_RISK_WEIGHTS_STANDARD,
        )

        for cqs_val in [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
            inst_rw = INSTITUTION_RISK_WEIGHTS_STANDARD[cqs_val]
            expected_cb_rw = COVERED_BOND_UNRATED_DERIVATION[inst_rw]
            assert inst_rw in COVERED_BOND_UNRATED_DERIVATION, (
                f"Standard institution RW {inst_rw} for CQS {cqs_val} not in derivation table"
            )
            assert expected_cb_rw is not None

    def test_unrated_institution_rw_in_derivation_table(self):
        """Unrated institution RW (both UK and standard) must be in derivation table."""
        from rwa_calc.data.tables.crr_risk_weights import (
            COVERED_BOND_UNRATED_DERIVATION,
            INSTITUTION_RISK_WEIGHTS_STANDARD,
            INSTITUTION_RISK_WEIGHTS_UK,
        )

        uk_unrated = INSTITUTION_RISK_WEIGHTS_UK[CQS.UNRATED]
        std_unrated = INSTITUTION_RISK_WEIGHTS_STANDARD[CQS.UNRATED]
        assert uk_unrated in COVERED_BOND_UNRATED_DERIVATION
        assert std_unrated in COVERED_BOND_UNRATED_DERIVATION


# =============================================================================
# SA CALCULATOR TESTS — Basel 3.1
# =============================================================================


class TestCoveredBondSABasel31:
    """Test covered bond risk weights in SA calculator (Basel 3.1)."""

    @pytest.mark.parametrize(
        ("cqs", "expected_rw"),
        [
            (1, 0.10),
            (2, 0.15),  # Art. 129A: CQS 2 = 15% under B31 (CRR: 20%)
            (3, 0.20),
            (4, 0.50),
            (5, 0.50),
            (6, 0.50),  # Art. 129A: CQS 6 = 50% under B31 (CRR: 100%)
        ],
    )
    def test_rated_covered_bond_b31(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        cqs: int,
        expected_rw: float,
    ):
        """Rated covered bond under Basel 3.1 gets correct CQS-based risk weight (Art. 129A)."""
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
            ("A_ENHANCED", 0.15),  # inst 30% → CB 15% (Art. 129(5))
            ("A", 0.20),  # inst 40% → CB 20%
            ("B", 0.35),  # inst 75% → CB 35%
            ("C", 1.00),  # inst 150% → CB 100%
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

    def test_unrated_covered_bond_null_scra_grade(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ):
        """Unrated covered bond with null SCRA grade defaults to Grade C derivation (100%).

        Why this matters:
            Missing SCRA data must not produce a favourable covered bond RW.
            Grade C institution RW (150%) derives to 100% covered bond RW.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            scra_grade=None,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# =============================================================================
# BASEL 3.1 COVERED BOND DATA TABLE TESTS
# =============================================================================


class TestB31CoveredBondRiskWeightTable:
    """Test Basel 3.1 covered bond CQS-based risk weight table (Art. 129A).

    Art. 129A changes from CRR Art. 129(4):
    - CQS 2: 15% (was 20%)
    - CQS 6: 50% (was 100%)
    """

    def test_b31_cqs1_ten_percent(self):
        """B31 CQS 1 covered bond gets 10% RW."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[1] == Decimal("0.10")

    def test_b31_cqs2_fifteen_percent(self):
        """B31 CQS 2 covered bond gets 15% RW (CRR: 20%)."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[2] == Decimal("0.15")

    def test_b31_cqs3_twenty_percent(self):
        """B31 CQS 3 covered bond gets 20% RW."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[3] == Decimal("0.20")

    def test_b31_cqs4_fifty_percent(self):
        """B31 CQS 4 covered bond gets 50% RW."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[4] == Decimal("0.50")

    def test_b31_cqs5_fifty_percent(self):
        """B31 CQS 5 covered bond gets 50% RW."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[5] == Decimal("0.50")

    def test_b31_cqs6_fifty_percent(self):
        """B31 CQS 6 covered bond gets 50% RW (CRR: 100%)."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[6] == Decimal("0.50")

    def test_b31_cqs2_differs_from_crr(self):
        """B31 CQS 2 (15%) differs from CRR CQS 2 (20%)."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[2] < COVERED_BOND_RISK_WEIGHTS[CQS.CQS2]

    def test_b31_cqs6_differs_from_crr(self):
        """B31 CQS 6 (50%) differs from CRR CQS 6 (100%)."""
        assert B31_COVERED_BOND_RISK_WEIGHTS[6] < COVERED_BOND_RISK_WEIGHTS[CQS.CQS6]


class TestB31CoveredBondDataFrame:
    """Test B31 covered bond CQS DataFrame generator."""

    def test_b31_df_has_six_rows(self):
        """B31 covered bond DataFrame has 6 rows (CQS 1-6, no unrated)."""
        df = _create_b31_covered_bond_df()
        assert len(df) == 6

    def test_b31_df_cqs2_is_fifteen_percent(self):
        """B31 covered bond DataFrame CQS 2 row has 15% RW."""
        df = _create_b31_covered_bond_df()
        cqs2_rw = df.filter(pl.col("cqs") == 2)["risk_weight"].item()
        assert cqs2_rw == pytest.approx(0.15)

    def test_b31_combined_table_uses_b31_weights(self):
        """B31 combined CQS table has B31-specific covered bond weights."""
        combined = get_b31_combined_cqs_risk_weights()
        cb_cqs2 = combined.filter(
            (pl.col("exposure_class") == "COVERED_BOND") & (pl.col("cqs") == 2)
        )
        assert len(cb_cqs2) == 1
        assert cb_cqs2["risk_weight"].item() == pytest.approx(0.15)


# =============================================================================
# DERIVATION TABLE TRACEABILITY TESTS
# =============================================================================


class TestCoveredBondDerivationTraceability:
    """Verify B31 SCRA→CB RW values are traceable to COVERED_BOND_UNRATED_DERIVATION.

    The derivation chain is:
        SCRA grade → institution RW (B31_SCRA_RISK_WEIGHTS) →
        covered bond RW (COVERED_BOND_UNRATED_DERIVATION)

    This test class verifies that B31_COVERED_BOND_UNRATED_FROM_SCRA values
    match the derivation table exactly.
    """

    @pytest.mark.parametrize(
        ("scra_grade", "inst_rw", "expected_cb_rw"),
        [
            ("A_ENHANCED", Decimal("0.30"), Decimal("0.15")),
            ("A", Decimal("0.40"), Decimal("0.20")),
            ("B", Decimal("0.75"), Decimal("0.35")),
            ("C", Decimal("1.50"), Decimal("1.00")),
        ],
    )
    def test_scra_derivation_matches_table(
        self,
        scra_grade: str,
        inst_rw: Decimal,
        expected_cb_rw: Decimal,
    ):
        """B31 SCRA CB RW matches derivation table lookup via institution RW."""
        # Verify the derivation table maps correctly
        assert COVERED_BOND_UNRATED_DERIVATION[inst_rw] == expected_cb_rw
        # Verify the B31 shortcut dict matches
        assert B31_COVERED_BOND_UNRATED_FROM_SCRA[scra_grade] == expected_cb_rw

    def test_all_scra_grades_covered(self):
        """B31 SCRA derivation dict covers all four SCRA grades."""
        assert set(B31_COVERED_BOND_UNRATED_FROM_SCRA.keys()) == {
            "A_ENHANCED",
            "A",
            "B",
            "C",
        }

    def test_a_enhanced_differs_from_a(self):
        """A_ENHANCED CB RW (15%) differs from standard A (20%).

        Why this matters: SCRA A_ENHANCED institutions have a lower RW (30%)
        than standard A (40%), so the derived CB RW must also be lower.
        """
        assert (
            B31_COVERED_BOND_UNRATED_FROM_SCRA["A_ENHANCED"]
            < (B31_COVERED_BOND_UNRATED_FROM_SCRA["A"])
        )


class TestB31CoveredBondRWACalculation:
    """Test B31 covered bond RWA calculations for edge cases."""

    def test_unrated_a_enhanced_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ):
        """Unrated covered bond with A_ENHANCED: RWA = 1M × 15% = 150,000."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=None,
            scra_grade="A_ENHANCED",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.15)
        assert result["rwa"] == pytest.approx(150_000.0)

    def test_rated_cqs2_b31_vs_crr(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        crr_config: CalculationConfig,
    ):
        """CQS 2 covered bond: B31=15% vs CRR=20% — B31 is more favourable."""
        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=2,
            config=b31_config,
        )
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=2,
            config=crr_config,
        )
        assert b31_result["risk_weight"] == pytest.approx(0.15)
        assert crr_result["risk_weight"] == pytest.approx(0.20)
        assert b31_result["rwa"] < crr_result["rwa"]

    def test_rated_cqs6_b31_vs_crr(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
        crr_config: CalculationConfig,
    ):
        """CQS 6 covered bond: B31=50% vs CRR=100% — B31 halves the RW."""
        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=6,
            config=b31_config,
        )
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="COVERED_BOND",
            cqs=6,
            config=crr_config,
        )
        assert b31_result["risk_weight"] == pytest.approx(0.50)
        assert crr_result["risk_weight"] == pytest.approx(1.00)
