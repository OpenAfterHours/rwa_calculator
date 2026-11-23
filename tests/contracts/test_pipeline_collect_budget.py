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
the numbers cover that window and nothing before or after it.

A class / module patch is visible to EVERY thread in the process, so the
window alone does not make the numbers the run's: until P5.74 any Polars work
another thread did during it was counted too, and a reconciliation job an
earlier test left running on the UI's background executor read as 2-3.5x the
budget in both regimes - but only when the two files ran in one process, close
together, which under xdist depends on which worker each file lands on.
So the wrappers count only the thread that installed them, which is the thread
that calls ``run_with_data``; calls from any other thread are tallied apart and
must be zero (``test_the_run_materialises_only_on_the_calling_thread``), and
the measurement first asserts no UI background job is running, so a leak of
that kind fails with its cause named rather than as a count. The thread filter
is exact only while the engine materialises on the calling thread - true
today, and the zero-tally test is what says so if it stops being true.

``collect_schema`` is counted at
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
- tests/fixtures/ui_jobs.py and tests/conftest.py::_no_leaked_ui_job (P5.74:
  the background-job leak this file was once order-dependent on)
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from tests.fixtures.ui_jobs import running_ui_job_ids
from tests.properties.portfolios import ExposureSpec, build_bundle, config_for

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.ui.app.progress import create_job

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
#: 2026-09-06 (Lever 2 item 2): ``collect_schema`` 136 -> 113 (CRR) and
#: 135 -> 113 (B31) as the schema each stage needs is resolved once and
#: threaded, instead of re-walking the plan at every call site. The input
#: gate resolves each raw table's column names ONCE
#: (``validation._table_column_names``) rather than once per check builder,
#: per declared foreign key and per unique key; the aggregator resolves the
#: post-floor ledger once for its four summary builders; the CRM facility
#: lookup reuses the names its caller already resolved.
#: 2026-11-18 (review cluster "undrawn", CM-01/CM-02/CM-11): ``collect_schema``
#: 113 -> 112 in both regimes. The hierarchy stage now collects the facility ->
#: facility edges ONCE (``graph.collect_facility_edges``) and hands them to both
#: the root lookup and the ancestor closure, dropping one schema resolution and
#: one collect; the collect it frees pays for the new HIE004-HIE006 warnings
#: collect (``facility_warnings``), so ``collect`` is unchanged.
#: 2026-11-18 (review IV-01): ``collect`` 85 -> 84 (CRR) and 83 -> 82 (B31) as
#: the classifier's post-materialise DQ008 and CLS010 roll-ups were folded into
#: one select (``audit.collect_classified_frame_warnings``), which also carries
#: the new SA006 project-finance-phase count without a collect of its own.
#: 2026-11-18 (collateral review CL-01/02/04/09/14): ``collect_schema`` 113 ->
#: 112 in both regimes. ``HaircutCalculator.apply_haircuts`` reads its optional
#: inputs through one ``ensure_columns`` call instead of four presence-guarded
#: schema resolutions, and the CRM018 / CRM019 recorders became one scan that
#: also emits CRM023 / CRM026; the CRM025 (CCR-only pledge) recorder added one
#: ``collect`` where the merged scan removed one, so ``collect`` is unchanged.
#: 2026-11-18 (review cluster "group", RC-05/RC-16): ``collect`` 83 -> 82 (B31)
#: as the classifier's counterparty-size warnings (CLS008/009/011 plus the new
#: CLS015/016) are counted in ONE select instead of a CLS009 collect and a
#: separate Basel 3.1 collect. CRR unchanged (it paid only the CLS009 collect).
#: 2026-11-19 (review cluster "dq", RC-10/RC-11/RC-01/RC-02/SF-03/CC-19):
#: ``collect`` one fewer in each regime (on its own branch 85 -> 84 CRR, 83 -> 82 B31). The four new data-quality
#: findings add no materialisation: DQ019 rides the duplicate-key collect, DQ020
#: the input gate's ``collect_all``, DQ021 / DQ022 the facility-edge and
#: facility-warnings collects. And ``validate_duplicate_keys`` now sorts in its
#: plan instead of on the collected frame, whose eager ``sort`` was a second
#: lazy collect of its own.
_BANKED: dict[str, dict[str, int]] = {
    "CRR": {"collect": 83, "collect_schema": 111, "collect_all": 8},
    "B31": {"collect": 80, "collect_schema": 111, "collect_all": 9},
}

_REGIMES: tuple[str, ...] = tuple(_BANKED)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Measurement:
    """One regime's run: the counts it made, and the evidence it was a real run.

    ``observed`` is what the run's own thread materialised - the budget.
    ``off_thread`` is what any OTHER thread materialised while the run was being
    counted, with ``live_threads`` naming the threads alive when it returned; it
    is not budgeted, and must be zero (see
    ``test_the_run_materialises_only_on_the_calling_thread``).
    """

    regime: str
    observed: dict[str, int]
    off_thread: dict[str, int]
    live_threads: tuple[str, ...]
    ledger: pl.DataFrame
    errors: tuple[CalculationError, ...]


