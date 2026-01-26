# BDD Testing Guide

This document describes how to implement and run BDD tests for the RWA Calculator using `pytest-bdd`.

## Feature File Location

Feature files are located in `docs/specifications/` to serve as living documentation accessible to both risk users and developers. See the [Specifications Index](../specifications/index.md) for the full list.

```
docs/specifications/
├── crr/                           # CRR (Basel 3.0) Framework
│   ├── sa_risk_weights.feature
│   ├── supporting_factors.feature
│   ├── firb_calculation.feature
│   ├── airb_calculation.feature
│   ├── credit_conversion_factors.feature
│   ├── credit_risk_mitigation.feature
│   ├── slotting_approach.feature
│   └── provisions.feature
├── basel31/                       # Basel 3.1 Framework
│   └── framework_differences.feature
└── common/                        # Framework-agnostic
    └── hierarchy_classification.feature

tests/bdd/
└── step_definitions/              # Step implementations
    ├── conftest.py
    ├── sa_steps.py
    ├── irb_steps.py
    └── ...
```

## Test Scenario Groups

### Group A: Standardised Approach (SA)
- Sovereign, institution, corporate risk weights by CQS
- Retail fixed 75% risk weight
- Residential mortgage LTV treatment (35%/75% split)
- Commercial real estate LTV bands
- Defaulted exposure treatment

### Group B: Foundation IRB (F-IRB)
- Supervisory LGD (45% senior, 75% subordinated)
- PD floor enforcement (0.03%)
- Corporate correlation formula
- SME firm-size correlation adjustment
- Maturity adjustment
- Expected loss calculation

### Group C: Advanced IRB (A-IRB)
- Internal LGD estimates
- Internal CCF estimates
- FI scalar (1.25×) for large financial institutions
- A-IRB vs F-IRB comparison

### Group D: Credit Risk Mitigation
- Credit conversion factors (SA and F-IRB)
- Financial collateral haircuts
- FX mismatch haircut (8%)
- Real estate collateral treatment
- Guarantee substitution
- Provision impact on exposure

### Group E: Slotting Approach
- Slotting categories (Strong to Default)
- HVCRE elevated risk weights
- Maturity adjustment for Strong/Good
- Specialised lending types (PF, OF, CF, IPRE)

### Group F: Supporting Factors (CRR only)
- SME supporting factor (0.7619)
- Infrastructure supporting factor (0.75)
- Combined factors

### Group G: Provisions
- SA provision deduction from exposure
- IRB expected loss calculation
- EL vs provisions comparison
- Tier 2 excess addition cap

### Group H: Basel 3.1 Differences
- No SME/infrastructure supporting factors
- No 1.06 scaling factor
- Output floor (72.5% of SA)
- Differentiated PD floors
- LGD floors for A-IRB
- Revised slotting risk weights

## Scenario ID Convention

Scenarios are tagged with identifiers that map to acceptance tests:

| Prefix   | Description                        |
|----------|-----------------------------------|
| CRR-A    | CRR Standardised Approach         |
| CRR-B    | CRR Foundation IRB                |
| CRR-C    | CRR Advanced IRB                  |
| CRR-D    | CRR Credit Risk Mitigation        |
| CRR-E    | CRR Slotting Approach             |
| CRR-F    | CRR Supporting Factors            |
| CRR-G    | CRR Provisions                    |
| BASEL31-F| Basel 3.1 Framework Differences   |
| HIER-    | Hierarchy scenarios               |
| CLASS-   | Classification scenarios          |
| APPROACH-| Approach assignment scenarios     |

## Running BDD Tests

Feature files are designed to be implemented using `pytest-bdd`.

### Installation

```bash
uv add pytest-bdd
```

### Example Step Definitions

```python
# tests/bdd/step_definitions/sa_steps.py

from pytest_bdd import scenarios, given, when, then, parsers
from pathlib import Path

# Reference feature files from docs/specifications/
SPECS_DIR = Path(__file__).parent.parent.parent.parent / "docs" / "specifications"
scenarios(str(SPECS_DIR / "crr" / "sa_risk_weights.feature"))

@given(parsers.parse('a counterparty "{id}" of type "{cpty_type}"'))
def counterparty_setup(id: str, cpty_type: str, context):
    context.counterparty = create_counterparty(id, cpty_type)

@when('the SA risk weight is calculated')
def calculate_sa_rw(context, calculator):
    context.result = calculator.calculate_sa(context.exposure)

@then(parsers.parse('the risk weight should be {rw}'))
def verify_risk_weight(context, rw: str):
    expected = parse_percentage(rw)
    assert context.result.risk_weight == pytest.approx(expected)
```

### Running Feature Tests

```bash
# Run all BDD tests
uv run pytest tests/bdd/

# Run specific feature file
uv run pytest --feature docs/specifications/crr/sa_risk_weights.feature

# Run by tag
uv run pytest tests/bdd/ -m "crr and sa"
```

## Gherkin Syntax Reference

### Basic Structure

```gherkin
@tag1 @tag2
Feature: Feature name
  As a [role]
  I need to [action]
  So that [benefit]

  Background:
    Given common setup steps

  Scenario: Scenario name
    Given [precondition]
    And [another precondition]
    When [action]
    Then [expected result]
    And [another expected result]
```

### Scenario Outlines

```gherkin
Scenario Outline: Risk weight by CQS
  Given a counterparty with CQS <cqs>
  When the SA risk weight is calculated
  Then the risk weight should be <risk_weight>

  Examples:
    | cqs | risk_weight |
    | 1   | 20%         |
    | 2   | 50%         |
    | 3   | 100%        |
```

### Data Tables

```gherkin
Scenario: Portfolio calculation
  Given a portfolio with exposures:
    | exposure_id | amount     | cqs |
    | EXP_001     | £1,000,000 | 1   |
    | EXP_002     | £500,000   | 2   |
  When the total RWA is calculated
  Then the result should reflect weighted sum
```

## Regulatory References

### CRR (Current Framework)
- CRR Art. 112-134: Standardised Approach
- CRR Art. 147-154: IRB Approach
- CRR Art. 158-163: LGD and EL
- CRR Art. 166: CCF
- CRR Art. 192-241: Credit Risk Mitigation
- CRR Art. 501: SME Supporting Factor

### Basel 3.1 (From January 2027)
- PRA PS9/24: UK Implementation
- BCBS CRE20-22: Standardised Approach
- BCBS CRE30-36: IRB Approach

## Next Steps

- [Testing Guide](testing.md) - General testing approach
- [Extending](extending.md) - Adding new features
- [Code Style](code-style.md) - Coding conventions
