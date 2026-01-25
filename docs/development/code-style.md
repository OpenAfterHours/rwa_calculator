# Code Style

This guide documents the coding conventions and style guidelines for the RWA calculator.

## General Principles

1. **Clarity over cleverness** - Write readable code
2. **Consistency** - Follow established patterns
3. **Simplicity** - Avoid over-engineering
4. **Type safety** - Use type hints everywhere

## Code Formatting

### Ruff Configuration

The project uses Ruff for linting and formatting:

```toml
# pyproject.toml
[tool.ruff]
target-version = "py313"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "SIM",    # flake8-simplify
]
```

### Running Formatters

```bash
# Check style
uv run ruff check src tests

# Fix issues
uv run ruff check --fix src tests

# Format code
uv run ruff format src tests
```

## Naming Conventions

### Variables and Functions

```python
# snake_case for variables and functions
total_rwa = calculate_total_rwa(exposures)

def calculate_risk_weight(exposure_class: ExposureClass) -> Decimal:
    ...
```

### Classes

```python
# PascalCase for classes
class SACalculator:
    ...

class RawDataBundle:
    ...
```

### Constants

```python
# UPPER_SNAKE_CASE for constants
EUR_GBP_RATE = Decimal("0.88")
MAX_HIERARCHY_DEPTH = 10
DEFAULT_PD_FLOOR = Decimal("0.0003")
```

### Private Members

```python
# Single underscore for internal use
def _validate_exposure(exposure: dict) -> list[Error]:
    ...

# Double underscore for name mangling (rarely used)
class Calculator:
    def __init__(self):
        self.__internal_state = {}
```

## Type Hints

### Function Signatures

```python
from decimal import Decimal
import polars as pl

def calculate_rwa(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> ResultBundle:
    """Calculate RWA for all exposures."""
    ...
```

### Optional Types

```python
from typing import Optional

# Use | None (Python 3.10+)
def get_rating(counterparty_id: str) -> str | None:
    ...

# For collections
def process_exposures(
    exposures: list[Exposure],
    filters: dict[str, str] | None = None,
) -> list[Result]:
    ...
```

### Generic Types

```python
from typing import TypeVar, Generic

T = TypeVar("T")

class Result(Generic[T]):
    def __init__(self, data: T, errors: list[Error]):
        self.data = data
        self.errors = errors
```

## Docstrings

### Google Style

```python
def calculate_maturity_adjustment(
    pd: float,
    effective_maturity: float,
) -> float:
    """
    Calculate maturity adjustment factor for IRB.

    The maturity adjustment accounts for the increased risk
    of longer-dated exposures.

    Args:
        pd: Probability of default (0.0 to 1.0).
        effective_maturity: Effective maturity in years (1-5).

    Returns:
        Maturity adjustment factor.

    Raises:
        ValueError: If PD is not in valid range.

    Example:
        >>> ma = calculate_maturity_adjustment(0.01, 3.0)
        >>> print(f"MA: {ma:.4f}")
        MA: 1.2345
    """
```

### Class Docstrings

```python
class SACalculator:
    """
    Calculate RWA using the Standardised Approach.

    The SA calculator applies regulatory risk weights to exposures
    based on their credit quality and exposure class.

    Attributes:
        config: Calculation configuration.

    Example:
        >>> calculator = SACalculator()
        >>> result = calculator.calculate(exposures, config)
    """
```

## Module Organization

### Import Order

```python
# 1. Standard library
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

# 2. Third-party
import polars as pl
from polars_normal_stats import normal_cdf, normal_ppf

# 3. Local - contracts first
from rwa_calc.contracts.bundles import ResultBundle
from rwa_calc.contracts.config import CalculationConfig

# 4. Local - other modules
from rwa_calc.engine.irb.formulas import calculate_k
```

### Module Structure

