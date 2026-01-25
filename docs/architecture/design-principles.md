# Design Principles

This document explains the key architectural decisions and design principles underlying the RWA calculator.

## Core Principles

### 1. Single Codebase, Dual Framework

**Decision:** Support both CRR and Basel 3.1 in a single codebase.

**Rationale:**
- Avoids code duplication
- Enables easy comparison between frameworks
- Simplifies maintenance
- Supports transition planning

**Implementation:**
```python
# Framework-specific behavior controlled by configuration
if config.framework == RegulatoryFramework.CRR:
    rwa = rwa * config.scaling_factor  # 1.06
else:
    rwa = apply_output_floor(rwa, sa_rwa, config.output_floor)
```

### 2. Pure LazyFrame Operations

**Decision:** Use Polars LazyFrames exclusively for all data operations.

**Rationale:**
- Enables query optimization by Polars
- Reduces memory usage through lazy evaluation
- Allows automatic parallelization
- Avoids row-by-row iteration (major performance gain)

**Anti-pattern (Avoided):**
```python
# BAD: Row-by-row processing
for row in dataframe.iter_rows():
    result = calculate_rwa(row)
    results.append(result)
```

**Pattern (Used):**
```python
# GOOD: Vectorized operation
result = df.with_columns(
    rwa=pl.col("ead") * pl.col("risk_weight") * pl.col("factor")
)
```

### 3. Protocol-Based Interfaces

**Decision:** Define component interfaces using Python Protocols.

**Rationale:**
- Enables dependency injection
- Supports testing with mocks
- Allows multiple implementations
- Documents expected behavior

**Implementation:**
```python
from typing import Protocol

class LoaderProtocol(Protocol):
    def load(self, path: Path) -> RawDataBundle:
        """Load raw data from source."""
        ...

# Any class with matching signature satisfies protocol
class ParquetLoader:
    def load(self, path: Path) -> RawDataBundle:
        # Implementation
        ...

class MockLoader:
    def load(self, path: Path) -> RawDataBundle:
        # Test implementation
        ...
```

### 4. Immutable Data Contracts

**Decision:** All data transfer objects (bundles) are frozen dataclasses.

**Rationale:**
- Prevents accidental mutation
- Ensures thread safety
- Supports lazy evaluation
- Makes data flow predictable

**Implementation:**
```python
from dataclasses import dataclass
import polars as pl

@dataclass(frozen=True)
class RawDataBundle:
    counterparties: pl.LazyFrame
    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    collateral: pl.LazyFrame | None = None
    guarantees: pl.LazyFrame | None = None
```

### 5. Error Accumulation

**Decision:** Accumulate errors rather than fail fast.

**Rationale:**
- Reports all validation issues at once
- Supports audit requirements
- Allows partial results
- Better user experience

**Implementation:**
```python
@dataclass
class LazyFrameResult:
    data: pl.LazyFrame
    errors: list[CalculationError]
    warnings: list[CalculationWarning]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

# Usage
result = processor.process(exposures, config)
if result.has_errors:
    for error in result.errors:
        logger.error(f"{error.exposure_id}: {error.message}")
```

### 6. Factory Methods for Configuration

**Decision:** Use factory methods rather than direct construction.

**Rationale:**
- Self-documenting code
- Encapsulates complex initialization
- Ensures valid combinations
- Easier to use correctly

**Implementation:**
```python
class CalculationConfig:
    @classmethod
    def crr(cls, reporting_date: date, **kwargs) -> "CalculationConfig":
        """Create CRR configuration with appropriate defaults."""
        return cls(
            framework=RegulatoryFramework.CRR,
            reporting_date=reporting_date,
            scaling_factor=Decimal("1.06"),
            pd_floors=PDFloors.crr(),
            # ... other CRR defaults
            **kwargs
        )

    @classmethod
    def basel_3_1(cls, reporting_date: date, **kwargs) -> "CalculationConfig":
        """Create Basel 3.1 configuration with appropriate defaults."""
        return cls(
            framework=RegulatoryFramework.BASEL_3_1,
            reporting_date=reporting_date,
            scaling_factor=Decimal("1.0"),
            pd_floors=PDFloors.basel_3_1(),
            # ... other Basel 3.1 defaults
            **kwargs
        )
```

