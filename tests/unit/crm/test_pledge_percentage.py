"""
Tests for pledge_percentage resolution in CRM collateral processing.

When collateral has pledge_percentage set instead of market_value, the system
resolves it to an absolute market_value based on the beneficiary's total EAD
before haircuts are applied.

Covers:
- No pledge_percentage column → collateral passes through unchanged
- Direct-level pledge_percentage → market_value = pct * exposure ead_gross
- market_value takes priority over pledge_percentage
- Facility-level pledge_percentage → market_value = pct * sum(facility exposure EADs)
- Counterparty-level pledge_percentage → market_value = pct * sum(cp exposure EADs)
- Mixed rows: some with market_value, some with pledge_percentage
- End-to-end: pledge_percentage cash → haircuts → LGD calculation
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.crm.processor import (
    CRMProcessor,
    _build_exposure_lookups,
    _join_collateral_to_lookups,
    _resolve_pledge_from_joined,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crm_processor() -> CRMProcessor:
    """Create CRM processor instance."""
    return CRMProcessor()


@pytest.fixture
def sa_config() -> CalculationConfig:
    """SA-only CRR config."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture
def firb_config() -> CalculationConfig:
    """F-IRB CRR config."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


# =============================================================================
# Helpers
# =============================================================================


def _base_exposure(
    ref: str = "EXP001",
    drawn: float = 1000.0,
    approach: str = "standardised",
    counterparty_ref: str = "CP001",
    parent_facility: str | None = None,
) -> dict:
    """Return a single exposure row dict with ead_gross already set."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": counterparty_ref,
        "exposure_class": "corporate",
        "approach": approach,
        "drawn_amount": drawn,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "undrawn_amount": 0.0,
        "risk_type": None,
        "lgd": 0.45,
        "seniority": "senior",
        "currency": "GBP",
        "maturity_date": date(2030, 12, 31),
        "value_date": date(2024, 1, 1),
        "ead_pre_crm": drawn,
        "ead_gross": drawn,
        "parent_facility_reference": parent_facility,
    }


def _base_collateral(
    ref: str = "COLL001",
    beneficiary_ref: str = "EXP001",
    beneficiary_type: str = "loan",
    collateral_type: str = "cash",
    market_value: float | None = None,
    pledge_percentage: float | None = None,
) -> dict:
    """Return a single collateral row dict."""
    return {
        "collateral_reference": ref,
        "beneficiary_reference": beneficiary_ref,
        "beneficiary_type": beneficiary_type,
        "collateral_type": collateral_type,
        "market_value": market_value,
        "nominal_value": market_value,
        "pledge_percentage": pledge_percentage,
        "currency": "GBP",
        "maturity_date": date(2030, 12, 31),
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        # Haircut-related columns (typed defaults for Polars compatibility)
        "residual_maturity_years": 10.0,  # High value → no maturity mismatch penalty
        "issuer_cqs": 1,
        "issuer_type": "",
        "is_main_index": False,
        "valuation_date": date(2024, 1, 1),
        "valuation_type": "",
        "property_type": "",
        "property_ltv": 0.0,
        "is_income_producing": False,
        "is_adc": False,
        "is_presold": False,
    }


def _run_resolve(
    processor: CRMProcessor,
    exposure_rows: list[dict],
    collateral_rows: list[dict],
) -> pl.DataFrame:
    """Run pledge resolution via combined join + resolve and return collateral."""
    exposures = pl.LazyFrame(exposure_rows)
    collateral = pl.LazyFrame(collateral_rows)
    direct_lookup, facility_lookup, cp_lookup = _build_exposure_lookups(exposures)
    joined = _join_collateral_to_lookups(
        collateral, direct_lookup, facility_lookup, cp_lookup
    )
    resolved = _resolve_pledge_from_joined(joined)
    return resolved.collect()


# =============================================================================
# Tests
# =============================================================================


