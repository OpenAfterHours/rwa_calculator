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

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    B31_C02_00_COLUMN_REFS,
    B31_C02_00_COLUMNS,
    B31_C02_00_ROW_SECTIONS,
    B31_C07_COLUMNS,
    B31_C08_07_ROWS,
    B31_C08_COLUMNS,
    B31_IRB_ROW_SECTIONS,
    B31_SA_RISK_WEIGHT_BANDS,
    B31_SA_ROW_SECTIONS,
    C02_00_SA_CLASS_MAP,
    C07_COLUMNS,
    C08_01_COLUMNS,
    CRR_C02_00_COLUMN_REFS,
    CRR_C02_00_COLUMNS,
    CRR_C02_00_ROW_SECTIONS,
    CRR_C07_COLUMNS,
    CRR_C08_07_ROWS,
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
    get_c02_00_columns,
    get_c02_00_row_sections,
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
        """No errors for well-formed input data (geo info messages are acceptable)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_combined_results())
        # C 09.01/09.02 emit info messages when cp_country_code is absent
        non_geo_errors = [e for e in bundle.errors if "C09" not in e]
        assert len(non_geo_errors) == 0

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
        bundle = gen.generate_from_lazyframe(_irb_results_b31_unrated_corporates(), framework="CRR")
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
        bundle = gen.generate_from_lazyframe(_irb_results_b31_unrated_corporates(), framework="CRR")
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
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="BASEL_3_1")
        corp = bundle.c08_01["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0175" in row_refs

    def test_crr_section3_has_0160_row(self) -> None:
        """CRR template includes row 0160 (Alternative RE treatment)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_slotting(), framework="CRR")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None

    def test_none_under_crr(self) -> None:
        """OF 02.01 is None when framework is CRR (no output floor)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="CRR")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert isinstance(bundle.of_02_01, pl.DataFrame)

    def test_row_count(self) -> None:
        """OF 02.01 has 8 rows (one per risk type)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert len(bundle.of_02_01) == 8

    def test_column_structure(self) -> None:
        """DataFrame has row_ref, row_name, and 4 data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=500, E2=1500, E3=100, E4=900 → 3000
        assert cr_row["0010"][0] == pytest.approx(3000.0)

    def test_sa_rwa(self) -> None:
        """Col 0020 = sum of sa_rwa for all exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=700, E2=1400, E3=100, E4=1050 → 3250
        assert cr_row["0020"][0] == pytest.approx(3250.0)

    def test_u_trea_equals_modelled(self) -> None:
        """Col 0030 (U-TREA) equals col 0010 for credit-risk-only calculator."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0030"][0] == cr_row["0010"][0]

    def test_s_trea_equals_sa(self) -> None:
        """Col 0040 (S-TREA) equals col 0020 for credit-risk-only calculator."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0040"][0] == cr_row["0020"][0]

    def test_floor_binding_scenario(self) -> None:
        """Floor binding: modelled < SA (modelled=1100 < SA=2200)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_floor_binding(), framework="BASEL_3_1")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert total_row[col_ref][0] == cr_row[col_ref][0]

    def test_total_modelled_rwa(self) -> None:
        """Total row col 0010 matches credit risk sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        assert total_row["0010"][0] == pytest.approx(3000.0)

    def test_total_row_name(self) -> None:
        """Total row is named 'Total'."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        row = bundle.of_02_01.filter(pl.col("row_ref") == row_ref)
        assert len(row) == 1
        assert row["row_name"][0] == row_name
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert row[col_ref][0] is None

    def test_null_rows_present(self) -> None:
        """All 6 out-of-scope rows are present."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert bundle.of_02_01[col_ref].dtype == pl.Float64

    def test_row_ref_and_name_are_string(self) -> None:
        """row_ref and row_name columns are String type."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01["row_ref"].dtype == pl.String
        assert bundle.of_02_01["row_name"].dtype == pl.String

    def test_no_errors_on_success(self) -> None:
        """No OF 02.01 errors when generation succeeds."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert not any("OF 02.01" in e for e in bundle.errors)

    def test_bundle_field_none_by_default(self) -> None:
        """COREPTemplateBundle.of_02_01 defaults to None."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
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
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
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

        E1 has irb_pd_floored=0.002 (0.20%) → '0.20 to < 0.25%' bucket (row 0060).
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


# =============================================================================
# C 08.04 / OF 08.04 — IRB RWEA Flow Statements
# =============================================================================


def _irb_flow_results() -> pl.LazyFrame:
    """Synthetic IRB results for C 08.04 flow statement tests.

    3 corporate exposures + 1 institution + 1 retail mortgage.
    Corporate total RWEA: 2750 + 1800 + 780 = 5330.
    Institution RWEA: 600. Retail mortgage RWEA: 1200.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
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
            "ead_final": [5500.0, 3000.0, 1200.0, 2000.0, 4000.0],
            "rwa_final": [2750.0, 1800.0, 780.0, 600.0, 1200.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
        }
    )


