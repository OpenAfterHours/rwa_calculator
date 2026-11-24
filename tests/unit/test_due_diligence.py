"""Unit tests for the Basel 3.1 due-diligence override and the SA004 census.

Tests cover:
- Override applied when due_diligence_override_rw > calculated risk_weight
- Override ignored when due_diligence_override_rw <= calculated risk_weight
- Override ignored when due_diligence_override_rw is null
- No-op when override column is absent from data
- No-op under CRR (Art. 110A is Basel 3.1 only)
- Audit column due_diligence_override_applied set correctly
- Override only increases risk weight (max behavior)
- SA004 census (P1.368): reads the attestation VALUE, counts only SA-branch rows
  outside the Art. 110A(5) exemptions, never counts a null (no attestation
  field), and is silent under CRR

These are unit legs on hand-built frames, which bypass unify and every edge. The
proof that the inputs reach the calculator at all is end to end:
``tests/acceptance/test_p1_368_due_diligence_override.py``.

References:
- PRA PS1/26 Art. 110A(2), (5): due-diligence obligation and its exemptions
- PRA PS1/26 Art. 120(4), 122(4), 129(4A): the one-step-higher risk weight
- P1.49: Art. 110A due diligence obligation implementation
- P1.368: the attestation and override reach the SA branch; SA004 reads the value
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.sa.rw_adjustments import apply_due_diligence_override

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _exposures_with_dd(
    *,
    risk_weights: list[float],
    override_rws: list[float | None] | None = None,
    dd_performed: list[bool | None] | None = None,
) -> pl.LazyFrame:
    """Create minimal SA exposures with due diligence columns."""
    n = len(risk_weights)
    data: dict[str, list[Any]] = {
        "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
        "risk_weight": risk_weights,
    }
    if override_rws is not None:
        data["due_diligence_override_rw"] = override_rws
    if dd_performed is not None:
        data["due_diligence_performed"] = dd_performed
    return pl.DataFrame(data).lazy()


def _exposures_without_dd(
    *,
    risk_weights: list[float],
) -> pl.LazyFrame:
    """Create minimal SA exposures without any due diligence columns."""
    n = len(risk_weights)
    return pl.DataFrame(
        {
            "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
            "risk_weight": risk_weights,
        }
    ).lazy()


# =============================================================================
# Override Application Tests
# =============================================================================


class TestDueDiligenceOverrideApplication:
    """Tests for the risk weight override mechanism."""

    def test_override_applied_when_higher(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW replaces calculated RW when it is higher."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_override_ignored_when_lower(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW is ignored when it is lower than calculated RW."""
        exposures = _exposures_with_dd(
            risk_weights=[1.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(1.50)

    def test_override_ignored_when_equal(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW is ignored when it equals calculated RW."""
        exposures = _exposures_with_dd(
            risk_weights=[0.75],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_null_override_ignored(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Null override values are silently ignored."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[None],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)

    def test_mixed_overrides(self, calculator: SACalculator, b31_config: CalculationConfig) -> None:
        """Mixed override values: some applied, some ignored, some null."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50, 1.50, 0.75, 1.00],
            override_rws=[0.75, 0.50, None, 2.50],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)  # override applied
        assert df["risk_weight"][1] == pytest.approx(1.50)  # override lower, ignored
        assert df["risk_weight"][2] == pytest.approx(0.75)  # null override, ignored
        assert df["risk_weight"][3] == pytest.approx(2.50)  # override applied

    def test_no_op_when_override_column_absent(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """No-op when due_diligence_override_rw column is not in the data."""
        exposures = _exposures_without_dd(risk_weights=[0.50, 1.00])
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)
        assert df["risk_weight"][1] == pytest.approx(1.00)

    def test_no_op_under_crr(self, calculator: SACalculator, crr_config: CalculationConfig) -> None:
        """No-op under CRR — Art. 110A is Basel 3.1 only."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, crr_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)
        assert "due_diligence_override_applied" not in df.columns


# =============================================================================
# Audit Column Tests
# =============================================================================


class TestDueDiligenceAuditColumn:
    """Tests for the due_diligence_override_applied audit flag."""

    def test_audit_flag_true_when_override_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is True when override was applied."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is True

    def test_audit_flag_false_when_override_not_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is False when override was not applied (lower RW)."""
        exposures = _exposures_with_dd(
            risk_weights=[1.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is False

    def test_audit_flag_false_for_null_override(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is False when override value is null."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[None],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is False

    def test_audit_flag_absent_under_crr(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Audit column is not added under CRR."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = apply_due_diligence_override(exposures, crr_config)
        df = result.collect()
        assert "due_diligence_override_applied" not in df.columns

    def test_audit_flag_false_when_column_missing(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """An absent override column reads as "no override": flag False, RW unchanged.

        The hierarchy edge always carries the column in production; only a
        hand-built frame can lack it, and it is then injected as a typed null.
        """
        exposures = _exposures_without_dd(risk_weights=[0.50])
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is False
        assert df["risk_weight"][0] == pytest.approx(0.50)


# =============================================================================
# SA004 census tests
# =============================================================================


def _census_frame(
    *,
    performed: list[bool | None],
    exposure_class: str = "corporate",
    approach: str = "standardised",
    cp_entity_type: str = "corporate",
) -> pl.LazyFrame:
    """SA calculator input rows carrying the carriers the SA004 census reads."""
    n = len(performed)
    return pl.DataFrame(
        {
            "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
            "counterparty_reference": ["CP_001"] * n,
            "exposure_class": [exposure_class] * n,
            "approach": [approach] * n,
            "cp_entity_type": [cp_entity_type] * n,
            "ead_final": [500_000.0] * n,
            "ead_gross": [500_000.0] * n,
            "cqs": [3] * n,
            "currency": ["GBP"] * n,
            "due_diligence_performed": performed,
        },
        schema_overrides={"due_diligence_performed": pl.Boolean},
    ).lazy()


def _sa004(
    calculator: SACalculator, frame: pl.LazyFrame, config: CalculationConfig
) -> list[CalculationError]:
    """Run the unified (output-floor) path and return its SA004 warnings."""
    errors: list[CalculationError] = []
    calculator.calculate_unified(frame, config, errors=errors)
    return [e for e in errors if e.code == ERROR_DUE_DILIGENCE_NOT_PERFORMED]


class TestDueDiligenceWarnings:
    """SA004 reads the attestation value, scoped to the rows Art. 110A covers."""

    def test_warning_when_sa_row_unattested_b31(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """An in-scope SA row with due_diligence_performed = False warns once."""
        warnings = _sa004(calculator, _census_frame(performed=[False]), b31_config)
        assert len(warnings) == 1
        assert warnings[0].actual_value == "False on 1 exposure row(s)"

    def test_no_warning_when_sa_row_attested_b31(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """The same row attested True is silent — the alarm discriminates (B9)."""
        assert _sa004(calculator, _census_frame(performed=[True]), b31_config) == []

    def test_null_attestation_is_not_counted(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """A null means "no attestation field" (facility-undrawn, SA-CCR, SFT rows)."""
        assert _sa004(calculator, _census_frame(performed=[None]), b31_config) == []

    def test_absent_attestation_column_is_not_counted(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """A hand-built frame without the column reads as all-null: nothing counted."""
        frame = _census_frame(performed=[False]).drop("due_diligence_performed")
        assert _sa004(calculator, frame, b31_config) == []

    @pytest.mark.parametrize(
        ("exposure_class", "cp_entity_type"),
        [
            ("central_govt_central_bank", "sovereign"),  # Art. 112(1)(a)
            ("rgla", "rgla_institution"),  # Art. 112(1)(b)
            ("pse", "pse_institution"),  # Art. 112(1)(c)
            ("mdb", "mdb_named"),  # Art. 117(2)
            ("international_organisation", "international_org"),  # Art. 118(1)
        ],
    )
    def test_art_110a_5_exemptions_are_not_counted(
        self,
        calculator: SACalculator,
        b31_config: CalculationConfig,
        exposure_class: str,
        cp_entity_type: str,
    ) -> None:
        """PS1/26 Art. 110A(5): the obligation does not apply, so no warning."""
        frame = _census_frame(
            performed=[False], exposure_class=exposure_class, cp_entity_type=cp_entity_type
        )
        assert _sa004(calculator, frame, b31_config) == []

    def test_mdb_outside_art_117_2_is_counted(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Only the Art. 117(2) named MDBs are exempt; another MDB is in scope."""
        frame = _census_frame(performed=[False], exposure_class="mdb", cp_entity_type="mdb")
        assert len(_sa004(calculator, frame, b31_config)) == 1

    @pytest.mark.parametrize("approach", ["foundation_irb", "advanced_irb", "slotting"])
    def test_irb_and_slotting_rows_are_not_counted(
        self, calculator: SACalculator, b31_config: CalculationConfig, approach: str
    ) -> None:
        """calculate_unified weights IRB rows for the output floor, but Art. 110A(1)
        applies to the Standardised Approach: only SA-branch rows are counted."""
        frame = _census_frame(performed=[False], approach=approach)
        assert _sa004(calculator, frame, b31_config) == []

    def test_equity_approach_rows_are_counted(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """An equity-class loan / contingent row is routed with ``approach='equity'``
        and weighted on the SA branch (``is_sa_branch_approach``), so it is in scope.
        A census keyed on the ``standardised`` label alone would miss it (P1.317)."""
        # Arrange
        frame = _census_frame(performed=[False], exposure_class="equity", approach="equity")

        # Act
        warnings = _sa004(calculator, frame, b31_config)

        # Assert
        assert len(warnings) == 1, [w.message for w in warnings]
        assert warnings[0].actual_value == "False on 1 exposure row(s)"

    def test_warning_counts_rows_once_not_per_row(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """One warning per run, carrying the count of in-scope unattested rows."""
        warnings = _sa004(calculator, _census_frame(performed=[False, True, False]), b31_config)
        assert len(warnings) == 1
        assert warnings[0].actual_value == "False on 2 exposure row(s)"
        assert warnings[0].message.startswith("2 Standardised Approach exposure row(s)")

    def test_warning_metadata(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """WARNING severity, DATA_QUALITY category, Art. 110A, the attestation field."""
        (warning,) = _sa004(calculator, _census_frame(performed=[False]), b31_config)
        assert warning.severity == ErrorSeverity.WARNING
        assert warning.category == ErrorCategory.DATA_QUALITY
        assert "110A" in (warning.regulatory_reference or "")
        assert warning.field_name == "due_diligence_performed"

    def test_no_warning_under_crr(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR has no Art. 110A: an unattested SA row raises nothing."""
        errors: list[CalculationError] = []
        calculator.calculate_branch(_census_frame(performed=[False]), crr_config, errors=errors)
        assert ERROR_DUE_DILIGENCE_NOT_PERFORMED not in [e.code for e in errors]

    def test_override_without_errors_kwarg_still_applies(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """The override itself takes no error channel and needs none."""
        exposures = _exposures_with_dd(risk_weights=[0.50], override_rws=[0.75])
        df = apply_due_diligence_override(exposures, b31_config).collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)


# =============================================================================
# Edge Cases
# =============================================================================


class TestDueDiligenceEdgeCases:
    """Edge cases for due diligence override."""

    def test_zero_override_ignored(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Zero override RW is lower than any valid RW and is ignored."""
        exposures = _exposures_with_dd(
            risk_weights=[0.20],
            override_rws=[0.0],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.20)

    def test_very_high_override_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Very high override RW (e.g. 12.5 = 1250%) is correctly applied."""
        exposures = _exposures_with_dd(
            risk_weights=[1.00],
            override_rws=[12.5],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(12.5)

    def test_override_with_dd_performed_false(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override applied even when due_diligence_performed is False.

        The override_rw is independent of the performed flag. If a firm provides
        an override value, it is applied regardless of the DD assessment status.
        """
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
            dd_performed=[False],
        )
        result = apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_override_preserves_other_columns(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override does not drop or alter other columns."""
        lf = pl.DataFrame(
            {
                "exposure_reference": ["EXP_001"],
                "risk_weight": [0.50],
                "due_diligence_override_rw": [0.75],
                "exposure_class": ["corporate"],
                "ead_final": [100_000.0],
            }
        ).lazy()
        result = apply_due_diligence_override(lf, b31_config)
        df = result.collect()
        assert df["exposure_class"][0] == "corporate"
        assert df["ead_final"][0] == pytest.approx(100_000.0)
        assert df["risk_weight"][0] == pytest.approx(0.75)
