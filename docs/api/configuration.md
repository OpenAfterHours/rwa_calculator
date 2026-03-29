# Configuration API

The configuration module provides immutable dataclasses for controlling calculation
behavior. All configurations are frozen (`@dataclass(frozen=True)`) and use factory
methods for self-documenting creation.

## Module: `rwa_calc.contracts.config`

### `PolarsEngine`

```python
PolarsEngine = Literal["cpu", "gpu", "streaming"]
```

Type alias controlling the Polars collection engine. `"streaming"` (default) processes
in batches for lower memory usage; `"cpu"` loads everything into memory.

### `CalculationConfig`

Master configuration for RWA calculations. Bundles all framework-specific settings.
Use factory methods `.crr()` and `.basel_3_1()` instead of constructing directly.

```python
@dataclass(frozen=True)
class CalculationConfig:
    """
    Attributes:
        framework: Regulatory framework (CRR or BASEL_3_1).
        reporting_date: As-of date for the calculation.
        base_currency: Currency for reporting (default "GBP").
        apply_fx_conversion: Whether to convert exposures to base_currency.
        pd_floors: PD floor configuration.
        lgd_floors: LGD floor configuration (A-IRB).
        supporting_factors: SME/infrastructure factors.
        output_floor: Output floor configuration.
        retail_thresholds: Retail classification thresholds.
        irb_permissions: IRB approach permissions.
        scaling_factor: 1.06 scaling for IRB K (CRR Art. 153), 1.0 for Basel 3.1.
        eur_gbp_rate: EUR/GBP exchange rate for threshold conversion.
        collect_engine: Polars engine for .collect() — "streaming" (default).
    """

    framework: RegulatoryFramework
    reporting_date: date
    base_currency: str = "GBP"
    apply_fx_conversion: bool = True
    pd_floors: PDFloors
    lgd_floors: LGDFloors
    supporting_factors: SupportingFactors
    output_floor: OutputFloorConfig
    retail_thresholds: RetailThresholds
    irb_permissions: IRBPermissions
    scaling_factor: Decimal = Decimal("1.06")
    eur_gbp_rate: Decimal = Decimal("0.8732")
    collect_engine: PolarsEngine = "streaming"
```

#### Properties

```python
    @property
    def is_crr(self) -> bool:
        """Check if using CRR framework."""

    @property
    def is_basel_3_1(self) -> bool:
        """Check if using Basel 3.1 framework."""

    def get_output_floor_percentage(self) -> Decimal:
        """Get the applicable output floor percentage for the reporting date."""
```

#### Factory Methods

```python
    @classmethod
    def crr(
        cls,
        reporting_date: date,
        irb_permissions: IRBPermissions | None = None,
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        collect_engine: PolarsEngine = "streaming",
    ) -> CalculationConfig:
        """
        Create CRR (Basel 3.0) configuration.

        CRR characteristics:
        - Single PD floor (0.03%) for all classes
        - No LGD floors for A-IRB
        - SME supporting factor (0.7619/0.85)
        - Infrastructure supporting factor (0.75)
        - No output floor
        - 1.06 scaling factor for IRB K

        Args:
            reporting_date: As-of date for calculation.
            irb_permissions: IRB approach permissions (defaults to SA-only).
            eur_gbp_rate: EUR/GBP exchange rate for threshold conversion.
            collect_engine: Polars collection engine.

        Example:
            >>> config = CalculationConfig.crr(
            ...     reporting_date=date(2026, 12, 31),
            ...     irb_permissions=IRBPermissions.full_irb(),
            ... )
        """

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        irb_permissions: IRBPermissions | None = None,
        collect_engine: PolarsEngine = "streaming",
    ) -> CalculationConfig:
        """
        Create Basel 3.1 (PRA PS1/26) configuration.

        Basel 3.1 characteristics:
        - Differentiated PD floors by exposure class
        - LGD floors for A-IRB by collateral type
        - No supporting factors
        - Output floor (72.5%, transitional from 50% in 2027)
        - 1.06 scaling factor removed

        Args:
            reporting_date: As-of date for calculation.
            irb_permissions: IRB approach permissions (defaults to SA-only).
            collect_engine: Polars collection engine.

        Example:
            >>> config = CalculationConfig.basel_3_1(
            ...     reporting_date=date(2027, 6, 30),
            ...     irb_permissions=IRBPermissions.full_irb(),
            ... )
        """
```

