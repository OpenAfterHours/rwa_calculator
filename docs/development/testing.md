# Testing Guide

This guide covers the testing approach, test organisation, and how to write effective tests. The test suite currently contains **~2,065 tests** across unit, acceptance, contract, integration, and benchmark categories.

| Category | Tests | Description |
|----------|------:|-------------|
| Unit | 1,537 | Component tests in isolation |
| Acceptance | 275 | End-to-end regulatory scenarios (CRR + Basel 3.1 + comparison) |
| Contract | 125 | Protocol/interface compliance |
| Benchmark | 27–34 | Performance at various scales (7 slow tests deselected by default) |
| Integration | 101 | Cross-component integration |
| **Total** | **~2,065** | |

## Test Organisation

```
tests/
├── unit/                    # Component unit tests (1,537 tests)
│   ├── crr/                 # CRR-specific tests
│   ├── crm/                 # Credit risk mitigation tests
│   ├── irb/                 # IRB-specific tests
│   ├── basel31/             # Basel 3.1-specific tests
│   └── api/                 # API tests
├── acceptance/              # End-to-end scenario tests (275 tests)
│   ├── crr/                 # CRR framework scenarios (97 tests)
│   ├── basel31/             # Basel 3.1 framework scenarios (116 tests)
│   └── comparison/          # Cross-framework comparison tests (62 tests)
├── contracts/               # Interface compliance tests (125 tests)
├── integration/             # Cross-component integration tests (101 tests)
├── benchmarks/              # Performance tests (27–34 tests)
│   ├── data_generators.py   # Dataset generation for various scales
│   └── data/                # Cached benchmark datasets (parquet)
├── bdd/                     # BDD-style tests (step definitions)
├── fixtures/                # Test data generators (parquet fixtures)
│   ├── counterparty/        # Counterparty fixtures (5 types)
│   ├── exposures/           # Facility, loan, contingent, mapping fixtures
│   ├── collateral/          # Collateral fixtures
│   ├── guarantee/           # Guarantee fixtures
│   ├── provision/           # Provision fixtures
│   ├── ratings/             # Rating fixtures
│   ├── mapping/             # Hierarchy mapping fixtures
│   ├── fx_rates/            # FX rates fixtures
│   └── generate_all.py      # Master fixture generation script
└── expected_outputs/        # Golden files for acceptance tests
    ├── crr/                 # CRR expected RWA outputs
    └── basel31/             # Basel 3.1 expected RWA outputs
```

## Running Tests

### All Tests

```bash
# Run entire test suite (benchmarks and slow tests excluded by default)
uv run pytest

# With verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=src/rwa_calc --cov-report=html
```

### By Category

```bash
# Unit tests only
uv run pytest tests/unit

# Acceptance tests
uv run pytest tests/acceptance
uv run pytest tests/acceptance/crr
uv run pytest tests/acceptance/basel31
uv run pytest tests/acceptance/comparison

# Contract tests
uv run pytest tests/contracts

# Benchmarks (requires --benchmark-only or --benchmark-enable)
uv run pytest tests/benchmarks --benchmark-only

# Include slow tests (10M+ scale)
uv run pytest -m slow
```

### Specific Tests

