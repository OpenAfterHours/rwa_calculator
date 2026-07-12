"""COREP C 08.02 / OF 08.02 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.unit.reporting.corep._builders import (
    _irb_results,
)


class TestC0802:
    """Tests for C 08.02 IRB PD grade breakdown template."""

    def test_c0802_produces_per_class_output(self) -> None:
        """C 08.02 produces a dict keyed by IRB exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert isinstance(bundle.c08_02, dict)
        assert "corporate" in bundle.c08_02

    def test_c0802_pd_bands_assigned(self) -> None:
        """Exposures are assigned to correct PD bands."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_names = corp["row_name"].to_list()

        # PD=0.005 -> "0.25% - 0.50%" band (0.005 = 0.5%)
        assert any("0.50%" in b for b in band_names)

    def test_c0802_per_band_ead(self) -> None:
        """EAD aggregated per PD band."""
        gen = COREPGenerator()
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
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        assert band_050["0010"][0] == pytest.approx(0.005)

    def test_c0802_has_obligor_grade_identifier(self) -> None:
        """C 08.02 rows include obligor grade identifier (col 0005)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        assert "0005" in corp.columns

    def test_c0802_maturity_in_days(self) -> None:
        """C 08.02 maturity (col 0250) is also in days."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_02["corporate"]
        band_050 = corp.filter(pl.col("row_name") == "0.50% - 0.75%")
        # Single exposure: maturity = 2.5 years = 912.5 days
        assert band_050["0250"][0] == pytest.approx(2.5 * 365.0, rel=1e-4)
