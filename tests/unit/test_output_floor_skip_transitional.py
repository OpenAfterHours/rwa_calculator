"""
Unit tests for output floor transitional optionality (Art. 92 para 5).

Tests cover:
- OutputFloorConfig.basel_3_1(skip_transitional=True) produces no transitional schedule
- get_floor_percentage() returns 72.5% at any date when transitional is skipped
- Default (skip_transitional=False) preserves the PRA 4-year schedule
- CalculationConfig.basel_3_1(skip_transitional_floor=True) propagates to OutputFloorConfig
- End-to-end: skipped transitional applies full 72.5% floor during transitional period
- Backward compatibility: existing callers without skip_transitional are unaffected

Why these tests matter:
Art. 92 para 5 says institutions "may apply" the 60/65/70% transitional rates —
they are permissive, not mandatory. A firm may voluntarily apply the full 72.5%
floor from 1 Jan 2027 (day one). Without the skip_transitional parameter, a firm
wanting early opt-in has no discoverable API path — they would need to construct
OutputFloorConfig manually with an empty schedule. This parameter makes the
regulatory optionality explicit and testable.

References:
- PRA PS1/26 Art. 92 para 5: transitional rates are permissive
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, OutputFloorConfig
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


# =============================================================================
# OutputFloorConfig.basel_3_1(skip_transitional=...)
# =============================================================================


class TestOutputFloorConfigSkipTransitional:
    """OutputFloorConfig.basel_3_1() skip_transitional parameter."""

    def test_skip_transitional_true_empty_schedule(self) -> None:
        """skip_transitional=True produces an empty transitional schedule."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.transitional_floor_schedule == {}

    def test_skip_transitional_true_no_start_date(self) -> None:
        """skip_transitional=True sets transitional_start_date to None."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.transitional_start_date is None

    def test_skip_transitional_true_no_end_date(self) -> None:
        """skip_transitional=True sets transitional_end_date to None."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.transitional_end_date is None

    def test_skip_transitional_true_floor_percentage_preserved(self) -> None:
        """skip_transitional=True still has 72.5% as the floor_percentage."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.floor_percentage == Decimal("0.725")

    def test_skip_transitional_true_enabled(self) -> None:
        """skip_transitional=True keeps the floor enabled."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.enabled is True

    def test_skip_transitional_false_has_schedule(self) -> None:
        """skip_transitional=False (default) has the PRA 4-year schedule."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert len(config.transitional_floor_schedule) == 4

    def test_skip_transitional_false_has_start_date(self) -> None:
        """Default (False) retains transitional start date."""
        config = OutputFloorConfig.basel_3_1()
        assert config.transitional_start_date == date(2027, 1, 1)

    def test_skip_transitional_false_has_end_date(self) -> None:
        """Default (False) retains transitional end date."""
        config = OutputFloorConfig.basel_3_1()
        assert config.transitional_end_date == date(2030, 1, 1)

    def test_default_is_false(self) -> None:
        """Default call (no skip_transitional) preserves existing behaviour."""
        config_default = OutputFloorConfig.basel_3_1()
        config_explicit = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert (
            config_default.transitional_floor_schedule
            == config_explicit.transitional_floor_schedule
        )

    def test_skip_transitional_with_entity_type(self) -> None:
        """skip_transitional combines with entity-type params."""
        from rwa_calc.domain.enums import InstitutionType, ReportingBasis

        config = OutputFloorConfig.basel_3_1(
            skip_transitional=True,
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
        assert config.transitional_floor_schedule == {}
        assert config.is_floor_applicable()

    def test_skip_transitional_with_of_adj_inputs(self) -> None:
        """skip_transitional combines with OF-ADJ capital-tier inputs."""
        config = OutputFloorConfig.basel_3_1(
            skip_transitional=True,
            gcra_amount=500_000.0,
            sa_t2_credit=200_000.0,
        )
        assert config.transitional_floor_schedule == {}
        assert config.gcra_amount == 500_000.0
        assert config.sa_t2_credit == 200_000.0


# =============================================================================
# get_floor_percentage() with skip_transitional
# =============================================================================


class TestGetFloorPercentageSkipTransitional:
    """get_floor_percentage() returns 72.5% at any date when transitional is skipped."""

    def test_2027_returns_725_when_skipped(self) -> None:
        """During year 1 of transitional, skipped config returns 72.5% not 60%."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.get_floor_percentage(date(2027, 6, 15)) == Decimal("0.725")

    def test_2028_returns_725_when_skipped(self) -> None:
        """During year 2 of transitional, skipped config returns 72.5% not 65%."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.get_floor_percentage(date(2028, 6, 15)) == Decimal("0.725")

    def test_2029_returns_725_when_skipped(self) -> None:
        """During year 3 of transitional, skipped config returns 72.5% not 70%."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.get_floor_percentage(date(2029, 6, 15)) == Decimal("0.725")

    def test_2030_returns_725_when_skipped(self) -> None:
        """Post-transitional, skipped config returns 72.5% (same as normal)."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.get_floor_percentage(date(2030, 6, 15)) == Decimal("0.725")

    def test_2026_returns_725_when_skipped(self) -> None:
        """Before transitional start, skipped config returns 72.5% (no start gate)."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=True)
        assert config.get_floor_percentage(date(2026, 6, 15)) == Decimal("0.725")

    def test_default_2027_returns_60(self) -> None:
        """Contrast: default (not skipped) returns 60% for 2027."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert config.get_floor_percentage(date(2027, 6, 15)) == Decimal("0.60")

    def test_default_2028_returns_65(self) -> None:
        """Contrast: default returns 65% for 2028."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert config.get_floor_percentage(date(2028, 6, 15)) == Decimal("0.65")

    def test_default_2029_returns_70(self) -> None:
        """Contrast: default returns 70% for 2029."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert config.get_floor_percentage(date(2029, 6, 15)) == Decimal("0.70")

    def test_default_2026_returns_zero(self) -> None:
        """Contrast: default returns 0% before transitional starts."""
        config = OutputFloorConfig.basel_3_1(skip_transitional=False)
        assert config.get_floor_percentage(date(2026, 6, 15)) == Decimal("0.0")


# =============================================================================
# CalculationConfig.basel_3_1(skip_transitional_floor=...)
# =============================================================================


class TestCalculationConfigSkipTransitionalFloor:
    """CalculationConfig.basel_3_1() propagates skip_transitional_floor."""

    def test_propagates_to_output_floor(self) -> None:
        """skip_transitional_floor=True reaches OutputFloorConfig."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
            skip_transitional_floor=True,
        )
        assert config.output_floor.transitional_floor_schedule == {}

    def test_floor_percentage_725_during_transitional(self) -> None:
        """With skip, get_output_floor_percentage returns 72.5% during transitional."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
            skip_transitional_floor=True,
        )
        assert config.get_output_floor_percentage() == Decimal("0.725")

    def test_default_floor_percentage_60_during_transitional(self) -> None:
        """Without skip, get_output_floor_percentage returns 60% in 2027."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
        )
        assert config.get_output_floor_percentage() == Decimal("0.60")

    def test_default_is_false(self) -> None:
        """Default call preserves existing behaviour (transitional active)."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 15))
        assert len(config.output_floor.transitional_floor_schedule) == 4

    def test_skip_with_other_params(self) -> None:
        """skip_transitional_floor combines with other params."""
        from rwa_calc.domain.enums import InstitutionType, ReportingBasis

        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
            skip_transitional_floor=True,
            institution_type=InstitutionType.STANDALONE_UK,
            reporting_basis=ReportingBasis.INDIVIDUAL,
            gcra_amount=100_000.0,
        )
        assert config.output_floor.transitional_floor_schedule == {}
        assert config.output_floor.gcra_amount == 100_000.0
        assert config.output_floor.is_floor_applicable()


# =============================================================================
# End-to-End: Aggregator with skip_transitional
# =============================================================================


def _irb_frame(rwa: float = 50_000.0, sa_rwa: float = 100_000.0) -> pl.LazyFrame:
    """Single IRB exposure where floor binds (50k < 72.5k)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP1"],
            "exposure_class": ["CORPORATE"],
            "approach_applied": ["FIRB"],
            "rwa_final": [rwa],
            "sa_rwa": [sa_rwa],
            "ead_final": [200_000.0],
            "risk_weight": [0.25],
        }
    )


