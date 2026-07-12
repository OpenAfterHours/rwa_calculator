"""COREP C 08.05 / OF 08.05 PD-backtesting tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle


def _irb_pd_backtest_results() -> pl.LazyFrame:
    """Synthetic results for C 08.05 PD backtesting tests.

    5 corporate exposures across different PD ranges with default status:
    - E1: PD 0.002 (floored), PD 0.001 (original), not defaulted
    - E2: PD 0.005 (floored), PD 0.004 (original), not defaulted
    - E3: PD 0.01, not defaulted
    - E4: PD 0.03, not defaulted
    - E5: PD 1.0, defaulted
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
            "exposure_class": ["corporate", "corporate", "corporate", "corporate", "corporate"],
            "ead_final": [5500.0, 3000.0, 2200.0, 1000.0, 500.0],
            "rwa_final": [2750.0, 1800.0, 1540.0, 750.0, 0.0],
            "pd_floored": [0.002, 0.005, 0.01, 0.03, 1.0],
            "pd": [0.001, 0.004, 0.01, 0.03, 1.0],
            "is_defaulted": [False, False, False, False, True],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
        }
    )


def _irb_backtest_multi_class() -> pl.LazyFrame:
    """Multi-class synthetic data for C 08.05 backtesting tests.

    Corporate (3 exposures, 1 defaulted) + Institution (1 exposure, 0 defaults).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": ["corporate", "corporate", "corporate", "institution"],
            "ead_final": [1000.0, 2000.0, 500.0, 3000.0],
            "rwa_final": [500.0, 1200.0, 0.0, 900.0],
            "pd_floored": [0.005, 0.01, 1.0, 0.002],
            "is_defaulted": [False, False, True, False],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
        }
    )


class TestC0805TemplateDefinitions:
    """Test C 08.05 / OF 08.05 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_05_COLUMNS

        assert len(CRR_C08_05_COLUMNS) == 5

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_05_COLUMNS

        assert len(B31_C08_05_COLUMNS) == 5

    def test_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_05_COLUMN_REFS, CRR_C08_05_COLUMNS

        assert [c.ref for c in CRR_C08_05_COLUMNS] == C08_05_COLUMN_REFS

    def test_column_refs_values(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_05_COLUMN_REFS

        assert C08_05_COLUMN_REFS == ["0010", "0020", "0030", "0040", "0050"]

    def test_crr_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_05_COLUMNS, get_c08_05_columns

        assert get_c08_05_columns("CRR") is CRR_C08_05_COLUMNS

    def test_b31_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_05_COLUMNS, get_c08_05_columns

        assert get_c08_05_columns("BASEL_3_1") is B31_C08_05_COLUMNS

    def test_b31_col_0010_post_input_floor(self) -> None:
        from rwa_calc.reporting.corep.templates import get_c08_05_columns

        cols = get_c08_05_columns("BASEL_3_1")
        assert "post input floor" in cols[0].name

    def test_crr_col_0010_no_post_input_floor(self) -> None:
        from rwa_calc.reporting.corep.templates import get_c08_05_columns

        cols = get_c08_05_columns("CRR")
        assert "post input floor" not in cols[0].name

    def test_reuses_c08_03_pd_ranges(self) -> None:
        """C 08.05 uses the same 17 PD range buckets as C 08.03."""
        from rwa_calc.reporting.corep.templates import C08_03_PD_RANGES

        assert len(C08_03_PD_RANGES) == 17


class TestC0805Generation:
    """Test C 08.05 / OF 08.05 generation from pipeline data."""

    def test_generates_per_class_dict(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        assert isinstance(bundle.c08_05, dict)
        assert "corporate" in bundle.c08_05

    def test_multi_class_separate_dataframes(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_backtest_multi_class(), framework="CRR")
        assert "corporate" in bundle.c08_05
        assert "institution" in bundle.c08_05

    def test_dataframe_has_7_columns(self) -> None:
        """5 data columns + row_ref + row_name = 7."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        assert len(corp.columns) == 7

    def test_sa_only_returns_empty(self) -> None:
        sa_data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "pd_floored": [0.005],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(sa_data, framework="CRR")
        assert bundle.c08_05 == {}

    def test_slotting_excluded(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["slotting", "foundation_irb"],
                "exposure_class": ["specialised_lending", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [700.0, 1000.0],
                "pd_floored": [0.005, 0.01],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        # Slotting excluded — only corporate appears
        assert "specialised_lending" not in bundle.c08_05
        assert "corporate" in bundle.c08_05


class TestC0805PDRangeAssignment:
    """Test PD bucket assignment in C 08.05."""

    def test_pd_0_002_in_row_0060(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1
        assert row["row_name"][0] == "0.20 to < 0.25%"

    def test_pd_0_005_in_row_0080(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        assert len(row) == 1
        assert row["row_name"][0] == "0.50 to < 0.75%"

    def test_pd_1_0_in_default_bucket(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert len(row) == 1
        assert row["row_name"][0] == "100% (Default)"

    def test_empty_buckets_omitted(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # 5 exposures across 5 different PD ranges → 5 rows
        assert len(corp) == 5

    def test_b31_allocation_uses_original_pd(self) -> None:
        """Basel 3.1 allocates rows by pd (pre-floor)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        corp = bundle.c08_05["corporate"]
        # E1: pd=0.001, should go to row 0040 (0.10 to < 0.15%)
        row = corp.filter(pl.col("row_ref") == "0040")
        assert len(row) == 1

    def test_crr_allocation_uses_floored_pd(self) -> None:
        """CRR allocates rows by pd_floored."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # E1: pd_floored=0.002, should go to row 0060 (0.20 to < 0.25%)
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1


class TestC0805ColumnValues:
    """Test C 08.05 column values for PD backtesting."""

    def test_col_0010_arithmetic_avg_pd(self) -> None:
        """Col 0010 is arithmetic average PD (not exposure-weighted)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # E2 alone in row 0080 (PD 0.005): arithmetic avg = 0.005
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0010"][0] == pytest.approx(0.005)

    def test_col_0010_default_bucket(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0010"][0] == pytest.approx(1.0)

    def test_col_0020_obligor_count(self) -> None:
        """Col 0020 is number of obligors."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # E2 alone in row 0080: 1 obligor (CP_B)
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0020"][0] == pytest.approx(1.0)

    def test_col_0030_defaults_count(self) -> None:
        """Col 0030 is count of defaulted obligors."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # Default bucket (row 0170) has 1 defaulted exposure (E5)
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0030"][0] == pytest.approx(1.0)

    def test_col_0030_no_defaults_in_non_default_bucket(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # Row 0080 has E2 (not defaulted)
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0030"][0] == pytest.approx(0.0)

    def test_col_0040_observed_default_rate(self) -> None:
        """Col 0040 = defaults / obligors."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # Default bucket (row 0170): 1 default / 1 obligor = 100%
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0040"][0] == pytest.approx(1.0)

    def test_col_0040_zero_default_rate(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # Row 0080: 0 defaults / 1 obligor = 0%
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0040"][0] == pytest.approx(0.0)

    def test_col_0050_historical_rate_fallback(self) -> None:
        """Without historical data, col 0050 = col 0040 (current observed rate)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0170")
        assert row["0050"][0] == row["0040"][0]

    def test_col_0050_zero_rate_non_default_bucket(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0050"][0] == pytest.approx(0.0)

    def test_multi_class_defaults_isolated(self) -> None:
        """Default counts are per exposure class, not global."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_backtest_multi_class(), framework="CRR")
        # Corporate has 1 default (E3, PD=1.0)
        corp = bundle.c08_05["corporate"]
        default_row = corp.filter(pl.col("row_ref") == "0170")
        assert default_row["0030"][0] == pytest.approx(1.0)
        # Institution has 0 defaults
        inst = bundle.c08_05["institution"]
        # Institution only has 1 row (PD 0.002 → row 0060)
        assert len(inst) == 1
        assert inst["0030"][0] == pytest.approx(0.0)

    def test_obligor_count_unique_counterparties(self) -> None:
        """Obligor count uses n_unique on counterparty_reference."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2", "E3"],
                "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate", "corporate"],
                "ead_final": [1000.0, 2000.0, 1500.0],
                "rwa_final": [500.0, 1000.0, 750.0],
                "pd_floored": [0.005, 0.006, 0.007],
                "is_defaulted": [False, False, False],
                # E1 and E3 share a counterparty
                "counterparty_reference": ["CP_A", "CP_B", "CP_A"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c08_05["corporate"]
        # All 3 in same bucket (0.50 to < 0.75%), but only 2 unique CPs
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0020"][0] == pytest.approx(2.0)


class TestC0805B31Features:
    """Test Basel 3.1-specific PD backtesting features."""

    def test_b31_col_0010_reports_post_floor_pd(self) -> None:
        """Basel 3.1 col 0010 reports post-input-floor PD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        corp = bundle.c08_05["corporate"]
        # E1: allocated to row 0040 by original PD 0.001, but col 0010 reports
        # the arithmetic avg of floored PD (0.002)
        row = corp.filter(pl.col("row_ref") == "0040")
        assert row["0010"][0] == pytest.approx(0.002)

    def test_crr_col_0010_reports_floored_pd(self) -> None:
        """CRR col 0010 reports floored PD (same as allocation PD)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # E1: allocated to row 0060 by floored PD 0.002, col 0010 = 0.002
        row = corp.filter(pl.col("row_ref") == "0060")
        assert row["0010"][0] == pytest.approx(0.002)

    def test_b31_still_5_columns(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        corp = bundle.c08_05["corporate"]
        # 5 data + row_ref + row_name = 7
        assert len(corp.columns) == 7

    def test_b31_different_row_count_from_crr(self) -> None:
        """B31 may produce different row counts due to pre-floor PD allocation."""
        gen = COREPGenerator()
        crr_bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        b31_bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        crr_corp = crr_bundle.c08_05["corporate"]
        b31_corp = b31_bundle.c08_05["corporate"]
        # E1 has different original (0.001) vs floored (0.002) PD
        # CRR: E1 in row 0060 (0.20-0.25%), E2 in row 0080 → 5 rows
        # B31: E1 in row 0040 (0.10-0.15%), E2 in row 0080 → still 5 but different rows
        assert len(crr_corp) == 5
        assert len(b31_corp) == 5
        # B31 has row 0040 that CRR doesn't
        b31_refs = set(b31_corp["row_ref"].to_list())
        crr_refs = set(crr_corp["row_ref"].to_list())
        assert "0040" in b31_refs
        assert "0040" not in crr_refs


class TestC0805EdgeCases:
    """Test C 08.05 edge cases and boundary conditions."""

    def test_no_pd_column_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c08_05 == {}

    def test_null_pd_goes_to_unassigned(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, 1000.0],
                "pd_floored": [None, 0.005],
                "is_defaulted": [False, False],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c08_05["corporate"]
        unassigned = corp.filter(pl.col("row_ref") == "9999")
        assert len(unassigned) == 1
        assert unassigned["row_name"][0] == "Unassigned"

    def test_default_field_from_bundle(self) -> None:
        """COREPTemplateBundle.c08_05 defaults to empty dict."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c08_05 == {}

    def test_no_is_defaulted_uses_pd_fallback(self) -> None:
        """Without is_defaulted column, defaults detected by PD >= 1.0."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [500.0, 0.0],
                "pd_floored": [0.005, 1.0],
                "counterparty_reference": ["CP_A", "CP_B"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c08_05["corporate"]
        # Default bucket (row 0170): PD >= 1.0 → 1 default
        default_row = corp.filter(pl.col("row_ref") == "0170")
        assert default_row["0030"][0] == pytest.approx(1.0)
        assert default_row["0040"][0] == pytest.approx(1.0)

    def test_no_counterparty_reference_uses_row_count(self) -> None:
        """Without counterparty_reference, obligor count = row count."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2", "E3"],
                "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate", "corporate"],
                "ead_final": [1000.0, 2000.0, 3000.0],
                "rwa_final": [500.0, 1000.0, 1500.0],
                "pd_floored": [0.005, 0.006, 0.007],
                "is_defaulted": [False, False, False],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c08_05["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        # 3 rows in same bucket, no CP ref → obligor count = 3
        assert row["0020"][0] == pytest.approx(3.0)

    def test_excel_export_prefix_crr(self) -> None:
        """CRR export uses 'C 08.05' prefix."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        assert bundle.framework == "CRR"
        # Verify the c08_05 dict is populated (Excel prefix tested indirectly)
        assert len(bundle.c08_05) > 0

    def test_excel_export_prefix_b31(self) -> None:
        """Basel 3.1 export uses 'OF 08.05' prefix."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"
        assert len(bundle.c08_05) > 0
