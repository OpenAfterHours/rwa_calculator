# Slotting Approach Specification

Basel 3.1 revised risk weights for specialised lending slotting categories, with maturity
split removal and no separate pre-operational project finance distinction.

**Regulatory Reference:** PRA PS1/26 Art. 147(8), Art. 153(5), CRE33
**Test Group:** B31-E

---

## Requirements Status

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-5.1 | Revised slotting risk weight tables (flat, no maturity split) | P0 | Done |
| FR-5.2 | No separate pre-operational PF table (PRA deviation from BCBS) | P0 | Done |
| FR-5.3 | HVCRE elevated risk weights | P0 | Done |
| FR-5.4 | Default category EL treatment (0% RW) | P0 | Done |

---

## Overview

Basel 3.1 revises the specialised lending slotting approach risk weights. The key changes are:

1. **Maturity split removed** — CRR distinguished < 2.5 years from ≥ 2.5 years; Basel 3.1 uses
   flat weights regardless of maturity
2. **No pre-operational PF distinction** — PRA does not adopt the BCBS separate table for
   pre-operational project finance (CRE33.6 Table 6); all PF uses the standard non-HVCRE table
3. **Revised weight levels** — lower weights for Strong/Good categories, higher for Weak

### Key Changes from CRR

| Category | CRR (< 2.5yr / ≥ 2.5yr) | Basel 3.1 (flat) | Change |
|----------|--------------------------|-------------------|--------|
| Strong | 50% / 70% | 70% | Increase for short, same for long |
| Good | 70% / 90% | 90% | Increase for short, same for long |
| Satisfactory | 115% / 115% | 115% | Unchanged |
| Weak | 250% / 250% | 250% | Unchanged |
| Default | 0% (EL) / 0% (EL) | 0% (EL) | Unchanged |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Table"
    BCBS CRE33.6 Table 6 defines separate elevated weights for pre-operational project finance
    (80%/100%/120%/350%). The PRA **does not adopt** this distinction — all project finance uses
    the standard non-HVCRE table regardless of operational status. This is confirmed by the
    absence of a separate pre-operational table in PRA PS1/26.

---

## Risk Weight Tables

### Non-HVCRE Specialised Lending (PF, IPRE, OF, CF)

**Art. 153(5), Table**

Applies to: Project Finance, Income-Producing Real Estate, Object Finance, Commodities Finance.

| Slotting Category | Risk Weight | EL Component |
|-------------------|-------------|--------------|
| Strong | 70% | 0.4% |
| Good | 90% | 0.8% |
| Satisfactory | 115% | 2.8% |
| Weak | 250% | 8.0% |
| Default | 0% | 50.0% |

### HVCRE Specialised Lending

**Art. 153(5), HVCRE Table**

High-Volatility Commercial Real Estate receives elevated weights to reflect the higher risk profile:

| Slotting Category | Risk Weight | EL Component |
|-------------------|-------------|--------------|
| Strong | 95% | 0.4% |
| Good | 120% | 0.8% |
| Satisfactory | 140% | 2.8% |
| Weak | 250% | 8.0% |
| Default | 0% | 50.0% |

!!! note "HVCRE vs Non-HVCRE"
    HVCRE is distinguished from standard CRE by the volatility of the underlying property
    cash flows and the speculative nature of the development. The classification is determined
    during the hierarchy/classification stage based on the `specialised_lending_type` input field.

### Subgrade Treatment

Within each slotting category, firms may assign sub-grades (A or B) for more granular
risk differentiation:

| Category | Sub-grade A | Sub-grade B |
|----------|------------|------------|
| Strong | 70% (non-HVCRE) / 95% (HVCRE) | 70% (non-HVCRE) / 95% (HVCRE) |
| Good | 90% (non-HVCRE) / 120% (HVCRE) | 90% (non-HVCRE) / 120% (HVCRE) |

!!! note "Basel 3.1 Subgrade Simplification"
    Under Basel 3.1, the removal of the maturity split means sub-grades A and B receive
    the same risk weight. Under CRR, sub-grade A received the shorter-maturity weight
    and sub-grade B the longer-maturity weight.

## Default Category (0% RW, EL Treatment)

For defaulted specialised lending exposures assigned to the Default slotting category:

- Risk weight = **0%** (no capital charge via RWA)
- Expected loss = **50%** of EAD
- The capital impact is captured through the EL shortfall/excess mechanism (Art. 159),
  not through the risk weight

This treatment is unchanged from CRR.

## Routing to Slotting

Under Basel 3.1, exposures are routed to slotting when:

1. The exposure is classified as specialised lending (PF, IPRE, HVCRE, OF, CF)
2. The firm does **not** have A-IRB permission for the sub-class (Art. 147A(2))
3. The firm has F-IRB or slotting permission

If the firm has A-IRB permission for the specific specialised lending sub-class, the exposure
may use A-IRB instead of slotting (see [Model Permissions](model-permissions.md)).

---

## Key Scenarios

| Scenario ID | Description | Expected RW |
|-------------|-------------|-------------|
| B31-E1 | PF Strong, operational | 70% |
| B31-E2 | IPRE Good | 90% |
| B31-E3 | IPRE Weak | 250% |
| B31-E4 | HVCRE Strong | 95% |

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| B31-E: Slotting Approach | E1–E4 | 13 | 100% (13/13) |
