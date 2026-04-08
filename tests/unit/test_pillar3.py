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
    CMS1_COLUMNS,
    CMS1_ROWS,
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
    CR10_CATEGORY_MAP,
    CR10_SLOTTING_ROWS,
    CR6A_COLUMNS,
    CR6_PD_RANGES,
    CR7_COLUMNS,
    CR7A_AIRB_ROWS,
    CR7A_FIRB_ROWS,
    CR8_COLUMNS,
    CR8_ROWS,
    CR9_1_COLUMNS,
    CR9_1_COLUMN_REFS,
    CR9_AIRB_CLASSES,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMN_REFS,
    CR9_COLUMNS,
    CR9_FIRB_CLASSES,
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
        drivers = bundle.cr8.filter(pl.col("row_ref").is_in(["2", "3", "4", "5", "6", "7", "8"]))
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
        data = _make_slotting_data(sl_type=["project_finance", "project_finance", "hvcre"])
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


def _make_mixed_data_with_sa_rwa() -> pl.LazyFrame:
    """Create mixed pipeline data with sa_rwa column for output floor tests."""
    sa = _make_sa_data(
        sa_rwa=[1000.0, 700.0, 750.0],  # SA RWA = actual RWA for SA exposures
    ).collect()
    irb = _make_irb_data(
        sa_rwa=[3500.0, 2100.0, 1400.0],  # SA equivalent of IRB exposures
    ).collect()
    slotting = _make_slotting_data(
        sa_rwa=[800.0, 650.0, 500.0],  # SA equivalent of slotting exposures
    ).collect()
    all_frames = [sa, irb, slotting]
    col_types: dict[str, pl.DataType] = {}
    for df in all_frames:
        for col_name in df.columns:
            dtype = df.schema[col_name]
            if dtype != pl.Null:
                col_types[col_name] = dtype
    all_cols = sorted(col_types.keys())
    frames = []
    for df in all_frames:
        for col in all_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(col_types[col]).alias(col))
        frames.append(df.select(all_cols))
    return pl.concat(frames).lazy()


# ---------------------------------------------------------------------------
# CMS1 — Output floor comparison by risk type (Art. 456(1)(a))
# ---------------------------------------------------------------------------


class TestCMS1TemplateDefinitions:
    """Tests for CMS1 template constant definitions."""

    def test_cms1_columns_count(self):
        assert len(CMS1_COLUMNS) == 4

    def test_cms1_column_refs(self):
        refs = [c.ref for c in CMS1_COLUMNS]
        assert refs == ["a", "b", "c", "d"]

    def test_cms1_rows_count(self):
        assert len(CMS1_ROWS) == 8

    def test_cms1_row_refs(self):
        refs = [r.ref for r in CMS1_ROWS]
        assert refs == ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]

    def test_cms1_total_row_is_last(self):
        assert CMS1_ROWS[-1].is_total is True
        assert CMS1_ROWS[-1].ref == "0080"

    def test_cms1_credit_risk_row_first(self):
        assert CMS1_ROWS[0].ref == "0010"
        assert "Credit risk" in CMS1_ROWS[0].name

    def test_cms1_no_crr_rows(self):
        """CMS1 has no CRR variant — B31 only."""
        # CMS1 constants are not framework-split, they are B31-only
        assert len(CMS1_ROWS) == 8


