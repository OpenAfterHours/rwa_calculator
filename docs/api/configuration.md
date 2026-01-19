# Configuration API

The configuration module provides classes for controlling calculation behavior.

## Module: `rwa_calc.contracts.config`

### `CalculationConfig`

```python
@dataclass(frozen=True)
class CalculationConfig:
    """
    Main configuration for RWA calculations.

    Attributes:
        framework: Regulatory framework (CRR or BASEL_3_1).
        reporting_date: Calculation reference date.
        scaling_factor: IRB scaling factor (1.06 for CRR, 1.0 for Basel 3.1).
        pd_floors: PD floor values by exposure class.
        lgd_floors: LGD floor values (Basel 3.1 A-IRB only).
        supporting_factors: Supporting factor configuration.
        output_floor_config: Output floor configuration (Basel 3.1 only).
        eur_gbp_rate: EUR to GBP conversion rate.
    """

    framework: RegulatoryFramework
    reporting_date: date
    scaling_factor: Decimal
    pd_floors: PDFloors
    lgd_floors: LGDFloors | None
    supporting_factors: SupportingFactors
    output_floor_config: OutputFloorConfig | None
    eur_gbp_rate: Decimal

    @classmethod
    def crr(
        cls,
        reporting_date: date,
        apply_sme_supporting_factor: bool = True,
        apply_infrastructure_factor: bool = True,
        eur_gbp_rate: Decimal = Decimal("0.88"),
    ) -> "CalculationConfig":
        """
        Create CRR (Basel 3.0) configuration.

        Args:
            reporting_date: Calculation reference date.
            apply_sme_supporting_factor: Apply SME factor (Art. 501).
            apply_infrastructure_factor: Apply infrastructure factor.
            eur_gbp_rate: EUR to GBP conversion rate.

        Returns:
            CalculationConfig: CRR configuration.

        Example:
            >>> config = CalculationConfig.crr(
            ...     reporting_date=date(2026, 12, 31),
            ...     apply_sme_supporting_factor=True,
            ... )
        """

    @classmethod
    def basel_3_1(
        cls,
        reporting_date: date,
        output_floor_percentage: float = 0.725,
        transitional_floor_year: int | None = None,
        eur_gbp_rate: Decimal = Decimal("0.88"),
    ) -> "CalculationConfig":
        """
        Create Basel 3.1 configuration.

        Args:
            reporting_date: Calculation reference date.
            output_floor_percentage: Output floor (default 72.5%).
            transitional_floor_year: Year for transitional phase-in.
            eur_gbp_rate: EUR to GBP conversion rate.

        Returns:
            CalculationConfig: Basel 3.1 configuration.

        Example:
            >>> config = CalculationConfig.basel_3_1(
            ...     reporting_date=date(2027, 1, 1),
            ...     output_floor_percentage=0.725,
            ... )
        """
```

### `PDFloors`

```python
@dataclass(frozen=True)
class PDFloors:
    """
    PD floor values by exposure class.

    Attributes:
        corporate: Corporate PD floor.
        institution: Institution PD floor.
        retail_mortgage: Retail mortgage PD floor.
        retail_qrre_transactor: QRRE transactor PD floor.
        retail_qrre_revolver: QRRE revolver PD floor.
        retail_other: Other retail PD floor.
    """

    corporate: Decimal
    institution: Decimal
    retail_mortgage: Decimal
    retail_qrre_transactor: Decimal
    retail_qrre_revolver: Decimal
    retail_other: Decimal

    @classmethod
    def crr(cls) -> "PDFloors":
        """Create CRR PD floors (uniform 0.03%)."""
        return cls(
            corporate=Decimal("0.0003"),
            institution=Decimal("0.0003"),
            retail_mortgage=Decimal("0.0003"),
            retail_qrre_transactor=Decimal("0.0003"),
            retail_qrre_revolver=Decimal("0.0003"),
            retail_other=Decimal("0.0003"),
        )

    @classmethod
    def basel_3_1(cls) -> "PDFloors":
        """Create Basel 3.1 PD floors (differentiated)."""
        return cls(
            corporate=Decimal("0.0005"),
            institution=Decimal("0.0005"),
            retail_mortgage=Decimal("0.0005"),
            retail_qrre_transactor=Decimal("0.0003"),
            retail_qrre_revolver=Decimal("0.0010"),
            retail_other=Decimal("0.0005"),
        )

    def get_floor(self, exposure_class: ExposureClass) -> Decimal:
        """Get PD floor for exposure class."""
```

### `LGDFloors`

