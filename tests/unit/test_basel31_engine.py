"""
Unit tests for Basel 3.1 engine changes.

Tests cover the key divergences between CRR and Basel 3.1 frameworks:

1. Per-exposure-class PD floors (CRE30.55)
2. Per-collateral-type LGD floors (CRE30.41)
3. F-IRB supervisory LGD revised values (CRE32.9-12)
4. CCF changes: UCC 10% and A-IRB CCF floor (CRE20.88, CRE32.27)
5. Equity routing: IRB Simple removed under Basel 3.1

References:
- CRR Art. 153-163: IRB risk weight functions, PD floors
- CRE30.41: Basel 3.1 LGD floors for A-IRB
- CRE30.55: Basel 3.1 differentiated PD floors
- CRE32.9-12: Revised F-IRB supervisory LGD
- CRE20.88: UCC CCF change (0% -> 10%)
- CRE32.27: A-IRB CCF floor (>= 50% of SA CCF)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - register namespace
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.tables.crr_firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_SUPERVISORY_LGD,
    get_firb_lgd_table_for_framework,
    lookup_firb_lgd,
)
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import CCFCalculator, sa_ccf_expression
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.formulas import (
    _lgd_floor_expression,
    _lgd_floor_expression_with_collateral,
    _pd_floor_expression,
    apply_irb_formulas,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR (Basel 3.0) configuration."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def crr_sa_only_config() -> CalculationConfig:
    """CRR configuration with SA-only permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture
