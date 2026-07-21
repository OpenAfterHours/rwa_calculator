"""
Unit tests for the multi-entity reporting input schemas and the intragroup /
book-attribution columns added to the exposure-bearing schemas.

Covers the two OPTIONAL registries that let one institution emit per-scope
regulatory submissions (group consolidated, sub-consolidated, solo), plus the
nullable tagging columns the scope-resolver stage keys on.

References:
- CRR Art. 6 / 11-18: individual / consolidated / sub-consolidated levels of
  application.
- docs/plans/multi-entity-reporting.md (Data model, wave W1-B).
"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.schemas import (
    BOOK_ENTITY_MAPPING_SCHEMA,
    CONTINGENTS_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    NETTING_SET_SCHEMA,
    REPORTING_ENTITY_SCHEMA,
    SFT_TRADE_SCHEMA,
)

# Exposure-bearing schemas that gain ``intragroup_entity_reference``.
_INTRAGROUP_SCHEMAS = {
    "FACILITY_SCHEMA": FACILITY_SCHEMA,
    "LOAN_SCHEMA": LOAN_SCHEMA,
    "CONTINGENTS_SCHEMA": CONTINGENTS_SCHEMA,
    "EQUITY_EXPOSURE_SCHEMA": EQUITY_EXPOSURE_SCHEMA,
    "NETTING_SET_SCHEMA": NETTING_SET_SCHEMA,
    "SFT_TRADE_SCHEMA": SFT_TRADE_SCHEMA,
}

# Schemas that gain ``book_code`` in this wave (facility/loan/contingent
# already carried it).
_NEW_BOOK_CODE_SCHEMAS = {
    "EQUITY_EXPOSURE_SCHEMA": EQUITY_EXPOSURE_SCHEMA,
    "NETTING_SET_SCHEMA": NETTING_SET_SCHEMA,
    "SFT_TRADE_SCHEMA": SFT_TRADE_SCHEMA,
}

# SA lending schemas that gain the CRR Art. 113(6) 0%-RW eligibility carrier
# (Wave 4). Deliberately NOT equity / CCR / SFT — those grains are out of scope.
_ZERO_RW_CARRIER_SCHEMAS = {
    "FACILITY_SCHEMA": FACILITY_SCHEMA,
    "LOAN_SCHEMA": LOAN_SCHEMA,
    "CONTINGENTS_SCHEMA": CONTINGENTS_SCHEMA,
}


class TestReportingEntitySchema:
    """The reporting-hierarchy registry (config/reporting_entities)."""

    def test_entity_reference_is_the_only_required_column(self) -> None:
        # Arrange / Act
        required = {name for name, spec in REPORTING_ENTITY_SCHEMA.items() if spec.required}

        # Assert
        assert required == {"entity_reference"}

    def test_declares_the_expected_columns(self) -> None:
        # Assert — exact column set per the design brief's data-model table.
        assert set(REPORTING_ENTITY_SCHEMA) == {
            "entity_reference",
            "entity_name",
            "lei",
            "parent_entity_reference",
            "institution_type",
            "core_uk_group",
        }

    def test_string_columns_are_strings(self) -> None:
        for column in (
            "entity_reference",
            "entity_name",
            "lei",
            "parent_entity_reference",
            "institution_type",
        ):
            assert REPORTING_ENTITY_SCHEMA[column].dtype == pl.String, column

    def test_core_uk_group_is_boolean_defaulting_false(self) -> None:
        # Assert — Art. 113(6) perimeter defaults conservatively to outside.
        spec = REPORTING_ENTITY_SCHEMA["core_uk_group"]

        assert spec.dtype == pl.Boolean
        assert spec.default is False
        assert spec.required is False


class TestBookEntityMappingSchema:
    """The booking-book -> reporting-entity map (mapping/book_entity_mapping)."""

    def test_both_columns_are_required(self) -> None:
        # Arrange / Act
        required = {name for name, spec in BOOK_ENTITY_MAPPING_SCHEMA.items() if spec.required}

        # Assert
        assert required == {"book_code", "reporting_entity_reference"}

    def test_declares_exactly_two_string_columns(self) -> None:
        assert set(BOOK_ENTITY_MAPPING_SCHEMA) == {"book_code", "reporting_entity_reference"}
        assert BOOK_ENTITY_MAPPING_SCHEMA["book_code"].dtype == pl.String
        assert BOOK_ENTITY_MAPPING_SCHEMA["reporting_entity_reference"].dtype == pl.String


class TestIntragroupEntityReferenceColumn:
    """``intragroup_entity_reference`` is a nullable String on every exposure schema."""

    def test_present_on_all_exposure_schemas(self) -> None:
        for name, schema in _INTRAGROUP_SCHEMAS.items():
            assert "intragroup_entity_reference" in schema, name

    def test_is_optional_nullable_string_with_no_default(self) -> None:
        # A null tag means "not intragroup" — the absence of data must never
        # fabricate an intragroup relationship, so there is no default fill.
        for name, schema in _INTRAGROUP_SCHEMAS.items():
            spec = schema["intragroup_entity_reference"]
            assert spec.dtype == pl.String, name
            assert spec.required is False, name
            assert spec.default is None, name


class TestIntragroupZeroRwEligibleColumn:
    """``intragroup_zero_rw_eligible`` — CRR Art. 113(6) 0%-RW carrier (Wave 4)."""

    def test_present_on_the_sa_lending_schemas(self) -> None:
        for name, schema in _ZERO_RW_CARRIER_SCHEMAS.items():
            assert "intragroup_zero_rw_eligible" in schema, name

    def test_is_optional_boolean_defaulting_false(self) -> None:
        # Default False so unscoped / non-CUG / consolidated runs are byte-identical;
        # the scope resolver overwrites it on eligible individual-basis rows.
        for name, schema in _ZERO_RW_CARRIER_SCHEMAS.items():
            spec = schema["intragroup_zero_rw_eligible"]
            assert spec.dtype == pl.Boolean, name
            assert spec.required is False, name
            assert spec.default is False, name

    def test_absent_from_equity_ccr_and_sft_grains(self) -> None:
        # The 0% treatment is SA lending only this wave.
        for name, schema in (
            ("EQUITY_EXPOSURE_SCHEMA", EQUITY_EXPOSURE_SCHEMA),
            ("NETTING_SET_SCHEMA", NETTING_SET_SCHEMA),
            ("SFT_TRADE_SCHEMA", SFT_TRADE_SCHEMA),
        ):
            assert "intragroup_zero_rw_eligible" not in schema, name


class TestGuarantorEntityReferenceColumn:
    """``guarantor_entity_reference`` is a nullable String on the guarantee schema."""

    def test_present_and_optional_nullable_string(self) -> None:
        spec = GUARANTEE_SCHEMA["guarantor_entity_reference"]

        assert spec.dtype == pl.String
        assert spec.required is False
        assert spec.default is None


class TestBookCodeMirrored:
    """``book_code`` mirrors the facility/loan/contingent definition on new schemas."""

    def test_book_code_added_with_matching_definition(self) -> None:
        # The reference definition lives on FACILITY_SCHEMA (default "", optional).
        reference = FACILITY_SCHEMA["book_code"]

        for name, schema in _NEW_BOOK_CODE_SCHEMAS.items():
            spec = schema["book_code"]
            assert spec.dtype == reference.dtype == pl.String, name
            assert spec.default == reference.default == "", name
            assert spec.required is reference.required is False, name
