# Pipeline API

The pipeline module provides the main entry points for RWA calculation.

## Module: `rwa_calc.engine.pipeline`

### `create_pipeline`

```python
def create_pipeline() -> RWAPipeline:
    """
    Create a pipeline with default components.

    Returns:
        RWAPipeline: Configured pipeline instance.

    Example:
        >>> pipeline = create_pipeline()
        >>> result = pipeline.run(config)
    """
```

### `RWAPipeline`

```python
class RWAPipeline:
    """
    Main RWA calculation pipeline.

    Orchestrates the calculation flow from raw data to final results.
    """

    def __init__(
        self,
        loader: LoaderProtocol,
        hierarchy_resolver: HierarchyResolverProtocol,
        classifier: ClassifierProtocol,
        crm_processor: CRMProcessorProtocol,
        sa_calculator: SACalculatorProtocol,
        irb_calculator: IRBCalculatorProtocol,
        slotting_calculator: SlottingCalculatorProtocol,
        aggregator: OutputAggregatorProtocol,
    ) -> None:
        """
        Initialize pipeline with components.

        Args:
            loader: Data loading component.
            hierarchy_resolver: Hierarchy resolution component.
            classifier: Exposure classification component.
            crm_processor: CRM processing component.
            sa_calculator: SA calculation component.
            irb_calculator: IRB calculation component.
            slotting_calculator: Slotting calculation component.
            aggregator: Output aggregation component.
        """

    def run(self, config: CalculationConfig) -> AggregatedResultBundle:
        """
        Run the complete calculation pipeline.

        Args:
            config: Calculation configuration.

        Returns:
            AggregatedResultBundle: Calculation results.

        Raises:
            CalculationError: If critical errors occur.

        Example:
            >>> config = CalculationConfig.crr(date(2026, 12, 31))
            >>> result = pipeline.run(config)
            >>> print(f"Total RWA: {result.total_rwa:,.0f}")
        """

    def run_with_data(
        self,
        raw_data: RawDataBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Run pipeline with pre-loaded data.

        Args:
            raw_data: Pre-loaded raw data bundle.
            config: Calculation configuration.

        Returns:
            AggregatedResultBundle: Calculation results.

        Example:
            >>> loader = ParquetLoader()
            >>> raw_data = loader.load(Path("./data"))
            >>> result = pipeline.run_with_data(raw_data, config)
        """
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
    apply_sme_supporting_factor=True,
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
