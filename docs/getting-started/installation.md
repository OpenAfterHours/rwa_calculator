# Installation

This guide covers how to install the UK Credit Risk RWA Calculator and its dependencies.

## Requirements

- **Python**: 3.13 or higher
- **Operating System**: Windows, macOS, or Linux
- **Package Manager**: uv (recommended) or pip

## Install from PyPI (Recommended)

The simplest way to install the calculator:

=== "pip"

    ```bash
    pip install rwa-calc
    ```

=== "uv"

    ```bash
    uv add rwa-calc
    ```

### Optional Dependencies

Install with UI support for Marimo workbooks:

```bash
pip install rwa-calc[ui]
```

---

## Install from Source

For development or to get the latest unreleased changes, install from the GitHub repository.

### Installation with uv (Recommended)

[uv](https://docs.astral.sh/uv/) is the recommended package manager for this project due to its speed and reliability.

### Install uv

=== "Windows (PowerShell)"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

=== "macOS/Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

### Install the Calculator

```bash
# Clone the repository
git clone https://github.com/OpenAfterHours/rwa_calculator.git
cd rwa_calculator

# Install dependencies with uv
uv sync

# Install with development dependencies
uv sync --all-extras
```

## Installation with pip

If you prefer pip, you can install using:

```bash
# Clone the repository
git clone https://github.com/OpenAfterHours/rwa_calculator.git
cd rwa_calculator

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"
```

## Dependencies

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `polars` | High-performance DataFrame operations |
| `pydantic` | Data validation and settings management |
| `polars-normal-stats` | Statistical functions for IRB formulas (normal CDF/PPF) |
| `pyarrow` | Parquet file support |
| `pyyaml` | Configuration file parsing |
| `duckdb` | SQL analytics engine |

### Development Dependencies

| Package | Purpose |
|---------|---------|
| `pytest` | Testing framework |
| `pytest-cov` | Test coverage reporting |
| `ruff` | Linting and formatting |
| `mypy` | Static type checking |
| `mkdocs` | Documentation generation |
| `mkdocs-material` | Documentation theme |
| `mkdocstrings[python]` | API documentation |
| `marimo` | Interactive notebooks |

## Verifying Installation

After installation, verify everything is working:

```bash
# Run the test suite
uv run pytest

# Or with pip
pytest
```

You should see output similar to:

```
========================= test session starts ==========================
collected 468 items

tests/contracts/test_bundles.py::TestRawDataBundle ...
...
========================= 448 passed, 20 skipped =======================
```

## Project Structure

After installation, your project structure should look like:

```
rwa_calculator/
├── src/
│   └── rwa_calc/           # Main source code
│       ├── config/         # Configuration (FX rates)
│       ├── contracts/      # Interfaces and data contracts
│       ├── data/           # Schemas and regulatory tables
│       ├── domain/         # Core domain enums
│       └── engine/         # Calculation engines
├── tests/                  # Test suite
├── workbooks/              # Reference implementations
├── ref_docs/               # Regulatory documents
├── docs/                   # This documentation
├── pyproject.toml          # Project configuration
└── mkdocs.yml              # Documentation configuration
```

## Environment Variables

The calculator uses sensible defaults, but you can configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `RWA_DATA_PATH` | Default path for input data | `./data` |
| `RWA_OUTPUT_PATH` | Default path for output files | `./output` |

## IDE Setup

### VS Code

Install recommended extensions:

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff"
  ]
}
```

### PyCharm

1. Open the project directory
2. Configure the Python interpreter to use the virtual environment
3. Mark `src` as a Sources Root

## Troubleshooting

### Common Issues

**Python version mismatch**

```bash
# Check your Python version
python --version

# Ensure it's 3.13 or higher
# If not, install Python 3.13+ from python.org
```

**Import errors**

```bash
# Ensure the package is installed in editable mode
uv pip install -e .

# Or verify PYTHONPATH includes src/
export PYTHONPATH="${PYTHONPATH}:./src"
```

**Polars installation issues**

```bash
# Polars requires a compatible CPU architecture
# For older CPUs, try:
pip install polars-lts-cpu
```

## Next Steps

- [Quick Start Guide](quickstart.md) - Run your first calculation
- [Concepts](concepts.md) - Understand the key terminology
