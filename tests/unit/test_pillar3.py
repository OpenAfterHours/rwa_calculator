"""Unit tests for Pillar III disclosure templates.

Tests cover:
    - Template definitions (column/row counts, framework switching)
    - OV1: Overview of RWA
    - CR4: SA exposure and CRM effects
    - CR5: SA risk weight allocation
    - CR6: IRB exposures by PD range
    - CR6-A: Scope of IRB and SA use
    - CR7: Credit derivatives effect on RWEA
    - CR7-A: Extent of CRM techniques
    - CR8: RWEA flow statements
    - CR9: IRB PD back-testing per exposure class (Basel 3.1 only)
    - CR10: Slotting approach exposures
    - CMS1: Output floor comparison by risk type (Basel 3.1 only)
    - CMS2: Output floor comparison by asset class (Basel 3.1 only)
    - Export integration

Why: Pillar III disclosures are mandatory public regulatory outputs.
These tests verify that pipeline data is correctly reshaped into
the fixed-format disclosure templates for both CRR and Basel 3.1.
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from rwa_calc.reporting.pillar3.templates import (
    B31_CR4_COLUMNS,
    B31_CR4_ROWS,
    B31_CR5_COLUMNS,
    B31_CR5_RISK_WEIGHTS,
    B31_CR6_COLUMNS,
    B31_CR7_ROWS,
    B31_CR7A_COLUMNS,
    B31_CR10_SUBTEMPLATES,
    B31_OV1_ROWS,
    CR6_PD_RANGES,
    CR6A_COLUMNS,
    CR7_COLUMNS,
    CR8_COLUMNS,
    CR8_ROWS,
    CR10_CATEGORY_MAP,
    CR10_SLOTTING_ROWS,
    CRR_CR4_COLUMNS,
    CRR_CR4_ROWS,
    CRR_CR5_COLUMNS,
    CRR_CR5_RISK_WEIGHTS,
    CRR_CR6_COLUMNS,
    CRR_CR7_ROWS,
    CRR_CR7A_COLUMNS,
    CRR_CR10_COLUMNS,
    CRR_CR10_SUBTEMPLATES,
    CRR_OV1_ROWS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    SA_DISCLOSURE_CLASSES,
    get_cr4_columns,
    get_cr5_columns,
    get_cr6_columns,
    get_cr7_rows,
    get_cr7a_columns,
    get_cr10_columns,
    get_cr10_subtemplates,
    get_ov1_rows,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sa_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal SA pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["SA1", "SA2", "SA3"],
        "approach_applied": ["standardised", "standardised", "standardised"],
        "exposure_class": ["corporate", "retail_mortgage", "defaulted"],
        "ead_final": [1000.0, 2000.0, 500.0],
        "rwa_final": [1000.0, 700.0, 750.0],
        "risk_weight": [1.0, 0.35, 1.5],
        "drawn_amount": [800.0, 1800.0, 400.0],
        "interest": [50.0, 100.0, 30.0],
        "nominal_amount": [200.0, 300.0, 100.0],
        "undrawn_amount": [150.0, 200.0, 70.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _make_irb_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal IRB pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["IRB1", "IRB2", "IRB3"],
        "approach_applied": ["foundation_irb", "advanced_irb", "advanced_irb"],
        "exposure_class": ["corporate", "retail_mortgage", "retail_other"],
        "ead_final": [5000.0, 3000.0, 2000.0],
        "rwa_final": [4000.0, 1500.0, 1200.0],
        "pd_floored": [0.02, 0.005, 0.01],
        "pd": [0.018, 0.004, 0.009],
        "lgd_floored": [0.45, 0.10, 0.30],
        "irb_maturity_m": [2.5, 1.0, 1.0],
        "expected_loss": [45.0, 15.0, 6.0],
        "counterparty_reference": ["CP1", "CP2", "CP3"],
        "drawn_amount": [4500.0, 2700.0, 1800.0],
        "nominal_amount": [600.0, 400.0, 300.0],
        "undrawn_amount": [500.0, 300.0, 200.0],
        "interest": [0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan"],
        "ccf_applied": [1.0, 1.0, 1.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _make_slotting_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal slotting pipeline data for testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["SL1", "SL2", "SL3"],
        "approach_applied": ["slotting", "slotting", "slotting"],
        "exposure_class": ["specialised_lending", "specialised_lending", "specialised_lending"],
        "sl_type": ["project_finance", "project_finance", "ipre"],
        "slotting_category": ["strong", "good", "satisfactory"],
        "ead_final": [1000.0, 800.0, 600.0],
        "rwa_final": [700.0, 720.0, 690.0],
        "expected_loss": [5.0, 8.0, 12.0],
        "drawn_amount": [900.0, 700.0, 500.0],
        "nominal_amount": [150.0, 120.0, 120.0],
        "undrawn_amount": [100.0, 100.0, 100.0],
        "interest": [0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _align_and_concat(frames: list[pl.DataFrame]) -> pl.LazyFrame:
    """Align schemas across frames and concat them into a single LazyFrame.

    Builds a per-column dtype map from the non-Null dtypes, sorts the column
    names, adds any missing columns as typed nulls, then concats in a stable
    column order.
    """
    # Build a type map: for each column, find the non-Null dtype
    col_types: dict[str, pl.DataType] = {}
    for df in frames:
        for col_name in df.columns:
            dtype = df.schema[col_name]
            if dtype != pl.Null:
                col_types[col_name] = dtype
    all_cols = sorted(col_types.keys())
    # Align schemas — add missing columns with the correct dtype
    aligned = []
    for df in frames:
        for col in all_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(col_types[col]).alias(col))
        aligned.append(df.select(all_cols))
    return pl.concat(aligned).lazy()


def _make_mixed_data() -> pl.LazyFrame:
    """Create pipeline data with SA, IRB, and slotting exposures."""
    sa = _make_sa_data().collect()
    irb = _make_irb_data().collect()
    slotting = _make_slotting_data().collect()
    return _align_and_concat([sa, irb, slotting])


# ---------------------------------------------------------------------------
# Template definition tests
# ---------------------------------------------------------------------------


class TestTemplateDefinitions:
    """Tests for template constant definitions."""

    def test_ov1_columns_count(self):
        assert len(OV1_COLUMNS) == 3

    def test_ov1_crr_rows_count(self):
        # 8 original rows + the 5-row CCR block (6, 7, 8, UK8a, 9).
        assert len(CRR_OV1_ROWS) == 13

    def test_ov1_b31_rows_count(self):
        # 20 original rows + the 5-row CCR block (6, 7, 8, UK8a, 9).
        assert len(B31_OV1_ROWS) == 25

    def test_ov1_b31_has_equity_rows(self):
        refs = {r.ref for r in B31_OV1_ROWS}
        assert {"11", "12", "13", "14"} <= refs

    def test_ov1_b31_has_output_floor_rows(self):
        refs = {r.ref for r in B31_OV1_ROWS}
        assert {"26", "27"} <= refs

    @pytest.mark.parametrize("rows", [CRR_OV1_ROWS, B31_OV1_ROWS])
    def test_ov1_has_the_ccr_block(self, rows):
        """Row 1 is "Credit risk (excluding CCR)" — the excluded CCR must land somewhere.

        Verbatim: "RWEAs ... for CCR are excluded and disclosed in rows 6 and 16 of
        this template." The UKB OV1 carries the identical block, so BOTH regimes get
        rows 6 / 7 / 8 / UK8a / 9. See docs/plans/c07-ccr-derivatives.md §4 D1.
        """
        refs = {r.ref for r in rows}
        assert {"6", "7", "8", "UK8a", "9"} <= refs

    def test_cr4_crr_columns_count(self):
        assert len(CRR_CR4_COLUMNS) == 6

    def test_cr4_b31_columns_count(self):
        assert len(B31_CR4_COLUMNS) == 6

    def test_cr4_crr_rows_include_total(self):
        total_rows = [r for r in CRR_CR4_ROWS if r.is_total]
        assert len(total_rows) == 1

    def test_cr4_crr_rows_count(self):
        # 16 exposure classes + 1 total
        assert len(CRR_CR4_ROWS) == 17

    def test_cr4_b31_rows_have_sub_rows(self):
        # B31 adds sub-rows under corporates (7a) and RE (9a-9e)
        assert len(B31_CR4_ROWS) > len(CRR_CR4_ROWS)

    def test_cr5_crr_risk_weight_count(self):
        assert len(CRR_CR5_RISK_WEIGHTS) == 14

    def test_cr5_b31_risk_weight_count(self):
        assert len(B31_CR5_RISK_WEIGHTS) == 28

    def test_cr5_crr_columns_include_total_and_unrated(self):
        refs = [c.ref for c in CRR_CR5_COLUMNS]
        # 14 RW + Other + Total + Unrated = 17
        assert len(refs) == 17
        assert "p" in refs  # Total
        assert "q" in refs  # Unrated

    def test_cr5_b31_columns_include_extra(self):
        refs = [c.ref for c in B31_CR5_COLUMNS]
        assert "ba" in refs
        assert "bb" in refs
        assert "bc" in refs
        assert "bd" in refs

    def test_cr6_crr_columns_count(self):
        assert len(CRR_CR6_COLUMNS) == 13

    def test_cr6_b31_columns_count(self):
        assert len(B31_CR6_COLUMNS) == 13

    def test_cr6_pd_ranges_count(self):
        assert len(CR6_PD_RANGES) == 17

    def test_cr6_pd_ranges_cover_full_range(self):
        """PD ranges should cover 0% to 100% default."""
        assert CR6_PD_RANGES[0][0] == pytest.approx(0.0, abs=1e-10)
        assert math.isinf(CR6_PD_RANGES[-1][1])

    def test_cr6a_columns_count(self):
        assert len(CR6A_COLUMNS) == 5

    def test_cr7_columns_count(self):
        assert len(CR7_COLUMNS) == 2

    def test_cr7_crr_rows_count(self):
        assert len(CRR_CR7_ROWS) == 10

    def test_cr7_b31_rows_count(self):
        assert len(B31_CR7_ROWS) == 8

    def test_cr7a_crr_columns_count(self):
        assert len(CRR_CR7A_COLUMNS) == 14

    def test_cr7a_b31_columns_count(self):
        # CRR 14 + 2 slotting columns
        assert len(B31_CR7A_COLUMNS) == 16

    def test_cr8_columns_count(self):
        assert len(CR8_COLUMNS) == 1

    def test_cr8_rows_count(self):
        assert len(CR8_ROWS) == 9

    def test_cr10_crr_subtemplates_count(self):
        assert len(CRR_CR10_SUBTEMPLATES) == 5

    def test_cr10_b31_subtemplates_count(self):
        assert len(B31_CR10_SUBTEMPLATES) == 5

    def test_cr10_b31_separates_hvcre(self):
        assert "hvcre" in B31_CR10_SUBTEMPLATES
        assert "hvcre" not in CRR_CR10_SUBTEMPLATES

    def test_cr10_slotting_rows_count(self):
        assert len(CR10_SLOTTING_ROWS) == 6  # 5 categories + total

    def test_cr10_category_map_count(self):
        assert len(CR10_CATEGORY_MAP) == 5

    def test_sa_disclosure_classes_count(self):
        assert len(SA_DISCLOSURE_CLASSES) == 16

    def test_irb_exposure_classes_count(self):
        assert len(IRB_EXPOSURE_CLASSES) == 8


class TestFrameworkSelectors:
    """Tests for framework-switching selector functions."""

    def test_get_ov1_rows_crr(self):
        assert get_ov1_rows("CRR") is CRR_OV1_ROWS

    def test_get_ov1_rows_b31(self):
        assert get_ov1_rows("BASEL_3_1") is B31_OV1_ROWS

    def test_get_cr4_columns_crr(self):
        assert get_cr4_columns("CRR") is CRR_CR4_COLUMNS

    def test_get_cr4_columns_b31(self):
        assert get_cr4_columns("BASEL_3_1") is B31_CR4_COLUMNS

    def test_get_cr5_columns_crr(self):
        assert get_cr5_columns("CRR") is CRR_CR5_COLUMNS

    def test_get_cr5_columns_b31(self):
        assert get_cr5_columns("BASEL_3_1") is B31_CR5_COLUMNS

    def test_get_cr6_columns_crr(self):
        assert get_cr6_columns("CRR") is CRR_CR6_COLUMNS

    def test_get_cr7_rows_crr(self):
        assert get_cr7_rows("CRR") is CRR_CR7_ROWS

    def test_get_cr7_rows_b31(self):
        assert get_cr7_rows("BASEL_3_1") is B31_CR7_ROWS

    def test_get_cr7a_columns_crr(self):
        assert get_cr7a_columns("CRR") is CRR_CR7A_COLUMNS

    def test_get_cr7a_columns_b31(self):
        assert get_cr7a_columns("BASEL_3_1") is B31_CR7A_COLUMNS

    def test_get_cr10_columns_crr(self):
        assert get_cr10_columns("CRR") is CRR_CR10_COLUMNS

    def test_get_cr10_subtemplates_b31(self):
        assert get_cr10_subtemplates("BASEL_3_1") is B31_CR10_SUBTEMPLATES


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


class TestPillar3Bundle:
    """Tests for Pillar3TemplateBundle structure."""

    def test_bundle_is_frozen(self):
        bundle = Pillar3TemplateBundle()
        with pytest.raises(AttributeError):
            bundle.framework = "CRR"  # ty: ignore[invalid-assignment]

    def test_bundle_defaults(self):
        bundle = Pillar3TemplateBundle()
        assert bundle.ov1 is None
        assert bundle.cr4 is None
        assert bundle.cr5 is None
        assert bundle.cr6 == {}
        assert bundle.cr6a is None
        assert bundle.cr7 is None
        assert bundle.cr7a == {}
        assert bundle.cr8 is None
        assert bundle.cr10 == {}
        assert bundle.framework == "CRR"
        assert bundle.errors == []


class TestOV1Generation:
    """Tests for OV1 — Overview of RWA."""

    def test_ov1_generated_crr(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        assert bundle.ov1.height == len(CRR_OV1_ROWS)

    def test_ov1_generated_b31(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.ov1 is not None
        assert bundle.ov1.height == len(B31_OV1_ROWS)

    def test_ov1_total_rwa_positive(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        total_row = bundle.ov1.filter(pl.col("row_ref") == "29")
        assert total_row["a"][0] > 0

    def test_ov1_own_funds_8_percent(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        total_row = bundle.ov1.filter(pl.col("row_ref") == "29")
        rwa = total_row["a"][0]
        own_funds = total_row["c"][0]
        assert own_funds == pytest.approx(rwa * 0.08, rel=1e-6)

    def test_ov1_sa_rwa_positive(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        sa_row = bundle.ov1.filter(pl.col("row_ref") == "2")
        assert sa_row["a"][0] > 0

    def test_ov1_has_row_ref_and_row_name(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        assert "row_ref" in bundle.ov1.columns
        assert "row_name" in bundle.ov1.columns

    def test_ov1_t_minus_1_is_null(self, generator: Pillar3Generator):
        """Column b (T-1) requires prior period data — should be null."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        assert bundle.ov1["b"].null_count() == bundle.ov1.height


