"""
P1.247 — CRR Art. 158(7): equity IRB-Simple emits EL, excluded from Art. 159.

Two things are verified end-to-end:

1. Emission (Art. 158(7)): the Art. 155(2) simple risk-weight path emits an
   expected-loss amount ``EL rate x exposure value`` paired with the RW bucket —
   0.8% for exchange-traded/diversified-PE, 2.4% for all other equity.

2. Art. 159 exclusion (the regulatory crux): the equity simple-approach EL does
   NOT enter the EL-vs-provisions shortfall/excess machinery. UK CRR Art. 159
   subtracts only the ``Article 158(5), (6) and (10)`` EL amounts from provisions
   (verbatim, crr.pdf p.155); equity's 158(7)/(8)/(9) is excluded. Art. 155(2)
   likewise sets equity RWA = ``RW x exposure value`` with no EL gross-up
   (crr.pdf p.152). So adding an equity IRB-Simple row with a large EL alongside
   an IRB corporate book must leave the portfolio EL shortfall/excess unmoved.

Hand calculation:
    Exchange-traded equity: EAD = 200,000, RW = 2.90, EL = 0.008 x 200,000 = 1,600.
    Other equity:           EAD = 100,000, RW = 3.70, EL = 0.024 x 100,000 = 2,400.
    Art. 159 pool (corporate IRB only): EL 50,000 vs provisions 30,000
        -> shortfall 20,000 (CET1 deduction, Art. 36(1)(d)) — equity EL 2,400
        is NOT added to the 50,000, so the shortfall stays 20,000.

Regulatory Reference:
    CRR Art. 158(7): equity simple-approach EL rates (PRA Rulebook (CRR Firms);
      Art. 158 omitted from onshored CRR by SI 2021/1078).
    CRR Art. 159: EL-vs-provisions comparison limited to Art. 158(5),(6),(10).
    CRR Art. 155(2): simple risk-weight RWA = RW x exposure value.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_irb_branch, pad_sa_branch, pad_slotting_branch
from tests.fixtures.resolved_bundle import make_crm_bundle
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.equity.calculator import EquityCalculator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENARIO_ID = "P1.247"
EL_RATE_EXCHANGE_TRADED = 0.008
EL_RATE_OTHER = 0.024

_EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SA = pad_sa_branch(_EMPTY)
EMPTY_SLOTTING = pad_slotting_branch(_EMPTY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR IRB config routing equity through Art. 155 IRB Simple."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Equity calculator instance."""
    return EquityCalculator()


@pytest.fixture
def aggregator() -> OutputAggregator:
    """OutputAggregator instance."""
    return OutputAggregator()


# ---------------------------------------------------------------------------
# P1.247 — Art. 158(7) EL emission (end-to-end via calculate_branch)
# ---------------------------------------------------------------------------


