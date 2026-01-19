# Adding Features

This guide explains how to extend the RWA calculator with new functionality.

## Extension Points

The calculator is designed for extensibility at several points:

1. **New exposure classes**
2. **New calculation approaches**
3. **New CRM types**
4. **Custom data loaders**
5. **New regulatory tables**

## Adding a New Exposure Class

### Step 1: Add Enum Value

```python
# src/rwa_calc/domain/enums.py

class ExposureClass(str, Enum):
    # ... existing classes ...
    NEW_CLASS = "NEW_CLASS"  # Add new class
```

### Step 2: Add Classification Logic

```python
# src/rwa_calc/engine/classifier.py

def _determine_exposure_class(
    counterparty_type: str,
    # ... other params ...
) -> ExposureClass:
    # Add classification rule
    if counterparty_type == "NEW_TYPE":
        return ExposureClass.NEW_CLASS

    # ... existing logic ...
```

### Step 3: Add Risk Weight Table

```python
# src/rwa_calc/data/tables/crr_risk_weights.py

NEW_CLASS_RISK_WEIGHTS = {
    CQS.CQS_1: Decimal("0.20"),
    CQS.CQS_2: Decimal("0.50"),
    # ... etc ...
}

def get_risk_weight(
    exposure_class: ExposureClass,
    cqs: CQS,
    framework: RegulatoryFramework,
) -> Decimal:
    if exposure_class == ExposureClass.NEW_CLASS:
        return NEW_CLASS_RISK_WEIGHTS.get(cqs, Decimal("1.00"))
    # ... existing logic ...
```

### Step 4: Add Tests

```python
# tests/unit/test_new_class.py

class TestNewExposureClass:
    def test_classification(self):
        """NEW_TYPE counterparty classified as NEW_CLASS."""
        # ...

    def test_risk_weights(self):
        """NEW_CLASS risk weights are correct."""
        # ...
```

## Adding a Custom Calculator

### Step 1: Implement Protocol

```python
# src/rwa_calc/engine/custom/calculator.py

from rwa_calc.contracts.protocols import CalculatorProtocol
from rwa_calc.contracts.bundles import ResultBundle

class CustomCalculator:
    """Custom calculator for specialized exposures."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> ResultBundle:
        """Calculate RWA using custom methodology."""
        result = (
            exposures
            .with_columns(
                # Custom calculation logic
                rwa=self._calculate_custom_rwa(
                    pl.col("ead"),
                    pl.col("custom_param"),
                )
            )
        )

        return ResultBundle(data=result)

    def _calculate_custom_rwa(
        self,
        ead: pl.Expr,
        custom_param: pl.Expr,
    ) -> pl.Expr:
        """Custom RWA calculation."""
        return ead * custom_param * 0.08  # Example
```

### Step 2: Register in Pipeline

```python
# src/rwa_calc/engine/pipeline.py

def create_pipeline(
    custom_calculator: CustomCalculator | None = None,
) -> RWAPipeline:
    """Create pipeline with optional custom calculator."""
    return RWAPipeline(
        # ... existing components ...
        custom_calculator=custom_calculator or CustomCalculator(),
    )
```

### Step 3: Add Tests

```python
# tests/unit/test_custom_calculator.py

class TestCustomCalculator:
    def test_implements_protocol(self):
        calculator = CustomCalculator()
        # Verify protocol compliance

    def test_calculation_logic(self, sample_exposures, config):
        calculator = CustomCalculator()
        result = calculator.calculate(sample_exposures, config)
        # Verify results
```

## Adding a New Data Loader

### Step 1: Implement Protocol

```python
# src/rwa_calc/engine/loaders/csv_loader.py

from rwa_calc.contracts.protocols import LoaderProtocol
from rwa_calc.contracts.bundles import RawDataBundle

class CSVLoader:
    """Load data from CSV files."""

    def load(self, path: Path) -> RawDataBundle:
        """Load all data files from directory."""
        return RawDataBundle(
            counterparties=pl.scan_csv(path / "counterparties.csv"),
            facilities=pl.scan_csv(path / "facilities.csv"),
            loans=pl.scan_csv(path / "loans.csv"),
            # ... other files ...
        )
```

### Step 2: Use in Pipeline

```python
from rwa_calc.engine.loaders.csv_loader import CSVLoader
from rwa_calc.engine.pipeline import RWAPipeline

# Create pipeline with CSV loader
csv_loader = CSVLoader()
pipeline = RWAPipeline(
    loader=csv_loader,
    # ... other components ...
)
```

