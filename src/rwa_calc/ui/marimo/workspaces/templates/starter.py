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

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import polars as pl

    from rwa_calc.ui.marimo.shared.sidebar import create_sidebar as _create_sidebar

    _create_sidebar(mo, base_url="http://localhost:8000")

    return Decimal, Path, date, mo, pl


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

    # Example — run a fresh calculation:
    # from rwa_calc import CreditRiskCalc
    # calc = CreditRiskCalc.from_path("path/to/data")
    # result = calc.run()
    return


if __name__ == "__main__":
    app.run()