class TestP1247_EquitySimpleELEmission:
    """The Art. 155(2) simple path emits the Art. 158(7) EL amount."""

    def test_exchange_traded_expected_loss_1600(
        self, equity_calculator: EquityCalculator, crr_irb_config: CalculationConfig
    ) -> None:
        """Exchange-traded (290% RW): EL = 0.8% x 200,000 = 1,600."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)
        assert result["expected_loss"] == pytest.approx(1_600.0), (
            f"{SCENARIO_ID}: EL = 0.8% x 200,000 = 1,600 (Art. 158(7)). "
            f"Got {result['expected_loss']}."
        )

    def test_other_equity_expected_loss_2400(
        self, equity_calculator: EquityCalculator, crr_irb_config: CalculationConfig
    ) -> None:
        """Other equity (370% RW): EL = 2.4% x 100,000 = 2,400."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="other",
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)
        assert result["expected_loss"] == pytest.approx(2_400.0), (
            f"{SCENARIO_ID}: EL = 2.4% x 100,000 = 2,400 (Art. 158(7)). "
            f"Got {result['expected_loss']}."
        )

    def test_simple_path_emits_expected_loss_column(
        self, equity_calculator: EquityCalculator, crr_irb_config: CalculationConfig
    ) -> None:
        """Regression sentinel: the simple path emits a non-null expected_loss
        (pre-fix engine emitted none — the Art. 158(7) amount was silently 0)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="other",
            config=crr_irb_config,
        )
        assert result.get("expected_loss") is not None, (
            f"{SCENARIO_ID} regression: IRB-Simple equity must emit expected_loss "
            "(Art. 158(7)). Pre-fix engine emitted no EL on the simple path."
        )


# ---------------------------------------------------------------------------
# P1.247 — Art. 159 exclusion (equity simple EL not in the shortfall pool)
# ---------------------------------------------------------------------------


class TestP1247_EquityELExcludedFromArt159:
    """Equity simple EL must not enter the Art. 159 EL-vs-provisions pool."""

    def _irb_corporate_shortfall_book(self) -> pl.LazyFrame:
        """IRB corporate book: EL 50,000 vs provisions 30,000 -> shortfall 20,000."""
        return pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["CORP-IRB-001"],
                    "exposure_class": ["CORPORATE"],
                    "approach_applied": ["FIRB"],
                    "ead_final": [5_000_000.0],
                    "risk_weight": [0.88],
                    "rwa": [4_400_000.0],
                    "rwa_final": [4_400_000.0],
                    "rwa_post_factor": [4_400_000.0],
                    "expected_loss": [50_000.0],
                    "provision_allocated": [30_000.0],
                    "el_shortfall": [20_000.0],
                    "el_excess": [0.0],
                }
            )
        )

    def _equity_bundle(self, equity_calculator: EquityCalculator, config: CalculationConfig):
        """An equity IRB-Simple 'other' exposure carrying EL = 2.4% x 100,000."""
        equity_frame = pl.LazyFrame(
            {
                "exposure_reference": ["EQ-OTHER-001"],
                "ead_final": [100_000.0],
                "equity_type": ["other"],
            }
        )
        bundle = make_crm_bundle(exposures=pl.LazyFrame(), equity_exposures=equity_frame)
        return equity_calculator.get_equity_result_bundle(bundle, config)

    def test_equity_el_does_not_move_shortfall(
        self,
        aggregator: OutputAggregator,
        equity_calculator: EquityCalculator,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """With an equity IRB-Simple row (EL 2,400) present, the Art. 159 shortfall
        stays at the corporate-only 20,000 — equity EL is excluded (Art. 159)."""
        equity_bundle = self._equity_bundle(equity_calculator, crr_irb_config)

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=self._irb_corporate_shortfall_book(),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=equity_bundle,
            config=crr_irb_config,
        )

        el = result.el_summary
        assert el is not None
        # Pool EL is corporate-only (50,000) — equity 2,400 is NOT added.
        assert float(el.total_expected_loss) == pytest.approx(50_000.0), (
            f"{SCENARIO_ID}: Art. 159 pool EL must exclude equity simple EL. "
            f"Got total_expected_loss={float(el.total_expected_loss)} "
            "(equity EL 2,400 must not be pooled)."
        )
        assert float(el.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(el.cet1_deduction) == pytest.approx(20_000.0)

    def test_equity_el_present_on_results_frame(
        self,
        aggregator: OutputAggregator,
        equity_calculator: EquityCalculator,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """The equity row still carries its Art. 158(7) EL on the results frame
        (emitted for disclosure), even though it is excluded from Art. 159."""
        equity_bundle = self._equity_bundle(equity_calculator, crr_irb_config)

        result = aggregator.aggregate(
            sa_results=EMPTY_SA,
            irb_results=self._irb_corporate_shortfall_book(),
            slotting_results=EMPTY_SLOTTING,
            equity_bundle=equity_bundle,
            config=crr_irb_config,
        )

        df = result.results.collect()
        equity_row = df.filter(pl.col("exposure_reference") == "EQ-OTHER-001")
        assert equity_row.height == 1
        assert equity_row["expected_loss"][0] == pytest.approx(2_400.0)
