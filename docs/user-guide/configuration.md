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

    # Optional - General
    eur_gbp_rate=Decimal("0.88"),          # Default: 0.88
)
```

!!! note "Supporting factors are pack-driven under CRR"
    The CRR SME and infrastructure supporting factors are applied automatically
    from the rulepack pack (`rwa_calc.rulebook`) when the regime is CRR — they are
    not toggled via config flags. To compare with/without, run CRR vs Basel 3.1
    (which withdraws them) rather than flipping a config flag.

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

## Permission Mode

The `permission_mode` parameter controls whether exposures are calculated using the
Standardised Approach (SA) or routed to IRB based on model-level permissions.

### Standardised Mode (Default)

```python
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode

# All exposures use SA — this is the default
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.STANDARDISED,
)
```

### IRB Mode

In IRB mode, approach routing is driven by the `model_permissions` input table. Each
model's approved approach (AIRB, FIRB, slotting) is resolved per-exposure. Exposures
without a matching model permission fall back to SA.

```python
# IRB routing — requires model_permissions input data
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    permission_mode=PermissionMode.IRB,
)
```

| Mode | Behaviour |
|------|-----------|
| `PermissionMode.STANDARDISED` | All exposures use the Standardised Approach. No IRB routing. |
| `PermissionMode.IRB` | Approach routing is driven by the `model_permissions` input table. Exposures without a matching model permission fall back to SA. If no `model_permissions` file is provided, all exposures fall back to SA with a warning. |

When using the Service API, pass the string values `"standardised"` or `"irb"`:

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

# SA-only (default)
response = CreditRiskCalc(
    data_path="/path/to/data",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
).calculate()

# IRB mode
response = CreditRiskCalc(
    data_path="/path/to/data",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
    permission_mode="irb",
).calculate()
```

!!! note "Model permissions required for IRB mode"
    When using IRB mode, provide a `model_permissions` input table to control which
    exposures use FIRB, AIRB, or slotting. Without it, all exposures fall back to SA
    with a warning. See
    [Input Schemas — Model Permissions](../data-model/input-schemas.md#model-permissions-schema).

## Configuration Parameters

### Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reporting_date` | `date` | Required | Calculation reference date |
| `permission_mode` | `PermissionMode` | `STANDARDISED` | SA-only or IRB with model permissions |
| `eur_gbp_rate` | `Decimal` | 0.88 | EUR to GBP conversion rate |

### CRR-Specific Parameters

CRR has no config-set regulatory toggles. The SME supporting factor (Art. 501) and
the infrastructure factor are applied automatically from the rulepack pack
(`rwa_calc.rulebook`) when the regime is CRR — they are no longer `apply_*` config
flags. Select the regime with `CalculationConfig.crr(...)`.

### Basel 3.1-Specific Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_floor_percentage` | `float` | 0.725 | Output floor percentage |
| `transitional_floor_year` | `int` | None | Year for transitional floor |

## Framework Differences

The config selects the regime via `regime_id` (set by `.crr()` / `.basel_3_1()`);
`framework` is a derived read-only property. The regulatory parameters below are **not**
carried on the config — they are resolved per regime from the rulepack pack
(`rwa_calc.rulebook`, via `resolve(regime_id, reporting_date)`):

### Regime Differences (resolved from the rulepack)

| Parameter | CRR | Basel 3.1 |
|---------|-----|-----------|
| `framework` (derived property) | `RegulatoryFramework.CRR` | `RegulatoryFramework.BASEL_3_1` |
| IRB scaling factor | 1.06 | 1.00 |
| PD floors | Uniform 0.03% | Differentiated |
| A-IRB LGD floors | None | By collateral type |
| Output floor | None | 72.5% (or transitional) |
| Supporting factors | Available | Withdrawn |

### PD Floors

```python
# CRR - All exposures
pd_floor = 0.0003  # 0.03%

# Basel 3.1 - Differentiated
pd_floors = {
    "CORPORATE": 0.0005,           # 0.05%
    "INSTITUTION": 0.0005,         # 0.05%
    "RETAIL_MORTGAGE": 0.0010,     # 0.10%
    "RETAIL_QRRE_TRANSACTOR": 0.0005,  # 0.05%
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
    "RECEIVABLES": 0.10,           # 10%
    "CRE": 0.10,                   # 10%
    "RRE": 0.10,                   # 10% (corporate, Art. 161(5); retail RRE is 5%, Art. 164(4)(a))
    "OTHER_PHYSICAL": 0.15,        # 15%
}
```

## Output Floor Configuration

### Phase-In Schedule

| Year | Floor Percentage |
|------|------------------|
| 2027 | 60.0% |
| 2028 | 65.0% |
| 2029 | 70.0% |
| 2030+ | 72.5% |

Note: PRA compressed the BCBS 6-year schedule to 4 years. Transitional rates are
permissive (Art. 92 para 5) — firms may use 72.5% from day one.

### Transitional Configuration

```python
# Automatically calculate transitional floor
config = CalculationConfig.basel_3_1(
    reporting_date=date(2028, 6, 30),
    transitional_floor_year=2028  # Uses 65% floor (PRA 4-year schedule)
)

# Or specify exact percentage
config = CalculationConfig.basel_3_1(
    reporting_date=date(2028, 6, 30),
    output_floor_percentage=0.65  # Explicit 65%
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

## Supporting Factors

The SME supporting factor (Art. 501) and the infrastructure factor are applied
automatically from the rulepack pack (`rwa_calc.rulebook`) when the regime is CRR.
They are no longer toggled via `apply_*` config flags. Basel 3.1 withdraws both, so
to compare with/without supporting factors run CRR vs Basel 3.1 rather than flipping
a config flag:

```python
# With supporting factors — CRR regime
config_crr = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Without supporting factors — Basel 3.1 regime (withdrawn)
config_b31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))
```

## Advanced Configuration

### Accessing Configuration Components

```python
from rwa_calc.contracts.config import CalculationConfig

