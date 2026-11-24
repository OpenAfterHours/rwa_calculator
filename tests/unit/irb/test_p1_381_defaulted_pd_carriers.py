"""
P1.381 - the IRB defaulted treatment sets the PD of an obligor in default to 100%.

Pipeline stage: IRB calculator - ``engine/irb/adjustments.py::apply_defaulted_treatment``
    (runs after the K / RWEA / EL batches, before guarantee substitution).

Bug: the treatment overrode K, correlation, maturity adjustment, RWEA, risk
weight and EL for a defaulted row but left ``pd`` and ``pd_floored`` at the
firm's performing estimate, so every PD-reading template reported a defaulted
obligor in a performing PD band.

Rule, both regimes: CRR Art. 160(3) "The PD of obligors in default shall be
100 %"; PS1/26 Art. 160(3) "An institution shall use a PD of 100% for obligors
in default"; Art. 163(2) the retail twin. It is the PD itself, not a floor, so
both the pre-input-floor ``pd`` and the post-input-floor ``pd_floored`` read 1.0.
Capital does not read a defaulted row's PD: K, RWEA and EL come from the
default flag, and those stay as they were.

References:
    - CRR Art. 160(3), 163(2); PRA PS1/26 Art. 160(3), 163(2)
    - CRR / PS1/26 Art. 153(1)(ii), 154(1)(i), 158(5)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.irb.adjustments import apply_defaulted_treatment

PD_PERFORMING = 0.006
EAD = 200_000.0
LGD = 0.20
BEEL = 0.05


def test_defaulted_row_carries_pd_100pct_on_both_bases() -> None:
    """Only the defaulted row moves; a null flag reads as not defaulted."""
    # Arrange
    frame = _post_formula_frame()

    # Act
    out = apply_defaulted_treatment(frame).collect()

    # Assert
    assert out["pd"].to_list() == [1.0, PD_PERFORMING, PD_PERFORMING]
    assert out["pd_floored"].to_list() == [1.0, PD_PERFORMING, PD_PERFORMING]


def test_defaulted_capital_is_set_from_the_default_flag_not_the_pd() -> None:
    """A-IRB defaulted: K = max(0, LGD - BEEL), RWEA = 12.5 x K x EAD, EL = BEEL x EAD."""
    # Arrange
    frame = _post_formula_frame()

    # Act
    defaulted = apply_defaulted_treatment(frame).collect().row(0, named=True)

    # Assert
    assert defaulted["k"] == pytest.approx(LGD - BEEL)
    assert defaulted["rwa"] == pytest.approx(12.5 * (LGD - BEEL) * EAD)
    assert defaulted["expected_loss"] == pytest.approx(BEEL * EAD)


def _post_formula_frame() -> pl.LazyFrame:
    """Three A-IRB rows after the formula batches, all at the performing PD."""
    rows = [
        {"is_defaulted": True},
        {"is_defaulted": False},
        {"is_defaulted": None},
    ]
    return pl.DataFrame(
        [
            {
                **row,
                "is_airb": True,
                "pd": PD_PERFORMING,
                "pd_floored": PD_PERFORMING,
                "lgd_floored": LGD,
                "beel": BEEL,
                "ead_final": EAD,
                "k": 0.03,
                "correlation": 0.15,
                "maturity_adjustment": 1.0,
                "rwa": 0.03 * 12.5 * EAD,
                "risk_weight": 0.03 * 12.5,
                "expected_loss": PD_PERFORMING * LGD * EAD,
            }
            for row in rows
        ],
        schema_overrides={"is_defaulted": pl.Boolean},
    ).lazy()
