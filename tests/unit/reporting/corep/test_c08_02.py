"""COREP C 08.02 / OF 08.02 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import (
    _irb_results,
)


class TestC0802:
    """Tests for C 08.02 IRB PD grade breakdown template."""

    def test_c0802_produces_per_class_output(self) -> None:
        """C 08.02 produces a dict keyed by IRB exposure class."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert isinstance(bundle.c08_02, dict)
        assert "corporate" in bundle.c08_02

    def test_c0802_pd_bands_assigned(self) -> None:
        """Exposures are assigned to correct PD bands."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_names = corp["row_name"].to_list()

        # PD=0.005 -> "0.25% - 0.50%" band (0.005 = 0.5%)
        assert any("0.50%" in b for b in band_names)

    def test_c0802_per_band_ead(self) -> None:
        """EAD aggregated per PD band."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]

        # Corp PD=0.005 (0.50%) -> "0.50% - 0.75%" band, EAD=5500
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        assert band_050["0110"][0] == pytest.approx(5500.0)

        # Corp PD=0.01 (1.00%) -> "0.75% - 2.50%" band, EAD=3000
        band_075 = corp.filter(pl.col("row_name") == "0.75% - 2.50%")
        assert band_075["0110"][0] == pytest.approx(3000.0)

    def test_c0802_weighted_pd_per_band(self) -> None:
        """Weighted PD within a single-exposure band equals the exposure PD."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        assert band_050["0010"][0] == pytest.approx(0.005)

    def test_c0802_has_obligor_grade_identifier(self) -> None:
        """C 08.02 rows include obligor grade identifier (col 0005)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        assert "0005" in corp.columns

    def test_c0802_maturity_in_days(self) -> None:
        """C 08.02 maturity (col 0250) is also in days."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        # Single exposure: maturity = 2.5 years = 912.5 days
        assert band_050["0250"][0] == pytest.approx(2.5 * 365.0, rel=1e-4)


def _irb_results_sme_factor() -> pl.LazyFrame:
    """CRR IRB corporate_sme exposures (both PD=2%, one band) with the SME
    supporting factor applied — the shared C 08.01/02 value surface, so col
    0256 must negate on C 08.02 exactly as on C 08.01.

        0255 = Σ rwa_pre_factor = 16000; delta = 2400; 0256 = -2400; 0260 = 13600.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_SME_1", "IRB_SME_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate_sme", "corporate_sme"],
            "drawn_amount": [10000.0, 6000.0],
            "undrawn_amount": [0.0, 0.0],
            "ead_final": [10000.0, 6000.0],
            "rwa_final": [8500.0, 5100.0],
            "rwa_pre_factor": [10000.0, 6000.0],
            "risk_weight": [0.85, 0.85],
            "pd_floored": [0.02, 0.02],
            "lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5],
            "expected_loss": [90.0, 54.0],
            "scra_provision_amount": [0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0],
            "counterparty_reference": ["CP_S1", "CP_S2"],
            "sme_supporting_factor_applied": [True, True],
            "is_sme": [True, True],
        }
    )


class TestC0802SignConvention:
    """Annex II §1.3 "(-)" negation applies to C 08.02 the same as C 08.01 (item R2)."""

    def test_crr_0256_negated_per_pd_band(self) -> None:
        """CRR col 0256 (SME supporting-factor adjustment) is reported negative,
        and 0255 + 0256 foots to 0260 on the populated PD-band row."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_sme_factor(), framework="CRR")
        corp_sme = bundle.c08_02["corporate_sme"]
        band = corp_sme.filter(pl.col("0255").is_not_null() & (pl.col("0255") > 0.0))
        assert band.height == 1  # both SME rows fall in one PD band
        assert band["0256"][0] == pytest.approx(-2400.0)
        assert band["0256"][0] <= 0.0
        assert band["0255"][0] + band["0256"][0] == pytest.approx(band["0260"][0])
