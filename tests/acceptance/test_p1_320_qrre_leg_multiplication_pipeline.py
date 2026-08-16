"""P1.320 end-to-end: the capital consequence of counting each facility limit
once, and the invariants the classification fix must NOT disturb.

CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the aggregate nominal exposure
to a single individual. ``engine/stages/classify/subtypes.py`` sums
``facility_limit`` over every qualifying exposure LEG, so a facility split into a
drawn loan plus a synthetic ``_UNDRAWN`` headroom row contributes its limit
twice. The unit sibling
(``tests/unit/classifier/test_p1_320_qrre_leg_multiplication.py``) pins the
classification; this file pins what that reclassification is worth and what it
must leave alone.

Three groups of assertions:

1. **The moving number, Basel 3.1 only.** Leg (i)'s drawn leg at EAD 20,000,
   PD 3.0%, firm LGD 0.60, ``is_qrre_transactor=False``. Admitted to
   ``retail_qrre`` it takes the Art. 154(4) FLAT correlation R = 0.04 instead of
   the Art. 154(1) curve's R = 0.075492, and ``rwa_final`` falls from
   16,744.50 to **10,310.44** — RWA-REDUCING by 38.4%. Only Basel 3.1 asserts
   money: under CRR the two classes' PD and LGD floors are identical to each
   other, so the direction is unambiguous but no CRR figure was independently
   derived, and a number nobody stands behind is not an assertion.

2. **The EAD conservation identity, per regime, separately.** A classification
   fix can neither create nor destroy exposure at default. Stated over EAD
   rather than RWA precisely because EAD cannot be satisfied by an offsetting
   change of basis (LESSONS C7).

3. **The output floor does not fall.** Every ``engine/sa/`` transform is an
   indirect IRB consumer, because ``sa/calculator.py::calculate_unified`` runs
   the risk-weight pipeline unconditionally to supply the Basel 3.1 output
   floor's SA-equivalent RW (LESSONS D1). For an RWA-REDUCING change that is the
   load-bearing evidence: the SA-equivalent leg (``s_trea``) and the SA total
   (``sa_rwa_total``) must be byte-identical across the fix, so the floor cannot
   be lowered with the modelled charge.

Groups 2 and 3 are GREEN ON BOTH SIDES of the fix by construction. That is what
they are for — they are the guard rails on an RWA-reducing change, not its
demonstration. Group 1 is the failing assertion.

References:
- CRR Art. 154(1)/(4) / PS1/26 Art. 147(5A): retail IRB correlation and QRRE.
- PS1/26 Art. 154(4A) / Art. 465: the Basel 3.1 output floor.
- ``.claude/state/outputs/P1.320-scenario.md``: the design and its addendum.
- ``tests/fixtures/p1_320/p1_320.py``: the portfolio.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.p1_320.p1_320 import (
    CP_Q2,
    LN_Q2,
    Q2_DRAWN,
    VALUE_DATE,
    build_p1_320_raw_bundle,
)
from tests.fixtures.raw_bundle import seal_raw_table

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

_QRRE = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER = ExposureClass.RETAIL_OTHER.value

_REPORTING_DATE = date(2027, 1, 4)

# ---------------------------------------------------------------------------
# The A-IRB inputs for leg (i)'s drawn leg.
#
# The P1.320 fixture is a CLASSIFICATION fixture: every obligor is unrated, so
# the whole portfolio routes standardised and no correlation is ever evaluated.
# Adding one internal rating and one firm LGD estimate — here, in the test that
# needs them — is what puts the moving row on the A-IRB branch where the QRRE
# correlation lives. Nothing about the QRRE gates reads either field, and the
# classification outcome is identical with and without them (measured).
# ---------------------------------------------------------------------------

#: Obligor PD for CP_Q2. Above both regimes' retail PD floors, so no floor binds
#: and the correlation is the only thing that changes across the fix.
PD_Q2: float = 0.03

#: Firm own-estimate LGD for LN_Q2. Above the Basel 3.1 QRRE unsecured LGD floor
#: (which is HIGHER than the other-retail one), so the higher floor a newly
#: admitted QRRE row inherits is non-binding and cannot mask the correlation
#: move. At a firm LGD low enough for that floor to bind the sign of this change
#: flips — deliberately out of scope here.
LGD_Q2: float = 0.60

#: The model_id ``create_full_irb_model_permissions`` grants every class.
_MODEL_ID: str = "TEST_FULL_IRB"

_RATINGS_SCHEMA: dict[str, pl.DataType] = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,
    "pd": pl.Float64,
    "model_id": pl.String,
    "rating_date": pl.Date,
}

# ---------------------------------------------------------------------------
# Expected values.
#
# Art. 154(1):  K = LGD x [ N( (1-R)^-0.5 G(PD) + (R/(1-R))^0.5 G(0.999) ) - PD ]
#               RWA = K x 12.5 x EAD
# Art. 154(4):  QRRE takes a FLAT R = 0.04 in place of the Art. 154(1) curve.
#
# Both figures below were derived from those formulae with the stdlib
# ``statistics.NormalDist``, i.e. NOT with the ``polars-normal-stats`` the engine
# evaluates them with, so the expected value and the engine do not share a
# source. The same derivation reproduces the PRE-fix ``retail_other`` basis to
# 16,744.496286 against an engine-measured 16,744.496287 — agreement to 6e-11
# relative — which is the evidence that the derivation method is sound before it
# is trusted for the post-fix number.
# ---------------------------------------------------------------------------

#: Art. 154(4) QRRE correlation — flat, no PD term.
QRRE_CORRELATION: float = 0.04

#: K for the moving leg once it is QRRE.
QRRE_K: float = 0.0412417577

#: ``rwa_final`` for the moving leg once it is QRRE.
QRRE_RWA: float = 10_310.44

#: What the same leg is worth in ``retail_other`` — the pre-fix basis. Recorded
#: for the reader and used only to prove the two are far apart; the assertions
#: are against ``QRRE_RWA``.
RETAIL_OTHER_RWA: float = 16_744.50

#: Total EAD of the whole portfolio, per regime, measured pre-fix. The CRR and
#: Basel 3.1 totals differ because the unconditionally-cancellable CCF differs
#: (CRR 0%, Basel 3.1 10%) — a ``risk_type`` function, not a class function, so
#: neither total may move when rows change class.
TOTAL_EAD_CRR: float = 170_000.0
TOTAL_EAD_B31: float = 186_000.0

#: The Basel 3.1 output-floor SA legs on the A-IRB run, measured pre-fix. Both
#: must be UNCHANGED by the fix (LESSONS D1): ``s_trea`` is the SA-equivalent of
#: the IRB-routed row and ``sa_rwa_total`` the SA-routed remainder.
S_TREA_B31: float = 15_000.0
SA_RWA_TOTAL_B31: float = 124_500.0


# =============================================================================
# Bundles and runs
# =============================================================================


def _airb_bundle() -> RawDataBundle:
    """The P1.320 bundle with leg (i)'s drawn leg put on the A-IRB branch.

    Re-sealed through ``seal_raw_table`` so the frames carry the same loader
    edge brands a production load produces — a hand-built frame slipped past the
    seal would bypass the input contract the engine is entitled to rely on.
    """
    raw = build_p1_320_raw_bundle()
    ratings = pl.LazyFrame(
        [
            {
                "rating_reference": "P1320-RTG-" + CP_Q2,
                "counterparty_reference": CP_Q2,
                "rating_type": "internal",
                "pd": PD_Q2,
                "model_id": _MODEL_ID,
                "rating_date": VALUE_DATE,
            }
        ],
        schema=_RATINGS_SCHEMA,
    )
    is_moving_leg = pl.col("loan_reference") == LN_Q2
    loans = raw.loans.with_columns(
        pl.when(is_moving_leg).then(pl.lit(LGD_Q2)).otherwise(pl.col("lgd")).alias("lgd"),
        # Art. 154(3)/(4) retail is A-IRB-only; the own-estimate LGD is admitted
        # only with the collateral-data attestation beside it.
        pl.when(is_moving_leg)
        .then(pl.lit(True))
        .otherwise(pl.col("has_sufficient_collateral_data"))
        .alias("has_sufficient_collateral_data"),
    )
    return replace(
        raw,
        loans=seal_raw_table(loans, "loans"),
        ratings=seal_raw_table(ratings, "ratings"),
        model_permissions=seal_raw_table(create_full_irb_model_permissions(), "model_permissions"),
    )


def _crr_config(*, irb: bool = False) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB if irb else PermissionMode.STANDARDISED,
    )


def _b31_config(*, irb: bool = False) -> CalculationConfig:
    """Basel 3.1 with the Art. 123A(1)(b)(ii) granularity limb disabled.

    P5.15's 0.2%-of-portfolio limb re-classes every retail row in a book this
    thin to CORPORATE, erasing the population under test before the QRRE gate is
    reached. ``tests/fixtures/p1_244`` uses the same documented isolation switch.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB if irb else PermissionMode.STANDARDISED,
        enforce_retail_granularity=False,
    )


