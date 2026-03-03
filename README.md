*This package is still in development and is not production ready*

# UK Credit Risk RWA Calculator

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://OpenAfterHours.github.io/rwa_calculator/)

A high-performance Risk-Weighted Assets (RWA) calculator for UK credit risk, supporting both current regulations and future Basel 3.1 implementation. Built with Python using Polars for vectorized performance.

**Documentation:** [https://OpenAfterHours.github.io/rwa_calculator/](https://OpenAfterHours.github.io/rwa_calculator/)

## Installation

```bash
# Install from PyPI
pip install rwa-calc

# Or with uv
uv add rwa-calc

# With UI support (web-based calculator interface)
pip install rwa-calc[ui]
```

### Optional Dependencies

| Extra | Description |
|-------|-------------|
| `ui` | Interactive web UI via Marimo |
| `dev` | Development tools (pytest, mypy, mkdocs) |
| `all` | All optional dependencies |

## Quick Start

**Quickest Start** — one call does everything:

```python
from rwa_calc.api import quick_calculate

response = quick_calculate("/path/to/data")
print(f"Total RWA: {response.summary.total_rwa:,.0f}")
```

**More Control** — choose framework, IRB approach, and reporting date:

```python
from datetime import date
from rwa_calc.api import create_service, CalculationRequest

service = create_service()
response = service.calculate(
    CalculationRequest(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2026, 12, 31),
        irb_approach="full_irb",
    )
)

if response.success:
    print(f"Total RWA: {response.summary.total_rwa:,.0f}")
    df = response.collect_results()
```

**Interactive UI** — web-based calculator interface:

```bash
pip install rwa-calc[ui]
rwa-calc-ui
# Open http://localhost:8000 in your browser
```

## Regulatory Scope

This calculator supports two regulatory regimes:

| Regime | Effective Period | UK Implementation | Status |
|--------|------------------|-------------------|--------|
| **CRR (Basel 3.0)** | Until 31 December 2026 | UK CRR (EU 575/2013 as onshored) | **Active** |
| **Basel 3.1** | From 1 January 2027 | PRA PS9/24 | **Active Development** |

A configuration toggle allows switching between calculation modes for:
- Current regulatory reporting under UK CRR
- Impact analysis and parallel running ahead of Basel 3.1 go-live
- Seamless transition when Basel 3.1 becomes effective

## Key Features

- **Dual-Framework Support**: Single codebase for CRR and Basel 3.1 with UK-specific deviations
- **High Performance**: Polars LazyFrames for vectorized calculations (50-100x improvement over row iteration)
- **Complete Coverage**: Standardised (SA), IRB (F-IRB & A-IRB), and Slotting approaches
- **Credit Risk Mitigation**: Collateral, guarantees, and provisions with RWA-optimized allocation
- **Complex Hierarchies**: Multi-level counterparty and facility hierarchy support
- **Audit Trail**: Full calculation transparency for regulatory review
- **Framework Comparison**: Side-by-side CRR vs Basel 3.1 impact analysis
- **COREP Output**: Export results to COREP regulatory templates
- **Multiple Export Formats**: Parquet, CSV, Excel, and COREP

### Supported Approaches

| Approach | Description |
|----------|-------------|
| Standardised (SA) | Risk weights based on external ratings and exposure characteristics |
| Foundation IRB (F-IRB) | Bank-estimated PD, supervisory LGD |
| Advanced IRB (A-IRB) | Bank-estimated PD, LGD, and EAD |
| Slotting | Category-based approach for specialised lending |

### Supported Exposure Classes

Sovereign, Institution, Corporate, Corporate SME, Retail Mortgage, Retail QRRE, Retail Other, Specialised Lending, Equity

## Documentation

Comprehensive documentation is available at **[OpenAfterHours.github.io/rwa_calculator](https://OpenAfterHours.github.io/rwa_calculator/)**

| Section | Description |
|---------|-------------|
| [Getting Started](https://OpenAfterHours.github.io/rwa_calculator/getting-started/) | Installation and first calculation |
| [User Guide](https://OpenAfterHours.github.io/rwa_calculator/user-guide/) | Regulatory frameworks, methodology, exposure classes |
| [Architecture](https://OpenAfterHours.github.io/rwa_calculator/architecture/) | System design and pipeline |
| [Data Model](https://OpenAfterHours.github.io/rwa_calculator/data-model/) | Input schemas and validation |
| [API Reference](https://OpenAfterHours.github.io/rwa_calculator/api/) | Complete technical documentation |
| [Development](https://OpenAfterHours.github.io/rwa_calculator/development/) | Testing, benchmarks, contributing |
| [Plans](https://OpenAfterHours.github.io/rwa_calculator/plans/) | Development roadmap and status |

## Running Tests

```bash
# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=src/rwa_calc

# Run benchmarks (10K + 100K, excludes 1M/10M)
uv run pytest tests/benchmarks/ -m "benchmark and not slow" -k "not 1m" -o "addopts=" --benchmark-only -v
```

**Test Results:** ~1,915 tests (1,485 unit + 275 acceptance + 123 contract + ~30 benchmark)

## License

[Apache-2.0 license](LICENSE)

## References

### Current Regulations (CRR / Basel 3.0)
- [PRA Rulebook - CRR Firms](https://www.prarulebook.co.uk/pra-rules/crr-firms)
- [UK CRR - Regulation (EU) No 575/2013 as onshored](https://www.legislation.gov.uk/eur/2013/575/contents)

### Basel 3.1 Implementation (January 2027)
- [PRA PS9/24 - Implementation of the Basel 3.1 standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- [PRA CP16/22 - Implementation of Basel 3.1 Standards](https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards)
- [Basel Committee - CRE: Calculation of RWA for credit risk](https://www.bis.org/basel_framework/chapter/CRE/20.htm)
