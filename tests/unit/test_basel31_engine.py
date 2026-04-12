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
from tests.fixtures.single_exposure import calculate_single_equity_exposure

import rwa_calc.engine.irb.namespace  # noqa: F401 - register namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_SUPERVISORY_LGD,
    get_firb_lgd_table_for_framework,
    lookup_firb_lgd,
)
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.ccf import CCFCalculator, sa_ccf_expression
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.formulas import (
    _lgd_floor_expression,
    _lgd_floor_expression_with_collateral,
    _pd_floor_expression,
    _polars_correlation_expr,
    apply_irb_formulas,
    calculate_correlation,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR (Basel 3.0) configuration."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def crr_sa_only_config() -> CalculationConfig:
    """CRR configuration with SA-only permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture
def basel31_sa_only_config() -> CalculationConfig:
    """Basel 3.1 configuration with SA-only permissions."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        permission_mode=PermissionMode.STANDARDISED,
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
        result = lf.with_columns(
            _pd_floor_expression(basel31_config, has_transactor_col=False).alias("pd_floor")
        ).collect()
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
        result = lf.with_columns(
            _pd_floor_expression(basel31_config, has_transactor_col=False).alias("pd_floor")
        ).collect()
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
        result = lf.with_columns(
            _pd_floor_expression(basel31_config, has_transactor_col=False).alias("pd_floor")
        ).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0010)

    def test_basel31_retail_mortgage_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Retail mortgage PD floor is 0.10% (PRA Art. 163(1)(b) UK RRE)."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_MORTGAGE"],
                "pd": [0.001],
            }
        )
        result = lf.with_columns(
            _pd_floor_expression(basel31_config, has_transactor_col=False).alias("pd_floor")
        ).collect()
        assert result["pd_floor"][0] == pytest.approx(0.0010)

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
        result = lf.with_columns(
            _pd_floor_expression(basel31_config, has_transactor_col=False).alias("pd_floor")
        ).collect()
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
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=False)
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
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=False)
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
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=False)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)  # Corporate: 0.05%
        assert result["pd_floored"][1] == pytest.approx(0.0010)  # QRRE revolver: 0.10%
        assert result["pd_floored"][2] == pytest.approx(0.0010)  # Mortgage: 0.10% (Art. 163(1)(b))

    def test_qrre_transactor_floor_with_column(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: QRRE transactor gets 0.05% floor (Art. 163(1)(c))."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_QRRE", "RETAIL_QRRE"],
                "pd": [0.0001, 0.0001],
                "is_qrre_transactor": [True, False],
            }
        )
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=True)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)  # Transactor: 0.05%
        assert result["pd_floored"][1] == pytest.approx(0.0010)  # Revolver: 0.10%

    def test_qrre_transactor_null_defaults_to_revolver(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: QRRE with null is_qrre_transactor defaults to revolver floor."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["RETAIL_QRRE"],
                "pd": [0.0001],
                "is_qrre_transactor": [None],
            },
            schema={
                "exposure_class": pl.String,
                "pd": pl.Float64,
                "is_qrre_transactor": pl.Boolean,
            },
        )
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=True)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0010)  # Conservative default

    def test_transactor_col_ignored_for_non_qrre(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """is_qrre_transactor only affects QRRE exposures, not other classes."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "RETAIL_OTHER", "RETAIL_QRRE"],
                "pd": [0.0001, 0.0001, 0.0001],
                "is_qrre_transactor": [True, True, True],
            }
        )
        pd_floor_expr = _pd_floor_expression(basel31_config, has_transactor_col=True)
        result = lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        ).collect()
        assert result["pd_floored"][0] == pytest.approx(0.0005)  # Corporate: 0.05%
        assert result["pd_floored"][1] == pytest.approx(0.0005)  # Retail other: 0.05%
        assert result["pd_floored"][2] == pytest.approx(0.0005)  # QRRE transactor: 0.05%


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
        - RRE: 10%, CRE: 10%
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

    def test_basel31_rre_floor_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Residential real estate LGD floor is 10% (PRA Art. 161/164)."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.01],
                "collateral_type": ["residential_re"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

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

    def test_apply_irb_formulas_lgd_floor_basel31_airb_unsecured(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() under Basel 3.1 floors A-IRB LGD at 25%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "ead_final": [1_000_000.0],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_apply_irb_formulas_lgd_floor_basel31_firb_no_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() under Basel 3.1 does NOT floor F-IRB LGD.

        F-IRB uses supervisory LGD values which are regulatory and don't
        need flooring. Only A-IRB own-estimate LGDs are floored (CRE30.41).
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "ead_final": [1_000_000.0],
                "is_airb": [False],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        # F-IRB: lgd_floored == lgd (no floor applied)
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_apply_irb_formulas_lgd_floor_basel31_airb_with_collateral(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_irb_formulas() with collateral_type column uses
        per-collateral floors for A-IRB rows."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "pd": [0.01, 0.01],
                "lgd": [0.01, 0.01],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "collateral_type": ["financial", "residential_re"],
                "is_airb": [True, True],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        # Financial collateral: floor 0%, so lgd stays at 0.01
        assert result["lgd_floored"][0] == pytest.approx(0.01)
        # Residential RE: floor 10%, so lgd is floored up to 0.10
        assert result["lgd_floored"][1] == pytest.approx(0.10)

    def test_apply_irb_formulas_lgd_floor_basel31_mixed_approaches(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 LGD floor applies to A-IRB but NOT F-IRB rows in same frame.

        This tests the core regulatory requirement: LGD floors per CRE30.41
        only apply to A-IRB own-estimate LGDs. F-IRB supervisory LGDs are
        regulatory values that don't need flooring.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "pd": [0.01, 0.01],
                "lgd": [0.10, 0.10],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "is_airb": [True, False],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        # A-IRB row: LGD floored to 25% (unsecured)
        assert result["lgd_floored"][0] == pytest.approx(0.25)
        # F-IRB row: LGD unchanged at 10% (no floor)
        assert result["lgd_floored"][1] == pytest.approx(0.10)

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

    def test_namespace_apply_lgd_floor_basel31_airb(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_lgd_floor under Basel 3.1 floors A-IRB at 25%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "is_airb": [True],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_namespace_apply_lgd_floor_basel31_firb_no_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Namespace apply_lgd_floor under Basel 3.1 does NOT floor F-IRB."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE"],
                "pd": [0.01],
                "lgd": [0.10],
                "is_airb": [False],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        # F-IRB: no floor applied
        assert result["lgd_floored"][0] == pytest.approx(0.10)

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
        expected = [0.00, 0.10, 0.10, 0.10, 0.15]
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

    def test_subordinated_unsecured_floor_50pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 (CRE30.41): Subordinated unsecured LGD floor is 50%.

        When seniority column is available and indicates subordinated debt,
        the unsecured LGD floor increases from 25% to 50%.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10],
                "collateral_type": ["unsecured", "unsecured"],
                "seniority": ["subordinated", "senior"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_seniority=True).alias(
                "lgd_floor"
            )
        ).collect()
        # Subordinated unsecured: 50% floor
        assert result["lgd_floor"][0] == pytest.approx(0.50)
        # Senior unsecured: 25% floor
        assert result["lgd_floor"][1] == pytest.approx(0.25)

    def test_subordinated_unsecured_floor_no_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Subordinated floor 50% via _lgd_floor_expression (no collateral col)."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10],
                "seniority": ["subordinated", "senior"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression(basel31_config, has_seniority=True).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.50)
        assert result["lgd_floor"][1] == pytest.approx(0.25)

    def test_subordinated_with_collateral_uses_collateral_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: Subordinated with physical collateral uses collateral floor, not 50%.

        The 50% subordinated floor only applies to unsecured exposures.
        When collateral is present, the collateral-specific floor applies.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.01, 0.01],
                "collateral_type": ["residential_re", "other_physical"],
                "seniority": ["subordinated", "subordinated"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_seniority=True).alias(
                "lgd_floor"
            )
        ).collect()
        # Collateral floor takes precedence: RRE 10%, other physical 15%
        assert result["lgd_floor"][0] == pytest.approx(0.10)
        assert result["lgd_floor"][1] == pytest.approx(0.15)

    def test_corporate_subordinated_floor_25pct_with_exposure_class(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 161(5): Corporate subordinated LGD floor is 25%, same as senior.

        When exposure_class is available, subordinated corporate exposures
        get the standard 25% floor (not 50%). The 50% floor only applies
        to retail QRRE per Art. 164(4)(b)(i).
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10, 0.10],
                "collateral_type": ["unsecured", "unsecured", "unsecured"],
                "seniority": ["subordinated", "senior", "subordinated"],
                "exposure_class": ["CORPORATE", "CORPORATE", "INSTITUTION"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(
                basel31_config, has_seniority=True, has_exposure_class=True
            ).alias("lgd_floor")
        ).collect()
        # Corporate subordinated: 25% (Art. 161(5))
        assert result["lgd_floor"][0] == pytest.approx(0.25)
        # Corporate senior: 25%
        assert result["lgd_floor"][1] == pytest.approx(0.25)
        # Institution subordinated: 25% (not retail QRRE, so no 50%)
        assert result["lgd_floor"][2] == pytest.approx(0.25)

    def test_corporate_subordinated_floor_25pct_no_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 161(5): Corporate subordinated floor 25% via _lgd_floor_expression."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10],
                "seniority": ["subordinated", "senior"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression(
                basel31_config, has_seniority=True, has_exposure_class=True
            ).alias("lgd_floor")
        ).collect()
        # Corporate subordinated: 25% (Art. 161(5))
        assert result["lgd_floor"][0] == pytest.approx(0.25)
        # Corporate senior: 25%
        assert result["lgd_floor"][1] == pytest.approx(0.25)

    def test_retail_qrre_floor_50pct_with_exposure_class(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(b)(i): ALL retail QRRE unsecured exposures get 50% LGD floor.

        The 50% floor applies to all QRRE exposures regardless of seniority.
        Corporate exposures get 25% regardless of seniority (Art. 161(5)).
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10, 0.10],
                "collateral_type": ["unsecured", "unsecured", "unsecured"],
                "seniority": ["subordinated", "subordinated", "senior"],
                "exposure_class": ["retail_qrre", "CORPORATE", "retail_qrre"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(
                basel31_config, has_seniority=True, has_exposure_class=True
            ).alias("lgd_floor")
        ).collect()
        # Retail QRRE subordinated: 50% (Art. 164(4)(b)(i))
        assert result["lgd_floor"][0] == pytest.approx(0.50)
        # Corporate subordinated: 25% (Art. 161(5))
        assert result["lgd_floor"][1] == pytest.approx(0.25)
        # Retail QRRE senior: 50% (ALL QRRE gets 50%, Art. 164(4)(b)(i))
        assert result["lgd_floor"][2] == pytest.approx(0.50)

    def test_corporate_subordinated_via_namespace(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Pipeline: apply_lgd_floor() gives corporate subordinated 25% floor.

        Verifies the namespace method correctly passes exposure_class
        awareness to the floor expression, so corporate subordinated
        exposures get 25% (not 50%) when exposure_class column is present.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "lgd_input": [0.10, 0.10],
                "seniority": ["subordinated", "senior"],
                "is_airb": [True, True],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        # Both get 25% floor — corporate subordinated same as senior (Art. 161(5))
        assert result["lgd_floored"][0] == pytest.approx(0.25)
        assert result["lgd_floored"][1] == pytest.approx(0.25)

    # --- Retail LGD floor tests (Art. 164(4)) ---

    def test_retail_mortgage_floor_5pct_no_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(a): Retail mortgage LGD floor is 5% (RRE-secured).

        Without collateral_type column, retail_mortgage is assumed RRE-secured
        and gets the 5% floor, not the corporate 25%.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.02, 0.02],
                "exposure_class": ["retail_mortgage", "CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression(basel31_config, has_exposure_class=True).alias("lgd_floor")
        ).collect()
        # Retail mortgage: 5% (Art. 164(4)(a))
        assert result["lgd_floor"][0] == pytest.approx(0.05)
        # Corporate: 25% (Art. 161(5))
        assert result["lgd_floor"][1] == pytest.approx(0.25)

    def test_retail_qrre_floor_50pct_no_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(b)(i): QRRE unsecured LGD floor is 50%.

        Applies regardless of seniority when exposure_class is available.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10],
                "exposure_class": ["retail_qrre", "retail_qrre"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression(basel31_config, has_exposure_class=True).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.50)
        assert result["lgd_floor"][1] == pytest.approx(0.50)

    def test_retail_other_floor_30pct_no_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(b)(ii): Other retail unsecured LGD floor is 30%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "exposure_class": ["retail_other"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression(basel31_config, has_exposure_class=True).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.30)

    def test_retail_mortgage_rre_collateral_floor_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(a): Retail mortgage with RRE collateral gets 5% floor.

        Corporate with RRE collateral gets 10% (Art. 161(5)).
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.02, 0.02],
                "collateral_type": ["residential_re", "residential_re"],
                "exposure_class": ["retail_mortgage", "CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        # Retail mortgage + RRE: 5% (Art. 164(4)(a))
        assert result["lgd_floor"][0] == pytest.approx(0.05)
        # Corporate + RRE: 10% (Art. 161(5))
        assert result["lgd_floor"][1] == pytest.approx(0.10)

    def test_retail_other_unsecured_floor_30pct_with_collateral_col(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Art. 164(4)(b)(ii): Other retail unsecured gets 30% floor.

        Corporate unsecured gets 25% (Art. 161(5)).
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.10, 0.10],
                "collateral_type": ["unsecured", "unsecured"],
                "exposure_class": ["retail_other", "CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        # Retail other unsecured: 30% (Art. 164(4)(b)(ii))
        assert result["lgd_floor"][0] == pytest.approx(0.30)
        # Corporate unsecured: 25% (Art. 161(5))
        assert result["lgd_floor"][1] == pytest.approx(0.25)

    def test_retail_with_financial_collateral_floor_0pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Retail with financial collateral gets 0% floor (same LGDS as corporate)."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "collateral_type": ["financial_collateral"],
                "exposure_class": ["retail_other"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.0)

    def test_retail_via_namespace_apply_lgd_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Pipeline: apply_lgd_floor() applies retail-specific floors.

        Verifies retail_other gets 30% and retail_qrre gets 50% through
        the namespace pipeline.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["retail_other", "retail_qrre", "CORPORATE"],
                "lgd_input": [0.10, 0.10, 0.10],
                "is_airb": [True, True, True],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        # Retail other: 30% (Art. 164(4)(b)(ii))
        assert result["lgd_floored"][0] == pytest.approx(0.30)
        # Retail QRRE: 50% (Art. 164(4)(b)(i))
        assert result["lgd_floored"][1] == pytest.approx(0.50)
        # Corporate: 25% (Art. 161(5))
        assert result["lgd_floored"][2] == pytest.approx(0.25)

    def test_retail_mortgage_via_namespace_apply_lgd_floor(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Pipeline: apply_lgd_floor() applies 5% floor for retail_mortgage."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["retail_mortgage"],
                "lgd_input": [0.02],
                "is_airb": [True],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.05)

    def test_retail_lgd_above_floor_unchanged(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Retail A-IRB LGD above floor is not modified.

        Retail other with LGD=0.40 above the 30% floor stays at 0.40.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["retail_other"],
                "lgd_input": [0.40],
                "is_airb": [True],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.40)

    # --- P1.8: Generic 'immovable' collateral_type routing for RRE/CRE ---

    def test_immovable_collateral_retail_mortgage_floor_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8 bug fix: collateral_type 'immovable' with retail_mortgage gets 5% floor.

        Previously, the generic 'immovable' branch always returned 10% (CRE floor)
        regardless of exposure class. Art. 164(4)(a) mandates 5% for retail RRE.
        Since retail_mortgage exposures are by definition RRE-secured (Art. 147(5A)(a)),
        'immovable' collateral on a retail_mortgage must use the 5% floor.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.02, 0.02],
                "collateral_type": ["immovable", "immovable"],
                "exposure_class": ["retail_mortgage", "CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        # Retail mortgage + immovable: 5% (Art. 164(4)(a))
        assert result["lgd_floor"][0] == pytest.approx(0.05)
        # Corporate + immovable: 10% (Art. 161(5))
        assert result["lgd_floor"][1] == pytest.approx(0.10)

    def test_real_estate_collateral_retail_mortgage_floor_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: collateral_type 'real_estate' with retail_mortgage also gets 5%.

        The alias 'real_estate' is another common name for immovable property
        and must also route correctly.
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "collateral_type": ["real_estate"],
                "exposure_class": ["retail_mortgage"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.05)

    def test_property_collateral_retail_mortgage_floor_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: collateral_type 'property' with retail_mortgage also gets 5%."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "collateral_type": ["property"],
                "exposure_class": ["retail_mortgage"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.05)

    def test_immovable_corporate_still_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8 regression: corporate + immovable stays at 10% (Art. 161(5))."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "collateral_type": ["immovable"],
                "exposure_class": ["CORPORATE"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

    def test_immovable_retail_other_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: retail_other with immovable collateral gets 10% (corporate LGDS).

        Art. 164(4)(a) 5% only applies to retail_mortgage (RRE-secured).
        Other retail with RE collateral uses the same LGDS as corporate (10%).
        """
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "collateral_type": ["immovable"],
                "exposure_class": ["retail_other"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

    def test_immovable_without_exposure_class_defaults_10pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: Without exposure_class, immovable defaults to 10% (conservative)."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "collateral_type": ["immovable"],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config).alias("lgd_floor")
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.10)

    def test_apply_irb_formulas_immovable_retail_mortgage_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: apply_irb_formulas() passes has_exposure_class for correct routing.

        Previously, apply_irb_formulas() did not pass has_exposure_class to
        _lgd_floor_expression_with_collateral(), so retail_mortgage with
        'immovable' collateral always got 10% instead of 5%.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["retail_mortgage"],
                "pd": [0.01],
                "lgd": [0.02],
                "ead_final": [500_000.0],
                "collateral_type": ["immovable"],
                "is_airb": [True],
            }
        )
        result = apply_irb_formulas(lf, basel31_config).collect()
        # Retail mortgage + immovable: floored to 5% (Art. 164(4)(a))
        assert result["lgd_floored"][0] == pytest.approx(0.05)

    def test_namespace_immovable_retail_mortgage_5pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: Namespace pipeline correctly floors retail_mortgage + immovable at 5%."""
        lf = pl.LazyFrame(
            {
                "exposure_class": ["retail_mortgage"],
                "lgd_input": [0.02],
                "is_airb": [True],
                "collateral_type": ["immovable"],
            }
        )
        result = lf.irb.apply_lgd_floor(basel31_config).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.05)

    def test_mixed_immovable_collateral_types_batch(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """P1.8: Mixed batch with different collateral aliases all route correctly."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02, 0.02, 0.02, 0.02, 0.02],
                "collateral_type": [
                    "residential_re",  # Explicit RRE
                    "immovable",  # Generic — should use rre_floor
                    "real_estate",  # Generic — should use rre_floor
                    "commercial_re",  # Explicit CRE
                    "immovable",  # Generic — corporate → 10%
                ],
                "exposure_class": [
                    "retail_mortgage",
                    "retail_mortgage",
                    "retail_mortgage",
                    "retail_mortgage",
                    "CORPORATE",
                ],
            }
        )
        result = lf.with_columns(
            _lgd_floor_expression_with_collateral(basel31_config, has_exposure_class=True).alias(
                "lgd_floor"
            )
        ).collect()
        assert result["lgd_floor"][0] == pytest.approx(0.05)  # residential_re → 5%
        assert result["lgd_floor"][1] == pytest.approx(0.05)  # immovable + retail_mortgage → 5%
        assert result["lgd_floor"][2] == pytest.approx(0.05)  # real_estate + retail_mortgage → 5%
        assert result["lgd_floor"][3] == pytest.approx(0.10)  # commercial_re → always 10%
        assert result["lgd_floor"][4] == pytest.approx(0.10)  # immovable + corporate → 10%

    def test_apply_all_formulas_lgd_floor_airb_only(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """apply_all_formulas() gates LGD floor on A-IRB only.

        Verifies that the full namespace pipeline correctly applies LGD
        floors only to A-IRB rows and leaves F-IRB rows unaffected.
        """
        lf = pl.LazyFrame(
            {
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "pd": [0.01, 0.01],
                "lgd": [0.10, 0.10],
                "lgd_input": [0.10, 0.10],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "is_airb": [True, False],
                "approach": [ApproachType.AIRB.value, ApproachType.FIRB.value],
            }
        )
        result = lf.irb.apply_all_formulas(basel31_config).collect()
        # A-IRB: LGD floored to 25%
        assert result["lgd_floored"][0] == pytest.approx(0.25)
        # F-IRB: LGD unchanged at 10%
        assert result["lgd_floored"][1] == pytest.approx(0.10)


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

    def test_lookup_crr_subordinated_unsecured(self) -> None:
        """lookup_firb_lgd CRR: subordinated unsecured returns 75%."""
        result = lookup_firb_lgd(
            collateral_type=None,
            is_subordinated=True,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.75")

    def test_lookup_crr_subordinated_financial_collateral(self) -> None:
        """lookup_firb_lgd CRR: subordinated + financial collateral LGDS = 0%."""
        result = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=True,
            is_basel_3_1=False,
        )
        assert result == Decimal("0.00")

    def test_lookup_basel31_subordinated_unsecured(self) -> None:
        """lookup_firb_lgd Basel 3.1: subordinated unsecured returns 75%."""
        result = lookup_firb_lgd(
            collateral_type=None,
            is_subordinated=True,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.75")

    def test_lookup_basel31_subordinated_financial_collateral(self) -> None:
        """lookup_firb_lgd Basel 3.1: subordinated + financial collateral LGDS = 0%."""
        result = lookup_firb_lgd(
            collateral_type="financial_collateral",
            is_subordinated=True,
            is_basel_3_1=True,
        )
        assert result == Decimal("0.00")

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

    # --- FSE vs non-FSE LGD (Art. 161(1)(a) vs (aa)) ---

    def test_namespace_b31_fse_firb_lgd_45pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 namespace: FSE FIRB gets 45% LGD (Art. 161(1)(a))."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [None],
                "approach": [ApproachType.FIRB.value],
                "cp_is_financial_sector_entity": [True],
            }
        )
        result = lf.irb.apply_firb_lgd(basel31_config).collect()
        assert result["lgd"][0] == pytest.approx(0.45)

    def test_namespace_b31_non_fse_firb_lgd_40pct(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 namespace: non-FSE FIRB gets 40% LGD (Art. 161(1)(aa))."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [None],
                "approach": [ApproachType.FIRB.value],
                "cp_is_financial_sector_entity": [False],
            }
        )
        result = lf.irb.apply_firb_lgd(basel31_config).collect()
        assert result["lgd"][0] == pytest.approx(0.40)

    def test_namespace_crr_fse_ignored(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR namespace: FSE flag is irrelevant — FIRB always gets 45%."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [None],
                "approach": [ApproachType.FIRB.value],
                "cp_is_financial_sector_entity": [True],
            }
        )
        result = lf.irb.apply_firb_lgd(crr_config).collect()
        assert result["lgd"][0] == pytest.approx(0.45)

    # --- Covered bond LGD ---

    def test_b31_covered_bond_dict_value(self) -> None:
        """Basel 3.1 covered bond LGD = 11.25% in dict (Art. 161(1)(d))."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["covered_bond"] == Decimal("0.1125")

    def test_crr_covered_bond_dict_value(self) -> None:
        """CRR covered bond LGD = 11.25% in dict (Art. 161(1)(d))."""
        assert FIRB_SUPERVISORY_LGD["covered_bond"] == Decimal("0.1125")

    # --- B31 FSE key exists ---

    def test_b31_fse_unsecured_key_exists(self) -> None:
        """Basel 3.1 dict has separate unsecured_senior_fse key = 45%."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior_fse"] == Decimal("0.45")


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
        Requires is_revolving=True (Art. 166D(1)(a): own CCFs for revolving only).
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
                "is_revolving": [True],
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
        Requires is_revolving=True (Art. 166D(1)(a): own CCFs for revolving only).
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
                "is_revolving": [True],
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
        """Basel 3.1: A-IRB FR (100% SA) cannot use own-estimate per Art. 166D(1)(a).

        Revolving facilities with 100% SA CCF (Table A1 Row 2 — factoring,
        repos, forward deposits) must use SA CCF, not own-estimate.
        Even a revolving facility gets SA 100% when risk_type=FR.
        """
        calculator = CCFCalculator()
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["FR"],  # SA CCF = 100%
                "approach": [ApproachType.AIRB.value],
                "ccf_modelled": [0.30],  # 30% — ignored, SA 100% applies
                "interest": [0.0],
                "is_revolving": [True],
            }
        )
        result = calculator.apply_ccf(lf, basel31_config).collect()
        # Art. 166D(1)(a): revolving with 100% SA CCF → SA 100% (not modelled)
        assert result["ccf"][0] == pytest.approx(1.0)

    def test_airb_ccf_floor_with_lr_basel31(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1: A-IRB CCF floor with LR (10%) is 5%.

        SA CCF = 10% (Basel 3.1 LR), floor = 50% of 10% = 5%.
        Modelled = 3% -> floored at 5%.
        Requires is_revolving=True (Art. 166D(1)(a): own CCFs for revolving only).
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
                "is_revolving": [True],
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
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "irb_simple"

    def test_basel31_firb_only_returns_sa(self) -> None:
        """Basel 3.1 + F-IRB only permissions -> sa (IRB equity removed)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "sa"

    def test_crr_airb_only_returns_irb_simple(self) -> None:
        """CRR + A-IRB only permissions -> irb_simple."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "irb_simple"

    def test_basel31_airb_only_returns_sa(self) -> None:
        """Basel 3.1 + A-IRB only permissions -> sa (IRB equity removed)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        approach = calculator._determine_approach(config)
        assert approach == "sa"

    def test_single_exposure_crr_irb_uses_irb_rw(self) -> None:
        """CRR: calculate_single_equity_exposure with IRB uses 370% for other."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="other",
            config=config,
        )
        assert result["approach"] == "irb_simple"
        assert result["risk_weight"] == pytest.approx(3.70)

    def test_single_exposure_basel31_uses_sa_rw(self) -> None:
        """Basel 3.1: calculate_single_equity_exposure with IRB perm uses SA 250%."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("1000000"),
            equity_type="unlisted",
            config=config,
        )
        assert result["approach"] == "sa"
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_single_exposure_basel31_exchange_traded(self) -> None:
        """Basel 3.1: Exchange-traded equity gets B31 SA 250% (not CRR 100%)."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
            permission_mode=PermissionMode.IRB,
        )
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            is_exchange_traded=True,
            config=config,
        )
        assert result["approach"] == "sa"
        # B31 Art. 133(3): listed/exchange-traded = 250%
        # 2028 transitional floor = 190%, but 250% > 190% so no floor effect
        assert result["risk_weight"] == pytest.approx(2.50)
        assert result["rwa"] == pytest.approx(1_250_000.0)


