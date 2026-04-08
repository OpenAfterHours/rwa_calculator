"""
Unit tests for COREP template generation.

Tests the COREPGenerator against synthetic exposure data to verify:
- Template definitions: CRR and Basel 3.1 column/row section structures
- C 07.00 (SA): Per-class output with 5 row sections, 4-digit column refs
- C 08.01 (IRB): Per-class output with 3 row sections, maturity in days
- C 08.02 (IRB PD grades): Per-class PD band assignment and aggregation
- C 08.03 (IRB PD ranges): 17 fixed regulatory PD buckets, 11 columns
- Excel export integration

Why: COREP templates are regulatory obligations — incorrect aggregation
leads to misreported capital requirements. These tests verify every
aggregation path with hand-calculated expected values.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
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
    OF_02_01_COLUMN_REFS,
    OF_02_01_COLUMNS,
    OF_02_01_ROW_SECTIONS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    SA_RISK_WEIGHT_BANDS,
    get_c07_columns,
    get_c08_columns,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    importlib.util.find_spec("xlsxwriter") is not None
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
                "CP_A",
                "CP_B",
                "CP_C",
                "CP_D",
                "CP_E",
                "CP_F",
                "CP_G",
                "CP_H",
            ],
            # Phase 2 columns
            "bs_type": ["ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB", "ONB"],
            "default_status": [False, False, False, False, False, False, False, True],
            "sme_supporting_factor_eligible": [
                False,
                False,
                True,
                False,
                False,
                False,
                False,
                False,
            ],
            "sme_supporting_factor_applied": [
                False,
                False,
                True,
                False,
                False,
                False,
                False,
                False,
            ],
            "infrastructure_factor_applied": [
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
            "rwa_before_sme_factor": [
                1200.0,
                2000.0,
                550.0,
                600.0,
                168.75,
                225.0,
                0.0,
                1200.0,
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
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_SME_1",
                "IRB_INST_1",
                "IRB_RETAIL_1",
                "IRB_DEF_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "institution",
                "retail_mortgage",
                "corporate",
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
                "SA_ON_1",
                "SA_OFF_0",
                "SA_OFF_20",
                "SA_OFF_50",
                "SA_OFF_100",
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
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
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
        sa_total_ead = sum(_get_total_row(df)["0200"][0] for df in bundle.c07_00.values())
        expected_sa_ead = _sa_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert sa_total_ead == pytest.approx(expected_sa_ead)

        # Sum EAD across all IRB classes
        irb_total_ead = sum(_get_total_row(df)["0110"][0] for df in bundle.c08_01.values())
        expected_irb_ead = _irb_results().select(pl.col("ead_final").sum()).collect()[0, 0]
        assert irb_total_ead == pytest.approx(expected_irb_ead)

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
        sheet_names: list[str] = list(sheets.keys()) if isinstance(sheets, dict) else []

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
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

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
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = list(bundle.c07_00.values())[0]
        assert "0235" in corp.columns

    def test_b31_unrated_exposure_in_0235(self) -> None:
        """Unrated exposure (sa_cqs=null) RWA goes to col 0235."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_DEF_1 has sa_cqs=None, rwa_final=1200 -> goes to 0235
        assert corp["0235"][0] == pytest.approx(1200.0)

    def test_b31_rated_plus_unrated_equals_total(self) -> None:
        """Col 0230 (rated) + col 0235 (unrated) = col 0220 (total RWEA)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_phase2_cols(), framework="BASEL_3_1")

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
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: EAD=600, default_status=True
        assert corp["0125"][0] == pytest.approx(600.0)

    def test_c0801_defaulted_rwea_col_0265(self) -> None:
        """C 08.01 col 0265 (defaulted RWEA) populated from default_status."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_DEF_1: rwa_final=900, default_status=True
        assert corp["0265"][0] == pytest.approx(900.0)

    def test_c0801_defaulted_zero_when_none_defaulted(self) -> None:
        """C 08.01 cols 0125/0265 are 0.0 when no exposures are defaulted."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_phase2_cols(), framework="BASEL_3_1")

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
        bundle = gen.generate_from_lazyframe(_irb_results_with_output_floor(), framework="CRR")

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0275" not in corp.columns
        assert "0276" not in corp.columns

    def test_b31_output_floor_null_without_sa_rwa(self) -> None:
        """Col 0276 is null when sa_equivalent_rwa not in data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="BASEL_3_1")

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


# =============================================================================
# TASK 2H: CRM SUBSTITUTION FLOWS
# =============================================================================


def _sa_results_with_substitution() -> pl.LazyFrame:
    """SA results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate exposure SA_CORP_2 has a guarantee from an institution.
    The guaranteed portion (500) flows out of corporate class into institution class.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_INST_1",
                "SA_RETAIL_1",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 200.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 50.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 225.0],
            "rwa_final": [1140.0, 1900.0, 600.0, 168.75],
            "risk_weight": [1.0, 1.0, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 2.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 1.0],
            "sa_cqs": [3, 0, 2, 0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
            "guaranteed_portion": [0.0, 500.0, 0.0, 0.0],
            # Pre-CRM: both corporates are in "corporate" class
            "pre_crm_exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_other",
            ],
            # Post-CRM: SA_CORP_2's guaranteed portion migrates to "institution"
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
                "retail_other",
            ],
        }
    )


def _irb_results_with_substitution() -> pl.LazyFrame:
    """IRB results with CRM substitution columns for Task 2H testing.

    Scenario: Corporate IRB exposure IRB_CORP_2 guaranteed by institution.
    The guaranteed portion (800) flows out of corporate class into institution class.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
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
            "bs_type": ["ONB", "ONB", "ONB"],
            "guaranteed_portion": [0.0, 800.0, 0.0],
            "pre_crm_exposure_class": ["corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "institution",
                "institution",
            ],
        }
    )


class TestSubstitutionFlows:
    """Task 2H: CRM substitution flow columns (C 07.00: 0090/0100/0110;
    C 08.01: 0040/0070/0080/0090).

    Why: COREP requires reporting how CRM guarantees cause exposure to
    'flow' between exposure classes. Outflows show guaranteed portions
    leaving the borrower's class; inflows show guaranteed portions
    arriving from other classes via the guarantor's class assignment.
    """

    def test_c07_outflow_populated(self) -> None:
        """Col 0090 shows guaranteed portion leaving the class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_2 has 500 guaranteed_portion migrating to institution
        assert corp["0090"][0] == pytest.approx(500.0)

    def test_c07_inflow_populated(self) -> None:
        """Col 0100 shows guaranteed portion arriving from other classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        inst = _get_total_row(bundle.c07_00["institution"])
        # SA_CORP_2's 500 guaranteed portion flows into institution class
        assert inst["0100"][0] == pytest.approx(500.0)

    def test_c07_no_flow_class_has_zero(self) -> None:
        """Class with no substitution has 0 outflow and 0 inflow."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        retail = _get_total_row(bundle.c07_00["retail_other"])
        assert retail["0090"][0] == pytest.approx(0.0)
        assert retail["0100"][0] == pytest.approx(0.0)

    def test_c07_net_exposure_after_substitution(self) -> None:
        """Col 0110 = 0040 - 0050 - 0090 + 0100 (other CRM cols are None/0)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_substitution())

        corp = _get_total_row(bundle.c07_00["corporate"])
        v_0040 = corp["0040"][0]
        v_0050 = corp["0050"][0]
        v_0090 = corp["0090"][0]
        v_0100 = corp["0100"][0]
        v_0110 = corp["0110"][0]

        expected = v_0040 - v_0050 - v_0090 + v_0100
        assert v_0110 == pytest.approx(expected)

    def test_c07_outflow_zero_without_substitution_cols(self) -> None:
        """Without pre/post CRM columns, outflow defaults to 0."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0090"][0] == pytest.approx(0.0)

    def test_c08_guarantee_col_populated(self) -> None:
        """C 08.01 col 0040 shows guaranteed_portion sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_CORP_2 has 800 guaranteed_portion
        assert corp["0040"][0] == pytest.approx(800.0)

    def test_c08_outflow_populated(self) -> None:
        """C 08.01 col 0070 shows guaranteed portion leaving the class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        assert corp["0070"][0] == pytest.approx(800.0)

    def test_c08_inflow_populated(self) -> None:
        """C 08.01 col 0080 shows guaranteed portion arriving from other classes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        inst = _get_total_row(bundle.c08_01["institution"])
        assert inst["0080"][0] == pytest.approx(800.0)

    def test_c08_net_after_substitution(self) -> None:
        """C 08.01 col 0090 = 0020 - 0040 - 0070 + 0080."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_substitution())

        corp = _get_total_row(bundle.c08_01["corporate"])
        v_0020 = corp["0020"][0]
        v_0040 = corp["0040"][0]
        v_0070 = corp["0070"][0]
        v_0080 = corp["0080"][0]
        v_0090 = corp["0090"][0]

        expected = v_0020 - v_0040 - v_0070 + v_0080
        assert v_0090 == pytest.approx(expected)


# =============================================================================
# Fixtures for on-BS netting (Task 3D)
# =============================================================================


def _sa_results_with_netting() -> pl.LazyFrame:
    """SA results with on_bs_netting_amount for Task 3D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_CORP_2",
                "SA_INST_1",
                "SA_RETAIL_1",
            ],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "institution", "retail_other"],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 500.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 100.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 550.0],
            "rwa_final": [1200.0, 2000.0, 600.0, 412.5],
            "risk_weight": [1.00, 1.00, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 2.0],
            "collateral_adjusted_value": [0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, None, 2, None],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
            # Netting amounts: CORP_1 has 150 netting, INST_1 has 200
            "on_bs_netting_amount": [150.0, 0.0, 200.0, 0.0],
        }
    )


