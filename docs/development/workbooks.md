# Workbooks & Interactive UI

This guide covers the Marimo workbooks used for expected output generation and the interactive UI applications.

## Overview

The project includes two types of Marimo-based components:

1. **Expected Output Workbooks** - Reference implementations for generating test expected outputs
2. **Interactive UI Applications** - Web-based tools for running calculations and exploring results

## Interactive UI

The calculator includes a multi-app web server providing three interactive applications.

### Starting the Server

```bash
# If installed from PyPI
rwa-calc-ui

# From source with uv
uv run python src/rwa_calc/ui/marimo/server.py

# Or using uvicorn directly
uvicorn rwa_calc.ui.marimo.server:app --host 0.0.0.0 --port 8000
```

### Available Applications

| Application | URL | Description |
|-------------|-----|-------------|
| **RWA Calculator** | `http://localhost:8000/` or `/calculator` | Run RWA calculations |
| **Results Explorer** | `http://localhost:8000/results` | Analyze calculation results |
| **Framework Reference** | `http://localhost:8000/reference` | Regulatory documentation |

### RWA Calculator (`rwa_app.py`)

The main calculator application provides:

- **Data Input**
    - Data path selection with validation
    - Format selection (Parquet / CSV)
    - Reporting date picker

- **Configuration**
    - Framework selection (CRR / Basel 3.1)
    - IRB approach toggle

- **Results**
    - Summary statistics (total EAD, total RWA, average risk weight)
    - Breakdown by calculation approach
    - Performance metrics (duration, throughput)
    - Results preview (first 100 rows)
    - CSV export

### Results Explorer (`results_explorer.py`)

Analyze and filter calculation results:

- **Filters**
    - By exposure class (dropdown)
    - By approach (dropdown)
    - By risk weight range (min/max)

- **Aggregation Options**
    - By Exposure Class
    - By Approach
    - By Risk Weight Band

- **Features**
    - Column selector for detailed view
    - Export filtered results (CSV + Parquet)
    - Summary statistics

### Framework Reference (`framework_reference.py`)

Interactive regulatory reference with tabbed navigation:

- Overview of CRR vs Basel 3.1
- CRR (Basel 3.0) parameters
- Basel 3.1 parameters
- Risk weight tables
- IRB parameters

### Server Architecture

The multi-app server uses Marimo's ASGI integration:

```python
from marimo import create_asgi_app

app = (
    create_asgi_app()
    .with_app(path="", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/calculator", root=str(apps_dir / "rwa_app.py"))
    .with_app(path="/results", root=str(apps_dir / "results_explorer.py"))
    .with_app(path="/reference", root=str(apps_dir / "framework_reference.py"))
    .build()
)
```

---

## Expected Output Workbooks

The workbooks in `workbooks/` provide reference implementations for generating expected test outputs, ensuring calculator accuracy.

### Structure

```
workbooks/
├── shared/                         # Common utilities
│   ├── fixture_loader.py           # Test data loading
│   ├── irb_formulas.py             # IRB K calculation
│   └── correlation.py              # Asset correlation
├── crr_expected_outputs/           # CRR (Basel 3.0)
│   ├── data/
│   │   └── crr_params.py           # Regulatory parameters
│   ├── calculations/               # Calculation modules
│   │   ├── crr_risk_weights.py     # SA risk weights
│   │   ├── crr_ccf.py              # Credit conversion factors
│   │   ├── crr_haircuts.py         # CRM haircuts
│   │   ├── crr_supporting_factors.py
│   │   └── crr_irb.py              # CRR IRB (with 1.06 factor)
│   ├── scenarios/                  # Expected output scenarios
│   │   ├── group_crr_a_sa.py       # SA scenarios (12)
│   │   ├── group_crr_b_firb.py     # F-IRB scenarios (6)
│   │   ├── group_crr_c_airb.py     # A-IRB scenarios (3)
│   │   ├── group_crr_d_crm.py      # CRM scenarios (6)
│   │   ├── group_crr_e_slotting.py # Slotting scenarios (4)
│   │   ├── group_crr_f_supporting_factors.py (7)
│   │   ├── group_crr_g_provisions.py (3)
│   │   └── group_crr_h_complex.py  # Complex scenarios (4)
│   ├── main.py                     # Main orchestration workbook
│   └── generate_outputs.py         # Output generation
└── basel31_expected_outputs/       # Basel 3.1 (mirrors CRR structure)
    ├── data/
    │   └── regulatory_params.py    # Basel 3.1 parameters
    ├── calculations/
    │   ├── sa_risk_weights.py      # Basel 3.1 SA (LTV-based)
    │   ├── ccf.py
    │   ├── crm_haircuts.py
    │   ├── irb_formulas.py         # IRB with floors
    │   └── correlation.py
    ├── scenarios/                  # 8 groups including output floor
    │   ├── group_a_sa.py
    │   ├── group_b_firb.py
    │   ├── group_c_airb.py
    │   ├── group_d_crm.py
    │   ├── group_e_slotting.py
    │   ├── group_f_output_floor.py # Output floor mechanics
    │   ├── group_g_provisions.py
    │   └── group_h_complex.py
    └── main.py
```

