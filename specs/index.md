# RWA Calculator Specifications

This section contains the formal specifications for the RWA Calculator. These specifications serve as:

1. **Living documentation** - Human-readable descriptions of business rules and regulatory treatments
2. **Acceptance criteria** - Clear definition of expected behaviour for each scenario
3. **Traceability** - Each scenario maps to acceptance tests via scenario IDs

## Specification Index

### CRR Framework (Current - Until December 2026)

| Specification | Description | Regulatory Reference |
|--------------|-------------|---------------------|
| [SA Risk Weights](crr/sa-risk-weights.md) | Standardised Approach risk weights by exposure class and CQS | CRR Art. 112-134 |
| [Supporting Factors](crr/supporting-factors.md) | SME (0.7619) and infrastructure (0.75) factors | CRR Art. 501, 501a |
| [F-IRB Calculation](crr/firb-calculation.md) | Foundation IRB with supervisory LGD | CRR Art. 153-154, 161-163 |
| [A-IRB Calculation](crr/airb-calculation.md) | Advanced IRB with internal estimates | CRR Art. 153-154 |
| [Credit Conversion Factors](crr/credit-conversion-factors.md) | CCF for off-balance sheet items | CRR Art. 111, 166 |
| [Credit Risk Mitigation](crr/credit-risk-mitigation.md) | Collateral haircuts, guarantees, and overcollateralisation | CRR Art. 192-241 |
| [Slotting Approach](crr/slotting-approach.md) | Specialised lending categories | CRR Art. 147(8), 153(5) |
| [Provisions](crr/provisions.md) | Provision treatment and EL comparison | CRR Art. 158-159 |

### Basel 3.1 Framework (From January 2027)

| Specification | Description | Regulatory Reference |
|--------------|-------------|---------------------|
| [Framework Differences](basel31/framework-differences.md) | Key changes from CRR including output floor, PD/LGD floors | PRA PS9/24 |

### Common (Framework-Agnostic)

| Specification | Description |
|--------------|-------------|
| [Hierarchy & Classification](common/hierarchy-classification.md) | Counterparty hierarchy resolution and exposure classification |

### Project

| Specification | Description |
|--------------|-------------|
| [Overview](overview.md) | Executive summary, scope, users, technology stack |
| [Architecture](architecture.md) | Pipeline stages, design decisions, data model |
| [Configuration](configuration.md) | Framework toggle, IRB permissions, PD/LGD floors |
| [Output & Reporting](output-reporting.md) | Aggregation, output floor, COREP, export |
| [Interfaces](interfaces.md) | Python API, Marimo UI, CLI |
| [NFRs](nfr.md) | Performance, correctness, reliability targets |
| [Milestones](milestones.md) | Release plan, risks |
| [Regulatory Compliance](regulatory-compliance.md) | CRR + Basel 3.1 compliance matrix, acceptance tests |
| [Glossary](glossary.md) | Regulatory terms |

## Scenario Coverage by Test Group

### Group A: Standardised Approach
Covers risk weight determination for all SA exposure classes:

- Sovereigns (CQS 1-6 and unrated)
- Institutions (including UK 30% CQS 2 deviation)
- Corporates (rated and unrated)
- Retail (fixed 75%)
- Residential mortgages (LTV-based split at 80%)
- Commercial real estate (LTV-based with income cover test)

### Group B: Foundation IRB
Covers F-IRB calculation components:

- PD floor (0.03%)
- Supervisory LGD (45% senior, 75% subordinated)
- Corporate correlation formula with PD-dependent decay
- SME firm-size correlation adjustment
- Maturity adjustment
- Expected loss calculation
- 1.06 scaling factor

### Group C: Advanced IRB
Covers A-IRB with internal estimates:

- Internal LGD application
- Internal CCF application
- FI scalar (1.25x) for large financial institutions

### Group D: Credit Risk Mitigation
Covers CRM techniques:

- Financial collateral haircuts (CRR Art. 224)
- FX mismatch haircut (8%)
- Overcollateralisation requirements (CRR Art. 230)
- Guarantee substitution (CRR Art. 213-217)
- Multi-level collateral allocation (exposure, facility, counterparty)
- Maturity mismatch adjustment (CRR Art. 238)

### Group E: Slotting
Covers specialised lending:

- Slotting categories (Strong to Default)
- HVCRE elevated risk weights
- Project/Object/Commodities/IPRE finance types

### Group F: Supporting Factors
Covers CRR-specific factors:

- SME supporting factor (tiered: 0.7619 / 0.85)
- Infrastructure supporting factor (0.75)

### Group G: Provisions
Covers provision treatment:

- SA provision deduction from exposure
- IRB expected loss comparison

### Group H: Basel 3.1 Differences
Covers framework changes:

- Removal of supporting factors
- Removal of 1.06 scaling factor
- Output floor (72.5% of SA)
- Differentiated PD floors
- LGD floors for A-IRB
- Revised slotting risk weights

## Scenario ID Convention

Each scenario is tagged with an identifier for traceability:

| Prefix | Description |
|--------|-------------|
| `CRR-A` | CRR Standardised Approach |
| `CRR-B` | CRR Foundation IRB |
| `CRR-C` | CRR Advanced IRB |
| `CRR-D` | CRR Credit Risk Mitigation |
| `CRR-E` | CRR Slotting Approach |
| `CRR-F` | CRR Supporting Factors |
| `CRR-G` | CRR Provisions |
| `BASEL31-F` | Basel 3.1 Framework Differences |
| `HIER-` | Hierarchy scenarios |
| `CLASS-` | Classification scenarios |

## For Developers

These specifications are verified through acceptance tests in `tests/acceptance/`. See the [Testing Guide](../development/testing.md) for details on running tests.