def _irb_results_with_netting() -> pl.LazyFrame:
    """IRB results with on_bs_netting_amount for Task 3D testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_INST_1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "foundation_irb"],
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
            "el_shortfall": [0.0, 3.5, 0.0],
            "el_excess": [2.625, 0.0, 1.2],
            "scra_provision_amount": [10.0, 5.0, 2.0],
            "gcra_provision_amount": [5.0, 5.0, 1.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_W"],
            # Netting amounts: CORP_1 has 300 netting
            "on_bs_netting_amount": [300.0, 0.0, 0.0],
        }
    )


class TestOnBSNetting:
    """Task 3D: On-balance-sheet netting (COREP col 0035).

    Why: Basel 3.1 introduces col 0035 to separately report on-BS netting
    within the EAD waterfall: Original (0010) - Provisions (0030) - Netting
    (0035) = Net exposure (0040). Without this, the netting benefit is
    invisible in COREP reporting.
    """

    def test_c07_col_0035_populated_b31(self) -> None:
        """Col 0035 shows summed on_bs_netting_amount for Basel 3.1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_1 has 150 netting, SA_CORP_2 has 0 → total 150
        assert corp["0035"][0] == pytest.approx(150.0)

    def test_c07_col_0035_absent_crr(self) -> None:
        """Col 0035 doesn't exist under CRR (no on-BS netting column)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="CRR")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0035" not in corp.columns

    def test_c07_col_0040_includes_netting_b31(self) -> None:
        """Col 0040 = 0010 - 0030 - 0035 (netting deducted from net exposure)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        v_0010 = corp["0010"][0]
        v_0030 = corp["0030"][0]
        v_0035 = corp["0035"][0]
        v_0040 = corp["0040"][0]
        assert v_0040 == pytest.approx(v_0010 - v_0030 - v_0035)

    def test_c07_zero_netting_class(self) -> None:
        """Class with no netting exposures reports 0 for col 0035."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        retail = _get_total_row(bundle.c07_00["retail_other"])
        assert retail["0035"][0] == pytest.approx(0.0)

    def test_c08_col_0035_populated_b31(self) -> None:
        """C 08.01 col 0035 shows summed on_bs_netting_amount for Basel 3.1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c08_01["corporate"])
        # IRB_CORP_1 has 300 netting, IRB_CORP_2 has 0 → total 300
        assert corp["0035"][0] == pytest.approx(300.0)

    def test_c08_col_0035_absent_crr(self) -> None:
        """C 08.01 col 0035 doesn't exist under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_netting(), framework="CRR")
        corp = _get_total_row(bundle.c08_01["corporate"])
        assert "0035" not in corp.columns

    def test_c07_netting_without_column(self) -> None:
        """Without on_bs_netting_amount in data, col 0035 is None."""
        gen = COREPGenerator()
        # _sa_results() does not have on_bs_netting_amount
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0035"][0] is None


# =============================================================================
# Fixtures for specialised lending detail rows (Task 3G)
# =============================================================================


def _sa_results_with_sl() -> pl.LazyFrame:
    """SA results with specialised lending types and project phases for Task 3G."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CORP_1",
                "SA_SL_OF_1",
                "SA_SL_CF_1",
                "SA_SL_PF_PRE_1",
                "SA_SL_PF_OP_1",
                "SA_SL_PF_HQ_1",
            ],
            "approach_applied": ["standardised"] * 6,
            "exposure_class": ["corporate"] * 6,
            "drawn_amount": [1000.0, 500.0, 300.0, 200.0, 400.0, 600.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 500.0, 300.0, 200.0, 400.0, 600.0],
            "rwa_final": [1000.0, 500.0, 300.0, 260.0, 400.0, 360.0],
            "risk_weight": [1.00, 1.00, 1.00, 1.30, 1.00, 0.60],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "collateral_adjusted_value": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, None, None, None, None, None],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E", "CP_F"],
            # SL type: None for non-SL, specific type for SL exposures
            "sl_type": [
                None,
                "object_finance",
                "commodities_finance",
                "project_finance",
                "project_finance",
                "project_finance",
            ],
            # Project phase: only for project_finance exposures
            "sl_project_phase": [
                None,
                None,
                None,
                "pre_operational",
                "operational",
                "high_quality_operational",
            ],
        }
    )


