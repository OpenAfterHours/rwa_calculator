"""
QRRE per-individual aggregate on the reporting tier: which C 08.01 sheet each leg lands on.

Pipeline position:
    reporting_qrre_headroom_portfolio -> PipelineOrchestrator -> COREPGenerator
        -> C 08.01 (CRR) / OF 08.01 (Basel 3.1) QRRE and retail-other sheets

Why this exists (P5.54, the deferred half of P1.320):
    P1.320 made ``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``
    count each committed facility limit once per individual rather than once per
    hierarchy leg. With that fix reverted, ``tests/acceptance/reporting`` ran
    fully green: no registered portfolio held a QRRE candidate with more than one
    leg under a facility, so the mandatory Tier 2 gate could not see the change.
    This file is the explicit Tier 2 assertion. It does not rely on the
    supervisory register to notice: the rules that tie the QRRE / retail-other
    sheets to C 09.02 rows 0100 / 0130 (``v0460_m`` / ``v0475_m``) read the same
    exposure class on both sides, so they hold whichever class a leg lands in.

Rule text (verbatim, ``docs/assets/ps126app1.pdf`` p.91):
    PS1/26 Art. 147(5A): "Retail exposures shall be assigned to the qualifying
    revolving retail exposures exposure subclass ... if they meet the following
    conditions: (a) the exposures are to individuals; (b) the exposures are
    revolving, unsecured, and to the extent they are not drawn, immediately and
    unconditionally cancellable by the institution ... (c) the largest aggregate
    nominal exposure to a single individual, out of all aggregate nominal
    exposures to individuals in the sub-portfolio, is GBP 90,000 or less;"
CRR (watchfire snapshot of legislation.gov.uk — ``docs/assets/crr.pdf`` is empty
in this checkout):
    CRR Art. 154(4)(c): "the maximum exposure to a single individual in the
    sub-portfolio is EUR 100 000 or less;"

Reporting basis: CRR Annex II item 5.3 "Retail - Qualifying revolving" (C 08.01
sheet ``retail_qrre``, z0015) against item 5.4 "Retail - Other" (``retail_other``,
z0017); PS1/26 Annex II §3.3.2 items 4.5 / 4.7, OF 08.01 sheet 0015 "Retail -
Qualifying revolving (AIRB approach)" (``retail_qrre_airb``) against sheet 0017
"Retail - Other non-SME (AIRB approach)" (``retail_other_non_sme_airb``).

What each test pins, and the regression that turns it red (measured with the
isolating plugins in ``tests/mutations/``, each regime red on its own — LESSONS
C7):

    plugin                                       what it does to the aggregate
    -------------------------------------------  ---------------------------------
    mutate_qrre_aggregate_sums_every_leg         the pre-P1.320 sum over every
                                                 leg: MOVER's two legs leave QRRE
    mutate_qrre_aggregate_takes_obligor_max      one contribution per individual:
                                                 PAST_CAP is wrongly admitted
    mutate_qrre_aggregate_divides_by_line_count  the ``attributes.py`` line-count
                                                 divide: MIXED's drawn leg and
                                                 MOF's LR leg are wrongly admitted
    mutate_qrre_aggregate_takes_first_row        a ROW-count ordinal ("the first
                                                 leg of the facility carries the
                                                 limit"): MOF's LR leg is wrongly
                                                 admitted. MIXED cannot see this
                                                 one — its candidate leg is its
                                                 first row — which is why MOF,
                                                 whose waterfall emits the
                                                 non-candidate row first, exists

MOF guards the row-count ordinal only while its non-candidate leg reaches the
aggregate FIRST — the waterfall's descending-CCF sort, an order and not a rule.
``test_mof_non_candidate_leg_reaches_the_aggregate_first`` asserts that order on
the aggregate's own input, so a change that reorders the frame fails there,
loudly, instead of silently blinding the guard.

One expectation here is a READING the owner has settled, not a fact of the
rule text: MOF's ``LR`` leg is retail-other because the engine counts the
multi-option ROOT's 120,000 limit (the P1.320 design, kept by the owner's
P1.355 brief "when some sibling sub-lines are not QRRE-eligible"). Read on the
QRRE-eligible sub-line's own 70,000 limit, it would be QRRE. If P1.355 adopts
that sub-line reading, the class test and both sheet tests go red — the right
outcome; re-point the expectation deliberately (fixture module docstring).

The sheet assertions read column 0020 (original exposure pre conversion
factors), not the exposure value. Col 0020 is the drawn balance plus the undrawn
commitment whatever the CCF, so it is fixed by the fixture's limits alone; the
exposure value is CCF-dependent and the two regimes' CCFs differ — under CRR the
LR headroom row converts at 0% and carries no exposure value at all (LESSONS C7:
state the identity over the basis-invariant carrier).

References:
- CRR Art. 154(4)(a)-(c) / PS1/26 Art. 147(5A)(a)-(c): the QRRE sub-class
- CRR Annex II item 5.3 / PS1/26 Annex II §3.3.2 item 4.5: the QRRE sheet
- tests/fixtures/reporting_qrre_headroom_portfolio.py: the portfolio
- tests/unit/classifier/test_p1_320_qrre_leg_multiplication.py: the engine guard
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import _irb_config
from tests.fixtures.reporting_qrre_headroom_portfolio import (
    EXP_MIXED_UNDRAWN,
    EXP_MOF_LR_UNDRAWN,
    EXP_MOF_MR_UNDRAWN,
    EXP_MOVER_UNDRAWN,
    FAC_MIXED,
    FAC_MOF,
    FAC_MOVER,
    LN_MIXED,
    LN_MOVER,
    MIXED_DRAWN,
    MIXED_LIMIT,
    MIXED_RISK_TYPE,
    MOF_LIMIT,
    MOF_LR_LIMIT,
    MOF_MR_LIMIT,
    MOVER_LIMIT,
    PAST_CAP_LIMIT,
    QRRE_HEADROOM_EXPECTED_CLASS,
    QRRE_HEADROOM_SHEET,
    SURVIVOR_LIMIT,
    build_reporting_qrre_headroom_bundle,
)

import rwa_calc.engine.classify.subtypes as subtypes
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

#: regime key -> the framework string ``_irb_config`` and the generator take.
_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

_QRRE: str = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER: str = ExposureClass.RETAIL_OTHER.value

#: C 08.01 / OF 08.01 row 0010 "Total exposures", column 0020 "Original exposure
#: pre conversion factors" — the CCF-invariant carrier (see the module docstring).
_TOTAL_ROW: str = "0010"
_ORIGINAL_EXPOSURE: str = "0020"
#: Column 0110 "Exposure value" — tied to the per-leg ``ead_final``.
_EXPOSURE_VALUE: str = "0110"

#: Original exposure pre-CCF each sheet must carry, from the fixture's own limits
#: and drawn balances — not from engine output (LESSONS B3). Every facility is
#: drawn up to or below its limit, so a facility's legs sum to its limit.
_EXPECTED_ORIGINAL_EXPOSURE: dict[str, float] = {
    # MOVER (drawn + headroom) + SURVIVOR (fully drawn).
    _QRRE: MOVER_LIMIT + SURVIVOR_LIMIT,
    # PAST_CAP (two fully drawn facilities) + MIXED (drawn + headroom) + MOF (two
    # waterfall headroom rows, one per sub-line, summing to the root limit).
    _RETAIL_OTHER: 2 * PAST_CAP_LIMIT + MIXED_LIMIT + MOF_LIMIT,
}


# =============================================================================
# Runs — one pipeline run per regime, memoised across the tests below
# =============================================================================


@functools.cache
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """Run the portfolio through one regime, on the config the register uses."""
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_qrre_headroom_bundle(), _irb_config(framework)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    return result.results.collect(), corep


def _ceiling(config: CalculationConfig) -> float:
    """The regime's QRRE per-individual ceiling, READ FROM THE PACK (LESSONS A4 / B3)."""
    pack = RulepackV0.from_config(config).pack
    return float(regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate))


