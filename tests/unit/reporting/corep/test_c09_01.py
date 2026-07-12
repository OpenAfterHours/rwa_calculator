"""COREP C 09.01 / OF 09.01 geographical-breakdown (SA) tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle


def _sa_geo_results() -> pl.LazyFrame:
    """Synthetic SA results with country codes for C 09.01 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_mortgage",
                "defaulted",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 3000.0, 200.0],
            "ead_gross": [1200.0, 600.0, 2100.0, 3200.0, 300.0],
            "rwa_final": [1000.0, 500.0, 400.0, 1050.0, 300.0],
            "cp_country_code": ["GB", "US", "GB", "GB", "US"],
            "default_status": [False, False, False, False, True],
        }
    )


def _sa_geo_multi_class() -> pl.LazyFrame:
    """Multi-class SA results with multiple countries."""
    return pl.LazyFrame(
        {
            "exposure_reference": [f"E{i}" for i in range(1, 9)],
            "approach_applied": ["standardised"] * 8,
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
                "retail_mortgage",
                "defaulted",
                "pse",
                "covered_bond",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 800.0, 3000.0, 200.0, 400.0, 600.0],
            "ead_gross": [1200.0, 600.0, 2100.0, 900.0, 3200.0, 300.0, 500.0, 700.0],
            "rwa_final": [1000.0, 500.0, 400.0, 600.0, 1050.0, 300.0, 80.0, 60.0],
            "cp_country_code": ["GB", "US", "GB", "DE", "GB", "US", "GB", "DE"],
            "default_status": [False, False, False, False, False, True, False, False],
        }
    )


