"""
RWA Calculator Marimo Application.

Interactive UI for running RWA calculations using the RWAService API.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/rwa_app.py
    uv run marimo run src/rwa_calc/ui/marimo/rwa_app.py

Features:
    - Data path input and validation
    - Framework selection (CRR / Basel 3.1)
    - Reporting date picker
    - IRB toggle
    - Summary statistics display
    - Results table with export
    - Error display
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    import sys
    from pathlib import Path
    from datetime import date
    from decimal import Decimal

    project_root = Path(__file__).parent.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Cache directory for sharing results between apps
    cache_dir = Path(__file__).parent / ".cache"
    cache_dir.mkdir(exist_ok=True)

    return Decimal, Path, cache_dir, date, mo, pl, project_root


@app.cell
def _(mo):
    mo.sidebar(
        [
            mo.md("# RWA Calculator"),
            mo.nav_menu(
                {
                    "/calculator": f"{mo.icon('calculator')} Calculator",
                    "/results": f"{mo.icon('table')} Results Explorer",
                    "/reference": f"{mo.icon('book')} Framework Reference",
                },
                orientation="vertical",
            ),
            mo.md("---"),
            mo.md("""
**Quick Links**
- [PRA PS9/24](https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2)
- [UK CRR](https://www.legislation.gov.uk/eur/2013/575/contents)
- [BCBS Framework](https://www.bis.org/basel_framework/)
            """),
        ],
        footer=mo.md("*RWA Calculator v1.0*"),
    )
    return


@app.cell
def _(mo):
    return mo.md("""
# RWA Calculator

Configure your calculation parameters below, then click **Run Calculation** to compute Risk-Weighted Assets.
    """)


@app.cell
def _(mo, project_root):
    default_path = str(project_root / "tests" / "fixtures")

    data_path_input = mo.ui.text(
        value=default_path,
        label="Data Path",
        placeholder="Enter path to data directory",
        full_width=True,
    )

    mo.output.replace(
        mo.vstack([
            mo.md("### Data Configuration"),
            data_path_input,
        ])
    )
    return (data_path_input,)


@app.cell
def _(mo):
    framework_dropdown = mo.ui.dropdown(
        options=["CRR", "BASEL_3_1"],
        value="CRR",
        label="Regulatory Framework",
    )

    format_dropdown = mo.ui.dropdown(
        options=["parquet", "csv"],
        value="parquet",
        label="Data Format",
    )

    irb_toggle = mo.ui.switch(
        value=False,
        label="Enable IRB Approaches",
    )

    mo.output.replace(
        mo.hstack([
            framework_dropdown,
            format_dropdown,
            irb_toggle,
        ], justify="start", gap=2)
    )
    return format_dropdown, framework_dropdown, irb_toggle


@app.cell
def _(date, mo):
    reporting_date_input = mo.ui.date(
        value=date.today(),
        label="Reporting Date",
    )

    mo.output.replace(reporting_date_input)
    return (reporting_date_input,)


@app.cell
def _(Path, data_path_input, format_dropdown, mo):
    from rwa_calc.api import validate_data_path

    path = Path(data_path_input.value) if data_path_input.value else None

    if path and path.exists():
        validation_result = validate_data_path(
            data_path=path,
            data_format=format_dropdown.value,
        )
    else:
        validation_result = None

    if path is None or not data_path_input.value:
        validation_status = mo.callout(
            "Please enter a data path",
            kind="warn",
        )
    elif not path.exists():
        validation_status = mo.callout(
            f"Path does not exist: {path}",
            kind="danger",
        )
    elif validation_result and validation_result.valid:
        validation_status = mo.callout(
            f"Data path valid. Found {validation_result.found_count} required files.",
            kind="success",
        )
    elif validation_result:
        missing = ", ".join(validation_result.files_missing[:3])
        more = f" (+{len(validation_result.files_missing) - 3} more)" if len(validation_result.files_missing) > 3 else ""
        validation_status = mo.callout(
            f"Missing files: {missing}{more}",
            kind="danger",
        )
    else:
        validation_status = mo.callout(
            "Unable to validate path",
            kind="warn",
        )

    mo.output.replace(validation_status)
    return (validation_result,)


@app.cell
def _(mo, validation_result):
    can_run = validation_result is not None and validation_result.valid

    run_button = mo.ui.run_button(
        label="Run Calculation",
        disabled=not can_run,
    )

    mo.output.replace(mo.hstack([run_button], justify="center"))
    return (run_button,)


@app.cell
def _(
    cache_dir,
    data_path_input,
    format_dropdown,
    framework_dropdown,
    irb_toggle,
    mo,
    reporting_date_input,
    run_button,
):
    from rwa_calc.api import RWAService, CalculationRequest
    from datetime import date as date_type
    import json

    calculation_response = None
    calculation_error = None

    if run_button.value:
        try:
            service = RWAService()

            rd = reporting_date_input.value
            if not isinstance(rd, date_type):
                rd = date_type.fromisoformat(str(rd))

            request = CalculationRequest(
                data_path=data_path_input.value,
                framework=framework_dropdown.value,
                reporting_date=rd,
                enable_irb=irb_toggle.value,
                data_format=format_dropdown.value,
            )

            calculation_response = service.calculate(request)

            # Cache results for the results explorer
            if calculation_response and calculation_response.success:
                calculation_response.results.write_parquet(cache_dir / "last_results.parquet")

                # Save metadata
                metadata = {
                    "framework": calculation_response.framework,
                    "reporting_date": str(calculation_response.reporting_date),
                    "total_ead": float(calculation_response.summary.total_ead),
                    "total_rwa": float(calculation_response.summary.total_rwa),
                    "exposure_count": calculation_response.summary.exposure_count,
                }
                (cache_dir / "last_results_meta.json").write_text(json.dumps(metadata, indent=2))

                if calculation_response.summary_by_class is not None:
                    calculation_response.summary_by_class.write_parquet(cache_dir / "last_summary_by_class.parquet")
                if calculation_response.summary_by_approach is not None:
                    calculation_response.summary_by_approach.write_parquet(cache_dir / "last_summary_by_approach.parquet")

        except Exception as e:
            calculation_error = str(e)

    if run_button.value and calculation_error:
        mo.output.replace(mo.callout(f"Calculation failed: {calculation_error}", kind="danger"))
    elif run_button.value and calculation_response and not calculation_response.success:
        error_msgs = [e.message for e in calculation_response.errors[:3]]
        mo.output.replace(mo.callout(f"Calculation completed with errors: {'; '.join(error_msgs)}", kind="warn"))
    elif run_button.value and calculation_response and calculation_response.success:
        mo.output.replace(
            mo.callout(
                mo.md(f"Calculation completed successfully! [Open Results Explorer](/results) to analyze."),
                kind="success",
            )
        )
    return (calculation_response,)


@app.cell
def _(Decimal, calculation_response, mo):
    if calculation_response and calculation_response.success:
        summary = calculation_response.summary

        def fmt_num(val: Decimal | int | float) -> str:
            return f"{float(val):,.0f}"

        def fmt_pct(val: Decimal | float) -> str:
            return f"{float(val) * 100:.2f}%"

        mo.output.replace(mo.md(f"""
## Summary Statistics

| Metric | Value |
|--------|-------|
| **Total EAD** | {fmt_num(summary.total_ead)} |
| **Total RWA** | {fmt_num(summary.total_rwa)} |
| **Average Risk Weight** | {fmt_pct(summary.average_risk_weight)} |
| **Exposure Count** | {summary.exposure_count:,} |
| **SA RWA** | {fmt_num(summary.total_rwa_sa)} |
| **IRB RWA** | {fmt_num(summary.total_rwa_irb)} |
| **Slotting RWA** | {fmt_num(summary.total_rwa_slotting)} |
| **Floor Applied** | {"Yes" if summary.floor_applied else "No"} |
| **Floor Impact** | {fmt_num(summary.floor_impact)} |
        """))
    elif calculation_response:
        mo.output.replace(mo.md("## Summary Statistics\n\n*Calculation did not complete successfully.*"))
    return


@app.cell
def _(calculation_response, mo):
    if calculation_response and calculation_response.performance:
        perf = calculation_response.performance
        mo.output.replace(mo.md(f"""
### Performance

- **Duration**: {perf.duration_seconds:.2f} seconds
- **Throughput**: {perf.exposures_per_second:,.0f} exposures/second
        """))
    return


@app.cell
def _(calculation_response, mo):
    if calculation_response and calculation_response.success and calculation_response.results.height > 0:
        results_df = calculation_response.results

        display_cols = [
            col for col in [
                "exposure_reference",
                "exposure_class",
                "approach_applied",
                "ead_final",
                "risk_weight",
                "rwa_final",
            ] if col in results_df.columns
        ]

        if display_cols:
            display_df = results_df.select(display_cols).head(100)
            mo.output.replace(
                mo.vstack([
                    mo.md("## Results Preview (first 100 rows)"),
                    mo.md("*For full analysis, use the [Results Explorer](/results)*"),
                    mo.ui.table(display_df, selection=None),
                ])
            )
    elif calculation_response:
        mo.output.replace(mo.md("## Detailed Results\n\n*No results to display.*"))
    return


@app.cell
def _(calculation_response, mo):
    if calculation_response and calculation_response.errors:
        errors = calculation_response.errors

        warnings = [e for e in errors if e.severity == "warning"]
        error_list = [e for e in errors if e.severity in ("error", "critical")]

        output_parts = []

        if error_list:
            error_items = "\n".join([
                f"- **[{e.code}]** {e.message}"
                for e in error_list[:10]
            ])
            more_errors = f"\n\n*({len(error_list) - 10} more errors)*" if len(error_list) > 10 else ""
            output_parts.append(mo.md(f"""
### Errors ({len(error_list)})

{error_items}{more_errors}
            """))

        if warnings:
            warning_items = "\n".join([
                f"- **[{e.code}]** {e.message}"
                for e in warnings[:10]
            ])
            more_warnings = f"\n\n*({len(warnings) - 10} more warnings)*" if len(warnings) > 10 else ""
            output_parts.append(mo.md(f"""
### Warnings ({len(warnings)})

{warning_items}{more_warnings}
            """))

        if output_parts:
            mo.output.replace(mo.vstack(output_parts))
    return


@app.cell
def _(calculation_response, mo):
    if calculation_response and calculation_response.success and calculation_response.results.height > 0:
        csv_data = calculation_response.results.write_csv()

        mo.output.replace(
            mo.vstack([
                mo.md("### Export Results"),
                mo.download(
                    data=csv_data.encode("utf-8"),
                    filename="rwa_results.csv",
                    label="Download CSV",
                ),
            ])
        )
    return


if __name__ == "__main__":
    app.run()
