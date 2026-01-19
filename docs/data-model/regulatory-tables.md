# Regulatory Tables

This page documents the lookup tables used for regulatory parameters.

## Risk Weight Tables

### Sovereign Risk Weights

| CQS | CRR Risk Weight | Basel 3.1 Risk Weight |
|-----|-----------------|----------------------|
| 1 | 0% | 0% |
| 2 | 20% | 20% |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |
| Unrated | 100% | 100% |

### Institution Risk Weights

| CQS | CRR Risk Weight | Basel 3.1 (ECRA) |
|-----|-----------------|------------------|
| 1 | 20% | 20% |
| 2 | 30%* | 30% |
| 3 | 50% | 50% |
| 4 | 100% | 100% |
| 5 | 100% | 100% |
| 6 | 150% | 150% |

*UK deviation from standard 50%

### Corporate Risk Weights

| CQS | CRR Risk Weight | Basel 3.1 Risk Weight |
|-----|-----------------|----------------------|
| 1 | 20% | 20% |
| 2 | 50% | 50% |
| 3 | 75% | 75% |
| 4 | 100% | 100% |
| 5 | 150% | 100% |
| 6 | 150% | 150% |
| Unrated | 100% | 100% |

### Retail Risk Weights

| Exposure Type | CRR | Basel 3.1 |
|---------------|-----|-----------|
| Retail Mortgage (LTV ≤80%) | 35% | LTV-based |
| Retail QRRE | 75% | 45-75% |
| Retail Other | 75% | 75% |

### Basel 3.1 Residential Real Estate

| LTV | Whole Loan | Income-Producing |
|-----|------------|------------------|
| ≤50% | 20% | 30% |
| 50-60% | 25% | 35% |
| 60-70% | 30% | 45% |
| 70-80% | 40% | 60% |
| 80-90% | 50% | 75% |
| 90-100% | 70% | 105% |
| >100% | Counterparty RW | Counterparty RW |

## Credit Conversion Factors

| Item Type | CRR CCF | Basel 3.1 CCF |
|-----------|---------|---------------|
| Unconditionally cancellable | 0% | 10% |
| Short-term trade finance | 20% | 20% |
| Undrawn commitments <1yr | 20% | 40% |
| Undrawn commitments ≥1yr | 50% | 40% |
| NIFs/RUFs | 50% | 50% |
| Direct credit substitutes | 100% | 100% |

## Supervisory Haircuts

### Financial Collateral

| Collateral Type | ≤1yr | 1-5yr | >5yr |
|-----------------|------|-------|------|
| Cash | 0% | 0% | 0% |
| Government CQS1 | 0.5% | 2% | 4% |
| Government CQS2-3 | 1% | 3% | 6% |
| Corporate CQS1-2 | 1% | 4% | 8% |
| Corporate CQS3 | 2% | 6% | 12% |
| Main index equity | 15% | 15% | 15% |
| Other equity | 25% | 25% | 25% |
| Gold | 15% | 15% | 15% |

### Additional Haircuts

| Condition | Haircut |
|-----------|---------|
| Currency mismatch | +8% |
| Daily revaluation absence | +√10 scaling |

## Slotting Risk Weights

### Standard Specialised Lending

| Category | CRR | Basel 3.1 |
|----------|-----|-----------|
| Strong | 70% | 70% |
| Good | 90% | 90% |
| Satisfactory | 115% | 115% |
| Weak | 250% | 250% |

### Project Finance Pre-Operational (Basel 3.1)

| Category | Basel 3.1 |
|----------|-----------|
| Strong | 80% |
| Good | 100% |
| Satisfactory | 120% |
| Weak | 350% |

### HVCRE

| Category | Risk Weight |
|----------|-------------|
| Strong | 95% |
| Good | 120% |
| Satisfactory | 140% |
| Weak | 250% |

## F-IRB Supervisory LGD

| Exposure Type | LGD |
|---------------|-----|
| Senior unsecured | 45% |
| Subordinated | 75% |
| Secured - Financial collateral | 0% |
| Secured - Receivables | 35% |
| Secured - CRE/RRE | 35% |
| Secured - Other physical | 40% |

## A-IRB LGD Floors (Basel 3.1)

| Collateral Type | LGD Floor |
|-----------------|-----------|
| Unsecured senior | 25% |
| Unsecured subordinated | 50% |
| Financial collateral | 0% |
| Receivables | 15% |
| Commercial real estate | 15% |
| Residential real estate | 10% |
| Other physical | 20% |

## PD Floors

| Exposure Class | CRR | Basel 3.1 |
|----------------|-----|-----------|
| Corporate | 0.03% | 0.05% |
| Institution | 0.03% | 0.05% |
| Retail Mortgage | 0.03% | 0.05% |
| Retail QRRE (transactor) | 0.03% | 0.03% |
| Retail QRRE (revolver) | 0.03% | 0.10% |
| Retail Other | 0.03% | 0.05% |

## Implementation

### Risk Weight Lookup

```python
from rwa_calc.data.tables.crr_risk_weights import get_risk_weight

rw = get_risk_weight(
    exposure_class=ExposureClass.CORPORATE,
    cqs=CQS.CQS_2,
    framework=RegulatoryFramework.CRR
)
# Returns: 0.50 (50%)
```

### CCF Lookup

```python
from rwa_calc.data.tables.crr_ccf import get_ccf

ccf = get_ccf(
    item_type="UNDRAWN_COMMITMENT",
    original_maturity_years=2,
    framework=RegulatoryFramework.CRR
)
# Returns: 0.50 (50%)
```

### Haircut Lookup

```python
from rwa_calc.data.tables.crr_haircuts import get_haircut

haircut = get_haircut(
    collateral_type=CollateralType.GOVERNMENT_BOND,
    cqs=CQS.CQS_1,
    residual_maturity_years=3
)
# Returns: 0.02 (2%)
```

### Slotting Lookup

```python
from rwa_calc.data.tables.crr_slotting import get_slotting_weight

rw = get_slotting_weight(
    lending_type=SpecialisedLendingType.PROJECT_FINANCE,
    category=SlottingCategory.GOOD,
    framework=RegulatoryFramework.CRR
)
# Returns: 0.90 (90%)
```

## Next Steps

- [API Reference](../api/index.md)
- [Standardised Approach](../user-guide/methodology/standardised-approach.md)
- [IRB Approach](../user-guide/methodology/irb-approach.md)
