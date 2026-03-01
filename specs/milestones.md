# Release Milestones & Risks

## v1.0 — Production-Ready CRR (Target: Q1 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1.1 | All CRR acceptance tests passing (74/74) | 71/74 (3 fixture gaps) |
| M1.2 | Performance benchmarks documented | Done |
| M1.3 | Full MkDocs documentation site | Done |
| M1.4 | PyPI package published | Done (v0.1.28) |
| M1.5 | Interactive web UI (Marimo) | Done |
| M1.6 | CI/CD pipeline (lint, typecheck, tests) | Partial |
| M1.7 | Complete remaining 3 acceptance tests (CRR-A7, A8, C3) | Not Started |

## v1.1 — Basel 3.1 Core (Target: Q2 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M2.1 | Basel 3.1 expected outputs (workbook reference calcs) | Not Started |
| M2.2 | LTV-based residential RE risk weights (CRE20.71) | Not Started |
| M2.3 | Differentiated PD floors by exposure class | Not Started |
| M2.4 | A-IRB LGD floors (CRE32) | Not Started |
| M2.5 | Basel 3.1 acceptance tests | Not Started |
| M2.6 | Output floor phase-in validation | Partial (engine done, tests pending) |

## v1.2 — Dual-Framework Comparison (Target: Q3 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M3.1 | Side-by-side CRR vs Basel 3.1 RWA comparison | Done |
| M3.2 | Capital impact analysis (delta RWA) | Done |
| M3.3 | Transitional floor schedule modelling | Done |
| M3.4 | Enhanced Marimo workbooks for impact analysis | Not Started |

## v2.0 — Enterprise Features (Future)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M4.1 | COREP template generation | Not Started |
| M4.2 | Batch processing with Parquet I/O | Partial |
| M4.3 | Stress testing integration | Not Started |
| M4.4 | Portfolio-level concentration metrics | Not Started |
| M4.5 | REST API | Not Started |

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| PRA amends Basel 3.1 before go-live | Medium | Medium | Framework-configurable design; parameters in `data/tables/` |
| Performance degrades at 10M+ | Medium | Low | Polars LazyFrame scales linearly; benchmark suite includes 1M+ |
| IRB formula precision | High | Low | `Decimal` for regulatory params; `polars-normal-stats` for stats |
| Scope creep into market/op risk | Medium | Medium | Explicit out-of-scope; modular architecture |
