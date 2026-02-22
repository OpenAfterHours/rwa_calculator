"""
RWA Results Explorer Marimo Application.

Interactive UI for exploring and analyzing RWA calculation results.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/results_explorer.py
    uv run marimo run src/rwa_calc/ui/marimo/results_explorer.py

Features:
    - Load cached results from calculator
    - Filter by exposure class, approach, risk weight range
    - Aggregation by different dimensions
    - Drill-down into individual exposures
    - Charts and visualizations
    - Export filtered results
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    import json
    from pathlib import Path

    cache_dir = Path(__file__).parent / ".cache"

    return Path, cache_dir, json, mo, pl


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
# Results Explorer

Analyze and drill down into your RWA calculation results. Use the filters below to explore the data.
    """)


@app.cell
def _(cache_dir, json, mo, pl):
    results_file = cache_dir / "last_results.parquet"
    meta_file = cache_dir / "last_results_meta.json"

    if results_file.exists():
        results_df = pl.read_parquet(results_file)
        metadata = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        has_results = True

        mo.output.replace(
            mo.callout(
                mo.md(f"""
**Loaded Results**
- Framework: {metadata.get('framework', 'Unknown')}
- Reporting Date: {metadata.get('reporting_date', 'Unknown')}
- Total Exposures: {results_df.height:,}
- Total RWA: {metadata.get('total_rwa', 0):,.0f}
                """),
                kind="success",
            )
        )
    else:
        results_df = pl.DataFrame()
        metadata = {}
        has_results = False

        mo.output.replace(
            mo.callout(
                mo.md("No results found. Please run a calculation in the [Calculator](/calculator) first."),
                kind="warn",
            )
        )

    return has_results, metadata, results_df


@app.cell
def _(has_results, mo, results_df):
    if has_results and results_df.height > 0:
        # Get unique values for filters
        exposure_classes = ["All"] + sorted(
            results_df["exposure_class"].unique().sort().to_list()
        ) if "exposure_class" in results_df.columns else ["All"]

        approaches = ["All"] + sorted(
            results_df["approach_applied"].unique().sort().to_list()
        ) if "approach_applied" in results_df.columns else ["All"]

        # Create filter widgets
        class_filter = mo.ui.dropdown(
            options=exposure_classes,
            value="All",
            label="Exposure Class",
        )

        approach_filter = mo.ui.dropdown(
            options=approaches,
            value="All",
            label="Approach",
        )

        rw_min = mo.ui.number(
            value=0.0,
            start=0.0,
            stop=5.0,
            step=0.01,
            label="Min Risk Weight",
        )

        rw_max = mo.ui.number(
            value=5.0,
            start=0.0,
            stop=5.0,
            step=0.01,
            label="Max Risk Weight",
        )

        mo.output.replace(
            mo.vstack([
                mo.md("### Filters"),
                mo.hstack([
                    class_filter,
                    approach_filter,
                    rw_min,
                    rw_max,
                ], justify="start", gap=2),
            ])
        )
    else:
        class_filter = None
        approach_filter = None
        rw_min = None
        rw_max = None

    return approach_filter, class_filter, rw_max, rw_min


@app.cell
def _(approach_filter, class_filter, has_results, mo, pl, results_df, rw_max, rw_min):
    if has_results and results_df.height > 0 and class_filter is not None:
        # Build combined filter predicate
        predicates = []

        if class_filter.value != "All" and "exposure_class" in results_df.columns:
            predicates.append(pl.col("exposure_class") == class_filter.value)

        if approach_filter.value != "All" and "approach_applied" in results_df.columns:
            predicates.append(pl.col("approach_applied") == approach_filter.value)

        if "risk_weight" in results_df.columns:
            predicates.append(
                (pl.col("risk_weight") >= rw_min.value) &
                (pl.col("risk_weight") <= rw_max.value)
            )

        if predicates:
            combined = predicates[0]
            for p in predicates[1:]:
                combined = combined & p
            filtered_df = results_df.filter(combined)
        else:
            filtered_df = results_df

        # Compute filtered statistics
        if "ead_final" in filtered_df.columns and "rwa_final" in filtered_df.columns:
            total_ead = filtered_df.select(pl.col("ead_final").sum()).item()
            total_rwa = filtered_df.select(pl.col("rwa_final").sum()).item()
            avg_rw = total_rwa / total_ead if total_ead > 0 else 0
        else:
            total_ead = 0
            total_rwa = 0
            avg_rw = 0

        mo.output.replace(
            mo.hstack([
                mo.stat(
                    value=f"{filtered_df.height:,}",
                    label="Exposures",
                ),
                mo.stat(
                    value=f"{total_ead:,.0f}",
                    label="Total EAD",
                ),
                mo.stat(
                    value=f"{total_rwa:,.0f}",
                    label="Total RWA",
                ),
                mo.stat(
                    value=f"{avg_rw:.2%}",
                    label="Avg Risk Weight",
                ),
            ], justify="space-around")
        )
    else:
        filtered_df = pl.DataFrame()
        total_ead = 0
        total_rwa = 0

    return avg_rw, filtered_df, total_ead, total_rwa


@app.cell
def _(filtered_df, has_results, mo):
    if has_results and filtered_df.height > 0:
        # Aggregation selector
        agg_options = ["None", "By Exposure Class", "By Approach", "By Risk Weight Band"]
        agg_selector = mo.ui.dropdown(
            options=agg_options,
            value="None",
            label="Aggregate By",
        )

        mo.output.replace(
            mo.vstack([
                mo.md("### Analysis View"),
                agg_selector,
            ])
        )
    else:
        agg_selector = None

    return (agg_selector,)


