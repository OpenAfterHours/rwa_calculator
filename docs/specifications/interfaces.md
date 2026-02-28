# Interfaces

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6.1 | Python API: `create_pipeline()` and `RWAService` for programmatic access | P0 | Done |
| FR-6.2 | Interactive web UI via Marimo for scenario analysis and exploration | P1 | Done |
| FR-6.3 | CLI entry point (`rwa-calc-ui`) for launching the web interface | P2 | Done |
| FR-6.4 | API input validation with clear error messages | P1 | Done |

## Python API

- `create_pipeline()` — primary entry point for programmatic RWA calculation
- `RWAService` — higher-level service wrapper

## Marimo Web UI

Interactive workbooks for scenario analysis, exposure drill-down, and regulatory exploration.

## CLI

- `rwa-calc-ui` — launches the Marimo web interface

## Status
All interface requirements implemented.
