# Interfaces

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6.1 | Python API: `create_pipeline()` and `CreditRiskCalc` for programmatic access | P0 | Done |
| FR-6.2 | Server-rendered web UI (FastAPI + Jinja) for running calculations, results exploration, and dual-framework comparison | P1 | Done |
| FR-6.3 | CLI entry point (`rwa-ui`) for launching the web interface | P2 | Done |
| FR-6.4 | API input validation with clear error messages | P1 | Done |
| FR-6.5 | REST API over `CreditRiskCalc` (calculate / validate / results / comparison / export) | P1 | Done |

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

## CLI

- `rwa-ui` — launches the server-rendered web UI + REST API

## Status
All interface requirements implemented.
