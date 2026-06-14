"""Unit tests for Basel 3.1 CRM (Credit Risk Mitigation) changes.

Tests cover the key differences between CRR and Basel 3.1 for CRM:
1. Revised supervisory haircut tables (PRA PS1/26 Art. 224 Table 1):
   - 5 maturity bands instead of CRR's 3
   - Higher haircuts for long-dated corporate bonds (CQS 2-3 10y+ = 20%)
   - Higher equity haircuts (20%/30% vs 15%/25%)
   - Sovereign CQS 2-3 unchanged from CRR 6% cap — the 5-band split is not
     a penal re-scale for well-rated sovereigns.
2. Revised F-IRB supervisory LGD (CRE32.9-12):
   - Senior unsecured: 40% (CRR: 45%)
   - Receivables/RE: 20% (CRR: 35%)
   - Other physical: 25% (CRR: 40%)
3. Framework-conditional logic in CRM processor

Why these tests matter:
    Basel 3.1 introduces material changes to CRM that reduce capital benefits
    from collateral (higher haircuts) while lowering regulatory LGD for F-IRB
    (better treatment of collateralised exposures). Getting these wrong
    produces materially incorrect RWA — in either direction.

References:
    CRR Art. 224: CRR supervisory haircuts
    PRA PS1/26 Art. 224 Table 3: Basel 3.1 supervisory haircuts
    CRR Art. 161: CRR F-IRB supervisory LGD
    CRE32.9-12: Basel 3.1 F-IRB supervisory LGD
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    get_haircut_table,
    get_maturity_band,
    lookup_collateral_haircut,
)
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.processor import CRMProcessor

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def crr_processor() -> CRMProcessor:
    """CRM processor for CRR framework."""
    return CRMProcessor()


@pytest.fixture
def b31_processor() -> CRMProcessor:
    """CRM processor for Basel 3.1 framework."""
    return CRMProcessor()


# =============================================================================
# Test: Basel 3.1 maturity bands (CRE22.52-53)
# =============================================================================


class TestBasel31MaturityBands:
    """Basel 3.1 uses 5 maturity bands instead of CRR's 3."""

    def test_crr_maturity_bands_are_3(self) -> None:
        """CRR uses 0-1y, 1-5y, 5y+ — 3 bands."""
        assert get_maturity_band(0.5, is_basel_3_1=False) == "0_1y"
        assert get_maturity_band(3.0, is_basel_3_1=False) == "1_5y"
        assert get_maturity_band(7.0, is_basel_3_1=False) == "5y_plus"

    def test_b31_maturity_bands_are_5(self) -> None:
        """Basel 3.1 uses 0-1y, 1-3y, 3-5y, 5-10y, 10y+ — 5 bands."""
        assert get_maturity_band(0.5, is_basel_3_1=True) == "0_1y"
        assert get_maturity_band(2.0, is_basel_3_1=True) == "1_3y"
        assert get_maturity_band(4.0, is_basel_3_1=True) == "3_5y"
        assert get_maturity_band(7.0, is_basel_3_1=True) == "5_10y"
        assert get_maturity_band(15.0, is_basel_3_1=True) == "10y_plus"

    def test_b31_maturity_band_boundaries(self) -> None:
        """Boundary values classified correctly for Basel 3.1."""
        assert get_maturity_band(1.0, is_basel_3_1=True) == "0_1y"
        assert get_maturity_band(3.0, is_basel_3_1=True) == "1_3y"
        assert get_maturity_band(5.0, is_basel_3_1=True) == "3_5y"
        assert get_maturity_band(10.0, is_basel_3_1=True) == "5_10y"
        assert get_maturity_band(10.01, is_basel_3_1=True) == "10y_plus"


# =============================================================================
# Test: Basel 3.1 haircut tables (CRE22.52-53)
# =============================================================================