class TestEquityTransitionalSchedule:
    """Tests for equity transitional phase-in (PRA Rules 4.1-4.10)."""

    @pytest.mark.parametrize(
        ("year", "expected_std_rw", "expected_hr_rw"),
        [
            (2027, 1.60, 2.20),
            (2028, 1.90, 2.80),
            (2029, 2.20, 3.40),
            (2030, 2.50, 4.00),
            (2031, 2.50, 4.00),  # fully phased
        ],
        ids=["2027", "2028", "2029", "2030_full", "2031_full"],
    )
    def test_transitional_floor_by_year(
        self,
        year: int,
        expected_std_rw: float,
        expected_hr_rw: float,
    ) -> None:
        """Transitional floor should match PRA schedule per year."""
        from rwa_calc.contracts.config import EquityTransitionalConfig

        config = EquityTransitionalConfig.basel_3_1()

        std = config.get_transitional_rw(date(year, 6, 30), is_higher_risk=False)
        hr = config.get_transitional_rw(date(year, 6, 30), is_higher_risk=True)

        assert std is not None
        assert hr is not None
        assert float(std) == pytest.approx(expected_std_rw)
        assert float(hr) == pytest.approx(expected_hr_rw)

    def test_crr_no_transitional(self) -> None:
        """CRR config should not have equity transitional enabled."""
        config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
        assert config.equity_transitional.enabled is False

    def test_speculative_equity_gets_higher_risk_floor(self) -> None:
        """Speculative equity should get the higher-risk transitional floor."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
        calculator = EquityCalculator()
        result = calculate_single_equity_exposure(
            calculator,
            ead=Decimal("100000"),
            equity_type="speculative",
            is_speculative=True,
            config=config,
        )
        # 2027 higher-risk transitional = 220%, SA speculative = 400%
        # max(400%, 220%) = 400% (SA weight already exceeds transitional)
        assert result["risk_weight"] == pytest.approx(4.00)


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
        """Basel 3.1 config pd_floors has differentiated values per PRA Art. 160/163."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 1, 1),
        )
        assert config.pd_floors.corporate == Decimal("0.0005")  # 0.05% Art. 160(1)
        assert config.pd_floors.corporate_sme == Decimal("0.0005")  # 0.05% Art. 160(1)
        assert config.pd_floors.retail_mortgage == Decimal("0.0010")  # 0.10% Art. 163(1)(b)
        assert config.pd_floors.retail_other == Decimal("0.0005")  # 0.05% Art. 163(1)(c)
        assert config.pd_floors.retail_qrre_transactor == Decimal("0.0005")  # 0.05% Art. 163(1)(c)
        assert config.pd_floors.retail_qrre_revolver == Decimal("0.0010")  # 0.10% Art. 163(1)(a)

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
        assert config.lgd_floors.residential_real_estate == Decimal("0.10")
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


