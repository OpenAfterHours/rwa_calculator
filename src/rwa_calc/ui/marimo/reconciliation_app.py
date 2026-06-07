"""
Parallel-Run Reconciliation Marimo Application.

Interactive UI for reconciling this calculator's output against a legacy
calculator's output, component by component, during a migration.

Pipeline position:
    Uses CreditRiskCalc.reconcile() (api/service.py), which runs our pipeline,
    loads + maps the legacy file (api/reconciliation.py), and reconciles via
    engine/reconciliation.ReconciliationRunner into a ReconciliationBundle.

Why: firms adopting this calculator run it in parallel with their existing
engine and must demonstrate where the two agree and, where they diverge, by how
much and why — so a break can be triaged to a data fix or an engine fix. This
workbook surfaces that reconciliation across four drill-down tiers (headline ->
segment -> worklist -> forensic) and lets analysts edit the TOML mapping live.

Usage:
    uv run marimo edit src/rwa_calc/ui/marimo/reconciliation_app.py
    uv run marimo run src/rwa_calc/ui/marimo/reconciliation_app.py

References:
    - Canonical components: data/schemas.RECONCILABLE_COMPONENTS
    - Config grammar: api/reconciliation.load_reconciliation_config
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full", css_file="shared/theme.css", html_head_file="shared/head.html")


@app.cell
def _():
    import sys
    from datetime import date
    from pathlib import Path

    import marimo as mo
    import polars as pl

    project_root = Path(__file__).parent.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    return Path, date, mo, pl, project_root


@app.cell
def _(mo):
    import sys as _sys
    from pathlib import Path as _P

    _shared = str(_P(__file__).parent / "shared")
    if _shared not in _sys.path:
        _sys.path.insert(0, _shared)
    try:
        from sidebar import create_sidebar as _create_sidebar

        _create_sidebar(mo)
    except Exception:
        pass
    return


@app.cell
def _(mo):
    return mo.md("""
# Parallel-Run Reconciliation

Run this calculator and reconcile its output against your **legacy** calculator,
component by component (EAD, RWA, risk weight, PD, LGD, CCF, exposure class, ...).
Each row is bucketed as **match / within-tolerance / break / missing**, with our
*reason* and *input drivers* attached so a break can be triaged to a **data** fix
or an **engine** fix.
    """)


# =============================================================================
# Our-side configuration
# =============================================================================


@app.cell
def _(mo, project_root):
    data_path_input = mo.ui.text(
        value=str(project_root / "tests" / "fixtures"),
        label="Our data path",
        full_width=True,
    )
    framework_dropdown = mo.ui.dropdown(
        options={"CRR": "CRR", "Basel 3.1": "BASEL_3_1"},
        value="CRR",
        label="Framework",
    )
    permission_dropdown = mo.ui.dropdown(
        options={"Standardised (All SA)": "standardised", "IRB (Model Permissions)": "irb"},
        value="Standardised (All SA)",
        label="Permission mode",
    )
    data_format_dropdown = mo.ui.dropdown(
        options={"Parquet": "parquet", "CSV": "csv"},
        value="Parquet",
        label="Our data format",
    )
    reporting_date_input = mo.ui.text(value="2025-01-01", label="Reporting date (YYYY-MM-DD)")

    mo.output.replace(
        mo.vstack(
            [
                mo.md("### Our calculation"),
                data_path_input,
                mo.hstack(
                    [
                        framework_dropdown,
                        permission_dropdown,
                        data_format_dropdown,
                        reporting_date_input,
                    ]
                ),
            ]
        )
    )
    return (
        data_format_dropdown,
        data_path_input,
        framework_dropdown,
        permission_dropdown,
        reporting_date_input,
    )


# =============================================================================
# Legacy mapping configuration (editable TOML)
# =============================================================================


@app.cell
def _(mo):
    _default_toml = """\
# Edit this mapping to match your legacy output file.
legacy_file   = "./legacy_output.csv"
legacy_format = "csv"
legacy_keys   = ["exposure_reference"]
our_keys      = ["exposure_reference"]
top_n         = 50

