"""Unit tests for provision resolution in CRM processor.

Tests cover:
- Direct-level provision (loan → exposure_reference match)
- Facility-level pro-rata allocation across child exposures
- Counterparty-level pro-rata allocation
- Drawn-first deduction (on-balance only loan: provision fully absorbed by drawn)
- OBS-only deduction (contingent with drawn=0)
- Mixed drawn+undrawn where provision spills from drawn to nominal
- Provision exceeding total exposure (capped)
- Negative drawn amount handling
- IRB provisions: provision_deducted=0 but provision_allocated tracked
- SA-only deduction: mixed SA/IRB exposures
- No beneficiary_type column fallback (backward compat)

References:
- CRR Art. 110: Specific provisions reduce exposure value
- CRR Art. 111(2): SCRAs deducted from nominal *before* CCF
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.processor import CRMProcessor


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration with SA-only permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture
def irb_config() -> CalculationConfig:
    """Return a CRR configuration with full IRB permissions."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture
def processor() -> CRMProcessor:
    """Return a CRM processor instance."""
    return CRMProcessor()


def _make_exposures(**overrides) -> pl.LazyFrame:
    """Helper to create a single-row exposure LazyFrame with sensible defaults."""
    defaults = {
        "exposure_reference": "EXP001",
        "counterparty_reference": "CP001",
        "parent_facility_reference": "FAC001",
        "drawn_amount": 500_000.0,
        "interest": 5_000.0,
        "nominal_amount": 500_000.0,
        "approach": ApproachType.SA.value,
        "risk_type": "MR",
        "exposure_class": "corporate",
        "lgd": 0.45,
        "seniority": "senior",
    }
    defaults.update(overrides)

    # Support lists for multi-row
    if isinstance(defaults["exposure_reference"], list):
        return pl.LazyFrame(defaults)
    return pl.LazyFrame({k: [v] for k, v in defaults.items()})


def _make_provisions(rows: list[dict]) -> pl.LazyFrame:
    """Helper to create provisions LazyFrame."""
    return pl.LazyFrame(rows)


# =============================================================================
# Direct-level provision tests
# =============================================================================


