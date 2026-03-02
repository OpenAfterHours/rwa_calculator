"""
CRR vs Basel 3.1 Comparison Marimo Application.

Interactive UI for dual-framework impact analysis, capital impact waterfall,
and transitional floor schedule modelling.

Pipeline position:
    Uses DualFrameworkRunner, CapitalImpactAnalyzer, TransitionalScheduleRunner
    from engine/comparison.py to produce ComparisonBundle, CapitalImpactBundle,
    TransitionalScheduleBundle.

Why: During the Basel 3.1 transition (PRA PS9/24, effective 1 Jan 2027),
firms must quantify the capital impact of moving from CRR to Basel 3.1
and model the transitional output floor phase-in from 50% (2027) to 72.5%
(2032+). This workbook provides interactive analysis of those impacts,
enabling capital planning and regulatory dialogue.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/comparison_app.py
    uv run marimo run src/rwa_calc/ui/marimo/comparison_app.py

Features:
    - Dual-framework comparison (CRR vs Basel 3.1) on the same portfolio
    - Executive summary with headline delta metrics
    - Capital impact waterfall decomposition (4 regulatory drivers)
    - Summary breakdowns by exposure class and approach
    - Transitional floor schedule timeline (2027-2032) with interactive slider
    - Drill-down from portfolio delta to exposure-level drivers
    - Export comparison results to CSV

References:
    - PRA PS9/24 Ch.12: Output floor transitional period
    - CRR Art. 92: Own funds requirements
    - CRR Art. 501/501a: SME/infrastructure supporting factors
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full")


@app.cell
def _():
    import io
    import sys
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import polars as pl

    project_root = Path(__file__).parent.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    return Decimal, Path, date, io, mo, pl, project_root


@app.cell
def _(mo):
    mo.sidebar(
        [
            mo.md("# RWA Calculator"),
            mo.nav_menu(
                {
                    "/calculator": f"{mo.icon('calculator')} Calculator",
                    "/results": f"{mo.icon('table')} Results Explorer",
                    "/comparison": f"{mo.icon('git-compare')} Impact Analysis",
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
        footer=mo.md("*RWA Calculator v1.2*"),
    )
    return


@app.cell
def _(mo):
    return mo.md("""
# CRR vs Basel 3.1 Impact Analysis

