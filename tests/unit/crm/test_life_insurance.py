"""
Unit tests for Life Insurance Method (Art. 232) and Credit-Linked Notes (Art. 218).

Tests verify:
- Art. 232: Life insurance collateral SA risk weight mapping
- Art. 232: Life insurance F-IRB LGD = 40% via waterfall
- Art. 232: No SA EAD reduction for life insurance collateral
- Art. 218: Credit-linked notes treated as cash collateral (0% haircut)
- Integration with CRM processor pipeline
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN,
    CalculationError,
)
from rwa_calc.engine.crm.expressions import (
    WATERFALL_ORDER,
    collateral_category_expr,
    collateral_lgd_expr,
    min_collateralisation_threshold_expr,
    overcollateralisation_ratio_expr,
    supervisory_lgd_values,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.life_insurance import (
    _add_default_life_ins_columns,
    _map_insurer_rw_to_secured_rw_expr,
    compute_life_insurance_columns,
)
from rwa_calc.engine.sa.rw_adjustments import apply_life_insurance_rw_mapping
from rwa_calc.rulebook.resolve import resolve

# Resolved packs for the per-expression unit tests (the CRM collateral builders
# now read their values + regime Features from the rulepack).
_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


def test_supervisory_lgd_values_crr_projection_byte_identical() -> None:
    # Assert — the canonical DecisionTable projects to the exact CRR CRM-shape
    # dict (literal pin of the former data/tables CRR_SUPERVISORY_LGD).
    assert supervisory_lgd_values(_CRR_PACK) == {
        "financial": 0.0,
        "receivables": 0.35,
        "real_estate": 0.35,
        "other_physical": 0.40,
        "unsecured": 0.45,
        "covered_bond": 0.1125,
        "life_insurance": 0.40,
        "receivables_subordinated": 0.65,
        "real_estate_subordinated": 0.65,
        "other_physical_subordinated": 0.70,
    }


def test_supervisory_lgd_values_b31_projection_byte_identical() -> None:
    # Assert — and to the exact Basel 3.1 CRM-shape dict (the flagged collapse;
    # literal pin of the former data/tables BASEL31_SUPERVISORY_LGD).
    assert supervisory_lgd_values(_B31_PACK) == {
        "financial": 0.0,
        "receivables": 0.20,
        "real_estate": 0.20,
        "other_physical": 0.25,
        "unsecured": 0.40,
        "unsecured_fse": 0.45,
        "covered_bond": 0.1125,
        "life_insurance": 0.40,
    }


# --- Art. 232: Risk Weight Mapping Table ---


class TestLifeInsuranceRWMapping:
    """Test Art. 232 insurer RW -> secured portion RW mapping."""

    def test_rw_20_maps_to_20(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [0.20]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.20)

    def test_rw_30_maps_to_35(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [0.30]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.35)

    def test_rw_50_maps_to_35(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [0.50]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.35)

    def test_rw_65_maps_to_70(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [0.65]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.70)

    def test_rw_100_maps_to_70(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [1.00]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.70)

    def test_rw_135_maps_to_70(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [1.35]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.70)

    def test_rw_150_maps_to_150(self) -> None:
        df = pl.DataFrame({"insurer_risk_weight": [1.50]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(1.50)

    def test_null_rw_defaults_to_100_then_maps_to_70(self) -> None:
        """Null insurer_risk_weight defaults to 100% (conservative) -> mapped 70%."""
        df = pl.DataFrame({"insurer_risk_weight": [None]}).lazy()
        result = df.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("mapped")).collect()
        assert result["mapped"][0] == pytest.approx(0.70)

    def test_rw_map_pack_band_table_covers_art_232_bands(self) -> None:
        """The Art. 232 pack band table holds the canonical insurer-RW -> secured-RW bands."""
        bands = _CRR_PACK.banded("life_insurance_secured_rw_map").bands
        assert [
            (float(bound) if bound is not None else None, float(value)) for bound, value in bands
        ] == [(0.20, 0.20), (0.50, 0.35), (1.35, 0.70), (None, 1.50)]


# --- Art. 232: Compute Life Insurance Columns ---


class TestComputeLifeInsuranceColumns:
    """Test life insurance column computation for SA RW blending."""

    @pytest.fixture()
    def exposures(self) -> pl.LazyFrame:
        return pl.DataFrame(
            {
                "exposure_reference": ["E1", "E2", "E3"],
                "ead_gross": [1000.0, 2000.0, 500.0],
                "currency": ["GBP", "GBP", "GBP"],
            }
        ).lazy()

    @pytest.fixture()
    def config(self) -> object:
        """Minimal config mock."""

        class _Cfg:
            is_basel_3_1 = False

        return _Cfg()

    def test_no_collateral_returns_zero_columns(self, exposures, config) -> None:
        result = compute_life_insurance_columns(exposures, None, config).collect()
        assert "life_ins_collateral_value" in result.columns
        assert "life_ins_secured_rw" in result.columns
        assert result["life_ins_collateral_value"].to_list() == [0.0, 0.0, 0.0]

    def test_no_life_insurance_in_collateral(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["cash"],
                "market_value": [500.0],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        assert result["life_ins_collateral_value"].to_list() == [0.0, 0.0, 0.0]

    def test_life_insurance_value_allocated_to_exposure(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(400.0)
        # 50% insurer RW -> 35% mapped RW
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.35)

    def test_life_insurance_value_capped_at_ead(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E3"],
                "collateral_type": ["life_insurance"],
                "market_value": [999.0],  # exceeds E3 EAD of 500
                "insurer_risk_weight": [0.20],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e3 = result.filter(pl.col("exposure_reference") == "E3")
        assert e3["life_ins_collateral_value"][0] == pytest.approx(500.0)  # capped at EAD

    def test_multiple_life_insurance_policies(self, exposures, config) -> None:
        """Multiple policies on same exposure: value-weighted average RW."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E2", "E2"],
                "collateral_type": ["life_insurance", "life_insurance"],
                "market_value": [600.0, 400.0],
                "insurer_risk_weight": [0.20, 1.00],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        assert e2["life_ins_collateral_value"][0] == pytest.approx(1000.0)
        # Weighted avg: (600*0.20 + 400*0.70) / 1000 = (120 + 280) / 1000 = 0.40
        assert e2["life_ins_secured_rw"][0] == pytest.approx(0.40)

    def test_missing_insurer_rw_defaults_to_70pct(self, exposures, config) -> None:
        """Missing insurer_risk_weight column defaults to 100% -> mapped 70%."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [300.0],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.70)


# --- Art. 233(3): Currency-mismatch 8% reduction ---


class TestLifeInsuranceFXMismatch:
    """Art. 233(3): the surrender value takes an 8% FX reduction on a currency mismatch."""

    @pytest.fixture()
    def exposures(self) -> pl.LazyFrame:
        return pl.DataFrame(
            {
                "exposure_reference": ["E1"],
                "ead_gross": [1000.0],
                "currency": ["GBP"],
            }
        ).lazy()

    @pytest.fixture()
    def config(self) -> object:
        class _Cfg:
            is_basel_3_1 = False

        return _Cfg()

    def test_matched_currency_no_reduction(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": ["GBP"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(400.0)
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.35)

    def test_mismatched_currency_takes_8pct_cut(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": ["USD"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        # 400 * (1 - 0.08) = 368 ; mapped RW unchanged at 0.35
        assert e1["life_ins_collateral_value"][0] == pytest.approx(368.0)
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.35)

    def test_original_currency_wins_over_reporting_currency(self, exposures, config) -> None:
        """Post-FX-conversion the value is in reporting currency; the mismatch must be
        judged on the pre-conversion original_currency pair (P1.135)."""
        # Exposure: reporting GBP, pre-conversion original_currency GBP.
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["E1"],
                "ead_gross": [1000.0],
                "currency": ["GBP"],
                "original_currency": ["GBP"],
            }
        ).lazy()
        # Collateral converted to GBP but original_currency preserves the USD denomination.
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.20],
                "currency": ["GBP"],
                "original_currency": ["USD"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(368.0)

    def test_null_policy_currency_takes_conservative_cut(self, exposures, config) -> None:
        """A present-but-null policy currency cannot prove a match -> conservative 8% cut."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": [None],
            },
            schema_overrides={"currency": pl.String},
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(368.0)

    def test_absent_currency_column_no_cut(self, exposures, config) -> None:
        """No currency column on the collateral -> no FX dimension -> full value (number-neutral)."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(400.0)

    def test_regime_parity_fx_reduction_identical(self, exposures) -> None:
        """Art. 232/233 are retained unchanged under PS1/26 -> identical FX reduction."""
        crr_cfg = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
        b31_cfg = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": ["USD"],
            }
        ).lazy()
        crr = compute_life_insurance_columns(exposures, collateral, crr_cfg).collect()
        b31 = compute_life_insurance_columns(exposures, collateral, b31_cfg).collect()
        assert (
            crr["life_ins_collateral_value"][0]
            == pytest.approx(b31["life_ins_collateral_value"][0])
            == pytest.approx(368.0)
        )

    def test_mixed_currency_pool_cuts_only_mismatched_portion(self, exposures, config) -> None:
        """A pool of a GBP + a USD policy on one GBP exposure cuts ONLY the USD share
        (cut-then-sum): 100 + 900×0.92 = 928, NOT the anti-conservative 1000 or 920."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1", "E1"],
                "collateral_type": ["life_insurance", "life_insurance"],
                "market_value": [100.0, 900.0],
                "insurer_risk_weight": [0.20, 0.20],
                "currency": ["GBP", "USD"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(928.0)
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.20)

    def test_mixed_currency_pool_is_order_independent(self, exposures, config) -> None:
        """The reversed row order yields the identical 928 — no `.first()` currency
        nondeterminism (the pool is summed, not sampled)."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1", "E1"],
                "collateral_type": ["life_insurance", "life_insurance"],
                "market_value": [900.0, 100.0],
                "insurer_risk_weight": [0.20, 0.20],
                "currency": ["USD", "GBP"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(928.0)


# --- Art. 232(3): Multi-level (facility/counterparty) pledges ---


class TestLifeInsuranceMultiLevelPledge:
    """A policy pledged at facility or counterparty level flows pro-rata to the exposures."""

    @pytest.fixture()
    def exposures(self) -> pl.LazyFrame:
        # Two exposures under facility F1 / counterparty C1, EAD 600 and 400.
        return pl.DataFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "counterparty_reference": ["C1", "C1"],
                "parent_facility_reference": ["F1", "F1"],
                "ead_gross": [600.0, 400.0],
                "currency": ["GBP", "GBP"],
            }
        ).lazy()

    @pytest.fixture()
    def config(self) -> object:
        class _Cfg:
            is_basel_3_1 = False

        return _Cfg()

    def test_facility_level_pledge_allocates_pro_rata(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["F1"],
                "collateral_type": ["life_insurance"],
                "market_value": [1000.0],
                "insurer_risk_weight": [0.20],
                "currency": ["GBP"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        # 1000 shared pro-rata by EAD: E1 600, E2 400 (each capped at its own EAD).
        assert e1["life_ins_collateral_value"][0] == pytest.approx(600.0)
        assert e2["life_ins_collateral_value"][0] == pytest.approx(400.0)
        assert e1["life_ins_secured_rw"][0] == pytest.approx(0.20)
        assert e2["life_ins_secured_rw"][0] == pytest.approx(0.20)

    def test_counterparty_level_pledge_allocates_pro_rata(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["C1"],
                "collateral_type": ["life_insurance"],
                "market_value": [1000.0],
                "insurer_risk_weight": [0.20],
                "currency": ["GBP"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(600.0)
        assert e2["life_ins_collateral_value"][0] == pytest.approx(400.0)

    def test_direct_pledge_takes_precedence_over_siblings(self, exposures, config) -> None:
        """A policy pledged to a single exposure benefits only that exposure, not its siblings."""
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [500.0],
                "insurer_risk_weight": [0.20],
                "currency": ["GBP"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(500.0)
        assert e2["life_ins_collateral_value"][0] == pytest.approx(0.0)

    def test_facility_pledge_with_fx_mismatch_cuts_each_share(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "beneficiary_reference": ["F1"],
                "collateral_type": ["life_insurance"],
                "market_value": [1000.0],
                "insurer_risk_weight": [0.20],
                "currency": ["USD"],
            }
        ).lazy()
        result = compute_life_insurance_columns(exposures, collateral, config).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        e2 = result.filter(pl.col("exposure_reference") == "E2")
        # Each pro-rata share takes the 8% cut: E1 600*0.92=552, E2 400*0.92=368.
        assert e1["life_ins_collateral_value"][0] == pytest.approx(552.0)
        assert e2["life_ins_collateral_value"][0] == pytest.approx(368.0)


# --- Art. 233(3): CRM020 unknown-currency warning ---


class TestLifeInsuranceCurrencyWarning:
    """A null policy currency (column present) raises CRM020 alongside the conservative cut."""

    @pytest.fixture()
    def exposures(self) -> pl.LazyFrame:
        return pl.DataFrame(
            {
                "exposure_reference": ["E1"],
                "ead_gross": [1000.0],
                "currency": ["GBP"],
            }
        ).lazy()

    @pytest.fixture()
    def config(self) -> object:
        class _Cfg:
            is_basel_3_1 = False

        return _Cfg()

    def test_null_currency_raises_crm020(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "collateral_reference": ["POL1"],
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": [None],
            },
            schema_overrides={"currency": pl.String},
        ).lazy()
        errors: list[CalculationError] = []
        compute_life_insurance_columns(exposures, collateral, config, errors=errors).collect()
        crm020 = [e for e in errors if e.code == ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN]
        assert len(crm020) == 1

    def test_matched_currency_raises_no_warning(self, exposures, config) -> None:
        collateral = pl.DataFrame(
            {
                "collateral_reference": ["POL1"],
                "beneficiary_reference": ["E1"],
                "collateral_type": ["life_insurance"],
                "market_value": [400.0],
                "insurer_risk_weight": [0.50],
                "currency": ["GBP"],
            }
        ).lazy()
        errors: list[CalculationError] = []
        compute_life_insurance_columns(exposures, collateral, config, errors=errors).collect()
        assert not [e for e in errors if e.code == ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN]

    def test_mixed_pool_null_policy_cut_per_policy_and_one_warning(self, exposures, config) -> None:
        """In a GBP + null-currency pool, only the null policy is cut (100 + 900×0.92 =
        928) and exactly one CRM020 is raised — cut and warning are coherent per policy."""
        collateral = pl.DataFrame(
            {
                "collateral_reference": ["POL_GBP", "POL_NULL"],
                "beneficiary_reference": ["E1", "E1"],
                "collateral_type": ["life_insurance", "life_insurance"],
                "market_value": [100.0, 900.0],
                "insurer_risk_weight": [0.20, 0.20],
                "currency": ["GBP", None],
            },
            schema_overrides={"currency": pl.String},
        ).lazy()
        errors: list[CalculationError] = []
        result = compute_life_insurance_columns(
            exposures, collateral, config, errors=errors
        ).collect()
        e1 = result.filter(pl.col("exposure_reference") == "E1")
        assert e1["life_ins_collateral_value"][0] == pytest.approx(928.0)
        assert len([e for e in errors if e.code == ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN]) == 1


# --- Art. 232: Constants Integration ---


class TestLifeInsuranceConstants:
    """Test that life insurance is correctly wired into CRM constants."""

    def test_life_insurance_in_waterfall(self) -> None:
        suffixes = [suffix for _, _, suffix in WATERFALL_ORDER]
        assert "li" in suffixes, "Life insurance missing from WATERFALL_ORDER"

    def test_life_insurance_lgds_crr_is_40pct(self) -> None:
        assert supervisory_lgd_values(_CRR_PACK)["life_insurance"] == pytest.approx(0.40)

    def test_life_insurance_lgds_b31_is_40pct(self) -> None:
        assert supervisory_lgd_values(_B31_PACK)["life_insurance"] == pytest.approx(0.40)

    def test_collateral_lgd_expr_maps_life_insurance(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(collateral_lgd_expr(_CRR_PACK).alias("lgd")).collect()
        assert result["lgd"][0] == pytest.approx(0.40)

    def test_overcollateralisation_ratio_is_1(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(overcollateralisation_ratio_expr(_CRR_PACK).alias("oc")).collect()
        assert result["oc"][0] == pytest.approx(1.0)

    def test_min_collateralisation_threshold_is_0(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(
            min_collateralisation_threshold_expr(_CRR_PACK).alias("thresh")
        ).collect()
        assert result["thresh"][0] == pytest.approx(0.0)

    def test_collateral_category_is_life_insurance(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(collateral_category_expr().alias("cat")).collect()
        assert result["cat"][0] == "life_insurance"


# --- Art. 232: Haircut = 0% ---


class TestLifeInsuranceHaircut:
    """Test that life insurance gets 0% supervisory haircut."""

    def test_life_insurance_haircut_is_zero(self) -> None:
        """Life insurance collateral gets 0% haircut — surrender value is the effective value."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=False,
            collateral_type="life_insurance",
            market_value=Decimal("50000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0")
        assert result.adjusted_value == Decimal("50000")

    def test_life_insurance_fx_mismatch_still_applies(self) -> None:
        """FX mismatch haircut should still apply for life insurance (currency risk)."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=False,
            collateral_type="life_insurance",
            market_value=Decimal("50000"),
            collateral_currency="EUR",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0")
        assert result.fx_haircut == Decimal("0.08")
        # Adjusted = 50000 * (1 - 0 - 0.08) = 46000
        assert result.adjusted_value == Decimal("46000")


# --- Art. 218: Credit-Linked Notes ---


class TestCreditLinkedNotes:
    """Test that credit-linked notes are treated as cash collateral."""

    def test_cln_normalized_to_cash(self) -> None:
        """CLN type normalizes to 'cash' in haircut lookup -> 0% haircut."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=False,
            collateral_type="credit_linked_note",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0")
        assert result.adjusted_value == Decimal("100000")

    def test_cln_category_is_financial(self) -> None:
        """CLN should be categorised as financial collateral."""
        df = pl.DataFrame({"collateral_type": ["credit_linked_note"]}).lazy()
        result = df.with_columns(collateral_category_expr().alias("cat")).collect()
        assert result["cat"][0] == "financial"

    def test_cln_lgds_is_zero(self) -> None:
        """CLN treated as financial -> LGDS = 0%."""
        df = pl.DataFrame({"collateral_type": ["credit_linked_note"]}).lazy()
        result = df.with_columns(collateral_lgd_expr(_CRR_PACK).alias("lgd")).collect()
        assert result["lgd"][0] == pytest.approx(0.0)

    def test_cln_in_valid_collateral_types(self) -> None:
        from rwa_calc.data.schemas import VALID_COLLATERAL_TYPES

        assert "credit_linked_note" in VALID_COLLATERAL_TYPES

    def test_life_insurance_in_valid_collateral_types(self) -> None:
        from rwa_calc.data.schemas import VALID_COLLATERAL_TYPES

        assert "life_insurance" in VALID_COLLATERAL_TYPES


