"""
CRR Group I: Defaulted Exposure IRB Treatment Acceptance Tests.

These tests validate the production calculator correctly handles defaulted
exposures under IRB, bypassing the Vasicek formula per CRR Art. 153(1)(ii)
and Art. 154(1)(i).

Key rules:
- F-IRB defaulted: K=0, RW=0 (capital requirement addressed via provisions)
- A-IRB defaulted: K = max(0, LGD_in_default - BEEL)
- No Vasicek correlation or maturity adjustment for defaulted exposures
- CRR 1.06 scaling applies to non-retail (even when defaulted)

Regulatory References:
- CRR Art. 153(1)(ii): Defaulted non-retail IRB risk weights
- CRR Art. 154(1)(i): Defaulted retail IRB risk weights
- Basel CRE31.3: Treatment of defaulted exposures
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ExposureClass, ApproachType
from rwa_calc.engine.irb import IRBLazyFrame  # noqa: F401 - registers namespace


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR config with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


def _build_defaulted_exposure(
    *,
    exposure_ref: str,
    exposure_class: str,
    approach: str,
    is_airb: bool,
    lgd: float,
    beel: float,
    ead_final: float,
    maturity: float = 2.5,
) -> pl.LazyFrame:
    """Build a single defaulted exposure for acceptance testing."""
    return pl.LazyFrame({
        "exposure_reference": [exposure_ref],
        "counterparty_reference": [f"CP_{exposure_ref}"],
        "pd": [1.0],  # Defaulted = PD 100%
        "lgd": [lgd],
        "beel": [beel],
        "ead_final": [ead_final],
        "exposure_class": [exposure_class],
        "maturity": [maturity],
        "approach": [approach],
        "is_airb": [is_airb],
        "is_defaulted": [True],
    })


# =============================================================================
# CRR-I1: F-IRB Corporate Defaulted
# =============================================================================


class TestCRRI1_FIRBCorporateDefaulted:
    """
    CRR-I1: F-IRB corporate defaulted exposure.

    Input: Corporate loan, PD=100%, supervisory LGD=45%, EAD=500,000
    Expected: K=0, RW=0%, RWA=0, EL = LGD × EAD = 225,000
    """

    def test_crr_i1_k_is_zero(self, crr_irb_config: CalculationConfig) -> None:
        """F-IRB defaulted corporate: K=0."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I1_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)

    def test_crr_i1_rwa_is_zero(self, crr_irb_config: CalculationConfig) -> None:
        """F-IRB defaulted corporate: RWA=0."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I1_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-6)
        assert result["risk_weight"][0] == pytest.approx(0.0, abs=1e-6)

    def test_crr_i1_expected_loss(self, crr_irb_config: CalculationConfig) -> None:
        """F-IRB defaulted corporate: EL = LGD × EAD = 0.45 × 500,000 = 225,000."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I1_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(225_000.0, rel=1e-6)


# =============================================================================
# CRR-I2: A-IRB Retail Defaulted
# =============================================================================


class TestCRRI2_AIRBRetailDefaulted:
    """
    CRR-I2: A-IRB retail defaulted exposure.

    Input: Retail loan, PD=100%, LGD_in_default=65%, BEEL=50%, EAD=25,000
    Expected: K=max(0, 0.65-0.50)=0.15, RWA=0.15×12.5×1.0×25,000=46,875
              EL = BEEL × EAD = 0.50 × 25,000 = 12,500
    """

    def test_crr_i2_k_lgd_minus_beel(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB retail defaulted: K = max(0, 0.65 - 0.50) = 0.15."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I2_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.15, abs=1e-10)

    def test_crr_i2_rwa(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB retail defaulted CRR: RWA = 0.15 × 12.5 × 1.0 × 25,000 = 46,875."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I2_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        expected_rwa = 0.15 * 12.5 * 1.0 * 25_000.0  # 46,875
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_crr_i2_expected_loss(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB retail defaulted: EL = BEEL × EAD = 0.50 × 25,000 = 12,500."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I2_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(12_500.0, rel=1e-6)


# =============================================================================
# CRR-I3: A-IRB Corporate Defaulted with CRR Scaling
# =============================================================================


class TestCRRI3_AIRBCorporateDefaultedCRRScaling:
    """
    CRR-I3: A-IRB corporate defaulted exposure with CRR 1.06 scaling.

    Input: Corporate loan, PD=100%, LGD_in_default=60%, BEEL=45%, EAD=500,000
    Expected: K=max(0, 0.60-0.45)=0.15,
              RWA = 0.15 × 12.5 × 1.06 × 500,000 = 993,750
              EL = BEEL × EAD = 0.45 × 500,000 = 225,000
    """

    def test_crr_i3_k(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB corporate defaulted: K = 0.15."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I3_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.15, abs=1e-10)

    def test_crr_i3_rwa_with_scaling(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB corporate defaulted CRR: RWA = 0.15 × 12.5 × 1.06 × 500,000 = 993,750."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I3_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        expected_rwa = 0.15 * 12.5 * 1.06 * 500_000.0  # 993,750
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_crr_i3_expected_loss(self, crr_irb_config: CalculationConfig) -> None:
        """A-IRB corporate defaulted: EL = BEEL × EAD = 0.45 × 500,000 = 225,000."""
        lf = _build_defaulted_exposure(
            exposure_ref="CRR_I3_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (lf
            .irb.prepare_columns(crr_irb_config)
            .irb.apply_all_formulas(crr_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(225_000.0, rel=1e-6)
