# Overview

## Product

| Field | Value |
|-------|-------|
| **Product** | rwa-calc |
| **Version** | 0.1.28 (Pre-Release) |
| **Author** | OpenAfterHours |
| **License** | Apache 2.0 |

## Executive Summary

The RWA Calculator is a Python-based regulatory capital engine that computes Risk-Weighted Assets (RWA) for credit risk under the UK implementation of the Basel framework. It supports both the current CRR regime (Basel 3.0, effective until 31 Dec 2026) and the forthcoming Basel 3.1 rules (PRA PS9/24, effective 1 Jan 2027) from a single codebase.

The product targets UK-regulated banks, building societies, and risk technology teams who need a transparent, auditable, and performant RWA calculation engine — whether for production use, parallel runs, regulatory impact analysis, or educational purposes.

## Problem Statement

UK credit institutions face a major regulatory transition: migrating from CRR (EU 575/2013 as onshored) to Basel 3.1 (PRA PS9/24) by 1 January 2027. Key pain points:

- **Dual-regime operation**: Firms must run CRR and Basel 3.1 in parallel during the transition period
- **Opacity of vendor solutions**: Commercial RWA engines are black-box systems with limited auditability
- **Regulatory complexity**: 9 exposure classes, 4 calculation approaches, CRM, supporting factors, output floors
- **Performance at scale**: Calculations must complete in seconds for hundreds of thousands to millions of exposures

## Target Users

| Persona | Role | Needs |
|---------|------|-------|
| **Credit Risk Analyst** | Day-to-day RWA reporting, scenario analysis | Accurate calculations, clear audit trail, what-if capability |
| **Risk Model Developer** | Building, validating IRB models | Transparent IRB formulas, configurable PD/LGD/EAD inputs |
| **Regulatory Capital Manager** | Capital planning, ICAAP, stress testing | Dual-framework comparison, transitional schedule modelling |
| **Risk Technology Engineer** | Integrating RWA into firm infrastructure | Python API, documented contracts, performance guarantees |
| **Internal Auditor** | Validating RWA methodology | Full regulatory traceability, pre/post-CRM breakdowns |
| **Student / Educator** | Learning Basel credit risk | Interactive workbooks, hand-calculated reference scenarios |

## Scope

### In Scope

| Area | Description |
|------|-------------|
| **Credit Risk RWA** | SA, F-IRB, A-IRB, Slotting, Equity |
| **Regulatory Frameworks** | UK CRR (Basel 3.0) and UK Basel 3.1 (PRA PS9/24) |
| **Credit Risk Mitigation** | Collateral (9 types), guarantees (substitution), provisions (drawn-first SA, EL shortfall IRB) |
| **Supporting Factors** | CRR SME tiered factor (0.7619/0.85), infrastructure factor (0.75) |
| **Output Floor** | Basel 3.1 output floor with transitional phase-in (50%–72.5%, 2027–2032) |
| **Multi-Currency** | FX conversion with haircut adjustments |
| **Hierarchies** | Multi-level counterparty (10 levels, rating inheritance) and facility hierarchies |
| **Interfaces** | Python API, Marimo web UI, CLI |

### Out of Scope

Market Risk (FRTB), Operational Risk, CVA Risk, Securitisation, Large Exposures, Leverage Ratio, COREP (stub only), Database integration, Authentication/Multi-tenancy.

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.13+ |
| DataFrame Engine | Polars | 1.0+ |
| Statistical Functions | polars-normal-stats | 0.2+ |
| SQL Engine | DuckDB | 0.9+ |
| Data Validation | Pydantic | 2.0+ |
| Serialisation | PyArrow | 14.0+ |
| Excel Export | fastexcel | 0.19+ |
| Web UI | Marimo | — |
| Documentation | MkDocs (Material) | — |
| Testing | Pytest + pytest-benchmark | — |
| Linting | Ruff | — |
| Type Checking | Mypy | — |
| Package Manager | UV | — |