@app.cell
def _(agg_selector, filtered_df, has_results, mo, pl):
    if has_results and filtered_df.height > 0 and agg_selector is not None:
        if agg_selector.value == "By Exposure Class" and "exposure_class" in filtered_df.columns:
            agg_df = filtered_df.group_by("exposure_class").agg([
                pl.col("ead_final").sum().alias("total_ead"),
                pl.col("rwa_final").sum().alias("total_rwa"),
                pl.len().alias("count"),
            ]).with_columns(
                (pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight")
            ).sort("total_rwa", descending=True)

            mo.output.replace(
                mo.vstack([
                    mo.md("#### Summary by Exposure Class"),
                    mo.ui.table(agg_df, selection=None),
                ])
            )

        elif agg_selector.value == "By Approach" and "approach_applied" in filtered_df.columns:
            agg_df = filtered_df.group_by("approach_applied").agg([
                pl.col("ead_final").sum().alias("total_ead"),
                pl.col("rwa_final").sum().alias("total_rwa"),
                pl.len().alias("count"),
            ]).with_columns(
                (pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight")
            ).sort("total_rwa", descending=True)

            mo.output.replace(
                mo.vstack([
                    mo.md("#### Summary by Approach"),
                    mo.ui.table(agg_df, selection=None),
                ])
            )

        elif agg_selector.value == "By Risk Weight Band" and "risk_weight" in filtered_df.columns:
            agg_df = filtered_df.with_columns(
                pl.when(pl.col("risk_weight") <= 0.20).then(pl.lit("0-20%"))
                .when(pl.col("risk_weight") <= 0.50).then(pl.lit("20-50%"))
                .when(pl.col("risk_weight") <= 0.75).then(pl.lit("50-75%"))
                .when(pl.col("risk_weight") <= 1.00).then(pl.lit("75-100%"))
                .when(pl.col("risk_weight") <= 1.50).then(pl.lit("100-150%"))
                .otherwise(pl.lit("150%+"))
                .alias("rw_band")
            ).group_by("rw_band").agg([
                pl.col("ead_final").sum().alias("total_ead"),
                pl.col("rwa_final").sum().alias("total_rwa"),
                pl.len().alias("count"),
            ]).with_columns(
                (pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight")
            ).sort("rw_band")

            mo.output.replace(
                mo.vstack([
                    mo.md("#### Summary by Risk Weight Band"),
                    mo.ui.table(agg_df, selection=None),
                ])
            )

        else:
            agg_df = None
    else:
        agg_df = None

    return (agg_df,)


@app.cell
def _(filtered_df, has_results, mo):
    if has_results and filtered_df.height > 0:
        # Column selector for detailed view
        available_cols = filtered_df.columns

        # Default columns to show
        default_cols = [
            col for col in [
                "exposure_reference",
                "counterparty_name",
                "exposure_class",
                "approach_applied",
                "ead_final",
                "risk_weight",
                "rwa_final",
            ] if col in available_cols
        ]

        column_selector = mo.ui.multiselect(
            options=available_cols,
            value=default_cols,
            label="Columns to Display",
        )

        mo.output.replace(
            mo.vstack([
                mo.md("### Detailed Results"),
                column_selector,
            ])
        )
    else:
        column_selector = None

    return (column_selector,)


@app.cell
def _(column_selector, filtered_df, has_results, mo):
    if has_results and filtered_df.height > 0 and column_selector is not None and column_selector.value:
        display_cols = [c for c in column_selector.value if c in filtered_df.columns]

        if display_cols:
            display_df = filtered_df.select(display_cols)

            mo.output.replace(
                mo.vstack([
                    mo.md(f"*Showing {min(display_df.height, 500):,} of {display_df.height:,} rows*"),
                    mo.ui.table(display_df.head(500), selection=None),
                ])
            )
    return (display_cols,)


@app.cell
def _(filtered_df, has_results, mo):
    import io

    if has_results and filtered_df.height > 0:
        # Defer export generation until download is clicked
        def _make_csv() -> bytes:
            return filtered_df.write_csv().encode("utf-8")

        def _make_parquet() -> bytes:
            buf = io.BytesIO()
            filtered_df.write_parquet(buf)
            return buf.getvalue()

        mo.output.replace(
            mo.vstack([
                mo.md("### Export Filtered Results"),
                mo.hstack([
                    mo.download(
                        data=_make_csv,
                        filename="filtered_rwa_results.csv",
                        label="Download CSV",
                    ),
                    mo.download(
                        data=_make_parquet,
                        filename="filtered_rwa_results.parquet",
                        label="Download Parquet",
                    ),
                ], gap=2),
            ])
        )
    return


@app.cell
def _(cache_dir, has_results, mo, pl):
    # Load summary tables if available
    class_summary_file = cache_dir / "last_summary_by_class.parquet"
    approach_summary_file = cache_dir / "last_summary_by_approach.parquet"

    if has_results:
        output_parts = []

        if class_summary_file.exists():
            class_summary_df = pl.read_parquet(class_summary_file)
            output_parts.append(mo.md("### Original Summary by Exposure Class"))
            output_parts.append(mo.ui.table(class_summary_df, selection=None))

        if approach_summary_file.exists():
            approach_summary_df = pl.read_parquet(approach_summary_file)
            output_parts.append(mo.md("### Original Summary by Approach"))
            output_parts.append(mo.ui.table(approach_summary_df, selection=None))

        if output_parts:
            mo.output.replace(mo.vstack(output_parts))
    return


if __name__ == "__main__":
    app.run()
