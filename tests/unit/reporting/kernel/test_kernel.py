"""
Unit tests for the shared reporting kernel (rwa_calc.reporting.kernel).

The kernel was extracted from the COREP and Pillar 3 generators, which each
carried a drifted private copy of these helpers. These tests pin:

- the unified missing-column behaviour of every filter (RETURN EMPTY — a
  missing discriminator must be a detectable failure, never a silent
  pass-through that double-counts rows across on-BS/off-BS cells), and
- the two deliberately-retained sum semantics (COREP zero-cell vs
  Pillar 3 null-cell).

References:
- src/rwa_calc/reporting/kernel/ (modules under test)
- filter_on_bs docstring (recorded drift decision)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.kernel import (
    available_columns,
    col_sum,
    filter_by_approach,
    filter_off_bs,
    filter_on_bs,
    null_row,
    pick,
    safe_sum,
    safe_sum_or_none,
    write_metadata_sheet,
)

XLSXWRITER_AVAILABLE = bool(sys.modules.get("xlsxwriter")) or (
    importlib.util.find_spec("xlsxwriter") is not None
)

# ---------------------------------------------------------------------------
# Shared frame builders
# ---------------------------------------------------------------------------


def _bs_frame() -> pl.DataFrame:
    """Frame with both bs_type and exposure_type indicator columns."""
    return pl.DataFrame(
        {
            "bs_type": ["ONB", "OFB", "ONB"],
            "exposure_type": ["loan", "facility", "contingent"],
            "ead_final": [100.0, 200.0, 300.0],
        }
    )


def _exposure_type_frame() -> pl.DataFrame:
    """Frame with only the exposure_type fallback indicator column."""
    return pl.DataFrame(
        {
            "exposure_type": ["loan", "facility", "contingent"],
            "ead_final": [100.0, 200.0, 300.0],
        }
    )


def _no_indicator_frame() -> pl.DataFrame:
    """Frame with NEITHER balance-sheet indicator column."""
    return pl.DataFrame({"ead_final": [100.0, 200.0, 300.0]})


def _cols(df: pl.DataFrame) -> set[str]:
    return set(df.columns)


# ---------------------------------------------------------------------------
# columns.py
# ---------------------------------------------------------------------------


class TestAvailableColumns:
    def test_returns_schema_names_as_set(self) -> None:
        # Arrange
        lf = pl.LazyFrame({"a": [1], "b": ["x"], "c": [1.0]})

        # Act
        cols = available_columns(lf)

        # Assert
        assert cols == {"a", "b", "c"}


class TestPick:
    def test_returns_first_present_candidate(self) -> None:
        # Arrange
        cols = {"ead_final", "rwa_final"}

        # Act
        chosen = pick(cols, "ead", "ead_final", "final_ead")

        # Assert
        assert chosen == "ead_final"

    def test_returns_none_when_no_candidate_present(self) -> None:
        # Arrange
        cols = {"rwa_final"}

        # Act
        chosen = pick(cols, "ead", "ead_final")

        # Assert
        assert chosen is None


# ---------------------------------------------------------------------------
# filters.py
# ---------------------------------------------------------------------------


class TestFilterByApproach:
    def test_filters_rows_matching_approach_applied(self) -> None:
        # Arrange
        lf = pl.LazyFrame(
            {
                "approach_applied": ["standardised", "foundation_irb", "standardised"],
                "ead_final": [1.0, 2.0, 3.0],
            }
        )

        # Act
        out = filter_by_approach(lf, "standardised", available_columns(lf)).collect()

        # Assert
        assert out["ead_final"].to_list() == [1.0, 3.0]

    def test_missing_approach_column_returns_empty(self) -> None:
        """A missing approach discriminator must not silently pass rows through."""
        # Arrange
        lf = pl.LazyFrame({"ead_final": [1.0, 2.0]})

        # Act
        out = filter_by_approach(lf, "standardised", available_columns(lf)).collect()

        # Assert
        assert out.height == 0

    def test_candidates_parameter_enables_legacy_approach_alias(self) -> None:
        """Pillar 3 keeps the legacy ``approach`` column via the candidates param."""
        # Arrange
        lf = pl.LazyFrame({"approach": ["standardised", "slotting"], "ead_final": [1.0, 2.0]})
        cols = available_columns(lf)

        # Act
        default_out = filter_by_approach(lf, "standardised", cols).collect()
        alias_out = filter_by_approach(
            lf, "standardised", cols, candidates=("approach_applied", "approach")
        ).collect()

        # Assert — default (COREP) candidates ignore the alias; explicit ones use it
        assert default_out.height == 0
        assert alias_out["ead_final"].to_list() == [1.0]


class TestFilterOnBs:
    def test_bs_type_column_selects_onb_rows(self) -> None:
        # Arrange
        df = _bs_frame()

        # Act
        out = filter_on_bs(df, _cols(df))

        # Assert
        assert out["ead_final"].to_list() == [100.0, 300.0]

    def test_exposure_type_fallback_selects_loans(self) -> None:
        # Arrange
        df = _exposure_type_frame()

        # Act
        out = filter_on_bs(df, _cols(df))

        # Assert
        assert out["ead_final"].to_list() == [100.0]

    def test_missing_indicator_columns_return_empty(self) -> None:
        """Recorded drift decision: missing balance-sheet indicator -> EMPTY.

        The COREP copy returned empty, the Pillar 3 copy returned ALL rows.
        Returning all rows double-counts every exposure across the on-BS and
        off-BS template cells, so both generators unify on the conservative,
        detectable empty result (see filter_on_bs docstring).
        """
        # Arrange
        df = _no_indicator_frame()

        # Act
        out = filter_on_bs(df, _cols(df))

        # Assert
        assert out.height == 0
        assert out.columns == df.columns  # schema preserved for downstream sums

    def test_missing_indicator_columns_do_not_double_count(self) -> None:
        """on-BS + off-BS partitions must never overlap when indicators are absent."""
        # Arrange
        df = _no_indicator_frame()

        # Act
        on_bs = filter_on_bs(df, _cols(df))
        off_bs = filter_off_bs(df, _cols(df))

        # Assert — combined height must not exceed the input population
        assert on_bs.height + off_bs.height <= df.height


class TestFilterOffBs:
    def test_bs_type_column_selects_ofb_rows(self) -> None:
        # Arrange
        df = _bs_frame()

        # Act
        out = filter_off_bs(df, _cols(df))

        # Assert
        assert out["ead_final"].to_list() == [200.0]

    def test_exposure_type_fallback_selects_facilities_and_contingents(self) -> None:
        # Arrange
        df = _exposure_type_frame()

        # Act
        out = filter_off_bs(df, _cols(df))

        # Assert
        assert out["ead_final"].to_list() == [200.0, 300.0]

    def test_missing_indicator_columns_return_empty(self) -> None:
        """Same missing-column policy as filter_on_bs: EMPTY, never pass-through."""
        # Arrange
        df = _no_indicator_frame()

        # Act
        out = filter_off_bs(df, _cols(df))

        # Assert
        assert out.height == 0


# ---------------------------------------------------------------------------
# sums.py
# ---------------------------------------------------------------------------


class TestColSum:
    def test_sums_column_with_nulls_treated_as_zero(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": [100.0, None, 300.0]})

        # Act
        total = col_sum(df, _cols(df), "ead_final")

        # Assert
        assert total == 400.0

    def test_missing_column_returns_none(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": [100.0]})

        # Act
        total = col_sum(df, _cols(df), "rwa_final")

        # Assert
        assert total is None

    def test_none_column_name_returns_none(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": [100.0]})

        # Act
        total = col_sum(df, _cols(df), None)

        # Assert
        assert total is None

    def test_empty_frame_defaults_to_zero_corep_semantics(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": pl.Series([], dtype=pl.Float64)})

        # Act
        total = col_sum(df, _cols(df), "ead_final")

        # Assert
        assert total == 0.0

    def test_empty_frame_with_empty_as_none_returns_none_pillar3_semantics(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": pl.Series([], dtype=pl.Float64)})

        # Act
        total = col_sum(df, _cols(df), "ead_final", empty_as_none=True)

        # Assert
        assert total is None


class TestSafeSum:
    def test_sums_present_columns_and_skips_absent(self) -> None:
        # Arrange
        df = pl.DataFrame({"drawn_amount": [100.0, 50.0], "interest": [10.0, None]})

        # Act
        total = safe_sum(df, _cols(df), "drawn_amount", "interest", "not_a_column")

        # Assert
        assert total == 160.0

    def test_no_column_present_returns_zero_corep_semantics(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": [100.0]})

        # Act
        total = safe_sum(df, _cols(df), "drawn_amount", "interest")

        # Assert
        assert total == 0.0


class TestSafeSumOrNone:
    def test_sums_present_columns_and_skips_absent(self) -> None:
        # Arrange
        df = pl.DataFrame({"drawn_amount": [100.0, 50.0], "interest": [10.0, None]})

        # Act
        total = safe_sum_or_none(df, _cols(df), "drawn_amount", "interest", "not_a_column")

        # Assert
        assert total == 160.0

    def test_no_column_present_returns_none_pillar3_semantics(self) -> None:
        # Arrange
        df = pl.DataFrame({"ead_final": [100.0]})

        # Act
        total = safe_sum_or_none(df, _cols(df), "drawn_amount", "interest")

        # Assert
        assert total is None


# ---------------------------------------------------------------------------
# rows.py
# ---------------------------------------------------------------------------


class TestNullRow:
    def test_builds_row_with_ref_name_and_null_cells(self) -> None:
        # Arrange
        column_refs = ["0010", "0020"]

        # Act
        row = null_row("0070", "Corporates", column_refs)

        # Assert
        assert row == {
            "row_ref": "0070",
            "row_name": "Corporates",
            "0010": None,
            "0020": None,
        }


# ---------------------------------------------------------------------------
# excel.py — write_metadata_sheet
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not XLSXWRITER_AVAILABLE, reason="xlsxwriter not installed")
class TestWriteMetadataSheet:
    """Tests for the filing-metadata workbook sheet (FilingMetadata.as_sheet_fields())."""

    def test_writes_field_value_rows(self, tmp_path: Path) -> None:
        # Arrange
        import xlsxwriter as xw

        path = tmp_path / "meta.xlsx"
        workbook = xw.Workbook(str(path))

        # Act
        write_metadata_sheet(
            workbook, {"Reporting date": "2026-07-19", "Framework": "CRR", "Run ID": "run-1"}
        )
        workbook.close()

        # Assert
        df = pl.read_excel(path, sheet_name="metadata")
        assert df.columns == ["Field", "Value"]
        assert df.to_dicts() == [
            {"Field": "Reporting date", "Value": "2026-07-19"},
            {"Field": "Framework", "Value": "CRR"},
            {"Field": "Run ID", "Value": "run-1"},
        ]

    def test_default_sheet_name_is_metadata(self, tmp_path: Path) -> None:
        # Arrange
        import xlsxwriter as xw

        path = tmp_path / "meta.xlsx"
        workbook = xw.Workbook(str(path))

        # Act
        write_metadata_sheet(workbook, {"Framework": "CRR"})
        workbook.close()

        # Assert
        import fastexcel

        assert fastexcel.read_excel(str(path)).sheet_names == ["metadata"]

    def test_leading_equals_value_is_a_literal_string_not_a_formula(self, tmp_path: Path) -> None:
        """entity_identifier is unsanitised REST input (e.g. ?entity_identifier=...);
        a leading '=' (or '+'/'-'/'@') must never become a live formula cell in
        this regulatory workbook."""
        # Arrange
        import zipfile

        import xlsxwriter as xw

        path = tmp_path / "meta.xlsx"
        workbook = xw.Workbook(str(path))

        # Act
        write_metadata_sheet(workbook, {"Entity identifier": "=1+2"})
        workbook.close()

        # Assert — the underlying sheet XML carries no <f> formula element; the
        # cell is a plain inline/shared string, so Excel never evaluates it.
        with zipfile.ZipFile(path) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode()
        assert "<f>" not in sheet_xml

        # And the value round-trips as the literal text, not a computed "3".
        df = pl.read_excel(path, sheet_name="metadata")
        assert df.filter(pl.col("Field") == "Entity identifier")["Value"].to_list() == ["=1+2"]
