"""Tests for the input-domain validation functions.

Covers the declared-domain predicates (``ColumnSpec.domain``), the categorical
column-value validators, and the whole-bundle input gate that drives both.

Phase 1 of docs/plans/test-space-correctness-proposal.md replaced the four
hand-written range validators (``validate_pd_range``, ``validate_lgd_range``,
``validate_ccf_modelled``, ``validate_non_negative_amounts``) with declarations
read generically. The behavioural coverage they carried lives in
``TestDeclaredDomains`` below, asserted against the DECLARATIONS in
``data/schemas.py`` rather than against default arguments — so a test cannot
pass while the shipped bound differs from the one under test.
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.validation import (
    validate_bundle_values,
    validate_column_values,
)
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity


def _domain(schema: dict, column: str):
    """The declared domain for a column, failing loudly when it is absent."""
    spec = schema[column]
    assert spec.domain is not None, f"{column} must declare a domain"
    return spec.domain


class TestDeclaredDomains:
    """The shipped declarations admit exactly the values the regulation does."""

    @staticmethod
    def _violations(domain, column: str, values: list) -> list[bool]:
        lf = pl.LazyFrame({column: values})
        return lf.select(domain.violation_expr(column)).collect().to_series().to_list()

    def test_pd_admits_zero_and_one_and_rejects_percent_scale(self):
        """PD is CLOSED at zero (CRR has no sovereign floor) and capped at 1."""
        domain = _domain(RATINGS_SCHEMA, "pd")

        assert self._violations(domain, "pd", [0.0, 0.0003, 0.5, 1.0]) == [False] * 4
        assert self._violations(domain, "pd", [-0.01, 1.5, 100.0]) == [True] * 3

    def test_lgd_admits_downturn_above_one(self):
        """Own-estimate downturn LGD can exceed 100%; 1.25 is the ceiling."""
        domain = _domain(FACILITY_SCHEMA, "lgd")

        assert self._violations(domain, "lgd", [0.0, 0.45, 1.0, 1.25]) == [False] * 4
        assert self._violations(domain, "lgd", [-0.1, 1.5, 45.0]) == [True] * 3

    def test_ccf_admits_retail_additional_drawdown(self):
        """Retail A-IRB CCF can exceed 100%; 1.5 is the ceiling."""
        domain = _domain(FACILITY_SCHEMA, "ccf_modelled")

        assert self._violations(domain, "ccf_modelled", [0.0, 0.75, 1.25, 1.5]) == [False] * 4
        assert self._violations(domain, "ccf_modelled", [-0.1, 1.6, 2.0]) == [True] * 3

    def test_null_is_never_a_domain_violation(self):
        """A MISSING value is a different finding from an out-of-range one."""
        for schema, column in (
            (RATINGS_SCHEMA, "pd"),
            (FACILITY_SCHEMA, "lgd"),
            (FACILITY_SCHEMA, "ccf_modelled"),
            (FACILITY_SCHEMA, "limit"),
        ):
            domain = _domain(schema, column)
            assert self._violations(domain, column, [None, None]) == [False, False]

    def test_amount_domain_rejects_negatives_only(self):
        """Zero is a legitimate amount; a negative manufactures exposure."""
        domain = _domain(FACILITY_SCHEMA, "limit")

        assert self._violations(domain, "limit", [0.0, 100.0]) == [False, False]
        assert self._violations(domain, "limit", [-0.01, -50.0]) == [True, True]

    def test_cqs_domain_is_one_to_six(self):
        """CQS 0 / 7 / 99 / -1 all silently took a wrong branch before Phase 1."""
        domain = _domain(RATINGS_SCHEMA, "cqs")

        assert self._violations(domain, "cqs", [1, 2, 3, 4, 5, 6]) == [False] * 6
        assert self._violations(domain, "cqs", [0, 7, 99, -1]) == [True] * 4

    def test_effective_maturity_is_open_at_zero(self):
        """A zero-year maturity is not a maturity — the lower bound is OPEN."""
        domain = _domain(CONTINGENTS_SCHEMA, "effective_maturity")

        assert self._violations(domain, "effective_maturity", [0.25, 1.0, 5.0]) == [False] * 3
        assert self._violations(domain, "effective_maturity", [0.0, -3.0, 5.01]) == [True] * 3

    def test_fx_rate_is_open_at_zero(self):
        """A zero rate silently zeroes every converted amount."""
        domain = _domain(FX_RATES_SCHEMA, "rate")

        assert self._violations(domain, "rate", [0.0001, 1.0, 1500.0]) == [False] * 3
        assert self._violations(domain, "rate", [0.0, -1.2]) == [True, True]

    @pytest.mark.parametrize(
        ("schema", "column"),
        [
            (RATINGS_SCHEMA, "pd"),
            (RATINGS_SCHEMA, "cqs"),
            (FACILITY_SCHEMA, "lgd"),
            (FACILITY_SCHEMA, "limit"),
            (FX_RATES_SCHEMA, "rate"),
        ],
    )
    def test_every_domain_states_its_basis(self, schema: dict, column: str) -> None:
        """A bound with no stated reason is how a WRONG bound survives review."""
        reason = _domain(schema, column).reason

        assert len(reason) > 40, f"{column}: reason is too thin to review: {reason!r}"


class TestValidateColumnValues:
    """Tests for validate_column_values function."""

    def test_all_valid_returns_empty(self):
        """All valid values should return no errors."""
        lf = pl.LazyFrame({"entity_type": ["sovereign", "corporate", "retail"]})
        valid = {"sovereign", "corporate", "retail"}

        errors = validate_column_values(lf, "entity_type", valid, context="counterparties")

        assert errors == []

    def test_invalid_values_detected(self):
        """Invalid values should produce errors."""
        lf = pl.LazyFrame({"entity_type": ["sovereign", "INVALID", "corporate"]})
        valid = {"sovereign", "corporate", "retail"}

        errors = validate_column_values(lf, "entity_type", valid, context="counterparties")

        assert len(errors) == 1
        assert errors[0].code == "DQ006"
        assert errors[0].category == ErrorCategory.DATA_QUALITY
        assert "INVALID" in errors[0].message
        assert errors[0].field_name == "entity_type"

    def test_case_insensitive(self):
        """Validation should be case insensitive."""
        lf = pl.LazyFrame({"entity_type": ["Sovereign", "CORPORATE", "Retail"]})
        valid = {"sovereign", "corporate", "retail"}

        errors = validate_column_values(lf, "entity_type", valid, context="counterparties")

        assert errors == []

    def test_null_values_skipped(self):
        """Null values should be skipped (not treated as invalid)."""
        lf = pl.LazyFrame({"seniority": ["senior", None, "subordinated", None]})
        valid = {"senior", "subordinated"}

        errors = validate_column_values(lf, "seniority", valid, context="facilities")

        assert errors == []

    def test_missing_column_returns_empty(self):
        """Missing column should return no errors."""
        lf = pl.LazyFrame({"other_col": ["a", "b"]})
        valid = {"senior", "subordinated"}

        errors = validate_column_values(lf, "seniority", valid, context="facilities")

        assert errors == []

    def test_multiple_invalid_values(self):
        """Multiple distinct invalid values should each produce an error."""
        lf = pl.LazyFrame({"entity_type": ["bad1", "bad2", "sovereign", "bad1"]})
        valid = {"sovereign", "corporate"}

        errors = validate_column_values(lf, "entity_type", valid, context="counterparties")

        assert len(errors) == 2
        messages = {e.actual_value for e in errors}
        assert "bad1" in messages
        assert "bad2" in messages

    def test_error_includes_row_count(self):
        """Error message should include the count of invalid rows."""
        lf = pl.LazyFrame({"entity_type": ["bad", "bad", "bad"]})
        valid = {"sovereign"}

        errors = validate_column_values(lf, "entity_type", valid, context="test")

        assert len(errors) == 1
        assert "3 row(s)" in errors[0].message

    def test_empty_frame_returns_empty(self):
        """Empty LazyFrame should return no errors."""
        lf = pl.LazyFrame({"entity_type": pl.Series([], dtype=pl.String)})
        valid = {"sovereign"}

        errors = validate_column_values(lf, "entity_type", valid, context="test")

        assert errors == []


class TestValidateBundleValues:
    """Tests for validate_bundle_values function."""

    def _make_bundle(self, **overrides) -> RawDataBundle:
        """Create a minimal RawDataBundle with overrides."""
        defaults = {
            "facilities": pl.LazyFrame({"facility_reference": pl.Series([], dtype=pl.String)}),
            "loans": pl.LazyFrame({"loan_reference": pl.Series([], dtype=pl.String)}),
            "counterparties": pl.LazyFrame(
                {"counterparty_reference": pl.Series([], dtype=pl.String)}
            ),
            "facility_mappings": pl.LazyFrame(
                {"parent_facility_reference": pl.Series([], dtype=pl.String)}
            ),
            "lending_mappings": pl.LazyFrame(
                {"parent_counterparty_reference": pl.Series([], dtype=pl.String)}
            ),
        }
        defaults.update(overrides)
        return make_raw_bundle(**defaults)

    def test_valid_bundle_returns_empty(self):
        """Bundle with all valid values should return no errors."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"entity_type": ["sovereign", "corporate"]}),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_entity_type_detected(self):
        """Invalid entity_type should produce error."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"entity_type": ["sovereign", "INVALID_TYPE"]}),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 1
        assert errors[0].field_name is not None
        assert "entity_type" in errors[0].field_name
        assert "INVALID_TYPE" in errors[0].message

    def test_none_tables_skipped(self):
        """Optional None tables should be skipped without error."""
        bundle = self._make_bundle(
            collateral=None,
            guarantees=None,
            provisions=None,
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_multiple_table_errors(self):
        """Errors from multiple tables should all be collected.

        Both toy frames carry a resolvable ``counterparty_reference``. Without
        one the facility row asserts no obligor at all, which the referential
        gate reports as a third error — true, but not what this test counts.
        """
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame(
                {"counterparty_reference": ["CP1"], "entity_type": ["BAD"]}
            ),
            facilities=pl.LazyFrame({"counterparty_reference": ["CP1"], "seniority": ["WRONG"]}),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 2
        tables = {e.message.split("]")[0].strip("[") for e in errors}
        assert "counterparties" in tables
        assert "facilities" in tables

    def test_custom_constraints(self):
        """Should accept custom constraints dict."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"entity_type": ["alien"]}),
        )
        custom = {"counterparties": {"entity_type": {"alien", "robot"}}}

        errors = validate_bundle_values(bundle, constraints=custom)

        assert errors == []

    def test_valid_ciu_approach_accepted(self):
        """Valid ciu_approach values should return no errors."""
        bundle = self._make_bundle(
            equity_exposures=pl.LazyFrame(
                {"ciu_approach": ["look_through", "mandate_based", "fallback"]}
            ),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_ciu_approach_detected(self):
        """Invalid ciu_approach should produce error."""
        bundle = self._make_bundle(
            equity_exposures=pl.LazyFrame({"ciu_approach": ["look_through", "INVALID_APPROACH"]}),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 1
        assert errors[0].field_name is not None
        assert "ciu_approach" in errors[0].field_name
        assert "INVALID_APPROACH" in errors[0].message

    def test_valid_adc_property_type_accepted(self):
        """ADC property type should be accepted as a valid value."""
        bundle = self._make_bundle(
            collateral=pl.LazyFrame({"property_type": ["residential", "commercial", "adc"]}),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_property_type_detected(self):
        """Invalid property_type should produce error."""
        bundle = self._make_bundle(
            collateral=pl.LazyFrame({"property_type": ["residential", "INVALID"]}),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 1
        assert errors[0].field_name is not None
        assert "property_type" in errors[0].field_name
        assert "INVALID" in errors[0].message

    def test_valid_risk_type_accepted(self):
        """Valid risk_type values should return no errors.

        Every facility row names an obligor that exists — a bundle whose
        facilities have no counterparty is not a no-errors bundle, whatever
        its risk_type values say.
        """
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"counterparty_reference": ["CP1"]}),
            facilities=pl.LazyFrame(
                {
                    "counterparty_reference": ["CP1"] * 6,
                    "risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"],
                }
            ),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_risk_type_detected(self):
        """Invalid risk_type should produce error."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"counterparty_reference": ["CP1"]}),
            facilities=pl.LazyFrame(
                {"counterparty_reference": ["CP1"] * 2, "risk_type": ["FR", "BAD_TYPE"]}
            ),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 1
        assert errors[0].field_name is not None
        assert "risk_type" in errors[0].field_name
        assert "BAD_TYPE" in errors[0].message

    def test_valid_scra_grade_accepted(self):
        """Valid scra_grade values should return no errors."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"scra_grade": ["A", "A_ENHANCED", "B", "C"]}),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_scra_grade_detected(self):
        """Invalid scra_grade should produce error."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"scra_grade": ["A", "D"]}),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 1
        assert errors[0].field_name is not None
        assert "scra_grade" in errors[0].field_name

    def test_null_ciu_approach_skipped(self):
        """Null ciu_approach values should not produce errors (nullable field)."""
        bundle = self._make_bundle(
            equity_exposures=pl.LazyFrame(
                {"ciu_approach": pl.Series([None, "look_through"], dtype=pl.String)}
            ),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_equity_exposures_multiple_constraints(self):
        """Both equity_type and ciu_approach validated on equity_exposures."""
        bundle = self._make_bundle(
            equity_exposures=pl.LazyFrame(
                {
                    "equity_type": ["listed", "BAD_EQ"],
                    "ciu_approach": ["look_through", "BAD_CIU"],
                }
            ),
        )

        errors = validate_bundle_values(bundle)

        assert len(errors) == 2
        fields = {e.field_name for e in errors}
        assert any("equity_type" in f for f in fields if f)
        assert any("ciu_approach" in f for f in fields if f)


class TestNumericInputDomainGate:
    """The numeric input-domain gate wired into validate_bundle_values.

    The four range validators only add boolean flag columns; these tests
    cover the collector that turns those flags into row-named
    CalculationErrors on the whole-bundle path.
    """

    def _bundle(self, **overrides) -> RawDataBundle:
        return make_raw_bundle(**overrides)

    def _domain_errors(self, bundle: RawDataBundle, code: str) -> list:
        return [e for e in validate_bundle_values(bundle) if e.code == code]

    def test_pd_above_one_is_an_error_naming_the_row(self):
        """A percent-scaled PD feed (1.5 meaning 1.5%) is rejected, not floored."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R-BAD", "R-OK"],
                    "counterparty_reference": ["C1", "C2"],
                    "pd": [1.5, 0.02],
                }
            ),
        )

        errors = self._domain_errors(bundle, "IRB001")

        assert len(errors) == 1
        assert errors[0].exposure_reference == "R-BAD"
        assert errors[0].severity == ErrorSeverity.ERROR
        assert errors[0].field_name == "pd"
        assert errors[0].actual_value == "1.5"

    def test_negative_pd_is_an_error(self):
        """A negative PD is rejected rather than silently floored."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R-NEG"],
                    "counterparty_reference": ["C1"],
                    "pd": [-0.01],
                }
            ),
        )

        errors = self._domain_errors(bundle, "IRB001")

        assert len(errors) == 1
        assert errors[0].exposure_reference == "R-NEG"

    def test_pd_zero_is_in_domain(self):
        """PD = 0 is admissible: CRR Art. 160(1) has no CGCB limb (pack sovereign floor = 0)."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R-SOV"],
                    "counterparty_reference": ["C1"],
                    "pd": [0.0],
                }
            ),
        )

        assert self._domain_errors(bundle, "IRB001") == []

    def test_null_pd_is_not_a_domain_violation(self):
        """A missing PD is IRB004's business, not the domain gate's."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R1"],
                    "counterparty_reference": ["C1"],
                    "pd": pl.Series([None], dtype=pl.Float64),
                }
            ),
        )

        assert self._domain_errors(bundle, "IRB001") == []

    def test_lgd_out_of_domain_on_both_lgd_columns(self):
        """lgd and lgd_unsecured are each validated, with distinct flags."""
        bundle = self._bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "lgd": [1.8],
                    "lgd_unsecured": [-0.2],
                }
            ),
        )

        errors = self._domain_errors(bundle, "IRB002")

        assert {e.field_name for e in errors} == {"lgd", "lgd_unsecured"}
        assert all(e.exposure_reference == "L1" for e in errors)

    def test_ccf_modelled_out_of_domain(self):
        """ccf_modelled above 150% is rejected; null is valid."""
        bundle = self._bundle(
            facilities=pl.LazyFrame(
                {
                    "facility_reference": ["F-BAD", "F-NULL"],
                    "ccf_modelled": [2.0, None],
                }
            ),
        )

        errors = self._domain_errors(bundle, "IRB008")

        assert len(errors) == 1
        assert errors[0].exposure_reference == "F-BAD"

    def test_negative_amount_columns_flagged(self):
        """A negative collateral market value manufactures relief from nothing."""
        bundle = self._bundle(
            collateral=pl.LazyFrame(
                {
                    "collateral_reference": ["X1"],
                    "collateral_type": ["cash"],
                    "market_value": [-5.0],
                }
            ),
        )

        errors = self._domain_errors(bundle, "DQ012")

        assert len(errors) == 1
        assert errors[0].exposure_reference == "X1"
        assert errors[0].field_name == "market_value"

    def test_negative_drawn_amount_is_not_a_domain_violation(self):
        """drawn_amount may be negative — the Art. 195/219 netting convention (DQ010 only)."""
        bundle = self._bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "drawn_amount": [-100.0],
                    "netting_agreement_reference": ["N1"],
                }
            ),
        )

        errors = validate_bundle_values(bundle)

        assert [e for e in errors if e.code == "DQ012"] == []
        assert [e for e in errors if e.code == "DQ010"] == []

    def test_signed_position_value_is_not_a_domain_violation(self):
        """position_value is declared signed (+long / -short) for the Art. 133 net long."""
        bundle = self._bundle(
            equity_exposures=pl.LazyFrame(
                {
                    "exposure_reference": ["EQ-SHORT"],
                    "counterparty_reference": ["C1"],
                    "position_value": [-400_000.0],
                }
            ),
        )

        assert self._domain_errors(bundle, "DQ012") == []

    def test_violations_are_sample_capped_with_a_summary(self):
        """More than five bad rows yield five named errors plus one omitted-count summary."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": [f"R{i}" for i in range(8)],
                    "counterparty_reference": ["C1"] * 8,
                    "pd": [1.5] * 8,
                }
            ),
        )

        errors = self._domain_errors(bundle, "IRB001")

        named = [e for e in errors if e.exposure_reference is not None]
        summary = [e for e in errors if e.exposure_reference is None]
        assert len(named) == 5
        assert len(summary) == 1
        assert "3 additional row(s) omitted" in summary[0].message

    def test_clean_bundle_raises_nothing(self):
        """In-domain values on every validated column produce no errors.

        "Clean" now has to mean referentially clean too: C1 exists, and the
        loan and facility name it. The earlier form declared a rating for a
        counterparty that was not in the bundle and gave its exposures no
        obligor at all, so it was asserting that a broken bundle is silent.
        """
        bundle = self._bundle(
            counterparties=pl.LazyFrame({"counterparty_reference": ["C1"]}),
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R1"],
                    "counterparty_reference": ["C1"],
                    "pd": [0.02],
                }
            ),
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "counterparty_reference": ["C1"],
                    "lgd": [0.45],
                    "drawn_amount": [1000.0],
                }
            ),
            facilities=pl.LazyFrame(
                {
                    "facility_reference": ["F1"],
                    "counterparty_reference": ["C1"],
                    "limit": [5000.0],
                    "ccf_modelled": [0.75],
                }
            ),
        )

        assert validate_bundle_values(bundle) == []
