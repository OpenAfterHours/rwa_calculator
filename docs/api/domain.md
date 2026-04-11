# Domain API

The `rwa_calc.domain.enums` module defines all enumerations used throughout the calculation
pipeline. These enums provide type safety, self-documenting code, and a single source of
truth for regulatory categories.

**Why enums over strings:** Regulatory capital calculations use dozens of categorical values
(exposure classes, approach types, collateral types). Raw strings are error-prone — a typo
in `"corproate"` silently produces wrong results. Enums catch invalid values at assignment
time and enable IDE autocompletion.

All enums use Python's `StrEnum` or `IntEnum` (not `str, Enum` — they use the modern
Python 3.11+ enum classes).

## Module: `rwa_calc.domain.enums`

### Framework and Approach

#### `RegulatoryFramework`

```python
class RegulatoryFramework(StrEnum):
    CRR = "CRR"             # Capital Requirements Regulation (EU 575/2013) — Basel 3.0
                             # Effective until 31 December 2026
    BASEL_3_1 = "BASEL_3_1"  # PRA PS1/26 UK implementation of Basel 3.1
                             # Effective from 1 January 2027
```

#### `ApproachType`

```python
class ApproachType(StrEnum):
    SA = "standardised"        # Standardised Approach — risk weights from lookup tables
    FIRB = "foundation_irb"    # Foundation IRB — bank-estimated PD, supervisory LGD/EAD
    AIRB = "advanced_irb"      # Advanced IRB — bank-estimated PD, LGD, EAD
    SLOTTING = "slotting"      # Slotting approach for specialised lending (CRE33)
```

#### `IRBApproachOption`

User-selectable IRB approach options that determine which IRB approaches are permitted
for the calculation.

```python
class IRBApproachOption(StrEnum):
    SA_ONLY = "sa_only"                                  # No IRB permissions
    FIRB = "firb"                                        # Foundation IRB permitted
    AIRB = "airb"                                        # Advanced IRB permitted
    FULL_IRB = "full_irb"                                # Both FIRB and AIRB (AIRB takes precedence)
    RETAIL_AIRB_CORPORATE_FIRB = "retail_airb_corporate_firb"  # Hybrid: AIRB for retail, FIRB for corporate
```

### Exposure Classification

#### `ExposureClass`

Regulatory exposure classes for credit risk classification (CRR Art. 112, Basel 3.1 CRE20).
The exposure class is determined by the counterparty's `entity_type` field.

```python
class ExposureClass(StrEnum):
    CENTRAL_GOVT_CENTRAL_BANK = "central_govt_central_bank"  # CRR Art. 112(a), CRE20.7-15
    INSTITUTION = "institution"                  # CRR Art. 112(d), CRE20.16-21
    CORPORATE = "corporate"                      # CRR Art. 112(g), CRE20.22-25
    CORPORATE_SME = "corporate_sme"              # SME corporate (turnover ≤ EUR 50m / GBP 44m)
    RETAIL_MORTGAGE = "retail_mortgage"           # Residential mortgages, CRE20.71-81
    RETAIL_QRRE = "retail_qrre"                  # Qualifying revolving retail, CRE30.23-24
    RETAIL_OTHER = "retail_other"                 # Other retail, CRE20.65-70
    SPECIALISED_LENDING = "specialised_lending"   # Slotting approach, CRE33
    EQUITY = "equity"                            # CRR Art. 112(p), CRE20.58-62
    DEFAULTED = "defaulted"                      # CRR Art. 112(j), CRE20.88-90
    PSE = "pse"                                  # Public Sector Entities, CRR Art. 112(c)
    MDB = "mdb"                                  # Multilateral Development Banks, CRR Art. 117-118
    RGLA = "rgla"                                # Regional Government/Local Authorities, CRR Art. 115
    OTHER = "other"                              # Other items, CRR Art. 112(q)
```

!!! note
    Each counterparty `entity_type` maps to both an SA and IRB exposure class. For example:
    `pse_sovereign` → SA: PSE, IRB: CENTRAL_GOVT_CENTRAL_BANK.
    See [Classification](../features/classification.md) for the complete entity type to
    exposure class mapping.

