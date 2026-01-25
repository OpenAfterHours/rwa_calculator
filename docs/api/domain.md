# Domain API

The domain module contains core enumerations and types.

## Module: `rwa_calc.domain.enums`

### `RegulatoryFramework`

```python
class RegulatoryFramework(str, Enum):
    """Regulatory framework for calculations."""

    CRR = "CRR"           # Current CRR (Basel 3.0)
    BASEL_3_1 = "BASEL_3_1"  # Basel 3.1 (from Jan 2027)
```

### `ExposureClass`

Regulatory exposure classes for SA and IRB approaches. The exposure class is determined by the counterparty's `entity_type` field.

```python
class ExposureClass(str, Enum):
    """Regulatory exposure classes."""

    SOVEREIGN = "SOVEREIGN"
    INSTITUTION = "INSTITUTION"
    CORPORATE = "CORPORATE"
    CORPORATE_SME = "CORPORATE_SME"
    RETAIL_MORTGAGE = "RETAIL_MORTGAGE"
    RETAIL_QRRE = "RETAIL_QRRE"
    RETAIL_OTHER = "RETAIL_OTHER"
    SPECIALISED_LENDING = "SPECIALISED_LENDING"
    EQUITY = "EQUITY"
    DEFAULTED = "DEFAULTED"
    PSE = "PSE"  # Public Sector Entity
    MDB = "MDB"  # Multilateral Development Bank
    RGLA = "RGLA"  # Regional Government/Local Authority
    OTHER = "OTHER"
```

**Note:** Each counterparty `entity_type` maps to both an SA and IRB exposure class. For example:
- `pse_sovereign` → SA: PSE, IRB: SOVEREIGN
- `rgla_institution` → SA: RGLA, IRB: INSTITUTION

See [Classification](../features/classification.md) for the complete entity type to exposure class mapping.

### `ApproachType`

```python
class ApproachType(str, Enum):
    """RWA calculation approaches."""

    SA = "SA"           # Standardised Approach
    FIRB = "FIRB"       # Foundation IRB
    AIRB = "AIRB"       # Advanced IRB
    SLOTTING = "SLOTTING"  # Slotting Approach
```

### `CQS`

```python
class CQS(int, Enum):
    """Credit Quality Steps (1-6 plus unrated)."""

    CQS_1 = 1  # AAA to AA-
    CQS_2 = 2  # A+ to A-
    CQS_3 = 3  # BBB+ to BBB-
    CQS_4 = 4  # BB+ to BB-
    CQS_5 = 5  # B+ to B-
    CQS_6 = 6  # CCC+ and below
    UNRATED = 0  # No external rating
```

### `CollateralType`

```python
class CollateralType(str, Enum):
    """Types of eligible collateral."""

    CASH = "CASH"
    GOVERNMENT_BOND = "GOVERNMENT_BOND"
    CORPORATE_BOND = "CORPORATE_BOND"
    COVERED_BOND = "COVERED_BOND"
    EQUITY_MAIN_INDEX = "EQUITY_MAIN_INDEX"
    EQUITY_OTHER = "EQUITY_OTHER"
    RESIDENTIAL_REAL_ESTATE = "RESIDENTIAL_REAL_ESTATE"
    COMMERCIAL_REAL_ESTATE = "COMMERCIAL_REAL_ESTATE"
    RECEIVABLES = "RECEIVABLES"
    OTHER_PHYSICAL = "OTHER_PHYSICAL"
    GOLD = "GOLD"
```

### `GuarantorType`

```python
class GuarantorType(str, Enum):
    """Types of guarantors."""

    SOVEREIGN = "SOVEREIGN"
    INSTITUTION = "INSTITUTION"
    CORPORATE = "CORPORATE"
    PARENT = "PARENT"
```

### `ProvisionType`

```python
class ProvisionType(str, Enum):
    """Types of provisions."""

    SCRA = "SCRA"  # Specific Credit Risk Adjustment
    GCRA = "GCRA"  # General Credit Risk Adjustment
```

### `IFRSStage`

