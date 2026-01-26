# RWA Calculator Specifications

This section contains the formal specifications for the RWA Calculator, written in Gherkin syntax. These specifications serve as:

1. **Living documentation** - Human-readable descriptions of business rules and regulatory treatments
2. **Acceptance criteria** - Clear definition of expected behaviour for each scenario
3. **Executable tests** - Automated verification that the calculator meets requirements

## How to Read Feature Files

Feature files use Gherkin syntax, designed to be readable by both technical and non-technical stakeholders:

```gherkin
Feature: Brief description of the capability

  Scenario: Description of a specific case
    Given [initial context/preconditions]
    When [action is performed]
    Then [expected outcome]
```

## Specification Index

### CRR Framework (Current - Until December 2026)

| Specification | Description | Regulatory Reference |
|--------------|-------------|---------------------|
| [SA Risk Weights](crr/sa-risk-weights.md) | Standardised Approach risk weights by exposure class and CQS | CRR Art. 112-134 |
| [Supporting Factors](crr/supporting-factors.md) | SME (0.7619) and infrastructure (0.75) factors | CRR Art. 501, 501a |
| [F-IRB Calculation](crr/firb-calculation.md) | Foundation IRB with supervisory LGD | CRR Art. 153-154, 161-163 |
| [A-IRB Calculation](crr/airb-calculation.md) | Advanced IRB with internal estimates | CRR Art. 153-154 |
| [Credit Conversion Factors](crr/credit-conversion-factors.md) | CCF for off-balance sheet items | CRR Art. 111, 166 |
| [Credit Risk Mitigation](crr/credit-risk-mitigation.md) | Collateral haircuts and guarantees | CRR Art. 192-241 |
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

## Scenario Coverage by Test Group

### Group A: Standardised Approach
Covers risk weight determination for all SA exposure classes:
- Sovereigns (CQS 1-6)
- Institutions (including UK 30% deviation)
- Corporates (rated and unrated)
- Retail (fixed 75%)
- Residential mortgages (LTV-based)
- Commercial real estate

### Group B: Foundation IRB
Covers F-IRB calculation components:
- PD floor (0.03%)
- Supervisory LGD (45% senior, 75% subordinated)
- Corporate correlation formula
- SME firm-size adjustment
- Maturity adjustment
- Expected loss

### Group C: Advanced IRB
Covers A-IRB with internal estimates:
- Internal LGD application
- Internal CCF application
- FI scalar (1.25×) for large financials

### Group D: Credit Risk Mitigation
Covers CRM techniques:
- Credit conversion factors
- Financial collateral haircuts
- FX mismatch haircut (8%)
- Guarantee substitution

### Group E: Slotting
Covers specialised lending:
- Slotting categories (Strong to Default)
- HVCRE elevated risk weights
- Project/Object/Commodities finance

### Group F: Supporting Factors
Covers CRR-specific factors:
- SME supporting factor
- Infrastructure supporting factor

### Group G: Provisions
Covers provision treatment:
- SA deduction from exposure
- IRB expected loss comparison
- IFRS 9 stage recognition

### Group H: Basel 3.1 Differences
Covers framework changes:
- Removal of supporting factors
- Removal of 1.06 scaling factor
- Output floor (72.5% of SA)
- Differentiated PD floors
- LGD floors for A-IRB

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

These specifications are executable using `pytest-bdd`. See the [BDD Testing Guide](../development/bdd.md) for implementation details.
