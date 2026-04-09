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

Under Basel 3.1, PRA PS1/26 Art. 153(5) Table A uses subgrade columns A/B (Strong) and
C/D (Good) for maturity-based differentiation. Art. 153(5)(c) assigns column B (Strong) and
column D (Good) as the default. Column A/C (lower weights) may be used in three cases:

- **Art. 153(5)(d):** remaining maturity **< 2.5 years** — optional for all SL types
- **Art. 153(5)(e):** IPRE Strong with enhanced criteria (very low LTV, investment-grade tenant income, no ADC)
- **Art. 153(5)(f):** PF Strong with substantially stronger underwriting

Satisfactory/Weak/Default have no maturity split. See [Basel 3.1 Slotting spec](../basel31/slotting-approach.md#subgrade-treatment-table-a-columns-abcd) for full details.

!!! note "PRA vs BCBS B31 Slotting Structure"
    BCBS CRE33 removes the maturity distinction and uses flat risk weights for B31 slotting. PRA PS1/26 Art. 153(5) Table A preserves maturity-based subgrade columns from CRR. Column A/C = short maturity (<2.5yr), Column B/D = standard (≥2.5yr). The values below reflect the PRA structure.

### Non-HVCRE Operational (OF, CF, IPRE, PF Operational) — Table A

| Category | Remaining Maturity >= 2.5yr | Remaining Maturity < 2.5yr |
|----------|----------------------------|---------------------------|
| Strong | 70% | 50% |
| Good | 90% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% (EL) | 0% (EL) |

### Project Finance Pre-Operational

!!! info "PRA Has No Separate Pre-Operational Slotting Table"
    PRA PS1/26 Art. 153(5) Table A does **not** contain a separate pre-operational PF
    table. All PF (including pre-operational) uses the standard Non-HVCRE weights above.
    The pre-operational distinction in PRA only applies under **SA** (Art. 122B(2)(c):
    130%/100%/80%), not under slotting. BCBS CRE33 had separate higher weights
    (Strong=80%, Good=100%, Satisfactory=120%, Weak=350%) but PRA did not adopt this.

Pre-operational PF under PRA slotting uses the **standard table**: Strong=70%, Good=90%,
Satisfactory=115%, Weak=250%, Default=0%.

### HVCRE — Table A

| Category | Remaining Maturity >= 2.5yr | Remaining Maturity < 2.5yr |
|----------|----------------------------|---------------------------|
| Strong | 95% | 70% |
| Good | 120% | 95% |
| Satisfactory | 140% | 140% |
| Weak | 250% | 250% |
| Default | 0% (EL) | 0% (EL) |

### Slotting Expected Loss Rates — Table B (PRA PS1/26 Art. 158(6))

EL rates for slotting exposures are maturity-dependent, unlike the flat values in BCBS CRE33.

#### Non-HVCRE (OF, PF, CF, IPRE) — Table B

| Category | Remaining Maturity < 2.5yr | Remaining Maturity >= 2.5yr |
|----------|---------------------------|----------------------------|
| Strong | 0% | 0.4% |
| Good | 0.4% | 0.8% |
| Satisfactory | 2.8% | 2.8% |
| Weak | 8% | 8% |
| Default | 50% | 50% |

#### HVCRE — Table B

| Category | EL Rate |
|----------|---------|
| Strong | 0.4% |
| Good | 0.8% |
| Satisfactory | 2.8% |
| Weak | 8% |
| Default | 50% |

!!! warning "Previous Values Were Wrong"
    The EL rates previously documented here (Strong=5%, Good=10%, Satisfactory=35%, Weak=50%, Default=50%) were **BCBS CRE33 values**, not PRA PS1/26 values. The PRA Table B values above are dramatically lower for Strong/Good categories (e.g., Strong 0% vs 5%, Good 0.4% vs 10%). Using the BCBS values would massively overstate the EL shortfall for well-categorised slotting exposures.

These EL rates are used when calculating the IRB EL shortfall/excess for slotting exposures. The 0% risk weight for defaulted slotting categories (in Tables 1/2 above) means K=0, but the EL amount = EL_rate × EAD is still recognised for the EL shortfall calculation.

### PRA vs BCBS Slotting Differences

!!! note "No Separate PRA Pre-Operational Table (CRR or Basel 3.1)"
    BCBS CRE33 defines a separate pre-operational PF table, but **PRA does not adopt this distinction** under either CRR or Basel 3.1. PRA PS1/26 Art. 153(5) Table A uses a single table for all non-HVCRE SL types regardless of operational status. The pre-operational PF differentiation in PRA only applies under SA (Art. 122B(2)(c): 130%/100%/80% by quality).

### Large FSE Threshold

A **large financial sector entity (FSE)** is defined as having total assets ≥ **EUR 70bn** (CRR Art. 4(1)(146), ≈ GBP 79bn at PRA FX rate). This threshold determines eligibility for the 1.25x correlation multiplier (Art. 153(2)), not the Art. 147A approach restriction (which applies to all FSEs regardless of size). This is distinct from the Art. 147A(1)(d) large corporate revenue threshold (GBP 440m).

See [Framework Differences](../../framework-comparison/technical-reference.md) for full Basel 3.1 detail.

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

### Long Maturity (≥2.5 years)

| Scenario ID | SL Type | Category | Expected RW | Reference |
|-------------|---------|----------|-------------|-----------|
| CRR-E1 | Project Finance | Strong | 70% | Art. 153(5) Table 1 |
| CRR-E2 | Project Finance | Good | 90% | Art. 153(5) Table 1 |
| CRR-E3 | IPRE | Weak | 250% | Art. 153(5) Table 1 |
| CRR-E4 | HVCRE | Strong | 95% | Art. 153(5) Table 2 |

### Short Maturity (<2.5 years)

| Scenario ID | SL Type | Category | Expected RW | Reference |
|-------------|---------|----------|-------------|-----------|
| CRR-E5 | Project Finance | Strong | 50% | Art. 153(5) Table 1 |
| CRR-E6 | Project Finance | Good | 70% | Art. 153(5) Table 1 |
| CRR-E7 | HVCRE | Strong | 70% | Art. 153(5) Table 2 |
| CRR-E8 | HVCRE | Good | 95% | Art. 153(5) Table 2 |

!!! note "Coverage Notes"
    Object finance and commodities finance use the same non-HVCRE table as PF — validated through CRR-E1/E2/E5/E6 (same risk weight lookup). Defaulted slotting (0% RW) is validated through the CRR-I group (defaulted exposures). Satisfactory and Weak short-maturity scenarios (115%/250% — no maturity differentiation) are validated implicitly through E3 (same weight regardless of maturity band).

## Acceptance Tests

| Group | Scenarios | Tests | Pass Rate |
|-------|-----------|-------|-----------|
| CRR-E: Specialised Lending | E1–E8 | 13 | 100% (13/13) |
