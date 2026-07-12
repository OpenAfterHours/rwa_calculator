"""COREP C 08.07 / OF 08.07 IRB scope-of-use tests.

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    B31_C08_07_ROWS,
    CRR_C08_07_ROWS,
)


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
