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
| [Framework Differences](../framework-comparison/technical-reference.md) | Key changes from CRR including output floor, PD/LGD floors | PRA PS1/26 |

See the [CRR vs Basel 3.1](../framework-comparison/index.md) section for comprehensive comparison documentation.

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

### Group H: Complex/Combined
Covers multi-approach and combined scenarios:

- Mixed SA/IRB portfolios
- Multi-level hierarchy with CRM
- Combined supporting factors with output floor

### Group I: Defaulted Exposures
Covers defaulted exposure treatment:

- F-IRB defaulted (K=0, CRR Art. 153(1)(ii))
- A-IRB defaulted (K=max(0, LGD−BEEL), CRR Art. 154(1)(i))
- Defaulted with CRM adjustments

### Basel 3.1 Groups
Basel 3.1 scenarios mirror the CRR structure with additional framework-specific tests:

- B31-A through B31-H: Same structure as CRR groups with Basel 3.1 rule changes
- B31-D7: Parameter substitution (guarantee-driven IRB→SA CCF/RW substitution)
- B31-F: Output floor phase-in (50%–72.5%, 2027–2032)

### Comparison Groups
Dual-framework comparison scenarios:

- M3.1: Side-by-side CRR vs Basel 3.1 RWA comparison
- M3.2: Capital impact analysis with delta decomposition by driver
- M3.3: Transitional floor schedule modelling (2027–2032)

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
| `CRR-H` | CRR Complex/Combined |
| `CRR-I` | CRR Defaulted Exposures |
| `B31-A` | Basel 3.1 Standardised Approach |
| `B31-B` | Basel 3.1 Foundation IRB |
| `B31-C` | Basel 3.1 Advanced IRB |
| `B31-D` | Basel 3.1 Credit Risk Mitigation |
| `B31-E` | Basel 3.1 Slotting Approach |
| `B31-F` | Basel 3.1 Output Floor |
| `B31-G` | Basel 3.1 Provisions |
| `B31-H` | Basel 3.1 Complex/Combined |
| `M3.1` | Dual-framework comparison |
| `M3.2` | Capital impact analysis |
| `M3.3` | Transitional floor modelling |
| `HIER-` | Hierarchy scenarios |
| `CLASS-` | Classification scenarios |

## For Developers

These specifications are verified through acceptance tests in `tests/acceptance/`. See the [Testing Guide](../development/testing.md) for details on running tests.
