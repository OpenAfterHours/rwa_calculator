"""Scaling gate for the P1.320 QRRE per-individual aggregate expression.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (``classify_exposure_subtypes``)
    -> CRMProcessor. This file drives the classify-stage transform directly on
    a synthetic hierarchy-exit-shaped frame, at two row counts.

Key responsibilities:
- Pin the ASYMPTOTIC SHAPE of ``classify_exposure_subtypes`` in row count, not
  a single wall-clock number, so a quadratic evaluation plan fails here rather
  than in a customer's overnight run.
- Keep the measured path live: assert the QRRE limb both fires and
  discriminates on the synthetic frame, so the timing is not measuring a dead
  expression (LESSONS B4 / C11).

The escape this closes
----------------------
Commit ``8ec7d302`` (P1.320) rewrote ``qrre_obligor_aggregate_limit_expr`` to
deduplicate a facility limit per ``(counterparty, parent_facility)`` before
summing it per obligor. The rewrite is REGULATORY CORRECT and its unit and
acceptance siblings (``test_p1_320_qrre_leg_multiplication.py`` and the
pipeline acceptance file) still pass unchanged. What it also did was nest two
window functions INSIDE the input of a third: the ``cum_sum().over([cp, fac])``
ordinal and the ``max().over([cp, fac])`` group limit both sit in the input of
``.sum().over(counterparty_reference)``. Polars evaluates a window's input
inside the OUTER group-by context, so the two inner windows re-run once per
obligor group. The classify stage went from 0.5 s to 5.6 s at 374k rows and
shipped that way through v0.3.27-v0.3.32. Every correctness gate in the estate
was green throughout: no test in the repo measures how the classifier scales,
and the benchmark suite is deselected from both the dev loop and the CI test
job.

Why a RATIO and not only an absolute budget
-------------------------------------------
An absolute threshold measures this box on this day. It has to be loose enough
to survive a loaded CI worker, which makes it blind to a regression that is
merely bad rather than catastrophic, and it silently loosens every time the
hardware gets faster. The defect here is a change of SHAPE - cost per row rises
with row count - and the shape is what a ratio across two sizes measures. The
absolute budget below is kept as a coarse second line, not as the guard.

Measured on the reference box, single-threaded (``POLARS_MAX_THREADS=1``, the
value ``tests/conftest.py`` pins for the whole session), best-of-3:

===============  =================  ==================
row count        nested (defect)    two-step (fixed)
===============  =================  ==================
100,000          0.32 - 0.43 s      0.108 - 0.114 s
400,000          4.60 - 5.67 s      0.502 - 0.559 s
ratio (4x rows)  13.5x - 14.3x      4.4x - 5.2x
===============  =================  ==================

so ``_MAX_SCALING_RATIO = 8.0`` sits close to the geometric midpoint, with
~1.5x headroom below it for the fixed form and ~1.7x above it for the defect.

Regime scope: ONE regime (CRR). The expression under test is regime-invariant -
the rulepack supplies only the scalar ceiling that the aggregate is COMPARED
against, and the aggregate itself is computed identically under both packs. The
LESSONS C7 rule (parametrise a regime-dependent basis over both regimes and
redden each separately) is about conservation identities over carriers whose
BASIS differs by regime; there is no such carrier here, and a second regime
would double a multi-second test to re-measure the same evaluation plan.

References:
- CRR Art. 154(4)(c) / PRA PS1/26 Art. 147(5A)(c): the per-individual
  aggregate nominal exposure limb whose expression is under test.
"""

from __future__ import annotations

import time
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classify.subtypes import classify_exposure_subtypes
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.p1_244.p1_244 import make_subtypes_frame

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 4)

#: The two row counts, exactly ``_SIZE_FACTOR`` apart.
_SMALL_ROWS = 100_000
_LARGE_ROWS = 400_000
_SIZE_FACTOR = _LARGE_ROWS // _SMALL_ROWS

#: Best-of-N per size. Best-of, not mean: a scheduler stall can only ever
#: inflate a sample, so the minimum is the least noisy estimator available.
_REPEATS = 3

#: Cost may grow at most this much for a ``_SIZE_FACTOR``x row increase. See the
#: measured table in the module docstring for the headroom on each side.
_MAX_SCALING_RATIO = 8.0

