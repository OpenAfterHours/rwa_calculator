"""Unit tests for P1.355: the QRRE per-individual aggregate is capped at the
multi-option facility's umbrella limit.

CRR Art. 154(4)(c) ("the maximum exposure to a single individual in the
sub-portfolio is EUR 100 000 or less") and PS1/26 Art. 147(5A)(c) ("the largest
aggregate nominal exposure to a single individual ... is GBP 90,000 or less")
cap the aggregate nominal exposure to one individual. Under a multi-option
facility (MOF) the hierarchy stage keys a drawn leg on its IMMEDIATE sub-facility
(carrying the sub-limit) and every waterfall / residual leg on the ROOT
(carrying the root's limit). P1.320 counts each of those limits once — but
nothing then caps the limits counted under one root by the root's own limit, so
a sub-limit is charged on top of the umbrella that already contains it, and two
sub-limits under a fully drawn umbrella are summed past it.

The approved reading (owner sign-off on the P1.355 decision brief): per
(individual, umbrella) the nominal is ``min(umbrella limit, sum of the distinct
limits counted under it)`` — never the largest single sub-limit. Today's
conservative result is KEPT where the umbrella has no limit, where a limit inside
the umbrella is null, where the individual has drawn more under the umbrella than
its limit (an overdrawn or zero-limit root), and where a sibling sub-line fails
the QRRE gate (P1.320 leg (vi), unchanged).

Direction: a capped aggregate is never above today's, so rows only ever move
``retail_other -> retail_qrre``. That lowers IRB RWA below the correlation
crossover (PD ~ 7.3%) and raises it above, and under Basel 3.1 the higher QRRE
PD / LGD floors can bind; the acceptance sibling measures all three. The SA risk
weight does not depend on the class, so S-TREA does not move.

Every assertion is made separately per regime (LESSONS C7). The ceiling is read
from the pack, never typed (LESSONS A4 / B3).

References:
- CRR Art. 154(4)(c) / PRA PS1/26 Art. 147(5A)(c).
- ``src/rwa_calc/engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``.
- ``tests/fixtures/p1_355/p1_355.py``: the fixture and its leg inventory.
- ``tests/unit/classifier/test_p1_320_qrre_leg_multiplication.py``: P1.320's
  leg (v), the fourth mover, re-pointed there.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classify import ExposureClassifier
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.p1_355.p1_355 import (
    ABOVE_ROOT_LIMIT,
    ABOVE_SUB_LIMIT,
    BULLET_ROOT_LIMIT,
    BULLET_SUB_LIMIT,
    CONT_DRAWN,
    CONT_ROOT_LIMIT,
    CONT_SUB_LIMIT,
    CP_SHARED_A,
    CP_SHARED_B,
    CP_XOWN_ROOT,
    CP_XOWN_SUB,
    CT_OFB,
    CT_ONB,
    DEEP_LEAF_LIMIT,
    DEEP_ROOT_LIMIT,
    DUP_ROOT_LIMIT,
    DUP_SUB_LIMIT,
    EUR_GBP_RATE,
    EXP_BULLET_SUBA_UNDRAWN,
    EXP_BULLET_SUBB_UNDRAWN,
    EXP_DEEP_LEAF_UNDRAWN,
    EXP_DEEP_MID_UNDRAWN,
    EXP_DEEP_RESIDUAL,
    EXP_NULLSUB_RESIDUAL,
    EXP_RESID_RESIDUAL,
    EXP_RESID_SUB_UNDRAWN,
    EXP_SHARED_OWN_A_UNDRAWN,
    EXP_SHARED_OWN_B_UNDRAWN,
    EXP_XOWN_RESIDUAL,
    EXP_XOWN_SUB_UNDRAWN,
    FAC_ABOVE_ROOT,
    FAC_BULLET_ROOT,
    FAC_DEEP_ROOT,
    FAC_NORATE_ROOT,
    FAC_NRL_ROOT,
    FAC_NULLFULL_ROOT,
    FAC_NULLPART_ROOT,
    FAC_NULLSUB_ROOT,
    FAC_OVER_ROOT,
    FAC_RESID_ROOT,
    FAC_SHARED_ROOT,
    FAC_XOWN_ROOT,
    FAC_ZERO_ROOT,
    FX_ROOT_LIMIT,
    FX_SUB_LIMIT,
    FXEUR_DRAWN,
    FXMIX_DRAWN,
    FXOK_DRAWN,
    LN_ABOVE_A,
    LN_ABOVE_B,
    LN_BULLET,
    LN_DEEP,
    LN_DUP_A,
    LN_DUP_B,
    LN_FXEUR_A,
    LN_FXEUR_B,
    LN_FXMIX_A,
    LN_FXMIX_B,
    LN_FXOK_A,
    LN_FXOK_B,
    LN_NORATE_A,
    LN_NORATE_B,
    LN_NRL_A,
    LN_NRL_B,
    LN_NULLFULL_A,
    LN_NULLFULL_B,
    LN_NULLPART_A,
    LN_NULLPART_B,
    LN_NULLSUB,
    LN_OFB,
    LN_ONB,
    LN_OVER_A,
    LN_OVER_B,
    LN_RESID,
    LN_SHARED_A,
    LN_SHARED_B,
    LN_SHARED_OWN_A,
    LN_SHARED_OWN_B,
    LN_XOWN,
    LN_ZERO_A,
    LN_ZERO_B,
    NORATE_DRAWN,
    NORATE_ROOT_LIMIT,
    NORATE_SUB_LIMIT,
    NRL_ROOT_LIMIT,
    NRL_SUB_LIMIT,
    NULLFULL_SUB_LIMIT,
    NULLPART_SUB_LIMIT,
    NULLSUB_ROOT_LIMIT,
    OVER_DRAWN,
    OVER_ROOT_LIMIT,
    OVER_SUB_LIMIT,
    RESID_ROOT_LIMIT,
    RESID_SUB_LIMIT,
    SHARED_DRAWN,
    SHARED_OWN_LIMIT,
    SHARED_ROOT_LIMIT,
    SHARED_SUB_LIMIT,
    XOWN_ROOT_LIMIT,
    XOWN_SUB_LIMIT,
    ZERO_DRAWN,
    ZERO_ROOT_LIMIT,
    ZERO_SUB_LIMIT,
    build_p1_355_duplicate_bundle,
    build_p1_355_guard_bundle,
    build_p1_355_raw_bundle,
    build_p1_355_shared_bundle,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.contracts.bundles import RawDataBundle

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value
_BOTH_QRRE = (_QRRE, _QRRE)
_BOTH_OTHER = (_RETAIL_OTHER, _RETAIL_OTHER)

_REPORTING_DATE = date(2027, 1, 4)

#: The NULLPART waterfall legs. The fixture keeps no constant for them because
#: no other module needs them; spelled from the hierarchy's naming rule.
_NULLPART_SUBA_UNDRAWN = FAC_NULLPART_ROOT + "_UNDRAWN_P1355_FAC_NULLPART_SUBA"
_NULLPART_SUBB_UNDRAWN = FAC_NULLPART_ROOT + "_UNDRAWN_P1355_FAC_NULLPART_SUBB"

#: Every exposure the hierarchy stage emits for the bundle, with the umbrella
#: (root) each one sits under. Asserted as a SET so a leg that silently stops
#: being emitted is a failure, not an invisible absence (LESSONS B4).
_LEG_ROOTS: dict[str, str] = {
    LN_NRL_A: FAC_NRL_ROOT,
    LN_NRL_B: FAC_NRL_ROOT,
    LN_DEEP: FAC_DEEP_ROOT,
    EXP_DEEP_MID_UNDRAWN: FAC_DEEP_ROOT,
    EXP_DEEP_LEAF_UNDRAWN: FAC_DEEP_ROOT,
    EXP_DEEP_RESIDUAL: FAC_DEEP_ROOT,
    LN_XOWN: FAC_XOWN_ROOT,
    EXP_XOWN_SUB_UNDRAWN: FAC_XOWN_ROOT,
    EXP_XOWN_RESIDUAL: FAC_XOWN_ROOT,
    LN_ABOVE_A: FAC_ABOVE_ROOT,
    LN_ABOVE_B: FAC_ABOVE_ROOT,
    LN_NULLFULL_A: FAC_NULLFULL_ROOT,
    LN_NULLFULL_B: FAC_NULLFULL_ROOT,
    LN_NULLPART_A: FAC_NULLPART_ROOT,
    LN_NULLPART_B: FAC_NULLPART_ROOT,
    _NULLPART_SUBA_UNDRAWN: FAC_NULLPART_ROOT,
    _NULLPART_SUBB_UNDRAWN: FAC_NULLPART_ROOT,
    LN_RESID: FAC_RESID_ROOT,
    EXP_RESID_SUB_UNDRAWN: FAC_RESID_ROOT,
    EXP_RESID_RESIDUAL: FAC_RESID_ROOT,
    LN_BULLET: FAC_BULLET_ROOT,
    EXP_BULLET_SUBA_UNDRAWN: FAC_BULLET_ROOT,
    EXP_BULLET_SUBB_UNDRAWN: FAC_BULLET_ROOT,
    LN_NULLSUB: FAC_NULLSUB_ROOT,
    EXP_NULLSUB_RESIDUAL: FAC_NULLSUB_ROOT,
    LN_OVER_A: FAC_OVER_ROOT,
    LN_OVER_B: FAC_OVER_ROOT,
    LN_ZERO_A: FAC_ZERO_ROOT,
    LN_ZERO_B: FAC_ZERO_ROOT,
}

#: Each umbrella's own limit, as the fixture supplies it (None = no limit).
_ROOT_LIMITS: dict[str, float | None] = {
    FAC_NRL_ROOT: NRL_ROOT_LIMIT,
    FAC_DEEP_ROOT: DEEP_ROOT_LIMIT,
    FAC_XOWN_ROOT: XOWN_ROOT_LIMIT,
    FAC_ABOVE_ROOT: ABOVE_ROOT_LIMIT,
    FAC_NULLFULL_ROOT: None,
    FAC_NULLPART_ROOT: None,
    FAC_RESID_ROOT: RESID_ROOT_LIMIT,
    FAC_BULLET_ROOT: BULLET_ROOT_LIMIT,
    FAC_NULLSUB_ROOT: NULLSUB_ROOT_LIMIT,
    FAC_OVER_ROOT: OVER_ROOT_LIMIT,
    FAC_ZERO_ROOT: ZERO_ROOT_LIMIT,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


@pytest.fixture(scope="module")
def b31_config() -> CalculationConfig:
    """Basel 3.1 with the optional 0.2% granularity test off (the default since RE-04).

    On a book this thin the BCBS CRE20.66 granularity test would fail every
    retail row before the (c) aggregate limb under test is reached — the same
    isolation switch ``tests/fixtures/p1_244`` and the P1.320 tests use.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, enforce_retail_granularity=False
    )