@pytest.fixture(scope="module")
def b31_airb_result():
    """Full pipeline over the A-IRB bundle under Basel 3.1."""
    return PipelineOrchestrator().run_with_data(_airb_bundle(), _b31_config(irb=True))


@pytest.fixture(scope="module")
def b31_airb_rows(b31_airb_result) -> pl.DataFrame:
    return b31_airb_result.results.collect()


@pytest.fixture(scope="module")
def crr_rows() -> pl.DataFrame:
    """Full pipeline over the unmodified (standardised) bundle under CRR."""
    result = PipelineOrchestrator().run_with_data(build_p1_320_raw_bundle(), _crr_config())
    return result.results.collect()


@pytest.fixture(scope="module")
def b31_rows() -> pl.DataFrame:
    """Full pipeline over the unmodified (standardised) bundle under Basel 3.1."""
    result = PipelineOrchestrator().run_with_data(build_p1_320_raw_bundle(), _b31_config())
    return result.results.collect()


def _row(df: pl.DataFrame, ref: str) -> dict[str, object]:
    match = df.filter(pl.col("exposure_reference") == ref)
    assert len(match) == 1, f"expected exactly 1 row for {ref!r}, got {len(match)}"
    return match.row(0, named=True)


# =============================================================================
# 1. The moving number — Basel 3.1 A-IRB. FAILS PRE-FIX.
# =============================================================================


