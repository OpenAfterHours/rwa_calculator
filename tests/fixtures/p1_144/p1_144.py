"""
P1.144 fixture: IRBCalculator.calculate_expected_loss() EAD-fallback bug.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer (calculator.py)

Key responsibilities:
- Provide Frame A: irb_exposures-shaped LazyFrame with ``ead`` but no ``ead_final``.
  The method must fall back to ``ead`` when ``ead_final`` is absent.
- Provide Frame B: same single row with ``ead_final=750_000.0`` ADDED.
  The method must prefer ``ead_final`` over ``ead`` when both are present.

Defect under test (pre-fix):
    IRBCalculator.calculate_expected_loss() detects the EAD column with:
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
    If the bug is that the method raises KeyError / produces wrong EL when
    ``ead_final`` is absent, Frame A reproduces it.  Frame B confirms the
    ``ead_final`` path gives the lower (CRM-adjusted) EAD.

Hand-calculations:
    Frame A (ead_col = "ead"):
        EL = PD × LGD × EAD = 0.02 × 0.45 × 1_000_000 = 9_000.0

    Frame B (ead_col = "ead_final"):
        EL = PD × LGD × EAD_final = 0.02 × 0.45 × 750_000 = 6_750.0

    Expected-loss formula: CRR Art. 158(1) / PRA Art. 158(1).

Scenario inputs:
    exposure_reference  = "P1144-EXP-001"
    counterparty_reference = "P1144-CP-001"
    exposure_class      = "CORPORATE"
    approach            = "foundation_irb"
    is_airb             = False
    ead                 = 1_000_000.0   (gross, pre-CRM)
    pd                  = 0.02          (2%)
    lgd                 = 0.45          (F-IRB supervisory, senior unsecured)
    maturity            = 2.5
    is_defaulted        = False
    [Frame B only] ead_final = 750_000.0  (post-CRM, simulating 25% collateral coverage)

References:
    - CRR Art. 158(1): EL = PD × LGD × EAD.
    - src/rwa_calc/engine/irb/calculator.py: calculate_expected_loss() EAD selection.

Usage:
    from tests.fixtures.p1_144.p1_144 import (
        build_irb_exposures_without_ead_final,
        build_irb_exposures_with_ead_final,
        EAD,
        EAD_FINAL,
        PD,
        LGD,
        EXPECTED_EL_NO_EAD_FINAL,
        EXPECTED_EL_WITH_EAD_FINAL,
    )
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — referenced by the acceptance test for assertion values
# ---------------------------------------------------------------------------

EXPOSURE_REF = "P1144-EXP-001"
COUNTERPARTY_REF = "P1144-CP-001"

#: Gross EAD (pre-CRM). Used by Frame A as the only EAD column.
EAD: float = 1_000_000.0

#: CRM-adjusted EAD. Present in Frame B only.
EAD_FINAL: float = 750_000.0

PD: float = 0.02
LGD: float = 0.45
MATURITY: float = 2.5

#: EL when EAD fallback applies: PD × LGD × EAD = 0.02 × 0.45 × 1_000_000
EXPECTED_EL_NO_EAD_FINAL: float = PD * LGD * EAD  # 9_000.0

#: EL when ead_final is present: PD × LGD × EAD_FINAL = 0.02 × 0.45 × 750_000
EXPECTED_EL_WITH_EAD_FINAL: float = PD * LGD * EAD_FINAL  # 6_750.0


# ---------------------------------------------------------------------------
# Public builders — return LazyFrame directly (no parquet involved)
# ---------------------------------------------------------------------------


def build_irb_exposures_without_ead_final() -> pl.LazyFrame:
    """Return a single-row irb_exposures-shaped LazyFrame with no ``ead_final`` column.

    This is Frame A: the ``ead`` column is the sole EAD source.
    ``calculate_expected_loss`` must fall back to ``ead`` and produce
    EL = PD × LGD × EAD = 9_000.0.

    Columns match the irb_exposures shape accepted by
    ``IRBCalculator.calculate_expected_loss()``:
        exposure_reference, counterparty_reference, exposure_class, approach,
        is_airb, ead, pd, lgd, maturity, is_defaulted.

    ``ead_final`` is intentionally absent to exercise the fallback branch.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [EXPOSURE_REF],
            "counterparty_reference": [COUNTERPARTY_REF],
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
            "is_airb": [False],
            "ead": [EAD],
            "pd": [PD],
            "lgd": [LGD],
            "maturity": [MATURITY],
            "is_defaulted": [False],
        }
    )


def build_irb_exposures_with_ead_final() -> pl.LazyFrame:
    """Return a single-row irb_exposures-shaped LazyFrame WITH an ``ead_final`` column.

    This is Frame B: both ``ead`` (1_000_000) and ``ead_final`` (750_000) are
    present.  ``calculate_expected_loss`` must prefer ``ead_final`` and produce
    EL = PD × LGD × EAD_FINAL = 6_750.0.

    The gap between EAD and EAD_FINAL (250_000) simulates 25% collateral
    coverage applied by the CRM processor upstream — a realistic post-CRM
    scenario where the two columns will always differ.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [EXPOSURE_REF],
            "counterparty_reference": [COUNTERPARTY_REF],
            "exposure_class": ["CORPORATE"],
            "approach": ["foundation_irb"],
            "is_airb": [False],
            "ead": [EAD],
            "ead_final": [EAD_FINAL],
            "pd": [PD],
            "lgd": [LGD],
            "maturity": [MATURITY],
            "is_defaulted": [False],
        }
    )
