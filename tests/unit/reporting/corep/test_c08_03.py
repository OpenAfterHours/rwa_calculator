"""COREP C 08.03 / OF 08.03 generation tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle


def _irb_pd_range_results() -> pl.LazyFrame:
    """Synthetic IRB results spanning multiple PD ranges for C 08.03 testing.

    Covers 5 exposures across 4 PD range buckets:
    - PD 0.002 (0.20%) → "0.15 to < 0.25%" bucket (row 0060)
    - PD 0.005 (0.50%) → "0.50 to < 0.75%" bucket (row 0080)
    - PD 0.01 (1.00%) → "1.00 to < 2.50%" bucket (row 0100)
    - PD 0.03 (3.00%) → "2.50 to < 5.00%" bucket (row 0110)
    - PD 1.0 (100%) → "100% (Default)" bucket (row 0170)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 1000.0, 500.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "nominal_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2200.0, 1000.0, 500.0],
            "rwa_final": [2750.0, 1800.0, 1540.0, 750.0, 0.0],
            "risk_weight": [0.50, 0.60, 0.70, 0.75, 0.0],
            "pd_floored": [0.002, 0.005, 0.01, 0.03, 1.0],
            "pd": [0.001, 0.004, 0.01, 0.03, 1.0],
            "lgd_floored": [0.45, 0.45, 0.35, 0.40, 0.45],
            "irb_maturity_m": [2.5, 3.0, 2.0, 4.0, 1.0],
            "expected_loss": [4.95, 6.75, 7.7, 12.0, 225.0],
            "provision_held": [5.0, 8.0, 6.0, 15.0, 200.0],
            "scra_provision_amount": [3.0, 4.0, 3.0, 8.0, 100.0],
            "gcra_provision_amount": [2.0, 4.0, 3.0, 7.0, 100.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "ccf": [0.5, 0.0, 0.4, 0.0, 0.0],
        }
    )


def _irb_multi_class_pd_range() -> pl.LazyFrame:
    """IRB results with multiple exposure classes for per-class C 08.03 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_mortgage",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 4000.0],
            "nominal_amount": [1000.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0, 4000.0],
            "rwa_final": [2750.0, 1800.0, 600.0, 1200.0],
            "pd_floored": [0.005, 0.01, 0.002, 0.003],
            "lgd_floored": [0.45, 0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 1.5, 20.0],
            "expected_loss": [12.375, 13.5, 1.8, 1.8],
            "provision_held": [15.0, 10.0, 3.0, 2.5],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
        }
    )


class TestC0803TemplateDefinitions:
    """Tests for C 08.03 / OF 08.03 template structure definitions."""

    def test_crr_c0803_has_11_columns(self) -> None:
        """CRR C 08.03 has exactly 11 columns."""
        from rwa_calc.reporting.corep.templates import CRR_C08_03_COLUMNS

        assert len(CRR_C08_03_COLUMNS) == 11

    def test_b31_c0803_has_11_columns(self) -> None:
        """Basel 3.1 OF 08.03 has exactly 11 columns."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS

        assert len(B31_C08_03_COLUMNS) == 11

    def test_c0803_pd_ranges_has_17_buckets(self) -> None:
        """C 08.03 PD ranges define exactly 17 regulatory buckets."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_RANGES

        assert len(C08_03_PD_RANGES) == 17

    def test_pd_ranges_cover_full_spectrum(self) -> None:
        """PD ranges cover 0% to 100% (default) without gaps."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_RANGES

        # First range starts at 0
        assert C08_03_PD_RANGES[0][0] == pytest.approx(0.0, abs=1e-10)
        # Last range upper bound is infinity (captures 100% default)
        assert math.isinf(C08_03_PD_RANGES[-1][1])
        # Ranges are contiguous (upper of i == lower of i+1)
        for i in range(len(C08_03_PD_RANGES) - 1):
            assert C08_03_PD_RANGES[i][1] == C08_03_PD_RANGES[i + 1][0]

    def test_pd_range_row_refs_are_sequential(self) -> None:
        """Row refs run from 0010 to 0170 in steps of 10."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_RANGES

        refs = [r[2] for r in C08_03_PD_RANGES]
        expected = [f"{i:04d}" for i in range(10, 180, 10)]
        assert refs == expected

    def test_column_refs_list_matches_columns(self) -> None:
        """C08_03_COLUMN_REFS is derived from CRR_C08_03_COLUMNS refs."""
        from rwa_calc.reporting.corep.templates import C08_03_COLUMN_REFS, CRR_C08_03_COLUMNS

        assert [c.ref for c in CRR_C08_03_COLUMNS] == C08_03_COLUMN_REFS

    def test_get_c08_03_columns_crr(self) -> None:
        """get_c08_03_columns returns CRR columns for 'CRR' framework."""
        from rwa_calc.reporting.corep.templates import CRR_C08_03_COLUMNS, get_c08_03_columns

        assert get_c08_03_columns("CRR") is CRR_C08_03_COLUMNS

    def test_get_c08_03_columns_b31(self) -> None:
        """get_c08_03_columns returns B31 columns for 'BASEL_3_1' framework."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS, get_c08_03_columns

        assert get_c08_03_columns("BASEL_3_1") is B31_C08_03_COLUMNS

    def test_b31_pd_column_name_includes_post_floor(self) -> None:
        """Basel 3.1 OF 08.03 col 0050 name specifies 'post input floor'."""
        from rwa_calc.reporting.corep.templates import B31_C08_03_COLUMNS

        pd_col = next(c for c in B31_C08_03_COLUMNS if c.ref == "0050")
        assert "post input floor" in pd_col.name.lower()


