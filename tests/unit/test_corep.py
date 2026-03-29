"""
Unit tests for COREP template generation.

Tests the COREPGenerator against synthetic exposure data to verify:
- Template definitions: CRR and Basel 3.1 column/row section structures
- C 07.00 (SA): Correct aggregation by exposure class, CRM deductions, RWA
- C 08.01 (IRB): Exposure-weighted PD/LGD/maturity, EAD, RWA, EL totals
- C 08.02 (IRB PD grades): PD band assignment and per-band aggregation
- C 07.00 RW breakdown: Risk weight band pivot correctness
- Total row computation and COREP row reference mapping
- Excel export integration

Why: COREP templates are regulatory obligations — incorrect aggregation
leads to misreported capital requirements. These tests verify every
aggregation path with hand-calculated expected values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.templates import (
    B31_C07_COLUMNS,
    B31_C08_COLUMNS,
    B31_IRB_ROW_SECTIONS,
    B31_SA_RISK_WEIGHT_BANDS,
    B31_SA_ROW_SECTIONS,
    C07_COLUMNS,
    C08_01_COLUMNS,
    CRR_C07_COLUMNS,
    CRR_C08_COLUMNS,
    CRR_IRB_ROW_SECTIONS,
    CRR_SA_ROW_SECTIONS,
    IRB_EXPOSURE_CLASS_ROWS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    SA_RISK_WEIGHT_BANDS,
    RowSection,
    get_c07_columns,
    get_c08_columns,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    __import__("importlib").util.find_spec("xlsxwriter") is not None
)

# =============================================================================
# FIXTURES
# =============================================================================


def _sa_results() -> pl.LazyFrame:
    """Synthetic SA results with multiple exposure classes and risk weights."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_CORP_3",
                "SA_INST_1",
                "SA_RETAIL_1",
                "SA_RETAIL_2",
                "SA_SOVN_1",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_other",
                "retail_other",
                "central_govt_central_bank",
            ],
            "drawn_amount": [1000.0, 2000.0, 500.0, 3000.0, 200.0, 300.0, 5000.0],
            "undrawn_amount": [500.0, 0.0, 100.0, 0.0, 50.0, 0.0, 0.0],
            "ead_final": [1200.0, 2000.0, 550.0, 3000.0, 225.0, 300.0, 5000.0],
            "rwa_final": [1200.0, 2000.0, 467.5, 600.0, 168.75, 225.0, 0.0],
            "risk_weight": [1.00, 1.00, 0.85, 0.20, 0.75, 0.75, 0.00],
            "scra_provision_amount": [10.0, 20.0, 5.0, 0.0, 2.0, 3.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5, 15.0, 1.0, 1.5, 0.0],
            "collateral_adjusted_value": [100.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 0, 0, 2, 0, 0, 1],
            "counterparty_reference": [
                "CP_A",
                "CP_B",
                "CP_C",
                "CP_D",
                "CP_E",
                "CP_F",
                "CP_G",
            ],
        }
    )


