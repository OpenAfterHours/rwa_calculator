"""
Unit tests for COREP template generation.

Tests the COREPGenerator against synthetic exposure data to verify:
- Template definitions: CRR and Basel 3.1 column/row section structures
- C 07.00 (SA): Per-class output with 5 row sections, 4-digit column refs
- C 08.01 (IRB): Per-class output with 3 row sections, maturity in days
- C 08.02 (IRB PD grades): Per-class PD band assignment and aggregation
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


def _sa_results_with_phase2_cols() -> pl.LazyFrame:
    """SA results with Phase 2 columns: bs_type, supporting factors, default_status."""
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
                "SA_DEF_1",
            ],
            "approach_applied": ["standardised"] * 8,
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_other",
                "retail_other",
                "central_govt_central_bank",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 500.0, 3000.0, 200.0, 300.0, 5000.0, 800.0],
            "undrawn_amount": [500.0, 0.0, 100.0, 0.0, 50.0, 0.0, 0.0, 0.0],
            "ead_final": [1200.0, 2000.0, 550.0, 3000.0, 225.0, 300.0, 5000.0, 800.0],
            "rwa_final": [1140.0, 1900.0, 467.5, 600.0, 168.75, 225.0, 0.0, 1200.0],
            "risk_weight": [1.00, 1.00, 0.85, 0.20, 0.75, 0.75, 0.00, 1.50],
            "scra_provision_amount": [10.0, 20.0, 5.0, 0.0, 2.0, 3.0, 0.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5, 15.0, 1.0, 1.5, 0.0, 3.0],
            "collateral_adjusted_value": [100.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 0, 0, 2, 0, 0, 1, None],
            "counterparty_reference": [
                "CP_A", "CP_B", "CP_C", "CP_D", "CP_E", "CP_F", "CP_G", "CP_H",
            ],
            # Phase 2 columns
            "bs_type": ["ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB"],
            "default_status": [False, False, False, False, False, False, False, True],
            "sme_supporting_factor_eligible": [
                False, False, True, False, False, False, False, False,
            ],
            "sme_supporting_factor_applied": [
                False, False, True, False, False, False, False, False,
            ],
            "infrastructure_factor_applied": [
                True, False, False, False, False, False, False, False,
            ],
            "rwa_before_sme_factor": [
                1200.0, 2000.0, 550.0, 600.0, 168.75, 225.0, 0.0, 1200.0,
            ],
        }
    )


def _sa_results_with_bs_split() -> pl.LazyFrame:
    """SA results with on-BS and off-BS exposures for Section 2 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_ON_1", "SA_ON_2", "SA_OFF_1"],
            "approach_applied": ["standardised"] * 3,
            "exposure_class": ["corporate", "corporate", "corporate"],
            "drawn_amount": [1000.0, 2000.0, 0.0],
            "undrawn_amount": [0.0, 0.0, 500.0],
            "ead_final": [1000.0, 2000.0, 400.0],
            "rwa_final": [1000.0, 2000.0, 400.0],
            "risk_weight": [1.0, 1.0, 1.0],
            "scra_provision_amount": [10.0, 20.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 2.5],
            "sa_cqs": [3, 3, 3],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
            "bs_type": ["ONB", "ONB", "OFB"],
        }
    )


def _irb_results_with_phase2_cols() -> pl.LazyFrame:
    """IRB results with Phase 2 columns for defaulted/LFSE testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1", "IRB_CORP_2", "IRB_SME_1",
                "IRB_INST_1", "IRB_RETAIL_1", "IRB_DEF_1",
            ],
            "approach_applied": [
                "foundation_irb", "foundation_irb", "foundation_irb",
                "foundation_irb", "advanced_irb", "foundation_irb",
            ],
            "exposure_class": [
                "corporate", "corporate", "corporate_sme",
                "institution", "retail_mortgage", "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 1000.0, 2000.0, 4000.0, 600.0],
            "undrawn_amount": [1000.0, 0.0, 500.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0, 600.0],
            "rwa_final": [3850.0, 1800.0, 780.0, 600.0, 1200.0, 900.0],
            "risk_weight": [0.70, 0.60, 0.65, 0.30, 0.30, 1.50],
            "irb_pd_floored": [0.005, 0.01, 0.02, 0.002, 0.003, 1.0],
            "irb_lgd_floored": [0.45, 0.45, 0.45, 0.45, 0.15, 0.45],
            "irb_maturity_m": [2.5, 3.0, 2.5, 1.5, 20.0, 2.5],
            "irb_expected_loss": [12.375, 13.5, 10.8, 1.8, 1.8, 270.0],
            "irb_capital_k": [0.056, 0.048, 0.052, 0.024, 0.024, 0.12],
            "provision_held": [15.0, 10.0, 8.0, 3.0, 2.5, 50.0],
            "el_shortfall": [0.0, 3.5, 2.8, 0.0, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.7, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 1.0, 10.0],
            "gcra_provision_amount": [5.0, 5.0, 5.0, 1.0, 1.5, 5.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V", "CP_DEF"],
            "default_status": [False, False, False, False, False, True],
            "bs_type": ["ONB", "ONB", "ONB", "ONB", "ONB", "ONB"],
            "apply_fi_scalar": [False, False, False, True, False, False],
        }
    )


def _sa_results_with_ccf() -> pl.LazyFrame:
    """SA results with off-BS exposures and CCF values for Phase 2C testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_ON_1", "SA_OFF_0", "SA_OFF_20", "SA_OFF_50", "SA_OFF_100",
            ],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": ["corporate"] * 5,
            "drawn_amount": [5000.0, 0.0, 0.0, 0.0, 0.0],
            "undrawn_amount": [0.0, 1000.0, 2000.0, 3000.0, 500.0],
            "ead_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "rwa_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "risk_weight": [1.0, 1.0, 1.0, 1.0, 1.0],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 3, 3, 3, 3],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "bs_type": ["ONB", "OFB", "OFB", "OFB", "OFB"],
            "ccf_applied": [None, 0.0, 0.2, 0.5, 1.0],
        }
    )