def _classify(
    config: CalculationConfig, build: Callable[[], RawDataBundle] = build_p1_355_raw_bundle
) -> pl.DataFrame:
    """Run HierarchyResolver -> ExposureClassifier over a P1.355 bundle.

    The whole classified frame, not a projection: the class assertions must not
    depend on the carrier column ``TestRootFacilityLimitIsCarriedOnEveryLeg``
    asserts, or a missing carrier would error every test instead of failing one.
    """
    resolved = HierarchyResolver().resolve(build(), config)
    return ExposureClassifier().classify(resolved, config).all_exposures.collect()


@pytest.fixture(scope="module")
def crr_classified(crr_config: CalculationConfig) -> pl.DataFrame:
    return _classify(crr_config)


@pytest.fixture(scope="module")
def b31_classified(b31_config: CalculationConfig) -> pl.DataFrame:
    return _classify(b31_config)


@pytest.fixture(scope="module")
def crr_guard(crr_config: CalculationConfig) -> pl.DataFrame:
    return _classify(crr_config, build_p1_355_guard_bundle)


@pytest.fixture(scope="module")
def b31_guard(b31_config: CalculationConfig) -> pl.DataFrame:
    return _classify(b31_config, build_p1_355_guard_bundle)


@pytest.fixture(scope="module")
def crr_shared(crr_config: CalculationConfig) -> pl.DataFrame:
    return _classify(crr_config, build_p1_355_shared_bundle)