class TestSpecialisedLendingRows:
    """Task 3G: Specialised lending detail rows (B3.1 OF 07.00 rows 0021-0026).

    Why: Basel 3.1 requires separate reporting of object finance, commodities
    finance, and project finance (with phase breakdown) within each exposure
    class. These "of which" rows enable supervisors to monitor concentration
    in specialised lending sub-types.
    """

    def test_object_finance_row_populated(self) -> None:
        """Row 0021 shows object finance exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0021 = corp.filter(pl.col("row_ref") == "0021")
        assert len(row_0021) == 1
        # SA_SL_OF_1: ead_final=500
        assert row_0021["0200"][0] == pytest.approx(500.0)

    def test_commodities_finance_row_populated(self) -> None:
        """Row 0022 shows commodities finance exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0022 = corp.filter(pl.col("row_ref") == "0022")
        assert len(row_0022) == 1
        # SA_SL_CF_1: ead_final=300
        assert row_0022["0200"][0] == pytest.approx(300.0)

    def test_project_finance_row_is_total(self) -> None:
        """Row 0023 shows total project finance (all phases)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0023 = corp.filter(pl.col("row_ref") == "0023")
        assert len(row_0023) == 1
        # 3 PF exposures: 200 + 400 + 600 = 1200
        assert row_0023["0200"][0] == pytest.approx(1200.0)

    def test_project_finance_pre_operational(self) -> None:
        """Row 0024 shows pre-operational project finance."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0024 = corp.filter(pl.col("row_ref") == "0024")
        assert len(row_0024) == 1
        assert row_0024["0200"][0] == pytest.approx(200.0)

    def test_project_finance_operational(self) -> None:
        """Row 0025 shows operational project finance."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0025 = corp.filter(pl.col("row_ref") == "0025")
        assert len(row_0025) == 1
        assert row_0025["0200"][0] == pytest.approx(400.0)

    def test_project_finance_hq_operational(self) -> None:
        """Row 0026 shows high quality operational project finance."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0026 = corp.filter(pl.col("row_ref") == "0026")
        assert len(row_0026) == 1
        assert row_0026["0200"][0] == pytest.approx(600.0)

    def test_sl_rows_absent_crr(self) -> None:
        """SL detail rows don't exist under CRR (no rows 0021-0026)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        sl_rows = corp.filter(
            pl.col("row_ref").is_in(["0021", "0022", "0023", "0024", "0025", "0026"])
        )
        assert len(sl_rows) == 0

    def test_sl_rows_null_without_sl_data(self) -> None:
        """Without sl_type column, SL rows are null."""
        gen = COREPGenerator()
        # _sa_results() has no sl_type column
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_0021 = corp.filter(pl.col("row_ref") == "0021")
        assert len(row_0021) == 1
        assert row_0021["0200"][0] is None

    def test_phase_sum_equals_total_pf(self) -> None:
        """Sum of phase rows (0024-0026) equals total project finance row (0023)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_sl(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        total_pf = corp.filter(pl.col("row_ref") == "0023")["0200"][0]
        pre_op = corp.filter(pl.col("row_ref") == "0024")["0200"][0]
        op = corp.filter(pl.col("row_ref") == "0025")["0200"][0]
        hq_op = corp.filter(pl.col("row_ref") == "0026")["0200"][0]
        assert total_pf == pytest.approx(pre_op + op + hq_op)


# =============================================================================
# Fixtures for real estate detail rows (Task 3H)
# =============================================================================


def _sa_results_with_re() -> pl.LazyFrame:
    """SA results with real estate columns for Task 3H testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_RE_RES_1",
                "SA_RE_RES_2",
                "SA_RE_COMM_1",
                "SA_RE_COMM_2",
                "SA_RE_COMM_3",
                "SA_RE_ADC_1",
                "SA_CORP_1",
            ],
            "approach_applied": ["standardised"] * 7,
            "exposure_class": [
                "secured_by_re_residential",
                "secured_by_re_residential",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "secured_by_re_commercial",
                "corporate",
            ],
            "drawn_amount": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [200.0, 300.0, 500.0, 400.0, 150.0, 100.0, 1000.0],
            "rwa_final": [40.0, 105.0, 300.0, 240.0, 112.5, 150.0, 1000.0],
            "risk_weight": [0.20, 0.35, 0.60, 0.60, 0.75, 1.50, 1.00],
            "scra_provision_amount": [0.0] * 7,
            "gcra_provision_amount": [0.0] * 7,
            "collateral_adjusted_value": [0.0] * 7,
            "guaranteed_portion": [0.0] * 7,
            "sa_cqs": [None] * 7,
            "counterparty_reference": [
                "CP_R1",
                "CP_R2",
                "CP_C1",
                "CP_C2",
                "CP_C3",
                "CP_ADC",
                "CP_CORP",
            ],
            "property_type": [
                "residential",
                "residential",
                "commercial",
                "commercial",
                "commercial",
                "commercial",
                None,
            ],
            "materially_dependent_on_property": [
                False,
                True,
                False,
                True,
                False,
                None,
                None,
            ],
            "is_adc": [False, False, False, False, False, True, False],
            # SME flag for commercial sub-split
            "sme_supporting_factor_eligible": [
                False,
                False,
                False,
                False,
                True,
                False,
                False,
            ],
        }
    )


class TestRealEstateRows:
    """Task 3H: Real estate detail rows (B3.1 OF 07.00 rows 0330-0360).

    Why: Basel 3.1 requires granular reporting of RE exposures by property
    type, cash-flow dependency, and SME status. This enables supervisors to
    assess concentration risk in property-secured lending.
    """

    def test_residential_re_total(self) -> None:
        """Row 0330 shows total regulatory residential RE."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        # RE exposures are in "secured_by_re_residential" class
        re_res = bundle.c07_00.get("secured_by_re_residential")
        assert re_res is not None
        row = re_res.filter(pl.col("row_ref") == "0330")
        assert len(row) == 1
        # SA_RE_RES_1 + SA_RE_RES_2: 200 + 300 = 500
        assert row["0200"][0] == pytest.approx(500.0)

    def test_residential_not_dependent(self) -> None:
        """Row 0331: residential, not materially dependent."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        row = re_res.filter(pl.col("row_ref") == "0331")
        assert len(row) == 1
        # SA_RE_RES_1: 200 (not dependent)
        assert row["0200"][0] == pytest.approx(200.0)

    def test_residential_dependent(self) -> None:
        """Row 0332: residential, materially dependent."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        row = re_res.filter(pl.col("row_ref") == "0332")
        assert len(row) == 1
        # SA_RE_RES_2: 300 (dependent)
        assert row["0200"][0] == pytest.approx(300.0)

    def test_commercial_re_total(self) -> None:
        """Row 0340 shows total regulatory commercial RE."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00.get("secured_by_re_commercial")
        assert re_comm is not None
        row = re_comm.filter(pl.col("row_ref") == "0340")
        assert len(row) == 1
        # All commercial (excl ADC): 500 + 400 + 150 + 100 = 1150
        # But property_type = commercial for all, including ADC
        assert row["0200"][0] == pytest.approx(1150.0)

    def test_commercial_not_dependent_non_sme(self) -> None:
        """Row 0341: commercial, not dependent, non-SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0341")
        assert len(row) == 1
        # SA_RE_COMM_1: 500 (not dependent, not SME)
        assert row["0200"][0] == pytest.approx(500.0)

    def test_commercial_sme_not_dependent(self) -> None:
        """Row 0343: commercial, not dependent, SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0343")
        assert len(row) == 1
        # SA_RE_COMM_3: 150 (not dependent, SME)
        assert row["0200"][0] == pytest.approx(150.0)

    def test_adc_row(self) -> None:
        """Row 0360 shows ADC exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_comm = bundle.c07_00["secured_by_re_commercial"]
        row = re_comm.filter(pl.col("row_ref") == "0360")
        assert len(row) == 1
        # SA_RE_ADC_1: 100
        assert row["0200"][0] == pytest.approx(100.0)

    def test_re_rows_absent_crr(self) -> None:
        """RE detail rows don't exist under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="CRR")
        re_res = bundle.c07_00.get("secured_by_re_residential")
        if re_res is not None:
            re_rows = re_res.filter(
                pl.col("row_ref").is_in(["0330", "0331", "0332", "0340", "0341", "0342", "0360"])
            )
            assert len(re_rows) == 0

    def test_dependent_splits_sum_to_total(self) -> None:
        """Rows 0331 + 0332 = 0330 for residential RE."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re(), framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        total = re_res.filter(pl.col("row_ref") == "0330")["0200"][0]
        not_dep = re_res.filter(pl.col("row_ref") == "0331")["0200"][0]
        dep = re_res.filter(pl.col("row_ref") == "0332")["0200"][0]
        assert total == pytest.approx(not_dep + dep)


# =============================================================================
# Fixtures for equity transitional rows (Task 3I)
# =============================================================================


def _sa_results_with_equity_transitional() -> pl.LazyFrame:
    """SA results with equity transitional columns for Task 3I testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_EQ_HR_1",
                "SA_EQ_OTHER_1",
                "SA_IRB_HR_1",
                "SA_IRB_OTHER_1",
                "SA_CORP_1",
            ],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": ["equity"] * 4 + ["corporate"],
            "drawn_amount": [100.0, 200.0, 150.0, 300.0, 1000.0],
            "undrawn_amount": [0.0] * 5,
            "ead_final": [100.0, 200.0, 150.0, 300.0, 1000.0],
            "rwa_final": [400.0, 500.0, 600.0, 750.0, 1000.0],
            "risk_weight": [4.00, 2.50, 4.00, 2.50, 1.00],
            "scra_provision_amount": [0.0] * 5,
            "gcra_provision_amount": [0.0] * 5,
            "collateral_adjusted_value": [0.0] * 5,
            "guaranteed_portion": [0.0] * 5,
            "sa_cqs": [None] * 5,
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "equity_transitional_approach": [
                "sa_transitional",
                "sa_transitional",
                "irb_transitional",
                "irb_transitional",
                None,
            ],
            "equity_higher_risk": [True, False, True, False, None],
        }
    )


class TestEquityTransitionalRows:
    """Task 3I: Equity transitional provisions (B3.1 OF 07.00 rows 0371-0374).

    Why: Basel 3.1 removes equity IRB treatment and transitions all equity to
    SA. Rows 0371-0374 report the transitional equity exposures split by
    approach (SA/IRB transitional) and risk level (higher risk vs other).
    """

    def test_sa_higher_risk_row(self) -> None:
        """Row 0371: SA transitional, higher risk."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0371")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(100.0)

    def test_sa_other_equity_row(self) -> None:
        """Row 0372: SA transitional, other equity."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0372")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(200.0)

    def test_irb_higher_risk_row(self) -> None:
        """Row 0373: IRB transitional, higher risk."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0373")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(150.0)

    def test_irb_other_equity_row(self) -> None:
        """Row 0374: IRB transitional, other equity."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="BASEL_3_1"
        )
        eq = bundle.c07_00["equity"]
        row = eq.filter(pl.col("row_ref") == "0374")
        assert len(row) == 1
        assert row["0200"][0] == pytest.approx(300.0)

    def test_equity_rows_absent_crr(self) -> None:
        """Equity transitional rows don't exist under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_equity_transitional(), framework="CRR"
        )
        eq = bundle.c07_00.get("equity")
        if eq is not None:
            eq_rows = eq.filter(pl.col("row_ref").is_in(["0371", "0372", "0373", "0374"]))
            assert len(eq_rows) == 0

    def test_equity_rows_null_without_column(self) -> None:
        """Without equity_transitional_approach, equity rows are null."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00.get("corporate")
        if corp is not None:
            row = corp.filter(pl.col("row_ref") == "0371")
            if len(row) > 0:
                assert row["0200"][0] is None


# =============================================================================
# COLLATERAL METHOD SPLIT — Task 3A
# =============================================================================


def _sa_results_with_collateral_split() -> pl.LazyFrame:
    """SA results with per-type collateral columns for collateral method split tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_INST_1"],
            "approach_applied": ["standardised"] * 3,
            "exposure_class": ["corporate", "corporate", "institution"],
            "drawn_amount": [1000.0, 2000.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3000.0],
            "rwa_final": [1000.0, 2000.0, 600.0],
            "risk_weight": [1.0, 1.0, 0.2],
            "scra_provision_amount": [10.0, 20.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0],
            "sa_cqs": [3, 0, 2],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D"],
            # Collateral columns
            "collateral_adjusted_value": [150.0, 0.0, 200.0],
            "collateral_market_value": [180.0, 0.0, 250.0],
            "collateral_financial_value": [100.0, 0.0, 200.0],
            "collateral_cash_value": [50.0, 0.0, 100.0],
            "collateral_re_value": [30.0, 0.0, 0.0],
            "collateral_receivables_value": [10.0, 0.0, 0.0],
            "collateral_other_physical_value": [10.0, 0.0, 0.0],
            "guaranteed_portion": [0.0, 500.0, 0.0],
        }
    )


