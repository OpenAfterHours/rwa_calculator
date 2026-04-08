"""
Direct unit tests for CRM collateral sub-functions.

Tests generate_netting_collateral and apply_firb_supervisory_lgd_no_collateral
in isolation, complementing integration-level tests that go through CRMProcessor.

Why these tests matter:
- generate_netting_collateral creates synthetic cash collateral from negative-drawn
  loans under netting agreements (CRR Art. 195). Incorrect netting can overstate
  or understate exposure values.
- apply_firb_supervisory_lgd_no_collateral assigns supervisory LGD values.
  Wrong LGD (e.g., 45% vs 40% for FSE under Basel 3.1) directly affects RWA.

References:
    CRR Art. 195: Netting agreements
    CRR Art. 161(1)(a): F-IRB supervisory LGD (senior 45%, subordinated 75%)
    PRA PS1/26 Art. 161(1)(a)/(aa): FSE 45%, non-FSE 40%
    PRA PS1/26 Art. 169B: A-IRB insufficient collateral data
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import AIRBCollateralMethod, ApproachType
from rwa_calc.engine.crm.collateral import (
    apply_firb_supervisory_lgd_no_collateral,
    generate_netting_collateral,
)

# =============================================================================
# generate_netting_collateral
# =============================================================================


class TestGenerateNettingCollateral:
    """CRR Art. 195: synthetic cash collateral from negative-drawn netting loans."""

    def test_no_netting_agreement_column_returns_none(self) -> None:
        """Missing has_netting_agreement column: returns None."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [-50_000.0],
                "parent_facility_reference": ["FAC001"],
                "ead_gross": [0.0],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is None

    def test_no_parent_facility_column_returns_none(self) -> None:
        """Missing parent_facility_reference column: returns None."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [-50_000.0],
                "has_netting_agreement": [True],
                "ead_gross": [0.0],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is None

    def _netting_frame(self, rows: dict) -> pl.LazyFrame:
        """Build frame with all columns needed by generate_netting_collateral."""
        from datetime import date as d

        n = len(rows["exposure_reference"])
        defaults = {
            "maturity_date": [d(2025, 12, 31)] * n,
        }
        defaults.update(rows)
        return pl.LazyFrame(defaults)

    def test_no_negative_drawn_loans_empty_result(self) -> None:
        """No negative-drawn loans: returns empty or None."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [100_000.0],
                "has_netting_agreement": [True],
                "parent_facility_reference": ["FAC001"],
                "ead_gross": [100_000.0],
                "currency": ["GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        if result is not None:
            df = result.collect()
            assert len(df) == 0

    def test_basic_netting_generates_cash_collateral(self) -> None:
        """Negative-drawn loan creates cash collateral for positive sibling."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEPOSIT", "LOAN_A"],
                "drawn_amount": [-200_000.0, 500_000.0],
                "has_netting_agreement": [True, False],
                "parent_facility_reference": ["FAC001", "FAC001"],
                "ead_gross": [0.0, 500_000.0],
                "currency": ["GBP", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is not None

        df = result.collect()
        assert len(df) >= 1
        assert df["collateral_type"][0] == "cash"
        assert df["market_value"][0] > 0

    def test_netting_pool_grouped_by_currency(self) -> None:
        """Netting pools group by (netting_group, currency)."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEP_GBP", "DEP_EUR", "LOAN_A"],
                "drawn_amount": [-100_000.0, -200_000.0, 500_000.0],
                "has_netting_agreement": [True, True, False],
                "parent_facility_reference": ["FAC001", "FAC001", "FAC001"],
                "ead_gross": [0.0, 0.0, 500_000.0],
                "currency": ["GBP", "EUR", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is not None

        df = result.collect()
        if len(df) > 0:
            currencies = set(df["currency"].to_list())
            assert "GBP" in currencies

    def test_netting_eligible_requires_true_flag(self) -> None:
        """Only loans with has_netting_agreement=True provide netting pool."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEPOSIT", "LOAN_A"],
                "drawn_amount": [-200_000.0, 500_000.0],
                "has_netting_agreement": [False, False],
                "parent_facility_reference": ["FAC001", "FAC001"],
                "ead_gross": [0.0, 500_000.0],
                "currency": ["GBP", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        if result is not None:
            df = result.collect()
            assert len(df) == 0

    def test_collateral_reference_prefixed_netting(self) -> None:
        """Synthetic collateral reference is prefixed with NETTING_."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEPOSIT", "LOAN_A"],
                "drawn_amount": [-200_000.0, 500_000.0],
                "has_netting_agreement": [True, False],
                "parent_facility_reference": ["FAC001", "FAC001"],
                "ead_gross": [0.0, 500_000.0],
                "currency": ["GBP", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is not None

        df = result.collect()
        if len(df) > 0:
            assert df["collateral_reference"][0].startswith("NETTING_")

    def test_is_eligible_financial_collateral_set(self) -> None:
        """Synthetic netting collateral marked as eligible financial collateral."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEPOSIT", "LOAN_A"],
                "drawn_amount": [-200_000.0, 500_000.0],
                "has_netting_agreement": [True, False],
                "parent_facility_reference": ["FAC001", "FAC001"],
                "ead_gross": [0.0, 500_000.0],
                "currency": ["GBP", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is not None

        df = result.collect()
        if len(df) > 0:
            assert df["is_eligible_financial_collateral"][0] is True
            assert df["is_eligible_irb_collateral"][0] is True

    def test_pro_rata_allocation_across_siblings(self) -> None:
        """Netting pool allocated pro-rata by ead_gross to positive siblings."""
        lf = self._netting_frame(
            {
                "exposure_reference": ["DEPOSIT", "LOAN_A", "LOAN_B"],
                "drawn_amount": [-100_000.0, 600_000.0, 400_000.0],
                "has_netting_agreement": [True, False, False],
                "parent_facility_reference": ["FAC001", "FAC001", "FAC001"],
                "ead_gross": [0.0, 600_000.0, 400_000.0],
                "currency": ["GBP", "GBP", "GBP"],
            }
        )
        result = generate_netting_collateral(lf)
        assert result is not None

        df = result.collect()
        if len(df) == 2:
            df_sorted = df.sort("beneficiary_reference")
            assert df_sorted["market_value"][0] == pytest.approx(60_000.0, rel=1e-4)
            assert df_sorted["market_value"][1] == pytest.approx(40_000.0, rel=1e-4)


# =============================================================================
# apply_firb_supervisory_lgd_no_collateral
# =============================================================================


class TestFIRBSupervisoryLGDNoCollateral:
    """F-IRB supervisory LGD assignment when no collateral is available."""

    def _base_exposures(self, **overrides) -> pl.LazyFrame:
        defaults = {
            "exposure_reference": ["EXP001"],
            "approach": [ApproachType.FIRB.value],
            "lgd_pre_crm": [0.45],
            "seniority": ["senior"],
        }
        defaults.update(overrides)
        return pl.LazyFrame(defaults)

    def test_crr_firb_senior_lgd_045(self) -> None:
        """CRR F-IRB senior unsecured: LGD = 45%."""
        lf = self._base_exposures(seniority=["senior"])
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_crr_firb_subordinated_lgd_075(self) -> None:
        """CRR F-IRB subordinated: LGD = 75%."""
        lf = self._base_exposures(seniority=["subordinated"])
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.75)

    def test_b31_firb_non_fse_senior_lgd_040(self) -> None:
        """Basel 3.1 F-IRB non-FSE senior: LGD = 40%."""
        lf = self._base_exposures(
            cp_is_financial_sector_entity=[False],
        )
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=True).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_b31_firb_fse_senior_lgd_045(self) -> None:
        """Basel 3.1 F-IRB FSE senior: LGD = 45%."""
        lf = self._base_exposures(
            cp_is_financial_sector_entity=[True],
        )
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=True).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_b31_firb_subordinated_lgd_075(self) -> None:
        """Basel 3.1 F-IRB subordinated: always 75% regardless of FSE."""
        lf = self._base_exposures(
            seniority=["subordinated"],
            cp_is_financial_sector_entity=[True],
        )
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=True).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.75)

    def test_seniority_absent_defaults_to_senior(self) -> None:
        """Missing seniority column: treated as not subordinated → senior LGD."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": [ApproachType.FIRB.value],
                "lgd_pre_crm": [0.45],
            }
        )
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_sa_exposure_keeps_lgd_unchanged(self) -> None:
        """SA exposures: lgd_post_crm = lgd_pre_crm (no supervisory override)."""
        lf = self._base_exposures(approach=[ApproachType.SA.value], lgd_pre_crm=[0.60])
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.60)

    def test_airb_crr_keeps_modelled_lgd(self) -> None:
        """CRR A-IRB: keeps modelled lgd_pre_crm unchanged."""
        lf = self._base_exposures(approach=[ApproachType.AIRB.value], lgd_pre_crm=[0.35])
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.35)

    def test_b31_airb_foundation_election_uses_supervisory(self) -> None:
        """B31 A-IRB Foundation election: uses supervisory LGDU like F-IRB."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1),
            airb_collateral_method=AIRBCollateralMethod.FOUNDATION,
        )
        lf = self._base_exposures(
            approach=[ApproachType.AIRB.value],
            lgd_pre_crm=[0.35],
            cp_is_financial_sector_entity=[False],
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            lf, is_basel_3_1=True, config=config
        ).collect()

        # Foundation election → same as F-IRB non-FSE: 40%
        assert result["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_b31_airb_lgd_modelling_insufficient_data_uses_own(self) -> None:
        """B31 A-IRB LGD modelling with insufficient data: uses own lgd_unsecured."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1),
            airb_collateral_method=AIRBCollateralMethod.LGD_MODELLING,
        )
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": [ApproachType.AIRB.value],
                "lgd_pre_crm": [0.35],
                "lgd_unsecured": [0.30],
                "has_sufficient_collateral_data": [False],
                "seniority": ["senior"],
            }
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            lf, is_basel_3_1=True, config=config
        ).collect()

        # Insufficient data → own lgd_unsecured
        assert result["lgd_post_crm"][0] == pytest.approx(0.30)

    def test_b31_airb_lgd_modelling_sufficient_data_keeps_modelled(self) -> None:
        """B31 A-IRB LGD modelling with sufficient data: keeps modelled LGD."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 1, 1),
            airb_collateral_method=AIRBCollateralMethod.LGD_MODELLING,
        )
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": [ApproachType.AIRB.value],
                "lgd_pre_crm": [0.35],
                "lgd_unsecured": [0.30],
                "has_sufficient_collateral_data": [True],
                "seniority": ["senior"],
            }
        )
        result = apply_firb_supervisory_lgd_no_collateral(
            lf, is_basel_3_1=True, config=config
        ).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.35)

    def test_zero_collateral_columns_added(self) -> None:
        """Function adds total_collateral_for_lgd=0 and collateral_coverage_pct=0."""
        lf = self._base_exposures()
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["total_collateral_for_lgd"][0] == pytest.approx(0.0)
        assert result["collateral_coverage_pct"][0] == pytest.approx(0.0)

    def test_junior_seniority_treated_as_subordinated(self) -> None:
        """'junior' seniority treated same as 'subordinated' → 75%."""
        lf = self._base_exposures(seniority=["junior"])
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=False).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.75)

    def test_config_none_defaults_no_airb_method(self) -> None:
        """config=None: no AIRB method, standard FIRB-only path."""
        lf = self._base_exposures()
        result = apply_firb_supervisory_lgd_no_collateral(
            lf, is_basel_3_1=True, config=None
        ).collect()

        # Without config, defaults to FIRB-only formula
        # B31 without FSE column → lgd_senior = 0.40
        assert result["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_b31_fse_absent_uses_non_fse_lgd(self) -> None:
        """B31 without cp_is_financial_sector_entity column: uses non-FSE 40%."""
        lf = self._base_exposures()  # No FSE column
        result = apply_firb_supervisory_lgd_no_collateral(lf, is_basel_3_1=True).collect()

        assert result["lgd_post_crm"][0] == pytest.approx(0.40)