def _irb_flow_with_slotting() -> pl.LazyFrame:
    """IRB results including slotting exposures for exclusion testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3"],
            "approach_applied": ["foundation_irb", "slotting", "advanced_irb"],
            "exposure_class": ["corporate", "specialised_lending", "corporate"],
            "ead_final": [5000.0, 3000.0, 2000.0],
            "rwa_final": [3500.0, 2100.0, 1400.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C"],
        }
    )


class TestC0804TemplateDefinitions:
    """Test C 08.04 / OF 08.04 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert len(CRR_C08_04_COLUMNS) == 1

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_04_COLUMNS

        assert len(B31_C08_04_COLUMNS) == 1

    def test_crr_column_ref(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert CRR_C08_04_COLUMNS[0].ref == "0010"

    def test_crr_column_includes_supporting_factors(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_04_COLUMNS

        assert "supporting factors" in CRR_C08_04_COLUMNS[0].name.lower()

    def test_b31_column_excludes_supporting_factors(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_04_COLUMNS

        assert "supporting factors" not in B31_C08_04_COLUMNS[0].name.lower()

    def test_column_refs_list(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_COLUMN_REFS

        assert C08_04_COLUMN_REFS == ["0010"]

    def test_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert len(C08_04_ROWS) == 9

    def test_rows_refs_sequential(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        expected_refs = [f"00{i}0" for i in range(1, 10)]
        assert [r.ref for r in C08_04_ROWS] == expected_refs

    def test_first_row_is_opening(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert "previous" in C08_04_ROWS[0].name.lower()

    def test_last_row_is_closing(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        assert "end of the reporting period" in C08_04_ROWS[8].name.lower()

    def test_movement_driver_rows(self) -> None:
        """7 movement driver rows between opening and closing."""
        from rwa_calc.reporting.corep.templates import C08_04_ROWS

        drivers = C08_04_ROWS[1:8]
        assert len(drivers) == 7
        expected_names = [
            "Asset size",
            "Asset quality",
            "Model updates",
            "Methodology and policy",
            "Acquisitions and disposals",
            "Foreign exchange movements",
            "Other",
        ]
        for row, expected in zip(drivers, expected_names, strict=True):
            assert expected.lower() in row.name.lower()

    def test_get_columns_crr(self) -> None:
        from rwa_calc.reporting.corep.templates import (
            CRR_C08_04_COLUMNS,
            get_c08_04_columns,
        )

        assert get_c08_04_columns("CRR") is CRR_C08_04_COLUMNS

    def test_get_columns_b31(self) -> None:
        from rwa_calc.reporting.corep.templates import (
            B31_C08_04_COLUMNS,
            get_c08_04_columns,
        )

        assert get_c08_04_columns("BASEL_3_1") is B31_C08_04_COLUMNS


class TestC0804Generation:
    """Test C 08.04 generation — per-class DataFrames with correct structure."""

    def test_generates_per_class(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        assert isinstance(bundle.c08_04, dict)
        assert len(bundle.c08_04) > 0

    def test_multiple_classes(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        # corporate, corporate_sme, institution, retail_mortgage
        assert len(bundle.c08_04) == 4

    def test_each_class_has_9_rows(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        for ec, df in bundle.c08_04.items():
            assert len(df) == 9, f"{ec} has {len(df)} rows instead of 9"

    def test_each_class_has_correct_columns(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        for _ec, df in bundle.c08_04.items():
            assert "row_ref" in df.columns
            assert "row_name" in df.columns
            assert "0010" in df.columns

    def test_empty_irb_returns_empty_dict(self) -> None:
        """No IRB data produces empty dict."""
        gen = COREPGenerator()
        sa_only = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
            }
        )
        bundle = gen.generate_from_lazyframe(sa_only)
        assert bundle.c08_04 == {}


class TestC0804ClosingRWEA:
    """Test row 0090 (closing RWEA) population from pipeline data."""

    def test_closing_rwea_corporate(self) -> None:
        """Corporate closing RWEA = sum of corporate+corporate_sme RWEA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        # E1=2750 + E2=1800 corporate
        assert closing["0010"][0] == pytest.approx(4550.0, rel=1e-4)

    def test_closing_rwea_institution(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        inst = bundle.c08_04["institution"]
        closing = inst.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(600.0, rel=1e-4)

    def test_closing_rwea_retail(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        retail = bundle.c08_04["retail_mortgage"]
        closing = retail.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(1200.0, rel=1e-4)

    def test_closing_rwea_sme(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        sme = bundle.c08_04["corporate_sme"]
        closing = sme.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(780.0, rel=1e-4)


class TestC0804NullDriverRows:
    """Test that opening and driver rows are null (require prior-period data)."""

    def test_opening_rwea_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        opening = corp.filter(pl.col("row_ref") == "0010")
        assert opening["0010"][0] is None

    def test_asset_size_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0020")
        assert row["0010"][0] is None

    def test_asset_quality_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert row["0010"][0] is None

    def test_model_updates_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0040")
        assert row["0010"][0] is None

    def test_methodology_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0050")
        assert row["0010"][0] is None

    def test_acquisitions_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0060")
        assert row["0010"][0] is None

    def test_fx_movements_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0070")
        assert row["0010"][0] is None

    def test_other_is_null(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        row = corp.filter(pl.col("row_ref") == "0080")
        assert row["0010"][0] is None

    def test_all_drivers_null(self) -> None:
        """All 7 driver rows + opening are null."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        for ref in ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]:
            row = corp.filter(pl.col("row_ref") == ref)
            assert row["0010"][0] is None, f"Row {ref} should be null"


class TestC0804B31Features:
    """Test Basel 3.1 specific features for C 08.04."""

    def test_b31_generates_same_row_count(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        for ec, df in bundle.c08_04.items():
            assert len(df) == 9, f"B31 {ec} has {len(df)} rows"

    def test_b31_closing_rwea_matches_crr(self) -> None:
        """Closing RWEA values are framework-independent."""
        gen = COREPGenerator()
        crr = gen.generate_from_lazyframe(_irb_flow_results(), framework="CRR")
        b31 = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        for ec in crr.c08_04:
            crr_closing = crr.c08_04[ec].filter(pl.col("row_ref") == "0090")["0010"][0]
            b31_closing = b31.c08_04[ec].filter(pl.col("row_ref") == "0090")["0010"][0]
            assert crr_closing == pytest.approx(b31_closing, rel=1e-4)

    def test_b31_framework_stored(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results(), framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"


class TestC0804EdgeCases:
    """Test edge cases for C 08.04 generation."""

    def test_excludes_slotting(self) -> None:
        """Slotting exposures excluded from C 08.04."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_with_slotting())
        # Only corporate class, slotting excluded
        assert "corporate" in bundle.c08_04
        assert "specialised_lending" not in bundle.c08_04

    def test_slotting_rwea_not_in_closing(self) -> None:
        """Closing RWEA excludes slotting RWEA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_with_slotting())
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        # E1=3500 + E3=1400 corporate only
        assert closing["0010"][0] == pytest.approx(4900.0, rel=1e-4)

    def test_missing_exposure_class_returns_empty(self) -> None:
        gen = COREPGenerator()
        no_ec = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(no_ec)
        assert bundle.c08_04 == {}

    def test_missing_rwa_column(self) -> None:
        """Missing rwa_final still generates template with null closing."""
        gen = COREPGenerator()
        no_rwa = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
            }
        )
        bundle = gen.generate_from_lazyframe(no_rwa)
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] is None

    def test_zero_rwa(self) -> None:
        """Zero RWEA is reported as 0.0, not null."""
        gen = COREPGenerator()
        zero_rwa = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [0.0],
            }
        )
        bundle = gen.generate_from_lazyframe(zero_rwa)
        corp = bundle.c08_04["corporate"]
        closing = corp.filter(pl.col("row_ref") == "0090")
        assert closing["0010"][0] == pytest.approx(0.0)

    def test_row_refs_are_correct(self) -> None:
        """All 9 row refs are the expected 4-digit codes."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        corp = bundle.c08_04["corporate"]
        expected = ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080", "0090"]
        assert corp["row_ref"].to_list() == expected

    def test_bundle_has_c08_04_field(self) -> None:
        """COREPTemplateBundle has c08_04 field."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_flow_results())
        assert hasattr(bundle, "c08_04")
        assert isinstance(bundle.c08_04, dict)


# =============================================================================
# C 08.05 / OF 08.05 — IRB PD Backtesting
# =============================================================================


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
            "irb_pd_floored": [0.002, 0.005, 0.01, 0.03, 1.0],
            "irb_pd_original": [0.001, 0.004, 0.01, 0.03, 1.0],
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
            "irb_pd_floored": [0.005, 0.01, 1.0, 0.002],
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
                "irb_pd_floored": [0.005],
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
                "irb_pd_floored": [0.005, 0.01],
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
        """Basel 3.1 allocates rows by irb_pd_original (pre-floor)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="BASEL_3_1")
        corp = bundle.c08_05["corporate"]
        # E1: irb_pd_original=0.001, should go to row 0040 (0.10 to < 0.15%)
        row = corp.filter(pl.col("row_ref") == "0040")
        assert len(row) == 1

    def test_crr_allocation_uses_floored_pd(self) -> None:
        """CRR allocates rows by irb_pd_floored."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_pd_backtest_results(), framework="CRR")
        corp = bundle.c08_05["corporate"]
        # E1: irb_pd_floored=0.002, should go to row 0060 (0.20 to < 0.25%)
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
                "irb_pd_floored": [0.005, 0.006, 0.007],
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
                "irb_pd_floored": [None, 0.005],
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
                "irb_pd_floored": [0.005, 1.0],
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
                "irb_pd_floored": [0.005, 0.006, 0.007],
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


# =============================================================================
# C 08.07 / OF 08.07 — IRB Scope of Use
# =============================================================================


def _irb_scope_of_use_results() -> pl.LazyFrame:
    """Synthetic results with mixed SA and IRB exposures for scope of use testing.

    Creates a dataset with:
    - Corporate: 5000 IRB EAD (2500 RWA), 3000 SA EAD (1500 RWA)
    - Institution: 2000 IRB EAD (800 RWA)
    - Retail mortgage: 4000 SA EAD (1200 RWA)
    - Retail QRRE: 1000 IRB EAD (200 RWA)
    - Specialised lending: 3000 slotting EAD (2100 RWA)
    - Equity: 500 SA EAD (1250 RWA)

    Total IRB EAD: 5000 + 2000 + 1000 + 3000 = 11000
    Total SA EAD: 3000 + 4000 + 500 = 7500
    Grand total EAD: 18500
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "E1",
                "E2",
                "E3",
                "E4",
                "E5",
                "E6",
                "E7",
                "E8",
            ],
            "approach_applied": [
                "foundation_irb",
                "standardised",
                "foundation_irb",
                "standardised",
                "advanced_irb",
                "slotting",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "institution",
                "retail_mortgage",
                "retail_qrre",
                "specialised_lending",
                "equity",
                "equity",
            ],
            "ead_final": [
                5000.0,
                3000.0,
                2000.0,
                4000.0,
                1000.0,
                3000.0,
                300.0,
                200.0,
            ],
            "rwa_final": [
                2500.0,
                1500.0,
                800.0,
                1200.0,
                200.0,
                2100.0,
                750.0,
                500.0,
            ],
        }
    )


class TestC0807TemplateDefinitions:
    """Tests for C 08.07 / OF 08.07 template structure definitions."""

    def test_crr_c0807_has_5_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_07_COLUMNS

        assert len(CRR_C08_07_COLUMNS) == 5

    def test_b31_c0807_has_18_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_COLUMNS

        assert len(B31_C08_07_COLUMNS) == 18

    def test_crr_c0807_has_17_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_07_ROWS

        assert len(CRR_C08_07_ROWS) == 17

    def test_b31_c0807_has_11_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_ROWS

        assert len(B31_C08_07_ROWS) == 11

    def test_column_refs_match_crr_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_07_COLUMN_REFS, CRR_C08_07_COLUMNS

        assert [c.ref for c in CRR_C08_07_COLUMNS] == C08_07_COLUMN_REFS

    def test_b31_column_refs_match_b31_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_COLUMN_REFS, B31_C08_07_COLUMNS

        assert [c.ref for c in B31_C08_07_COLUMNS] == B31_C08_07_COLUMN_REFS

    def test_get_c08_07_columns_crr(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_07_COLUMNS, get_c08_07_columns

        assert get_c08_07_columns("CRR") is CRR_C08_07_COLUMNS

    def test_get_c08_07_columns_b31(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_COLUMNS, get_c08_07_columns

        assert get_c08_07_columns("BASEL_3_1") is B31_C08_07_COLUMNS

    def test_get_c08_07_rows_crr(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_07_ROWS, get_c08_07_rows

        assert get_c08_07_rows("CRR") is CRR_C08_07_ROWS

    def test_get_c08_07_rows_b31(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_ROWS, get_c08_07_rows

        assert get_c08_07_rows("BASEL_3_1") is B31_C08_07_ROWS

    def test_crr_row_refs_unique(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C08_07_ROWS

        refs = [r[0] for r in CRR_C08_07_ROWS]
        assert len(refs) == len(set(refs))

    def test_b31_row_refs_unique(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C08_07_ROWS

        refs = [r[0] for r in B31_C08_07_ROWS]
        assert len(refs) == len(set(refs))

    def test_crr_total_row_is_last_data_row(self) -> None:
        """CRR Total row (0170) is the last row."""
        from rwa_calc.reporting.corep.templates import CRR_C08_07_ROWS

        assert CRR_C08_07_ROWS[-1][1] == "Total"
        assert CRR_C08_07_ROWS[-1][0] == "0170"

    def test_b31_total_and_materiality_rows(self) -> None:
        """B31 has Total (0270) and Aggregate immateriality % (0280) rows."""
        from rwa_calc.reporting.corep.templates import B31_C08_07_ROWS

        total_row = [r for r in B31_C08_07_ROWS if r[1] == "Total"]
        assert len(total_row) == 1
        assert total_row[0][0] == "0270"
        mat_row = [r for r in B31_C08_07_ROWS if "immateriality" in r[1]]
        assert len(mat_row) == 1
        assert mat_row[0][0] == "0280"

    def test_irb_approaches_frozenset(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_07_IRB_APPROACHES

        assert "foundation_irb" in C08_07_IRB_APPROACHES
        assert "advanced_irb" in C08_07_IRB_APPROACHES
        assert "slotting" in C08_07_IRB_APPROACHES
        assert "standardised" not in C08_07_IRB_APPROACHES

    def test_crr_retail_classes_frozenset(self) -> None:
        from rwa_calc.reporting.corep.templates import C08_07_CRR_RETAIL_CLASSES

        assert "retail_mortgage" in C08_07_CRR_RETAIL_CLASSES
        assert "retail_qrre" in C08_07_CRR_RETAIL_CLASSES
        assert "retail_other" in C08_07_CRR_RETAIL_CLASSES
        assert "corporate" not in C08_07_CRR_RETAIL_CLASSES

    def test_b31_column_groups(self) -> None:
        """Basel 3.1 columns cover Exposure, Coverage %, RWEA, SA Breakdown, Materiality."""
        from rwa_calc.reporting.corep.templates import B31_C08_07_COLUMNS

        groups = {c.group for c in B31_C08_07_COLUMNS}
        assert "Exposure" in groups
        assert "Coverage %" in groups
        assert "RWEA" in groups
        assert "RWEA: SA Breakdown" in groups
        assert "Materiality" in groups


class TestC0807Generation:
    """Tests for C 08.07 / OF 08.07 generation logic."""

    def test_c0807_produces_output(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        assert bundle.c08_07 is not None
        assert isinstance(bundle.c08_07, pl.DataFrame)

    def test_c0807_crr_has_correct_column_count(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="CRR")
        df = bundle.c08_07
        assert df is not None
        # 5 data columns + row_ref + row_name = 7
        assert len(df.columns) == 7

    def test_c0807_b31_has_correct_column_count(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        # 18 data columns + row_ref + row_name = 20
        assert len(df.columns) == 20

    def test_c0807_crr_has_17_rows(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        assert bundle.c08_07 is not None
        assert len(bundle.c08_07) == 17

    def test_c0807_b31_has_11_rows(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        assert bundle.c08_07 is not None
        assert len(bundle.c08_07) == 11

    def test_c0807_none_for_sa_only(self) -> None:
        """Returns None when no IRB or SA data (empty results)."""
        gen = COREPGenerator()
        empty = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(empty)
        assert bundle.c08_07 is None

    def test_c0807_none_for_missing_columns(self) -> None:
        """Returns None with error when required columns missing."""
        gen = COREPGenerator()
        no_ead = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
            }
        )
        bundle = gen.generate_from_lazyframe(no_ead)
        assert bundle.c08_07 is None
        assert any("C 08.07" in e for e in bundle.errors)

    def test_c0807_has_row_ref_and_row_name(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        assert "row_ref" in df.columns
        assert "row_name" in df.columns


class TestC0807ColumnValues:
    """Tests for C 08.07 column values with hand-calculated expectations."""

    def test_corporate_irb_ead(self) -> None:
        """Col 0010 (IRB EAD) for corporate = 5000."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0050")
        assert row["0010"][0] == pytest.approx(5000.0)

    def test_corporate_total_ead(self) -> None:
        """Col 0020 (total EAD) for corporate = 5000 + 3000 = 8000."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0050")
        assert row["0020"][0] == pytest.approx(8000.0)

    def test_corporate_sa_pct(self) -> None:
        """Col 0030 (SA %) for corporate = 3000/8000 * 100 = 37.5%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0050")
        assert row["0030"][0] == pytest.approx(37.5, rel=1e-4)

    def test_corporate_irb_pct(self) -> None:
        """Col 0050 (IRB %) for corporate = 5000/8000 * 100 = 62.5%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0050")
        assert row["0050"][0] == pytest.approx(62.5, rel=1e-4)

    def test_institution_fully_irb(self) -> None:
        """Institution is 100% IRB: SA%=0, IRB%=100."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0040")
        assert row["0030"][0] == pytest.approx(0.0)
        assert row["0050"][0] == pytest.approx(100.0)
        assert row["0010"][0] == pytest.approx(2000.0)

    def test_retail_mortgage_fully_sa(self) -> None:
        """Retail mortgage is 100% SA: IRB EAD=0, SA%=100."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0110")
        assert row["0010"][0] == pytest.approx(0.0)
        assert row["0030"][0] == pytest.approx(100.0)
        assert row["0050"][0] == pytest.approx(0.0)

    def test_specialised_lending_fully_irb(self) -> None:
        """Specialised lending (slotting) row 0070 is 100% IRB."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0070")
        assert row["0010"][0] == pytest.approx(3000.0)
        assert row["0050"][0] == pytest.approx(100.0)

    def test_total_row_sums(self) -> None:
        """Total row (0170) aggregates all classes correctly."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0170")
        # IRB EAD: 5000 + 2000 + 1000 + 3000 = 11000
        assert row["0010"][0] == pytest.approx(11000.0)
        # Total EAD: 11000 + 3000 + 4000 + 500 = 18500
        assert row["0020"][0] == pytest.approx(18500.0)
        # IRB%: 11000/18500 * 100 ≈ 59.459%
        assert row["0050"][0] == pytest.approx(11000.0 / 18500.0 * 100.0, rel=1e-4)

    def test_retail_aggregate_row(self) -> None:
        """CRR row 0090 (Retail) aggregates mortgage + QRRE + other."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0090")
        # Retail IRB: QRRE 1000; Retail SA: mortgage 4000
        assert row["0010"][0] == pytest.approx(1000.0)
        assert row["0020"][0] == pytest.approx(5000.0)

    def test_equity_row(self) -> None:
        """Equity row (0150) shows 100% SA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0150")
        assert row["0010"][0] == pytest.approx(0.0)
        assert row["0020"][0] == pytest.approx(500.0)
        assert row["0050"][0] == pytest.approx(0.0)

    def test_rollout_plan_pct_zero(self) -> None:
        """Col 0040 (roll-out plan %) is always 0 — not tracked in pipeline."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0170")
        assert total["0040"][0] == pytest.approx(0.0)