def _install_counters(
    monkeypatch: pytest.MonkeyPatch, other_threads: dict[str, int] | None = None
) -> dict[str, int]:
    """Replace the three materialising callables with counting wrappers.

    Returns the live counter dict, which counts ONLY calls made on the thread
    that installed the wrappers - the thread that then calls ``run_with_data``.
    The patch itself is on the class and the module, so every thread in the
    process goes through it; without the filter, Polars work any other thread
    did while the run was in flight was counted as the run's (P5.74: a UI
    reconciliation job an earlier test left running read as 2-3.5x the budget).
    Calls from any other thread are tallied into ``other_threads`` when it is
    given, so they are reported rather than silently dropped.

    Asserts each patch actually landed (LESSONS C12, mechanism 2: a patch that
    silently no-ops reads as a dramatic improvement here, which is the opposite
    of what happened).
    """
    owner = threading.get_ident()
    counts: dict[str, int] = dict.fromkeys(_METRICS, 0)
    foreign: dict[str, int] = dict.fromkeys(_METRICS, 0) if other_threads is None else other_threads
    original_collect = pl.LazyFrame.collect
    original_collect_schema = pl.LazyFrame.collect_schema
    original_collect_all = pl.collect_all

    def tally(metric: str) -> None:
        target = counts if threading.get_ident() == owner else foreign
        target[metric] = target.get(metric, 0) + 1

    def counting_collect(self: pl.LazyFrame, *args: Any, **kwargs: Any) -> Any:
        tally("collect")
        return original_collect(self, *args, **kwargs)

    def counting_collect_schema(self: pl.LazyFrame, *args: Any, **kwargs: Any) -> Any:
        tally("collect_schema")
        return original_collect_schema(self, *args, **kwargs)

    def counting_collect_all(*args: Any, **kwargs: Any) -> Any:
        tally("collect_all")
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


def _assert_no_background_ui_job_running(regime: str) -> None:
    """Measurement precondition: no UI background job is running in this process.

    A UI job is a full pipeline run on ``rwa_calc.ui.app.progress``'s
    module-level ``ThreadPoolExecutor``. The counters no longer count it (they
    count the measuring thread only), so this is not what keeps the budget
    right. It is here so that a job some earlier test dispatched and never
    waited for fails HERE with its cause named, instead of surfacing - as it did
    before P5.74 - as an unexplained count of up to 3.5x the banked one that
    reproduced only when xdist happened to give both files to one worker.
    ``"running"`` stands in for "its worker thread is still busy";
    ``tests/fixtures/ui_jobs.py`` says why that holds.
    """
    running = sorted(running_ui_job_ids())
    assert not running, (
        f"{regime}: {len(running)} background UI job(s) from an earlier test are still "
        f"running in this process: {running}. Each is a pipeline run on the UI's "
        "ThreadPoolExecutor, doing Polars work on another thread while the budget is "
        "measured. Find the test that dispatched it (tests/conftest.py::_no_leaked_ui_job "
        "fails it by name when it runs in the same process) and make it wait for its job."
    )


@pytest.fixture(scope="module", params=_REGIMES)
def measurement(request: pytest.FixtureRequest) -> Iterator[_Measurement]:
    """Run the one-row bundle once per regime under the counters.

    Module-scoped so the tests below share one run per regime; the counters
    live inside a ``MonkeyPatch.context`` because a function-scoped
    ``monkeypatch`` cannot serve a module-scoped fixture.
    """
    regime: str = request.param
    # Arrange - everything that is NOT the run happens before the counters go in.
    _assert_no_background_ui_job_running(regime)
    bundle = build_bundle((ExposureSpec(),))
    config = config_for(regime)
    off_thread: dict[str, int] = dict.fromkeys(_METRICS, 0)

    with pytest.MonkeyPatch.context() as monkeypatch:
        counts = _install_counters(monkeypatch, other_threads=off_thread)
        # Act - the run, and a snapshot the instant it returns.
        result = PipelineOrchestrator().run_with_data(bundle, config)
        observed = dict(counts)
        observed_off_thread = dict(off_thread)
        live_threads = tuple(sorted(t.name for t in threading.enumerate()))

    # Read outside the patched region so the evidence collect is not counted.
    ledger = result.results.collect()
    yield _Measurement(
        regime=regime,
        observed=observed,
        off_thread=observed_off_thread,
        live_threads=live_threads,
        ledger=ledger,
        errors=tuple(result.errors),
    )


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