def _irb_results_with_collateral_split() -> pl.LazyFrame:
    """IRB results with per-type collateral columns for collateral method split tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [3850.0, 1800.0],
            "risk_weight": [0.70, 0.60],
            "irb_pd_floored": [0.005, 0.01],
            "irb_lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "irb_expected_loss": [12.375, 13.5],
            "irb_capital_k": [0.056, 0.048],
            "provision_held": [15.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [2.625, 0.0],
            "scra_provision_amount": [10.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0],
            "counterparty_reference": ["CP_X", "CP_Y"],
            # Collateral columns
            "collateral_financial_value": [200.0, 0.0],
            "collateral_cash_value": [80.0, 0.0],
            "collateral_re_value": [150.0, 100.0],
            "collateral_receivables_value": [50.0, 0.0],
            "collateral_other_physical_value": [30.0, 20.0],
            "guaranteed_portion": [0.0, 500.0],
        }
    )


class TestCollateralMethodSplit:
    """Tests for Task 3A: collateral method split for COREP reporting."""

    def test_c07_comprehensive_method_columns(self) -> None:
        """C 07.00 cols 0070=0.0, 0080 populated, 0120=0.0 for SA with collateral."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0070: Simple method not used → 0.0
        assert total["0070"][0] == pytest.approx(0.0)
        # 0080: Other funded = RE + receivables + other_physical = 30+10+10 = 50
        assert total["0080"][0] == pytest.approx(50.0)
        # 0120: He = 0 for loans
        assert total["0120"][0] == pytest.approx(0.0)

    def test_c07_vol_mat_adjustment(self) -> None:
        """C 07.00 col 0140 = market_value - adjusted_value."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Corporate: market_value=180, adjusted_value=150 → vol/mat adj = 30
        assert total["0140"][0] == pytest.approx(30.0)

    def test_c07_fully_adjusted_exposure(self) -> None:
        """C 07.00 col 0150 = max(0, 0110 - 0130)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0110 = net after CRM substitution
        v_0110 = total["0110"][0]
        # 0130 = collateral adjusted value = 150
        v_0130 = total["0130"][0]
        # 0150 = max(0, 0110 - 0130)
        expected = max(0.0, v_0110 - v_0130)
        assert total["0150"][0] == pytest.approx(expected)

    def test_c08_collateral_type_breakdown(self) -> None:
        """C 08.01 cols 0180/0190/0200/0210 populated from per-type collateral values."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0180: Financial collateral = 200 + 0 = 200
        assert total["0180"][0] == pytest.approx(200.0)
        # 0190: Real estate = 150 + 100 = 250
        assert total["0190"][0] == pytest.approx(250.0)
        # 0200: Other physical = 30 + 20 = 50
        assert total["0200"][0] == pytest.approx(50.0)
        # 0210: Receivables = 50 + 0 = 50
        assert total["0210"][0] == pytest.approx(50.0)

    def test_c08_other_funded_protection(self) -> None:
        """C 08.01 cols 0170-0173 are 0.0 (catch-all types not tracked)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        assert total["0170"][0] == pytest.approx(0.0)
        assert total["0171"][0] == pytest.approx(0.0)
        assert total["0172"][0] == pytest.approx(0.0)
        assert total["0173"][0] == pytest.approx(0.0)

    def test_c08_guarantees_unfunded(self) -> None:
        """C 08.01 col 0150 = guaranteed_portion sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # guaranteed_portion = 0 + 500 = 500
        assert total["0150"][0] == pytest.approx(500.0)

    def test_c08_other_funded_for_irb(self) -> None:
        """C 08.01 col 0060 = non-financial collateral total."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # 0060 = RE + receivables + other_physical = (150+100) + (50+0) + (30+20) = 350
        assert total["0060"][0] == pytest.approx(350.0)

    def test_no_collateral_class(self) -> None:
        """Columns are 0.0 when no collateral in class (institution has no non-fin)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        inst = bundle.c07_00["institution"]
        total = inst.filter(pl.col("row_ref") == "0010")

        # Institution has no non-financial collateral
        assert total["0080"][0] == pytest.approx(0.0)
        # But has financial collateral
        assert total["0130"][0] == pytest.approx(200.0)


# =============================================================================
# Task 3B: Credit Derivatives Tracking
# =============================================================================


def _sa_results_with_credit_derivatives() -> pl.LazyFrame:
    """SA results with protection_type distinguishing guarantees from credit derivatives."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_CORP_3", "SA_INST_1"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "corporate", "institution"],
            "drawn_amount": [1000.0, 2000.0, 1500.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 1500.0, 3000.0],
            "rwa_final": [1000.0, 2000.0, 1500.0, 600.0],
            "risk_weight": [1.0, 1.0, 1.0, 0.2],
            "scra_provision_amount": [10.0, 20.0, 15.0, 0.0],
            "gcra_provision_amount": [5.0, 10.0, 5.0, 15.0],
            "sa_cqs": [3, 0, 2, 2],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            # Protection split: CORP_1 has guarantee, CORP_2 has credit derivative
            "guaranteed_portion": [200.0, 300.0, 0.0, 0.0],
            "protection_type": ["guarantee", "credit_derivative", None, None],
            # Substitution tracking
            "pre_crm_exposure_class": ["corporate", "corporate", "corporate", "institution"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
            ],
        }
    )


def _irb_results_with_credit_derivatives() -> pl.LazyFrame:
    """IRB results with protection_type for credit derivative tracking tests."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [3850.0, 1800.0],
            "risk_weight": [0.70, 0.60],
            "irb_pd_floored": [0.005, 0.01],
            "irb_lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "irb_expected_loss": [12.375, 13.5],
            "irb_capital_k": [0.056, 0.048],
            "provision_held": [15.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [2.625, 0.0],
            "counterparty_reference": ["CP_E", "CP_F"],
            # Protection split: CORP_1 has guarantee, CORP_2 has credit derivative
            "guaranteed_portion": [800.0, 400.0],
            "protection_type": ["guarantee", "credit_derivative"],
            # Substitution tracking
            "pre_crm_exposure_class": ["corporate", "corporate"],
            "post_crm_exposure_class_guaranteed": ["corporate", "corporate"],
        }
    )


class TestCreditDerivativeTracking:
    """Tests for Task 3B: credit derivative tracking for COREP reporting."""

    def test_c07_guarantee_and_cd_split(self) -> None:
        """C 07.00 col 0050=guarantee only, col 0060=credit derivative only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0050: guarantees only = 200.0 (SA_CORP_1)
        assert total["0050"][0] == pytest.approx(200.0)
        # Col 0060: credit derivatives only = 300.0 (SA_CORP_2)
        assert total["0060"][0] == pytest.approx(300.0)

    def test_c07_institution_no_protection(self) -> None:
        """C 07.00 cols 0050/0060 are 0 for institution with no protection."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        inst = bundle.c07_00["institution"]
        total = inst.filter(pl.col("row_ref") == "0010")

        assert total["0050"][0] == pytest.approx(0.0)
        assert total["0060"][0] == pytest.approx(0.0)

    def test_c07_col_0110_includes_cd_deduction(self) -> None:
        """C 07.00 col 0110 formula deducts both guarantees and credit derivatives."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        col_0040 = total["0040"][0]
        col_0050 = total["0050"][0]
        col_0060 = total["0060"][0]
        col_0110 = total["0110"][0]

        # 0110 = 0040 - 0050 - 0060 - 0070 - 0080 - 0090 + 0100
        # (other cols are 0 since no collateral/substitution flows)
        assert col_0110 == pytest.approx(col_0040 - col_0050 - col_0060)

    def test_c08_guarantee_and_cd_split(self) -> None:
        """C 08.01 col 0040=guarantee only, col 0050=credit derivative only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0040: guarantees only = 800.0 (IRB_CORP_1)
        assert total["0040"][0] == pytest.approx(800.0)
        # Col 0050: credit derivatives only = 400.0 (IRB_CORP_2)
        assert total["0050"][0] == pytest.approx(400.0)

    def test_c08_unfunded_protection_split(self) -> None:
        """C 08.01 col 0150=guarantee, col 0160=credit derivative."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0150: unfunded guarantees = 800.0
        assert total["0150"][0] == pytest.approx(800.0)
        # Col 0160: unfunded credit derivatives = 400.0
        assert total["0160"][0] == pytest.approx(400.0)

    def test_c08_pre_credit_derivatives_rwea(self) -> None:
        """C 08.01 col 0310 = total RWEA (pre-credit-derivative baseline)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_credit_derivatives(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0310: total RWEA = 3850 + 1800 = 5650
        assert total["0310"][0] == pytest.approx(5650.0)

    def test_backward_compat_no_protection_type(self) -> None:
        """Without protection_type column, all guaranteed_portion is col 0050 (guarantees)."""
        gen = COREPGenerator()
        # Use the existing collateral split fixture which has guaranteed_portion but no
        # protection_type column — backward compatibility path
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_collateral_split(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        # Col 0050: all guaranteed_portion goes to guarantees = 500.0 (SA_CORP_2)
        assert total["0050"][0] == pytest.approx(500.0)
        # Col 0060: 0.0 since no protection_type column to identify credit derivatives
        assert total["0060"][0] == pytest.approx(0.0)

    def test_crr_framework_includes_cd_cols(self) -> None:
        """CRR framework also has cols 0050/0060 for C 07.00."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_credit_derivatives(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")

        assert total["0050"][0] == pytest.approx(200.0)
        assert total["0060"][0] == pytest.approx(300.0)


# =============================================================================
# CURRENCY MISMATCH MULTIPLIER — Task 3J
# =============================================================================