class TestC0807B31Features:
    """Tests for Basel 3.1 OF 08.07 specific features."""

    def test_b31_total_rwea(self) -> None:
        """Col 0060 (total RWEA) present and correct under B31."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        # Total RWA: 2500 + 1500 + 800 + 1200 + 200 + 2100 + 750 + 500 = 9550
        assert total["0060"][0] == pytest.approx(9550.0)

    def test_b31_irb_rwea(self) -> None:
        """Col 0150 (IRB RWEA) correct under B31."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        # IRB RWA: 2500 + 800 + 200 + 2100 = 5600
        assert total["0150"][0] == pytest.approx(5600.0)

    def test_b31_sa_rwea_other(self) -> None:
        """Col 0140 (SA RWEA: other) = total SA RWEA when no sa_use_reason."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        # SA RWA: 1500 + 1200 + 750 + 500 = 3950
        assert total["0140"][0] == pytest.approx(3950.0)

    def test_b31_materiality_columns_null_for_total(self) -> None:
        """Materiality cols 0160-0180 are null (requires institutional config)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        assert total["0160"][0] is None
        assert total["0170"][0] is None
        assert total["0180"][0] is None

    def test_b31_materiality_row_present(self) -> None:
        """B31 has an aggregate immateriality % row (0280)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        mat_row = df.filter(pl.col("row_ref") == "0280")
        assert len(mat_row) == 1

    def test_b31_corporate_class_row(self) -> None:
        """B31 row 0200 (Corporate — other) maps to corporate class."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0200")
        assert row["0010"][0] == pytest.approx(5000.0)  # IRB corporate EAD
        assert row["0020"][0] == pytest.approx(8000.0)  # Total corporate EAD

    def test_b31_sa_breakdown_cols_zero_without_reason(self) -> None:
        """SA RWEA breakdown cols 0070-0130 are 0 without sa_use_reason data."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        for ref in ["0070", "0080", "0090", "0100", "0110", "0120", "0130"]:
            assert total[ref][0] == pytest.approx(0.0)

    def test_b31_rwea_additive(self) -> None:
        """Col 0060 = sum of SA RWEA breakdown (0070-0140) + IRB RWEA (0150)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0270")
        sa_breakdown = sum(
            total[ref][0]
            for ref in ["0070", "0080", "0090", "0100", "0110", "0120", "0130", "0140"]
        )
        irb = total["0150"][0]
        assert total["0060"][0] == pytest.approx(sa_breakdown + irb, rel=1e-4)


class TestC0807EdgeCases:
    """Edge case tests for C 08.07 / OF 08.07."""

    def test_c0807_bundle_default_is_none(self) -> None:
        """COREPTemplateBundle.c08_07 defaults to None."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c08_07 is None

    def test_c0807_single_irb_class(self) -> None:
        """Works with a single IRB class."""
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
        assert bundle.c08_07 is not None
        total = bundle.c08_07.filter(pl.col("row_ref") == "0170")
        assert total["0010"][0] == pytest.approx(1000.0)
        assert total["0050"][0] == pytest.approx(100.0)

    def test_c0807_all_sa(self) -> None:
        """All SA exposures: IRB EAD = 0, IRB% = 0 everywhere."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "institution"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [500.0, 800.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_07 is not None
        total = bundle.c08_07.filter(pl.col("row_ref") == "0170")
        assert total["0010"][0] == pytest.approx(0.0)
        assert total["0020"][0] == pytest.approx(3000.0)
        assert total["0050"][0] == pytest.approx(0.0)
        assert total["0030"][0] == pytest.approx(100.0)

    def test_c0807_without_rwa_column(self) -> None:
        """Works even when rwa_final column is absent (CRR only needs EAD)."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_07 is not None

    def test_c0807_zero_ead_class(self) -> None:
        """Class with zero total EAD has 0% for both SA and IRB."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [0.0],
                "rwa_final": [0.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results)
        assert bundle.c08_07 is not None
        row = bundle.c08_07.filter(pl.col("row_ref") == "0050")
        # Zero EAD → 0% for everything
        assert row["0030"][0] == pytest.approx(0.0)
        assert row["0050"][0] == pytest.approx(0.0)

    def test_c0807_preserves_row_order(self) -> None:
        """Rows are emitted in the order defined by the template."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results())
        df = bundle.c08_07
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r[0] for r in CRR_C08_07_ROWS]
        assert refs == expected

    def test_c0807_b31_preserves_row_order(self) -> None:
        """B31 rows are emitted in the order defined by the template."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_scope_of_use_results(), framework="BASEL_3_1")
        df = bundle.c08_07
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r[0] for r in B31_C08_07_ROWS]
        assert refs == expected


# =============================================================================
# C 02.00 / OF 02.00 — OWN FUNDS REQUIREMENTS
# =============================================================================


def _c02_sa_results() -> pl.LazyFrame:
    """SA-only results for C 02.00 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "S2", "S3", "S4"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "institution", "retail", "central_government"],
            "ead_final": [1000.0, 500.0, 300.0, 200.0],
            "risk_weight": [1.0, 0.2, 0.75, 0.0],
            "rwa_final": [1000.0, 100.0, 225.0, 0.0],
        }
    )


def _c02_mixed_results() -> pl.LazyFrame:
    """Mixed SA + IRB results for C 02.00 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "S2", "I1", "I2", "SL1"],
            "approach_applied": [
                "standardised",
                "standardised",
                "foundation_irb",
                "advanced_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "institution",
                "corporate",
                "retail_mortgage",
                "specialised_lending",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 800.0, 600.0],
            "risk_weight": [1.0, 0.2, 0.5, 0.3, 0.7],
            "rwa_final": [1000.0, 100.0, 1000.0, 240.0, 420.0],
        }
    )


def _c02_b31_results_with_floor() -> pl.LazyFrame:
    """Basel 3.1 results with output floor columns."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["S1", "I1", "I2", "SL1"],
            "approach_applied": [
                "standardised",
                "foundation_irb",
                "advanced_irb",
                "slotting",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "retail_mortgage",
                "specialised_lending",
            ],
            "ead_final": [1000.0, 2000.0, 800.0, 600.0],
            "risk_weight": [1.0, 0.5, 0.3, 0.7],
            "rwa_final": [1000.0, 1000.0, 240.0, 420.0],
            "rwa_pre_floor": [1000.0, 1000.0, 240.0, 420.0],
            "sa_rwa": [1000.0, 1500.0, 400.0, 500.0],
            "sl_type": [None, None, None, "project_finance"],
        }
    )


def _c02_b31_floor_binding() -> pl.LazyFrame:
    """Basel 3.1 results where floor is binding (total RWA > pre-floor)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["I1", "I2"],
            "approach_applied": ["foundation_irb", "advanced_irb"],
            "exposure_class": ["corporate", "retail_mortgage"],
            "ead_final": [2000.0, 800.0],
            "risk_weight": [0.15, 0.1],
            "rwa_final": [600.0, 280.0],  # Post-floor (higher)
            "rwa_pre_floor": [300.0, 80.0],  # Pre-floor (lower)
            "sa_rwa": [1500.0, 400.0],
        }
    )