@pytest.fixture(scope="module")
def b31_shared(b31_config: CalculationConfig) -> pl.DataFrame:
    return _classify(b31_config, build_p1_355_shared_bundle)


@pytest.fixture(scope="module")
def crr_duplicate(crr_config: CalculationConfig) -> pl.DataFrame:
    return _classify(crr_config, build_p1_355_duplicate_bundle)


@pytest.fixture(scope="module")
def b31_duplicate(b31_config: CalculationConfig) -> pl.DataFrame:
    return _classify(b31_config, build_p1_355_duplicate_bundle)


def _classes(df: pl.DataFrame, ref: str) -> tuple[str | None, str | None]:
    """Return ``(exposure_class, exposure_class_irb)`` for one exposure."""
    row = df.filter(pl.col("exposure_reference") == ref)
    assert len(row) == 1, f"expected exactly 1 row for {ref!r}, got {len(row)}"
    return row["exposure_class"].item(), row["exposure_class_irb"].item()


def _ceiling(config: CalculationConfig) -> float:
    """The regime's QRRE aggregate-nominal ceiling, READ FROM THE PACK."""
    pack = RulepackV0.from_config(config).pack
    return float(regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate))


# =============================================================================
# Adequacy — the fixture's arithmetic straddles the PACK ceiling in each regime.
# Green on both sides; the premise of every moving and control assertion.
# =============================================================================


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestFixtureStraddlesThePackCeiling:
    """Each mover is over the ceiling as HEAD counts it and within it capped;
    each max-trap control is within it under ``max`` and over it capped. A leg
    on the wrong side of either regime's ceiling would make that regime's
    assertion below measure nothing (LESSONS C7 / C11)."""

    def test_no_root_leg_mover_straddles(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert NRL_ROOT_LIMIT <= ceiling < 2 * NRL_SUB_LIMIT

    def test_second_individual_mover_straddles(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert XOWN_ROOT_LIMIT <= ceiling < XOWN_SUB_LIMIT + XOWN_ROOT_LIMIT

    def test_max_trap_controls_would_be_admitted_by_max(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """Under ``max`` these three are within the ceiling; correctly counted
        they are above it. Without that gap they could not catch the trap."""
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert ABOVE_SUB_LIMIT <= ceiling < ABOVE_ROOT_LIMIT
        assert NULLFULL_SUB_LIMIT <= ceiling < 2 * NULLFULL_SUB_LIMIT
        assert RESID_SUB_LIMIT <= ceiling < RESID_ROOT_LIMIT

    def test_conservative_null_controls_would_be_admitted_by_a_bolder_rule(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """A sum-of-sub-limits rule for a null umbrella (NULLPART), or capping a
        null sub-limit at its umbrella (NULLSUB), would admit these — which is
        what makes keeping them out an observable choice."""
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert ceiling >= 2 * NULLPART_SUB_LIMIT
        assert ceiling >= NULLSUB_ROOT_LIMIT

    def test_overdrawn_controls_would_be_admitted_by_an_unguarded_cap(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """Each overdrawn umbrella is within the ceiling at its own limit and
        over it at its sub-limits, and drawn past its own limit — so an
        unguarded cap would admit it and the guard is observable. OVER's drawn
        balance alone is over the ceiling: the capped figure would understate
        the individual's own drawings."""
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert OVER_ROOT_LIMIT <= ceiling < 2 * OVER_SUB_LIMIT
        assert 2 * OVER_DRAWN > OVER_ROOT_LIMIT
        assert ceiling < 2 * OVER_DRAWN
        assert ZERO_ROOT_LIMIT <= ceiling < 2 * ZERO_SUB_LIMIT
        assert 2 * ZERO_DRAWN > ZERO_ROOT_LIMIT

    def test_bullet_example_is_within_the_ceiling_either_way(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert ceiling >= BULLET_ROOT_LIMIT + BULLET_SUB_LIMIT


def test_crr_three_level_mover_straddles_only_the_crr_ceiling(
    crr_config: CalculationConfig, b31_config: CalculationConfig
) -> None:
    """HEAD counts the leaf's limit beside the root's: over the CRR ceiling,
    within the B31 one. Capped at the root it is within both."""
    crr_ceiling, b31_ceiling = _ceiling(crr_config), _ceiling(b31_config)
    assert DEEP_ROOT_LIMIT <= crr_ceiling < DEEP_LEAF_LIMIT + DEEP_ROOT_LIMIT
    assert b31_ceiling >= DEEP_LEAF_LIMIT + DEEP_ROOT_LIMIT


# =============================================================================
# The umbrella carrier — the hierarchy puts each leg's root limit on the row.
# FAILS PRE-FIX (the column does not exist).
# =============================================================================


class TestRootFacilityLimitIsCarriedOnEveryLeg:
    """``root_facility_limit`` is the limit of the leg's root facility, on drawn
    legs (keyed on a sub) and on waterfall / residual legs (keyed on the root)
    alike, and null exactly where the umbrella carries no limit."""

    def test_crr_every_designed_leg_is_emitted(self, crr_classified: pl.DataFrame) -> None:
        assert set(crr_classified["exposure_reference"]) == set(_LEG_ROOTS)

    def test_b31_every_designed_leg_is_emitted(self, b31_classified: pl.DataFrame) -> None:
        assert set(b31_classified["exposure_reference"]) == set(_LEG_ROOTS)

    def test_crr_each_leg_carries_its_roots_limit(self, crr_classified: pl.DataFrame) -> None:
        for ref, root in _LEG_ROOTS.items():
            row = crr_classified.filter(pl.col("exposure_reference") == ref)
            assert row["root_facility_reference"].item() == root, ref
            assert row["root_facility_limit"].item() == _ROOT_LIMITS[root], ref

    def test_b31_each_leg_carries_its_roots_limit(self, b31_classified: pl.DataFrame) -> None:
        for ref, root in _LEG_ROOTS.items():
            row = b31_classified.filter(pl.col("exposure_reference") == ref)
            assert row["root_facility_reference"].item() == root, ref
            assert row["root_facility_limit"].item() == _ROOT_LIMITS[root], ref


# =============================================================================
# MOVERS — retail_other at HEAD, retail_qrre once capped. FAIL PRE-FIX.
# =============================================================================


class TestNoRootLegMover:
    """(NRL) root 80,000, subs 60,000 + 60,000, 40,000 drawn under each. The
    umbrella is fully drawn, so only the two sub-keyed loans exist: HEAD sums the
    sub-limits to 120,000; capped at the umbrella it is 80,000."""

    def test_crr_first_loan_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_NRL_A) == _BOTH_QRRE

    def test_b31_first_loan_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_NRL_A) == _BOTH_QRRE

    def test_crr_second_loan_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_NRL_B) == _BOTH_QRRE

    def test_b31_second_loan_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_NRL_B) == _BOTH_QRRE


class TestThreeLevelHierarchy:
    """(DEEP) root 70,000 -> mid 40,000 -> leaf 20,000, 10,000 drawn under the
    leaf. The loan keys on the leaf (20,000); the mid's and the leaf's waterfall
    legs and the residual key on the root (70,000). HEAD 90,000: retail_other
    under CRR, retail_qrre under B31 ("or less"). Capped: 70,000, QRRE in both —
    a CRR mover and a B31 control. Intermediate umbrellas (the mid) are NOT
    applied as caps; only the root is, which can only over-count."""

    @pytest.mark.parametrize(
        "ref", [LN_DEEP, EXP_DEEP_MID_UNDRAWN, EXP_DEEP_LEAF_UNDRAWN, EXP_DEEP_RESIDUAL]
    )
    def test_crr_every_leg_becomes_qrre(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_QRRE

    @pytest.mark.parametrize(
        "ref", [LN_DEEP, EXP_DEEP_MID_UNDRAWN, EXP_DEEP_LEAF_UNDRAWN, EXP_DEEP_RESIDUAL]
    )
    def test_b31_every_leg_stays_qrre(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_QRRE


class TestSubOwnedByASecondIndividual:
    """(XOWN) root 70,000 owned by CP_XOWN_ROOT; sub 25,000 owned by CP_XOWN_SUB,
    who draws 10,000 under it. CP_XOWN_SUB holds the loan (25,000) and the sub's
    waterfall leg (the root's 70,000): HEAD 95,000, capped 70,000. CP_XOWN_ROOT's
    residual is 70,000 either way.

    This class pins the cap reaching a sub-line owner who does not own the
    umbrella. It does NOT pin that the cap is applied per individual: a cap
    pooled across the umbrella's owners puts 70,000 on one of them and 0 on the
    other, and both stay within the ceiling. ``TestTwoIndividualsUnderOneUmbrella``
    is the detector for that."""

    def test_crr_sub_owners_loan_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, LN_XOWN) == _BOTH_QRRE

    def test_b31_sub_owners_loan_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, LN_XOWN) == _BOTH_QRRE

    def test_crr_sub_owners_waterfall_leg_becomes_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, EXP_XOWN_SUB_UNDRAWN) == _BOTH_QRRE

    def test_b31_sub_owners_waterfall_leg_becomes_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, EXP_XOWN_SUB_UNDRAWN) == _BOTH_QRRE

    def test_crr_legs_sit_with_the_designed_owners(self, crr_classified: pl.DataFrame) -> None:
        """Adequacy: the move is only a cross-owner case if the waterfall leg is
        the SUB owner's and the residual the ROOT owner's."""
        owner = dict(
            crr_classified.select("exposure_reference", "counterparty_reference").iter_rows()
        )
        assert owner[LN_XOWN] == CP_XOWN_SUB
        assert owner[EXP_XOWN_SUB_UNDRAWN] == CP_XOWN_SUB
        assert owner[EXP_XOWN_RESIDUAL] == CP_XOWN_ROOT

    def test_crr_root_owners_residual_stays_qrre(self, crr_classified: pl.DataFrame) -> None:
        assert _classes(crr_classified, EXP_XOWN_RESIDUAL) == _BOTH_QRRE

    def test_b31_root_owners_residual_stays_qrre(self, b31_classified: pl.DataFrame) -> None:
        assert _classes(b31_classified, EXP_XOWN_RESIDUAL) == _BOTH_QRRE


