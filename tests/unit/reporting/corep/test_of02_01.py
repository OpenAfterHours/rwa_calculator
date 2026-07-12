"""COREP OF 02.01 output-floor comparison tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    OF_02_01_COLUMN_REFS,
    OF_02_01_COLUMNS,
    OF_02_01_ROW_SECTIONS,
)


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
        assert bundle.of_02_01 is not None
        assert len(bundle.of_02_01) == 8

    def test_column_structure(self) -> None:
        """DataFrame has row_ref, row_name, and 4 data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
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
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=500, E2=1500, E3=100, E4=900 → 3000
        assert cr_row["0010"][0] == pytest.approx(3000.0)

    def test_sa_rwa(self) -> None:
        """Col 0020 = sum of sa_rwa for all exposures."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        # E1=700, E2=1400, E3=100, E4=1050 → 3250
        assert cr_row["0020"][0] == pytest.approx(3250.0)

    def test_u_trea_is_sum_of_modelled_and_sa(self) -> None:
        """P2.42: Col 0030 (U-TREA) must equal col 0010 + col 0020 (Annex II §1.3.2).

        Arrange: four exposures with rwa_pre_floor sum=3000, sa_rwa sum=3250.
        Act:     generate OF 02.01 under BASEL_3_1 framework.
        Assert:  col 0030 == col 0010 + col 0020 == 6250.0.
        """
        # Arrange
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")

        # Act / Assert
        # Regulatory requirement: U-TREA = modelled_TREA + SA_TREA (Annex II §1.3.2)
        # col 0010 (modelled) = 500+1500+100+900 = 3000
        # col 0020 (SA)       = 700+1400+100+1050 = 3250
        # col 0030 (U-TREA)   = 3000 + 3250 = 6250
        assert cr_row["0030"][0] == pytest.approx(cr_row["0010"][0] + cr_row["0020"][0]), (
            "U-TREA (col 0030) must equal col 0010 + col 0020 per Annex II §1.3.2"
        )
        assert cr_row["0030"][0] == pytest.approx(6250.0)

    def test_s_trea_equals_sa(self) -> None:
        """Col 0040 (S-TREA) equals col 0020 for credit-risk-only calculator."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0040"][0] == cr_row["0020"][0]

    def test_floor_binding_scenario(self) -> None:
        """Floor binding: modelled < SA (modelled=1100 < SA=2200)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_floor_binding(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(1100.0)  # 300+800
        assert cr_row["0020"][0] == pytest.approx(2200.0)  # 600+1600

    def test_sa_only_portfolio(self) -> None:
        """SA-only portfolio: modelled = SA (no IRB benefit)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(
            _sa_only_results_with_floor_cols(), framework="BASEL_3_1"
        )
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(1100.0)  # 1000+100
        assert cr_row["0020"][0] == pytest.approx(1100.0)  # same


class TestOF0201TotalRow:
    """OF 02.01 row 0080 — Total."""

    def test_total_equals_credit_risk(self) -> None:
        """Total row equals credit risk row (credit-risk-only calculator)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert total_row[col_ref][0] == cr_row[col_ref][0]

    def test_total_modelled_rwa(self) -> None:
        """Total row col 0010 matches credit risk sum."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        total_row = bundle.of_02_01.filter(pl.col("row_ref") == "0080")
        assert total_row["0010"][0] == pytest.approx(3000.0)

    def test_total_row_name(self) -> None:
        """Total row is named 'Total'."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
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
        assert bundle.of_02_01 is not None
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
        assert bundle.of_02_01 is not None
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
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(500.0)
        assert cr_row["0020"][0] == pytest.approx(1400.0)

    def test_data_columns_are_float64(self) -> None:
        """All 4 data columns are Float64 type."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        for col_ref in ["0010", "0020", "0030", "0040"]:
            assert bundle.of_02_01 is not None
            assert bundle.of_02_01[col_ref].dtype == pl.Float64

    def test_row_ref_and_name_are_string(self) -> None:
        """row_ref and row_name columns are String type."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
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
        assert bundle.of_02_01 is not None
        cr_row = bundle.of_02_01.filter(pl.col("row_ref") == "0010")
        assert cr_row["0010"][0] == pytest.approx(5e11)
        assert cr_row["0020"][0] == pytest.approx(7e11)

    def test_row_order_preserved(self) -> None:
        """Rows are in the correct order: 0010, 0020, ..., 0080."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
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
