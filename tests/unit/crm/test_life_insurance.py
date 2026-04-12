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

from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.data.tables.crm_supervisory import (
    BASEL31_SUPERVISORY_LGD,
    CRR_SUPERVISORY_LGD,
)
from rwa_calc.engine.crm.constants import (
    WATERFALL_ORDER,
    collateral_category_expr,
    collateral_lgd_expr,
    min_collateralisation_threshold_expr,
    overcollateralisation_ratio_expr,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.life_insurance import (
    LIFE_INSURANCE_RW_MAP,
    _add_default_life_ins_columns,
    _map_insurer_rw_to_secured_rw_expr,
    compute_life_insurance_columns,
)

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

    def test_rw_map_dict_has_all_regulatory_values(self) -> None:
        """The mapping dict covers all insurer RW values mentioned in Art. 232."""
        expected_keys = {0.20, 0.30, 0.50, 0.65, 1.00, 1.35, 1.50}
        assert set(LIFE_INSURANCE_RW_MAP.keys()) == expected_keys


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


# --- Art. 232: Constants Integration ---


class TestLifeInsuranceConstants:
    """Test that life insurance is correctly wired into CRM constants."""

    def test_life_insurance_in_waterfall(self) -> None:
        suffixes = [suffix for _, _, suffix in WATERFALL_ORDER]
        assert "li" in suffixes, "Life insurance missing from WATERFALL_ORDER"

    def test_life_insurance_lgds_crr_is_40pct(self) -> None:
        assert CRR_SUPERVISORY_LGD["life_insurance"] == pytest.approx(0.40)

    def test_life_insurance_lgds_b31_is_40pct(self) -> None:
        assert BASEL31_SUPERVISORY_LGD["life_insurance"] == pytest.approx(0.40)

    def test_collateral_lgd_expr_maps_life_insurance(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(collateral_lgd_expr(False).alias("lgd")).collect()
        assert result["lgd"][0] == pytest.approx(0.40)

    def test_overcollateralisation_ratio_is_1(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(overcollateralisation_ratio_expr().alias("oc")).collect()
        assert result["oc"][0] == pytest.approx(1.0)

    def test_min_collateralisation_threshold_is_0(self) -> None:
        df = pl.DataFrame({"collateral_type": ["life_insurance"]}).lazy()
        result = df.with_columns(min_collateralisation_threshold_expr().alias("thresh")).collect()
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
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.calculate_single_haircut(
            collateral_type="life_insurance",
            market_value=Decimal("50000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0")
        assert result.adjusted_value == Decimal("50000")

    def test_life_insurance_fx_mismatch_still_applies(self) -> None:
        """FX mismatch haircut should still apply for life insurance (currency risk)."""
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.calculate_single_haircut(
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
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.calculate_single_haircut(
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
        result = df.with_columns(collateral_lgd_expr(False).alias("lgd")).collect()
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
        from rwa_calc.engine.sa.calculator import SACalculator

        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead": [1000.0],
                "life_ins_collateral_value": [500.0],
                "life_ins_secured_rw": [0.35],
            }
        ).lazy()
        result = SACalculator._apply_life_insurance_rw_mapping(exposures).collect()
        # Blended: 50% * 0.35 + 50% * 1.00 = 0.175 + 0.50 = 0.675
        assert result["risk_weight"][0] == pytest.approx(0.675)

    def test_no_life_ins_keeps_original_rw(self) -> None:
        from rwa_calc.engine.sa.calculator import SACalculator

        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead": [1000.0],
                "life_ins_collateral_value": [0.0],
                "life_ins_secured_rw": [0.0],
            }
        ).lazy()
        result = SACalculator._apply_life_insurance_rw_mapping(exposures).collect()
        assert result["risk_weight"][0] == pytest.approx(1.00)

    def test_full_coverage_uses_mapped_rw_only(self) -> None:
        from rwa_calc.engine.sa.calculator import SACalculator

        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead": [1000.0],
                "life_ins_collateral_value": [1000.0],
                "life_ins_secured_rw": [0.20],
            }
        ).lazy()
        result = SACalculator._apply_life_insurance_rw_mapping(exposures).collect()
        # 100% secured -> mapped RW = 0.20
        assert result["risk_weight"][0] == pytest.approx(0.20)

    def test_no_20pct_floor_unlike_fcsm(self) -> None:
        """Art. 232 has no 20% floor — unlike FCSM Art. 222(1)."""
        from rwa_calc.engine.sa.calculator import SACalculator

        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead": [1000.0],
                "life_ins_collateral_value": [1000.0],
                "life_ins_secured_rw": [0.20],  # Lowest possible mapped RW
            }
        ).lazy()
        result = SACalculator._apply_life_insurance_rw_mapping(exposures).collect()
        # Should be exactly 0.20, not floored higher
        assert result["risk_weight"][0] == pytest.approx(0.20)

    def test_missing_columns_is_noop(self) -> None:
        from rwa_calc.engine.sa.calculator import SACalculator

        exposures = pl.DataFrame(
            {
                "risk_weight": [1.00],
                "ead": [1000.0],
            }
        ).lazy()
        result = SACalculator._apply_life_insurance_rw_mapping(exposures).collect()
        assert result["risk_weight"][0] == pytest.approx(1.00)


# --- Default Columns ---


class TestDefaultLifeInsColumns:
    def test_adds_zero_columns(self) -> None:
        df = pl.DataFrame({"a": [1, 2]}).lazy()
        result = _add_default_life_ins_columns(df).collect()
        assert result["life_ins_collateral_value"].to_list() == [0.0, 0.0]
        assert result["life_ins_secured_rw"].to_list() == [0.0, 0.0]