class TestBasel31HaircutTable:
    """Verify the Basel 3.1 haircut table has correct structure and values."""

    def test_b31_haircut_table_has_5_maturity_bands(self) -> None:
        """Basel 3.1 table should have 5 maturity band variants for bonds."""
        df = get_haircut_table(is_basel_3_1=True)
        bond_bands = df.filter(pl.col("collateral_type") == "govt_bond")["maturity_band"].to_list()
        unique_bands = set(bond_bands)
        assert unique_bands == {"0_1y", "1_3y", "3_5y", "5_10y", "10y_plus"}

    def test_crr_haircut_table_has_3_maturity_bands(self) -> None:
        """CRR table should have 3 maturity band variants for bonds."""
        df = get_haircut_table(is_basel_3_1=False)
        bond_bands = df.filter(pl.col("collateral_type") == "govt_bond")["maturity_band"].to_list()
        unique_bands = set(bond_bands)
        assert unique_bands == {"0_1y", "1_5y", "5y_plus"}


class TestBasel31EquityHaircuts:
    """Equity haircuts increase under Basel 3.1."""

    def test_crr_equity_main_index_15pct(self) -> None:
        assert COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.15")

    def test_crr_equity_other_25pct(self) -> None:
        assert COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.25")

    def test_b31_equity_main_index_20pct(self) -> None:
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.20")

    def test_b31_equity_other_30pct(self) -> None:
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.30")

    def test_lookup_equity_haircut_crr(self) -> None:
        assert lookup_collateral_haircut(
            "equity", is_main_index=True, is_basel_3_1=False
        ) == Decimal("0.15")
        assert lookup_collateral_haircut(
            "equity", is_main_index=False, is_basel_3_1=False
        ) == Decimal("0.25")

    def test_lookup_equity_haircut_b31(self) -> None:
        assert lookup_collateral_haircut(
            "equity", is_main_index=True, is_basel_3_1=True
        ) == Decimal("0.20")
        assert lookup_collateral_haircut(
            "equity", is_main_index=False, is_basel_3_1=True
        ) == Decimal("0.30")