# =============================================================================
# The per-INDIVIDUAL half of the cap's key (``build_p1_355_shared_bundle``).
# Controls: green on both sides, red under a cap keyed on the umbrella alone.
# =============================================================================

#: Every leg of the SHARED bundle, with the individual who holds it.
_SHARED_OWNERS: dict[str, str] = {
    LN_SHARED_A: CP_SHARED_A,
    LN_SHARED_OWN_A: CP_SHARED_A,
    EXP_SHARED_OWN_A_UNDRAWN: CP_SHARED_A,
    LN_SHARED_B: CP_SHARED_B,
    LN_SHARED_OWN_B: CP_SHARED_B,
    EXP_SHARED_OWN_B_UNDRAWN: CP_SHARED_B,
}


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_shared_umbrella_fixture_straddles(
    regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
) -> None:
    """Adequacy: each individual's correct figure — their own sub-limit (within
    the umbrella) plus their standalone revolver — is over the ceiling, while
    the standalone revolver alone, which is all a pooled cap leaves the second
    owner, is within it. The umbrella is fully drawn and within its own limit,
    so the pooled cap would apply and bind (80,000 < 120,000)."""
    ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
    correct = min(SHARED_ROOT_LIMIT, SHARED_SUB_LIMIT) + SHARED_OWN_LIMIT
    assert SHARED_OWN_LIMIT <= ceiling < correct
    assert 2 * SHARED_DRAWN <= SHARED_ROOT_LIMIT < 2 * SHARED_SUB_LIMIT


