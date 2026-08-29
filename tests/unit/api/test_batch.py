"""Unit tests for the batch driver (rwa_calc.api.batch).

The driver fans N independent scoped calculations out over a
``ProcessPoolExecutor`` and returns one handle per scope, in input order. What
these tests pin:

- **Input-order preservation** — and, more to the point, that each result
  carries *its own* scope's response. Order alone is trivially preserved by
  building the results from the input list; the failure mode worth detecting is
  a slot/outcome misalignment, so every order assertion checks a marker that
  came back from the run. The serial-path order tests cannot tell "assembled by
  run_id" from "assembled by completion order", because on that path the two
  coincide — ``test_input_order_survives_a_reversed_completion_order`` is the
  one that can, over a real pool whose workers finish backwards.
- **Per-scope failure isolation** — a worker that raises, and a worker that
  dies HARD (``os._exit``, standing in for the SIGSEGV ``engine/materialise.py``
  documents), must each cost exactly one scope. The hard case is the one that
  needed work: it breaks the whole pool, so the bystanders have to be recovered
  rather than merely reported.
- **Serial/parallel equivalence** — over a REAL pipeline and a REAL process
  pool, asserting the worker pids differ from this process's. Without that
  check the test would pass just as happily if the parallel path had silently
  degraded to serial, which is the one thing it exists to rule out.
- **The worker Polars cap** — asserted inside a real worker, against an
  uncapped control, with the session-wide ``POLARS_MAX_THREADS`` cleared from
  this process first so the child cannot inherit the answer.
- **Both sides of the run index** — a successful run is written, a failed one
  and an undispatched one are not.
- **max_workers bounding** — against a monkeypatched ``os.cpu_count`` so the
  assertions pin the intended policy rather than this box's core count.

Four groups spawn real processes: ``TestSerialParallelEquivalence`` (a real
pipeline, two workers), ``TestHardWorkerExit`` (one pool plus one recovery pool
per lost scope, hence the ~20s), ``TestWorkerPolarsCap``, and the
reversed-completion order test. They are deliberately NOT skipped under xdist —
a skipped test of the parallel path is indistinguishable from a passing one that
never ran anything, and the whole file is ~50s for that reason. Everything else
monkeypatches ``_run_scope`` or replaces the executor.
"""

from __future__ import annotations

import dataclasses
import os
import pickle
from concurrent.futures import Future
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import _batch_probe
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rwa_calc import worker_bootstrap
from rwa_calc.api import batch, run_index
from rwa_calc.api.batch import (
    DEFAULT_MAX_WORKERS,
    BatchRequest,
    ScopeSpec,
    resolve_max_workers,
    run_batch,
)
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.worker_bootstrap import configure_worker_process

if TYPE_CHECKING:
    from collections.abc import Sequence

# =============================================================================
# Fixtures and helpers
# =============================================================================


@pytest.fixture(autouse=True)
def clean_index() -> None:
    """Each test starts from an empty in-process run index."""
    run_index.clear()


def _response(marker: str, framework: str = "CRR") -> CalculationResponse:
    """A successful response tagged with *marker* in ``reporting_entity``.

    The marker is what makes an order assertion meaningful: it travels back
    from the (faked) run, so a result holding the wrong scope's response fails.
    """
    return CalculationResponse(
        success=True,
        framework=framework,
        reporting_date=date(2025, 1, 1),
        summary=SummaryStatistics(
            total_ead=Decimal("100"),
            total_rwa=Decimal("50"),
            exposure_count=1,
            average_risk_weight=Decimal("0.5"),
        ),
        # Deliberately absent: run_index.find_reusable drops an entry whose
        # results parquet does not exist, so faked runs cannot leak across tests.
        results_path=Path("no-such-results.parquet"),
        reporting_entity=marker,
    )


def _entity_scopes(*names: str) -> tuple[ScopeSpec, ...]:
    """One scope per entity name, all on the consolidated basis."""
    return tuple(
        ScopeSpec(reporting_entity=name, reporting_basis=ReportingBasis.CONSOLIDATED)
        for name in names
    )


def _request(scopes: Sequence[ScopeSpec], tmp_path: Path, **kwargs: object) -> BatchRequest:
    """A BatchRequest over *scopes* with the shared inputs the fakes ignore."""
    return BatchRequest(
        scopes=tuple(scopes),
        data_path=tmp_path,
        reporting_date=date(2025, 1, 1),
        **kwargs,  # type: ignore[arg-type]
    )


