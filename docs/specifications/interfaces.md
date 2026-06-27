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
- `GET /api/export/{parquet|csv|excel|corep}` — download an export

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
