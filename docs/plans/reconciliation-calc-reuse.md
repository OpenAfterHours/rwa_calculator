# Reconciliation — Reuse of a Prior Calculation Run

> **Status:** Implemented 2026-07-10 (phases 1–5 **and** the §6 follow-ons — see per-item notes) · **Owner:** orchestrator (main session) · **Created:** 2026-07-10
> **Scope decision:** in-session reuse only (process lifetime). Cross-restart persistence and
> comparison-page reuse are recorded as follow-ons, not in scope.

---

## 1. Why — the gap

The UI offers three flows: **calculate**, **compare**, **reconcile**. Reconciliation always re-runs
the full engine pipeline even when the operator has just run the identical calculation:

- `CreditRiskCalc.reconcile()` calls `self.calculate()` unconditionally
  (`api/service.py:210`) before joining against the legacy output. There is no way to hand it an
  existing result.
- The UI reconciliation worker constructs a **fresh** `CreditRiskCalc` per submit
  (`ui/app/main.py::_reconciliation_worker`, ~line 835) — it never consults the run registry.
- The run registry `_RUNS` (`api/rest.py:62`) already holds every completed
  `CalculationResponse`, but it is keyed only by an opaque `run_id`. Nothing indexes runs by
  *calculation parameters*, so "has this calculation already been run?" is unanswerable today.
- Every `CreditRiskCalc` instance gets a **fresh temp cache dir** (`api/service.py:96-99`,
  `tempfile.mkdtemp(prefix="rwa_cache_")`), so `ResultsCache.load_cached()`
  (`api/results_cache.py:167`) never finds a prior run's parquet either.

Consequence: calculate → reconcile on the same portfolio costs **two full pipeline runs**. On a
large book the second run is pure waste — the reconciliation itself only needs the results frame.

## 2. Why the fix is cheap

`reconcile()` consumes exactly one thing from the calculation: `calc_response.scan_results()`
(`api/service.py:227`) — a lazy scan of the results parquet that every successful calculation
already sinks to disk (`api/results_cache.py::sink_results`) and that `_RUNS` already holds a
handle to (`CalculationResponse.results_path`, `api/models.py:204`). Reuse is literally "pass the
previous `CalculationResponse` instead of recomputing it". No engine changes are needed.

The one correctness hazard is **staleness**: the input data directory may have changed since the
cached run. A regulatory tool must never silently reconcile against stale results, so reuse must be
gated on a fingerprint of both the calculation parameters and the input files.

## 3. Design

### 3.1 Calculation fingerprint (new module `api/run_index.py`)

```python
@dataclass(frozen=True, slots=True)
class CalculationFingerprint:
    data_path: str          # str(Path(data_path).resolve())
    framework: str
    reporting_date: str     # ISO
    permission_mode: str
    data_format: str
    base_currency: str
    eur_gbp_rate: str       # str(Decimal) — exact
    data_signature: tuple[tuple[str, int, int], ...]  # (relpath, size, mtime_ns) sorted
```

- `data_signature` walks `data_path` recursively for the loader-relevant extensions
  (`*.parquet` for parquet format — including `config/model_permissions.parquet` — `*.csv` for
  csv) and records `(relative path, size, mtime_ns)`. Stat-only: cheap even for many files, no
  hashing of contents.
- Module also owns the index and lookup:
  - `register(fingerprint, run_id, completed_at)` — latest run wins per fingerprint.
  - `find_reusable(params) -> ReusableRun | None` — recomputes the *current* data signature,
    compares against the stored fingerprint, and returns the run only when: fingerprint matches
    exactly, the run is still present in `_RUNS`, its `results_path` still exists on disk, **and**
    `response.success` is `True`. `ReusableRun` carries `run_id`, `response`, `completed_at`.
- In-process only (module-level dict), mirroring the `_RUNS` trade-off. Thread-safety matches the
  existing registries (GIL-atomic dict ops from the single progress-executor worker).

### 3.2 Service seam

`CreditRiskCalc.reconcile(settings, calculation: CalculationResponse | None = None)`:

- `calculation is None` → current behaviour (run `self.calculate()`).
- `calculation` provided → skip the pipeline, keep the existing `success` guard
  (`api/service.py:212-225`) operating on the supplied response, then proceed with
  `calculation.scan_results()` into `ReconciliationRunner` unchanged.
- The *caller* owns fingerprint verification — the service seam stays dumb and testable.

### 3.3 UI flow

**Form render (`GET /reconciliation`)** — `_reconciliation_form_context` additionally calls
`find_reusable(...)` with the form's effective values and, when a hit exists, passes a
`reusable_run` context block to `reconciliation.html`:

> ☑ Use results from the calculation completed at 14:32 (CRR · 2026-12-31 · standardised)
> Untick to recompute from source data.

- Checkbox `reuse_calculation`, **default ON when a fresh matching run exists**; absent otherwise.
- When a prior run exists but the data signature no longer matches, show a passive note instead:
  "Input data has changed since the last calculation — it will be recomputed." (no checkbox).

**Submit (`POST /reconciliation`)** — re-verify at submit time (the form snapshot may be stale):
call `find_reusable(...)` again with the *posted* values. Only when the checkbox was ticked AND the
lookup still hits does the worker receive the cached `CalculationResponse`. A silent fall-through
to full recompute is the correct degraded path (never an error).

**Worker (`_reconciliation_worker`)** — new optional `calculation:` argument:

- Reuse path: immediately `job.mark_stage(...)` every engine stage in `STAGE_SEQUENCE` (the SSE
  replay in `_stage_event_stream` ticks them all at once in the browser), then run
  `reconcile(settings, calculation=...)` — the legacy load + join executes under the existing
  `recon_reconcile` tail step exactly as today, including `_warm_reconciliation_frames`.
