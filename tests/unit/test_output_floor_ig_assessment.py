"""
Output floor Art. 122(8) — IG assessment choice affects S-TREA.

PRA PS1/26 Art. 122(8): IRB institutions must choose between 100% flat
(Art. 122(2)) or 65%/135% IG assessment (Art. 122(6)) for unrated
corporates. This choice flows through to the output floor S-TREA
computation via ``CalculationConfig.use_investment_grade_assessment``.

Why this matters:
    An IRB institution's choice between 100% flat and 65%/135% IG assessment
    materially changes S-TREA and therefore whether the output floor binds.
    For a portfolio of investment-grade corporates, choosing IG assessment
    reduces S-TREA by up to 35% (65% vs 100%), making the floor less likely
    to bind — directly reducing capital requirements. The choice must be
    declared to the PRA and cannot be changed opportunistically.

References:
- PRA PS1/26 Art. 122(6)/(8): IG/non-IG corporate RW election
- PRA PS1/26 Art. 92 para 2A: Output floor formula
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator.aggregator import OutputAggregator
from rwa_calc.engine.sa.calculator import SACalculator

# --- Helpers ---

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


def _irb_corporate_frame(
    *,
    ead: float = 1_000_000.0,
    rwa: float = 500_000.0,
    sa_rwa: float = 1_000_000.0,
    exposure_class: str = "CORPORATE",
    ref: str = "EXP1",
) -> pl.LazyFrame:
    """Build a minimal IRB corporate exposure with pre-baked sa_rwa."""
    return pl.LazyFrame(
        {
            "exposure_reference": [ref],
            "exposure_class": [exposure_class],
            "approach_applied": ["FIRB"],
            "ead_final": [ead],
            "risk_weight": [rwa / ead if ead > 0 else 0.0],
            "rwa_final": [rwa],
            "sa_rwa": [sa_rwa],
        }
    )


def _b31_config(
    *,
    use_ig: bool = False,
    reporting_date: date = date(2032, 1, 1),
) -> CalculationConfig:
    """B31 config with optional IG assessment election."""
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        use_investment_grade_assessment=use_ig,
    )


# --- SA Calculator: sa_rwa reflects IG flag ---


class TestSACalculatorIGForFloor:
    """SA calculator unified path produces sa_rwa reflecting Art. 122(8) choice.

    Why: The unified path computes SA-equivalent RWA for ALL exposures,
    including IRB exposures. The sa_rwa column feeds directly into S-TREA.
    The IG assessment flag must flow through to sa_rwa values.
    """

    @pytest.fixture
    def sa_calculator(self) -> SACalculator:
        return SACalculator()

    def _unrated_corporate_frame(
        self,
        *,
        is_ig: bool = False,
        approach: str = "standardised",
        ead: float = 1_000_000.0,
    ) -> pl.LazyFrame:
        """Build a minimal unrated corporate frame for unified path."""
        return pl.LazyFrame(
            {
                "exposure_reference": ["CORP1"],
                "exposure_class": ["CORPORATE"],
                "approach": [approach],
                "ead_final": [ead],
                "cqs": [None],
                "cp_is_investment_grade": [is_ig],
            }
        )

    def test_sa_rwa_100pct_without_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Default (no IG election): unrated corporate sa_rwa = EAD × 100%."""
        config = _b31_config(use_ig=False)
        frame = self._unrated_corporate_frame(approach="firb")
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(1_000_000.0)

    def test_sa_rwa_65pct_with_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """IG election + IG counterparty: unrated corporate sa_rwa = EAD × 65%."""
        config = _b31_config(use_ig=True)
        frame = self._unrated_corporate_frame(approach="firb", is_ig=True)
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(650_000.0)

    def test_sa_rwa_135pct_non_ig(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """IG election + non-IG counterparty: sa_rwa = EAD × 135%."""
        config = _b31_config(use_ig=True)
        frame = self._unrated_corporate_frame(approach="firb", is_ig=False)
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(1_350_000.0)

    def test_rated_corporate_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Rated corporates (CQS present) use CQS table regardless of IG flag."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_RATED"],
                "exposure_class": ["CORPORATE"],
                "approach": ["firb"],
                "ead_final": [1_000_000.0],
                "cqs": [3],
                "cp_is_investment_grade": [True],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # CQS 3 corporate → 75% (B31 Table 6) regardless of IG flag
        assert float(result["sa_rwa"][0]) == pytest.approx(750_000.0)

    def test_sme_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Corporate SME exposures get 85% regardless of IG flag (SME gate in when-chain)."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_SME"],
                "exposure_class": ["CORPORATE_SME"],
                "approach": ["firb"],
                "ead_final": [500_000.0],
                "cqs": [None],
                "cp_is_investment_grade": [True],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # Corporate SME → 85% always (Art. 122A), not affected by IG
        assert float(result["sa_rwa"][0]) == pytest.approx(425_000.0)

    def test_institution_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Institution exposures use SCRA/ECRA regardless of IG flag."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["INST1"],
                "exposure_class": ["INSTITUTION"],
                "approach": ["firb"],
                "ead_final": [1_000_000.0],
                "cqs": [None],
                "cp_is_investment_grade": [False],
                "cp_scra_grade": ["B"],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # SCRA grade B → 75%, not affected by corporate IG assessment
        assert float(result["sa_rwa"][0]) == pytest.approx(750_000.0)