class TestC0901TemplateDefinitions:
    """Test C 09.01 / OF 09.01 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_COLUMNS

        assert len(CRR_C09_01_COLUMNS) == 13

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_COLUMNS

        assert len(B31_C09_01_COLUMNS) == 10

    def test_crr_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_01_COLUMN_REFS

        assert C09_01_COLUMN_REFS == [
            "0010",
            "0020",
            "0040",
            "0050",
            "0055",
            "0060",
            "0061",
            "0070",
            "0075",
            "0080",
            "0081",
            "0082",
            "0090",
        ]

    def test_b31_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_COLUMN_REFS

        assert B31_C09_01_COLUMN_REFS == [
            "0010",
            "0020",
            "0040",
            "0050",
            "0055",
            "0060",
            "0061",
            "0070",
            "0075",
            "0090",
        ]

    def test_b31_removes_supporting_factor_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_COLUMN_REFS

        assert "0080" not in B31_C09_01_COLUMN_REFS
        assert "0081" not in B31_C09_01_COLUMN_REFS
        assert "0082" not in B31_C09_01_COLUMN_REFS

    def test_crr_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_ROWS

        assert len(CRR_C09_01_ROWS) == 23

    def test_b31_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_ROWS

        assert len(B31_C09_01_ROWS) == 29

    def test_crr_has_short_term_row(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_ROWS

        refs = [r.ref for r in CRR_C09_01_ROWS]
        assert "0130" in refs

    def test_b31_removes_short_term_row(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_ROWS

        refs = [r.ref for r in B31_C09_01_ROWS]
        assert "0130" not in refs

    def test_b31_adds_sl_sub_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_ROWS

        refs = [r.ref for r in B31_C09_01_ROWS]
        assert "0071" in refs  # object finance
        assert "0072" in refs  # commodities finance
        assert "0073" in refs  # project finance

    def test_b31_adds_re_sub_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_ROWS

        refs = [r.ref for r in B31_C09_01_ROWS]
        assert "0091" in refs  # residential RE
        assert "0092" in refs  # commercial RE
        assert "0093" in refs  # other RE
        assert "0094" in refs  # ADC

    def test_crr_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_COLUMNS, get_c09_01_columns

        assert get_c09_01_columns("CRR") is CRR_C09_01_COLUMNS

    def test_b31_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_COLUMNS, get_c09_01_columns

        assert get_c09_01_columns("BASEL_3_1") is B31_C09_01_COLUMNS

    def test_row_selector_crr(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_ROWS, get_c09_01_rows

        assert get_c09_01_rows("CRR") is CRR_C09_01_ROWS

    def test_row_selector_b31(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_01_ROWS, get_c09_01_rows

        assert get_c09_01_rows("BASEL_3_1") is B31_C09_01_ROWS

    def test_total_row_is_last(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_01_ROWS

        assert CRR_C09_01_ROWS[-1].ref == "0170"
        assert CRR_C09_01_ROWS[-1].exposure_class_value is None

    def test_sa_class_map_covers_main_classes(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_01_SA_CLASS_MAP

        assert "corporate" in C09_01_SA_CLASS_MAP
        assert "institution" in C09_01_SA_CLASS_MAP
        assert "retail_mortgage" in C09_01_SA_CLASS_MAP
        assert "defaulted" in C09_01_SA_CLASS_MAP


class TestC0901Generation:
    """Test C 09.01 / OF 09.01 generation from pipeline data."""

    def test_generates_per_country_dict(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        assert isinstance(bundle.c09_01, dict)
        assert "TOTAL" in bundle.c09_01

    def test_generates_gb_and_us_countries(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        assert "GB" in bundle.c09_01
        assert "US" in bundle.c09_01

    def test_total_has_all_exposure_classes(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        refs = total["row_ref"].to_list()
        assert "0070" in refs  # Corporate
        assert "0060" in refs  # Institution
        assert "0170" in refs  # Total

    def test_dataframe_has_correct_column_count_crr(self) -> None:
        """13 data columns + row_ref + row_name = 15."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        assert len(total.columns) == 15  # 13 data + 2 meta

    def test_dataframe_has_correct_column_count_b31(self) -> None:
        """10 data columns + row_ref + row_name = 12."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_01["TOTAL"]
        assert len(total.columns) == 12  # 10 data + 2 meta

    def test_missing_country_code_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_01 == {}

    def test_sa_only_no_irb_in_c09_01(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [500.0, 250.0],
                "cp_country_code": ["GB", "GB"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        # C 09.01 is SA only — IRB exposures excluded
        if "TOTAL" in bundle.c09_01:
            total = bundle.c09_01["TOTAL"]
            total_row = total.filter(pl.col("row_ref") == "0170")
            # Should only include SA exposure (500.0), not IRB (1000.0)
            assert total_row["0075"][0] == pytest.approx(500.0)

    def test_multi_country_isolation(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        gb = bundle.c09_01["GB"]
        us = bundle.c09_01["US"]
        # GB has 3 exposures (E1, E3, E4), US has 2 (E2, E5)
        gb_total = gb.filter(pl.col("row_ref") == "0170")
        us_total = us.filter(pl.col("row_ref") == "0170")
        # GB EAD: 1000 + 2000 + 3000 = 6000
        assert gb_total["0075"][0] == pytest.approx(6000.0)
        # US EAD: 500 + 200 = 700
        assert us_total["0075"][0] == pytest.approx(700.0)


class TestC0901ColumnValues:
    """Test C 09.01 column value computation."""

    def test_col_0010_original_exposure(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # ead_gross sum: 1200 + 600 + 2100 + 3200 + 300 = 7400
        assert total_row["0010"][0] == pytest.approx(7400.0)

    def test_col_0020_defaulted_exposure(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # Defaulted ead_gross: E5 = 300
        assert total_row["0020"][0] == pytest.approx(300.0)

    def test_col_0075_exposure_value(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # ead_final sum: 1000 + 500 + 2000 + 3000 + 200 = 6700
        assert total_row["0075"][0] == pytest.approx(6700.0)

    def test_col_0090_rwea(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # rwa_final sum: 1000 + 500 + 400 + 1050 + 300 = 3250
        assert total_row["0090"][0] == pytest.approx(3250.0)

    def test_col_0080_crr_pre_supporting_factors(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0080"][0] == pytest.approx(3250.0)

    def test_corporate_row_values(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0070")
        # Corporate EAD: 1000 + 500 = 1500
        assert corp_row["0075"][0] == pytest.approx(1500.0)

    def test_institution_row_values(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        inst_row = total.filter(pl.col("row_ref") == "0060")
        # Institution EAD: 2000
        assert inst_row["0075"][0] == pytest.approx(2000.0)

    def test_defaulted_row_values(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        def_row = total.filter(pl.col("row_ref") == "0100")
        # Defaulted EAD: 200
        assert def_row["0075"][0] == pytest.approx(200.0)


class TestC0901B31Features:
    """Test Basel 3.1 specific features of OF 09.01."""

    def test_no_supporting_factor_columns(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_01["TOTAL"]
        assert "0080" not in total.columns
        assert "0081" not in total.columns
        assert "0082" not in total.columns

    def test_col_0090_is_plain_rwea(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0090"][0] == pytest.approx(3250.0)

    def test_b31_has_more_rows(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_multi_class(), framework="BASEL_3_1")
        total_b31 = bundle.c09_01["TOTAL"]
        gen2 = COREPGenerator()
        bundle2 = gen2.generate_from_lazyframe(_sa_geo_multi_class(), framework="CRR")
        total_crr = bundle2.c09_01["TOTAL"]
        # B31 has more rows due to SL and RE sub-rows
        assert len(total_b31) >= len(total_crr)


class TestC0901EdgeCases:
    """Test C 09.01 edge cases."""

    def test_empty_sa_data_returns_empty_dict(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_01 == {}

    def test_null_country_code_excluded_from_per_country(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [500.0, 250.0],
                "cp_country_code": ["GB", None],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        # TOTAL includes both, but only GB gets its own sheet
        assert "TOTAL" in bundle.c09_01
        assert "GB" in bundle.c09_01
        assert None not in bundle.c09_01

    def test_single_country_produces_total_and_country(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "ead_gross": [1200.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.c09_01) == 2  # TOTAL + GB
        # TOTAL and GB should have same values
        total_rwa = bundle.c09_01["TOTAL"].filter(pl.col("row_ref") == "0170")["0090"][0]
        gb_rwa = bundle.c09_01["GB"].filter(pl.col("row_ref") == "0170")["0090"][0]
        assert total_rwa == pytest.approx(gb_rwa)

    def test_total_equals_sum_of_countries(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total_rwa = bundle.c09_01["TOTAL"].filter(pl.col("row_ref") == "0170")["0090"][0]
        gb_rwa = bundle.c09_01["GB"].filter(pl.col("row_ref") == "0170")["0090"][0]
        us_rwa = bundle.c09_01["US"].filter(pl.col("row_ref") == "0170")["0090"][0]
        assert total_rwa == pytest.approx(gb_rwa + us_rwa)

    def test_zero_ead_exposure(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [0.0],
                "ead_gross": [0.0],
                "rwa_final": [0.0],
                "cp_country_code": ["GB"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0075"][0] == pytest.approx(0.0)

    def test_bundle_field_default_empty(self) -> None:
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c09_01 == {}
        assert bundle.c09_02 == {}