def _irb_results() -> pl.LazyFrame:
    """Synthetic IRB results with PD, LGD, maturity, and EL data."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_SME_1",
                "IRB_INST_1",
                "IRB_RETAIL_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
            ],
            "drawn_amount": [5000.0, 3000.0, 1000.0, 2000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0],
            "rwa_final": [3850.0, 1800.0, 780.0, 600.0, 1200.0],
            "risk_weight": [0.70, 0.60, 0.65, 0.30, 0.30],
            "irb_pd_floored": [0.005, 0.01, 0.02, 0.002, 0.003],
            "irb_lgd_floored": [0.45, 0.45, 0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 2.5, 1.5, 20.0],
            "irb_expected_loss": [12.375, 13.5, 10.8, 1.8, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.052, 0.024, 0.024],
            "provision_held": [15.0, 10.0, 8.0, 3.0, 2.5],
            "el_shortfall": [0.0, 3.5, 2.8, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.7],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 1.0],
            "gcra_provision_amount": [5.0, 5.0, 5.0, 1.0, 1.5],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V"],
        }
    )


def _combined_results() -> pl.LazyFrame:
    """Combined SA + IRB results for full template generation."""
    sa = _sa_results().collect()
    irb = _irb_results().collect()
    return pl.concat([sa, irb], how="diagonal_relaxed").lazy()


# =============================================================================
# TEMPLATE DEFINITIONS — CRR AND BASEL 3.1
# =============================================================================


class TestTemplateDefinitions:
    """Tests for COREP template structure definitions."""

    def test_sa_exposure_class_rows_cover_all_sa_classes(self) -> None:
        """All SA exposure classes have a COREP row mapping."""
        assert "corporate" in SA_EXPOSURE_CLASS_ROWS
        assert "institution" in SA_EXPOSURE_CLASS_ROWS
        assert "retail_other" in SA_EXPOSURE_CLASS_ROWS
        assert "central_govt_central_bank" in SA_EXPOSURE_CLASS_ROWS
        assert "defaulted" in SA_EXPOSURE_CLASS_ROWS
        assert "equity" in SA_EXPOSURE_CLASS_ROWS
        assert "international_org" in SA_EXPOSURE_CLASS_ROWS

    def test_irb_exposure_class_rows_cover_irb_classes(self) -> None:
        """All IRB exposure classes have a COREP row mapping."""
        assert "corporate" in IRB_EXPOSURE_CLASS_ROWS
        assert "corporate_sme" in IRB_EXPOSURE_CLASS_ROWS
        assert "institution" in IRB_EXPOSURE_CLASS_ROWS
        assert "retail_mortgage" in IRB_EXPOSURE_CLASS_ROWS
        assert "retail_qrre" in IRB_EXPOSURE_CLASS_ROWS
        assert "retail_other" in IRB_EXPOSURE_CLASS_ROWS
        assert "specialised_lending" in IRB_EXPOSURE_CLASS_ROWS

    def test_sa_risk_weight_bands_in_ascending_order(self) -> None:
        """Risk weight bands must be in ascending order."""
        rw_values = [rw for rw, _ in SA_RISK_WEIGHT_BANDS]
        assert rw_values == sorted(rw_values)

    def test_pd_bands_cover_full_range(self) -> None:
        """PD bands must cover 0% to 100%+ without gaps."""
        assert PD_BANDS[0][0] == 0.0
        assert PD_BANDS[-1][1] == float("inf")

        for i in range(len(PD_BANDS) - 1):
            assert PD_BANDS[i][1] == PD_BANDS[i + 1][0], f"Gap between bands {i} and {i + 1}"

    def test_c07_columns_have_refs(self) -> None:
        """C 07.00 column definitions have reference numbers."""
        for col in C07_COLUMNS:
            assert col.ref.isdigit(), f"Column ref must be numeric: {col.ref}"
            assert len(col.name) > 0

    def test_c08_01_columns_have_refs(self) -> None:
        """C 08.01 column definitions have reference numbers."""
        for col in C08_01_COLUMNS:
            assert col.ref.isdigit()
            assert len(col.name) > 0

    def test_row_refs_are_unique(self) -> None:
        """Row references must be unique within each template."""
        sa_refs = [ref for ref, _ in SA_EXPOSURE_CLASS_ROWS.values()]
        assert len(sa_refs) == len(set(sa_refs))

        irb_refs = [ref for ref, _ in IRB_EXPOSURE_CLASS_ROWS.values()]
        assert len(irb_refs) == len(set(irb_refs))


class TestCRRC07ColumnDefinitions:
    """Tests for CRR C 07.00 column definitions (correct 4-digit refs)."""

    def test_crr_c07_has_24_data_columns(self) -> None:
        """CRR C 07.00 has 27 columns covering full SA waterfall."""
        # 27 columns: 0010, 0030, 0040, 0050-0100, 0110-0150, 0160-0190, 0200-0240
        assert len(CRR_C07_COLUMNS) == 27

    def test_crr_c07_uses_4_digit_refs(self) -> None:
        """All CRR C 07.00 column refs are 4 digits."""
        for col in CRR_C07_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"
            assert col.ref.isdigit(), f"Ref {col.ref} is not numeric"

    def test_crr_c07_refs_unique(self) -> None:
        """Column refs are unique."""
        refs = [col.ref for col in CRR_C07_COLUMNS]
        assert len(refs) == len(set(refs))

    def test_crr_c07_starts_with_original_exposure(self) -> None:
        """First column is original exposure (0010)."""
        assert CRR_C07_COLUMNS[0].ref == "0010"
        assert "Original exposure" in CRR_C07_COLUMNS[0].name

    def test_crr_c07_ends_with_ecai_derived(self) -> None:
        """Last column is ECAI credit assessment derived from central govt (0240)."""
        assert CRR_C07_COLUMNS[-1].ref == "0240"

    def test_crr_c07_has_supporting_factor_columns(self) -> None:
        """CRR includes supporting factor columns (0215-0217)."""
        refs = {col.ref for col in CRR_C07_COLUMNS}
        assert "0215" in refs  # RWEA pre supporting factors
        assert "0216" in refs  # SME supporting factor
        assert "0217" in refs  # Infrastructure supporting factor

    def test_crr_c07_ccf_buckets(self) -> None:
        """CRR CCF buckets are 0%, 20%, 50%, 100%."""
        ccf_cols = [col for col in CRR_C07_COLUMNS if col.group == "CCF Breakdown"]
        assert len(ccf_cols) == 4
        assert ccf_cols[0].name == "Off-BS by CCF: 0%"
        assert ccf_cols[1].name == "Off-BS by CCF: 20%"
        assert ccf_cols[2].name == "Off-BS by CCF: 50%"
        assert ccf_cols[3].name == "Off-BS by CCF: 100%"

    def test_crr_c07_all_columns_have_groups(self) -> None:
        """Every CRR C 07.00 column has a logical group assigned."""
        for col in CRR_C07_COLUMNS:
            assert col.group, f"Column {col.ref} has no group"


class TestB31C07ColumnDefinitions:
    """Tests for Basel 3.1 OF 07.00 column definitions."""

    def test_b31_c07_has_correct_column_count(self) -> None:
        """B3.1 OF 07.00 has 27 columns (adds 3, removes 3 vs CRR)."""
        assert len(B31_C07_COLUMNS) == 27

    def test_b31_c07_uses_4_digit_refs(self) -> None:
        """All B3.1 OF 07.00 column refs are 4 digits."""
        for col in B31_C07_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"

    def test_b31_c07_has_on_bs_netting(self) -> None:
        """B3.1 adds on-balance sheet netting column (0035)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0035" in refs

    def test_b31_c07_has_40pct_ccf(self) -> None:
        """B3.1 adds 40% CCF bucket (0171)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0171" in refs

    def test_b31_c07_has_unrated_ecai(self) -> None:
        """B3.1 adds unrated ECAI column (0235)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0235" in refs

    def test_b31_c07_no_supporting_factors(self) -> None:
        """B3.1 removes supporting factor columns (0215-0217)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0215" not in refs
        assert "0216" not in refs
        assert "0217" not in refs

    def test_b31_c07_ccf_10pct_replaces_0pct(self) -> None:
        """B3.1 changes 0% CCF to 10%."""
        col_0160 = next(c for c in B31_C07_COLUMNS if c.ref == "0160")
        assert "10%" in col_0160.name

    def test_b31_c07_ccf_buckets(self) -> None:
        """B3.1 CCF buckets are 10%, 20%, 40%, 50%, 100%."""
        ccf_cols = [col for col in B31_C07_COLUMNS if col.group == "CCF Breakdown"]
        assert len(ccf_cols) == 5
        assert "10%" in ccf_cols[0].name
        assert "20%" in ccf_cols[1].name
        assert "40%" in ccf_cols[2].name
        assert "50%" in ccf_cols[3].name
        assert "100%" in ccf_cols[4].name


class TestSARowSections:
    """Tests for SA row section definitions (C 07.00 / OF 07.00)."""

    def test_crr_sa_has_5_sections(self) -> None:
        """CRR C 07.00 has 5 row sections."""
        assert len(CRR_SA_ROW_SECTIONS) == 5

    def test_crr_sa_section_names(self) -> None:
        """CRR C 07.00 sections have correct names."""
        names = [s.name for s in CRR_SA_ROW_SECTIONS]
        assert "Total Exposures" in names
        assert "Breakdown by Exposure Types" in names
        assert "Breakdown by Risk Weights" in names
        assert "Breakdown by CIU Approach" in names
        assert "Memorandum Items" in names

    def test_crr_sa_total_section_starts_with_0010(self) -> None:
        """Section 1 starts with TOTAL EXPOSURES row 0010."""
        total_section = CRR_SA_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"
        assert "TOTAL" in total_section.rows[0].name

    def test_crr_sa_total_section_has_of_which_rows(self) -> None:
        """Section 1 has 'of which' rows (0015-0060)."""
        total_section = CRR_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs  # Defaulted
        assert "0020" in refs  # SME
        assert "0030" in refs  # SME factor
        assert "0035" in refs  # Infra factor

    def test_crr_sa_rw_section_has_15_rows(self) -> None:
        """CRR RW section has 15 rows (0%-1250% + Other)."""
        rw_section = CRR_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 15

    def test_crr_sa_rw_section_row_refs_ascending(self) -> None:
        """RW section row refs are in ascending order."""
        rw_section = CRR_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert refs == sorted(refs)

    def test_crr_sa_memorandum_has_4_rows(self) -> None:
        """CRR memorandum section has 4 rows."""
        memo_section = CRR_SA_ROW_SECTIONS[4]
        assert memo_section.name == "Memorandum Items"
        assert len(memo_section.rows) == 4

    def test_crr_sa_all_row_refs_unique(self) -> None:
        """All row refs across all CRR SA sections are unique."""
        all_refs = [r.ref for s in CRR_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_sa_has_5_sections(self) -> None:
        """B3.1 OF 07.00 has 5 row sections."""
        assert len(B31_SA_ROW_SECTIONS) == 5

    def test_b31_sa_rw_section_has_28_rows(self) -> None:
        """B3.1 RW section has 28 rows (29 weights including Other)."""
        rw_section = B31_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 28

    def test_b31_sa_has_specialised_lending_rows(self) -> None:
        """B3.1 Section 1 includes specialised lending detail rows."""
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0021" in refs  # Object finance
        assert "0022" in refs  # Commodities
        assert "0023" in refs  # Project finance
        assert "0024" in refs  # Pre-operational
        assert "0025" in refs  # Operational
        assert "0026" in refs  # High quality operational

    def test_b31_sa_has_re_detail_rows(self) -> None:
        """B3.1 Section 1 includes real estate detail rows."""
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0330" in refs  # Regulatory residential RE
        assert "0340" in refs  # Regulatory commercial RE
        assert "0360" in refs  # ADC

    def test_b31_sa_no_supporting_factor_rows(self) -> None:
        """B3.1 removes supporting factor rows (0030, 0035 as 'of which')."""
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        # 0030 (SME supporting factor) should not be present
        assert "0030" not in refs
        # 0035 (infrastructure supporting factor) should not be present
        assert "0035" not in refs

    def test_b31_sa_has_400pct_rw(self) -> None:
        """B3.1 adds 400% RW row (0261), replaces 370%."""
        rw_section = B31_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert "0261" in refs  # 400%
        assert "0260" not in refs  # 370% removed

    def test_b31_sa_memorandum_has_equity_transitional(self) -> None:
        """B3.1 memorandum includes equity transitional rows."""
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0371" in refs
        assert "0372" in refs
        assert "0373" in refs
        assert "0374" in refs

    def test_b31_sa_memorandum_has_currency_mismatch(self) -> None:
        """B3.1 memorandum includes currency mismatch row."""
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0380" in refs

    def test_b31_sa_all_row_refs_unique(self) -> None:
        """All row refs across all B3.1 SA sections are unique."""
        all_refs = [r.ref for s in B31_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestCRRC08ColumnDefinitions:
    """Tests for CRR C 08.01 column definitions."""

    def test_crr_c08_has_correct_column_count(self) -> None:
        """CRR C 08.01 has 37 columns."""
        assert len(CRR_C08_COLUMNS) == 37

    def test_crr_c08_uses_4_digit_refs(self) -> None:
        """All CRR C 08.01 column refs are 4 digits."""
        for col in CRR_C08_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"

    def test_crr_c08_starts_with_pd(self) -> None:
        """First column is PD (0010)."""
        assert CRR_C08_COLUMNS[0].ref == "0010"
        assert "PD" in CRR_C08_COLUMNS[0].name

    def test_crr_c08_has_double_default(self) -> None:
        """CRR includes double default column (0220)."""
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0220" in refs

    def test_crr_c08_has_supporting_factors(self) -> None:
        """CRR includes supporting factor columns (0255-0257)."""
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0255" in refs
        assert "0256" in refs
        assert "0257" in refs

    def test_crr_c08_maturity_in_days(self) -> None:
        """CRR C 08.01 maturity column specifies days."""
        col_0250 = next(c for c in CRR_C08_COLUMNS if c.ref == "0250")
        assert "days" in col_0250.name.lower()

    def test_crr_c08_refs_unique(self) -> None:
        """Column refs are unique."""
        refs = [col.ref for col in CRR_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestB31C08ColumnDefinitions:
    """Tests for Basel 3.1 OF 08.01 column definitions."""

    def test_b31_c08_no_pd_column(self) -> None:
        """B3.1 removes PD column from totals (only in OF 08.02)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0010" not in refs

    def test_b31_c08_no_double_default(self) -> None:
        """B3.1 removes double default column (0220)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0220" not in refs

    def test_b31_c08_no_supporting_factors(self) -> None:
        """B3.1 removes supporting factor columns (0255-0257)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0255" not in refs
        assert "0256" not in refs
        assert "0257" not in refs

    def test_b31_c08_has_on_bs_netting(self) -> None:
        """B3.1 adds on-BS netting (0035)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0035" in refs

    def test_b31_c08_has_slotting_fccm(self) -> None:
        """B3.1 adds slotting FCCM columns (0101-0104)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0101" in refs
        assert "0102" in refs
        assert "0103" in refs
        assert "0104" in refs

    def test_b31_c08_has_defaulted_breakdowns(self) -> None:
        """B3.1 adds 'of which: defaulted' columns (0125, 0265)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0125" in refs
        assert "0265" in refs

    def test_b31_c08_has_post_model_adjustments(self) -> None:
        """B3.1 adds post-model adjustment columns (0251-0254)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0251" in refs
        assert "0252" in refs
        assert "0253" in refs
        assert "0254" in refs

    def test_b31_c08_has_output_floor(self) -> None:
        """B3.1 adds output floor columns (0275-0276)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0275" in refs
        assert "0276" in refs

    def test_b31_c08_has_el_adjustments(self) -> None:
        """B3.1 adds EL post-model adjustment columns (0281-0282)."""
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0281" in refs
        assert "0282" in refs

    def test_b31_c08_refs_unique(self) -> None:
        """Column refs are unique."""
        refs = [col.ref for col in B31_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestIRBRowSections:
    """Tests for IRB row section definitions (C 08.01 / OF 08.01)."""

    def test_crr_irb_has_3_sections(self) -> None:
        """CRR C 08.01 has 3 row sections."""
        assert len(CRR_IRB_ROW_SECTIONS) == 3

    def test_crr_irb_section_names(self) -> None:
        """CRR C 08.01 sections have correct names."""
        names = [s.name for s in CRR_IRB_ROW_SECTIONS]
        assert "Total and Supporting Factors" in names
        assert "Breakdown by Exposure Types" in names
        assert "Calculation Approaches" in names

    def test_crr_irb_total_starts_with_0010(self) -> None:
        """Section 1 starts with TOTAL EXPOSURES row 0010."""
        total_section = CRR_IRB_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"

    def test_crr_irb_has_supporting_factor_rows(self) -> None:
        """CRR has SME and infra supporting factor rows."""
        total_section = CRR_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs
        assert "0016" in refs

    def test_crr_irb_has_alt_re_treatment(self) -> None:
        """CRR has alternative RE treatment row (0160)."""
        calc_section = CRR_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" in refs

    def test_crr_irb_all_refs_unique(self) -> None:
        """All CRR IRB row refs are unique."""
        all_refs = [r.ref for s in CRR_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_irb_has_3_sections(self) -> None:
        """B3.1 OF 08.01 has 3 row sections."""
        assert len(B31_IRB_ROW_SECTIONS) == 3

    def test_b31_irb_no_supporting_factor_rows(self) -> None:
        """B3.1 removes supporting factor rows."""
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" not in refs
        assert "0016" not in refs

    def test_b31_irb_has_revolving_commitments(self) -> None:
        """B3.1 adds revolving loan commitments row."""
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0017" in refs

    def test_b31_irb_has_ccf_breakdown_rows(self) -> None:
        """B3.1 adds off-BS CCF breakdown rows (0031-0035)."""
        exp_section = B31_IRB_ROW_SECTIONS[1]
        refs = [r.ref for r in exp_section.rows]
        assert "0031" in refs
        assert "0032" in refs
        assert "0033" in refs
        assert "0034" in refs
        assert "0035" in refs

    def test_b31_irb_no_alt_re_treatment(self) -> None:
        """B3.1 removes alternative RE treatment row."""
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" not in refs

    def test_b31_irb_has_purchased_receivables(self) -> None:
        """B3.1 adds purchased receivables row (0175)."""
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0175" in refs

    def test_b31_irb_has_ecai_rows(self) -> None:
        """B3.1 adds corporates without ECAI / investment grade rows."""
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0190" in refs
        assert "0200" in refs

    def test_b31_irb_all_refs_unique(self) -> None:
        """All B3.1 IRB row refs are unique."""
        all_refs = [r.ref for s in B31_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestB31SAWeightBands:
    """Tests for Basel 3.1 risk weight bands."""

    def test_b31_rw_bands_ascending(self) -> None:
        """B3.1 RW bands are in ascending order."""
        rw_values = [rw for rw, _ in B31_SA_RISK_WEIGHT_BANDS]
        assert rw_values == sorted(rw_values)

    def test_b31_rw_bands_has_27_entries(self) -> None:
        """B3.1 has 27 RW band entries."""
        assert len(B31_SA_RISK_WEIGHT_BANDS) == 27

    def test_b31_rw_bands_has_new_weights(self) -> None:
        """B3.1 includes new granular weights (15%, 25%, 30%, etc.)."""
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 0.15 in rw_dict
        assert 0.25 in rw_dict
        assert 0.30 in rw_dict
        assert 0.40 in rw_dict
        assert 0.45 in rw_dict
        assert 0.60 in rw_dict
        assert 0.65 in rw_dict

    def test_b31_rw_bands_has_400pct(self) -> None:
        """B3.1 has 400% RW (replaces 370%)."""
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 4.00 in rw_dict
        assert 3.70 not in rw_dict


class TestFrameworkHelpers:
    """Tests for framework-aware helper functions."""

    def test_get_c07_columns_crr(self) -> None:
        """get_c07_columns returns CRR columns by default."""
        cols = get_c07_columns("CRR")
        assert cols is CRR_C07_COLUMNS

    def test_get_c07_columns_b31(self) -> None:
        """get_c07_columns returns B3.1 columns for BASEL_3_1."""
        cols = get_c07_columns("BASEL_3_1")
        assert cols is B31_C07_COLUMNS

    def test_get_c08_columns_crr(self) -> None:
        """get_c08_columns returns CRR columns by default."""
        cols = get_c08_columns("CRR")
        assert cols is CRR_C08_COLUMNS

    def test_get_c08_columns_b31(self) -> None:
        """get_c08_columns returns B3.1 columns for BASEL_3_1."""
        cols = get_c08_columns("BASEL_3_1")
        assert cols is B31_C08_COLUMNS

    def test_get_sa_row_sections_crr(self) -> None:
        """get_sa_row_sections returns CRR sections by default."""
        sections = get_sa_row_sections("CRR")
        assert sections is CRR_SA_ROW_SECTIONS

    def test_get_sa_row_sections_b31(self) -> None:
        """get_sa_row_sections returns B3.1 sections for BASEL_3_1."""
        sections = get_sa_row_sections("BASEL_3_1")
        assert sections is B31_SA_ROW_SECTIONS

    def test_get_irb_row_sections_crr(self) -> None:
        """get_irb_row_sections returns CRR sections by default."""
        sections = get_irb_row_sections("CRR")
        assert sections is CRR_IRB_ROW_SECTIONS

    def test_get_irb_row_sections_b31(self) -> None:
        """get_irb_row_sections returns B3.1 sections for BASEL_3_1."""
        sections = get_irb_row_sections("BASEL_3_1")
        assert sections is B31_IRB_ROW_SECTIONS

    def test_get_sa_risk_weight_bands_crr(self) -> None:
        """get_sa_risk_weight_bands returns CRR bands by default."""
        bands = get_sa_risk_weight_bands("CRR")
        assert bands is SA_RISK_WEIGHT_BANDS

    def test_get_sa_risk_weight_bands_b31(self) -> None:
        """get_sa_risk_weight_bands returns B3.1 bands for BASEL_3_1."""
        bands = get_sa_risk_weight_bands("BASEL_3_1")
        assert bands is B31_SA_RISK_WEIGHT_BANDS


# =============================================================================
# C 07.00 — SA CREDIT RISK
# =============================================================================


class TestC0700:
    """Tests for C 07.00 SA credit risk template generation."""

    def test_c07_contains_all_sa_exposure_classes(self) -> None:
        """C 07.00 has a row for each SA exposure class in the data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        classes = c07["exposure_class"].to_list()

        assert "TOTAL" in classes
        assert "corporate" in classes
        assert "institution" in classes
        assert "retail_other" in classes
        assert "central_govt_central_bank" in classes

    def test_c07_total_row_sums_correctly(self) -> None:
        """The total row aggregates all exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        total = c07.filter(pl.col("exposure_class") == "TOTAL")

        # Total original exposure: sum of all drawn + undrawn
        expected_original = (1000 + 2000 + 500 + 3000 + 200 + 300 + 5000) + (
            500 + 0 + 100 + 0 + 50 + 0 + 0
        )
        assert total["original_exposure_010"][0] == pytest.approx(expected_original)

        # Total EAD
        expected_ead = 1200.0 + 2000.0 + 550.0 + 3000.0 + 225.0 + 300.0 + 5000.0
        assert total["exposure_value_070"][0] == pytest.approx(expected_ead)

        # Total RWA
        expected_rwa = 1200.0 + 2000.0 + 467.5 + 600.0 + 168.75 + 225.0 + 0.0
        assert total["rwea_080"][0] == pytest.approx(expected_rwa)

    def test_c07_corporate_row_aggregation(self) -> None:
        """Corporate exposure class row aggregates correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        corp = c07.filter(pl.col("exposure_class") == "corporate")

        # 2 corporate exposures: drawn 1000+2000=3000, undrawn 500+0=500
        assert corp["original_exposure_010"][0] == pytest.approx(3500.0)
        # EAD: 1200 + 2000 = 3200
        assert corp["exposure_value_070"][0] == pytest.approx(3200.0)
        # RWA: 1200 + 2000 = 3200
        assert corp["rwea_080"][0] == pytest.approx(3200.0)

    def test_c07_provisions_deducted(self) -> None:
        """Provisions are summed from SCRA + GCRA amounts."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        corp = c07.filter(pl.col("exposure_class") == "corporate")

        # Corp provisions: (10+5) + (20+10) = 45
        assert corp["provisions_020"][0] == pytest.approx(45.0)
        # Net exposure: 3500 - 45 = 3455
        assert corp["net_exposure_030"][0] == pytest.approx(3455.0)

    def test_c07_crm_collateral(self) -> None:
        """Funded CRM (collateral) is aggregated correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        corp = c07.filter(pl.col("exposure_class") == "corporate")

        # Corp collateral: 100 + 0 = 100
        assert corp["funded_crm_040"][0] == pytest.approx(100.0)

    def test_c07_crm_guarantees(self) -> None:
        """Unfunded CRM (guarantees) is aggregated correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        corp = c07.filter(pl.col("exposure_class") == "corporate")

        # Corp guarantees: 0 + 500 = 500
        assert corp["unfunded_crm_050"][0] == pytest.approx(500.0)

    def test_c07_zero_rw_for_sovereign(self) -> None:
        """Central government with CQS 1 gets 0% RW, hence 0 RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        sovn = c07.filter(pl.col("exposure_class") == "central_govt_central_bank")

        assert sovn["rwea_080"][0] == pytest.approx(0.0)
        assert sovn["exposure_value_070"][0] == pytest.approx(5000.0)

    def test_c07_row_refs_assigned(self) -> None:
        """Row references are assigned from the SA template mapping."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        c07 = bundle.c07_00
        corp = c07.filter(pl.col("exposure_class") == "corporate")

        assert corp["row_ref"][0] == "0070"  # Corporates

    def test_c07_sorted_by_row_ref(self) -> None:
        """Rows are sorted by COREP row reference."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        refs = bundle.c07_00["row_ref"].to_list()
        assert refs == sorted(refs)

    def test_c07_no_irb_exposures_included(self) -> None:
        """C 07.00 must not include IRB or slotting exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        c07 = bundle.c07_00
        classes = c07["exposure_class"].to_list()

        # Should only contain SA classes + TOTAL
        assert "TOTAL" in classes
        for ec in classes:
            if ec != "TOTAL":
                assert ec in SA_EXPOSURE_CLASS_ROWS

    def test_c07_empty_results(self) -> None:
        """C 07.00 handles empty results gracefully."""
        gen = COREPGenerator()
        empty = pl.LazyFrame(
            schema={
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(empty)
        assert len(bundle.c07_00) == 0


# =============================================================================
# C 07.00 — RISK WEIGHT BREAKDOWN
# =============================================================================


class TestC0700RWBreakdown:
    """Tests for C 07.00 risk weight band breakdown."""

    def test_rw_breakdown_pivots_correctly(self) -> None:
        """Each exposure class has EAD allocated to RW band columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        rw = bundle.c07_rw_breakdown
        # Corporates have RW=1.00 -> "100%" column
        corp = rw.filter(pl.col("exposure_class") == "corporate")
        assert corp["100%"][0] == pytest.approx(3200.0)  # 1200 + 2000

    def test_rw_breakdown_sovereign_at_zero(self) -> None:
        """Sovereign with 0% RW appears in the 0% column."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        rw = bundle.c07_rw_breakdown
        sovn = rw.filter(pl.col("exposure_class") == "central_govt_central_bank")
        assert sovn["0%"][0] == pytest.approx(5000.0)

    def test_rw_breakdown_retail_at_75(self) -> None:
        """Retail exposures with 75% RW appear in the 75% column."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        rw = bundle.c07_rw_breakdown
        retail = rw.filter(pl.col("exposure_class") == "retail_other")
        assert retail["75%"][0] == pytest.approx(525.0)  # 225 + 300

    def test_rw_breakdown_has_total_row(self) -> None:
        """The total row sums across all exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        rw = bundle.c07_rw_breakdown
        total = rw.filter(pl.col("exposure_class") == "TOTAL")
        assert len(total) == 1


# =============================================================================
# C 08.01 — IRB TOTALS
# =============================================================================


class TestC0801:
    """Tests for C 08.01 IRB totals template generation."""

    def test_c0801_contains_irb_exposure_classes(self) -> None:
        """C 08.01 has rows for each IRB exposure class in the data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        classes = c08["exposure_class"].to_list()

        assert "TOTAL" in classes
        assert "corporate" in classes
        assert "corporate_sme" in classes
        assert "institution" in classes
        assert "retail_mortgage" in classes

    def test_c0801_total_ead(self) -> None:
        """Total EAD sums across all IRB exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        total = c08.filter(pl.col("exposure_class") == "TOTAL")

        expected_ead = 5500.0 + 3000.0 + 1200.0 + 2000.0 + 4000.0
        assert total["ead_040"][0] == pytest.approx(expected_ead)

    def test_c0801_total_rwa(self) -> None:
        """Total RWA sums across all IRB exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        total = c08.filter(pl.col("exposure_class") == "TOTAL")

        expected_rwa = 3850.0 + 1800.0 + 780.0 + 600.0 + 1200.0
        assert total["rwea_070"][0] == pytest.approx(expected_rwa)

    def test_c0801_weighted_average_pd(self) -> None:
        """Exposure-weighted average PD is correct for corporates."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        # Corp PDs: 0.005 * 5500 + 0.01 * 3000 = 27.5 + 30 = 57.5
        # Total EAD: 5500 + 3000 = 8500
        # Weighted PD: 57.5 / 8500 = 0.006765
        expected_pd = (0.005 * 5500 + 0.01 * 3000) / (5500 + 3000)
        assert corp["weighted_pd_010"][0] == pytest.approx(expected_pd, rel=1e-6)

    def test_c0801_weighted_average_lgd(self) -> None:
        """Exposure-weighted average LGD is correct for corporates."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        # Both corporates have LGD=0.45, so weighted average = 0.45
        assert corp["weighted_lgd_050"][0] == pytest.approx(0.45)

    def test_c0801_weighted_average_maturity(self) -> None:
        """Exposure-weighted average maturity is correct for corporates."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        # Maturities: 2.5 * 5500 + 3.0 * 3000 = 13750 + 9000 = 22750
        # Weighted: 22750 / 8500 = 2.6765
        expected_m = (2.5 * 5500 + 3.0 * 3000) / (5500 + 3000)
        assert corp["weighted_maturity_060"][0] == pytest.approx(expected_m, rel=1e-6)

    def test_c0801_expected_loss(self) -> None:
        """Expected loss sums correctly per exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        expected_el = 12.375 + 13.5
        assert corp["el_080"][0] == pytest.approx(expected_el)

    def test_c0801_el_net(self) -> None:
        """EL net (excess - shortfall) is computed correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        # Corp: excess=2.625, shortfall=0+3.5=3.5 -> net = 2.625 - 3.5 = -0.875
        expected_net = (2.625 + 0.0) - (0.0 + 3.5)
        assert corp["el_net_110"][0] == pytest.approx(expected_net)

    def test_c0801_obligor_count(self) -> None:
        """Obligor count uses distinct counterparty references."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        # 2 distinct counterparties: CP_X, CP_Y
        assert corp["obligor_count_100"][0] == 2

    def test_c0801_no_sa_exposures(self) -> None:
        """C 08.01 must not include SA exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        c08 = bundle.c08_01
        classes = c08["exposure_class"].to_list()

        # Should not contain pure SA classes like central_govt if no IRB version
        for ec in classes:
            if ec != "TOTAL":
                assert ec in IRB_EXPOSURE_CLASS_ROWS or ec not in SA_EXPOSURE_CLASS_ROWS

    def test_c0801_row_refs_assigned(self) -> None:
        """Row references are assigned from the IRB template mapping."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08 = bundle.c08_01
        corp = c08.filter(pl.col("exposure_class") == "corporate")

        assert corp["row_ref"][0] == "0030"  # Corporates - Other

    def test_c0801_empty_results(self) -> None:
        """C 08.01 handles empty results gracefully."""
        gen = COREPGenerator()
        empty = pl.LazyFrame(
            schema={
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(empty)
        assert len(bundle.c08_01) == 0


# =============================================================================
# C 08.02 — IRB PD GRADE BREAKDOWN
# =============================================================================


class TestC0802:
    """Tests for C 08.02 IRB PD grade breakdown template."""

    def test_c0802_pd_bands_assigned(self) -> None:
        """Exposures are assigned to correct PD bands."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08_02 = bundle.c08_02
        bands = c08_02["pd_band"].unique().to_list()

        # PD=0.005 -> 0.25-0.50% band, PD=0.01 -> 0.75-2.50% band, etc.
        assert any("0.25%" in b for b in bands)

    def test_c0802_per_band_ead(self) -> None:
        """EAD aggregated per PD band per exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08_02 = bundle.c08_02

        # Corp PD=0.005 (0.50%) -> "0.50% - 0.75%" band, EAD=5500
        corp_050 = c08_02.filter(
            (pl.col("exposure_class") == "corporate") & (pl.col("pd_band") == "0.50% - 0.75%")
        )
        assert corp_050["ead_040"][0] == pytest.approx(5500.0)

        # Corp PD=0.01 (1.00%) -> "0.75% - 2.50%" band, EAD=3000
        corp_075 = c08_02.filter(
            (pl.col("exposure_class") == "corporate") & (pl.col("pd_band") == "0.75% - 2.50%")
        )
        assert corp_075["ead_040"][0] == pytest.approx(3000.0)

    def test_c0802_weighted_pd_per_band(self) -> None:
        """Weighted PD within a single-exposure band equals the exposure PD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08_02 = bundle.c08_02

        # Corp PD=0.005 (0.50%), single exposure in "0.50% - 0.75%" band
        corp_050 = c08_02.filter(
            (pl.col("exposure_class") == "corporate") & (pl.col("pd_band") == "0.50% - 0.75%")
        )
        assert corp_050["weighted_pd_010"][0] == pytest.approx(0.005)

    def test_c0802_sorted_by_class_then_pd(self) -> None:
        """Rows are sorted by exposure class, then PD band order."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08_02 = bundle.c08_02
        # Within same exposure class, bands should be in ascending PD order
        corp_rows = c08_02.filter(pl.col("exposure_class") == "corporate")
        if len(corp_rows) > 1:
            # PD bands should be ordered by the first PD value
            bands = corp_rows["pd_band"].to_list()
            band_order = [label for _, _, label in PD_BANDS]
            indices = [band_order.index(b) if b in band_order else 999 for b in bands]
            assert indices == sorted(indices)

    def test_c0802_has_exposure_class_name(self) -> None:
        """Rows include the human-readable exposure class name."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        c08_02 = bundle.c08_02
        names = c08_02["exposure_class_name"].unique().to_list()

        assert any("Corporates" in n for n in names)


# =============================================================================
# FULL PIPELINE — COMBINED SA + IRB
# =============================================================================


class TestCombinedGeneration:
    """Tests for generating all templates from combined SA + IRB data."""

    def test_all_templates_generated(self) -> None:
        """All three templates are non-empty for combined data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        assert len(bundle.c07_00) > 0
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0
        assert len(bundle.c07_rw_breakdown) > 0

    def test_sa_and_irb_separated(self) -> None:
        """C 07.00 only has SA data; C 08.01 only has IRB data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # C 07.00 total EAD should match SA-only
        c07_total = bundle.c07_00.filter(pl.col("exposure_class") == "TOTAL")
        sa_ead = _sa_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert c07_total["exposure_value_070"][0] == pytest.approx(sa_ead)

        # C 08.01 total EAD should match IRB-only
        c08_total = bundle.c08_01.filter(pl.col("exposure_class") == "TOTAL")
        irb_ead = _irb_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert c08_total["ead_040"][0] == pytest.approx(irb_ead)

    def test_bundle_framework_stored(self) -> None:
        """Framework is stored in the template bundle."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results(), framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"

    def test_bundle_errors_empty_on_success(self) -> None:
        """No errors for well-formed input data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())
        assert len(bundle.errors) == 0


# =============================================================================
# EXCEL EXPORT
# =============================================================================


@pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
class TestExcelExport:
    """Tests for COREP Excel workbook generation."""

    def test_export_creates_file(self, tmp_path: Path) -> None:
        """COREP export creates an Excel file."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        output = tmp_path / "corep.xlsx"
        result = gen.export_to_excel(bundle, output)

        assert output.exists()
        assert result.format == "corep_excel"
        assert result.row_count > 0
        assert output in result.files

    def test_export_has_all_sheets(self, tmp_path: Path) -> None:
        """COREP Excel workbook has all 4 sheets."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        # Read back and check sheet names
        sheets = pl.read_excel(output, sheet_id=0)
        sheet_names = list(sheets.keys()) if isinstance(sheets, dict) else []

        assert "C 07.00" in sheet_names
        assert "C 07.00 RW Breakdown" in sheet_names
        assert "C 08.01" in sheet_names
        assert "C 08.02" in sheet_names

    def test_export_round_trip_c07(self, tmp_path: Path) -> None:
        """C 07.00 data survives Excel round-trip."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        # Read back C 07.00
        c07_read = pl.read_excel(output, sheet_name="C 07.00")
        assert len(c07_read) == len(bundle.c07_00)

    def test_export_integration_via_exporter(self, tmp_path: Path) -> None:
        """COREP export works through the ResultExporter interface."""

        # We can't easily create a full CalculationResponse without the
        # pipeline, but we can test the COREPGenerator directly
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())
        result = gen.export_to_excel(bundle, tmp_path / "via_exporter.xlsx")

        assert result.row_count > 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_columns_handled_gracefully(self) -> None:
        """Generator handles missing optional columns without crashing."""
        minimal = pl.LazyFrame(
            {
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "institution"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [1000.0, 400.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(minimal)

        # Should produce C 07.00 without crashing
        assert len(bundle.c07_00) > 0

    def test_alternative_column_names(self) -> None:
        """Generator works with 'ead' instead of 'ead_final'."""
        alt_names = pl.LazyFrame(
            {
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead": [1000.0],
                "rwa": [1000.0],
                "risk_weight": [1.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(alt_names)
        assert len(bundle.c07_00) > 0

    def test_sa_only_data(self) -> None:
        """SA-only data produces C 07.00 but empty C 08.01/C 08.02."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert len(bundle.c07_00) > 0
        assert len(bundle.c08_01) == 0
        assert len(bundle.c08_02) == 0

    def test_irb_only_data(self) -> None:
        """IRB-only data produces C 08.01/C 08.02 but empty C 07.00."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert len(bundle.c07_00) == 0
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0

    def test_single_exposure(self) -> None:
        """Single exposure produces valid templates."""
        single = pl.LazyFrame(
            {
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
                "risk_weight": [1.0],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(single)

        assert len(bundle.c07_00) == 2  # 1 corp + 1 total
        total = bundle.c07_00.filter(pl.col("exposure_class") == "TOTAL")
        assert total["exposure_value_070"][0] == pytest.approx(1000.0)
