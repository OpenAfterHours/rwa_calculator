"""
Unit tests for output floor entity-type carve-outs (Art. 92 para 2A).

Tests cover:
- OutputFloorConfig.is_floor_applicable() for all (institution_type, reporting_basis) combos
- Floor applies: standalone UK (individual), RFB (sub-consolidated), CRR entity (consolidated)
- Floor exempt: non-ring-fenced (sub-consolidated), RFB (individual), intl subsidiary
- Backward compatibility: None institution_type/reporting_basis defaults to applicable
- CalculationConfig.basel_3_1() accepts and propagates entity-type params
- End-to-end: exempt entity's RWA is NOT floored; applicable entity's RWA IS floored

Why these tests matter:
Without entity-type carve-outs, the output floor is incorrectly applied to ring-fenced
bodies at individual level, international subsidiaries, and non-ring-fenced institutions
on sub-consolidated basis. This is materially wrong for major UK retail banks (ring-fenced
bodies) and international subsidiaries. Art. 92 para 2A defines exactly three entity
categories where the floor formula applies — all others use U-TREA with no floor add-on.

References:
- PRA PS1/26 Art. 92 para 2A(a)-(d)
- Reporting (CRR) Part Rule 2.2A
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, OutputFloorConfig
from rwa_calc.domain.enums import InstitutionType, ReportingBasis
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


def _b31_config(
    institution_type: InstitutionType | None = None,
    reporting_basis: ReportingBasis | None = None,
) -> CalculationConfig:
    """Fully-phased Basel 3.1 config (72.5% floor) with entity-type params."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2032, 1, 1),
        institution_type=institution_type,
        reporting_basis=reporting_basis,
    )


