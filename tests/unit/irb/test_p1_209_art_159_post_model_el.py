"""
Unit pins — P1.209: the Art. 159 EL comparison includes the Art. 158(6A) PMA.

Pipeline position:
    CRMProcessor -> IRBCalculator (per-row Art. 159 carriers)
        -> OutputAggregator (portfolio Art. 159 netting -> CET1 / T2 -> OF-ADJ)

Key assertion:
    PS1/26 Art. 158(6A) (ps126app1.pdf, printed p.108, verbatim): "An
    institution shall increase the total expected loss amounts calculated under
    paragraphs 5 and 6 to reflect any post model adjustments in respect of
    expected loss amounts calculated under point (c) of Article 146(3)."

    PS1/26 Art. 159(1) (printed pp.108-109, verbatim): "'A' = the sum of
    expected loss amounts calculated in accordance with Article 158(5), (6),
    (6A) and (10) for non-defaulted exposures; ... 'C' = the sum of expected
    loss amounts calculated in accordance with paragraphs 5, 6, 6A and 10 of
    Article 158 for defaulted exposures". Art. 159(3)(c)/(d) then compare
    ('A' + 'C') against ('B' + 'D').

    So the EL that enters the Art. 159 comparison is the post-6A amount
    (``el_after_adjustment``), in BOTH pools. The engine computed that amount
    and then compared the pre-6A ``expected_loss`` against Pool B, at two
    sites: the per-row audit carriers (``compute_el_shortfall_excess``) and
    the portfolio netting that produces the Art. 36(1)(d) CET1 deduction, the
    Art. 62(d) T2 credit and, through them, OF-ADJ (Art. 92(2A)).

    Every figure here STRADDLES Pool B: pre-6A EL 10 sits below Pool B 12 and
    post-6A EL 15 above it, so the comparison changes sign. A fixture where
    both ELs sit on the same side of Pool B would prove nothing.

    CRR has no Art. 158(6A) (CRR Art. 159 nets "Article 158(5), (6) and (10)"
    EL only) and the ``post_model_adjustments`` pack Feature is off there, so
    the CRR legs below are regression guards, not fail-first tests: CRR cannot
    be reddened by this item. The CRR guarantee leg pins the producer-side gate
    that keeps a directly-constructed CRR config with a non-zero
    ``pma_el_scalar`` from leaking a PMA into ``el_after_adjustment``.

References:
    - PS1/26 Art. 146(3)(c), 158(6A), 159(1), 159(3)
    - PS1/26 Art. 92(2A): OF-ADJ = 12.5 x (IRB T2 - IRB CET1 - GCRA + SA T2)
    - CRR Art. 36(1)(d), 62(d)
    - src/rwa_calc/engine/irb/adjustments.py::compute_el_shortfall_excess
    - src/rwa_calc/engine/aggregator/_el_summary.py::compute_el_portfolio_summary
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.contract_columns import (
    pad_crm_exit_defaults,
    pad_irb_branch,
    pad_sa_branch,
    pad_slotting_branch,
)

from rwa_calc.contracts.config import CalculationConfig, PostModelAdjustmentConfig
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.irb import IRBCalculator
from rwa_calc.engine.irb.transforms import (
    apply_guarantee_substitution,
    apply_post_model_adjustments,
    compute_el_shortfall_excess,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EAD = 1_000.0
PD = 0.02
LGD = 0.50
BEEL = 0.01  # defaulted A-IRB leg: EL = BEEL x EAD = 10
EL_PRE_6A = 10.0  # PD x LGD x EAD = 0.02 x 0.50 x 1,000 (and BEEL x EAD)
PMA_EL_SCALAR = Decimal("0.5")
EL_POST_6A = 15.0  # 10 + max(0, 10 x 0.5)
POOL_B = 12.0  # provisions only (no AVA / other own funds reductions)

SHORTFALL_POST_6A = EL_POST_6A - POOL_B  # 3
EXCESS_PRE_6A = POOL_B - EL_PRE_6A  # 2 -- the pre-fix (wrong) B31 figure

T2_CAP_RATE = 0.006  # CRR Art. 62(d), as the test's adequacy check only


def _b31_config(pma_el_scalar: Decimal) -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 3, 31),
        post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(pma_el_scalar=pma_el_scalar),
    )


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


def _irb_results(config: CalculationConfig, *, defaulted: bool) -> pl.LazyFrame:
    """One A-IRB corporate leg through the full IRB chain, EL 10 vs Pool B 12."""
    frame = pl.DataFrame(
        {
            "exposure_reference": ["P1209_D" if defaulted else "P1209_ND"],
            "ead_final": [EAD],
            "pd": [1.0 if defaulted else PD],
            "lgd": [LGD],
            "beel": [BEEL],
            "exposure_class": ["corporate"],
            "maturity": [2.5],
            "approach": ["advanced_irb"],
            "provision_allocated": [POOL_B],
            "is_defaulted": [defaulted],
        }
    ).lazy()
    return IRBCalculator().calculate_branch(pad_crm_exit_defaults(frame), config)


def _assert_straddles_pool_b(row: dict, *, el_after: float) -> None:
    """Fixture adequacy: the pre- and post-6A EL sit on opposite sides of Pool B."""
    assert row["expected_loss"] == pytest.approx(EL_PRE_6A, rel=1e-12), (
        "pre-6A EL must be 10 so it sits BELOW Pool B 12"
    )
    assert row["el_after_adjustment"] == pytest.approx(el_after, rel=1e-12)
    assert row["provision_allocated"] == pytest.approx(POOL_B, rel=1e-12)


# ---------------------------------------------------------------------------
# Site 1 -- per-row Art. 159 audit carriers (IRBCalculator)
# ---------------------------------------------------------------------------


class TestArt159PerRowCarriers:
    """``el_shortfall`` / ``el_excess`` compare the post-6A EL against Pool B."""

    @pytest.mark.parametrize("defaulted", [False, True], ids=["A_non_defaulted", "C_defaulted"])
    def test_b31_post_model_el_above_pool_b_is_a_shortfall(self, defaulted: bool) -> None:
        """B31, PMA EL scalar 0.5: EL 10 -> 15 against Pool B 12 -> shortfall 3, excess 0.

        Art. 159(1) puts 158(6A) inside 'A' (non-defaulted) and 'C' (defaulted).
        Pre-fix failure: shortfall 0, excess 2 -- the pre-6A EL was compared.
        """
        # Arrange
        config = _b31_config(PMA_EL_SCALAR)

        # Act
        row = _irb_results(config, defaulted=defaulted).collect().to_dicts()[0]

        # Assert
        _assert_straddles_pool_b(row, el_after=EL_POST_6A)
        assert row["el_shortfall"] == pytest.approx(SHORTFALL_POST_6A, rel=1e-12)
        assert row["el_excess"] == pytest.approx(0.0, abs=1e-12)

    def test_b31_zero_scalar_compares_unadjusted_el(self) -> None:
        """Control: B31 with no EL PMA keeps the 2 excess (6A adds nothing)."""
        # Arrange
        config = _b31_config(Decimal("0"))

        # Act
        row = _irb_results(config, defaulted=False).collect().to_dicts()[0]

        # Assert
        _assert_straddles_pool_b(row, el_after=EL_PRE_6A)
        assert row["el_shortfall"] == pytest.approx(0.0, abs=1e-12)
        assert row["el_excess"] == pytest.approx(EXCESS_PRE_6A, rel=1e-12)

    def test_crr_has_no_158_6a_increase(self) -> None:
        """CRR Art. 159 nets 158(5)/(6)/(10) EL only: excess 2, shortfall 0."""
        # Arrange
        config = _crr_config()

        # Act
        row = _irb_results(config, defaulted=False).collect().to_dicts()[0]

        # Assert
        _assert_straddles_pool_b(row, el_after=EL_PRE_6A)
        assert row["el_shortfall"] == pytest.approx(0.0, abs=1e-12)
        assert row["el_excess"] == pytest.approx(EXCESS_PRE_6A, rel=1e-12)


# ---------------------------------------------------------------------------
# Site 2 -- portfolio Art. 159 netting (the capital figures)
# ---------------------------------------------------------------------------


class TestArt159PortfolioCapital:
    """CET1 deduction / T2 credit net the post-6A EL against Pool B per pool."""

    @pytest.mark.parametrize("defaulted", [False, True], ids=["A_non_defaulted", "C_defaulted"])
    def test_b31_cet1_deduction_includes_post_model_el(self, defaulted: bool) -> None:
        """B31, scalar 0.5: shortfall 3 -> CET1 deduction 3, T2 credit 0.

        Pre-fix failure: total shortfall 0, CET1 0, T2 credit 2 -- the portfolio
        netting re-summed the pre-6A ``expected_loss``, so fixing only the
        per-row carriers would have left every capital figure here unchanged.
        """
        # Arrange
        irb = _irb_results(_b31_config(PMA_EL_SCALAR), defaulted=defaulted)

        # Act
        summary = compute_el_portfolio_summary(irb, None)

        # Assert
        assert summary is not None
        assert float(summary.total_irb_rwa) * T2_CAP_RATE >= EXCESS_PRE_6A, (
            "the Art. 62(d) cap would bind on the pre-fix excess, so a T2 credit "
            "of 0 would not discriminate the fix"
        )
        assert float(summary.total_el_shortfall) == pytest.approx(SHORTFALL_POST_6A, rel=1e-12)
        assert float(summary.total_el_excess) == pytest.approx(0.0, abs=1e-12)
        assert float(summary.cet1_deduction) == pytest.approx(SHORTFALL_POST_6A, rel=1e-12)
        assert float(summary.t2_credit) == pytest.approx(0.0, abs=1e-12)
        assert float(summary.total_expected_loss) == pytest.approx(EL_POST_6A, rel=1e-12)

    def test_crr_capital_figures_unchanged(self) -> None:
        """CRR: excess 2 -> T2 credit 2, CET1 deduction 0 (no 158(6A))."""
        # Arrange
        irb = _irb_results(_crr_config(), defaulted=False)

        # Act
        summary = compute_el_portfolio_summary(irb, None)

        # Assert
        assert summary is not None
        assert float(summary.total_el_shortfall) == pytest.approx(0.0, abs=1e-12)
        assert float(summary.cet1_deduction) == pytest.approx(0.0, abs=1e-12)
        assert float(summary.t2_credit) == pytest.approx(EXCESS_PRE_6A, rel=1e-12)


# ---------------------------------------------------------------------------
# Carrier presence -- slotting legs: NULL (concat) and ABSENT (slotting-only)
# ---------------------------------------------------------------------------


def _slotting_results(*, el: float, provisions: float) -> pl.LazyFrame:
    """A slotting leg as the slotting calculator emits it: no PMA EL carrier."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["P1209_SL"],
            "rwa_final": [700.0],
            "expected_loss": [el],
            "provision_allocated": [provisions],
            "ava_amount": [0.0],
            "other_own_funds_reductions": [0.0],
            "el_shortfall": [max(0.0, el - provisions)],
            "el_excess": [max(0.0, provisions - el)],
            "is_defaulted": [False],
        }
    )