def _sa_results_with_currency_mismatch() -> pl.LazyFrame:
    """SA results with currency mismatch multiplier tracking for COREP row 0380."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_RET_1", "SA_RET_2", "SA_MORT_1", "SA_CORP_1"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["retail_other", "retail_other", "retail_mortgage", "corporate"],
            "drawn_amount": [100.0, 200.0, 500.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [100.0, 200.0, 500.0, 3000.0],
            "rwa_final": [112.5, 150.0, 375.0, 3000.0],
            "risk_weight": [1.125, 0.75, 0.75, 1.0],
            "sa_cqs": [None, None, None, 3],
            "currency_mismatch_multiplier_applied": [True, False, True, False],
        }
    )


class TestCurrencyMismatchRow:
    """Task 3J: Currency mismatch multiplier memorandum row 0380.

    Why: Basel 3.1 Art. 123B requires reporting of retail and RE exposures
    subject to the 1.5x currency mismatch RW multiplier. Row 0380 in the
    OF 07.00 memorandum section aggregates these exposures for supervisory
    transparency.
    """

    def test_b31_row_0380_populated(self) -> None:
        """Row 0380 aggregates exposures with currency mismatch applied."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        # Retail class — SA_RET_1 has mismatch, SA_RET_2 does not
        ret = bundle.c07_00["retail_other"]
        row = ret.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        # Only SA_RET_1 (EAD=100, RWA=112.5) has mismatch
        assert row["0200"][0] == pytest.approx(100.0)
        assert row["0220"][0] == pytest.approx(112.5)

    def test_b31_mortgage_row_0380(self) -> None:
        """Row 0380 works for retail_mortgage class too."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        mort = bundle.c07_00["retail_mortgage"]
        row = mort.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        # SA_MORT_1 has mismatch (EAD=500, RWA=375)
        assert row["0200"][0] == pytest.approx(500.0)
        assert row["0220"][0] == pytest.approx(375.0)

    def test_b31_corporate_row_0380_null(self) -> None:
        """Corporate class — no mismatch exposures → row 0380 is null."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_currency_mismatch(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0380")
        assert len(row) == 1
        assert row["0200"][0] is None

    def test_crr_no_row_0380(self) -> None:
        """CRR framework does not have row 0380 — it's a B3.1-only memorandum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_currency_mismatch(), framework="CRR")
        ret = bundle.c07_00.get("retail_other")
        if ret is not None:
            row = ret.filter(pl.col("row_ref") == "0380")
            assert len(row) == 0

    def test_no_mismatch_column_row_0380_null(self) -> None:
        """Without currency_mismatch_multiplier_applied column, row 0380 is null."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = bundle.c07_00.get("corporate")
        if corp is not None:
            row = corp.filter(pl.col("row_ref") == "0380")
            if len(row) > 0:
                assert row["0200"][0] is None


# =============================================================================
# POST-MODEL ADJUSTMENTS — Task 3F
# =============================================================================


def _irb_results_with_pma() -> pl.LazyFrame:
    """IRB results with post-model adjustment columns for C 08.01 testing.

    Why: Basel 3.1 requires reporting of IRB RWEA waterfall including
    pre-adjustment RWEA, general PMAs, mortgage RW floor, and unrecognised
    exposure adjustments. This fixture simulates pipeline output after the
    IRB calculator has applied post-model adjustments.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_CORP_1", "IRB_CORP_2", "IRB_MTG_1"],
            "approach_applied": ["foundation_irb", "foundation_irb", "advanced_irb"],
            "exposure_class": ["corporate", "corporate", "retail_mortgage"],
            "drawn_amount": [5000.0, 3000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 4000.0],
            "rwa_final": [4050.0, 1920.0, 1400.0],
            "risk_weight": [0.70, 0.60, 0.30],
            "irb_pd_floored": [0.005, 0.01, 0.003],
            "irb_lgd_floored": [0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 20.0],
            "irb_expected_loss": [12.375, 13.5, 1.8],
            "irb_capital_k": [0.056, 0.048, 0.024],
            "scra_provision_amount": [10.0, 5.0, 1.0],
            "gcra_provision_amount": [5.0, 5.0, 1.5],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_V"],
            # Post-model adjustment columns (from IRB calculator)
            "rwa_pre_adjustments": [3850.0, 1800.0, 1200.0],
            "post_model_adjustment_rwa": [192.5, 90.0, 60.0],
            "mortgage_rw_floor_adjustment": [0.0, 0.0, 100.0],
            "unrecognised_exposure_adjustment": [7.7, 30.0, 40.0],
            # EL adjustments
            "el_pre_adjustment": [12.375, 13.5, 1.8],
            "post_model_adjustment_el": [0.62, 0.675, 0.09],
            "el_after_adjustment": [12.995, 14.175, 1.89],
        }
    )


class TestPostModelAdjustments:
    """Task 3F: Post-model adjustments (Basel 3.1 OF 08.01 cols 0251-0254, 0280-0282).

    Why: PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require firms to report
    the RWEA waterfall showing the impact of post-model adjustments on IRB
    results. These columns enable supervisors to assess whether PMAs are
    adequate and whether modelled risk weights adequately capture risk.
    """

    def test_b31_col_0251_rwa_pre_adjustments(self) -> None:
        """Col 0251: RWEA pre adjustments equals sum of rwa_pre_adjustments."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0251"][0] == pytest.approx(3850.0 + 1800.0)

    def test_b31_col_0252_general_pma(self) -> None:
        """Col 0252: General PMA equals sum of post_model_adjustment_rwa."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0252"][0] == pytest.approx(192.5 + 90.0)

    def test_b31_col_0253_mortgage_floor(self) -> None:
        """Col 0253: Mortgage RW floor adjustment for mortgage class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        mtg = bundle.c08_01.get("retail_mortgage")
        if mtg is not None:
            total = mtg.filter(pl.col("row_ref") == "0010")
            assert total["0253"][0] == pytest.approx(100.0)

    def test_b31_col_0254_unrecognised(self) -> None:
        """Col 0254: Unrecognised exposure adjustment."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0254"][0] == pytest.approx(7.7 + 30.0)

    def test_b31_col_0280_el_pre_adjustment(self) -> None:
        """Col 0280: EL pre-adjustment equals sum of el_pre_adjustment."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0280"][0] == pytest.approx(12.375 + 13.5)

    def test_b31_col_0281_el_pma(self) -> None:
        """Col 0281: EL PMA equals sum of post_model_adjustment_el."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0281"][0] == pytest.approx(0.62 + 0.675)

    def test_b31_col_0282_el_after_adjustment(self) -> None:
        """Col 0282: EL after adjustment equals sum of el_after_adjustment."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0282"][0] == pytest.approx(12.995 + 14.175)

    def test_crr_no_pma_columns(self) -> None:
        """CRR framework does not have PMA columns 0251-0254."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert "0251" not in total.columns
        assert "0252" not in total.columns
        assert "0253" not in total.columns
        assert "0254" not in total.columns

    def test_without_pma_columns_returns_none(self) -> None:
        """Without PMA columns in pipeline data, COREP cols are None."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="BASEL_3_1")
        corp = bundle.c08_01.get("corporate")
        if corp is not None:
            total = corp.filter(pl.col("row_ref") == "0010")
            if "0251" in total.columns:
                assert total["0251"][0] is None

    def test_corporate_zero_mortgage_floor(self) -> None:
        """Corporate class should have zero mortgage floor adjustment."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_pma(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0253"][0] == pytest.approx(0.0)


# =============================================================================
# DOUBLE DEFAULT TREATMENT — Task 3E
# =============================================================================


def _irb_results_with_double_default() -> pl.LazyFrame:
    """IRB results with double default tracking columns for C 08.01 col 0220.

    Why: CRR Art. 153(3) requires reporting of unfunded credit protection
    subject to double default treatment. Col 0220 shows the guaranteed amount
    where the DD formula was used instead of standard substitution.

    Two corporate exposures:
    - IRB_DD_1: DD-eligible (guaranteed by institution, A-IRB, has DD protection)
    - IRB_DD_2: Not DD-eligible (no guarantee)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB_DD_1", "IRB_DD_2"],
            "approach_applied": ["advanced_irb", "advanced_irb"],
            "exposure_class": ["corporate", "corporate"],
            "drawn_amount": [5000.0, 3000.0],
            "undrawn_amount": [1000.0, 0.0],
            "ead_final": [5500.0, 3000.0],
            "rwa_final": [2750.0, 1800.0],
            "risk_weight": [0.50, 0.60],
            "irb_pd_floored": [0.02, 0.01],
            "irb_lgd_floored": [0.45, 0.45],
            "irb_maturity_m": [2.5, 3.0],
            "irb_expected_loss": [49.5, 13.5],
            "irb_capital_k": [0.04, 0.048],
            "provision_held": [50.0, 10.0],
            "el_shortfall": [0.0, 3.5],
            "el_excess": [0.5, 0.0],
            "scra_provision_amount": [10.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0],
            "counterparty_reference": ["CP_DD1", "CP_DD2"],
            # Double default tracking columns
            "is_double_default_eligible": [True, False],
            "double_default_unfunded_protection": [3000.0, 0.0],
            "irb_lgd_double_default": [0.45, None],
            "guaranteed_portion": [3000.0, 0.0],
            "unguaranteed_portion": [2500.0, 3000.0],
        }
    )