def _irb_results_with_output_floor() -> pl.LazyFrame:
    """IRB results with output floor columns for Phase 2D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": [
                "foundation_irb", "foundation_irb", "foundation_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [5000.0, 3000.0, 2000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0],
            "rwa_final": [3850.0, 1800.0, 600.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "irb_pd_floored": [0.005, 0.01, 0.002],
            "irb_lgd_floored": [0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0, 1.5],
            "irb_expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "provision_held": [15.0, 10.0, 3.0],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            "sa_equivalent_rwa": [5500.0, 3000.0, 400.0],
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
        assert "0215" in refs
        assert "0216" in refs
        assert "0217" in refs

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
        assert len(CRR_SA_ROW_SECTIONS) == 5

    def test_crr_sa_section_names(self) -> None:
        names = [s.name for s in CRR_SA_ROW_SECTIONS]
        assert "Total Exposures" in names
        assert "Breakdown by Exposure Types" in names
        assert "Breakdown by Risk Weights" in names
        assert "Breakdown by CIU Approach" in names
        assert "Memorandum Items" in names

    def test_crr_sa_total_section_starts_with_0010(self) -> None:
        total_section = CRR_SA_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"
        assert "TOTAL" in total_section.rows[0].name

    def test_crr_sa_total_section_has_of_which_rows(self) -> None:
        total_section = CRR_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs
        assert "0020" in refs
        assert "0030" in refs
        assert "0035" in refs

    def test_crr_sa_rw_section_has_15_rows(self) -> None:
        rw_section = CRR_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 15

    def test_crr_sa_rw_section_row_refs_ascending(self) -> None:
        rw_section = CRR_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert refs == sorted(refs)

    def test_crr_sa_memorandum_has_4_rows(self) -> None:
        memo_section = CRR_SA_ROW_SECTIONS[4]
        assert memo_section.name == "Memorandum Items"
        assert len(memo_section.rows) == 4

    def test_crr_sa_all_row_refs_unique(self) -> None:
        all_refs = [r.ref for s in CRR_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_sa_has_5_sections(self) -> None:
        assert len(B31_SA_ROW_SECTIONS) == 5

    def test_b31_sa_rw_section_has_28_rows(self) -> None:
        rw_section = B31_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 28

    def test_b31_sa_has_specialised_lending_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0021" in refs
        assert "0022" in refs
        assert "0023" in refs
        assert "0024" in refs
        assert "0025" in refs
        assert "0026" in refs

    def test_b31_sa_has_re_detail_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0330" in refs
        assert "0340" in refs
        assert "0360" in refs

    def test_b31_sa_no_supporting_factor_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0030" not in refs
        assert "0035" not in refs

    def test_b31_sa_has_400pct_rw(self) -> None:
        rw_section = B31_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert "0261" in refs
        assert "0260" not in refs

    def test_b31_sa_memorandum_has_equity_transitional(self) -> None:
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0371" in refs
        assert "0372" in refs
        assert "0373" in refs
        assert "0374" in refs

    def test_b31_sa_memorandum_has_currency_mismatch(self) -> None:
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0380" in refs

    def test_b31_sa_all_row_refs_unique(self) -> None:
        all_refs = [r.ref for s in B31_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestCRRC08ColumnDefinitions:
    """Tests for CRR C 08.01 column definitions."""

    def test_crr_c08_has_correct_column_count(self) -> None:
        assert len(CRR_C08_COLUMNS) == 37

    def test_crr_c08_uses_4_digit_refs(self) -> None:
        for col in CRR_C08_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"

    def test_crr_c08_starts_with_pd(self) -> None:
        assert CRR_C08_COLUMNS[0].ref == "0010"
        assert "PD" in CRR_C08_COLUMNS[0].name

    def test_crr_c08_has_double_default(self) -> None:
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0220" in refs

    def test_crr_c08_has_supporting_factors(self) -> None:
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0255" in refs
        assert "0256" in refs
        assert "0257" in refs

    def test_crr_c08_maturity_in_days(self) -> None:
        col_0250 = next(c for c in CRR_C08_COLUMNS if c.ref == "0250")
        assert "days" in col_0250.name.lower()

    def test_crr_c08_refs_unique(self) -> None:
        refs = [col.ref for col in CRR_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestB31C08ColumnDefinitions:
    """Tests for Basel 3.1 OF 08.01 column definitions."""

    def test_b31_c08_no_pd_column(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0010" not in refs

    def test_b31_c08_no_double_default(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0220" not in refs

    def test_b31_c08_no_supporting_factors(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0255" not in refs
        assert "0256" not in refs
        assert "0257" not in refs

    def test_b31_c08_has_on_bs_netting(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0035" in refs

    def test_b31_c08_has_slotting_fccm(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0101" in refs
        assert "0102" in refs
        assert "0103" in refs
        assert "0104" in refs

    def test_b31_c08_has_defaulted_breakdowns(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0125" in refs
        assert "0265" in refs

    def test_b31_c08_has_post_model_adjustments(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0251" in refs
        assert "0252" in refs
        assert "0253" in refs
        assert "0254" in refs

    def test_b31_c08_has_output_floor(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0275" in refs
        assert "0276" in refs

    def test_b31_c08_has_el_adjustments(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0281" in refs
        assert "0282" in refs

    def test_b31_c08_refs_unique(self) -> None:
        refs = [col.ref for col in B31_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestIRBRowSections:
    """Tests for IRB row section definitions (C 08.01 / OF 08.01)."""

    def test_crr_irb_has_3_sections(self) -> None:
        assert len(CRR_IRB_ROW_SECTIONS) == 3

    def test_crr_irb_section_names(self) -> None:
        names = [s.name for s in CRR_IRB_ROW_SECTIONS]
        assert "Total and Supporting Factors" in names
        assert "Breakdown by Exposure Types" in names
        assert "Calculation Approaches" in names

    def test_crr_irb_total_starts_with_0010(self) -> None:
        total_section = CRR_IRB_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"

    def test_crr_irb_has_supporting_factor_rows(self) -> None:
        total_section = CRR_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs
        assert "0016" in refs

    def test_crr_irb_has_alt_re_treatment(self) -> None:
        calc_section = CRR_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" in refs

    def test_crr_irb_all_refs_unique(self) -> None:
        all_refs = [r.ref for s in CRR_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_irb_has_3_sections(self) -> None:
        assert len(B31_IRB_ROW_SECTIONS) == 3

    def test_b31_irb_no_supporting_factor_rows(self) -> None:
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" not in refs
        assert "0016" not in refs

    def test_b31_irb_has_revolving_commitments(self) -> None:
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0017" in refs

    def test_b31_irb_has_ccf_breakdown_rows(self) -> None:
        exp_section = B31_IRB_ROW_SECTIONS[1]
        refs = [r.ref for r in exp_section.rows]
        assert "0031" in refs
        assert "0032" in refs
        assert "0033" in refs
        assert "0034" in refs
        assert "0035" in refs

    def test_b31_irb_no_alt_re_treatment(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" not in refs

    def test_b31_irb_has_purchased_receivables(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0175" in refs

    def test_b31_irb_has_ecai_rows(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0190" in refs
        assert "0200" in refs

    def test_b31_irb_all_refs_unique(self) -> None:
        all_refs = [r.ref for s in B31_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestB31SAWeightBands:
    """Tests for Basel 3.1 risk weight bands."""

    def test_b31_rw_bands_ascending(self) -> None:
        rw_values = [rw for rw, _ in B31_SA_RISK_WEIGHT_BANDS]
        assert rw_values == sorted(rw_values)

    def test_b31_rw_bands_has_27_entries(self) -> None:
        assert len(B31_SA_RISK_WEIGHT_BANDS) == 27

    def test_b31_rw_bands_has_new_weights(self) -> None:
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 0.15 in rw_dict
        assert 0.25 in rw_dict
        assert 0.30 in rw_dict
        assert 0.40 in rw_dict
        assert 0.45 in rw_dict
        assert 0.60 in rw_dict
        assert 0.65 in rw_dict

    def test_b31_rw_bands_has_400pct(self) -> None:
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 4.00 in rw_dict
        assert 3.70 not in rw_dict


class TestFrameworkHelpers:
    """Tests for framework-aware helper functions."""

    def test_get_c07_columns_crr(self) -> None:
        assert get_c07_columns("CRR") is CRR_C07_COLUMNS

    def test_get_c07_columns_b31(self) -> None:
        assert get_c07_columns("BASEL_3_1") is B31_C07_COLUMNS

    def test_get_c08_columns_crr(self) -> None:
        assert get_c08_columns("CRR") is CRR_C08_COLUMNS

    def test_get_c08_columns_b31(self) -> None:
        assert get_c08_columns("BASEL_3_1") is B31_C08_COLUMNS

    def test_get_sa_row_sections_crr(self) -> None:
        assert get_sa_row_sections("CRR") is CRR_SA_ROW_SECTIONS

    def test_get_sa_row_sections_b31(self) -> None:
        assert get_sa_row_sections("BASEL_3_1") is B31_SA_ROW_SECTIONS

    def test_get_irb_row_sections_crr(self) -> None:
        assert get_irb_row_sections("CRR") is CRR_IRB_ROW_SECTIONS

    def test_get_irb_row_sections_b31(self) -> None:
        assert get_irb_row_sections("BASEL_3_1") is B31_IRB_ROW_SECTIONS

    def test_get_sa_risk_weight_bands_crr(self) -> None:
        assert get_sa_risk_weight_bands("CRR") is SA_RISK_WEIGHT_BANDS

    def test_get_sa_risk_weight_bands_b31(self) -> None:
        assert get_sa_risk_weight_bands("BASEL_3_1") is B31_SA_RISK_WEIGHT_BANDS


# =============================================================================
# HELPERS FOR ACCESSING NEW BUNDLE STRUCTURE
# =============================================================================


def _get_total_row(df: pl.DataFrame) -> pl.DataFrame:
    """Get the TOTAL EXPOSURES row (row_ref == '0010') from a per-class DataFrame."""
    return df.filter(pl.col("row_ref") == "0010")


def _get_rw_row(df: pl.DataFrame, rw_label: str) -> pl.DataFrame:
    """Get a risk weight breakdown row by its label (e.g., '100%')."""
    return df.filter(pl.col("row_name") == rw_label)


# =============================================================================
# C 07.00 — SA CREDIT RISK (PER-CLASS OUTPUT)
# =============================================================================


class TestC0700:
    """Tests for C 07.00 SA credit risk template generation.

    The generator now produces one DataFrame per exposure class, each with
    5 row sections and 4-digit COREP column references.
    """

    def test_c07_produces_per_class_output(self) -> None:
        """C 07.00 produces a dict keyed by exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert isinstance(bundle.c07_00, dict)
        assert "corporate" in bundle.c07_00
        assert "institution" in bundle.c07_00
        assert "retail_other" in bundle.c07_00
        assert "central_govt_central_bank" in bundle.c07_00

    def test_c07_each_class_has_row_sections(self) -> None:
        """Each per-class DataFrame has rows from all 5 sections."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()

        # Section 1: Total row (0010) must be present
        assert "0010" in row_refs
        # Section 2: Exposure type rows
        assert "0070" in row_refs  # On-BS
        assert "0080" in row_refs  # Off-BS
        # Section 3: Risk weight rows
        assert "0230" in row_refs  # 100% RW
        # Section 4: CIU approach
        assert "0281" in row_refs
        # Section 5: Memorandum
        assert "0290" in row_refs or "0300" in row_refs

    def test_c07_uses_4_digit_column_refs(self) -> None:
        """DataFrame columns use 4-digit COREP refs."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        cols = set(corp.columns)

        # Key COREP columns should be present
        assert "0010" in cols  # Original exposure
        assert "0030" in cols  # Provisions
        assert "0040" in cols  # Net exposure
        assert "0200" in cols  # Exposure value
        assert "0220" in cols  # RWEA

    def test_c07_total_row_original_exposure(self) -> None:
        """Total row (0010) aggregates original exposure correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 2 corporate exposures: drawn 1000+2000=3000, undrawn 500+0=500
        assert corp["0010"][0] == pytest.approx(3500.0)

    def test_c07_total_row_provisions(self) -> None:
        """Provisions (col 0030) sum SCRA + GCRA amounts."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp provisions: (10+5) + (20+10) = 45
        assert corp["0030"][0] == pytest.approx(45.0)

    def test_c07_total_row_net_exposure(self) -> None:
        """Net exposure (col 0040) = original - provisions."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 3500 - 45 = 3455
        assert corp["0040"][0] == pytest.approx(3455.0)

    def test_c07_total_row_guarantees(self) -> None:
        """Guarantees (col 0050) are aggregated correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp guarantees: 0 + 500 = 500
        assert corp["0050"][0] == pytest.approx(500.0)

    def test_c07_total_row_collateral(self) -> None:
        """Collateral (col 0130) is aggregated correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # Corp collateral: 100 + 0 = 100
        assert corp["0130"][0] == pytest.approx(100.0)

    def test_c07_total_row_ead(self) -> None:
        """Exposure value (col 0200) matches EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # EAD: 1200 + 2000 = 3200
        assert corp["0200"][0] == pytest.approx(3200.0)

    def test_c07_total_row_rwea(self) -> None:
        """RWEA (col 0220) matches RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # RWA: 1200 + 2000 = 3200
        assert corp["0220"][0] == pytest.approx(3200.0)

    def test_c07_zero_rw_for_sovereign(self) -> None:
        """Central government with CQS 1 gets 0% RW, hence 0 RWEA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        sovn = _get_total_row(bundle.c07_00["central_govt_central_bank"])
        assert sovn["0220"][0] == pytest.approx(0.0)
        assert sovn["0200"][0] == pytest.approx(5000.0)

    def test_c07_ecai_assessment(self) -> None:
        """ECAI column (0230) only includes rated exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # All corp exposures have sa_cqs not null -> all RWA is rated
        assert corp["0230"][0] == pytest.approx(3200.0)

    def test_c07_no_irb_in_sa_output(self) -> None:
        """C 07.00 dict must not include IRB-only exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # retail_mortgage is IRB-only in test data
        assert "retail_mortgage" not in bundle.c07_00

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
        assert bundle.c07_00 == {}