```python
"""
Module docstring explaining purpose.

This module provides...
"""

# Imports (as above)

# Constants
DEFAULT_VALUE = Decimal("0.45")

# Main entry point (top of module)
def main_function():
    """Main entry point - at top for visibility."""
    ...

# Supporting functions
def _helper_function():
    """Internal helper."""
    ...

# Classes
class MainClass:
    """Primary class."""
    ...

class _HelperClass:
    """Internal helper class."""
    ...
```

## Data Classes

### Frozen Data Classes

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ResultBundle:
    """Immutable result container."""

    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Whether any errors occurred."""
        return len(self.errors) > 0
```

### With Validation

```python
@dataclass(frozen=True)
class PDFloor:
    """PD floor with validation."""

    value: Decimal

    def __post_init__(self):
        if self.value < 0 or self.value > 1:
            raise ValueError(f"PD floor must be between 0 and 1, got {self.value}")
```

## Error Handling

### Custom Exceptions

```python
class CalculationError(Exception):
    """Base exception for calculation errors."""

    def __init__(
        self,
        message: str,
        exposure_id: str | None = None,
        stage: str | None = None,
    ):
        super().__init__(message)
        self.exposure_id = exposure_id
        self.stage = stage
```

### Error Accumulation

```python
def process_exposures(exposures: list[dict]) -> Result:
    """Process exposures, accumulating errors."""
    results = []
    errors = []

    for exposure in exposures:
        try:
            result = calculate_single(exposure)
            results.append(result)
        except ValidationError as e:
            errors.append(CalculationError(
                message=str(e),
                exposure_id=exposure.get("id"),
            ))

    return Result(data=results, errors=errors)
```

## Polars Best Practices

### Use LazyFrames

```python
# Good - lazy evaluation
result = (
    df
    .filter(pl.col("exposure_class") == "CORPORATE")
    .with_columns(rwa=pl.col("ead") * pl.col("risk_weight"))
    .group_by("counterparty_id")
    .agg(pl.col("rwa").sum())
)

# Bad - eager evaluation
df_filtered = df.filter(pl.col("exposure_class") == "CORPORATE").collect()
df_with_rwa = df_filtered.with_columns(...)  # Loses optimization
```

### Chain Operations

```python
# Good - single chain
result = (
    df
    .filter(condition)
    .with_columns(new_col)
    .group_by(group_col)
    .agg(aggregations)
)

# Bad - multiple assignments
df1 = df.filter(condition)
df2 = df1.with_columns(new_col)
df3 = df2.group_by(group_col)
result = df3.agg(aggregations)
```

### Use Expressions

```python
# Good - vectorized
df.with_columns(
    rwa=pl.col("ead") * pl.col("risk_weight")
)

# Bad - row iteration
for row in df.iter_rows():
    rwa = row["ead"] * row["risk_weight"]
```

## Testing Style

### Test Naming

```python
# Descriptive names
def test_sme_factor_returns_0_7619_for_exposure_below_threshold():
    ...

def test_irb_calculator_raises_error_for_negative_pd():
    ...

# Not
def test_sme():
    ...
```

### Arrange-Act-Assert

```python
def test_calculate_k():
    """Test IRB K formula calculation."""
    # Arrange
    pd = 0.01
    lgd = 0.45
    correlation = 0.20

    # Act
    result = calculate_k(pd, lgd, correlation)

    # Assert
    assert result == pytest.approx(0.0445, rel=0.01)
```

## Comments

### When to Comment

```python
# Good - explain why, not what
# CRR Article 153 requires 1.06 scaling for all IRB exposures
rwa = k * 12.5 * ead * ma * 1.06

# Bad - obvious comment
# Calculate RWA
rwa = k * 12.5 * ead * ma * 1.06
```

### TODO Comments

```python
# TODO: Implement Basel 3.1 output floor calculation
# Reference: CRE99

# FIXME: Handle edge case where maturity < 1 year
```

## Next Steps

- [Testing Guide](testing.md) - Writing tests
- [Adding Features](extending.md) - Extending the calculator
- [Architecture](../architecture/index.md) - System design
