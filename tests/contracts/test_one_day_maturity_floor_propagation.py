"""Contract tests for ``has_one_day_maturity_floor`` end-to-end propagation.

The flag gates the CRR Art. 162(3) carve-out from the IRB 1-year M floor in
the maturity-adjustment formula (daily-margined SFTs/derivatives, margin
lending, short-term self-liquidating trade transactions). It must survive
intact from each input table through hierarchy resolution and into the IRB
stage's ``prepare_columns`` output, otherwise the formula will silently fall
back to the default 1-year floor and zero-out the regulatory relief.

References:
- CRR Art. 162(3); BCBS CRE32.50
- ``src/rwa_calc/engine/irb/formulas.py::_maturity_adjustment_expr_from_pd``
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
)
from rwa_calc.engine.irb import IRBExpr, IRBLazyFrame  # noqa: F401 - registers namespace


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestSchemaDeclarations:
    """The flag must be declared on every input table that feeds IRB."""

    @pytest.mark.parametrize(
        "schema",
        [FACILITY_SCHEMA, LOAN_SCHEMA, CONTINGENTS_SCHEMA],
    )
    def test_flag_declared_on_input_schemas(self, schema: dict) -> None:
        assert "has_one_day_maturity_floor" in schema
        spec = schema["has_one_day_maturity_floor"]
        assert spec.dtype == pl.Boolean
        assert spec.required is False


class TestIRBPrepareColumnsPropagation:
    """``prepare_columns`` either preserves the input flag or default-adds False."""

    def test_flag_preserved_when_present(self, b31_config: CalculationConfig) -> None:
        """A True flag on an input row survives unchanged into prepare_columns output."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = _pad(lf).irb.prepare_columns(b31_config).collect()

        assert "has_one_day_maturity_floor" in result.columns
        assert result["has_one_day_maturity_floor"][0] is True

    def test_flag_defaulted_to_false_when_absent(self, b31_config: CalculationConfig) -> None:
        """A null/contract-default flag normalises to False so downstream
        formulas can read it safely (the crm_exit edge guarantees the
        column is present on the sealed branch input)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = _pad(lf).irb.prepare_columns(b31_config).collect()

        assert "has_one_day_maturity_floor" in result.columns
        assert result["has_one_day_maturity_floor"][0] is False


class TestMaturityAdjustmentEndToEnd:
    """The flag actually changes the formula output downstream."""

    def test_carve_out_produces_ma_below_one(self, b31_config: CalculationConfig) -> None:
        """A non-retail row with the flag set and effective_maturity=0.1 must
        produce maturity_adjustment < 1.0 — the regulatory relief that
        ``has_one_day_maturity_floor`` is supposed to deliver."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "effective_maturity": [0.1],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = _pad(lf).irb.prepare_columns(b31_config).irb.apply_all_formulas(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(0.1, abs=1e-9)
        assert result["maturity_adjustment"][0] < 1.0

    def test_no_carve_out_clamps_ma_to_one(self, b31_config: CalculationConfig) -> None:
        """Without the flag, a sub-1y effective_maturity must still produce
        maturity_adjustment = 1.0 (1y floor preserved for non-carve-out rows)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "effective_maturity": [0.1],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = _pad(lf).irb.prepare_columns(b31_config).irb.apply_all_formulas(b31_config).collect()

        assert result["maturity"][0] == pytest.approx(0.1, abs=1e-9)
        assert result["maturity_adjustment"][0] == pytest.approx(1.0, abs=1e-9)

    def test_carve_out_under_crr_produces_ma_below_one(self, crr_config: CalculationConfig) -> None:
        """The carve-out works identically under CRR (Art. 162(3) is in both
        the CRR onshored framework and the PRA PS1/26 Basel 3.1 framework)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "effective_maturity": [0.1],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = (
            _pad(lf)
            .irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .irb.apply_all_formulas(crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(0.1, abs=1e-9)
        assert result["maturity_adjustment"][0] < 1.0
        # CRR keeps the 1.06 scaling factor regardless of the carve-out
        assert result["scaling_factor"][0] == pytest.approx(1.06, abs=1e-9)

    def test_rwa_relief_is_significant(self, b31_config: CalculationConfig) -> None:
        """End-to-end smoke for the user-reported regression: a 1y M corporate
        produces RWA = X; with the carve-out and M=0.1 RWA falls by ~20%
        (the magnitude scales with PD via the b coefficient — typical relief
        is 15-25% across the realistic PD range for non-defaulted exposures)."""
        base_lf = pl.LazyFrame(
            {
                "pd": [0.005],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "effective_maturity": [1.0],  # at 1y floor — MA = 1.0
                "has_one_day_maturity_floor": [False],
                "exposure_class": ["CORPORATE"],
            }
        )
        carve_out_lf = pl.LazyFrame(
            {
                "pd": [0.005],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "effective_maturity": [0.1],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        base_result = (
            _pad(base_lf)
            .irb.prepare_columns(b31_config)
            .irb.apply_all_formulas(b31_config)
            .collect()
        )
        carve_out_result = (
            _pad(carve_out_lf)
            .irb.prepare_columns(b31_config)
            .irb.apply_all_formulas(b31_config)
            .collect()
        )

        # Relief is at least 10% (typically 15-25% depending on PD)
        assert carve_out_result["rwa"][0] < 0.9 * base_result["rwa"][0]
        # Relief is bounded — MA cannot go negative or exceed reasonable bounds
        assert carve_out_result["rwa"][0] > 0.5 * base_result["rwa"][0]