```python
class IFRSStage(str, Enum):
    """IFRS 9 impairment stages."""

    STAGE_1 = "STAGE_1"  # Performing, 12-month ECL
    STAGE_2 = "STAGE_2"  # Performing, lifetime ECL
    STAGE_3 = "STAGE_3"  # Non-performing, lifetime ECL
```

### `SpecialisedLendingType`

```python
class SpecialisedLendingType(str, Enum):
    """Types of specialised lending."""

    PROJECT_FINANCE = "PROJECT_FINANCE"
    OBJECT_FINANCE = "OBJECT_FINANCE"
    COMMODITIES_FINANCE = "COMMODITIES_FINANCE"
    IPRE = "IPRE"  # Income-Producing Real Estate
    HVCRE = "HVCRE"  # High Volatility Commercial Real Estate
```

### `SlottingCategory`

```python
class SlottingCategory(str, Enum):
    """Slotting categories for specialised lending."""

    STRONG = "STRONG"
    GOOD = "GOOD"
    SATISFACTORY = "SATISFACTORY"
    WEAK = "WEAK"
    DEFAULT = "DEFAULT"
```

### `FacilityType`

```python
class FacilityType(str, Enum):
    """Types of credit facilities."""

    RCF = "RCF"  # Revolving Credit Facility
    TERM = "TERM"  # Term Loan
    MORTGAGE = "MORTGAGE"  # Mortgage
    OVERDRAFT = "OVERDRAFT"  # Overdraft
    CREDIT_CARD = "CREDIT_CARD"  # Credit Card
    TRADE_FINANCE = "TRADE_FINANCE"  # Trade Finance
    GUARANTEE = "GUARANTEE"  # Guarantee Facility
    PROJECT_FINANCE = "PROJECT_FINANCE"  # Project Finance
```

### `CounterpartyType`

**Note:** This enum is used for high-level counterparty categorisation. For exposure class determination, the counterparty schema uses the `entity_type` string field which supports 17 distinct values with granular SA/IRB class mappings. See [Classification](../features/classification.md) for details.

```python
class CounterpartyType(str, Enum):
    """Types of counterparties (high-level)."""

    SOVEREIGN = "SOVEREIGN"
    CENTRAL_BANK = "CENTRAL_BANK"
    INSTITUTION = "INSTITUTION"
    CORPORATE = "CORPORATE"
    INDIVIDUAL = "INDIVIDUAL"
    PSE = "PSE"
    MDB = "MDB"
    PROJECT_ENTITY = "PROJECT_ENTITY"
```

## Usage Examples

### Classification

```python
from rwa_calc.domain.enums import ExposureClass, ApproachType

# Check exposure class
if exposure_class == ExposureClass.CORPORATE_SME:
    # Apply SME treatment
    pass

# Check approach
if approach == ApproachType.FIRB:
    # Use supervisory LGD
    lgd = 0.45
```

### Risk Weight Lookup

```python
from rwa_calc.domain.enums import ExposureClass, CQS

def get_corporate_rw(cqs: CQS) -> float:
    """Get corporate risk weight by CQS."""
    weights = {
        CQS.CQS_1: 0.20,
        CQS.CQS_2: 0.50,
        CQS.CQS_3: 0.75,
        CQS.CQS_4: 1.00,
        CQS.CQS_5: 1.50,
        CQS.CQS_6: 1.50,
        CQS.UNRATED: 1.00,
    }
    return weights[cqs]
```

### Collateral Handling

```python
from rwa_calc.domain.enums import CollateralType

def get_haircut(collateral_type: CollateralType) -> float:
    """Get base haircut for collateral type."""
    if collateral_type == CollateralType.CASH:
        return 0.0
    elif collateral_type == CollateralType.GOVERNMENT_BOND:
        return 0.02  # Varies by maturity
    elif collateral_type == CollateralType.EQUITY_MAIN_INDEX:
        return 0.15
    # ...
```

## Related

- [Contracts API](contracts.md)
- [Engine API](engine.md)
- [Data Model](../data-model/index.md)