class TestDirectLevelProvision:
    """Provisions that reference an exposure directly (beneficiary_type=loan)."""

    def test_direct_provision_allocates_to_matching_exposure(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Direct provision should match on exposure_reference."""
        exposures = _make_exposures(
            drawn_amount=1_000_000.0, interest=0.0, nominal_amount=0.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(50_000.0)

    def test_direct_provision_drawn_first_deduction(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Provision should reduce drawn first before touching nominal."""
        exposures = _make_exposures(
            drawn_amount=800_000.0, interest=10_000.0, nominal_amount=200_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        # 50k fully absorbed by drawn (800k available)
        assert result["provision_on_drawn"][0] == pytest.approx(50_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(0.0)
        assert result["nominal_after_provision"][0] == pytest.approx(200_000.0)

    def test_provision_spills_from_drawn_to_nominal(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """When provision exceeds drawn, remainder reduces nominal."""
        exposures = _make_exposures(
            drawn_amount=30_000.0, interest=5_000.0, nominal_amount=200_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        # 30k absorbed by drawn, 20k spills to nominal
        assert result["provision_on_drawn"][0] == pytest.approx(30_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(20_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(180_000.0)


# =============================================================================
# OBS-only deduction tests
# =============================================================================


class TestOBSOnlyProvision:
    """Provisions applied to off-balance-sheet (contingent) items with drawn=0."""

    def test_obs_only_provision_reduces_nominal(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Contingent with drawn=0: provision goes entirely to nominal."""
        exposures = _make_exposures(
            drawn_amount=0.0, interest=0.0, nominal_amount=500_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 20_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_on_drawn"][0] == pytest.approx(0.0)
        assert result["provision_on_nominal"][0] == pytest.approx(20_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(480_000.0)


# =============================================================================
# Provision capping tests
# =============================================================================


class TestProvisionCapping:
    """Provisions exceeding total exposure should be capped."""

    def test_provision_exceeding_total_exposure_is_capped(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Provision cannot exceed drawn + nominal."""
        exposures = _make_exposures(
            drawn_amount=50_000.0, interest=0.0, nominal_amount=50_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 200_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        # Capped: 50k on drawn + 50k on nominal = 100k total
        assert result["provision_on_drawn"][0] == pytest.approx(50_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(100_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(0.0)


# =============================================================================
# Negative drawn amount tests
# =============================================================================


class TestNegativeDrawnAmount:
    """Negative drawn (credit balance) should not absorb provision."""

    def test_negative_drawn_provision_goes_to_nominal(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Negative drawn floored to 0 → provision reduces nominal only."""
        exposures = _make_exposures(
            drawn_amount=-50_000.0, interest=5_000.0, nominal_amount=200_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 30_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        # Floored drawn is 0 → no absorption
        assert result["provision_on_drawn"][0] == pytest.approx(0.0)
        assert result["provision_on_nominal"][0] == pytest.approx(30_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(170_000.0)


# =============================================================================
# IRB provision tests
# =============================================================================


class TestIRBProvisions:
    """IRB provisions: allocated but NOT deducted from EAD."""

    def test_irb_provision_not_deducted(
        self, processor: CRMProcessor, irb_config: CalculationConfig
    ) -> None:
        """F-IRB exposure: provision_deducted=0, provision_allocated tracked."""
        exposures = _make_exposures(
            approach=ApproachType.FIRB.value,
            drawn_amount=1_000_000.0, interest=0.0, nominal_amount=0.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, irb_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(0.0)
        assert result["provision_on_drawn"][0] == pytest.approx(0.0)
        assert result["provision_on_nominal"][0] == pytest.approx(0.0)
        assert result["nominal_after_provision"][0] == pytest.approx(0.0)  # nominal stays 0

    def test_slotting_provision_not_deducted(
        self, processor: CRMProcessor, irb_config: CalculationConfig
    ) -> None:
        """Slotting exposure: provision_deducted=0."""
        exposures = _make_exposures(
            approach=ApproachType.SLOTTING.value,
            drawn_amount=1_000_000.0, interest=0.0, nominal_amount=500_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "beneficiary_type": "loan",
            "amount": 100_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, irb_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(100_000.0)
        assert result["provision_deducted"][0] == pytest.approx(0.0)
        assert result["nominal_after_provision"][0] == pytest.approx(500_000.0)


# =============================================================================
# Mixed SA/IRB tests
# =============================================================================


class TestMixedSAIRBProvisions:
    """Mixed SA/IRB exposures: only SA gets provision_deducted > 0."""

    def test_sa_irb_mixed_deduction(
        self, processor: CRMProcessor, irb_config: CalculationConfig
    ) -> None:
        """Only SA exposure gets deduction; IRB gets allocated but not deducted."""
        exposures = _make_exposures(
            exposure_reference=["EXP_SA", "EXP_IRB"],
            counterparty_reference=["CP001", "CP002"],
            parent_facility_reference=["FAC001", "FAC002"],
            drawn_amount=[500_000.0, 500_000.0],
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.FIRB.value],
            risk_type=["MR", "MR"],
            exposure_class=["corporate", "corporate"],
            lgd=[0.45, 0.45],
            seniority=["senior", "senior"],
        )
        provisions = _make_provisions([
            {
                "provision_reference": "P1",
                "beneficiary_reference": "EXP_SA",
                "beneficiary_type": "loan",
                "amount": 50_000.0,
                "provision_type": "SCRA",
            },
            {
                "provision_reference": "P2",
                "beneficiary_reference": "EXP_IRB",
                "beneficiary_type": "loan",
                "amount": 50_000.0,
                "provision_type": "SCRA",
            },
        ])

        result = processor.resolve_provisions(exposures, provisions, irb_config).collect()

        sa_row = result.filter(pl.col("exposure_reference") == "EXP_SA")
        irb_row = result.filter(pl.col("exposure_reference") == "EXP_IRB")

        assert sa_row["provision_deducted"][0] == pytest.approx(50_000.0)
        assert irb_row["provision_deducted"][0] == pytest.approx(0.0)
        assert irb_row["provision_allocated"][0] == pytest.approx(50_000.0)


# =============================================================================
# Facility-level provision tests
# =============================================================================


class TestFacilityLevelProvision:
    """Provisions referencing a facility, pro-rata allocated to child exposures."""

    def test_facility_provision_allocated_pro_rata(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Facility-level provision should be allocated pro-rata by exposure weight."""
        # Two exposures under the same facility
        exposures = _make_exposures(
            exposure_reference=["EXP_A", "EXP_B"],
            counterparty_reference=["CP001", "CP001"],
            parent_facility_reference=["FAC001", "FAC001"],
            drawn_amount=[600_000.0, 400_000.0],  # 60:40 ratio
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.SA.value],
            risk_type=["MR", "MR"],
            exposure_class=["corporate", "corporate"],
            lgd=[0.45, 0.45],
            seniority=["senior", "senior"],
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "FAC001",
            "beneficiary_type": "facility",
            "amount": 100_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")

        # Pro-rata: 60% of 100k = 60k; 40% of 100k = 40k
        assert exp_a["provision_allocated"][0] == pytest.approx(60_000.0)
        assert exp_b["provision_allocated"][0] == pytest.approx(40_000.0)


# =============================================================================
# Counterparty-level provision tests
# =============================================================================


class TestCounterpartyLevelProvision:
    """Provisions referencing a counterparty, pro-rata allocated."""

    def test_counterparty_provision_allocated_pro_rata(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Counterparty-level provision should be pro-rata allocated."""
        exposures = _make_exposures(
            exposure_reference=["EXP_A", "EXP_B"],
            counterparty_reference=["CP001", "CP001"],
            parent_facility_reference=["FAC001", "FAC002"],
            drawn_amount=[700_000.0, 300_000.0],  # 70:30 ratio
            interest=[0.0, 0.0],
            nominal_amount=[0.0, 0.0],
            approach=[ApproachType.SA.value, ApproachType.SA.value],
            risk_type=["MR", "MR"],
            exposure_class=["corporate", "corporate"],
            lgd=[0.45, 0.45],
            seniority=["senior", "senior"],
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "CP001",
            "beneficiary_type": "counterparty",
            "amount": 100_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        exp_a = result.filter(pl.col("exposure_reference") == "EXP_A")
        exp_b = result.filter(pl.col("exposure_reference") == "EXP_B")

        assert exp_a["provision_allocated"][0] == pytest.approx(70_000.0)
        assert exp_b["provision_allocated"][0] == pytest.approx(30_000.0)


# =============================================================================
# No beneficiary_type fallback (backward compat)
# =============================================================================


class TestNoBeneficiaryTypeFallback:
    """When beneficiary_type column is absent, fall back to direct join only."""

    def test_no_beneficiary_type_direct_join(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Provisions without beneficiary_type column use direct exposure join."""
        exposures = _make_exposures(
            drawn_amount=1_000_000.0, interest=0.0, nominal_amount=0.0
        )
        # No beneficiary_type column
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "EXP001",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(50_000.0)
        assert result["provision_deducted"][0] == pytest.approx(50_000.0)


# =============================================================================
# Exposure with no matching provision
# =============================================================================


class TestNoMatchingProvision:
    """Exposures without matching provisions should get zeros."""

    def test_no_provision_all_zeros(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Exposure with no matching provision gets all-zero provision columns."""
        exposures = _make_exposures(
            drawn_amount=500_000.0, interest=0.0, nominal_amount=200_000.0
        )
        provisions = _make_provisions([{
            "provision_reference": "P1",
            "beneficiary_reference": "NO_MATCH",
            "beneficiary_type": "loan",
            "amount": 50_000.0,
            "provision_type": "SCRA",
        }])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        assert result["provision_allocated"][0] == pytest.approx(0.0)
        assert result["provision_deducted"][0] == pytest.approx(0.0)
        assert result["provision_on_drawn"][0] == pytest.approx(0.0)
        assert result["provision_on_nominal"][0] == pytest.approx(0.0)
        assert result["nominal_after_provision"][0] == pytest.approx(200_000.0)


# =============================================================================
# Multiple provisions combining
# =============================================================================


class TestMultipleProvisions:
    """Multiple provisions for the same exposure should sum."""

    def test_multiple_provisions_summed(
        self, processor: CRMProcessor, crr_config: CalculationConfig
    ) -> None:
        """Two direct provisions should sum before drawn-first deduction."""
        exposures = _make_exposures(
            drawn_amount=100_000.0, interest=0.0, nominal_amount=200_000.0
        )
        provisions = _make_provisions([
            {
                "provision_reference": "P1",
                "beneficiary_reference": "EXP001",
                "beneficiary_type": "loan",
                "amount": 60_000.0,
                "provision_type": "SCRA",
            },
            {
                "provision_reference": "P2",
                "beneficiary_reference": "EXP001",
                "beneficiary_type": "loan",
                "amount": 80_000.0,
                "provision_type": "SCRA",
            },
        ])

        result = processor.resolve_provisions(exposures, provisions, crr_config).collect()

        # Total = 140k. Drawn=100k absorbs 100k, remaining 40k → nominal
        assert result["provision_allocated"][0] == pytest.approx(140_000.0)
        assert result["provision_on_drawn"][0] == pytest.approx(100_000.0)
        assert result["provision_on_nominal"][0] == pytest.approx(40_000.0)
        assert result["nominal_after_provision"][0] == pytest.approx(160_000.0)
