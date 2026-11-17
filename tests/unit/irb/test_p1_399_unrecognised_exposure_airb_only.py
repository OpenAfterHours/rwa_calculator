"""
P1.399 - the unrecognised exposure adjustment reaches Advanced IRB legs only.

Pipeline stage: IRB calculator - ``engine/irb/adjustments.py::apply_post_model_adjustments``
    (limb (c) of Art. 154(4A), limb (b) of Art. 153(5A)).

Bug: the transform multiplied ``post_model_adjustments.unrecognised_exposure_scalar``
into the RWEA of EVERY formula-IRB leg, Foundation IRB included. The adjustment
is the one PS1/26 Art. 166D(6) defines, and that paragraph confines it to
facilities where "the institution would have applied the Advanced IRB Approach in
accordance with Article 147A" (166D(6)(a)(ii)) - it sits in Article 166D, the
Advanced IRB exposure-value article. Annex II p.112 then says column 0254 "shall
not be reported for sheets relating to the FIRB approach or the slotting
approach", so an F-IRB sheet's column 0260 exceeded 0251 + 0252 + 0253 + 0254 by
the F-IRB uplift and ``boe_b0751`` (ERROR) failed on any Basel 3.1 run with a
non-zero scalar.

The general post model adjustment (limb (a)) is an Art. 146(3) amount and still
reaches an F-IRB leg; only limb (c) is gated, and on the sealed ``approach``
column, never on the regime.

References:
    - PRA PS1/26 Art. 153(5A)(b), Art. 154(4A)(c), Art. 166D(6)
    - PRA PS1/26 Annex II §3.3.3 column 0254 (p.112)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PostModelAdjustmentConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.transforms import apply_post_model_adjustments

#: The modelled (paragraph 1/3/4) RWEA every leg below starts from.
BASE_RWEA = 1_000.0
#: A non-zero firm election for the unrecognised exposure adjustment.
UNRECOGNISED_SCALAR = Decimal("0.05")
#: A non-zero general post model adjustment (limb (a), Art. 146(3)).
GENERAL_PMA_SCALAR = Decimal("0.10")


def _legs(*approaches: ApproachType) -> pl.LazyFrame:
    """One non-retail corporate leg per approach, identical in everything else.

    Corporate, so the Art. 154(4A)(b) mortgage floor cannot reach any of them and
    the only difference between two legs is the approach.
    """
    count = len(approaches)
    return pl.LazyFrame(
        {
            "exposure_reference": [f"LEG_{i}" for i in range(count)],
            "approach": [approach.value for approach in approaches],
            "exposure_class": ["corporate"] * count,
            "rwa": [BASE_RWEA] * count,
            "risk_weight": [0.50] * count,
            "ead_final": [2_000.0] * count,
            "expected_loss": [10.0] * count,
            "is_defaulted": pl.Series([False] * count, dtype=pl.Boolean),
        }
    )


def _b31_config(
    unrecognised_scalar: Decimal = UNRECOGNISED_SCALAR,
    pma_rwa_scalar: Decimal = Decimal("0.0"),
) -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 3, 31),
        post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(
            pma_rwa_scalar=pma_rwa_scalar,
            unrecognised_exposure_scalar=unrecognised_scalar,
        ),
    )


def _adjust(lf: pl.LazyFrame, config: CalculationConfig) -> pl.DataFrame:
    return lf.pipe(apply_post_model_adjustments, config).collect()


def test_an_firb_legs_rwea_is_unchanged_by_a_non_zero_scalar() -> None:
    # Arrange
    legs = _legs(ApproachType.FIRB)

    # Act
    row = _adjust(legs, _b31_config()).row(0, named=True)

    # Assert
    assert row["unrecognised_exposure_adjustment"] == pytest.approx(0.0)
    assert row["rwa"] == pytest.approx(BASE_RWEA)


def test_an_airb_leg_is_still_uplifted_by_the_scalar() -> None:
    # Arrange
    legs = _legs(ApproachType.AIRB)
    uplift = BASE_RWEA * float(UNRECOGNISED_SCALAR)

    # Act
    row = _adjust(legs, _b31_config()).row(0, named=True)

    # Assert
    assert row["unrecognised_exposure_adjustment"] == pytest.approx(uplift)
    assert row["rwa"] == pytest.approx(BASE_RWEA + uplift)


def test_one_frame_holding_both_approaches_uplifts_only_the_airb_leg() -> None:
    """Both legs in one frame, so a gate that reads a per-frame value (or a
    column that is constant across the frame) cannot pass by coincidence."""
    # Arrange
    legs = _legs(ApproachType.FIRB, ApproachType.AIRB)
    uplift = BASE_RWEA * float(UNRECOGNISED_SCALAR)

    # Act
    result = _adjust(legs, _b31_config())

    # Assert
    assert result["unrecognised_exposure_adjustment"].to_list() == pytest.approx([0.0, uplift])
    assert result["rwa"].to_list() == pytest.approx([BASE_RWEA, BASE_RWEA + uplift])


def test_the_general_post_model_adjustment_still_reaches_an_firb_leg() -> None:
    """Limb (a) is an Art. 146(3) amount on the firm's rating systems, which an
    F-IRB leg has; gating the whole adjustment block on A-IRB would drop it."""
    # Arrange
    legs = _legs(ApproachType.FIRB)
    general = BASE_RWEA * float(GENERAL_PMA_SCALAR)

    # Act
    row = _adjust(legs, _b31_config(pma_rwa_scalar=GENERAL_PMA_SCALAR)).row(0, named=True)

    # Assert
    assert row["post_model_adjustment_rwa"] == pytest.approx(general)
    assert row["unrecognised_exposure_adjustment"] == pytest.approx(0.0)
    assert row["rwa"] == pytest.approx(BASE_RWEA + general)


def test_each_legs_rwea_foots_to_its_reported_components() -> None:
    """``rwa == rwa_pre_adjustments + the three adjustments`` on every leg - the
    per-leg form of OF 08.01 c0260 = c0251 + c0252 + c0253 + c0254."""
    # Arrange
    legs = _legs(ApproachType.FIRB, ApproachType.AIRB)

    # Act
    result = _adjust(legs, _b31_config(pma_rwa_scalar=GENERAL_PMA_SCALAR))
    footed = result.select(
        pl.col("rwa")
        - pl.col("rwa_pre_adjustments")
        - pl.col("post_model_adjustment_rwa")
        - pl.col("mortgage_rw_floor_adjustment")
        - pl.col("unrecognised_exposure_adjustment")
    ).to_series()

    # Assert
    assert footed.to_list() == pytest.approx([0.0, 0.0])
