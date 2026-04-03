# Getting Started

This section will help you get up and running with the UK Credit Risk RWA Calculator quickly.

## Prerequisites

Before you begin, ensure you have:

- **Python 3.13+** installed
- **uv** package manager (recommended) or pip
- Access to your exposure data in Parquet or CSV format

## What You'll Learn

1. [**Installation**](installation.md) - How to install the calculator and its dependencies
2. [**Quick Start**](quickstart.md) - Run your first RWA calculation in minutes
3. [**Concepts**](concepts.md) - Understand the key concepts and terminology

## Overview

The RWA calculator processes your credit exposure data through a pipeline that:

1. **Loads** raw data from Parquet/CSV files
2. **Resolves** counterparty and facility hierarchies
3. **Classifies** exposures into regulatory exposure classes
4. **Applies** credit risk mitigation (CRM)
5. **Calculates** RWA using SA, IRB, or Slotting approaches
6. **Aggregates** results with supporting factors and output floors

```mermaid
graph TD
    A[Your Data] --> B[RWA Calculator]
    B --> C[RWA Results]

    subgraph Configuration
        D[CRR Config]
        E[Basel 3.1 Config]
    end

    D --> B
    E --> B
```

## Quick Example

```python
from datetime import date
from rwa_calc.api import CreditRiskCalc

response = CreditRiskCalc(
    data_path="/path/to/data",
    framework="CRR",
    reporting_date=date(2026, 12, 31),
).calculate()

print(f"Total RWA: {response.summary.total_rwa:,.0f}")
```

Need more control? See the [Quick Start](quickstart.md) for framework selection, IRB mode, and export options.

## Next Steps

- New to RWA calculations? Start with [Concepts](concepts.md)
- Ready to install? Go to [Installation](installation.md)
- Want to jump right in? Try the [Quick Start](quickstart.md)
