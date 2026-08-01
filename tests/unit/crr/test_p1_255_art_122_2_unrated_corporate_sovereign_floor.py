"""
P1.255 — CRR Art. 122(2): unrated corporates take max(100%, sovereign RW).

CRR Art. 122(2), verbatim (docs/assets/crr.pdf p.120):

    "Exposures for which such a credit assessment is not available shall be
    assigned a 100 % risk weight or the risk weight of exposures to the central
    government of the jurisdiction in which the corporate is incorporated,
    whichever is the higher."

The engine assigned a flat 100% with no sovereign comparison, under-weighting a
corporate incorporated in a CQS6 jurisdiction (Art. 114 Table 1 = 150%).

Only sovereign CQS6 binds: the Art. 114 ladder is 0/20/50/100/100/150, so
max(100%, ·) dominates at every other step, and an unrated sovereign is 100%.

CRR-only: PS1/26 Art. 122(5) is a flat 100% with no jurisdiction clause.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator

_EAD = Decimal("10000000")


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestP1255UnratedCorporateSovereignFloor:
    """Art. 122(2) 'whichever is the higher' for unrated corporates."""

    def test_p1_255_cqs6_sovereign_lifts_unrated_corporate_to_150pct(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Unrated corporate in a CQS6 jurisdiction takes the sovereign's 150%.

        Anti-confound: 1.50 is unreachable pre-fix for this row. The only CRR
        routes to 1.50 for a corporate are (a) own cqs in {5,6} — excluded, cqs
        is null; (b) Art. 127 default with provisions < 20% — excluded, not
        defaulted and no provisions; (c) Art. 131 Table 7 short-term ECAI, which
        gates on is_rated. Pre-fix this row returns exactly 1.00.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="CORPORATE",
            config=crr_config,
            cqs=None,
            sovereign_cqs=6,
        )

        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["risk_weight"] != pytest.approx(1.00)

    def test_p1_255_cqs1_sovereign_keeps_the_100pct_floor(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """A CQS1 sovereign (0%) must NOT drag the corporate below 100%.

        This is the discriminator that pins the max() semantics rather than the
        lookup. An implementation that copied the PSE/RGLA
        ``_sovereign_derived_rw_expr`` pattern WITHOUT ``max_horizontal`` returns
        0% here and zero-weights a corporate.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="CORPORATE",
            config=crr_config,
            cqs=None,
            sovereign_cqs=1,
        )

        assert result["risk_weight"] == pytest.approx(1.00)

    def test_p1_255_cqs5_sovereign_does_not_bind(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """CQS5 sovereign is 100%, equal to the floor — guards an off-by-one."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="CORPORATE",
            config=crr_config,
            cqs=None,
            sovereign_cqs=5,
        )

        assert result["risk_weight"] == pytest.approx(1.00)

    def test_p1_255_null_sovereign_cqs_keeps_100pct(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """No sovereign assessment: Art. 114(1) unrated is 100%, so no change.

        Guards the overwhelming majority of the existing corporate estate, none
        of which populates ``sovereign_cqs``.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="CORPORATE",
            config=crr_config,
            cqs=None,
            sovereign_cqs=None,
        )

        assert result["risk_weight"] == pytest.approx(1.00)

    def test_p1_255_rated_corporate_is_untouched(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """A RATED corporate keeps its Art. 122(1) Table 6 weight.

        Art. 122(2) reaches only exposures "for which such a credit assessment
        is not available". CQS2 -> 50% must survive even beside a CQS6 sovereign.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=_EAD,
            exposure_class="CORPORATE",
            config=crr_config,
            cqs=2,
            sovereign_cqs=6,
        )

        assert result["risk_weight"] == pytest.approx(0.50)
