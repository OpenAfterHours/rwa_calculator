"""
RWA Results Explorer Marimo Application.

Interactive UI for exploring and analyzing RWA calculation results.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/results_explorer.py
    uv run marimo run src/rwa_calc/ui/marimo/results_explorer.py

Features:
    - Load cached results from calculator (lazy scan, no full materialization)
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
    import json
    from pathlib import Path

    import marimo as mo
    import polars as pl

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
        results_lf = pl.scan_parquet(results_file)
        metadata = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        has_results = True

        exposure_count = metadata.get("exposure_count", 0)

        mo.output.replace(
            mo.callout(
                mo.md(f"""
**Loaded Results**
- Framework: {metadata.get("framework", "Unknown")}
- Reporting Date: {metadata.get("reporting_date", "Unknown")}
- Total Exposures: {exposure_count:,}
- Total RWA: {metadata.get("total_rwa", 0):,.0f}
                """),
                kind="success",
            )
        )
    else:
        results_lf = pl.LazyFrame()
        metadata = {}
        has_results = False

        mo.output.replace(
            mo.callout(
                mo.md(
                    "No results found. Please run a calculation in the [Calculator](/calculator) first."
                ),
                kind="warn",
            )
        )

    return has_results, metadata, results_lf


@app.cell
def _(has_results, mo, pl, results_lf):
    if has_results and len(results_lf.collect_schema().names()) > 0:
        schema_names = results_lf.collect_schema().names()

        # Get unique values for filters via lazy scan
        exposure_classes = (
            ["All"]
            + sorted(results_lf.select("exposure_class").unique().collect().to_series().to_list())
            if "exposure_class" in schema_names
            else ["All"]
        )

        approaches = (
            ["All"]
            + sorted(results_lf.select("approach_applied").unique().collect().to_series().to_list())
            if "approach_applied" in schema_names
            else ["All"]
        )

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
            mo.vstack(
                [
                    mo.md("### Filters"),
                    mo.hstack(
                        [
                            class_filter,
                            approach_filter,
                            rw_min,
                            rw_max,
                        ],
                        justify="start",
                        gap=2,
                    ),
                ]
            )
        )
    else:
        class_filter = None
        approach_filter = None
        rw_min = None
        rw_max = None

    return approach_filter, class_filter, rw_max, rw_min


@app.cell
def _(approach_filter, class_filter, has_results, mo, pl, results_lf, rw_max, rw_min):
    if has_results and class_filter is not None:
        schema_names = results_lf.collect_schema().names()

        # Build combined filter predicate on LazyFrame
        predicates = []

        if class_filter.value != "All" and "exposure_class" in schema_names:
            predicates.append(pl.col("exposure_class") == class_filter.value)

        if approach_filter.value != "All" and "approach_applied" in schema_names:
            predicates.append(pl.col("approach_applied") == approach_filter.value)

        if "risk_weight" in schema_names:
            predicates.append(
                (pl.col("risk_weight") >= rw_min.value) & (pl.col("risk_weight") <= rw_max.value)
            )

        if predicates:
            combined = predicates[0]
            for p in predicates[1:]:
                combined = combined & p
            filtered_lf = results_lf.filter(combined)
        else:
            filtered_lf = results_lf

        # Compute filtered statistics via a single lazy aggregation
        stats_df = filtered_lf.select(
            [
                pl.col("ead_final").sum().alias("total_ead"),
                pl.col("rwa_final").sum().alias("total_rwa"),
                pl.len().alias("count"),
            ]
        ).collect()

        total_ead = stats_df["total_ead"][0] or 0
        total_rwa = stats_df["total_rwa"][0] or 0
        row_count = int(stats_df["count"][0])
        avg_rw = total_rwa / total_ead if total_ead > 0 else 0

        mo.output.replace(
            mo.hstack(
                [
                    mo.stat(
                        value=f"{row_count:,}",
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
                ],
                justify="space-around",
            )
        )
    else:
        filtered_lf = pl.LazyFrame()
        total_ead = 0
        total_rwa = 0
        row_count = 0

    return avg_rw, filtered_lf, row_count, total_ead, total_rwa


@app.cell
def _(has_results, mo, row_count):
    if has_results and row_count > 0:
        # Aggregation selector
        agg_options = ["None", "By Exposure Class", "By Approach", "By Risk Weight Band"]
        agg_selector = mo.ui.dropdown(
            options=agg_options,
            value="None",
            label="Aggregate By",
        )

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("### Analysis View"),
                    agg_selector,
                ]
            )
        )
    else:
        agg_selector = None

    return (agg_selector,)


@app.cell
def _(agg_selector, filtered_lf, has_results, mo, pl, row_count):
    if has_results and row_count > 0 and agg_selector is not None:
        schema_names = filtered_lf.collect_schema().names()

        if agg_selector.value == "By Exposure Class" and "exposure_class" in schema_names:
            agg_df = (
                filtered_lf.group_by("exposure_class")
                .agg(
                    [
                        pl.col("ead_final").sum().alias("total_ead"),
                        pl.col("rwa_final").sum().alias("total_rwa"),
                        pl.len().alias("count"),
                    ]
                )
                .with_columns((pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight"))
                .sort("total_rwa", descending=True)
                .collect()
            )

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("#### Summary by Exposure Class"),
                        mo.ui.table(agg_df, selection=None),
                    ]
                )
            )

        elif agg_selector.value == "By Approach" and "approach_applied" in schema_names:
            agg_df = (
                filtered_lf.group_by("approach_applied")
                .agg(
                    [
                        pl.col("ead_final").sum().alias("total_ead"),
                        pl.col("rwa_final").sum().alias("total_rwa"),
                        pl.len().alias("count"),
                    ]
                )
                .with_columns((pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight"))
                .sort("total_rwa", descending=True)
                .collect()
            )

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("#### Summary by Approach"),
                        mo.ui.table(agg_df, selection=None),
                    ]
                )
            )

        elif agg_selector.value == "By Risk Weight Band" and "risk_weight" in schema_names:
            agg_df = (
                filtered_lf.with_columns(
                    pl.when(pl.col("risk_weight") <= 0.20)
                    .then(pl.lit("0-20%"))
                    .when(pl.col("risk_weight") <= 0.50)
                    .then(pl.lit("20-50%"))
                    .when(pl.col("risk_weight") <= 0.75)
                    .then(pl.lit("50-75%"))
                    .when(pl.col("risk_weight") <= 1.00)
                    .then(pl.lit("75-100%"))
                    .when(pl.col("risk_weight") <= 1.50)
                    .then(pl.lit("100-150%"))
                    .otherwise(pl.lit("150%+"))
                    .alias("rw_band")
                )
                .group_by("rw_band")
                .agg(
                    [
                        pl.col("ead_final").sum().alias("total_ead"),
                        pl.col("rwa_final").sum().alias("total_rwa"),
                        pl.len().alias("count"),
                    ]
                )
                .with_columns((pl.col("total_rwa") / pl.col("total_ead")).alias("avg_risk_weight"))
                .sort("rw_band")
                .collect()
            )

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("#### Summary by Risk Weight Band"),
                        mo.ui.table(agg_df, selection=None),
                    ]
                )
            )

        else:
            agg_df = None
    else:
        agg_df = None

    return (agg_df,)


@app.cell
def _(filtered_lf, has_results, mo, row_count):
    if has_results and row_count > 0:
        # Column selector for detailed view
        available_cols = filtered_lf.collect_schema().names()

        # Default columns to show
        default_cols = [
            col
            for col in [
                "exposure_reference",
                "counterparty_name",
                "exposure_class",
                "approach_applied",
                "ead_final",
                "risk_weight",
                "rwa_final",
            ]
            if col in available_cols
        ]

        column_selector = mo.ui.multiselect(
            options=available_cols,
            value=default_cols,
            label="Columns to Display",
        )

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("### Detailed Results"),
                    column_selector,
                ]
            )
        )
    else:
        column_selector = None

    return (column_selector,)


@app.cell
def _(column_selector, filtered_lf, has_results, mo, row_count):
    if has_results and row_count > 0 and column_selector is not None and column_selector.value:
        schema_names = filtered_lf.collect_schema().names()
        display_cols = [c for c in column_selector.value if c in schema_names]

        if display_cols:
            display_df = filtered_lf.select(display_cols).head(500).collect()

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md(f"*Showing {display_df.height:,} of {row_count:,} rows*"),
                        mo.ui.table(display_df, selection=None),
                    ]
                )
            )
    return (display_cols,)


@app.cell
def _(filtered_lf, has_results, mo, row_count):
    import io

    if has_results and row_count > 0:

        def _make_csv() -> bytes:
            return filtered_lf.collect().write_csv().encode("utf-8")

        def _make_parquet() -> bytes:
            buf = io.BytesIO()
            filtered_lf.collect().write_parquet(buf)
            return buf.getvalue()

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("### Export Filtered Results"),
                    mo.hstack(
                        [
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
                        ],
                        gap=2,
                    ),
                ]
            )
        )
    return


@app.cell
def _(cache_dir, has_results, mo, pl):
    # Load summary tables if available (small tables, collect eagerly)
    class_summary_file = cache_dir / "last_summary_by_class.parquet"
    approach_summary_file = cache_dir / "last_summary_by_approach.parquet"

    if has_results:
        output_parts = []

        if class_summary_file.exists():
            class_summary_df = pl.scan_parquet(class_summary_file).collect()
            output_parts.append(mo.md("### Original Summary by Exposure Class"))
            output_parts.append(mo.ui.table(class_summary_df, selection=None))

        if approach_summary_file.exists():
            approach_summary_df = pl.scan_parquet(approach_summary_file).collect()
            output_parts.append(mo.md("### Original Summary by Approach"))
            output_parts.append(mo.ui.table(approach_summary_df, selection=None))

        if output_parts:
            mo.output.replace(mo.vstack(output_parts))
    return


if __name__ == "__main__":
    app.run()
