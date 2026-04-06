"""
Unit tests for MDB (Multilateral Development Bank) and International Organisation
risk weights under CRR and Basel 3.1.

Why these tests matter:
    MDB exposures to the 16 named institutions in Art. 117(2) should receive 0%
    risk weight (e.g. World Bank, EIB, EBRD). Without proper MDB risk weight tables,
    these exposures silently default to 100% via the CQS join fallback, causing
    significant capital overstatement. Non-named MDBs use Table 2B which differs
    from the institution table (CQS 2 = 30%, unrated = 50% vs institution's 40%).
    International Organisations (Art. 118) always receive 0%.

MDB/IO treatment is identical under CRR and PRA PS1/26 Basel 3.1:
    - Named MDBs (Art. 117(2)): 0% unconditional
    - Rated non-named MDBs (Art. 117(1)): Table 2B
    - Unrated non-named MDBs: 50% (Table 2B unrated)
    - International Organisations (Art. 118): 0% unconditional

References:
    - CRR Art. 117 / PRA PS1/26 Art. 117: MDB risk weights
    - CRR Art. 118 / PRA PS1/26 Art. 118: International organisation risk weights
    - Table 2B: MDB own-rating risk weights
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.crr_risk_weights import (
    IO_ZERO_RW,
    MDB_NAMED_ZERO_RW,
    MDB_RISK_WEIGHTS_TABLE_2B,
    MDB_UNRATED_RW,
    get_combined_cqs_risk_weights,
    lookup_risk_weight,
)
from rwa_calc.data.tables.b31_risk_weights import get_b31_combined_cqs_risk_weights
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa import SACalculator


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# DATA TABLE TESTS
# =============================================================================


class TestMDBRiskWeightTables:
    """Tests for MDB risk weight dict tables and DataFrame generators."""

    def test_table_2b_values(self):
        """Table 2B (Art. 117(1)): MDB own-rating risk weights."""
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS1] == Decimal("0.20")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS2] == Decimal("0.30")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS3] == Decimal("0.50")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS4] == Decimal("1.00")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS5] == Decimal("1.00")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS6] == Decimal("1.50")
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.UNRATED] == Decimal("0.50")

    def test_cqs2_differs_from_standard_institutions(self):
        """MDB Table 2B CQS 2 = 30% matches UK institution deviation (not 50% standard)."""
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS2] == Decimal("0.30")

    def test_unrated_differs_from_institutions(self):
        """MDB unrated = 50% (Table 2B), not 40% like institutions."""
        assert MDB_RISK_WEIGHTS_TABLE_2B[CQS.UNRATED] == Decimal("0.50")
        assert MDB_UNRATED_RW == Decimal("0.50")

    def test_named_mdb_zero_rw(self):
        """Art. 117(2): Named MDB constant is 0%."""
        assert MDB_NAMED_ZERO_RW == Decimal("0.00")

    def test_io_zero_rw(self):
        """Art. 118: International organisation constant is 0%."""
        assert IO_ZERO_RW == Decimal("0.00")

    def test_mdb_in_combined_crr_table(self):
        """MDB rows present in combined CRR CQS risk weight table."""
        combined = get_combined_cqs_risk_weights()
        mdb_rows = combined.filter(combined["exposure_class"] == "MDB")
        assert len(mdb_rows) == 7  # CQS 1-6 + unrated

    def test_mdb_in_combined_b31_table(self):
        """MDB rows present in combined B31 CQS risk weight table."""
        combined = get_b31_combined_cqs_risk_weights()
        mdb_rows = combined.filter(combined["exposure_class"] == "MDB")
        assert len(mdb_rows) == 7  # CQS 1-6 + unrated

    def test_lookup_risk_weight_mdb_cqs3(self):
        """lookup_risk_weight for MDB CQS 3 returns 50%."""
        assert lookup_risk_weight("MDB", 3) == Decimal("0.50")

    def test_lookup_risk_weight_mdb_unrated(self):
        """lookup_risk_weight for MDB unrated returns 50%."""
        assert lookup_risk_weight("MDB", None) == Decimal("0.50")

    def test_lookup_risk_weight_mdb_cqs2(self):
        """lookup_risk_weight for MDB CQS 2 returns 30%."""
        assert lookup_risk_weight("MDB", 2) == Decimal("0.30")


# =============================================================================
# CRR SA CALCULATOR TESTS
# =============================================================================


class TestCRRMDBRiskWeights:
    """Tests for MDB/IO risk weights through the CRR SA calculator."""

    def test_named_mdb_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 117(2): Named MDB (e.g. World Bank) → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="mdb",
            config=crr_config,
            entity_type="mdb_named",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_international_org_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 118: International Organisation (e.g. IMF, BIS) → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            config=crr_config,
            entity_type="international_org",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_rated_mdb_cqs1(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Rated MDB CQS 1 → 20%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=1,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_mdb_cqs2(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Rated MDB CQS 2 → 30% (not 50% like standard institutions)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=2,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.30)

    def test_rated_mdb_cqs3(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Rated MDB CQS 3 → 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=3,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_mdb_cqs4(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Rated MDB CQS 4 → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=4,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rated_mdb_cqs6(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Rated MDB CQS 6 → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=6,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_unrated_non_named_mdb(self, sa_calculator, crr_config):
        """CRR Art. 117(1), Table 2B: Unrated non-named MDB → 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_named_mdb_ignores_cqs(self, sa_calculator, crr_config):
        """Named MDB gets 0% regardless of CQS rating."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=3,
            config=crr_config,
            entity_type="mdb_named",
        )
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_rwa_calculation_named_mdb(self, sa_calculator, crr_config):
        """Named MDB with 0% RW produces 0 RWA."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="mdb",
            config=crr_config,
            entity_type="mdb_named",
        )
        assert result["rwa"] == pytest.approx(0.0)

    def test_rwa_calculation_rated_mdb(self, sa_calculator, crr_config):
        """Rated MDB CQS 3 → 50% RW → RWA = EAD × 0.50."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=3,
            config=crr_config,
        )
        assert result["rwa"] == pytest.approx(2500000.0)


# =============================================================================
# BASEL 3.1 SA CALCULATOR TESTS
# =============================================================================


class TestB31MDBRiskWeights:
    """Tests for MDB/IO risk weights through the Basel 3.1 SA calculator.

    MDB/IO treatment is unchanged between CRR and Basel 3.1. The only
    Basel 3.1 change is the IRB approach restriction (Art. 147A): named MDBs
    and IOs with 0% SA RW are SA-only under Basel 3.1 (no IRB).
    """

    def test_named_mdb_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 117(2): Named MDB → 0% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="mdb",
            config=b31_config,
            entity_type="mdb_named",
        )
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_international_org_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 118: International Organisation → 0% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            config=b31_config,
            entity_type="international_org",
        )
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_rated_mdb_cqs1(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: CQS 1 → 20%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=1,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_rated_mdb_cqs2(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: CQS 2 → 30%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=2,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.30)

    def test_rated_mdb_cqs3(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: CQS 3 → 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=3,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_rated_mdb_cqs5(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: CQS 5 → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=5,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rated_mdb_cqs6(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: CQS 6 → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=6,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_unrated_non_named_mdb(self, sa_calculator, b31_config):
        """B31 Art. 117(1), Table 2B: Unrated non-named MDB → 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_named_mdb_ignores_cqs(self, sa_calculator, b31_config):
        """Named MDB gets 0% regardless of CQS rating under B31."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="mdb",
            cqs=2,
            config=b31_config,
            entity_type="mdb_named",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
