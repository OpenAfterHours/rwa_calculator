"""
Tests for multi-level collateral allocation for SA EAD reduction.

When collateral is pledged at facility or counterparty level (via beneficiary_type),
child exposures must receive the collateral benefit pro-rata by EAD for SA EAD reduction,
and the haircut calculator must resolve FX haircuts at all levels.

Covers:
- Direct collateral still reduces SA EAD (baseline)
- Facility-level collateral reduces SA EAD for child exposures
- Facility-level collateral split pro-rata across multiple children
- Counterparty-level collateral split pro-rata across multiple children
- Mixed direct + facility + counterparty collateral stacks
- Facility collateral does NOT reduce IRB EAD (IRB uses LGD path)
- EAD cannot go below 0 when collateral exceeds exposure
- FX haircut applied for facility-level collateral with currency mismatch
- No FX haircut when facility-level collateral same currency as exposure
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def sa_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture
def firb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


# =============================================================================
# Helpers
# =============================================================================


def _make_bundle(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
) -> ClassifiedExposuresBundle:
    """Build a ClassifiedExposuresBundle with collateral only."""
    empty_cp = pl.LazyFrame(schema={"counterparty_reference": pl.String, "entity_type": pl.String})
    empty_mappings = pl.LazyFrame(
        schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }
    )
    empty_ultimate = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }
    )
    empty_ri = pl.LazyFrame(
        schema={"counterparty_reference": pl.String, "cqs": pl.Int8, "rating_type": pl.String}
    )
    return ClassifiedExposuresBundle(
        all_exposures=exposures,
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        slotting_exposures=pl.LazyFrame(),
        equity_exposures=None,
        counterparty_lookup=CounterpartyLookup(
            counterparties=empty_cp,
            parent_mappings=empty_mappings,
            ultimate_parent_mappings=empty_ultimate,
            rating_inheritance=empty_ri,
        ),
        collateral=collateral,
        guarantees=None,
        provisions=None,
    )


def _sa_exposure(
    ref: str,
    drawn: float,
    nominal: float = 0.0,
    facility_ref: str = "FAC_DEFAULT",
    cp_ref: str = "CP001",
    currency: str = "GBP",
) -> dict:
    """Create an SA exposure row."""
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
        "parent_facility_reference": facility_ref,
        "currency": currency,
        "maturity_date": None,
    }


def _irb_exposure(
    ref: str,
    drawn: float,
    nominal: float = 0.0,
    facility_ref: str = "FAC_DEFAULT",
    cp_ref: str = "CP001",
) -> dict:
    """Create an FIRB exposure row."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": cp_ref,
        "exposure_class": "corporate",
        "approach": ApproachType.FIRB.value,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": nominal,
        "risk_type": "FR" if nominal == 0.0 else "MR",
        "lgd": 0.45,
        "seniority": "senior",
        "parent_facility_reference": facility_ref,
        "currency": "GBP",
        "maturity_date": None,
    }


def _cash_collateral(
    beneficiary_ref: str,
    market_value: float,
    beneficiary_type: str = "exposure",
    currency: str = "GBP",
) -> dict:
    """Create a cash collateral row with all required haircut fields."""
    return {
        "collateral_reference": f"COLL_{beneficiary_ref}",
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": "cash",
        "market_value": market_value,
        "currency": currency,
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "is_eligible_financial_collateral": True,
        "pledge_percentage": None,
        "collateral_maturity_date": None,
    }


def _run_crm(
    processor: CRMProcessor,
    config: CalculationConfig,
    exposure_rows: list[dict],
    collateral_rows: list[dict],
) -> pl.DataFrame:
    """Run CRM pipeline and return collected result."""
    exposures = pl.LazyFrame(exposure_rows)
    collateral_schema = {
        "collateral_reference": pl.String,
        "beneficiary_reference": pl.String,
        "beneficiary_type": pl.String,
        "collateral_type": pl.String,
        "market_value": pl.Float64,
        "currency": pl.String,
        "issuer_cqs": pl.Int64,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "pledge_percentage": pl.Float64,
        "collateral_maturity_date": pl.Date,
    }
    collateral = pl.LazyFrame(collateral_rows, schema=collateral_schema)
    bundle = _make_bundle(exposures, collateral)
    result = processor.get_crm_adjusted_bundle(bundle, config)
    return result.exposures.collect()


# =============================================================================
# Tests: SA EAD Reduction Multi-Level
# =============================================================================


