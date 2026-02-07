# Features

This section provides an overview of all implemented features in the RWA calculator with links to detailed documentation.

## Core Calculation Features

| Feature | Description | Documentation |
|---------|-------------|---------------|
| **Standardised Approach (SA)** | CQS-based risk weights for all exposure classes, including UK CRR deviations | [Methodology](../user-guide/methodology/standardised-approach.md), [Specification](../specifications/crr/sa-risk-weights.md) |
| **Foundation IRB (F-IRB)** | Supervisory LGD, PD floors, correlation formulas, maturity adjustment | [Methodology](../user-guide/methodology/irb-approach.md), [Specification](../specifications/crr/firb-calculation.md) |
| **Advanced IRB (A-IRB)** | Internal LGD/CCF estimates with Basel 3.1 LGD floors | [Methodology](../user-guide/methodology/irb-approach.md), [Specification](../specifications/crr/airb-calculation.md) |
| **Slotting Approach** | Category-based risk weights for specialised lending (PF, OF, CF, IPRE, HVCRE) | [Methodology](../user-guide/methodology/specialised-lending.md), [Specification](../specifications/crr/slotting-approach.md) |
| **Equity Calculator** | Article 133 (SA) and Article 155 (IRB Simple) equity risk weights | [Methodology](../user-guide/methodology/equity.md), [API](../api/engine.md#equity-calculator) |

## Credit Risk Mitigation Features

| Feature | Description | Documentation |
|---------|-------------|---------------|
| **Collateral Haircuts** | CRR Art. 224 supervisory haircuts for financial and physical collateral | [Methodology](../user-guide/methodology/crm.md#collateral), [Specification](../specifications/crr/credit-risk-mitigation.md) |
| **Overcollateralisation** | CRR Art. 230 overcollateralisation ratios and minimum thresholds | [Methodology](../user-guide/methodology/crm.md#overcollateralisation-crr-art-230), [Specification](../specifications/crr/credit-risk-mitigation.md#overcollateralisation-crr-art-230) |
| **Guarantee Substitution** | Risk weight substitution for beneficial guarantees with pre/post CRM tracking | [Methodology](../user-guide/methodology/crm.md#guarantees), [Specification](../specifications/crr/credit-risk-mitigation.md#guarantee-substitution-crr-art-213-217) |
| **Provisions** | SA provision deduction and IRB expected loss comparison | [Methodology](../user-guide/methodology/crm.md#provisions), [Specification](../specifications/crr/provisions.md) |
| **Maturity Mismatch** | CRR Art. 238 adjustment for collateral/guarantee maturity shorter than exposure | [Methodology](../user-guide/methodology/crm.md#maturity-mismatch), [Specification](../specifications/crr/credit-risk-mitigation.md#maturity-mismatch-adjustment-crr-art-238) |

## Pipeline & Infrastructure Features

| Feature | Description | Documentation |
|---------|-------------|---------------|
| **Classification** | Entity type mapping, SME/retail detection, approach assignment | [Detail](classification.md), [Specification](../specifications/common/hierarchy-classification.md) |
| **Hierarchy Resolution** | Parent-child traversal, rating inheritance, lending group aggregation | [Architecture](../architecture/pipeline.md), [Specification](../specifications/common/hierarchy-classification.md) |
| **FX Conversion** | Multi-currency support with configurable base currency and audit trail | [Methodology](../user-guide/methodology/fx-conversion.md), [API](../api/engine.md#fx-converter) |
| **Credit Conversion Factors** | SA and F-IRB CCFs for off-balance sheet exposures | [Specification](../specifications/crr/credit-conversion-factors.md), [API](../api/engine.md#ccf-calculator) |
| **Supporting Factors** | CRR SME tiered factor (0.7619/0.85) and infrastructure factor (0.75) | [Methodology](../user-guide/methodology/supporting-factors.md), [Specification](../specifications/crr/supporting-factors.md) |
| **Output Floor** | Basel 3.1 output floor (72.5% of SA) with transitional schedule | [Specification](../specifications/basel31/framework-differences.md#output-floor), [API](../api/engine.md#aggregator) |
| **Input Validation** | Categorical value validation with DQ006 error codes | [Data Model](../data-model/data-validation.md) |
| **Audit Trail** | Full calculation transparency with formatted audit strings for every approach | [API](../api/engine.md#audit-namespace) |

## Dual-Framework Support

The calculator supports both CRR and Basel 3.1 via a single configuration toggle:

```python
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))     # CRR
config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))  # Basel 3.1
```

Key differences are documented in the [Framework Differences](../specifications/basel31/framework-differences.md) specification.

## Performance

All calculations use Polars LazyFrames for vectorized performance (50-100x improvement over row-by-row iteration). Eight custom Polars namespace extensions provide fluent, chainable APIs. See [Design Principles](../architecture/design-principles.md) for details.
