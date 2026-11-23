"""
P5.61: the CRR Art. 155(3) PD/LGD equity election is a ``CalculationConfig.crr()`` keyword.

Rule text
---------
CRR Art. 155(1) (legislation.gov.uk, onshored): "Institutions shall determine
their risk-weighted exposure amounts for equity exposures ... in accordance with
the approaches set out in paragraphs 2, 3 and 4 of this Article. An institution
may apply different approaches to different equity portfolios where the
institution itself uses different approaches for internal risk management
purposes." Art. 155(3): "Under the PD/LGD approach, risk-weighted exposure
amounts shall be calculated according to the formulas in Article 153(1). ... For
these purposes M shall be five years."

The choice between Art. 155(2) and Art. 155(3) is a firm election, like the
Art. 153(3) double-default and Art. 162(1) fixed-maturity elections that
``crr()`` already takes as keywords. Before P5.61 the factory had no
``equity_pd_lgd`` keyword, so a factory user could reach the PD/LGD approach
only through ``dataclasses.replace`` - and ``replace(..., permission_mode=IRB)``
on an SA-built config keeps the SA-only ``irb_permissions`` map, which silently
routes the equity book to Art. 133.

Regime scope: CRR only. PS1/26 Art. 155(1)-(4) are "[Note: Provision left
blank]", so ``basel_3_1()`` takes no such keyword here. The firm's legacy
Art. 155 method does stay capital-relevant in 2027-2029 as the PS1/26 Credit
Risk: General Provisions rule 4.6(1) input; that half is P1.389's, not this
item's.

Hand calculation (exchange-traded equity, EAD 1,000,000; P1.153 / CRR-J21):
    Art. 155(3) PD/LGD:  RW 1.918731, RWA 1,918,731
    Art. 155(2) simple:  RW 2.90,     RWA 2,900,000   (default, no election)
    Art. 133 SA:         RW 1.00,     RWA 1,000,000   (no F-IRB / A-IRB permission)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_153.p1_153 import EXPECTED_RISK_WEIGHT, EXPECTED_RWA

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import EquityApproach, PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator

_REPORTING_DATE = date(2026, 6, 30)
_EAD = 1_000_000.0


def _crr(permission_mode: PermissionMode, *, equity_pd_lgd: bool) -> CalculationConfig:
    """A CRR config built through the public factory only - never ``dataclasses.replace``."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=permission_mode,
        equity_pd_lgd=equity_pd_lgd,
    )


def _exchange_traded_leg(config: CalculationConfig) -> dict:
    """The P1.153 exchange-traded equity leg through ``EquityCalculator.calculate_branch``."""
    frame = pl.LazyFrame(
        {
            "exposure_reference": ["EQ-P5-61"],
            "counterparty_reference": ["CP-P5-61"],
            "equity_type": ["exchange_traded"],
            "is_exchange_traded": [True],
            "ead_final": [_EAD],
            "is_speculative": [False],
            "is_government_supported": [False],
            "is_diversified_portfolio": [False],
            "has_default_definition_info": [True],
        }
    )
    return EquityCalculator().calculate_branch(frame, config).collect().row(0, named=True)


class TestCrrFactoryEquityPdLgdKeyword:
    """``CalculationConfig.crr(equity_pd_lgd=...)`` reaches the Art. 155(3) approach."""

    def test_factory_keyword_sets_the_election(self) -> None:
        # Arrange / Act
        config = _crr(PermissionMode.IRB, equity_pd_lgd=True)

        # Assert
        assert config.equity_pd_lgd is True

    def test_factory_default_leaves_the_election_off(self) -> None:
        # Arrange / Act
        config = CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )

        # Assert
        assert config.equity_pd_lgd is False

    @pytest.mark.parametrize(
        ("permission_mode", "equity_pd_lgd", "expected"),
        [
            (PermissionMode.IRB, True, EquityApproach.PD_LGD),
            (PermissionMode.IRB, False, EquityApproach.IRB_SIMPLE),
            (PermissionMode.STANDARDISED, True, EquityApproach.SA),
        ],
        ids=["irb-elected-pd_lgd", "irb-default-irb_simple", "sa_only-elected-stays_sa"],
    )
    def test_factory_built_config_routes_equity_approach(
        self,
        permission_mode: PermissionMode,
        equity_pd_lgd: bool,
        expected: EquityApproach,
    ) -> None:
        # Arrange
        config = _crr(permission_mode, equity_pd_lgd=equity_pd_lgd)

        # Act
        approach = EquityCalculator()._determine_approach(config)

        # Assert
        assert approach is expected

    @pytest.mark.parametrize(
        ("permission_mode", "equity_pd_lgd", "expected_rw", "expected_rwa", "expected_method"),
        [
            (PermissionMode.IRB, True, EXPECTED_RISK_WEIGHT, EXPECTED_RWA, "pd_lgd"),
            (PermissionMode.IRB, False, 2.90, 2_900_000.0, "irb_simple"),
            (PermissionMode.STANDARDISED, True, 1.00, 1_000_000.0, "sa"),
        ],
        ids=["irb-elected-pd_lgd", "irb-default-irb_simple", "sa_only-elected-stays_sa"],
    )
    def test_factory_built_config_weights_exchange_traded_equity(
        self,
        permission_mode: PermissionMode,
        equity_pd_lgd: bool,
        expected_rw: float,
        expected_rwa: float,
        expected_method: str,
    ) -> None:
        # Arrange
        config = _crr(permission_mode, equity_pd_lgd=equity_pd_lgd)

        # Act
        row = _exchange_traded_leg(config)

        # Assert
        assert row["equity_method"] == expected_method
        assert row["risk_weight"] == pytest.approx(expected_rw, rel=1e-6)
        assert row["rwa"] == pytest.approx(expected_rwa, rel=1e-6)