# =============================================================================
# SME CORRELATION ADJUSTMENT — Basel 3.1 GBP-native parameters (Art. 153(4))
# =============================================================================


class TestB31SMECorrelation:
    """Tests for Basel 3.1 SME correlation using GBP-native thresholds.

    PRA PS1/26 Art. 153(4) mandates GBP parameters for the SME correlation
    adjustment: threshold = GBP 44m, floor = GBP 4.4m, range = 39.6.
    Unlike CRR (EUR 50m/5m/45 with FX conversion), B31 operates directly
    on GBP turnover without currency conversion.

    References:
    - PRA PS1/26 Art. 153(4)
    - CRR Art. 153(4) (EUR version)
    """

    def test_b31_sme_floor_max_adjustment(self) -> None:
        """At GBP 4.4m floor, SME adjustment should be maximum (0.04).

        Under B31, turnover GBP 4.4m is the floor — anything at or below
        gets the full 0.04 reduction.
        """
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        floor_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=4.4, is_b31=True
        )
        assert base_corr - floor_corr == pytest.approx(0.04, rel=0.01)

    def test_b31_sme_below_floor_also_max_adjustment(self) -> None:
        """Below GBP 4.4m, adjustment still maxes at 0.04 (clamped to floor)."""
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        below_floor_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=2.0, is_b31=True
        )
        assert base_corr - below_floor_corr == pytest.approx(0.04, rel=0.01)

    def test_b31_sme_at_threshold_no_adjustment(self) -> None:
        """At GBP 44m threshold, SME adjustment should be zero.

        s = max(4.4, min(44, 44)) = 44
        adjustment = 0.04 × (1 - (44 - 4.4) / 39.6) = 0.04 × 0 = 0
        """
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        threshold_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=44.0, is_b31=True
        )
        assert base_corr == pytest.approx(threshold_corr, abs=1e-10)

    def test_b31_sme_above_threshold_no_adjustment(self) -> None:
        """Above GBP 44m, no SME adjustment (not classified as SME).

        Large corporates with turnover >= GBP 44m get base corporate correlation.
        """
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        large_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=100.0, is_b31=True
        )
        assert base_corr == pytest.approx(large_corr)

    def test_b31_sme_midpoint_partial_adjustment(self) -> None:
        """At GBP 24.2m (midpoint), adjustment should be ~0.02.

        s = max(4.4, min(24.2, 44)) = 24.2
        adjustment = 0.04 × (1 - (24.2 - 4.4) / 39.6) = 0.04 × 0.5 = 0.02
        """
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        mid_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=24.2, is_b31=True
        )
        assert base_corr - mid_corr == pytest.approx(0.02, rel=0.01)

    def test_b31_no_fx_conversion(self) -> None:
        """B31 uses GBP directly — eur_gbp_rate should not affect the result.

        Passing different eur_gbp_rate values should produce identical B31 results
        because the formula ignores the FX rate under B31.
        """
        corr_default_rate = calculate_correlation(
            pd=0.01,
            exposure_class="CORPORATE",
            turnover_m=20.0,
            eur_gbp_rate=0.8732,
            is_b31=True,
        )
        corr_different_rate = calculate_correlation(
            pd=0.01,
            exposure_class="CORPORATE",
            turnover_m=20.0,
            eur_gbp_rate=0.5000,
            is_b31=True,
        )
        assert corr_default_rate == pytest.approx(corr_different_rate)

    def test_crr_uses_fx_conversion(self) -> None:
        """CRR results should change with different eur_gbp_rate.

        Verifies the CRR path still converts GBP→EUR using the rate.
        """
        corr_rate_1 = calculate_correlation(
            pd=0.01,
            exposure_class="CORPORATE",
            turnover_m=20.0,
            eur_gbp_rate=0.8732,
            is_b31=False,
        )
        corr_rate_2 = calculate_correlation(
            pd=0.01,
            exposure_class="CORPORATE",
            turnover_m=20.0,
            eur_gbp_rate=0.5000,
            is_b31=False,
        )
        # Different FX rates should produce different results under CRR
        assert corr_rate_1 != pytest.approx(corr_rate_2, abs=1e-6)

    def test_b31_vs_crr_numerical_difference(self) -> None:
        """B31 and CRR should produce different results for the same GBP turnover.

        GBP 20m under B31: s = max(4.4, min(20, 44)) = 20
          adjustment = 0.04 × (1 - (20 - 4.4) / 39.6) = 0.04 × 0.60606...

        GBP 20m under CRR at rate 0.8732: EUR = 20/0.8732 ≈ 22.9m
          s = max(5, min(22.9, 50)) = 22.9
          adjustment = 0.04 × (1 - (22.9 - 5) / 45) = 0.04 × 0.60222...

        The adjustments are close but not identical.
        """
        b31_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=20.0, is_b31=True
        )
        crr_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=20.0, is_b31=False
        )
        # Both should have SME adjustment (both are SME-sized)
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        assert b31_corr < base_corr
        assert crr_corr < base_corr
        # But they should differ slightly
        assert b31_corr != pytest.approx(crr_corr, abs=1e-6)

    def test_b31_namespace_sme_correlation(self, basel31_config: CalculationConfig) -> None:
        """B31 namespace path uses GBP-native SME correlation parameters.

        Verifies the full namespace pipeline produces consistent results
        with the scalar B31 formula.
        """
        lf = pl.LazyFrame(
            {
                "pd_floored": [0.01, 0.01, 0.01],
                "exposure_class": ["CORPORATE_SME", "CORPORATE_SME", "CORPORATE"],
                "turnover_m": [4.4, 24.2, 100.0],
                "requires_fi_scalar": [False, False, False],
            }
        )
        result = lf.with_columns(
            _polars_correlation_expr(
                eur_gbp_rate=float(basel31_config.eur_gbp_rate),
                is_b31=True,
            ).alias("correlation")
        ).collect()

        correlations = result["correlation"].to_list()

        # Floor turnover (4.4m) — max adjustment of 0.04
        base = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        assert correlations[0] == pytest.approx(base - 0.04, rel=0.01)

        # Midpoint (24.2m) — ~0.02 adjustment
        assert correlations[1] == pytest.approx(base - 0.02, rel=0.01)

        # Large corp (100m) — no adjustment
        assert correlations[2] == pytest.approx(base)

    def test_b31_sme_boundary_43_66m_vs_44m(self) -> None:
        """GBP 43.66m is below B31 threshold (44m) but was above old EUR-converted threshold.

        Under the old code: GBP 43.66m / 0.8732 ≈ EUR 50m → no adjustment.
        Under B31: GBP 43.66m < GBP 44m → gets SME adjustment.
        This is the boundary case the fix corrects.
        """
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE", is_b31=True)
        boundary_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=43.66, is_b31=True
        )
        # Should get a small but non-zero adjustment
        # s = max(4.4, min(43.66, 44)) = 43.66
        # adjustment = 0.04 × (1 - (43.66 - 4.4) / 39.6) ≈ 0.04 × 0.00859 ≈ 0.000344
        assert boundary_corr < base_corr
        expected_adj = 0.04 * (1.0 - (43.66 - 4.4) / 39.6)
        assert base_corr - boundary_corr == pytest.approx(expected_adj, rel=0.01)
