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
| Slotting Risk Weights | Non-differentiated | HVCRE differentiated | PRA PS9/24 |

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
| Unsecured | 25% |
| Financial collateral | 0% |
| Receivables | 10% |
| Commercial real estate | 10% |
| Residential real estate | 5% |
| Other physical | 15% |

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

HVCRE exposures receive elevated risk weights under Basel 3.1:

| Category | Non-HVCRE | HVCRE |
|----------|-----------|-------|
| Strong | 50% | 100% |
| Good | 70% | 70% |
| Satisfactory | 100% | 150% |
| Weak | 150% | 150% |
| Default | 350% | 350% |

Compare with CRR slotting weights in the [Slotting Approach](../crr/slotting-approach.md) specification.

## Configuration

Switch between frameworks using the configuration factory:

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR (current)
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Basel 3.1
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```
