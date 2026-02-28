# Architecture & Pipeline

## Pipeline Architecture

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

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Polars LazyFrame throughout** | Vectorised operations, query optimisation, parallel execution — 50–100x faster than row-by-row Python |
| **Immutable frozen dataclass bundles** | Prevents accidental mutation between stages; enables safe parallelism |
| **Protocol interfaces (not ABC)** | Structural typing allows loose coupling; components satisfy contracts without inheritance |
| **Error accumulation (not exceptions)** | Data quality issues reported, not crash the pipeline; enables partial results |
| **Single codebase, dual framework** | CRR→Basel 3.1 transition requires running both in parallel; avoids code duplication |
| **Polars namespace extensions** | Domain-specific operations (`.sa.calculate()`, `.irb.calculate_k()`) read naturally |

## Pipeline & Data Flow Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-3.1 | Six-stage immutable pipeline: Load → Hierarchy → Classify → CRM → Calculate → Aggregate | P0 | Done |
| FR-3.2 | Multi-level counterparty hierarchies with rating inheritance (up to 10 levels) | P0 | Done |
| FR-3.3 | Multi-level facility hierarchies with drawn aggregation and sub-facility exclusion | P0 | Done |
| FR-3.4 | Automatic exposure classification by approach based on config and exposure attributes | P0 | Done |
| FR-3.5 | Non-blocking input validation with categorised error accumulation | P0 | Done |
| FR-3.6 | Multi-currency FX conversion with configurable target currency | P1 | Done |
| FR-3.7 | Results caching with lazy loading | P2 | Done |

## Data Model

### Input Tables

| Table | Key Columns | Description |
|-------|-------------|-------------|
| `counterparties` | `counterparty_reference`, `entity_type`, `country`, `turnover`, `sector` | Obligor/guarantor master data |
| `facilities` | `facility_reference`, `counterparty_reference`, `facility_type`, `limit`, `currency` | Credit facilities |
| `loans` | `loan_reference`, `facility_reference`, `drawn_amount`, `interest_rate` | Drawn exposure records |
| `contingents` | `contingent_reference`, `facility_reference`, `nominal_amount`, `bs_type` | Off-balance sheet items |
| `collateral` | `collateral_reference`, `collateral_type`, `market_value`, `currency` | Collateral pledged |
| `guarantees` | `guarantee_reference`, `guarantor_reference`, `covered_amount` | Third-party guarantees |
| `provisions` | `provision_reference`, `beneficiary_reference`, `provision_amount` | Specific/general provisions |
| `ratings` | `entity_reference`, `rating_agency`, `rating`, `rating_type` | External and internal ratings |
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
