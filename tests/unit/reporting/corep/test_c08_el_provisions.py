"""COREP C 08.01/02/03 expected-loss + provisions carrier tests (R10).

Two rectifications, both proven here on synthetic ledger-shim frames:

(a) Col 0280 (EL pre post-model adjustment) and its B31 twin 0282 (EL after
    adjustments) coalesce PER LEG. The formula-IRB adjustment columns
    ``el_pre_adjustment`` / ``el_after_adjustment`` are NULL on slotting legs
    (their EL rides on ``expected_loss`` from the slotting calculator), so the
    retired ``Sum`` with null-fill masked the slotting EL as 0.0 while C 08.06
    col 0090 reported it correctly. The coalesce reads the adjustment EL where
    non-null else ``expected_loss`` — a value no-op on formula-IRB legs.

(b) The provisions ladder (C 08.01/02 col 0290, C 08.03 col 0110, C 08.06 col
    0100) fell back to ``provision_held`` — an input pass-through the aggregator
    seal strips — so every real submission rendered a hard 0.0. It now falls
    back to the sealed ``provision_allocated`` when the base scra/gcra sum nets
    to ~0. ``provision_allocated`` (not C 07.00's ``provision_deducted``) is the
    correct carrier for the IRB templates: the Art. 111(2) drawn-first deduction
    is SA-only, so ``provision_deducted`` is structurally 0.0 on every IRB leg.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row

# =============================================================================
# Part (a) fixtures — formula-IRB + slotting EL coalesce
# =============================================================================


def _formula_and_slotting_b31() -> pl.LazyFrame:
    """Formula-IRB corporate + slotting specialised-lending in one run (B31).

    Corporate: 2 foundation-IRB rows carrying the post-model-adjustment EL
    columns (el_pre_adjustment / el_after_adjustment). Specialised lending:
    2 slotting rows (project_finance) whose adjustment EL columns are NULL —
    the real EL rides on expected_loss (30 + 45 = 75).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["CORP_1", "CORP_2", "SL_1", "SL_2"],
            "counterparty_reference": ["CP_A", "CP_B", "CP_S1", "CP_S2"],
            "approach_applied": ["foundation_irb", "foundation_irb", "slotting", "slotting"],
            "exposure_class": [
                "corporate",
                "corporate",
                "specialised_lending",
                "specialised_lending",
            ],
            "drawn_amount": [1000.0, 2000.0, 1500.0, 2500.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "nominal_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 1500.0, 2500.0],
            "rwa_final": [700.0, 1200.0, 750.0, 2250.0],
            "risk_weight": [0.70, 0.60, 0.50, 0.90],
            "pd_floored": [0.005, 0.01, None, None],
            "lgd_floored": [0.45, 0.45, None, None],
            "irb_maturity_m": [2.5, 3.0, None, None],
            "expected_loss": [100.0, 200.0, 30.0, 45.0],
            "el_pre_adjustment": [100.0, 200.0, None, None],
            "post_model_adjustment_el": [10.0, 20.0, None, None],
            "el_after_adjustment": [110.0, 220.0, None, None],
            # Slotting routing columns for C 08.06.
            "sl_type": [None, None, "project_finance", "project_finance"],
            "slotting_category": [None, None, "strong", "good"],
            "is_short_maturity": [None, None, True, False],
            "is_hvcre": [None, None, False, False],
        }
    )