### `PDFloors`

PD floor values by exposure class. All values expressed as decimals (e.g., 0.0003 = 0.03%).

```python
@dataclass(frozen=True)
class PDFloors:
    """
    Under CRR: Single floor of 0.03% for all exposures (Art. 163).
    Under Basel 3.1: Differentiated floors (CRE30.55, PS1/26 Ch.5).
    """

    corporate: Decimal = Decimal("0.0003")          # 0.03%
    corporate_sme: Decimal = Decimal("0.0003")       # 0.03%
    retail_mortgage: Decimal = Decimal("0.0003")     # 0.03%
    retail_other: Decimal = Decimal("0.0003")        # 0.03%
    retail_qrre_transactor: Decimal = Decimal("0.0003")  # 0.03%
    retail_qrre_revolver: Decimal = Decimal("0.0003")    # 0.03%

    def get_floor(
        self,
        exposure_class: ExposureClass,
        is_qrre_transactor: bool = False,
    ) -> Decimal:
        """Get the PD floor for a given exposure class.

        For RETAIL_QRRE, distinguish transactors vs revolvers via is_qrre_transactor.
        """

    @classmethod
    def crr(cls) -> PDFloors:
        """CRR PD floors: single 0.03% floor for all classes."""

    @classmethod
    def basel_3_1(cls) -> PDFloors:
        """Basel 3.1 PD floors: differentiated by class (CRE30.55).

        - Corporate/Corporate SME: 0.05%
        - Retail mortgage: 0.05%
        - Retail other: 0.05%
        - QRRE transactors: 0.03%
        - QRRE revolvers: 0.10%
        """
```

### `LGDFloors`

LGD floor values by collateral type for A-IRB. Only applicable under Basel 3.1
(CRE30.41, PS1/26 Ch.5). CRR has no LGD floors.

```python
@dataclass(frozen=True)
class LGDFloors:
    unsecured: Decimal = Decimal("0.25")                  # 25%
    subordinated_unsecured: Decimal = Decimal("0.50")      # 50%
    financial_collateral: Decimal = Decimal("0.0")         # 0%
    receivables: Decimal = Decimal("0.10")                 # 10%
    commercial_real_estate: Decimal = Decimal("0.10")      # 10%
    residential_real_estate: Decimal = Decimal("0.05")     # 5%
    other_physical: Decimal = Decimal("0.15")              # 15%

    def get_floor(self, collateral_type: CollateralType) -> Decimal:
        """Get the LGD floor for a given collateral type.
        Defaults to unsecured floor for unknown types."""

    @classmethod
    def crr(cls) -> LGDFloors:
        """CRR: No LGD floors (all zero)."""

    @classmethod
    def basel_3_1(cls) -> LGDFloors:
        """Basel 3.1 LGD floors (CRE30.41).
        Note: Values reflect PRA implementation."""
```

### `SupportingFactors`

Supporting factors for CRR (SME and infrastructure). Basel 3.1 removes these.

```python
@dataclass(frozen=True)
class SupportingFactors:
    """
    SME Supporting Factor (CRR Art. 501):
        Factor 1: 0.7619 for exposure up to EUR 2.5m
        Factor 2: 0.85 for exposure above EUR 2.5m

    Infrastructure Supporting Factor (CRR Art. 501a):
        Factor: 0.75
    """

    sme_factor_under_threshold: Decimal = Decimal("0.7619")
    sme_factor_above_threshold: Decimal = Decimal("0.85")
    sme_exposure_threshold_eur: Decimal = Decimal("2500000")   # EUR 2.5m
    sme_turnover_threshold_eur: Decimal = Decimal("50000000")  # EUR 50m
    infrastructure_factor: Decimal = Decimal("0.75")
    enabled: bool = True

    @classmethod
    def crr(cls) -> SupportingFactors:
        """CRR supporting factors enabled."""

    @classmethod
    def basel_3_1(cls) -> SupportingFactors:
        """Basel 3.1: Supporting factors disabled (all 1.0)."""
```

