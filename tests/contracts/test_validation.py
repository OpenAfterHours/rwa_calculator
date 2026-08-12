"""Tests for the input-domain validation functions.

Covers the four numeric range validators, the categorical column-value
validators, and the whole-bundle input gate that drives both.
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.validation import (
    validate_bundle_values,
    validate_ccf_modelled,
    validate_column_values,
    validate_lgd_range,
    validate_non_negative_amounts,
    validate_pd_range,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity


class TestValidateNonNegativeAmounts:
    """Tests for validate_non_negative_amounts function."""

    def test_adds_validation_columns(self):
        """Should add _valid_ columns for amount fields."""
        lf = pl.LazyFrame(
            {
                "amount1": [100.0, -50.0, 0.0],
                "amount2": [200.0, 300.0, -100.0],
            }
        )

        result = validate_non_negative_amounts(lf, ["amount1", "amount2"])
        df = result.collect()

        assert "_valid_amount1" in df.columns
        assert "_valid_amount2" in df.columns
        assert df["_valid_amount1"].to_list() == [True, False, True]
        assert df["_valid_amount2"].to_list() == [True, True, False]

    def test_ignores_missing_columns(self):
        """Should ignore columns not in LazyFrame."""
        lf = pl.LazyFrame({"amount1": [100.0, 200.0]})

        result = validate_non_negative_amounts(lf, ["amount1", "missing"])
        df = result.collect()

        assert "_valid_amount1" in df.columns
        assert "_valid_missing" not in df.columns


class TestValidatePDRange:
    """Tests for validate_pd_range function."""

    def test_valid_pd_values(self):
        """Valid PD values should pass validation."""
        lf = pl.LazyFrame({"pd": [0.0, 0.01, 0.5, 1.0]})

        result = validate_pd_range(lf)
        df = result.collect()

        assert all(df["_valid_pd"].to_list())

    def test_invalid_pd_values(self):
        """Invalid PD values should fail validation."""
        lf = pl.LazyFrame({"pd": [-0.01, 0.5, 1.01]})

        result = validate_pd_range(lf)
        df = result.collect()

        assert df["_valid_pd"].to_list() == [False, True, False]

    def test_custom_pd_range(self):
        """Should respect custom min/max values."""
        lf = pl.LazyFrame({"pd": [0.0003, 0.01, 0.5]})

        result = validate_pd_range(lf, min_pd=0.0003)
        df = result.collect()

        assert all(df["_valid_pd"].to_list())


class TestValidateLGDRange:
    """Tests for validate_lgd_range function."""

    def test_valid_lgd_values(self):
        """Valid LGD values should pass validation."""
        lf = pl.LazyFrame({"lgd": [0.0, 0.45, 1.0]})

        result = validate_lgd_range(lf)
        df = result.collect()

        assert all(df["_valid_lgd"].to_list())

    def test_lgd_can_exceed_one(self):
        """LGD can exceed 1.0 in some cases (downturn LGD)."""
        lf = pl.LazyFrame({"lgd": [0.45, 1.1, 1.25]})

        result = validate_lgd_range(lf, max_lgd=1.25)
        df = result.collect()

        assert all(df["_valid_lgd"].to_list())

    def test_invalid_lgd_values(self):
        """Invalid LGD values should fail validation."""
        lf = pl.LazyFrame({"lgd": [-0.1, 0.45, 1.5]})

        result = validate_lgd_range(lf, max_lgd=1.25)
        df = result.collect()

        assert df["_valid_lgd"].to_list() == [False, True, False]


class TestValidateCCFModelled:
    """Tests for validate_ccf_modelled function."""

    def test_valid_range(self):
        """Valid CCF values (0.0 to 1.5) should pass. Retail IRB can exceed 100%."""
        lf = pl.LazyFrame({"ccf_modelled": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert all(df["_valid_ccf_modelled"].to_list())

    def test_null_is_valid(self):
        """Null values should be valid (optional field)."""
        lf = pl.LazyFrame({"ccf_modelled": [0.5, None, 0.75, None]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert all(df["_valid_ccf_modelled"].to_list())

    def test_out_of_range_fails(self):
        """Values outside [0.0, 1.5] should fail."""
        lf = pl.LazyFrame({"ccf_modelled": [-0.1, 0.5, 1.25, 1.6, 2.0]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        # -0.1 fails (below 0), 0.5 passes, 1.25 passes (Retail IRB can exceed 100%), 1.6 and 2.0 fail (above 150%)
        assert df["_valid_ccf_modelled"].to_list() == [False, True, True, False, False]

    def test_missing_column(self):
        """Should return original LazyFrame if column missing."""
        lf = pl.LazyFrame({"other_column": [1.0, 2.0, 3.0]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert "_valid_ccf_modelled" not in df.columns


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
        """Errors from multiple tables should all be collected."""
        bundle = self._make_bundle(
            counterparties=pl.LazyFrame({"entity_type": ["BAD"]}),
            facilities=pl.LazyFrame({"seniority": ["WRONG"]}),
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
        """Valid risk_type values should return no errors."""
        bundle = self._make_bundle(
            facilities=pl.LazyFrame({"risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"]}),
        )

        errors = validate_bundle_values(bundle)

        assert errors == []

    def test_invalid_risk_type_detected(self):
        """Invalid risk_type should produce error."""
        bundle = self._make_bundle(
            facilities=pl.LazyFrame({"risk_type": ["FR", "BAD_TYPE"]}),
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
        """In-domain values on every validated column produce no errors."""
        bundle = self._bundle(
            ratings=pl.LazyFrame(
                {
                    "rating_reference": ["R1"],
                    "counterparty_reference": ["C1"],
                    "pd": [0.02],
                }
            ),
            loans=pl.LazyFrame({"loan_reference": ["L1"], "lgd": [0.45], "drawn_amount": [1000.0]}),
            facilities=pl.LazyFrame(
                {"facility_reference": ["F1"], "limit": [5000.0], "ccf_modelled": [0.75]}
            ),
        )

        assert validate_bundle_values(bundle) == []
