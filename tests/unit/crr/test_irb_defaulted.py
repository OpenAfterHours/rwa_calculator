"""Unit tests for IRB defaulted exposure treatment.

Tests cover:
- K calculation: F-IRB K=0, A-IRB K=max(0, LGD-BEEL)
- RWA calculation: scaling, no correlation, no maturity adjustment
- Expected loss: F-IRB EL=LGD*EAD, A-IRB EL=BEEL*EAD
- Pipeline integration: mixed defaulted+performing, missing columns
- BEEL column flow through hierarchy

References:
- CRR Art. 153(1)(ii): Defaulted non-retail exposures
- CRR Art. 154(1)(i): Defaulted retail exposures
- Basel CRE31.3: Defaulted exposure treatment
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb import IRBLazyFrame, IRBExpr  # noqa: F401
from rwa_calc.engine.irb.formulas import apply_irb_formulas


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _make_defaulted_lf(
    *,
    exposure_class: str = "CORPORATE",
    approach: str = "foundation_irb",
    is_airb: bool = False,
    lgd: float = 0.45,
    beel: float = 0.0,
    ead_final: float = 500_000.0,
    pd: float = 1.0,
    maturity: float = 2.5,
    is_defaulted: bool = True,
) -> pl.LazyFrame:
    """Create a single-row defaulted exposure LazyFrame."""
    return pl.LazyFrame({
        "exposure_reference": ["DEF001"],
        "pd": [pd],
        "lgd": [lgd],
        "ead_final": [ead_final],
        "exposure_class": [exposure_class],
        "maturity": [maturity],
        "approach": [approach],
        "is_airb": [is_airb],
        "is_defaulted": [is_defaulted],
        "beel": [beel],
    })


# =============================================================================
# TestDefaultedK
# =============================================================================


class TestDefaultedK:
    """Test capital requirement (K) for defaulted exposures."""

    def test_firb_k_is_zero(self, crr_config: CalculationConfig) -> None:
        """F-IRB defaulted: K=0."""
        lf = _make_defaulted_lf(approach="foundation_irb", is_airb=False, lgd=0.45, beel=0.0)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)

    def test_airb_k_lgd_minus_beel(self, crr_config: CalculationConfig) -> None:
        """A-IRB defaulted: K = max(0, LGD - BEEL) = max(0, 0.65 - 0.50) = 0.15."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.65, beel=0.50, exposure_class="RETAIL_OTHER",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.15, abs=1e-10)

    def test_airb_k_floored_at_zero_when_beel_exceeds_lgd(self, crr_config: CalculationConfig) -> None:
        """A-IRB defaulted: K floored at 0 when BEEL > LGD."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.40, beel=0.55, exposure_class="RETAIL_OTHER",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)

    def test_airb_k_with_zero_beel(self, crr_config: CalculationConfig) -> None:
        """A-IRB defaulted with BEEL=0: K = LGD."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.60, beel=0.0, exposure_class="CORPORATE",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.60, abs=1e-10)


# =============================================================================
# TestDefaultedRWA
# =============================================================================


class TestDefaultedRWA:
    """Test RWA calculation for defaulted exposures."""

    def test_firb_rwa_is_zero(self, crr_config: CalculationConfig) -> None:
        """F-IRB defaulted: RWA=0."""
        lf = _make_defaulted_lf(approach="foundation_irb", is_airb=False, ead_final=500_000.0)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-6)
        assert result["risk_weight"][0] == pytest.approx(0.0, abs=1e-6)

    def test_airb_retail_rwa_no_scaling(self, crr_config: CalculationConfig) -> None:
        """A-IRB retail defaulted CRR: no 1.06 scaling (retail never gets scaling)."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.65, beel=0.50, ead_final=25_000.0,
            exposure_class="RETAIL_OTHER",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # K=0.15, scaling=1.0 (retail), RWA = 0.15 * 12.5 * 1.0 * 25000 = 46,875
        expected_rwa = 0.15 * 12.5 * 1.0 * 25_000.0
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_airb_corporate_rwa_crr_scaling(self, crr_config: CalculationConfig) -> None:
        """A-IRB corporate defaulted CRR: 1.06 scaling applies."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.60, beel=0.45, ead_final=500_000.0,
            exposure_class="CORPORATE",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # K=0.15, scaling=1.06, RWA = 0.15 * 12.5 * 1.06 * 500000 = 993,750
        expected_rwa = 0.15 * 12.5 * 1.06 * 500_000.0
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_airb_corporate_rwa_basel31_no_scaling(self, basel31_config: CalculationConfig) -> None:
        """A-IRB corporate defaulted Basel 3.1: no scaling."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.60, beel=0.45, ead_final=500_000.0,
            exposure_class="CORPORATE",
        )
        result = (lf
            .irb.prepare_columns(basel31_config)
            .irb.apply_all_formulas(basel31_config)
            .collect()
        )
        # K=0.15, scaling=1.0 (Basel 3.1), RWA = 0.15 * 12.5 * 1.0 * 500000 = 937,500
        expected_rwa = 0.15 * 12.5 * 1.0 * 500_000.0
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_defaulted_correlation_is_zero(self, crr_config: CalculationConfig) -> None:
        """Defaulted exposures bypass Vasicek: correlation=0."""
        lf = _make_defaulted_lf(approach="foundation_irb", is_airb=False)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["correlation"][0] == pytest.approx(0.0, abs=1e-10)

    def test_defaulted_maturity_adjustment_is_one(self, crr_config: CalculationConfig) -> None:
        """Defaulted exposures: maturity adjustment=1.0 (not applicable)."""
        lf = _make_defaulted_lf(approach="foundation_irb", is_airb=False)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["maturity_adjustment"][0] == pytest.approx(1.0, abs=1e-10)


# =============================================================================
# TestDefaultedExpectedLoss
# =============================================================================


class TestDefaultedExpectedLoss:
    """Test expected loss for defaulted exposures."""

    def test_firb_el_lgd_times_ead(self, crr_config: CalculationConfig) -> None:
        """F-IRB defaulted: EL = LGD × EAD."""
        lf = _make_defaulted_lf(
            approach="foundation_irb", is_airb=False,
            lgd=0.45, ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # lgd_floored = 0.45 (CRR no LGD floor), EL = 0.45 * 500000 = 225,000
        assert result["expected_loss"][0] == pytest.approx(0.45 * 500_000.0, rel=1e-6)

    def test_airb_el_beel_times_ead(self, crr_config: CalculationConfig) -> None:
        """A-IRB defaulted: EL = BEEL × EAD."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.65, beel=0.50, ead_final=25_000.0,
            exposure_class="RETAIL_OTHER",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # EL = BEEL * EAD = 0.50 * 25000 = 12,500
        assert result["expected_loss"][0] == pytest.approx(0.50 * 25_000.0, rel=1e-6)


