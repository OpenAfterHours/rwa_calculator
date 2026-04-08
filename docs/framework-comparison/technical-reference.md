# Basel 3.1 Framework Differences

Key differences from CRR including output floor, PD/LGD floors, and removal of supporting factors.

**Regulatory Reference:** PRA PS1/26

---

## Overview

Basel 3.1 (effective 1 January 2027 in the UK) introduces significant changes to the credit risk framework. The calculator supports both regimes via a configuration toggle.

## Key Differences

| Parameter | CRR (Current) | Basel 3.1 | Reference |
|-----------|---------------|-----------|-----------|
| RWA Scaling Factor | 1.06 | Removed | — |
| SME Supporting Factor | 0.7619 / 0.85 | Removed | CRR Art. 501 |
| Infrastructure Factor | 0.75 | Removed | CRR Art. 501a |
| Output Floor | None | 72.5% of SA | PRA PS1/26 |
| PD Floor | 0.03% (all classes) | Differentiated | CRE30.55 |
| A-IRB LGD Floors | None | Yes (by collateral type) | CRE30.41 |
| Slotting Risk Weights | Maturity-differentiated | HVCRE-differentiated (no pre-op distinction) | PRA PS1/26 |

## Differentiated PD Floors (Basel 3.1)

PRA PS1/26 Art. 163(1):

| Exposure Class | PD Floor | Reference |
|---------------|----------|-----------|
| Corporate | 0.05% | Art. 160(1) |
| Corporate SME | 0.05% | Art. 160(1) |
| Retail Mortgage | 0.10% | Art. 163(1)(b) |
| Retail Other | 0.05% | Art. 163(1)(c) |
| QRRE (Transactors) | 0.05% | Art. 163(1)(c) |
| QRRE (Revolvers) | 0.10% | Art. 163(1)(a) |

## A-IRB LGD Floors (Basel 3.1)

**Corporate / Institution (Art. 161(5)):**

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10%* |
| Commercial real estate | 10%* |
| Residential real estate | 10%* |
| Other physical | 15%* |

!!! note "No senior/subordinated distinction"
    Art. 161(5)(a) sets a flat 25% floor for **all** corporate unsecured exposures. Unlike F-IRB supervisory LGD (which distinguishes senior 40% / subordinated 75%), A-IRB LGD floors have no subordinated uplift.

**Retail (Art. 164(4)):**

| Exposure Type | LGD Floor |
|---------------|-----------|
| Secured by residential RE | 5% |
| QRRE unsecured | 50% |
| Other unsecured retail | 30% |

*Values reflect PRA PS1/26 implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%).

## F-IRB Supervisory LGD (CRE32)

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Corporate/Institution (Senior) | 45% | 40% |
| Corporate/Institution (Subordinated) | 75% | 75% |
| Secured - Financial Collateral | 0% | 0% |
| Secured - Receivables | 35% | 20% |
| Secured - CRE/RRE | 35% | 20% |
| Secured - Other Physical | 40% | 25% |

## Output Floor

The output floor ensures IRB RWA cannot fall below a percentage of what the SA would produce:

```
RWA_final = max(RWA_IRB, floor_percentage x RWA_SA)
```

### Transitional Schedule (PRA PS1/26 Art. 92 para 5)

The PRA compressed the BCBS 6-year phase-in to a 4-year schedule:

| Year | Floor Percentage |
|------|-----------------|
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

Note: Art. 92 para 5 says institutions "may apply" these transitional rates — they are
permissive. Firms can voluntarily use 72.5% from day one.

### Output Floor Adjustment (OF-ADJ)

The full output floor formula from PRA PS1/26 Art. 92 is:

```
TREA = max(U-TREA, x × S-TREA + OF-ADJ)
```

Where:

- **U-TREA** = un-floored total risk exposure (using internal models where permitted)
- **S-TREA** = standardised total risk exposure (recalculated using SA only)
- **x** = floor percentage (see transitional schedule above)
- **OF-ADJ** = adjustment for the difference between IRB expected loss provisions treatment
  and SA general credit risk adjustments

OF-ADJ reconciles the different treatment of provisions: under IRB, expected loss shortfall
adds to capital requirements while under SA, general credit risk adjustments reduce
risk exposure. Without this adjustment, the floor comparison would not be on a like-for-like
basis.

## Supervisory Haircut Comparison

### CRR Haircuts (3 maturity bands)

