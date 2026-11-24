"""
The Art. 122(8)(b) output-floor election without the Art. 122(6) permission — the registered book.

Pipeline position:
    build_reporting_ig_election_bundle() -> PipelineOrchestrator (Basel 3.1,
        PermissionMode.IRB, 2027-06-01; election on, permission off — and the
        identical bundle with the election off) -> COREPGenerator (OF 08.01)

What is asserted, and the text it is asserted from (P1.475):

- PS1/26 Art. 122(8): "For the purposes of calculating the output floor, an
  institution with permission to use the IRB Approach shall, for exposures to
  which it applies the IRB Approach within the exposure class set out in point
  (g) of Article 112(1) [...] (a) assign a 100% risk weight [...] or (b) assign
  the risk weights in points (a) or (b) of paragraph 6 [...]. An institution
  that assigns, or ceases to assign, risk weights in accordance with this point
  (b) shall give notice to the PRA." So under (b) the IRB legs' ``sa_rwa`` is
  65% / 135% of exposure value, under (a) 100%, and S-TREA moves with it.
- PS1/26 Art. 122(5)/(6): without the paragraph 6 *permission*, an unrated
  corporate weighted under the Standardised Approach takes 100% — the (8)(b)
  notice does not reach the SA leg.
- PS1/26 Annex II OF 08.01 row 0200 "Of which: investment grade": "consistent
  with approach used for the purpose of calculating the output floor". Read as
  the legs whose output-floor weight the investment-grade assessment SETS (the
  paragraph 6(a) 65% under (8)(b)). So under (8)(b) the row holds the IRB leg the
  firm assessed investment grade and leaves out two legs assessed investment
  grade whose weight another rule sets: an SME (Art. 122(11) 85%) and a
  subordinated loan (Art. 133(5) 150%; Table A2 puts it in Art. 112(1)(p), and
  Art. 122(8) reaches only "the exposure class set out in point (g)"). Under
  (8)(a) the firm made no such assessment for the floor and the row is left
  unreported (the reading this item records — LESSONS B4). Row 0190 keeps every
  unrated IRB corporate leg in either case.
- Which election an IRB-origin guarantee crossing leg reads. The registered
  crm-substitution book's S3 leg (F-IRB corporate obligor, SA domestic-CGCB
  guarantor) is reported under the SA but keeps ``approach`` ``foundation_irb``
  at the SA risk-weight stage, so it reads the Art. 122(8) election: it is part
  of an exposure the firm "applies the IRB Approach" to. Only the carrier is
  measured there. No money moves on that leg: its guarantor is a domestic
  central government at 0%, so its ``sa_rwa`` and ``rwa_final`` are 0 under
  every permission / election combination (LESSONS C2).

References:
- PRA PS1/26 Art. 122(5), (6), (8); Art. 92(3A)(b)(ii)
- PRA PS1/26 Annex II, OF 08.01 rows 0190 / 0200 (printed p.118)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.reporting_crm_substitution_portfolio import (
    GTOR_S3,
    LN_S3,
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_ig_election_portfolio import (
    DRAWN_IRB_IG,
    DRAWN_IRB_NIG,
    DRAWN_IRB_SME,
    DRAWN_IRB_SUB,
    DRAWN_SA_IG,
    LN_IRB_IG,
    LN_IRB_NIG,
    LN_IRB_SME,
    LN_IRB_SUB,
    LN_SA_IG,
    build_reporting_ig_election_bundle,
    ig_election_config,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

#: PS1/26 Art. 122(6)(a)/(b) weights the (8)(b) election selects for S-TREA.
_IG_RW = 0.65
_NIG_RW = 1.35
#: The weights that govern the two legs the election must not reach.
_SME_RW = 0.85  # Art. 122(11)
_SUB_RW = 1.50  # Art. 133(5)

#: The S-TREA contribution of the three legs the election does not move.
_UNMOVED_S_TREA = DRAWN_IRB_SME * _SME_RW + DRAWN_IRB_SUB * _SUB_RW + DRAWN_SA_IG

#: The crm-substitution book's IRB -> SA crossing leg: the S3 loan's guaranteed
#: share, substituted onto the SA domestic-CGCB guarantor.
_CROSSING_LEG = f"{LN_S3}__G_{GTOR_S3}"


@lru_cache(maxsize=2)
def _run(election: bool) -> tuple[AggregatedResultBundle, pl.DataFrame, COREPTemplateBundle]:
    """The registered book through the pipeline and COREP, with the election on or off."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_ig_election_bundle(), ig_election_config(election=election)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework="BASEL_3_1",
        output_floor_summary=result.output_floor_summary,
    )
    return result, result.results.collect(), corep