class TestDoubleDefaultCOREP:
    """Task 3E: Double default treatment in COREP C 08.01 col 0220.

    Why: CRR Art. 153(3) allows firms with A-IRB permission to recognise
    double default effects, reducing capital for guaranteed corporate exposures
    where the joint default probability is low. Col 0220 reports the unfunded
    protection amount subject to this treatment, enabling supervisory review
    of DD usage and risk concentration.
    """

    def test_crr_col_0220_populated(self) -> None:
        """CRR C 08.01 col 0220 reports DD unfunded protection amount."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # IRB_DD_1 has 3000 DD unfunded protection, IRB_DD_2 has 0
        assert total["0220"][0] == pytest.approx(3000.0)

    def test_crr_col_0220_zero_when_no_dd(self) -> None:
        """CRR C 08.01 col 0220 is zero when no DD exposures."""
        gen = COREPGenerator()
        # Use plain IRB results (no DD columns)
        bundle = gen.generate_from_lazyframe(_irb_results(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Without DD column, should be None
        assert total["0220"][0] is None

    def test_b31_no_col_0220(self) -> None:
        """Basel 3.1 OF 08.01 does not have col 0220 (DD removed)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_double_default(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert "0220" not in total.columns

    def test_crr_col_0220_institution_class(self) -> None:
        """Col 0220 for institution class with no DD → None."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        inst = bundle.c08_01.get("institution")
        # No institution exposures in fixture → class absent or empty
        if inst is not None:
            total = inst.filter(pl.col("row_ref") == "0010")
            if len(total) > 0:
                # Institution exposures can't have DD (not corporate)
                assert total["0220"][0] is None or total["0220"][0] == pytest.approx(0.0)

    def test_dd_unfunded_included_in_total_guarantees(self) -> None:
        """DD unfunded is a subset of total unfunded protection."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_double_default(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        dd_amount = total["0220"][0]
        guar_amount = total["0150"][0] if "0150" in total.columns else None
        # DD unfunded should be <= total guarantees (DD is a subset of guarantee treatments)
        if dd_amount is not None and guar_amount is not None:
            assert dd_amount <= guar_amount + 0.01


# =============================================================================
# SECTION 3: CALCULATION APPROACHES
# =============================================================================


def _irb_results_with_slotting() -> pl.LazyFrame:
    """Synthetic IRB results with both PD/LGD model and slotting approaches.

    Corporate class: 2 F-IRB + 1 slotting = 3 rows
    - F-IRB corp: EAD 5500 + 3000 = 8500, RWA 3850 + 1800 = 5650
    - Slotting corp: EAD 2000, RWA 1600

    Institution class: 1 F-IRB row
    - F-IRB inst: EAD 2000, RWA 600

    Specialised lending class: 1 slotting row
    - Slotting SL: EAD 4000, RWA 2800
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_1",
                "IRB_CORP_2",
                "IRB_CORP_SLOT",
                "IRB_INST_1",
                "IRB_SL_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "slotting",
                "foundation_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "institution",
                "specialised_lending",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 2000.0, 4000.0],
            "undrawn_amount": [1000.0, 0.0, 0.0, 0.0, 0.0],
            "ead_final": [5500.0, 3000.0, 2000.0, 2000.0, 4000.0],
            "rwa_final": [3850.0, 1800.0, 1600.0, 600.0, 2800.0],
            "risk_weight": [0.70, 0.60, 0.80, 0.30, 0.70],
            "irb_pd_floored": [0.005, 0.01, None, 0.002, None],
            "irb_lgd_floored": [0.45, 0.45, None, 0.45, None],
            "irb_maturity_m": [2.5, 3.0, None, 1.5, None],
            "irb_expected_loss": [12.375, 13.5, 0.0, 1.8, 0.0],
            "irb_capital_k": [0.056, 0.048, None, 0.024, None],
            "provision_held": [15.0, 10.0, 5.0, 3.0, 8.0],
            "el_shortfall": [0.0, 3.5, 0.0, 0.0, 0.0],
            "el_excess": [2.625, 0.0, 0.0, 1.2, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 2.0, 5.0],
            "gcra_provision_amount": [5.0, 5.0, 2.0, 1.0, 3.0],
            "counterparty_reference": ["CP_X", "CP_Y", "CP_Z", "CP_W", "CP_V"],
        }
    )


def _irb_results_b31_unrated_corporates() -> pl.LazyFrame:
    """Synthetic B31 IRB results for testing unrated corporates (rows 0190/0200).

    Corporate class: 4 rows — 2 rated (sa_cqs present), 2 unrated (sa_cqs null)
    Of the 2 unrated: 1 investment grade, 1 non-investment grade
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "IRB_CORP_RATED_1",
                "IRB_CORP_RATED_2",
                "IRB_CORP_UNRATED_IG",
                "IRB_CORP_UNRATED_NIG",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [5000.0, 3000.0, 2000.0, 1000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [5000.0, 3000.0, 2000.0, 1000.0],
            "rwa_final": [3500.0, 2100.0, 1000.0, 800.0],
            "risk_weight": [0.70, 0.70, 0.50, 0.80],
            "irb_pd_floored": [0.005, 0.01, 0.003, 0.02],
            "irb_lgd_floored": [0.45, 0.45, 0.45, 0.45],
            "irb_maturity_m": [2.5, 2.5, 2.5, 2.5],
            "irb_expected_loss": [11.25, 13.5, 2.7, 9.0],
            "irb_capital_k": [0.056, 0.056, 0.04, 0.064],
            "provision_held": [15.0, 10.0, 5.0, 8.0],
            "el_shortfall": [0.0, 0.0, 0.0, 0.0],
            "el_excess": [3.75, 0.0, 2.3, 0.0],
            "scra_provision_amount": [10.0, 5.0, 3.0, 4.0],
            "gcra_provision_amount": [5.0, 5.0, 2.0, 4.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [2, 3, None, None],
            "cp_is_investment_grade": [None, None, True, False],
        }
    )


def _get_section3_row(df: pl.DataFrame, row_ref: str) -> pl.DataFrame:
    """Get a Section 3 row by row_ref from a per-class DataFrame."""
    return df.filter(pl.col("row_ref") == row_ref)


class TestSection3CalculationApproaches:
    """Tests for C 08.01 Section 3 — Calculation Approaches.

    Section 3 splits the total IRB exposure by calculation method:
    row 0070 (PD/LGD model) vs row 0080 (slotting), with additional
    sub-portfolio rows for free deliveries, purchased receivables,
    unrated corporates, and investment grade corporates.

    Why: Regulators use Section 3 to verify that exposures are correctly
    allocated between calculation approaches (Art. 142-191). An entirely
    null Section 3 masks whether the institution correctly segregates
    model-based and slotting exposures.
    """

    # --- Row 0070: Obligor grades/pools (F-IRB + A-IRB) ---

    def test_row_0070_populated_for_firb_airb(self) -> None:
        """Row 0070 is populated with F-IRB/A-IRB exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        assert len(row) == 1
        # F-IRB corporate EAD: 5500 + 3000 = 8500 (excludes slotting 2000)
        assert row["0110"][0] == pytest.approx(8500.0)

    def test_row_0070_ead_excludes_slotting(self) -> None:
        """Row 0070 EAD excludes slotting rows (those go to row 0080)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total_ead = _get_total_row(corp)["0110"][0]
        row_0070_ead = _get_section3_row(corp, "0070")["0110"][0]
        row_0080_ead = _get_section3_row(corp, "0080")["0110"][0]
        # 0070 + 0080 should equal total
        assert row_0070_ead + (row_0080_ead or 0.0) == pytest.approx(total_ead)

    def test_row_0070_rwea_correct(self) -> None:
        """Row 0070 RWEA sums F-IRB/A-IRB rows only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB corporate RWA: 3850 + 1800 = 5650 (excludes slotting 1600)
        assert row["0260"][0] == pytest.approx(5650.0)

    def test_row_0070_weighted_average_pd(self) -> None:
        """Row 0070 PD is EAD-weighted average of F-IRB/A-IRB exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # PD: (0.005*5500 + 0.01*3000) / (5500+3000) = 57.5/8500
        expected_pd = (0.005 * 5500 + 0.01 * 3000) / 8500
        assert row["0010"][0] == pytest.approx(expected_pd, rel=1e-6)

    def test_row_0070_obligor_count(self) -> None:
        """Row 0070 obligor count covers F-IRB/A-IRB counterparties only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB corporates have 2 unique counterparties: CP_X, CP_Y
        assert row["0300"][0] == pytest.approx(2.0)

    def test_row_0070_institution_class(self) -> None:
        """Row 0070 works for institution class (all F-IRB, no slotting)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        inst = bundle.c08_01["institution"]
        row = _get_section3_row(inst, "0070")
        assert row["0110"][0] == pytest.approx(2000.0)

    # --- Row 0080: Slotting approach ---

    def test_row_0080_populated_for_slotting(self) -> None:
        """Row 0080 is populated with slotting exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0080")
        assert len(row) == 1
        # Slotting corporate EAD: 2000
        assert row["0110"][0] == pytest.approx(2000.0)

    def test_row_0080_rwea_correct(self) -> None:
        """Row 0080 RWEA sums slotting rows only."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0080")
        # Slotting corporate RWA: 1600
        assert row["0260"][0] == pytest.approx(1600.0)

    def test_row_0080_sl_class_all_slotting(self) -> None:
        """Specialised lending class has all EAD in row 0080 (slotting)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        sl = bundle.c08_01["specialised_lending"]
        row_0080 = _get_section3_row(sl, "0080")
        assert row_0080["0110"][0] == pytest.approx(4000.0)
        assert row_0080["0260"][0] == pytest.approx(2800.0)

    def test_row_0080_null_when_no_slotting_in_class(self) -> None:
        """Row 0080 is null when the class has no slotting exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        inst = bundle.c08_01["institution"]
        row = _get_section3_row(inst, "0080")
        assert row["0110"][0] is None

    def test_row_0070_null_when_no_model_based_in_class(self) -> None:
        """Row 0070 is null when the class has only slotting exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        sl = bundle.c08_01["specialised_lending"]
        row_0070 = _get_section3_row(sl, "0070")
        assert row_0070["0110"][0] is None

    # --- Rows 0070 + 0080 additive integrity ---

    def test_section3_ead_adds_to_total(self) -> None:
        """Row 0070 EAD + row 0080 EAD = total row 0010 EAD (within class)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total = _get_total_row(corp)["0110"][0]
        r70 = _get_section3_row(corp, "0070")["0110"][0] or 0.0
        r80 = _get_section3_row(corp, "0080")["0110"][0] or 0.0
        assert r70 + r80 == pytest.approx(total)

    def test_section3_rwea_adds_to_total(self) -> None:
        """Row 0070 RWEA + row 0080 RWEA = total row 0010 RWEA (within class)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        total = _get_total_row(corp)["0260"][0]
        r70 = _get_section3_row(corp, "0070")["0260"][0] or 0.0
        r80 = _get_section3_row(corp, "0080")["0260"][0] or 0.0
        assert r70 + r80 == pytest.approx(total)

    # --- Row 0160: Alternative RE treatment (CRR only) ---

    def test_row_0160_null_no_pipeline_flag(self) -> None:
        """Row 0160 is null — requires pipeline flag not yet available."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0160")
        assert row["0110"][0] is None

    # --- Row 0170: Free deliveries ---

    def test_row_0170_null_no_pipeline_data(self) -> None:
        """Row 0170 is null — free delivery tracking not yet in pipeline."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0170")
        assert row["0110"][0] is None

    # --- Row 0180: Dilution risk ---

    def test_row_0180_null_no_dilution_data(self) -> None:
        """Row 0180 is null — dilution risk tracking not yet in pipeline."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0180")
        assert row["0110"][0] is None

    # --- B31 Row 0190: Corporates without ECAI ---

    def test_row_0190_b31_unrated_corporates(self) -> None:
        """Row 0190 is populated for unrated corporates under Basel 3.1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0190")
        # Unrated corporates: EAD 2000 + 1000 = 3000
        assert row["0110"][0] == pytest.approx(3000.0)

    def test_row_0190_excludes_rated(self) -> None:
        """Row 0190 excludes corporates that have an ECAI rating."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        total_ead = _get_total_row(corp)["0110"][0]
        row_0190_ead = _get_section3_row(corp, "0190")["0110"][0]
        # Total 11000, rated 8000, unrated 3000
        assert row_0190_ead < total_ead
        assert row_0190_ead == pytest.approx(3000.0)

    def test_row_0190_not_present_in_crr(self) -> None:
        """Row 0190 does not exist in CRR template (B31 only)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="CRR"
        )
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0190" not in row_refs

    # --- B31 Row 0200: Investment grade ---

    def test_row_0200_b31_investment_grade(self) -> None:
        """Row 0200 is populated for investment grade unrated corporates."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0200")
        # Investment grade unrated: EAD 2000 only (the IG flagged one)
        assert row["0110"][0] == pytest.approx(2000.0)

    def test_row_0200_subset_of_0190(self) -> None:
        """Row 0200 EAD is <= row 0190 EAD (investment grade is a subset)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        ead_0190 = _get_section3_row(corp, "0190")["0110"][0] or 0.0
        ead_0200 = _get_section3_row(corp, "0200")["0110"][0] or 0.0
        assert ead_0200 <= ead_0190 + 0.01

    def test_row_0200_not_present_in_crr(self) -> None:
        """Row 0200 does not exist in CRR template (B31 only)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_b31_unrated_corporates(), framework="CRR"
        )
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0200" not in row_refs

    # --- Edge cases ---

    def test_section3_with_basic_irb_data(self) -> None:
        """Section 3 works with basic IRB data (no slotting column ambiguity)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())
        corp = bundle.c08_01["corporate"]
        row_0070 = _get_section3_row(corp, "0070")
        # All basic IRB data is F-IRB or A-IRB, so 0070 should match total
        total = _get_total_row(corp)["0110"][0]
        assert row_0070["0110"][0] == pytest.approx(total)

    def test_section3_row_0080_null_when_no_slotting(self) -> None:
        """Row 0080 is null when input has no slotting approach."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results())
        corp = bundle.c08_01["corporate"]
        row_0080 = _get_section3_row(corp, "0080")
        assert row_0080["0110"][0] is None

    def test_section3_provisions_column(self) -> None:
        """Row 0070 provisions (col 0290) sums correctly for sub-rows."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting())
        corp = bundle.c08_01["corporate"]
        row = _get_section3_row(corp, "0070")
        # F-IRB provisions: (10+5) + (5+5) = 25
        assert row["0290"][0] == pytest.approx(25.0)

    def test_b31_section3_has_0175_row(self) -> None:
        """B31 template includes row 0175 (Purchased receivables)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_slotting(), framework="BASEL_3_1"
        )
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0175" in row_refs

    def test_crr_section3_has_0160_row(self) -> None:
        """CRR template includes row 0160 (Alternative RE treatment)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_slotting(), framework="CRR"
        )
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0160" in row_refs


# =============================================================================
# OF 02.01 — OUTPUT FLOOR COMPARISON (Basel 3.1 only)
# =============================================================================


def _b31_results_with_floor() -> pl.LazyFrame:
    """Results LazyFrame with rwa_pre_floor and sa_rwa columns (floor applied)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "standardised",
                "advanced_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution", "corporate"],
            "ead_final": [1000.0, 2000.0, 500.0, 1500.0],
            "risk_weight": [0.5, 0.75, 0.2, 0.6],
            "rwa_final": [500.0, 1500.0, 100.0, 900.0],
            "rwa_pre_floor": [500.0, 1500.0, 100.0, 900.0],
            "sa_rwa": [700.0, 1400.0, 100.0, 1050.0],
        }
    )


