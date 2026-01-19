# API Reference

This section provides complete API documentation for the RWA calculator modules.

## Module Overview

| Module | Purpose |
|--------|---------|
| [**Pipeline**](pipeline.md) | Main orchestration and entry points |
| [**Configuration**](configuration.md) | Configuration classes and factories |
| [**Engine**](engine.md) | Calculation components |
| [**Contracts**](contracts.md) | Interfaces and data contracts |
| [**Domain**](domain.md) | Enumerations and core types |

## Quick Reference

### Main Entry Point

```python
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

# Create and run pipeline
pipeline = create_pipeline()
config = CalculationConfig.crr(date(2026, 12, 31))
result = pipeline.run(config)
```

### Configuration

```python
from rwa_calc.contracts.config import CalculationConfig

# CRR configuration
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
    apply_sme_supporting_factor=True,
)

# Basel 3.1 configuration
config = CalculationConfig.basel_3_1(
    reporting_date=date(2027, 1, 1),
    output_floor_percentage=0.725,
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

- [**Pipeline API**](pipeline.md) - Pipeline creation and execution
- [**Configuration API**](configuration.md) - Configuration classes
- [**Engine API**](engine.md) - Calculation components
- [**Contracts API**](contracts.md) - Data contracts and protocols
- [**Domain API**](domain.md) - Enumerations and types
