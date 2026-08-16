"""Unit tests for P1.320: the QRRE per-individual aggregate counts each facility
limit ONCE, not once per exposure leg.

CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the *aggregate nominal exposure*
to a single individual. The hierarchy stage emits one row per LEG of a facility
(each drawn loan, the synthetic ``_UNDRAWN`` headroom row, each MOF waterfall /
``_RESIDUAL`` sub-row) and every leg inherits the parent's full
``facility_limit``. ``engine/stages/classify/subtypes.py`` sums that limit over
every qualifying leg, so a facility split into N legs contributes N x its limit
and the obligor is spuriously pushed out of QRRE.

The defect is one of GRAIN: the carrier (``facility_limit``) and the partition
(``counterparty_reference``) are both right; the sum runs over legs where the
rule runs over the individual's FACILITIES. The fix deduplicates on
``(counterparty_reference, parent_facility_reference)`` — the exact functional
determinant of the value being summed, since every row carrying limit ``L`` has
``parent_facility_reference`` equal to the facility that supplied ``L``.

Direction: RWA-REDUCING (Art. 154(4) gives QRRE a flat 0.04 correlation against
the Art. 154(1) curve). Under Basel 3.1 the higher QRRE PD/LGD floors are the
counterweight; see the acceptance sibling for the measured figures and for the
output-floor evidence.

Scope of THIS file: classification only, both regimes, asserted SEPARATELY per
regime (LESSONS C7 — one red across a both-regimes parametrisation proves one
regime, not two). ``exposure_class`` and ``exposure_class_irb`` are both
asserted: they are synced at ``subtypes.py:487`` and the conformance register
carries one entry for each, so they stand or fall together.

Legs that are GREEN ON BOTH SIDES BY DESIGN — do not "fix" them for not failing
first; each has a job that is not moving:

- (iv) ``LN_Q1`` — the live-cell control. It keeps the QRRE population non-empty
  PRE-fix, so a reader can distinguish "the fix worked" from "the fix zeroed the
  cell" (LESSONS B5, the two-leg fixture pattern).
- (v)  the MOF trio — pins the dedupe KEY decision (``parent_facility_reference``
  over ``root_facility_reference``). It pins the LEG-MULTIPLICATION grain ONLY:
  the root/sub grain over-count SURVIVES this fix (a drawn leg keys on its
  immediate sub, a waterfall leg on the root, so one economic facility still
  spans two dedupe groups) and is filed separately as P1.355. It is conservative
  — over-counting denies QRRE — so it does not block this item.
- (vi) the MIXED candidate / non-candidate group — the highest-value leg here.
  See ``TestLegVIMixedCandidateGroup``.

The QRRE ceiling is never typed in this file. It is read from the pack via
``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)`` (LESSONS
B3 / A4): a test that writes the number the code reads was written from the same
sentence as the code and validates nothing.

References:
- CRR Art. 154(4)(a)-(c) / PRA PS1/26 Art. 147(5A)(a)-(c): QRRE assignment.
- ``src/rwa_calc/engine/stages/classify/subtypes.py``: the obligor-aggregate
  expression under test.
- ``tests/fixtures/p1_320/p1_320.py``: the fixture and its full leg inventory.
- ``tests/unit/classifier/test_p1_191_qrre_aggregate_nominal.py``: the sibling
  that established the per-individual aggregate and carries the two-distinct-
  facilities control this file deliberately does not duplicate.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.stages.classify import ExposureClassifier
from rwa_calc.engine.stages.classify.subtypes import classify_exposure_subtypes
from rwa_calc.engine.stages.hierarchy import HierarchyResolver
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.p1_244.p1_244 import make_subtypes_frame
from tests.fixtures.p1_320.p1_320 import (
    EXP_MIX_R1_SUBA_UNDRAWN,
    EXP_MIX_R1_SUBB_UNDRAWN,
    EXP_MIX_R2_SUBA_UNDRAWN,
    EXP_MIX_R2_SUBB_UNDRAWN,
    EXP_MOF_RESIDUAL,
    EXP_MOF_SUB_UNDRAWN,
    EXP_Q2_UNDRAWN,
    LN_MOF,
    LN_Q1,
    LN_Q2,
    LN_Q3A,
    LN_Q3B,
    MIX_ROOT_LIMIT,
    QRRE2_LIMIT,
    build_p1_320_raw_bundle,
)

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value

_REPORTING_DATE = date(2027, 1, 4)

#: Every exposure the hierarchy stage emits for this bundle. Asserted as a SET
#: (not a count) so a leg that silently stops being emitted is a failure rather
#: than an invisible absence (LESSONS B4).
_EXPECTED_EXPOSURES: frozenset[str] = frozenset(
    {
        LN_Q2,
        EXP_Q2_UNDRAWN,
        LN_Q3A,
        LN_Q3B,
        LN_Q1,
        LN_MOF,
        EXP_MOF_SUB_UNDRAWN,
        EXP_MOF_RESIDUAL,
        EXP_MIX_R1_SUBA_UNDRAWN,
        EXP_MIX_R1_SUBB_UNDRAWN,
        EXP_MIX_R2_SUBA_UNDRAWN,
        EXP_MIX_R2_SUBB_UNDRAWN,
    }
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 with the Art. 123A(1)(b)(ii) granularity limb disabled.

    P5.15's 0.2%-of-portfolio granularity limb is Basel-3.1-only and, on a book
    this thin, re-classes EVERY retail row here to CORPORATE — orthogonal noise
    that would erase the QRRE population before the (c) aggregate gate under
    test could be reached. ``tests/fixtures/p1_244``'s own ``b31_drawn_leg_``
    fixture uses the same documented isolation switch for the same reason.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, enforce_retail_granularity=False
    )


def _classify(config: CalculationConfig) -> pl.DataFrame:
    """Run HierarchyResolver -> ExposureClassifier over the P1.320 bundle."""
    raw = build_p1_320_raw_bundle()
    resolved = HierarchyResolver().resolve(raw, config)
    result = ExposureClassifier().classify(resolved, config)
    return result.all_exposures.select(
        "exposure_reference",
        "counterparty_reference",
        "parent_facility_reference",
        "facility_limit",
        "exposure_class",
        "exposure_class_irb",
    ).collect()


@pytest.fixture(scope="module")
def crr_classified(crr_config: CalculationConfig) -> pl.DataFrame:
    return _classify(crr_config)


@pytest.fixture(scope="module")
def b31_classified(b31_config: CalculationConfig) -> pl.DataFrame:
    return _classify(b31_config)


def _classes(df: pl.DataFrame, ref: str) -> tuple[str | None, str | None]:
    """Return ``(exposure_class, exposure_class_irb)`` for one exposure."""
    row = df.filter(pl.col("exposure_reference") == ref)
    assert len(row) == 1, f"expected exactly 1 row for {ref!r}, got {len(row)}"
    return row["exposure_class"].item(), row["exposure_class_irb"].item()


def _ceiling(config: CalculationConfig) -> float:
    """Return the regime's QRRE aggregate-nominal ceiling, READ FROM THE PACK.

    Never typed in this file (LESSONS B3 / A4): the value the assertions must
    straddle has to come from the same place the engine reads it, or the test
    and the code were written from one sentence.
    """
    pack = RulepackV0.from_config(config).pack
    return float(regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate))


# =============================================================================
# The fixture's arithmetic against the PACK ceiling — the premise of every
# moving assertion below. Green on both sides of the fix.
# =============================================================================


class TestFixtureStraddlesThePackCeiling:
    """The mover legs must straddle the ceiling in BOTH regimes, or a "red"
    below would only be measuring the regime whose ceiling happens to sit on the
    right side of the fixture's limit (LESSONS C7).

    One leg's limit (60,000) must be admissible alone and inadmissible doubled;
    the mixed group's two roots (50,000 each) must be inadmissible summed and
    admissible halved — the latter is what makes ``TestLegVIMixedCandidateGroup``
    able to discriminate at all.
    """

    def test_crr_mover_limit_is_admissible_once_and_not_twice(
        self, crr_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config)
        assert QRRE2_LIMIT <= ceiling < 2 * QRRE2_LIMIT

    def test_b31_mover_limit_is_admissible_once_and_not_twice(
        self, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(b31_config)
        assert QRRE2_LIMIT <= ceiling < 2 * QRRE2_LIMIT

    def test_crr_mixed_group_pair_straddles_the_ceiling(
        self, crr_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config)
        assert MIX_ROOT_LIMIT <= ceiling < 2 * MIX_ROOT_LIMIT

    def test_b31_mixed_group_pair_straddles_the_ceiling(
        self, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(b31_config)
        assert MIX_ROOT_LIMIT <= ceiling < 2 * MIX_ROOT_LIMIT


# =============================================================================
# Leg (i) — headroom mover. FAILS PRE-FIX in both regimes.
# =============================================================================


class TestLegIHeadroomMover:
    """One partially-drawn card: ``FAC_Q2`` limit 60,000, ``LN_Q2`` drawn 20,000.

    The hierarchy stage emits two legs of the SAME facility — the drawn loan and
    the synthetic ``_UNDRAWN`` headroom row — and both carry ``facility_limit``
    60,000. Pre-fix the obligor aggregate is 2 x 60,000 = 120,000, above both
    ceilings, so both legs are demoted to RETAIL_OTHER. Counting the facility
    once gives 60,000, below both ceilings: both legs are QRRE.
    """

    def test_crr_drawn_leg_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_Q2) == (_QRRE, _QRRE)

    def test_b31_drawn_leg_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_Q2) == (_QRRE, _QRRE)

    def test_crr_undrawn_headroom_leg_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, EXP_Q2_UNDRAWN) == (_QRRE, _QRRE)

    def test_b31_undrawn_headroom_leg_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, EXP_Q2_UNDRAWN) == (_QRRE, _QRRE)


# =============================================================================
# Leg (ii) — multi-loan mover, NO headroom row. FAILS PRE-FIX in both regimes.
# =============================================================================


class TestLegIIMultiLoanMoverWithoutHeadroom:
    """``FAC_Q3`` limit 60,000 drawn to the penny by two 30,000 loans.

    There is no ``_UNDRAWN`` row in existence here, so this leg is what proves
    the mechanism is LEGS, not headroom: the same 60,000 limit is counted twice
    purely because the facility was drawn through two loan records. Pre-fix
    aggregate 120,000 -> RETAIL_OTHER; post-fix 60,000 -> RETAIL_QRRE.
    """

    def test_crr_first_loan_leg_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_Q3A) == (_QRRE, _QRRE)

    def test_b31_first_loan_leg_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_Q3A) == (_QRRE, _QRRE)

    def test_crr_second_loan_leg_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_Q3B) == (_QRRE, _QRRE)

    def test_b31_second_loan_leg_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_Q3B) == (_QRRE, _QRRE)


# =============================================================================
# Leg (iv) — the live-cell control. GREEN BEFORE AND AFTER, deliberately.
# =============================================================================


class TestLegIVFullyDrawnControlStaysQRRE:
    """``FAC_Q1`` 40,000 drawn to 40,000 — one leg, aggregate 40,000 either way.

    GREEN ON BOTH SIDES BY DESIGN, and that is its whole job. It keeps the QRRE
    population non-empty PRE-fix, so the suite can distinguish "the fix admitted
    the right rows" from "the fix zeroed the QRRE cell" (LESSONS B5: a single
    moving row leaves the cell empty on one side and the test cannot tell the two
    apart). Do not delete it for not failing first.
    """

    def test_crr_fully_drawn_single_leg_stays_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_Q1) == (_QRRE, _QRRE)

    def test_b31_fully_drawn_single_leg_stays_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_Q1) == (_QRRE, _QRRE)


# =============================================================================
# Leg (v) — the dedupe-KEY pin. GREEN BEFORE AND AFTER, deliberately.
# =============================================================================


class TestLegVMofPinsTheDedupeKey:
    """A nested (MOF) facility: root ``FAC_MOF`` 70,000, sub ``FAC_MOF_SUB``
    25,000, ``LN_MOF`` 10,000 drawn under the sub.

    Three legs are emitted: the drawn loan (keyed on the SUB, limit 25,000), the
    waterfall row for the sub and the residual row (both keyed on the ROOT, both
    limit 70,000). Under the chosen key ``parent_facility_reference`` the
    aggregate is 25,000 + 70,000 = 95,000, above both ceilings -> RETAIL_OTHER.
    Under the REJECTED ``root_facility_reference`` key it would collapse to
    70,000 and flip to RETAIL_QRRE in both regimes — which is what makes these
    assertions a pin on the key rather than decoration.

    GREEN ON BOTH SIDES BY DESIGN (today's un-deduplicated 165,000 is also above
    both ceilings). It does not fail first and must not be expected to.

    ⚠ It pins the LEG-MULTIPLICATION grain ONLY. The root/sub grain over-count
    survives this fix — the drawn leg keys on ``FAC_MOF_SUB`` while the waterfall
    legs key on ``FAC_MOF``, so one economic facility still spans two dedupe
    groups and 95,000 is charged where the economic aggregate nominal is 70,000.
    That residual is conservative (over-counting denies QRRE) and is filed as its
    own item, P1.355. Do not read this leg as evidence that it is fixed.
    """

    def test_crr_drawn_leg_under_the_sub_stays_retail_other(
        self, crr_classified: pl.DataFrame
    ) -> None:
        assert _classes(crr_classified, LN_MOF) == (_RETAIL_OTHER, _RETAIL_OTHER)

    def test_b31_drawn_leg_under_the_sub_stays_retail_other(
        self, b31_classified: pl.DataFrame
    ) -> None:
        assert _classes(b31_classified, LN_MOF) == (_RETAIL_OTHER, _RETAIL_OTHER)

    def test_crr_waterfall_leg_stays_retail_other(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, EXP_MOF_SUB_UNDRAWN) == (_RETAIL_OTHER, _RETAIL_OTHER)

    def test_b31_waterfall_leg_stays_retail_other(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, EXP_MOF_SUB_UNDRAWN) == (_RETAIL_OTHER, _RETAIL_OTHER)

    def test_crr_residual_leg_stays_retail_other(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, EXP_MOF_RESIDUAL) == (_RETAIL_OTHER, _RETAIL_OTHER)

    def test_b31_residual_leg_stays_retail_other(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, EXP_MOF_RESIDUAL) == (_RETAIL_OTHER, _RETAIL_OTHER)


# =============================================================================
# Leg (vi) — MIXED candidate / non-candidate group. GREEN BEFORE AND AFTER, and
# the single most load-bearing leg in this file.
# =============================================================================


class TestLegVIMixedCandidateGroup:
    """Two 50,000 MOF roots under one individual, each with an LR sub (a QRRE
    candidate) and an FR sub (fails the (b) cancellability limb). Four waterfall
    rows, every one carrying the ROOT's own ``facility_limit`` of 50,000.

    Correct aggregate: 50,000 + 50,000 = 100,000, above both ceilings ->
    RETAIL_OTHER. GREEN ON BOTH SIDES BY DESIGN — today's un-deduplicated sum is
    also 100,000, because each root already has exactly one candidate leg.

    ⚠ THIS LEG EXISTS TO REDDEN THE WRONG FIX, NOT THE OLD BEHAVIOUR. The repo's
    own nearest sibling solves the identical problem — count each obligor once
    over rows that repeat it, on the same nullable key — by DIVIDING BY THE GROUP
    LINE COUNT: ``engine/stages/classify/attributes.py:711-716`` writes
    ``partition_by_nullable(pl.len().over("counterparty_reference"), ...)`` for
    the Art. 123A(1)(b)(ii) granularity denominator. An implementer who copies
    that shape here writes ``(candidate_limit / pl.len().over(group)).sum()``,
    and that form passes EVERY OTHER LEG in this file. It is wrong only on a
    group that mixes candidate and non-candidate legs, where it gives
    50,000/2 + 50,000/2 = 50,000 and WRONGLY admits the obligor to QRRE — an
    RWA-reducing error of roughly -38% on the affected rows, reachable in
    production through an ordinary multi-option facility whose sub-limits differ
    in ``risk_type``.

    THE DIFFERENCE FROM THAT SIBLING, stated so it cannot be missed: the ordinal
    must be a ``cum_sum`` of the candidate MASK, not a row count. ``pl.len()``
    counts the non-candidate legs; a cumulative sum over the candidacy flag does
    not.
    """

    def test_crr_mixed_group_candidate_leg_stays_retail_other(
        self, crr_classified: pl.DataFrame
    ) -> None:
        assert _classes(crr_classified, EXP_MIX_R1_SUBA_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )

    def test_b31_mixed_group_candidate_leg_stays_retail_other(
        self, b31_classified: pl.DataFrame
    ) -> None:
        assert _classes(b31_classified, EXP_MIX_R1_SUBA_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )

    def test_crr_mixed_group_second_root_candidate_leg_stays_retail_other(
        self, crr_classified: pl.DataFrame
    ) -> None:
        assert _classes(crr_classified, EXP_MIX_R2_SUBA_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )

    def test_b31_mixed_group_second_root_candidate_leg_stays_retail_other(
        self, b31_classified: pl.DataFrame
    ) -> None:
        assert _classes(b31_classified, EXP_MIX_R2_SUBA_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )

    def test_crr_mixed_group_non_candidate_legs_stay_retail_other(
        self, crr_classified: pl.DataFrame
    ) -> None:
        """The FR legs fail limb (b) outright and can never be QRRE."""
        assert _classes(crr_classified, EXP_MIX_R1_SUBB_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )
        assert _classes(crr_classified, EXP_MIX_R2_SUBB_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )

    def test_b31_mixed_group_non_candidate_legs_stay_retail_other(
        self, b31_classified: pl.DataFrame
    ) -> None:
        """The FR legs fail limb (b) outright and can never be QRRE."""
        assert _classes(b31_classified, EXP_MIX_R1_SUBB_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )
        assert _classes(b31_classified, EXP_MIX_R2_SUBB_UNDRAWN) == (
            _RETAIL_OTHER,
            _RETAIL_OTHER,
        )


# =============================================================================
# Negative space — absence, not wrongness, is this project's dominant escape
# class (LESSONS B4). Green on both sides; these guard the fix's blast radius.
# =============================================================================


class TestClassificationNegativeSpace:
    """Presence and non-nullity of everything the fix newly depends on.

    ``parent_facility_reference`` becomes a newly-dereferenced column in the
    classifier's conditional expression (LESSONS D2): if it were absent or null
    the dedupe would silently pool unrelated facilities into one group, which is
    RWA-REDUCING and would show up nowhere else.
    """

    def test_crr_every_designed_leg_is_emitted(self, crr_classified: pl.DataFrame) -> None:
        assert set(crr_classified["exposure_reference"]) == _EXPECTED_EXPOSURES

    def test_b31_every_designed_leg_is_emitted(self, b31_classified: pl.DataFrame) -> None:
        assert set(b31_classified["exposure_reference"]) == _EXPECTED_EXPOSURES

    def test_crr_classes_are_non_null_on_every_leg(self, crr_classified: pl.DataFrame) -> None:
        assert crr_classified["exposure_class"].null_count() == 0
        assert crr_classified["exposure_class_irb"].null_count() == 0

    def test_b31_classes_are_non_null_on_every_leg(self, b31_classified: pl.DataFrame) -> None:
        assert b31_classified["exposure_class"].null_count() == 0
        assert b31_classified["exposure_class_irb"].null_count() == 0

    def test_crr_classes_are_enum_members(self, crr_classified: pl.DataFrame) -> None:
        """Anchored to the enum, never to a hand-written list (LESSONS B2/B3)."""
        assert set(crr_classified["exposure_class"]) <= {m.value for m in ExposureClass}
        assert set(crr_classified["exposure_class_irb"]) <= {m.value for m in ExposureClass}

    def test_b31_classes_are_enum_members(self, b31_classified: pl.DataFrame) -> None:
        """Anchored to the enum, never to a hand-written list (LESSONS B2/B3)."""
        assert set(b31_classified["exposure_class"]) <= {m.value for m in ExposureClass}
        assert set(b31_classified["exposure_class_irb"]) <= {m.value for m in ExposureClass}

    def test_crr_irb_class_stays_synced_with_the_routing_class(
        self, crr_classified: pl.DataFrame
    ) -> None:
        """``subtypes.py:487`` syncs the two; a fix that moved only one would
        leave the reporting axis and the IRB branch disagreeing."""
        mismatched = crr_classified.filter(pl.col("exposure_class") != pl.col("exposure_class_irb"))
        assert mismatched.is_empty(), mismatched

    def test_b31_irb_class_stays_synced_with_the_routing_class(
        self, b31_classified: pl.DataFrame
    ) -> None:
        """``subtypes.py:487`` syncs the two; a fix that moved only one would
        leave the reporting axis and the IRB branch disagreeing."""
        mismatched = b31_classified.filter(pl.col("exposure_class") != pl.col("exposure_class_irb"))
        assert mismatched.is_empty(), mismatched

    def test_crr_dedupe_key_and_summed_carrier_are_populated(
        self, crr_classified: pl.DataFrame
    ) -> None:
        assert crr_classified["parent_facility_reference"].null_count() == 0
        assert crr_classified["facility_limit"].null_count() == 0

    def test_b31_dedupe_key_and_summed_carrier_are_populated(
        self, b31_classified: pl.DataFrame
    ) -> None:
        assert b31_classified["parent_facility_reference"].null_count() == 0
        assert b31_classified["facility_limit"].null_count() == 0

    def test_crr_qrre_population_is_non_empty(self, crr_classified: pl.DataFrame) -> None:
        """Leg (iv) guarantees this holds PRE-fix as well as post — the fix must
        not be readable as "everything moved" or "nothing survived"."""
        assert (crr_classified["exposure_class"] == _QRRE).sum() > 0

    def test_b31_qrre_population_is_non_empty(self, b31_classified: pl.DataFrame) -> None:
        """Leg (iv) guarantees this holds PRE-fix as well as post — the fix must
        not be readable as "everything moved" or "nothing survived"."""
        assert (b31_classified["exposure_class"] == _QRRE).sum() > 0

    def test_crr_retail_other_population_is_non_empty(self, crr_classified: pl.DataFrame) -> None:
        """Legs (v) and (vi) guarantee it. A portfolio the fix moves ENTIRELY to
        QRRE cannot distinguish a correct fix from an over-reaching one."""
        assert (crr_classified["exposure_class"] == _RETAIL_OTHER).sum() > 0

    def test_b31_retail_other_population_is_non_empty(self, b31_classified: pl.DataFrame) -> None:
        """Legs (v) and (vi) guarantee it. A portfolio the fix moves ENTIRELY to
        QRRE cannot distinguish a correct fix from an over-reaching one."""
        assert (b31_classified["exposure_class"] == _RETAIL_OTHER).sum() > 0


# =============================================================================
# Leg (vii) — NULL-PARENT rows are NOT deduplicated. GREEN BEFORE AND AFTER,
# deliberately. This is the only thing in the estate that gates the third
# argument of the dedupe's ``partition_by_nullable`` call.
# =============================================================================

#: Two distinct committed limits on ONE obligor, each admissible ALONE under
#: both ceilings, their SUM inadmissible under both. That straddle is what makes
#: the leg able to tell "not deduplicated" from "deduplicated to the largest"
#: from "collapsed to zero"; ``TestNullParentRowsAreNotDeduplicated`` asserts it
#: against the PACK rather than trusting these constants.
NULL_PARENT_LIMIT_A: float = 50_000.0
NULL_PARENT_LIMIT_B: float = 45_000.0

_NULL_PARENT_REF_A = "P1320_NULLPARENT_A"
_NULL_PARENT_REF_B = "P1320_NULLPARENT_B"
_NULL_PARENT_CP = "P1320_NULLPARENT_CP"


def _null_parent_frame() -> pl.LazyFrame:
    """Two QRRE-candidate rows, one obligor, NULL ``parent_facility_reference``,
    distinct non-null ``facility_limit``.

    Built by re-pointing ``tests/fixtures/p1_244``'s single-row subtypes frame
    rather than hand-writing a schema, so the column set stays anchored to the
    fixture that is itself pinned to the ``HIERARCHY_EXIT_EDGE`` contract — a
    hand-written column list here would silently stop matching the transform's
    requirements the next time one is added (LESSONS B3).

    This shape CANNOT be produced by the hierarchy stage, which is exactly why
    no fixture bundle has it: a leg receives a non-null ``facility_limit`` only
    from the facilities left-join on ``parent_facility_reference``, or (for
    ``_UNDRAWN`` rows) from the facility that key coalesces to, so in production
    a null parent implies a null limit. It is reachable from a hand-built frame,
    from a future carrier change, and from any caller of the transform that is
    not the hierarchy stage.
    """
    base = make_subtypes_frame(cp_entity_type="individual", cp_is_natural_person=True)

    def _leg(reference: str, limit: float) -> pl.LazyFrame:
        return base.with_columns(
            pl.lit(reference).alias("exposure_reference"),
            pl.lit(_NULL_PARENT_CP).alias("counterparty_reference"),
            pl.lit(None, dtype=pl.String).alias("parent_facility_reference"),
            pl.lit(limit).alias("facility_limit"),
        )

    return pl.concat(
        [
            _leg(_NULL_PARENT_REF_A, NULL_PARENT_LIMIT_A),
            _leg(_NULL_PARENT_REF_B, NULL_PARENT_LIMIT_B),
        ]
    )


class TestNullParentRowsAreNotDeduplicated:
    """A null ``parent_facility_reference`` means "no facility identity", not
    "the same facility as every other unkeyed row of this obligor".

    Polars pools nulls into a single window partition, so a `.over([cp, parent])`
    aggregate would silently treat every unkeyed row of one obligor as legs of
    one facility and count only the largest. ``qrre_obligor_aggregate_limit_expr``
    guards against that by passing ``facility_limit`` as the third argument to
    ``partition_by_nullable`` — the fallback for null-keyed rows — so such a row
    is NOT deduplicated and contributes its own limit, which is the behaviour
    that predates P1.320.

    Two rows at 50,000 and 45,000 on one obligor therefore aggregate to 95,000,
    above both ceilings: both stay RETAIL_OTHER.

    GREEN ON BOTH SIDES of the P1.320 change by design. It pins PRESERVED
    behaviour, not the fix — HEAD before the fix gives the same answer. Do not
    delete it for not failing first, and do not fold it into the mover legs.

    ⚠ THE MUTATION IT EXISTS TO CATCH. Reduce that third argument to a literal
    (``pl.lit(0.0)`` in place of ``facility_limit``) and every null-parent row
    contributes ZERO: the obligor aggregate collapses to 0.00, which is below
    every ceiling, and both rows are WRONGLY admitted to RETAIL_QRRE —
    RWA-REDUCING, via the Art. 154(4) flat 0.04 correlation. Measured before this
    leg existed, that mutation ran the entire estate to the SAME 4 failures as
    the unmutated tree: nothing anywhere else could see it. This class is the
    whole gate.
    """

    def test_crr_the_two_limits_straddle_the_ceiling_only_when_summed(
        self, crr_config: CalculationConfig
    ) -> None:
        """The premise, read from the pack (LESSONS B3). Each limit must be
        admissible ALONE — otherwise the assertions below would pass under the
        mutation's "keep only the largest" cousin too, and prove nothing."""
        ceiling = _ceiling(crr_config)
        assert max(NULL_PARENT_LIMIT_A, NULL_PARENT_LIMIT_B) <= ceiling
        assert ceiling < NULL_PARENT_LIMIT_A + NULL_PARENT_LIMIT_B

    def test_b31_the_two_limits_straddle_the_ceiling_only_when_summed(
        self, b31_config: CalculationConfig
    ) -> None:
        """The premise, read from the pack (LESSONS B3). Each limit must be
        admissible ALONE — otherwise the assertions below would pass under the
        mutation's "keep only the largest" cousin too, and prove nothing."""
        ceiling = _ceiling(b31_config)
        assert max(NULL_PARENT_LIMIT_A, NULL_PARENT_LIMIT_B) <= ceiling
        assert ceiling < NULL_PARENT_LIMIT_A + NULL_PARENT_LIMIT_B

    def test_crr_null_parent_rows_keep_their_own_limits(
        self, crr_config: CalculationConfig
    ) -> None:
        out = classify_exposure_subtypes(_null_parent_frame(), crr_config).collect()
        assert out["exposure_class"].to_list() == [_RETAIL_OTHER, _RETAIL_OTHER]

    def test_b31_null_parent_rows_keep_their_own_limits(
        self, b31_config: CalculationConfig
    ) -> None:
        out = classify_exposure_subtypes(_null_parent_frame(), b31_config).collect()
        assert out["exposure_class"].to_list() == [_RETAIL_OTHER, _RETAIL_OTHER]