```python
@dataclass(frozen=True)
class LGDFloors:
    """
    LGD floor values by collateral type (Basel 3.1 A-IRB).

    Attributes:
        unsecured_senior: Unsecured senior debt floor.
        unsecured_subordinated: Subordinated debt floor.
        financial_collateral: Financial collateral floor.
        receivables: Receivables floor.
        cre: Commercial real estate floor.
        rre: Residential real estate floor.
        other_physical: Other physical collateral floor.
    """

    unsecured_senior: Decimal = Decimal("0.25")
    unsecured_subordinated: Decimal = Decimal("0.50")
    financial_collateral: Decimal = Decimal("0.00")
    receivables: Decimal = Decimal("0.15")
    cre: Decimal = Decimal("0.15")
    rre: Decimal = Decimal("0.10")
    other_physical: Decimal = Decimal("0.20")

    def get_floor(self, collateral_type: CollateralType) -> Decimal:
        """Get LGD floor for collateral type."""
```

### `SupportingFactors`

```python
@dataclass(frozen=True)
class SupportingFactors:
    """
    Supporting factor configuration.

    Attributes:
        apply_sme_factor: Apply SME supporting factor.
        apply_infrastructure_factor: Apply infrastructure factor.
        sme_threshold: EUR exposure threshold for tiered factor.
        sme_factor_below: Factor for exposure below threshold.
        sme_factor_above: Factor for exposure above threshold.
        infrastructure_factor: Infrastructure factor value.
    """

    apply_sme_factor: bool
    apply_infrastructure_factor: bool
    sme_threshold: Decimal
    sme_factor_below: Decimal
    sme_factor_above: Decimal
    infrastructure_factor: Decimal

    @classmethod
    def crr(
        cls,
        apply_sme: bool = True,
        apply_infrastructure: bool = True,
    ) -> "SupportingFactors":
        """Create CRR supporting factors."""
        return cls(
            apply_sme_factor=apply_sme,
            apply_infrastructure_factor=apply_infrastructure,
            sme_threshold=Decimal("2500000"),
            sme_factor_below=Decimal("0.7619"),
            sme_factor_above=Decimal("0.85"),
            infrastructure_factor=Decimal("0.75"),
        )

    @classmethod
    def none(cls) -> "SupportingFactors":
        """Create configuration with no supporting factors."""
        return cls(
            apply_sme_factor=False,
            apply_infrastructure_factor=False,
            sme_threshold=Decimal("0"),
            sme_factor_below=Decimal("1.0"),
            sme_factor_above=Decimal("1.0"),
            infrastructure_factor=Decimal("1.0"),
        )
```

### `OutputFloorConfig`

```python
@dataclass(frozen=True)
class OutputFloorConfig:
    """
    Output floor configuration (Basel 3.1).

    Attributes:
        floor_percentage: Floor as percentage of SA RWA.
        is_transitional: Whether using transitional phase-in.
        transitional_year: Year for phase-in calculation.
    """

    floor_percentage: Decimal
    is_transitional: bool = False
    transitional_year: int | None = None

    @classmethod
    def full(cls) -> "OutputFloorConfig":
        """Create fully phased-in floor (72.5%)."""
        return cls(floor_percentage=Decimal("0.725"))

    @classmethod
    def transitional(cls, year: int) -> "OutputFloorConfig":
        """Create transitional floor for given year."""
        phase_in = {
            2027: Decimal("0.50"),
            2028: Decimal("0.55"),
            2029: Decimal("0.60"),
            2030: Decimal("0.65"),
            2031: Decimal("0.70"),
        }
        return cls(
            floor_percentage=phase_in.get(year, Decimal("0.725")),
            is_transitional=True,
            transitional_year=year,
        )
```

## Usage Examples

### CRR Configuration

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig

# Full CRR with all options
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=True,
    apply_infrastructure_factor=True,
    eur_gbp_rate=Decimal("0.88"),
)

# Access configuration
print(f"Framework: {config.framework}")
print(f"Scaling factor: {config.scaling_factor}")
print(f"SME factor enabled: {config.supporting_factors.apply_sme_factor}")
```

### Basel 3.1 Configuration

```python
# Full phase-in
config = CalculationConfig.basel_3_1(
    reporting_date=date(2032, 1, 1),
    output_floor_percentage=0.725,
)

# Transitional (2027)
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 6, 30),
    transitional_floor_year=2027,  # 50% floor
)
```

### Accessing Floors

```python
from rwa_calc.domain.enums import ExposureClass, CollateralType

# PD floor lookup
pd_floor = config.pd_floors.get_floor(ExposureClass.CORPORATE)
print(f"Corporate PD floor: {pd_floor:.4%}")

# LGD floor lookup (Basel 3.1 only)
if config.lgd_floors:
    lgd_floor = config.lgd_floors.get_floor(CollateralType.RESIDENTIAL_REAL_ESTATE)
    print(f"RRE LGD floor: {lgd_floor:.0%}")
```

## Related

- [Pipeline API](pipeline.md)
- [Configuration Guide](../user-guide/configuration.md)
- [Framework Comparison](../user-guide/regulatory/comparison.md)