class TestC0803Generation:
    """Tests for C 08.03 DataFrame generation from IRB pipeline results."""

    def test_c0803_produces_per_class_output(self) -> None:
        """C 08.03 produces a dict keyed by exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        assert isinstance(bundle.c08_03, dict)
        assert "corporate" in bundle.c08_03

    def test_c0803_multiple_classes(self) -> None:
        """C 08.03 produces separate DataFrames for each IRB exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_multi_class_pd_range())
        assert "corporate" in bundle.c08_03
        assert "institution" in bundle.c08_03
        assert "retail_mortgage" in bundle.c08_03

    def test_c0803_has_11_columns_plus_row_metadata(self) -> None:
        """Each C 08.03 DataFrame has 11 data columns + 2 metadata (row_ref, row_name)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # 11 data columns + row_ref + row_name = 13
        assert len(corp.columns) == 13

    def test_c0803_empty_for_sa_only(self) -> None:
        """C 08.03 is empty when only SA exposures exist."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_c0803_excludes_slotting(self) -> None:
        """C 08.03 excludes slotting exposures — only F-IRB/A-IRB."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "slotting"],
                "exposure_class": ["corporate", "specialised_lending"],
                "ead_final": [5000.0, 3000.0],
                "rwa_final": [2500.0, 2100.0],
                "pd_floored": [0.005, 0.0],
                "lgd_floored": [0.45, 0.0],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        # Only corporate should appear (slotting excluded)
        assert "corporate" in bundle.c08_03
        assert "specialised_lending" not in bundle.c08_03


class TestC0803PDRangeAssignment:
    """Tests for correct PD range bucket assignment in C 08.03."""

    def test_pd_002_lands_in_020_025_bucket(self) -> None:
        """PD 0.002 (0.20%) falls in '0.20 to < 0.25%' bucket (row 0060)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1
        assert row["row_name"][0] == "0.20 to < 0.25%"

    def test_pd_005_lands_in_050_075_bucket(self) -> None:
        """PD 0.005 (0.50%) falls in '0.50 to < 0.75%' bucket (row 0080)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        assert len(row) == 1
        assert row["row_name"][0] == "0.50 to < 0.75%"

    def test_pd_001_lands_in_100_250_bucket(self) -> None:
        """PD 0.01 (1.00%) falls in '1.00 to < 2.50%' bucket (row 0100)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0100")
        assert len(row) == 1

    def test_pd_003_lands_in_250_500_bucket(self) -> None:
        """PD 0.03 (3.00%) falls in '2.50 to < 5.00%' bucket (row 0110)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0110")
        assert len(row) == 1

    def test_pd_100_lands_in_default_bucket(self) -> None:
        """PD 1.0 (100%) falls in '100% (Default)' bucket (row 0170)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert len(row) == 1
        assert row["row_name"][0] == "100% (Default)"

    def test_empty_buckets_omitted(self) -> None:
        """PD range buckets with no exposures are not included in output."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # Only 5 buckets should have data (PDs: 0.002, 0.005, 0.01, 0.03, 1.0)
        assert len(corp) == 5


class TestC0803ColumnValues:
    """Tests for C 08.03 column value computation."""

    def test_ead_in_050_075_bucket(self) -> None:
        """Col 0040 (EAD) in 0.50-0.75% bucket equals the single exposure's EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: PD=0.005, EAD=3000
        assert row["0040"][0] == pytest.approx(3000.0, rel=1e-4)

    def test_rwea_in_050_075_bucket(self) -> None:
        """Col 0090 (RWEA) in 0.50-0.75% bucket equals the single exposure's RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: RWA=1800
        assert row["0090"][0] == pytest.approx(1800.0, rel=1e-4)

    def test_avg_pd_single_exposure(self) -> None:
        """Col 0050 (avg PD) for a single-exposure bucket equals that exposure's PD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: PD=0.005
        assert row["0050"][0] == pytest.approx(0.005, rel=1e-6)

    def test_avg_lgd_single_exposure(self) -> None:
        """Col 0070 (avg LGD) for a single-exposure bucket equals that exposure's LGD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: LGD=0.45
        assert row["0070"][0] == pytest.approx(0.45, rel=1e-6)

    def test_avg_maturity_in_years(self) -> None:
        """Col 0080 (avg maturity) is reported in years (not days like C 08.01)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: maturity=3.0 years
        assert row["0080"][0] == pytest.approx(3.0, rel=1e-4)

    def test_expected_loss(self) -> None:
        """Col 0100 (EL) sums expected loss for the bucket."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: EL=6.75
        assert row["0100"][0] == pytest.approx(6.75, rel=1e-4)

    def test_provisions(self) -> None:
        """Col 0110 (provisions) sums scra + gcra provisions for the bucket."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: scra=4.0 + gcra=4.0 = 8.0
        assert row["0110"][0] == pytest.approx(8.0, rel=1e-4)

    def test_obligor_count(self) -> None:
        """Col 0060 (obligors) counts unique counterparty references."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: 1 counterparty (CP_B)
        assert row["0060"][0] == pytest.approx(1.0)

    def test_on_bs_exposure(self) -> None:
        """Col 0010 (on-BS) sums drawn_amount + interest for the bucket."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # E2: drawn=3000, no interest column so drawn only
        assert row["0010"][0] == pytest.approx(3000.0, rel=1e-4)

    def test_off_bs_exposure(self) -> None:
        """Col 0020 (off-BS) sums nominal_amount for the bucket."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        # E1: nominal=1000
        assert row["0020"][0] == pytest.approx(1000.0, rel=1e-4)

    def test_default_bucket_has_zero_rwa(self) -> None:
        """Default bucket (PD=100%) has RWEA=0 (K=0 for defaulted exposures)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0090"][0] == pytest.approx(0.0, abs=1e-4)


