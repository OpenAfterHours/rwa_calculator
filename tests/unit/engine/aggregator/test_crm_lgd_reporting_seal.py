"""
Unit tests for the W5 aggregator seal defect: the four ``reporting_crm_lgd_*``
carriers ``engine/aggregator/aggregator.py::_add_reporting_projection``
(``:782-995``) must add.

PS1/26 Annex II p.108 / CRR Annex II p.101 (cols 0180/0190/0200/0210): FIRB
and Foundation-Collateral-Method rows report the ADJUSTED value C_i; AIRB
rows report the ESTIMATED MARKET VALUE. Today ``_add_reporting_projection``
seals no collateral carrier at all, so COREP reads the raw ``collateral_*``
columns directly and picks the wrong basis on AIRB rows (D2). This work item
seals the method-resolved basis ONCE, in the engine, so ``reporting/`` never
re-derives it:

    reporting_crm_lgd_financial       = AIRB: collateral_financial_market_value
                                                + collateral_cash_market_value
                                         FIRB: collateral_financial_value
                                                + collateral_cash_value
    reporting_crm_lgd_real_estate     = AIRB: collateral_re_market_value
                                         FIRB: collateral_re_value
    reporting_crm_lgd_other_physical  = AIRB: collateral_other_physical_market_value
                                         FIRB: collateral_other_physical_value
    reporting_crm_lgd_receivables     = AIRB: collateral_receivables_market_value
                                         FIRB: collateral_receivables_value

The financial fold also carries the D4 fix: cash/deposit collateral is
eligible financial collateral (Art. 197(1)(a)) and belongs in col 0180, not
in a carrier no template reads.

Design note on the AIRB/FIRB discriminator: these fixtures use the CANONICAL
``ApproachType`` values (``advanced_irb`` / ``foundation_irb`` /
``standardised`` / ``slotting``), not the short uppercase aliases
(``AIRB``/``FIRB``/``SA``/``SLOTTING``) some older fixtures in
``tests/unit/test_aggregator.py`` use. Production data always carries the
canonical lowercase values (``domain/enums.py::ApproachType``); the short
aliases are a test-only convenience that only resolves correctly through
``_method_expr``'s permissive matching. Using the canonical values here
means the test exercises whichever approach-matching the W5 implementation
actually chooses, without assuming it reuses that permissive matcher.

RD-8 (recorded after this file's first revision): the Art. 200(1) "other
funded credit protection" routing decision (Art. 232 guarantee treatment vs
the AIRB LGD Modelling Collateral Method) depends on a run-level
``AIRBCollateralMethod`` election that never reaches the COREP generator, so
``engine/crm/`` -- which already holds the config and pack -- makes that
decision ONCE and emits three mutually-exclusive-by-construction amounts.
This file's section 6 seals them as plain aliases:

    ofcp_lgd_cash_deposit    -> reporting_ofcp_lgd_cash_deposit   (C 08.01 0171)
    ofcp_lgd_life_insurance  -> reporting_ofcp_lgd_life_insurance (C 08.01 0172)
    ofcp_substitution_amount -> reporting_ofcp_substitution       (C 08.01 0060)

References:
    PS1/26 Annex II, cols 0150-0210 (CRM techniques in LGD estimates)
    CRR Annex II, cols 0150-0210
    docs/plans/irb-collateral-corep-reporting.md, RD-1 / RD-4 / RD-8 / W5
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_irb_branch, pad_sa_branch, pad_slotting_branch

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

# =============================================================================
# Fixtures / helpers
# =============================================================================

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SA = pad_sa_branch(EMPTY)
EMPTY_IRB = pad_irb_branch(EMPTY)
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _irb_row(
    ref: str,
    approach_applied: str,
    *,
    ead: float = 1_000_000.0,
    collateral_re_value: float = 0.0,
    collateral_re_market_value: float = 0.0,
    collateral_financial_value: float = 0.0,
    collateral_financial_market_value: float = 0.0,
    collateral_cash_value: float = 0.0,
    collateral_cash_market_value: float = 0.0,
    collateral_receivables_value: float = 0.0,
    collateral_receivables_market_value: float = 0.0,
    collateral_other_physical_value: float = 0.0,
    collateral_other_physical_market_value: float = 0.0,
    ofcp_lgd_cash_deposit: float = 0.0,
    ofcp_lgd_life_insurance: float = 0.0,
    ofcp_substitution_amount: float = 0.0,
) -> dict:
    """One IRB-branch exposure row carrying both collateral bases per
    category, plus (RD-8) the three mutually-exclusive-by-construction
    Art. 200(1)/Art. 232 "other funded credit protection" amounts."""
    return {
        "exposure_reference": ref,
        "counterparty_reference": f"CP_{ref}",
        "exposure_class": "CORPORATE",
        "approach": approach_applied,
        "approach_applied": approach_applied,
        "ead_final": ead,
        "risk_weight": 0.5,
        "rwa": ead * 0.5,
        "rwa_final": ead * 0.5,
        "collateral_re_value": collateral_re_value,
        "collateral_re_market_value": collateral_re_market_value,
        "collateral_financial_value": collateral_financial_value,
        "collateral_financial_market_value": collateral_financial_market_value,
        "collateral_cash_value": collateral_cash_value,
        "collateral_cash_market_value": collateral_cash_market_value,
        "collateral_receivables_value": collateral_receivables_value,
        "collateral_receivables_market_value": collateral_receivables_market_value,
        "collateral_other_physical_value": collateral_other_physical_value,
        "collateral_other_physical_market_value": collateral_other_physical_market_value,
        "ofcp_lgd_cash_deposit": ofcp_lgd_cash_deposit,
        "ofcp_lgd_life_insurance": ofcp_lgd_life_insurance,
        "ofcp_substitution_amount": ofcp_substitution_amount,
    }


def _run(
    aggregator: OutputAggregator,
    config: CalculationConfig,
    *,
    sa: pl.LazyFrame = EMPTY_SA,
    irb: pl.LazyFrame = EMPTY_IRB,
    slotting: pl.LazyFrame = EMPTY_SLOTTING,
) -> pl.DataFrame:
    result = aggregator.aggregate(
        sa_results=sa,
        irb_results=irb,
        slotting_results=slotting,
        equity_bundle=None,
        config=config,
    )
    return result.results.collect()


# =============================================================================
# 1. Basis selection: AIRB seals market value, FIRB seals adjusted value
# =============================================================================


class TestBasisSelection:
    """W5 assertion #1: same RE pledge, AIRB seals the market value, FIRB
    seals the adjusted value (the two-limb rule, RD-1)."""

    def test_airb_seals_market_value_firb_seals_adjusted_value(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange: identical pledge on an AIRB row and a FIRB row --
        # adjusted (post-haircut) = 300,000, market (pre-haircut) = 500,000.
        rows = [
            _irb_row(
                "AIRB1",
                "advanced_irb",
                collateral_re_value=300_000.0,
                collateral_re_market_value=500_000.0,
            ),
            _irb_row(
                "FIRB1",
                "foundation_irb",
                collateral_re_value=300_000.0,
                collateral_re_market_value=500_000.0,
            ),
        ]
        irb = pad_irb_branch(pl.LazyFrame(rows))

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        airb = df.filter(pl.col("exposure_reference") == "AIRB1")
        firb = df.filter(pl.col("exposure_reference") == "FIRB1")
        assert airb["reporting_crm_lgd_real_estate"][0] == pytest.approx(500_000.0)
        assert firb["reporting_crm_lgd_real_estate"][0] == pytest.approx(300_000.0)


# =============================================================================
# 2. D4: cash/deposit collateral folds into the financial carrier
# =============================================================================


class TestCashFoldsIntoFinancial:
    """W5 assertion #2 (D4): cash on deposit is eligible financial collateral
    (Art. 197(1)(a)), so reporting_crm_lgd_financial must include it -- on
    BOTH the AIRB (market) and FIRB (adjusted) bases."""

    def test_airb_cash_only_pledge_yields_nonzero_financial(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange: only cash pledged, financial itself is 0.0.
        irb = pad_irb_branch(
            pl.LazyFrame(
                [
                    _irb_row(
                        "AIRB1",
                        "advanced_irb",
                        collateral_financial_market_value=0.0,
                        collateral_cash_market_value=200_000.0,
                    )
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        assert df["reporting_crm_lgd_financial"][0] == pytest.approx(200_000.0)

    def test_firb_cash_only_pledge_yields_nonzero_financial(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange
        irb = pad_irb_branch(
            pl.LazyFrame(
                [
                    _irb_row(
                        "FIRB1",
                        "foundation_irb",
                        collateral_financial_value=0.0,
                        collateral_cash_value=150_000.0,
                    )
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        assert df["reporting_crm_lgd_financial"][0] == pytest.approx(150_000.0)


# =============================================================================
# 3. Non-IRB rows (SA / slotting) match the projection's existing convention
# =============================================================================


class TestNonIrbRowsMatchExistingConvention:
    """W5 assertion #3: an SA/slotting row -- not AIRB, so it falls to the
    same fallback branch as FIRB -- seals whatever the underlying (adjusted)
    carrier already holds. Every other ``_add_reporting_projection`` carrier
    (reporting_class, reporting_ead, ...) resolves via direct expression on
    EVERY row regardless of approach; none of them special-case a "wrong
    approach" to a different null/zero convention. A collateral-free SA/
    slotting row's adjusted carrier is 0.0 (the CRM engine's own established
    never-null-for-uncollateralised convention), so the seal must be 0.0 too.
    """

    def test_sa_row_with_no_collateral_seals_zero(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange
        sa = pad_sa_branch(
            pl.LazyFrame(
                [
                    {
                        "exposure_reference": "SA1",
                        "counterparty_reference": "CPSA1",
                        "exposure_class": "CORPORATE",
                        "approach_applied": "standardised",
                        "ead_final": 1_000_000.0,
                        "risk_weight": 1.0,
                        "rwa_pre_factor": 1_000_000.0,
                        "rwa_post_factor": 1_000_000.0,
                        "rwa_final": 1_000_000.0,
                        "collateral_re_value": 0.0,
                        "collateral_re_market_value": 0.0,
                    }
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, sa=sa)

        # Assert
        assert df["reporting_crm_lgd_real_estate"][0] == pytest.approx(0.0)

    def test_slotting_row_with_no_collateral_seals_zero(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange
        slotting = pad_slotting_branch(
            pl.LazyFrame(
                [
                    {
                        "exposure_reference": "SL1",
                        "counterparty_reference": "CPSL1",
                        "exposure_class": "SPECIALISED_LENDING",
                        "approach_applied": "slotting",
                        "ead_final": 800_000.0,
                        "risk_weight": 0.7,
                        "rwa_final": 560_000.0,
                        "collateral_re_value": 0.0,
                        "collateral_re_market_value": 0.0,
                    }
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, slotting=slotting)

        # Assert
        assert df["reporting_crm_lgd_real_estate"][0] == pytest.approx(0.0)


# =============================================================================
# 4. Never fill Float nulls to 0.0
# =============================================================================


class TestNeverFillFloatNullsToZero:
    """W5 assertion #4: when collateral was never computed for a leg (both
    the adjusted and market carriers are the branch edge's typed-null
    default -- omitted from the hand-rolled fixture entirely), the sealed
    carrier must stay null, mirroring every other nullable carrier
    ``_add_reporting_projection`` already seals (e.g. ``guarantee_rwa_benefit``,
    ``reporting_gross_on_bs`` -- "never fill Float nulls to 0.0 --
    anti-conservative", the aggregator's own docstring wording)."""

    def test_airb_row_without_collateral_columns_seals_null(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        # Arrange: collateral_re_value / collateral_re_market_value
        # deliberately OMITTED -- pad_irb_branch injects the edge's typed-null
        # default for both (they are REQUIRED-with-injection columns).
        irb = pad_irb_branch(
            pl.LazyFrame(
                [
                    {
                        "exposure_reference": "AIRB_NULL",
                        "counterparty_reference": "CPN1",
                        "exposure_class": "CORPORATE",
                        "approach": "advanced_irb",
                        "approach_applied": "advanced_irb",
                        "ead_final": 1_000_000.0,
                        "risk_weight": 0.5,
                        "rwa": 500_000.0,
                        "rwa_final": 500_000.0,
                    }
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        assert df["reporting_crm_lgd_real_estate"][0] is None


# =============================================================================
# 5. The four carriers are declared on the aggregator_exit edge
# =============================================================================


class TestSealedCarriersDeclaredOnEdge:
    """W5 scope includes ``contracts/edges.py`` -- the edge contract must
    declare the four new sealed names, mirroring the established pattern for
    every other ``_add_reporting_projection`` output
    (``test_aggregator.py::TestReportingProjection::test_projection_columns_declared_on_edge``).
    """

    def test_reporting_crm_lgd_columns_declared_on_aggregator_exit(self) -> None:
        from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE

        expected = (
            "reporting_crm_lgd_financial",
            "reporting_crm_lgd_real_estate",
            "reporting_crm_lgd_other_physical",
            "reporting_crm_lgd_receivables",
        )
        missing = [name for name in expected if name not in AGGREGATOR_EXIT_EDGE.columns]
        assert not missing, f"reporting_crm_lgd_* columns missing from aggregator_exit: {missing}"

    def test_reporting_ofcp_columns_declared_on_aggregator_exit(self) -> None:
        """RD-8's three OFCP routing aliases must also be declared."""
        from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE

        expected = (
            "reporting_ofcp_lgd_cash_deposit",
            "reporting_ofcp_lgd_life_insurance",
            "reporting_ofcp_substitution",
        )
        missing = [name for name in expected if name not in AGGREGATOR_EXIT_EDGE.columns]
        assert not missing, f"reporting_ofcp_* columns missing from aggregator_exit: {missing}"


# =============================================================================
# 6. RD-8: the Art. 200(1) OFCP routing carriers alias mutually-exclusive-by-
#    construction engine amounts -- including the FOUNDATION-election case
#    that could not be tested at COREP.
# =============================================================================


class TestOfcpRoutingCarriersAliasEngineAmounts:
    """RD-8: ``engine/crm/`` -- which already holds the config and pack --
    resolves the Art. 200(1)/Art. 232 routing decision ONCE, per leg, and
    emits three mutually-exclusive-by-construction amounts. The aggregator's
    job is only to alias them:

        ofcp_lgd_cash_deposit    -> reporting_ofcp_lgd_cash_deposit   (0171)
        ofcp_lgd_life_insurance  -> reporting_ofcp_lgd_life_insurance (0172)
        ofcp_substitution_amount -> reporting_ofcp_substitution       (0060)

    This is where the previously-untestable FOUNDATION-election case
    (``AIRBCollateralMethod.FOUNDATION`` vs ``LGD_MODELLING``) becomes
    testable: the election is resolved upstream, in ``engine/crm/``, before
    this fixture is even built, so a Basel-3.1 A-IRB leg on the FOUNDATION
    election is indistinguishable at the seal from any other leg whose
    Art. 200(1) amount the engine routed to the substitution carrier -- it
    is simply a leg where ``ofcp_substitution_amount`` is nonzero and the
    two LGD carriers are 0.0. ``config``/``framework`` play no role at this
    layer (the election was already resolved before the branch frame
    reaches the aggregator), so ``crr_config`` is used purely for fixture
    convenience, matching the file's other tests.
    """

    def test_foundation_election_leg_seals_amount_into_substitution_carrier(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        """A Basel-3.1 A-IRB leg on the FOUNDATION election: engine/crm/
        routes its Art. 200(1) amount entirely into ofcp_substitution_amount,
        leaving the two LGD carriers at 0.0. The seal must mirror that
        routing exactly, not re-derive it."""
        # Arrange
        irb = pad_irb_branch(
            pl.LazyFrame(
                [
                    _irb_row(
                        "AIRB_FOUNDATION",
                        "advanced_irb",
                        ofcp_substitution_amount=250_000.0,
                        ofcp_lgd_cash_deposit=0.0,
                        ofcp_lgd_life_insurance=0.0,
                    )
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        assert df["reporting_ofcp_substitution"][0] == pytest.approx(250_000.0)
        assert df["reporting_ofcp_lgd_cash_deposit"][0] == pytest.approx(0.0)
        assert df["reporting_ofcp_lgd_life_insurance"][0] == pytest.approx(0.0)

    def test_lgd_modelling_election_leg_seals_amounts_into_lgd_carriers(
        self, aggregator: OutputAggregator, crr_config: CalculationConfig
    ) -> None:
        """The mirror leg: a Basel-3.1 A-IRB leg on the LGD_MODELLING
        election routes its Art. 200(1)(a)/(b) amounts into the two LGD
        carriers, leaving ofcp_substitution_amount at 0.0."""
        # Arrange
        irb = pad_irb_branch(
            pl.LazyFrame(
                [
                    _irb_row(
                        "AIRB_LGD_MODELLING",
                        "advanced_irb",
                        ofcp_lgd_cash_deposit=300_000.0,
                        ofcp_lgd_life_insurance=100_000.0,
                        ofcp_substitution_amount=0.0,
                    )
                ]
            )
        )

        # Act
        df = _run(aggregator, crr_config, irb=irb)

        # Assert
        assert df["reporting_ofcp_lgd_cash_deposit"][0] == pytest.approx(300_000.0)
        assert df["reporting_ofcp_lgd_life_insurance"][0] == pytest.approx(100_000.0)
        assert df["reporting_ofcp_substitution"][0] == pytest.approx(0.0)