def _b31_results_floor_binding() -> pl.LazyFrame:
    """Results where modelled RWA < SA RWA (floor is binding)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "ead_final": [1000.0, 2000.0],
            "risk_weight": [0.3, 0.4],
            "rwa_final": [300.0, 800.0],
            "rwa_pre_floor": [300.0, 800.0],
            "sa_rwa": [600.0, 1600.0],
        }
    )


def _sa_only_results_with_floor_cols() -> pl.LazyFrame:
    """SA-only results that happen to have floor columns (modelled = SA)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "institution"],
            "ead_final": [1000.0, 500.0],
            "risk_weight": [1.0, 0.2],
            "rwa_final": [1000.0, 100.0],
            "rwa_pre_floor": [1000.0, 100.0],
            "sa_rwa": [1000.0, 100.0],
        }
    )


class TestOF0201TemplateDefinitions:
    """Template structure definitions for OF 02.01."""

    def test_column_count(self) -> None:
        """OF 02.01 has exactly 4 columns."""
        assert len(OF_02_01_COLUMNS) == 4

    def test_column_refs(self) -> None:
        """Column refs are 0010, 0020, 0030, 0040."""
        assert OF_02_01_COLUMN_REFS == ["0010", "0020", "0030", "0040"]

    def test_column_names(self) -> None:
        """Columns have correct regulatory names."""
        names = [c.name for c in OF_02_01_COLUMNS]
        assert "modelled approaches" in names[0].lower()
        assert "standardised approaches" in names[1].lower()
        assert "U-TREA" in names[2]
        assert "S-TREA" in names[3]

    def test_column_groups(self) -> None:
        """First two columns are Comparison, last two are Output Floor."""
        groups = [c.group for c in OF_02_01_COLUMNS]
        assert groups == ["Comparison", "Comparison", "Output Floor", "Output Floor"]

    def test_row_count(self) -> None:
        """OF 02.01 has exactly 8 rows (risk types) in 1 section."""
        assert len(OF_02_01_ROW_SECTIONS) == 1
        assert len(OF_02_01_ROW_SECTIONS[0].rows) == 8

    def test_row_refs(self) -> None:
        """Row refs are 0010-0080."""
        refs = [r.ref for r in OF_02_01_ROW_SECTIONS[0].rows]
        assert refs == ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]

    def test_credit_risk_row_name(self) -> None:
        """First row is 'Credit risk (excluding CCR)'."""
        assert OF_02_01_ROW_SECTIONS[0].rows[0].name == "Credit risk (excluding CCR)"

    def test_total_row_name(self) -> None:
        """Last row is 'Total'."""
        assert OF_02_01_ROW_SECTIONS[0].rows[-1].name == "Total"

    def test_section_name(self) -> None:
        """Section is named 'Risk Type Breakdown'."""
        assert OF_02_01_ROW_SECTIONS[0].name == "Risk Type Breakdown"


