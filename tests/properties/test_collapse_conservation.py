"""
Collapsing a split exposure's legs back to its parent must reproduce the input.

Pipeline position:
    ExposureSpec -> PipelineOrchestrator -> RealEstateSplitter (one exposure -> N legs)
        -> aggregate_to_key_grain (N legs -> one parent row) -> reconciliation

What this proves:
The real-estate splitter divides a parent's money carriers across its legs, and
``aggregate_to_key_grain`` puts them back together. A round trip that starts and
ends at the same grain must return the quantity it began with. Any carrier the
splitter ALLOCATES but the collapse does not SUM comes back holding one leg's
share, and the parent row silently understates.

Why the expected side is the INPUT and not the leg-level sum: the collapse helper
sums the legs, so "collapsed == sum of legs" is the same computation on both
sides and would pass no matter how wrong either was. The only expected value that
is independent of the code under test is the amount that went IN — the
``ExposureSpec`` literal (`.claude/LESSONS.md` B3).

Recorded finding, measured 2026-08-08: ``interest`` is allocated pro-rata
(``engine/re_split/carriers.py::_PRORATA_CARRIERS``) but is absent from
``data/schemas.py::ADDITIVE_OUTPUT_FIELDS``, so ``engine/aggregator/_collapse.py``
takes ``.first()`` for it. On a 40,000 interest parent split 769,230.77 /
230,769.23 by EAD share, the legs correctly carry 30,769.23 + 9,230.77 and the
collapsed parent reports 30,769.23 — understated by 23.1%. ``drawn_amount``
beside it is correct, because it IS additive; the two components of one gross
carrier disagree, which is what makes the defect hard to see by inspection.

This is a REGRESSION SURFACED BY A FIX, not a pre-existing bug: before the legs
were allocated, each inherited the parent's full interest and ``.first()``
returned the right answer by accident. Correcting the leg-level duplication
removed the accident.

The companion set-level contract is
``tests/contracts/test_collapse_additivity.py``, which catches the same class of
defect without running a pipeline.

References:
- CRR Art. 111 / Art. 166: gross exposure is drawn + interest
- CRR Art. 125 / 126, PS1/26 Art. 124F / 124H: the real-estate loan split
- `.claude/LESSONS.md` B3: a test written from the same sentence as the code proves nothing
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._collapse import aggregate_to_key_grain
from tests.properties.portfolios import ExposureSpec, run

#: Absolute money tolerance, matching the sibling property modules. Polars
#: group-by sums are not process-deterministic in the last ulps; half a penny is
#: far below any real defect (the understatement measured here is thousands).
MONEY_TOLERANCE = 0.005

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

#: Splitting exposures that carry BOTH components of the on-balance-sheet gross
#: carrier. Interest is what makes this portfolio different from ``RE_SPLIT`` in
#: the corpus: without it the interest limb of every assertion below is a
#: comparison of 0.0 against 0.0, which is the vacuous shape this suite exists to
#: avoid. The amounts are deliberately unequal so a leg's share is identifiable.
SPLIT_WITH_INTEREST: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="corporate",
        drawn=1_000_000.0,
        interest=40_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
    ),
    ExposureSpec(
        entity_type="corporate",
        drawn=2_000_000.0,
        interest=125_000.0,
        external_cqs=None,
        collateral_value=1_000_000.0,
        collateral_property_type="residential",
    ),
)

#: ``build_bundle`` assigns loan references positionally, so spec i is LN{i:03d}.
#: The splitter renames its legs (``LN000_sec`` / ``LN000_res``) and the collapse
#: coalesces them back to the parent reference.
_PARENT_REFS: tuple[str, ...] = tuple(f"LN{i:03d}" for i in range(len(SPLIT_WITH_INTEREST)))

#: The two components of the on-balance-sheet gross carrier, and the spec field
#: each one is built from. They are asserted TOGETHER rather than in separate
#: tests on purpose: what made this defect hard to see is that the two halves of
#: one quantity disagreed — ``drawn_amount`` correct because it is additive,
#: ``interest`` understated because it was not — so a test of either alone reads
#: as healthy. Checking them side by side makes the ASYMMETRY the thing that
#: fails, and the failure message prints the passing component next to the
#: failing one so the reader sees it immediately.
GROSS_COMPONENTS: dict[str, str] = {"drawn_amount": "drawn", "interest": "interest"}


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_collapsed_parent_reproduces_both_gross_components(regime: str) -> None:
    """Each parent's collapsed drawn AND interest equal the amounts that went in.

    ``reporting_gross_on_bs`` is ``drawn + interest`` (CRR Art. 111 / Art. 166).
    Both components are allocated across the split legs, so both must be summed
    back. One right and one wrong still produces a wrong gross exposure, and it
    is the harder failure to spot because the larger component looks correct.
    """
    # Arrange
    expected = {
        (ref, column): getattr(spec, field)
        for column, field in GROSS_COMPONENTS.items()
        for ref, spec in zip(_PARENT_REFS, SPLIT_WITH_INTEREST, strict=True)
    }
    assert all(expected.values()), (
        f"the portfolio carries a zero in {sorted(k for k, v in expected.items() if not v)}, "
        f"so those limbs would compare zero against zero and prove nothing"
    )

    # Act
    collapsed = aggregate_to_key_grain(run(SPLIT_WITH_INTEREST, regime).results).collect()
    published = {
        (row["exposure_reference"], column): row[column]
        for column in GROSS_COMPONENTS
        for row in collapsed.select("exposure_reference", *GROSS_COMPONENTS).to_dicts()
        if row["exposure_reference"] in _PARENT_REFS
    }

    # Assert
    verdict = {
        f"{ref}.{column}": (
            f"input {amount:,.2f} -> collapsed "
            f"{'MISSING' if published.get((ref, column)) is None else f'{published[(ref, column)]:,.2f}'}"
            + (
                ""
                if published.get((ref, column)) is not None
                and abs(published[(ref, column)] - amount) <= MONEY_TOLERANCE
                else "   <-- LOST"
            )
        )
        for (ref, column), amount in sorted(expected.items())
    }
    assert not any("LOST" in line for line in verdict.values()), (
        f"collapsing the real-estate split legs back to their parent lost money under "
        f"{regime}. Note which component survived and which did not — a carrier "
        f"allocated across legs must be in ADDITIVE_OUTPUT_FIELDS (data/schemas.py), or "
        f"_collapse.py takes .first() and keeps only one leg's share:\n  "
        + "\n  ".join(f"{key}: {line}" for key, line in verdict.items())
    )


def test_the_split_actually_fanned_out() -> None:
    """The portfolio really does split, so the round trip above has something to undo.

    Without this, a change that stopped the exposures splitting would leave one
    leg per parent, the collapse would become an identity function, and every
    assertion above would pass while testing nothing at all.
    """
    # Arrange
    results = run(SPLIT_WITH_INTEREST, "CRR").results.collect()

    # Act
    legs_per_parent = (
        results.filter(pl.col("split_parent_id").is_not_null())
        .group_by("split_parent_id")
        .len()
        .to_dicts()
    )

    # Assert
    assert legs_per_parent, "no exposure carries a split_parent_id — nothing split"
    assert all(row["len"] > 1 for row in legs_per_parent), (
        f"a split parent produced only one leg, so the collapse is an identity "
        f"function and the conservation assertions are vacuous: {legs_per_parent}"
    )