class TestC0803B31Features:
    """Tests for Basel 3.1-specific C 08.03 / OF 08.03 features."""

    def test_b31_row_allocation_uses_pre_floor_pd(self) -> None:
        """Basel 3.1 OF 08.03 allocates rows using pre-input-floor PD.

        E1 has pd=0.001 (0.10%) which falls in '0.10 to < 0.15%'
        bucket (row 0040), even though pd_floored=0.002 (0.20%) would
        fall in '0.20 to < 0.25%' (row 0060).
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        # E1: pd_original=0.001 → "0.10 to < 0.15%" (row 0040)
        row = corp.filter(pl.col("row_ref") == "0040")
        assert len(row) == 1

    def test_b31_pd_value_reports_post_floor(self) -> None:
        """Basel 3.1 OF 08.03 col 0050 reports post-input-floor PD.

        E1 is in '0.10 to < 0.15%' bucket (by original PD 0.001) but
        col 0050 should report floored PD 0.002.
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        # E1: post-floor PD=0.002
        assert row["0050"][0] == pytest.approx(0.002, rel=1e-6)

    def test_crr_uses_floored_pd_for_allocation(self) -> None:
        """CRR C 08.03 uses floored PD for both allocation and reporting.

        E1 has pd_floored=0.002 (0.20%) → '0.20 to < 0.25%' bucket (row 0060).
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="CRR")
        corp = bundle.c08_03["corporate"]
        # E1: pd_floored=0.002 → "0.20 to < 0.25%" (row 0060)
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1

    def test_b31_has_11_columns(self) -> None:
        """Basel 3.1 C 08.03 still produces 11 data columns + 2 metadata."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results(), framework="BASEL_3_1")
        corp = bundle.c08_03["corporate"]
        assert len(corp.columns) == 13