### `OutputFloorConfig`

Output floor configuration for Basel 3.1. The output floor (CRE99.1-8, PS1/26 Ch.12)
requires IRB RWAs to be at least 72.5% of the equivalent SA RWAs.

```python
@dataclass(frozen=True)
class OutputFloorConfig:
    enabled: bool = False
    floor_percentage: Decimal = Decimal("0.725")  # 72.5%
    transitional_start_date: date | None = None
    transitional_end_date: date | None = None
    transitional_floor_schedule: dict[date, Decimal] = field(default_factory=dict)

    def get_floor_percentage(self, calculation_date: date) -> Decimal:
        """Get the applicable floor percentage for a given date.

        Returns 0% if floor is disabled or the calculation date precedes
        the transitional start date (PS1/26: 1 Jan 2027 for UK firms).

        Transitional schedule:
        - 2027: 50%
        - 2028: 55%
        - 2029: 60%
        - 2030: 65%
        - 2031: 70%
        - 2032+: 72.5%
        """

    @classmethod
    def crr(cls) -> OutputFloorConfig:
        """CRR: No output floor."""

    @classmethod
    def basel_3_1(cls) -> OutputFloorConfig:
        """Basel 3.1 output floor with PRA transitional schedule."""
```

### `RetailThresholds`

Thresholds for retail exposure classification. Different thresholds apply under
CRR vs Basel 3.1.

```python
@dataclass(frozen=True)
class RetailThresholds:
    # Maximum aggregated exposure to qualify as retail
    max_exposure_threshold: Decimal = Decimal("1000000")  # GBP 1m (CRR)

    # QRRE specific limits
    qrre_max_limit: Decimal = Decimal("100000")  # GBP 100k

    @classmethod
    def crr(cls, eur_gbp_rate: Decimal = Decimal("0.8732")) -> RetailThresholds:
        """CRR retail thresholds (converted from EUR dynamically).

        Args:
            eur_gbp_rate: EUR/GBP exchange rate for threshold conversion.

        CRR thresholds (EUR):
        - Max exposure: EUR 1m (converted to GBP)
        - QRRE max limit: EUR 100k (converted to GBP)
        """

    @classmethod
    def basel_3_1(cls) -> RetailThresholds:
        """Basel 3.1 retail thresholds (GBP).

        - Max exposure: GBP 880k
        - QRRE max limit: GBP 100k
        """
```

### `IRBPermissions`

IRB approach permissions by exposure class. Tracks which approaches are
permitted for each class — must align with PRA permissions granted to the firm.

```python
@dataclass(frozen=True)
class IRBPermissions:
    permissions: dict[ExposureClass, set[ApproachType]] = field(default_factory=dict)

    def is_permitted(
        self,
        exposure_class: ExposureClass,
        approach: ApproachType,
    ) -> bool:
        """Check if an approach is permitted for an exposure class.
        Defaults to SA only if no permissions defined."""

    def get_permitted_approaches(
        self,
        exposure_class: ExposureClass,
    ) -> set[ApproachType]:
        """Get all permitted approaches for an exposure class."""
```

#### Factory Methods