# =============================================================================
# C 07.00 — RISK WEIGHT BREAKDOWN (NOW SECTION 3)
# =============================================================================


class TestC0700RiskWeightSection:
    """Tests for C 07.00 Section 3: Risk weight band breakdown.

    Risk weight breakdown is now integrated as Section 3 of each
    per-class DataFrame (no longer a separate template).
    """

    def test_rw_section_100pct_for_corporates(self) -> None:
        """Corporates with RW=1.00 appear in the 100% row."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        rw_100 = _get_rw_row(corp, "100%")

        # EAD: 1200 + 2000 = 3200 (both corps are 100% RW)
        assert len(rw_100) == 1
        assert rw_100["0200"][0] == pytest.approx(3200.0)

    def test_rw_section_0pct_for_sovereign(self) -> None:
        """Sovereign with 0% RW appears in the 0% row."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        sovn = bundle.c07_00["central_govt_central_bank"]
        rw_0 = _get_rw_row(sovn, "0%")

        assert len(rw_0) == 1
        assert rw_0["0200"][0] == pytest.approx(5000.0)

    def test_rw_section_75pct_for_retail(self) -> None:
        """Retail exposures with 75% RW appear in the 75% row."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        retail = bundle.c07_00["retail_other"]
        rw_75 = _get_rw_row(retail, "75%")

        # EAD: 225 + 300 = 525
        assert len(rw_75) == 1
        assert rw_75["0200"][0] == pytest.approx(525.0)

    def test_rw_section_empty_bands_are_null(self) -> None:
        """RW bands with no exposures have null values."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = bundle.c07_00["corporate"]
        # Corporates are all 100% RW, so 0% band should be null
        rw_0 = _get_rw_row(corp, "0%")
        assert len(rw_0) == 1
        assert rw_0["0200"][0] is None

    def test_rw_section_rwea_populated(self) -> None:
        """RW section rows have RWEA values populated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        retail = bundle.c07_00["retail_other"]
        rw_75 = _get_rw_row(retail, "75%")
        # RWA: 168.75 + 225.0 = 393.75
        assert rw_75["0220"][0] == pytest.approx(393.75)


# =============================================================================
# C 08.01 — IRB TOTALS (PER-CLASS OUTPUT)
# =============================================================================


class TestC0801:
    """Tests for C 08.01 IRB totals template generation."""

    def test_c0801_produces_per_class_output(self) -> None:
        """C 08.01 produces a dict keyed by IRB exposure class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert isinstance(bundle.c08_01, dict)
        assert "corporate" in bundle.c08_01
        assert "corporate_sme" in bundle.c08_01
        assert "institution" in bundle.c08_01
        assert "retail_mortgage" in bundle.c08_01

    def test_c0801_each_class_has_row_sections(self) -> None:
        """Each per-class DataFrame has rows from all 3 IRB sections."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()

        # Section 1: Total
        assert "0010" in row_refs
        # Section 2: Exposure types
        assert "0020" in row_refs  # On-BS
        # Section 3: Calculation approaches
        assert "0070" in row_refs  # Grades/pools

    def test_c0801_uses_4_digit_column_refs(self) -> None:
        """DataFrame uses 4-digit COREP column refs."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = bundle.c08_01["corporate"]
        cols = set(corp.columns)

        assert "0010" in cols  # PD
        assert "0020" in cols  # Original exposure
        assert "0110" in cols  # Exposure value (EAD)
        assert "0230" in cols  # LGD
        assert "0250" in cols  # Maturity (days)
        assert "0260" in cols  # RWEA

    def test_c0801_total_ead(self) -> None:
        """Total EAD (col 0110) sums correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corp EAD: 5500 + 3000 = 8500
        assert corp["0110"][0] == pytest.approx(8500.0)

    def test_c0801_total_rwea(self) -> None:
        """Total RWEA (col 0260) sums correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corp RWA: 3850 + 1800 = 5650
        assert corp["0260"][0] == pytest.approx(5650.0)

    def test_c0801_weighted_average_pd(self) -> None:
        """Exposure-weighted average PD (col 0010) is correct."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # PD: (0.005*5500 + 0.01*3000) / 8500 = 57.5 / 8500
        expected_pd = (0.005 * 5500 + 0.01 * 3000) / (5500 + 3000)
        assert corp["0010"][0] == pytest.approx(expected_pd, rel=1e-6)

    def test_c0801_weighted_average_lgd(self) -> None:
        """Exposure-weighted average LGD (col 0230) is correct."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Both corporates have LGD=0.45, so weighted average = 0.45
        assert corp["0230"][0] == pytest.approx(0.45)

    def test_c0801_maturity_in_days(self) -> None:
        """Maturity (col 0250) is in DAYS, not years.

        Why: COREP col 0250 requires maturity in days. The pipeline
        stores irb_maturity_m in years. The generator must multiply by 365.
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Weighted maturity in years: (2.5*5500 + 3.0*3000) / 8500 = 2.6765
        # In days: 2.6765 * 365 = 976.9
        expected_m_years = (2.5 * 5500 + 3.0 * 3000) / (5500 + 3000)
        expected_m_days = expected_m_years * 365.0
        assert corp["0250"][0] == pytest.approx(expected_m_days, rel=1e-4)

    def test_c0801_expected_loss(self) -> None:
        """Expected loss (col 0280) sums correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # EL: 12.375 + 13.5 = 25.875
        assert corp["0280"][0] == pytest.approx(25.875)

    def test_c0801_provisions(self) -> None:
        """Provisions (col 0290) sums correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Provisions: (10+5) + (5+5) = 25
        assert corp["0290"][0] == pytest.approx(25.0)

    def test_c0801_obligor_count(self) -> None:
        """Obligor count (col 0300) uses distinct counterparty refs."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # 2 distinct counterparties: CP_X, CP_Y
        assert corp["0300"][0] == pytest.approx(2.0)

    def test_c0801_no_sa_in_irb_output(self) -> None:
        """C 08.01 dict must not include SA-only exposure classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # central_govt_central_bank is SA-only in test data
        assert "central_govt_central_bank" not in bundle.c08_01

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
        assert bundle.c08_01 == {}


# =============================================================================
# C 08.02 — IRB PD GRADE BREAKDOWN
# =============================================================================


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


# =============================================================================
# FULL PIPELINE — COMBINED SA + IRB
# =============================================================================


class TestCombinedGeneration:
    """Tests for generating all templates from combined SA + IRB data."""

    def test_all_templates_generated(self) -> None:
        """All three template dicts are non-empty for combined data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        assert len(bundle.c07_00) > 0
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0

    def test_sa_and_irb_separated(self) -> None:
        """C 07.00 only has SA data; C 08.01 only has IRB data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        # Sum EAD across all SA classes
        sa_total_ead = sum(
            _get_total_row(df)["0200"][0]
            for df in bundle.c07_00.values()
        )
        expected_sa_ead = _sa_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert sa_total_ead == pytest.approx(expected_sa_ead)

        # Sum EAD across all IRB classes
        irb_total_ead = sum(
            _get_total_row(df)["0110"][0]
            for df in bundle.c08_01.values()
        )
        expected_irb_ead = (
            _irb_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        )
        assert irb_total_ead == pytest.approx(expected_irb_ead)

    def test_bundle_framework_stored(self) -> None:
        """Framework is stored in the template bundle."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _combined_results(), framework="BASEL_3_1"
        )
        assert bundle.framework == "BASEL_3_1"

    def test_bundle_errors_empty_on_success(self) -> None:
        """No errors for well-formed input data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())
        assert len(bundle.errors) == 0

    def test_framework_affects_column_set(self) -> None:
        """CRR and Basel 3.1 produce different column sets."""
        gen = COREPGenerator()
        crr = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        b31 = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")

        crr_cols = set(list(crr.c07_00.values())[0].columns)
        b31_cols = set(list(b31.c07_00.values())[0].columns)

        # CRR has supporting factor columns, B3.1 doesn't
        assert "0215" in crr_cols
        assert "0215" not in b31_cols

        # B3.1 has on-BS netting, CRR doesn't
        assert "0035" in b31_cols
        assert "0035" not in crr_cols


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

    def test_export_has_per_class_sheets(self, tmp_path: Path) -> None:
        """COREP Excel workbook has per-class sheets."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        sheets = pl.read_excel(output, sheet_id=0)
        sheet_names = list(sheets.keys()) if isinstance(sheets, dict) else []

        # Should have C 07.00 sheets for SA classes
        assert any("C 07.00" in s for s in sheet_names)
        # Should have C 08.01 sheets for IRB classes
        assert any("C 08.01" in s for s in sheet_names)

    def test_export_round_trip_c07(self, tmp_path: Path) -> None:
        """C 07.00 data survives Excel round-trip."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        output = tmp_path / "corep.xlsx"
        gen.export_to_excel(bundle, output)

        # Read back the first sheet
        sheets = pl.read_excel(output, sheet_id=0)
        if isinstance(sheets, dict):
            first_sheet = next(iter(sheets.values()))
            assert len(first_sheet) > 0


# =============================================================================
# PHASE 2A — SUPPORTING FACTOR COLUMNS (CRR ONLY)
# =============================================================================


class TestSupportingFactors:
    """Tests for CRR supporting factor columns 0215-0217 (C 07.00) and 0255-0257 (C 08.01)."""

    def test_c07_supporting_factor_pre_rwea(self) -> None:
        """Col 0215 (RWEA pre factors) is populated from rwa_before_sme_factor."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # corporate has 3 exposures: rwa_before_sme_factor = 1200+2000+1200 = 4400
        assert corp["0215"][0] == pytest.approx(4400.0)

    def test_c07_sme_factor_benefit(self) -> None:
        """Col 0216 (SME factor benefit) = pre - post for SME-eligible exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = _get_total_row(bundle.c07_00["corporate_sme"])
        # corporate_sme: rwa_before_sme_factor=550, rwa_final=467.5, benefit = 82.5
        assert sme["0216"][0] == pytest.approx(82.5)

    def test_c07_infra_factor_benefit(self) -> None:
        """Col 0217 (infrastructure factor benefit) computed for eligible exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_1 has infra_factor_applied=True: pre=1200, post=1140, benefit=60
        assert corp["0217"][0] == pytest.approx(60.0)

    def test_c07_supporting_factors_not_in_b31(self) -> None:
        """Supporting factor columns (0215-0217) absent from Basel 3.1 output."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = list(bundle.c07_00.values())[0]
        assert "0215" not in corp.columns
        assert "0216" not in corp.columns
        assert "0217" not in corp.columns

    def test_c07_rwea_relationship(self) -> None:
        """Col 0220 = 0215 - 0216 - 0217 (RWEA after factors)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = _get_total_row(bundle.c07_00["corporate_sme"])
        pre = sme["0215"][0]
        sme_benefit = sme["0216"][0]
        post = sme["0220"][0]
        # pre - sme_benefit = post (no infra for SME class)
        assert post == pytest.approx(pre - sme_benefit)


