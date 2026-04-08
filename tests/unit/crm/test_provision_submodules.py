"""
Direct unit tests for CRM provision sub-functions.

Tests resolve_provisions function internals: multi-level allocation (direct,
facility, counterparty), SA drawn-first deduction, IRB pass-through, and edge
cases. Complements integration-level tests in test_provisions.py (15 tests)
with focused sub-function coverage.

Why these tests matter:
- Multi-level provision allocation (direct + facility + counterparty) uses
  pro-rata weights. Off-by-one errors or zero-division bugs silently produce
  wrong provision allocations, affecting EAD and capital.
- SA drawn-first deduction is order-sensitive: provision reduces drawn first,
  remainder spills to nominal. Incorrect ordering changes CCF application.
- IRB exposures track provision_allocated for EL shortfall/excess but must NOT
  deduct from EAD. A deduction bug directly overstates IRB capital.

References:
    CRR Art. 110: Specific provisions reduce exposure value
    CRR Art. 111(2): SCRAs deducted from nominal before CCF
    CRR Art. 158-159: IRB EL shortfall/excess uses provision_allocated
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.provisions import resolve_provisions


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _make_exposures(**overrides) -> pl.LazyFrame:
    """Build exposure frame with sensible defaults."""
    defaults = {
        "exposure_reference": "EXP001",
        "counterparty_reference": "CP001",
        "parent_facility_reference": "FAC001",
        "drawn_amount": 500_000.0,
        "interest": 5_000.0,
        "nominal_amount": 500_000.0,
        "approach": ApproachType.SA.value,
    }
    defaults.update(overrides)
    if isinstance(defaults["exposure_reference"], list):
        return pl.LazyFrame(defaults)
    return pl.LazyFrame({k: [v] for k, v in defaults.items()})


def _make_provisions(rows: list[dict]) -> pl.LazyFrame:
    return pl.LazyFrame(rows)


# =============================================================================
# Direct provision — sub-function level
# =============================================================================


class TestDirectProvisionAllocation:
    """Direct-level provisions (beneficiary_type in loan/exposure/contingent)."""

    def test_direct_provision_allocated_by_reference(self, crr_config: CalculationConfig) -> None:
        """Direct provision matched to exposure_reference."""
        exposures = _make_exposures()
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 50_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)

    def test_exposure_type_beneficiary_matches(self, crr_config: CalculationConfig) -> None:
        """beneficiary_type='exposure' also matches as direct."""
        exposures = _make_exposures()
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "exposure",
                    "amount": 30_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(30_000.0)

    def test_contingent_type_beneficiary_matches(self, crr_config: CalculationConfig) -> None:
        """beneficiary_type='contingent' also matches as direct."""
        exposures = _make_exposures()
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "contingent",
                    "amount": 20_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(20_000.0)

    def test_case_insensitive_beneficiary_type(self, crr_config: CalculationConfig) -> None:
        """beneficiary_type matching is case-insensitive."""
        exposures = _make_exposures()
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "LOAN",
                    "amount": 25_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(25_000.0)


# =============================================================================
# Multi-level provision allocation
# =============================================================================


class TestMultiLevelProvisionAllocation:
    """Direct + facility + counterparty levels combine additively."""

    def test_three_levels_sum_to_total(self, crr_config: CalculationConfig) -> None:
        """Direct + facility + counterparty provisions sum."""
        exposures = _make_exposures(
            drawn_amount=1_000_000.0,
            interest=0.0,
            nominal_amount=0.0,
        )
        provisions = _make_provisions(
            [
                {"beneficiary_reference": "EXP001", "beneficiary_type": "loan", "amount": 10_000.0},
                {
                    "beneficiary_reference": "FAC001",
                    "beneficiary_type": "facility",
                    "amount": 20_000.0,
                },
                {
                    "beneficiary_reference": "CP001",
                    "beneficiary_type": "counterparty",
                    "amount": 30_000.0,
                },
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        # Single exposure gets all levels: 10k + 20k + 30k = 60k
        assert result["provision_allocated"][0] == pytest.approx(60_000.0)

    def test_facility_pro_rata_across_children(self, crr_config: CalculationConfig) -> None:
        """Facility-level provision split pro-rata by weight across exposures."""
        exposures = _make_exposures(
            exposure_reference=["EXP_A", "EXP_B"],
            counterparty_reference=["CP001", "CP001"],
            parent_facility_reference=["FAC001", "FAC001"],
            drawn_amount=[600_000.0, 400_000.0],
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.SA.value],
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "FAC001",
                    "beneficiary_type": "facility",
                    "amount": 100_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")

        assert exp_a["provision_allocated"][0] == pytest.approx(60_000.0)
        assert exp_b["provision_allocated"][0] == pytest.approx(40_000.0)

    def test_counterparty_pro_rata_across_exposures(self, crr_config: CalculationConfig) -> None:
        """Counterparty-level provision split pro-rata."""
        exposures = _make_exposures(
            exposure_reference=["EXP_A", "EXP_B"],
            counterparty_reference=["CP001", "CP001"],
            parent_facility_reference=["FAC_A", "FAC_B"],
            drawn_amount=[750_000.0, 250_000.0],
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.SA.value],
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "CP001",
                    "beneficiary_type": "counterparty",
                    "amount": 80_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")

        assert exp_a["provision_allocated"][0] == pytest.approx(60_000.0)
        assert exp_b["provision_allocated"][0] == pytest.approx(20_000.0)

    def test_zero_weight_exposures_get_zero_allocation(self, crr_config: CalculationConfig) -> None:
        """Exposures with zero weight (drawn=0, interest=0, nominal=0) get zero."""
        exposures = _make_exposures(
            exposure_reference=["EXP_A", "EXP_B"],
            counterparty_reference=["CP001", "CP001"],
            parent_facility_reference=["FAC001", "FAC001"],
            drawn_amount=[0.0, 0.0],
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.SA.value],
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "CP001",
                    "beneficiary_type": "counterparty",
                    "amount": 100_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        # Total weight is 0 → all get 0 allocation
        assert result["provision_allocated"][0] == pytest.approx(0.0)
        assert result["provision_allocated"][1] == pytest.approx(0.0)


# =============================================================================
# SA drawn-first deduction
# =============================================================================


class TestSADrawnFirstDeduction:
    """SA provision deduction: drawn first, remainder to nominal."""

    def test_provision_fully_absorbed_by_drawn(self, crr_config: CalculationConfig) -> None:
        """Provision < drawn: fully absorbed, nominal untouched."""
        exposures = _make_exposures(drawn_amount=500_000.0, nominal_amount=200_000.0)
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 100_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_on_drawn"][0] == pytest.approx(100_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(0.0)
        assert result["nominal_after_provision"][0] == pytest.approx(200_000.0)

    def test_provision_spills_to_nominal(self, crr_config: CalculationConfig) -> None:
        """Provision > drawn: excess goes to nominal."""
        exposures = _make_exposures(drawn_amount=30_000.0, nominal_amount=200_000.0)
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 80_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_on_drawn"][0] == pytest.approx(30_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(50_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(150_000.0)

    def test_provision_capped_at_drawn_plus_nominal(self, crr_config: CalculationConfig) -> None:
        """Provision > drawn + nominal: capped at total."""
        exposures = _make_exposures(drawn_amount=50_000.0, nominal_amount=50_000.0)
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 200_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_on_drawn"][0] == pytest.approx(50_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(100_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(0.0)


# =============================================================================
# IRB provision handling
# =============================================================================


class TestIRBProvisionTracking:
    """IRB: provision_allocated tracked, provision_deducted = 0."""

    def test_firb_provision_not_deducted(self, crr_config: CalculationConfig) -> None:
        """F-IRB: provision tracked but not deducted from EAD."""
        exposures = _make_exposures(
            approach=ApproachType.FIRB.value,
            drawn_amount=1_000_000.0,
            nominal_amount=0.0,
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 50_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(0.0)
        assert result["provision_on_drawn"][0] == pytest.approx(0.0)
        assert result["provision_on_nominal"][0] == pytest.approx(0.0)

    def test_airb_provision_not_deducted(self, crr_config: CalculationConfig) -> None:
        """A-IRB: same tracking behavior as F-IRB."""
        exposures = _make_exposures(
            approach=ApproachType.AIRB.value,
            drawn_amount=1_000_000.0,
            nominal_amount=500_000.0,
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "beneficiary_type": "loan",
                    "amount": 100_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(100_000.0)
        assert result["provision_deducted"][0] == pytest.approx(0.0)


# =============================================================================
# Backward compatibility (no beneficiary_type)
# =============================================================================


class TestNoBeneficiaryTypeFallback:
    """Provisions without beneficiary_type column use direct-only join."""

    def test_direct_join_without_beneficiary_type(self, crr_config: CalculationConfig) -> None:
        """No beneficiary_type column: falls back to direct join."""
        exposures = _make_exposures(drawn_amount=1_000_000.0, nominal_amount=0.0)
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "EXP001",
                    "amount": 50_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)

    def test_facility_ref_ignored_without_beneficiary_type(
        self, crr_config: CalculationConfig
    ) -> None:
        """Without beneficiary_type, facility references are treated as direct."""
        exposures = _make_exposures(drawn_amount=1_000_000.0, nominal_amount=0.0)
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "FAC001",  # matches parent_facility_reference
                    "amount": 50_000.0,
                }
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        # No beneficiary_type → direct join on exposure_reference = FAC001 → no match
        assert result["provision_allocated"][0] == pytest.approx(0.0)


# =============================================================================
# No parent_facility_reference
# =============================================================================


class TestNoParentFacilityReference:
    """Facility-level allocation skipped when column absent."""

    def test_facility_provisions_skipped(self, crr_config: CalculationConfig) -> None:
        """Facility provisions ignored when exposures lack parent_facility_reference."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "drawn_amount": [500_000.0],
                "interest": [0.0],
                "nominal_amount": [200_000.0],
                "approach": [ApproachType.SA.value],
            }
        )
        provisions = _make_provisions(
            [
                {
                    "beneficiary_reference": "FAC001",
                    "beneficiary_type": "facility",
                    "amount": 50_000.0,
                },
                {
                    "beneficiary_reference": "CP001",
                    "beneficiary_type": "counterparty",
                    "amount": 30_000.0,
                },
            ]
        )
        result = resolve_provisions(exposures, provisions, crr_config).collect()

        # Facility provision skipped, counterparty provision applied
        assert result["provision_allocated"][0] == pytest.approx(30_000.0)