```python
    @classmethod
    def sa_only(cls) -> IRBPermissions:
        """SA only — no IRB permissions."""

    @classmethod
    def full_irb(cls) -> IRBPermissions:
        """Full IRB permissions for all applicable classes.

        Includes FIRB + AIRB for corporates, institutions, sovereigns.
        AIRB only for retail (FIRB not permitted — CRE30.1).
        Slotting + FIRB + AIRB for specialised lending.
        SA only for equity (IRB removed under Basel 3.1).
        """

    @classmethod
    def firb_only(cls) -> IRBPermissions:
        """Foundation IRB only — no AIRB permissions.

        FIRB not permitted for retail (CRE30.1) — falls back to SA.
        Specialised lending can use FIRB or slotting (CRE33).
        """

    @classmethod
    def airb_only(cls) -> IRBPermissions:
        """Advanced IRB only — no FIRB permissions.

        AIRB permitted for all non-equity classes except specialised lending.
        Specialised lending uses slotting (no AIRB — CRE33.5).
        """

    @classmethod
    def retail_airb_corporate_firb(cls) -> IRBPermissions:
        """AIRB for retail, FIRB for corporate — hybrid approach.

        For firms with:
        - AIRB approval for retail exposures
        - FIRB approval for corporate exposures
        - Ability to reclassify qualifying corporates as regulatory retail

        Corporate-to-retail reclassification (CRR Art. 147(5)):
        - Must be managed as part of retail pool
        - Aggregated exposure < EUR 1m
        - Must have internally modelled LGD
        """
```

!!! note "Model-level override"
    When `model_permissions.parquet` is provided in the data directory,
    per-model permissions take precedence over `IRBPermissions` config for
    counterparties with internal ratings that carry a `model_id`. `IRBPermissions` still applies as the
    fallback for exposures without model-level permissions. See
    [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema).

## Usage Examples

### CRR Configuration

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

# SA-only CRR configuration
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
)

# CRR with full IRB permissions
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    irb_permissions=IRBPermissions.full_irb(),
)

# Access configuration
print(f"Framework: {config.framework}")          # RegulatoryFramework.CRR
print(f"Is CRR: {config.is_crr}")                # True
print(f"Scaling factor: {config.scaling_factor}") # 1.06
print(f"SME enabled: {config.supporting_factors.enabled}")  # True
```

### Basel 3.1 Configuration

```python
# Basel 3.1 with full IRB (auto-calculates output floor from reporting_date)
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    irb_permissions=IRBPermissions.full_irb(),
)

# Check output floor percentage (transitional for 2027 = 50%)
floor = config.get_output_floor_percentage()
print(f"Output floor: {floor:.0%}")  # 50%

# Fully phased-in (2032+)
config = CalculationConfig.basel_3_1(
    reporting_date=date(2032, 1, 1),
    irb_permissions=IRBPermissions.full_irb(),
)
floor = config.get_output_floor_percentage()
print(f"Output floor: {floor:.1%}")  # 72.5%
```

### Accessing Floors

```python
from rwa_calc.domain.enums import ExposureClass, CollateralType

# PD floor lookup
pd_floor = config.pd_floors.get_floor(ExposureClass.CORPORATE)
print(f"Corporate PD floor: {pd_floor:.4%}")  # 0.0500% (Basel 3.1)

# PD floor for QRRE (distinguish transactor vs revolver)
qrre_floor = config.pd_floors.get_floor(
    ExposureClass.RETAIL_QRRE, is_qrre_transactor=True
)
print(f"QRRE transactor PD floor: {qrre_floor:.4%}")  # 0.0300%

# LGD floor lookup
lgd_floor = config.lgd_floors.get_floor(CollateralType.IMMOVABLE)
print(f"CRE LGD floor: {lgd_floor:.0%}")  # 10%
```

### IRB Permissions

```python
from rwa_calc.contracts.config import IRBPermissions
from rwa_calc.domain.enums import ExposureClass, ApproachType

# Check permissions
permissions = IRBPermissions.full_irb()
print(permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB))  # True
print(permissions.is_permitted(ExposureClass.EQUITY, ApproachType.AIRB))     # False

# Get all permitted approaches
approaches = permissions.get_permitted_approaches(ExposureClass.CORPORATE)
print(approaches)  # {SA, FIRB, AIRB}

# Hybrid approach — common for UK banks
permissions = IRBPermissions.retail_airb_corporate_firb()
print(permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB))      # True
print(permissions.is_permitted(ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB)) # True
```

## Related

- [Pipeline API](pipeline.md)
- [Contracts API](contracts.md)
- [Engine API](engine.md)
- [Framework Comparison](../framework-comparison/index.md)
