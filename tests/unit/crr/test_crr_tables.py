"""
Unit tests for CRR data tables.

Tests verify:
- Lookup tables contain expected values per CRR regulations
- Lookup functions return correct values
- DataFrames have correct schemas
- Edge cases are handled correctly
"""

from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_UK,
    INSTITUTION_RISK_WEIGHTS_STANDARD,
    CORPORATE_RISK_WEIGHTS,
    RETAIL_RISK_WEIGHT,
    RESIDENTIAL_MORTGAGE_PARAMS,
    COMMERCIAL_RE_PARAMS,
    get_all_risk_weight_tables,
    get_combined_cqs_risk_weights,
    lookup_risk_weight,
    calculate_residential_mortgage_rw,
    calculate_commercial_re_rw,
)
from rwa_calc.data.tables.crr_haircuts import (
    COLLATERAL_HAIRCUTS,
    FX_HAIRCUT,
    get_haircut_table,
    lookup_collateral_haircut,
    lookup_fx_haircut,
    calculate_adjusted_collateral_value,
    calculate_maturity_mismatch_adjustment,
)
from rwa_calc.data.tables.crr_slotting import (
    SLOTTING_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS_HVCRE,
    get_slotting_table,
    lookup_slotting_rw,
    calculate_slotting_rwa,
)
from rwa_calc.data.tables.crr_firb_lgd import (
    FIRB_SUPERVISORY_LGD,
    CRR_PD_FLOOR,
    CRR_MATURITY_FLOOR,
    CRR_MATURITY_CAP,
    get_firb_lgd_table,
    lookup_firb_lgd,
    apply_pd_floor,
    apply_maturity_bounds,
)
from rwa_calc.domain.enums import CQS, SlottingCategory


# =============================================================================
# RISK WEIGHT TABLE TESTS
# =============================================================================