| Collateral Type | 0-1y | 1-5y | 5y+ |
|-----------------|------|------|-----|
| Govt bonds CQS 1 | 0.5% | 2% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 6% |
| Corp bonds CQS 1 | 1% | 4% | 8% |
| Corp bonds CQS 2-3 | 2% | 6% | 12% |
| Main index equities | 15% | — | — |
| Other equities | 25% | — | — |
| Gold | 15% | — | — |
| Cash | 0% | — | — |

### Basel 3.1 Haircuts (5 maturity bands)

PRA PS1/26 Art. 224 Table 3 (10-day holding period):

| Collateral Type | 0-1y | 1-3y | 3-5y | 5-10y | 10y+ |
|-----------------|------|------|------|-------|------|
| Govt bonds CQS 1 | 0.5% | 2% | 2% | 4% | 4% |
| Govt bonds CQS 2-3 | 1% | 3% | 4% | 6% | **12%** |
| Corp bonds CQS 1 | 1% | 4% | 6% | **10%** | **12%** |
| Corp bonds CQS 2-3 | 2% | 6% | 8% | **15%** | **15%** |
| Main index equities | **20%** | — | — | — | — |
| Other equities | **30%** | — | — | — | — |
| Gold | **20%** | — | — | — | — |
| Cash | 0% | — | — | — | — |

Currency mismatch haircut remains 8% under both frameworks (CRR Art. 224 / CRE22.54).

## Slotting Risk Weights (Basel 3.1)

PRA PS1/26 Art. 153(5) Table A defines two slotting weight tables — non-HVCRE and HVCRE:

### Non-HVCRE (OF, CF, PF, IPRE)

| Category | Risk Weight |
|----------|-------------|
| Strong | 70% |
| Good | 90% |
| Satisfactory | 115% |
| Weak | 250% |
| Default | 0% (EL) |

!!! warning "PRA Deviation from BCBS — No Pre-Operational PF Slotting Table"
    BCBS CRE33.6 Table 6 defines separate elevated slotting weights for pre-operational
    project finance (Strong 80%, Good 100%, Satisfactory 120%, Weak 350%). **PRA PS1/26
    does not adopt this distinction** — all project finance uses the standard non-HVCRE
    table regardless of operational status. The pre-operational / operational distinction
    only applies under the SA approach (Art. 122B(2)(c): 130% pre-op, 100% operational,
    80% high-quality operational).

### HVCRE

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |
| Default | 0% (EL) |

### Slotting Subgrades

Basel 3.1 allows residual maturity-based differentiation within the Strong and Good
categories using subgrades:

| Category | Subgrade A (< 2.5yr residual) | Subgrade B (≥ 2.5yr residual) |
|----------|-------------------------------|-------------------------------|
| Strong A / Strong B | 50% / 70% (PF Operational) | 70% / 70% |
| Good C / Good D | 70% / 90% (PF Operational) | 90% / 90% |

IPRE "Strong A" requires specific criteria: low LTV, adequate tenant income, and no ADC
characteristics. These subgrades provide finer risk differentiation within the broader
slotting categories.

Compare with CRR slotting weights in the [Slotting Approach](../specifications/crr/slotting-approach.md) specification.

## Financial Institution Correlation Multiplier (CRE31.5)

The 1.25x correlation multiplier applies to exposures to **financial institutions** only (not non-financial corporates):
- Regulated financial institutions with total assets above the applicable threshold:
  - **CRR**: EUR 70bn (Art. 153(2))
  - **BCBS/Basel 3.1**: USD 100bn (CRE31.5)
- Unregulated financial institutions regardless of size

This multiplier is already implemented via the `requires_fi_scalar` flag in the classifier and `_polars_correlation_expr()` in the IRB formulas. It applies under both CRR and Basel 3.1 frameworks.

Note: There is no separate "large corporate" correlation multiplier for non-financial corporates in either the BCBS standard or PRA PS1/26.

## A-IRB CCF Floor (CRE32.27)

A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type.

## IRB Maturity Calculation Changes

Basel 3.1 refines the IRB effective maturity (M) calculation (PRA PS1/26 Art. 162):

| Aspect | CRR | Basel 3.1 |
|--------|-----|-----------|
| Cash-flow schedule | Weighted average of cash flows | Same: `M = max(1, min(Σ(t×CF_t)/Σ(CF_t), 5))` |
| Revolving exposures | Repayment date of current drawing | **Maximum contractual termination date** |
| Floor | 1 year | 1 year |
| Cap | 5 years | 5 years |

The revolving maturity change is significant — it typically increases M for revolving
facilities, leading to higher maturity adjustments and therefore higher capital.

## Configuration

Switch between frameworks using the configuration factory:

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR (current)
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Basel 3.1
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```