class TestB31MovingLegCapital:
    """Leg (i)'s drawn leg, Basel 3.1 A-IRB: EAD 20,000, PD 3.0%, LGD 0.60.

    Pre-fix the obligor's aggregate nominal is double-counted (2 x 60,000) so
    the row sits in ``retail_other`` on the Art. 154(1) correlation curve and is
    worth 16,744.50. Counting the facility once admits it to ``retail_qrre``,
    whose Art. 154(4) correlation is a flat 0.04, and it is worth 10,310.44.
    """

    def test_b31_moving_leg_is_qrre(self, b31_airb_rows: pl.DataFrame) -> None:
        assert _row(b31_airb_rows, LN_Q2)["exposure_class"] == _QRRE

    def test_b31_moving_leg_takes_the_flat_qrre_correlation(
        self, b31_airb_rows: pl.DataFrame
    ) -> None:
        """Art. 154(4): R = 0.04 flat, replacing the Art. 154(1) PD-dependent
        curve (which gives 0.075492 at PD 3%)."""
        assert _row(b31_airb_rows, LN_Q2)["correlation"] == pytest.approx(
            QRRE_CORRELATION, rel=1e-9
        )

    def test_b31_moving_leg_capital_requirement(self, b31_airb_rows: pl.DataFrame) -> None:
        assert _row(b31_airb_rows, LN_Q2)["k"] == pytest.approx(QRRE_K, rel=1e-6)

    def test_b31_moving_leg_rwa(self, b31_airb_rows: pl.DataFrame) -> None:
        assert _row(b31_airb_rows, LN_Q2)["rwa_final"] == pytest.approx(QRRE_RWA, rel=1e-6)

    def test_b31_moving_leg_rwa_is_not_the_pre_fix_basis(self, b31_airb_rows: pl.DataFrame) -> None:
        """Anti-confound. The two bases are 38.4% apart, so an assertion that
        merely landed "somewhere plausible" would not distinguish them."""
        rwa = _row(b31_airb_rows, LN_Q2)["rwa_final"]
        assert rwa != pytest.approx(RETAIL_OTHER_RWA, rel=1e-3)

    def test_b31_moving_leg_inputs_are_the_designed_ones(self, b31_airb_rows: pl.DataFrame) -> None:
        """Green on both sides — it pins the inputs the expected value was
        derived from, so a failure of the value assertions above can only be the
        correlation. Both floors are non-binding, which is why the class change
        shows up entirely in R."""
        row = _row(b31_airb_rows, LN_Q2)
        assert row["approach"] == "advanced_irb"
        assert row["ead_final"] == pytest.approx(Q2_DRAWN, rel=1e-9)
        assert row["pd_floored"] == pytest.approx(PD_Q2, rel=1e-9)
        assert row["lgd_floored"] == pytest.approx(LGD_Q2, rel=1e-9)


# =============================================================================
# 2. EAD conservation — per regime, SEPARATELY. Green on both sides.
# =============================================================================


