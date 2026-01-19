# Configuration Guide

This guide explains how to configure the RWA calculator for different scenarios, regulatory frameworks, and calculation options.

## Configuration Overview

The calculator uses a `CalculationConfig` object to control all aspects of the calculation:

```python
from rwa_calc.contracts.config import CalculationConfig

# Create configuration
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31)
)
```

## Framework Selection

### CRR Configuration

For calculations under current CRR rules:

```python
from datetime import date
from decimal import Decimal
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(
    # Required
    reporting_date=date(2026, 12, 31),

    # Optional - CRR-specific
    apply_sme_supporting_factor=True,      # Default: True
    apply_infrastructure_factor=True,       # Default: True

    # Optional - General
    eur_gbp_rate=Decimal("0.88"),          # Default: 0.88
)
```

### Basel 3.1 Configuration

For calculations under Basel 3.1 rules:

```python
config = CalculationConfig.basel_3_1(
    # Required
    reporting_date=date(2027, 1, 1),

    # Optional - Basel 3.1-specific
    output_floor_percentage=0.725,          # Default: 0.725 (72.5%)
    transitional_floor_year=2027,           # For phase-in calculation

    # Optional - General
    eur_gbp_rate=Decimal("0.88"),
)
```

## Configuration Parameters

### Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reporting_date` | `date` | Required | Calculation reference date |
| `eur_gbp_rate` | `Decimal` | 0.88 | EUR to GBP conversion rate |

### CRR-Specific Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `apply_sme_supporting_factor` | `bool` | True | Apply SME factor (Art. 501) |
| `apply_infrastructure_factor` | `bool` | True | Apply infrastructure factor |

### Basel 3.1-Specific Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_floor_percentage` | `float` | 0.725 | Output floor percentage |
| `transitional_floor_year` | `int` | None | Year for transitional floor |

## Framework Differences

The configuration factories automatically set framework-specific values:

### Automatic Settings

| Setting | CRR | Basel 3.1 |
|---------|-----|-----------|
| `framework` | `RegulatoryFramework.CRR` | `RegulatoryFramework.BASEL_3_1` |
| `scaling_factor` | 1.06 | 1.00 |
| `pd_floors` | Uniform 0.03% | Differentiated |
| `lgd_floors` | None | By collateral type |
| `output_floor` | None | 72.5% (or transitional) |
| `supporting_factors` | Available | Not available |

### PD Floors

```python
# CRR - All exposures
pd_floor = 0.0003  # 0.03%

# Basel 3.1 - Differentiated
pd_floors = {
    "CORPORATE": 0.0005,           # 0.05%
    "INSTITUTION": 0.0005,         # 0.05%
    "RETAIL_MORTGAGE": 0.0005,     # 0.05%
    "RETAIL_QRRE_TRANSACTOR": 0.0003,  # 0.03%
    "RETAIL_QRRE_REVOLVER": 0.0010,    # 0.10%
    "RETAIL_OTHER": 0.0005,        # 0.05%
}
```

### LGD Floors (Basel 3.1 A-IRB)

```python
lgd_floors = {
    "UNSECURED_SENIOR": 0.25,      # 25%
    "UNSECURED_SUBORDINATED": 0.50, # 50%
    "FINANCIAL_COLLATERAL": 0.00,  # 0%
    "RECEIVABLES": 0.15,           # 15%
    "CRE": 0.15,                   # 15%
    "RRE": 0.10,                   # 10%
    "OTHER_PHYSICAL": 0.20,        # 20%
}
```

## Output Floor Configuration

### Phase-In Schedule

| Year | Floor Percentage |
|------|------------------|
| 2027 | 50.0% |
| 2028 | 55.0% |
| 2029 | 60.0% |
| 2030 | 65.0% |
| 2031 | 70.0% |
| 2032+ | 72.5% |

### Transitional Configuration

```python
# Automatically calculate transitional floor
config = CalculationConfig.basel_3_1(
    reporting_date=date(2028, 6, 30),
    transitional_floor_year=2028  # Uses 55% floor
)

# Or specify exact percentage
config = CalculationConfig.basel_3_1(
    reporting_date=date(2028, 6, 30),
    output_floor_percentage=0.55  # Explicit 55%
)
```

## FX Rate Configuration

### EUR/GBP Conversion

Many regulatory thresholds are defined in EUR. The calculator converts these to GBP:

```python
# Default rate
eur_gbp_rate = Decimal("0.88")

# Converted thresholds
SME_TURNOVER = EUR 50m × 0.88 = GBP 44m
SME_EXPOSURE = EUR 2.5m × 0.88 = GBP 2.2m
RETAIL_THRESHOLD = EUR 1m × 0.88 = GBP 880k
```

