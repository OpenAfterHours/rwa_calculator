# Testing Guide

This guide covers the testing approach, test organization, and how to write effective tests.

## Test Organization

```
tests/
├── acceptance/           # End-to-end scenario tests
│   ├── crr/             # CRR framework scenarios
│   └── basel31/         # Basel 3.1 scenarios
├── benchmarks/          # Performance and scale tests
├── contracts/           # Interface compliance tests
├── unit/                # Component unit tests
│   ├── crr/             # CRR-specific tests
│   ├── basel31/         # Basel 3.1-specific tests
│   └── test_fx_converter.py  # FX conversion tests
└── fixtures/            # Test data generators
    ├── counterparty/    # Counterparty fixtures
    ├── exposures/       # Facility, loan, contingent fixtures
    ├── collateral/      # Collateral fixtures
    ├── guarantee/       # Guarantee fixtures
    ├── provision/       # Provision fixtures
    ├── ratings/         # Rating fixtures
    ├── mapping/         # Hierarchy mapping fixtures
    └── fx_rates/        # FX rates fixtures
```

## Running Tests

### All Tests

```bash
# Run entire test suite
uv run pytest

# With verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=src/rwa_calc --cov-report=html
```

### Specific Tests

```bash
# Run specific file
uv run pytest tests/unit/test_pipeline.py

# Run specific test
uv run pytest tests/unit/test_pipeline.py::test_crr_basic_calculation

# Run by marker
uv run pytest -m "crr"
uv run pytest -m "not slow"

# Run by pattern
uv run pytest -k "test_sa_"
```

### Test Options

```bash
# Stop on first failure
uv run pytest -x

# Show local variables in tracebacks
uv run pytest -l

# Run last failed tests
uv run pytest --lf

# Parallel execution
uv run pytest -n auto
```

## Test Categories

### Unit Tests

Test individual components in isolation:

```python
# tests/unit/test_ccf.py

import pytest
from rwa_calc.engine.ccf import get_ccf
from rwa_calc.domain.enums import RegulatoryFramework

class TestCCF:
    """Tests for credit conversion factor calculation."""

    def test_unconditionally_cancellable_crr_returns_zero(self):
        """Unconditionally cancellable commitments have 0% CCF under CRR."""
        ccf = get_ccf(
            item_type="UNDRAWN_COMMITMENT",
            is_unconditionally_cancellable=True,
            original_maturity_years=5,
            framework=RegulatoryFramework.CRR,
        )
        assert ccf == 0.0

    def test_unconditionally_cancellable_basel31_returns_ten_percent(self):
        """Unconditionally cancellable has 10% CCF under Basel 3.1."""
        ccf = get_ccf(
            item_type="UNDRAWN_COMMITMENT",
            is_unconditionally_cancellable=True,
            original_maturity_years=5,
            framework=RegulatoryFramework.BASEL_3_1,
        )
        assert ccf == 0.10
```

### Contract Tests

Test interface compliance:

```python
# tests/contracts/test_calculator_protocol.py

import pytest
from rwa_calc.contracts.protocols import SACalculatorProtocol
from rwa_calc.engine.sa.calculator import SACalculator

class TestSACalculatorProtocol:
    """Verify SACalculator implements protocol correctly."""

    def test_implements_protocol(self):
        """SACalculator should implement SACalculatorProtocol."""
        calculator = SACalculator()
        assert isinstance(calculator, SACalculatorProtocol)

    def test_calculate_returns_result_bundle(self, sample_exposures, config):
        """Calculate should return SAResultBundle."""
        calculator = SACalculator()
        result = calculator.calculate(sample_exposures, config)
        assert hasattr(result, "data")
        assert hasattr(result, "errors")
```

### Acceptance Tests

Test complete scenarios:

```python
# tests/acceptance/crr/test_scenario_crr_a_sa.py

import pytest
from datetime import date
from rwa_calc.engine.pipeline import create_pipeline
from rwa_calc.contracts.config import CalculationConfig

class TestCRRStandardisedApproach:
    """CRR Standardised Approach acceptance tests."""

    @pytest.fixture
    def pipeline(self):
        return create_pipeline()

    @pytest.fixture
    def crr_config(self):
        return CalculationConfig.crr(reporting_date=date(2026, 12, 31))

    def test_crr_a01_sovereign_cqs1_zero_risk_weight(
        self, pipeline, crr_config, sovereign_cqs1_exposure
    ):
        """
        CRR-A01: Sovereign CQS1 exposure receives 0% risk weight.

        Given: Exposure to UK Government (CQS1)
        When: Calculating RWA under CRR SA
        Then: Risk weight is 0%, RWA is 0
        """
        result = pipeline.run_with_data(sovereign_cqs1_exposure, crr_config)

        assert result.total_rwa == 0
        df = result.to_dataframe()
        assert df.filter(pl.col("exposure_class") == "SOVEREIGN")["risk_weight"][0] == 0.0

    def test_crr_a02_corporate_unrated_100_percent(
        self, pipeline, crr_config, corporate_unrated_exposure
    ):
        """
        CRR-A02: Unrated corporate receives 100% risk weight.

        Given: Unrated corporate exposure of GBP 1m
        When: Calculating RWA under CRR SA
        Then: RWA is GBP 1m (100% risk weight)
        """
        result = pipeline.run_with_data(corporate_unrated_exposure, crr_config)

        assert result.total_rwa == pytest.approx(1_000_000, rel=0.01)
```

