"""COREP C 09.01 / OF 09.01 geographical-breakdown (SA) tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator


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
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        assert isinstance(bundle.c09_01, dict)
        assert "TOTAL" in bundle.c09_01

    def test_generates_gb_and_us_countries(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        assert "GB" in bundle.c09_01
        assert "US" in bundle.c09_01

    def test_total_has_all_exposure_classes(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        refs = total["row_ref"].to_list()
        assert "0070" in refs  # Corporate
        assert "0060" in refs  # Institution
        assert "0170" in refs  # Total

    def test_dataframe_has_correct_column_count_crr(self) -> None:
        """13 data columns + row_ref + row_name = 15."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        assert len(total.columns) == 15  # 13 data + 2 meta

    def test_dataframe_has_correct_column_count_b31(self) -> None:
        """10 data columns + row_ref + row_name = 12."""
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        # C 09.01 is SA only — IRB exposures excluded
        if "TOTAL" in bundle.c09_01:
            total = bundle.c09_01["TOTAL"]
            total_row = total.filter(pl.col("row_ref") == "0170")
            # Should only include SA exposure (500.0), not IRB (1000.0)
            assert total_row["0075"][0] == pytest.approx(500.0)

    def test_multi_country_isolation(self) -> None:
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # ead_gross sum: 1200 + 600 + 2100 + 3200 + 300 = 7400
        assert total_row["0010"][0] == pytest.approx(7400.0)

    def test_col_0020_defaulted_exposure(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # Defaulted ead_gross: E5 = 300
        assert total_row["0020"][0] == pytest.approx(300.0)

    def test_col_0075_exposure_value(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # ead_final sum: 1000 + 500 + 2000 + 3000 + 200 = 6700
        assert total_row["0075"][0] == pytest.approx(6700.0)

    def test_col_0090_rwea(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        # rwa_final sum: 1000 + 500 + 400 + 1050 + 300 = 3250
        assert total_row["0090"][0] == pytest.approx(3250.0)

    def test_col_0080_crr_pre_supporting_factors(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0080"][0] == pytest.approx(3250.0)

    def test_corporate_row_values(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0070")
        # Corporate EAD: 1000 + 500 = 1500
        assert corp_row["0075"][0] == pytest.approx(1500.0)

    def test_institution_row_values(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        inst_row = total.filter(pl.col("row_ref") == "0060")
        # Institution EAD: 2000
        assert inst_row["0075"][0] == pytest.approx(2000.0)

    def test_defaulted_row_values(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        def_row = total.filter(pl.col("row_ref") == "0100")
        # Defaulted EAD: 200
        assert def_row["0075"][0] == pytest.approx(200.0)


class TestC0901B31Features:
    """Test Basel 3.1 specific features of OF 09.01."""

    def test_no_supporting_factor_columns(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_01["TOTAL"]
        assert "0080" not in total.columns
        assert "0081" not in total.columns
        assert "0082" not in total.columns

    def test_col_0090_is_plain_rwea(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0090"][0] == pytest.approx(3250.0)

    def test_b31_has_more_rows(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_geo_multi_class(), framework="BASEL_3_1")
        total_b31 = bundle.c09_01["TOTAL"]
        gen2 = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.c09_01) == 2  # TOTAL + GB
        # TOTAL and GB should have same values
        total_rwa = bundle.c09_01["TOTAL"].filter(pl.col("row_ref") == "0170")["0090"][0]
        gb_rwa = bundle.c09_01["GB"].filter(pl.col("row_ref") == "0170")["0090"][0]
        assert total_rwa == pytest.approx(gb_rwa)

    def test_total_equals_sum_of_countries(self) -> None:
        gen = LedgerShimCorepGenerator()
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
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_01["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0170")
        assert total_row["0075"][0] == pytest.approx(0.0)

    def test_bundle_field_default_empty(self) -> None:
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c09_01 == {}
        assert bundle.c09_02 == {}


class TestC0901DefaultedAllocation:
    """Annex II C 09.1 recorded fix (2026-07-12): primary columns follow the
    APPLIED Art. 112 ladder (defaulted -> row 0100, as C 07.00); column
    0020 is a MEMORANDUM on the obligor's ORIGINAL class row ("where the
    obligors would have been reported if those exposures were not assigned
    to 'exposures in default'")."""

    @staticmethod
    def _defaulted_corporate() -> pl.LazyFrame:
        return pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "exposure_class_applied": ["corporate", "defaulted"],
                "ead_final": [1000.0, 200.0],
                "ead_gross": [1200.0, 300.0],
                "rwa_final": [1000.0, 300.0],
                "cp_country_code": ["GB", "GB"],
                "default_status": [False, True],
            }
        )

    def test_primary_columns_move_to_default_row(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(self._defaulted_corporate(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        default_row = total.filter(pl.col("row_ref") == "0100")
        assert default_row["0010"][0] == pytest.approx(300.0)
        assert default_row["0075"][0] == pytest.approx(200.0)
        assert default_row["0090"][0] == pytest.approx(300.0)

    def test_corporate_row_primary_excludes_defaulted(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(self._defaulted_corporate(), framework="CRR")
        corp = bundle.c09_01["TOTAL"].filter(pl.col("row_ref") == "0070")
        assert corp["0010"][0] == pytest.approx(1200.0)
        assert corp["0075"][0] == pytest.approx(1000.0)

    def test_memo_0020_stays_on_original_class_row(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(self._defaulted_corporate(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        corp = total.filter(pl.col("row_ref") == "0070")
        default_row = total.filter(pl.col("row_ref") == "0100")
        assert corp["0020"][0] == pytest.approx(300.0)  # the memo look-through
        assert default_row["0020"][0] == pytest.approx(0.0)

    def test_memo_survives_when_class_row_otherwise_empty(self) -> None:
        """A class whose ONLY exposure defaulted keeps its 0020 memo while
        the primary columns sit in row 0100."""
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["institution"],
                "exposure_class_applied": ["defaulted"],
                "ead_final": [500.0],
                "ead_gross": [600.0],
                "rwa_final": [750.0],
                "cp_country_code": ["GB"],
                "default_status": [True],
            }
        )
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(frame, framework="CRR")
        total = bundle.c09_01["TOTAL"]
        inst = total.filter(pl.col("row_ref") == "0060")
        assert inst["0020"][0] == pytest.approx(600.0)
        assert inst["0010"][0] == pytest.approx(0.0)  # primary moved to 0100
        default_row = total.filter(pl.col("row_ref") == "0100")
        assert default_row["0010"][0] == pytest.approx(600.0)


def _b31_re_results() -> pl.LazyFrame:
    """B31 SA real-estate book — one exposure per RE sub-row plus a corporate
    control. RE reporting classes: retail_mortgage (retail RRE), and the SA
    loan-splitter's residential_mortgage / commercial_mortgage secured legs."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["RRE", "RESI", "CRE", "OTHR", "ADC", "CORP"],
            "approach_applied": ["standardised"] * 6,
            "exposure_class": [
                "retail_mortgage",
                "residential_mortgage",
                "commercial_mortgage",
                "commercial_mortgage",
                "commercial_mortgage",
                "corporate",
            ],
            "ead_final": [400.0, 300.0, 1000.0, 200.0, 150.0, 5000.0],
            "ead_gross": [400.0, 300.0, 1000.0, 200.0, 150.0, 5000.0],
            "rwa_final": [140.0, 105.0, 500.0, 300.0, 225.0, 5000.0],
            "cp_country_code": ["GB"] * 6,
            "property_type": [
                "residential",
                "residential",
                "commercial",
                "residential",
                "adc",
                None,
            ],
            "is_qualifying_re": [True, True, True, False, True, None],
            "is_adc": [False, False, False, False, True, None],
            "is_sme": [False, False, False, False, False, False],
            "default_status": [False] * 6,
        }
    )


def _b31_sl_results() -> pl.LazyFrame:
    """B31 SA specialised lending — one exposure per sl_type plus a plain
    corporate. SL maps to the corporate parent row 0070 (Art. 112(1)(g)); the
    of-which rows 0071-0073 split it back out by sl_type."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["OF", "CF", "PF", "CORP"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": [
                "specialised_lending",
                "specialised_lending",
                "specialised_lending",
                "corporate",
            ],
            "sl_type": ["object_finance", "commodities_finance", "project_finance", None],
            "ead_final": [100.0, 200.0, 300.0, 1000.0],
            "ead_gross": [100.0, 200.0, 300.0, 1000.0],
            "rwa_final": [100.0, 200.0, 300.0, 1000.0],
            "cp_country_code": ["GB"] * 4,
            "default_status": [False] * 4,
        }
    )


class TestC0901B31RealEstateRows:
    """OF 09.01 real-estate rows 0090-0095 (rectification R7).

    Before R7 every RE row was permanently null because the reverse map had no
    ``real_estate`` / ``re_*`` value, so B31 RE money (retail mortgages, the
    loan-splitter's secured legs) was missing from every class row and only
    survived in the country Total. These rows now key the RE reporting classes.
    """

    @staticmethod
    def _total() -> pl.DataFrame:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_b31_re_results(), framework="BASEL_3_1")
        return bundle.c09_01["TOTAL"]

    def test_parent_row_0090_sums_all_re_classes(self) -> None:
        row = self._total().filter(pl.col("row_ref") == "0090")
        # retail_mortgage 400 + residential_mortgage 300 + commercial_mortgage (1000+200+150)
        assert row["0075"][0] == pytest.approx(2050.0)
        assert row["0010"][0] == pytest.approx(2050.0)

    def test_row_0091_regulatory_residential(self) -> None:
        # RRE (retail_mortgage, residential, qualifying) + RESI (residential_mortgage).
        row = self._total().filter(pl.col("row_ref") == "0091")
        assert row["0075"][0] == pytest.approx(700.0)

    def test_row_0092_regulatory_commercial(self) -> None:
        # CRE (commercial_mortgage, commercial, qualifying) only.
        row = self._total().filter(pl.col("row_ref") == "0092")
        assert row["0075"][0] == pytest.approx(1000.0)

    def test_row_0093_other_real_estate(self) -> None:
        # OTHR (is_qualifying_re explicitly False).
        row = self._total().filter(pl.col("row_ref") == "0093")
        assert row["0075"][0] == pytest.approx(200.0)

    def test_row_0094_land_adc(self) -> None:
        # ADC (is_adc True).
        row = self._total().filter(pl.col("row_ref") == "0094")
        assert row["0075"][0] == pytest.approx(150.0)

    def test_re_sub_rows_partition_the_parent(self) -> None:
        """0090 == 0091 + 0092 + 0093 + 0094 (the property/qualifying/ADC
        discriminators partition the RE class for this well-formed book)."""
        total = self._total()

        def ead(ref: str) -> float:
            return float(total.filter(pl.col("row_ref") == ref)["0075"][0])

        assert ead("0090") == pytest.approx(ead("0091") + ead("0092") + ead("0093") + ead("0094"))

    def test_row_0095_re_sme_is_null_without_sme(self) -> None:
        # No RE exposure is SME here -> the SME of-which row stays null.
        row = self._total().filter(pl.col("row_ref") == "0095")
        assert row["0075"][0] is None

    def test_re_money_not_double_counted_in_corporate(self) -> None:
        # commercial_mortgage is an RE class, NOT corporate — the corporate row
        # holds only the plain corporate control (5000).
        corp = self._total().filter(pl.col("row_ref") == "0070")
        assert corp["0075"][0] == pytest.approx(5000.0)

    def test_total_row_still_covers_the_whole_book(self) -> None:
        # Regression guard for the high-severity finding: RE money is in a class
        # row now, and the Total equals the sum of all populated class rows.
        total = self._total()
        grand = float(total.filter(pl.col("row_ref") == "0170")["0075"][0])
        assert grand == pytest.approx(2050.0 + 5000.0)


class TestC0901B31SpecialisedLendingRows:
    """OF 09.01 SA specialised-lending of-which rows 0071-0073 (rectification R7)."""

    @staticmethod
    def _total() -> pl.DataFrame:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_b31_sl_results(), framework="BASEL_3_1")
        return bundle.c09_01["TOTAL"]

    def test_sl_stays_in_corporate_parent_row_0070(self) -> None:
        # SL (object/commodities/project = 600) + corporate 1000 all in row 0070.
        corp = self._total().filter(pl.col("row_ref") == "0070")
        assert corp["0075"][0] == pytest.approx(1600.0)

    def test_row_0071_object_finance(self) -> None:
        row = self._total().filter(pl.col("row_ref") == "0071")
        assert row["0075"][0] == pytest.approx(100.0)

    def test_row_0072_commodities_finance(self) -> None:
        row = self._total().filter(pl.col("row_ref") == "0072")
        assert row["0075"][0] == pytest.approx(200.0)

    def test_row_0073_project_finance(self) -> None:
        row = self._total().filter(pl.col("row_ref") == "0073")
        assert row["0075"][0] == pytest.approx(300.0)


class TestC0901CrrRealEstateUnchanged:
    """CRR C 09.01 must be untouched by R7 — its rows key retail_mortgage /
    corporate directly and never reach the RE/SL branch."""

    def test_crr_retail_mortgage_in_row_0090(self) -> None:
        # CRR row 0090 is "Secured by mortgages" keyed retail_mortgage.
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_b31_re_results(), framework="CRR")
        total = bundle.c09_01["TOTAL"]
        # retail_mortgage 400 -> CRR row 0090; the mortgage-class loan-split legs
        # (residential_mortgage / commercial_mortgage) have no CRR row and stay in
        # the Total only (pre-existing CRR behaviour, out of R7 scope).
        assert total.filter(pl.col("row_ref") == "0090")["0075"][0] == pytest.approx(400.0)

    def test_crr_has_no_re_sl_sub_rows(self) -> None:
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_b31_sl_results(), framework="CRR")
        refs = bundle.c09_01["TOTAL"]["row_ref"].to_list()
        for ref in ("0071", "0072", "0073", "0091", "0092", "0093", "0094"):
            assert ref not in refs