class TestOF0201Generation:
    """OF 02.01 generation from pipeline results."""

    def test_generated_under_b31(self) -> None:
        """OF 02.01 is generated when framework is BASEL_3_1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        assert bundle.of_02_01 is not None

    def test_none_under_crr(self) -> None:
        """OF 02.01 is None when framework is CRR (no output floor)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="CRR"
        )
        assert bundle.of_02_01 is None

    def test_none_without_floor_columns(self) -> None:
        """OF 02.01 is None when rwa_pre_floor/sa_rwa columns are absent."""
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
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None

    def test_error_logged_when_skipped(self) -> None:
        """Error message added when OF 02.01 is skipped (missing columns)."""
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
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert any("OF 02.01 skipped" in e for e in bundle.errors)

    def test_is_dataframe(self) -> None:
        """OF 02.01 output is a Polars DataFrame."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        assert isinstance(bundle.of_02_01, pl.DataFrame)

    def test_row_count(self) -> None:
        """OF 02.01 has 8 rows (one per risk type)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        assert len(bundle.of_02_01) == 8

    def test_column_structure(self) -> None:
        """DataFrame has row_ref, row_name, and 4 data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cols = set(bundle.of_02_01.columns)
        assert "row_ref" in cols
        assert "row_name" in cols
        assert "0010" in cols
        assert "0020" in cols
        assert "0030" in cols
        assert "0040" in cols


class TestOF0201CreditRiskRow:
    """OF 02.01 row 0010 — Credit risk (excluding CCR)."""

    def test_modelled_rwa(self) -> None:
        """Col 0010 = sum of rwa_pre_floor for all exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=500, E2=1500, E3=100, E4=900 → 3000
        assert cr_row["0010"][0] == pytest.approx(3000.0)

    def test_sa_rwa(self) -> None:
        """Col 0020 = sum of sa_rwa for all exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=700, E2=1400, E3=100, E4=1050 → 3250
        assert cr_row["0020"][0] == pytest.approx(3250.0)

    def test_u_trea_equals_modelled(self) -> None:
        """Col 0030 (U-TREA) equals col 0010 for credit-risk-only calculator."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0030"][0] == cr_row["0010"][0]

    def test_s_trea_equals_sa(self) -> None:
        """Col 0040 (S-TREA) equals col 0020 for credit-risk-only calculator."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0040"][0] == cr_row["0020"][0]

    def test_floor_binding_scenario(self) -> None:
        """Floor binding: modelled < SA (modelled=1100 < SA=2200)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_floor_binding(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(1100.0)  # 300+800
        assert cr_row["0020"][0] == pytest.approx(2200.0)  # 600+1600

    def test_sa_only_portfolio(self) -> None:
        """SA-only portfolio: modelled = SA (no IRB benefit)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_only_results_with_floor_cols(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(1100.0)  # 1000+100
        assert cr_row["0020"][0] == pytest.approx(1100.0)  # same


class TestOF0201TotalRow:
    """OF 02.01 row 0080 — Total."""

    def test_total_equals_credit_risk(self) -> None:
        """Total row equals credit risk row (credit-risk-only calculator)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert total_row[col_ref][0] == cr_row[col_ref][0]

    def test_total_modelled_rwa(self) -> None:
        """Total row col 0010 matches credit risk sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        assert total_row["0010"][0] == pytest.approx(3000.0)

    def test_total_row_name(self) -> None:
        """Total row is named 'Total'."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        assert total_row["row_name"][0] == "Total"


class TestOF0201NullRows:
    """OF 02.01 rows 0020-0070 — out-of-scope risk types (null)."""

    @pytest.mark.parametrize(
        "row_ref,row_name",
        [
            ("0020", "Counterparty credit risk"),
            ("0030", "Credit valuation adjustment risk"),
            ("0040", "Securitisation positions in the non-trading book"),
            ("0050", "Market risk"),
            ("0060", "Operational risk"),
            ("0070", "Other"),
        ],
    )
    def test_out_of_scope_row_is_null(self, row_ref: str, row_name: str) -> None:
        """Out-of-scope risk types have null values in all data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        row = bundle.of_02_01.filter(pl.col("row_ref") == row_ref)
        assert len(row) == 1
        assert row["row_name"][0] == row_name
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert row[col_ref][0] is None

    def test_null_rows_present(self) -> None:
        """All 6 out-of-scope rows are present."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        null_refs = {"0020", "0030", "0040", "0050", "0060", "0070"}
        actual_refs = set(bundle.of_02_01["row_ref"].to_list())
        assert null_refs.issubset(actual_refs)


class TestOF0201EdgeCases:
    """Edge cases and data type verification for OF 02.01."""

    def test_empty_results(self) -> None:
        """Empty LazyFrame with floor columns produces zero-valued OF 02.01."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
                "rwa_pre_floor": pl.Float64,
                "sa_rwa": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(0.0)
        assert cr_row["0020"][0] == pytest.approx(0.0)

    def test_null_rwa_values_treated_as_zero(self) -> None:
        """Null rwa_pre_floor/sa_rwa values are treated as 0."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, None],
                "rwa_pre_floor": [500.0, None],
                "sa_rwa": [None, 1400.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(500.0)
        assert cr_row["0020"][0] == pytest.approx(1400.0)

    def test_data_columns_are_float64(self) -> None:
        """All 4 data columns are Float64 type."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert bundle.of_02_01[col_ref].dtype == pl.Float64

    def test_row_ref_and_name_are_string(self) -> None:
        """row_ref and row_name columns are String type."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        assert bundle.of_02_01["row_ref"].dtype == pl.String
        assert bundle.of_02_01["row_name"].dtype == pl.String

    def test_no_errors_on_success(self) -> None:
        """No OF 02.01 errors when generation succeeds."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        assert not any("OF 02.01" in e for e in bundle.errors)

    def test_bundle_field_none_by_default(self) -> None:
        """COREPTemplateBundle.of_02_01 defaults to None."""
        bundle = COREPTemplateBundle(
            c07_00={}, c08_01={}, c08_02={}
        )
        assert bundle.of_02_01 is None

    def test_large_rwa_values(self) -> None:
        """OF 02.01 handles large RWA values without precision loss."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1e12],
                "rwa_final": [5e11],
                "rwa_pre_floor": [5e11],
                "sa_rwa": [7e11],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(5e11)
        assert cr_row["0020"][0] == pytest.approx(7e11)

    def test_row_order_preserved(self) -> None:
        """Rows are in the correct order: 0010, 0020, ..., 0080."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _b31_results_with_floor(), framework="BASEL_3_1"
        )
        refs = bundle.of_02_01["row_ref"].to_list()
        assert refs == ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]

    def test_only_rwa_pre_floor_missing(self) -> None:
        """OF 02.01 is None when only rwa_pre_floor is missing."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "sa_rwa": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None

    def test_only_sa_rwa_missing(self) -> None:
        """OF 02.01 is None when only sa_rwa is missing."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "rwa_pre_floor": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None


# =============================================================================
# C 08.03 / OF 08.03 — IRB PD Range Tests
# =============================================================================


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
            "irb_pd_floored": [0.002, 0.005, 0.01, 0.03, 1.0],
            "irb_pd_original": [0.001, 0.004, 0.01, 0.03, 1.0],
            "irb_lgd_floored": [0.45, 0.45, 0.35, 0.40, 0.45],
            "irb_maturity_m": [2.5, 3.0, 2.0, 4.0, 1.0],
            "irb_expected_loss": [4.95, 6.75, 7.7, 12.0, 225.0],
            "provision_held": [5.0, 8.0, 6.0, 15.0, 200.0],
            "scra_provision_amount": [3.0, 4.0, 3.0, 8.0, 100.0],
            "gcra_provision_amount": [2.0, 4.0, 3.0, 7.0, 100.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "ccf_applied": [0.5, 0.0, 0.4, 0.0, 0.0],
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
            "irb_pd_floored": [0.005, 0.01, 0.002, 0.003],
            "irb_lgd_floored": [0.45, 0.45, 0.45, 0.15],
            "irb_maturity_m": [2.5, 3.0, 1.5, 20.0],
            "irb_expected_loss": [12.375, 13.5, 1.8, 1.8],
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
        assert C08_03_PD_RANGES[0][0] == 0.0
        # Last range upper bound is infinity (captures 100% default)
        assert C08_03_PD_RANGES[-1][1] == float("inf")
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

        assert C08_03_COLUMN_REFS == [c.ref for c in CRR_C08_03_COLUMNS]

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
                "irb_pd_floored": [0.005, 0.0],
                "irb_lgd_floored": [0.45, 0.0],
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

        E1 has irb_pd_original=0.001 (0.10%) which falls in '0.10 to < 0.15%'
        bucket (row 0040), even though irb_pd_floored=0.002 (0.20%) would
        fall in '0.20 to < 0.25%' (row 0060).
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_pd_range_results(), framework="BASEL_3_1"
        )
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
        bundle = gen.generate_from_lazyframe(
            _irb_pd_range_results(), framework="BASEL_3_1"
        )
        corp = bundle.c08_03["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        # E1: post-floor PD=0.002
        assert row["0050"][0] == pytest.approx(0.002, rel=1e-6)

    def test_crr_uses_floored_pd_for_allocation(self) -> None:
        """CRR C 08.03 uses floored PD for both allocation and reporting.

        E1 has irb_pd_floored=0.002 (0.20%) → '0.20 to < 0.25%' bucket (row 0060).
        """
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_pd_range_results(), framework="CRR"
        )
        corp = bundle.c08_03["corporate"]
        # E1: pd_floored=0.002 → "0.20 to < 0.25%" (row 0060)
        row = corp.filter(pl.col("row_ref") == "0060")
        assert len(row) == 1

    def test_b31_has_11_columns(self) -> None:
        """Basel 3.1 C 08.03 still produces 11 data columns + 2 metadata."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_pd_range_results(), framework="BASEL_3_1"
        )
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
                "irb_pd_floored": [0.01],
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
                "irb_pd_floored": [0.005, None],
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
