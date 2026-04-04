# /// script
# [tool.marimo.runtime]
# auto_instantiate = true
# [tool.marimo.display]
# theme = "dark"
# ///

"""
Starter Workbook Template.

A starting point for custom RWA analysis. Includes pre-configured imports,
sidebar navigation, and cached results loading.

Usage:
    Created via the Workbench hub at /workbench.
    Opened for editing at http://localhost:8002.
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(
    width="medium", css_file="../../shared/theme.css", html_head_file="../../shared/head.html"
)


@app.cell(hide_code=True)
def _():
    import sys
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import polars as pl

    project_root = Path(__file__).parent
    # Walk up to find the project root (src/rwa_calc/ui/marimo/workspaces/local)
    for _ in range(6):
        if (project_root / "src").exists():
            break
        project_root = project_root.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Cache directory for loading calculator results
    cache_dir = Path(__file__).parent.parent.parent / ".cache"

    return Decimal, Path, cache_dir, date, mo, pl, project_root


@app.cell(hide_code=True)
def _(mo, project_root):
    import sys as _sys

    _shared = str(project_root / "src" / "rwa_calc" / "ui" / "marimo" / "shared")
    if _shared not in _sys.path:
        _sys.path.insert(0, _shared)
    from sidebar import create_sidebar as _create_sidebar

    _create_sidebar(mo, base_url="http://localhost:8000")
    return


@app.cell(hide_code=True)
def _(mo):
    return mo.md("""
# Custom Analysis Workbook

Use this workbook for ad-hoc RWA analysis. The `CreditRiskCalc` API and cached
results are available below.

## Quick Start

```python
from rwa_calc import CreditRiskCalc

calc = CreditRiskCalc.from_path("path/to/data")
result = calc.run()
result.summary()
```
    """)


@app.cell
def _(cache_dir, mo, pl):
    _results_file = cache_dir / "last_results.parquet"
    if _results_file.exists():
        cached_results = pl.scan_parquet(_results_file)
        mo.output.replace(
            mo.md(
                f"Cached results loaded from `{_results_file}` "
                f"({cached_results.collect().height:,} rows)"
            )
        )
    else:
        cached_results = None
        mo.output.replace(
            mo.callout(
                mo.md(
                    "No cached results found. Run a calculation in the "
                    "[Calculator](/calculator) first, then reload this notebook."
                ),
                kind="warn",
            )
        )
    return (cached_results,)


@app.cell
def _():
    # Start your analysis here
    return


if __name__ == "__main__":
    app.run()
