"""
Contract tests for loading the multi-entity reporting input tables.

Asserts the loader wires the two OPTIONAL registries (``reporting_entities``,
``book_entity_mapping``) into the ``RawDataBundle`` via the shared optional-table
path, that an absent file resolves to ``None`` (non-blocking), and that the new
nullable tagging / book columns on the exposure schemas default correctly when
the input parquet omits them.

References:
- CRR Art. 6 / 11-18: individual / consolidated / sub-consolidated levels of
  application.
- docs/plans/multi-entity-reporting.md (Data model, wave W1-B).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.edges import RAW_TABLE_EDGES
from rwa_calc.engine.loader import ParquetLoader


def _write_required_tables(base: Path) -> None:
    """Write the four mandatory input tables with their required columns."""
    (base / "counterparty").mkdir(parents=True, exist_ok=True)
    (base / "exposures").mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"counterparty_reference": ["CP1"], "entity_type": ["corporate"]}).write_parquet(
        base / "counterparty" / "counterparties.parquet"
    )
    pl.DataFrame({"facility_reference": ["FAC1"], "counterparty_reference": ["CP1"]}).write_parquet(
        base / "exposures" / "facilities.parquet"
    )
    pl.DataFrame({"loan_reference": ["LN1"], "counterparty_reference": ["CP1"]}).write_parquet(
        base / "exposures" / "loans.parquet"
    )
    pl.DataFrame({"parent_facility_reference": ["FAC1"], "child_reference": ["LN1"]}).write_parquet(
        base / "exposures" / "facility_mapping.parquet"
    )


def _write_scope_tables(base: Path) -> None:
    """Write the two optional multi-entity reporting registries."""
    (base / "config").mkdir(parents=True, exist_ok=True)
    (base / "mapping").mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "entity_reference": ["GRP", "SUB_A"],
            "entity_name": ["Group Apex", "Subsidiary A"],
            "parent_entity_reference": [None, "GRP"],
            "institution_type": ["standalone_uk", "standalone_uk"],
        }
    ).write_parquet(base / "config" / "reporting_entities.parquet")
    pl.DataFrame(
        {
            "book_code": ["BOOK_1", "BOOK_2"],
            "reporting_entity_reference": ["GRP", "SUB_A"],
        }
    ).write_parquet(base / "mapping" / "book_entity_mapping.parquet")


class TestScopeInputsLoaded:
    """The loader attaches both registries when the files are present."""

    def test_reporting_entities_loaded_as_lazyframe(self, tmp_path: Path) -> None:
        # Arrange
        _write_required_tables(tmp_path)
        _write_scope_tables(tmp_path)

        # Act
        bundle = ParquetLoader(tmp_path).load()

        # Assert
        assert isinstance(bundle.reporting_entities, pl.LazyFrame)
        df = bundle.reporting_entities.collect()
        assert set(df.columns) >= {
            "entity_reference",
            "entity_name",
            "lei",
            "parent_entity_reference",
            "institution_type",
            "core_uk_group",
        }
        assert sorted(df["entity_reference"].to_list()) == ["GRP", "SUB_A"]

    def test_book_entity_mapping_loaded_as_lazyframe(self, tmp_path: Path) -> None:
        # Arrange
        _write_required_tables(tmp_path)
        _write_scope_tables(tmp_path)

        # Act
        bundle = ParquetLoader(tmp_path).load()

        # Assert
        assert isinstance(bundle.book_entity_mappings, pl.LazyFrame)
        df = bundle.book_entity_mappings.collect()
        assert set(df.columns) == {"book_code", "reporting_entity_reference"}
        assert df.height == 2

    def test_core_uk_group_defaults_false_when_absent(self, tmp_path: Path) -> None:
        # The registry omits core_uk_group; the loader edge injects the Boolean
        # default (False) rather than a null.
        _write_required_tables(tmp_path)
        _write_scope_tables(tmp_path)

        bundle = ParquetLoader(tmp_path).load()

        df = bundle.reporting_entities.collect()
        assert df["core_uk_group"].to_list() == [False, False]


class TestScopeInputsAbsent:
    """Absent registries resolve to None — non-blocking, no behaviour change."""

    def test_both_fields_none_when_files_absent(self, tmp_path: Path) -> None:
        # Arrange — only the mandatory tables, no scope files.
        _write_required_tables(tmp_path)

        # Act
        bundle = ParquetLoader(tmp_path).load()

        # Assert
        assert bundle.reporting_entities is None
        assert bundle.book_entity_mappings is None

    def test_absent_scope_files_produce_no_errors(self, tmp_path: Path) -> None:
        # A missing optional file is the legitimate "not configured" case — it
        # must not accumulate a data-quality error.
        _write_required_tables(tmp_path)

        bundle = ParquetLoader(tmp_path).load()

        scope_errors = [
            e
            for e in bundle.errors
            if "reporting_entities" in str(e) or "book_entity_mapping" in str(e)
        ]
        assert scope_errors == []


class TestNewOptionalColumnsDefaulting:
    """New nullable columns default correctly when the input parquet omits them."""

    def test_intragroup_reference_injected_as_null_on_facilities(self, tmp_path: Path) -> None:
        # The facilities parquet has no intragroup_entity_reference column; the
        # loader edge injects it as a typed null String (never fabricated).
        _write_required_tables(tmp_path)

        bundle = ParquetLoader(tmp_path).load()

        df = bundle.facilities.collect()
        assert "intragroup_entity_reference" in df.columns
        assert df.schema["intragroup_entity_reference"] == pl.String
        assert df["intragroup_entity_reference"].to_list() == [None]

    def test_book_code_injected_as_empty_string_on_equity(self, tmp_path: Path) -> None:
        # An equity file without book_code gets the mirrored "" default injected.
        _write_required_tables(tmp_path)
        (tmp_path / "equity").mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            {"exposure_reference": ["EQ1"], "counterparty_reference": ["CP1"]}
        ).write_parquet(tmp_path / "equity" / "equity_exposures.parquet")

        bundle = ParquetLoader(tmp_path).load()

        assert bundle.equity_exposures is not None
        df = bundle.equity_exposures.collect()
        assert df["book_code"].to_list() == [""]
        assert df.schema["intragroup_entity_reference"] == pl.String
        assert df["intragroup_entity_reference"].to_list() == [None]


class TestBundleFieldContract:
    """The two frame fields exist on RawDataBundle and are covered by an edge."""

    def test_fields_present_and_default_none(self) -> None:
        field_names = {f.name for f in dataclasses.fields(RawDataBundle)}
        assert {"reporting_entities", "book_entity_mappings"} <= field_names

    def test_raw_table_edges_cover_the_new_frame_fields(self) -> None:
        assert "reporting_entities" in RAW_TABLE_EDGES
        assert "book_entity_mappings" in RAW_TABLE_EDGES
        assert RAW_TABLE_EDGES["reporting_entities"].name == "raw_reporting_entities"
        assert RAW_TABLE_EDGES["book_entity_mappings"].name == "raw_book_entity_mappings"