class TestEndToEndSkipTransitional:
    """End-to-end: aggregator respects skip_transitional."""

    def test_skipped_applies_full_floor_during_transitional(self) -> None:
        """With skip, a 2027 reporting date uses 72.5% floor, not 60%.

        IRB RWA=50k, SA RWA=100k.
        - With 72.5%: floor = 72,500 > 50,000 → binds, shortfall = 22,500
        - With 60%:   floor = 60,000 > 50,000 → binds, shortfall = 10,000
        """
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
            skip_transitional_floor=True,
        )
        aggregator = OutputAggregator()
        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=_irb_frame(),
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.floor_pct == pytest.approx(0.725)
        assert summary.portfolio_floor_binding is True
        assert summary.shortfall == pytest.approx(22_500.0)
        assert summary.total_rwa_post_floor == pytest.approx(72_500.0)

    def test_default_applies_transitional_rate(self) -> None:
        """Without skip, a 2027 reporting date uses 60% floor.

        IRB RWA=50k, SA RWA=100k.
        - With 60%: floor = 60,000 > 50,000 → binds, shortfall = 10,000
        """
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 15),
        )
        aggregator = OutputAggregator()
        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=_irb_frame(),
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.floor_pct == pytest.approx(0.60)
        assert summary.portfolio_floor_binding is True
        assert summary.shortfall == pytest.approx(10_000.0)
        assert summary.total_rwa_post_floor == pytest.approx(60_000.0)

    def test_skipped_vs_default_higher_floor_impact(self) -> None:
        """Skipped transitional always produces >= the transitional floor impact.

        This verifies the regulatory intent: voluntary early adoption of the
        full floor is more conservative than using the transitional rate.
        """
        for year in range(2027, 2031):
            reporting_date = date(year, 6, 15)
            config_skip = CalculationConfig.basel_3_1(
                reporting_date=reporting_date,
                skip_transitional_floor=True,
            )
            config_default = CalculationConfig.basel_3_1(
                reporting_date=reporting_date,
            )
            pct_skip = config_skip.get_output_floor_percentage()
            pct_default = config_default.get_output_floor_percentage()
            assert pct_skip >= pct_default, (
                f"Year {year}: skipped {pct_skip} < default {pct_default}"
            )