# --- Aggregator: S-TREA changes with IG flag ---


class TestOutputFloorSTeaIG:
    """Output floor S-TREA depends on Art. 122(8) IG assessment choice.

    Why: S-TREA = sum(sa_rwa) for floor-eligible exposures. When sa_rwa
    changes due to the IG flag, S-TREA changes, which changes the floor
    threshold and whether the floor binds. This directly affects capital.
    """

    @pytest.fixture
    def aggregator(self) -> OutputAggregator:
        return OutputAggregator()

    def test_s_trea_100pct_without_ig(self, aggregator: OutputAggregator) -> None:
        """Without IG election: S-TREA = EAD × 100% for unrated corporate."""
        config = _b31_config(use_ig=False)
        # sa_rwa = 1M (100% of EAD) — simulating no IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(1_000_000.0)

    def test_s_trea_65pct_with_ig(self, aggregator: OutputAggregator) -> None:
        """With IG election: S-TREA = EAD × 65% for IG corporate."""
        config = _b31_config(use_ig=True)
        # sa_rwa = 650k (65% of EAD) — simulating IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(650_000.0)

    def test_s_trea_135pct_non_ig(self, aggregator: OutputAggregator) -> None:
        """With IG election: S-TREA = EAD × 135% for non-IG corporate."""
        config = _b31_config(use_ig=True)
        # sa_rwa = 1.35M (135% of EAD) — simulating non-IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_350_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(1_350_000.0)

    def test_ig_reduces_floor_threshold(self, aggregator: OutputAggregator) -> None:
        """IG assessment reduces floor threshold: 72.5% × 650k < 72.5% × 1M.

        Why: The floor threshold = floor_pct × S-TREA. When IG assessment
        reduces S-TREA (65% vs 100%), the floor threshold drops proportionally.
        """
        config = _b31_config(use_ig=True)
        # IG corporate: sa_rwa = 650k
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # Floor threshold = 72.5% × 650k = 471,250
        assert summary.floor_threshold == pytest.approx(471_250.0)

    def test_ig_changes_floor_binding(self, aggregator: OutputAggregator) -> None:
        """IG assessment can flip floor from binding to non-binding.

        Why: With IRB RWA = 500k:
        - Without IG: floor = 72.5% × 1M = 725k > 500k → binds
        - With IG: floor = 72.5% × 650k = 471.25k < 500k → does NOT bind
        This demonstrates the material capital impact of Art. 122(8).
        """
        # Without IG: floor binds (725k > 500k)
        config_no_ig = _b31_config(use_ig=False)
        irb_no_ig = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result_no_ig = aggregator.aggregate(EMPTY, irb_no_ig, EMPTY, None, config_no_ig)
        assert result_no_ig.output_floor_summary is not None
        assert result_no_ig.output_floor_summary.portfolio_floor_binding is True
        assert result_no_ig.output_floor_summary.shortfall == pytest.approx(225_000.0)

        # With IG: floor does NOT bind (471.25k < 500k)
        config_ig = _b31_config(use_ig=True)
        irb_ig = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result_ig = aggregator.aggregate(EMPTY, irb_ig, EMPTY, None, config_ig)
        assert result_ig.output_floor_summary is not None
        assert result_ig.output_floor_summary.portfolio_floor_binding is False
        assert result_ig.output_floor_summary.shortfall == pytest.approx(0.0)

    def test_non_ig_increases_floor_threshold(self, aggregator: OutputAggregator) -> None:
        """Non-IG 135% increases floor threshold vs default 100%.

        Why: Non-IG corporates INCREASE S-TREA and make the floor more likely
        to bind. This is the capital penalty for choosing IG assessment without
        actually having IG counterparties.
        """
        config = _b31_config(use_ig=True)
        # Non-IG corporate: sa_rwa = 1.35M
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_350_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # Floor threshold = 72.5% × 1.35M = 978,750
        assert summary.floor_threshold == pytest.approx(978_750.0)
        assert summary.shortfall == pytest.approx(478_750.0)

    def test_mixed_ig_and_non_ig(self, aggregator: OutputAggregator) -> None:
        """Mixed portfolio: IG and non-IG corporates affect S-TREA additively.

        Why: In practice, IRB institutions will have a mix of IG and non-IG
        corporate counterparties. S-TREA is the sum of all sa_rwa values.
        """
        config = _b31_config(use_ig=True)
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IG_CORP", "NON_IG_CORP"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["FIRB", "FIRB"],
                "ead_final": [1_000_000.0, 1_000_000.0],
                "risk_weight": [0.5, 0.5],
                "rwa_final": [500_000.0, 500_000.0],
                "sa_rwa": [650_000.0, 1_350_000.0],  # IG=65%, non-IG=135%
            }
        )
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # S-TREA = 650k + 1.35M = 2M (average 100%, same as no-IG in aggregate)
        assert summary.s_trea == pytest.approx(2_000_000.0)
        assert summary.u_trea == pytest.approx(1_000_000.0)

    def test_rwa_post_floor_with_ig(self, aggregator: OutputAggregator) -> None:
        """Post-floor RWA reflects the IG-adjusted S-TREA.

        Why: When the floor does not bind (IG assessment reduces S-TREA below
        U-TREA), the final RWA equals the pre-floor IRB RWA — no add-on.
        """
        config = _b31_config(use_ig=True)
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Floor does not bind → rwa_final = pre-floor IRB RWA
        assert float(df["rwa_final"][0]) == pytest.approx(500_000.0)

    def test_rwa_post_floor_without_ig(self, aggregator: OutputAggregator) -> None:
        """Without IG: floor binds and increases RWA.

        Why: When floor binds, rwa_final = pre-floor + shortfall.
        """
        config = _b31_config(use_ig=False)
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Floor binds: rwa_final = 500k + 225k shortfall = 725k
        assert float(df["rwa_final"][0]) == pytest.approx(725_000.0)

    def test_config_flag_propagates_to_factory(self) -> None:
        """CalculationConfig.basel_3_1() correctly propagates use_ig_assessment.

        Why: The factory method is the primary entry point for config creation.
        The flag must survive the factory construction chain.
        """
        config_no_ig = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            use_investment_grade_assessment=False,
        )
        assert config_no_ig.use_investment_grade_assessment is False

        config_ig = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            use_investment_grade_assessment=True,
        )
        assert config_ig.use_investment_grade_assessment is True

    def test_crr_ig_flag_locked_false(self) -> None:
        """CRR config always has use_investment_grade_assessment=False.

        Why: CRR Art. 122 does not have the IG assessment election. The CRR
        factory must not accept or propagate this flag.
        """
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.use_investment_grade_assessment is False
