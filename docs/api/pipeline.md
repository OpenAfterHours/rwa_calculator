# Pipeline API

The pipeline module provides the main entry points for RWA calculation. See [`pipeline.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/src/rwa_calc/engine/pipeline.py) for the full implementation.

## Module: `rwa_calc.engine.pipeline`

### `create_pipeline`

Factory function to create a pipeline with default components:

::: rwa_calc.engine.pipeline.create_pipeline
    options:
      show_root_heading: false
      show_source: false

### `PipelineOrchestrator`

The main pipeline class (note: the class is `PipelineOrchestrator`, not `RWAPipeline`):

::: rwa_calc.engine.pipeline.PipelineOrchestrator
    options:
      show_root_heading: true
      members:
        - run
        - run_with_data
      show_source: false

??? example "Pipeline Implementation (pipeline.py)"
    ```python
    --8<-- "src/rwa_calc/engine/pipeline.py:80:180"
    ```

## Usage Examples

### Basic Usage

```python
from datetime import date
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

# Create pipeline
pipeline = create_pipeline()

# Configure for CRR
config = CalculationConfig.crr(
    reporting_date=date(2026, 12, 31),
)

# Run calculation
result = pipeline.run(config)

# Access results
print(f"Total RWA: {result.total_rwa:,.0f}")
print(f"SA RWA: {result.sa_rwa:,.0f}")
print(f"IRB RWA: {result.irb_rwa:,.0f}")
```

### With Custom Data Path

```python
from pathlib import Path
from rwa_calc.engine.loader import ParquetLoader

# Load data from custom path
loader = ParquetLoader()
raw_data = loader.load(Path("/path/to/data"))

# Run with pre-loaded data
result = pipeline.run_with_data(raw_data, config)
```

### Framework Comparison

```python
# Run under both frameworks
config_crr = CalculationConfig.crr(date(2026, 12, 31))
config_b31 = CalculationConfig.basel_3_1(date(2027, 1, 1))

result_crr = pipeline.run(config_crr)
result_b31 = pipeline.run(config_b31)

# Compare
impact = (result_b31.total_rwa / result_crr.total_rwa - 1) * 100
print(f"Basel 3.1 impact: {impact:+.1f}%")
```

### Error Handling

```python
result = pipeline.run(config)

# Check for errors
if result.has_errors:
    print("Calculation completed with errors:")
    for error in result.errors:
        print(f"  - {error.exposure_id}: {error.message}")

# Check for warnings
if result.has_warnings:
    print("Warnings:")
    for warning in result.warnings:
        print(f"  - {warning.message}")
```

## Related

- [Configuration API](configuration.md)
- [Contracts API](contracts.md)
- [Architecture - Pipeline](../architecture/pipeline.md)