# =============================================================================
# PHASE 2B — EXPOSURE TYPE ROWS (SECTION 2)
# =============================================================================


class TestExposureTypeRows:
    """Tests for Section 2 exposure type breakdown (on-BS vs off-BS)."""

    def test_c07_on_bs_row_populated(self) -> None:
        """Row 0070 (on-BS) aggregates on-balance-sheet exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0070")
        # 2 on-BS: EAD 1000+2000=3000
        assert on_bs["0200"][0] == pytest.approx(3000.0)

    def test_c07_off_bs_row_populated(self) -> None:
        """Row 0080 (off-BS) aggregates off-balance-sheet exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        off_bs = corp.filter(pl.col("row_ref") == "0080")
        # 1 off-BS: EAD 400
        assert off_bs["0200"][0] == pytest.approx(400.0)

    def test_c07_on_plus_off_equals_total(self) -> None:
        """On-BS EAD + off-BS EAD = total EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        total_ead = _get_total_row(corp)["0200"][0]
        on_bs_ead = corp.filter(pl.col("row_ref") == "0070")["0200"][0]
        off_bs_ead = corp.filter(pl.col("row_ref") == "0080")["0200"][0]
        assert on_bs_ead + off_bs_ead == pytest.approx(total_ead)

    def test_c07_ccr_rows_null(self) -> None:
        """CCR rows (0090-0130) remain null — CCR not implemented."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_bs_split())

        corp = bundle.c07_00["corporate"]
        for ref in ("0090", "0100", "0110", "0120", "0130"):
            row = corp.filter(pl.col("row_ref") == ref)
            if len(row) > 0:
                assert row["0200"][0] is None

    def test_c0801_on_bs_row_populated(self) -> None:
        """C 08.01 row 0020 (on-BS) is populated when bs_type available."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        corp = bundle.c08_01["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0020")
        # All IRB corp are ONB: EAD 5500+3000+600=9100
        assert on_bs["0110"][0] == pytest.approx(9100.0)

    def test_c07_section2_null_without_bs_type(self) -> None:
        """Section 2 rows are null when bs_type column is missing."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())  # no bs_type col

        corp = bundle.c07_00["corporate"]
        on_bs = corp.filter(pl.col("row_ref") == "0070")
        assert on_bs["0200"][0] is None