class TestTwoIndividualsUnderOneUmbrella:
    """(SHARED) root 80,000 (CP_SHARED_A); sub A 60,000 (CP_SHARED_A) and sub B
    60,000 (CP_SHARED_B), 40,000 drawn under each; each individual also holds a
    standalone 50,000 revolver, 10,000 drawn. Art. 147(5A)(c) / 154(4)(c) cap
    the exposure to A SINGLE INDIVIDUAL, so the umbrella caps each individual's
    figure under it separately: 60,000 + 50,000 = 110,000 each — retail_other
    in both regimes, at HEAD and after the fix.

    Catches a cap keyed on the umbrella alone (the headroom-netting grain): it
    pools both owners' sub-limits, caps the pool at 80,000, credits it to one
    owner and 0 to the other, whose figure falls to 50,000 — every leg of that
    individual wrongly QRRE. Which owner is credited depends on row order, so
    every leg of BOTH is asserted."""

    def test_crr_every_designed_leg_is_emitted(self, crr_shared: pl.DataFrame) -> None:
        assert set(crr_shared["exposure_reference"]) == set(_SHARED_OWNERS)

    def test_b31_every_designed_leg_is_emitted(self, b31_shared: pl.DataFrame) -> None:
        assert set(b31_shared["exposure_reference"]) == set(_SHARED_OWNERS)

    def test_crr_legs_sit_with_the_designed_individuals_and_umbrella(
        self, crr_shared: pl.DataFrame
    ) -> None:
        """Adequacy: both owners' sub-keyed loans sit under the one root."""
        owner = dict(crr_shared.select("exposure_reference", "counterparty_reference").iter_rows())
        assert owner == _SHARED_OWNERS
        root = dict(crr_shared.select("exposure_reference", "root_facility_reference").iter_rows())
        assert root[LN_SHARED_A] == root[LN_SHARED_B] == FAC_SHARED_ROOT

    @pytest.mark.parametrize("ref", list(_SHARED_OWNERS))
    def test_crr_every_leg_of_both_individuals_stays_retail_other(
        self, crr_shared: pl.DataFrame, ref: str
    ) -> None:
        assert _classes(crr_shared, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", list(_SHARED_OWNERS))
    def test_b31_every_leg_of_both_individuals_stays_retail_other(
        self, b31_shared: pl.DataFrame, ref: str
    ) -> None:
        assert _classes(b31_shared, ref) == _BOTH_OTHER


# =============================================================================
# CONTROLS — the same class before and after. Green on both sides by design:
# each one reddens a specific WRONG fix, named in its docstring.
# =============================================================================


class TestUmbrellaAboveTheCeilingStaysRetailOther:
    """(ABOVE) root 100,000, subs 60,000 + 60,000, 50,000 drawn under each. HEAD
    120,000; capped 100,000 — still above both ceilings. Catches the MAX TRAP:
    the largest single sub-limit (60,000) would wrongly admit it."""

    @pytest.mark.parametrize("ref", [LN_ABOVE_A, LN_ABOVE_B])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_ABOVE_A, LN_ABOVE_B])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestNullUmbrellaFullyDrawnKeepsTheSubLimitSum:
    """(NULLFULL) root limit null, subs 50,000 + 50,000 fully drawn: only the two
    sub-keyed loans, 100,000 on both sides. A null umbrella caps nothing.
    Catches the max trap on a null root (50,000 would wrongly admit it)."""

    @pytest.mark.parametrize("ref", [LN_NULLFULL_A, LN_NULLFULL_B])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_NULLFULL_A, LN_NULLFULL_B])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestNullUmbrellaPartiallyDrawnStaysUnbounded:
    """(NULLPART) root limit null, subs 30,000 + 30,000, 10,000 drawn under each.
    The root-keyed waterfall legs carry the umbrella's null limit, which the
    engine reads as unbounded: retail_other on both sides.

    The owner's choice, pinned: a "sum of the sub-limits" rule for a null
    umbrella would make it 60,000 and admit it — an RWA-reducing move on a
    null-data path that the sign-off did not cover."""

    @pytest.mark.parametrize(
        "ref", [LN_NULLPART_A, LN_NULLPART_B, _NULLPART_SUBA_UNDRAWN, _NULLPART_SUBB_UNDRAWN]
    )
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize(
        "ref", [LN_NULLPART_A, LN_NULLPART_B, _NULLPART_SUBA_UNDRAWN, _NULLPART_SUBB_UNDRAWN]
    )
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestUmbrellaAboveTheCeilingWithAResidualLeg:
    """(RESID) root 100,000, sub 25,000, 10,000 drawn under the sub. Legs: loan
    25,000, waterfall 100,000, residual 100,000. HEAD 125,000; capped 100,000:
    retail_other. Catches the misreading that counts "what is drawn directly
    against the root" as a drawn amount instead of the root's limit: that gives
    min(100,000, 25,000) and wrongly admits it — a misreading leg (v) cannot
    see, because there it gives 25,000, which is QRRE anyway."""

    @pytest.mark.parametrize("ref", [LN_RESID, EXP_RESID_SUB_UNDRAWN, EXP_RESID_RESIDUAL])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_RESID, EXP_RESID_SUB_UNDRAWN, EXP_RESID_RESIDUAL])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestBulletExampleStaysQrre:
    """(BULLET) the plan bullet's own example: root 50,000, subs 30,000 + 30,000,
    10,000 drawn under SUBA. HEAD 80,000, capped 50,000 — QRRE both sides. The
    live-cell control (LESSONS B5): it keeps the QRRE population non-empty
    pre-fix, so "the fix admitted the movers" is distinguishable from "the fix
    moved everything"."""

    @pytest.mark.parametrize("ref", [LN_BULLET, EXP_BULLET_SUBA_UNDRAWN, EXP_BULLET_SUBB_UNDRAWN])
    def test_crr_stays_qrre(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_QRRE

    @pytest.mark.parametrize("ref", [LN_BULLET, EXP_BULLET_SUBA_UNDRAWN, EXP_BULLET_SUBB_UNDRAWN])
    def test_b31_stays_qrre(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_QRRE


class TestNullSubLimitUnderALimitedUmbrellaStaysUnbounded:
    """(NULLSUB) root 50,000, sub limit null, 10,000 drawn under the sub. Legs:
    the loan (null -> unbounded) and the residual (50,000). retail_other on both
    sides: a null limit inside the umbrella keeps today's unbounded result
    rather than being capped at the umbrella.

    A choice, pinned so it is visible and easy to reverse: capping it would give
    50,000 and admit it — like NULLPART, an RWA-reducing move on a null-data
    path outside the sign-off."""

    @pytest.mark.parametrize("ref", [LN_NULLSUB, EXP_NULLSUB_RESIDUAL])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_NULLSUB, EXP_NULLSUB_RESIDUAL])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestOverdrawnUmbrellaIsNotACap:
    """(OVER) root 50,000, subs 60,000 + 60,000, 55,000 drawn under each: the
    individual has drawn 110,000 under an umbrella whose limit is 50,000. That
    limit bounds nothing, so it is not applied: 120,000, retail_other on both
    sides. An unguarded cap gives 50,000 — below the individual's own drawn
    balance, which alone is over both ceilings — and wrongly admits it."""

    @pytest.mark.parametrize("ref", [LN_OVER_A, LN_OVER_B])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_OVER_A, LN_OVER_B])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