def _single_class_mixed_b31() -> pl.LazyFrame:
    """One class (corporate) with a formula-IRB leg AND a slotting leg (B31).

    Proves the per-ROW coalesce on a single sheet: the formula leg keeps its
    el_pre_adjustment (100 / el_after 112), the slotting leg (adjustment EL
    NULL) contributes its expected_loss (40).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["CORP_F", "CORP_S"],
            "counterparty_reference": ["CP_F", "CP_S"],
            "approach_applied": ["foundation_irb", "slotting"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [1000.0, 800.0],
            "undrawn_amount": [0.0, 0.0],
            "nominal_amount": [0.0, 0.0],
            "ead_final": [1000.0, 800.0],
            "rwa_final": [700.0, 640.0],
            "risk_weight": [0.70, 0.80],
            "pd_floored": [0.005, None],
            "lgd_floored": [0.45, None],
            "irb_maturity_m": [2.5, None],
            "expected_loss": [100.0, 40.0],
            "el_pre_adjustment": [100.0, None],
            "post_model_adjustment_el": [12.0, None],
            "el_after_adjustment": [112.0, None],
            "sl_type": [None, "object_finance"],
            "slotting_category": [None, "strong"],
            "is_short_maturity": [None, False],
            "is_hvcre": [None, False],
        }
    )


class TestC0801ExpectedLossSlottingCoalesce:
    """R10a: the slotting EL memo columns 0280/0282 coalesce per leg."""

    def test_slotting_sheet_0280_reports_real_el_not_masked_zero(self) -> None:
        """The slotting class sheet's 0280 surfaces the real slotting EL (75),
        not the 0.0 the retired Sum(el_pre_adjustment) null-fill produced."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_formula_and_slotting_b31(), framework="BASEL_3_1")

        sl_total = _get_total_row(bundle.c08_01["specialised_lending"])
        # SL slotting expected_loss: 30 + 45 = 75 (retired code reported 0.0).
        assert sl_total["0280"][0] == pytest.approx(75.0)

    def test_slotting_sheet_0282_reports_real_el_not_masked_zero(self) -> None:
        """0282 (EL after adjustments) also coalesces to expected_loss on
        slotting legs — slotting has no post-model adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_formula_and_slotting_b31(), framework="BASEL_3_1")

        sl_total = _get_total_row(bundle.c08_01["specialised_lending"])
        assert sl_total["0282"][0] == pytest.approx(75.0)

    def test_slotting_sheet_0280_cross_checks_c0806_0090(self) -> None:
        """Cross-template tie-out: the slotting EL in C 08.01 col 0280 equals the
        same slotting EL C 08.06 col 0090 reports (its two maturity Total rows)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_formula_and_slotting_b31(), framework="BASEL_3_1")

        sl_0280 = _get_total_row(bundle.c08_01["specialised_lending"])["0280"][0]
        pf = bundle.c08_06["project_finance"]
        # Rows 0110 (short-maturity Total) + 0120 (long-maturity Total), col 0090.
        c0806_el = float(pf.filter(pl.col("row_ref").is_in(["0110", "0120"]))["0090"].sum())
        assert sl_0280 == pytest.approx(75.0)
        assert sl_0280 == pytest.approx(c0806_el)

    def test_formula_irb_sheet_0280_reads_el_pre_adjustment_unchanged(self) -> None:
        """A pure formula-IRB sheet is a value no-op: 0280 == sum el_pre_adjustment
        (== expected_loss there), 0282 == sum el_after_adjustment."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_formula_and_slotting_b31(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0280"][0] == pytest.approx(300.0)  # 100 + 200
        assert corp["0282"][0] == pytest.approx(330.0)  # 110 + 220

    def test_mixed_sheet_0280_coalesces_per_row(self) -> None:
        """A single sheet mixing formula-IRB and slotting legs: 0280 sums the
        PER-ROW pick — el_pre_adjustment (100) for the formula leg, expected_loss
        (40) for the slotting leg = 140 (retired code masked to 100)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_single_class_mixed_b31(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0280"][0] == pytest.approx(140.0)  # 100 (el_pre) + 40 (expected_loss)

    def test_mixed_sheet_0282_coalesces_per_row(self) -> None:
        """0282 on the mixed sheet: el_after_adjustment (112) for the formula leg,
        expected_loss (40) for the slotting leg = 152."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_single_class_mixed_b31(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0282"][0] == pytest.approx(152.0)  # 112 (el_after) + 40 (expected_loss)


# =============================================================================
# Part (b) fixtures — provisions sealed-carrier fallback
# =============================================================================


def _irb_provisions_allocated_only() -> pl.LazyFrame:
    """The shape of a real IRB submission: NO scra/gcra and NO provision_held
    (the seal strips them), but the sealed provision_allocated carries the
    provisions. provision_deducted is 0.0 (Art. 111(2) is SA-only), proving the
    carrier choice — reading provision_deducted would report 0.0."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_1", "IRB_2"],
            "counterparty_reference": ["CP_A", "CP_B"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [1000.0, 2000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [1000.0, 2000.0],
            "rwa_final": [700.0, 1200.0],
            "risk_weight": [0.70, 0.60],
            "pd_floored": [0.005, 0.01],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "expected_loss": [100.0, 200.0],
            "provision_allocated": [100.0, 50.0],
            "provision_deducted": [0.0, 0.0],
        }
    )