def _legs(results: pl.DataFrame, facility_reference: str) -> pl.DataFrame:
    """Every exposure leg the hierarchy emitted under one parent facility."""
    return results.filter(pl.col("parent_facility_reference") == facility_reference)


# =============================================================================
# Adequacy — the portfolio can express the condition under test (LESSONS C11)
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_the_limits_straddle_the_regime_ceiling_as_each_guard_needs(regime_key: str) -> None:
    """Each obligor's limits sit where its guard needs them, against the PACK ceiling.

    If any of these fails, the guard it belongs to cannot fail either: a mover
    whose doubled limit is still under the cap does not move, and a past-cap
    control whose sum is under it is not past the cap.

    Arrange: the regime config the register runs, and its pack ceiling.
    Act:     compare the fixture limits with the ceiling.
    Assert:  MOVER in (ceiling/2, ceiling]; SURVIVOR <= ceiling; each PAST_CAP
             facility <= ceiling with their sum past it; MIXED and the MOF root
             in (ceiling, 2 x ceiling], the MOF sub-lines summing to the root;
             and no fx table re-derives the CRR ceiling.
    """
    # Arrange
    config = _irb_config(_REGIMES[regime_key])
    ceiling = _ceiling(config)

    # Act / Assert
    assert build_reporting_qrre_headroom_bundle().fx_rates is None, (
        "an fx_rates table re-syncs eur_gbp_rate and moves the CRR ceiling off the one "
        "these limits were checked against"
    )
    assert ceiling / 2 < MOVER_LIMIT <= ceiling, (
        f"MOVER limit {MOVER_LIMIT:,.0f} must qualify counted once and fail counted per leg "
        f"against the {ceiling:,.2f} ceiling"
    )
    assert ceiling >= SURVIVOR_LIMIT, "the live-cell control must be QRRE under every reading"
    assert PAST_CAP_LIMIT <= ceiling < 2 * PAST_CAP_LIMIT, (
        "PAST_CAP must qualify facility by facility and fail only in aggregate"
    )
    assert ceiling < MIXED_LIMIT <= 2 * ceiling, (
        f"MIXED limit {MIXED_LIMIT:,.0f} must fail counted once and pass when halved "
        f"against the {ceiling:,.2f} ceiling"
    )
    assert ceiling < MOF_LIMIT <= 2 * ceiling, (
        f"MOF root limit {MOF_LIMIT:,.0f} must fail counted once and pass when halved "
        f"against the {ceiling:,.2f} ceiling"
    )
    assert MOF_LR_LIMIT + MOF_MR_LIMIT == MOF_LIMIT, (
        "the MOF sub-lines must absorb the whole root headroom, or the waterfall adds a "
        "_RESIDUAL row to the dedupe group"
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_the_mover_mixed_and_mof_facilities_each_emit_two_legs(regime_key: str) -> None:
    """MOVER, MIXED and MOF each reach the results as two legs under one parent.

    The per-leg multiplication and the line-count divide are only reachable
    from a facility with more than one leg, and the line-count divide only from
    one whose legs differ in candidacy — MIXED's headroom leg and MOF's ``MR``
    waterfall leg each carry an undrawn commitment that is not unconditionally
    cancellable. Both MOF legs carry the ROOT's limit under the root, so they
    are one dedupe group; the waterfall's descending-CCF sort puts the ``MR`` leg
    first — ``test_mof_non_candidate_leg_reaches_the_aggregate_first`` asserts
    that order on the aggregate's own input (the results frame is not in
    classifier order).

    Arrange: the portfolio under one regime.
    Act:     read the legs under each parent facility.
    Assert:  the leg references, every leg's inherited limit, and that MIXED's
             headroom leg and MOF's ``MR`` leg are non-LR undrawn rows.
    """
    # Arrange / Act
    results, _corep = _run(regime_key)
    mover = _legs(results, FAC_MOVER)
    mixed = _legs(results, FAC_MIXED)
    mof = _legs(results, FAC_MOF)
    mixed_headroom = mixed.filter(pl.col("exposure_reference") == EXP_MIXED_UNDRAWN)
    mof_mr = mof.filter(pl.col("exposure_reference") == EXP_MOF_MR_UNDRAWN)
    mof_lr = mof.filter(pl.col("exposure_reference") == EXP_MOF_LR_UNDRAWN)

    # Assert
    assert sorted(mover["exposure_reference"]) == sorted([LN_MOVER, EXP_MOVER_UNDRAWN])
    assert sorted(mixed["exposure_reference"]) == sorted([LN_MIXED, EXP_MIXED_UNDRAWN])
    assert sorted(mof["exposure_reference"]) == sorted([EXP_MOF_LR_UNDRAWN, EXP_MOF_MR_UNDRAWN])
    assert mover["facility_limit"].to_list() == [MOVER_LIMIT, MOVER_LIMIT], (
        "every leg must inherit the full facility limit, or no leg multiplication exists"
    )
    assert mof["facility_limit"].to_list() == [MOF_LIMIT, MOF_LIMIT], (
        "both MOF waterfall legs must carry the ROOT's limit, or they are not one group"
    )
    assert mixed_headroom["undrawn_amount"].item() == pytest.approx(MIXED_LIMIT - MIXED_DRAWN)
    assert mixed_headroom["risk_type"].item() == MIXED_RISK_TYPE
    assert mof_mr["undrawn_amount"].item() == pytest.approx(MOF_MR_LIMIT)
    assert mof_mr["risk_type"].item() == MIXED_RISK_TYPE
    assert mof_lr["undrawn_amount"].item() == pytest.approx(MOF_LR_LIMIT)
    assert mof_lr["risk_type"].item() == "LR"


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_mof_non_candidate_leg_reaches_the_aggregate_first(
    regime_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MOF's ``MR`` leg is the FIRST row of its dedupe group in the aggregate's own input.

    MOF is the only leg here a row-count ordinal can mis-handle
    (``mutate_qrre_aggregate_takes_first_row``), and only while the first row
    of its (obligor, facility) group at ``qrre_obligor_aggregate_limit_expr`` is
    NOT a QRRE candidate. That order comes from the waterfall's descending-CCF
    sort, and the results frame is not in classifier order, so this spies on the
    frame the aggregate is handed. The row ordinal is computed in the same pass
    as the aggregate's own windows. If this goes red the engine may still be
    right, but MOF has stopped guarding the ordinal: make a non-candidate leg
    lead again, then re-run the plugin.

    Arrange: a spy around whichever aggregate is installed (a mutation plugin's
             included), recording MOF's group as that aggregate's frame orders it.
    Act:     run the pipeline.
    Assert:  the spy ran; row 0 of MOF's group is the ``MR`` leg and is not a
             candidate; row 1 is the ``LR`` leg and is one.
    """
    # Arrange
    installed = subtypes.qrre_obligor_aggregate_limit_expr
    seen: list[pl.DataFrame] = []
    facility_keys = ["counterparty_reference", "parent_facility_reference"]

    def _spy(
        exposures: pl.LazyFrame,
        is_qrre_candidate: pl.Expr,
        facility_limit: pl.Expr,
        candidate_limit: pl.Expr,
    ) -> tuple[pl.LazyFrame, pl.Expr]:
        frame, obligor_sum = installed(
            exposures, is_qrre_candidate, facility_limit, candidate_limit
        )
        seen.append(
            frame.with_columns(
                pl.int_range(pl.len()).over(facility_keys).alias("row_in_group"),
                is_qrre_candidate.alias("is_candidate"),
            )
            .filter(pl.col("parent_facility_reference") == FAC_MOF)
            .select("row_in_group", "exposure_reference", "is_candidate")
            .sort("row_in_group")
            .collect()
        )
        return frame, obligor_sum

    monkeypatch.setattr(subtypes, "qrre_obligor_aggregate_limit_expr", _spy)

    # Act
    PipelineOrchestrator().run_with_data(
        build_reporting_qrre_headroom_bundle(), _irb_config(_REGIMES[regime_key])
    )

    # Assert
    assert len(seen) == 1, f"{regime_key}: the QRRE aggregate was built {len(seen)} times, not once"
    assert seen[0].rows() == [
        (0, EXP_MOF_MR_UNDRAWN, False),
        (1, EXP_MOF_LR_UNDRAWN, True),
    ], f"{regime_key}: MOF's group no longer leads with its non-candidate leg:\n{seen[0]}"


# =============================================================================
# The classification each leg reaches
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_every_leg_resolves_its_qrre_or_retail_other_class(regime_key: str) -> None:
    """Each leg takes the Art. 147(5A) / Art. 154(4) class its individual's aggregate gives.

    Arrange: the portfolio under one regime.
    Act:     run the pipeline.
    Assert:  every leg's ``exposure_class`` is the recorded one, and every leg is
             A-IRB, so the sheets below are the A-IRB retail sheets.
    """
    # Arrange / Act
    results, _corep = _run(regime_key)
    classes = dict(results.select("exposure_reference", "exposure_class").iter_rows())
    approaches = set(results["reporting_approach_origin"])

    # Assert
    assert classes == QRRE_HEADROOM_EXPECTED_CLASS
    assert approaches == {"advanced_irb"}, f"{regime_key}: a retail leg left A-IRB: {approaches}"


# =============================================================================
# The reporting tier — C 08.01 / OF 08.01 sheet placement
# =============================================================================


@pytest.mark.parametrize("exposure_class", [_QRRE, _RETAIL_OTHER])
@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_each_retail_sheet_carries_exactly_its_legs_original_exposure(
    regime_key: str, exposure_class: str
) -> None:
    """The QRRE and retail-other sheets each carry exactly their legs' original exposure.

    The QRRE sheet's figure is MOVER's limit plus SURVIVOR's; the retail-other
    sheet's is PAST_CAP's two limits plus MIXED's plus the MOF root's. SURVIVOR keeps the QRRE sheet
    non-zero whichever way MOVER goes, so a regression that moved MOVER is
    distinguishable from one that emptied the sheet (LESSONS B5).

    Arrange: the portfolio under one regime.
    Act:     generate C 08.01 / OF 08.01 and read row 0010 of the class's sheet.
    Assert:  the sheet is emitted, col 0020 equals the fixture-derived original
             exposure, and col 0110 equals the summed ``ead_final`` of the legs
             whose class names this sheet.
    """
    # Arrange
    results, corep = _run(regime_key)
    sheet_key = QRRE_HEADROOM_SHEET[regime_key][exposure_class]
    legs = [ref for ref, cls in QRRE_HEADROOM_EXPECTED_CLASS.items() if cls == exposure_class]
    leg_ead = results.filter(pl.col("exposure_reference").is_in(legs))["ead_final"].sum()

    # Act
    assert sheet_key in corep.c08_01, (
        f"{regime_key}: C 08.01 emitted no {sheet_key!r} sheet; emitted {sorted(corep.c08_01)}"
    )
    total = corep.c08_01[sheet_key].filter(pl.col("row_ref") == _TOTAL_ROW)

    # Assert
    assert total[_ORIGINAL_EXPOSURE].item() == pytest.approx(
        _EXPECTED_ORIGINAL_EXPOSURE[exposure_class], rel=1e-9
    ), f"{regime_key}: {sheet_key} col {_ORIGINAL_EXPOSURE} holds another class's legs"
    assert total[_EXPOSURE_VALUE].item() == pytest.approx(leg_ead, rel=1e-9)