```bash
# Run specific file
uv run pytest tests/unit/test_pipeline.py

# Run specific test
uv run pytest tests/unit/test_pipeline.py::test_crr_basic_calculation

# Run by pattern
uv run pytest -k "test_sa_"

# Stop on first failure
uv run pytest -x

# Show local variables in tracebacks
uv run pytest -l

# Run last failed tests
uv run pytest --lf
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

End-to-end tests that run fixture data through the full production pipeline and compare results against pre-calculated expected outputs (golden files). There are three suites:

**CRR scenarios** (97 tests across 9 files):

| File | Tests | Covers |
|------|------:|--------|
| `test_scenario_crr_a_sa.py` | 14 | Standardised Approach risk weights |
| `test_scenario_crr_b_firb.py` | 13 | Foundation IRB |
| `test_scenario_crr_c_airb.py` | 7 | Advanced IRB |
| `test_scenario_crr_d_crm.py` | 9 | Credit Risk Mitigation |
| `test_scenario_crr_e_slotting.py` | 9 | Specialised Lending Slotting |
| `test_scenario_crr_f_supporting_factors.py` | 15 | SME/Infrastructure factors |
| `test_scenario_crr_g_provisions.py` | 17 | Provision resolution |
| `test_scenario_crr_h_complex.py` | 4 | Complex/combined scenarios |
| `test_scenario_crr_i_defaulted.py` | 9 | Defaulted exposures |

**Basel 3.1 scenarios** (116 tests across 9 files):

| File | Tests | Covers |
|------|------:|--------|
| `test_scenario_b31_a_sa.py` | 14 | SA risk weights (PRA PS9/24) |
| `test_scenario_b31_b_firb.py` | 16 | Foundation IRB |
| `test_scenario_b31_c_airb.py` | 13 | Advanced IRB |
| `test_scenario_b31_d_crm.py` | 15 | Credit Risk Mitigation |
| `test_scenario_b31_d7_parameter_substitution.py` | 5 | IRB parameter substitution |
| `test_scenario_b31_e_slotting.py` | 13 | Specialised Lending Slotting |
| `test_scenario_b31_f_output_floor.py` | 6 | Output floor (72.5%) |
| `test_scenario_b31_g_provisions.py` | 24 | Provision resolution |
| `test_scenario_b31_h_complex.py` | 10 | Complex/combined scenarios |

**Comparison tests** (62 tests) validate that CRR and Basel 3.1 results relate to each other correctly (e.g. output floor binds when SA RWA exceeds IRB).

Each acceptance test looks up a specific exposure in the pipeline results and asserts against the expected output:

```python
# tests/acceptance/crr/test_scenario_crr_a_sa.py

