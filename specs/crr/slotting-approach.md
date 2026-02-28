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

Under CRR, the same risk weights apply regardless of HVCRE status:

| Category | Risk Weight | Description |
|----------|-------------|-------------|
| Strong | 70% | Highly favourable financial and risk characteristics |
| Good | 70% | Favourable characteristics |
| Satisfactory | 115% | Acceptable characteristics |
| Weak | 250% | Weakened characteristics |
| Default | 0% | Fully provisioned |

## Basel 3.1 Slotting Risk Weights

Under Basel 3.1, HVCRE receives elevated risk weights:

| Category | Non-HVCRE | HVCRE |
|----------|-----------|-------|
| Strong | 50% | 100% |
| Good | 70% | 70% |
| Satisfactory | 100% | 150% |
| Weak | 150% | 150% |
| Default | 350% | 350% |

## Equity

### SA (CRR Art. 133)

Risk weights by equity type (listed, unlisted, strategic holdings).

### IRB Simple (CRR Art. 155)

- Listed equity: 190%
- Unlisted equity: 290%
- Other equity: 370%

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