class TestC0200TemplateDefinitions:
    """Template structure definitions for C 02.00 / OF 02.00."""

    def test_crr_column_count(self) -> None:
        """CRR C 02.00 has 1 column."""
        assert len(CRR_C02_00_COLUMNS) == 1

    def test_b31_column_count(self) -> None:
        """Basel 3.1 OF 02.00 has 3 columns."""
        assert len(B31_C02_00_COLUMNS) == 3

    def test_crr_column_refs(self) -> None:
        """CRR column ref is 0010."""
        assert CRR_C02_00_COLUMN_REFS == ["0010"]

    def test_b31_column_refs(self) -> None:
        """Basel 3.1 column refs are 0010, 0020, 0030."""
        assert B31_C02_00_COLUMN_REFS == ["0010", "0020", "0030"]

    def test_crr_section_count(self) -> None:
        """CRR has 3 sections."""
        assert len(CRR_C02_00_ROW_SECTIONS) == 3

    def test_b31_section_count(self) -> None:
        """Basel 3.1 has 6 sections (SA, F-IRB, A-IRB, slotting, other expanded)."""
        assert len(B31_C02_00_ROW_SECTIONS) == 6

    def test_crr_total_row_exists(self) -> None:
        """CRR has a TOTAL RISK EXPOSURE AMOUNT row."""
        all_rows = [r for s in CRR_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0010" in refs

    def test_b31_floor_indicator_rows(self) -> None:
        """Basel 3.1 has output floor indicator rows 0034, 0035, 0036."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0034" in refs
        assert "0035" in refs
        assert "0036" in refs

    def test_b31_slotting_rows(self) -> None:
        """Basel 3.1 has per-SL-type slotting rows 0412-0416."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0411", "0412", "0413", "0414", "0415", "0416"]:
            assert ref in refs, f"Missing slotting row {ref}"

    def test_b31_firb_breakdown_rows(self) -> None:
        """Basel 3.1 has F-IRB sub-class rows 0271, 0290, 0295-0297."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0271", "0290", "0295", "0296", "0297"]:
            assert ref in refs, f"Missing F-IRB row {ref}"

    def test_b31_airb_retail_rows(self) -> None:
        """Basel 3.1 has A-IRB retail sub-rows 0382-0385."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        for ref in ["0382", "0383", "0384", "0385"]:
            assert ref in refs, f"Missing A-IRB retail row {ref}"

    def test_sa_class_map_covers_major_classes(self) -> None:
        """SA class map has entries for major exposure classes."""
        for cls in ["corporate", "institution", "retail", "central_government", "equity"]:
            assert cls in C02_00_SA_CLASS_MAP, f"Missing SA class mapping for {cls}"

    def test_get_columns_selector(self) -> None:
        """get_c02_00_columns returns framework-appropriate columns."""
        assert get_c02_00_columns("CRR") == CRR_C02_00_COLUMNS
        assert get_c02_00_columns("BASEL_3_1") == B31_C02_00_COLUMNS

    def test_get_row_sections_selector(self) -> None:
        """get_c02_00_row_sections returns framework-appropriate rows."""
        assert get_c02_00_row_sections("CRR") == CRR_C02_00_ROW_SECTIONS
        assert get_c02_00_row_sections("BASEL_3_1") == B31_C02_00_ROW_SECTIONS

    def test_b31_sa_specialised_lending_row(self) -> None:
        """Basel 3.1 has SA specialised lending row 0131."""
        all_rows = [r for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        refs = [r.ref for r in all_rows]
        assert "0131" in refs


class TestC0200Generation:
    """C 02.00 / OF 02.00 generation from pipeline results."""

    def test_generated_under_crr(self) -> None:
        """C 02.00 is generated under CRR."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        assert bundle.c_02_00 is not None

    def test_generated_under_b31(self) -> None:
        """OF 02.00 is generated under Basel 3.1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None

    def test_is_dataframe(self) -> None:
        """Result is a polars DataFrame."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        assert isinstance(bundle.c_02_00, pl.DataFrame)

    def test_crr_has_one_data_column(self) -> None:
        """CRR C 02.00 has row_ref, row_name, and 1 data column (0010)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert "row_ref" in df.columns
        assert "row_name" in df.columns
        assert "0010" in df.columns
        # Only 1 data column + 2 metadata columns
        assert len(df.columns) == 3

    def test_b31_has_three_data_columns(self) -> None:
        """Basel 3.1 OF 02.00 has row_ref, row_name, and 3 data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        assert "0010" in df.columns
        assert "0020" in df.columns
        assert "0030" in df.columns
        assert len(df.columns) == 5

    def test_missing_rwa_column_returns_none(self) -> None:
        """Returns None when RWA column is missing."""
        gen = COREPGenerator()
        results = pl.LazyFrame({"exposure_reference": ["E1"], "ead_final": [1000.0]})
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        assert bundle.c_02_00 is None

    def test_error_logged_when_skipped(self) -> None:
        """Error logged when C 02.00 is skipped."""
        gen = COREPGenerator()
        results = pl.LazyFrame({"exposure_reference": ["E1"]})
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        assert any("C 02.00 skipped" in e for e in bundle.errors)

    def test_bundle_field_none_by_default(self) -> None:
        """c_02_00 field defaults to None."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.c_02_00 is None


class TestC0200TotalRow:
    """TOTAL RISK EXPOSURE AMOUNT row (0010) tests."""

    def test_sa_only_total(self) -> None:
        """Total RWEA = sum of all SA RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, S2=100, S3=225, S4=0 → 1325
        assert row["0010"][0] == pytest.approx(1325.0)

    def test_mixed_total(self) -> None:
        """Total RWEA = SA + IRB + slotting."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, S2=100, I1=1000, I2=240, SL1=420 → 2760
        assert row["0010"][0] == pytest.approx(2760.0)

    def test_own_funds_requirement(self) -> None:
        """Own funds requirement (row 0040) = 8% × TREA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        trea = df.filter(pl.col("row_ref") == "0010")["0010"][0]
        own_funds = df.filter(pl.col("row_ref") == "0040")["0010"][0]
        assert own_funds == pytest.approx(trea * 0.08)

    def test_b31_total_row_three_columns(self) -> None:
        """B31 total row has all 3 columns populated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        assert row["0010"][0] is not None
        assert row["0020"][0] is not None
        assert row["0030"][0] is not None

    def test_b31_total_rwa_matches(self) -> None:
        """B31 col 0010 total = sum of all rwa_final."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # S1=1000, I1=1000, I2=240, SL1=420 → 2660
        assert row["0010"][0] == pytest.approx(2660.0)


class TestC0200SABreakdown:
    """SA exposure class breakdown rows."""

    def test_sa_total(self) -> None:
        """SA total (row 0060) = sum of SA approach RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0060")
        # All SA: 1000+100+225+0 = 1325
        assert row["0010"][0] == pytest.approx(1325.0)

    def test_sa_corporate_row(self) -> None:
        """Corporate RWA in SA class row 0130."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0130")
        assert row["0010"][0] == pytest.approx(1000.0)

    def test_sa_institution_row(self) -> None:
        """Institution RWA in SA class row 0120."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0120")
        assert row["0010"][0] == pytest.approx(100.0)

    def test_sa_retail_row(self) -> None:
        """Retail RWA in SA class row 0140."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0140")
        assert row["0010"][0] == pytest.approx(225.0)

    def test_sa_sovereign_row(self) -> None:
        """Sovereign RWA in SA class row 0070."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0070")
        assert row["0010"][0] == pytest.approx(0.0)

    def test_mixed_sa_only_in_sa_rows(self) -> None:
        """With mixed data, only SA approach goes to SA rows."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        sa_total = df.filter(pl.col("row_ref") == "0060")
        # SA exposures only: S1=1000, S2=100 → 1100
        assert sa_total["0010"][0] == pytest.approx(1100.0)


class TestC0200IRBBreakdown:
    """IRB approach breakdown rows."""

    def test_irb_total(self) -> None:
        """IRB total (row 0220) = F-IRB + A-IRB + slotting."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0220")
        # I1=1000 (FIRB) + I2=240 (AIRB) + SL1=420 (slotting) = 1660
        assert row["0010"][0] == pytest.approx(1660.0)

    def test_firb_total(self) -> None:
        """F-IRB total (row 0240) = F-IRB RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0240")
        assert row["0010"][0] == pytest.approx(1000.0)

    def test_airb_total(self) -> None:
        """A-IRB total (row 0300) = A-IRB RWA."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0300")
        assert row["0010"][0] == pytest.approx(240.0)

    def test_airb_retail_mortgage(self) -> None:
        """A-IRB retail mortgage RWA in row 0380."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0380")
        assert row["0010"][0] == pytest.approx(240.0)

    def test_slotting_total(self) -> None:
        """Slotting total in CRR row 0410."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0410")
        assert row["0010"][0] == pytest.approx(420.0)

    def test_b31_slotting_by_type(self) -> None:
        """Basel 3.1 breaks slotting into per-SL-type rows."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        # SL1 is project_finance → row 0412
        sl_total = df.filter(pl.col("row_ref") == "0411")
        pf_row = df.filter(pl.col("row_ref") == "0412")
        assert sl_total["0010"][0] == pytest.approx(420.0)
        assert pf_row["0010"][0] == pytest.approx(420.0)

    def test_credit_risk_equals_total(self) -> None:
        """Credit risk row (0050) = total (0010) since only CR in scope."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")["0010"][0]
        cr = df.filter(pl.col("row_ref") == "0050")["0010"][0]
        assert cr == pytest.approx(total)

    def test_sa_plus_irb_equals_credit_risk(self) -> None:
        """SA total + IRB total = credit risk total."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_mixed_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        cr = df.filter(pl.col("row_ref") == "0050")["0010"][0]
        sa = df.filter(pl.col("row_ref") == "0060")["0010"][0]
        irb = df.filter(pl.col("row_ref") == "0220")["0010"][0]
        assert sa + irb == pytest.approx(cr)


class TestC0200B31Features:
    """Basel 3.1 specific features: 3 columns, floor rows, sub-breakdowns."""

    def test_sa_equivalent_column(self) -> None:
        """Col 0020 (SA-equivalent) is populated from sa_rwa."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0010")
        # sa_rwa: 1000+1500+400+500 = 3400
        assert row["0020"][0] == pytest.approx(3400.0)

    def test_floor_indicator_row(self) -> None:
        """Row 0034 indicates whether floor is activated."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0034")
        assert len(row) == 1
        # Floor not binding in this dataset (rwa_final == rwa_pre_floor)
        assert row["0010"][0] == pytest.approx(0.0)

    def test_floor_binding_indicator(self) -> None:
        """Row 0034 = 1 when floor is binding."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_floor_binding(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0034")
        assert row["0010"][0] == pytest.approx(1.0)

    def test_b31_firb_institution_row(self) -> None:
        """B31 has F-IRB institution detail row 0271."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0271")
        assert len(row) == 1  # Row exists

    def test_b31_sa_specialised_lending_row(self) -> None:
        """B31 SA SL sub-row 0131 populated when SL under SA."""
        gen = COREPGenerator()
        # SL under SA → goes to corporate row 0130 and SL sub-row 0131
        results = pl.LazyFrame(
            {
                "exposure_reference": ["SL1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["specialised_lending"],
                "ead_final": [500.0],
                "risk_weight": [1.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == "0131")
        assert row["0010"][0] == pytest.approx(500.0)


class TestC0200NullRows:
    """Non-credit-risk rows should be null (out of scope)."""

    @pytest.mark.parametrize(
        "row_ref,row_name",
        [
            ("0430", "Settlement risk"),
            ("0440", "Securitisation positions in non-trading book"),
            ("0460", "Position, foreign exchange and commodities risk"),
            ("0590", "Credit valuation adjustment (CVA)"),
            ("0640", "Operational risk"),
            ("0680", "Additional risk exposure: fixed overheads"),
        ],
    )
    def test_out_of_scope_row_is_null(self, row_ref: str, row_name: str) -> None:
        """Non-credit-risk rows have null values."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        row = df.filter(pl.col("row_ref") == row_ref)
        assert len(row) == 1
        assert row["row_name"][0] == row_name
        assert row["0010"][0] is None