class TestArt159CarrierPresence:
    """A leg with no post-6A carrier nets its own ``expected_loss``."""

    def test_null_carrier_on_slotting_leg_falls_back_to_its_el(self) -> None:
        """IRB (EL 10 -> 15) + slotting (EL 8, no carrier) vs Pool B 12 + 8.

        After the diagonal concat the slotting row's ``el_after_adjustment`` is
        NULL. 'A' = 15 + 8 = 23 > 'B' = 20 -> shortfall 3. Summing the carrier
        alone (null as zero) would give 'A' = 15 -> excess 5; the pre-fix code
        gave 'A' = 18 -> excess 2.
        """
        # Arrange
        irb = _irb_results(_b31_config(PMA_EL_SCALAR), defaulted=False)
        slotting = _slotting_results(el=8.0, provisions=8.0)
        assert "el_after_adjustment" not in slotting.collect_schema().names(), (
            "the slotting leg must lack the carrier for the concat to null it"
        )

        # Act
        summary = compute_el_portfolio_summary(irb, slotting)

        # Assert
        assert summary is not None
        assert float(summary.total_expected_loss) == pytest.approx(23.0, rel=1e-12)
        assert float(summary.total_el_shortfall) == pytest.approx(3.0, rel=1e-12)
        assert float(summary.total_el_excess) == pytest.approx(0.0, abs=1e-12)

    def test_absent_carrier_on_slotting_only_run_nets_expected_loss(self) -> None:
        """Slotting-only run: no ``el_after_adjustment`` column anywhere -> EL 8 vs 12."""
        # Arrange
        slotting = _slotting_results(el=8.0, provisions=12.0)

        # Act
        summary = compute_el_portfolio_summary(None, slotting)
        per_row = compute_el_shortfall_excess(slotting).collect().to_dicts()[0]

        # Assert
        assert summary is not None
        assert float(summary.total_el_excess) == pytest.approx(4.0, rel=1e-12)
        assert float(summary.total_el_shortfall) == pytest.approx(0.0, abs=1e-12)
        assert per_row["el_excess"] == pytest.approx(4.0, rel=1e-12)
        assert per_row["el_shortfall"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# CRR regime gate -- the guarantee rebase must not resurrect a CRR PMA
# ---------------------------------------------------------------------------


class TestCRRGuaranteeRebaseGate:
    """``el_after_adjustment`` carries no PMA wherever the pack Feature is off."""

    @staticmethod
    def _guaranteed_leg(config: CalculationConfig) -> dict:
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["P1209_G"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["corporate"],
                "exposure_class_applied": ["corporate"],
                "approach": ["foundation_irb"],
                "approach_applied": ["foundation_irb"],
                "rwa": [1_000_000.0],
                "risk_weight": [1.00],
                "expected_loss": [4_500.0],
                "is_defaulted": [False],
                "provision_allocated": [2_400.0],
                "ava_amount": [0.0],
                "other_own_funds_reductions": [0.0],
                "guaranteed_portion": [600_000.0],
                "unguaranteed_portion": [400_000.0],
                "guarantor_entity_type": ["institution"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [0.002],
            }
        )
        return (
            frame.pipe(apply_post_model_adjustments, config)
            .pipe(apply_guarantee_substitution, config)
            .pipe(compute_el_shortfall_excess)
            .collect()
            .to_dicts()[0]
        )

    def test_crr_config_with_pma_scalar_keeps_el_after_equal_to_el(self) -> None:
        """A directly-built CRR config carrying pma_el_scalar 0.10 adds no 6A PMA.

        ``CalculationConfig.crr()`` cannot carry a PMA election, but direct
        construction can. The PMA stage is gated on the ``post_model_adjustments``
        pack Feature; the guarantee rebase recomputed the PMA from the config
        election without that gate.

        Pre-fix failure: post_model_adjustment_el 234 (10% of the post-CRM EL
        2,340) and el_after_adjustment 2,574 on a CRR leg.
        """
        # Arrange
        config = replace(
            _crr_config(),
            post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(
                pma_el_scalar=Decimal("0.10")
            ),
        )

        # Act
        row = self._guaranteed_leg(config)

        # Assert
        assert row["expected_loss"] != pytest.approx(4_500.0), (
            "the leg was not substituted, so the guarantee rebase never ran"
        )
        assert row["post_model_adjustment_el"] == pytest.approx(0.0, abs=1e-12)
        assert row["el_after_adjustment"] == pytest.approx(row["expected_loss"], rel=1e-12)

    def test_crr_art_159_nets_unadjusted_el_on_guaranteed_leg(self) -> None:
        """CRR Art. 159 on the same leg: EL 2,340 vs Pool B 2,400 -> excess 60.

        Guard against a reading of ``el_after_adjustment`` that the regime gate
        does not cover: with the leaked 10% PMA the leg would show a 174
        shortfall instead.
        """
        # Arrange
        config = replace(
            _crr_config(),
            post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(
                pma_el_scalar=Decimal("0.10")
            ),
        )

        # Act
        row = self._guaranteed_leg(config)

        # Assert
        assert row["expected_loss"] == pytest.approx(2_340.0, rel=1e-9)
        assert row["el_excess"] == pytest.approx(60.0, rel=1e-9)
        assert row["el_shortfall"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Output floor -- OF-ADJ and floored TREA fall (RWA-reducing evidence)
# ---------------------------------------------------------------------------


_EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


def _floor_irb_branch(el_after_adjustment: float) -> pl.LazyFrame:
    """IRB branch leg: RWA 50m, SA-equivalent 100m, EL 100k, Pool B 120k.

    The per-row carriers are written as the FIXED IRB chain emits them (shortfall
    30k, excess 0), so this test exercises the portfolio netting on its own: the
    pre-fix aggregator ignored them and re-netted the pre-6A ``expected_loss``.
    """
    return pad_irb_branch(
        pl.LazyFrame(
            {
                "exposure_reference": ["P1209_OF"],
                "exposure_class": ["corporate"],
                "approach_applied": ["foundation_irb"],
                "ead_final": [200_000_000.0],
                "risk_weight": [0.25],
                "rwa_post_factor": [50_000_000.0],
                "rwa_final": [50_000_000.0],
                "sa_rwa": [100_000_000.0],
                "expected_loss": [100_000.0],
                "el_pre_adjustment": [100_000.0],
                "post_model_adjustment_el": [el_after_adjustment - 100_000.0],
                "el_after_adjustment": [el_after_adjustment],
                "provision_allocated": [120_000.0],
                "el_shortfall": [max(0.0, el_after_adjustment - 120_000.0)],
                "el_excess": [max(0.0, 120_000.0 - el_after_adjustment)],
            }
        )
    )


class TestOfAdjFallsWithPostModelEL:
    """OF-ADJ = 12.5 x (IRB T2 - IRB CET1 - GCRA + SA T2) sees the post-6A EL."""

    def test_b31_of_adj_and_floored_trea_reflect_post_model_el(self) -> None:
        """EL 100k -> 150k vs Pool B 120k, floor 72.5% (2032), floor binding.

        CET1 deduction 30k, T2 credit 0 -> OF-ADJ = 12.5 x (0 - 30k) = -375k.
        Floor threshold = 72.5% x 100m - 375k = 72,125,000 = floored TREA.

        Pre-fix failure: T2 credit 20k, CET1 0 -> OF-ADJ +250k, threshold
        72,750,000. The fix lowers floored TREA by 12.5 x (30k + 20k) = 625k.
        """
        # Arrange
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))
        irb = _floor_irb_branch(el_after_adjustment=150_000.0)

        # Act
        result = OutputAggregator().aggregate(
            pad_sa_branch(_EMPTY), irb, pad_slotting_branch(_EMPTY), None, config
        )

        # Assert
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.portfolio_floor_binding is True
        assert summary.irb_cet1_deduction == pytest.approx(30_000.0, rel=1e-9)
        assert summary.irb_t2_credit == pytest.approx(0.0, abs=1e-6)
        assert summary.of_adj == pytest.approx(-375_000.0, rel=1e-9)
        assert summary.floor_threshold == pytest.approx(72_125_000.0, rel=1e-9)
        assert summary.floored_modelled_rwa == pytest.approx(72_125_000.0, rel=1e-9)

    def test_b31_of_adj_control_without_post_model_el(self) -> None:
        """Control: EL 100k (no PMA) vs Pool B 120k -> T2 credit 20k, OF-ADJ +250k."""
        # Arrange
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))
        irb = _floor_irb_branch(el_after_adjustment=100_000.0)

        # Act
        result = OutputAggregator().aggregate(
            pad_sa_branch(_EMPTY), irb, pad_slotting_branch(_EMPTY), None, config
        )

        # Assert
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.irb_t2_credit == pytest.approx(20_000.0, rel=1e-9)
        assert summary.irb_cet1_deduction == pytest.approx(0.0, abs=1e-6)
        assert summary.of_adj == pytest.approx(250_000.0, rel=1e-9)
        assert summary.floor_threshold == pytest.approx(72_750_000.0, rel=1e-9)

    def test_b31_securitised_leg_nets_only_its_residual_post_model_el(self) -> None:
        """Residual 50%: post-6A EL 150k -> 75k vs Pool B 120k -> 60k -> shortfall 15k.

        Art. 159(2)(b) keeps securitised EL out of the comparison, so the post-6A
        carrier must be residual-scaled with ``expected_loss`` and Pool B. Left
        unscaled it would net 150k against 60k (shortfall 90k); the pre-fix code
        netted the scaled pre-6A 50k (excess 10k, T2 credit 10k).
        """
        # Arrange
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))
        irb = _floor_irb_branch(el_after_adjustment=150_000.0).with_columns(
            pl.lit(0.5).alias("securitisation_residual_pct")
        )

        # Act
        result = OutputAggregator().aggregate(
            pad_sa_branch(_EMPTY), irb, pad_slotting_branch(_EMPTY), None, config
        )

        # Assert
        el_summary = result.el_summary
        assert el_summary is not None
        assert float(el_summary.total_pool_b) == pytest.approx(60_000.0, rel=1e-9), (
            "the residual multiplier did not reach Pool B, so this test cannot "
            "tell a scaled post-6A EL from an unscaled one"
        )
        assert float(el_summary.total_expected_loss) == pytest.approx(75_000.0, rel=1e-9)
        assert float(el_summary.cet1_deduction) == pytest.approx(15_000.0, rel=1e-9)
        assert float(el_summary.t2_credit) == pytest.approx(0.0, abs=1e-6)