class TestDirectCollateralBaseline:
    """Baseline: direct collateral still works as before."""

    def test_direct_collateral_reduces_sa_ead(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Direct collateral (beneficiary_type='exposure') reduces SA EAD."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0)],
            [_cash_collateral("EXP001", market_value=400.0, beneficiary_type="exposure")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(600.0, abs=1.0)


class TestFacilityLevelCollateral:
    """Facility-level collateral flows to child exposures."""

    def test_facility_collateral_reduces_sa_ead_single_child(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Facility cash collateral with one child reduces that child's SA EAD."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=400.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        # Single child gets 100% of facility collateral → 1000 - 400 = 600
        assert ead_after == pytest.approx(600.0, abs=1.0)

    def test_facility_collateral_reduces_sa_ead_pro_rata(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Facility collateral split pro-rata across multiple children by EAD."""
        # EXP001: drawn=600 (60%), EXP002: drawn=400 (40%), total=1000
        # Collateral: 500 → EXP001 gets 300, EXP002 gets 200
        result = _run_crm(
            processor,
            sa_config,
            [
                _sa_exposure("EXP001", drawn=600.0, facility_ref="FAC001"),
                _sa_exposure("EXP002", drawn=400.0, facility_ref="FAC001"),
            ],
            [_cash_collateral("FAC001", market_value=500.0, beneficiary_type="facility")],
        )
        row1 = result.filter(pl.col("exposure_reference") == "EXP001")
        row2 = result.filter(pl.col("exposure_reference") == "EXP002")
        # EXP001: 600 - (500 * 600/1000) = 600 - 300 = 300
        assert row1["ead_after_collateral"][0] == pytest.approx(300.0, abs=1.0)
        # EXP002: 400 - (500 * 400/1000) = 400 - 200 = 200
        assert row2["ead_after_collateral"][0] == pytest.approx(200.0, abs=1.0)


class TestCounterpartyLevelCollateral:
    """Counterparty-level collateral flows to child exposures."""

    def test_counterparty_collateral_reduces_sa_ead_pro_rata(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Counterparty collateral split pro-rata across all exposures for that CP."""
        # EXP001: drawn=700 (70%), EXP002: drawn=300 (30%), total=1000
        # Collateral: 200 → EXP001 gets 140, EXP002 gets 60
        result = _run_crm(
            processor,
            sa_config,
            [
                _sa_exposure("EXP001", drawn=700.0, cp_ref="CP001"),
                _sa_exposure("EXP002", drawn=300.0, cp_ref="CP001"),
            ],
            [_cash_collateral("CP001", market_value=200.0, beneficiary_type="counterparty")],
        )
        row1 = result.filter(pl.col("exposure_reference") == "EXP001")
        row2 = result.filter(pl.col("exposure_reference") == "EXP002")
        # EXP001: 700 - (200 * 700/1000) = 700 - 140 = 560
        assert row1["ead_after_collateral"][0] == pytest.approx(560.0, abs=1.0)
        # EXP002: 300 - (200 * 300/1000) = 300 - 60 = 240
        assert row2["ead_after_collateral"][0] == pytest.approx(240.0, abs=1.0)


class TestMixedLevelCollateral:
    """Stacking direct + facility + counterparty collateral."""

    def test_mixed_level_collateral_combines_all_levels(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """Direct + facility + counterparty collateral all contribute to SA EAD reduction."""
        # Single exposure with drawn=1000, under FAC001, counterparty CP001
        # Direct collateral: 100
        # Facility collateral: 200 (100% to single child)
        # Counterparty collateral: 150 (100% to single cp exposure)
        # Total: 450 → EAD = 1000 - 450 = 550
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", cp_ref="CP001")],
            [
                _cash_collateral("EXP001", market_value=100.0, beneficiary_type="exposure"),
                _cash_collateral("FAC001", market_value=200.0, beneficiary_type="facility"),
                _cash_collateral("CP001", market_value=150.0, beneficiary_type="counterparty"),
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(550.0, abs=1.0)


class TestIRBExposuresUnaffected:
    """FIRB exposures: collateral affects LGD, not EAD."""

    def test_facility_collateral_does_not_reduce_irb_ead(
        self, processor: CRMProcessor, firb_config: CalculationConfig
    ):
        """FIRB exposure EAD unchanged by facility-level collateral (LGD path handles it)."""
        result = _run_crm(
            processor,
            firb_config,
            [_irb_exposure("EXP001", drawn=1000.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=400.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        # IRB: EAD after collateral = ead_gross (unchanged)
        assert row["ead_after_collateral"][0] == pytest.approx(1000.0, abs=1.0)


class TestCollateralCap:
    """EAD cannot go below 0."""

    def test_collateral_capped_at_ead(self, processor: CRMProcessor, sa_config: CalculationConfig):
        """SA EAD after collateral is floored at 0 when collateral exceeds exposure."""
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=500.0, facility_ref="FAC001")],
            [_cash_collateral("FAC001", market_value=800.0, beneficiary_type="facility")],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        assert row["ead_after_collateral"][0] == pytest.approx(0.0, abs=0.01)


class TestFXHaircutMultiLevel:
    """FX haircut correctly applied for facility-level collateral."""

    def test_facility_collateral_fx_haircut_applied(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """FX haircut on facility-level collateral when currencies differ."""
        # Exposure in GBP, collateral in USD → 8% FX haircut
        # Cash has 0% collateral haircut, so adjusted = 400 * (1 - 0.0 - 0.08) = 368
        # EAD = 1000 - 368 = 632
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", currency="GBP")],
            [
                _cash_collateral(
                    "FAC001", market_value=400.0, beneficiary_type="facility", currency="USD"
                )
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        # With maturity adjustment factor applied (cash residual_maturity_years=None → 10.0 → factor=1.0)
        # So adjusted = 400 * (1 - 0.08) = 368, EAD = 1000 - 368 = 632
        assert ead_after == pytest.approx(632.0, abs=1.0)

    def test_facility_collateral_same_currency_no_fx_haircut(
        self, processor: CRMProcessor, sa_config: CalculationConfig
    ):
        """No FX haircut when facility collateral and exposure share same currency."""
        # Both in GBP → 0% FX haircut; cash 0% collateral haircut → adjusted = 400
        # EAD = 1000 - 400 = 600
        result = _run_crm(
            processor,
            sa_config,
            [_sa_exposure("EXP001", drawn=1000.0, facility_ref="FAC001", currency="GBP")],
            [
                _cash_collateral(
                    "FAC001", market_value=400.0, beneficiary_type="facility", currency="GBP"
                )
            ],
        )
        row = result.filter(pl.col("exposure_reference") == "EXP001")
        ead_after = row["ead_after_collateral"][0]
        assert ead_after == pytest.approx(600.0, abs=1.0)
