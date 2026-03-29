# Slotting Approach Specification

Specialised lending slotting categories for project finance, object finance, commodities finance, and IPRE.

**Regulatory Reference:** CRR Articles 147(8), 153(5)

**Test Group:** CRR-E

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1.6 | Specialised lending slotting with maturity band risk weights | P0 | Done |
| FR-1.7 | Equity risk weights: SA (Art. 133) and IRB Simple (Art. 155) | P1 | Done |

---

## Overview

The slotting approach assigns risk weights based on qualitative category assessment rather than PD/LGD modelling. It applies to specialised lending exposures where banks cannot estimate PD using standard IRB models.

## Specialised Lending Types

| Type | Abbreviation | Description |
|------|-------------|-------------|
| Project Finance | PF | Long-term financing of infrastructure/industrial projects |
| Object Finance | OF | Financing of physical assets (ships, aircraft, etc.) |
| Commodities Finance | CF | Structured financing of commodity inventories |
| Income-Producing RE | IPRE | Commercial real estate where repayment depends on rental income |
| High Volatility CRE | HVCRE | CRE with higher risk characteristics |

## CRR Slotting Risk Weights

Under CRR Art. 153(5), risk weights are differentiated by HVCRE status and remaining maturity.

### Non-HVCRE (Table 1)

| Category | Remaining Maturity >= 2.5yr | Remaining Maturity < 2.5yr |
|----------|----------------------------|---------------------------|
| Strong | 70% | 50% |
| Good | 90% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% | 0% |

### HVCRE (Table 2)

| Category | Remaining Maturity >= 2.5yr | Remaining Maturity < 2.5yr |
|----------|----------------------------|---------------------------|
| Strong | 95% | 70% |
| Good | 120% | 95% |
| Satisfactory | 140% | 140% |
| Weak | 250% | 250% |
| Default | 0% | 0% |

## Basel 3.1 Slotting Risk Weights

Under Basel 3.1 (BCBS CRE33), slotting risk weights are split into three distinct tables
differentiating Non-HVCRE operational, Project Finance pre-operational, and HVCRE exposures.

### Non-HVCRE Operational (OF, CF, IPRE, PF Operational)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
| Default | 0% (EL) |

### Project Finance Pre-Operational

| Category | Risk Weight |
|----------|-------------|
| Strong | 80% |
| Good | 100% |
| Satisfactory | 120% |
| Weak | 350% |
| Default | 0% (EL) |

### HVCRE

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |
| Default | 0% (EL) |

See [Framework Differences](../basel31/framework-differences.md) for full Basel 3.1 detail.

## Equity

### SA (CRR Art. 133)

Risk weights by equity type (listed, unlisted, strategic holdings).

### IRB Simple (CRR Art. 155)

- Exchange-traded / listed equity: 290%
- Private equity (diversified): 190%
- All other equity (unlisted, speculative, etc.): 370%

### Basel 3.1

Removal of equity IRB — all equity falls to SA treatment.

## Key Scenarios

| Scenario ID | Description |
|-------------|-------------|
| CRR-E | Project finance, Strong category (70%) |
| CRR-E | Object finance, Satisfactory category (115%) |
| CRR-E | HVCRE exposure, Weak category (250%) |
| CRR-E | Defaulted specialised lending (0%, fully provisioned) |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-E: Specialised Lending | E1–E4 | 9 | 100% |
