"""
Tests for COREP C 08.06 / OF 08.06 — IRB specialised lending slotting template.

C 08.06 reports slotting exposures by category (Strong/Good/Satisfactory/Weak/Default)
× maturity band (< 2.5yr / >= 2.5yr), one submission per SL type.

Why: The slotting template is a mandatory regulatory report for specialised lending
under CRR Art. 153(5). These tests verify that pipeline slotting data is correctly
reshaped into the regulatory template format with correct row/column structure,
category assignment, maturity band allocation, and column value computation.

References:
- CRR Art. 153(5), Regulation (EU) 2021/451 Annex I (C 08.06)
- PRA PS1/26 Art. 153(5) Table A (OF 08.06)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.templates import (
    B31_C08_06_COLUMNS,
    B31_C08_06_ROWS,
    B31_SL_TYPES,
    C08_06_CATEGORY_MAP,
    C08_06_COLUMN_REFS,
    CRR_C08_06_COLUMNS,
    CRR_C08_06_ROWS,
    CRR_SL_TYPES,
    get_c08_06_columns,
    get_c08_06_rows,
    get_c08_06_sl_types,
)

# =============================================================================
# TEST FIXTURES (module-level functions, not pytest fixtures)
# =============================================================================


def _slotting_results() -> pl.LazyFrame:
    """Slotting pipeline results with known values for hand-verification.

    Contains 6 exposures across 2 SL types:
    - 2 project_finance: strong/short (RW 50%, EAD 1M), good/long (RW 90%, EAD 2M)
    - 2 ipre: satisfactory/short (RW 115%, EAD 500K), weak/long (RW 250%, EAD 300K)
    - 1 ipre: default/long (RW 0%, EAD 100K)
    - 1 object_finance: strong/long (RW 70%, EAD 1.5M)

    Expected values:
    - PF total EAD: 3M (1M + 2M)
    - PF strong/short EAD: 1M, RWEA: 500K (1M * 0.50)
    - PF good/long EAD: 2M, RWEA: 1.8M (2M * 0.90)
    - IPRE total EAD: 900K (500K + 300K + 100K)
    - OF strong/long EAD: 1.5M, RWEA: 1.05M (1.5M * 0.70)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL001", "SL002", "SL003", "SL004", "SL005", "SL006"],
            "counterparty_reference": ["CP01", "CP02", "CP03", "CP04", "CP05", "CP06"],
            "exposure_class": ["specialised_lending"] * 6,
            "approach_applied": ["slotting"] * 6,
            "sl_type": [
                "project_finance",
                "project_finance",
                "ipre",
                "ipre",
                "ipre",
                "object_finance",
            ],
            "slotting_category": [
                "strong",
                "good",
                "satisfactory",
                "weak",
                "default",
                "strong",
            ],
            "is_hvcre": [False, False, False, False, False, False],
            "is_short_maturity": [True, False, True, False, False, False],
            "risk_weight": [0.50, 0.90, 1.15, 2.50, 0.0, 0.70],
            "ead_final": [1_000_000, 2_000_000, 500_000, 300_000, 100_000, 1_500_000],
            "rwa_final": [500_000, 1_800_000, 575_000, 750_000, 0, 1_050_000],
            "drawn_amount": [900_000, 1_800_000, 450_000, 270_000, 90_000, 1_350_000],
            "nominal_amount": [100_000, 200_000, 50_000, 30_000, 10_000, 150_000],
            "expected_loss": [4_000, 16_000, 14_000, 24_000, 50_000, 6_000],
            "provision_held": [2_000, 8_000, 7_000, 12_000, 50_000, 3_000],
        }
    )