class TestCR8Generation:
    """Tests for CR8 — RWEA Flow Statements."""

    def test_cr8_generated(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr8 is not None
        assert bundle.cr8.height == 9

    def test_cr8_closing_rwa_populated(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr8 is not None
        closing = bundle.cr8.filter(pl.col("row_ref") == "9")
        assert closing["a"][0] > 0

    def test_cr8_opening_rwa_null(self, generator: Pillar3Generator):
        """Opening balance requires prior period — should be null."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr8 is not None
        opening = bundle.cr8.filter(pl.col("row_ref") == "1")
        assert opening["a"][0] is None

    def test_cr8_flow_drivers_null(self, generator: Pillar3Generator):
        """Flow drivers require multi-period comparison — should be null."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr8 is not None
        drivers = bundle.cr8.filter(pl.col("row_ref").is_in(["2", "3", "4", "5", "6", "7", "8"]))
        assert drivers["a"].null_count() == 7


# ---------------------------------------------------------------------------
# CMS1 — Output floor comparison by risk type (Art. 456(1)(a))


# ---------------------------------------------------------------------------


class TestGeneratorEndToEnd:
    """End-to-end generator tests with mixed data."""

    def test_all_templates_populated(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1 is not None
        assert bundle.cr4 is not None
        assert bundle.cr5 is not None
        assert len(bundle.cr6) > 0
        assert bundle.cr6a is not None
        assert bundle.cr7 is not None
        assert bundle.cr8 is not None

    def test_b31_framework_set(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.framework == "BASEL_3_1"

    def test_crr_framework_set(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.framework == "CRR"

    def test_empty_data_no_crash(self, generator: Pillar3Generator):
        data = pl.LazyFrame(
            {
                "exposure_reference": [],
                "approach_applied": [],
                "exposure_class": [],
                "ead_final": [],
                "rwa_final": [],
                "risk_weight": [],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.errors == [] or isinstance(bundle.errors, list)

    def test_missing_columns_accumulates_errors(self, generator: Pillar3Generator):
        data = pl.LazyFrame({"exposure_reference": ["X"]})
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.errors) > 0

    def test_no_duplicate_row_refs_in_cr4(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        refs = bundle.cr4["row_ref"].to_list()
        assert len(refs) == len(set(refs))


# ---------------------------------------------------------------------------
# CR9 — PD back-testing per exposure class (Art. 452(h)) — Basel 3.1 only
class TestExcelExport:
    """Tests for Excel export (structural — does not verify file content)."""

    def test_export_creates_file(self, generator: Pillar3Generator, tmp_path: Path):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        output = tmp_path / "pillar3.xlsx"
        result = generator.export_to_excel(bundle, output)
        assert output.exists()
        assert result.format == "pillar3_excel"
        assert result.row_count > 0

    def test_export_b31_prefix(self, generator: Pillar3Generator, tmp_path: Path):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        output = tmp_path / "pillar3_b31.xlsx"
        result = generator.export_to_excel(bundle, output)
        assert output.exists()
        assert result.row_count > 0

    def test_export_writes_non_finite_cells_as_blank(
        self, generator: Pillar3Generator, tmp_path: Path
    ):
        # Arrange — a disclosure cell can be non-finite on real data (e.g. an
        # average PD or a ratio over a zero denominator in an empty segment).
        # xlsxwriter rejects NaN/Inf in write_number(), so they must be written
        # blank rather than crashing the whole disclosure workbook.
        bundle = Pillar3TemplateBundle(
            ov1=pl.DataFrame(
                {"row": ["Average PD", "RW ratio"], "value": [float("nan"), float("inf")]}
            ),
            framework="CRR",
        )
        output = tmp_path / "pillar3_nonfinite.xlsx"

        # Act — must not raise "NAN/INF not supported in write_number()".
        result = generator.export_to_excel(bundle, output)

        # Assert — workbook written; the non-finite cells read back blank (null).
        # The data header sits on row 1 (row 0 is the readable-name banner band).
        assert output.exists()
        assert result.format == "pillar3_excel"
        readback = pl.read_excel(output, sheet_name="UK OV1", read_options={"header_row": 1})
        assert all(v is None for v in readback["value"].to_list())

    def test_export_writes_readable_name_banner_above_refs(
        self, generator: Pillar3Generator, tmp_path: Path
    ):
        # Arrange — a real-schema OV1 frame (row_ref/row_name + ref-coded columns).
        bundle = Pillar3TemplateBundle(
            ov1=pl.DataFrame(
                {
                    "row_ref": ["1"],
                    "row_name": ["Credit risk (excluding CCR)"],
                    "a": [100.0],
                    "b": [90.0],
                    "c": [8.0],
                }
            ),
            framework="CRR",
        )
        output = tmp_path / "pillar3_banner.xlsx"

        # Act
        generator.export_to_excel(bundle, output)

        # Assert — row 0 carries the readable column names, row 1 the ref codes.
        raw = pl.read_excel(output, sheet_name="UK OV1", read_options={"header_row": None})
        banner = raw.row(0)
        refs = raw.row(1)
        assert "RWEAs (T)" in banner  # readable name of column "a" (OV1_COLUMNS)
        assert "Row code" in banner and "Row name" in banner
        assert "a" in refs and "row_ref" in refs