class TestCRRGroupA_StandardisedApproach:

    def test_crr_a1_uk_sovereign_zero_rw(
        self,
        sa_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-A1: UK Sovereign with CQS 1 should have 0% risk weight.

        Input: £1,000,000 loan to UK Government (CQS 1)
        Expected: RWA = £0 (0% RW per CRR Art. 114)
        """
        expected = expected_outputs_dict["CRR-A1"]
        result = get_sa_result_for_exposure(sa_results_df, "LOAN_SOV_UK_001")

        assert result is not None, "Exposure LOAN_SOV_UK_001 not found in SA results"
        assert_risk_weight_match(
            result["risk_weight"], expected["risk_weight"], scenario_id="CRR-A1"
        )
        assert_rwa_within_tolerance(
            result["rwa_post_factor"], expected["rwa_after_sf"], scenario_id="CRR-A1"
        )
```

The session-scoped fixtures (`sa_results_df`, `expected_outputs_dict`, `pipeline_results`, etc.) are defined in each suite's `conftest.py`. The pipeline runs once per session and results are shared across all tests.

### Benchmark Tests

Performance tests at various scales. See [Benchmark Tests](benchmarks.md) for full details.

```bash
# Run benchmarks (uses cached datasets)
uv run pytest tests/benchmarks --benchmark-only

# Force regenerate all benchmark datasets
uv run pytest tests/benchmarks --benchmark-only --benchmark-regenerate

# Force regenerate a specific scale
uv run pytest tests/benchmarks --benchmark-only --benchmark-regenerate-scale=100k
```

Scales: 10K (quick, ~1s), 100K (standard, ~5s), 1M (large, ~60s), 10M (production, slow marker).

## Acceptance Test Datasets

Acceptance tests depend on two things: **input fixture data** (parquet files in `tests/fixtures/`) and **expected outputs** (golden files in `tests/expected_outputs/`). Understanding how to generate and maintain these is essential for working with acceptance tests.

### Data flow

```
tests/fixtures/               tests/expected_outputs/
    ├── counterparty/*.py             ├── crr/expected_rwa_crr.json
    ├── exposures/*.py                └── basel31/expected_rwa_b31.json
    ├── collateral/*.py
    ├── ...                                     │
    │                                           │
    ▼  generate_all.py                          │
    │                                           │
tests/fixtures/                                 │
    ├── counterparty/*.parquet                  │
    ├── exposures/*.parquet                     │
    ├── ...                                     │
    │                                           │
    ▼  conftest.py: load_fixtures()             │
    │                                           │
    RawDataBundle (LazyFrames)                  │
    │                                           │
    ▼  conftest.py: PipelineOrchestrator.run()  │
    │                                           │
    AggregatedResultBundle                      │
    │                                           │
    ▼  test assertions ◄────────────────────────┘
```

### Generating fixture data

Each subdirectory in `tests/fixtures/` contains Python modules with `create_*()` and `save_*()` functions that produce parquet files. The master script generates everything in the correct order:

```bash
# Generate all fixture parquet files
uv run python tests/fixtures/generate_all.py
```

This produces parquet files across 8 fixture groups:

| Group | Directory | Files | Description |
|-------|-----------|-------|-------------|
| Counterparties | `counterparty/` | sovereign, institution, corporate, retail, specialised_lending | All counterparty types with various CQS bands |
| Mappings | `mapping/` | org_mapping, lending_mapping | Organisational and lending group hierarchies |
| Ratings | `ratings/` | ratings | External and internal ratings |
| Exposures | `exposures/` | facilities, loans, contingents, facility_mapping | All exposure types with facility-to-loan mappings |
| Collateral | `collateral/` | collateral | Financial and non-financial collateral |
| Guarantees | `guarantee/` | guarantee | Guarantee and credit protection |
| Provisions | `provision/` | provision | Specific and general provisions |
| FX Rates | `fx_rates/` | fx_rates | Currency conversion rates |

The script also runs data integrity checks (referential integrity between counterparties, exposures, collateral, etc.).

**When to regenerate**: after modifying any `create_*()` function in `tests/fixtures/`, or when adding new test scenarios that require new input data.

### Expected outputs (golden files)

Expected outputs live in `tests/expected_outputs/` and define the correct RWA results for each test scenario. Three formats are supported (checked in priority order):

1. **Parquet** (fastest) — `expected_rwa_crr.parquet` / `expected_rwa_b31.parquet`
2. **CSV** (fallback) — `expected_rwa_crr.csv` / `expected_rwa_b31.csv`
3. **JSON** (source of truth) — `expected_rwa_crr.json` / `expected_rwa_b31.json`

Each record has at minimum:

- `scenario_id` — unique test identifier (e.g. `"CRR-A1"`, `"B31-B03"`)
- `scenario_group` — grouping for fixture filtering (e.g. `"CRR-A"`, `"B31-D"`)
- `risk_weight`, `rwa_after_sf`, `ead` — expected calculation outputs

The JSON file is the canonical source of truth. Parquet/CSV are derived for faster loading. When updating expected values, edit the JSON and regenerate the other formats.

### How conftest.py wires it together

Each acceptance suite's `conftest.py` (e.g. `tests/acceptance/crr/conftest.py`) provides session-scoped fixtures:

1. **`load_test_fixtures`** — calls `load_fixtures()` from `workbooks/shared/fixture_loader.py`, which reads all parquet files into a `FixtureData` container of LazyFrames
2. **`raw_data_bundle`** — assembles the `FixtureData` into a `RawDataBundle` (the pipeline's input type)
3. **`pipeline_results`** — runs `PipelineOrchestrator().run_with_data(bundle, config)` once per session
4. **`sa_results_df` / `irb_results_df` / `slotting_results_df`** — collected DataFrames for each approach
5. **`expected_outputs_df` / `expected_outputs_dict`** — loaded golden file data for assertions

Different configs are used for different scenario groups (SA-only, full IRB, slotting permissions, etc.).

### Adding a new acceptance test scenario

1. Add input data in the appropriate `tests/fixtures/` module (e.g. a new counterparty in `corporate.py`, a new loan in `loans.py`)
2. Regenerate fixtures: `uv run python tests/fixtures/generate_all.py`
3. Add expected outputs to the relevant JSON golden file in `tests/expected_outputs/`
4. Write the test in the appropriate `test_scenario_*.py` file, using conftest fixtures
5. Run and verify: `uv run pytest tests/acceptance/crr/test_scenario_crr_a_sa.py -v`

## Test Fixtures

### Unit test fixtures

Unit tests use inline Polars DataFrames or `@pytest.fixture` functions:

```python
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
```

### Parametrized fixtures

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

### Configuration fixtures

```python
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

Use descriptive names that explain what is being tested, under what conditions, and the expected outcome:

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

Markers are configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --benchmark-disable -m 'not slow'"
markers = [
    "benchmark: mark test as a benchmark (deselect with --benchmark-skip)",
    "slow: mark test as slow (10M+ scale, may take several minutes)",
]
```

Usage:
```python
@pytest.mark.slow
def test_large_portfolio_calculation():
    ...
```

Run by marker:
```bash
uv run pytest -m "not slow"    # Default — excludes slow tests
uv run pytest -m slow           # Only slow tests
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

- [Specifications](../specifications/index.md) - Regulatory specifications and scenarios
- [Adding Features](extending.md) - Extending the calculator
- [Code Style](code-style.md) - Coding conventions
- [Architecture](../architecture/index.md) - System design
