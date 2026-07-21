"""COREP C 07.00 col 0030 provisions-carrier tests (R9).

The SCRA/GCRA input pass-throughs are never sealed on the aggregator exit, so
a real submission must report the sealed SA Art. 111(2) deducted provision
(``provision_deducted``) in col 0030 instead of the hard 0.0 the retired
``SafeSum(scra, gcra)`` zero-fallback rendered — and col 0040 (net of
provisions) must shrink by it. Split out of test_c07.py to keep that file under
the reporting-test-file LOC ratchet.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row


def _sa_results_sealed_provision_carrier() -> pl.LazyFrame:
    """SA results carrying the sealed Art. 111(2) deducted provision but NO
    scra/gcra input pass-throughs — the shape of a real submission (R9).

    Two corporate exposures: gross drawn 1000 + 2000 = 3000; the engine's
    drawn-first deduction consumed provision_deducted 100 + 50 = 150, so the
    net-of-provisions figure (col 0040) must be 3000 - 150 = 2850.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_P_1", "SA_P_2"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [1000.0, 2000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [900.0, 1950.0],
            "rwa_final": [900.0, 1950.0],
            "risk_weight": [1.0, 1.0],
            "provision_allocated": [100.0, 50.0],
            "provision_deducted": [100.0, 50.0],
            "counterparty_reference": ["CP_A", "CP_B"],
            "sa_cqs": [3, 3],
        }
    )


class TestC0700ProvisionCarrier:
    """Col 0030 provisions ladder (R9): the SCRA/GCRA input pass-throughs are
    never sealed on the aggregator exit, so a real submission must report the
    sealed SA Art. 111(2) deducted provision (``provision_deducted``) instead of
    the hard 0.0 the retired ``SafeSum(scra, gcra)`` zero-fallback rendered."""

    def test_sealed_carrier_drives_col_0030(self) -> None:
        """No scra/gcra: col 0030 reports -provision_deducted (Annex II §1.3)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_sealed_provision_carrier())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # provision_deducted 100 + 50 = 150; emitted negative per §1.3.
        assert corp["0030"][0] == pytest.approx(-150.0)

    def test_col_0040_consumes_corrected_provision(self) -> None:
        """Col 0040 (net of provisions) = 0010 - 0030 shrinks by the provision."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_sealed_provision_carrier())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # gross 3000 - deducted provision 150 = 2850.
        assert corp["0010"][0] == pytest.approx(3000.0)
        assert corp["0040"][0] == pytest.approx(2850.0)

    def test_scra_gcra_preferred_when_supplied(self) -> None:
        """A book that supplies non-degenerate scra/gcra keeps that granular
        figure over the sealed carrier (the C 08 preference order)."""
        data = _sa_results_sealed_provision_carrier().with_columns(
            pl.Series("scra_provision_amount", [30.0, 10.0]),
            pl.Series("gcra_provision_amount", [5.0, 0.0]),
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data)

        corp = _get_total_row(bundle.c07_00["corporate"])
        # scra+gcra (35 + 10 = 45) wins over provision_deducted (150).
        assert corp["0030"][0] == pytest.approx(-45.0)
        assert corp["0040"][0] == pytest.approx(2955.0)

    def test_degenerate_scra_gcra_falls_back_to_carrier(self) -> None:
        """scra/gcra present but netting to ~0 falls back to the sealed carrier
        (the value-dependent limb of the C 08 ladder)."""
        data = _sa_results_sealed_provision_carrier().with_columns(
            pl.Series("scra_provision_amount", [0.0, 0.0]),
            pl.Series("gcra_provision_amount", [0.0, 0.0]),
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data)

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0030"][0] == pytest.approx(-150.0)
        assert corp["0040"][0] == pytest.approx(2850.0)

    def test_mixed_frame_picks_per_row_not_per_cell(self) -> None:
        """Some rows carry non-degenerate scra/gcra, others only the sealed
        carrier: col 0030 sums the PER-ROW pick. This pins the recorded
        granularity contract — a future "align to C 08 per-cell" refactor
        (aggregate scra/gcra over the subset, keep 35, never consult the carrier)
        would report -35 and must go red here."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SA_MIX_1", "SA_MIX_2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "drawn_amount": [1000.0, 2000.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [900.0, 1960.0],
                "rwa_final": [900.0, 1960.0],
                "risk_weight": [1.0, 1.0],
                # Row 1 supplies scra+gcra = 35 (deliberately below its own
                # provision_deducted 100, to prove scra/gcra wins per row); row 2
                # supplies neither, so it falls back to provision_deducted 40.
                "provision_allocated": [100.0, 40.0],
                "provision_deducted": [100.0, 40.0],
                "scra_provision_amount": [30.0, None],
                "gcra_provision_amount": [5.0, None],
                "counterparty_reference": ["CP_A", "CP_B"],
                "sa_cqs": [3, 3],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data)

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Per-row pick: row 1 -> 35 (scra+gcra), row 2 -> 40 (carrier). Sum = 75.
        assert corp["0030"][0] == pytest.approx(-75.0)
        assert corp["0040"][0] == pytest.approx(3000.0 - 75.0)

    def test_no_provisions_stays_zero(self) -> None:
        """A book with no provisions at all keeps col 0030 == 0.0."""
        data = _sa_results_sealed_provision_carrier().with_columns(
            pl.Series("provision_deducted", [0.0, 0.0]),
            pl.Series("provision_allocated", [0.0, 0.0]),
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data)

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0030"][0] == pytest.approx(0.0)
        assert corp["0040"][0] == pytest.approx(3000.0)

    def test_ccr_rows_contribute_no_provision(self) -> None:
        """CCR synthetic rows (null provision_deducted) add nothing to col 0030:
        the derivative netting-set row 0110 reports a zero provision."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SA_CORP", "CCR_DRV"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "drawn_amount": [1000.0, 0.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [900.0, 500.0],
                "rwa_final": [900.0, 250.0],
                "risk_weight": [1.0, 0.5],
                "provision_allocated": [100.0, None],
                "provision_deducted": [100.0, None],
                "risk_type": [None, "CCR_DERIVATIVE"],
                "counterparty_reference": ["CP_A", "CP_D"],
                "sa_cqs": [3, None],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data)
        corp = bundle.c07_00["corporate"]

        # Row 0110 (derivative + long-settlement netting sets) carries no provision.
        row_0110 = corp.filter(pl.col("row_ref") == "0110")
        assert row_0110["0030"][0] == pytest.approx(0.0)
        # The total row's provision is the lending row's deduction only.
        total = _get_total_row(corp)
        assert total["0030"][0] == pytest.approx(-100.0)
