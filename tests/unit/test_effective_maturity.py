"""Unit tests for the effective_maturity override and has_one_day_maturity_floor.

Covers the priority chain in `lf.pipe(prepare_columns, config)`:
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
from typing import TYPE_CHECKING

import polars as pl
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.engine.irb.transforms import (
    prepare_columns,
)
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad
from tests.fixtures.raw_bundle import make_raw_bundle

ONE_DAY = 1.0 / 365.0


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def bundle_with_loans() -> Callable[[pl.LazyFrame], RawDataBundle]:
    def _make(loans: pl.LazyFrame) -> RawDataBundle:
        return make_raw_bundle(
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

    return _make


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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(0.1, abs=1e-9)


class TestOneDayMaturityFloorFlag:
    """Priority-2: has_one_day_maturity_floor replaces the 1-year M minimum with one day.

    CRR Art. 162(3) "M shall be at least one-day"; PS1/26 Art. 162(3) "M shall be
    at least one day, instead of the minimum set in paragraph 2A". A MINIMUM, not
    a value: until review TR-11 the flag SET M to 1/365 whatever the residual
    (``test_flag_wins_over_date_derived`` pinned a 5-year loan at one day).
    """

    @staticmethod
    def _flagged(maturity_date: date) -> pl.LazyFrame:
        return pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [maturity_date],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

    def test_flag_lets_a_sub_one_year_residual_through(self, b31_config: CalculationConfig) -> None:
        # Arrange — 2030-06-30 -> 2030-12-31: (365 - 181) / 365 = 0.504110y
        lf = self._flagged(date(2030, 12, 31))

        # Act
        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

        # Assert
        assert result["maturity"][0] == pytest.approx(184 / 365, abs=1e-12)

    def test_flag_floors_the_residual_at_one_day(self, b31_config: CalculationConfig) -> None:
        # Arrange — maturing on the reporting date: residual 0 -> floored at one day
        lf = self._flagged(date(2030, 6, 30))

        # Act
        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

        # Assert
        assert result["maturity"][0] == pytest.approx(ONE_DAY, abs=1e-12)

    def test_flag_does_not_shorten_a_long_residual(self, b31_config: CalculationConfig) -> None:
        # Arrange — 5y from reporting: the one-day minimum cannot bind
        lf = self._flagged(date(2035, 6, 30))

        # Act
        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

        # Assert
        assert result["maturity"][0] == pytest.approx(5.0, abs=0.01)

    def test_flag_without_a_maturity_date_keeps_the_default(
        self, b31_config: CalculationConfig
    ) -> None:
        # Arrange — residual unknown: the conservative date-free default stands
        # (pre-TR-11 the flag forced M to one day with no date at all)
        lf = self._flagged(date(2035, 6, 30)).with_columns(
            pl.lit(None, dtype=pl.Date).alias("maturity_date")
        )

        # Act
        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

        # Assert
        assert result["maturity"][0] == pytest.approx(2.5, abs=1e-12)

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

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
        from rwa_calc.engine.hierarchy.unify import unify_exposures

        source = unify_exposures.__code__.co_consts
        # Flatten nested code constants looking for the string literal
        found = any(
            isinstance(c, str) and c == "effective_maturity"
            for const in source
            for c in (const if isinstance(const, tuple) else (const,))
        )
        assert found, "effective_maturity must be referenced inside _unify_exposures"


class TestValidation:
    """validate_bundle_values flags out-of-range overrides without blocking the pipeline."""

    def test_out_of_range_emits_warning(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["L1", "L2"],
                "counterparty_reference": ["C1", "C1"],
                "drawn_amount": [100.0, 100.0],
                "effective_maturity": [0.25, 12.0],  # second row out of range
            }
        )
        bundle = bundle_with_loans(loans)

        errors = validate_bundle_values(bundle)

        maturity_errors = [e for e in errors if e.field_name == "effective_maturity"]
        assert len(maturity_errors) == 1
        assert maturity_errors[0].code == "IRB003"

    def test_in_range_no_error(
        self, bundle_with_loans: Callable[[pl.LazyFrame], RawDataBundle]
    ) -> None:
        loans = pl.LazyFrame(
            {
                "loan_reference": ["L1"],
                "counterparty_reference": ["C1"],
                "drawn_amount": [100.0],
                "effective_maturity": [0.25],
            }
        )
        bundle = bundle_with_loans(loans)

        errors = validate_bundle_values(bundle)

        assert not [e for e in errors if e.field_name == "effective_maturity"]