#: Coarse absolute backstop at the large size. Deliberately ~6x the measured
#: fixed-form cost so a loaded CI worker cannot redden it, while still sitting
#: below the defect's 4.6 s.
_LARGE_BUDGET_SECONDS = 3.0

#: Deterministic mixing constants for the synthetic frame. A pure integer hash
#: over the row index, evaluated in Polars - no RNG, so the frame is identical
#: on every platform, interpreter and library version.
_SEED = 20_260_905
_KNUTH = 2_654_435_761
_MERSENNE = 4_294_967_291

#: Cardinalities, chosen to mirror a real hierarchy exit: ~4 legs per obligor
#: (drawn loans + the synthetic ``_UNDRAWN`` headroom row + MOF waterfall
#: sub-rows all inherit one facility limit), ~3 facilities per obligor, a
#: minority of legs with no parent facility, and a thin null-obligor slice.
_LEGS_PER_OBLIGOR = 4
_FACILITIES_PER_OBLIGOR = 3
_NULL_PARENT_FACILITY_PCT = 15
_NULL_COUNTERPARTY_PCT = 1
_REVOLVING_PCT = 50
_SECURED_PCT = 20

#: The transform's input contract, READ FROM THE SHARED FIXTURE BUILDER rather
#: than typed here. ``make_subtypes_frame`` is the estate's canonical
#: ``classify_exposure_subtypes`` input frame; anchoring to it means a column
#: added to the transform's contract fails this file loudly at build time
#: instead of letting it drift into measuring a differently-shaped frame
#: (LESSONS B3 - a test written from the same sentence as the code proves
#: nothing).
_INPUT_SCHEMA = make_subtypes_frame(
    cp_entity_type="individual", cp_is_natural_person=True
).collect_schema()


# ---------------------------------------------------------------------------
# Synthetic frame builder
# ---------------------------------------------------------------------------