config = CalculationConfig.crr(date(2026, 12, 31))

# Access config-carried fields
print(config.regime_id)              # "crr"
print(config.framework)              # RegulatoryFramework.CRR (derived property)
print(config.output_floor)           # output-floor election (None for CRR)

# Regulatory parameters are NOT on the config — inspect them via the resolved
# rulepack pack (read at the regime + reporting date):
from rwa_calc.rulebook.resolve import resolve

pack = resolve(config.regime_id, config.reporting_date)
print(pack.formula("pd_floors"))     # PD floors for the regime (cited pack entry)
```

### Custom Regulatory Values

PD floors (and all other regulatory values) are no longer user-overridable config
objects — they are cited entries in the rulepack packs
(`src/rwa_calc/rulebook/packs/{common,crr,b31}.py`). To change a regulatory value,
edit or extend the relevant pack entry (with its `Citation`) rather than constructing
a config override. The config only selects the regime via `regime_id`.

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

Supporting factors are pack-driven, not a config flag. CRR applies them; Basel 3.1
withdraws them. Compare the two regimes to see their effect:

```python
# With factors — CRR regime
config_with = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Without factors — Basel 3.1 regime (supporting factors withdrawn)
config_without = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

result_with = pipeline.run(config_with)
result_without = pipeline.run(config_without)

print(f"With SME factor (CRR): {result_with.total_rwa:,.0f}")
print(f"Without (Basel 3.1): {result_without.total_rwa:,.0f}")
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
# (regime is carried by regime_id; framework is a derived read-only property)
config = CalculationConfig(
    regime_id="crr",
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
)
```

### 3. Version Control Configuration

```python
# Store configuration in version control
CONFIG_Q4_2026 = {
    "reporting_date": "2026-12-31",
    "regime_id": "crr",
    "eur_gbp_rate": "0.88",
}
```

## Next Steps

- [Quick Start Guide](../getting-started/quickstart.md)
- [API Reference - Configuration](../api/configuration.md)
- [Framework Comparison](../framework-comparison/index.md)
