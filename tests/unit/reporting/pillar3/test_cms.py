"""Unit tests for the declarative Pillar 3 CMS1/CMS2 templates (Phase 7 S8).

Tests cover:
    - CMS1: output-floor comparison by risk type — the modelled vs
      standardised split, the full-SA column, framework gating
    - CMS2: comparison by asset class — class rows, F-IRB/A-IRB sub-rows,
      recorded-null purchased-receivables rows, the SA class map
    - The recorded equity fix: the standardised side is the explicit
      origin-approach complement ("standardised", "equity") — equity RWA
      populates CMS2 row 0030 and reconciles the CMS2 total to CMS1
    - The recorded origination-class keying (CR6-A pattern): substituted
      legs never move CMS2 rows

Why: CMS1/CMS2 are the Basel 3.1 output-floor comparison disclosures
(Art. 456(1)); their actual-vs-SA-equivalent columns must agree across the
two templates and carry every credit-risk approach.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.pillar3.templates import (
    CMS1_COLUMNS,
    CMS1_ROWS,
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
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
    return _align_and_concat([sa, irb, slotting])


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


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
        assert bundle.cms1 is not None
        assert bundle.cms1.height == 8

    def test_cms1_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        expected = {"row_ref", "row_name"} | {c.ref for c in CMS1_COLUMNS}
        assert set(bundle.cms1.columns) == expected

    def test_cms1_credit_risk_row_populated(self, generator: Pillar3Generator):
        """Row 0010 (credit risk) should have non-null values."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        assert cr_row["a"][0] is not None  # Modelled RWA
        assert cr_row["b"][0] is not None  # SA portfolio RWA
        assert cr_row["c"][0] is not None  # Total actual RWA
        assert cr_row["d"][0] is not None  # Full SA RWA

    def test_cms1_total_row_matches_credit_risk(self, generator: Pillar3Generator):
        """Total row should match credit risk row (only risk type in scope)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        total_row = bundle.cms1.filter(pl.col("row_ref") == "0080")
        for col in ["a", "b", "c", "d"]:
            assert total_row[col][0] == cr_row[col][0]

    def test_cms1_non_credit_rows_null(self, generator: Pillar3Generator):
        """Rows 0020-0070 (CCR, CVA, etc.) should be all null."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        non_credit_refs = ["0020", "0030", "0040", "0050", "0060", "0070"]
        for ref in non_credit_refs:
            row = bundle.cms1.filter(pl.col("row_ref") == ref)
            for col in ["a", "b", "c", "d"]:
                assert row[col][0] is None, f"Row {ref} col {col} should be None"

    def test_cms1_modelled_rwa_is_irb_plus_slotting(self, generator: Pillar3Generator):
        """Col a: modelled RWA = F-IRB + A-IRB + slotting RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        modelled_rwa = cr_row["a"][0]
        # IRB RWA: 4000 + 1500 + 1200 = 6700, Slotting RWA: 700 + 720 + 690 = 2110
        assert modelled_rwa == pytest.approx(6700.0 + 2110.0)

    def test_cms1_sa_portfolio_rwa(self, generator: Pillar3Generator):
        """Col b: SA portfolio RWA (exposures actually using SA)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        sa_portfolio_rwa = cr_row["b"][0]
        # SA RWA: 1000 + 700 + 750 = 2450
        assert sa_portfolio_rwa == pytest.approx(2450.0)

    def test_cms1_total_actual_rwa(self, generator: Pillar3Generator):
        """Col c: total actual RWA = modelled + SA portfolio."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
        cr_row = bundle.cms1.filter(pl.col("row_ref") == "0010")
        total_rwa = cr_row["c"][0]
        # 6700 + 2110 + 2450 = 11260
        assert total_rwa == pytest.approx(8810.0 + 2450.0)

    def test_cms1_full_sa_rwa(self, generator: Pillar3Generator):
        """Col d: full SA RWA for all exposures."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms1 is not None
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
        assert bundle.cms2 is not None
        assert bundle.cms2.height == 17

    def test_cms2_columns_match(self, generator: Pillar3Generator):
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        expected = {"row_ref", "row_name"} | {c.ref for c in CMS2_COLUMNS}
        assert set(bundle.cms2.columns) == expected

    def test_cms2_corporate_row_populated(self, generator: Pillar3Generator):
        """Corporate row (0040) should be populated from IRB data."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        corp_row = bundle.cms2.filter(pl.col("row_ref") == "0040")
        # IRB corporate RWA = 4000 (foundation_irb, corporate)
        assert corp_row["a"][0] is not None
        assert corp_row["a"][0] > 0

    def test_cms2_retail_row_populated(self, generator: Pillar3Generator):
        """Retail row (0050) should have modelled RWA from A-IRB retail."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        retail_row = bundle.cms2.filter(pl.col("row_ref") == "0050")
        # IRB retail: retail_mortgage 1500 + retail_other 1200 = 2700
        assert retail_row["a"][0] == pytest.approx(2700.0)

    def test_cms2_retail_sub_rows(self, generator: Pillar3Generator):
        """Retail sub-rows should break down the total."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        _qrre = bundle.cms2.filter(pl.col("row_ref") == "0051")
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
        assert bundle.cms2 is not None
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total modelled RWA = IRB (6700) + slotting (2110)
        assert total_row["a"][0] == pytest.approx(8810.0)

    def test_cms2_col_b_sa_equivalent(self, generator: Pillar3Generator):
        """Col b should show SA-equivalent RWA for modelled exposures."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total sa_rwa for modelled: 3500+2100+1400 + 800+650+500 = 8950
        assert total_row["b"][0] == pytest.approx(8950.0)

    def test_cms2_col_c_total_actual(self, generator: Pillar3Generator):
        """Col c should be modelled + SA portfolio for total row."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total actual = modelled (8810) + SA portfolio (2450) = 11260
        assert total_row["c"][0] == pytest.approx(11260.0)

    def test_cms2_col_d_full_sa(self, generator: Pillar3Generator):
        """Col d should show full SA RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        total_row = bundle.cms2.filter(pl.col("row_ref") == "0070")
        # Total sa_rwa for all: 11400
        assert total_row["d"][0] == pytest.approx(11400.0)

    def test_cms2_firb_sub_row(self, generator: Pillar3Generator):
        """Row 0041 (FIRB) should show corporate F-IRB RWA."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        firb_row = bundle.cms2.filter(pl.col("row_ref") == "0041")
        # Corporate F-IRB: 4000
        assert firb_row["a"][0] == pytest.approx(4000.0)

    def test_cms2_airb_sub_row(self, generator: Pillar3Generator):
        """Row 0042 (AIRB) should show corporate A-IRB RWA (zero in test data)."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        airb_row = bundle.cms2.filter(pl.col("row_ref") == "0042")
        # No corporate A-IRB in test data (A-IRB is retail)
        assert airb_row["a"][0] is None or airb_row["a"][0] == pytest.approx(0.0)

    def test_cms2_purchased_receivables_null(self, generator: Pillar3Generator):
        """Purchased receivable rows (0045, 0054) should be null."""
        data = _make_mixed_data_with_sa_rwa()
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
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
        assert bundle.cms2 is not None
        sl_row = bundle.cms2.filter(pl.col("row_ref") == "0043")
        # Slotting RWA: 700 + 720 + 690 = 2110
        assert sl_row["a"][0] == pytest.approx(2110.0)