# =============================================================================
# PHASE 2E — ECAI UNRATED SPLIT (B3.1 COL 0235)
# =============================================================================


class TestECAIUnratedSplit:
    """Tests for Basel 3.1 ECAI unrated split column 0235."""

    def test_b31_ecai_unrated_column_present(self) -> None:
        """Col 0235 (without ECAI) present in Basel 3.1 output."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = list(bundle.c07_00.values())[0]
        assert "0235" in corp.columns

    def test_b31_unrated_exposure_in_0235(self) -> None:
        """Unrated exposure (sa_cqs=null) RWA goes to col 0235."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_DEF_1 has sa_cqs=None, rwa_final=1200 -> goes to 0235
        assert corp["0235"][0] == pytest.approx(1200.0)

    def test_b31_rated_plus_unrated_equals_total(self) -> None:
        """Col 0230 (rated) + col 0235 (unrated) = col 0220 (total RWEA)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c07_00["corporate"])
        rated = corp["0230"][0]
        unrated = corp["0235"][0]
        total = corp["0220"][0]
        assert rated + unrated == pytest.approx(total)


# =============================================================================
# PHASE 2G — "OF WHICH" DETAIL ROWS (DEFAULTED, SME)
# =============================================================================


class TestOfWhichDetailRows:
    """Tests for C 07.00 'of which' detail rows 0015 (defaulted) and 0020 (SME)."""

    def test_c07_defaulted_row_populated(self) -> None:
        """Row 0015 (defaulted) is populated when default_status column exists."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        # SA_DEF_1: EAD=800, default_status=True
        assert defaulted["0200"][0] == pytest.approx(800.0)

    def test_c07_defaulted_row_rwea(self) -> None:
        """Row 0015 RWEA matches defaulted exposures only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        # SA_DEF_1: rwa_final=1200
        assert defaulted["0220"][0] == pytest.approx(1200.0)

    def test_c07_sme_row_populated(self) -> None:
        """Row 0020 (SME) is populated when sme columns exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols())

        sme = bundle.c07_00["corporate_sme"]
        sme_row = sme.filter(pl.col("row_ref") == "0020")
        # corporate_sme has sme_supporting_factor_eligible=True, EAD=550
        assert sme_row["0200"][0] == pytest.approx(550.0)

    def test_c07_defaulted_row_null_without_flag(self) -> None:
        """Row 0015 is null when no defaulted identification columns exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())  # no default_status

        corp = bundle.c07_00["corporate"]
        defaulted = corp.filter(pl.col("row_ref") == "0015")
        assert defaulted["0200"][0] is None

    def test_c0801_defaulted_ead_col_0125(self) -> None:
        """C 08.01 col 0125 (defaulted EAD) populated from default_status."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: EAD=600, default_status=True
        assert corp["0125"][0] == pytest.approx(600.0)

    def test_c0801_defaulted_rwea_col_0265(self) -> None:
        """C 08.01 col 0265 (defaulted RWEA) populated from default_status."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: rwa_final=900, default_status=True
        assert corp["0265"][0] == pytest.approx(900.0)

    def test_c0801_defaulted_zero_when_none_defaulted(self) -> None:
        """C 08.01 cols 0125/0265 are 0.0 when no exposures are defaulted."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_phase2_cols(), framework="BASEL_3_1"
        )

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0125"][0] == pytest.approx(0.0)
        assert inst["0265"][0] == pytest.approx(0.0)


