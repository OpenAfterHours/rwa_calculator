# Installation

This guide covers how to install the UK Credit Risk RWA Calculator and its dependencies.

The calculator is installed and run with [uv](https://docs.astral.sh/uv/), and every
command in this documentation assumes it. uv installs the right Python version, creates
the project's virtual environment and keeps the lockfile, so there is no environment to
create or activate by hand: you prefix a command with `uv run` and it runs inside the
project's environment.

## Requirements

- **Python**: 3.13 or higher (uv downloads it for you if it is missing)
- **Operating System**: Windows, macOS, or Linux
- **Package Manager**: [uv](https://docs.astral.sh/uv/)

## Install uv

=== "macOS/Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Check it with `uv --version`. The
[uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) lists
other options, such as Homebrew and WinGet.

---

## Install from PyPI (Recommended)

Add the calculator to a uv project. If you do not have one yet, create it first:

```bash
# Create a project that targets Python 3.13 (skip if you already have a pyproject.toml)
uv init --python 3.13 my-rwa-project
cd my-rwa-project

# Add the calculator
uv add rwa-calc
```

`uv add` records `rwa-calc` in `pyproject.toml`, pins the resolved versions in
`uv.lock`, and installs everything into the project's `.venv`. Run your code and the
calculator's commands through `uv run`, which uses that environment without activating
it:

```bash
uv run python my_calculation.py   # your own script using rwa_calc
uv run rwa-ui                     # the web UI, on http://localhost:8000
```

The base package is all most users need: the web UI, the REST API, the Marimo workbooks
and [`rwa-filer`](../rwa-filer/index.md) are all included.

### Run the UI without a project

To try the web UI without creating a project, run it in a temporary environment:

```bash
uvx --from rwa-calc rwa-ui
```

To keep the UI available as a command on your `PATH`, install it as a uv tool:

```bash
uv tool install rwa-calc
rwa-ui
```

### Optional Dependencies

```bash
# Development tools (pytest, ruff, ty, zensical)
uv add "rwa-calc[dev]"

# Everything (ui and dev dependencies)
uv add "rwa-calc[all]"
```

The quotes stop shells such as zsh from reading the square brackets as a file pattern.

| Extra | Description |
|-------|-------------|
| `ui` | Kept for compatibility. Marimo, FastAPI and Uvicorn now ship in the base package |
| `dev` | Development tools (pytest, ruff, ty, zensical, etc.) |
| `all` | All optional dependencies combined |

---

## Install from Source

For development or to get the latest unreleased changes, install from the GitHub
repository:

```bash
# Clone the repository
git clone https://github.com/OpenAfterHours/rwa_calculator.git
cd rwa_calculator

# Create .venv and install the locked dependencies
uv sync

# Or include the development tools (pytest, ruff, ty, zensical)
uv sync --all-extras

# Download regulatory reference documents
uv run python scripts/download_docs.py
```

The repository is a [uv workspace](../development/workspace.md). `uv sync` installs
`rwa-calc` and `rwa-filer` in editable mode, so a change under `src/` takes effect
without reinstalling. Run every script, test and tool through `uv run` so it uses that
environment.

## Dependencies

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `polars` | High-performance DataFrame operations |
| `polars-normal-stats` | Statistical functions for IRB calculations (normal CDF/PPF) |
| `fastexcel` | Excel file reading (polars read_excel backend) |
| `xlsxwriter` | Excel file writing |
| `fastapi`, `uvicorn`, `jinja2` | Web UI and REST API (`rwa-ui`) |
| `marimo` | Interactive notebooks and the expected-output workbooks |
| `rwa-filer` | Validation of generated returns against the published rules |

### Development Dependencies

| Package | Purpose |
|---------|---------|
| `pytest` | Testing framework (with `pytest-xdist`, `pytest-benchmark`, `pytest-cov`) |
| `hypothesis` | Property-based tests |
| `ruff` | Linting and formatting |
| `ty` | Static type checking |
| `zensical` | Documentation generation |
| `mkdocstrings[python]` | API documentation |

## Verifying Installation

After installing from PyPI, check that the calculator's entry point imports:

```bash
uv run python -c "import rwa_calc; from rwa_calc.api import CreditRiskCalc; print(rwa_calc.__version__)"
```

From a source checkout, build the test fixtures (they are git-ignored, so a fresh clone
has none) and run the test suite:

```bash
uv run python tests/fixtures/generate_all.py
uv run pytest tests/
```

pytest ends with a summary of passed and skipped tests. No test should fail.

## Project Structure

After installation, your project structure should look like:

```
rwa_calculator/
├── src/
│   └── rwa_calc/           # Main source code
│       ├── config/         # Configuration (FX rates)
│       ├── contracts/      # Interfaces and data contracts
│       ├── data/           # Input-domain schemas & validation (column_spec.py, schemas.py)
│       ├── domain/         # Core domain enums
│       ├── rulebook/       # Regulatory rulepack — cited values in packs/{common,crr,b31}.py
│       └── engine/         # Calculation engines (incl. thin pack-binding RW/haircut shims)
├── packages/
│   └── rwa-filer/          # The separately released filing package
├── tests/                  # Test suite
├── workbooks/              # Reference implementations
├── docs/assets/            # Regulatory documents (run scripts/download_docs.py)
├── docs/                   # This documentation
├── pyproject.toml          # Project and uv workspace configuration
├── uv.lock                 # Locked dependency versions
└── zensical.toml           # Documentation configuration
```

## Environment Variables

The calculator uses sensible defaults, but you can configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `RWA_DATA_PATH` | Default path for input data | `./data` |
| `RWA_OUTPUT_PATH` | Default path for output files | `./output` |

## IDE Setup

Point your IDE at the environment `uv sync` created: `.venv/bin/python` on macOS and
Linux, `.venv\Scripts\python.exe` on Windows.

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
2. Set the project interpreter to the `.venv` interpreter that `uv sync` created
3. Mark `src` as a Sources Root

## Troubleshooting

### Common Issues

**Python version mismatch**

```bash
# List the Python versions uv can find or has installed
uv python list

# Install Python 3.13 (uv also does this on demand)
uv python install 3.13

# Pin the project to it
uv python pin 3.13
```

If `uv add rwa-calc` fails because your project's Python requirement is lower than 3.13,
set `requires-python = ">=3.13"` in your `pyproject.toml` and run `uv add rwa-calc`
again.

**Import errors or `command not found`**

`ModuleNotFoundError: No module named 'rwa_calc'` or `rwa-ui: command not found` usually
means the command ran outside the project's environment. Run it through `uv run`:

```bash
uv run python my_calculation.py
uv run rwa-ui
```

In a source checkout, `uv sync` brings an out-of-date environment back in line with
`uv.lock`:

```bash
uv sync --all-extras
```

**Polars installation issues**

```bash
# Polars needs a recent CPU instruction set. For older CPUs,
# add the compatibility runtime:
uv add "polars[rtcompat]"
```

## Next Steps

- [Quick Start Guide](quickstart.md) - Run your first calculation
- [Concepts](concepts.md) - Understand the key terminology
