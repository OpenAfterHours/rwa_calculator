"""Unit tests: FilingMetadata reporting-scope fields (multi-entity reporting W1-A).

Pins the filing-metadata half of run-per-scope submissions:
- ``entity_name`` / ``consolidation_basis`` appear on the metadata sheet only
  when set, so an un-scoped run's sheet is byte-identical to before;
- ``stamped_filename`` appends filesystem-safe lowercase ``_<entity>_<basis>``
  tokens only when present, and is unchanged when absent;
- both fields are stamped as constant columns onto the fact frame (null when
  unset), matching ``entity_identifier``'s existing treatment.

References:
- src/rwa_calc/reporting/facts.py (module under test)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting import facts
from rwa_calc.reporting.corep.generator import COREPTemplateBundle

# =============================================================================
# Builders
# =============================================================================


def _sheet(**cols: Sequence[object]) -> pl.DataFrame:
    data: dict[str, Sequence[object]] = {"row_ref": ["0010"], "row_name": ["Total exposures"]}
    data.update(cols)
    return pl.DataFrame(data)


def _corep(**fields: object) -> COREPTemplateBundle:
    base: dict[str, Any] = {"c07_00": {}, "c08_01": {}, "c08_02": {}}
    base.update(fields)
    return COREPTemplateBundle(**base)


def _meta(**overrides: object) -> facts.FilingMetadata:
    params: dict[str, Any] = {
        "reporting_date": date(2026, 7, 19),
        "framework": "CRR",
        "run_id": "run-1",
    }
    params.update(overrides)
    return facts.FilingMetadata(**params)


# =============================================================================
# New fields — defaults / immutability
# =============================================================================


class TestScopeFields:
    def test_defaults_are_none(self) -> None:
        meta = _meta()

        assert meta.entity_name is None
        assert meta.consolidation_basis is None

    def test_frozen(self) -> None:
        meta = _meta()

        with pytest.raises(AttributeError):
            meta.consolidation_basis = "consolidated"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


# =============================================================================
# as_sheet_fields
# =============================================================================


class TestAsSheetFields:
    def test_unscoped_sheet_is_unchanged(self) -> None:
        # No entity_name / consolidation_basis -> exactly the original five rows.
        fields = _meta(entity_identifier="LEI1", generator_version="9.9.9").as_sheet_fields()

        assert fields == {
            "Reporting date": "2026-07-19",
            "Framework": "CRR",
            "Entity identifier": "LEI1",
            "Run ID": "run-1",
            "Generator version": "9.9.9",
        }

    def test_scope_rows_appear_when_set(self) -> None:
        fields = _meta(
            entity_identifier="LEI1",
            entity_name="Group Apex Ltd",
            consolidation_basis="consolidated",
        ).as_sheet_fields()

        assert fields["Entity name"] == "Group Apex Ltd"
        assert fields["Consolidation basis"] == "consolidated"

    def test_scope_rows_sit_between_identifier_and_run_id(self) -> None:
        # Grouping check: the scope rows follow the identifier, before Run ID.
        keys = list(
            _meta(
                entity_identifier="LEI1",
                entity_name="Group Apex Ltd",
                consolidation_basis="consolidated",
            )
            .as_sheet_fields()
            .keys()
        )

        assert keys == [
            "Reporting date",
            "Framework",
            "Entity identifier",
            "Entity name",
            "Consolidation basis",
            "Run ID",
            "Generator version",
        ]

    def test_only_entity_name_set(self) -> None:
        fields = _meta(entity_name="Solo Bank").as_sheet_fields()

        assert fields["Entity name"] == "Solo Bank"
        assert "Consolidation basis" not in fields


# =============================================================================
# stamped_filename
# =============================================================================


class TestStampedFilename:
    def test_unchanged_when_no_scope(self) -> None:
        assert _meta().stamped_filename("rwa_corep", "xlsx") == "rwa_corep_CRR_2026-07-19.xlsx"

    def test_appends_entity_and_basis_tokens_lowercased(self) -> None:
        name = _meta(
            entity_identifier="LEI123",
            consolidation_basis="consolidated",
        ).stamped_filename("rwa_corep", "xlsx")

        assert name == "rwa_corep_CRR_2026-07-19_lei123_consolidated.xlsx"

    def test_basis_only_appends_single_token(self) -> None:
        name = _meta(consolidation_basis="sub_consolidated").stamped_filename("rwa_corep", "xlsx")

        # Underscores are already filesystem-safe and preserved.
        assert name == "rwa_corep_CRR_2026-07-19_sub_consolidated.xlsx"

    def test_entity_only_appends_single_token(self) -> None:
        name = _meta(entity_identifier="Entity A").stamped_filename("rwa_corep", "xlsx")

        # A space is not filesystem-safe -> collapsed to a hyphen, lowercased.
        assert name == "rwa_corep_CRR_2026-07-19_entity-a.xlsx"

    def test_unsafe_characters_are_sanitised(self) -> None:
        name = _meta(
            entity_identifier="A/B:C*",
            consolidation_basis="Individual",
        ).stamped_filename("rwa_corep", "csv")

        assert name == "rwa_corep_CRR_2026-07-19_a-b-c_individual.csv"

    def test_all_unsafe_token_drops_without_dangling_underscore(self) -> None:
        # "***" slugs to "" — it must contribute no token (no trailing "_"),
        # and a following real token must not inherit a dangling separator.
        assert (
            _meta(entity_identifier="***").stamped_filename("rwa_corep", "xlsx")
            == "rwa_corep_CRR_2026-07-19.xlsx"
        )
        assert (
            _meta(entity_identifier="***", consolidation_basis="consolidated").stamped_filename(
                "rwa_corep", "xlsx"
            )
            == "rwa_corep_CRR_2026-07-19_consolidated.xlsx"
        )


# =============================================================================
# Fact-frame stamping
# =============================================================================


class TestFactFrameStamping:
    def test_scope_columns_stamped_when_set(self) -> None:
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})
        meta = _meta(entity_name="Group Apex Ltd", consolidation_basis="consolidated")

        (row,) = facts.build_fact_frame(corep, None, metadata=meta).to_dicts()

        assert row["entity_name"] == "Group Apex Ltd"
        assert row["consolidation_basis"] == "consolidated"

    def test_scope_columns_null_when_unset(self) -> None:
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})

        frame = facts.build_fact_frame(corep, None, metadata=_meta())

        assert frame["entity_name"].to_list() == [None]
        assert frame["consolidation_basis"].to_list() == [None]

    def test_no_metadata_omits_scope_columns(self) -> None:
        corep = _corep(c07_00={"corporate": _sheet(**{"0010": [1.0]})})

        frame = facts.build_fact_frame(corep, None)

        assert "entity_name" not in frame.columns
        assert "consolidation_basis" not in frame.columns