class TestCMSBundleIntegration:
    """End-to-end CMS assertions relocated from TestGeneratorEndToEnd."""

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


class TestCMSRecordedDecisions:
    """The recorded CMS decisions: the explicit standardised-side complement
    (equity counts as SA under the Basel 3.1 equity transitional) and the
    origination-class row keying."""

    def _mixed_with_equity(self) -> pl.LazyFrame:
        frames = [
            _make_sa_data(sa_rwa=[1000.0, 700.0, 750.0]).collect(),
            _make_irb_data(sa_rwa=[3500.0, 2100.0, 1400.0]).collect(),
            _make_slotting_data(sa_rwa=[800.0, 650.0, 500.0]).collect(),
            pl.DataFrame(
                {
                    "exposure_reference": ["EQ1"],
                    "approach_applied": ["equity"],
                    "exposure_class": ["equity"],
                    "ead_final": [1000.0],
                    "rwa_final": [500.0],
                    "exposure_type": ["equity_holding"],
                }
            ),
        ]
        return _align_and_concat(frames)

    def test_cms2_equity_row_carries_equity_rwa(self, generator: Pillar3Generator):
        """Recorded fix: equity-approach RWA belongs in row 0030 column c —
        "exposures calculated according to the SA for credit risk include
        equity exposures subject to the IRB Equity Transitional"."""
        bundle = generator.generate_from_lazyframe(self._mixed_with_equity(), framework="BASEL_3_1")
        assert bundle.cms2 is not None
        equity_row = bundle.cms2.filter(pl.col("row_ref") == "0030")
        assert equity_row["c"][0] == pytest.approx(500.0)

    def test_cms2_total_reconciles_to_cms1(self, generator: Pillar3Generator):
        """Recorded fix: CMS1 and CMS2 report the same total actual RWA —
        the retired standardised-only add left CMS2 short by the equity RWA."""
        bundle = generator.generate_from_lazyframe(self._mixed_with_equity(), framework="BASEL_3_1")
        assert bundle.cms1 is not None
        assert bundle.cms2 is not None
        cms1_total = bundle.cms1.filter(pl.col("row_ref") == "0080")["c"][0]
        cms2_total = bundle.cms2.filter(pl.col("row_ref") == "0070")["c"][0]
        assert cms1_total == pytest.approx(11260.0 + 500.0)
        assert cms2_total == pytest.approx(cms1_total)

    def test_cms2_substituted_legs_stay_in_obligor_class_row(self, generator: Pillar3Generator):
        """Recorded keying: CMS2 rows carry the origination class — column b
        is the SA recomputation "of exposures reported in column (a)", the
        same population, so substitution never moves a row."""
        data = _make_irb_data(
            exposure_reference=["G1__G_SOV", "G1__REM", "IRB3"],
            approach_applied=["foundation_irb", "foundation_irb", "advanced_irb"],
            exposure_class=["corporate", "corporate", "retail_other"],
            exposure_class_applied=["corporate", "corporate", "retail_other"],
            exposure_class_post_crm=[
                "central_govt_central_bank",
                "corporate",
                "retail_other",
            ],
            rwa_final=[0.0, 3200.0, 1200.0],
            sa_rwa=[3500.0, 2100.0, 1400.0],
        )
        bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
        assert bundle.cms2 is not None
        corp = bundle.cms2.filter(pl.col("row_ref") == "0040")
        sov = bundle.cms2.filter(pl.col("row_ref") == "0010")
        assert corp["a"][0] == pytest.approx(3200.0)  # both legs' actual RWA
        assert corp["b"][0] == pytest.approx(5600.0)  # both legs' SA-equivalent
        assert sov["a"][0] is None  # no sovereign-row inflow