class TestZeroLimitUmbrellaIsNotACap:
    """(ZERO) root limit 0, subs 60,000 + 60,000, 40,000 drawn under each. The
    same guard: 80,000 drawn under a zero limit, so no cap — 120,000,
    retail_other on both sides. Capping at 0 would admit it; a feed that writes
    "no limit" as 0 is the plausible source."""

    @pytest.mark.parametrize("ref", [LN_ZERO_A, LN_ZERO_B])
    def test_crr_stays_retail_other(self, crr_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_classified, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_ZERO_A, LN_ZERO_B])
    def test_b31_stays_retail_other(self, b31_classified: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_classified, ref) == _BOTH_OTHER


# =============================================================================
# The overdrawn guard — what it counts as drawn, and in which currency
# (``build_p1_355_guard_bundle``). Every leg but FXOK is a control: the same
# class at HEAD and after the fix, red under a specific WRONG guard. FXOK is a
# mover. Each umbrella is fully drawn, so its two sub-limits sum past the
# ceiling and only the cap could admit it.
# =============================================================================


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestGuardFixtureStraddles:
    """Adequacy: each guard control is admitted by its wrong guard and refused
    by the right one, so a green control means the guard read it correctly."""

    def test_contingent_umbrellas_are_overdrawn_only_by_both_drawings(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert CONT_ROOT_LIMIT <= ceiling < 2 * CONT_SUB_LIMIT
        assert CONT_DRAWN <= CONT_ROOT_LIMIT < 2 * CONT_DRAWN

    def test_eur_umbrellas_straddle_the_ceiling(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        """Whether the classifier reads the EUR limits as stated or converted."""
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert FX_ROOT_LIMIT <= ceiling < 2 * FX_SUB_LIMIT * EUR_GBP_RATE

    def test_fx_drawings_sit_on_the_designed_side_of_the_root(self, regime: str) -> None:
        """FXEUR is over the root in EUR, within it in GBP; FXMIX is over it in
        EUR, within it as stated in GBP and converted the wrong way; FXOK is
        within it."""
        assert 2 * FXEUR_DRAWN > FX_ROOT_LIMIT >= 2 * FXEUR_DRAWN * EUR_GBP_RATE
        assert 2 * FXMIX_DRAWN / EUR_GBP_RATE > FX_ROOT_LIMIT >= 2 * FXMIX_DRAWN
        assert FX_ROOT_LIMIT >= 2 * FXMIX_DRAWN * EUR_GBP_RATE
        assert 2 * FXOK_DRAWN <= FX_ROOT_LIMIT

    def test_unconvertible_drawings_would_pass_a_guard_that_skipped_them(
        self, regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
    ) -> None:
        ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
        assert NORATE_ROOT_LIMIT <= ceiling < 2 * NORATE_SUB_LIMIT
        assert 2 * NORATE_DRAWN <= NORATE_ROOT_LIMIT


class TestOnBalanceSheetContingentDrawsAgainstTheUmbrella:
    """(ONB) a 30,000 loan and a 30,000 ON-balance-sheet contingent under a
    50,000 umbrella: 60,000 drawn, so no cap — retail_other on both sides. The
    unified frame carries an ONB contingent's amount in ``drawn_amount``
    (``nominal_amount`` 0): a guard reading a contingent's nominal only sees
    30,000 and wrongly caps."""

    @pytest.mark.parametrize("ref", [LN_ONB, CT_ONB])
    def test_crr_stays_retail_other(self, crr_guard: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_ONB, CT_ONB])
    def test_b31_stays_retail_other(self, b31_guard: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_guard, ref) == _BOTH_OTHER

    def test_the_contingent_is_on_balance_sheet(self, crr_guard: pl.DataFrame) -> None:
        """Adequacy: the amount sits where an ONB contingent's does."""
        row = crr_guard.filter(pl.col("exposure_reference") == CT_ONB)
        assert (row["drawn_amount"].item(), row["nominal_amount"].item()) == (CONT_DRAWN, 0.0)


class TestOffBalanceSheetContingentDrawsAgainstTheUmbrella:
    """(OFB) the same with an OFF-balance-sheet contingent, whose amount is in
    ``nominal_amount``: a guard reading only ``drawn_amount`` wrongly caps."""

    @pytest.mark.parametrize("ref", [LN_OFB, CT_OFB])
    def test_crr_stays_retail_other(self, crr_guard: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_OFB, CT_OFB])
    def test_b31_stays_retail_other(self, b31_guard: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_guard, ref) == _BOTH_OTHER

    def test_the_contingent_is_off_balance_sheet(self, crr_guard: pl.DataFrame) -> None:
        row = crr_guard.filter(pl.col("exposure_reference") == CT_OFB)
        assert (row["drawn_amount"].item(), row["nominal_amount"].item()) == (0.0, CONT_DRAWN)