# --- SA Calculator Integration ---


class TestSALifeInsuranceRWBlending:
    """Test SA calculator life insurance RW blending."""

    def test_life_ins_blends_risk_weight(self) -> None:
        """Secured portion gets mapped RW, unsecured keeps original RW."""
        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead_final": [1000.0],
                "life_ins_collateral_value": [500.0],
                "life_ins_secured_rw": [0.35],
            }
        ).lazy()
        result = apply_life_insurance_rw_mapping(exposures).collect()
        # Blended: 50% * 0.35 + 50% * 1.00 = 0.175 + 0.50 = 0.675
        assert result["risk_weight"][0] == pytest.approx(0.675)

    def test_no_life_ins_keeps_original_rw(self) -> None:
        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead_final": [1000.0],
                "life_ins_collateral_value": [0.0],
                "life_ins_secured_rw": [0.0],
            }
        ).lazy()
        result = apply_life_insurance_rw_mapping(exposures).collect()
        assert result["risk_weight"][0] == pytest.approx(1.00)

    def test_full_coverage_uses_mapped_rw_only(self) -> None:
        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead_final": [1000.0],
                "life_ins_collateral_value": [1000.0],
                "life_ins_secured_rw": [0.20],
            }
        ).lazy()
        result = apply_life_insurance_rw_mapping(exposures).collect()
        # 100% secured -> mapped RW = 0.20
        assert result["risk_weight"][0] == pytest.approx(0.20)

    def test_no_20pct_floor_unlike_fcsm(self) -> None:
        """Art. 232 has no 20% floor — unlike FCSM Art. 222(1)."""
        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead_final": [1000.0],
                "life_ins_collateral_value": [1000.0],
                "life_ins_secured_rw": [0.20],  # Lowest possible mapped RW
            }
        ).lazy()
        result = apply_life_insurance_rw_mapping(exposures).collect()
        # Should be exactly 0.20, not floored higher
        assert result["risk_weight"][0] == pytest.approx(0.20)

    def test_null_life_ins_values_is_noop(self) -> None:
        """Null life-insurance values (contract columns present) are a no-op."""
        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead_final": [1000.0],
                "life_ins_collateral_value": [None],
                "life_ins_secured_rw": [None],
            },
            schema_overrides={
                "life_ins_collateral_value": pl.Float64,
                "life_ins_secured_rw": pl.Float64,
            },
        ).lazy()
        result = apply_life_insurance_rw_mapping(exposures).collect()
        assert result["risk_weight"][0] == pytest.approx(1.00)


# --- Default Columns ---


class TestDefaultLifeInsColumns:
    def test_adds_zero_columns(self) -> None:
        df = pl.DataFrame({"a": [1, 2]}).lazy()
        result = _add_default_life_ins_columns(df).collect()
        assert result["life_ins_collateral_value"].to_list() == [0.0, 0.0]
        assert result["life_ins_secured_rw"].to_list() == [0.0, 0.0]
