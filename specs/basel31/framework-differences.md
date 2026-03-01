# Basel 3.1 Framework Differences

Key differences from CRR including output floor, PD/LGD floors, and removal of supporting factors.

**Regulatory Reference:** PRA PS9/24

---

## Overview

Basel 3.1 (effective 1 January 2027 in the UK) introduces significant changes to the credit risk framework. The calculator supports both regimes via a configuration toggle.

## Key Differences

| Parameter | CRR (Current) | Basel 3.1 | Reference |
|-----------|---------------|-----------|-----------|
| RWA Scaling Factor | 1.06 | Removed | — |
| SME Supporting Factor | 0.7619 / 0.85 | Removed | CRR Art. 501 |
| Infrastructure Factor | 0.75 | Removed | CRR Art. 501a |
| Output Floor | None | 72.5% of SA | PRA PS9/24 |
| PD Floor | 0.03% (all classes) | Differentiated | CRE30.55 |
| A-IRB LGD Floors | None | Yes (by collateral type) | CRE30.41 |
| Slotting Risk Weights | Maturity-differentiated | HVCRE + PF pre-op differentiated | PRA PS9/24 |

## Differentiated PD Floors (Basel 3.1)

| Exposure Class | PD Floor |
|---------------|----------|
| Corporate | 0.05% |
| Corporate SME | 0.05% |
| Retail Mortgage | 0.05% |
| Retail Other | 0.05% |
| QRRE (Transactors) | 0.03% |
| QRRE (Revolvers) | 0.10% |

## A-IRB LGD Floors (Basel 3.1)

| Collateral Type | LGD Floor |
|----------------|-----------|
| Unsecured (Senior) | 25% |
| Unsecured (Subordinated) | 50% |
| Financial collateral | 0% |
| Receivables | 10%* |
| Commercial real estate | 10%* |
| Residential real estate | 5%* |
| Other physical | 15%* |

*Values reflect PRA implementation. BCBS standard values differ (Receivables: 15%, CRE: 10%, RRE: 10%, Other Physical: 20%). Verify against PRA PS1/26 final rules.

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

### Transitional Schedule

| Year | Floor Percentage |
|------|-----------------|
| 2027 | 50.0% |
| 2028 | 55.0% |
| 2029 | 60.0% |
| 2030 | 65.0% |
| 2031 | 70.0% |
| 2032+ | 72.5% |

## Slotting Risk Weights (Basel 3.1)

Basel 3.1 (BCBS CRE33) introduces three distinct slotting weight tables:

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

Compare with CRR slotting weights in the [Slotting Approach](../crr/slotting-approach.md) specification.

## Financial Institution Correlation Multiplier (CRE31.5)

The 1.25x correlation multiplier applies to exposures to **financial institutions** only (not non-financial corporates):
- Regulated financial institutions with total assets >= USD 100bn (CRR Art. 153(2): EUR 70bn threshold)
- Unregulated financial institutions regardless of size

This multiplier is already implemented via the `requires_fi_scalar` flag in the classifier and `_polars_correlation_expr()` in the IRB formulas. It applies under both CRR and Basel 3.1 frameworks.

Note: There is no separate "large corporate" correlation multiplier for non-financial corporates in either the BCBS standard or PRA PS9/24.

## A-IRB CCF Floor (CRE32.27)

A-IRB own-estimate CCFs must be at least **50% of the SA CCF** for the same item type.

## Configuration

Switch between frameworks using the configuration factory:

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR (current)
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Basel 3.1
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```
