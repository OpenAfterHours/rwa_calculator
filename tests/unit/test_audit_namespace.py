"""Unit tests for the Audit Polars namespace.

Tests cover:
- Namespace registration and availability
- Expression formatting (currency, percent, ratio)
- SA calculation audit string
- IRB calculation audit string
- Slotting calculation audit string
- CRM calculation audit string
- Haircut calculation audit string
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine import AuditExpr, AuditLazyFrame  # noqa: F401

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sa_data() -> pl.LazyFrame:
    """Return SA calculation data."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "ead_final": [1_000_000.0],
            "risk_weight": [0.50],
            "supporting_factor": [0.7619],
            "rwa_pre_factor": [500_000.0],
            "rwa_post_factor": [380_950.0],
        }
    )


@pytest.fixture
def irb_data() -> pl.LazyFrame:
    """Return IRB calculation data."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "ead_final": [1_000_000.0],
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "correlation": [0.19],
            "k": [0.05],
            "maturity_adjustment": [1.2],
            "rwa": [700_000.0],
        }
    )


@pytest.fixture
def slotting_data() -> pl.LazyFrame:
    """Return slotting calculation data."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "slotting_category": ["satisfactory"],
            "is_hvcre": [False],
            "risk_weight": [1.15],
            "rwa": [1_150_000.0],
        }
    )


@pytest.fixture
def crm_data() -> pl.LazyFrame:
    """Return CRM/EAD calculation data."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "ead_gross": [1_000_000.0],
            "collateral_adjusted_value": [200_000.0],
            "guarantee_amount": [300_000.0],
            "provision_allocated": [50_000.0],
            "ead_final": [450_000.0],
        }
    )


@pytest.fixture
def haircut_data() -> pl.LazyFrame:
    """Return haircut calculation data."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001"],
            "market_value": [100_000.0],
            "collateral_haircut": [0.10],
            "fx_haircut": [0.08],
            "value_after_haircut": [82_000.0],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestAuditNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, sa_data: pl.LazyFrame) -> None:
        """LazyFrame should have .audit namespace available."""
        assert hasattr(sa_data, "audit")

    def test_expr_namespace_registered(self) -> None:
        """Expression should have .audit namespace available."""
        expr = pl.col("ead")
        assert hasattr(expr, "audit")

    def test_lazyframe_methods_available(self, sa_data: pl.LazyFrame) -> None:
        """LazyFrame namespace should have expected methods."""
        audit = sa_data.audit
        expected_methods = [
            "build_sa_calculation",
            "build_irb_calculation",
            "build_slotting_calculation",
            "build_crm_calculation",
            "build_haircut_calculation",
            "build_floor_calculation",
        ]
        for method in expected_methods:
            assert hasattr(audit, method), f"Missing method: {method}"

    def test_expr_methods_available(self) -> None:
        """Expression namespace should have expected methods."""
        audit = pl.col("value").audit
        expected_methods = [
            "format_currency",
            "format_percent",
            "format_ratio",
            "format_bps",
        ]
        for method in expected_methods:
            assert hasattr(audit, method), f"Missing method: {method}"


# =============================================================================
# Expression Formatting Tests
# =============================================================================


class TestExprFormatCurrency:
    """Tests for currency formatting."""

    def test_format_currency_integer(self) -> None:
        """Should format as integer string."""
        df = pl.DataFrame({"value": [1_000_000.0]})
        result = df.with_columns(pl.col("value").audit.format_currency().alias("formatted"))
        assert result["formatted"][0] == "1000000.0"

    def test_format_currency_no_decimals(self) -> None:
        """Should round to specified decimals."""
        df = pl.DataFrame({"value": [1_234_567.89]})
        result = df.with_columns(
            pl.col("value").audit.format_currency(decimals=0).alias("formatted")
        )
        assert result["formatted"][0] == "1234568.0"


class TestExprFormatPercent:
    """Tests for percentage formatting."""

    def test_format_percent_default(self) -> None:
        """Should format as percentage with 1 decimal."""
        df = pl.DataFrame({"value": [0.50]})
        result = df.with_columns(pl.col("value").audit.format_percent().alias("formatted"))
        assert result["formatted"][0] == "50.0%"

    def test_format_percent_more_decimals(self) -> None:
        """Should format with specified decimals."""
        df = pl.DataFrame({"value": [0.7619]})
        result = df.with_columns(
            pl.col("value").audit.format_percent(decimals=2).alias("formatted")
        )
        assert result["formatted"][0] == "76.19%"