def _build_frame(n_rows: int) -> pl.LazyFrame:
    """Return a deterministic ``n_rows``-row ``classify_exposure_subtypes`` input.

    Every column is derived from a multiplicative hash of the row index, so the
    frame is a pure function of ``n_rows`` - repeatable across runs, workers
    and machines, with no dependence on any RNG implementation.

    The frame is materialised eagerly and re-wrapped as a ``LazyFrame`` so the
    timed region below measures the transform and its collect, never the
    construction of the source data.
    """
    n_obligors = max(1, n_rows // _LEGS_PER_OBLIGOR)
    row_index = pl.col("_i")
    mixed = ((row_index.cast(pl.UInt64) + _SEED) * _KNUTH) % _MERSENNE
    obligor_id = mixed % n_obligors
    facility_id = obligor_id * _FACILITIES_PER_OBLIGOR + (mixed // 7) % _FACILITIES_PER_OBLIGOR

    columns: dict[str, pl.Expr] = {
        "exposure_reference": pl.format("EXP{}", row_index),
        "counterparty_reference": pl.when((mixed // 11) % 100 < _NULL_COUNTERPARTY_PCT)
        .then(None)
        .otherwise(pl.format("CP{}", obligor_id)),
        "exposure_class": pl.lit(ExposureClass.RETAIL_OTHER.value),
        "exposure_class_irb": pl.lit(ExposureClass.RETAIL_OTHER.value),
        "qualifies_as_retail": pl.lit(True),
        "is_revolving": (mixed // 13) % 100 < _REVOLVING_PCT,
        "is_secured": (mixed // 17) % 100 < _SECURED_PCT,
        "risk_type": pl.lit("FR"),
        # Fully drawn: the Art. 147(5A)(b) cancellability limb is satisfied
        # trivially, isolating the (c) aggregate limb this file times.
        "undrawn_amount": pl.lit(0.0),
        # Limits spread across the QRRE ceiling so the aggregate DISCRIMINATES
        # rather than admitting or demoting the whole book.
        "facility_limit": (mixed % 190_000).cast(pl.Float64) + 1_000.0,
        "parent_facility_reference": pl.when((mixed // 19) % 100 < _NULL_PARENT_FACILITY_PCT)
        .then(None)
        .otherwise(pl.format("FAC{}", facility_id)),
        "is_mortgage": pl.lit(False),
        "is_adc": pl.lit(False),
        "is_hvcre": pl.lit(False),
        "cp_entity_type": pl.lit("individual"),
        "cp_is_natural_person": pl.lit(True),
        "cp_is_financial_sector_entity": pl.lit(False),
        "cp_total_assets": pl.lit(None, dtype=pl.Float64),
        "cp_apply_fi_scalar": pl.lit(False),
        "sme_size_metric_gbp": pl.lit(None, dtype=pl.Float64),
        "sme_size_source": pl.lit(None, dtype=pl.String),
    }

    missing = set(_INPUT_SCHEMA) - set(columns)
    extra = set(columns) - set(_INPUT_SCHEMA)
    assert not missing and not extra, (
        "the synthetic frame no longer matches the classify_exposure_subtypes "
        "input contract that tests/fixtures/p1_244 builds - a frame missing a "
        "column the transform reads would measure a different evaluation plan. "
        f"missing={sorted(missing)} extra={sorted(extra)}"
    )

    frame = (
        pl.LazyFrame({"_i": range(n_rows)})
        .with_columns([expr.alias(name) for name, expr in columns.items()])
        .select([pl.col(name).cast(dtype) for name, dtype in _INPUT_SCHEMA.items()])
    )
    return pl.LazyFrame(frame.collect())


# ---------------------------------------------------------------------------
# Fixtures — one measurement shared by every test in the file
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


@pytest.fixture(scope="module")
def measurements(crr_config: CalculationConfig) -> dict[int, tuple[float, pl.DataFrame]]:
    """``{row_count: (best_of_N_seconds, classified_frame)}`` for both sizes.

    Module-scoped and shared: ``--dist=loadfile`` pins the whole file to one
    xdist worker, so the two frames are built and timed exactly once.
    """
    # Arrange — the pack is resolved once, outside every timed region.
    pack = RulepackV0.from_config(crr_config).pack
    results: dict[int, tuple[float, pl.DataFrame]] = {}

    for n_rows in (_SMALL_ROWS, _LARGE_ROWS):
        source = _build_frame(n_rows)
        best = float("inf")
        classified: pl.DataFrame | None = None
        # Act — best-of-N wall clock over transform + collect.
        for _ in range(_REPEATS):
            started = time.perf_counter()
            classified = classify_exposure_subtypes(source, crr_config, pack=pack).collect()
            best = min(best, time.perf_counter() - started)
        assert classified is not None
        results[n_rows] = (best, classified)

    return results


# ---------------------------------------------------------------------------
# Adequacy — the frame can express the thing being timed
# ---------------------------------------------------------------------------


class TestTheMeasuredPathIsLive:
    """A timing is only evidence while the expression it times actually runs.

    Every assertion here would still hold on the pre-change engine: this class
    is the premise of the two timing tests, not a mover.
    """

    @pytest.mark.parametrize("n_rows", [_SMALL_ROWS, _LARGE_ROWS])
    def test_the_window_keys_are_non_degenerate(self, n_rows: int) -> None:
        """Multi-leg obligors, multi-facility obligors, and both null slices.

        A frame of singleton groups would make the deduplication window a
        no-op, and a frame with no null keys would skip the
        ``partition_by_nullable`` guards entirely - either way the timing
        would measure a shape the engine never meets.
        """
        # Arrange / Act
        frame = _build_frame(n_rows).collect()
        obligors = frame["counterparty_reference"].drop_nulls().n_unique()
        facilities = frame["parent_facility_reference"].drop_nulls().n_unique()
        null_obligors = frame["counterparty_reference"].null_count()
        null_facilities = frame["parent_facility_reference"].null_count()

        # Assert
        assert frame.height == n_rows
        assert frame.height / obligors >= 2.0, (
            f"only {frame.height / obligors:.2f} legs per obligor - the "
            "per-(obligor, facility) deduplication window has nothing to "
            "deduplicate and this file would time a no-op"
        )
        assert facilities > obligors, (
            "obligors hold at most one facility each, so the inner "
            "(obligor, facility) window degenerates to the outer obligor window"
        )
        assert 0 < null_obligors < frame.height // 2, (
            "the null-counterparty slice is empty or dominant; "
            f"got {null_obligors} of {frame.height}"
        )
        assert 0 < null_facilities < frame.height // 2, (
            "the null-parent-facility slice is empty or dominant; "
            f"got {null_facilities} of {frame.height}"
        )

    @pytest.mark.parametrize("n_rows", [_SMALL_ROWS, _LARGE_ROWS])
    def test_the_qrre_limb_fires_and_discriminates(
        self, n_rows: int, measurements: dict[int, tuple[float, pl.DataFrame]]
    ) -> None:
        """QRRE is populated AND is not the whole book, at both sizes.

        Asserts the negative space as well as the values: the class column is
        emitted, is non-null on every row, and every value it carries is a real
        ``ExposureClass`` member - anchored to the enum rather than to a
        hand-written list (LESSONS B2 / B3).
        """
        # Arrange / Act
        _, classified = measurements[n_rows]
        columns = classified.collect_schema().names()

        # Assert — presence first.
        for expected in ("exposure_class", "is_sme", "requires_fi_scalar", "is_hvcre"):
            assert expected in columns, (
                f"classify_exposure_subtypes did not emit {expected!r} - the "
                "transform's output contract changed and this file is timing "
                "something else"
            )
        assert classified["exposure_class"].null_count() == 0, (
            "exposure_class is null on some rows; a null and a legitimate "
            "class are different claims"
        )

        # Assert — the population is live on both sides of the ceiling.
        counts = dict(
            classified["exposure_class"].value_counts().iter_rows()  # (value, count)
        )
        assert set(counts) <= {member.value for member in ExposureClass}, (
            f"classify emitted a class outside the enum: "
            f"{sorted(set(counts) - {m.value for m in ExposureClass})}"
        )
        qrre = counts.get(ExposureClass.RETAIL_QRRE.value, 0)
        other = counts.get(ExposureClass.RETAIL_OTHER.value, 0)
        assert qrre > 0, (
            "no row classified as QRRE, so the Art. 154(4)(c) aggregate limb "
            "never admitted anything and the timing below measures a dead path"
        )
        assert other > 0, (
            "every row classified as QRRE, so the aggregate ceiling never "
            "bound and the timing below measures a degenerate path"
        )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_classifier_cost_scales_linearly_in_row_count(
    measurements: dict[int, tuple[float, pl.DataFrame]],
) -> None:
    """A 4x row increase costs materially less than 8x.

    This is the SHAPE assertion. A window nested inside another window's input
    re-runs once per outer group, which turns per-row cost into a function of
    row count; the measured penalty on the shipped form is 13.5x-14.3x for a
    4x row increase, against 4.4x-5.2x for the two-step form.
    """
    # Arrange
    small_seconds, _ = measurements[_SMALL_ROWS]
    large_seconds, _ = measurements[_LARGE_ROWS]

    # Act
    ratio = large_seconds / small_seconds

    # Assert
    assert ratio < _MAX_SCALING_RATIO, (
        f"classify_exposure_subtypes cost grew {ratio:.1f}x for a "
        f"{_SIZE_FACTOR}x row increase ({_SMALL_ROWS:,} rows: "
        f"{small_seconds:.3f}s -> {_LARGE_ROWS:,} rows: {large_seconds:.3f}s), "
        f"above the {_MAX_SCALING_RATIO:.1f}x ceiling. Cost per row is rising "
        "with row count. The known cause is a Polars window nested inside "
        "another window's input (a `.over()` in the input of a `.over()`), "
        "which Polars re-evaluates once per outer group - see "
        "engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr and "
        "arch_check check 21. Compute the inner result as its own column in a "
        "preceding with_columns and read it back with pl.col()."
    )


def test_classifier_stays_within_the_absolute_budget_at_scale(
    measurements: dict[int, tuple[float, pl.DataFrame]],
) -> None:
    """400k legs classify inside a coarse wall-clock budget.

    Second line only. The ratio above is the guard; this catches a regression
    that is uniformly slow at every size, which a ratio cannot see.
    """
    # Arrange / Act
    large_seconds, _ = measurements[_LARGE_ROWS]

    # Assert
    assert large_seconds < _LARGE_BUDGET_SECONDS, (
        f"classify_exposure_subtypes took {large_seconds:.3f}s on "
        f"{_LARGE_ROWS:,} rows, over the {_LARGE_BUDGET_SECONDS:.1f}s budget "
        f"(best of {_REPEATS}). The reference two-step form costs ~0.5s here."
    )