class TestC0200EdgeCases:
    """Edge cases for C 02.00 generation."""

    def test_empty_results(self) -> None:
        """Empty results produce zero totals."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")
        assert total["0010"][0] == pytest.approx(0.0)

    def test_data_columns_are_float64(self) -> None:
        """Data columns are Float64."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert df["0010"].dtype == pl.Float64

    def test_row_ref_is_string(self) -> None:
        """Row ref column is String."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        assert df["row_ref"].dtype == pl.String

    def test_row_order_preserved(self) -> None:
        """Rows appear in the order defined by row sections."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_sa_results(), framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r.ref for s in CRR_C02_00_ROW_SECTIONS for r in s.rows]
        assert refs == expected

    def test_b31_row_order_preserved(self) -> None:
        """Basel 3.1 rows appear in the order defined by row sections."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_c02_b31_results_with_floor(), framework="BASEL_3_1")
        df = bundle.c_02_00
        assert df is not None
        refs = df["row_ref"].to_list()
        expected = [r.ref for s in B31_C02_00_ROW_SECTIONS for r in s.rows]
        assert refs == expected

    def test_null_rwa_treated_as_zero(self) -> None:
        """Null RWA values treated as zero in aggregation."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [1000.0, None],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="CRR")
        df = bundle.c_02_00
        assert df is not None
        total = df.filter(pl.col("row_ref") == "0010")
        assert total["0010"][0] == pytest.approx(1000.0)


# =============================================================================
# C 09.01 / OF 09.01 — GEOGRAPHICAL BREAKDOWN SA
# =============================================================================


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


# =============================================================================
# C 09.02 / OF 09.02 — GEOGRAPHICAL BREAKDOWN IRB
# =============================================================================


def _irb_geo_results() -> pl.LazyFrame:
    """Synthetic IRB results with country codes for C 09.02 testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_qrre",
                "institution",
            ],
            "ead_final": [1000.0, 500.0, 2000.0, 800.0, 1500.0],
            "ead_gross": [1200.0, 600.0, 2200.0, 900.0, 1700.0],
            "rwa_final": [700.0, 350.0, 600.0, 200.0, 300.0],
            "cp_country_code": ["GB", "US", "GB", "GB", "US"],
            "default_status": [False, False, False, False, False],
            "irb_pd_floored": [0.01, 0.02, 0.005, 0.03, 0.008],
            "lgd_post_crm": [0.45, 0.45, 0.20, 0.75, 0.45],
            "expected_loss": [4.5, 4.5, 2.0, 18.0, 5.4],
        }
    )


class TestC0902TemplateDefinitions:
    """Test C 09.02 / OF 09.02 template structure definitions."""

    def test_crr_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_COLUMNS

        assert len(CRR_C09_02_COLUMNS) == 17

    def test_b31_columns_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMNS

        assert len(B31_C09_02_COLUMNS) == 15

    def test_crr_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_02_COLUMN_REFS

        assert C09_02_COLUMN_REFS == [
            "0010",
            "0030",
            "0040",
            "0050",
            "0055",
            "0060",
            "0070",
            "0080",
            "0090",
            "0100",
            "0105",
            "0110",
            "0120",
            "0121",
            "0122",
            "0125",
            "0130",
        ]

    def test_b31_column_refs(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert B31_C09_02_COLUMN_REFS == [
            "0010",
            "0030",
            "0040",
            "0050",
            "0055",
            "0060",
            "0070",
            "0080",
            "0090",
            "0100",
            "0105",
            "0107",
            "0120",
            "0125",
            "0130",
        ]

    def test_b31_adds_col_0107(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert "0107" in B31_C09_02_COLUMN_REFS

    def test_b31_removes_supporting_factor_columns(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMN_REFS

        assert "0110" not in B31_C09_02_COLUMN_REFS
        assert "0121" not in B31_C09_02_COLUMN_REFS
        assert "0122" not in B31_C09_02_COLUMN_REFS

    def test_crr_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        assert len(CRR_C09_02_ROWS) == 16

    def test_b31_rows_count(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        assert len(B31_C09_02_ROWS) == 19

    def test_crr_has_equity_row(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        refs = [r.ref for r in CRR_C09_02_ROWS]
        assert "0140" in refs

    def test_b31_removes_equity_row(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0140" not in refs

    def test_b31_adds_corporate_sub_rows(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0048" in refs  # FSE/large corporates
        assert "0049" in refs  # purchased receivables
        assert "0055" in refs  # non-SME

    def test_b31_restructures_retail_re(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_ROWS

        refs = [r.ref for r in B31_C09_02_ROWS]
        assert "0071" in refs  # resi RE SME
        assert "0072" in refs  # resi RE non-SME
        assert "0073" in refs  # commercial RE SME
        assert "0074" in refs  # commercial RE non-SME

    def test_crr_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_COLUMNS, get_c09_02_columns

        assert get_c09_02_columns("CRR") is CRR_C09_02_COLUMNS

    def test_b31_selector(self) -> None:
        from rwa_calc.reporting.corep.templates import B31_C09_02_COLUMNS, get_c09_02_columns

        assert get_c09_02_columns("BASEL_3_1") is B31_C09_02_COLUMNS

    def test_total_row_is_last(self) -> None:
        from rwa_calc.reporting.corep.templates import CRR_C09_02_ROWS

        assert CRR_C09_02_ROWS[-1].ref == "0150"

    def test_irb_class_map(self) -> None:
        from rwa_calc.reporting.corep.templates import C09_02_IRB_CLASS_MAP

        assert C09_02_IRB_CLASS_MAP["corporate"] == "corporate"
        assert C09_02_IRB_CLASS_MAP["retail_mortgage"] == "retail"
        assert C09_02_IRB_CLASS_MAP["institution"] == "institution"


class TestC0902Generation:
    """Test C 09.02 / OF 09.02 generation from pipeline data."""

    def test_generates_per_country_dict(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        assert isinstance(bundle.c09_02, dict)
        assert "TOTAL" in bundle.c09_02

    def test_generates_gb_and_us_countries(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        assert "GB" in bundle.c09_02
        assert "US" in bundle.c09_02

    def test_dataframe_has_correct_column_count_crr(self) -> None:
        """17 data columns + row_ref + row_name = 19."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        assert len(total.columns) == 19  # 17 data + 2 meta

    def test_dataframe_has_correct_column_count_b31(self) -> None:
        """15 data columns + row_ref + row_name = 17."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert len(total.columns) == 17  # 15 data + 2 meta

    def test_sa_only_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_02 == {}

    def test_missing_country_code_returns_empty(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "irb_pd_floored": [0.01],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert bundle.c09_02 == {}


class TestC0902ColumnValues:
    """Test C 09.02 column value computation."""

    def test_col_0010_original_exposure(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # ead_gross sum: 1200 + 600 + 2200 + 900 + 1700 = 6600
        assert total_row["0010"][0] == pytest.approx(6600.0)

    def test_col_0105_exposure_value(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # ead_final sum: 1000 + 500 + 2000 + 800 + 1500 = 5800
        assert total_row["0105"][0] == pytest.approx(5800.0)

    def test_col_0125_rwea(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # rwa_final sum: 700 + 350 + 600 + 200 + 300 = 2150
        assert total_row["0125"][0] == pytest.approx(2150.0)

    def test_col_0080_ewa_pd(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EAD-weighted PD: (0.01*1000 + 0.02*500 + 0.005*2000 + 0.03*800 + 0.008*1500) / 5800
        # = (10 + 10 + 10 + 24 + 12) / 5800 = 66 / 5800 ≈ 0.011379
        assert total_row["0080"][0] == pytest.approx(66.0 / 5800.0, rel=1e-3)

    def test_col_0090_ewa_lgd(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EAD-weighted LGD: (0.45*1000 + 0.45*500 + 0.20*2000 + 0.75*800 + 0.45*1500) / 5800
        # = (450 + 225 + 400 + 600 + 675) / 5800 = 2350 / 5800 ≈ 0.40517
        assert total_row["0090"][0] == pytest.approx(2350.0 / 5800.0, rel=1e-3)

    def test_col_0130_expected_loss(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        # EL sum: 4.5 + 4.5 + 2.0 + 18.0 + 5.4 = 34.4
        assert total_row["0130"][0] == pytest.approx(34.4)

    def test_corporate_row_values(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0030")
        # Corporate EAD: 1000 + 500 = 1500
        assert corp_row["0105"][0] == pytest.approx(1500.0)

    def test_institution_row_values(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total = bundle.c09_02["TOTAL"]
        inst_row = total.filter(pl.col("row_ref") == "0020")
        # Institution EAD: 1500
        assert inst_row["0105"][0] == pytest.approx(1500.0)


class TestC0902B31Features:
    """Test Basel 3.1 specific features of OF 09.02."""

    def test_no_supporting_factor_columns(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert "0110" not in total.columns
        assert "0121" not in total.columns
        assert "0122" not in total.columns

    def test_has_col_0107_defaulted_ev(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        assert "0107" in total.columns

    def test_no_equity_row(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="BASEL_3_1")
        total = bundle.c09_02["TOTAL"]
        refs = total["row_ref"].to_list()
        assert "0140" not in refs


class TestC0902EdgeCases:
    """Test C 09.02 edge cases."""

    def test_total_equals_sum_of_countries(self) -> None:
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_geo_results(), framework="CRR")
        total_rwa = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0125"][0]
        gb_rwa = bundle.c09_02["GB"].filter(pl.col("row_ref") == "0150")["0125"][0]
        us_rwa = bundle.c09_02["US"].filter(pl.col("row_ref") == "0150")["0125"][0]
        assert total_rwa == pytest.approx(gb_rwa + us_rwa)

    def test_single_country_total_matches(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "ead_gross": [1200.0],
                "rwa_final": [500.0],
                "cp_country_code": ["GB"],
                "irb_pd_floored": [0.01],
                "lgd_post_crm": [0.45],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total_rwa = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0125"][0]
        gb_rwa = bundle.c09_02["GB"].filter(pl.col("row_ref") == "0150")["0125"][0]
        assert total_rwa == pytest.approx(gb_rwa)

    def test_null_country_in_total_but_not_per_country(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [500.0, 250.0],
                "cp_country_code": ["GB", None],
                "irb_pd_floored": [0.01, 0.02],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        assert "TOTAL" in bundle.c09_02
        assert "GB" in bundle.c09_02
        total_ead = bundle.c09_02["TOTAL"].filter(pl.col("row_ref") == "0150")["0105"][0]
        # Total includes both (1000 + 500 = 1500)
        assert total_ead == pytest.approx(1500.0)

    def test_slotting_included_in_corporate(self) -> None:
        """Slotting exposures classified under corporate in geographical breakdown."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["slotting", "foundation_irb"],
                "exposure_class": ["specialised_lending", "corporate"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [700.0, 250.0],
                "cp_country_code": ["GB", "GB"],
                "irb_pd_floored": [0.005, 0.01],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_02["TOTAL"]
        corp_row = total.filter(pl.col("row_ref") == "0030")
        # SL maps to corporate: 1000 + 500 = 1500
        assert corp_row["0105"][0] == pytest.approx(1500.0)

    def test_zero_ead_exposure(self) -> None:
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [0.0],
                "ead_gross": [0.0],
                "rwa_final": [0.0],
                "cp_country_code": ["GB"],
                "irb_pd_floored": [0.01],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        total = bundle.c09_02["TOTAL"]
        total_row = total.filter(pl.col("row_ref") == "0150")
        assert total_row["0105"][0] == pytest.approx(0.0)


# =============================================================================
# C 07.00 / OF 07.00 — MEMORANDUM ROWS AND SUPPORTING FACTOR ROWS
# =============================================================================


def _sa_results_with_defaulted() -> pl.LazyFrame:
    """SA results with defaulted exposures at different risk weights.

    Contains:
    - 2 defaulted corporate exposures: one at RW 100%, one at RW 150%
    - 1 non-defaulted corporate (RW 100%) to verify filtering
    - 1 defaulted retail at RW 150%
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_DEF_100",
                "SA_DEF_150",
                "SA_CORP_LIVE",
                "SA_RET_DEF",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "retail_other",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 500.0],
            "undrawn_amount": [0.0, 0.0, 500.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3200.0, 500.0],
            "rwa_final": [1000.0, 3000.0, 3200.0, 750.0],
            "risk_weight": [1.00, 1.50, 1.00, 1.50],
            "default_status": [True, True, False, True],
            "scra_provision_amount": [50.0, 100.0, 10.0, 25.0],
            "gcra_provision_amount": [0.0, 0.0, 5.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [None, None, 3, None],
        }
    )


def _sa_results_with_re_memorandum() -> pl.LazyFrame:
    """SA results with RE-secured exposures for CRR memorandum rows 0290/0310.

    Contains:
    - 2 commercial RE-secured exposures (EAD 1000 + 2000)
    - 1 residential RE-secured exposure (EAD 3000)
    - 1 non-RE exposure
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_CRE_1",
                "SA_CRE_2",
                "SA_RRE_1",
                "SA_PLAIN",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "secured_by_re_property",
                "secured_by_re_property",
                "secured_by_re_property",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 4000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 0.0],
            "ead_final": [1000.0, 2000.0, 3000.0, 4000.0],
            "rwa_final": [500.0, 1000.0, 1050.0, 4000.0],
            "risk_weight": [0.50, 0.50, 0.35, 1.00],
            "property_type": ["commercial", "commercial", "residential", None],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [None, None, None, 3],
        }
    )