## Adding New CRM Type

### Step 1: Add Collateral Type

```python
# src/rwa_calc/domain/enums.py

class CollateralType(str, Enum):
    # ... existing types ...
    NEW_COLLATERAL = "NEW_COLLATERAL"
```

### Step 2: Add Haircut Table

```python
# src/rwa_calc/data/tables/crr_haircuts.py

NEW_COLLATERAL_HAIRCUTS = {
    "<=1yr": Decimal("0.05"),
    "1-5yr": Decimal("0.10"),
    ">5yr": Decimal("0.15"),
}
```

### Step 3: Update CRM Processor

```python
# src/rwa_calc/engine/crm/processor.py

def _get_haircut(
    collateral_type: CollateralType,
    residual_maturity: float,
) -> Decimal:
    if collateral_type == CollateralType.NEW_COLLATERAL:
        if residual_maturity <= 1:
            return NEW_COLLATERAL_HAIRCUTS["<=1yr"]
        # ... etc ...
```

## Adding Basel 3.1 Features

### Step 1: Add Configuration

```python
# src/rwa_calc/contracts/config.py

@dataclass(frozen=True)
class Basel31SpecificConfig:
    """Basel 3.1 specific configuration."""
    new_feature_enabled: bool = True
    new_feature_threshold: Decimal = Decimal("0.05")
```

### Step 2: Conditional Logic

```python
# In calculator
def calculate(self, exposures: pl.LazyFrame, config: CalculationConfig):
    result = exposures

    if config.framework == RegulatoryFramework.BASEL_3_1:
        result = self._apply_basel31_treatment(result, config)

    return result

def _apply_basel31_treatment(
    self,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Apply Basel 3.1 specific treatment."""
    return exposures.with_columns(
        # Basel 3.1 specific logic
    )
```

## Adding New Regulatory Table

### Step 1: Create Table Module

```python
# src/rwa_calc/data/tables/new_table.py

import polars as pl
from decimal import Decimal

NEW_TABLE = pl.DataFrame({
    "category": ["A", "B", "C"],
    "weight": [0.10, 0.20, 0.30],
})

def lookup_new_table(category: str) -> Decimal:
    """Look up value from new table."""
    result = NEW_TABLE.filter(pl.col("category") == category)
    if len(result) == 0:
        raise ValueError(f"Unknown category: {category}")
    return Decimal(str(result["weight"][0]))
```

### Step 2: Add Tests

```python
# tests/unit/test_new_table.py

class TestNewTable:
    @pytest.mark.parametrize("category,expected", [
        ("A", Decimal("0.10")),
        ("B", Decimal("0.20")),
        ("C", Decimal("0.30")),
    ])
    def test_lookup_returns_correct_value(self, category, expected):
        result = lookup_new_table(category)
        assert result == expected

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError):
            lookup_new_table("UNKNOWN")
```

## Best Practices

### 1. Follow Existing Patterns

Look at existing implementations for guidance:
- `sa/calculator.py` for calculator patterns
- `data/tables/*.py` for lookup tables
- `contracts/bundles.py` for data contracts

### 2. Write Tests First

Follow TDD:
1. Write failing acceptance test
2. Write failing unit tests
3. Implement to pass tests
4. Refactor

### 3. Use Type Hints

```python
def calculate_rwa(
    ead: float,
    risk_weight: Decimal,
    factor: Decimal | None = None,
) -> Decimal:
    """Calculate RWA with optional factor."""
    base_rwa = Decimal(str(ead)) * risk_weight
    if factor is not None:
        return base_rwa * factor
    return base_rwa
```

### 4. Document Regulatory References

```python
def calculate_sme_factor(total_exposure: Decimal) -> Decimal:
    """
    Calculate SME supporting factor per CRR Article 501.

    The factor provides capital relief using a tiered approach:
    - Exposure <= EUR 2.5m: 0.7619 factor
    - Exposure > EUR 2.5m: Blended factor

    Args:
        total_exposure: Total exposure to SME counterparty.

    Returns:
        SME supporting factor (0.7619 to 0.85).
    """
```

### 5. Update Documentation

After adding features, update:
- API documentation
- User guide (if user-facing)
- Changelog

## Next Steps

- [Code Style](code-style.md) - Coding conventions
- [Testing Guide](testing.md) - Writing tests
- [Architecture](../architecture/index.md) - System design