class TestOverdrawnGuardComparesInTheRootsCurrency:
    """The root's limit is never FX-converted; ``drawn_amount`` is converted to
    the reporting currency before classification. The guard must compare the
    two in the ROOT's currency, as headroom netting does."""

    @pytest.mark.parametrize("ref", [LN_FXEUR_A, LN_FXEUR_B])
    def test_crr_eur_book_overdrawn_in_eur_stays_retail_other(
        self, crr_guard: pl.DataFrame, ref: str
    ) -> None:
        """(FXEUR) EUR 84,000 drawn under a EUR 80,000 root; GBP 73,349 in the
        reporting currency, which would wrongly pass the guard."""
        assert _classes(crr_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_FXEUR_A, LN_FXEUR_B])
    def test_b31_eur_book_overdrawn_in_eur_stays_retail_other(
        self, b31_guard: pl.DataFrame, ref: str
    ) -> None:
        assert _classes(b31_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_FXMIX_A, LN_FXMIX_B])
    def test_crr_gbp_drawings_over_a_eur_root_stay_retail_other(
        self, crr_guard: pl.DataFrame, ref: str
    ) -> None:
        """(FXMIX) GBP 72,000 drawn under a EUR 80,000 root is EUR 82,455."""
        assert _classes(crr_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_FXMIX_A, LN_FXMIX_B])
    def test_b31_gbp_drawings_over_a_eur_root_stay_retail_other(
        self, b31_guard: pl.DataFrame, ref: str
    ) -> None:
        assert _classes(b31_guard, ref) == _BOTH_OTHER

    @pytest.mark.parametrize("ref", [LN_FXOK_A, LN_FXOK_B])
    def test_crr_eur_book_within_its_root_becomes_qrre(
        self, crr_guard: pl.DataFrame, ref: str
    ) -> None:
        """(FXOK) MOVER: EUR 80,000 drawn under the EUR 80,000 root, so the cap
        applies — the guard is not merely refusing every non-GBP umbrella."""
        assert _classes(crr_guard, ref) == _BOTH_QRRE

    @pytest.mark.parametrize("ref", [LN_FXOK_A, LN_FXOK_B])
    def test_b31_eur_book_within_its_root_becomes_qrre(
        self, b31_guard: pl.DataFrame, ref: str
    ) -> None:
        assert _classes(b31_guard, ref) == _BOTH_QRRE


