"""
P1.144 — IRBCalculator.calculate_expected_loss() must use ead_final as EAD basis.

Pipeline stage: IRBCalculator.calculate_expected_loss()

Bug: when ``ead_final`` is absent from the input frame the method falls back to
``ead`` for the calculation AND the output projection — meaning the returned
LazyFrame has no ``ead_final`` column.  This makes downstream consumers that
expect a stable ``ead_final`` column fail silently or produce incorrect EL
when ``ead_final`` and ``ead`` differ.

Fix (Option A — preferred): ensure ``ead_final`` always exists in the output
by materialising ``ead_final = ead`` when the column is absent, then computing
EL = pd × lgd × ead_final, and projecting ``ead_final`` (not the conditional
``ead_col``).

Expected outputs per scenario proposal:
    Frame A (no ead_final): EL = 0.02 × 0.45 × 1_000_000 = 9_000.0
                            output schema MUST contain ``ead_final``
    Frame B (ead_final=750_000): EL = 0.02 × 0.45 × 750_000 = 6_750.0
                                 (regression guard — should already pass)

References:
    - CRR Art. 158(1): EL = PD × LGD × EAD
    - src/rwa_calc/engine/irb/calculator.py: calculate_expected_loss()
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.calculator import IRBCalculator
from tests.fixtures.p1_144.p1_144 import (
    EXPECTED_EL_NO_EAD_FINAL,
    EXPECTED_EL_WITH_EAD_FINAL,
    build_irb_exposures_with_ead_final,
    build_irb_exposures_without_ead_final,
)

_REPORTING_DATE = date(2026, 1, 1)


# =============================================================================
# HELPERS
# =============================================================================


def _bundle_from(lf: pl.LazyFrame) -> CRMAdjustedBundle:
    """Wrap a LazyFrame in a minimal CRMAdjustedBundle."""
    return CRMAdjustedBundle(
        exposures=lf,
        sa_exposures=pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.Utf8)}),
        irb_exposures=lf,
    )


# =============================================================================
# P1.144 TESTS
# =============================================================================


class TestP1144ELEadFinalConsistency:
    """P1.144: calculate_expected_loss() must always emit ead_final in output schema.

    Regulatory basis: CRR Art. 158(1) — EL = PD × LGD × EAD.
    The EAD used for EL must be the CRM-adjusted EAD (ead_final) if present;
    when absent the method must synthesise ead_final = ead so the output
    schema is stable and correct EL is computed.
    """

    @pytest.fixture()
    def calc(self) -> IRBCalculator:
        """Shared IRBCalculator instance."""
        return IRBCalculator()

    @pytest.fixture()
    def config(self) -> CalculationConfig:
        """CRR config (reporting date 2026-01-01)."""
        return CalculationConfig.crr(_REPORTING_DATE)

    # -------------------------------------------------------------------------
    # Frame A — no ead_final column in input
    # -------------------------------------------------------------------------

    def test_p1_144_frame_a_ead_final_present_in_output_schema(
        self,
        calc: IRBCalculator,
        config: CalculationConfig,
    ) -> None:
        """Frame A: output schema must contain ead_final even when input does not.

        This is the primary failing assertion (pre-fix).  Currently the buggy
        code projects the raw ``ead`` column when ``ead_final`` is absent, so
        ``ead_final`` does not appear in the result schema.

        After the fix: the method synthesises ``ead_final = ead`` before
        projecting, ensuring the output schema always contains ``ead_final``.
        """
        # Arrange
        lf = build_irb_exposures_without_ead_final()
        bundle = _bundle_from(lf)

        # Act
        result = calc.calculate_expected_loss(bundle, config)
        schema_names = result.frame.collect_schema().names()

        # Assert — ead_final must be present (fails before fix)
        assert "ead_final" in schema_names, (
            f"Output schema must contain 'ead_final' even when input lacked it. "
            f"Got schema columns: {schema_names}"
        )

    def test_p1_144_frame_a_expected_loss_equals_9000(
        self,
        calc: IRBCalculator,
        config: CalculationConfig,
    ) -> None:
        """Frame A: EL = PD × LGD × EAD = 0.02 × 0.45 × 1_000_000 = 9_000.0.

        When ead_final is absent the calculator must fall back to ead,
        computing the correct EL of 9_000.0.
        """
        # Arrange
        lf = build_irb_exposures_without_ead_final()
        bundle = _bundle_from(lf)

        # Act
        result = calc.calculate_expected_loss(bundle, config)
        df = result.frame.collect()

        # Assert
        assert df["expected_loss"][0] == pytest.approx(EXPECTED_EL_NO_EAD_FINAL, abs=1e-6), (
            f"EL with no ead_final must equal {EXPECTED_EL_NO_EAD_FINAL} "
            f"(PD × LGD × EAD), got {df['expected_loss'][0]}"
        )

    # -------------------------------------------------------------------------
    # Frame B — ead_final=750_000 present in input (regression guard)
    # -------------------------------------------------------------------------

    def test_p1_144_frame_b_expected_loss_uses_ead_final(
        self,
        calc: IRBCalculator,
        config: CalculationConfig,
    ) -> None:
        """Frame B: EL = PD × LGD × ead_final = 0.02 × 0.45 × 750_000 = 6_750.0.

        Regression guard: when ead_final is already present the calculator
        must prefer it over ead (which equals 1_000_000 in Frame B).
        This should pass both before and after the fix.
        """
        # Arrange
        lf = build_irb_exposures_with_ead_final()
        bundle = _bundle_from(lf)

        # Act
        result = calc.calculate_expected_loss(bundle, config)
        df = result.frame.collect()

        # Assert
        assert df["expected_loss"][0] == pytest.approx(EXPECTED_EL_WITH_EAD_FINAL, abs=1e-6), (
            f"EL with ead_final present must equal {EXPECTED_EL_WITH_EAD_FINAL} "
            f"(PD × LGD × ead_final), got {df['expected_loss'][0]}"
        )

    def test_p1_144_frame_b_ead_final_present_in_output_schema(
        self,
        calc: IRBCalculator,
        config: CalculationConfig,
    ) -> None:
        """Frame B: output schema must contain ead_final (already true today).

        Confirms ead_final is projected when it exists in the input frame.
        Regression guard only.
        """
        # Arrange
        lf = build_irb_exposures_with_ead_final()
        bundle = _bundle_from(lf)

        # Act
        result = calc.calculate_expected_loss(bundle, config)
        schema_names = result.frame.collect_schema().names()

        # Assert
        assert "ead_final" in schema_names, (
            f"Output schema must contain 'ead_final'. Got: {schema_names}"
        )