class TestSovereignRiskWeights:
    """Tests for sovereign risk weights (CRR Art. 114)."""

    def test_cqs1_zero_risk_weight(self) -> None:
        """CQS 1 sovereigns (AAA-AA) get 0% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS1] == Decimal("0.00")

    def test_cqs2_twenty_percent(self) -> None:
        """CQS 2 sovereigns (A) get 20% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS2] == Decimal("0.20")

    def test_cqs3_fifty_percent(self) -> None:
        """CQS 3 sovereigns (BBB) get 50% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS3] == Decimal("0.50")

    def test_cqs4_5_hundred_percent(self) -> None:
        """CQS 4-5 sovereigns get 100% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS4] == Decimal("1.00")
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS5] == Decimal("1.00")

    def test_cqs6_one_fifty_percent(self) -> None:
        """CQS 6 sovereigns get 150% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.CQS6] == Decimal("1.50")

    def test_unrated_hundred_percent(self) -> None:
        """Unrated sovereigns get 100% RW."""
        assert CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED] == Decimal("1.00")

    def test_lookup_function(self) -> None:
        """Test lookup_risk_weight for sovereigns."""
        assert lookup_risk_weight("CENTRAL_GOVT_CENTRAL_BANK", 1) == Decimal("0.00")
        assert lookup_risk_weight("CENTRAL_GOVT_CENTRAL_BANK", 2) == Decimal("0.20")
        assert lookup_risk_weight("CENTRAL_GOVT_CENTRAL_BANK", None) == Decimal("1.00")


class TestInstitutionRiskWeights:
    """Tests for institution risk weights (CRR Art. 120-121)."""

    def test_uk_deviation_cqs2(self) -> None:
        """UK deviation: CQS 2 institutions get 30% (not Basel 50%)."""
        assert INSTITUTION_RISK_WEIGHTS_UK[CQS.CQS2] == Decimal("0.30")
        assert INSTITUTION_RISK_WEIGHTS_STANDARD[CQS.CQS2] == Decimal("0.50")

    def test_uk_cqs1_twenty_percent(self) -> None:
        """CQS 1 institutions get 20% RW."""
        assert INSTITUTION_RISK_WEIGHTS_UK[CQS.CQS1] == Decimal("0.20")

    def test_unrated_forty_percent(self) -> None:
        """Unrated institutions get 40% RW (derived from sovereign CQS2)."""
        assert INSTITUTION_RISK_WEIGHTS_UK[CQS.UNRATED] == Decimal("0.40")

    def test_lookup_with_uk_deviation(self) -> None:
        """Test lookup function respects UK deviation."""
        assert lookup_risk_weight("INSTITUTION", 2, use_uk_deviation=True) == Decimal("0.30")
        assert lookup_risk_weight("INSTITUTION", 2, use_uk_deviation=False) == Decimal("0.50")


class TestCorporateRiskWeights:
    """Tests for corporate risk weights (CRR Art. 122)."""

    def test_cqs1_twenty_percent(self) -> None:
        """CQS 1 corporates get 20% RW."""
        assert CORPORATE_RISK_WEIGHTS[CQS.CQS1] == Decimal("0.20")

    def test_cqs2_fifty_percent(self) -> None:
        """CQS 2 corporates get 50% RW."""
        assert CORPORATE_RISK_WEIGHTS[CQS.CQS2] == Decimal("0.50")

    def test_unrated_hundred_percent(self) -> None:
        """Unrated corporates get 100% RW."""
        assert CORPORATE_RISK_WEIGHTS[CQS.UNRATED] == Decimal("1.00")

    def test_cqs5_6_one_fifty_percent(self) -> None:
        """CQS 5-6 corporates get 150% RW."""
        assert CORPORATE_RISK_WEIGHTS[CQS.CQS5] == Decimal("1.50")
        assert CORPORATE_RISK_WEIGHTS[CQS.CQS6] == Decimal("1.50")


class TestRetailRiskWeight:
    """Tests for retail risk weight (CRR Art. 123)."""

    def test_retail_seventy_five_percent(self) -> None:
        """Retail exposures get 75% RW."""
        assert RETAIL_RISK_WEIGHT == Decimal("0.75")

    def test_lookup_function(self) -> None:
        """Test lookup_risk_weight for retail."""
        assert lookup_risk_weight("RETAIL", None) == Decimal("0.75")


class TestResidentialMortgageRiskWeights:
    """Tests for residential mortgage risk weights (CRR Art. 125)."""

    def test_low_ltv_thirty_five_percent(self) -> None:
        """LTV <= 80% gets 35% RW."""
        rw, _ = calculate_residential_mortgage_rw(Decimal("0.60"))
        assert rw == Decimal("0.35")

    def test_at_threshold_thirty_five_percent(self) -> None:
        """LTV = 80% exactly gets 35% RW."""
        rw, _ = calculate_residential_mortgage_rw(Decimal("0.80"))
        assert rw == Decimal("0.35")

    def test_high_ltv_split_treatment(self) -> None:
        """LTV > 80% gets split treatment (weighted average)."""
        # 85% LTV: 80/85 at 35% + 5/85 at 75%
        rw, _ = calculate_residential_mortgage_rw(Decimal("0.85"))
        expected = (Decimal("0.80") / Decimal("0.85")) * Decimal("0.35") + \
                   (Decimal("0.05") / Decimal("0.85")) * Decimal("0.75")
        assert abs(rw - expected) < Decimal("0.001")

    def test_params_contain_expected_values(self) -> None:
        """Verify parameter constants."""
        assert RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"] == Decimal("0.80")
        assert RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"] == Decimal("0.35")
        assert RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"] == Decimal("0.75")


class TestCommercialRERiskWeights:
    """Tests for commercial RE risk weights (CRR Art. 126)."""

    def test_low_ltv_with_income_cover(self) -> None:
        """LTV <= 50% with income cover gets 50% RW."""
        rw, _ = calculate_commercial_re_rw(Decimal("0.40"), has_income_cover=True)
        assert rw == Decimal("0.50")

    def test_low_ltv_without_income_cover(self) -> None:
        """LTV <= 50% without income cover gets 100% RW."""
        rw, _ = calculate_commercial_re_rw(Decimal("0.40"), has_income_cover=False)
        assert rw == Decimal("1.00")

    def test_high_ltv(self) -> None:
        """LTV > 50% gets 100% RW regardless of income cover."""
        rw, _ = calculate_commercial_re_rw(Decimal("0.60"), has_income_cover=True)
        assert rw == Decimal("1.00")


class TestRiskWeightDataFrames:
    """Tests for risk weight DataFrame generation."""

    def test_get_all_tables_returns_dict(self) -> None:
        """get_all_risk_weight_tables returns dictionary of DataFrames."""
        tables = get_all_risk_weight_tables()
        assert isinstance(tables, dict)
        assert "central_govt_central_bank" in tables
        assert "institution" in tables
        assert "corporate" in tables
        assert "retail" in tables

    def test_combined_table_has_all_classes(self) -> None:
        """Combined CQS table contains all exposure classes."""
        df = get_combined_cqs_risk_weights()
        assert isinstance(df, pl.DataFrame)
        classes = df["exposure_class"].unique().to_list()
        assert "CENTRAL_GOVT_CENTRAL_BANK" in classes
        assert "INSTITUTION" in classes
        assert "CORPORATE" in classes


# =============================================================================
# HAIRCUT TABLE TESTS
# =============================================================================

class TestCollateralHaircuts:
    """Tests for CRM supervisory haircuts (CRR Art. 224)."""

    def test_cash_zero_haircut(self) -> None:
        """Cash has 0% haircut."""
        assert COLLATERAL_HAIRCUTS["cash"] == Decimal("0.00")

    def test_gold_fifteen_percent(self) -> None:
        """Gold has 15% haircut."""
        assert COLLATERAL_HAIRCUTS["gold"] == Decimal("0.15")

    def test_govt_bond_cqs1_by_maturity(self) -> None:
        """Government bond haircuts vary by maturity."""
        assert COLLATERAL_HAIRCUTS["govt_bond_cqs1_0_1y"] == Decimal("0.005")
        assert COLLATERAL_HAIRCUTS["govt_bond_cqs1_1_5y"] == Decimal("0.02")
        assert COLLATERAL_HAIRCUTS["govt_bond_cqs1_5y_plus"] == Decimal("0.04")

    def test_equity_main_index(self) -> None:
        """Main index equity has 15% haircut."""
        assert COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.15")

    def test_equity_other(self) -> None:
        """Other equity has 25% haircut."""
        assert COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.25")

    def test_fx_haircut(self) -> None:
        """FX mismatch haircut is 8%."""
        assert FX_HAIRCUT == Decimal("0.08")


class TestHaircutLookup:
    """Tests for haircut lookup functions."""

    def test_lookup_cash(self) -> None:
        """Test cash haircut lookup."""
        assert lookup_collateral_haircut("cash") == Decimal("0.00")

    def test_lookup_govt_bond(self) -> None:
        """Test government bond haircut lookup."""
        assert lookup_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=0.5) == Decimal("0.005")
        assert lookup_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=3.0) == Decimal("0.02")

    def test_lookup_equity(self) -> None:
        """Test equity haircut lookup."""
        assert lookup_collateral_haircut("equity", is_main_index=True) == Decimal("0.15")
        assert lookup_collateral_haircut("equity", is_main_index=False) == Decimal("0.25")

    def test_fx_haircut_same_currency(self) -> None:
        """Same currency has 0% FX haircut."""
        assert lookup_fx_haircut("GBP", "GBP") == Decimal("0.00")

    def test_fx_haircut_different_currency(self) -> None:
        """Different currency has 8% FX haircut."""
        assert lookup_fx_haircut("GBP", "EUR") == Decimal("0.08")


class TestAdjustedCollateralValue:
    """Tests for collateral value adjustments."""

    def test_adjusted_value_no_haircut(self) -> None:
        """Cash collateral has no adjustment."""
        adj = calculate_adjusted_collateral_value(Decimal("1000"), Decimal("0.00"))
        assert adj == Decimal("1000")

    def test_adjusted_value_with_haircut(self) -> None:
        """Haircut reduces collateral value."""
        adj = calculate_adjusted_collateral_value(Decimal("1000"), Decimal("0.15"))
        assert adj == Decimal("850")

    def test_adjusted_value_with_fx_haircut(self) -> None:
        """FX haircut adds to collateral haircut."""
        adj = calculate_adjusted_collateral_value(Decimal("1000"), Decimal("0.15"), Decimal("0.08"))
        assert adj == Decimal("770")  # 1000 * (1 - 0.15 - 0.08)


class TestMaturityMismatch:
    """Tests for maturity mismatch adjustment."""

    def test_no_mismatch(self) -> None:
        """No adjustment when collateral maturity >= exposure maturity."""
        adj, _ = calculate_maturity_mismatch_adjustment(
            Decimal("1000"), collateral_maturity_years=5.0, exposure_maturity_years=3.0
        )
        assert adj == Decimal("1000")

    def test_mismatch_adjustment(self) -> None:
        """Adjustment applied when collateral maturity < exposure maturity."""
        adj, _ = calculate_maturity_mismatch_adjustment(
            Decimal("1000"), collateral_maturity_years=2.0, exposure_maturity_years=5.0
        )
        # Formula: (t - 0.25) / (T - 0.25) = (2 - 0.25) / (5 - 0.25) = 1.75 / 4.75
        expected_factor = Decimal(str(1.75 / 4.75))
        expected = Decimal("1000") * expected_factor
        assert abs(adj - expected) < Decimal("0.01")

    def test_short_collateral_maturity(self) -> None:
        """No protection if collateral maturity < 3 months."""
        adj, _ = calculate_maturity_mismatch_adjustment(
            Decimal("1000"), collateral_maturity_years=0.1, exposure_maturity_years=2.0
        )
        assert adj == Decimal("0")


# =============================================================================
# SLOTTING TABLE TESTS
# =============================================================================

class TestSlottingRiskWeights:
    """Tests for specialised lending slotting (CRR Art. 153(5))."""

    def test_strong_seventy_percent(self) -> None:
        """Strong category gets 70% RW."""
        assert SLOTTING_RISK_WEIGHTS[SlottingCategory.STRONG] == Decimal("0.70")

    def test_good_seventy_percent(self) -> None:
        """Good category gets 70% RW (same as Strong under CRR)."""
        assert SLOTTING_RISK_WEIGHTS[SlottingCategory.GOOD] == Decimal("0.70")

    def test_satisfactory_one_fifteen(self) -> None:
        """Satisfactory category gets 115% RW."""
        assert SLOTTING_RISK_WEIGHTS[SlottingCategory.SATISFACTORY] == Decimal("1.15")

    def test_weak_two_fifty(self) -> None:
        """Weak category gets 250% RW."""
        assert SLOTTING_RISK_WEIGHTS[SlottingCategory.WEAK] == Decimal("2.50")

    def test_default_zero(self) -> None:
        """Default category gets 0% RW (100% provisioned)."""
        assert SLOTTING_RISK_WEIGHTS[SlottingCategory.DEFAULT] == Decimal("0.00")

    def test_hvcre_same_as_standard(self) -> None:
        """Under CRR, HVCRE uses same weights as non-HVCRE."""
        for cat in SlottingCategory:
            assert SLOTTING_RISK_WEIGHTS[cat] == SLOTTING_RISK_WEIGHTS_HVCRE[cat]


class TestSlottingLookup:
    """Tests for slotting lookup functions."""

    def test_lookup_by_string(self) -> None:
        """Test lookup with string category."""
        assert lookup_slotting_rw("strong") == Decimal("0.70")
        assert lookup_slotting_rw("weak") == Decimal("2.50")

    def test_lookup_by_enum(self) -> None:
        """Test lookup with enum category."""
        assert lookup_slotting_rw(SlottingCategory.STRONG) == Decimal("0.70")

    def test_rwa_calculation(self) -> None:
        """Test slotting RWA calculation."""
        rwa, rw, _ = calculate_slotting_rwa(Decimal("10000000"), "strong")
        assert rw == Decimal("0.70")
        assert rwa == Decimal("7000000")


class TestSlottingDataFrame:
    """Tests for slotting DataFrame generation."""

    def test_table_has_both_types(self) -> None:
        """Table includes both HVCRE and non-HVCRE entries."""
        df = get_slotting_table()
        hvcre_count = df.filter(pl.col("is_hvcre") == True).height
        non_hvcre_count = df.filter(pl.col("is_hvcre") == False).height
        assert hvcre_count == 5
        assert non_hvcre_count == 5


# =============================================================================
# F-IRB LGD TABLE TESTS
# =============================================================================

class TestFIRBSupervisoryLGD:
    """Tests for F-IRB supervisory LGD (CRR Art. 161)."""

    def test_unsecured_senior_forty_five(self) -> None:
        """Unsecured senior claims have 45% LGD."""
        assert FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.45")

    def test_subordinated_seventy_five(self) -> None:
        """Subordinated claims have 75% LGD."""
        assert FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")

    def test_financial_collateral_zero(self) -> None:
        """Financial collateral has 0% LGD (after haircuts)."""
        assert FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")

    def test_receivables_thirty_five(self) -> None:
        """Receivables collateral has 35% LGD."""
        assert FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.35")

    def test_real_estate_thirty_five(self) -> None:
        """Real estate collateral has 35% LGD."""
        assert FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.35")
        assert FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.35")

    def test_other_physical_forty(self) -> None:
        """Other physical collateral has 40% LGD."""
        assert FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.40")


class TestFIRBLGDLookup:
    """Tests for F-IRB LGD lookup functions."""

    def test_unsecured_lookup(self) -> None:
        """Test unsecured LGD lookup."""
        assert lookup_firb_lgd(None) == Decimal("0.45")

    def test_subordinated_lookup(self) -> None:
        """Test subordinated LGD lookup."""
        assert lookup_firb_lgd(None, is_subordinated=True) == Decimal("0.75")

    def test_cash_collateral_lookup(self) -> None:
        """Test cash collateral LGD lookup."""
        assert lookup_firb_lgd("cash") == Decimal("0.00")

    def test_real_estate_lookup(self) -> None:
        """Test real estate LGD lookup."""
        assert lookup_firb_lgd("residential_re") == Decimal("0.35")


class TestIRBParameterFloors:
    """Tests for IRB parameter floors and caps."""

    def test_pd_floor(self) -> None:
        """PD floor is 0.03%."""
        assert CRR_PD_FLOOR == Decimal("0.0003")

    def test_maturity_floor(self) -> None:
        """Maturity floor is 1 year."""
        assert CRR_MATURITY_FLOOR == Decimal("1.0")

    def test_maturity_cap(self) -> None:
        """Maturity cap is 5 years."""
        assert CRR_MATURITY_CAP == Decimal("5.0")

    def test_apply_pd_floor(self) -> None:
        """Test PD floor application."""
        assert apply_pd_floor(Decimal("0.0001")) == Decimal("0.0003")
        assert apply_pd_floor(Decimal("0.01")) == Decimal("0.01")

    def test_apply_maturity_bounds(self) -> None:
        """Test maturity bounds application."""
        assert apply_maturity_bounds(Decimal("0.5")) == Decimal("1.0")
        assert apply_maturity_bounds(Decimal("3.0")) == Decimal("3.0")
        assert apply_maturity_bounds(Decimal("7.0")) == Decimal("5.0")


class TestFIRBDataFrame:
    """Tests for F-IRB LGD DataFrame generation."""

    def test_table_has_expected_columns(self) -> None:
        """Table has expected schema."""
        df = get_firb_lgd_table()
        assert "collateral_type" in df.columns
        assert "seniority" in df.columns
        assert "lgd" in df.columns
