"""
Unit tests: the keyed cell-fact export (rwa_calc.reporting.facts).

Pins the flat, machine-mappable cell feed a vendor filing tool consumes:
- one row per cell that exists in a generated template's row/column grid —
  traversal delegates to reporting.catalog and never re-walks the bundles
  itself, so a template absent from the run contributes no rows;
- null vs 0.0 is preserved (never filled) — a filing validator needs the
  distinction between "not applicable" and "reported zero";
- non-finite floats (NaN / +-Inf) are nulled, mirroring the workbook export;
- String-valued template cells (e.g. a data-driven grade label) land in
  ``text_value``, never coerced into the numeric ``value`` column;
- ``FilingMetadata`` stamps constant columns onto the frame, and separately
  drives the workbook metadata sheet / export filenames (see
  ``kernel/test_kernel.py`` and ``api/test_export.py``).

References:
- src/rwa_calc/reporting/facts.py (module under test)
- docs/plans/report-cell-lineage.md §3 (the catalogue this module reuses)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting import facts
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

# =============================================================================
# Builders
# =============================================================================

_FACT_COLUMNS = [
    "template_id",
    "sheet",
    "row_ref",
    "row_name",
    "col_ref",
    "col_name",
    "value",
    "text_value",
    "framework",
]


def _sheet(**cols: Sequence[object]) -> pl.DataFrame:
    """A minimal template frame: structural columns plus the given value columns."""
    data: dict[str, Sequence[object]] = {"row_ref": ["0010"], "row_name": ["Total exposures"]}
    data.update(cols)
    return pl.DataFrame(data)


def _corep(**fields: object) -> COREPTemplateBundle:
    base: dict[str, Any] = {"c07_00": {}, "c08_01": {}, "c08_02": {}}
    base.update(fields)
    return COREPTemplateBundle(**base)


# =============================================================================
# build_fact_frame — shape
# =============================================================================


class TestFactFrameShape:
    def test_columns(self) -> None:
        # Arrange
        corep = _corep(c_02_00=_sheet(**{"0010": [100.0]}))

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame.columns == _FACT_COLUMNS

    def test_one_row_per_cell(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0], "0020": [2.0]})})

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame.height == 2
        assert set(frame["col_ref"].to_list()) == {"0010", "0020"}

    def test_row_and_cell_identity_carried_through(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0200": [500.0]})})

        # Act
        (row,) = facts.build_fact_frame(corep, None).to_dicts()

        # Assert
        assert row["template_id"] == "c07_00"
        assert row["sheet"] == "corporate"
        assert row["row_ref"] == "0010"
        assert row["row_name"] == "Total exposures"
        assert row["col_ref"] == "0200"
        assert row["col_name"] != "0200"  # a readable name, not the bare ref
        assert row["value"] == 500.0
        assert row["framework"] == "CRR"

    def test_single_frame_template_has_null_sheet(self) -> None:
        # Arrange
        corep = _corep(c_02_00=_sheet(**{"0010": [1.0]}))

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame["sheet"].to_list() == [None]

    def test_spans_both_bundles(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})
        pillar3 = Pillar3TemplateBundle(cr4=_sheet(a=[1.0]))

        # Act
        frame = facts.build_fact_frame(corep, pillar3)

        # Assert
        assert set(frame["template_id"].to_list()) == {"c07_00", "cr4"}

    def test_absent_template_contributes_no_rows(self) -> None:
        """A template not in this run's bundle is excluded upstream by
        catalog.template_index — never emitted here as an all-null row."""
        # Arrange
        corep = _corep()

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame.height == 0

    def test_no_bundles_returns_empty_frame_with_the_full_schema(self) -> None:
        # Act
        frame = facts.build_fact_frame(None, None)

        # Assert
        assert frame.height == 0
        assert frame.columns == _FACT_COLUMNS

    def test_family_can_be_exported_alone(self) -> None:
        # Arrange
        pillar3 = Pillar3TemplateBundle(cr4=_sheet(a=[1.0]))

        # Act
        frame = facts.build_fact_frame(None, pillar3)

        # Assert
        assert frame["template_id"].to_list() == ["cr4"]


# =============================================================================
# Null / non-finite handling
# =============================================================================


class TestValuePreservation:
    def test_null_cell_stays_null_not_zero(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [None]})})

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame["value"].to_list() == [None]

    def test_zero_cell_stays_zero_not_null(self) -> None:
        """The null/0.0 distinction this module exists to preserve."""
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [0.0]})})

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame["value"].to_list() == [0.0]

    def test_non_finite_floats_are_nulled(self) -> None:
        # Arrange
        corep = _corep(
            c07_00={"corporate": _sheet(**{"0010": [float("nan")], "0020": [float("inf")]})}
        )

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame["value"].to_list() == [None, None]


# =============================================================================
# String-valued cells (e.g. C 08.02 col 0005, the PD-grade label)
# =============================================================================


class TestTextValue:
    def test_string_column_lands_in_text_value_not_value(self) -> None:
        # Arrange
        frame = pl.DataFrame(
            {"row_ref": ["0010"], "row_name": ["Grade 1"], "0005": ["Grade 1"]},
            schema={"row_ref": pl.String, "row_name": pl.String, "0005": pl.String},
        )
        corep = _corep(c08_02={"corporate": frame})

        # Act
        (row,) = facts.build_fact_frame(corep, None).to_dicts()

        # Assert
        assert row["value"] is None
        assert row["text_value"] == "Grade 1"

    def test_mixed_numeric_and_string_columns_on_one_sheet(self) -> None:
        # Arrange
        frame = pl.DataFrame(
            {"row_ref": ["0010"], "row_name": ["Grade 1"], "0005": ["Grade 1"], "0060": [100.0]},
            schema={
                "row_ref": pl.String,
                "row_name": pl.String,
                "0005": pl.String,
                "0060": pl.Float64,
            },
        )
        corep = _corep(c08_02={"corporate": frame})

        # Act
        by_ref = {r["col_ref"]: r for r in facts.build_fact_frame(corep, None).to_dicts()}

        # Assert — exactly one of value/text_value is populated per cell.
        assert by_ref["0005"]["text_value"] == "Grade 1"
        assert by_ref["0005"]["value"] is None
        assert by_ref["0060"]["value"] == 100.0
        assert by_ref["0060"]["text_value"] is None


# =============================================================================
# FilingMetadata — stamping the fact frame
# =============================================================================


class TestFilingMetadataStamping:
    def test_stamps_constant_columns(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19),
            framework="CRR",
            run_id="run-123",
            entity_identifier="LEI999",
        )

        # Act
        (row,) = facts.build_fact_frame(corep, None, metadata=meta).to_dicts()

        # Assert
        assert row["reporting_date"] == date(2026, 7, 19)
        assert row["entity_identifier"] == "LEI999"
        assert row["run_id"] == "run-123"
        assert row["generator_version"]

    def test_entity_identifier_optional(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act
        frame = facts.build_fact_frame(corep, None, metadata=meta)

        # Assert
        assert frame["entity_identifier"].to_list() == [None]

    def test_no_metadata_omits_metadata_columns(self) -> None:
        # Arrange
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})

        # Act
        frame = facts.build_fact_frame(corep, None)

        # Assert
        assert frame.columns == _FACT_COLUMNS
        assert "reporting_date" not in frame.columns
        assert "run_id" not in frame.columns

    def test_stamps_empty_frame_too(self) -> None:
        # Arrange
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act
        frame = facts.build_fact_frame(None, None, metadata=meta)

        # Assert
        assert frame.height == 0
        assert "reporting_date" in frame.columns


# =============================================================================
# FilingMetadata — standalone methods
# =============================================================================


class TestFilingMetadataMethods:
    def test_as_sheet_fields(self) -> None:
        # Arrange
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19),
            framework="CRR",
            run_id="run-1",
            entity_identifier="LEI1",
            generator_version="9.9.9",
        )

        # Act
        fields = meta.as_sheet_fields()

        # Assert
        assert fields == {
            "Reporting date": "2026-07-19",
            "Framework": "CRR",
            "Entity identifier": "LEI1",
            "Run ID": "run-1",
            "Generator version": "9.9.9",
        }

    def test_as_sheet_fields_blanks_missing_entity_identifier(self) -> None:
        # Arrange
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act / Assert
        assert meta.as_sheet_fields()["Entity identifier"] == ""

    def test_stamped_filename(self) -> None:
        # Arrange
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act / Assert
        assert meta.stamped_filename("rwa_corep", "xlsx") == "rwa_corep_CRR_2026-07-19.xlsx"

    def test_default_generator_version_matches_the_installed_package(self) -> None:
        # Arrange
        from rwa_calc import __version__

        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act / Assert
        assert meta.generator_version == __version__

    def test_frozen(self) -> None:
        # Arrange
        meta = facts.FilingMetadata(
            reporting_date=date(2026, 7, 19), framework="CRR", run_id="run-1"
        )

        # Act / Assert
        with pytest.raises(AttributeError):
            meta.run_id = "other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