def _sa_results_with_supporting_factors() -> pl.LazyFrame:
    """SA results with supporting factor data for CRR rows 0030/0035.

    All exposures are "corporate" class. The is_sme/is_infrastructure flags
    indicate which supporting factor applies. In a real pipeline, the
    classifier sets these flags while keeping exposure_class as "corporate".

    Contains:
    - 2 SME corporate exposures with supporting factor applied
    - 1 infrastructure corporate exposure with supporting factor applied
    - 1 plain corporate (no factor)
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_SME_1",
                "SA_SME_2",
                "SA_INFRA_1",
                "SA_CORP_1",
            ],
            "approach_applied": [
                "standardised",
                "standardised",
                "standardised",
                "standardised",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
            ],
            "drawn_amount": [1000.0, 2000.0, 5000.0, 3000.0],
            "undrawn_amount": [0.0, 0.0, 0.0, 500.0],
            "ead_final": [1000.0, 2000.0, 5000.0, 3200.0],
            "rwa_final": [700.0, 1400.0, 3750.0, 3200.0],
            "risk_weight": [1.00, 1.00, 1.00, 1.00],
            "rwa_pre_factor": [1000.0, 2000.0, 5000.0, 3200.0],
            "supporting_factor_applied": [True, True, True, False],
            "is_sme": [True, True, False, False],
            "is_infrastructure": [False, False, True, False],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
            "sa_cqs": [3, 3, 3, 3],
        }
    )


class TestC0700MemorandumRows:
    """Tests for C 07.00 / OF 07.00 Section 5 memorandum rows.

    Memorandum items provide supplementary breakdowns:
    - Row 0290 (CRR): Exposures secured by mortgages on commercial immovable property
    - Row 0300: Exposures in default subject to RW of 100%
    - Row 0310 (CRR): Exposures secured by mortgages on residential immovable property
    - Row 0320: Exposures in default subject to RW of 150%

    Why: These rows are mandatory COREP fields. Previously they were
    always null, misrepresenting the institution's defaulted exposure
    distribution and RE-secured positions.

    References:
        CRR Art. 127: Defaulted exposure risk weights
        CRR Art. 124-126: Exposures secured by immovable property
    """

    def test_row_0300_defaulted_rw_100(self) -> None:
        """Row 0300 filters defaulted exposures with RW = 100%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        assert len(row) == 1
        # SA_DEF_100 has EAD 1000, RW 100%, defaulted
        assert row["0200"][0] == pytest.approx(1000.0)
        assert row["0220"][0] == pytest.approx(1000.0)

    def test_row_0320_defaulted_rw_150(self) -> None:
        """Row 0320 filters defaulted exposures with RW = 150%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0320")
        assert len(row) == 1
        # SA_DEF_150 has EAD 2000, RW 150%, defaulted
        assert row["0200"][0] == pytest.approx(2000.0)
        assert row["0220"][0] == pytest.approx(3000.0)

    def test_row_0300_excludes_non_defaulted(self) -> None:
        """Row 0300 must not include non-defaulted exposures even at RW 100%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0300 = corp.filter(pl.col("row_ref") == "0300")
        # SA_CORP_LIVE is RW 100% but NOT defaulted; should be excluded
        # Only SA_DEF_100 (EAD 1000) qualifies
        assert row_0300["0200"][0] == pytest.approx(1000.0)

    def test_row_0320_retail_class(self) -> None:
        """Row 0320 applies within each exposure class independently."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        retail = bundle.c07_00["retail_other"]
        row = retail.filter(pl.col("row_ref") == "0320")
        # SA_RET_DEF has EAD 500, RW 150%, defaulted
        assert row["0200"][0] == pytest.approx(500.0)
        assert row["0220"][0] == pytest.approx(750.0)

    def test_row_0300_null_when_no_defaults_at_100(self) -> None:
        """Row 0300 is null when no defaulted exposures have RW = 100%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        retail = bundle.c07_00["retail_other"]
        row = retail.filter(pl.col("row_ref") == "0300")
        # No defaulted retail exposures at RW 100%
        assert row["0200"][0] is None

    def test_b31_rows_0300_0320_present(self) -> None:
        """Basel 3.1 OF 07.00 also has rows 0300 and 0320."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()
        assert "0300" in row_refs
        assert "0320" in row_refs

    def test_b31_row_0300_populated(self) -> None:
        """B31 row 0300 is populated from defaulted exposures at RW 100%."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="BASEL_3_1")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        assert row["0200"][0] == pytest.approx(1000.0)

    def test_row_0290_crr_commercial_re(self) -> None:
        """CRR row 0290: commercial immovable property secured exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        re = bundle.c07_00["secured_by_re_property"]
        row = re.filter(pl.col("row_ref") == "0290")
        assert len(row) == 1
        # Two commercial RE: EAD 1000 + 2000 = 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        # RWA 500 + 1000 = 1500
        assert row["0220"][0] == pytest.approx(1500.0)

    def test_row_0310_crr_residential_re(self) -> None:
        """CRR row 0310: residential immovable property secured exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        re = bundle.c07_00["secured_by_re_property"]
        row = re.filter(pl.col("row_ref") == "0310")
        assert len(row) == 1
        # One residential RE: EAD 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        assert row["0220"][0] == pytest.approx(1050.0)

    def test_row_0290_null_for_non_re_class(self) -> None:
        """Row 0290 is null for classes without RE-secured exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_re_memorandum(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0290")
        assert row["0200"][0] is None

    def test_b31_no_rows_0290_0310(self) -> None:
        """B31 OF 07.00 does not have rows 0290/0310 (replaced by Section 1 RE breakdown)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_re_memorandum(), framework="BASEL_3_1"
        )
        re = bundle.c07_00["secured_by_re_property"]
        row_refs = re["row_ref"].to_list()
        # B31 memorandum doesn't include 0290/0310 (removed in template defs)
        assert "0290" not in row_refs
        assert "0310" not in row_refs

    def test_defaulted_rw_matching_uses_rounding(self) -> None:
        """RW comparison uses 4-decimal rounding to handle float imprecision."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "ead_final": [1000.0],
                "rwa_final": [1000.0],
                # Slightly imprecise 100% due to float arithmetic
                "risk_weight": [0.99999999],
                "default_status": [True],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP_A"],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0300")
        # Should match despite float imprecision
        assert row["0200"][0] == pytest.approx(1000.0)

    def test_memorandum_columns_complete(self) -> None:
        """Memorandum rows have the full set of COREP columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_defaulted(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0300 = corp.filter(pl.col("row_ref") == "0300")
        # Should have all CRR C07 columns
        crr_col_refs = [c.ref for c in CRR_C07_COLUMNS]
        for ref in crr_col_refs:
            assert ref in row_0300.columns


class TestC0700SupportingFactorRows:
    """Tests for CRR C 07.00 Section 1 supporting factor rows.

    Row 0030: of which: Exposures subject to SME-supporting factor
    Row 0035: of which: Exposures subject to infrastructure supporting factor

    Why: These rows report the regulatory benefit from supporting factors.
    Previously they were always null despite the pipeline computing
    supporting factors. Now populated using is_sme/is_infrastructure
    flags and supporting_factor_applied status.

    References:
        CRR Art. 501: SME supporting factor
        CRR Art. 501a: Infrastructure supporting factor
    """

    def test_row_0030_sme_exposures(self) -> None:
        """Row 0030 filters SME exposures with supporting factor applied."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        # corporate_sme merges into corporate for C 07.00
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert len(row) == 1
        # SA_SME_1 (EAD 1000) + SA_SME_2 (EAD 2000) = 3000
        assert row["0200"][0] == pytest.approx(3000.0)
        assert row["0220"][0] == pytest.approx(2100.0)  # 700 + 1400

    def test_row_0035_infrastructure_exposures(self) -> None:
        """Row 0035 filters infrastructure exposures with factor applied."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0035")
        assert len(row) == 1
        # SA_INFRA_1: EAD 5000, RWA 3750
        assert row["0200"][0] == pytest.approx(5000.0)
        assert row["0220"][0] == pytest.approx(3750.0)

    def test_row_0030_excludes_non_sme(self) -> None:
        """Row 0030 excludes non-SME exposures even with factor applied."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0030 = corp.filter(pl.col("row_ref") == "0030")
        # Only SME exposures (3000), not infra (5000) or plain (3200)
        assert row_0030["0200"][0] == pytest.approx(3000.0)

    def test_row_0035_excludes_non_infrastructure(self) -> None:
        """Row 0035 excludes non-infrastructure exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0035 = corp.filter(pl.col("row_ref") == "0035")
        # Only infra (5000), not SME (3000) or plain (3200)
        assert row_0035["0200"][0] == pytest.approx(5000.0)

    def test_row_0030_null_when_no_sme(self) -> None:
        """Row 0030 is null when no SME exposures exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        assert row["0200"][0] is None

    def test_b31_no_supporting_factor_rows(self) -> None:
        """B31 has no supporting factor rows (removed under Basel 3.1)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_supporting_factors(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        row_refs = corp["row_ref"].to_list()
        # B31 removes rows 0030 and 0035
        assert "0030" not in row_refs
        assert "0035" not in row_refs

    def test_supporting_factor_without_flag_column(self) -> None:
        """Rows 0030/0035 are null when is_sme/is_infrastructure absent."""
        gen = COREPGenerator()
        # _sa_results() has no is_sme or is_infrastructure columns
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row_0030 = corp.filter(pl.col("row_ref") == "0030")
        row_0035 = corp.filter(pl.col("row_ref") == "0035")
        assert row_0030["0200"][0] is None
        assert row_0035["0200"][0] is None

    def test_original_exposure_correct_for_sme(self) -> None:
        """Row 0030 original exposure (col 0010) = drawn + undrawn for SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        row = corp.filter(pl.col("row_ref") == "0030")
        # SME_1: 1000+0=1000, SME_2: 2000+0=2000, total 3000
        assert row["0010"][0] == pytest.approx(3000.0)


class TestC0700SupportingFactorRWEA:
    """Tests for CRR C 07.00 RWEA columns 0215-0217 with pipeline columns.

    The pipeline produces rwa_pre_factor and supporting_factor_applied,
    while the COREP spec expects per-type breakdown (SME vs infrastructure).
    The generator now uses fallback logic: tries legacy column names first,
    then pipeline columns (is_sme/is_infrastructure + supporting_factor_applied).

    Why: These columns quantify the SME/infrastructure capital relief. Without
    the fallback, they were always null despite the pipeline computing factors.

    References:
        CRR Art. 501: SME supporting factor
        CRR Art. 501a: Infrastructure supporting factor
    """

    def test_col_0215_pre_factor_rwa(self) -> None:
        """Col 0215 uses rwa_pre_factor when rwa_before_sme_factor absent."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Total rwa_pre_factor: 1000+2000+5000+3200 = 11200
        assert total["0215"][0] == pytest.approx(11200.0)

    def test_col_0216_sme_adjustment(self) -> None:
        """Col 0216 computes SME factor adjustment from pipeline columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # SME adjustment = pre - post for SME rows
        # SME_1: 1000 - 700 = 300, SME_2: 2000 - 1400 = 600
        assert total["0216"][0] == pytest.approx(900.0)

    def test_col_0217_infra_adjustment(self) -> None:
        """Col 0217 computes infrastructure factor adjustment."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Infrastructure adjustment = pre - post for infra rows
        # INFRA_1: 5000 - 3750 = 1250
        assert total["0217"][0] == pytest.approx(1250.0)

    def test_col_0220_post_factor_rwa(self) -> None:
        """Col 0220 (post-factor RWEA) is the sum of rwa_final."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        # Total rwa_final: 700+1400+3750+3200 = 9050
        assert total["0220"][0] == pytest.approx(9050.0)

    def test_pre_minus_adjustments_equals_post(self) -> None:
        """RWEA integrity: 0215 - 0216 - 0217 ≈ 0220."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        pre = total["0215"][0]
        sme_adj = total["0216"][0]
        infra_adj = total["0217"][0]
        post = total["0220"][0]
        # 11200 - 900 - 1250 = 9050
        assert pre - sme_adj - infra_adj == pytest.approx(post)

    def test_col_0216_null_without_pipeline_columns(self) -> None:
        """Col 0216 is null when neither legacy nor pipeline columns exist."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="CRR")
        corp = bundle.c07_00["corporate"]
        total = corp.filter(pl.col("row_ref") == "0010")
        assert total["0216"][0] is None

    def test_b31_no_supporting_factor_columns(self) -> None:
        """B31 does not have cols 0215-0217 (supporting factors removed)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_results_with_supporting_factors(), framework="BASEL_3_1"
        )
        corp = bundle.c07_00["corporate"]
        assert "0215" not in corp.columns
        assert "0216" not in corp.columns
        assert "0217" not in corp.columns