class TestBasel31ReceivablesHaircut:
    """Receivables HC increases from ~20% (CRR ad-hoc) to 40% (B31 Art. 230(2)).

    Why this matters:
        PRA PS1/26 Art. 230(2) explicitly defines HC=40% for receivables in the
        LGD* formula: ES = min(C(1-HC-Hfx), E(1+HE)). The HC reduces the
        collateral value before determining the secured portion. The previous
        code value of 20% confused HC with LGDS (secured LGD), which is also 20%
        for receivables but serves a different purpose in the formula.
        HC=20% understates the haircut and overstates CRM benefit.

    References:
        PRA PS1/26 Art. 230(2) table: HC=40% for receivables
        CRR Art. 230: uses C*/C** threshold mechanism (no HC concept)
    """

    def test_crr_receivables_no_haircut(self) -> None:
        """CRR Art. 224 has no receivables row — Hc=0 (P1.165).

        Receivables are non-financial collateral per Art. 199(5); CRR Art. 230
        provides the entire treatment via the LGD* / 1.25x OC mechanism.
        Basel 3.1 Art. 230(2) HC=40% sits in BASEL31_COLLATERAL_HAIRCUTS only.
        """
        assert COLLATERAL_HAIRCUTS["receivables"] == Decimal("0")

    def test_b31_receivables_haircut_40pct(self) -> None:
        """Basel 3.1 receivables haircut is 40% per Art. 230(2)."""
        assert BASEL31_COLLATERAL_HAIRCUTS["receivables"] == Decimal("0.40")

    def test_lookup_receivables_haircut_crr(self) -> None:
        """lookup_collateral_haircut returns 0 for CRR receivables (P1.165).

        CRR Art. 224 has no receivables row; Art. 230 owns the treatment.
        """
        result = lookup_collateral_haircut("receivables", is_basel_3_1=False)
        assert result == Decimal("0")

    def test_lookup_receivables_haircut_b31(self) -> None:
        """lookup_collateral_haircut returns 40% for B31 receivables."""
        result = lookup_collateral_haircut("receivables", is_basel_3_1=True)
        assert result == Decimal("0.40")

    def test_lookup_trade_receivables_haircut_b31(self) -> None:
        """trade_receivables alias also returns 40% under B31."""
        result = lookup_collateral_haircut("trade_receivables", is_basel_3_1=True)
        assert result == Decimal("0.40")

    def test_b31_receivables_haircut_in_dataframe(self) -> None:
        """B31 haircut DataFrame has 40% for receivables row."""
        df = get_haircut_table(is_basel_3_1=True)
        rec_row = df.filter(pl.col("collateral_type") == "receivables")
        assert rec_row.shape[0] == 1
        assert rec_row["haircut"][0] == pytest.approx(0.40)

    def test_crr_receivables_haircut_in_dataframe(self) -> None:
        """CRR haircut DataFrame has 0% for receivables row (P1.165).

        Art. 224 has no receivables row; CRR Art. 230 LGD* / 1.25x OC mechanism
        provides the entire treatment.
        """
        df = get_haircut_table(is_basel_3_1=False)
        rec_row = df.filter(pl.col("collateral_type") == "receivables")
        assert rec_row.shape[0] == 1
        assert rec_row["haircut"][0] == pytest.approx(0.0)

    def test_b31_single_haircut_receivables_40pct(self) -> None:
        """HaircutCalculator.calculate_single_haircut applies 40% for B31 receivables."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=True,
            collateral_type="receivables",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0.40")
        assert result.adjusted_value == Decimal("600000")

    def test_crr_single_haircut_receivables_no_haircut(self) -> None:
        """HaircutCalculator.calculate_single_haircut applies 0% for CRR receivables (P1.165).

        Art. 224 has no receivables row; the Art. 230 LGD* / OC mechanism
        downstream is the only applicable reduction.
        """
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=False,
            collateral_type="receivables",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0")
        assert result.adjusted_value == Decimal("1000000")

    def test_b31_receivables_with_fx_mismatch(self) -> None:
        """B31 receivables: 40% HC + 8% FX = 48% total, adjusted = 520,000."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=True,
            collateral_type="receivables",
            market_value=Decimal("1000000"),
            collateral_currency="USD",
            exposure_currency="GBP",
        )
        assert result.collateral_haircut == Decimal("0.40")
        assert result.fx_haircut == Decimal("0.08")
        assert result.adjusted_value == Decimal("520000")


class TestBasel31BondHaircuts:
    """Bond haircuts differ for long-dated maturities under Basel 3.1."""

    def test_govt_bond_cqs1_short_same_both_frameworks(self) -> None:
        """Government bond CQS 1, 0-1y: 0.5% under both."""
        crr = lookup_collateral_haircut(
            "govt_bond", cqs=1, residual_maturity_years=0.5, is_basel_3_1=False
        )
        b31 = lookup_collateral_haircut(
            "govt_bond", cqs=1, residual_maturity_years=0.5, is_basel_3_1=True
        )
        assert crr == Decimal("0.005")
        assert b31 == Decimal("0.005")

    @pytest.mark.parametrize(
        ("collateral_type", "cqs", "maturity_years", "expected"),
        [
            # Sovereign CQS 2-3: 5-band split does not re-scale; cap stays at 6%
            # even at 10y+. An earlier B31 draft had 12% (misread of BCBS CRE22.52)
            # and 4% at 3-5y; Table 1 is 3% and 6%.
            ("govt_bond", 2, 4.0, "0.03"),
            ("govt_bond", 2, 15.0, "0.06"),
            ("govt_bond", 3, 15.0, "0.06"),
            # Corporate/institution CQS 1: 1/3/4/6/12% across the 5 bands.
            ("corp_bond", 1, 0.5, "0.01"),
            ("corp_bond", 1, 2.0, "0.03"),
            ("corp_bond", 1, 4.0, "0.04"),
            ("corp_bond", 1, 7.0, "0.06"),
            ("corp_bond", 1, 12.0, "0.12"),
            # Corporate/institution CQS 2-3: 2/4/6/12/20% across the 5 bands.
            # 10y+ = 20% is a capital *increase* vs the prior stale 15%; the
            # other bands were previously over-haircut.
            ("corp_bond", 2, 0.5, "0.02"),
            ("corp_bond", 2, 2.0, "0.04"),
            ("corp_bond", 3, 4.0, "0.06"),
            ("corp_bond", 2, 7.0, "0.12"),
            ("corp_bond", 3, 12.0, "0.20"),
        ],
    )
    def test_b31_bond_haircuts_match_pra_table_1(
        self,
        collateral_type: str,
        cqs: int,
        maturity_years: float,
        expected: str,
    ) -> None:
        """PRA PS1/26 Art. 224 Table 1 10-day haircuts (verified against ps126app1.pdf p.203)."""
        result = lookup_collateral_haircut(
            collateral_type,
            cqs=cqs,
            residual_maturity_years=maturity_years,
            is_basel_3_1=True,
        )
        assert result == Decimal(expected)

    def test_cash_and_gold_b31(self) -> None:
        """Cash 0% unchanged; gold is 20% under Basel 3.1 (PRA PS1/26 Art. 224 Table 3)."""
        assert lookup_collateral_haircut("cash", is_basel_3_1=True) == Decimal("0.00")
        assert lookup_collateral_haircut("gold", is_basel_3_1=True) == Decimal("0.20")