#### `CQS`

Credit Quality Steps for external ratings mapping:

```python
class CQS(IntEnum):
    UNRATED = 0  # No eligible external rating
    CQS1 = 1    # AAA to AA- (S&P/Fitch), Aaa to Aa3 (Moody's)
    CQS2 = 2    # A+ to A-
    CQS3 = 3    # BBB+ to BBB-
    CQS4 = 4    # BB+ to BB-
    CQS5 = 5    # B+ to B-
    CQS6 = 6    # CCC+ and below
```

### Collateral and CRM

#### `CollateralType`

Categories of eligible collateral for CRM, determining applicable haircuts and LGD
treatment (CRR Art. 197-199, CRE22):

```python
class CollateralType(StrEnum):
    FINANCIAL = "financial"          # Cash and eligible financial collateral (CRE22.40)
    IMMOVABLE = "immovable"          # Real estate / immovable property (CRE22.72-78)
    RECEIVABLES = "receivables"      # Eligible receivables (CRE22.65-66)
    OTHER_PHYSICAL = "other_physical" # Other eligible physical collateral (CRE22.67-71)
    OTHER = "other"                  # Collateral not eligible for CRM
```

#### `PropertyType`

Property types for real estate collateral:

```python
class PropertyType(StrEnum):
    RESIDENTIAL = "residential"  # Residential property
    COMMERCIAL = "commercial"    # Commercial property
    ADC = "adc"                  # Acquisition, Development, Construction
```

#### `Seniority`

Seniority of exposure for LGD determination:

```python
class Seniority(StrEnum):
    SENIOR = "senior"              # Senior unsecured debt — 45% LGD under F-IRB
    SUBORDINATED = "subordinated"  # Subordinated unsecured debt — 75% LGD under F-IRB
                                   # Under Basel 3.1 SA: flat 150% RW (CRE20.47)
```

### Specialised Lending

#### `SlottingCategory`

Supervisory slotting categories for specialised lending (CRE33.5-8):

```python
class SlottingCategory(StrEnum):
    STRONG = "strong"              # 70% RW (50% if < 2.5yr maturity)
    GOOD = "good"                  # 90% RW (70% if < 2.5yr maturity)
    SATISFACTORY = "satisfactory"  # 115% RW
    WEAK = "weak"                  # 250% RW
    DEFAULT = "default"            # 0% RW (100% provisioning expected)
```

#### `SpecialisedLendingType`

Types of specialised lending exposures (CRE33.1-4):

```python
class SpecialisedLendingType(StrEnum):
    PROJECT_FINANCE = "project_finance"        # Project Finance
    OBJECT_FINANCE = "object_finance"          # Object Finance
    COMMODITIES_FINANCE = "commodities_finance" # Commodities Finance
    IPRE = "ipre"                              # Income-producing real estate
    HVCRE = "hvcre"                            # High-volatility commercial real estate
```

### Equity

#### `EquityType`

Types of equity exposures for risk weight determination under both Article 133 (SA)
and Article 155 (IRB Simple):

```python
class EquityType(StrEnum):
    CENTRAL_BANK = "central_bank"                          # 0% SA (Art. 133(6))
    LISTED = "listed"                                      # 100% SA / 290% IRB
    EXCHANGE_TRADED = "exchange_traded"                     # 100% SA / 290% IRB
    GOVERNMENT_SUPPORTED = "government_supported"           # 100% CRR SA / 250% B31 SA / 190% IRB
    UNLISTED = "unlisted"                                  # 250% SA / 370% IRB
    SPECULATIVE = "speculative"                            # 400% SA / 370% IRB
    PRIVATE_EQUITY = "private_equity"                      # 250% SA / 370% IRB
    PRIVATE_EQUITY_DIVERSIFIED = "private_equity_diversified"  # 250% SA / 190% IRB
    CIU = "ciu"                                            # Collective investment undertakings
    OTHER = "other"                                        # 250% SA / 370% IRB
```