def _slotting_results_with_irb() -> pl.LazyFrame:
    """Slotting + IRB results to verify slotting-only filtering.

    Has 2 slotting and 2 F-IRB exposures. Only slotting should appear in C 08.06.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL001", "SL002", "IRB01", "IRB02"],
            "counterparty_reference": ["CP01", "CP02", "CP03", "CP04"],
            "exposure_class": [
                "specialised_lending",
                "specialised_lending",
                "corporate",
                "corporate",
            ],
            "approach_applied": ["slotting", "slotting", "foundation_irb", "advanced_irb"],
            "sl_type": ["project_finance", "project_finance", None, None],
            "slotting_category": ["strong", "good", None, None],
            "is_hvcre": [False, False, None, None],
            "is_short_maturity": [True, False, None, None],
            "risk_weight": [0.50, 0.90, 0.65, 0.45],
            "ead_final": [1_000_000, 2_000_000, 500_000, 300_000],
            "rwa_final": [500_000, 1_800_000, 325_000, 135_000],
            "drawn_amount": [900_000, 1_800_000, 450_000, 270_000],
            "nominal_amount": [100_000, 200_000, 50_000, 30_000],
            "expected_loss": [4_000, 16_000, 5_000, 3_000],
            "provision_held": [2_000, 8_000, 2_500, 1_500],
        }
    )


def _b31_slotting_with_hvcre() -> pl.LazyFrame:
    """Basel 3.1 slotting data with HVCRE separated from IPRE.

    Under B31, HVCRE is reported as a separate SL type.
    - 1 IPRE: strong/long (RW 70%, EAD 2M)
    - 1 HVCRE: strong/long (RW 95%, EAD 1M)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL_IPRE", "SL_HVCRE"],
            "counterparty_reference": ["CP_IPRE", "CP_HVCRE"],
            "exposure_class": ["specialised_lending", "specialised_lending"],
            "approach_applied": ["slotting", "slotting"],
            "sl_type": ["ipre", "hvcre"],
            "slotting_category": ["strong", "strong"],
            "is_hvcre": [False, True],
            "is_short_maturity": [False, False],
            "risk_weight": [0.70, 0.95],
            "ead_final": [2_000_000, 1_000_000],
            "rwa_final": [1_400_000, 950_000],
            "drawn_amount": [1_800_000, 900_000],
            "nominal_amount": [200_000, 100_000],
            "expected_loss": [8_000, 4_000],
            "provision_held": [4_000, 2_000],
        }
    )


def _sa_only_results() -> pl.LazyFrame:
    """SA-only results with no slotting exposures."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA01", "SA02"],
            "counterparty_reference": ["CP01", "CP02"],
            "exposure_class": ["corporate", "retail_mortgage"],
            "approach_applied": ["standardised", "standardised"],
            "risk_weight": [1.0, 0.35],
            "ead_final": [500_000, 300_000],
            "rwa_final": [500_000, 105_000],
            "drawn_amount": [500_000, 300_000],
        }
    )


def _slotting_with_supporting_factors() -> pl.LazyFrame:
    """CRR slotting data with infrastructure supporting factor applied."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL_SF"],
            "counterparty_reference": ["CP_SF"],
            "exposure_class": ["specialised_lending"],
            "approach_applied": ["slotting"],
            "sl_type": ["project_finance"],
            "slotting_category": ["strong"],
            "is_hvcre": [False],
            "is_short_maturity": [False],
            "risk_weight": [0.70],
            "ead_final": [1_000_000],
            "rwa_final": [525_000],
            "rwa_post_factor": [525_000],  # 700K * 0.75 SF
            "drawn_amount": [900_000],
            "nominal_amount": [100_000],
            "expected_loss": [4_000],
            "provision_held": [2_000],
        }
    )


# =============================================================================
# TEMPLATE DEFINITIONS TESTS
# =============================================================================