def _fake_run(calls: list[str]) -> object:
    """A ``_run_scope`` stand-in recording each dispatched entity."""

    def run(job: batch._ScopeJob) -> batch._JobOutcome:
        calls.append(job.reporting_entity or "<unscoped>")
        return batch._JobOutcome(
            response=_response(job.reporting_entity or "<unscoped>", job.framework),
            worker_pid=os.getpid(),
        )

    return run


# =============================================================================
# max_workers bounding
# =============================================================================


class TestResolveMaxWorkers:
    """``resolve_max_workers`` is the whole of the bounding policy."""

    @pytest.fixture(autouse=True)
    def sixteen_cores(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin the core count so the assertions are about policy, not this box."""
        monkeypatch.setattr(batch.os, "cpu_count", lambda: 16)

    def test_default_is_the_memory_bound_not_the_core_count(self) -> None:
        """16 cores must not mean 16 workers — each holds a full result frame."""
        assert resolve_max_workers(None, 100) == DEFAULT_MAX_WORKERS
        assert DEFAULT_MAX_WORKERS < 16

    def test_never_exceeds_the_number_of_runs(self) -> None:
        """A worker with no job is pure spawn cost."""
        assert resolve_max_workers(8, 2) == 2
        assert resolve_max_workers(None, 3) == 3

    def test_explicit_request_is_capped_at_the_core_count(self) -> None:
        """A caller cannot ask for more resident sets than the box has cores."""
        assert resolve_max_workers(64, 64) == 16

    def test_explicit_request_below_the_default_is_honoured(self) -> None:
        """The default is a default, not a floor."""
        assert resolve_max_workers(2, 10) == 2

    def test_a_single_run_is_serial(self) -> None:
        """One run never justifies a pool, whatever was asked for."""
        assert resolve_max_workers(8, 1) == 1
        assert resolve_max_workers(8, 0) == 1

    def test_below_one_is_a_programming_error(self) -> None:
        """The serial path is max_workers=1; 0 is a mistake, not a mode."""
        with pytest.raises(ValueError, match="must be >= 1"):
            resolve_max_workers(0, 4)
        with pytest.raises(ValueError, match="must be >= 1"):
            resolve_max_workers(-1, 4)


class TestRequestValidation:
    """Construction-time guards, before anything is dispatched."""

    def test_max_workers_below_one_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            _request(_entity_scopes("E1"), tmp_path, max_workers=0)

    def test_zero_polars_threads_rejected(self, tmp_path: Path) -> None:
        """Polars accepts 0 at import and then panics at compute time."""
        with pytest.raises(ValueError, match="panics at compute time"):
            _request(_entity_scopes("E1"), tmp_path, worker_polars_threads=0)

    def test_entity_without_basis_rejected(self) -> None:
        """Same rule the REST layer enforces as a 422, applied at construction."""
        with pytest.raises(ValueError, match="requires reporting_basis"):
            ScopeSpec(reporting_entity="E1")

    def test_scopes_are_normalised_to_a_tuple(self, tmp_path: Path) -> None:
        request = _request(list(_entity_scopes("E1", "E2")), tmp_path)
        assert isinstance(request.scopes, tuple)

    def test_no_scopes_is_an_empty_batch_not_an_error(self, tmp_path: Path) -> None:
        result = run_batch(_request((), tmp_path))
        assert len(result) == 0
        assert result.parallel is False


# =============================================================================
# Order, isolation and dedup — serial path, faked runs
# =============================================================================


class TestOrderAndIsolation:
    """The two guarantees the batch API makes about its result list."""

    def test_results_carry_their_own_scopes_response_in_input_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))

        result = run_batch(
            _request(_entity_scopes("E1", "E2", "E3", "E4"), tmp_path, max_workers=1)
        )

        assert [r.scope.reporting_entity for r in result] == ["E1", "E2", "E3", "E4"]
        # The marker travelled back from the run, so this also rules out a
        # slot/outcome misalignment that a pure order check would miss.
        assert [r.response.reporting_entity for r in result.results] == [  # type: ignore[union-attr]
            "E1",
            "E2",
            "E3",
            "E4",
        ]
        assert calls == ["E1", "E2", "E3", "E4"]

    def test_one_raising_scope_costs_exactly_one_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(job: batch._ScopeJob) -> batch._JobOutcome:
            if job.reporting_entity == "E2":
                raise RuntimeError("boom")
            return batch._JobOutcome(response=_response(job.reporting_entity or ""))

        monkeypatch.setattr(batch, "_run_scope", run)

        result = run_batch(
            _request(_entity_scopes("E1", "E2", "E3", "E4"), tmp_path, max_workers=1)
        )

        assert [r.success for r in result] == [True, False, True, True]
        failed = result.results[1]
        assert failed.response is None
        assert failed.error is not None
        assert failed.error.code == batch.ERROR_SCOPE_FAILED
        assert "boom" in failed.error.message
        # The surviving three still carry their own results.
        assert [r.response.reporting_entity for r in result.succeeded] == ["E1", "E3", "E4"]  # type: ignore[union-attr]

    def test_a_failed_calculation_is_not_a_dispatch_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """success=False is a run that happened; response=None is one that did not."""
        failed = dataclasses.replace(_response("E1"), success=False)
        monkeypatch.setattr(
            batch, "_run_scope", lambda job: batch._JobOutcome(response=failed, worker_pid=1)
        )

        result = run_batch(_request(_entity_scopes("E1"), tmp_path, max_workers=1))

        assert result.results[0].success is False
        assert result.results[0].response is failed
        assert result.results[0].error is None

    def test_duplicate_scopes_are_run_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))

        result = run_batch(_request(_entity_scopes("E1", "E2", "E1"), tmp_path, max_workers=1))

        assert calls == ["E1", "E2"]
        assert len(result) == 3
        assert result.results[0].run_id == result.results[2].run_id
        assert [r.response.reporting_entity for r in result.results] == ["E1", "E2", "E1"]  # type: ignore[union-attr]

    def test_reuse_runs_false_dispatches_every_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))

        result = run_batch(
            _request(_entity_scopes("E1", "E1"), tmp_path, max_workers=1, reuse_runs=False)
        )

        assert calls == ["E1", "E1"]
        assert result.results[0].run_id != result.results[1].run_id

    def test_input_order_survives_a_reversed_completion_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The "in input order" guarantee, over a REAL pool that finishes backwards.

        The three ordering assertions above run the serial path, where
        completion order IS input order — so they cannot distinguish "assembled
        by run_id" from "assembled by completion". This one can: three scopes go
        to three real workers with staggered sleeps, so the last submitted
        finishes first. If ``_assemble`` ever zipped results positionally onto
        completion order, the entities would come back E3, E2, E1.

        ``_batch_probe.staggered_run`` replaces ``_run_scope`` in the batch
        module's globals; ``_run_parallel`` resolves that name at call time and
        pickles it by reference, so the workers really do run the probe. It
        rendezvouses under ``cache_root`` before sleeping — hence both that
        argument and ``max_workers`` matching the scope count, which
        ``_batch_probe.BARRIER_SIZE`` pins.
        """
        monkeypatch.setattr(batch, "_run_scope", _batch_probe.staggered_run)
        scopes = _entity_scopes("E1", "E2", "E3")
        assert len(scopes) == _batch_probe.BARRIER_SIZE

        result = run_batch(
            _request(
                scopes,
                tmp_path,
                max_workers=_batch_probe.BARRIER_SIZE,
                cache_root=tmp_path / "rendezvous",
            )
        )

        assert result.parallel is True
        assert all(r.worker_pid not in (None, os.getpid()) for r in result)
        assert [r.response.reporting_entity for r in result.results] == ["E1", "E2", "E3"]  # type: ignore[union-attr]

        # Proof the stagger did what it claims: had every worker finished in
        # submission order, the assertion above would hold for the wrong reason.
        finished = [r.response.performance.completed_at for r in result.results]  # type: ignore[union-attr]
        assert finished == sorted(finished, reverse=True), finished

    def test_scope_reaches_the_worker_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The entity/basis/framework a caller asked for is what the job carries."""
        jobs: list[batch._ScopeJob] = []

        def run(job: batch._ScopeJob) -> batch._JobOutcome:
            jobs.append(job)
            return batch._JobOutcome(response=_response(job.reporting_entity or ""))

        monkeypatch.setattr(batch, "_run_scope", run)
        scopes = (
            ScopeSpec(
                reporting_entity="SOLO-1",
                reporting_basis=ReportingBasis.INDIVIDUAL,
                framework="BASEL_3_1",
            ),
            ScopeSpec(reporting_entity="GRP", reporting_basis=ReportingBasis.CONSOLIDATED),
        )

        run_batch(_request(scopes, tmp_path, framework="CRR", max_workers=1))

        assert [(j.reporting_entity, j.reporting_basis, j.framework) for j in jobs] == [
            ("SOLO-1", "individual", "BASEL_3_1"),
            ("GRP", "consolidated", "CRR"),
        ]


# =============================================================================
# Run-index reuse
# =============================================================================


class TestRunIndexReuse:
    """Both sides of the index: what the batch reads, and what it writes back."""

    @staticmethod
    def _fingerprint(tmp_path: Path, entity: str) -> run_index.CalculationFingerprint:
        return run_index.compute_fingerprint(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
            data_format="parquet",
            reporting_entity=entity,
            reporting_basis="consolidated",
        )

    def test_a_successful_run_is_written_to_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The write side — otherwise the read side below could never fire."""
        results_path = tmp_path / "cache" / "last_results.parquet"
        results_path.parent.mkdir(parents=True)
        results_path.write_bytes(b"only existence is checked")
        good = dataclasses.replace(_response("E1"), results_path=results_path)
        monkeypatch.setattr(
            batch, "_run_scope", lambda job: batch._JobOutcome(response=good, worker_pid=1)
        )

        result = run_batch(_request(_entity_scopes("E1"), tmp_path, max_workers=1))

        indexed = run_index.find_reusable(self._fingerprint(tmp_path, "E1"))
        assert indexed is not None
        assert indexed.run_id == result.results[0].run_id

    def test_a_failed_run_is_never_written_to_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unsuccessful run must never be offered for reuse.

        Indexing one would serve a 0-row error-path parquet to the NEXT caller
        as though it were a completed calculation. Paired with the test above,
        which proves the same code path DOES index a successful run — so a green
        result here cannot be the index simply never being written.
        """
        results_path = tmp_path / "cache" / "last_results.parquet"
        results_path.parent.mkdir(parents=True)
        results_path.write_bytes(b"only existence is checked")
        bad = dataclasses.replace(_response("E1"), success=False, results_path=results_path)
        monkeypatch.setattr(
            batch, "_run_scope", lambda job: batch._JobOutcome(response=bad, worker_pid=1)
        )

        result = run_batch(_request(_entity_scopes("E1"), tmp_path, max_workers=1))

        assert result.results[0].success is False
        assert run_index.find_reusable(self._fingerprint(tmp_path, "E1")) is None
        assert run_index.entries() == []

    def test_a_scope_that_never_ran_is_never_written_to_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dispatch failure leaves no response, and so must leave no entry."""

        def boom(job: batch._ScopeJob) -> batch._JobOutcome:
            raise RuntimeError("worker died")

        monkeypatch.setattr(batch, "_run_scope", boom)

        result = run_batch(_request(_entity_scopes("E1"), tmp_path, max_workers=1))

        assert result.results[0].response is None
        assert run_index.entries() == []

    def test_indexed_run_is_reused_without_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        results_path = tmp_path / "cache" / "last_results.parquet"
        results_path.parent.mkdir(parents=True)
        results_path.write_bytes(b"not really parquet, only its existence is checked")
        cached = dataclasses.replace(_response("E1"), results_path=results_path)
        run_index.register_calculation(self._fingerprint(tmp_path, "E1"), "earlier-run", cached)

        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))
        result = run_batch(_request(_entity_scopes("E1", "E2"), tmp_path, max_workers=1))

        assert calls == ["E2"]
        assert result.results[0].reused is True
        assert result.results[0].run_id == "earlier-run"
        assert result.results[1].reused is False