def _irb_provisions_scra_preferred() -> pl.LazyFrame:
    """A book supplying non-degenerate scra/gcra keeps that granular base over
    the sealed provision_allocated fallback."""
    return _irb_provisions_allocated_only().with_columns(
        pl.Series("scra_provision_amount", [30.0, 10.0]),
        pl.Series("gcra_provision_amount", [5.0, 0.0]),
    )


def _irb_provisions_held_and_allocated() -> pl.LazyFrame:
    """provision_held present (a synthetic/legacy frame) wins over
    provision_allocated in the fallback — preserving the retired behaviour."""
    return _irb_provisions_allocated_only().with_columns(
        pl.Series("provision_held", [80.0, 20.0]),
    )


def _irb_pd_bucket_allocated_only() -> pl.LazyFrame:
    """A single foundation-IRB corporate exposure (PD 0.01 -> the
    '1.00 to < 2.50%' C 08.03 bucket) carrying only the sealed
    provision_allocated — no scra/gcra, no provision_held."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_1"],
            "counterparty_reference": ["CP_A"],
            "approach_applied": ["foundation_irb"],
            "exposure_class": ["corporate"],
            "drawn_amount": [1000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "ead_final": [1000.0],
            "rwa_final": [700.0],
            "risk_weight": [0.70],
            "pd_floored": [0.01],
            "lgd_floored": [0.45],
            "irb_maturity_m": [2.5],
            "expected_loss": [60.0],
            "provision_allocated": [60.0],
            "provision_deducted": [0.0],
        }
    )


class TestC08ProvisionsSealedCarrier:
    """R10b: the provisions ladder falls back to the sealed provision_allocated
    when the scra/gcra base nets to ~0 — the retired provision_held fallback was
    dead on every real submission."""

    def test_col_0290_falls_back_to_provision_allocated(self) -> None:
        """C 08.01 col 0290 reports -provision_allocated (Annex II §1.3) on a
        real IRB submission carrying no scra/gcra and no provision_held."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_provisions_allocated_only())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # provision_allocated 100 + 50 = 150; emitted negative per §1.3.
        assert corp["0290"][0] == pytest.approx(-150.0)

    def test_col_0290_meaningful_on_irb_legs_not_provision_deducted(self) -> None:
        """The carrier is provision_allocated, not provision_deducted: the frame
        carries provision_deducted = 0.0 (SA-only Art. 111(2) deduction), so a
        provision_deducted fallback would report 0.0 — 0290 reports -150."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_provisions_allocated_only())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0290"][0] != pytest.approx(0.0)
        assert corp["0290"][0] == pytest.approx(-150.0)

    def test_scra_gcra_preferred_over_sealed_carrier(self) -> None:
        """Non-degenerate scra/gcra base (35 + 10 = 45) wins over the sealed
        provision_allocated (150)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_provisions_scra_preferred())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0290"][0] == pytest.approx(-45.0)

    def test_provision_held_preferred_over_provision_allocated(self) -> None:
        """provision_held (a synthetic/legacy frame) is preferred over
        provision_allocated in the fallback — the retired behaviour is a strict
        subset, so those tests stay green."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_provisions_held_and_allocated())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # provision_held 80 + 20 = 100 wins over provision_allocated (150).
        assert corp["0290"][0] == pytest.approx(-100.0)

    def test_c08_03_col_0110_falls_back_to_provision_allocated(self) -> None:
        """The shared _provisions_postfix fixes C 08.03 col 0110 too: the PD
        bucket reports +provision_allocated (0110 is not negated)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_bucket_allocated_only())

        corp = bundle.c08_03["corporate"]
        # One populated bucket; 0110 is positive (C 08.03 has no §1.3 negation).
        assert float(corp["0110"].sum()) == pytest.approx(60.0)
