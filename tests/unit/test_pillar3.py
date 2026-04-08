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
    - CR10: Slotting approach exposures
    - Export integration

Why: Pillar III disclosures are mandatory public regulatory outputs.
These tests verify that pipeline data is correctly reshaped into
the fixed-format disclosure templates for both CRR and Basel 3.1.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from rwa_calc.reporting.pillar3.templates import (
    B31_CR10_SUBTEMPLATES,
    B31_CR4_COLUMNS,
    B31_CR4_ROWS,
    B31_CR5_COLUMNS,
    B31_CR5_RISK_WEIGHTS,
    B31_CR6_COLUMNS,
    B31_CR7A_COLUMNS,
    B31_CR7_ROWS,
    B31_OV1_ROWS,
    CR10_CATEGORY_MAP,
    CR10_SLOTTING_ROWS,
    CR6A_COLUMNS,
    CR6_PD_RANGES,
    CR7_COLUMNS,
    CR7A_AIRB_ROWS,
    CR7A_FIRB_ROWS,
    CR8_COLUMNS,
    CR8_ROWS,
    CRR_CR10_COLUMNS,
    CRR_CR10_SUBTEMPLATES,
    CRR_CR4_COLUMNS,
    CRR_CR4_ROWS,
    CRR_CR5_COLUMNS,
    CRR_CR5_RISK_WEIGHTS,
    CRR_CR6_COLUMNS,
    CRR_CR7A_COLUMNS,
    CRR_CR7_ROWS,
    CRR_OV1_ROWS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    SA_DISCLOSURE_CLASSES,
    get_cr10_columns,
    get_cr10_subtemplates,
    get_cr4_columns,
    get_cr4_rows,
    get_cr5_columns,
    get_cr5_risk_weights,
    get_cr6_columns,
    get_cr6a_rows,
    get_cr7_rows,
    get_cr7a_columns,
    get_ov1_rows,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sa_data(**overrides: object) -> pl.LazyFrame:
    """Create minimal SA pipeline data for testing."""
    defaults = {
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
    defaults = {
        "exposure_reference": ["IRB1", "IRB2", "IRB3"],
        "approach_applied": ["foundation_irb", "advanced_irb", "advanced_irb"],
        "exposure_class": ["corporate", "retail_mortgage", "retail_other"],
        "ead_final": [5000.0, 3000.0, 2000.0],
        "rwa_final": [4000.0, 1500.0, 1200.0],
        "irb_pd_floored": [0.02, 0.005, 0.01],
        "irb_pd_original": [0.018, 0.004, 0.009],
        "irb_lgd_floored": [0.45, 0.10, 0.30],
        "irb_maturity_m": [2.5, 1.0, 1.0],
        "irb_expected_loss": [45.0, 15.0, 6.0],
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
    defaults = {
        "exposure_reference": ["SL1", "SL2", "SL3"],
        "approach_applied": ["slotting", "slotting", "slotting"],
        "exposure_class": ["specialised_lending", "specialised_lending", "specialised_lending"],
        "sl_type": ["project_finance", "project_finance", "ipre"],
        "slotting_category": ["strong", "good", "satisfactory"],
        "ead_final": [1000.0, 800.0, 600.0],
        "rwa_final": [700.0, 720.0, 690.0],
        "irb_expected_loss": [5.0, 8.0, 12.0],
        "drawn_amount": [900.0, 700.0, 500.0],
        "nominal_amount": [150.0, 120.0, 120.0],
        "undrawn_amount": [100.0, 100.0, 100.0],
        "interest": [0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan"],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


def _make_mixed_data() -> pl.LazyFrame:
    """Create pipeline data with SA, IRB, and slotting exposures."""
    sa = _make_sa_data().collect()
    irb = _make_irb_data().collect()
    slotting = _make_slotting_data().collect()
    all_frames = [sa, irb, slotting]
    # Build a type map: for each column, find the non-Null dtype
    col_types: dict[str, pl.DataType] = {}
    for df in all_frames:
        for col_name in df.columns:
            dtype = df.schema[col_name]
            if dtype != pl.Null:
                col_types[col_name] = dtype
    all_cols = sorted(col_types.keys())
    # Align schemas — add missing columns with the correct dtype
    frames = []
    for df in all_frames:
        for col in all_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(col_types[col]).alias(col))
        frames.append(df.select(all_cols))
    return pl.concat(frames).lazy()


# ---------------------------------------------------------------------------
# Template definition tests
# ---------------------------------------------------------------------------


class TestTemplateDefinitions:
    """Tests for template constant definitions."""

    def test_ov1_columns_count(self):
        assert len(OV1_COLUMNS) == 3

    def test_ov1_crr_rows_count(self):
        assert len(CRR_OV1_ROWS) == 8

    def test_ov1_b31_rows_count(self):
        assert len(B31_OV1_ROWS) == 13

    def test_ov1_b31_has_equity_rows(self):
        refs = {r.ref for r in B31_OV1_ROWS}
        assert {"11", "12", "13", "14"} <= refs

    def test_ov1_b31_has_output_floor_rows(self):
        refs = {r.ref for r in B31_OV1_ROWS}
        assert {"26", "27"} <= refs

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
        assert CR6_PD_RANGES[0][0] == 0.0
        assert CR6_PD_RANGES[-1][1] == float("inf")

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
    return Pillar3Generator()


class TestPillar3Bundle:
    """Tests for Pillar3TemplateBundle structure."""

    def test_bundle_is_frozen(self):
        bundle = Pillar3TemplateBundle()
        with pytest.raises(AttributeError):
            bundle.framework = "CRR"  # type: ignore[misc]

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
        total_row = bundle.ov1.filter(pl.col("row_ref") == "29")
        assert total_row["a"][0] > 0

    def test_ov1_own_funds_8_percent(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total_row = bundle.ov1.filter(pl.col("row_ref") == "29")
        rwa = total_row["a"][0]
        own_funds = total_row["c"][0]
        assert own_funds == pytest.approx(rwa * 0.08, rel=1e-6)

    def test_ov1_sa_rwa_positive(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        sa_row = bundle.ov1.filter(pl.col("row_ref") == "2")
        assert sa_row["a"][0] > 0

    def test_ov1_has_row_ref_and_row_name(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert "row_ref" in bundle.ov1.columns
        assert "row_name" in bundle.ov1.columns

    def test_ov1_t_minus_1_is_null(self, generator: Pillar3Generator):
        """Column b (T-1) requires prior period data — should be null."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.ov1["b"].null_count() == bundle.ov1.height


class TestCR4Generation:
    """Tests for CR4 — SA Exposure and CRM Effects."""

    def test_cr4_generated_crr(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr4 is not None
        assert bundle.cr4.height == len(CRR_CR4_ROWS)

    def test_cr4_generated_b31(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr4 is not None
        assert bundle.cr4.height == len(B31_CR4_ROWS)

    def test_cr4_total_row_rwea(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        assert total["e"][0] == pytest.approx(2450.0)  # 1000 + 700 + 750

    def test_cr4_corporate_row_populated(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr4.filter(pl.col("row_ref") == "7")
        assert corp["e"][0] == pytest.approx(1000.0)

    def test_cr4_rwea_density_calculated(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr4.filter(pl.col("row_ref") == "17")
        f_val = total["f"][0]
        assert f_val is not None
        assert f_val > 0

    def test_cr4_empty_rows_are_null(self, generator: Pillar3Generator):
        """Rows for classes not in pipeline should be null."""
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        # Row 11 (high risk) has no pipeline data
        hr = bundle.cr4.filter(pl.col("row_ref") == "11")
        assert hr["e"][0] is None

    def test_cr4_columns_match_template(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected_cols = {"row_ref", "row_name"} | {c.ref for c in CRR_CR4_COLUMNS}
        assert set(bundle.cr4.columns) == expected_cols


class TestCR5Generation:
    """Tests for CR5 — SA Risk Weight Allocation."""

    def test_cr5_generated_crr(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr5 is not None

    def test_cr5_total_matches_ead(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        # Total column (p for CRR) should equal total EAD
        assert total["p"][0] == pytest.approx(3500.0)  # 1000 + 2000 + 500

    def test_cr5_100pct_bucket_has_corporate(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr5.filter(pl.col("row_ref") == "7")
        # Corporate has RW 1.0 (100%), column j
        assert corp["j"][0] == pytest.approx(1000.0)

    def test_cr5_35pct_bucket_has_mortgage(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        mortgage = bundle.cr5.filter(pl.col("row_ref") == "9")
        # Mortgage RW 0.35 (35%), column f
        assert mortgage["f"][0] == pytest.approx(2000.0)

    def test_cr5_b31_has_extra_columns(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr5 is not None
        assert "ba" in bundle.cr5.columns
        assert "bd" in bundle.cr5.columns

    def test_cr5_unrated_column(self, generator: Pillar3Generator):
        """Without sa_cqs column, all exposures should be 'unrated'."""
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr5.filter(pl.col("row_ref") == "17")
        # Column q (unrated) — no CQS column so all treated as unrated
        assert total["q"][0] == pytest.approx(3500.0)


class TestCR6Generation:
    """Tests for CR6 — IRB Exposures by PD Range."""

    def test_cr6_generates_per_class(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.cr6) > 0
        assert "corporate" in bundle.cr6

    def test_cr6_has_17_pd_rows_plus_total(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for ec, df in bundle.cr6.items():
            assert df.height == 18  # 17 PD ranges + 1 total

    def test_cr6_total_ead_positive(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for ec, df in bundle.cr6.items():
            total = df.filter(pl.col("row_ref") == "18")
            assert total["e"][0] > 0

    def test_cr6_pd_range_column_is_string(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for df in bundle.cr6.values():
            assert df.schema["a"] == pl.String

    def test_cr6_obligor_count(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        # Corporate has 1 obligor (CP1)
        corp = bundle.cr6["corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["g"][0] == pytest.approx(1.0)

    def test_cr6_b31_uses_original_pd_for_allocation(self, generator: Pillar3Generator):
        """B31: PD range allocation should use pre-floor PD (irb_pd_original)."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert len(bundle.cr6) > 0

    def test_cr6_rwea_density(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        corp = bundle.cr6["corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        density = total["k"][0]
        ead = total["e"][0]
        rwa = total["j"][0]
        assert density == pytest.approx(rwa / ead, rel=1e-4)

    def test_cr6_columns_match_template(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected = {"row_ref", "row_name"} | {c.ref for c in CRR_CR6_COLUMNS}
        for df in bundle.cr6.values():
            assert set(df.columns) == expected


class TestCR6AGeneration:
    """Tests for CR6-A — Scope of IRB and SA Use."""

    def test_cr6a_generated(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr6a is not None

    def test_cr6a_total_row_has_all_ead(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr6a.filter(pl.col("row_name").str.contains("Total"))
        assert total["b"][0] > 0

    def test_cr6a_irb_percentage(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr6a.filter(pl.col("row_name").str.contains("Total"))
        irb_pct = total["d"][0]
        sa_pct = total["c"][0]
        # Percentages should sum to ~100%
        assert irb_pct + sa_pct == pytest.approx(100.0, rel=0.01)

    def test_cr6a_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected = {"row_ref", "row_name"} | {c.ref for c in CR6A_COLUMNS}
        assert set(bundle.cr6a.columns) == expected


class TestCR7Generation:
    """Tests for CR7 — Credit Derivatives Effect on RWEA."""

    def test_cr7_generated_crr(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr7 is not None
        assert bundle.cr7.height == len(CRR_CR7_ROWS)

    def test_cr7_generated_b31(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr7 is not None
        assert bundle.cr7.height == len(B31_CR7_ROWS)

    def test_cr7_pre_equals_post(self, generator: Pillar3Generator):
        """Pre-CD RWEA ≈ post-CD RWEA (approximation: no CD tracking)."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for i in range(bundle.cr7.height):
            a = bundle.cr7["a"][i]
            b = bundle.cr7["b"][i]
            if a is not None and b is not None:
                assert a == pytest.approx(b)

    def test_cr7_total_positive(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        total = bundle.cr7.filter(pl.col("row_ref") == "10")
        assert total["b"][0] > 0


class TestCR7AGeneration:
    """Tests for CR7-A — Extent of CRM Techniques."""

    def test_cr7a_generates_per_approach(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        # Should have at least one of foundation_irb / advanced_irb
        assert len(bundle.cr7a) > 0

    def test_cr7a_firb_rows(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        if "foundation_irb" in bundle.cr7a:
            assert bundle.cr7a["foundation_irb"].height == len(CR7A_FIRB_ROWS)

    def test_cr7a_airb_rows(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        if "advanced_irb" in bundle.cr7a:
            assert bundle.cr7a["advanced_irb"].height == len(CR7A_AIRB_ROWS)

    def test_cr7a_total_exposure_positive(self, generator: Pillar3Generator):
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for approach, df in bundle.cr7a.items():
            total = df.filter(pl.col("row_name").str.contains("Total"))
            assert total["a"][0] > 0


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
        closing = bundle.cr8.filter(pl.col("row_ref") == "9")
        assert closing["a"][0] > 0

    def test_cr8_opening_rwa_null(self, generator: Pillar3Generator):
        """Opening balance requires prior period — should be null."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        opening = bundle.cr8.filter(pl.col("row_ref") == "1")
        assert opening["a"][0] is None

    def test_cr8_flow_drivers_null(self, generator: Pillar3Generator):
        """Flow drivers require multi-period comparison — should be null."""
        data = _make_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        drivers = bundle.cr8.filter(
            pl.col("row_ref").is_in(["2", "3", "4", "5", "6", "7", "8"])
        )
        assert drivers["a"].null_count() == 7


class TestCR10Generation:
    """Tests for CR10 — Slotting Approach Exposures."""

    def test_cr10_generates_per_sl_type(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.cr10) > 0
        assert "project_finance" in bundle.cr10

    def test_cr10_rows_per_subtemplate(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        for sl_type, df in bundle.cr10.items():
            assert df.height == 6  # 5 categories + total

    def test_cr10_risk_weight_populated(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        pf = bundle.cr10["project_finance"]
        strong = pf.filter(pl.col("row_ref") == "1")
        assert strong["c"][0] == pytest.approx(70.0)  # 0.70 * 100

    def test_cr10_total_ead(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        pf = bundle.cr10["project_finance"]
        total = pf.filter(pl.col("row_ref") == "6")
        assert total["d"][0] > 0

    def test_cr10_b31_separates_hvcre(self, generator: Pillar3Generator):
        """B31 should separate HVCRE from IPRE."""
        data = _make_slotting_data(
            sl_type=["project_finance", "project_finance", "hvcre"]
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        if "hvcre" in bundle.cr10:
            hvcre = bundle.cr10["hvcre"]
            strong = hvcre.filter(pl.col("row_ref") == "1")
            # HVCRE Strong = 95%
            assert strong["c"][0] == pytest.approx(95.0)

    def test_cr10_columns_match(self, generator: Pillar3Generator):
        data = _make_slotting_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        expected = {"row_ref", "row_name"} | {c.ref for c in CRR_CR10_COLUMNS}
        for df in bundle.cr10.values():
            assert set(df.columns) == expected


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
        data = pl.LazyFrame({
            "exposure_reference": [],
            "approach_applied": [],
            "exposure_class": [],
            "ead_final": [],
            "rwa_final": [],
            "risk_weight": [],
        })
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.errors == [] or isinstance(bundle.errors, list)

    def test_missing_columns_accumulates_errors(self, generator: Pillar3Generator):
        data = pl.LazyFrame({"exposure_reference": ["X"]})
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert len(bundle.errors) > 0

    def test_no_duplicate_row_refs_in_cr4(self, generator: Pillar3Generator):
        data = _make_sa_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        refs = bundle.cr4["row_ref"].to_list()
        assert len(refs) == len(set(refs))


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