# =============================================================================
# TestDefaultedPipeline
# =============================================================================


class TestDefaultedPipeline:
    """Test defaulted treatment in mixed pipelines."""

    def test_mixed_defaulted_and_performing(self, crr_config: CalculationConfig) -> None:
        """Mixed rows: defaulted rows get treatment, performing rows unchanged."""
        lf = pl.LazyFrame({
            "exposure_reference": ["PERF001", "DEF001"],
            "pd": [0.01, 1.0],
            "lgd": [0.45, 0.45],
            "ead_final": [1_000_000.0, 500_000.0],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "maturity": [2.5, 2.5],
            "approach": ["foundation_irb", "foundation_irb"],
            "is_airb": [False, False],
            "is_defaulted": [False, True],
            "beel": [0.0, 0.0],
        })
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # Performing row should have non-zero K
        assert result["k"][0] > 0.0
        assert result["rwa"][0] > 0.0

        # Defaulted F-IRB row should have K=0, RWA=0
        assert result["k"][1] == pytest.approx(0.0, abs=1e-10)
        assert result["rwa"][1] == pytest.approx(0.0, abs=1e-6)

    def test_missing_is_defaulted_column_is_noop(self, crr_config: CalculationConfig) -> None:
        """No is_defaulted column → defaulted treatment is a no-op."""
        lf = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "approach": ["foundation_irb"],
        })
        # Should run without errors (prepare_columns adds is_defaulted=False)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        assert result["k"][0] > 0.0
        assert result["rwa"][0] > 0.0

    def test_missing_beel_column_defaults_to_zero(self, crr_config: CalculationConfig) -> None:
        """Missing beel column defaults to 0.0."""
        lf = pl.LazyFrame({
            "exposure_reference": ["DEF001"],
            "pd": [1.0],
            "lgd": [0.45],
            "ead_final": [500_000.0],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "approach": ["advanced_irb"],
            "is_airb": [True],
            "is_defaulted": [True],
        })
        # prepare_columns adds beel=0.0
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )
        # A-IRB with BEEL=0: K = max(0, 0.45 - 0) = 0.45
        assert result["k"][0] == pytest.approx(0.45, abs=1e-10)

    def test_apply_irb_formulas_standalone_with_defaulted(self, crr_config: CalculationConfig) -> None:
        """apply_irb_formulas() standalone function also handles defaulted rows."""
        lf = pl.LazyFrame({
            "exposure_reference": ["DEF001"],
            "pd": [1.0],
            "lgd": [0.45],
            "ead_final": [500_000.0],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "is_airb": [False],
            "is_defaulted": [True],
            "beel": [0.0],
        })
        result = apply_irb_formulas(lf, crr_config).collect()
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-6)


# =============================================================================
# TestDefaultedAudit
# =============================================================================


class TestDefaultedAudit:
    """Test audit trail for defaulted exposures."""

    def test_firb_defaulted_audit_string(self, crr_config: CalculationConfig) -> None:
        """F-IRB defaulted audit string indicates K=0."""
        lf = _make_defaulted_lf(approach="foundation_irb", is_airb=False)
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .irb.build_audit()
            .collect()
        )
        audit_str = result["irb_calculation"][0]
        assert "DEFAULTED" in audit_str
        assert "F-IRB" in audit_str

    def test_airb_defaulted_audit_string(self, crr_config: CalculationConfig) -> None:
        """A-IRB defaulted audit string shows K=max(0, LGD-BEEL)."""
        lf = _make_defaulted_lf(
            approach="advanced_irb", is_airb=True,
            lgd=0.65, beel=0.50, exposure_class="RETAIL_OTHER",
        )
        result = (lf
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .irb.build_audit()
            .collect()
        )
        audit_str = result["irb_calculation"][0]
        assert "DEFAULTED" in audit_str
        assert "A-IRB" in audit_str
        assert "BEEL" in audit_str
