# Product Requirements Document (PRD)

## RWA Calculator — Basel 3.1 Credit Risk RWA Engine

| Field | Value |
|-------|-------|
| **Product** | rwa-calc |
| **Version** | 0.1.28 (Pre-Release) |
| **Author** | OpenAfterHours |
| **Status** | Draft |
| **Last Updated** | 2026-02-28 |
| **License** | Apache 2.0 |

---

## 1. Executive Summary

The RWA Calculator is a Python-based regulatory capital engine that computes Risk-Weighted Assets (RWA) for credit risk under the UK implementation of the Basel framework. It supports both the current CRR regime (Basel 3.0, effective until 31 Dec 2026) and the forthcoming Basel 3.1 rules (PRA PS9/24, effective 1 Jan 2027) from a single codebase.

The product targets UK-regulated banks, building societies, and risk technology teams who need a transparent, auditable, and performant RWA calculation engine — whether for production use, parallel runs, regulatory impact analysis, or educational purposes.

---

## 2. Problem Statement

### Industry Challenge

UK credit institutions face a major regulatory transition: migrating from CRR (EU 575/2013 as onshored) to Basel 3.1 (PRA PS9/24) by 1 January 2027. This affects every firm's capital adequacy calculation. Key pain points include:

- **Dual-regime operation**: Firms must run CRR and Basel 3.1 in parallel during the transition period to assess capital impact, yet most internal systems are hardwired to a single framework.
- **Opacity of vendor solutions**: Commercial RWA engines are black-box systems with limited auditability, making it difficult for risk teams to validate results, explain calculations to regulators, or perform what-if analysis.
- **Regulatory complexity**: Credit risk RWA involves 9 exposure classes, 4 calculation approaches (SA, F-IRB, A-IRB, Slotting), credit risk mitigation (collateral, guarantees, provisions), supporting factors, output floors, and numerous special treatments — each with framework-specific rules.
- **Performance at scale**: UK banks typically hold hundreds of thousands to millions of exposure records. Calculations must complete in seconds, not minutes, for interactive analysis and overnight batch processing.

### Product Opportunity

An open-source, framework-configurable RWA engine with full audit trails, regulatory traceability, and native performance addresses all of these gaps. It gives risk teams a tool they can inspect, extend, and trust — while delivering the computational throughput needed for production-scale portfolios.

---

## 3. Target Users

### Primary Personas

| Persona | Role | Needs |
|---------|------|-------|
| **Credit Risk Analyst** | Day-to-day RWA reporting, scenario analysis, regulatory submissions | Accurate calculations, clear audit trail, exposure-level drill-down, what-if capability |
| **Risk Model Developer** | Building, validating, and calibrating IRB models | Transparent IRB formulas, configurable PD/LGD/EAD inputs, easy integration with internal model pipelines |
| **Regulatory Capital Manager** | Capital planning, ICAAP, stress testing, output floor impact | Dual-framework comparison, transitional schedule modelling, aggregated views by approach/class |
| **Risk Technology Engineer** | Integrating RWA calculation into firm infrastructure | Python API, documented contracts, protocol-based extensibility, performance guarantees |

### Secondary Personas

| Persona | Role | Needs |
|---------|------|-------|
| **Internal Auditor** | Validating RWA calculation methodology | Full regulatory traceability, pre/post-CRM breakdowns, error/warning logs |
| **Student / Educator** | Learning Basel credit risk framework | Interactive workbooks, hand-calculated reference scenarios, regulatory documentation links |
| **Regulator (PRA examiner)** | Reviewing firm's RWA methodology | Transparent formulas, scenario-level expected outputs, regulatory article references |

---

## 4. Product Scope

### 4.1 In Scope