[components.rwa]
legacy_column = "RWA"
# scale = 1_000_000   # if legacy RWA is in millions

[components.ead]
legacy_column = "EAD"

# [components.risk_weight]
# legacy_column = "RW_pct"
# unit = "percent"

# [components.exposure_class]
# legacy_column = "Asset_Class"
# value_map = { CORP = "corporate", RETAIL = "retail" }
"""
    mapping_editor = mo.ui.code_editor(value=_default_toml, language="toml", label="Mapping (TOML)")

    mo.output.replace(
        mo.vstack(
            [
                mo.md("### Legacy mapping"),
                mo.md(
                    "Declare the join key(s) and which legacy column maps to each "
                    "canonical component. Numeric components accept `scale` (e.g. "
                    'millions) and `unit = "percent"`; categoricals accept a '
                    "`value_map` of label synonyms. `legacy_file` is resolved "
                    "relative to the data path above."
                ),
                mapping_editor,
            ]
        )
    )
    return (mapping_editor,)


# =============================================================================
# Run
# =============================================================================


@app.cell
def _(mo):
    run_button = mo.ui.run_button(label="Run reconciliation")
    mo.output.replace(mo.hstack([run_button], justify="center"))
    return (run_button,)


@app.cell
def _(
    Path,
    data_format_dropdown,
    data_path_input,
    framework_dropdown,
    mapping_editor,
    mo,
    permission_dropdown,
    reporting_date_input,
    run_button,
):
    from datetime import date as _date

    response = None
    run_error = None

    if run_button.value:
        try:
            from rwa_calc.api import CreditRiskCalc, loads_reconciliation_config

            settings = loads_reconciliation_config(
                mapping_editor.value, base_dir=data_path_input.value or "."
            )
            rd = reporting_date_input.value
            rd = rd if isinstance(rd, _date) else _date.fromisoformat(str(rd))
            calc = CreditRiskCalc(
                data_path=Path(data_path_input.value),
                framework=framework_dropdown.value,
                reporting_date=rd,
                permission_mode=permission_dropdown.value,
                data_format=data_format_dropdown.value,
            )
            response = calc.reconcile(settings)
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            run_error = f"{type(e).__name__}: {e}"

    if run_button.value and run_error:
        mo.output.replace(mo.callout(run_error, kind="danger"))
    elif response is not None and response.success:
        _warn = (
            mo.callout(
                mo.md(f"{len(response.errors)} reconciliation warning(s) — see the Warnings tab."),
                kind="warn",
            )
            if response.errors
            else mo.md("")
        )
        mo.output.replace(
            mo.vstack([mo.callout("Reconciliation complete.", kind="success"), _warn])
        )
    elif run_button.value:
        mo.output.replace(mo.callout("No comparable components — check the mapping.", kind="warn"))
    return (response,)


# =============================================================================
# Tier 1 — headline: totals tie-out + per-component summary
# =============================================================================


@app.cell
def _(mo, pl, response):
    if response is not None and response.success:
        tie = response.collect_totals_tie_out()

        def _fmt(v: float) -> str:
            return f"{v:,.0f}"

        stats = []
        for row in tie.iter_rows(named=True):
            stats.append(
                mo.stat(
                    value=_fmt(row["our_total"]),
                    label=f"{row['component'].upper()} — ours",
                    caption=f"legacy {_fmt(row['legacy_total'])} | Δ {row['delta_pct']:+.2f}%"
                    if row["delta_pct"] is not None
                    else f"legacy {_fmt(row['legacy_total'])}",
                    bordered=True,
                )
            )
        summary = response.collect_summary_by_component()
        mo.output.replace(
            mo.vstack(
                [
                    mo.md("## 1 · Headline — does it tie out?"),
                    mo.hstack(stats, justify="start", wrap=True) if stats else mo.md(""),
                    mo.md("**By component** (bucket counts + break rate)"),
                    mo.ui.table(summary, selection=None),
                ]
            )
        )
    else:
        mo.output.replace(mo.md(""))
    return


# =============================================================================
# Tier 2 — segment: where breaks concentrate
# =============================================================================


@app.cell
def _(mo, response):
    if response is not None and response.success:
        by_bucket = response.collect_summary_by_bucket()
        by_class = response.bundle.summary_by_exposure_class.collect()
        by_approach = response.bundle.summary_by_approach.collect()
        mo.output.replace(
            mo.vstack(
                [
                    mo.md("## 2 · Segment — where do breaks concentrate?"),
                    mo.hstack(
                        [
                            mo.vstack(
                                [mo.md("**By bucket**"), mo.ui.table(by_bucket, selection=None)]
                            ),
                            mo.vstack(
                                [
                                    mo.md("**By exposure class**"),
                                    mo.ui.table(by_class, selection=None),
                                ]
                            ),
                            mo.vstack(
                                [mo.md("**By approach**"), mo.ui.table(by_approach, selection=None)]
                            ),
                        ],
                        wrap=True,
                    ),
                ]
            )
        )
    else:
        mo.output.replace(mo.md(""))
    return


# =============================================================================
# Tier 3 — worklist: every break, ranked by materiality
# =============================================================================


@app.cell
def _(mo, response):
    if response is not None and response.success:
        breaks = response.collect_breaks_detail()
        mo.output.replace(
            mo.vstack(
                [
                    mo.md(f"## 3 · Worklist — {breaks.height} break(s), largest first"),
                    mo.ui.table(breaks, selection=None, page_size=25),
                ]
            )
        )
    else:
        mo.output.replace(mo.md(""))
    return


# =============================================================================
# Tier 4 — forensic: per-key reconciliation, filterable by bucket
# =============================================================================


@app.cell
def _(mo, response):
    if response is not None and response.success:
        bucket_filter = mo.ui.dropdown(
            options=[
                "(all)",
                "break",
                "within_tolerance",
                "exact_match",
                "missing_left",
                "missing_right",
            ],
            value="break",
            label="Row bucket",
        )
        mo.output.replace(mo.vstack([mo.md("## 4 · Forensic — per-key detail"), bucket_filter]))
    else:
        bucket_filter = None
        mo.output.replace(mo.md(""))
    return (bucket_filter,)


@app.cell
def _(bucket_filter, mo, pl, response):
    if response is not None and response.success and bucket_filter is not None:
        recon = response.collect_component_reconciliation()
        if bucket_filter.value != "(all)":
            recon = recon.filter(pl.col("row_bucket") == bucket_filter.value)
        mo.output.replace(
            mo.vstack(
                [
                    mo.md(
                        "Legacy vs ours per component, plus our **explain** (why) and "
                        "**input** (drivers) columns — use these to decide *data fix* vs "
                        "*engine fix*."
                    ),
                    mo.ui.table(recon, selection=None, page_size=25),
                ]
            )
        )
    else:
        mo.output.replace(mo.md(""))
    return


# =============================================================================
# Downloads
# =============================================================================


@app.cell
def _(mapping_editor, mo, response):
    if response is not None and response.success:

        def _recon_csv() -> bytes:
            return response.collect_component_reconciliation().write_csv().encode("utf-8")

        def _breaks_csv() -> bytes:
            return response.collect_breaks_detail().write_csv().encode("utf-8")

        def _mapping_toml() -> bytes:
            return mapping_editor.value.encode("utf-8")

        mo.output.replace(
            mo.vstack(
                [
                    mo.md("## Export"),
                    mo.hstack(
                        [
                            mo.download(
                                data=_recon_csv,
                                filename="reconciliation.csv",
                                label="Reconciliation CSV",
                            ),
                            mo.download(
                                data=_breaks_csv,
                                filename="reconciliation_breaks.csv",
                                label="Breaks CSV",
                            ),
                            mo.download(
                                data=_mapping_toml,
                                filename="reconciliation.toml",
                                label="Mapping TOML",
                            ),
                        ],
                        wrap=True,
                    ),
                ]
            )
        )
    else:
        mo.output.replace(mo.md(""))
    return


if __name__ == "__main__":
    app.run()
