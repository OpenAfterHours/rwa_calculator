# /// script
# [tool.marimo.runtime]
# auto_instantiate = true
# ///

"""
Starter Workbook Template.

A starting point for custom RWA analysis. Includes pre-configured imports,
sidebar navigation, and cached results loading.

Usage:
    Created via the Workbench hub at /workbench.
    Opened for editing at http://localhost:8002.
"""

from pathlib import Path as _Path

import marimo

# Resolve shared assets via absolute paths so this works at any nesting depth
# under workspaces/. Walks up to find pyproject.toml as the project-root marker.
_here = _Path(__file__).resolve()
_project_root = next(
    (p for p in _here.parents if (p / "pyproject.toml").exists()),
    _here.parents[-1],
)
_shared_dir = _project_root / "src" / "rwa_calc" / "ui" / "marimo" / "shared"

__generated_with = "0.19.4"
app = marimo.App(
    width="medium",
    css_file=str(_shared_dir / "theme.css"),
    html_head_file=str(_shared_dir / "head.html"),
)


@app.cell(hide_code=True)
def _():
    import sys
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import polars as pl

    # Locate project root by walking up parents to find pyproject.toml.
    # Robust to any workbook nesting depth under workspaces/.
    _here = Path(__file__).resolve()
    project_root = next(
        (p for p in _here.parents if (p / "pyproject.toml").exists()),
        _here.parents[-1],
    )
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    cache_dir = project_root / "src" / "rwa_calc" / "ui" / "marimo" / ".cache"

    _shared = str(project_root / "src" / "rwa_calc" / "ui" / "marimo" / "shared")
    if _shared not in sys.path:
        sys.path.insert(0, _shared)
    from sidebar import create_sidebar as _create_sidebar

    _create_sidebar(mo, base_url="http://localhost:8000")

    return Decimal, Path, cache_dir, date, mo, pl, project_root


@app.cell(hide_code=True)
def _(mo):
    run_btn = mo.ui.run_button(label="Run Analysis")
    mo.hstack([run_btn, mo.md("_Click to execute analysis cells below_")], gap=1)
    return (run_btn,)


@app.cell
def _(mo, run_btn):
    mo.stop(
        not run_btn.value, mo.md("")
    )  # leave this code to prevent full re-run of workbook on re-open

    # Load cached results (run a calculation in the Calculator first)
    # cached = pl.scan_parquet(cache_dir / "last_results.parquet")

    # Or run a fresh calculation
    # from rwa_calc import CreditRiskCalc
    # calc = CreditRiskCalc.from_path("path/to/data")
    # result = calc.run()
    return


if __name__ == "__main__":
    app.run()