# =============================================================================
# Execution mode selection
# =============================================================================


class TestExecutionMode:
    """Which of the two paths a batch takes, and why."""

    def test_serial_env_var_forces_the_serial_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deployment kill-switch beats an explicit max_workers.

        Detector, not decoration: the fake ``_run_scope`` exists only in THIS
        process. If the kill-switch were ignored the batch would spawn real
        workers running the real pipeline, and ``calls`` would come back empty.
        """
        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))
        monkeypatch.setenv(batch.SERIAL_ENV_VAR, "1")

        result = run_batch(_request(_entity_scopes("E1", "E2", "E3"), tmp_path, max_workers=3))

        assert calls == ["E1", "E2", "E3"]
        assert result.parallel is False
        assert result.max_workers == 1

    def test_unstartable_pool_falls_back_to_serial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sandbox that forbids spawning still returns every scope's result."""

        def refuse(**_kwargs: object) -> object:
            raise OSError("spawning is not permitted here")

        calls: list[str] = []
        monkeypatch.setattr(batch, "_run_scope", _fake_run(calls))
        monkeypatch.setattr(batch, "ProcessPoolExecutor", refuse)

        result = run_batch(_request(_entity_scopes("E1", "E2", "E3"), tmp_path, max_workers=3))

        assert calls == ["E1", "E2", "E3"]
        assert [r.success for r in result] == [True, True, True]
        assert result.parallel is False
        assert [e.code for e in result.errors] == [batch.ERROR_POOL_UNAVAILABLE]

    def test_a_bystander_of_a_broken_pool_is_recovered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the isolation guarantee, at fake-executor speed.

        ``TestHardWorkerExit`` proves this end to end with a real ``os._exit``;
        this pins the same branch deterministically and in milliseconds. E2 is a
        BYSTANDER — somebody else's worker died while E2 was in flight — so on
        its second, solitary attempt it succeeds and must end up with a real
        response, not an error.
        """
        attempts: list[str] = []

        class _FakeExecutor:
            """Breaks the pool under E2 once; every other submission succeeds."""

            def __enter__(self) -> _FakeExecutor:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def submit(self, _fn: object, job: batch._ScopeJob) -> Future[batch._JobOutcome]:
                entity = job.reporting_entity or ""
                attempts.append(entity)
                future: Future[batch._JobOutcome] = Future()
                if entity == "E2" and attempts.count("E2") == 1:
                    future.set_exception(
                        batch.BrokenProcessPool("a process in the pool terminated abruptly")
                    )
                else:
                    future.set_result(batch._JobOutcome(response=_response(entity), worker_pid=999))
                return future

        monkeypatch.setattr(batch, "ProcessPoolExecutor", lambda **_kw: _FakeExecutor())

        result = run_batch(_request(_entity_scopes("E1", "E2", "E3"), tmp_path, max_workers=3))

        assert [r.success for r in result] == [True, True, True]
        assert [r.response.reporting_entity for r in result.results] == ["E1", "E2", "E3"]  # type: ignore[union-attr]
        # Only the bystander was re-run; the two that completed are not touched.
        assert attempts == ["E1", "E2", "E3", "E2"]
        # Not a fallback case: the batch stays "parallel" and reports no
        # batch-level error, because the pool did start and did do the work.
        assert result.parallel is True
        assert result.errors == ()

    def test_a_planned_scope_with_no_outcome_gets_its_own_code(self) -> None:
        """A bookkeeping bug in here is not "the worker pool broke".

        Unreachable through ``run_batch`` today, which is exactly why the
        distinction is worth pinning: if it ever does fire, BATCH002 would send
        whoever reads it looking at the pool.
        """
        slot = batch._Slot(scope=ScopeSpec(), run_id="never-ran", reused_response=None)

        result = batch._assemble(slot, {})

        assert result.error is not None
        assert result.error.code == batch.ERROR_SCOPE_NOT_DISPATCHED
        assert result.error.code != batch.ERROR_POOL_BROKEN
        assert "pool" not in result.error.message


# =============================================================================
# A worker dying HARD
# =============================================================================


class TestHardWorkerExit:
    """The isolation guarantee against a worker that never gets to raise.

    A raised exception fails one future. A hard exit — segfault, OOM kill,
    ``os._exit`` — fails **every pending future in the pool** with
    ``BrokenProcessPool``, so the naive handling loses the bystanders too. That
    is not hypothetical here: ``engine/materialise.py`` documents Polars taking
    the process down with SIGSEGV on deep plans, and a batch of scoped runs is
    precisely where one pathological portfolio meets three healthy ones.
    """

    def test_a_hard_exit_costs_only_the_scope_that_caused_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three healthy scopes survive a fourth calling ``os._exit`` beside them.

        Timing-robust by construction: whether a healthy scope completes before
        the break or is recovered afterwards, it must end up with a real
        response. Only the crasher may fail, and it must fail with the code that
        names it as the crasher rather than as a bystander.
        """
        monkeypatch.setattr(batch, "_run_scope", _batch_probe.crashing_run)
        scopes = _entity_scopes("E1", _batch_probe.CRASH_ENTITY, "E3", "E4")

        result = run_batch(_request(scopes, tmp_path, max_workers=2))

        survivors = [r for r in result if r.scope.reporting_entity != _batch_probe.CRASH_ENTITY]
        assert [r.success for r in survivors] == [True, True, True], [r.errors for r in survivors]
        assert [r.response.reporting_entity for r in survivors] == ["E1", "E3", "E4"]  # type: ignore[union-attr]

        crasher = result.results[1]
        assert crasher.success is False
        assert crasher.response is None
        assert crasher.error is not None
        assert crasher.error.code == batch.ERROR_WORKER_DIED

    def test_the_crashing_scope_is_retried_once_and_only_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recovery is bounded: a scope that kills two workers is not tried a third.

        Without a bound this is an infinite loop, because re-running the scope
        that segfaults segfaults again. Counted through a fake executor so the
        assertion is on the number of attempts, not on wall time.
        """
        attempts: list[str] = []

        class _AlwaysBreaks:
            def __enter__(self) -> _AlwaysBreaks:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def submit(self, _fn: object, job: batch._ScopeJob) -> Future[batch._JobOutcome]:
                attempts.append(job.reporting_entity or "")
                future: Future[batch._JobOutcome] = Future()
                future.set_exception(batch.BrokenProcessPool("worker terminated abruptly"))
                return future

        monkeypatch.setattr(batch, "ProcessPoolExecutor", lambda **_kw: _AlwaysBreaks())

        result = run_batch(_request(_entity_scopes("E1", "E2"), tmp_path, max_workers=2))

        # Two in the main pool, then one recovery attempt each — never more.
        assert attempts == ["E1", "E2", "E1", "E2"]
        assert [r.error.code for r in result if r.error is not None] == [  # type: ignore[union-attr]
            batch.ERROR_WORKER_DIED,
            batch.ERROR_WORKER_DIED,
        ]


# =============================================================================
# The Polars cap inside a real worker
# =============================================================================


@pytest.mark.skipif(
    (os.cpu_count() or 1) < 2,
    reason="a single-core box cannot distinguish a capped worker from an uncapped one",
)
class TestWorkerPolarsCap:
    """The cap is applied in the worker, and this process is never touched.

    ``tests/conftest.py`` sets ``POLARS_MAX_THREADS=1`` for the whole session, so
    a child would inherit the cap even with no initializer at all — which would
    make this test green in both states. Both cases therefore clear the variable
    from THIS process first, and the uncapped control asserts a thread pool the
    size of the box. That control is the discriminator; without it the test
    proves nothing.
    """

    @staticmethod
    def _unset_in_parent(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(worker_bootstrap.POLARS_THREADS_ENV_VAR, raising=False)

    def test_the_initializer_caps_the_worker_before_polars_is_imported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real spawned worker reports one Polars thread, not the core count.

        Both work items are stdlib/Polars module-level callables, pickled by
        reference — so the only thing this asserts about is the initializer.
        ``pl.thread_pool_size`` is the load-bearing one: it is fixed when Polars
        is first imported in the child, which happens when the work item is
        unpickled, i.e. strictly after ``_process_worker`` runs the initializer.
        """
        self._unset_in_parent(monkeypatch)

        with batch._make_executor(1, 1) as executor:
            assert (
                executor.submit(os.getenv, worker_bootstrap.POLARS_THREADS_ENV_VAR).result() == "1"
            )
            assert executor.submit(pl.thread_pool_size).result() == 1

    def test_an_uncapped_worker_sizes_to_the_box(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control: without the initializer the child takes every core."""
        self._unset_in_parent(monkeypatch)

        with batch._make_executor(1, None) as executor:
            assert (
                executor.submit(os.getenv, worker_bootstrap.POLARS_THREADS_ENV_VAR).result() is None
            )
            assert executor.submit(pl.thread_pool_size).result() == os.cpu_count()

    def test_this_process_environment_is_never_mutated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression this design exists to prevent.

        The old implementation held the cap in the PARENT's environ for the
        pool's lifetime, so two batches running concurrently on the UI's
        ``ThreadPoolExecutor`` could steal each other's value and leave a worker
        uncapped with no log and no symptom. Nothing in this process may change.
        """
        self._unset_in_parent(monkeypatch)

        with batch._make_executor(1, 1) as executor:
            executor.submit(os.getenv, "PATH").result()
            assert worker_bootstrap.POLARS_THREADS_ENV_VAR not in os.environ

        assert worker_bootstrap.POLARS_THREADS_ENV_VAR not in os.environ

    def test_zero_threads_is_refused_where_it_would_bite(self) -> None:
        """Polars accepts 0 at import and panics one stage into the run."""
        with pytest.raises(ValueError, match="must be >= 1"):
            configure_worker_process(0)


# =============================================================================
# The process boundary
# =============================================================================


class TestProcessBoundary:
    """Windows spawn pickles everything that crosses; nothing may hold a frame."""

    def test_the_job_carries_only_plain_values(self, tmp_path: Path) -> None:
        request = _request(
            _entity_scopes("E1"), tmp_path, cache_root=tmp_path / "cache", framework="BASEL_3_1"
        )
        job = batch._build_job(request, request.scopes[0], "run-1")

        assert all(
            isinstance(value, str | date | Decimal | type(None))
            for value in dataclasses.asdict(job).values()
        ), dataclasses.asdict(job)
        assert job.cache_dir == str(tmp_path / "cache" / "run-1")

    def test_the_job_round_trips_through_pickle(self, tmp_path: Path) -> None:
        request = _request(_entity_scopes("E1"), tmp_path)
        job = batch._build_job(request, request.scopes[0], "run-1")

        assert pickle.loads(pickle.dumps(job)) == job

    def test_the_outcome_round_trips_through_pickle(self) -> None:
        """The response comes BACK across the boundary — paths, never frames."""
        outcome = batch._JobOutcome(response=_response("E1"), worker_pid=123)

        restored = pickle.loads(pickle.dumps(outcome))

        assert restored == outcome
        assert restored.response is not None
        assert restored.response.results_path == Path("no-such-results.parquet")


# =============================================================================
# Serial / parallel equivalence — real pipeline, real process pool
# =============================================================================


class TestSerialParallelEquivalence:
    """The only coverage of the true-parallel path.

    Spawns two worker processes over a one-row book (~5s). Not skipped under
    xdist on purpose: a skipped equivalence test looks exactly like a passing
    one, and the whole point of the serial fallback is that it must agree with
    the path it replaces.
    """

    def test_parallel_and_serial_batches_agree(self, tmp_path: Path) -> None:
        from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

        data_path = tmp_path / "data"
        data_path.mkdir()
        write_mandatory_minimum(data_path)
        scopes = (ScopeSpec(framework="CRR"), ScopeSpec(framework="BASEL_3_1"))

        def request(cache: str, max_workers: int) -> BatchRequest:
            return BatchRequest(
                scopes=scopes,
                data_path=data_path,
                reporting_date=date(2027, 1, 1),
                cache_root=tmp_path / cache,
                max_workers=max_workers,
                # Independent runs on both paths: reuse would serve the second
                # batch from the first and there would be nothing to compare.
                reuse_runs=False,
            )

        serial = run_batch(request("serial", 1))
        parallel = run_batch(request("parallel", 2))

        assert serial.parallel is False
        assert parallel.parallel is True
        assert parallel.max_workers == 2
        assert all(r.success for r in serial), [r.errors for r in serial]
        assert all(r.success for r in parallel), [r.errors for r in parallel]

        # The detector: without this, a silent degradation to serial would let
        # every other assertion in this test pass.
        assert [r.worker_pid for r in serial] == [os.getpid(), os.getpid()]
        assert all(r.worker_pid not in (None, os.getpid()) for r in parallel)

        for index, scope in enumerate(scopes):
            lhs = serial.results[index].response
            rhs = parallel.results[index].response
            assert lhs is not None and rhs is not None
            assert lhs.framework == scope.framework == rhs.framework
            assert lhs.summary == rhs.summary
            assert lhs.output_floor_summary == rhs.output_floor_summary
            assert_frame_equal(lhs.collect_results(), rhs.collect_results())