class TestC0803EdgeCases:
    """Edge case tests for C 08.03 generation."""

    def test_no_pd_column_returns_empty(self) -> None:
        """C 08.03 returns empty dict when no PD column is available."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_no_irb_data_returns_empty(self) -> None:
        """C 08.03 returns empty dict when no IRB exposures exist."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "pd_floored": [0.01],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_03 == {}

    def test_c0803_bundle_default_is_empty_dict(self) -> None:
        """COREPTemplateBundle.c08_03 defaults to empty dict."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c08_03 == {}

    def test_null_pd_goes_to_unassigned(self) -> None:
        """Exposures with null PD go to 'Unassigned' row."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, 1000.0],
                "pd_floored": [0.005, None],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        corp = bundle.c08_03["corporate"]
        unassigned = corp.filter(pl.col("row_name") == "Unassigned")
        assert len(unassigned) == 1
        assert unassigned["0040"][0] == pytest.approx(2000.0)

    def test_total_ead_across_buckets(self) -> None:
        """Total EAD across all PD range buckets equals total input EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        total_ead = corp["0040"].sum()
        # Sum of all input EADs: 5500 + 3000 + 2200 + 1000 + 500 = 12200
        assert total_ead == pytest.approx(12200.0, rel=1e-4)

    def test_total_rwea_across_buckets(self) -> None:
        """Total RWEA across all PD range buckets equals total input RWEA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        total_rwea = corp["0090"].sum()
        # Sum: 2750 + 1800 + 1540 + 750 + 0 = 6840
        assert total_rwea == pytest.approx(6840.0, rel=1e-4)

    def test_ccf_average_weighted_by_nominal(self) -> None:
        """Col 0030 (avg CCF) is weighted by nominal amount, not EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # E1 (PD=0.002, row 0060): nominal=1000, ccf=0.5 → avg=0.5
        row = corp.filter(pl.col("row_ref") == "0060")
        assert row["0030"][0] == pytest.approx(0.5, rel=1e-4)

    def test_zero_nominal_bucket_has_null_ccf(self) -> None:
        """Bucket with zero nominal amount has null average CCF."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_range_results())
        corp = bundle.c08_03["corporate"]
        # E2 (PD=0.005, row 0080): nominal=0, ccf=0 → null
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0030"][0] is None
