"""
IV-05: CIU look-through weights each underlying by its class, not a flat 100%.

What this pins
--------------
``EquityCalculator._resolve_look_through_rw`` joined every holding to the
(exposure_class, CQS) table and filled every miss with a flat 100%. Classes the
table cannot price therefore took 100% whatever they were:

- a nested CIU (``ciu``) -- a level-2 CIU with no look-through data of its own;
- a Basel 3.1 ``high_risk`` item;
- any value outside the ``ExposureClass`` vocabulary (``securitisation``,
  ``subordinated_debt``, a typo, a null) -- an underlying the engine cannot
  identify and so cannot weight "as if directly held".

Rule text (PS1/26 Appendix 1, ps126app1.pdf pp.62-64; the Art. 132 note reads
"This rule corresponds to Article 132 of CRR as it applied immediately before
revocation by the Treasury", so the CRR-firm text in the PRA Rulebook is the
same):

- Art. 132A(1): "an institution that has sufficient information about the
  individual underlying exposures of a CIU shall look through to those
  exposures to calculate the risk-weighted exposure amount of the CIU, risk
  weighting all underlying exposures of the CIU as if they were directly held
  by the institution."
- Art. 132(5): "... any of the underlying exposures of the level 1 CIU is an
  exposure in the form of units or shares in another CIU ('level 2 CIU'), the
  risk-weighted exposure amount of the level 2 CIU's exposures may be
  calculated by using any of the three approaches described in paragraph 2.
  ... In any other scenario it shall use the fall-back approach."
- Art. 132(2): "an institution that does not apply the look-through approach
  or the mandate-based approach shall assign a risk weight of 1,250%
  ('fall-back approach')" and "may calculate the risk-weighted exposure amount
  ... by using a combination of the approaches referred to in this paragraph".
- Art. 128(1) (Basel 3.1): "An institution shall assign a 150% risk weight to
  exposures that are associated with particularly high risk." UK CRR Art. 128
  was omitted by SI 2021/1078, so a CRR ``high_risk`` holding keeps 100%.

Orchestrator decision (binding): nested CIU holdings with no further
look-through data take 1,250% in both regimes; Basel 3.1 ``high_risk`` 150%,
CRR ``high_risk`` 100%; a class outside the ``ExposureClass`` vocabulary takes
1,250% (with an SA008 warning, asserted at pipeline level in
``tests/integration/test_ciu_look_through_holding_classes.py``). Retail / real
estate holdings keep 100% (an overstatement, out of scope).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.equity import EquityCalculator
from tests.fixtures.resolved_bundle import make_crm_bundle

_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
# 2030: past the PS1/26 rules 4.1-4.3 transitional, so no equity higher-of.
_B31 = CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))

_FALLBACK = 12.50


def _fund_rw(
    config: CalculationConfig, holdings: list[tuple[str | None, int | None, float]]
) -> float:
    """Look-through RW of a one-fund CIU holding the given (class, cqs, value) rows."""
    equity = pl.LazyFrame(
        {
            "exposure_reference": ["CIU_1"],
            "ead_final": [100.0],
            "equity_type": ["ciu"],
            "ciu_approach": ["look_through"],
            "fund_reference": ["FUND_A"],
        }
    )
    ciu_holdings = pl.LazyFrame(
        {
            "fund_reference": ["FUND_A"] * len(holdings),
            "holding_reference": [f"H{i}" for i in range(len(holdings))],
            "exposure_class": [cls for cls, _, _ in holdings],
            "cqs": [cqs for _, cqs, _ in holdings],
            "holding_value": [value for _, _, value in holdings],
        },
        schema_overrides={"exposure_class": pl.String, "cqs": pl.Int8},
    )
    bundle = make_crm_bundle(
        exposures=pl.LazyFrame(), equity_exposures=equity, ciu_holdings=ciu_holdings
    )
    result = EquityCalculator().get_equity_result_bundle(bundle, config)
    return result.results.collect().row(0, named=True)["risk_weight"]


class TestNestedCIUHoldingTakesFallBack:
    """Art. 132(5): a level-2 CIU with no look-through data of its own is 1,250%."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["CRR", "BASEL_3_1"])
    def test_nested_ciu_holding_is_1250(self, config: CalculationConfig) -> None:
        # Act
        rw = _fund_rw(config, [("ciu", None, 100.0)])

        # Assert (pre-fix: 1.00 in both regimes)
        assert rw == pytest.approx(_FALLBACK)

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["CRR", "BASEL_3_1"])
    def test_upper_case_nested_ciu_is_recognised(self, config: CalculationConfig) -> None:
        # Act
        rw = _fund_rw(config, [("CIU", None, 100.0)])

        # Assert
        assert rw == pytest.approx(_FALLBACK)

    def test_nested_ciu_combines_with_looked_through_holdings(self) -> None:
        """Art. 132(2) combination: 50 corporate CQS1 (20%) + 50 nested CIU (1,250%).

        (50 x 0.20 + 50 x 12.50) / 100 = 6.35 under Basel 3.1.
        """
        # Act
        rw = _fund_rw(_B31, [("corporate", 1, 50.0), ("ciu", None, 50.0)])

        # Assert
        assert rw == pytest.approx(6.35)


class TestHighRiskHolding:
    """Art. 128: 150% under Basel 3.1; the class does not exist in UK CRR."""

    def test_b31_high_risk_holding_is_150(self) -> None:
        # Act
        rw = _fund_rw(_B31, [("high_risk", None, 100.0)])

        # Assert (pre-fix: 1.00)
        assert rw == pytest.approx(1.50)

    def test_crr_high_risk_holding_stays_100(self) -> None:
        """UK CRR Art. 128 omitted by SI 2021/1078: a direct HIGH_RISK row is OTHER 100%."""
        # Act
        rw = _fund_rw(_CRR, [("high_risk", None, 100.0)])

        # Assert
        assert rw == pytest.approx(1.00)


class TestUnidentifiedUnderlyingTakesFallBack:
    """A class the engine cannot identify cannot be weighted as if directly held."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["CRR", "BASEL_3_1"])
    @pytest.mark.parametrize("cls", ["securitisation", "subordinated_debt", "corprate", None])
    def test_out_of_vocabulary_class_is_1250(
        self, config: CalculationConfig, cls: str | None
    ) -> None:
        # Act
        rw = _fund_rw(config, [(cls, None, 100.0)])

        # Assert (pre-fix: 1.00)
        assert rw == pytest.approx(_FALLBACK)


class TestUnchangedHoldingWeights:
    """The fix touches only the three cases above; these stay as they were."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["CRR", "BASEL_3_1"])
    def test_unrated_corporate_stays_100(self, config: CalculationConfig) -> None:
        # Act
        rw = _fund_rw(config, [("corporate", None, 100.0)])

        # Assert
        assert rw == pytest.approx(1.00)

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["CRR", "BASEL_3_1"])
    @pytest.mark.parametrize("cls", ["retail_other", "residential_mortgage", "other"])
    def test_in_vocabulary_unpriced_class_stays_100(
        self, config: CalculationConfig, cls: str
    ) -> None:
        """Retail / RE holdings are overstated at 100%; out of scope (decision)."""
        # Act
        rw = _fund_rw(config, [(cls, None, 100.0)])

        # Assert
        assert rw == pytest.approx(1.00)

    def test_b31_rated_corporate_still_uses_the_cqs_table(self) -> None:
        # Act
        rw = _fund_rw(_B31, [("CORPORATE", 5, 100.0)])

        # Assert
        assert rw == pytest.approx(1.50)