- The progress page (`reconciling.html` / `RECON_STAGE_SEQUENCE`) needs **no change**: stages tick
  instantly and the stepper parks on "Reconcile & summarise".

**Registry seeding** — `_calculation_worker` computes the fingerprint from its request params and
calls `run_index.register(...)` after `register_run_with_id` (success only). The reconciliation
worker's *embedded* full calculation is not registered (its `CalculationResponse` is internal to
`reconcile()`); acceptable for v1, noted as a follow-on.

### 3.4 REST parity

`POST /api/reconcile` gains an optional `run_id: str | None` body field:

- Provided → look up `_RUNS[run_id]`; 404 if unknown. Verify the request's
  framework/reporting_date/permission_mode match the stored response's fields and that
  `results_path` exists — 422 on mismatch (the caller asked to reuse an incompatible run; do not
  silently recompute on an explicit request).
- Absent → current behaviour.

The REST contract stays the shared substrate for the UI and embedders; the UI form flow uses the
fingerprint index, the API uses the explicit `run_id` (callers already hold it from
`/api/calculate`).

## 4. Phases

| # | Phase | Contents | Tests first (TDD) |
|---|---|---|---|
| 1 | Service seam | `reconcile(settings, calculation=...)` in `api/service.py` | Unit: reuse path skips pipeline (spy on `calculate`), failed supplied response short-circuits, default path unchanged |
| 2 | Run index | `api/run_index.py` — fingerprint, data signature, register/find | Unit: param mismatch → miss; file mtime/size change → miss; file added/removed → miss; failed run → miss; deleted parquet → miss; latest-wins |
| 3 | UI wiring | `_calculation_worker` seeds index; `_reconciliation_worker` reuse path + instant stage ticks; form banner + checkbox in `reconciliation.html`; submit-time re-verify | Integration: calc → reconcile(reuse) runs pipeline once (count via monkeypatched orchestrator); stale-data submit falls through to full run; SSE replays all stages |
| 4 | REST parity | Optional `run_id` on `ReconcileRequest` + verify-or-422 | Contract: reuse honoured, unknown run_id → 404, mismatched params → 422 |
| 5 | Docs + changelog | `docs/specifications/interfaces.md` (FR-6.x), UI docs page, `docs/appendix/changelog.md` | `uv run zensical build` green |

Phases 1–2 are pure `api/` additions with no UI dependency and can land together; 3 depends on
both; 4 and 5 are independent of each other after 3.

## 5. Decisions taken (and why)

- **Default = reuse when fresh, with an opt-out checkbox.** The fingerprint guard makes reuse safe
  by construction; forcing an opt-in would leave the waste in place for the default flow. The
  operator keeps an explicit "recompute from source" escape hatch.
- **Stat-based signature (size + mtime_ns), not content hashes.** Content hashing a multi-GB
  portfolio to save a pipeline run defeats the purpose. mtime+size false-negatives (touch without
  change) merely recompute — conservative in the right direction. False positives (same
  size+mtime, different bytes) require deliberate tampering; out of threat model for a local tool.
- **No cross-restart persistence in v1.** Result parquets live in per-process temp dirs
  (`rwa_cache_*`); persisting the index without moving the cache home would dangle. Moving the
  cache to `$RWA_STATE_DIR` is the natural phase-2 follow-on and is deliberately split out.
- **Silent fall-through on stale reuse at submit (UI), hard 422 (REST).** The UI checkbox is a
  preference ("use it if you still can"); the API `run_id` is an explicit instruction whose
  violation must not be papered over.

## 6. Follow-ons — DONE 2026-07-10 (second pass)

- **Persist across restarts** — DONE. `run_index.configure_persistence(state home)` at UI app
  startup: write-through JSON index at `$RWA_STATE_DIR/run_index.json`, per-run parquet caches at
  `<state>/runs/<run_id>/` (`run_cache_dir`, passed as `CreditRiskCalc(cache_dir=...)` by the UI
  workers), cap `MAX_INDEXED_RUNS=10` (oldest evicted, index entry only), orphan run dirs swept at
  the NEXT startup (never mid-session — a `/results/{run_id}` page may still serve them). Reloaded
  runs are re-registered into `_RUNS` so their results pages resolve after a restart.
- **Comparison-page reuse** — DONE as *seeding*: `_compute_comparison` formats both embedded
  framework runs into `CalculationResponse`s (`_seed_comparison_runs`, best-effort) and indexes
  them; `POST /api/comparison` + `POST /api/calculate` index theirs too. The comparison
  deliberately does NOT *consume* cached runs: `CapitalImpactAnalyzer` attribution needs the
  `floor_impact` frame and `rwa_pre_factor`/`rwa_pre_floor` columns that a cached response does
  not persist — consuming would silently change the waterfall. Revisit only if the cache ever
  persists those frames.
- **Seed the index from a reconciliation's embedded calculation** — DONE.
  `ReconciliationResponse.calculation` carries the our-side run back; the UI recon worker
  registers + indexes it after a full run (never after a reuse).
- **Calculator-page reuse** — DONE. Non-blocking "already ran — view its results" banner on
  `/calculator` when the pre-filled form matches a fresh run.
- **`ValidationResponse.cached_path`** — DONE: deleted (field + `/api/validate` serialization).

## 7. Verification gate

Per project convention: `uv run python scripts/arch_check.py`, `uv run ruff check`, `uv run ty`,
`uv run pytest tests/` (dev-loop default), plus a manual `/run`-style drive of the UI:
calculate → reconcile with reuse (observe instant stage ticks + identical recon output to a cold
run) → touch an input parquet → reconcile again (observe full recompute banner path).