# =============================================================================
# Test: HaircutCalculator framework branching
# =============================================================================


class TestHaircutCalculatorFrameworkBranching:
    """HaircutCalculator produces different results by framework."""

    def test_crr_calculator_uses_crr_haircuts(self) -> None:
        """CRR calculator returns 15% for main index equity."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=False,
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
        )
        assert result.collateral_haircut == Decimal("0.15")
        assert result.adjusted_value == Decimal("850000")

    def test_b31_calculator_uses_b31_haircuts(self) -> None:
        """Basel 3.1 calculator returns 20% for main index equity (PRA PS1/26 Art. 224 Table 3)."""
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=True,
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
        )
        assert result.collateral_haircut == Decimal("0.20")
        assert result.adjusted_value == Decimal("800000")

    def test_b31_corp_bond_long_dated_higher_haircut(self) -> None:
        """Basel 3.1 produces same haircut as CRR for 7y corporate bond CQS 2.

        PRA PS1/26 Art. 224 Table 1 (entity types (c)/(d)): CQS 2-3 corporate
        5-10y = 12%. Matches CRR 5y+ CQS 2-3 (12%). The B31 step-up for CQS 2-3
        appears only at 10y+ (20%). An earlier draft of the B31 table had 15%
        here (stale value, now corrected).
        """
        calc = HaircutCalculator()
        result = calc.calculate_single_haircut(
            is_basel_3_1=True,
            collateral_type="corp_bond",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=2,
            residual_maturity_years=7.0,
        )
        # PRA PS1/26 Art. 224 Table 1: CQS 2-3 corporate 5-10y = 12%
        assert result.collateral_haircut == Decimal("0.12")

    def test_apply_haircuts_uses_config_framework(
        self, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """apply_haircuts produces different maturity bands based on config.

        P1.186: liquidation_period_days=10 is set explicitly because this test
        verifies maturity-band selection and haircut-table lookup, not the
        secured-lending period scaling. The new pipeline default is 20-day.
        """
        collateral = pl.LazyFrame(
            {
                "collateral_reference": ["C1"],
                "collateral_type": ["govt_bond"],
                "market_value": [100_000.0],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "residual_maturity_years": [7.0],
                "issuer_cqs": [2],
                "issuer_type": ["sovereign"],
                "is_eligible_financial_collateral": [True],
                "liquidation_period_days": [10],  # P1.186: explicit 10-day
            }
        )

        crr_calc = HaircutCalculator()
        crr_result = crr_calc.apply_haircuts(collateral, crr_config).collect()

        b31_calc = HaircutCalculator()
        b31_result = b31_calc.apply_haircuts(collateral, b31_config).collect()

        # CRR: 5y+ band = 6%
        assert crr_result["maturity_band"][0] == "5y_plus"
        assert crr_result["collateral_haircut"][0] == pytest.approx(0.06)

        # Basel 3.1: 5-10y band = 6%
        assert b31_result["maturity_band"][0] == "5_10y"
        assert b31_result["collateral_haircut"][0] == pytest.approx(0.06)


# =============================================================================
# Test: CRM Processor framework branching for F-IRB LGD
# =============================================================================


class TestCRMProcessorFIRBLGDBranching:
    """CRM processor uses correct F-IRB supervisory LGD per framework."""

    def test_crr_processor_uses_45pct_senior_unsecured(self, crr_config: CalculationConfig) -> None:
        """CRR processor applies 45% LGD for senior unsecured F-IRB."""
        processor = CRMProcessor()
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.FIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.45],
                "seniority": ["senior"],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            }
        )

        result = processor._apply_firb_supervisory_lgd_no_collateral(
            exposures, crr_config
        ).collect()
        assert result["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_b31_processor_uses_40pct_senior_unsecured(self, b31_config: CalculationConfig) -> None:
        """Basel 3.1 processor applies 40% LGD for senior unsecured F-IRB."""
        processor = CRMProcessor()
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.FIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.40],
                "seniority": ["senior"],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            }
        )

        result = processor._apply_firb_supervisory_lgd_no_collateral(
            exposures, b31_config
        ).collect()
        assert result["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_subordinated_75pct_both_frameworks(
        self, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """Subordinated LGD = 75% under both CRR and Basel 3.1."""
        for is_b31 in [False, True]:
            processor = CRMProcessor()
            config = b31_config if is_b31 else crr_config
            exposures = pl.LazyFrame(
                {
                    "exposure_reference": ["E1"],
                    "counterparty_reference": ["CP1"],
                    "approach": [ApproachType.FIRB.value],
                    "ead_gross": [1_000_000.0],
                    "lgd_pre_crm": [0.75],
                    "seniority": ["subordinated"],
                    "parent_facility_reference": [None],
                    "currency": ["GBP"],
                }
            )

            result = processor._apply_firb_supervisory_lgd_no_collateral(
                exposures, config
            ).collect()
            assert result["lgd_post_crm"][0] == pytest.approx(0.75), (
                f"Subordinated LGD should be 75% for {'B31' if is_b31 else 'CRR'}"
            )

    def test_airb_preserves_modelled_lgd(
        self, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """A-IRB exposures keep their modelled LGD under both frameworks."""
        for is_b31 in [False, True]:
            processor = CRMProcessor()
            config = b31_config if is_b31 else crr_config
            exposures = pl.LazyFrame(
                {
                    "exposure_reference": ["E1"],
                    "counterparty_reference": ["CP1"],
                    "approach": [ApproachType.AIRB.value],
                    "ead_gross": [1_000_000.0],
                    "lgd_pre_crm": [0.32],
                    "seniority": ["senior"],
                    "parent_facility_reference": [None],
                    "currency": ["GBP"],
                }
            )

            result = processor._apply_firb_supervisory_lgd_no_collateral(
                exposures, config
            ).collect()
            assert result["lgd_post_crm"][0] == pytest.approx(0.32)

    def test_no_seniority_column_uses_senior_default(
        self, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """Without seniority column, F-IRB defaults to senior unsecured LGD."""
        # CRR: 45%
        crr = CRMProcessor()
        exp_crr = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.FIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.45],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            }
        )
        result_crr = crr._apply_firb_supervisory_lgd_no_collateral(exp_crr, crr_config).collect()
        assert result_crr["lgd_post_crm"][0] == pytest.approx(0.45)

        # Basel 3.1: 40%
        b31 = CRMProcessor()
        exp_b31 = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.FIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.40],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            }
        )
        result_b31 = b31._apply_firb_supervisory_lgd_no_collateral(exp_b31, b31_config).collect()
        assert result_b31["lgd_post_crm"][0] == pytest.approx(0.40)