### Running Workbooks

```bash
# Run CRR workbook interactively
uv run marimo edit workbooks/crr_expected_outputs/main.py

# Run Basel 3.1 workbook
uv run marimo edit workbooks/basel31_expected_outputs/main.py

# Generate expected outputs (non-interactive)
uv run python workbooks/crr_expected_outputs/generate_outputs.py
```

### Scenario Groups

#### CRR Scenarios (45 total)

| Group | Description | Scenarios |
|-------|-------------|-----------|
| CRR-A | Standardised Approach | 12 |
| CRR-B | Foundation IRB | 6 |
| CRR-C | Advanced IRB | 3 |
| CRR-D | Credit Risk Mitigation | 6 |
| CRR-E | Specialised Lending (Slotting) | 4 |
| CRR-F | Supporting Factors | 7 |
| CRR-G | Provisions & Impairments | 3 |
| CRR-H | Complex/Combined | 4 |

#### Basel 3.1 Scenarios

Similar structure to CRR with additional:

- **Group F: Output Floor** - Testing the 72.5% floor mechanics and transitional schedule

### Shared Utilities

#### IRB Formulas (`shared/irb_formulas.py`)

Common IRB calculations used by both frameworks:

```python
from workbooks.shared.irb_formulas import calculate_k, maturity_adjustment

# Calculate capital requirement (K)
k = calculate_k(pd=0.01, lgd=0.45, correlation=0.20)

# Calculate maturity adjustment
ma = maturity_adjustment(pd=0.01, maturity=2.5)
```

#### Asset Correlation (`shared/correlation.py`)

Correlation parameters by exposure class:

```python
from workbooks.shared.correlation import get_correlation

# Corporate correlation (PD-dependent)
r = get_correlation("CORPORATE", pd=0.01)

# Retail mortgage (fixed 15%)
r = get_correlation("RETAIL_MORTGAGE", pd=0.01)
```

### Adding New Scenarios

1. **Create scenario file** in the appropriate `scenarios/` directory
2. **Define expected outputs** with all required fields
3. **Add to main.py** orchestration
4. **Generate outputs** using the generation script
5. **Create acceptance test** in `tests/acceptance/`

Example scenario definition:

```python
# workbooks/crr_expected_outputs/scenarios/group_crr_a_sa.py

def get_scenarios():
    return [
        {
            "scenario_id": "CRR-A01",
            "description": "Sovereign CQS1 - 0% RW",
            "exposure_ref": "EXP_SOV_CQS1",
            "expected": {
                "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                "approach": "SA",
                "risk_weight": 0.0,
                "ead": 1_000_000,
                "rwa": 0,
            }
        },
        # ... more scenarios
    ]
```

---

## Development Workflow

### Workbook Development

1. **Edit interactively** using `marimo edit`
2. **Test calculations** against regulatory documentation
3. **Generate outputs** to CSV/JSON/Parquet
4. **Validate** with acceptance tests

### UI Development

1. **Run server** in development mode
2. **Edit app files** - Marimo hot-reloads changes
3. **Test** all applications through the browser
4. **Validate** with API and integration tests

## Next Steps

- [Testing Guide](testing.md) - Testing approach and examples
- [Benchmark Tests](benchmarks.md) - Performance testing
- [Adding Features](extending.md) - Extending the calculator
