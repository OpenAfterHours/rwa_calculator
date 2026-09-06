"""
Pipeline collect-budget ratchet (test-suite runtime proposal, Lever 2 item 4).

Pipeline position:
    (no pipeline stage - counts the Polars materialisations that ONE full
    ``PipelineOrchestrator.run_with_data`` makes on a one-row bundle, per regime)

Key responsibilities:
- Make the per-run FIXED cost of the pipeline visible as three integers - the
  number of ``pl.LazyFrame.collect``, ``pl.LazyFrame.collect_schema`` and
  ``pl.collect_all`` calls a run makes - and bank them, so the cost cannot
  drift up silently.
- Ratchet BOTH ways. A count above the banked value fails as a regression. A
  count below it ALSO fails, with a message asking the author to bank the
  improvement deliberately. The supervisory-validation register and the
  reporting-coverage ratchet work the same way, for the reason
  ``.claude/LESSONS.md`` E1 records: a ratchet nobody re-banks stops being a
  floor, because the next regression has the whole unbanked gain as headroom.
- Prove the measured run is live (a real ledger row with a positive RWA)
  before trusting its counts, so a broken run that materialises nothing
  cannot pass as an "improvement" (LESSONS B4 / C11).

Why a one-row bundle
--------------------
On one row every collect is overhead: there is no data-proportional work to
hide behind, so the three counts ARE the fixed cost. They are a property of the
evaluation plan, not of the data or the machine - measured identical across
cold and warm runs in one process and under ``POLARS_MAX_THREADS=1``, the value
``tests/conftest.py`` pins for the whole session - which is what makes them
bankable to the exact integer where a wall-clock figure could not be.

The lesson this graduates
-------------------------
``docs/plans/test-suite-runtime-proposal.md`` Lever 2 measured the fixed cost
of a run at ~0.4 s single-row and found it dominated by roughly a hundred
collects and well over a hundred schema resolutions, most of them re-resolving
a schema a previous line had already resolved. Nothing measured that number,
so it drifted up with every stage that added a guard or a recorder, and the
dev loop paid it ~1,350 times per run of the suite. This file is the
executable form the learning loop asks for (LESSONS, graduation ledger): the
count is now a gate, and Lever 2 items 1-3 land against it by re-banking
LOWER values.

How the counting works, and what it does and does not see
----------------------------------------------------------
The three callables are replaced on the CLASS / MODULE object through
``monkeypatch`` for the duration of the run, so every call site in
``src/rwa_calc`` is intercepted regardless of how it spells the call, and the
originals are restored at teardown. The counter is installed AFTER the bundle
and config are built and read IMMEDIATELY after ``run_with_data`` returns, so
the numbers cover the run and nothing else. ``collect_schema`` is counted at
the Python method, so a Polars property that calls ``self.collect_schema()``
internally (``LazyFrame.columns``, ``LazyFrame.schema``) counts once each time
it is read - which is correct, because that is a schema resolution the run
paid for. What it cannot see is materialisation that never crosses a Python
call - a ``collect_all`` counts once however many plans it carries.

References:
- docs/plans/test-suite-runtime-proposal.md, Lever 2 (items 1-4)
- tests/unit/classifier/test_p1_320_qrre_aggregate_scaling.py (the sibling
  scaling guard from PR #488, same graduate-the-measurement shape)
- .claude/LESSONS.md B4, C11, C12 (proof the patch applied), E1 (two-way)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from tests.properties.portfolios import ExposureSpec, build_bundle, config_for

from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from collections.abc import Iterator

    from rwa_calc.contracts.errors import CalculationError

# ---------------------------------------------------------------------------
# Constants - the banked budget
# ---------------------------------------------------------------------------

_NOTE = """\
How to re-bank these numbers
----------------------------
Never type a value you did not measure. Run

    uv run pytest tests/contracts/test_pipeline_collect_budget.py -n 0 -q