def basel31_sa_only_config() -> CalculationConfig:
    """Basel 3.1 configuration with SA-only permissions."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        irb_permissions=IRBPermissions.sa_only(),
    )


# =============================================================================
# PD FLOOR TESTS (CRE30.55)
# =============================================================================


class TestPDFloors:
    """Tests for per-exposure-class PD floor expressions.

    CRR: Uniform 0.03% floor for all exposure classes (Art. 163).
    Basel 3.1: Differentiated floors (CRE30.55):
        - Corporate/SME: 0.05%
        - Retail mortgage: 0.05%
        - QRRE revolvers: 0.10%, transactors: 0.03%
        - Retail other: 0.05%
    """

    def test_crr_uniform_floor_corporate(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: Corporate PD floor is 0.03%."""
        lf = pl.LazyFrame({"exposure_class": ["CORPORATE"], "pd": [0.001]})
        result = lf.with_columns(_pd_floor_expression(crr_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0003)

    def test_crr_uniform_floor_retail_mortgage(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: Retail mortgage PD floor is 0.03% (same as corporate)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_MORTGAGE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(crr_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0003)

    def test_crr_uniform_floor_qrre(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: QRRE PD floor is 0.03% (uniform across all classes)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_QRRE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(crr_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0003)

    def test_crr_uniform_floor_all_classes_equal(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: All exposure classes receive the same 0.03% PD floor."""
        classes = [
            "CORPORATE",
            "CORPORATE_SME",
            "RETAIL_MORTGAGE",
            "RETAIL_QRRE",
            "RETAIL_OTHER",
            "INSTITUTION",
        ]
        lf = pl.LazyFrame(
            {
                "exposure_class": classes,
                "pd": [0.001] * len(classes),
            }
        )
        result = lf.with_columns(_pd_floor_expression(crr_config).alias("pd_floor")).collect()
        for i, cls_name in enumerate(classes):
            assert result["pd_floor"][i] == pytest.approx(
                0.0003,
                abs=1e-8,
            ), f"CRR PD floor mismatch for {cls_name}"

    def test_basel31_corporate_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Corporate PD floor is 0.05%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(basel31_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0005)

    def test_basel31_corporate_sme_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Corporate SME PD floor is 0.05%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE_SME"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(basel31_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0005)

    def test_basel31_qrre_revolver_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: QRRE revolver PD floor is 0.10% (default)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_QRRE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(basel31_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0010)

    def test_basel31_retail_mortgage_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Retail mortgage PD floor is 0.05%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_MORTGAGE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(basel31_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0005)

    def test_basel31_retail_other_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Retail other PD floor is 0.05%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_OTHER"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(_pd_floor_expression(basel31_config).alias("pd_floor")).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0005)

    def test_pd_below_floor_is_floored(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """PD below the floor should be raised to the floor value."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.0001],  # 0.01%, below 0.05% floor
            }
        )
        pd_floor_expr = _pd_floor_expression(basel31_config)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)

    def test_pd_above_floor_is_unchanged(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """PD above the floor should remain unchanged."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.05],  # 5%, well above 0.05% floor
            }
        )
        pd_floor_expr = _pd_floor_expression(basel31_config)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.05)

    def test_apply_irb_formulas_uses_correct_pd_floor_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() should use uniform 0.03% PD floor under CRR."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.0001],  # below 0.03% floor
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0003)

    def test_apply_irb_formulas_uses_correct_pd_floor_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() should use 0.05% PD floor for corporate
        under Basel 3.1."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.0001],  # below 0.05% floor
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)

    def test_namespace_apply_pd_floor_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Namespace apply_pd_floor uses CRR uniform floor."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.0001],
            }
        )
        result = lf.irb.apply_pd_floor(crr_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0003)

    def test_namespace_apply_pd_floor_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_pd_floor uses Basel 3.1 differentiated floors."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_QRRE"],
                "pd": [0.0001],
            }
        )
        result = lf.irb.apply_pd_floor(basel31_config).collect()
        # QRRE revolver default is 0.10%
        assert result["pd_floored"][0] == pytest.approx(0.0010)

    def test_namespace_apply_all_formulas_pd_floor_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_all_formulas uses Basel 3.1 PD floors."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.0001],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
            }
        )
        result = lf.irb.apply_all_formulas(basel31_config).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)

    def test_multiple_classes_differentiated_floors(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Multiple exposure classes get their own floors."""
        lf = pl.LazyFrame(
            {
                "exposure_class": [
                    "CORPORATE",
                    "RETAIL_QRRE",
                    "RETAIL_MORTGAGE",
                ],
                "pd": [0.0001, 0.0001, 0.0001],
            }
        )
        pd_floor_expr = _pd_floor_expression(basel31_config)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)  # Corporate
        assert result["pd_floored"][1] == pytest.approx(0.0010)  # QRRE
        assert result["pd_floored"][2] == pytest.approx(0.0005)  # Mortgage


# =============================================================================
# LGD FLOOR TESTS (CRE30.41)
# =============================================================================


class TestLGDFloors:
    """Tests for per-collateral-type LGD floor expressions.

    CRR: No LGD floors for A-IRB (all 0%).
    Basel 3.1 (CRE30.41): Differentiated floors:
        - Unsecured: 25%
        - Financial collateral: 0%
        - Receivables: 10%
        - RRE: 5%, CRE: 10%
        - Other physical: 15%
    """

    def test_crr_lgd_floor_is_zero(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: LGD floor should be 0% (no floor)."""
        lf = pl.LazyFrame({"lgd": [0.10]})
        result = lf.with_columns(_lgd_floor_expression(crr_config).alias("lgd_floor")).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.0)

    def test_crr_lgd_floor_with_collateral_is_zero(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: LGD floor with collateral column should also be 0%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "collateral_type": ["residential_re"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(crr_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.0)

    def test_basel31_unsecured_floor_25pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Unsecured default LGD floor is 25%."""
        lf = pl.LazyFrame({"lgd": [0.10]})
        result = lf.with_columns(_lgd_floor_expression(basel31_config).alias("lgd_floor")).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.25)

    def test_basel31_financial_collateral_floor_0pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Financial collateral LGD floor is 0%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "collateral_type": ["financial"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.0)

    def test_basel31_rre_floor_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Residential real estate LGD floor is 5%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01],
                "collateral_type": ["residential_re"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.05)

    def test_basel31_cre_floor_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Commercial real estate LGD floor is 10%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01],
                "collateral_type": ["commercial_re"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

    def test_basel31_receivables_floor_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Receivables LGD floor is 10%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01],
                "collateral_type": ["receivables"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

    def test_basel31_other_physical_floor_15pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Other physical collateral LGD floor is 15%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01],
                "collateral_type": ["other_physical"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.15)

    def test_lgd_above_floor_is_unchanged(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """LGD above the floor should remain unchanged."""
        lf = pl.LazyFrame({"lgd": [0.40]})
        lgd_floor_expr = _lgd_floor_expression(basel31_config)
        result = lf.with_columns(
            pl.max_horizontal(
                pl.col("lgd"),
                lgd_floor_expr,
            ).alias("lgd_floored")
        ).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.40)

    def test_lgd_below_floor_is_floored(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """LGD below the unsecured floor should be raised to 25%."""
        lf = pl.LazyFrame({"lgd": [0.10]})
        lgd_floor_expr = _lgd_floor_expression(basel31_config)
        result = lf.with_columns(
            pl.max_horizontal(
                pl.col("lgd"),
                lgd_floor_expr,
            ).alias("lgd_floored")
        ).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_apply_irb_formulas_lgd_floor_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() under CRR applies no LGD floor."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        # CRR: lgd_floored == lgd (no floor)
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_apply_irb_formulas_lgd_floor_basel31_unsecured(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() under Basel 3.1 floors LGD at 25%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_apply_irb_formulas_lgd_floor_basel31_with_collateral(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() with collateral_type column uses
        per-collateral floors."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "pd": [0.01, 0.01],
                "lgd": [0.01, 0.01],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "collateral_type": ["financial", "residential_re"],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        # Financial collateral: floor 0%, so lgd stays at 0.01
        assert result["lgd_floored"][0] == pytest.approx(0.01)
        # Residential RE: floor 5%, so lgd stays at 0.05
        assert result["lgd_floored"][1] == pytest.approx(0.05)

    def test_namespace_apply_lgd_floor_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Namespace apply_lgd_floor under CRR returns original LGD."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
            }
        )
        result = lf.irb.apply_lgd_floor(crr_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_namespace_apply_lgd_floor_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_lgd_floor under Basel 3.1 floors at 25%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_multiple_collateral_types_floors(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Each collateral type gets its own LGD floor."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01, 0.01, 0.01, 0.01, 0.01],
                "collateral_type": [
                    "financial",
                    "receivables",
                    "residential_re",
                    "commercial_re",
                    "other_physical",
                ],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        expected = [0.00, 0.10, 0.05, 0.10, 0.15]
        for i, (coll_type, exp_floor) in enumerate(
            zip(result["collateral_type"].to_list(), expected, strict=True)
        ):
            assert result["lgd_floor"][i] == pytest.approx(exp_floor), (
                f"LGD floor mismatch for {coll_type}"
            )

    def test_unknown_collateral_defaults_to_unsecured(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Unknown collateral type defaults to unsecured 25%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "collateral_type": ["unknown_type"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.25)


# =============================================================================
# F-IRB SUPERVISORY LGD TESTS (CRE32.9-12)
# =============================================================================


class TestFIRBSupervisoryLGD:
    """Tests for F-IRB supervisory LGD lookup tables.

    CRR (Art. 161): Senior unsecured 45%, subordinated 75%,
        financial 0%, receivables 35%, RE 35%, other physical 40%.

    Basel 3.1 (CRE32.9-12): Senior unsecured 40%, subordinated 75%,
        financial 0%, receivables 20%, RE 20%, other physical 25%.
    """

    # --- Dictionary / table values ---

    def test_crr_senior_unsecured_lgd(self) -> None:
        """CRR: Senior unsecured LGD is 45%."""
        assert FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.45")

    def test_crr_subordinated_lgd(self) -> None:
        """CRR: Subordinated LGD is 75%."""
        assert FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")

    def test_crr_financial_collateral_lgd(self) -> None:
        """CRR: Financial collateral LGD is 0%."""
        assert FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")

    def test_crr_receivables_lgd(self) -> None:
        """CRR: Receivables LGD is 35%."""
        assert FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.35")

    def test_crr_residential_re_lgd(self) -> None:
        """CRR: Residential RE LGD is 35%."""
        assert FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.35")

    def test_crr_commercial_re_lgd(self) -> None:
        """CRR: Commercial RE LGD is 35%."""
        assert FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.35")

    def test_crr_other_physical_lgd(self) -> None:
        """CRR: Other physical LGD is 40%."""
        assert FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.40")

    def test_basel31_senior_unsecured_lgd(self) -> None:
        """Basel 3.1: Senior unsecured LGD is 40% (down from 45%)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.40")

    def test_basel31_subordinated_lgd(self) -> None:
        """Basel 3.1: Subordinated LGD is 75% (unchanged)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")

    def test_basel31_financial_collateral_lgd(self) -> None:
        """Basel 3.1: Financial collateral LGD is 0% (unchanged)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")

    def test_basel31_receivables_lgd(self) -> None:
        """Basel 3.1: Receivables LGD is 20% (down from 35%)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.20")

    def test_basel31_residential_re_lgd(self) -> None:
        """Basel 3.1: Residential RE LGD is 20% (down from 35%)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.20")

    def test_basel31_commercial_re_lgd(self) -> None:
        """Basel 3.1: Commercial RE LGD is 20% (down from 35%)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.20")

    def test_basel31_other_physical_lgd(self) -> None:
        """Basel 3.1: Other physical LGD is 25% (down from 40%)."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.25")

    # --- get_firb_lgd_table_for_framework ---

    def test_get_table_crr_returns_crr_dict(self) -> None:
        """get_firb_lgd_table_for_framework(False) returns CRR table."""
        table = get_firb_lgd_table_for_framework(is_basel_3_1=False)
        assert table is FIRB_SUPERVISORY_LGD

    def test_get_table_basel31_returns_basel31_dict(self) -> None:
        """get_firb_lgd_table_for_framework(True) returns Basel 3.1 table."""
        table = get_firb_lgd_table_for_framework(is_basel_3_1=True)
        assert table is BASEL31_FIRB_SUPERVISORY_LGD

    # --- lookup_firb_lgd ---

    def test_lookup_crr_unsecured_senior(self) -> None:
        """lookup_firb_lgd CRR: unsecured senior returns 45%."""
        result = lookup_firb_lgd(
            collateral_type=None,
            is_subordinated=False,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.45")

    def test_lookup_basel31_unsecured_senior(self) -> None:
        """lookup_firb_lgd Basel 3.1: unsecured senior returns 40%."""
        result = lookup_firb_lgd(
            collateral_type=None,
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.40")

    def test_lookup_crr_subordinated(self) -> None:
        """lookup_firb_lgd CRR: subordinated returns 75%."""
        result = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=True,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.75")

    def test_lookup_basel31_subordinated(self) -> None:
        """lookup_firb_lgd Basel 3.1: subordinated returns 75% (unchanged)."""
        result = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=True,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.75")

    def test_lookup_crr_receivables(self) -> None:
        """lookup_firb_lgd CRR: receivables returns 35%."""
        result = lookup_firb_lgd(
            collateral_type="receivables",
            is_subordinated=False,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.35")

    def test_lookup_basel31_receivables(self) -> None:
        """lookup_firb_lgd Basel 3.1: receivables returns 20%."""
        result = lookup_firb_lgd(
            collateral_type="receivables",
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.20")

    def test_lookup_crr_residential_re(self) -> None:
        """lookup_firb_lgd CRR: residential RE returns 35%."""
        result = lookup_firb_lgd(
            collateral_type="residential_re",
            is_subordinated=False,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.35")

    def test_lookup_basel31_residential_re(self) -> None:
        """lookup_firb_lgd Basel 3.1: residential RE returns 20%."""
        result = lookup_firb_lgd(
            collateral_type="residential_re",
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.20")

    def test_lookup_crr_other_physical(self) -> None:
        """lookup_firb_lgd CRR: other physical returns 40%."""
        result = lookup_firb_lgd(
            collateral_type="other_physical",
            is_subordinated=False,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.40")

    def test_lookup_basel31_other_physical(self) -> None:
        """lookup_firb_lgd Basel 3.1: other physical returns 25%."""
        result = lookup_firb_lgd(
            collateral_type="other_physical",
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.25")

    def test_lookup_financial_collateral_unchanged(self) -> None:
        """Financial collateral LGD is 0% under both frameworks."""
        crr_lgd = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=False,
            is_basel_3_1=False,
        )
        b31_lgd = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert crr_lgd == Decimal("0.00")
        assert b31_lgd == Decimal("0.00")

    def test_lookup_unknown_collateral_defaults_to_unsecured(self) -> None:
        """Unknown collateral type defaults to unsecured senior LGD."""
        crr_lgd = lookup_firb_lgd(
            collateral_type="rare_gems",
            is_subordinated=False,
            is_basel_3_1=False,
        )
        b31_lgd = lookup_firb_lgd(
            collateral_type="rare_gems",
            is_subordinated=False,
            is_basel_3_1=True,
        )
        assert crr_lgd == Decimal("0.45")
        assert b31_lgd == Decimal("0.40")

    # --- Namespace apply_firb_lgd ---

    def test_namespace_apply_firb_lgd_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Namespace apply_firb_lgd uses CRR LGD values (45% senior)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [None],
                "approach": [ApproachType.FIRB.value],
            }
        )
        result = lf.irb.apply_firb_lgd(crr_config).collect()
        assert result["lgd"][0] == pytest.approx(0.45)

    def test_namespace_apply_firb_lgd_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_firb_lgd uses Basel 3.1 LGD values (40% senior)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [None],
                "approach": [ApproachType.FIRB.value],
            }
        )
        result = lf.irb.apply_firb_lgd(basel31_config).collect()
        assert result["lgd"][0] == pytest.approx(0.40)

    def test_namespace_firb_lgd_airb_retains_own_lgd(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """A-IRB exposures retain their own LGD estimates, not supervisory."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.30],
                "approach": [ApproachType.AIRB.value],
            }
        )
        result = lf.irb.apply_firb_lgd(basel31_config).collect()
        assert result["lgd"][0] == pytest.approx(0.30)


# =============================================================================
# CCF TESTS (CRE20.88, CRE32.27)
# =============================================================================


class TestCCFBasel31:
    """Tests for CCF changes under Basel 3.1.

    Key changes:
    - UCC (LR) CCF: CRR 0% -> Basel 3.1 10% (CRE20.88)
    - A-IRB CCF floor: modelled CCF >= 50% of SA CCF (CRE32.27)
    """

    # --- sa_ccf_expression ---

    def test_sa_ccf_lr_crr_is_zero(self) -> None:
        """CRR: LR (low risk / UCC) gets 0% CCF."""
        lf = pl.LazyFrame({"risk_type": ["LR"]})
        result = lf.with_columns(sa_ccf_expression(is_basel_3_1=False).alias("ccf")).collect()
        assert result["ccf"][0] == pytest.approx(0.0)

    def test_sa_ccf_lr_basel31_is_10pct(self) -> None:
        """Basel 3.1: LR (UCC) gets 10% CCF (CRE20.88)."""
        lf = pl.LazyFrame({"risk_type": ["LR"]})
        result = lf.with_columns(sa_ccf_expression(is_basel_3_1=True).alias("ccf")).collect()
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_sa_ccf_low_risk_crr_is_zero(self) -> None:
        """CRR: low_risk gets 0% CCF (alias for LR)."""
        lf = pl.LazyFrame({"risk_type": ["low_risk"]})
        result = lf.with_columns(sa_ccf_expression(is_basel_3_1=False).alias("ccf")).collect()
        assert result["ccf"][0] == pytest.approx(0.0)

    def test_sa_ccf_low_risk_basel31_is_10pct(self) -> None:
        """Basel 3.1: low_risk gets 10% CCF."""
        lf = pl.LazyFrame({"risk_type": ["low_risk"]})
        result = lf.with_columns(sa_ccf_expression(is_basel_3_1=True).alias("ccf")).collect()
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_sa_ccf_fr_unchanged(self) -> None:
        """Full risk CCF is 100% under both frameworks."""
        lf = pl.LazyFrame({"risk_type": ["FR", "FR"]})
        crr_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=False).alias("ccf")).collect()
        b31_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=True).alias("ccf")).collect()
        assert crr_result["ccf"][0] == pytest.approx(1.0)
        assert b31_result["ccf"][0] == pytest.approx(1.0)

    def test_sa_ccf_mr_unchanged(self) -> None:
        """Medium risk CCF is 50% under both frameworks."""
        lf = pl.LazyFrame({"risk_type": ["MR"]})
        crr_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=False).alias("ccf")).collect()
        b31_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=True).alias("ccf")).collect()
        assert crr_result["ccf"][0] == pytest.approx(0.5)
        assert b31_result["ccf"][0] == pytest.approx(0.5)

    def test_sa_ccf_mlr_unchanged(self) -> None:
        """Medium-low risk CCF is 20% under both frameworks."""
        lf = pl.LazyFrame({"risk_type": ["MLR"]})
        crr_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=False).alias("ccf")).collect()
        b31_result = lf.with_columns(sa_ccf_expression(is_basel_3_1=True).alias("ccf")).collect()
        assert crr_result["ccf"][0] == pytest.approx(0.2)
        assert b31_result["ccf"][0] == pytest.approx(0.2)

    # --- A-IRB CCF floor (CRE32.27) ---

    def test_airb_ccf_floor_applied_under_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: A-IRB modelled CCF is floored at 50% of SA CCF.

        Example: SA CCF = 50% (MR), modelled = 10%.
        Floor = 0.50 * 0.50 = 0.25. Result should be 0.25.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],  # SA CCF = 50%
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.10],  # 10% modelled < 25% floor
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        # Floor = 50% of 50% = 25%
        assert result["ccf"][0] == pytest.approx(0.25)

    def test_airb_ccf_above_floor_unchanged_under_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: A-IRB modelled CCF above floor passes through.

        Example: SA CCF = 50% (MR), modelled = 40%.
        Floor = 0.50 * 0.50 = 0.25. Result should be 0.40.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],  # SA CCF = 50%
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.40],  # 40% > 25% floor
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.40)

    def test_airb_ccf_floor_not_applied_under_crr(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: A-IRB modelled CCF passes through without a floor.

        Under CRR, there is no 50%-of-SA floor on A-IRB CCF estimates.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],  # SA CCF = 50%
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.10],  # 10% modelled
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, crr_config).collect()
        # No floor under CRR, modelled value passes through
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_airb_ccf_floor_with_full_risk(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: A-IRB CCF floor with FR (100%) is 50%.

        SA CCF = 100%, floor = 50% of 100% = 50%.
        Modelled = 30% -> floored at 50%.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["FR"],  # SA CCF = 100%
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.30],  # 30% < 50% floor
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.50)

    def test_airb_ccf_floor_with_lr_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: A-IRB CCF floor with LR (10%) is 5%.

        SA CCF = 10% (Basel 3.1 LR), floor = 50% of 10% = 5%.
        Modelled = 3% -> floored at 5%.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["LR"],  # SA CCF = 10% under Basel 3.1
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.03],  # 3% < 5% floor
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.05)

    def test_ccf_calculator_lr_crr_via_apply_ccf(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CCFCalculator.apply_ccf: CRR LR gets 0% CCF."""
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["LR"],
                "approach": ["standardised"],
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, crr_config).collect()
        assert result["ccf"][0] == pytest.approx(0.0)

    def test_ccf_calculator_lr_basel31_via_apply_ccf(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """CCFCalculator.apply_ccf: Basel 3.1 LR gets 10% CCF."""
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["LR"],
                "approach": ["standardised"],
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_ead_from_ccf_lr_crr_is_zero(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: EAD from CCF for LR is 0 (0% of nominal)."""
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["LR"],
                "approach": ["standardised"],
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, crr_config).collect()
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)

    def test_ead_from_ccf_lr_basel31_is_10k(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: EAD from CCF for LR is 10% of nominal."""
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["LR"],
                "approach": ["standardised"],
                "interest": [0.0],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        assert result["ead_from_ccf"][0] == pytest.approx(10_000.0)


# =============================================================================
# EQUITY ROUTING TESTS (CRE20.58-62)
# =============================================================================


class TestEquityBasel31:
    """Tests for equity approach routing under Basel 3.1.

    Under CRR: Firms with IRB permissions use IRB Simple (Art. 155).
    Under Basel 3.1: IRB for equity removed -- all equity uses SA (Art. 133).
    """

    def test_crr_with_full_irb_returns_irb_simple(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR + full IRB permissions -> irb_simple approach for equity."""
        calculator = EquityCalculator()
        approach = calculator._determine_approach(crr_config)
        assert approach == "irb_simple"

    def test_basel31_with_full_irb_returns_sa(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 + full IRB permissions -> sa (IRB equity removed)."""
        calculator = EquityCalculator()
        approach = calculator._determine_approach(basel31_config)
        assert approach == "sa"

    def test_crr_sa_only_returns_sa(
        self,
        crr_sa_only_config: CalculationConfig,
    ) -> None:
        """CRR + SA-only permissions -> sa approach."""
        calculator = EquityCalculator()
        approach = calculator._determine_approach(crr_sa_only_config)
        assert approach == "sa"

    def test_basel31_sa_only_returns_sa(
        self,
        basel31_sa_only_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 + SA-only permissions -> sa approach."""
        calculator = EquityCalculator()
        approach = calculator._determine_approach(basel31_sa_only_config)
        assert approach == "sa"

    def test_crr_firb_only_returns_irb_simple(self) -> None:
        """CRR + F-IRB only permissions -> irb_simple."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.firb_only(),
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "irb_simple"

    def test_basel31_firb_only_returns_sa(self) -> None:
        """Basel 3.1 + F-IRB only permissions -> sa (IRB equity removed)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            irb_permissions=IRBPermissions.firb_only(),
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "sa"

    def test_crr_airb_only_returns_irb_simple(self) -> None:
        """CRR + A-IRB only permissions -> irb_simple."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.airb_only(),
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "irb_simple"

    def test_basel31_airb_only_returns_sa(self) -> None:
        """Basel 3.1 + A-IRB only permissions -> sa (IRB equity removed)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            irb_permissions=IRBPermissions.airb_only(),
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "sa"

    def test_single_exposure_crr_irb_uses_irb_rw(self) -> None:
        """CRR: calculate_single_exposure with IRB uses 370% for other."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.full_irb(),
        )
        calculator = EquityCalculator()
        result = calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="other",
            config=config,
        )
        assert result["approach"] == "irb_simple"
        assert result["risk_weight"] == pytest.approx(3.70)

    def test_single_exposure_basel31_uses_sa_rw(self) -> None:
        """Basel 3.1: calculate_single_exposure with IRB perm uses SA 250%."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            irb_permissions=IRBPermissions.full_irb(),
        )
        calculator = EquityCalculator()
        result = calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=config,
        )
        assert result["approach"] == "sa"
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_single_exposure_basel31_exchange_traded(self) -> None:
        """Basel 3.1: Exchange-traded equity gets SA 100% RW (not IRB 290%)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            irb_permissions=IRBPermissions.full_irb(),
        )
        calculator = EquityCalculator()
        result = calculator.calculate_single_exposure(
            ead=Decimal("500000"),
            equity_type="listed",
            is_exchange_traded=True,
            config=config,
        )
        assert result["approach"] == "sa"
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(500_000.0)


# =============================================================================
# SCALING FACTOR AND END-TO-END TESTS
# =============================================================================


class TestScalingFactor:
    """Tests for CRR 1.06 scaling factor removal under Basel 3.1."""

    def test_crr_applies_scaling_factor(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: apply_irb_formulas uses 1.06 scaling factor."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["scaling_factor"][0] == pytest.approx(1.06)

    def test_basel31_removes_scaling_factor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: apply_irb_formulas uses 1.0 scaling factor."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        assert result["scaling_factor"][0] == pytest.approx(1.0)

    def test_crr_rwa_includes_scaling(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR: RWA = K * 12.5 * 1.06 * EAD * MA (scaling included)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
            }
        )
        result = apply_irb_formulas(lf, crr_config).collect()
        k = result["k"][0]
        ma = result["maturity_adjustment"][0]
        expected_rwa = k * 12.5 * 1.06 * 1_000_000.0 * ma
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_basel31_rwa_no_scaling(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: RWA = K * 12.5 * 1.0 * EAD * MA (no scaling)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        k = result["k"][0]
        ma = result["maturity_adjustment"][0]
        expected_rwa = k * 12.5 * 1.0 * 1_000_000.0 * ma
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_same_inputs_crr_rwa_higher_than_basel31(
        self,
        crr_config: CalculationConfig,
        basel31_config: CalculationConfig,
    ) -> None:
        """For the same inputs, CRR RWA should be higher due to 1.06 factor
        (partially offset by different PD/LGD floors)."""
        # Use inputs that are above both frameworks' floors
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.05],  # well above both floors
                "lgd": [0.45],  # above Basel 3.1 25% unsecured floor
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
            }
        )
        crr_result = apply_irb_formulas(lf, crr_config).collect()
        b31_result = apply_irb_formulas(lf, basel31_config).collect()
        # CRR has 1.06x scaling, so its RWA should be ~6% higher
        ratio = crr_result["rwa"][0] / b31_result["rwa"][0]
        assert ratio == pytest.approx(1.06, rel=0.01)


# =============================================================================
# CONFIG FACTORY METHOD TESTS
# =============================================================================


class TestConfigFactoryMethods:
    """Tests for CalculationConfig factory methods to ensure correct
    framework-specific defaults."""

    def test_crr_pd_floors_uniform(self) -> None:
        """CRR config pd_floors has uniform 0.03% for all classes."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.pd_floors.corporate == Decimal("0.0003")
        assert config.pd_floors.corporate_sme == Decimal("0.0003")
        assert config.pd_floors.retail_mortgage == Decimal("0.0003")
        assert config.pd_floors.retail_other == Decimal("0.0003")
        assert config.pd_floors.retail_qrre_transactor == Decimal("0.0003")
        assert config.pd_floors.retail_qrre_revolver == Decimal("0.0003")

    def test_basel31_pd_floors_differentiated(self) -> None:
        """Basel 3.1 config pd_floors has differentiated values."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
        )
        assert config.pd_floors.corporate == Decimal("0.0005")
        assert config.pd_floors.corporate_sme == Decimal("0.0005")
        assert config.pd_floors.retail_mortgage == Decimal("0.0005")
        assert config.pd_floors.retail_other == Decimal("0.0005")
        assert config.pd_floors.retail_qrre_transactor == Decimal("0.0003")
        assert config.pd_floors.retail_qrre_revolver == Decimal("0.0010")

    def test_crr_lgd_floors_all_zero(self) -> None:
        """CRR config lgd_floors are all 0% (no floor)."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.lgd_floors.unsecured == Decimal("0.0")
        assert config.lgd_floors.financial_collateral == Decimal("0.0")
        assert config.lgd_floors.receivables == Decimal("0.0")
        assert config.lgd_floors.residential_real_estate == Decimal("0.0")
        assert config.lgd_floors.commercial_real_estate == Decimal("0.0")
        assert config.lgd_floors.other_physical == Decimal("0.0")

    def test_basel31_lgd_floors_differentiated(self) -> None:
        """Basel 3.1 config lgd_floors has differentiated values."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
        )
        assert config.lgd_floors.unsecured == Decimal("0.25")
        assert config.lgd_floors.financial_collateral == Decimal("0.0")
        assert config.lgd_floors.receivables == Decimal("0.10")
        assert config.lgd_floors.residential_real_estate == Decimal("0.05")
        assert config.lgd_floors.commercial_real_estate == Decimal("0.10")
        assert config.lgd_floors.other_physical == Decimal("0.15")

    def test_crr_scaling_factor(self) -> None:
        """CRR config has 1.06 scaling factor."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.scaling_factor == Decimal("1.06")

    def test_basel31_scaling_factor_removed(self) -> None:
        """Basel 3.1 config has 1.0 scaling factor (removed)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
        )
        assert config.scaling_factor == Decimal("1.0")

    def test_crr_is_crr_property(self) -> None:
        """CRR config.is_crr is True."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.is_crr is True
        assert config.is_basel_3_1 is False

    def test_basel31_is_basel31_property(self) -> None:
        """Basel 3.1 config.is_basel_3_1 is True."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
        )
        assert config.is_crr is False
        assert config.is_basel_3_1 is True