class TestC0806TemplateDefinitions:
    """Verify template structure constants are correctly defined."""

    def test_crr_column_count(self):
        assert len(CRR_C08_06_COLUMNS) == 10

    def test_b31_column_count(self):
        assert len(B31_C08_06_COLUMNS) == 11

    def test_b31_adds_fccm_column(self):
        b31_refs = {c.ref for c in B31_C08_06_COLUMNS}
        crr_refs = {c.ref for c in CRR_C08_06_COLUMNS}
        assert "0031" in b31_refs
        assert "0031" not in crr_refs

    def test_crr_row_count(self):
        assert len(CRR_C08_06_ROWS) == 12

    def test_b31_row_count(self):
        assert len(B31_C08_06_ROWS) == 14

    def test_b31_adds_substantially_stronger_rows(self):
        b31_refs = {row[0] for row in B31_C08_06_ROWS}
        crr_refs = {row[0] for row in CRR_C08_06_ROWS}
        assert "0015" in b31_refs
        assert "0025" in b31_refs
        assert "0015" not in crr_refs
        assert "0025" not in crr_refs

    def test_column_refs_match_crr(self):
        assert [c.ref for c in CRR_C08_06_COLUMNS] == C08_06_COLUMN_REFS

    def test_get_c08_06_columns_crr(self):
        assert get_c08_06_columns("CRR") is CRR_C08_06_COLUMNS

    def test_get_c08_06_columns_b31(self):
        assert get_c08_06_columns("BASEL_3_1") is B31_C08_06_COLUMNS

    def test_get_c08_06_rows_crr(self):
        assert get_c08_06_rows("CRR") is CRR_C08_06_ROWS

    def test_get_c08_06_rows_b31(self):
        assert get_c08_06_rows("BASEL_3_1") is B31_C08_06_ROWS

    def test_crr_sl_types_count(self):
        assert len(CRR_SL_TYPES) == 4

    def test_b31_sl_types_count(self):
        assert len(B31_SL_TYPES) == 5

    def test_b31_separates_hvcre(self):
        assert "hvcre" in B31_SL_TYPES
        assert "hvcre" not in CRR_SL_TYPES

    def test_get_sl_types_crr(self):
        assert get_c08_06_sl_types("CRR") is CRR_SL_TYPES

    def test_get_sl_types_b31(self):
        assert get_c08_06_sl_types("BASEL_3_1") is B31_SL_TYPES

    def test_category_map_covers_all_categories(self):
        expected = {"strong", "good", "satisfactory", "weak", "default"}
        assert set(C08_06_CATEGORY_MAP.values()) == expected

    def test_crr_rwea_label_includes_supporting_factors(self):
        rwea_col = [c for c in CRR_C08_06_COLUMNS if c.ref == "0080"][0]
        assert "supporting factors" in rwea_col.name.lower()

    def test_b31_rwea_label_excludes_supporting_factors(self):
        rwea_col = [c for c in B31_C08_06_COLUMNS if c.ref == "0080"][0]
        assert "supporting factors" not in rwea_col.name.lower()


# =============================================================================
# GENERATION TESTS
# =============================================================================