#### `EquityApproach`

```python
class EquityApproach(StrEnum):
    SA = "sa"              # Article 133 Standardised Approach
    IRB_SIMPLE = "irb_simple"  # Article 155 IRB Simple Risk Weight Method
```

### Basel 3.1 Specific

#### `SCRAGrade`

Standardised Credit Risk Assessment Approach grades (Basel 3.1 CRE20.16-21).
Used for unrated institution exposures under Basel 3.1:

```python
class SCRAGrade(StrEnum):
    A = "A"  # CET1 > 14%, Leverage > 5% → 40% RW
    B = "B"  # CET1 > 5.5%, Leverage > 3% → 75% RW
    C = "C"  # Below minimum requirements → 150% RW
```

### Off-Balance Sheet

#### `CommitmentType`

Commitment types for CCF determination:

```python
class CommitmentType(StrEnum):
    UNCONDITIONALLY_CANCELLABLE = "unconditionally_cancellable"  # 0% CCF (SA), 10% (Basel 3.1)
    COMMITTED = "committed"                                      # 40%+ CCF
    TRADE_FINANCE = "trade_finance"                               # 20% CCF
    DIRECT_CREDIT_SUBSTITUTE = "direct_credit_substitute"         # 100% CCF
```

#### `RiskType`

Off-balance sheet risk categories for CCF determination (CRR Art. 111):

```python
class RiskType(StrEnum):
    FR = "full_risk"        # 100% CCF (SA and F-IRB) — direct credit substitutes, guarantees
    MR = "medium_risk"      # 50% CCF (SA), 75% (F-IRB) — NIFs, RUFs, standby LCs
    MLR = "medium_low_risk" # 20% CCF (SA), 75% (F-IRB) — documentary credits, trade finance
    LR = "low_risk"         # 0% CCF — unconditionally cancellable commitments
```

### IFRS 9

#### `IFRSStage`

IFRS 9 expected credit loss staging:

```python
class IFRSStage(IntEnum):
    STAGE_1 = 1  # 12-month ECL (performing)
    STAGE_2 = 2  # Lifetime ECL, not credit-impaired
    STAGE_3 = 3  # Lifetime ECL, credit-impaired (defaulted)
```

### Error Handling

#### `ErrorSeverity`

```python
class ErrorSeverity(StrEnum):
    WARNING = "warning"    # Informational — calculation proceeds
    ERROR = "error"        # May affect result accuracy
    CRITICAL = "critical"  # May invalidate results
```

#### `ErrorCategory`

```python
class ErrorCategory(StrEnum):
    DATA_QUALITY = "data_quality"           # Missing or invalid input data
    BUSINESS_RULE = "business_rule"         # Violation of regulatory business rules
    SCHEMA_VALIDATION = "schema_validation" # Schema validation failures
    CONFIGURATION = "configuration"         # Configuration issues
    CALCULATION = "calculation"             # Internal calculation errors
    HIERARCHY = "hierarchy"                 # Hierarchy resolution issues
    CRM = "crm"                            # CRM application issues
```

## Usage Examples

### Classification

```python
from rwa_calc.domain.enums import ExposureClass, ApproachType

if exposure_class == ExposureClass.CORPORATE_SME:
    # Apply SME treatment
    pass

if approach == ApproachType.FIRB:
    # Use supervisory LGD
    lgd = 0.45
```

### Risk Weight Lookup

```python
from rwa_calc.domain.enums import CQS

def get_corporate_rw(cqs: CQS) -> float:
    weights = {
        CQS.CQS1: 0.20,
        CQS.CQS2: 0.50,
        CQS.CQS3: 0.75,
        CQS.CQS4: 1.00,
        CQS.CQS5: 1.50,
        CQS.CQS6: 1.50,
        CQS.UNRATED: 1.00,
    }
    return weights[cqs]
```

## Related

- [Contracts API](contracts.md) — error types using `ErrorSeverity` and `ErrorCategory`
- [Engine API](engine.md) — implementations that use these enums
- [Data Model](../data-model/index.md) — schemas that reference these enum values