## Test Fixtures

### Creating Fixtures

```python
# tests/fixtures/exposures.py

import pytest
import polars as pl
from datetime import date

@pytest.fixture
def sample_counterparty():
    """Single corporate counterparty."""
    return pl.DataFrame({
        "counterparty_id": ["C001"],
        "counterparty_name": ["Acme Corp"],
        "counterparty_type": ["CORPORATE"],
        "country_code": ["GB"],
        "annual_turnover": [30_000_000.0],
    }).lazy()

@pytest.fixture
def sample_facility(sample_counterparty):
    """Single term loan facility."""
    return pl.DataFrame({
        "facility_id": ["F001"],
        "counterparty_id": ["C001"],
        "facility_type": ["TERM"],
        "committed_amount": [1_000_000.0],
        "drawn_amount": [1_000_000.0],
        "currency": ["GBP"],
        "start_date": [date(2024, 1, 1)],
        "maturity_date": [date(2029, 1, 1)],
        "is_unconditionally_cancellable": [False],
        "is_committed": [True],
    }).lazy()

@pytest.fixture
def sample_raw_data(sample_counterparty, sample_facility):
    """Complete raw data bundle."""
    from rwa_calc.contracts.bundles import RawDataBundle

    return RawDataBundle(
        counterparties=sample_counterparty,
        facilities=sample_facility,
        loans=pl.DataFrame().lazy(),
    )
```

### Parametrized Fixtures

```python
@pytest.fixture(params=[
    ("CQS_1", 0.20),
    ("CQS_2", 0.50),
    ("CQS_3", 0.75),
    ("CQS_4", 1.00),
    ("UNRATED", 1.00),
])
def corporate_risk_weight_case(request):
    """Parametrized corporate risk weight test cases."""
    cqs, expected_rw = request.param
    return {"cqs": cqs, "expected_risk_weight": expected_rw}
```

### Configuration Fixtures

```python
# tests/conftest.py

import pytest
from datetime import date
from rwa_calc.contracts.config import CalculationConfig

@pytest.fixture
def crr_config():
    """Standard CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2026, 12, 31))

@pytest.fixture
def basel31_config():
    """Standard Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

@pytest.fixture(params=["crr", "basel31"])
def both_frameworks(request, crr_config, basel31_config):
    """Run test under both frameworks."""
    if request.param == "crr":
        return crr_config
    return basel31_config
```

## Writing Effective Tests

### Test Naming

Use descriptive names that explain:
- What is being tested
- Under what conditions
- Expected outcome

```python
# Good
def test_sme_factor_tiered_calculation_exposure_above_threshold_returns_blended_factor():
    ...

# Bad
def test_sme():
    ...
```

### Test Structure (AAA Pattern)

```python
def test_irb_capital_requirement_calculation():
    """Test IRB K formula calculation."""
    # Arrange
    pd = 0.01
    lgd = 0.45
    correlation = 0.20

    # Act
    k = calculate_k(pd, lgd, correlation)

    # Assert
    assert k == pytest.approx(0.0445, rel=0.01)
```

### Assertions

```python
# Exact equality
assert result == expected

# Approximate equality
assert result == pytest.approx(expected, rel=0.01)  # 1% tolerance
assert result == pytest.approx(expected, abs=0.001)  # Absolute tolerance

# Collections
assert set(result) == set(expected)
assert result in expected_values

# DataFrame assertions
assert len(df) == expected_count
assert df["column"].sum() == expected_sum
```

### Testing Errors

```python
def test_invalid_pd_raises_error():
    """Negative PD should raise ValueError."""
    with pytest.raises(ValueError, match="PD must be positive"):
        calculate_k(pd=-0.01, lgd=0.45, correlation=0.20)

def test_calculation_accumulates_errors():
    """Invalid exposures should accumulate errors."""
    result = pipeline.run_with_data(invalid_data, config)
    assert result.has_errors
    assert any("Invalid PD" in e.message for e in result.errors)
```

## Test Markers

```python
# tests/conftest.py

def pytest_configure(config):
    config.addinivalue_line("markers", "crr: CRR framework tests")
    config.addinivalue_line("markers", "basel31: Basel 3.1 framework tests")
    config.addinivalue_line("markers", "slow: slow-running tests")
    config.addinivalue_line("markers", "integration: integration tests")
```

Usage:
```python
@pytest.mark.crr
def test_crr_specific_feature():
    ...

@pytest.mark.slow
def test_large_portfolio_calculation():
    ...
```

Run by marker:
```bash
uv run pytest -m crr
uv run pytest -m "not slow"
```

## Coverage

### Generate Coverage Report

```bash
# Terminal report
uv run pytest --cov=src/rwa_calc

# HTML report
uv run pytest --cov=src/rwa_calc --cov-report=html
open htmlcov/index.html
```

### Coverage Configuration

```toml
# pyproject.toml
[tool.coverage.run]
source = ["src/rwa_calc"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

## Next Steps

- [BDD Specification](bdd.md) - Gherkin feature files and scenarios
- [Adding Features](extending.md) - Extending the calculator
- [Code Style](code-style.md) - Coding conventions
- [Architecture](../architecture/index.md) - System design