def _leg(results: pl.DataFrame, reference: str) -> dict[str, object]:
    leg = results.filter(pl.col("exposure_reference") == reference)
    assert leg.height == 1, f"{reference}: expected one leg, got {leg.height}"
    return leg.row(0, named=True)


def _firb_sheet(z_axis: str) -> str:
    """The OF 08.01 bundle key the published sheet code addresses (LESSONS B3)."""
    (key,) = SHEET_INDEX_MAPS["of08"][z_axis].bundle_keys
    return key


#: OF 08.01 z:0012 "Corporates - other general corporates - non-SME (FIRB)".
_NON_SME_FIRB = "0012"
#: OF 08.01 z:0024 "Corporates - SME (FIRB)".
_SME_FIRB = "0024"


def _of08_cell(
    corep: COREPTemplateBundle, row_ref: str, column: str = "0110", z_axis: str = _NON_SME_FIRB
) -> float | None:
    sheet = _firb_sheet(z_axis)
    assert sheet in corep.c08_01, f"sheet {sheet!r} not emitted; got {sorted(corep.c08_01)}"
    matched = corep.c08_01[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched[column][0]


# ---------------------------------------------------------------------------
# Adequacy (LESSONS C11): IG and non-IG IRB legs, two IG IRB legs another rule
# weights, and an IG SA leg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "approach", "exposure_class", "seniority", "assessed_ig"),
    [
        (LN_IRB_IG, ApproachType.FIRB.value, "corporate", "senior", True),
        (LN_IRB_NIG, ApproachType.FIRB.value, "corporate", "senior", False),
        (LN_IRB_SME, ApproachType.FIRB.value, "corporate_sme", "senior", True),
        (LN_IRB_SUB, ApproachType.FIRB.value, "corporate", "subordinated", True),
        (LN_SA_IG, ApproachType.SA.value, "corporate", "senior", True),
    ],
)
def test_the_book_holds_each_population_the_rule_separates(
    reference: str, approach: str, exposure_class: str, seniority: str, assessed_ig: bool
) -> None:
    """Without these five unrated legs, nothing below can fail."""
    leg = _leg(_run(True)[1], reference)

    assert (
        leg["approach_applied"],
        leg["exposure_class"],
        leg["seniority"],
        leg["cqs"],
        leg["cp_is_investment_grade"],
    ) == (approach, exposure_class, seniority, None, assessed_ig)


# ---------------------------------------------------------------------------
# Engine: the election sets the IRB legs' S-TREA weight, and only theirs
# ---------------------------------------------------------------------------


_UNMOVED_SA_RWA = {
    LN_IRB_SME: DRAWN_IRB_SME * _SME_RW,  # 1,020,000: Art. 122(11) either way
    LN_IRB_SUB: DRAWN_IRB_SUB * _SUB_RW,  # 1,200,000: Art. 133(5) either way
    LN_SA_IG: DRAWN_SA_IG,  # 1,500,000: no Art. 122(6) permission
}


@pytest.mark.parametrize(
    ("election", "expected"),
    [
        pytest.param(
            True,
            {
                LN_IRB_IG: DRAWN_IRB_IG * _IG_RW,  # 1,950,000
                LN_IRB_NIG: DRAWN_IRB_NIG * _NIG_RW,  # 2,700,000
                **_UNMOVED_SA_RWA,
            },
            id="8b",
        ),
        pytest.param(
            False,
            {LN_IRB_IG: DRAWN_IRB_IG, LN_IRB_NIG: DRAWN_IRB_NIG, **_UNMOVED_SA_RWA},
            id="8a",
        ),
    ],
)
def test_sa_rwa_follows_the_floor_election_on_irb_legs_only(
    election: bool, expected: dict[str, float]
) -> None:
    """sa_rwa = exposure value x the weight that governs: the election moves two legs only."""
    results = _run(election)[1]

    sa_rwa = {ref: _leg(results, ref)["sa_rwa"] for ref in expected}

    assert sa_rwa == pytest.approx(expected)


def test_sa_leg_rwea_stays_at_the_art_122_5_weight() -> None:
    """The (8)(b) notice is not the (6) permission: the SA leg's own RWEA is 100%."""
    leg = _leg(_run(True)[1], LN_SA_IG)

    assert (leg["risk_weight"], leg["rwa_final"]) == pytest.approx((1.0, DRAWN_SA_IG))


@pytest.mark.parametrize(
    ("election", "expected"),
    [
        pytest.param(
            True, DRAWN_IRB_IG * _IG_RW + DRAWN_IRB_NIG * _NIG_RW + _UNMOVED_S_TREA, id="8b"
        ),
        pytest.param(False, DRAWN_IRB_IG + DRAWN_IRB_NIG + _UNMOVED_S_TREA, id="8a"),
    ],
)
def test_s_trea_moves_with_the_election(election: bool, expected: float) -> None:
    """Whole-book S-TREA: 8,370,000 under (8)(b), 8,720,000 under (8)(a)."""
    summary = _run(election)[0].output_floor_summary

    assert summary is not None
    assert summary.s_trea == pytest.approx(expected)