class TestC0806Generation:
    """Verify C 08.06 template generation produces correct structure."""

    def test_c08_06_is_dict(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        assert isinstance(bundle.c08_06, dict)

    def test_c08_06_keys_are_sl_types(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        assert "project_finance" in bundle.c08_06
        assert "ipre" in bundle.c08_06
        assert "object_finance" in bundle.c08_06

    def test_c08_06_crr_column_count(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="CRR")
        for sl_type, df in bundle.c08_06.items():
            # 10 data columns + row_ref + row_name = 12
            assert len(df.columns) == 12, f"{sl_type}: expected 12 cols, got {len(df.columns)}"

    def test_c08_06_b31_column_count(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="BASEL_3_1")
        for sl_type, df in bundle.c08_06.items():
            # 11 data columns + row_ref + row_name = 13
            assert len(df.columns) == 13, f"{sl_type}: expected 13 cols, got {len(df.columns)}"

    def test_c08_06_empty_for_sa_only(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_only_results())
        assert bundle.c08_06 == {}

    def test_c08_06_excludes_irb_exposures(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results_with_irb())
        # Only project_finance SL type should appear (the 2 slotting exposures)
        assert "project_finance" in bundle.c08_06
        # Corporate IRB exposures should NOT appear
        assert "corporate" not in bundle.c08_06

    def test_c08_06_default_factory_empty(self):
        """COREPTemplateBundle.c08_06 defaults to empty dict."""
        from rwa_calc.reporting.corep.generator import COREPTemplateBundle

        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c08_06 == {}

    def test_c08_06_framework_in_bundle(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="CRR")
        assert bundle.framework == "CRR"


# =============================================================================
# ROW ASSIGNMENT TESTS
# =============================================================================


class TestC0806RowAssignment:
    """Verify exposures land in correct category × maturity rows."""

    def test_strong_short_maturity_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        row = pf.filter(pl.col("row_ref") == "0010")
        assert len(row) == 1
        assert row["row_name"][0] == "Category 1 (Strong)"
        # EAD should be 1M (the strong/short PF exposure)
        assert row["0040"][0] == pytest.approx(1_000_000, rel=1e-4)

    def test_good_long_maturity_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        row = pf.filter(pl.col("row_ref") == "0040")
        assert len(row) == 1
        assert row["row_name"][0] == "Category 2 (Good)"
        assert row["0040"][0] == pytest.approx(2_000_000, rel=1e-4)

    def test_satisfactory_short_maturity_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        ipre = bundle.c08_06["ipre"]
        row = ipre.filter(pl.col("row_ref") == "0050")
        assert len(row) == 1
        assert row["0040"][0] == pytest.approx(500_000, rel=1e-4)

    def test_weak_long_maturity_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        ipre = bundle.c08_06["ipre"]
        row = ipre.filter(pl.col("row_ref") == "0080")
        assert len(row) == 1
        assert row["0040"][0] == pytest.approx(300_000, rel=1e-4)

    def test_default_long_maturity_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        ipre = bundle.c08_06["ipre"]
        row = ipre.filter(pl.col("row_ref") == "0100")
        assert len(row) == 1
        assert row["0040"][0] == pytest.approx(100_000, rel=1e-4)

    def test_total_short_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        ipre = bundle.c08_06["ipre"]
        row = ipre.filter(pl.col("row_ref") == "0110")
        assert len(row) == 1
        # Only satisfactory/short (500K)
        assert row["0040"][0] == pytest.approx(500_000, rel=1e-4)

    def test_total_long_row(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        ipre = bundle.c08_06["ipre"]
        row = ipre.filter(pl.col("row_ref") == "0120")
        assert len(row) == 1
        # weak/long (300K) + default/long (100K) = 400K
        assert row["0040"][0] == pytest.approx(400_000, rel=1e-4)

    def test_empty_categories_have_zero_values(self):
        """Categories with no exposures should still appear with zero values."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        # PF has no satisfactory, weak, or default exposures
        row_0050 = pf.filter(pl.col("row_ref") == "0050")
        assert len(row_0050) == 1
        assert row_0050["0040"][0] == pytest.approx(0.0)


# =============================================================================
# COLUMN VALUE TESTS
# =============================================================================


class TestC0806ColumnValues:
    """Verify individual column computations are correct."""

    def test_col_0010_original_exposure(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        # drawn_amount + nominal_amount = 900K + 100K = 1M
        assert strong_short["0010"][0] == pytest.approx(1_000_000, rel=1e-4)

    def test_col_0040_ead(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        good_long = pf.filter(pl.col("row_ref") == "0040")
        assert good_long["0040"][0] == pytest.approx(2_000_000, rel=1e-4)

    def test_col_0070_risk_weight(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0070"][0] == pytest.approx(0.50, rel=1e-4)

    def test_col_0070_weighted_average_for_total(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        total_long = pf.filter(pl.col("row_ref") == "0120")
        # Only good/long: RW 90%, EAD 2M → weighted avg = 0.90
        assert total_long["0070"][0] == pytest.approx(0.90, rel=1e-4)

    def test_col_0080_rwea(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0080"][0] == pytest.approx(500_000, rel=1e-4)

    def test_col_0090_expected_loss(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0090"][0] == pytest.approx(4_000, rel=1e-4)

    def test_col_0100_provisions(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0100"][0] == pytest.approx(2_000, rel=1e-4)

    def test_col_0030_off_bs_original(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        # nominal_amount = 100K (off-BS proxy)
        assert strong_short["0030"][0] == pytest.approx(100_000, rel=1e-4)

    def test_col_0060_ccr_none_for_populated_rows(self):
        """CCR column is None for rows with actual exposures (CCR is out of scope)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        # Check populated rows (strong/short and good/long have exposures)
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0060"][0] is None
        good_long = pf.filter(pl.col("row_ref") == "0040")
        assert good_long["0060"][0] is None

    def test_total_ead_equals_sum_of_maturity_bands(self):
        """Total short EAD + total long EAD = sum of all individual EADs."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        total_short = pf.filter(pl.col("row_ref") == "0110")["0040"][0]
        total_long = pf.filter(pl.col("row_ref") == "0120")["0040"][0]
        # PF: 1M (short) + 2M (long) = 3M
        assert total_short + total_long == pytest.approx(3_000_000, rel=1e-4)

    def test_total_rwea_equals_sum_of_maturity_bands(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf = bundle.c08_06["project_finance"]
        total_short = pf.filter(pl.col("row_ref") == "0110")["0080"][0]
        total_long = pf.filter(pl.col("row_ref") == "0120")["0080"][0]
        # PF: 500K (short) + 1.8M (long) = 2.3M
        assert total_short + total_long == pytest.approx(2_300_000, rel=1e-4)


# =============================================================================
# BASEL 3.1 SPECIFIC TESTS
# =============================================================================


class TestC0806B31Features:
    """Verify Basel 3.1-specific template features."""

    def test_b31_fccm_column_present(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="BASEL_3_1")
        for sl_type, df in bundle.c08_06.items():
            assert "0031" in df.columns, f"{sl_type}: missing col 0031"

    def test_b31_fccm_column_null_for_populated_rows(self):
        """FCCM deduction is None for populated rows (not yet wired from pipeline)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="BASEL_3_1")
        pf = bundle.c08_06["project_finance"]
        # Strong/short has actual data — FCCM should be None
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0031"][0] is None

    def test_b31_hvcre_separate_sl_type(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_slotting_with_hvcre(), framework="BASEL_3_1")
        assert "ipre" in bundle.c08_06
        assert "hvcre" in bundle.c08_06

    def test_b31_hvcre_ead_correct(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_slotting_with_hvcre(), framework="BABEL_3_1" if False else "BASEL_3_1"
        )
        hvcre = bundle.c08_06["hvcre"]
        total_long = hvcre.filter(pl.col("row_ref") == "0120")
        assert total_long["0040"][0] == pytest.approx(1_000_000, rel=1e-4)

    def test_b31_ipre_excludes_hvcre(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_slotting_with_hvcre(), framework="BASEL_3_1")
        ipre = bundle.c08_06["ipre"]
        total_long = ipre.filter(pl.col("row_ref") == "0120")
        # Only IPRE exposure (2M), not HVCRE (1M)
        assert total_long["0040"][0] == pytest.approx(2_000_000, rel=1e-4)

    def test_b31_substantially_stronger_rows_present(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="BASEL_3_1")
        pf = bundle.c08_06["project_finance"]
        row_0015 = pf.filter(pl.col("row_ref") == "0015")
        row_0025 = pf.filter(pl.col("row_ref") == "0025")
        assert len(row_0015) == 1
        assert len(row_0025) == 1

    def test_b31_substantially_stronger_rows_zero_ead(self):
        """Substantially stronger rows have zero EAD (pipeline doesn't identify them yet)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="BASEL_3_1")
        pf = bundle.c08_06["project_finance"]
        row_0015 = pf.filter(pl.col("row_ref") == "0015")
        assert row_0015["0040"][0] == pytest.approx(0.0)

    def test_crr_no_fccm_column(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results(), framework="CRR")
        for sl_type, df in bundle.c08_06.items():
            assert "0031" not in df.columns, f"{sl_type}: CRR should not have col 0031"

    def test_crr_combines_ipre_hvcre(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_slotting_with_hvcre(), framework="CRR")
        # Under CRR, IPRE and HVCRE are combined into one SL type
        assert "ipre" in bundle.c08_06
        ipre = bundle.c08_06["ipre"]
        total_long = ipre.filter(pl.col("row_ref") == "0120")
        # Both IPRE (2M) and HVCRE (1M) = 3M
        assert total_long["0040"][0] == pytest.approx(3_000_000, rel=1e-4)


# =============================================================================
# SUPPORTING FACTORS TESTS
# =============================================================================


class TestC0806SupportingFactors:
    """Verify CRR supporting factor handling in RWEA column."""

    def test_crr_uses_post_factor_rwea(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_with_supporting_factors(), framework="CRR")
        pf = bundle.c08_06["project_finance"]
        strong_long = pf.filter(pl.col("row_ref") == "0020")
        # rwa_post_factor = 525K (with SF)
        assert strong_long["0080"][0] == pytest.approx(525_000, rel=1e-4)

    def test_b31_uses_plain_rwea(self):
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _slotting_with_supporting_factors(), framework="BASEL_3_1"
        )
        pf = bundle.c08_06["project_finance"]
        strong_long = pf.filter(pl.col("row_ref") == "0020")
        # B31 should use rwa_final (525K) — no separate post-factor under B31
        assert strong_long["0080"][0] == pytest.approx(525_000, rel=1e-4)


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestC0806EdgeCases:
    """Verify edge cases and error handling."""

    def test_no_approach_column_returns_empty(self):
        lf = pl.LazyFrame(
            {"ead_final": [100.0], "rwa_final": [50.0], "slotting_category": ["strong"]}
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        assert bundle.c08_06 == {}

    def test_no_slotting_category_returns_empty(self):
        lf = pl.LazyFrame(
            {
                "approach_applied": ["slotting"],
                "ead_final": [100.0],
                "rwa_final": [50.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        assert bundle.c08_06 == {}

    def test_missing_ead_column_returns_empty(self):
        lf = pl.LazyFrame(
            {
                "approach_applied": ["slotting"],
                "slotting_category": ["strong"],
                "rwa_final": [50.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        assert bundle.c08_06 == {}

    def test_no_sl_type_column_uses_single_key(self):
        """Without sl_type column, all slotting goes to 'specialised_lending' key."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL01"],
                "counterparty_reference": ["CP01"],
                "approach_applied": ["slotting"],
                "slotting_category": ["strong"],
                "is_short_maturity": [True],
                "risk_weight": [0.50],
                "ead_final": [1_000_000],
                "rwa_final": [500_000],
                "drawn_amount": [900_000],
                "nominal_amount": [100_000],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        assert "specialised_lending" in bundle.c08_06

    def test_no_maturity_column_defaults_to_long(self):
        """Without is_short_maturity, all exposures go to long maturity rows."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL01"],
                "counterparty_reference": ["CP01"],
                "approach_applied": ["slotting"],
                "sl_type": ["project_finance"],
                "slotting_category": ["strong"],
                "risk_weight": [0.70],
                "ead_final": [1_000_000],
                "rwa_final": [700_000],
                "drawn_amount": [900_000],
                "nominal_amount": [100_000],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        pf = bundle.c08_06["project_finance"]
        # Short maturity row should have 0 EAD
        total_short = pf.filter(pl.col("row_ref") == "0110")
        assert total_short["0040"][0] == pytest.approx(0.0)
        # Long maturity total should have full 1M
        total_long = pf.filter(pl.col("row_ref") == "0120")
        assert total_long["0040"][0] == pytest.approx(1_000_000, rel=1e-4)

    def test_zero_ead_exposure(self):
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL01"],
                "counterparty_reference": ["CP01"],
                "approach_applied": ["slotting"],
                "sl_type": ["project_finance"],
                "slotting_category": ["strong"],
                "is_short_maturity": [True],
                "risk_weight": [0.50],
                "ead_final": [0.0],
                "rwa_final": [0.0],
                "drawn_amount": [0.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        pf = bundle.c08_06["project_finance"]
        strong_short = pf.filter(pl.col("row_ref") == "0010")
        assert strong_short["0040"][0] == pytest.approx(0.0)

    def test_errors_list_populated_on_missing_columns(self):
        lf = pl.LazyFrame(
            {
                "approach_applied": ["slotting"],
                "ead_final": [100.0],
                "rwa_final": [50.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(lf)
        assert any("C08.06" in e for e in bundle.errors)

    def test_multiple_sl_types_independent(self):
        """Each SL type gets its own independent template."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_slotting_results())
        pf_total_ead = (
            bundle.c08_06["project_finance"]
            .filter(pl.col("row_ref").is_in(["0110", "0120"]))["0040"]
            .sum()
        )
        ipre_total_ead = (
            bundle.c08_06["ipre"].filter(pl.col("row_ref").is_in(["0110", "0120"]))["0040"].sum()
        )
        of_total_ead = (
            bundle.c08_06["object_finance"]
            .filter(pl.col("row_ref").is_in(["0110", "0120"]))["0040"]
            .sum()
        )
        assert pf_total_ead == pytest.approx(3_000_000, rel=1e-4)
        assert ipre_total_ead == pytest.approx(900_000, rel=1e-4)
        assert of_total_ead == pytest.approx(1_500_000, rel=1e-4)
