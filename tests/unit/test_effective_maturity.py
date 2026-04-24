"""Unit tests for the effective_maturity override and has_one_day_maturity_floor.

Covers the priority chain in `lf.irb.prepare_columns(config)`:
    1. `effective_maturity` input populated → firm override (clipped to [1/365, 5])
    2. `has_one_day_maturity_floor = True` → M = 1/365
    3. Basel 3.1 revolving + `facility_termination_date` → termination-date derivation
    4. `maturity_date` → standard derivation clipped [1, 5]
    5. Fallback default 2.5

References:
- CRR Art. 162(3): 1-day M floor for daily-margined SFTs/derivatives and short-term trade
- CRR Art. 162(2A)(k) / PS1/26: revolving termination-date path
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb import IRBExpr, IRBLazyFrame  # noqa: F401 - registers namespace

ONE_DAY = 1.0 / 365.0


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestEffectiveMaturityOverride:
    """Priority-1: numeric override wins over all other rules."""

    def test_override_wins_over_date_derived(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2035, 6, 30)],  # 5y from reporting
                "effective_maturity": [0.25],  # firm-asserted M = 3 months
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(0.25, abs=1e-9)

    def test_override_wins_over_one_day_floor_flag(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],
                "has_one_day_maturity_floor": [True],
                "effective_maturity": [0.5],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        # Override > flag: M = 0.5 wins over M = 1/365
        assert result["maturity"][0] == pytest.approx(0.5, abs=1e-9)

    def test_override_out_of_range_is_clipped_to_five(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],
                "effective_maturity": [12.0],  # bogus — above 5y cap
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(5.0, abs=1e-9)

    def test_override_below_one_day_is_clipped_up(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],
                "effective_maturity": [0.0001],  # below 1 day
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(ONE_DAY, abs=1e-9)

    def test_null_override_falls_back_to_date_derivation(
        self, b31_config: CalculationConfig
    ) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2033, 6, 30)],  # 3y
                "effective_maturity": [None],
                "exposure_class": ["CORPORATE"],
            }
        ).cast({"effective_maturity": pl.Float64})

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(3.0, abs=0.05)

    def test_override_wins_over_firb_sft_supervisory(self, crr_config: CalculationConfig) -> None:
        """CRR F-IRB SFT supervisory 0.5y should be overridden by explicit input."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2026, 6, 30)],
                "is_sft": [True],
                "effective_maturity": [0.1],
                "approach": ["FIRB"],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(crr_config).collect()

        assert result["maturity"][0] == pytest.approx(0.1, abs=1e-9)


class TestOneDayMaturityFloorFlag:
    """Priority-2: has_one_day_maturity_floor sets M = 1/365 (Art. 162(3))."""

    def test_flag_wins_over_date_derived(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2035, 6, 30)],  # 5y from reporting
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(ONE_DAY, abs=1e-9)

    def test_flag_false_leaves_date_derivation(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2033, 6, 30)],  # 3y
                "has_one_day_maturity_floor": [False],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(3.0, abs=0.05)

    def test_flag_null_treated_as_false(self, b31_config: CalculationConfig) -> None:
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2033, 6, 30)],
                "has_one_day_maturity_floor": [None],
                "exposure_class": ["CORPORATE"],
            }
        ).cast({"has_one_day_maturity_floor": pl.Boolean})

        result = lf.irb.prepare_columns(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(3.0, abs=0.05)


class TestSchemaAndPropagation:
    """Schema-level assertions — the column is declared on inputs and propagates."""

    def test_effective_maturity_on_all_input_schemas(self) -> None:
        from rwa_calc.data.schemas import (
            CONTINGENTS_SCHEMA,
            FACILITY_SCHEMA,
            LOAN_SCHEMA,
        )

        for schema in (FACILITY_SCHEMA, LOAN_SCHEMA, CONTINGENTS_SCHEMA):
            assert "effective_maturity" in schema
            spec = schema["effective_maturity"]
            assert spec.dtype == pl.Float64
            assert spec.required is False

    def test_effective_maturity_on_exposures_frame_schema(self) -> None:
        """The column is declared in the internal exposures frame schema."""

        source = HierarchyResolver._unify_exposures.__code__.co_consts
        # Flatten nested code constants looking for the string literal
        found = any(
            isinstance(c, str) and c == "effective_maturity"
            for const in source
            for c in (const if isinstance(const, tuple) else (const,))
        )
        assert found, "effective_maturity must be referenced inside _unify_exposures"


class TestValidation:
    """validate_bundle_values flags out-of-range overrides without blocking the pipeline."""

    def test_out_of_range_emits_warning(self) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["L1", "L2"],
                "counterparty_reference": ["C1", "C1"],
                "drawn_amount": [100.0, 100.0],
                "effective_maturity": [0.25, 12.0],  # second row out of range
            }
        )
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(),
            counterparties=pl.LazyFrame(
                {"counterparty_reference": ["C1"], "entity_type": ["corporate"]}
            ),
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        errors = validate_bundle_values(bundle)

        maturity_errors = [e for e in errors if e.field_name == "effective_maturity"]
        assert len(maturity_errors) == 1
        assert maturity_errors[0].code == "IRB003"

    def test_in_range_no_error(self) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["L1"],
                "counterparty_reference": ["C1"],
                "drawn_amount": [100.0],
                "effective_maturity": [0.25],
            }
        )
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=loans,
            contingents=pl.LazyFrame(),
            counterparties=pl.LazyFrame(
                {"counterparty_reference": ["C1"], "entity_type": ["corporate"]}
            ),
            facility_mappings=pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            ),
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )

        errors = validate_bundle_values(bundle)

        assert not [e for e in errors if e.field_name == "effective_maturity"]