def test_the_run_materialises_only_on_the_calling_thread(measurement: _Measurement) -> None:
    """No other thread did Polars work while the run was being counted.

    The budget counts the calling thread only (``_install_counters``). That is
    the whole run today - nothing under ``src/rwa_calc/engine`` starts a thread,
    and its one Python UDF (the securitisation allocator's ``map_elements``)
    does not materialise - but a future change that DID materialise off the
    calling thread (a worker pool, a UDF that collects) would drop out of the
    budget and read as an improvement someone might bank. This makes it a named
    failure instead. The other source is a thread an earlier test left running;
    the measurement precondition already names the UI's own background jobs.
    """
    # Arrange / Act
    stray = {name: n for name, n in measurement.off_thread.items() if n}

    # Assert
    assert not stray, (
        f"{measurement.regime}: Polars materialisations on threads other than the "
        f"run's while it was counted: {stray}; threads alive when it returned: "
        f"{list(measurement.live_threads)}. If the ENGINE now materialises off the "
        "calling thread, extend _install_counters to count it - do not bank the drop. "
        "If a thread an earlier test left running did this work, make that test wait."
    )


# ---------------------------------------------------------------------------
# Isolation - the counters see the run and nothing else
# ---------------------------------------------------------------------------


def _materialise_once() -> None:
    """Make exactly one call of each counted kind on a trivial plan."""
    plan = pl.LazyFrame({"a": [1]})
    plan.collect()
    plan.collect_schema()
    pl.collect_all([plan])


def test_counters_ignore_polars_work_on_other_threads() -> None:
    """A materialisation on another thread is not part of the measured run.

    The patch is on the CLASS and the MODULE, so every thread in the process
    sees it. Before P5.74 every thread was also counted: a reconciliation job an
    earlier test left running on the UI's module-level executor was counted as
    part of the run. Measured on 2026-11-23, with that test run first in the same
    process, the budget read 159/272/15 (CRR) and 284/298/23 (B31) against a
    banked 83/111/8 and 80/111/9; how much it adds depends on how far the job has
    got. The adequacy half proves the installing thread still counts, so this
    cannot pass because counting broke altogether.
    """
    # Arrange
    with pytest.MonkeyPatch.context() as monkeypatch:
        counts = _install_counters(monkeypatch)
        _materialise_once()
        on_own_thread = dict(counts)

        # Act
        worker = threading.Thread(target=_materialise_once, name="p5-74-other-thread")
        worker.start()
        worker.join()
        after_other_thread = dict(counts)

    # Assert
    assert on_own_thread == dict.fromkeys(_METRICS, 1), (
        f"the installing thread's own calls were not counted once each: {on_own_thread}"
    )
    assert after_other_thread == on_own_thread, (
        "Polars calls made on ANOTHER thread were counted as part of the run: "
        f"{on_own_thread} -> {after_other_thread}"
    )


def test_counters_report_polars_work_on_other_threads() -> None:
    """Calls the thread filter excludes are tallied apart, not silently dropped.

    ``test_the_run_materialises_only_on_the_calling_thread`` asserts that tally
    is zero for the measured run; without this it could pass because the tally
    never counts anything (LESSONS C11).
    """
    # Arrange
    off_thread: dict[str, int] = dict.fromkeys(_METRICS, 0)
    with pytest.MonkeyPatch.context() as monkeypatch:
        counts = _install_counters(monkeypatch, other_threads=off_thread)

        # Act
        worker = threading.Thread(target=_materialise_once, name="p5-74-other-thread")
        worker.start()
        worker.join()

    # Assert - ">= 1", not "== 1": the tally is process-wide by design, so a
    # thread another test left running may add to it, and that leak is named by
    # the measurement precondition and tests/conftest.py, not here.
    untallied = [name for name in _METRICS if off_thread[name] < 1]
    assert not untallied, (
        f"another thread's calls were not tallied into other_threads: {untallied}; "
        f"tally {off_thread}"
    )
    assert counts == dict.fromkeys(_METRICS, 0), (
        f"another thread's calls reached the budget: {counts}"
    )


def test_measurement_precondition_names_a_running_background_ui_job() -> None:
    """A UI job still running when the measurement starts fails by name, not by count.

    The job is registered through the real ``create_job``, so this also proves
    the precondition reads the registry the UI actually writes to - a renamed
    module would leave the check silently empty, and this test red.
    """
    # Arrange
    job = create_job()
    try:
        # Act / Assert
        with pytest.raises(AssertionError, match="still running in this process") as raised:
            _assert_no_background_ui_job_running("CRR")
        assert job.job_id in str(raised.value), "the precondition did not name the running job"
    finally:
        job.finish(success=True)

    # Assert - a job that has left "running" is no longer reported.
    assert job.job_id not in running_ui_job_ids()


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