| Area | Description |
|------|-------------|
| **Credit Risk RWA** | Standardised Approach (SA), Foundation IRB (F-IRB), Advanced IRB (A-IRB), Specialised Lending (Slotting), Equity |
| **Regulatory Frameworks** | UK CRR (Basel 3.0) and UK Basel 3.1 (PRA PS9/24) |
| **Credit Risk Mitigation** | Collateral (9 types with supervisory haircuts), guarantees (substitution approach), provisions (drawn-first SA deduction, IRB EL shortfall/excess) |
| **Supporting Factors** | CRR SME tiered factor (0.7619/0.85), infrastructure factor (0.75) |
| **Output Floor** | Basel 3.1 output floor with transitional phase-in schedule (50%–72.5%, 2027–2032) |
| **Multi-Currency** | FX conversion to configurable target currency with haircut adjustments |
| **Hierarchies** | Multi-level counterparty hierarchies (up to 10 levels) with rating inheritance; multi-level facility hierarchies with drawn aggregation |
| **Input Validation** | Non-blocking error accumulation with categorised error codes |
| **Audit Trail** | Pre/post-CRM RWA tracking, guarantee benefit attribution, full calculation transparency |
| **Interfaces** | Python API, interactive web UI (Marimo), CLI entry point |
| **Documentation** | MkDocs site with user guide, architecture docs, API reference, regulatory specifications |

### 4.2 Out of Scope (Current Release)

| Area | Rationale |
|------|-----------|
| Market Risk RWA (FRTB) | Different risk type — separate product |
| Operational Risk RWA | Different risk type — separate product |
| CVA Risk | Different risk type — separate product |
| Securitisation | Specialised framework (CRR Part 3, Title II, Chapter 5) — future consideration |
| Large Exposures | Reporting framework, not RWA calculation |
| Leverage Ratio | Different capital metric |
| COREP/Regulatory Reporting Templates | Stub exists; full implementation deferred |
| Database / Data Warehouse Integration | Users provide data as Parquet/CSV/DataFrames; persistence is out of scope |
| User Authentication / Multi-Tenancy | Standalone tool, not a hosted SaaS |

---

## 5. Functional Requirements

### FR-1: Calculation Approaches

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.1 | SA risk weight calculation for all 9 exposure classes (CRR Art. 112–134) | P0 | Done |
| FR-1.2 | SA risk weight calculation for Basel 3.1 (CRE20–22), including LTV-based RE weights | P0 | Partial |
| FR-1.3 | F-IRB capital requirement (K) calculation: PD, supervisory LGD, maturity adjustment (CRR Art. 153, 161–163) | P0 | Done |
| FR-1.4 | A-IRB capital requirement: own-estimate PD, LGD, EAD with PD floors (CRR Art. 143, 154) | P0 | Done |
| FR-1.5 | A-IRB LGD floors per Basel 3.1 (CRE32) | P1 | Not Started |
| FR-1.6 | Specialised lending slotting (CRR Art. 153(5)) with maturity band risk weights | P0 | Done |
| FR-1.7 | Equity risk weights: SA (Art. 133) and IRB Simple (Art. 155) | P1 | Done |
| FR-1.8 | Defaulted exposure treatment: F-IRB (K=0) and A-IRB (K=max(0, LGD−BEEL)) | P0 | Done |
| FR-1.9 | Differentiated PD floors per Basel 3.1 (sovereign, bank, corporate, retail sub-classes) | P1 | Not Started |

### FR-2: Credit Risk Mitigation

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-2.1 | Collateral recognition for 9 types: cash, government bonds, corporate bonds, covered bonds, listed equity, other equity, real estate, receivables, physical | P0 | Done |
| FR-2.2 | Supervisory haircut application (CRR Art. 224) with maturity mismatch (Art. 238) and currency mismatch (+8%) | P0 | Done |
| FR-2.3 | Overcollateralisation ratios (CRR Art. 230): 1.0x financial, 1.25x receivables, 1.4x RE/physical | P0 | Done |
| FR-2.4 | Multi-level collateral allocation: direct (loan), facility (pro-rata), counterparty (pro-rata) | P0 | Done |
| FR-2.5 | Guarantee substitution: split RWA into covered (guarantor RW) and uncovered (original RW) portions | P0 | Done |
| FR-2.6 | Cross-approach CCF substitution: SA CCFs on guaranteed portion of IRB exposures (CRR Art. 166/194) | P0 | Done |
| FR-2.7 | Provision resolution: drawn-first deduction for SA, EL shortfall/excess for IRB | P0 | Done |