### 7. Hierarchical Join Pattern

**Decision:** Use iterative joins for hierarchy resolution instead of Python dictionaries.

**Rationale:**
- 50-100x performance improvement
- Stays within Polars optimization
- Handles deep hierarchies efficiently
- Avoids Python GIL limitations

**Anti-pattern (Avoided):**
```python
# BAD: Python dictionary lookup
parent_dict = {row['id']: row['parent'] for row in df}
results = [parent_dict.get(x) for x in ids]
```

**Pattern (Used):**
```python
# GOOD: Polars join
result = (
    df
    .join(parent_df, left_on="parent_id", right_on="id")
    .select(["id", "resolved_parent"])
)
```

## Module Organization

### Main Entry Point First

**Decision:** Place main entry points at the top of modules.

**Rationale:**
- Reads like a book
- Easy to find key functionality
- Follows "newspaper" style
- Better developer experience

**Implementation:**
```python
# module.py

# Main entry point at top
def calculate_rwa(exposures: Bundle, config: Config) -> Result:
    """Calculate RWA for all exposures."""
    validated = _validate_exposures(exposures)
    enriched = _apply_crm(validated, config)
    return _compute_rwa(enriched, config)


# Supporting functions below
def _validate_exposures(exposures: Bundle) -> Bundle:
    ...

def _apply_crm(exposures: Bundle, config: Config) -> Bundle:
    ...

def _compute_rwa(exposures: Bundle, config: Config) -> Result:
    ...
```

### Clean Imports

**Decision:** Organize imports clearly with separation.

```python
# Standard library
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Third-party
import polars as pl
from polars_normal_stats import normal_cdf, normal_ppf

# Local - contracts first
from rwa_calc.contracts.bundles import ResultBundle
from rwa_calc.contracts.config import CalculationConfig

# Local - engine components
from rwa_calc.engine.irb.formulas import calculate_k
```

## Error Handling Strategy

### Validation Errors

Collected and reported:
```python
errors = []
if pd < config.pd_floors.minimum:
    errors.append(ValidationError(
        field="pd",
        message=f"PD {pd} below floor {config.pd_floors.minimum}"
    ))
```

### Calculation Errors

Logged with context:
```python
try:
    k = calculate_k(pd, lgd, correlation)
except ValueError as e:
    errors.append(CalculationError(
        exposure_id=exposure.id,
        stage="IRB",
        message=str(e)
    ))
```

### System Errors

Raised immediately:
```python
if config is None:
    raise RuntimeError("Configuration must be provided")
```

## Testing Philosophy

### Test-Driven Development

1. Write acceptance test (what should happen)
2. Write unit tests (how it should work)
3. Implement to pass tests
4. Refactor with confidence

### Test Organization

```
tests/
├── acceptance/           # End-to-end scenarios
│   ├── crr/             # CRR scenarios
│   └── basel31/         # Basel 3.1 scenarios
├── contracts/           # Interface compliance
├── unit/                # Component tests
│   ├── test_loader.py
│   ├── test_hierarchy.py
│   └── crr/             # Framework-specific
└── fixtures/            # Test data generation
```

### Test Naming

```python
def test_sa_corporate_rated_cqs2_returns_50_percent_risk_weight():
    """Clear description of what is being tested."""
    ...

def test_sme_factor_tiered_calculation_above_threshold():
    """Documents the specific scenario."""
    ...
```

## Documentation Philosophy

### Code as Documentation

Self-documenting names and types:
```python
def calculate_maturity_adjustment(
    pd: float,
    effective_maturity_years: float
) -> float:
    """Calculate maturity adjustment factor for IRB."""
    ...
```

### Regulatory References

Link to articles:
```python
def calculate_sme_supporting_factor(
    total_exposure: Decimal,
    threshold: Decimal = EUR_2_5M
) -> Decimal:
    """
    Calculate SME supporting factor per CRR Article 501.

    The factor provides capital relief for SME exposures using
    a tiered approach based on total exposure amount.
    """
    ...
```

## Next Steps

- [Pipeline Architecture](pipeline.md) - Detailed pipeline documentation
- [Data Flow](data-flow.md) - How data moves through the system
- [Component Overview](components.md) - Individual components