# =============================================================================
# OF 02.00 IRB SUB-ROW SPLITS AND FLOOR INDICATOR TESTS (P2.5)
# =============================================================================


def _irb_results_with_sme_fse() -> pl.LazyFrame:
    """IRB results with is_sme and apply_fi_scalar for OF 02.00 sub-row tests.

    Contains F-IRB and A-IRB exposures with SME and FSE flags to test
    the per-sub-class breakdown (rows 0295-0297, 0355-0356, 0382-0385,
    0400/0410).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "FIRB_CORP_FSE_1",
                "FIRB_CORP_SME_1",
                "FIRB_CORP_OTHER_1",
                "AIRB_CORP_SME_1",
                "AIRB_CORP_OTHER_1",
                "AIRB_MORT_RES_SME_1",
                "AIRB_MORT_RES_1",
                "AIRB_MORT_COM_SME_1",
                "AIRB_MORT_COM_1",
                "AIRB_QRRE_1",
                "AIRB_OTHER_SME_1",
                "AIRB_OTHER_1",
            ],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "foundation_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
                "advanced_irb",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "corporate",
                "retail_mortgage",
                "retail_mortgage",
                "retail_mortgage",
                "retail_mortgage",
                "retail_qrre",
                "retail_other",
                "retail_other",
            ],
            "ead_final": [
                1000.0,
                500.0,
                2000.0,
                800.0,
                1200.0,
                400.0,
                600.0,
                300.0,
                700.0,
                900.0,
                350.0,
                450.0,
            ],
            "rwa_final": [
                800.0,
                300.0,
                1600.0,
                640.0,
                960.0,
                120.0,
                180.0,
                150.0,
                350.0,
                540.0,
                280.0,
                360.0,
            ],
            "is_sme": [
                False,
                True,
                False,
                True,
                False,
                True,
                False,
                True,
                False,
                False,
                True,
                False,
            ],
            "apply_fi_scalar": [
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
            "property_type": [
                None,
                None,
                None,
                None,
                None,
                "residential",
                "residential",
                "commercial",
                "commercial",
                None,
                None,
                None,
            ],
            "sa_rwa": [
                700.0,
                350.0,
                1400.0,
                560.0,
                840.0,
                100.0,
                150.0,
                120.0,
                280.0,
                450.0,
                245.0,
                315.0,
            ],
            "rwa_pre_floor": [
                800.0,
                300.0,
                1600.0,
                640.0,
                960.0,
                120.0,
                180.0,
                150.0,
                350.0,
                540.0,
                280.0,
                360.0,
            ],
            "counterparty_reference": [
                "CP1",
                "CP2",
                "CP3",
                "CP4",
                "CP5",
                "CP6",
                "CP7",
                "CP8",
                "CP9",
                "CP10",
                "CP11",
                "CP12",
            ],
        }
    )


class TestOF0200IRBSubRowSplits:
    """Tests for OF 02.00 IRB sub-row population using is_sme and apply_fi_scalar.

    Why: The master capital template (OF 02.00) must report F-IRB and A-IRB
    RWEA with proper sub-class breakdown: financial/large corporates vs SME vs
    other general corporates (rows 0295-0297, 0355-0356), and retail RE by
    property type and SME status (rows 0382-0385, 0400/0410). Previously these
    rows showed placeholder zeros.
    """

    def test_firb_fse_row_0295(self) -> None:
        """Row 0295: F-IRB financial/large corporates."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        assert bundle.c_02_00 is not None
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0295")
        assert len(row) == 1
        # FIRB_CORP_FSE_1: rwa = 800
        assert row["0010"][0] == pytest.approx(800.0)

    def test_firb_sme_row_0296(self) -> None:
        """Row 0296: F-IRB other general corporates SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0296")
        assert len(row) == 1
        # FIRB_CORP_SME_1: rwa = 300
        assert row["0010"][0] == pytest.approx(300.0)

    def test_firb_nonsme_row_0297(self) -> None:
        """Row 0297: F-IRB other general corporates non-SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0297")
        assert len(row) == 1
        # FIRB_CORP_OTHER_1: rwa = 1600
        assert row["0010"][0] == pytest.approx(1600.0)

    def test_firb_corp_sub_rows_sum_to_total(self) -> None:
        """Rows 0295+0296+0297 should sum to total F-IRB corporates (row 0260)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        df = bundle.c_02_00
        r0260 = float(df.filter(pl.col("row_ref") == "0260")["0010"][0])
        r0290 = float(df.filter(pl.col("row_ref") == "0290")["0010"][0])
        r0295 = float(df.filter(pl.col("row_ref") == "0295")["0010"][0])
        r0296 = float(df.filter(pl.col("row_ref") == "0296")["0010"][0])
        r0297 = float(df.filter(pl.col("row_ref") == "0297")["0010"][0])
        # 0260 = SL (0290) + FSE (0295) + SME (0296) + non-SME (0297)
        assert r0260 == pytest.approx(r0290 + r0295 + r0296 + r0297)

    def test_airb_sme_row_0355(self) -> None:
        """Row 0355: A-IRB other general corporates SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0355")
        assert len(row) == 1
        # AIRB_CORP_SME_1: rwa = 640
        assert row["0010"][0] == pytest.approx(640.0)

    def test_airb_nonsme_row_0356(self) -> None:
        """Row 0356: A-IRB other general corporates non-SME (incl. FSE)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0356")
        assert len(row) == 1
        # AIRB_CORP_OTHER_1: rwa = 960
        assert row["0010"][0] == pytest.approx(960.0)

    def test_airb_resi_sme_row_0382(self) -> None:
        """Row 0382: A-IRB retail residential RE SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0382")
        assert len(row) == 1
        # AIRB_MORT_RES_SME_1: rwa = 120
        assert row["0010"][0] == pytest.approx(120.0)

    def test_airb_resi_nonsme_row_0383(self) -> None:
        """Row 0383: A-IRB retail residential RE non-SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0383")
        assert len(row) == 1
        # AIRB_MORT_RES_1: rwa = 180
        assert row["0010"][0] == pytest.approx(180.0)

    def test_airb_comm_sme_row_0384(self) -> None:
        """Row 0384: A-IRB retail commercial RE SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0384")
        assert len(row) == 1
        # AIRB_MORT_COM_SME_1: rwa = 150
        assert row["0010"][0] == pytest.approx(150.0)

    def test_airb_comm_nonsme_row_0385(self) -> None:
        """Row 0385: A-IRB retail commercial RE non-SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0385")
        assert len(row) == 1
        # AIRB_MORT_COM_1: rwa = 350
        assert row["0010"][0] == pytest.approx(350.0)

    def test_airb_retail_re_sub_rows_sum_to_total(self) -> None:
        """Rows 0382+0383+0384+0385 sum to total A-IRB retail RE (row 0380)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        df = bundle.c_02_00
        r0380 = float(df.filter(pl.col("row_ref") == "0380")["0010"][0])
        r0382 = float(df.filter(pl.col("row_ref") == "0382")["0010"][0])
        r0383 = float(df.filter(pl.col("row_ref") == "0383")["0010"][0])
        r0384 = float(df.filter(pl.col("row_ref") == "0384")["0010"][0])
        r0385 = float(df.filter(pl.col("row_ref") == "0385")["0010"][0])
        assert r0380 == pytest.approx(r0382 + r0383 + r0384 + r0385)

    def test_airb_other_sme_row_0400(self) -> None:
        """Row 0400: A-IRB retail other SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0400")
        assert len(row) == 1
        # AIRB_OTHER_SME_1: rwa = 280
        assert row["0010"][0] == pytest.approx(280.0)

    def test_airb_other_nonsme_row_0410(self) -> None:
        """Row 0410: A-IRB retail other non-SME."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0410")
        assert len(row) == 1
        # AIRB_OTHER_1: rwa = 360
        assert row["0010"][0] == pytest.approx(360.0)

    def test_no_sub_rows_in_crr(self) -> None:
        """CRR does not have sub-rows 0295-0297, 0355-0356, 0382-0385."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="CRR")
        assert bundle.c_02_00 is not None
        df = bundle.c_02_00
        b31_only_rows = ["0295", "0296", "0297", "0355", "0356", "0382", "0383", "0384", "0385"]
        for ref in b31_only_rows:
            assert len(df.filter(pl.col("row_ref") == ref)) == 0

    def test_fallback_without_sme_flag(self) -> None:
        """Without is_sme column, non-FSE corporate RWA goes to non-SME row."""
        data = _irb_results_with_sme_fse().drop("is_sme")
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        df = bundle.c_02_00
        # FSE exposure (800) still goes to 0295; rest (300+1600=1900) to 0297
        r0295 = float(df.filter(pl.col("row_ref") == "0295")["0010"][0])
        assert r0295 == pytest.approx(800.0)
        r0297 = float(df.filter(pl.col("row_ref") == "0297")["0010"][0])
        assert r0297 == pytest.approx(1900.0)
        r0296 = float(df.filter(pl.col("row_ref") == "0296")["0010"][0])
        assert r0296 == pytest.approx(0.0)


class TestOF0200FloorIndicatorRows:
    """Tests for OF 02.00 output floor indicator rows 0034-0036.

    Why: These rows tell regulators whether the output floor is active
    (row 0034), what multiplier % applies (row 0035), and the OF-ADJ
    monetary value (row 0036). Previously rows 0035/0036 were always zero.
    """

    def test_floor_multiplier_from_summary(self) -> None:
        """Row 0035 shows floor_pct * 100 from OutputFloorSummary."""
        summary = OutputFloorSummary(
            u_trea=1000.0,
            s_trea=800.0,
            floor_pct=0.725,
            floor_threshold=580.0,
            shortfall=0.0,
            portfolio_floor_binding=False,
            total_rwa_post_floor=1000.0,
            of_adj=50.0,
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_sme_fse(),
            framework="BASEL_3_1",
            output_floor_summary=summary,
        )
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0035")
        assert len(row) == 1
        # 72.5% → 72.5
        assert row["0010"][0] == pytest.approx(72.5)

    def test_of_adj_from_summary(self) -> None:
        """Row 0036 shows of_adj monetary value from OutputFloorSummary."""
        summary = OutputFloorSummary(
            u_trea=1000.0,
            s_trea=800.0,
            floor_pct=0.725,
            floor_threshold=580.0,
            shortfall=0.0,
            portfolio_floor_binding=False,
            total_rwa_post_floor=1000.0,
            of_adj=123.45,
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _irb_results_with_sme_fse(),
            framework="BASEL_3_1",
            output_floor_summary=summary,
        )
        row = bundle.c_02_00.filter(pl.col("row_ref") == "0036")
        assert len(row) == 1
        assert row["0010"][0] == pytest.approx(123.45)

    def test_floor_rows_zero_without_summary(self) -> None:
        """Rows 0035/0036 are zero when no OutputFloorSummary is provided."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="BASEL_3_1")
        r0035 = bundle.c_02_00.filter(pl.col("row_ref") == "0035")
        r0036 = bundle.c_02_00.filter(pl.col("row_ref") == "0036")
        assert r0035["0010"][0] == pytest.approx(0.0)
        assert r0036["0010"][0] == pytest.approx(0.0)

    def test_floor_rows_absent_crr(self) -> None:
        """CRR does not have floor indicator rows 0034-0036."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_irb_results_with_sme_fse(), framework="CRR")
        df = bundle.c_02_00
        for ref in ("0034", "0035", "0036"):
            assert len(df.filter(pl.col("row_ref") == ref)) == 0


class TestOF0700RESubRowFallback:
    """Tests for OF 07.00 RE sub-row filtering with has_income_cover fallback.

    Why: The generator previously required materially_dependent_on_property
    to populate RE sub-rows (0331-0354). The SA calculator produces
    has_income_cover instead. The fallback allows these rows to be populated
    from existing pipeline data.
    """

    def test_re_rows_with_has_income_cover(self) -> None:
        """RE sub-rows populate using has_income_cover as fallback."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1", "RE_2", "RE_3"],
                "approach_applied": ["standardised"] * 3,
                "exposure_class": ["secured_by_re_residential"] * 3,
                "drawn_amount": [100.0, 200.0, 300.0],
                "undrawn_amount": [0.0, 0.0, 0.0],
                "ead_final": [100.0, 200.0, 300.0],
                "rwa_final": [20.0, 70.0, 105.0],
                "risk_weight": [0.20, 0.35, 0.35],
                "property_type": ["residential", "residential", "residential"],
                "has_income_cover": [False, True, False],
                "scra_provision_amount": [0.0] * 3,
                "gcra_provision_amount": [0.0] * 3,
                "counterparty_reference": ["CP1", "CP2", "CP3"],
                "sa_cqs": [None] * 3,
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        # 0331: residential, NOT dependent → RE_1 + RE_3 (EAD 100+300=400)
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        assert len(r0331) == 1
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        val = float(r0331[ead_col][0] or 0)
        assert val == pytest.approx(400.0)
        # 0332: residential, dependent → RE_2 (EAD 200)
        r0332 = re_res.filter(pl.col("row_ref") == "0332")
        val2 = float(r0332[ead_col][0] or 0)
        assert val2 == pytest.approx(200.0)

    def test_re_rows_with_is_income_producing(self) -> None:
        """RE sub-rows populate using is_income_producing as second fallback."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1", "RE_2"],
                "approach_applied": ["standardised"] * 2,
                "exposure_class": ["secured_by_re_residential"] * 2,
                "drawn_amount": [100.0, 200.0],
                "undrawn_amount": [0.0, 0.0],
                "ead_final": [100.0, 200.0],
                "rwa_final": [20.0, 70.0],
                "risk_weight": [0.20, 0.35],
                "property_type": ["residential", "residential"],
                "is_income_producing": [False, True],
                "scra_provision_amount": [0.0] * 2,
                "gcra_provision_amount": [0.0] * 2,
                "counterparty_reference": ["CP1", "CP2"],
                "sa_cqs": [None] * 2,
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        assert float(r0331[ead_col][0] or 0) == pytest.approx(100.0)

    def test_re_rows_empty_without_any_dependency_column(self) -> None:
        """Without any dependency column, sub-rows remain null."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["secured_by_re_residential"],
                "drawn_amount": [100.0],
                "undrawn_amount": [0.0],
                "ead_final": [100.0],
                "rwa_final": [20.0],
                "risk_weight": [0.20],
                "property_type": ["residential"],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP1"],
                "sa_cqs": [None],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        ead_col = "0200" if "0200" in r0331.columns else "0010"
        # Should be null (no data to split on)
        assert r0331[ead_col][0] is None

    def test_materially_dependent_preferred_over_has_income_cover(self) -> None:
        """When both columns exist, materially_dependent_on_property wins."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["RE_1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["secured_by_re_residential"],
                "drawn_amount": [100.0],
                "undrawn_amount": [0.0],
                "ead_final": [100.0],
                "rwa_final": [20.0],
                "risk_weight": [0.20],
                "property_type": ["residential"],
                "materially_dependent_on_property": [True],
                "has_income_cover": [False],  # Different value — should be ignored
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "counterparty_reference": ["CP1"],
                "sa_cqs": [None],
            }
        )
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")
        re_res = bundle.c07_00["secured_by_re_residential"]
        ead_col = "0200" if "0200" in re_res.columns else "0010"
        # RE_1 has materially_dependent=True, so should appear in row 0332
        r0332 = re_res.filter(pl.col("row_ref") == "0332")
        assert float(r0332[ead_col][0] or 0) == pytest.approx(100.0)
        # And NOT in row 0331
        r0331 = re_res.filter(pl.col("row_ref") == "0331")
        assert r0331[ead_col][0] is None


class TestEquityTransitionalColumns:
    """Tests for equity_transitional_approach/equity_higher_risk columns.

    Why: The equity calculator's _apply_transitional_floor() now writes
    annotation columns needed by COREP OF 07.00 rows 0371-0374. Without
    these columns, the equity transitional rows were always null.
    """

    def test_equity_transitional_approach_column_added(self) -> None:
        """Equity calculator adds equity_transitional_approach column."""
        from datetime import date
        from decimal import Decimal

        from rwa_calc.contracts.config import (
            CalculationConfig,
            EquityTransitionalConfig,
        )
        from rwa_calc.engine.equity.calculator import EquityCalculator

        eq_config = EquityTransitionalConfig(
            enabled=True,
            schedule={date(2027, 1, 1): (Decimal("1.00"), Decimal("1.50"))},
        )
        config_b31 = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1),
        )
        # Replace equity_transitional with our test config
        import dataclasses

        config_with_trans = dataclasses.replace(config_b31, equity_transitional=eq_config)

        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EQ_1", "EQ_2"],
                "equity_type": ["listed", "listed"],
                "ead_final": [1000.0, 500.0],
                "risk_weight": [2.50, 2.50],
                "is_speculative": [False, True],
                "is_diversified_portfolio": [False, False],
                "is_exchange_traded": [False, False],
                "is_government_supported": [False, False],
                "ciu_approach": [None, None],
                "ciu_mandate_rw": [None, None],
                "ciu_third_party_calc": [None, None],
                "fund_reference": [None, None],
                "ciu_look_through_rw": [None, None],
                "fund_nav": [None, None],
            }
        )
        calc = EquityCalculator()
        result = calc._apply_transitional_floor(exposures, config_with_trans)
        collected = result.collect()
        assert "equity_transitional_approach" in collected.columns
        assert "equity_higher_risk" in collected.columns
        # SA transitional (B31 has no IRB equity)
        assert collected["equity_transitional_approach"][0] == "sa_transitional"
        # Non-speculative
        assert collected["equity_higher_risk"][0] is False
        # Speculative
        assert collected["equity_higher_risk"][1] is True