class TestUnconvertibleDrawingIsNotACap:
    """(NORATE) USD 40,000 drawn under each GBP sub and no USD rate. The
    hierarchy leaves the drawings out of the root's netting, so the root emits
    waterfall legs at its 80,000 too: 200,000, retail_other on both sides. The
    guard cannot measure the drawings, so it declines to cap; a guard that
    skipped them would find nothing drawn, cap at 80,000 and admit it."""

    @staticmethod
    def _legs(df: pl.DataFrame) -> list[str]:
        refs = df.filter(pl.col("root_facility_reference") == FAC_NORATE_ROOT)
        return sorted(refs["exposure_reference"])

    def test_the_umbrella_emits_waterfall_legs_beside_the_loans(
        self, crr_guard: pl.DataFrame
    ) -> None:
        """Adequacy: four legs, two of them root-keyed headroom."""
        legs = self._legs(crr_guard)
        assert len(legs) == 4
        assert {LN_NORATE_A, LN_NORATE_B} < set(legs)

    def test_crr_every_leg_stays_retail_other(self, crr_guard: pl.DataFrame) -> None:
        for ref in self._legs(crr_guard):
            assert _classes(crr_guard, ref) == _BOTH_OTHER, ref

    def test_b31_every_leg_stays_retail_other(self, b31_guard: pl.DataFrame) -> None:
        for ref in self._legs(b31_guard):
            assert _classes(b31_guard, ref) == _BOTH_OTHER, ref


# =============================================================================
# A duplicated root reference (DQ004) — ``build_p1_355_duplicate_bundle``.
# =============================================================================


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_duplicated_root_fixture_straddles(
    regime: str, crr_config: CalculationConfig, b31_config: CalculationConfig
) -> None:
    ceiling = _ceiling(crr_config if regime == "crr" else b31_config)
    assert DUP_ROOT_LIMIT <= ceiling < 2 * DUP_SUB_LIMIT


class TestDuplicatedRootStillCaps:
    """(DUP) the NRL mover under a root the facilities table lists twice: one
    row per loan, the root's limit counted once, so the 80,000 drawn is within
    the 80,000 root and the cap applies — QRRE. A join that copied the legs
    doubles the drawings past the root (no cap) and doubles their EAD."""

    @pytest.mark.parametrize("ref", [LN_DUP_A, LN_DUP_B])
    def test_crr_becomes_qrre(self, crr_duplicate: pl.DataFrame, ref: str) -> None:
        assert _classes(crr_duplicate, ref) == _BOTH_QRRE

    @pytest.mark.parametrize("ref", [LN_DUP_A, LN_DUP_B])
    def test_b31_becomes_qrre(self, b31_duplicate: pl.DataFrame, ref: str) -> None:
        assert _classes(b31_duplicate, ref) == _BOTH_QRRE


# =============================================================================
# Negative space (LESSONS B4 / B2). Green on both sides.
# =============================================================================


class TestClassificationNegativeSpace:
    def test_crr_classes_are_non_null_enum_members(self, crr_classified: pl.DataFrame) -> None:
        members = {m.value for m in ExposureClass}
        assert crr_classified["exposure_class"].null_count() == 0
        assert set(crr_classified["exposure_class"]) <= members

    def test_b31_classes_are_non_null_enum_members(self, b31_classified: pl.DataFrame) -> None:
        members = {m.value for m in ExposureClass}
        assert b31_classified["exposure_class"].null_count() == 0
        assert set(b31_classified["exposure_class"]) <= members

    def test_crr_irb_class_stays_synced(self, crr_classified: pl.DataFrame) -> None:
        mismatched = crr_classified.filter(pl.col("exposure_class") != pl.col("exposure_class_irb"))
        assert mismatched.is_empty(), mismatched

    def test_b31_irb_class_stays_synced(self, b31_classified: pl.DataFrame) -> None:
        mismatched = b31_classified.filter(pl.col("exposure_class") != pl.col("exposure_class_irb"))
        assert mismatched.is_empty(), mismatched

    def test_crr_both_populations_are_non_empty(self, crr_classified: pl.DataFrame) -> None:
        """A fix that moved the whole book could not be told from a correct one."""
        classes = set(crr_classified["exposure_class"])
        assert {_QRRE, _RETAIL_OTHER} <= classes

    def test_b31_both_populations_are_non_empty(self, b31_classified: pl.DataFrame) -> None:
        """A fix that moved the whole book could not be told from a correct one."""
        classes = set(b31_classified["exposure_class"])
        assert {_QRRE, _RETAIL_OTHER} <= classes