### Custom FX Rate

```python
from decimal import Decimal

config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    eur_gbp_rate=Decimal("0.85")  # Custom rate
)
```

## Supporting Factors Configuration

### SME Supporting Factor

```python
# Enable (default)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=True
)

# Disable for comparison
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=False
)
```

### Infrastructure Factor

```python
# Enable (default)
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_infrastructure_factor=True
)

# Disable
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_infrastructure_factor=False
)
```

## Advanced Configuration

### Accessing Configuration Components

```python
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(date(2026, 12, 31))

# Access sub-components
print(config.framework)              # RegulatoryFramework.CRR
print(config.pd_floors)              # PDFloors object
print(config.lgd_floors)             # LGDFloors object (None for CRR)
print(config.supporting_factors)     # SupportingFactors object
print(config.output_floor_config)    # OutputFloorConfig object (None for CRR)
```

### Custom PD Floors

```python
from rwa_calc.contracts.config import PDFloors

# Custom floors
custom_pd_floors = PDFloors(
    corporate=0.0006,        # 0.06%
    institution=0.0005,      # 0.05%
    retail_mortgage=0.0005,  # 0.05%
    retail_qrre=0.0003,      # 0.03%
    retail_other=0.0005      # 0.05%
)
```

## Configuration Validation

The calculator validates configuration:

```python
# Invalid date
try:
    config = CalculationConfig.crr(
        reporting_date=date(2020, 1, 1)  # Historic date
    )
except ValueError as e:
    print(f"Invalid config: {e}")

# Framework mismatch
try:
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2025, 1, 1)  # Before Basel 3.1 effective
    )
    # Warning issued but allowed for testing
except ValueError:
    pass
```

## Comparison Runs

### Framework Comparison

Run under both frameworks for impact analysis:

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import create_pipeline

pipeline = create_pipeline()

# CRR calculation
config_crr = CalculationConfig.crr(date(2026, 12, 31))
result_crr = pipeline.run(config_crr)

# Basel 3.1 calculation
config_b31 = CalculationConfig.basel_3_1(date(2027, 1, 1))
result_b31 = pipeline.run(config_b31)

# Compare
print(f"CRR RWA: {result_crr.total_rwa:,.0f}")
print(f"Basel 3.1 RWA: {result_b31.total_rwa:,.0f}")
print(f"Impact: {(result_b31.total_rwa / result_crr.total_rwa - 1) * 100:.1f}%")
```

### With/Without Supporting Factors

```python
# With factors
config_with = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=True
)

# Without factors
config_without = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=False
)

result_with = pipeline.run(config_with)
result_without = pipeline.run(config_without)

print(f"With SME factor: {result_with.total_rwa:,.0f}")
print(f"Without: {result_without.total_rwa:,.0f}")
print(f"SME benefit: {result_without.total_rwa - result_with.total_rwa:,.0f}")
```

## Environment Variables

The calculator can read certain settings from environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `RWA_EUR_GBP_RATE` | Default EUR/GBP rate | 0.88 |
| `RWA_DATA_PATH` | Default data directory | ./data |
| `RWA_OUTPUT_PATH` | Default output directory | ./output |

```python
import os

os.environ["RWA_EUR_GBP_RATE"] = "0.85"
os.environ["RWA_DATA_PATH"] = "/path/to/data"
```

## Configuration Best Practices

### 1. Use Factory Methods

```python
# Good - clear intent
config = CalculationConfig.crr(date(2026, 12, 31))

# Avoid - manual construction
config = CalculationConfig(
    framework=RegulatoryFramework.CRR,
    reporting_date=date(2026, 12, 31),
    # ... many more parameters
)
```

### 2. Document Configuration

```python
# Document your configuration choices
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    # Using Q4 2026 rate per Treasury guidance
    eur_gbp_rate=Decimal("0.88"),
    # SME factor enabled per policy
    apply_sme_supporting_factor=True,
)
```

### 3. Version Control Configuration

```python
# Store configuration in version control
CONFIG_Q4_2026 = {
    "reporting_date": "2026-12-31",
    "framework": "CRR",
    "eur_gbp_rate": "0.88",
    "apply_sme_supporting_factor": True,
}
```

## Next Steps

- [Quick Start Guide](../getting-started/quickstart.md)
- [API Reference - Configuration](../api/configuration.md)
- [Framework Comparison](regulatory/comparison.md)
