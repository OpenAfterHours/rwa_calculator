"""
P1.316 — CRR Art. 121(1) Table 5: unrated institutions take their home
sovereign's risk weight.

CRR Art. 121, verbatim (``docs/assets/crr.pdf`` PAGE_INDEX 119):

    (1) "Exposures to institutions for which a credit assessment by a nominated
        ECAI is not available shall be assigned a risk weight in accordance with
        the credit quality step to which exposures to the central government of
        the jurisdiction in which the institution is incorporated are assigned
        in accordance with Table 5."

        TABLE 5
        Credit quality step to which central government is assigned
                                    1     2     3     4     5     6
        Risk weight of exposure    20%   50%  100%  100%  100%  150%

    (2) "For exposures to unrated institutions incorporated in countries where
        the central government is unrated, the risk weight shall be 100%."

    (3) "For exposures to unrated institutions with an original effective
        maturity of three months or less, the risk weight shall be 20%."

    (4) "Notwithstanding paragraphs 2 and 3, for trade finance exposures
        referred to in point (b) of the second subparagraph of Article 162(3)
        to unrated institutions, the risk weight shall be 50% and where the
        residual maturity of these trade finance exposures to unrated
        institutions is three months or less, the risk weight shall be 20%."

The engine returned a flat 100% for every sovereign CQS: the CRR institution
branch handled only the Art. 121(3) <=3m carve-out and fell through to
``INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]`` = 1.00. The sovereign-derived
ladder itself was correct and already wired for RGLA, PSE and — from this very
table — the Art. 117(1) unrated-MDB redirect; only the direct INSTITUTION branch
never read ``cp_sovereign_cqs``.

Direction is NOT uniform, and on balance the fix REDUCES capital:

    CQS 1: 100% -> 20%    reducing (-80pp, the largest move)
    CQS 2: 100% -> 50%    reducing (-50pp)
    CQS 3/4/5:  unchanged
    CQS 6: 100% -> 150%   increasing (+50pp, the capital shortfall)

Two of six steps reduce. ``test_p1_316_portfolio_direction_is_net_reducing``
asserts both portfolio totals so that claim is measured, not narrated.

Art. 121(4) scope. Paragraph (4) reaches only "trade finance exposures referred
to in point (b) of the second subparagraph of Article 162(3)", and point (b)
reads (legislation.gov.uk, CRR as at 2026-01-01):

    "(b) self-liquidating short-term trade finance transactions connected to
    the exchange of goods or services with a residual maturity of up to one
    year as referred to in point (80) of Article 4(1);"

The first fix held every trade-LC-flagged row out of Table 5 at the 100%
interim, at every maturity, on the belief that the 50% limb had no maturity
condition. It has one, through that cross-reference: a trade LC with more than
a year to run is not an Art. 121(4) exposure, and Table 5 governs it. At
sovereign CQS 6 the blanket hold-out was 100% against 150% under every reading
of paragraph (4). ``TestP1316Art1214TradeFinanceScope`` pins both sides of the
one-year bound, inclusive, keyed on RESIDUAL maturity.

Discharges oracle register entries ORC-105 (CQS 1), ORC-020 (CQS 2) and ORC-109
(CQS 6), which were ``xfail(strict=True)`` in ``KNOWN_DISAGREEMENTS``. ORC-106 /
107 / 108 (CQS 3/4/5) and ORC-021 (Art. 121(2)) already passed and are the
regression guards: a mis-keyed table moves the first three, an unconditional
branch moves the fourth. Both failure modes are pinned here too, so they fail in
``tests/unit`` and not only in the oracle suite.

CRR ONLY. PS1/26 replaced Art. 121 with the Grade A/B/C SCRA, routed through
``cp_scra_grade`` with no sovereign-derived institution table.
``test_p1_316_basel_31_sa_rw_is_invariant_to_sovereign_cqs`` pins that, and
doubles as the LESSONS D1 output-floor evidence — see its docstring.

Why the parquets are not scanned here:
    ``tests/fixtures/**/*.parquet`` are gitignored build artifacts. This module
    builds the bundle from the P1.316 DataFrame factories directly, so it runs
    on a fresh checkout with no generation step, while
    ``save_p1316_fixtures`` (registered in ``generate_all.py``) writes the same
    rows for the reporting estate to pick up under P5.22.

References:
    - CRR Art. 121(1) Table 5; Art. 121(2); Art. 121(3); Art. 121(4).
    - CRR Art. 120(1) Table 3 (the rated control).
    - CRR Art. 162(3) second subparagraph point (b) (Art. 121(4) scope).
    - src/rwa_calc/rulebook/packs/crr.py: ``institution_rw_sovereign_derived``.
    - src/rwa_calc/engine/sa/risk_weights.py:
      ``_crr_append_institution_maturity_branches``.
    - src/rwa_calc/engine/sa/sovereign_derived.py:
      ``sovereign_derived_rw_expr`` / ``crr_art_121_4_trade_finance_expr``.
    - tests/fixtures/p1_316/p1_316.py: the ten legs and the hand-calc.
    - tests/oracle/ORACLE_DERIVATIONS.md: ORC-105/020/106/107/108/109/021.
    - IMPLEMENTATION_PLAN.md: P1.316; P1.326 / P1.338 / P7.8 (Art. 121(4)
      rates).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.p1_316.p1_316 import (
    DRAWN_AMOUNT,
    EXPECTED_PORTFOLIO_RWA,
    LEGS,
    PRE_FIX_PORTFOLIO_RWA,
    REPORTING_DATE_GUIDANCE,
    create_p1316_counterparties,
    create_p1316_facilities,
    create_p1316_facility_mappings,
    create_p1316_loans,
    create_p1316_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    INSTITUTION_RISK_WEIGHTS_CRR,
    INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED,
)

_EAD = Decimal("10000000")

#: Art. 121(1) Table 5, transcribed from the article text quoted in the module
#: docstring. Deliberately hand-written rather than read from the pack: this is
#: the one place the pack's own values are checked against primary text, so
#: sourcing it from the pack would make the check circular (LESSONS B3).
_TABLE_5_FROM_ARTICLE: dict[int, float] = {1: 0.20, 2: 0.50, 3: 1.00, 4: 1.00, 5: 1.00, 6: 1.50}


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR config — Art. 121 sunsets 31 Dec 2026, so a 2024 reporting date."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _unrated_institution_rw(
    calculator: SACalculator,
    config: CalculationConfig,
    *,
    sovereign_cqs: int | None,
    maturity_years: float | None = 5.0,
    original_maturity_years: float | None = None,
    is_trade_lc: bool = False,
    own_cqs: int | None = None,
) -> float:
    """Risk-weight one unrated GB institution exposure.

    ``local_currency == currency`` keeps the Art. 121(6) FX sovereign floor off
    structurally, so every number below is Table 5's and not the floor's. With
    the floor armed a CQS-6 row already returned 150% before this fix.

    ``maturity_years`` is the residual maturity; the original maturity defaults
    to the same value unless ``original_maturity_years`` is given.
    """
    return calculate_single_sa_exposure(
        calculator,
        ead=_EAD,
        exposure_class="INSTITUTION",
        config=config,
        cqs=own_cqs,
        sovereign_cqs=sovereign_cqs,
        entity_type="institution",
        country_code="GB",
        currency="GBP",
        local_currency="GBP",
        residual_maturity_years=maturity_years,
        original_maturity_years=(
            maturity_years if original_maturity_years is None else original_maturity_years
        ),
        is_short_term_trade_lc=is_trade_lc,
    )["risk_weight"]


class TestP1316Table5Ladder:
    """Art. 121(1) Table 5 across its whole domain, plus the two discriminators."""

    @pytest.mark.parametrize("sovereign_cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_316_table_5_is_applied_at_every_step(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig, sovereign_cqs: int
    ) -> None:
        """Every step of Table 5, keyed off the article text.

        Parametrised across the whole domain rather than at the interesting
        steps: sampling only CQS 1 and 2 read this defect as purely
        conservative and missed the CQS-6 shortfall entirely. CQS 3/4/5 are
        100% both pre- and post-fix, so they cannot fail on the ladder being
        absent — they fail on it being MIS-KEYED, which is the point of
        keeping them.
        """
        actual = _unrated_institution_rw(sa_calculator, crr_config, sovereign_cqs=sovereign_cqs)

        assert actual == pytest.approx(_TABLE_5_FROM_ARTICLE[sovereign_cqs])

    def test_p1_316_cqs6_is_the_only_step_that_rises(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """The capital-shortfall limb: 150%, not the pre-fix 100%.

        Anti-confound — 1.50 is unreachable pre-fix for this row. The CRR
        routes to 1.50 for an institution are (a) own ``cqs`` 6 via Art. 120
        Table 3, excluded because ``cqs`` is null; (b) Art. 131 Table 7, which
        gates on ``is_rated``; (c) Art. 127 default, excluded — not defaulted,
        no provisions; (d) the Art. 121(6) FX floor, held off structurally by
        ``local_currency == currency``. Pre-fix this row returns exactly 1.00.
        """
        actual = _unrated_institution_rw(sa_calculator, crr_config, sovereign_cqs=6)

        assert actual == pytest.approx(1.50)
        assert actual != pytest.approx(1.00)

    def test_p1_316_null_sovereign_cqs_stays_at_the_art_121_2_residual(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Art. 121(2): an unrated central government gives 100%, not a lookup miss.

        This is the discriminator for an UNCONDITIONAL branch. An
        implementation that fires the sovereign-derived lookup without falling
        back to the Art. 121(2) residual moves this row and nothing else in the
        family notices — it is also what oracle ORC-021 guards. The value is
        read from the pack because here it IS the fallback under test, not the
        table being verified against primary text.
        """
        actual = _unrated_institution_rw(sa_calculator, crr_config, sovereign_cqs=None)

        assert actual == pytest.approx(float(INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]))
        assert actual == pytest.approx(1.00)

    def test_p1_316_short_dated_keeps_the_art_121_3_flat_20pct(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Art. 121(3) outranks Table 5: <=3m is 20% even beside a CQS 6 sovereign.

        Pinned at the worst sovereign step precisely because that is where a
        branch inserted in the wrong ORDER would show: ahead of Art. 121(3)
        the ladder would return 150% here.
        """
        actual = _unrated_institution_rw(
            sa_calculator, crr_config, sovereign_cqs=6, maturity_years=0.2
        )

        assert actual == pytest.approx(0.20)

    @pytest.mark.parametrize("own_cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_316_rated_institutions_keep_art_120_table_3(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig, own_cqs: int
    ) -> None:
        """Art. 121 reaches only exposures with no ECAI assessment.

        A rated institution must keep its Art. 120(1) Table 3 weight beside a
        CQS 6 sovereign. Table 3 and Table 5 differ at CQS 3 (50% vs 100%), so
        this is a real discriminator and not a restatement.
        """
        actual = _unrated_institution_rw(
            sa_calculator, crr_config, sovereign_cqs=6, own_cqs=own_cqs
        )

        assert actual == pytest.approx(float(INSTITUTION_RISK_WEIGHTS_CRR[CQS(own_cqs)]))

    def test_p1_316_pack_table_matches_the_article_text(self) -> None:
        """The pack's Table 5 equals the article, step for step.

        Anchored to the transcription in the module docstring rather than to the
        pack, so pack and primary text are compared rather than the pack being
        compared with itself (LESSONS A4 / B3).
        """
        from_pack = {
            int(cqs): float(rw)
            for cqs, rw in INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED.items()
            if cqs is not CQS.UNRATED
        }

        assert from_pack == _TABLE_5_FROM_ARTICLE


class TestP1316Art1214TradeFinanceScope:
    """Art. 121(4) reaches trade finance with up to one year to run — no further."""

    @pytest.mark.parametrize("residual_years", [0.5, 1.0])
    @pytest.mark.parametrize("sovereign_cqs", [1, 2, 6])
    def test_p1_316_trade_finance_within_one_year_stays_on_the_100pct_interim(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        residual_years: float,
        sovereign_cqs: int,
    ) -> None:
        """Inside Art. 121(4): held out of Table 5 on the 100% interim.

        Neither Art. 121(4) rate (50%, or 20% at residual <= 3m) is implemented
        (P1.326 / P1.338 / P7.8), so the in-scope rows fall through to the
        Art. 121 unrated 100% residual. That interim is NOT conservative against
        every reading: on the literal one ("Notwithstanding paragraphs 2 and 3",
        not 1, so Table 5 still governs) sovereign CQS 6 would be 150%. It is
        pinned so that settling the reading is a visible, deliberate edit.

        1.0 is in the set because "up to one year" is inclusive.
        """
        actual = _unrated_institution_rw(
            sa_calculator,
            crr_config,
            sovereign_cqs=sovereign_cqs,
            maturity_years=residual_years,
            is_trade_lc=True,
        )

        assert actual == pytest.approx(1.00)
        assert actual != pytest.approx(0.50), "an Art. 121(4) 50% branch was added"

    @pytest.mark.parametrize("residual_years", [1.01, 1.5, 5.0])
    @pytest.mark.parametrize("sovereign_cqs", [1, 2, 6])
    def test_p1_316_trade_finance_beyond_one_year_takes_table_5(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
        residual_years: float,
        sovereign_cqs: int,
    ) -> None:
        """Outside Art. 121(4): a trade LC with more than a year to run takes Table 5.

        Art. 162(3) second subparagraph point (b) is trade finance "with a
        residual maturity of up to one year", so these rows are ordinary
        Art. 121(1) exposures. Before this fix all nine returned 1.00: CQS 1
        and 2 over-stated by 80pp and 50pp, CQS 6 UNDER-stated by 50pp.
        """
        actual = _unrated_institution_rw(
            sa_calculator,
            crr_config,
            sovereign_cqs=sovereign_cqs,
            maturity_years=residual_years,
            is_trade_lc=True,
        )

        assert actual == pytest.approx(_TABLE_5_FROM_ARTICLE[sovereign_cqs])

    @pytest.mark.parametrize("sovereign_cqs", [1, 6])
    def test_p1_316_trade_finance_scope_keys_on_residual_not_original_maturity(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig, sovereign_cqs: int
    ) -> None:
        """Two years original, half a year residual: inside Art. 121(4).

        The discriminator against an ORIGINAL-maturity gate — the shape of the
        sibling PS1/26 Art. 121(6)(b) floor exemption, which is a different
        rule. Such a gate would leak this row into Table 5 (20% at CQS 1, 150%
        at CQS 6).
        """
        actual = _unrated_institution_rw(
            sa_calculator,
            crr_config,
            sovereign_cqs=sovereign_cqs,
            maturity_years=0.5,
            original_maturity_years=2.0,
            is_trade_lc=True,
        )

        assert actual == pytest.approx(1.00)

    @pytest.mark.parametrize("sovereign_cqs", [1, 6])
    def test_p1_316_trade_finance_with_no_maturity_stays_inside_art_121_4(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig, sovereign_cqs: int
    ) -> None:
        """No residual maturity and no maturity date: the row stays in scope.

        A trade LC whose maturity is unknown is not shown to be outside
        Art. 162(3)(b), so it keeps the Art. 121(4) interim rather than being
        priced off Table 5.
        """
        actual = _unrated_institution_rw(
            sa_calculator,
            crr_config,
            sovereign_cqs=sovereign_cqs,
            maturity_years=None,
            is_trade_lc=True,
        )

        assert actual == pytest.approx(1.00)

    @pytest.mark.parametrize("maturity_years", [0.5, 1.0, 1.5, 5.0])
    def test_p1_316_the_same_row_without_the_trade_flag_takes_the_ladder(
        self, sa_calculator: SACalculator, crr_config: CalculationConfig, maturity_years: float
    ) -> None:
        """The live control for the exclusion above.

        Without this, an exclusion that accidentally swallowed every unrated
        institution would pass the in-scope trade-finance tests and look
        correct. Same rows, same maturities, flag off -> 20% at CQS 1.
        """
        actual = _unrated_institution_rw(
            sa_calculator,
            crr_config,
            sovereign_cqs=1,
            maturity_years=maturity_years,
            is_trade_lc=False,
        )

        assert actual == pytest.approx(0.20)


class TestP1316ThroughTheFullPipeline:
    """The ten-leg P1.316 fixture through ``PipelineOrchestrator``."""

    @staticmethod
    def _run(config: CalculationConfig) -> dict[str, dict[str, float]]:
        bundle = make_raw_bundle(
            counterparties=create_p1316_counterparties(),
            facilities=create_p1316_facilities(),
            loans=create_p1316_loans(),
            facility_mappings=create_p1316_facility_mappings(),
            ratings=create_p1316_ratings(),
            # fx_rates MUST stay None: a rate row rewrites `currency` in the
            # converter and silently re-arms the Art. 121(6) FX floor, which
            # would return 150% at CQS 6 with or without this fix.
            fx_rates=None,
        )
        df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
        return {r["exposure_reference"]: r for r in df.to_dicts()}

    @pytest.fixture(scope="class")
    @classmethod
    def crr_results(cls) -> dict[str, dict[str, float]]:
        return cls._run(CalculationConfig.crr(reporting_date=REPORTING_DATE_GUIDANCE))

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_316_every_leg_carries_its_expected_risk_weight(
        self, crr_results: dict[str, dict[str, float]], label: str
    ) -> None:
        """Each of the ten legs, end to end through the real pipeline.

        Five legs MOVE and five SURVIVE (LESSONS B5): a single moving row
        cannot distinguish "the ladder works" from "the branch is
        unconditional". The full-pipeline run is what proves
        ``cp_sovereign_cqs`` actually arrives on the SA branch off the sealed
        ``crm_exit`` edge — the synthetic single-exposure helper above sets the
        column directly and so cannot.
        """
        leg = LEGS[label]
        row = crr_results[leg.loan_ref]

        assert row["risk_weight"] == pytest.approx(leg.expected_rw), leg.role
        assert row["ead_final"] == pytest.approx(DRAWN_AMOUNT)
        assert row["rwa_final"] == pytest.approx(leg.expected_rwa), leg.role

    @pytest.mark.parametrize("label", sorted(k for k, v in LEGS.items() if v.is_trade_lc))
    def test_p1_316_trade_legs_reach_the_sa_branch_with_no_residual_column(
        self, crr_results: dict[str, dict[str, float]], label: str
    ) -> None:
        """Adequacy: the Art. 121(4) scope can only be read off ``maturity_date``.

        Exposure rows carry ``residual_maturity_years`` as NULL (it is a
        collateral-schema column), so the trade legs above move only if the
        residual is derived from ``maturity_date`` and the reporting date. A
        gate on the column alone would hold all four in scope at 100%, and the
        two that must move could not.
        """
        row = crr_results[LEGS[label].loan_ref]

        assert row["is_short_term_trade_lc"] is True
        assert row["residual_maturity_years"] is None
        assert row["maturity_date"] == LEGS[label].maturity_date

    def test_p1_316_portfolio_direction_is_net_reducing(
        self, crr_results: dict[str, dict[str, float]]
    ) -> None:
        """The fix REDUCES portfolio RWA on this book. Do not call it an increase.

        Both totals are asserted absolutely. A relative assertion
        (``post < pre``) would pass on almost any change to the branch —
        LESSONS C1 measured two such assertions letting a 48% RWA movement
        through green.
        """
        total = sum(row["rwa_final"] for row in crr_results.values())

        assert total == pytest.approx(EXPECTED_PORTFOLIO_RWA)
        assert total == pytest.approx(8_100_000.0)
        assert pytest.approx(8_700_000.0) == PRE_FIX_PORTFOLIO_RWA
        assert total < PRE_FIX_PORTFOLIO_RWA

    def test_p1_316_basel_31_sa_rw_is_invariant_to_sovereign_cqs(self) -> None:
        """Basel 3.1 is untouched — which is also the LESSONS D1 floor evidence.

        Every ``engine/sa/`` transform is an indirect IRB consumer:
        ``calculate_unified`` runs the risk-weight pipeline unconditionally so
        each row carries an SA-equivalent RW for the output floor, and lowering
        that at sovereign CQS 1/2 would lower S-TREA wherever the floor binds.

        It cannot here, for two independent structural reasons, and this test
        pins the second so a future pack change cannot quietly undo it:

        1. The floor runs only where the resolved pack has
           ``feature("output_floor")``, which is True for ``b31`` and False for
           ``crr``. The changed branch lives in
           ``_apply_crr_risk_weight_overrides``, reached only when
           ``feature("sa_revised_risk_weight_overrides")`` is False — i.e.
           exactly when the floor does not run.
        2. Under Basel 3.1 the SA-equivalent comes from the SCRA chain, which
           never reads ``cp_sovereign_cqs``, nor the CRR Art. 121(4) scope. So
           the six long-dated unrated-institution legs — the two 5-year trade
           LCs among them — are invariant across the sovereign ladder.
        """
        results = self._run(CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)))
        unrated = [
            results[leg.loan_ref]["risk_weight"]
            for leg in LEGS.values()
            if leg.own_cqs is None and leg.long_dated
        ]

        assert len(unrated) == 6
        assert len(set(unrated)) == 1, (
            "a Basel 3.1 unrated-institution RW varied with cp_sovereign_cqs; "
            "the CRR Table 5 ladder has leaked into the SCRA path and the "
            "output floor is now exposed to it"
        )


def test_p1_316_sovereign_derived_helper_is_shared_with_pse_rgla_mdb() -> None:
    """The institution branch reuses the same helper as PSE / RGLA / MDB.

    Not a style assertion: the Art. 117(1) unrated-MDB branch already read
    ``INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED`` through this helper before
    P1.316, so a second, divergent implementation for institutions would have
    let the two drift. This pins that there is one lookup, by checking the
    helper reproduces Table 5 off ``cp_sovereign_cqs`` directly.
    """
    from rwa_calc.engine.sa.sovereign_derived import sovereign_derived_rw_expr

    frame = pl.DataFrame(
        {"cp_sovereign_cqs": [1, 2, 3, 4, 5, 6, None]}, schema={"cp_sovereign_cqs": pl.Int32}
    )
    out = frame.select(
        sovereign_derived_rw_expr(
            INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED,
            float(INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]),
        ).alias("rw")
    )["rw"].to_list()

    assert out == [0.20, 0.50, 1.00, 1.00, 1.00, 1.50, 1.00]