and copy the OBSERVED counts out of the failure message into ``_BANKED`` for the
regime that moved - the message prints them in exactly that shape. Then say in
the commit message which change moved them and why. A count that went DOWN is an
improvement and must still be banked here: the ratchet fails on it deliberately,
so the gain becomes the new ceiling instead of headroom for the next regression.
A count that went UP is a regression in the pipeline's fixed cost - a new
collect, a new schema resolution, a recorder filtering the plan instead of the
materialised edge - and the right response is to remove it, not to bank it.

The counts are per full ``run_with_data`` on the one-row bundle
``build_bundle((ExposureSpec(),))`` under ``config_for(<regime>)``, and are
invariant in warm/cold state and in row count.
"""

#: The three call kinds counted, keyed as the failure message prints them.
_METRICS: tuple[str, ...] = ("collect", "collect_schema", "collect_all")

#: The banked per-run fixed cost, per regime. See ``_NOTE`` before editing.
#: 2026-09-06 (Lever 2 items 1 and 3): ``collect`` 98 -> 85 / 96 -> 83 as the
#: CRM recorders moved onto materialised frames; ``collect_all`` +2 in each
#: regime because 28 single collects were folded into two batches (the
#: input-domain gate's 26 -> 1, the short-term-lookup + DQ015 count 2 -> 1).
_BANKED: dict[str, dict[str, int]] = {
    "CRR": {"collect": 85, "collect_schema": 136, "collect_all": 8},
    "B31": {"collect": 83, "collect_schema": 135, "collect_all": 9},
}

_REGIMES: tuple[str, ...] = tuple(_BANKED)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Measurement:
    """One regime's run: the counts it made, and the evidence it was a real run."""

    regime: str
    observed: dict[str, int]
    ledger: pl.DataFrame
    errors: tuple[CalculationError, ...]