class TestEADConservationAcrossTheReclassification:
    """RWA moves; EAD does not.

    Stated over EAD rather than RWA on purpose (LESSONS C7): an RWA identity can
    be satisfied by an offsetting change of basis, whereas a classification fix
    that created or destroyed EAD would have no way to hide. Asserted once per
    regime because the two totals genuinely differ — the unconditionally-
    cancellable CCF is 0% under CRR and 10% under Basel 3.1 — and a single
    parametrised red would prove only one of them.
    """

    def test_crr_every_row_is_in_one_of_the_two_retail_classes(
        self, crr_rows: pl.DataFrame
    ) -> None:
        assert set(crr_rows["exposure_class"]) <= {_QRRE, _RETAIL_OTHER}

    def test_b31_every_row_is_in_one_of_the_two_retail_classes(
        self, b31_rows: pl.DataFrame
    ) -> None:
        assert set(b31_rows["exposure_class"]) <= {_QRRE, _RETAIL_OTHER}

    def test_crr_class_breakdown_sums_to_the_portfolio_total(self, crr_rows: pl.DataFrame) -> None:
        """The breakdown must foot to its parent — a breakdown that silently
        drops rows still looks plausible (LESSONS E2)."""
        qrre = crr_rows.filter(pl.col("exposure_class") == _QRRE)["ead_final"].sum()
        other = crr_rows.filter(pl.col("exposure_class") == _RETAIL_OTHER)["ead_final"].sum()
        assert qrre + other == pytest.approx(crr_rows["ead_final"].sum(), rel=1e-12)

    def test_b31_class_breakdown_sums_to_the_portfolio_total(self, b31_rows: pl.DataFrame) -> None:
        """The breakdown must foot to its parent — a breakdown that silently
        drops rows still looks plausible (LESSONS E2)."""
        qrre = b31_rows.filter(pl.col("exposure_class") == _QRRE)["ead_final"].sum()
        other = b31_rows.filter(pl.col("exposure_class") == _RETAIL_OTHER)["ead_final"].sum()
        assert qrre + other == pytest.approx(b31_rows["ead_final"].sum(), rel=1e-12)

    def test_crr_total_ead_is_unchanged_by_the_reclassification(
        self, crr_rows: pl.DataFrame
    ) -> None:
        """Absolute, not relative to a baseline: the value is the pre-fix
        measurement and must survive the fix untouched."""
        assert crr_rows["ead_final"].sum() == pytest.approx(TOTAL_EAD_CRR, rel=1e-9)

    def test_b31_total_ead_is_unchanged_by_the_reclassification(
        self, b31_rows: pl.DataFrame
    ) -> None:
        """Absolute, not relative to a baseline: the value is the pre-fix
        measurement and must survive the fix untouched."""
        assert b31_rows["ead_final"].sum() == pytest.approx(TOTAL_EAD_B31, rel=1e-9)

    def test_crr_no_row_carries_a_null_ead(self, crr_rows: pl.DataFrame) -> None:
        """A null and a legitimate zero are different claims (LESSONS B4)."""
        assert crr_rows["ead_final"].null_count() == 0

    def test_b31_no_row_carries_a_null_ead(self, b31_rows: pl.DataFrame) -> None:
        """A null and a legitimate zero are different claims (LESSONS B4)."""
        assert b31_rows["ead_final"].null_count() == 0


# =============================================================================
# 3. The Basel 3.1 output floor is not lowered. Green on both sides.
# =============================================================================


class TestOutputFloorSAEquivalentDoesNotMove:
    """The direction evidence for an RWA-REDUCING change.

    ``engine/sa/calculator.py::calculate_unified`` runs the SA risk-weight
    pipeline unconditionally, so every IRB row also carries an SA-equivalent RW
    that feeds the Basel 3.1 output floor (LESSONS D1). Were that SA-equivalent
    to move with the exposure class, this change would lower the floor as well as
    the modelled charge — the unshippable shape. It does not: the SA retail
    ladder gates on ``uc.str.contains("RETAIL")``, which both classes satisfy,
    and the 45% transactor limb gates on ``is_qrre_transactor`` (pinned False
    throughout this fixture), not on the class.

    Both figures are pre-fix measurements and must be byte-identical after it.
    """

    def test_b31_sa_equivalent_of_the_irb_leg_is_unchanged(self, b31_airb_result) -> None:
        assert b31_airb_result.output_floor_summary.s_trea == pytest.approx(S_TREA_B31, rel=1e-9)

    def test_b31_sa_routed_total_is_unchanged(self, b31_airb_result) -> None:
        assert b31_airb_result.output_floor_summary.sa_rwa_total == pytest.approx(
            SA_RWA_TOTAL_B31, rel=1e-9
        )

    def test_b31_portfolio_floor_does_not_bind_on_either_side(self, b31_airb_result) -> None:
        """If the floor started binding, ``rwa_final`` would stop being the
        modelled charge and the value assertions above would be measuring
        something else."""
        assert b31_airb_result.output_floor_summary.portfolio_floor_binding is False

    def test_b31_modelled_rwa_is_published_unfloored(self, b31_airb_rows: pl.DataFrame) -> None:
        """``rwa_final`` is already post-floor; with no shortfall it must equal
        the modelled ``rwa`` on every IRB row."""
        irb = b31_airb_rows.filter(pl.col("rwa").is_not_null())
        assert not irb.is_empty(), "no IRB-routed row — the A-IRB wiring is inert"
        assert (irb["rwa_final"] - irb["rwa"]).abs().max() == pytest.approx(0.0, abs=1e-9)
