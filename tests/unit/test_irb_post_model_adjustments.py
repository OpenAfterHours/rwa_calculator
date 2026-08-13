"""
Tests for IRB post-model adjustments (Basel 3.1).

Why: PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require post-model
adjustments (PMAs) to IRB model outputs. These tests verify that the
IRB namespace correctly applies mortgage RW floors, general PMAs,
unrecognised exposure adjustments, and EL adjustments — and that CRR
exposures are unaffected.

Phase 5 S11e-v3: the mortgage RW floor is a rulepack ScalarParam read engine-
side, so a non-default floor is injected via the ResolvedRulepack.with_overrides
seam (``_b31_config`` returns the (config, pack) pair). The PMA scalars
(pma_rwa/el/unrecognised) stay config-side firm elections.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import (
    CalculationConfig,
    PostModelAdjustmentConfig,
)
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.irb.transforms import (
    apply_post_model_adjustments,
)
from rwa_calc.rulebook.model import Citation, ScalarParam
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve


def _make_irb_frame(
    exposure_class: str = "corporate",
    rwa: float = 1000.0,
    risk_weight: float = 0.50,
    ead_final: float = 2000.0,
    expected_loss: float = 10.0,
    is_defaulted: bool = False,
) -> pl.LazyFrame:
    """Minimal IRB frame with columns expected by apply_post_model_adjustments.

    ``is_defaulted`` is the CRR Art. 178 default flag. It is emitted
    unconditionally because PS1/26 Art. 154(4A)(b) confines the mortgage RWEA
    floor to NON-defaulted exposures, so the transform reads the column on every
    row. It is ``required=True`` on the ``crm_exit``/``re_split_exit`` sealed
    edges and ``apply_defaulted_treatment`` — same module, strictly earlier on
    every production path — already dereferences it, so no production frame can
    reach ``apply_post_model_adjustments`` without it.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP_1"],
            "exposure_class": [exposure_class],
            "rwa": [rwa],
            "risk_weight": [risk_weight],
            "ead_final": [ead_final],
            "expected_loss": [expected_loss],
            "is_defaulted": pl.Series([is_defaulted], dtype=pl.Boolean),
        }
    )


def _b31_config(
    pma_rwa_scalar: Decimal = Decimal("0.0"),
    pma_el_scalar: Decimal = Decimal("0.0"),
    mortgage_rw_floor: Decimal = Decimal("0.15"),
    unrecognised_exposure_scalar: Decimal = Decimal("0.0"),
) -> tuple[CalculationConfig, ResolvedRulepack]:
    """Basel 3.1 config + rulepack with custom PMA settings.

    The PMA scalars are firm elections and stay on the config. The mortgage RW
    floor is a regulatory pack scalar (S11e-v3), so a non-default floor is
    injected via ``ResolvedRulepack.with_overrides`` and the engine reads it
    from the returned pack — not the config.
    """
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2028, 3, 31),
        post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(
            pma_rwa_scalar=pma_rwa_scalar,
            pma_el_scalar=pma_el_scalar,
            unrecognised_exposure_scalar=unrecognised_exposure_scalar,
        ),
    )
    pack = resolve("b31", date(2028, 3, 31)).with_overrides(
        mortgage_rw_floor=ScalarParam(
            name="mortgage_rw_floor",
            value=mortgage_rw_floor,
            citation=Citation("PS1/26", "154(4A)"),
        )
    )
    return config, pack