class TestExprFormatRatio:
    """Tests for ratio formatting."""

    def test_format_ratio_default(self) -> None:
        """Should format as ratio with 3 decimals."""
        df = pl.DataFrame({"value": [0.123456]})
        result = df.with_columns(pl.col("value").audit.format_ratio().alias("formatted"))
        assert result["formatted"][0] == "0.123"


class TestExprFormatBps:
    """Tests for basis points formatting."""

    def test_format_bps(self) -> None:
        """Should format as basis points."""
        df = pl.DataFrame({"value": [0.015]})  # 1.5% = 150 bps
        result = df.with_columns(pl.col("value").audit.format_bps().alias("formatted"))
        assert result["formatted"][0] == "150.0 bps"


# =============================================================================
# SA Audit Tests
# =============================================================================


class TestBuildSACalculation:
    """Tests for SA calculation audit string."""

    def test_sa_calculation_with_supporting_factor(self, sa_data: pl.LazyFrame) -> None:
        """Should build SA calculation string with supporting factor."""
        result = sa_data.audit.build_sa_calculation().collect()

        assert "sa_calculation" in result.columns
        calc_str = result["sa_calculation"][0]

        assert "SA:" in calc_str
        assert "EAD=" in calc_str
        assert "RW=" in calc_str
        assert "SF=" in calc_str
        assert "RWA=" in calc_str

    def test_sa_calculation_without_supporting_factor(self) -> None:
        """Should build SA calculation string without supporting factor."""
        data = pl.LazyFrame(
            {
                "ead_final": [1_000_000.0],
                "risk_weight": [0.50],
                "rwa_pre_factor": [500_000.0],
            }
        )

        result = data.audit.build_sa_calculation().collect()
        calc_str = result["sa_calculation"][0]

        assert "SA:" in calc_str
        assert "EAD=" in calc_str
        assert "RW=" in calc_str


# =============================================================================
# IRB Audit Tests
# =============================================================================


class TestBuildIRBCalculation:
    """Tests for IRB calculation audit string."""

    def test_irb_calculation_full(self, irb_data: pl.LazyFrame) -> None:
        """Should build full IRB calculation string."""
        result = irb_data.audit.build_irb_calculation().collect()

        assert "irb_calculation" in result.columns
        calc_str = result["irb_calculation"][0]

        assert "IRB:" in calc_str
        assert "PD=" in calc_str
        assert "LGD=" in calc_str
        assert "R=" in calc_str
        assert "K=" in calc_str
        assert "MA=" in calc_str
        assert "RWA=" in calc_str


# =============================================================================
# Slotting Audit Tests
# =============================================================================


class TestBuildSlottingCalculation:
    """Tests for slotting calculation audit string."""

    def test_slotting_calculation(self, slotting_data: pl.LazyFrame) -> None:
        """Should build slotting calculation string."""
        result = slotting_data.audit.build_slotting_calculation().collect()

        assert "slotting_calculation" in result.columns
        calc_str = result["slotting_calculation"][0]

        assert "Slotting:" in calc_str
        assert "Category=" in calc_str
        assert "RW=" in calc_str
        assert "RWA=" in calc_str

    def test_slotting_calculation_hvcre(self) -> None:
        """Should include HVCRE marker when applicable."""
        data = pl.LazyFrame(
            {
                "slotting_category": ["strong"],
                "is_hvcre": [True],
                "risk_weight": [0.70],
                "rwa": [700_000.0],
            }
        )

        result = data.audit.build_slotting_calculation().collect()
        calc_str = result["slotting_calculation"][0]

        assert "(HVCRE)" in calc_str


# =============================================================================
# CRM Audit Tests
# =============================================================================


class TestBuildCRMCalculation:
    """Tests for CRM calculation audit string."""

    def test_crm_calculation(self, crm_data: pl.LazyFrame) -> None:
        """Should build CRM calculation string."""
        result = crm_data.audit.build_crm_calculation().collect()

        assert "crm_calculation" in result.columns
        calc_str = result["crm_calculation"][0]

        assert "EAD:" in calc_str
        assert "gross=" in calc_str
        assert "coll=" in calc_str
        assert "guar=" in calc_str
        assert "prov=" in calc_str
        assert "final=" in calc_str


# =============================================================================
# Haircut Audit Tests
# =============================================================================


class TestBuildHaircutCalculation:
    """Tests for haircut calculation audit string."""

    def test_haircut_calculation(self, haircut_data: pl.LazyFrame) -> None:
        """Should build haircut calculation string."""
        result = haircut_data.audit.build_haircut_calculation().collect()

        assert "haircut_calculation" in result.columns
        calc_str = result["haircut_calculation"][0]

        assert "MV=" in calc_str
        assert "Hc=" in calc_str
        assert "Hfx=" in calc_str
        assert "Adj=" in calc_str
