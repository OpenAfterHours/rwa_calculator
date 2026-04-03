# API Reference

This section provides complete API documentation for the RWA calculator modules.

## Module Overview

| Module | Purpose |
|--------|---------|
| [**Service API**](service.md) | High-level facade: `quick_calculate`, `RWAService`, request/response models |
| [**Pipeline**](pipeline.md) | Low-level orchestration and custom pipeline construction |
| [**Configuration**](configuration.md) | Configuration classes and factories |
| [**Engine**](engine.md) | Calculation components |
| [**Contracts**](contracts.md) | Interfaces and data contracts |
| [**Domain**](domain.md) | Enumerations and core types |

## Quick Reference

### Main Entry Point

```python
from rwa_calc.api import quick_calculate

# One-liner calculation
response = quick_calculate("/path/to/data")
print(f"Total RWA: {response.summary.total_rwa:,.0f}")
```

### Service API (More Control)

```python
from datetime import date
from rwa_calc.api import RWAService, CalculationRequest, create_service

service = create_service()
response = service.calculate(
    CalculationRequest(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2026, 12, 31),
        permission_mode="irb",
    )
)

if response.success:
    print(f"Total RWA: {response.summary.total_rwa:,.0f}")
    df = response.collect_results()
```

### Pipeline API (Advanced)

For custom loaders or direct pipeline access:

```python
from datetime import date
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

pipeline = create_pipeline()
config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
result = pipeline.run(config)
```

### Configuration

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR configuration
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
)

# Basel 3.1 configuration
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 1, 1),
)
```

### Enumerations

```python
from rwa_calc.domain.enums import (
    RegulatoryFramework,
    ExposureClass,
    ApproachType,
    CQS,
    CollateralType,
)
```

### Data Contracts

```python
from rwa_calc.contracts.bundles import (
    RawDataBundle,
    ResolvedHierarchyBundle,
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
    SAResultBundle,
    IRBResultBundle,
    SlottingResultBundle,
    AggregatedResultBundle,
)
```

## API Sections

- [**Service API**](service.md) - High-level facade (`quick_calculate`, `RWAService`)
- [**Pipeline API**](pipeline.md) - Pipeline creation and execution
- [**Configuration API**](configuration.md) - Configuration classes
- [**Engine API**](engine.md) - Calculation components
- [**Contracts API**](contracts.md) - Data contracts and protocols
- [**Domain API**](domain.md) - Enumerations and types