### FR-3: Pipeline & Data Flow

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-3.1 | Six-stage immutable pipeline: Load → Hierarchy → Classify → CRM → Calculate → Aggregate | P0 | Done |
| FR-3.2 | Support for multi-level counterparty hierarchies with rating inheritance (up to 10 levels) | P0 | Done |
| FR-3.3 | Multi-level facility hierarchies with drawn aggregation and sub-facility exclusion | P0 | Done |
| FR-3.4 | Automatic exposure classification by approach (SA/F-IRB/A-IRB/Slotting) based on config and exposure attributes | P0 | Done |
| FR-3.5 | Non-blocking input validation with categorised error accumulation (DQ, CL, SA, IRB, CRM codes) | P0 | Done |
| FR-3.6 | Multi-currency FX conversion with configurable target currency | P1 | Done |
| FR-3.7 | Results caching with lazy loading | P2 | Done |

### FR-4: Output & Reporting

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-4.1 | Aggregated RWA by approach (SA, F-IRB, A-IRB, Slotting, Equity) | P0 | Done |
| FR-4.2 | Aggregated RWA by exposure class (9 classes) | P0 | Done |
| FR-4.3 | Basel 3.1 output floor calculation with transitional phase-in schedule | P1 | Done |
| FR-4.4 | Pre/post-CRM RWA breakdown with guarantee benefit attribution | P1 | Done |
| FR-4.5 | Exposure-level detail output with all intermediate calculations | P1 | Done |
| FR-4.6 | COREP template generation (CRR reporting) | P3 | Not Started |
| FR-4.7 | Excel / Parquet export of results | P2 | Partial |

### FR-5: Configuration

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-5.1 | Framework toggle: CRR vs Basel 3.1 via factory methods (`CalculationConfig.crr()` / `.basel_3_1()`) | P0 | Done |
| FR-5.2 | IRB approach configuration: F-IRB, A-IRB, or hybrid (per-exposure-class permissions) | P0 | Done |
| FR-5.3 | Configurable reporting date (drives regulatory parameter selection) | P0 | Done |
| FR-5.4 | Configurable PD floors, LGD floors, output floor percentage | P1 | Partial |
| FR-5.5 | Configurable scaling factor (1.06 CRR, 1.0 Basel 3.1) | P0 | Done |
| FR-5.6 | Target currency for FX conversion | P1 | Done |

### FR-6: Interfaces

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6.1 | Python API: `create_pipeline()` and `RWAService` for programmatic access | P0 | Done |
| FR-6.2 | Interactive web UI via Marimo for scenario analysis and exploration | P1 | Done |
| FR-6.3 | CLI entry point (`rwa-calc-ui`) for launching the web interface | P2 | Done |
| FR-6.4 | API input validation with clear error messages | P1 | Done |

---

## 6. Non-Functional Requirements

### NFR-1: Performance

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-1.1 | Full CRR pipeline execution at 100K exposures | < 2 seconds | Met (~1.7s) |
| NFR-1.2 | Full CRR pipeline execution at 1M exposures | < 20 seconds | Met |
| NFR-1.3 | Interactive analysis response time (single scenario) | < 500ms | Met |
| NFR-1.4 | Memory efficiency for 1M+ exposure portfolios | < 4 GB | Met |

### NFR-2: Correctness

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-2.1 | Acceptance test pass rate (CRR scenarios) | 100% | 96% (71/74, 3 skip) |
| NFR-2.2 | Hand-calculated expected outputs for all acceptance scenarios | Full coverage | Done (38 CRR scenarios) |
| NFR-2.3 | Numerical precision: RWA values within 0.01% of hand calculations | < 0.01% error | Met |
| NFR-2.4 | Regulatory article traceability for all risk weight lookups | Full coverage | Done |

### NFR-3: Reliability

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-3.1 | Unit test coverage | > 1,000 tests | Met (1,050) |
| NFR-3.2 | Zero data loss — immutable pipeline with frozen dataclass bundles | Guaranteed | Met |
| NFR-3.3 | Graceful handling of invalid data (error accumulation, not exceptions) | All data quality issues | Met |