class TestNoPledgePercentageColumn:
    """When collateral has no pledge_percentage column, it passes through unchanged."""

    def test_no_pledge_percentage_column_passes_through(
        self, crm_processor: CRMProcessor
    ) -> None:
        """Collateral without pledge_percentage column is returned unchanged."""
        exposures = [_base_exposure()]
        collateral_data = {
            "collateral_reference": ["COLL001"],
            "beneficiary_reference": ["EXP001"],
            "beneficiary_type": ["loan"],
            "collateral_type": ["cash"],
            "market_value": [500.0],
            "nominal_value": [500.0],
            "currency": ["GBP"],
        }
        collateral = pl.LazyFrame(collateral_data)
        exposures_lf = pl.LazyFrame(exposures)

        direct_lookup, facility_lookup, cp_lookup = _build_exposure_lookups(exposures_lf)
        joined = _join_collateral_to_lookups(
            collateral, direct_lookup, facility_lookup, cp_lookup
        )
        result = _resolve_pledge_from_joined(joined)
        df = result.collect()

        assert df["market_value"][0] == 500.0
        assert "pledge_percentage" not in df.columns


class TestDirectLevelPledgePercentage:
    """pledge_percentage on direct (exposure/loan) level collateral."""

    def test_pledge_percentage_resolves_to_market_value(
        self, crm_processor: CRMProcessor
    ) -> None:
        """pledge_percentage=0.5 on exposure with ead_gross=1000 → market_value=500."""
        exposures = [_base_exposure(drawn=1000.0)]
        collateral = [
            _base_collateral(
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                market_value=None,
                pledge_percentage=0.5,
            )
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        assert result["market_value"][0] == pytest.approx(500.0)

    def test_pledge_percentage_zero_market_value_resolves(
        self, crm_processor: CRMProcessor
    ) -> None:
        """pledge_percentage=0.5 with market_value=0 → market_value=500."""
        exposures = [_base_exposure(drawn=1000.0)]
        collateral = [
            _base_collateral(
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                market_value=0.0,
                pledge_percentage=0.5,
            )
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        assert result["market_value"][0] == pytest.approx(500.0)


class TestMarketValueTakesPriority:
    """When market_value is set, pledge_percentage is ignored."""

    def test_market_value_present_ignores_pledge_percentage(
        self, crm_processor: CRMProcessor
    ) -> None:
        """market_value=1000 + pledge_percentage=0.5 → market_value stays 1000."""
        exposures = [_base_exposure(drawn=2000.0)]
        collateral = [
            _base_collateral(
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                market_value=1000.0,
                pledge_percentage=0.5,
            )
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        assert result["market_value"][0] == pytest.approx(1000.0)


class TestFacilityLevelPledgePercentage:
    """pledge_percentage on facility-level collateral uses sum of facility exposure EADs."""

    def test_facility_level_pledge_resolves_to_sum_of_eads(
        self, crm_processor: CRMProcessor
    ) -> None:
        """
        Facility FAC001 has two exposures: EXP001 (ead=600), EXP002 (ead=400).
        pledge_percentage=0.5 → market_value = 0.5 * (600+400) = 500.
        """
        exposures = [
            _base_exposure(ref="EXP001", drawn=600.0, parent_facility="FAC001"),
            _base_exposure(ref="EXP002", drawn=400.0, parent_facility="FAC001"),
        ]
        collateral = [
            _base_collateral(
                beneficiary_ref="FAC001",
                beneficiary_type="facility",
                market_value=None,
                pledge_percentage=0.5,
            )
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        assert result["market_value"][0] == pytest.approx(500.0)


class TestCounterpartyLevelPledgePercentage:
    """pledge_percentage on counterparty-level collateral uses sum of counterparty exposure EADs."""

    def test_counterparty_level_pledge_resolves_to_sum_of_eads(
        self, crm_processor: CRMProcessor
    ) -> None:
        """
        Counterparty CP001 has two exposures: EXP001 (ead=700), EXP002 (ead=300).
        pledge_percentage=0.3 → market_value = 0.3 * (700+300) = 300.
        """
        exposures = [
            _base_exposure(ref="EXP001", drawn=700.0, counterparty_ref="CP001"),
            _base_exposure(ref="EXP002", drawn=300.0, counterparty_ref="CP001"),
        ]
        collateral = [
            _base_collateral(
                beneficiary_ref="CP001",
                beneficiary_type="counterparty",
                market_value=None,
                pledge_percentage=0.3,
            )
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        assert result["market_value"][0] == pytest.approx(300.0)


class TestMixedCollateral:
    """Some rows have market_value, others have pledge_percentage."""

    def test_mixed_rows_resolved_correctly(
        self, crm_processor: CRMProcessor
    ) -> None:
        """
        COLL001: market_value=200 (kept as-is)
        COLL002: pledge_percentage=0.5, no market_value → resolved from EAD
        """
        exposures = [_base_exposure(drawn=1000.0)]
        collateral = [
            _base_collateral(
                ref="COLL001",
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                market_value=200.0,
                pledge_percentage=None,
            ),
            _base_collateral(
                ref="COLL002",
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                market_value=None,
                pledge_percentage=0.5,
            ),
        ]

        result = _run_resolve(crm_processor, exposures, collateral)

        coll1 = result.filter(pl.col("collateral_reference") == "COLL001")
        coll2 = result.filter(pl.col("collateral_reference") == "COLL002")

        assert coll1["market_value"][0] == pytest.approx(200.0)
        assert coll2["market_value"][0] == pytest.approx(500.0)


class TestEndToEndViaApplyCollateral:
    """pledge_percentage flows through apply_collateral → haircuts → EAD reduction."""

    def test_pledge_percentage_cash_reduces_ead_for_sa(
        self,
        crm_processor: CRMProcessor,
        sa_config: CalculationConfig,
    ) -> None:
        """
        SA exposure with ead_gross=1000.
        Cash collateral with pledge_percentage=0.5 → market_value=500.
        Cash has 0% haircut → adjusted_value=500.
        ead_after_collateral = 1000 - 500 = 500.
        """
        exposures_lf = pl.LazyFrame([
            _base_exposure(drawn=1000.0, approach="standardised", parent_facility="FAC001"),
        ])
        # Initialize EAD columns that apply_collateral expects
        exposures_lf = exposures_lf.with_columns([
            pl.col("ead_pre_crm").alias("ead_gross"),
            pl.col("ead_pre_crm").alias("ead_after_collateral"),
            pl.lit(0.45).alias("lgd_pre_crm"),
            pl.lit(0.45).alias("lgd_post_crm"),
        ])

        collateral_lf = pl.LazyFrame([
            _base_collateral(
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                collateral_type="cash",
                market_value=None,
                pledge_percentage=0.5,
            )
        ])

        result = crm_processor.apply_collateral(exposures_lf, collateral_lf, sa_config)
        df = result.collect()

        # Cash has 0% haircut, so full 500 reduces EAD
        assert df["ead_after_collateral"][0] == pytest.approx(500.0)

    def test_pledge_percentage_with_firb_affects_lgd(
        self,
        crm_processor: CRMProcessor,
        firb_config: CalculationConfig,
    ) -> None:
        """
        F-IRB exposure with ead_gross=1000.
        Cash collateral with pledge_percentage=1.0 → market_value=1000.
        Cash has 0% haircut, financial collateral LGD=0%, fully secured.
        lgd_post_crm should be 0% (fully secured by financial collateral).
        """
        exposures_lf = pl.LazyFrame([
            _base_exposure(drawn=1000.0, approach="foundation_irb", parent_facility="FAC001"),
        ])
        exposures_lf = exposures_lf.with_columns([
            pl.col("ead_pre_crm").alias("ead_gross"),
            pl.col("ead_pre_crm").alias("ead_after_collateral"),
            pl.lit(0.45).alias("lgd_pre_crm"),
            pl.lit(0.45).alias("lgd_post_crm"),
        ])

        collateral_lf = pl.LazyFrame([
            _base_collateral(
                beneficiary_ref="EXP001",
                beneficiary_type="loan",
                collateral_type="cash",
                market_value=None,
                pledge_percentage=1.0,
            )
        ])

        result = crm_processor.apply_collateral(exposures_lf, collateral_lf, firb_config)
        df = result.collect()

        # Fully secured by cash (financial collateral) → LGD = 0%
        assert df["lgd_post_crm"][0] == pytest.approx(0.0)
