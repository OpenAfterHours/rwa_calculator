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

Under Basel 3.1, PRA PS1/26 Art. 153(5) Table A preserves the CRR maturity-based structure
for slotting risk weights. BCBS CRE33 uses flat (maturity-independent) values, but PRA retains
the < 2.5yr / >= 2.5yr distinction.

!!! note "PRA vs BCBS B31 Slotting Structure"
    BCBS CRE33 removes the maturity distinction and uses flat risk weights for B31 slotting. PRA PS1/26 Art. 153(5) Table A preserves the maturity-based columns from CRR. The values below reflect the PRA structure.

### Non-HVCRE Operational (OF, CF, IPRE, PF Operational) — Table A

| Category | Remaining Maturity >= 2.5yr | Remaining Maturity < 2.5yr |
|----------|----------------------------|---------------------------|
| Strong | 70% | 50% |
| Good | 90% | 70% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |
| Default | 0% (EL) | 0% (EL) |

### Project Finance Pre-Operational

!!! warning "BCBS Values — PRA Verification Required"
    The pre-operational PF slotting table below is from **BCBS CRE33**. PRA PS1/26 Art. 153(5) Table A may **not** contain a separate pre-operational PF table — the pre-operational distinction may only apply under **SA** (Art. 122B(2)(c): 130%/100%/80%), not under slotting. If PRA does not define a separate slotting pre-op table, PF pre-operational exposures should use the standard Non-HVCRE Operational weights above. This requires PDF verification.

| Category | Risk Weight (BCBS CRE33) |
|----------|--------------------------|
| Strong | 80% |
| Good | 100% |
| Satisfactory | 120% |
| Weak | 350% |
| Default | 0% (EL) |

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

!!! note "No Separate PRA Pre-Operational Table"
    BCBS CRE33 defines a separate pre-operational PF table for both CRR-era and Basel 3.1 slotting. However, **PRA does not have a separate CRR-era pre-operational slotting table** — CRR Art. 153(5) uses a single table for all non-HVCRE SL types. The pre-operational PF differentiation only applies under Basel 3.1 (see Basel 3.1 tables above).

### Large FSE Threshold

Under Basel 3.1, a **large financial sector entity (FSE)** is defined as having total assets exceeding **GBP 79 billion** (per PRA PS1/26 Art. 1.3). This threshold is relevant for slotting approach exposures to FSEs, which may attract different treatment under Art. 147A restrictions.

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