# =============================================================================
# PHASE 2C — CCF BREAKDOWN (COLS 0160-0190)
# =============================================================================


class TestCCFBreakdown:
    """Tests for off-BS CCF breakdown columns 0160-0190."""

    def test_c07_ccf_columns_populated(self) -> None:
        """CCF breakdown columns are populated when ccf_applied is available."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # 0% CCF: EAD=0, 20% CCF: EAD=400, 50% CCF: EAD=1500, 100% CCF: EAD=500
        assert corp["0160"][0] == pytest.approx(0.0)  # 0% bucket
        assert corp["0170"][0] == pytest.approx(400.0)  # 20% bucket
        assert corp["0180"][0] == pytest.approx(1500.0)  # 50% bucket
        assert corp["0190"][0] == pytest.approx(500.0)  # 100% bucket

    def test_c07_ccf_sum_equals_off_bs_ead(self) -> None:
        """Sum of CCF columns = total off-BS EAD."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = _get_total_row(bundle.c07_00["corporate"])
        ccf_sum = (
            (corp["0160"][0] or 0.0)
            + (corp["0170"][0] or 0.0)
            + (corp["0180"][0] or 0.0)
            + (corp["0190"][0] or 0.0)
        )
        # Off-BS EAD: 0+400+1500+500=2400
        assert ccf_sum == pytest.approx(2400.0)

    def test_c07_ccf_null_without_column(self) -> None:
        """CCF columns are null when ccf_applied not in data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0160"][0] is None
        assert corp["0170"][0] is None

    def test_b31_ccf_includes_40pct_bucket(self) -> None:
        """Basel 3.1 has 0171 (40% CCF) column; 0160 maps to 10% CCF."""
        # Create B3.1 data with 10% and 40% CCF values
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SA_OFF_10", "SA_OFF_40"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "drawn_amount": [0.0, 0.0],
                "undrawn_amount": [1000.0, 2000.0],
                "ead_final": [100.0, 800.0],
                "rwa_final": [100.0, 800.0],
                "risk_weight": [1.0, 1.0],
                "sa_cqs": [3, 3],
                "counterparty_reference": ["CP_A", "CP_B"],
                "bs_type": ["OFB", "OFB"],
                "ccf_applied": [0.1, 0.4],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0171" in corp.columns
        assert corp["0160"][0] == pytest.approx(100.0)  # 10% bucket
        assert corp["0171"][0] == pytest.approx(800.0)  # 40% bucket

    def test_c07_ccf_on_rw_section_rows(self) -> None:
        """CCF breakdown also works within risk weight section rows."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        corp = bundle.c07_00["corporate"]
        rw_100 = corp.filter(pl.col("row_name") == "100%")
        if len(rw_100) > 0:
            # All exposures are RW=100%, so RW section should match total CCF
            assert rw_100["0170"][0] == pytest.approx(400.0)