@pytest.mark.parametrize("election", [True, False], ids=["8b", "8a"])
def test_the_floor_does_not_bind_so_the_reported_total_is_u_trea(election: bool) -> None:
    """The fixture's claim, measured: U-TREA clears the 60% threshold under either election."""
    summary = _run(election)[0].output_floor_summary

    assert summary is not None
    assert summary.u_trea > summary.floor_threshold
    assert summary.total_rwa_post_floor == pytest.approx(summary.u_trea)


# ---------------------------------------------------------------------------
# OF 08.01 rows 0190 / 0200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("election", [True, False], ids=["8b", "8a"])
def test_row_0190_holds_every_unrated_irb_leg_whatever_the_election(election: bool) -> None:
    """Row 0190, non-SME F-IRB sheet: 3,000,000 + 2,000,000 + the subordinated 800,000."""
    corep = _run(election)[2]

    assert _of08_cell(corep, "0190") == pytest.approx(DRAWN_IRB_IG + DRAWN_IRB_NIG + DRAWN_IRB_SUB)


def test_row_0200_holds_only_the_leg_whose_weight_the_assessment_set_under_8b() -> None:
    """Row 0200 under (8)(b): the 65% leg, 3,000,000 — not the IG subordinated leg.

    The subordinated leg is assessed investment grade and sits in row 0190 beside
    it, but Art. 133(5) sets its weight (150%), so it is not in row 0200: a raw
    ``cp_is_investment_grade`` read reports 3,800,000 here.
    """
    assert _of08_cell(_run(True)[2], "0200") == pytest.approx(DRAWN_IRB_IG)


def test_row_0200_leaves_out_the_investment_grade_sme_leg_under_8b() -> None:
    """SME F-IRB sheet under (8)(b): row 0190 1,200,000, row 0200 unreported.

    The SME is assessed investment grade, but Art. 122(11) sets its weight (85%)
    whatever the election, so row 0200 has no leg to hold: empty, not 0 and not
    1,200,000 (what a raw ``cp_is_investment_grade`` read reports).
    """
    corep = _run(True)[2]

    assert (
        _of08_cell(corep, "0190", z_axis=_SME_FIRB),
        _of08_cell(corep, "0200", z_axis=_SME_FIRB),
    ) == (pytest.approx(DRAWN_IRB_SME), None)


def test_row_0200_is_unreported_under_8a() -> None:
    """Row 0200 under (8)(a): no IG assessment for the floor, so empty — not 0, not 3,000,000.

    The book still flags the obligor investment grade on its input; at HEAD that
    flag alone filled the row although S-TREA weighted the leg at 100%.
    """
    assert _of08_cell(_run(False)[2], "0200") is None


# ---------------------------------------------------------------------------
# IRB-origin guarantee crossing legs read the Art. 122(8) election
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _crossing_leg(permission: bool, election: bool) -> dict[str, object]:
    """The S3 crossing leg of the registered crm-substitution book (Basel 3.1, IRB)."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
        sa_investment_grade_permission=permission,
        output_floor_investment_grade_election=election,
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_crm_substitution_bundle(), config)
    return _leg(result.results.collect(), _CROSSING_LEG)


def test_crossing_leg_is_irb_origin_and_sa_reported() -> None:
    """Adequacy (LESSONS C11): the leg crosses from F-IRB to the SA and is an unrated corporate."""
    leg = _crossing_leg(False, True)
    assert (
        leg["approach_applied"],
        leg["reporting_approach"],
        leg["exposure_class"],
        leg["cp_is_investment_grade"],
    ) == (ApproachType.FIRB.value, ApproachType.SA.value, "corporate", False)


@pytest.mark.parametrize(
    ("permission", "election", "expected"),
    [
        pytest.param(False, True, False, id="election-only-governs"),
        pytest.param(True, False, None, id="permission-only-does-not"),
    ],
)
def test_crossing_leg_reads_the_floor_election(
    permission: bool, election: bool, expected: bool | None
) -> None:
    """An IRB -> SA crossing leg's assessment carrier follows Art. 122(8), not 122(6).

    The obligor is assessed not investment grade, so under the (8)(b) election
    the carrier is False (135% basis) and under the (6) permission alone it is
    null: the permission does not govern a leg of an exposure the firm weights
    under the IRB Approach. This pins the carrier only. It moves no money: the
    leg's guarantor is a domestic central government at 0%, so its ``sa_rwa``
    and ``rwa_final`` are 0 in every combination (LESSONS C2).
    """
    assert _crossing_leg(permission, election)["sa_investment_grade_assessed"] is expected