def _install_counters(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the three materialising callables with counting wrappers.

    Returns the live counter dict. Asserts each patch actually landed
    (LESSONS C12, mechanism 2: a patch that silently no-ops reads as a
    dramatic improvement here, which is the opposite of what happened).
    """
    counts: dict[str, int] = dict.fromkeys(_METRICS, 0)
    original_collect = pl.LazyFrame.collect
    original_collect_schema = pl.LazyFrame.collect_schema
    original_collect_all = pl.collect_all

    def counting_collect(self: pl.LazyFrame, *args: Any, **kwargs: Any) -> Any:
        counts["collect"] += 1
        return original_collect(self, *args, **kwargs)

    def counting_collect_schema(self: pl.LazyFrame, *args: Any, **kwargs: Any) -> Any:
        counts["collect_schema"] += 1
        return original_collect_schema(self, *args, **kwargs)

    def counting_collect_all(*args: Any, **kwargs: Any) -> Any:
        counts["collect_all"] += 1
        return original_collect_all(*args, **kwargs)

    monkeypatch.setattr(pl.LazyFrame, "collect", counting_collect)
    monkeypatch.setattr(pl.LazyFrame, "collect_schema", counting_collect_schema)
    monkeypatch.setattr(pl, "collect_all", counting_collect_all)

    assert pl.LazyFrame.collect is counting_collect, "collect patch did not apply"
    assert pl.LazyFrame.collect_schema is counting_collect_schema, (
        "collect_schema patch did not apply"
    )
    assert pl.collect_all is counting_collect_all, "collect_all patch did not apply"
    return counts


@pytest.fixture(scope="module", params=_REGIMES)
def measurement(request: pytest.FixtureRequest) -> Iterator[_Measurement]:
    """Run the one-row bundle once per regime under the counters.

    Module-scoped so the three tests below share one run per regime; the
    counters live inside a ``MonkeyPatch.context`` because a function-scoped
    ``monkeypatch`` cannot serve a module-scoped fixture.
    """
    regime: str = request.param
    # Arrange - everything that is NOT the run happens before the counters go in.
    bundle = build_bundle((ExposureSpec(),))
    config = config_for(regime)

    with pytest.MonkeyPatch.context() as monkeypatch:
        counts = _install_counters(monkeypatch)
        # Act - the run, and a snapshot the instant it returns.
        result = PipelineOrchestrator().run_with_data(bundle, config)
        observed = dict(counts)

    # Read outside the patched region so the evidence collect is not counted.
    ledger = result.results.collect()
    yield _Measurement(regime=regime, observed=observed, ledger=ledger, errors=tuple(result.errors))


# ---------------------------------------------------------------------------
# Adequacy - the counted run was a real run
# ---------------------------------------------------------------------------


def test_the_counted_run_produced_a_live_ledger(measurement: _Measurement) -> None:
    """The run under the counters produced a row with a positive, finite RWA.

    Without this, a run that failed early would materialise almost nothing
    and read as a large improvement. The one-row corporate bundle carries a
    1,000,000 term loan, so its RWA must be a positive finite number under both
    regimes; and no edge contract may have been violated, since a violated edge
    short-circuits the stages after it (LESSONS D3).
    """
    # Arrange
    ledger = measurement.ledger
    violations = [e for e in measurement.errors if "contract violated" in e.message]

    # Act
    rwa = ledger["rwa_final"].to_list()

    # Assert
    assert ledger.height >= 1, f"{measurement.regime}: the counted run emitted no ledger rows"
    assert all(v is not None and math.isfinite(v) and v > 0.0 for v in rwa), (
        f"{measurement.regime}: rwa_final is not positive and finite on every row: {rwa}"
    )
    assert not violations, (
        f"{measurement.regime}: an edge contract was violated during the counted run, "
        f"so later stages never ran and the counts are not a full run's: "
        f"{[e.code for e in violations]}"
    )


def test_every_counter_fired(measurement: _Measurement) -> None:
    """Each of the three counters saw at least one call during the run.

    The patch-applied assertion in ``_install_counters`` proves the wrappers
    were installed; this proves the run actually went through them. A zero
    here means the engine has stopped reaching that callable through the
    patched name, and the budget for it is no longer being measured.
    """
    # Arrange / Act
    silent = [name for name in _METRICS if measurement.observed[name] == 0]

    # Assert
    assert not silent, (
        f"{measurement.regime}: counters that never fired: {silent}; observed "
        f"{measurement.observed}. If the engine now reaches this call by another "
        "name, extend _install_counters - do not bank a zero."
    )


# ---------------------------------------------------------------------------
# The gate - two-way ratchet
# ---------------------------------------------------------------------------


def test_banked_budget_covers_every_metric() -> None:
    """The banked table names exactly the metrics the counter emits, per regime."""
    # Arrange / Act
    mismatched = {
        regime: sorted(set(banked) ^ set(_METRICS))
        for regime, banked in _BANKED.items()
        if set(banked) != set(_METRICS)
    }

    # Assert
    assert not mismatched, f"_BANKED metric names differ from _METRICS: {mismatched}"


def test_pipeline_fixed_cost_matches_the_banked_budget(measurement: _Measurement) -> None:
    """Observed collect / collect_schema / collect_all counts equal the banked ones.

    Above is a regression in the pipeline's fixed cost. Below is an improvement
    that must be banked so it becomes the new ceiling. Both fail; the message
    says which, and prints the observed counts in the shape ``_BANKED`` takes.
    """
    # Arrange
    banked = _BANKED[measurement.regime]
    observed = measurement.observed

    # Act
    drifted_up = {m: (banked[m], observed[m]) for m in _METRICS if observed[m] > banked[m]}
    improved = {m: (banked[m], observed[m]) for m in _METRICS if observed[m] < banked[m]}

    # Assert
    report = (
        f"\n{measurement.regime}: observed {observed!r}\n"
        f"{measurement.regime}: banked   {banked!r}\n"
    )
    if drifted_up:
        report += (
            "FIXED COST DRIFTED UP (banked -> observed): "
            f"{drifted_up}. A one-row run now materialises more than it did; find the "
            "new collect / collect_schema / collect_all site and remove it - a recorder "
            "filtering the plan instead of the materialised edge, a schema re-resolved "
            "inside a loop, a gate issuing one collect per check. Do not bank a rise.\n"
        )
    if improved:
        report += (
            "IMPROVED (banked -> observed): "
            f"{improved}. Bank it deliberately: paste the observed line above into "
            "_BANKED for this regime and say what moved it in the commit message. "
            "The ratchet fails on an improvement on purpose - see _NOTE.\n"
        )
    assert not drifted_up and not improved, report