### NFR-4: Maintainability

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-4.1 | Full type annotations on all public functions | 100% | Met |
| NFR-4.2 | Protocol-based interfaces for all pipeline components | All 6 stages | Met |
| NFR-4.3 | Ruff linting and formatting with zero violations | CI-enforced | Met |
| NFR-4.4 | Module-level docstrings with pipeline position and regulatory references | All modules | Met |

### NFR-5: Extensibility

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-5.1 | New calculation approaches addable via Protocol implementation | Pluggable | Met |
| NFR-5.2 | New regulatory framework configurable via `CalculationConfig` factory | Addable | Met |
| NFR-5.3 | Polars namespace extensions for domain-specific operations | 8 namespaces | Met |

### NFR-6: Documentation

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-6.1 | MkDocs documentation site with user guide, architecture, API reference | Comprehensive | Met (59 pages) |
| NFR-6.2 | Interactive Marimo workbooks with reference implementations | All CRR scenarios | Met |
| NFR-6.3 | Regulatory reference links to PRA Rulebook, CRR articles, BCBS standards | All calculations | Met |

---

## 7. Architecture Overview

### Pipeline Architecture

```
Input Data (Parquet/CSV/DataFrames)
  │
  ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1: Loader                                    │
│  Parse & validate raw input tables                  │
│  → RawDataBundle                                    │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 2: Hierarchy Resolver                        │
│  Resolve counterparty trees, facility trees,        │
│  inherit ratings, unify drawn/undrawn exposures     │
│  → ResolvedHierarchyBundle                          │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 3: Classifier                                │
│  Assign exposure class + calculation approach        │
│  (SA / F-IRB / A-IRB / Slotting / Equity)           │
│  → ClassifiedExposuresBundle                        │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 4: CRM Processor                             │
│  Provisions → CCF → EAD → Collateral → Guarantees  │
│  → CRMAdjustedBundle                                │
└─────────────────────┬───────────────────────────────┘
                      │
           ┌──────────┼──────────┐
           ▼          ▼          ▼
┌────────────┐ ┌───────────┐ ┌──────────┐
│ SA Calc    │ │ IRB Calc  │ │ Slotting │
│            │ │ (F/A-IRB) │ │ Calc     │
└─────┬──────┘ └─────┬─────┘ └────┬─────┘
      │               │            │
      └───────────────┼────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 6: Aggregator                                │
│  Combine results, apply output floor (Basel 3.1),   │
│  produce summary views                              │
│  → AggregatedResultBundle                           │
└─────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Polars LazyFrame throughout** | Vectorised operations, query optimisation, and parallel execution — 50–100x faster than row-by-row Python |
| **Immutable frozen dataclass bundles** | Prevents accidental mutation between pipeline stages; enables safe parallelism |
| **Protocol interfaces (not ABC)** | Structural typing allows loose coupling; components satisfy contracts without inheritance |
| **Error accumulation (not exceptions)** | Data quality issues should be reported, not crash the pipeline; enables partial results |
| **Single codebase, dual framework** | CRR→Basel 3.1 transition requires running both in parallel; avoids code duplication |
| **Polars namespace extensions** | Domain-specific operations (`.sa.calculate()`, `.irb.calculate_k()`) read naturally and are discoverable |

---

## 8. Data Model

### Input Tables

| Table | Key Columns | Description |
|-------|-------------|-------------|
| `counterparties` | `counterparty_reference`, `entity_type`, `country`, `turnover`, `sector` | Obligor/guarantor master data |
| `facilities` | `facility_reference`, `counterparty_reference`, `facility_type`, `limit`, `currency` | Credit facilities (RCFs, term loans, mortgages) |
| `loans` | `loan_reference`, `facility_reference`, `drawn_amount`, `interest_rate` | Drawn exposure records |
| `contingents` | `contingent_reference`, `facility_reference`, `nominal_amount`, `bs_type` | Off-balance sheet items (LCs, guarantees, commitments) |
| `collateral` | `collateral_reference`, `collateral_type`, `market_value`, `currency` | Collateral pledged against exposures |
| `guarantees` | `guarantee_reference`, `guarantor_reference`, `covered_amount` | Third-party guarantees |
| `provisions` | `provision_reference`, `beneficiary_reference`, `provision_amount` | Specific and general provisions |
| `ratings` | `entity_reference`, `rating_agency`, `rating`, `rating_type` | External (S&P, Moody's) and internal ratings |
| `org_mappings` | `parent_reference`, `child_reference` | Counterparty parent-subsidiary relationships |
| `facility_mappings` | `parent_reference`, `child_reference` | Facility-to-exposure relationships |
| `lending_groups` | `group_reference`, `member_reference` | Retail lending group connections |
| `fx_rates` | `currency_pair`, `rate` | FX conversion rates |

### Output Fields (Exposure-Level)

| Field | Description |
|-------|-------------|
| `exposure_reference` | Unique exposure identifier |
| `exposure_class` | Assigned class (e.g., CORPORATE, RETAIL, INSTITUTION) |
| `calculation_approach` | SA, FIRB, AIRB, SLOTTING, or EQUITY |
| `ead_pre_crm` | Exposure at default before CRM |
| `ead_post_crm` | Exposure at default after CRM |
| `risk_weight` | Applied risk weight (SA) or effective RW (IRB: K × 12.5) |
| `rwa` | Final risk-weighted assets |
| `rwa_pre_crm` | RWA before credit risk mitigation |
| `rwa_post_crm` | RWA after credit risk mitigation |
| `supporting_factor` | Applied supporting factor (SME/infrastructure) |
| `pd` | Probability of default (IRB) |
| `lgd` | Loss given default (IRB) |
| `maturity` | Effective maturity in years (IRB) |
| `expected_loss` | EL = PD × LGD × EAD (IRB) |
| `errors` | List of validation/calculation warnings |

---

## 9. Regulatory Compliance Matrix

### CRR (Basel 3.0) — Current UK Rules

| CRR Article | Topic | Status |
|-------------|-------|--------|
| Art. 111 | Credit conversion factors (CCF) | Done |
| Art. 112–134 | SA risk weights by exposure class | Done |
| Art. 143–154 | IRB approach (F-IRB and A-IRB) | Done |
| Art. 153(5) | Specialised lending slotting | Done |
| Art. 155 | Equity IRB Simple | Done |
| Art. 133 | Equity SA | Done |
| Art. 161–163 | F-IRB supervisory LGD | Done |
| Art. 153(1)(ii) | Defaulted exposure F-IRB (K=0) | Done |
| Art. 154(1)(i) | Defaulted exposure A-IRB (K=max(0, LGD−BEEL)) | Done |
| Art. 207–224 | Collateral eligibility and haircuts | Done |
| Art. 213 | Guarantee substitution | Done |
| Art. 224 | Supervisory haircut table | Done |
| Art. 230 | Overcollateralisation ratios | Done |
| Art. 238 | Maturity mismatch adjustment | Done |
| Art. 501 | SME supporting factor (tiered) | Done |
| Art. 501a | Infrastructure supporting factor | Done |

### Basel 3.1 (PRA PS9/24) — Upcoming UK Rules

| BCBS Standard | Topic | Status |
|---------------|-------|--------|
| CRE20.7–26 | SA risk weights (revised) | Partial |
| CRE20.71 | LTV-based residential RE risk weights | Not Started |
| CRE30–36 | IRB approach revisions | Partial |
| CRE32.9–12 | Overcollateralisation (carried forward) | Done |
| CRE32 | A-IRB LGD floors | Not Started |
| — | Differentiated PD floors | Not Started |
| — | Output floor (50%–72.5% phase-in) | Done |
| — | Removal of 1.06 scaling factor | Done |
| — | Removal of SME supporting factor | Done |
| — | Removal of equity IRB | Done |

---

## 10. Release Milestones

### v1.0 — Production-Ready CRR (Target: Q1 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1.1 | All CRR acceptance tests passing (74/74) | 71/74 (3 fixture gaps) |
| M1.2 | Performance benchmarks documented and reproducible | Done |
| M1.3 | Full MkDocs documentation site | Done |
| M1.4 | PyPI package published | Done (v0.1.28) |
| M1.5 | Interactive web UI (Marimo) operational | Done |
| M1.6 | CI/CD pipeline with linting, type checking, and tests | Partial |
| M1.7 | Complete remaining 3 acceptance tests (CRR-A7, A8, C3) | Not Started |

### v1.1 — Basel 3.1 Core (Target: Q2 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M2.1 | Basel 3.1 expected outputs (workbook reference calculations) | Not Started |
| M2.2 | LTV-based residential RE risk weights (CRE20.71) | Not Started |
| M2.3 | Differentiated PD floors by exposure class | Not Started |
| M2.4 | A-IRB LGD floors (CRE32) | Not Started |
| M2.5 | Basel 3.1 acceptance tests | Not Started |
| M2.6 | Output floor phase-in validation (2027–2032 schedule) | Partial (engine done, tests pending) |

### v1.2 — Dual-Framework Comparison (Target: Q3 2026)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M3.1 | Side-by-side CRR vs Basel 3.1 RWA comparison output | Not Started |
| M3.2 | Capital impact analysis (delta RWA by approach, class, portfolio) | Not Started |
| M3.3 | Transitional floor schedule modelling (year-by-year impact) | Not Started |
| M3.4 | Enhanced Marimo workbooks for regulatory impact analysis | Not Started |

### v2.0 — Enterprise Features (Future)

| Milestone | Description | Status |
|-----------|-------------|--------|
| M4.1 | COREP template generation (C07.00, C08.01, C08.02) | Not Started |
| M4.2 | Batch processing mode with Parquet I/O | Partial |
| M4.3 | Stress testing integration (PD/LGD shift scenarios) | Not Started |
| M4.4 | Portfolio-level concentration metrics | Not Started |
| M4.5 | REST API for system integration | Not Started |

---

## 11. Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| **Regulatory Accuracy** | 100% acceptance test pass rate | Automated test suite against hand-calculated expected outputs |
| **Performance** | < 2s for 100K exposures, < 20s for 1M | Benchmark tests (`pytest-benchmark`) |
| **Test Coverage** | > 1,200 tests across unit, acceptance, benchmark | `pytest --co -q \| wc -l` |
| **Documentation Completeness** | All public APIs documented; all calculations traced to CRR/BCBS articles | MkDocs site review |
| **Adoption** | PyPI downloads, GitHub stars, community contributions | PyPI stats, GitHub analytics |
| **Transition Readiness** | Full Basel 3.1 coverage before 1 Jan 2027 go-live | Acceptance test pass rate for B31 scenarios |

---

## 12. Dependencies & Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.13+ | Core runtime |
| DataFrame Engine | Polars | 1.0+ | Vectorised LazyFrame operations |
| Statistical Functions | polars-normal-stats | 0.2+ | CDF, PPF, PDF for IRB formulas |
| SQL Engine | DuckDB | 0.9+ | Complex join operations (where needed) |
| Data Validation | Pydantic | 2.0+ | API input validation |
| Serialisation | PyArrow | 14.0+ | Parquet I/O |
| Excel Export | fastexcel | 0.19+ | XLSX output |
| Configuration | PyYAML | 6.0+ | YAML-based config files |
| Web UI | Marimo | — | Interactive notebooks |
| Documentation | MkDocs (Material) | — | Documentation site |
| Testing | Pytest + pytest-benchmark | — | Unit, acceptance, and performance tests |
| Linting | Ruff | — | Linting and formatting |
| Type Checking | Mypy | — | Static type analysis |
| Package Manager | UV | — | Dependency management |

---

## 13. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **PRA amends Basel 3.1 rules before go-live** | Medium — may require parameter updates or new treatments | Medium | Framework-configurable design; regulatory parameters isolated in `data/tables/`; monitoring PRA consultation papers |
| **Performance degrades at 10M+ scale** | Medium — some firms have very large portfolios | Low | Polars LazyFrame architecture scales linearly; benchmark suite includes 1M+ tests; streaming engine available for memory-constrained runs |
| **IRB formula precision** | High — small rounding errors compound across millions of exposures | Low | `Decimal` type for regulatory parameters; hand-calculated reference values validated to 0.01%; `polars-normal-stats` for statistical functions (avoids scipy float issues) |
| **Scope creep into market/op risk** | Medium — dilutes focus, increases maintenance burden | Medium | Explicit out-of-scope declaration; modular architecture allows separate products for other risk types |
| **Open-source contribution quality** | Low — incorrect PRs could introduce regulatory errors | Medium | Comprehensive acceptance test suite as guardrail; all PRs must pass 1,200+ tests; regulatory traceability in docstrings |

---

## 14. Glossary

| Term | Definition |
|------|------------|
| **RWA** | Risk-Weighted Assets — credit exposures multiplied by risk weights to determine capital requirements |
| **CRR** | Capital Requirements Regulation (EU 575/2013 as onshored into UK law) — current Basel 3.0 implementation |
| **Basel 3.1** | BCBS finalisation of Basel III reforms, implemented in UK via PRA PS9/24, effective 1 Jan 2027 |
| **SA** | Standardised Approach — risk weights assigned by exposure class and external rating |
| **F-IRB** | Foundation Internal Ratings-Based — firm provides PD, regulator sets LGD/CCF |
| **A-IRB** | Advanced Internal Ratings-Based — firm provides PD, LGD, EAD, CCF |
| **Slotting** | Specialised lending approach — risk weights assigned by supervisory category (Strong/Good/Satisfactory/Weak/Default) |
| **CRM** | Credit Risk Mitigation — collateral, guarantees, and provisions that reduce capital requirements |
| **EAD** | Exposure at Default — estimated exposure amount at the time of default |
| **PD** | Probability of Default — estimated likelihood of obligor default within one year |
| **LGD** | Loss Given Default — estimated loss as percentage of EAD if default occurs |
| **CCF** | Credit Conversion Factor — converts off-balance sheet amounts to on-balance sheet equivalents |
| **CQS** | Credit Quality Step — standardised rating scale (1=AAA/AA, 2=A, 3=BBB, etc.) |
| **Output Floor** | Basel 3.1 minimum: IRB RWA must be at least X% of SA-equivalent RWA |
| **PRA** | Prudential Regulation Authority — UK banking regulator |
| **BCBS** | Basel Committee on Banking Supervision — global standard setter |
| **SME** | Small and Medium Enterprise — turnover < EUR 50m, eligible for supporting factor |

---

## Appendix A: Acceptance Test Summary

### CRR Scenarios (74 tests)

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-A: Standardised Approach | A1–A12 | 14 | 86% (12/14, 2 skip) |
| CRR-C: Advanced IRB | C1–C3 | 7 | 86% (6/7, 1 skip) |
| CRR-D: Credit Risk Mitigation | D1–D6 | 9 | 100% |
| CRR-E: Specialised Lending | E1–E4 | 9 | 100% |
| CRR-F: Supporting Factors | F1–F7 | 15 | 100% |
| CRR-G: Provisions | G1–G3 | 7 | 100% |
| CRR-H: Complex/Combined | H1–H4 | 4 | 100% |
| CRR-I: Defaulted Exposures | I1–I3 | 9 | 100% |
| **Total** | | **74** | **96%** |

### Basel 3.1 Scenarios (Planned)

| Group | Scenarios | Status |
|-------|-----------|--------|
| B31-A: SA (Revised) | A1–A10 | Not Started |
| B31-F: Output Floor | F1–F3 | Not Started |

---

## Appendix B: Regulatory References

| Reference | URL |
|-----------|-----|
| PRA Rulebook (CRR firms) | https://www.prarulebook.co.uk/pra-rules/crr-firms |
| UK CRR (EU 575/2013) | https://www.legislation.gov.uk/eur/2013/575/contents |
| PRA PS9/24 (Basel 3.1) | https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2 |
| BCBS CRE Standards | https://www.bis.org/basel_framework/standard/CRE.htm |
| PRA CP16/22 | https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards |
