# Development Guide

This section provides guidance for developers working on the RWA calculator.

## Overview

The development guide covers:

- [**Testing Guide**](testing.md) - Running tests, writing tests, test fixtures
- [**Workbooks & UI**](workbooks.md) - Marimo workbooks and interactive UI applications
- [**Scripts & Automation**](scripts.md) - Developer scripts for setup, deployment, and test data
- [**Benchmark Tests**](benchmarks.md) - Performance and scale testing (10K-10M)
- [**Adding Features**](extending.md) - Extending the calculator
- [**Code Style**](code-style.md) - Coding standards and conventions
- [**Citation Tracking**](citation-tracking.md) - `@cites` decorator conventions, watchfire CLI usage, strict-gate behaviour
- [**Citation Coverage Matrix**](citation-matrix.md) - Auto-generated article -> implementing-function index with click-to-expand source snippets

## Development Setup

### Prerequisites

- Python 3.13+
- uv package manager (recommended)
- Git

### Setup Steps

```bash
# Clone the repository
git clone https://github.com/OpenAfterHours/rwa_calculator.git
cd rwa_calculator

# Install with development dependencies
uv sync --all-extras

# Verify installation
uv run pytest
```

### IDE Configuration

**VS Code:**
```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.formatting.provider": "none",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

**PyCharm:**
1. Open project directory
2. Configure interpreter to use `.venv`
3. Mark `src` as Sources Root
4. Enable Ruff integration

## Development Workflow

### TDD Approach

The project follows Test-Driven Development:

1. **Write acceptance test** - Define expected behavior
2. **Write unit tests** - Test component behavior
3. **Implement** - Write code to pass tests
4. **Refactor** - Improve code while tests pass

### Branch Strategy

```
master
  └── feature/feature-name
  └── fix/bug-description
  └── tests/test-description
```

### Commit Convention

```
type: short description

- Detail 1
- Detail 2

Co-Authored-By: Name <email>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

## Project Structure

```
src/rwa_calc/
├── config/           # Configuration (FX rates)
├── contracts/        # Interfaces and data contracts
│   ├── bundles.py   # Data transfer objects
│   ├── config.py    # Configuration classes
│   ├── errors.py    # Error types
│   ├── protocols.py # Component interfaces
│   └── validation.py
├── data/            # Schemas and lookup tables
│   ├── schemas.py   # Polars schemas
│   └── tables/      # Regulatory tables
├── domain/          # Core domain
│   └── enums.py     # Enumerations
└── engine/          # Calculation engine
    ├── pipeline.py  # Orchestration
    ├── loader.py    # Data loading
    ├── hierarchy.py # Hierarchy resolution
    ├── classifier.py # Classification
    ├── ccf.py       # Credit conversion factors
    ├── aggregator.py # Aggregation
    ├── crm/         # Credit risk mitigation
    ├── sa/          # Standardised approach
    ├── irb/         # IRB approach
    └── slotting/    # Slotting approach
```

## Key Development Principles

### 1. LazyFrame Operations

Always use Polars LazyFrames:

```python
# Good
result = df.with_columns(
    rwa=pl.col("ead") * pl.col("risk_weight")
)

# Bad - row iteration
for row in df.iter_rows():
    rwa = row["ead"] * row["risk_weight"]
```

### 2. Protocol-Based Design

Implement protocols for new components:

```python
from rwa_calc.contracts.protocols import CalculatorProtocol

class MyCalculator:
    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> ResultBundle:
        # Implementation
        ...
```

### 3. Immutable Data

Use frozen dataclasses for data contracts:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MyBundle:
    data: pl.LazyFrame
    metadata: dict
```

### 4. Error Accumulation

Collect errors instead of raising:

```python
errors = []
for exposure in exposures:
    if not valid(exposure):
        errors.append(CalculationError(
            exposure_id=exposure.id,
            message="Invalid exposure"
        ))

return Result(data=data, errors=errors)
```

## Running Tasks

### Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/rwa_calc

# Run specific test file
uv run pytest tests/unit/test_pipeline.py

# Run specific test
uv run pytest tests/unit/test_pipeline.py::test_crr_calculation
```

### Linting

```bash
# Check code style
uv run ruff check src tests

# Fix automatically
uv run ruff check --fix src tests

# Format code
uv run ruff format src tests
```

### Type Checking

```bash
# Run ty
uv run ty src
```

### Documentation

```bash
# Serve documentation locally
uv run zensical serve

# Build documentation
uv run zensical build
```

## Next Steps

- [Testing Guide](testing.md) - Comprehensive testing documentation
- [Adding Features](extending.md) - How to extend the calculator
- [Code Style](code-style.md) - Coding conventions
