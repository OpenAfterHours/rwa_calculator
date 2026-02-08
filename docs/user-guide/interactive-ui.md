# Interactive UI

The RWA Calculator includes a web-based interactive interface for running calculations, exploring results, and referencing regulatory parameters—all without writing code.

## Prerequisites

Before using the UI, ensure you have installed the calculator with UI dependencies:

```bash
# Install with UI support
pip install rwa-calc[ui]

# Or with uv
uv add rwa-calc --extra ui
```

This installs Marimo and Uvicorn, which power the web interface.

---

## Starting the UI Server

Launch the multi-application server:

=== "Installed from PyPI"

    ```bash
    # Using the console command (recommended)
    rwa-calc-ui

    # Or using the module directly
    python -m rwa_calc.ui.marimo.server

    # Or using uvicorn
    uvicorn rwa_calc.ui.marimo.server:app --host 0.0.0.0 --port 8000
    ```

=== "From Source"

    ```bash
    # Using uv
    uv run python src/rwa_calc/ui/marimo/server.py

    # Or using uvicorn
    uv run uvicorn rwa_calc.ui.marimo.server:app --host 0.0.0.0 --port 8000
    ```

Once started, open your browser to [http://localhost:8000](http://localhost:8000).

---

## Available Applications

The UI provides three integrated applications:

| Application | URL | Purpose |
|-------------|-----|---------|
| **RWA Calculator** | `/` or `/calculator` | Run RWA calculations on your data |
| **Results Explorer** | `/results` | Filter, aggregate, and export results |
| **Framework Reference** | `/reference` | View regulatory parameters and risk weights |

---

## RWA Calculator

The main calculator application at [http://localhost:8000/](http://localhost:8000/) allows you to run RWA calculations through a visual interface.

### Configuration Options

| Option | Description |
|--------|-------------|
| **Data Path** | Path to your data directory containing Parquet or CSV files |
| **Data Format** | Select Parquet (recommended) or CSV |
| **Reporting Date** | The calculation reference date |
| **Framework** | Choose between CRR (Basel 3.0) or Basel 3.1 |
| **Enable IRB** | Toggle IRB calculations on/off |

### Running a Calculation

1. **Set your data path** - Enter the path to your data directory
2. **Select format** - Choose Parquet or CSV
3. **Choose framework** - CRR for current rules, Basel 3.1 for future rules
4. **Configure options** - Set reporting date and IRB toggle
5. **Run calculation** - Click the calculate button

### Understanding Results

The calculator displays:

- **Summary Statistics**
    - Total EAD (Exposure at Default)
    - Total RWA (Risk-Weighted Assets)
    - Average Risk Weight (RWA / EAD)

- **Breakdown by Approach**
    - Standardised Approach RWA
    - IRB RWA (if enabled)
    - Slotting RWA (for specialised lending)

- **Performance Metrics**
    - Calculation duration
    - Throughput (exposures per second)

- **Results Preview**
    - First 100 rows of detailed results
    - Export to CSV option

---

## Results Explorer

The Results Explorer at [http://localhost:8000/results](http://localhost:8000/results) provides interactive analysis of calculation outputs.

### Filtering Options

| Filter | Description |
|--------|-------------|
| **Exposure Class** | Filter by class (Corporate, Retail, Central Govt / Central Bank, etc.) |
| **Approach** | Filter by calculation approach (SA, F-IRB, A-IRB, Slotting) |
| **Risk Weight Range** | Set minimum and maximum risk weight bounds |

### Aggregation Views

Aggregate results by different dimensions:

- **By Exposure Class** - See totals for each exposure category
- **By Approach** - Compare SA vs IRB vs Slotting
- **By Risk Weight Band** - Distribution across risk weight ranges

### Exporting Data

Export your filtered and aggregated results:

- **CSV** - For spreadsheet analysis
- **Parquet** - For further processing with Polars/Pandas

---

## Framework Reference

The Framework Reference at [http://localhost:8000/reference](http://localhost:8000/reference) provides an interactive regulatory reference.

### Available Sections

| Tab | Content |
|-----|---------|
| **Overview** | Summary of CRR vs Basel 3.1 differences |
| **CRR Parameters** | Current framework regulatory values |
| **Basel 3.1 Parameters** | Future framework regulatory values |
| **Risk Weight Tables** | SA risk weights by exposure class and rating |
| **IRB Parameters** | PD floors, LGD values, correlation factors |

This reference is useful for:

- Validating calculation inputs
- Understanding regulatory differences
- Quick lookup of risk weights and parameters

---

## Data Requirements

The UI expects data in the same format as the Python API. Place your files in a directory structure:

```
your_data_directory/
├── counterparty/
│   └── counterparties.parquet
├── exposures/
│   ├── facilities.parquet
│   └── loans.parquet
├── collateral/           # Optional
│   └── collateral.parquet
├── guarantee/            # Optional
│   └── guarantee.parquet
└── ratings/              # Optional
    └── ratings.parquet
```

See [Input Schemas](../data-model/input-schemas.md) for detailed field requirements.

---

## Troubleshooting

### Server won't start

**Error: `ModuleNotFoundError: No module named 'marimo'`**

Install with UI dependencies:
```bash
pip install rwa-calc[ui]
```

**Error: Port 8000 already in use**

Use a different port:
```bash
uv run uvicorn rwa_calc.ui.marimo.server:app --port 8080
```

### Data path not found

- Ensure the path is absolute or relative to your current working directory
- Check that the required files (counterparties, facilities, loans) exist
- Verify file format matches your selection (Parquet vs CSV)

### Calculation errors

- Check the error panel for specific validation failures
- Ensure required fields are present in your data
- See [Data Validation](../data-model/data-validation.md) for field requirements

---

## Next Steps

- [Configuration Guide](configuration.md) - Advanced configuration options
- [Calculation Methodology](methodology/index.md) - Understanding how RWA is calculated
- [Data Model](../data-model/index.md) - Detailed schema documentation