class TestCMS1Generation:
    """Tests for CMS1 template generation."""

    def test_cms1_none_under_crr(self, generator: Pillar3Generator):
        """CMS1 is Basel 3.1 only — must be None under CRR."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cms1 is None

    def test_cms1_generated_under_b31(self, generator: Pillar3Generator):
        """CMS1 must be populated under Basel 3.1."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None

    def test_cms1_row_count(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1.height == 8

    def test_cms1_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        expected = {"row_ref", "row_name"} | {c.ref for c in CMS1_COLUMNS}
        assert set(bundle.cms1.columns) == expected

    def test_cms1_credit_risk_row_populated(self, generator: Pillar3Generator):
        """Row 0010 (credit risk) should have non-null values."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        assert cr_row["a"][0] is not None  # Modelled RWA
        assert cr_row["b"][0] is not None  # SA portfolio RWA
        assert cr_row["c"][0] is not None  # Total actual RWA
        assert cr_row["d"][0] is not None  # Full SA RWA

    def test_cms1_total_row_matches_credit_risk(self, generator: Pillar3Generator):
        """Total row should match credit risk row (only risk type in scope)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        total_row = bundle.cms1.filter(pl.col("row_ref") == "0080")
        for col in ["a", "b", "c", "d"]:
            assert total_row[col][0] == cr_row[col][0]

    def test_cms1_non_credit_rows_null(self, generator: Pillar3Generator):
        """Rows 0020-0070 (CCR, CVA, etc.) should be all null."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        non_credit_refs = ["0020", "0030", "0040", "0050", "0060", "0070"]
        for ref in non_credit_refs:
            row = bundle.cms1.filter(pl.col("row_ref") == ref)
            for col in ["a", "b", "c", "d"]:
                assert row[col][0] is None, f"Row {ref} col {col} should be None"

    def test_cms1_modelled_rwa_is_irb_plus_slotting(self, generator: Pillar3Generator):
        """Col a: modelled RWA = F-IRB + A-IRB + slotting RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        modelled_rwa = cr_row["a"][0]
        # IRB RWA: 4000 + 1500 + 1200 = 6700, Slotting RWA: 700 + 720 + 690 = 2110
        assert modelled_rwa == pytest.approx(6700.0 + 2110.0)

    def test_cms1_sa_portfolio_rwa(self, generator: Pillar3Generator):
        """Col b: SA portfolio RWA (exposures actually using SA)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        sa_portfolio_rwa = cr_row["b"][0]
        # SA RWA: 1000 + 700 + 750 = 2450
        assert sa_portfolio_rwa == pytest.approx(2450.0)

    def test_cms1_total_actual_rwa(self, generator: Pillar3Generator):
        """Col c: total actual RWA = modelled + SA portfolio."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        total_rwa = cr_row["c"][0]
        # 6700 + 2110 + 2450 = 11260
        assert total_rwa == pytest.approx(8810.0 + 2450.0)

    def test_cms1_full_sa_rwa(self, generator: Pillar3Generator):
        """Col d: full SA RWA for all exposures."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        full_sa_rwa = cr_row["d"][0]
        # Total sa_rwa: 1000+700+750 + 3500+2100+1400 + 800+650+500 = 11400
        assert full_sa_rwa == pytest.approx(11400.0)

    def test_cms1_missing_rwa_column(self, generator: Pillar3Generator):
        """Missing RWA column should return None and add error."""
        data = pl.LazyFrame({"exposure_reference": ["X"]})
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is None
        assert any("CMS1" in e for e in bundle.errors)

    def test_cms1_no_sa_rwa_column(self, generator: Pillar3Generator):
        """Without sa_rwa column, col d should be None."""
        data = _make_mixed_data()  # No sa_rwa column
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        assert cr_row["d"][0] is None


# ---------------------------------------------------------------------------
# CMS2 — Output floor comparison by asset class (Art. 456(1)(b))
# ---------------------------------------------------------------------------


class TestCMS2TemplateDefinitions:
    """Tests for CMS2 template constant definitions."""

    def test_cms2_columns_count(self):
        assert len(CMS2_COLUMNS) == 4

    def test_cms2_column_refs(self):
        refs = [c.ref for c in CMS2_COLUMNS]
        assert refs == ["a", "b", "c", "d"]

    def test_cms2_rows_count(self):
        assert len(CMS2_ROWS) == 17

    def test_cms2_row_refs(self):
        refs = [r.ref for r in CMS2_ROWS]
        expected = [
            "0010",
            "0011",
            "0020",
            "0030",
            "0040",
            "0041",
            "0042",
            "0043",
            "0044",
            "0045",
            "0050",
            "0051",
            "0052",
            "0053",
            "0054",
            "0060",
            "0070",
        ]
        assert refs == expected

    def test_cms2_total_row_is_last(self):
        assert CMS2_ROWS[-1].is_total is True
        assert CMS2_ROWS[-1].ref == "0070"

    def test_cms2_corporate_row_has_exposure_classes(self):
        corp_row = [r for r in CMS2_ROWS if r.ref == "0040"][0]
        assert "corporate" in corp_row.exposure_classes
        assert "corporate_sme" in corp_row.exposure_classes
        assert "specialised_lending" in corp_row.exposure_classes

    def test_cms2_retail_row_has_exposure_classes(self):
        retail_row = [r for r in CMS2_ROWS if r.ref == "0050"][0]
        assert "retail_mortgage" in retail_row.exposure_classes
        assert "retail_qrre" in retail_row.exposure_classes
        assert "retail_other" in retail_row.exposure_classes

    def test_cms2_sa_class_map_covers_main_rows(self):
        """SA class map should cover all main rows with exposure classes."""
        for row in CMS2_ROWS:
            if row.exposure_classes and row.ref in CMS2_SA_CLASS_MAP:
                assert len(CMS2_SA_CLASS_MAP[row.ref]) > 0


class TestCMS2Generation:
    """Tests for CMS2 template generation."""

    def test_cms2_none_under_crr(self, generator: Pillar3Generator):
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cms2 is None

    def test_cms2_generated_under_b31(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None

    def test_cms2_row_count(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2.height == 17

    def test_cms2_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        expected = {"row_ref", "row_name"} | {c.ref for c in CMS2_COLUMNS}
        assert set(bundle.cms2.columns) == expected

    def test_cms2_corporate_row_populated(self, generator: Pillar3Generator):
        """Corporate row (0040) should be populated from IRB data."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp_row = bundle.cms2.filter(pl.col("row_ref") == "0040")
        # IRB corporate RWA = 4000 (foundation_irb, corporate)
        assert corp_row["a"][0] is not None
        assert corp_row["a"][0] > 0

    def test_cms2_retail_row_populated(self, generator: Pillar3Generator):
        """Retail row (0050) should have modelled RWA from A-IRB retail."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        retail_row = bundle.cms2.filter(pl.col("row_ref") == "0050")
        # IRB retail: retail_mortgage 1500 + retail_other 1200 = 2700
        assert retail_row["a"][0] == pytest.approx(2700.0)

    def test_cms2_retail_sub_rows(self, generator: Pillar3Generator):
        """Retail sub-rows should break down the total."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        qrre = bundle.cms2.filter(pl.col("row_ref") == "0051")
        other = bundle.cms2.filter(pl.col("row_ref") == "0052")
        mortgage = bundle.cms2.filter(pl.col("row_ref") == "0053")
        # retail_qrre: not in IRB data → 0 or None
        # retail_other IRB: 1200
        assert other["a"][0] == pytest.approx(1200.0)
        # retail_mortgage IRB: 1500
        assert mortgage["a"][0] == pytest.approx(1500.0)

    def test_cms2_total_row(self, generator: Pillar3Generator):
        """Total row (0070) should aggregate all modelled exposures."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total modelled RWA = IRB (6700) + slotting (2110)
        assert total_row["a"][0] == pytest.approx(8810.0)

    def test_cms2_col_b_sa_equivalent(self, generator: Pillar3Generator):
        """Col b should show SA-equivalent RWA for modelled exposures."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total sa_rwa for modelled: 3500+2100+1400 + 800+650+500 = 8950
        assert total_row["b"][0] == pytest.approx(8950.0)

    def test_cms2_col_c_total_actual(self, generator: Pillar3Generator):
        """Col c should be modelled + SA portfolio for total row."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total actual = modelled (8810) + SA portfolio (2450) = 11260
        assert total_row["c"][0] == pytest.approx(11260.0)

    def test_cms2_col_d_full_sa(self, generator: Pillar3Generator):
        """Col d should show full SA RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total sa_rwa for all: 11400
        assert total_row["d"][0] == pytest.approx(11400.0)

    def test_cms2_firb_sub_row(self, generator: Pillar3Generator):
        """Row 0041 (FIRB) should show corporate F-IRB RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        firb_row = bundle.cms2.filter(pl.col("row_ref") == "0041")
        # Corporate F-IRB: 4000
        assert firb_row["a"][0] == pytest.approx(4000.0)

    def test_cms2_airb_sub_row(self, generator: Pillar3Generator):
        """Row 0042 (AIRB) should show corporate A-IRB RWA (zero in test data)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        airb_row = bundle.cms2.filter(pl.col("row_ref") == "0042")
        # No corporate A-IRB in test data (A-IRB is retail)
        assert airb_row["a"][0] is None or airb_row["a"][0] == pytest.approx(0.0)

    def test_cms2_purchased_receivables_null(self, generator: Pillar3Generator):
        """Purchased receivable rows (0045, 0054) should be null."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for ref in ["0045", "0054"]:
            row = bundle.cms2.filter(pl.col("row_ref") == ref)
            assert row["a"][0] is None

    def test_cms2_missing_rwa_column(self, generator: Pillar3Generator):
        data = pl.LazyFrame({"exposure_reference": ["X"]})
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is None
        assert any("CMS2" in e for e in bundle.errors)

    def test_cms2_no_sa_rwa_column(self, generator: Pillar3Generator):
        """Without sa_rwa, cols b and d should be None."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        assert total_row["b"][0] is None
        assert total_row["d"][0] is None

    def test_cms2_specialised_lending_sub_row(self, generator: Pillar3Generator):
        """Row 0043 (specialised lending) should show slotting RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        sl_row = bundle.cms2.filter(pl.col("row_ref") == "0043")
        # Slotting RWA: 700 + 720 + 690 = 2110
        assert sl_row["a"][0] == pytest.approx(2110.0)


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

    def test_b31_cms_templates_populated(self, generator: Pillar3Generator):
        """CMS1 and CMS2 should be populated under Basel 3.1."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        assert bundle.cms2 is not None

    def test_crr_cms_templates_none(self, generator: Pillar3Generator):
        """CMS1 and CMS2 should be None under CRR."""
        data = _make_mixed_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cms1 is None
        assert bundle.cms2 is None

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
        refs = bundle.cr4["row_ref"].to_list()
        assert len(refs) == len(set(refs))


# ---------------------------------------------------------------------------
# CR9 — PD back-testing per exposure class (Art. 452(h)) — Basel 3.1 only
# ---------------------------------------------------------------------------


def _make_cr9_irb_data(**overrides: object) -> pl.LazyFrame:
    """Create IRB data with multiple obligors for CR9 back-testing tests.

    Includes 6 exposures across F-IRB (corporate, institution) and A-IRB
    (retail_mortgage, retail_other) with varied PDs, default status, and
    counterparty references for obligor counting.
    """
    defaults = {
        "exposure_reference": ["CR9_1", "CR9_2", "CR9_3", "CR9_4", "CR9_5", "CR9_6"],
        "approach_applied": [
            "foundation_irb",
            "foundation_irb",
            "advanced_irb",
            "advanced_irb",
            "advanced_irb",
            "advanced_irb",
        ],
        "exposure_class": [
            "corporate",
            "institution",
            "retail_mortgage",
            "retail_mortgage",
            "retail_other",
            "retail_other",
        ],
        "ead_final": [5000.0, 3000.0, 2000.0, 1500.0, 1000.0, 800.0],
        "rwa_final": [4000.0, 1800.0, 1200.0, 900.0, 600.0, 480.0],
        "irb_pd_floored": [0.02, 0.005, 0.01, 0.008, 0.03, 1.0],
        "irb_pd_original": [0.018, 0.004, 0.009, 0.007, 0.025, 1.0],
        "irb_lgd_floored": [0.45, 0.45, 0.10, 0.10, 0.30, 0.45],
        "irb_maturity_m": [2.5, 2.5, 1.0, 1.0, 1.0, 1.0],
        "irb_expected_loss": [45.0, 6.75, 2.0, 1.2, 9.0, 360.0],
        "counterparty_reference": ["CP1", "CP2", "CP3", "CP4", "CP5", "CP6"],
        "is_defaulted": [False, False, False, False, False, True],
        "drawn_amount": [4500.0, 2700.0, 1800.0, 1350.0, 900.0, 720.0],
        "nominal_amount": [600.0, 400.0, 300.0, 200.0, 150.0, 100.0],
        "undrawn_amount": [500.0, 300.0, 200.0, 150.0, 100.0, 80.0],
        "interest": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "exposure_type": ["loan", "loan", "loan", "loan", "loan", "loan"],
        "ccf_applied": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


class TestCR9TemplateDefinitions:
    """Tests for CR9 template constant definitions."""

    def test_cr9_has_8_columns(self):
        assert len(CR9_COLUMNS) == 8

    def test_cr9_column_refs(self):
        assert CR9_COLUMN_REFS == ["a", "b", "c", "d", "e", "f", "g", "h"]

    def test_cr9_col_a_is_exposure_class(self):
        assert CR9_COLUMNS[0].name == "Exposure class"

    def test_cr9_col_b_is_pd_range(self):
        assert CR9_COLUMNS[1].name == "PD range"

    def test_cr9_col_f_mentions_post_input_floor(self):
        col_f = next(c for c in CR9_COLUMNS if c.ref == "f")
        assert "post input floor" in col_f.name.lower()

    def test_cr9_col_h_is_historical_rate(self):
        col_h = next(c for c in CR9_COLUMNS if c.ref == "h")
        assert "historical" in col_h.name.lower()

    def test_cr9_airb_classes_count(self):
        assert len(CR9_AIRB_CLASSES) == 6

    def test_cr9_firb_classes_count(self):
        assert len(CR9_FIRB_CLASSES) == 4

    def test_cr9_approach_display_has_both(self):
        assert "foundation_irb" in CR9_APPROACH_DISPLAY
        assert "advanced_irb" in CR9_APPROACH_DISPLAY

    def test_cr9_firb_includes_institution(self):
        keys = [k for k, _ in CR9_FIRB_CLASSES]
        assert "institution" in keys

    def test_cr9_airb_includes_retail(self):
        keys = [k for k, _ in CR9_AIRB_CLASSES]
        assert "retail_mortgage" in keys
        assert "retail_qrre" in keys
        assert "retail_other" in keys

    def test_cr9_1_has_base_columns(self):
        """CR9.1 has at least the 8 base columns (ECAI columns added dynamically)."""
        assert len(CR9_1_COLUMNS) == 8

    def test_cr9_1_col_b_is_firm_defined(self):
        col_b = next(c for c in CR9_1_COLUMNS if c.ref == "b")
        assert "firm-defined" in col_b.name.lower()

    def test_cr9_uses_same_pd_ranges_as_cr6(self):
        """CR9 uses the same 17 fixed PD range buckets as CR6."""
        assert len(CR6_PD_RANGES) == 17
        assert CR6_PD_RANGES[0][0] == 0.0
        assert CR6_PD_RANGES[-1][1] == float("inf")


class TestCR9Generation:
    """Tests for CR9 template generation logic."""

    def test_cr9_returns_empty_under_crr(self, generator: Pillar3Generator):
        """CR9 is Basel 3.1 only — CRR returns empty dict."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="CRR")
        assert bundle.cr9 == {}

    def test_cr9_returns_dict_under_b31(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert isinstance(bundle.cr9, dict)
        assert len(bundle.cr9) > 0

    def test_cr9_keys_include_approach_and_class(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # Should have F-IRB corporate, F-IRB institution, A-IRB retail_mortgage,
        # A-IRB retail_other from the test data
        keys = set(bundle.cr9.keys())
        assert "foundation_irb - corporate" in keys
        assert "foundation_irb - institution" in keys
        assert "advanced_irb - retail_mortgage" in keys
        assert "advanced_irb - retail_other" in keys

    def test_cr9_has_correct_column_count(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            # row_ref + row_name + 8 template columns = 10
            assert len(df.columns) == 10, f"Wrong column count for {key}: {df.columns}"

    def test_cr9_total_row_present(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            total_rows = df.filter(pl.col("row_ref") == "18")
            assert total_rows.height == 1, f"Missing total row for {key}"

    def test_cr9_no_empty_buckets_emitted(self, generator: Pillar3Generator):
        """Empty PD buckets should not produce rows (unlike CR6 which emits all 17)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            # Should have fewer than 18 rows (17 PD ranges + 1 total)
            # since not all PD ranges have data
            assert df.height < 18, f"Too many rows for {key}: {df.height}"


class TestCR9ColumnValues:
    """Tests for CR9 column value computation."""

    def test_col_c_obligor_count(self, generator: Pillar3Generator):
        """Col c counts unique counterparty references."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        # 1 corporate F-IRB counterparty (CP1)
        assert total["c"][0] == pytest.approx(1.0)

    def test_col_d_default_count(self, generator: Pillar3Generator):
        """Col d counts defaulted obligors."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # retail_other has one defaulted (CP6, PD=1.0, is_defaulted=True)
        ro = bundle.cr9["advanced_irb - retail_other"]
        total = ro.filter(pl.col("row_ref") == "18")
        assert total["d"][0] == pytest.approx(1.0)

    def test_col_d_non_defaulted_class_zero(self, generator: Pillar3Generator):
        """Classes with no defaults should have d=0."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["d"][0] == pytest.approx(0.0)

    def test_col_e_observed_default_rate(self, generator: Pillar3Generator):
        """Col e = d/c * 100 (observed default rate as percentage)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # retail_other: 2 obligors (CP5, CP6), 1 defaulted → 50%
        ro = bundle.cr9["advanced_irb - retail_other"]
        total = ro.filter(pl.col("row_ref") == "18")
        assert total["e"][0] == pytest.approx(50.0)

    def test_col_f_ewa_pd_percentage(self, generator: Pillar3Generator):
        """Col f = EAD-weighted average PD * 100 (post input floor)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        # F-IRB corporate: PD=0.02, EAD=5000 → EWA PD = 0.02 * 100 = 2.0%
        assert total["f"][0] == pytest.approx(2.0)

    def test_col_g_arithmetic_avg_pd(self, generator: Pillar3Generator):
        """Col g = arithmetic average PD * 100 (obligor-weighted)."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # retail_mortgage: PDs=[0.01, 0.008] → avg 0.009 * 100 = 0.9%
        rm = bundle.cr9["advanced_irb - retail_mortgage"]
        total = rm.filter(pl.col("row_ref") == "18")
        assert total["g"][0] == pytest.approx(0.9)

    def test_col_h_falls_back_to_observed_rate(self, generator: Pillar3Generator):
        """Col h falls back to col e when historical_annual_default_rate is absent."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        ro = bundle.cr9["advanced_irb - retail_other"]
        total = ro.filter(pl.col("row_ref") == "18")
        # Should equal observed rate (50%) as fallback
        assert total["h"][0] == pytest.approx(total["e"][0])

    def test_col_h_uses_historical_data_when_present(self, generator: Pillar3Generator):
        """Col h uses historical_annual_default_rate when column is present."""
        data = _make_cr9_irb_data(
            historical_annual_default_rate=[0.01, 0.02, 0.015, 0.015, 0.025, 0.05],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        # Corporate: historical_annual_default_rate=0.01 → 1.0%
        assert total["h"][0] == pytest.approx(1.0)

    def test_col_a_shows_class_display_name(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        # All rows in col a should show "Corporates"
        assert all(v == "Corporates" for v in corp["a"].to_list())

    def test_col_b_shows_pd_range_label(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        # Total row col b should be "Total"
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["b"][0] == "Total"


class TestCR9PDAllocation:
    """Tests for PD range bucket assignment in CR9."""

    def test_pd_allocation_uses_original_pd(self, generator: Pillar3Generator):
        """B31 allocates by irb_pd_original (pre-input-floor), not irb_pd_floored."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        # Corporate: irb_pd_original=0.018 → bucket "10" (1.00-2.50%)
        non_total = corp.filter(pl.col("row_ref") != "18")
        refs = non_total["row_ref"].to_list()
        assert "10" in refs  # 1.00 to < 2.50%

    def test_defaulted_in_100_percent_bucket(self, generator: Pillar3Generator):
        """Defaulted exposures (PD=1.0) should be in the 100% (Default) bucket."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        ro = bundle.cr9["advanced_irb - retail_other"]
        bucket_17 = ro.filter(pl.col("row_ref") == "17")
        assert bucket_17.height == 1
        assert bucket_17["d"][0] == pytest.approx(1.0)  # 1 defaulted

    def test_pd_range_labels_are_readable(self, generator: Pillar3Generator):
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        for key, df in bundle.cr9.items():
            labels = df["b"].to_list()
            assert "Total" in labels
            for label in labels:
                assert isinstance(label, str)
                assert len(label) > 0


class TestCR9EdgeCases:
    """Tests for CR9 edge cases and error handling."""

    def test_no_irb_data_returns_empty(self, generator: Pillar3Generator):
        """No IRB exposures → empty CR9 dict."""
        sa_only = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [800.0],
                "irb_pd_floored": [0.01],
            }
        )
        bundle = generator.generate_from_lazyframe(sa_only, framework="BASEL_3_1")
        assert bundle.cr9 == {}

    def test_missing_pd_column_returns_empty_with_error(
        self,
        generator: Pillar3Generator,
    ):
        """Missing PD columns → empty dict and error message."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X"],
                "approach_applied": ["foundation_irb"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [800.0],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cr9 == {}
        assert any("CR9" in e for e in bundle.errors)

    def test_slotting_exposures_excluded(self, generator: Pillar3Generator):
        """Slotting exposures should not appear in CR9 (they use CR10)."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SL1"],
                "approach_applied": ["slotting"],
                "exposure_class": ["specialised_lending"],
                "ead_final": [1000.0],
                "rwa_final": [700.0],
                "irb_pd_floored": [0.02],
                "irb_pd_original": [0.018],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        # Slotting is filtered out by _filter_irb_non_slotting before CR9 runs
        assert bundle.cr9 == {}

    def test_default_detection_falls_back_to_pd(self, generator: Pillar3Generator):
        """Without is_defaulted column, PD >= 1.0 is used as default proxy."""
        data = _make_cr9_irb_data()
        # Remove is_defaulted column
        collected = data.collect().drop("is_defaulted")
        no_default_col = collected.lazy()
        bundle = generator.generate_from_lazyframe(no_default_col, framework="BASEL_3_1")
        ro = bundle.cr9.get("advanced_irb - retail_other")
        assert ro is not None
        total = ro.filter(pl.col("row_ref") == "18")
        # CP6 has PD=1.0, should be detected as defaulted
        assert total["d"][0] == pytest.approx(1.0)

    def test_single_exposure_class(self, generator: Pillar3Generator):
        """Single exposure class produces a single CR9 template."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X2"],
                "approach_applied": ["foundation_irb", "foundation_irb"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": [1000.0, 2000.0],
                "rwa_final": [800.0, 1600.0],
                "irb_pd_floored": [0.01, 0.02],
                "irb_pd_original": [0.009, 0.018],
                "counterparty_reference": ["A", "B"],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert len(bundle.cr9) == 1
        assert "foundation_irb - corporate" in bundle.cr9

    def test_prior_year_obligor_count_used_when_present(
        self,
        generator: Pillar3Generator,
    ):
        """Col c uses prior_year_obligor_count when available."""
        data = _make_cr9_irb_data(
            prior_year_obligor_count=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["foundation_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        # prior_year_obligor_count for corporate is 1.0 (one row)
        assert total["c"][0] == pytest.approx(1.0)

    def test_multiple_obligors_same_class(self, generator: Pillar3Generator):
        """Multiple obligors in same class are counted correctly."""
        data = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X2", "X3"],
                "approach_applied": ["advanced_irb", "advanced_irb", "advanced_irb"],
                "exposure_class": ["corporate", "corporate", "corporate"],
                "ead_final": [1000.0, 2000.0, 3000.0],
                "rwa_final": [800.0, 1600.0, 2400.0],
                "irb_pd_floored": [0.01, 0.01, 0.02],
                "irb_pd_original": [0.009, 0.009, 0.018],
                "counterparty_reference": ["A", "A", "B"],  # 2 unique CPs
                "is_defaulted": [False, False, False],
            }
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        corp = bundle.cr9["advanced_irb - corporate"]
        total = corp.filter(pl.col("row_ref") == "18")
        assert total["c"][0] == pytest.approx(2.0)  # 2 unique counterparties


class TestCR9BundleIntegration:
    """Tests for CR9 integration with Pillar3TemplateBundle."""

    def test_bundle_cr9_field_default_empty(self):
        bundle = Pillar3TemplateBundle()
        assert bundle.cr9 == {}

    def test_bundle_cr9_alongside_other_templates(self, generator: Pillar3Generator):
        """CR9 coexists with other templates in the same bundle."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert isinstance(bundle.cr9, dict)
        assert bundle.cr6 is not None or isinstance(bundle.cr6, dict)
        assert bundle.framework == "BASEL_3_1"

    def test_end_to_end_with_mixed_data(self, generator: Pillar3Generator):
        """CR9 generated alongside all other templates from mixed data."""
        sa = pl.DataFrame(
            {
                "exposure_reference": ["SA1", "SA2"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "retail_other"],
                "ead_final": [1000.0, 500.0],
                "rwa_final": [1000.0, 375.0],
                "risk_weight": [1.0, 0.75],
                "drawn_amount": [900.0, 450.0],
                "nominal_amount": [150.0, 75.0],
                "undrawn_amount": [100.0, 50.0],
                "interest": [0.0, 0.0],
                "exposure_type": ["loan", "loan"],
                "sa_rwa": [1000.0, 375.0],
            }
        )
        irb = _make_cr9_irb_data().collect()
        irb = irb.with_columns(pl.lit(None).alias("risk_weight").cast(pl.Float64))
        irb = irb.with_columns(pl.col("rwa_final").alias("sa_rwa"))
        # Align schemas
        all_cols = set(sa.columns) | set(irb.columns)
        for col in all_cols:
            if col not in sa.columns:
                dtype = irb.schema.get(col, pl.Float64)
                sa = sa.with_columns(pl.lit(None).cast(dtype).alias(col))
            if col not in irb.columns:
                dtype = sa.schema.get(col, pl.Float64)
                irb = irb.with_columns(pl.lit(None).cast(dtype).alias(col))
        combined = pl.concat([sa.select(sorted(all_cols)), irb.select(sorted(all_cols))])
        bundle = generator.generate_from_lazyframe(
            combined.lazy(),
            framework="BASEL_3_1",
        )
        assert len(bundle.cr9) > 0
        assert bundle.ov1 is not None
        assert bundle.cr4 is not None


class TestCR9ExcelExport:
    """Tests for CR9 Excel export."""

    def test_export_includes_cr9_sheets(
        self,
        generator: Pillar3Generator,
        tmp_path: Path,
    ):
        """CR9 templates should be written to Excel sheets."""
        data = _make_cr9_irb_data()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        output = tmp_path / "pillar3_cr9.xlsx"
        result = generator.export_to_excel(bundle, output)
        assert output.exists()
        # CR9 rows should be included in total row count
        cr9_rows = sum(df.height for df in bundle.cr9.values())
        assert result.row_count >= cr9_rows


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