Run a dual-framework comparison on the same portfolio to quantify the capital impact
of moving from CRR to Basel 3.1. The analysis decomposes the RWA delta into four
regulatory drivers and models the transitional output floor phase-in (2027-2032).
    """)


# =============================================================================
# Data Configuration
# =============================================================================


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
        mo.vstack(
            [
                mo.md("### Data Configuration"),
                data_path_input,
            ]
        )
    )
    return (data_path_input,)


@app.cell
def _(date, mo):
    irb_approach_dropdown = mo.ui.dropdown(
        options={
            "SA Only (No IRB)": "sa_only",
            "Foundation IRB (F-IRB)": "firb",
            "Advanced IRB (A-IRB)": "airb",
            "Full IRB (A-IRB preferred)": "full_irb",
            "Retail A-IRB / Corporate F-IRB": "retail_airb_corporate_firb",
        },
        value="Foundation IRB (F-IRB)",
        label="IRB Approach",
    )

    format_dropdown = mo.ui.dropdown(
        options=["parquet", "csv"],
        value="parquet",
        label="Data Format",
    )

    reporting_date_input = mo.ui.date(
        value=date(2027, 6, 30),
        label="Reporting Date",
    )

    mo.output.replace(
        mo.hstack(
            [irb_approach_dropdown, format_dropdown, reporting_date_input],
            justify="start",
            gap=2,
        )
    )
    return (format_dropdown, irb_approach_dropdown, reporting_date_input)


# =============================================================================
# Data Validation & Run
# =============================================================================


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
        validation_status = mo.callout("Please enter a data path", kind="warn")
    elif not path.exists():
        validation_status = mo.callout(f"Path does not exist: {path}", kind="danger")
    elif validation_result and validation_result.valid:
        validation_status = mo.callout(
            f"Data path valid. Found {validation_result.found_count} required files.",
            kind="success",
        )
    elif validation_result:
        missing = ", ".join(validation_result.files_missing[:3])
        more = (
            f" (+{len(validation_result.files_missing) - 3} more)"
            if len(validation_result.files_missing) > 3
            else ""
        )
        validation_status = mo.callout(f"Missing files: {missing}{more}", kind="danger")
    else:
        validation_status = mo.callout("Unable to validate path", kind="warn")

    mo.output.replace(validation_status)
    return (validation_result,)


@app.cell
def _(mo, validation_result):
    can_run = validation_result is not None and validation_result.valid

    run_button = mo.ui.run_button(
        label="Run Comparison",
        disabled=not can_run,
    )

    mo.output.replace(
        mo.vstack(
            [
                mo.callout(
                    mo.md(
                        "This runs the portfolio through **both** CRR and Basel 3.1 pipelines, "
                        "then computes capital impact attribution and transitional floor schedule. "
                        "Takes roughly 2x a single-framework run."
                    ),
                    kind="info",
                ),
                mo.hstack([run_button], justify="center"),
            ]
        )
    )
    return (run_button,)


# =============================================================================
# Run Comparison
# =============================================================================


@app.cell
def _(
    Decimal,
    Path,
    data_path_input,
    format_dropdown,
    irb_approach_dropdown,
    mo,
    reporting_date_input,
    run_button,
):
    from datetime import date as date_type

    comparison_bundle = None
    impact_bundle = None
    schedule_bundle = None
    run_error = None

    if run_button.value:
        try:
            from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
            from rwa_calc.engine.comparison import (
                CapitalImpactAnalyzer,
                DualFrameworkRunner,
                TransitionalScheduleRunner,
            )
            from rwa_calc.engine.loader import CSVLoader, ParquetLoader

            # Create loader and load data once
            data_path = Path(data_path_input.value)
            if format_dropdown.value == "csv":
                loader = CSVLoader(base_path=data_path)
            else:
                loader = ParquetLoader(base_path=data_path)

            raw_data = loader.load()

            # Resolve IRB permissions
            irb_approach = irb_approach_dropdown.value
            if irb_approach == "sa_only":
                irb_perms = IRBPermissions.sa_only()
            elif irb_approach == "firb":
                irb_perms = IRBPermissions.firb_only()
            elif irb_approach == "airb":
                irb_perms = IRBPermissions.airb_only()
            elif irb_approach == "retail_airb_corporate_firb":
                irb_perms = IRBPermissions.retail_airb_corporate_firb()
            elif irb_approach == "full_irb":
                irb_perms = IRBPermissions.full_irb()
            else:
                irb_perms = IRBPermissions.sa_only()

            rd = reporting_date_input.value
            if not isinstance(rd, date_type):
                rd = date_type.fromisoformat(str(rd))

            # Create configs for both frameworks
            crr_config = CalculationConfig.crr(
                reporting_date=rd,
                irb_permissions=irb_perms,
                eur_gbp_rate=Decimal("0.8732"),
            )
            b31_config = CalculationConfig.basel_3_1(
                reporting_date=rd,
                irb_permissions=irb_perms,
            )

            # M3.1: Run dual-framework comparison
            runner = DualFrameworkRunner()
            comparison_bundle = runner.compare(raw_data, crr_config, b31_config)

            # M3.2: Capital impact analysis
            analyzer = CapitalImpactAnalyzer()
            impact_bundle = analyzer.analyze(comparison_bundle)

            # M3.3: Transitional floor schedule (only if IRB is enabled)
            if irb_approach != "sa_only":
                schedule_runner = TransitionalScheduleRunner()
                schedule_bundle = schedule_runner.run(raw_data, irb_perms)

        except Exception as e:
            run_error = str(e)

    if run_button.value and run_error:
        mo.output.replace(mo.callout(f"Comparison failed: {run_error}", kind="danger"))
    elif run_button.value and comparison_bundle:
        mo.output.replace(mo.callout("Comparison completed successfully!", kind="success"))

    return comparison_bundle, impact_bundle, run_error, schedule_bundle


# =============================================================================
# Executive Summary
# =============================================================================


@app.cell
def _(comparison_bundle, mo, pl):
    if comparison_bundle is not None:
        # Compute headline metrics from comparison bundle
        crr_agg = comparison_bundle.crr_results
        b31_agg = comparison_bundle.b31_results

        # Get total RWA from summary_by_approach for each framework
        def _sum_rwa(result) -> float:
            if result.summary_by_approach is not None:
                df = result.summary_by_approach.collect()
                if "total_rwa" in df.columns and df.height > 0:
                    return float(df["total_rwa"].sum())
            return 0.0

        def _sum_ead(result) -> float:
            if result.summary_by_approach is not None:
                df = result.summary_by_approach.collect()
                if "total_ead" in df.columns and df.height > 0:
                    return float(df["total_ead"].sum())
            return 0.0

        crr_rwa = _sum_rwa(crr_agg)
        b31_rwa = _sum_rwa(b31_agg)
        crr_ead = _sum_ead(crr_agg)
        b31_ead = _sum_ead(b31_agg)
        delta_rwa = b31_rwa - crr_rwa
        delta_pct = (delta_rwa / crr_rwa * 100) if crr_rwa != 0 else 0.0

        def _fmt(val: float) -> str:
            return f"{val:,.0f}"

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("## Executive Summary"),
                    mo.hstack(
                        [
                            mo.stat(value=_fmt(crr_rwa), label="CRR Total RWA"),
                            mo.stat(value=_fmt(b31_rwa), label="Basel 3.1 Total RWA"),
                            mo.stat(
                                value=f"{_fmt(delta_rwa)} ({delta_pct:+.1f}%)",
                                label="Delta RWA",
                            ),
                        ],
                        justify="space-around",
                    ),
                    mo.hstack(
                        [
                            mo.stat(value=_fmt(crr_ead), label="CRR Total EAD"),
                            mo.stat(value=_fmt(b31_ead), label="Basel 3.1 Total EAD"),
                            mo.stat(
                                value=f"{crr_rwa / crr_ead:.2%}" if crr_ead else "N/A",
                                label="CRR Avg RW",
                            ),
                            mo.stat(
                                value=f"{b31_rwa / b31_ead:.2%}" if b31_ead else "N/A",
                                label="B31 Avg RW",
                            ),
                        ],
                        justify="space-around",
                    ),
                ]
            )
        )
    return


# =============================================================================
# Capital Impact Waterfall (M3.2)
# =============================================================================


@app.cell
def _(impact_bundle, mo, pl):
    if impact_bundle is not None:
        waterfall_df = impact_bundle.portfolio_waterfall.collect()

        if waterfall_df.height > 0:
            # Build a formatted waterfall display
            rows = []
            for i in range(waterfall_df.height):
                driver = waterfall_df["driver"][i]
                impact = float(waterfall_df["impact_rwa"][i])
                cumulative = float(waterfall_df["cumulative_rwa"][i])
                direction = "increase" if impact > 0 else "decrease" if impact < 0 else "neutral"
                sign = "+" if impact >= 0 else ""
                rows.append(
                    {
                        "Step": int(waterfall_df["step"][i]),
                        "Driver": driver,
                        "Impact (RWA)": f"{sign}{impact:,.0f}",
                        "Cumulative": f"{cumulative:,.0f}",
                        "Direction": direction,
                    }
                )

            waterfall_display = pl.DataFrame(rows)

            # Calculate the total delta for the summary bar
            total_impact = sum(
                float(waterfall_df["impact_rwa"][i]) for i in range(waterfall_df.height)
            )

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("## Capital Impact Waterfall"),
                        mo.md(
                            "The RWA delta is decomposed into four sequential regulatory drivers. "
                            "Each driver's impact is additive — they sum exactly to the total delta."
                        ),
                        mo.ui.table(waterfall_display, selection=None),
                        mo.md(f"**Total RWA impact: {total_impact:+,.0f}**"),
                    ]
                )
            )
    return


# =============================================================================
# Summary by Exposure Class
# =============================================================================


@app.cell
def _(comparison_bundle, mo, pl):
    if comparison_bundle is not None:
        class_df = comparison_bundle.summary_by_class.collect()

        if class_df.height > 0:
            # Select and format relevant columns
            schema = class_df.columns
            display_cols = [
                c
                for c in [
                    "exposure_class",
                    "count_crr",
                    "count_b31",
                    "total_ead_crr",
                    "total_ead_b31",
                    "total_rwa_crr",
                    "total_rwa_b31",
                    "delta_rwa",
                    "delta_rwa_pct",
                ]
                if c in schema
            ]

            if display_cols:
                sorted_df = class_df.select(display_cols).sort("delta_rwa", descending=True)
                mo.output.replace(
                    mo.vstack(
                        [
                            mo.md("## Comparison by Exposure Class"),
                            mo.md(
                                "Positive delta = Basel 3.1 RWA higher than CRR (increased capital)."
                            ),
                            mo.ui.table(sorted_df, selection=None),
                        ]
                    )
                )
    return


# =============================================================================
# Summary by Approach
# =============================================================================


@app.cell
def _(comparison_bundle, mo, pl):
    if comparison_bundle is not None:
        approach_df = comparison_bundle.summary_by_approach.collect()

        if approach_df.height > 0:
            schema = approach_df.columns
            display_cols = [
                c
                for c in [
                    "approach_applied",
                    "count_crr",
                    "count_b31",
                    "total_ead_crr",
                    "total_ead_b31",
                    "total_rwa_crr",
                    "total_rwa_b31",
                    "delta_rwa",
                    "delta_rwa_pct",
                ]
                if c in schema
            ]

            if display_cols:
                sorted_df = approach_df.select(display_cols).sort("delta_rwa", descending=True)
                mo.output.replace(
                    mo.vstack(
                        [
                            mo.md("## Comparison by Approach"),
                            mo.ui.table(sorted_df, selection=None),
                        ]
                    )
                )
    return


# =============================================================================
# Capital Impact by Exposure Class (M3.2 attribution)
# =============================================================================


@app.cell
def _(impact_bundle, mo, pl):
    if impact_bundle is not None:
        class_attr_df = impact_bundle.summary_by_class.collect()

        if class_attr_df.height > 0:
            schema = class_attr_df.columns
            display_cols = [
                c
                for c in [
                    "exposure_class",
                    "delta_rwa",
                    "scaling_factor_impact",
                    "supporting_factor_impact",
                    "output_floor_impact",
                    "methodology_impact",
                ]
                if c in schema
            ]

            if display_cols:
                sorted_df = class_attr_df.select(display_cols).sort("delta_rwa", descending=True)
                mo.output.replace(
                    mo.vstack(
                        [
                            mo.md("## Capital Impact Attribution by Exposure Class"),
                            mo.md(
                                "Breakdown of each driver's contribution to the RWA delta "
                                "per exposure class. All four drivers sum to delta_rwa."
                            ),
                            mo.ui.table(sorted_df, selection=None),
                        ]
                    )
                )
    return


# =============================================================================
# Transitional Floor Schedule (M3.3)
# =============================================================================


@app.cell
def _(mo, pl, schedule_bundle):
    if schedule_bundle is not None:
        timeline_df = schedule_bundle.timeline.collect()

        if timeline_df.height > 0:
            # Format timeline for display
            display_timeline = timeline_df.select(
                [
                    c
                    for c in [
                        "year",
                        "floor_percentage",
                        "total_rwa_pre_floor",
                        "total_rwa_post_floor",
                        "total_floor_impact",
                        "floor_binding_count",
                        "total_irb_exposure_count",
                        "total_ead",
                        "total_sa_rwa",
                    ]
                    if c in timeline_df.columns
                ]
            )

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("## Transitional Output Floor Schedule (2027-2032)"),
                        mo.md(
                            "PRA PS9/24 phases in the output floor from 50% (2027) to 72.5% "
                            "(2032+). The table shows total RWA pre- and post-floor for each "
                            "transitional year, including floor impact and how many IRB "
                            "exposures become floor-constrained."
                        ),
                        mo.ui.table(display_timeline, selection=None),
                    ]
                )
            )
    return


# =============================================================================
# Transitional Year Drill-Down (slider)
# =============================================================================


@app.cell
def _(mo, schedule_bundle):
    if schedule_bundle is not None and schedule_bundle.yearly_results:
        years = sorted(schedule_bundle.yearly_results.keys())

        year_slider = mo.ui.slider(
            start=min(years),
            stop=max(years),
            step=1,
            value=min(years),
            label="Select Transitional Year",
            show_value=True,
        )

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("### Drill Down by Transitional Year"),
                    mo.md("Use the slider to explore floor impact detail for a specific year."),
                    year_slider,
                ]
            )
        )
    else:
        year_slider = None

    return (year_slider,)


@app.cell
def _(mo, pl, schedule_bundle, year_slider):
    if schedule_bundle is not None and year_slider is not None:
        selected_year = int(year_slider.value)
        year_result = schedule_bundle.yearly_results.get(selected_year)

        if year_result is not None and year_result.summary_by_approach is not None:
            approach_df = year_result.summary_by_approach.collect()

            output_parts = [
                mo.md(f"#### {selected_year} Summary by Approach"),
                mo.ui.table(approach_df, selection=None),
            ]

            if year_result.summary_by_class is not None:
                class_df = year_result.summary_by_class.collect()
                output_parts.append(mo.md(f"#### {selected_year} Summary by Exposure Class"))
                output_parts.append(mo.ui.table(class_df, selection=None))

            mo.output.replace(mo.vstack(output_parts))
    return


# =============================================================================
# Exposure-Level Drill-Down
# =============================================================================


@app.cell
def _(comparison_bundle, mo, pl):
    if comparison_bundle is not None:
        deltas_lf = comparison_bundle.exposure_deltas
        schema = deltas_lf.collect_schema().names()

        # Get unique classes for filter
        exposure_classes = ["All"]
        if "exposure_class" in schema:
            classes = deltas_lf.select("exposure_class").unique().collect().to_series().to_list()
            exposure_classes += sorted(c for c in classes if c is not None)

        approaches = ["All"]
        if "approach_applied" in schema:
            apps = deltas_lf.select("approach_applied").unique().collect().to_series().to_list()
            approaches += sorted(a for a in apps if a is not None)

        drill_class_filter = mo.ui.dropdown(
            options=exposure_classes,
            value="All",
            label="Filter Exposure Class",
        )

        drill_approach_filter = mo.ui.dropdown(
            options=approaches,
            value="All",
            label="Filter Approach",
        )

        drill_sort = mo.ui.dropdown(
            options={
                "Largest RWA increase": "delta_rwa_desc",
                "Largest RWA decrease": "delta_rwa_asc",
                "Largest absolute delta": "delta_rwa_abs",
            },
            value="Largest RWA increase",
            label="Sort By",
        )

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("## Exposure-Level Drill-Down"),
                    mo.md(
                        "Explore per-exposure deltas. Positive delta = Basel 3.1 requires "
                        "more capital than CRR for that exposure."
                    ),
                    mo.hstack(
                        [drill_class_filter, drill_approach_filter, drill_sort],
                        justify="start",
                        gap=2,
                    ),
                ]
            )
        )
    else:
        drill_class_filter = None
        drill_approach_filter = None
        drill_sort = None

    return drill_approach_filter, drill_class_filter, drill_sort


@app.cell
def _(comparison_bundle, drill_approach_filter, drill_class_filter, drill_sort, mo, pl):
    if comparison_bundle is not None and drill_class_filter is not None:
        deltas_lf = comparison_bundle.exposure_deltas
        schema = deltas_lf.collect_schema().names()

        # Apply filters
        predicates = []
        if drill_class_filter.value != "All" and "exposure_class" in schema:
            predicates.append(pl.col("exposure_class") == drill_class_filter.value)
        if drill_approach_filter.value != "All" and "approach_applied" in schema:
            predicates.append(pl.col("approach_applied") == drill_approach_filter.value)

        filtered = deltas_lf
        if predicates:
            combined = predicates[0]
            for p in predicates[1:]:
                combined = combined & p
            filtered = deltas_lf.filter(combined)

        # Select display columns
        display_cols = [
            c
            for c in [
                "exposure_reference",
                "exposure_class",
                "approach_applied",
                "ead_final_crr",
                "ead_final_b31",
                "risk_weight_crr",
                "risk_weight_b31",
                "rwa_final_crr",
                "rwa_final_b31",
                "delta_rwa",
                "delta_risk_weight",
                "delta_rwa_pct",
            ]
            if c in schema
        ]

        if not display_cols:
            display_cols = [c for c in schema if c != "exposure_reference"][:10]
            if "exposure_reference" in schema:
                display_cols = ["exposure_reference"] + display_cols

        # Apply sort
        sort_val = drill_sort.value if drill_sort else "delta_rwa_desc"
        if sort_val == "delta_rwa_desc" and "delta_rwa" in schema:
            filtered = filtered.sort("delta_rwa", descending=True)
        elif sort_val == "delta_rwa_asc" and "delta_rwa" in schema:
            filtered = filtered.sort("delta_rwa", descending=False)
        elif sort_val == "delta_rwa_abs" and "delta_rwa" in schema:
            filtered = filtered.sort(pl.col("delta_rwa").abs(), descending=True)

        result_df = filtered.select(display_cols).head(200).collect()

        # Summary stats for filtered set
        stats = filtered.select(
            [
                pl.len().alias("count"),
                pl.col("delta_rwa").sum().alias("total_delta"),
                pl.col("delta_rwa").mean().alias("avg_delta"),
            ]
        ).collect()

        count = int(stats["count"][0])
        total_delta = float(stats["total_delta"][0]) if stats["total_delta"][0] is not None else 0.0
        avg_delta = float(stats["avg_delta"][0]) if stats["avg_delta"][0] is not None else 0.0

        mo.output.replace(
            mo.vstack(
                [
                    mo.hstack(
                        [
                            mo.stat(value=f"{count:,}", label="Exposures"),
                            mo.stat(value=f"{total_delta:+,.0f}", label="Total Delta RWA"),
                            mo.stat(value=f"{avg_delta:+,.0f}", label="Avg Delta RWA"),
                        ],
                        justify="space-around",
                    ),
                    mo.md(f"*Showing first {result_df.height:,} of {count:,} exposures*"),
                    mo.ui.table(result_df, selection=None),
                ]
            )
        )
    return


# =============================================================================
# Exposure-Level Attribution (M3.2 drill-down)
# =============================================================================


@app.cell
def _(impact_bundle, mo, pl):
    if impact_bundle is not None:
        attr_lf = impact_bundle.exposure_attribution
        schema = attr_lf.collect_schema().names()

        display_cols = [
            c
            for c in [
                "exposure_reference",
                "exposure_class",
                "approach_applied",
                "rwa_crr",
                "rwa_b31",
                "delta_rwa",
                "scaling_factor_impact",
                "supporting_factor_impact",
                "output_floor_impact",
                "methodology_impact",
            ]
            if c in schema
        ]

        if display_cols:
            # Show top 100 by absolute delta
            if "delta_rwa" in schema:
                sorted_lf = attr_lf.sort(pl.col("delta_rwa").abs(), descending=True)
            else:
                sorted_lf = attr_lf

            attr_df = sorted_lf.select(display_cols).head(100).collect()

            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("## Exposure-Level Driver Attribution"),
                        mo.md(
                            "Per-exposure breakdown of the four capital impact drivers. "
                            "Sorted by absolute delta — largest impacts first. "
                            "Scaling/supporting factor drivers only apply to IRB exposures."
                        ),
                        mo.ui.table(attr_df, selection=None),
                    ]
                )
            )
    return


# =============================================================================
# Export
# =============================================================================


@app.cell
def _(comparison_bundle, impact_bundle, io, mo, pl, schedule_bundle):
    if comparison_bundle is not None:

        def _make_deltas_csv() -> bytes:
            return comparison_bundle.exposure_deltas.collect().write_csv().encode("utf-8")

        def _make_waterfall_csv() -> bytes:
            if impact_bundle is not None:
                return impact_bundle.portfolio_waterfall.collect().write_csv().encode("utf-8")
            return b""

        def _make_attribution_csv() -> bytes:
            if impact_bundle is not None:
                return impact_bundle.exposure_attribution.collect().write_csv().encode("utf-8")
            return b""

        def _make_timeline_csv() -> bytes:
            if schedule_bundle is not None:
                return schedule_bundle.timeline.collect().write_csv().encode("utf-8")
            return b""

        downloads = [
            mo.download(
                data=_make_deltas_csv,
                filename="comparison_exposure_deltas.csv",
                label="Exposure Deltas CSV",
            ),
        ]

        if impact_bundle is not None:
            downloads.append(
                mo.download(
                    data=_make_waterfall_csv,
                    filename="capital_impact_waterfall.csv",
                    label="Waterfall CSV",
                )
            )
            downloads.append(
                mo.download(
                    data=_make_attribution_csv,
                    filename="exposure_attribution.csv",
                    label="Attribution CSV",
                )
            )

        if schedule_bundle is not None:
            downloads.append(
                mo.download(
                    data=_make_timeline_csv,
                    filename="transitional_timeline.csv",
                    label="Timeline CSV",
                )
            )

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("### Export Comparison Results"),
                    mo.hstack(downloads, gap=2),
                ]
            )
        )
    return


# =============================================================================
# Error Display
# =============================================================================


@app.cell
def _(comparison_bundle, mo):
    if comparison_bundle is not None and comparison_bundle.errors:
        errors = comparison_bundle.errors
        # Show first 10 errors
        error_items = "\n".join([f"- {e}" for e in errors[:10]])
        more = f"\n\n*({len(errors) - 10} more errors)*" if len(errors) > 10 else ""

        mo.output.replace(
            mo.callout(
                mo.md(f"### Data Quality Issues ({len(errors)})\n\n{error_items}{more}"),
                kind="warn",
            )
        )
    return


if __name__ == "__main__":
    app.run()