def _irb_frame(rwa: float = 50_000.0, sa_rwa: float = 100_000.0) -> pl.LazyFrame:
    """Single IRB exposure where floor binds when applicable (50k < 72.5k)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP1"],
            "exposure_class": ["CORPORATE"],
            "approach_applied": ["FIRB"],
            "ead_final": [100_000.0],
            "risk_weight": [rwa / 100_000.0],
            "rwa_final": [rwa],
            "sa_rwa": [sa_rwa],
        }
    )


# =============================================================================
# OutputFloorConfig.is_floor_applicable() unit tests
# =============================================================================


class TestIsFloorApplicable:
    """Test the Art. 92 para 2A floor applicability rules."""

    def test_crr_not_applicable(self) -> None:
        """CRR config: floor disabled, never applicable."""
        config = OutputFloorConfig.crr()
        assert config.is_floor_applicable() is False

    def test_b31_default_applicable(self) -> None:
        """B31 config with no entity type: defaults to applicable (backward compat)."""
        config = OutputFloorConfig.basel_3_1()
        assert config.is_floor_applicable() is True

    def test_b31_none_institution_type_applicable(self) -> None:
        """B31 with None institution_type: applicable (backward compat)."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=None, reporting_basis=ReportingBasis.INDIVIDUAL
        )
        assert config.is_floor_applicable() is True

    def test_b31_none_reporting_basis_applicable(self) -> None:
        """B31 with None reporting_basis: applicable (backward compat)."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.STANDALONE_UK, reporting_basis=None
        )
        assert config.is_floor_applicable() is True

    # --- Floor applies: Art. 92 para 2A(a) ---

    def test_standalone_uk_individual_applicable(self) -> None:
        """Para 2A(a)(i): stand-alone UK institution, individual basis → floor applies."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.is_floor_applicable() is True

    def test_rfb_sub_consolidated_applicable(self) -> None:
        """Para 2A(a)(ii): ring-fenced body, sub-consolidated basis → floor applies."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        assert config.is_floor_applicable() is True

    def test_crr_consolidation_entity_consolidated_applicable(self) -> None:
        """Para 2A(a)(iii): CRR consolidation entity, consolidated basis → floor applies."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.CRR_CONSOLIDATION_ENTITY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.is_floor_applicable() is True

    # --- Floor exempt: Art. 92 para 2A(b)-(d) ---

    def test_non_ring_fenced_sub_consolidated_exempt(self) -> None:
        """Para 2A(b): non-ring-fenced on sub-consolidated basis → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    def test_rfb_individual_exempt(self) -> None:
        """Para 2A(c): ring-fenced body at individual level → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.is_floor_applicable() is False

    def test_international_subsidiary_exempt(self) -> None:
        """Para 2A(d): international subsidiary → exempt on any basis."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    def test_international_subsidiary_individual_exempt(self) -> None:
        """Para 2A(d): international subsidiary at individual level → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.is_floor_applicable() is False

    def test_international_subsidiary_sub_consolidated_exempt(self) -> None:
        """Para 2A(d): international subsidiary at sub-consolidated level → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    # --- Cross-checks: wrong basis for applicable types ---

    def test_standalone_uk_consolidated_exempt(self) -> None:
        """Stand-alone UK on consolidated basis: not in applicability set → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    def test_standalone_uk_sub_consolidated_exempt(self) -> None:
        """Stand-alone UK on sub-consolidated basis: not in applicability set → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    def test_rfb_consolidated_exempt(self) -> None:
        """RFB on consolidated basis: not in applicability set → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False

    def test_crr_entity_individual_exempt(self) -> None:
        """CRR consolidation entity on individual basis: not applicable → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.CRR_CONSOLIDATION_ENTITY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.is_floor_applicable() is False

    def test_non_ring_fenced_individual_exempt(self) -> None:
        """Non-ring-fenced on individual basis: not in applicability set → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.is_floor_applicable() is False

    def test_non_ring_fenced_consolidated_exempt(self) -> None:
        """Non-ring-fenced on consolidated basis: not in applicability set → exempt."""
        config = OutputFloorConfig.basel_3_1(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.is_floor_applicable() is False


# =============================================================================
# CalculationConfig integration
# =============================================================================


class TestCalculationConfigIntegration:
    """CalculationConfig.basel_3_1() propagates entity-type params to OutputFloorConfig."""

    def test_config_propagates_institution_type(self) -> None:
        config = _b31_config(
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.output_floor.institution_type == InstitutionType.STANDALONE_UK
        assert config.output_floor.reporting_basis == ReportingBasis.INDIVIDUAL
        assert config.output_floor.is_floor_applicable() is True

    def test_config_propagates_exempt_type(self) -> None:
        config = _b31_config(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        assert config.output_floor.institution_type == InstitutionType.INTERNATIONAL_SUBSIDIARY
        assert config.output_floor.is_floor_applicable() is False

    def test_config_default_no_entity_type(self) -> None:
        """Default B31 config (no entity type) → floor applicable."""
        config = _b31_config()
        assert config.output_floor.institution_type is None
        assert config.output_floor.reporting_basis is None
        assert config.output_floor.is_floor_applicable() is True

    def test_crr_config_not_applicable(self) -> None:
        """CRR config → floor not applicable regardless of entity type."""
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        assert config.output_floor.is_floor_applicable() is False


# =============================================================================
# End-to-end: aggregator respects entity-type carve-outs
# =============================================================================


class TestAggregatorEntityTypeCarveOuts:
    """The aggregator skips the output floor for exempt entity types."""

    def test_exempt_entity_rwa_not_floored(self, aggregator: OutputAggregator) -> None:
        """International subsidiary: IRB RWA stays at 50k (not floored to 72.5k)."""
        config = _b31_config(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Floor disabled for intl subsidiary → RWA stays at 50k
        assert df["rwa_final"][0] == pytest.approx(50_000.0, rel=0.001)
        assert result.output_floor_summary is None
        assert result.floor_impact is None

    def test_applicable_entity_rwa_floored(self, aggregator: OutputAggregator) -> None:
        """Standalone UK: IRB RWA floored from 50k to 72.5k."""
        config = _b31_config(
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Floor binds: 72.5% * 100k = 72.5k > 50k
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)
        assert result.output_floor_summary is not None
        assert result.output_floor_summary.portfolio_floor_binding is True

    def test_rfb_sub_consolidated_floored(self, aggregator: OutputAggregator) -> None:
        """Ring-fenced body on sub-consolidated basis: floor applies."""
        config = _b31_config(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)

    def test_rfb_individual_not_floored(self, aggregator: OutputAggregator) -> None:
        """Ring-fenced body at individual level: exempt per para 2A(c)."""
        config = _b31_config(
            institution_type=InstitutionType.RING_FENCED_BODY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Exempt → RWA stays at 50k
        assert df["rwa_final"][0] == pytest.approx(50_000.0, rel=0.001)
        assert result.output_floor_summary is None

    def test_non_ring_fenced_sub_consolidated_not_floored(
        self, aggregator: OutputAggregator
    ) -> None:
        """Non-ring-fenced on sub-consolidated basis: exempt per para 2A(b)."""
        config = _b31_config(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.SUB_CONSOLIDATED,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        assert df["rwa_final"][0] == pytest.approx(50_000.0, rel=0.001)
        assert result.output_floor_summary is None

    def test_crr_entity_consolidated_floored(self, aggregator: OutputAggregator) -> None:
        """CRR consolidation entity on consolidated basis: floor applies."""
        config = _b31_config(
            institution_type=InstitutionType.CRR_CONSOLIDATION_ENTITY,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)
        assert result.output_floor_summary is not None

    def test_default_b31_config_still_floors(self, aggregator: OutputAggregator) -> None:
        """Default B31 config (no entity type) still applies floor — backward compat."""
        config = _b31_config()  # No entity type specified
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        assert df["rwa_final"][0] == pytest.approx(72_500.0, rel=0.001)

    def test_exempt_entity_summary_and_impact_none(self, aggregator: OutputAggregator) -> None:
        """Exempt entity: no OutputFloorSummary, no floor_impact frame."""
        config = _b31_config(
            institution_type=InstitutionType.NON_RING_FENCED,
            reporting_basis=ReportingBasis.CONSOLIDATED,
        )
        irb = _irb_frame(rwa=50_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        assert result.output_floor_summary is None
        assert result.floor_impact is None

    def test_exempt_entity_floor_not_binding_when_irb_exceeds_sa(
        self, aggregator: OutputAggregator
    ) -> None:
        """Exempt entity with high IRB RWA: still no floor, no summary."""
        config = _b31_config(
            institution_type=InstitutionType.INTERNATIONAL_SUBSIDIARY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        irb = _irb_frame(rwa=90_000.0, sa_rwa=100_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)
        df = result.results.collect()
        # Even though IRB > SA threshold, exempt entity gets no floor processing
        assert df["rwa_final"][0] == pytest.approx(90_000.0, rel=0.001)
        assert result.output_floor_summary is None


# =============================================================================
# Completeness: all (InstitutionType, ReportingBasis) combos
# =============================================================================


class TestAllCombinations:
    """Exhaustive test of all 15 (institution_type x reporting_basis) combinations."""

    @pytest.mark.parametrize(
        ("institution_type", "reporting_basis", "expected_applicable"),
        [
            # Floor applies (3 combos) — Art. 92 para 2A(a)
            (InstitutionType.STANDALONE_UK, ReportingBasis.INDIVIDUAL, True),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.SUB_CONSOLIDATED, True),
            (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.CONSOLIDATED, True),
            # Floor exempt (12 combos) — Art. 92 para 2A(b)-(d)
            (InstitutionType.STANDALONE_UK, ReportingBasis.SUB_CONSOLIDATED, False),
            (InstitutionType.STANDALONE_UK, ReportingBasis.CONSOLIDATED, False),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.RING_FENCED_BODY, ReportingBasis.CONSOLIDATED, False),
            (InstitutionType.NON_RING_FENCED, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.NON_RING_FENCED, ReportingBasis.SUB_CONSOLIDATED, False),
            (InstitutionType.NON_RING_FENCED, ReportingBasis.CONSOLIDATED, False),
            (InstitutionType.INTERNATIONAL_SUBSIDIARY, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.INTERNATIONAL_SUBSIDIARY, ReportingBasis.SUB_CONSOLIDATED, False),
            (InstitutionType.INTERNATIONAL_SUBSIDIARY, ReportingBasis.CONSOLIDATED, False),
            (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.INDIVIDUAL, False),
            (InstitutionType.CRR_CONSOLIDATION_ENTITY, ReportingBasis.SUB_CONSOLIDATED, False),
        ],
    )
    def test_combination(
        self,
        institution_type: InstitutionType,
        reporting_basis: ReportingBasis,
        expected_applicable: bool,
    ) -> None:
        config = OutputFloorConfig.basel_3_1(
            institution_type=institution_type,
            reporting_basis=reporting_basis,
        )
        assert config.is_floor_applicable() is expected_applicable, (
            f"Expected is_floor_applicable()={expected_applicable} for "
            f"({institution_type.value}, {reporting_basis.value})"
        )


# =============================================================================
# Enum values
# =============================================================================


class TestEnumValues:
    """Verify enum members exist and have expected string values."""

    def test_institution_type_members(self) -> None:
        assert InstitutionType.STANDALONE_UK == "standalone_uk"
        assert InstitutionType.RING_FENCED_BODY == "ring_fenced_body"
        assert InstitutionType.NON_RING_FENCED == "non_ring_fenced"
        assert InstitutionType.INTERNATIONAL_SUBSIDIARY == "international_subsidiary"
        assert InstitutionType.CRR_CONSOLIDATION_ENTITY == "crr_consolidation_entity"

    def test_reporting_basis_members(self) -> None:
        assert ReportingBasis.INDIVIDUAL == "individual"
        assert ReportingBasis.SUB_CONSOLIDATED == "sub_consolidated"
        assert ReportingBasis.CONSOLIDATED == "consolidated"

    def test_institution_type_count(self) -> None:
        """5 institution types per Art. 92 para 2A."""
        assert len(InstitutionType) == 5

    def test_reporting_basis_count(self) -> None:
        """3 reporting bases per Rule 2.2A."""
        assert len(ReportingBasis) == 3
