"""Unit tests for base_currency forwarding in CreditRiskCalc._create_config().

Covers P6.20: CreditRiskCalc.base_currency must be forwarded through
_create_config() into CalculationConfig.base_currency.

Currently CalculationConfig.crr() and CalculationConfig.basel_3_1() both
hardcode base_currency="GBP", and _create_config() does not pass the value
through — so the forwarding tests (EUR/USD) fail until the engine is fixed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rwa_calc.api.service import CreditRiskCalc
from rwa_calc.contracts.config import CalculationConfig

# =============================================================================
# CreditRiskCalc._create_config() forwarding tests
# =============================================================================


def test_credit_risk_calc_forwards_base_currency_eur_for_crr(tmp_path: Path) -> None:
    """_create_config() must propagate base_currency='EUR' into CalculationConfig for CRR."""
    # Arrange
    calc = CreditRiskCalc(
        data_path=tmp_path,
        framework="CRR",
        reporting_date=date(2024, 12, 31),
        base_currency="EUR",
    )

    # Act
    config = calc._create_config()

    # Assert
    assert config.base_currency == "EUR"


def test_credit_risk_calc_forwards_base_currency_usd_for_basel_3_1(tmp_path: Path) -> None:
    """_create_config() must propagate base_currency='USD' into CalculationConfig for Basel 3.1."""
    # Arrange
    calc = CreditRiskCalc(
        data_path=tmp_path,
        framework="BASEL_3_1",
        reporting_date=date(2027, 1, 1),
        base_currency="USD",
    )

    # Act
    config = calc._create_config()

    # Assert
    assert config.base_currency == "USD"


def test_credit_risk_calc_default_base_currency_is_gbp(tmp_path: Path) -> None:
    """When base_currency is not supplied, _create_config() must produce 'GBP'."""
    # Arrange
    calc = CreditRiskCalc(
        data_path=tmp_path,
        framework="CRR",
        reporting_date=date(2024, 12, 31),
    )

    # Act
    config = calc._create_config()

    # Assert
    assert config.base_currency == "GBP"


# =============================================================================
# CalculationConfig factory-method default tests
# =============================================================================


def test_calculation_config_crr_factory_default_base_currency_is_gbp() -> None:
    """CalculationConfig.crr() must default base_currency to 'GBP'."""
    # Arrange / Act
    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

    # Assert
    assert config.base_currency == "GBP"


def test_calculation_config_basel_3_1_factory_default_base_currency_is_gbp() -> None:
    """CalculationConfig.basel_3_1() must default base_currency to 'GBP'."""
    # Arrange / Act
    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

    # Assert
    assert config.base_currency == "GBP"