class TestPostModelAdjustmentsCRR:
    """CRR framework: PMAs disabled, columns added with zero values."""

    def test_crr_rwa_unchanged(self) -> None:
        """CRR: RWA is not modified by PMAs."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        lf = _make_irb_frame(rwa=1000.0)
        result = lf.pipe(apply_post_model_adjustments, config).collect()
        assert result["rwa"][0] == pytest.approx(1000.0)

    def test_crr_pma_columns_zero(self) -> None:
        """CRR: PMA adjustment columns are zero."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        result = _make_irb_frame().pipe(apply_post_model_adjustments, config).collect()
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(0.0)
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(0.0)

    def test_crr_el_unchanged(self) -> None:
        """CRR: Expected loss not modified."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        result = (
            _make_irb_frame(expected_loss=10.0).pipe(apply_post_model_adjustments, config).collect()
        )
        assert result["el_after_adjustment"][0] == pytest.approx(10.0)


class TestPostModelAdjustmentsBasel31:
    """Basel 3.1: PMAs applied when enabled and configured."""

    def test_general_pma_rwa(self) -> None:
        """General PMA adds scalar × base_rwa to RWEA."""
        config, pack = _b31_config(pma_rwa_scalar=Decimal("0.05"))
        result = (
            _make_irb_frame(rwa=1000.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["rwa_pre_adjustments"][0] == pytest.approx(1000.0)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(50.0)
        # Final RWA = 1000 + 50 = 1050
        assert result["rwa"][0] == pytest.approx(1050.0)

    def test_mortgage_rw_floor_binding(self) -> None:
        """Mortgage RW floor increases RWEA when modelled RW < floor."""
        config, pack = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        # Mortgage with RW=0.10 < floor=0.15 → floor adds (0.15-0.10)*EAD
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        # Floor adjustment = (0.15 - 0.10) * 2000 = 100.0
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)
        # Final RWA = 200 + 100 = 300
        assert result["rwa"][0] == pytest.approx(300.0)

    def test_mortgage_rw_floor_non_binding(self) -> None:
        """Mortgage RW floor has no effect when modelled RW >= floor."""
        config, pack = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=400.0,
            risk_weight=0.20,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["rwa"][0] == pytest.approx(400.0)

    def test_mortgage_floor_corporate_unaffected(self) -> None:
        """Mortgage RW floor only applies to mortgage exposures, not corporate."""
        config, pack = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="corporate",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)

    def test_unrecognised_exposure_adjustment(self) -> None:
        """Unrecognised exposure adjustment adds scalar × base_rwa."""
        config, pack = _b31_config(unrecognised_exposure_scalar=Decimal("0.02"))
        result = (
            _make_irb_frame(rwa=1000.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(20.0)
        assert result["rwa"][0] == pytest.approx(1020.0)

    def test_all_adjustments_combined(self) -> None:
        """All three RWEA adjustments are additive increases to one common base.

        Why: Art. 154(4A)'s chapeau — "An institution shall increase the total
        risk-weighted exposure amounts calculated under paragraphs 1, 3 and 4
        ... to reflect: (a) ... (b) ... (c) ..." — makes the three limbs
        additive to that single pre-floor base, not a pipeline. Limb (b) is a
        TEST ("any amount needed to ensure that risk-weighted exposure amounts
        ... are greater than or equal to 10% of the exposure value") evaluated
        "following application of any post model adjustments calculated under
        point (b) of Article 146(3)" — which is limb (a), and only limb (a).
        Limb (c) is "calculated under Article 166D(6)", a different provision,
        so it stays outside the comparison.

        Inverted by P1.325. This test previously asserted the floor first with
        both scalars multiplying the post-floor base, and attributed that
        ordering to the article — the same misattribution the engine docstring
        carried. Its expected values were internally consistent with the code
        rather than with Art. 154(4A), which is why nothing objected.
        """
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.05"),
            mortgage_rw_floor=Decimal("0.20"),
            unrecognised_exposure_scalar=Decimal("0.02"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        # Base (paragraphs 1/3/4) = 200.
        # (a) general PMA on the base:            200 * 0.05 = 10
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(10.0)
        # (c) unrecognised exposure on the base:  200 * 0.02 = 4
        #     NOT in the (b) comparison — Art. 166D(6), not Art. 146(3)(b).
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(4.0)
        # (b) floor tested after (a): 0.20 * 2000 = 400 required,
        #     base + (a) = 210 present, so the shortfall is 190.
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(190.0)
        # Total: 200 + 10 + 190 + 4 = 404 (was 428 under the inverted order).
        assert result["rwa"][0] == pytest.approx(404.0)
        # The floor is a floor: the post-adjustment RWEA less limb (c), which
        # sits outside the test, must be exactly the 10%-of-exposure-value
        # minimum. Stated as an identity so it survives a change to the
        # scalars — a per-component check alone would not catch the floor
        # being satisfied at the wrong level.
        assert result["rwa"][0] - result["unrecognised_exposure_adjustment"][0] == pytest.approx(
            0.20 * 2000.0
        )

    def test_el_adjustment(self) -> None:
        """EL adjustment adds scalar × base_el to expected loss."""
        config, pack = _b31_config(pma_el_scalar=Decimal("0.10"))
        result = (
            _make_irb_frame(expected_loss=10.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["el_pre_adjustment"][0] == pytest.approx(10.0)
        assert result["post_model_adjustment_el"][0] == pytest.approx(1.0)
        assert result["el_after_adjustment"][0] == pytest.approx(11.0)

    def test_zero_scalars_no_change(self) -> None:
        """With all scalars at zero (and no mortgage floor), RWA unchanged."""
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.0"),
            mortgage_rw_floor=Decimal("0.0"),
            unrecognised_exposure_scalar=Decimal("0.0"),
        )
        result = (
            _make_irb_frame(rwa=1000.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["rwa"][0] == pytest.approx(1000.0)

    def test_sa_residential_mortgage_class_does_not_trigger_mortgage_floor(self) -> None:
        """'residential_mortgage' is the SA loan-splitter's class, not Art. 147(5B)(d)(ii).

        INVERTED (P1.319). This test previously asserted that the class DID
        trigger the floor, which pinned the defect: the gate matched
        ``exposure_class`` against the regex ``MORTGAGE|RESIDENTIAL`` and nothing
        else.

        PS1/26 Art. 154(4A)(b) reaches only "retail exposures secured by
        residential immovable property", i.e. the Art. 147(5B) subclass
        (d)(ii) — whose engine carrier is ``ExposureClass.RETAIL_MORTGAGE``.
        ``residential_mortgage`` is the SA real-estate loan-splitter's
        non-retail RRE child (``domain/enums.py``), is SA-bound by
        ``engine/stages/re_split/splitter.py`` and is not an Art. 147(5B)
        subclass at all. It must NOT receive the IRB post-model floor.
        """
        config, pack = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="residential_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)


class TestPostModelAdjustmentConfig:
    """Test PostModelAdjustmentConfig factory methods."""

    def test_crr_disabled(self) -> None:
        """CRR config has PMAs disabled."""
        config = PostModelAdjustmentConfig.crr()
        assert config.enabled is False

    def test_b31_enabled(self) -> None:
        """Basel 3.1 config has PMAs enabled."""
        config = PostModelAdjustmentConfig.basel_3_1()
        assert config.enabled is True

    def test_b31_default_mortgage_floor(self) -> None:
        """Basel 3.1 default mortgage RW floor is 10% (PRA Art. 154(4A)(b))."""
        config = PostModelAdjustmentConfig.basel_3_1()
        assert config.mortgage_rw_floor == Decimal("0.10")

    def test_pack_mortgage_floor_matches_config_default(self) -> None:
        """The b31 pack scalar mirrors the config factory's 10% default (S11e-v3).

        Byte-identity: production reads mortgage_rw_floor from the pack, and the
        pack default must equal the config default the engine read before.
        """
        pack = resolve("b31", date(2028, 3, 31))
        assert (
            pack.scalar("mortgage_rw_floor")
            == PostModelAdjustmentConfig.basel_3_1().mortgage_rw_floor
        )

    def test_b31_custom_scalars(self) -> None:
        """Basel 3.1 config accepts custom scalars."""
        config = PostModelAdjustmentConfig.basel_3_1(
            pma_rwa_scalar=Decimal("0.10"),
            unrecognised_exposure_scalar=Decimal("0.03"),
        )
        assert config.pma_rwa_scalar == Decimal("0.10")
        assert config.unrecognised_exposure_scalar == Decimal("0.03")

    def test_calculation_config_b31_includes_pma(self) -> None:
        """CalculationConfig.basel_3_1() includes PMAs by default."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 3, 31))
        assert config.post_model_adjustments.enabled is True

    def test_calculation_config_crr_excludes_pma(self) -> None:
        """CalculationConfig.crr() excludes PMAs."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.post_model_adjustments.enabled is False


class TestPMASequencing:
    """Art. 154(4A): the three limbs are additive increases to one base.

    Why: the chapeau increases "the total risk-weighted exposure amounts
    calculated under paragraphs 1, 3 and 4", so (a), (b) and (c) all measure
    against that single pre-floor base. Limb (b) is a test evaluated
    "following application of any post model adjustments calculated under
    point (b) of Article 146(3)" — limb (a), and only limb (a); limb (c) is
    Art. 166D(6) and stays outside it.

    Corrected by P1.325. This class previously asserted the reverse — floor
    first, both scalars on the post-floor base — and gave the article as its
    reason. Every method name and expected value was internally consistent
    with the code and inconsistent with Art. 154(4A).
    """

    def test_pma_multiplies_the_pre_floor_base(self) -> None:
        """Limb (a) multiplies the paragraph-1/3/4 base, not the floored RWEA.

        Model RW=5% (RWA=100), mortgage floor=10%, PMA=10%, EAD=2000.
        (a) = 100 x 0.10 = 10. The floor then requires 0.10 x 2000 = 200
        against a post-(a) figure of 110, so (b) = 90 and the total is 200 —
        the floor binding exactly, which is what a floor should do.
        """
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=100.0,
            risk_weight=0.05,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        # (a) on the base: 100 * 0.10 = 10
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(10.0)
        # (b) tested after (a): 0.10 * 2000 = 200 required, 110 present -> 90
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(90.0)
        # Total: 100 + 10 + 90 = 200 — the floor binds exactly.
        assert result["rwa"][0] == pytest.approx(200.0)
        assert result["rwa"][0] == pytest.approx(0.10 * 2000.0)

    def test_unrecognised_sits_outside_the_floor_test(self) -> None:
        """Limb (c) multiplies the base and is added outside the (b) comparison.

        Art. 154(4A)(c) is "any unrecognised exposure adjustment calculated
        under Article 166D(6)". The (b) parenthetical admits only
        Art. 146(3)(b) adjustments, so (c) neither feeds the floor test nor is
        capped by it: the floor brings RWEA to 200 and (c) adds 5 on top.
        """
        config, pack = _b31_config(
            mortgage_rw_floor=Decimal("0.10"),
            unrecognised_exposure_scalar=Decimal("0.05"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=100.0,
            risk_weight=0.05,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        # (c) on the base: 100 * 0.05 = 5
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(5.0)
        # (b) with no limb (a) configured: 200 required, 100 present -> 100
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)
        # Total: 100 + 100 + 5 = 205, i.e. the floor plus (c) on top of it.
        assert result["rwa"][0] == pytest.approx(205.0)

    def test_non_binding_floor_pma_uses_base_rwa(self) -> None:
        """When floor is non-binding, PMA uses original base RWA (no floor increase)."""
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=500.0,
            risk_weight=0.25,  # Above floor
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        # PMA: 500 * 0.10 = 50 (no floor increase, so base is still 500)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(50.0)
        assert result["rwa"][0] == pytest.approx(550.0)

    def test_corporate_with_pma_no_floor_effect(self) -> None:
        """Corporate exposures: mortgage floor inapplicable, PMA uses base RWA."""
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="corporate",
            rwa=1000.0,
            risk_weight=0.50,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(100.0)
        assert result["rwa"][0] == pytest.approx(1100.0)

    def test_mixed_batch_sequencing(self) -> None:
        """Mixed mortgage+corporate batch: sequencing correct per-row.

        Why: Mortgage row has binding floor; corporate row doesn't.
        PMA must use different bases per row.
        """
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["MTG_1", "CORP_1"],
                "exposure_class": ["retail_mortgage", "corporate"],
                "rwa": [100.0, 1000.0],
                "risk_weight": [0.05, 0.50],
                "ead_final": [2000.0, 2000.0],
                "expected_loss": [5.0, 50.0],
                # Both rows NON-defaulted, so the Art. 154(4A)(b) scope gate is a
                # no-op here and every asserted value below is preserved exactly.
                # The column is emitted because the transform reads it per row.
                "is_defaulted": [False, False],
            }
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        # Mortgage row: (a) = 100 * 0.10 = 10 on the base; (b) then needs
        # 0.10 * 2000 = 200 against a post-(a) 110, so 90; total 200.
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(10.0)
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(90.0)
        assert result["rwa"][0] == pytest.approx(200.0)
        # Corporate row: no floor limb, so (a) alone: 1000 * 0.10 = 100.
        # The load-bearing half of this test — limb (a) is computed on each
        # row's own base, and the corporate row must be untouched by the
        # mortgage row's floor.
        assert result["mortgage_rw_floor_adjustment"][1] == pytest.approx(0.0)
        assert result["post_model_adjustment_rwa"][1] == pytest.approx(100.0)
        assert result["rwa"][1] == pytest.approx(1100.0)

    def test_rwa_pre_adjustments_records_original(self) -> None:
        """rwa_pre_adjustments captures original model RWA before any adjustment."""
        config, pack = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.15"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.pipe(apply_post_model_adjustments, config, pack=pack).collect()
        assert result["rwa_pre_adjustments"][0] == pytest.approx(200.0)


class TestPMAELMonotonicity:
    """Art. 158(6A): PMA EL adjustments can only increase expected loss.

    Why: Art. 158(6A) explicitly requires that post-model EL adjustments
    result in EL >= pre-adjustment EL. A negative pma_el_scalar would
    decrease EL and understate capital shortfall.
    """

    def test_negative_pma_el_scalar_rejected(self) -> None:
        """Negative pma_el_scalar raises ValueError at config construction."""
        with pytest.raises(ValueError, match="pma_el_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(pma_el_scalar=Decimal("-0.05"))

    def test_negative_pma_rwa_scalar_rejected(self) -> None:
        """Negative pma_rwa_scalar raises ValueError."""
        with pytest.raises(ValueError, match="pma_rwa_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(pma_rwa_scalar=Decimal("-0.01"))

    def test_negative_unrecognised_scalar_rejected(self) -> None:
        """Negative unrecognised_exposure_scalar raises ValueError."""
        with pytest.raises(ValueError, match="unrecognised_exposure_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(unrecognised_exposure_scalar=Decimal("-0.10"))

    def test_negative_mortgage_floor_rejected(self) -> None:
        """Negative mortgage_rw_floor raises ValueError."""
        with pytest.raises(ValueError, match="mortgage_rw_floor must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(mortgage_rw_floor=Decimal("-0.05"))

    def test_zero_el_scalar_allowed(self) -> None:
        """Zero pma_el_scalar is valid (no EL adjustment)."""
        config = PostModelAdjustmentConfig.basel_3_1(pma_el_scalar=Decimal("0.0"))
        assert config.pma_el_scalar == Decimal("0.0")

    def test_el_adjustment_floored_at_zero_in_calculation(self) -> None:
        """Even if somehow a zero scalar is passed, EL adjustment never negative.

        Why: The calculation itself floors post_model_adjustment_el at 0,
        providing defense-in-depth beyond the config validation.
        """
        config, pack = _b31_config(pma_el_scalar=Decimal("0.0"))
        result = (
            _make_irb_frame(expected_loss=10.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["post_model_adjustment_el"][0] >= 0.0
        assert result["el_after_adjustment"][0] >= result["el_pre_adjustment"][0]

    def test_positive_el_scalar_increases_el(self) -> None:
        """Positive EL scalar correctly increases expected loss."""
        config, pack = _b31_config(pma_el_scalar=Decimal("0.20"))
        result = (
            _make_irb_frame(expected_loss=100.0)
            .pipe(apply_post_model_adjustments, config, pack=pack)
            .collect()
        )
        assert result["el_pre_adjustment"][0] == pytest.approx(100.0)
        assert result["post_model_adjustment_el"][0] == pytest.approx(20.0)
        assert result["el_after_adjustment"][0] == pytest.approx(120.0)

    def test_crr_disabled_config_allows_zero_defaults(self) -> None:
        """CRR config (disabled=True) passes validation with zero defaults."""
        config = PostModelAdjustmentConfig.crr()
        assert config.enabled is False
        assert config.pma_el_scalar == Decimal("0.0")


# =============================================================================
# P1.319 — the Art. 154(4A)(b) scope of the mortgage RWEA floor
# =============================================================================

#: Every P1.319 row carries the same exposure value, so a floor add-on is
#: readable as ``(floor - modelled RW) x EAD`` without a per-row lookup.
_P1319_EAD: float = 10_000_000.0

#: The Basel 3.1 ``mortgage_rw_floor`` pack scalar (PS1/26 Art. 154(4A)(b)),
#: injected through ``_b31_config`` so the expected values below are exact and
#: independent of the pack. ``test_p1319_injected_floor_matches_the_pack_scalar``
#: pins it back to the pack, so a pack move fails loudly on that one assertion
#: rather than scattering across the whole table.
_P1319_FLOOR: Decimal = Decimal("0.10")

#: The seven-row scope frame of the P1.319 design, plus the eighth hardening row.
#: Columns: (reference, exposure_class, is_defaulted, risk_weight, rwa, EL).
#: ``exposure_class`` values are taken from ``ExposureClass`` rather than typed as
#: strings — a hand-written class name that is not an enum member would silently
#: fall to the ``otherwise`` branch and the row would prove nothing.
_P1319_ROWS: tuple[tuple[str, str, bool | None, float, float, float], ...] = (
    # 1 L1-DEMO      the ORC-140 replica: defaulted, Art. 154(1)(a) drives RW to 0
    ("P1319_DEF_RRE", ExposureClass.RETAIL_MORTGAGE.value, True, 0.00, 0.0, 500_000.0),
    # 2 L1-CONTROL   in scope on BOTH limbs — must be bit-identical before/after
    ("P1319_LIVE_RRE", ExposureClass.RETAIL_MORTGAGE.value, False, 0.04, 400_000.0, 5_000.0),
    # 3 L2-DEMO-a    the ORC-141 replica: matched the old regex through "MORTGAGE"
    ("P1319_CRE", ExposureClass.COMMERCIAL_MORTGAGE.value, False, 0.04, 400_000.0, 20_000.0),
    # 4 L2-DEMO-b    the SA loan-splitter's non-retail RRE child
    ("P1319_RESI_SA", ExposureClass.RESIDENTIAL_MORTGAGE.value, False, 0.04, 400_000.0, 20_000.0),
    # 5 L2-GUARD     Art. 147(5C) other retail — zero on both sides; the sole
    #                catcher of an over-broad ``starts_with("retail")`` gate
    ("P1319_RET_OTH", ExposureClass.RETAIL_OTHER.value, False, 0.04, 400_000.0, 30_000.0),
    # 6 L1-NULL-GUARD null is_defaulted resolves to NOT defaulted (conservative)
    ("P1319_NULL_DEF", ExposureClass.RETAIL_MORTGAGE.value, None, 0.04, 400_000.0, 5_000.0),
    # 7 L1-PROXY-KILLER defaulted WITH a positive modelled RW — see its own test
    ("P1319_DEF_RRE_RW", ExposureClass.RETAIL_MORTGAGE.value, True, 0.04, 400_000.0, 350_000.0),
    # 8 L1-ZERO-RW-KILLER non-defaulted WITH a zero modelled RW — see its own test
    ("P1319_ND_RRE_ZERO", ExposureClass.RETAIL_MORTGAGE.value, False, 0.00, 0.0, 500_000.0),
)

#: reference -> (mortgage_rw_floor_adjustment, rwa) once Art. 154(4A)(b) scope is
#: honoured. The trailing comment on each line is what the PRE-fix engine
#: produces, i.e. the fail-first evidence.
_P1319_EXPECTED: dict[str, tuple[float, float]] = {
    "P1319_DEF_RRE": (0.0, 0.0),  # pre-fix 1,000,000.00 / 1,000,000.00
    "P1319_LIVE_RRE": (600_000.0, 1_000_000.0),  # unchanged by the fix
    "P1319_CRE": (0.0, 400_000.0),  # pre-fix   600,000.00 / 1,000,000.00
    "P1319_RESI_SA": (0.0, 400_000.0),  # pre-fix   600,000.00 / 1,000,000.00
    "P1319_RET_OTH": (0.0, 400_000.0),  # unchanged by the fix
    "P1319_NULL_DEF": (600_000.0, 1_000_000.0),  # unchanged by the fix
    "P1319_DEF_RRE_RW": (0.0, 400_000.0),  # pre-fix   600,000.00 / 1,000,000.00
    "P1319_ND_RRE_ZERO": (1_000_000.0, 1_000_000.0),  # unchanged by the fix
}

#: The seven columns ``apply_post_model_adjustments`` is contractually required to
#: emit on EVERY row of EVERY regime. C 08.01 cols 0251-0254 and 0280-0282 read
#: them directly, so a dropped column or a null silently zeroes a published cell.
_P1319_PMA_COLUMNS: tuple[str, ...] = (
    "rwa_pre_adjustments",
    "post_model_adjustment_rwa",
    "mortgage_rw_floor_adjustment",
    "unrecognised_exposure_adjustment",
    "el_pre_adjustment",
    "post_model_adjustment_el",
    "el_after_adjustment",
)


def _make_p1319_frame() -> pl.LazyFrame:
    """The P1.319 scope frame — every row at the same EAD, PMA scalars at zero."""
    return pl.LazyFrame(
        {
            "exposure_reference": [row[0] for row in _P1319_ROWS],
            "exposure_class": [row[1] for row in _P1319_ROWS],
            "is_defaulted": pl.Series([row[2] for row in _P1319_ROWS], dtype=pl.Boolean),
            "risk_weight": [row[3] for row in _P1319_ROWS],
            "rwa": [row[4] for row in _P1319_ROWS],
            "ead_final": [_P1319_EAD] * len(_P1319_ROWS),
            "expected_loss": [row[5] for row in _P1319_ROWS],
        }
    )


@pytest.fixture(scope="module")
def p1319_b31() -> dict[str, dict[str, float]]:
    """Run the P1.319 frame through the Basel 3.1 branch; index it by reference."""
    config, pack = _b31_config(mortgage_rw_floor=_P1319_FLOOR)
    result = _make_p1319_frame().pipe(apply_post_model_adjustments, config, pack=pack).collect()
    return {row["exposure_reference"]: row for row in result.to_dicts()}


@pytest.fixture(scope="module")
def p1319_b31_frame() -> pl.DataFrame:
    """The same run, unindexed, for the total and presence assertions."""
    config, pack = _b31_config(mortgage_rw_floor=_P1319_FLOOR)
    return _make_p1319_frame().pipe(apply_post_model_adjustments, config, pack=pack).collect()


class TestMortgageFloorScopeArt154_4Ab:
    """PS1/26 Art. 154(4A)(b): the 10% RWEA floor has a scope, and the engine ignored it.

    Verbatim (``ps126app1.pdf``, Art. 154(4A)):

        (b) any amount needed to ensure that risk-weighted exposure amounts for
        NON-DEFAULTED exposures which are RETAIL exposures secured by UK
        RESIDENTIAL immovable property are greater than or equal to 10% of the
        exposure value for such exposures ...

    Three cumulative conditions. Before P1.319 the gate matched ``exposure_class``
    against the regex ``MORTGAGE|RESIDENTIAL`` and tested none of them, so the
    floor reached defaulted exposures (ORC-140) and commercial real estate
    (ORC-141). This class pins the first two:

    - **non-defaulted** — exactly, off ``is_defaulted``;
    - **retail secured by residential immovable property** — via the engine's
      closest available proxy, ``ExposureClass.RETAIL_MORTGAGE``, which is
      OVER-INCLUSIVE of retail exposures secured only by COMMERCIAL property
      (``hierarchy/enrich.py`` computes ``property_collateral_value`` over both
      property kinds by design, so ``classify/attributes.py`` sets ``is_mortgage``
      for either). That residual is conservative and is a separate item.

    The **UK** limb is not implementable — no property-country column reaches the
    IRB branch — so ``ORC-142`` stays a recorded disagreement.

    Direction: the floor can only ADD RWEA, so every limb of this narrowing
    REMOVES RWEA. That is why rows 2, 5, 6 and 8 are here: a change that moved
    them would have over-reached in the capital-shortfall direction.
    """

    def test_p1319_injected_floor_matches_the_pack_scalar(self) -> None:
        """The floor this frame is built on is the production Basel 3.1 pack value.

        Anchors the whole expected table to the rulepack rather than to a number
        typed next to the assertions. If the pack scalar moves, this fails first
        and says so, instead of the table failing for an unrelated reason.
        """
        # Arrange / Act
        pack_floor = resolve("b31", date(2028, 3, 31)).scalar("mortgage_rw_floor")

        # Assert
        assert pack_floor == _P1319_FLOOR

    def test_p1319_exposure_classes_are_real_enum_members(self) -> None:
        """Every class string in the frame is an actual ``ExposureClass`` member.

        A class name that is not an enum member would fall to the ``otherwise``
        branch for the wrong reason and the row would pass while proving nothing
        — the shape that let ``C02_00_SA_CLASS_MAP`` zero-fill for its whole life.
        """
        # Arrange / Act
        used = {row[1] for row in _P1319_ROWS}

        # Assert
        assert used <= {member.value for member in ExposureClass}

    @pytest.mark.parametrize("reference", list(_P1319_EXPECTED))
    def test_p1319_floor_add_on_and_rwea_per_row(
        self, reference: str, p1319_b31: dict[str, dict[str, float]]
    ) -> None:
        """Each row takes the Art. 154(4A)(b) add-on its scope entitles it to.

        Arrange: the eight-row scope frame at a 10% pack floor, PMA scalars zero.
        Act:     one ``apply_post_model_adjustments`` pass over the whole frame.
        Assert:  the row's floor add-on and post-adjustment RWEA.
        """
        # Arrange / Act
        row = p1319_b31[reference]
        expected_adjustment, expected_rwa = _P1319_EXPECTED[reference]

        # Assert
        assert row["mortgage_rw_floor_adjustment"] == pytest.approx(expected_adjustment)
        assert row["rwa"] == pytest.approx(expected_rwa)

    def test_p1319_defaulted_retail_mortgage_with_positive_rw_loses_the_floor(
        self, p1319_b31: dict[str, dict[str, float]]
    ) -> None:
        """``is_defaulted`` is the carrier — ``risk_weight`` and ``rwa`` are not proxies.

        DO NOT DELETE THIS ROW AS REDUNDANT WITH ``P1319_DEF_RRE``. Twenty-four
        candidate gates were mutation-tested against the six-row frame this design
        started from. ``P1319_DEF_RRE_RW`` is the SOLE killer of three of them:

            (risk_weight > 0) & (exposure_class == "retail_mortgage")
            (rwa > 0)         & (exposure_class == "retail_mortgage")
            ~(is_defaulted & (risk_weight == 0)) & (exposure_class == ...)

        All three survive without it, because every OTHER defaulted row in the
        frame models to RW 0 — under F-IRB a defaulted row takes ``K = 0``
        unconditionally, and the A-IRB replica sets ``LGD = BEEL``. That
        coincidence is exactly what invites "defaulted <=> RW 0" as a shortcut.

        This row breaks the coincidence: it is DEFAULTED and models to
        ``risk_weight = 0.04``, identical to the non-defaulted control
        ``P1319_LIVE_RRE``, so the two rows differ ONLY in ``is_defaulted``.
        Production reaches it whenever an A-IRB defaulted mortgage has
        ``LGD > BEEL``: Art. 154(1)(a) then gives ``K > 0`` and hence ``RW > 0``
        on an exposure Art. 154(4A)(b) still excludes.

        ``P1319_DEF_RRE`` is the ORC-140 replica and is the only row proving the
        full ``0.10 x EAD`` over-statement; neither row substitutes for the other.
        """
        # Arrange / Act
        defaulted = p1319_b31["P1319_DEF_RRE_RW"]
        control = p1319_b31["P1319_LIVE_RRE"]

        # Assert — same class, same modelled RW, same EAD; only the flag differs
        assert defaulted["risk_weight"] == pytest.approx(control["risk_weight"])
        assert defaulted["exposure_class"] == control["exposure_class"]
        assert defaulted["mortgage_rw_floor_adjustment"] == pytest.approx(0.0)
        assert control["mortgage_rw_floor_adjustment"] == pytest.approx(600_000.0)

    def test_p1319_non_defaulted_retail_mortgage_modelling_to_zero_rw_keeps_the_floor(
        self, p1319_b31: dict[str, dict[str, float]]
    ) -> None:
        """A zero modelled RW does not put a NON-defaulted mortgage out of scope.

        The mirror image of the row above, and the capital-SHORTFALL direction.
        Three further wrong gates survive the seven-row frame, the strongest being

            (risk_weight != 0) & ~is_defaulted & (exposure_class == "retail_mortgage")

        which drops the floor from a non-defaulted retail mortgage that happens to
        model to RW 0 — precisely the case Art. 154(4A)(b) exists to catch, since
        the floor's whole purpose is to bind where the model output is lowest.
        The same row also kills the EL-threshold survivors, which read
        ``expected_loss`` as a default proxy.

        This combination is not reachable under Basel 3.1 today (the retail-RRE
        LGD and PD input floors keep a non-defaulted modelled RW off zero), so
        this is hardening rather than a live defect — but the gate must not
        DEPEND on that, because the coupling is a floor value away from breaking.

        With ``P1319_DEF_RRE`` this row also closes the question structurally,
        not case by case. The two are IDENTICAL on every column the transform can
        read — same class, same ``risk_weight`` 0.00, same ``rwa`` 0.00, same
        ``expected_loss`` 500,000.00, same ``ead_final`` — and differ ONLY in
        ``is_defaulted``, while their required add-ons differ by the full
        ``0.10 x EAD``. No gate that fails to read ``is_defaulted`` can satisfy
        both, whatever it reads instead.
        """
        # Arrange / Act
        row = p1319_b31["P1319_ND_RRE_ZERO"]
        defaulted_twin = p1319_b31["P1319_DEF_RRE"]

        # Assert — the twins differ in the flag and nothing else the gate can see
        for column in ("exposure_class", "risk_weight", "rwa_pre_adjustments", "ead_final"):
            assert row[column] == defaulted_twin[column], f"the twins diverged on {column}"
        assert row["el_pre_adjustment"] == pytest.approx(defaulted_twin["el_pre_adjustment"])
        assert row["is_defaulted"] is False and defaulted_twin["is_defaulted"] is True

        # Assert — the floor binds in full: 0.10 x 10,000,000
        assert row["mortgage_rw_floor_adjustment"] == pytest.approx(1_000_000.0)
        assert row["rwa"] == pytest.approx(1_000_000.0)

    def test_p1319_null_default_flag_resolves_to_non_defaulted(
        self, p1319_b31: dict[str, dict[str, float]]
    ) -> None:
        """A null ``is_defaulted`` keeps the floor — the conservative side.

        ``is_defaulted`` genuinely reaches this branch null in production (the
        ``crm_exit`` edge column has ``fill_null_default=False``), and
        ``apply_defaulted_treatment`` in the same module already resolves it with
        ``fill_null(False)``. Resolving it the other way would REMOVE RWEA on a
        missing input, which is the direction a data gap must never take.
        """
        # Arrange / Act
        row = p1319_b31["P1319_NULL_DEF"]

        # Assert
        assert row["mortgage_rw_floor_adjustment"] == pytest.approx(600_000.0)
        assert row["rwa"] == pytest.approx(1_000_000.0)

    def test_p1319_frame_totals(self, p1319_b31_frame: pl.DataFrame) -> None:
        """The frame's column totals, so a per-row regression cannot net to zero.

        Pre-fix the engine produces ``5,000,000.00`` of floor add-on and
        ``7,400,000.00`` of RWEA on this frame — a 40.5% over-statement.
        """
        # Arrange / Act
        totals = {
            name: p1319_b31_frame[name].sum()
            for name in ("ead_final", "rwa_pre_adjustments", "mortgage_rw_floor_adjustment", "rwa")
        }

        # Assert
        assert totals["ead_final"] == pytest.approx(80_000_000.0)
        assert totals["rwa_pre_adjustments"] == pytest.approx(2_400_000.0)
        assert totals["mortgage_rw_floor_adjustment"] == pytest.approx(2_200_000.0)
        assert totals["rwa"] == pytest.approx(4_600_000.0)
        assert p1319_b31_frame["el_after_adjustment"].sum() == pytest.approx(1_430_000.0)

    def test_p1319_every_pma_column_is_emitted_and_non_null(
        self, p1319_b31_frame: pl.DataFrame
    ) -> None:
        """All seven PMA columns exist and carry a value on every row.

        The fix must set an out-of-scope add-on to ``0.0`` — NEVER to null and
        never by dropping the column. C 08.01 col 0253 is
        ``Sum("mortgage_rw_floor_adjustment")``; a null there is indistinguishable
        from a legitimate zero in the template and would zero the cell for the
        whole regime without anything raising.
        """
        # Arrange / Act
        emitted = set(p1319_b31_frame.columns)

        # Assert
        assert set(_P1319_PMA_COLUMNS) <= emitted
        for name in _P1319_PMA_COLUMNS:
            assert p1319_b31_frame[name].null_count() == 0, f"{name} published a null"

    def test_p1319_rwea_foots_to_its_components_on_every_row(
        self, p1319_b31_frame: pl.DataFrame
    ) -> None:
        """``rwa == pre + floor + pma + unrecognised`` per row — the C 08.01 footing.

        This is the ``0251 + 0252 + 0253 + 0254 = 0260`` identity at row level. A
        breakdown that silently drops a component still foots against a total that
        was computed the same wrong way, so it is asserted against the sealed
        ``rwa`` rather than against a re-derived sum of the same parts.
        """
        # Arrange / Act
        footed = p1319_b31_frame.with_columns(
            (
                pl.col("rwa_pre_adjustments")
                + pl.col("mortgage_rw_floor_adjustment")
                + pl.col("post_model_adjustment_rwa")
                + pl.col("unrecognised_exposure_adjustment")
                - pl.col("rwa")
            )
            .abs()
            .alias("footing_gap")
        )

        # Assert
        assert footed["footing_gap"].max() == pytest.approx(0.0, abs=1e-6)
        assert footed["el_after_adjustment"].to_list() == pytest.approx(
            (footed["el_pre_adjustment"] + footed["post_model_adjustment_el"]).to_list()
        )

    def test_p1319_crr_branch_emits_every_pma_column_as_a_nil_control(self) -> None:
        """CRR: the PMA feature is off, so the same frame gets zero adjustments.

        The CRR limb is a NIL control, not a demonstration — ``packs/crr.py``
        carries ``Feature("post_model_adjustments", enabled=False)`` and the
        transform short-circuits. What matters is that it still emits the whole
        column set, because C 08.01 reads those columns on both regimes.
        """
        # Arrange
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        # Act
        result = _make_p1319_frame().pipe(apply_post_model_adjustments, config).collect()

        # Assert
        assert set(_P1319_PMA_COLUMNS) <= set(result.columns)
        for name in _P1319_PMA_COLUMNS:
            assert result[name].null_count() == 0, f"{name} published a null under CRR"
        for name in (
            "post_model_adjustment_rwa",
            "mortgage_rw_floor_adjustment",
            "unrecognised_exposure_adjustment",
            "post_model_adjustment_el",
        ):
            assert result[name].to_list() == pytest.approx([0.0] * len(_P1319_ROWS))
        assert result["rwa"].sum() == pytest.approx(2_400_000.0)