# =============================================================================
# PHASE 2D — OUTPUT FLOOR (B3.1 COLS 0275/0276)
# =============================================================================


class TestOutputFloor:
    """Tests for Basel 3.1 output floor columns 0275/0276."""

    def test_b31_output_floor_columns_present(self) -> None:
        """Cols 0275/0276 present in Basel 3.1 C 08.01 output."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0275" in corp.columns
        assert "0276" in corp.columns

    def test_b31_output_floor_exposure_value(self) -> None:
        """Col 0275 (SA-equiv exposure) = sum of EAD for the class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corporate: EAD 5500+3000=8500
        assert corp["0275"][0] == pytest.approx(8500.0)

    def test_b31_output_floor_sa_rwa(self) -> None:
        """Col 0276 (SA-equiv RWEA) = sum of sa_equivalent_rwa."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        # Corporate: sa_equivalent_rwa 5500+3000=8500
        assert corp["0276"][0] == pytest.approx(8500.0)

    def test_crr_output_floor_columns_absent(self) -> None:
        """Cols 0275/0276 are not in CRR C 08.01 output."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_output_floor(), framework="CRR"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0275" not in corp.columns
        assert "0276" not in corp.columns

    def test_b31_output_floor_null_without_sa_rwa(self) -> None:
        """Col 0276 is null when sa_equivalent_rwa not in data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results(), framework="BASEL_3_1"
        )

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0276"][0] is None


# =============================================================================
# PHASE 2F — LFSE SUB-COLUMNS (COLS 0030, 0140, 0240, 0270)
# =============================================================================


class TestLFSESubColumns:
    """Tests for C 08.01 large financial sector entity sub-columns."""

    def test_c0801_lfse_original_exposure(self) -> None:
        """Col 0030 (LFSE original exposure) populated from apply_fi_scalar."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        # Institution has apply_fi_scalar=True: drawn=2000, undrawn=0
        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0030"][0] == pytest.approx(2000.0)

    def test_c0801_lfse_ead(self) -> None:
        """Col 0140 (LFSE EAD) populated from apply_fi_scalar."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution: ead_final=2000, apply_fi_scalar=True
        assert inst["0140"][0] == pytest.approx(2000.0)

    def test_c0801_lfse_lgd(self) -> None:
        """Col 0240 (LFSE LGD) = EAD-weighted avg LGD for LFSE exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution LFSE: single exposure with LGD=0.45
        assert inst["0240"][0] == pytest.approx(0.45)

    def test_c0801_lfse_rwea(self) -> None:
        """Col 0270 (LFSE RWEA) populated from apply_fi_scalar."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        inst = _get_total_row(bundle.c08_01["institution"])
        # Institution: rwa_final=600, apply_fi_scalar=True
        assert inst["0270"][0] == pytest.approx(600.0)

    def test_c0801_lfse_zero_when_no_lfse_in_class(self) -> None:
        """LFSE cols are 0.0 when no exposures have apply_fi_scalar=True."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols())

        # Corporate has no LFSE exposures (all apply_fi_scalar=False)
        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0030"][0] == pytest.approx(0.0)
        assert corp["0140"][0] == pytest.approx(0.0)
        assert corp["0270"][0] == pytest.approx(0.0)

    def test_c0801_lfse_null_without_column(self) -> None:
        """LFSE cols are null when apply_fi_scalar not in data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())  # no apply_fi_scalar

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0030"][0] is None
        assert corp["0140"][0] is None
        assert corp["0270"][0] is None


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

        # Should produce C 07.00 per-class output
        assert len(bundle.c07_00) == 2
        assert "corporate" in bundle.c07_00

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
        assert len(bundle.c07_00) == 1

    def test_sa_only_data(self) -> None:
        """SA-only data produces C 07.00 but empty C 08.01/C 08.02."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert len(bundle.c07_00) > 0
        assert bundle.c08_01 == {}
        assert bundle.c08_02 == {}

    def test_irb_only_data(self) -> None:
        """IRB-only data produces C 08.01/C 08.02 but empty C 07.00."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())

        assert bundle.c07_00 == {}
        assert len(bundle.c08_01) > 0
        assert len(bundle.c08_02) > 0

    def test_single_exposure(self) -> None:
        """Single exposure produces valid per-class template."""
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

        assert "corporate" in bundle.c07_00
        corp = bundle.c07_00["corporate"]
        total = _get_total_row(corp)
        assert total["0200"][0] == pytest.approx(1000.0)

    def test_corporate_sme_separate_from_corporate(self) -> None:
        """corporate_sme gets its own separate template from corporate."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        assert "corporate" in bundle.c07_00
        assert "corporate_sme" in bundle.c07_00

        corp_ead = _get_total_row(bundle.c07_00["corporate"])["0200"][0]
        sme_ead = _get_total_row(bundle.c07_00["corporate_sme"])["0200"][0]

        # Corporate: 1200+2000=3200, SME: 550
        assert corp_ead == pytest.approx(3200.0)
        assert sme_ead == pytest.approx(550.0)
