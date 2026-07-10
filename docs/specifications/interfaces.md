# Interfaces

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6.1 | Python API: `create_pipeline()` and `CreditRiskCalc` for programmatic access | P0 | Done |
| FR-6.2 | Server-rendered web UI (FastAPI + Jinja) for running calculations, results exploration, and dual-framework comparison | P1 | Done |
| FR-6.3 | CLI entry point (`rwa-ui`) for launching the web interface | P2 | Done |
| FR-6.4 | API input validation with clear error messages | P1 | Done |
| FR-6.5 | REST API over `CreditRiskCalc` (calculate / validate / results / comparison / export) | P1 | Done |
| FR-6.6 | UI can write results to a user-chosen local output folder (calc-time + on-demand save), loopback-guarded | P1 | Done |
| FR-6.7 | Reconciliation can reuse a completed calculation instead of re-running the pipeline (UI: fingerprint-verified reuse checkbox; REST: explicit `run_id`) | P1 | Done |

## Python API

- `create_pipeline()` — primary entry point for programmatic RWA calculation
- `CreditRiskCalc` — higher-level service wrapper

## REST API (`ui/app` + `api/rest.py`)

The `rwa-ui` server (`rwa_calc.ui.app.main:main`) is a FastAPI + Jinja app that
serves the read-only surface and mounts the REST API in the same process
(`create_api_app` / `api_router`, also importable standalone):

- `POST /api/calculate` — run a calculation; returns a `run_id` + summary
- `POST /api/validate` — validate a data directory
- `GET /api/results` — page exposure-level results for a run
- `GET /api/results/summary/{class|approach}` — portfolio summaries
- `POST /api/comparison` — dual-framework run with deltas (uses
  `DualFrameworkRunner` + `CapitalImpactAnalyzer`, transformed by
  `ui/views/comparison.py`)
- `POST /api/reconcile` — reconcile against a mapped legacy output; an optional
  `run_id` reuses a registered calculation instead of re-running the pipeline
  (an explicit run_id is an instruction: unknown → 404, mismatched
  framework/date, failed run or vanished results → 422 — never a silent
  recompute)
- `GET /api/export/{parquet|csv|excel|corep}` — download an export

### Calculation reuse for reconciliation (FR-6.7)

A reconciliation embeds a full pipeline run for our side
(`CreditRiskCalc.reconcile`). When the identical calculation has already run,
that run is reused instead:

- `CreditRiskCalc.reconcile(settings, calculation=...)` accepts an
  already-completed `CalculationResponse`; the embedded pipeline run is skipped
  and the supplied response's cached results parquet is reconciled. The caller
  owns freshness verification. The response also carries the our-side run back
  (`ReconciliationResponse.calculation`) so callers can index it.
- `rwa_calc.api.run_index` is that verification: it fingerprints each
  calculation request (parameters **plus** a stat-based `(relpath, size,
  mtime_ns)` signature of every input file the loader would read, captured
  *before* the run) and indexes successful runs. `find_reusable` recomputes the
  signature at lookup time, so any input-file change, addition or removal —
  or a vanished results parquet — misses and forces a recompute.
- **Every run seeds the index**: the UI calculator, the UI comparison page
  (both embedded framework runs are formatted and registered; the comparison
  itself still computes from the rich bundle — its capital-impact attribution
  needs floor-impact/pre-factor frames a cached response does not persist), a
  full UI reconciliation's embedded run, `POST /api/calculate` and
  `POST /api/comparison`.
- **Persistence**: the UI app calls `run_index.configure_persistence(state
  home)` at startup — registrations write through to
  `$RWA_STATE_DIR/run_index.json` (default `~/.rwa_calc/`), each UI run's
  parquet cache lives under `<state>/runs/<run_id>/` (`run_cache_dir`), and the
  index (capped at `MAX_INDEXED_RUNS`, oldest evicted) is reloaded at the next
  startup with reloaded runs re-registered so `/results/{run_id}` resolves
  again. Run directories are never deleted mid-session; unreferenced ones are
  swept at the next startup. The standalone REST app stays in-process only.
- The UI reconciliation form offers a pre-ticked reuse checkbox when a fresh
  matching run exists (a passive "input data has changed" note when only the
  data moved), re-verifies at submit time, and degrades silently to a full run
  on any miss; on reuse the stepper ticks every engine stage instantly and
  parks on the reconcile tail. The calculator page shows a non-blocking
  "already ran — view its results" banner on a fresh match.

### UI page routes that write to disk (FR-6.6)

The UI can write a run's results to a folder on the local machine (the server is
the user's own process, so a server-side write is a write to the user's disk):

- `POST /calculate` — accepts an optional `output_folder` + `output_formats`; when
  set, the background worker writes the selected formats *after* the run, into a
  run-stamped `rwa_export_<run_id>` subfolder of the chosen folder.
- `POST /results/{run_id}/save` — re-exports an already-computed run (looked up by
  `run_id`) to a chosen folder without recomputing.

**Security posture (deliberate reversal).** The REST export endpoints keep user
input out of the filesystem path (temp dir + literal filenames). FR-6.6 instead
lets a user-supplied `output_folder` become a real write target — acceptable only
because the app is loopback single-user. It is guarded by
`TrustedHostMiddleware(["localhost", "127.0.0.1"])` (DNS-rebinding) and a
same-origin check (`require_same_origin`) on the write routes; `output_folder` is
validated by `validate_output_path` (absolute, parent exists, no reserved names),
and `run_id` never becomes a path component.

## CLI

- `rwa-ui` — launches the server-rendered web UI + REST API

## Status
All interface requirements implemented.
