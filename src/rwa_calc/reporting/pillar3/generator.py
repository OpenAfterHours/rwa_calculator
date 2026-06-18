"""
Pillar III Disclosure Generator.

Generates 13 quantitative credit risk disclosure templates from pipeline results.
CRR templates use UK prefix; Basel 3.1 templates use UKB prefix.

Pipeline position:
    OutputAggregator -> Pillar3Generator

Key responsibilities:
    - OV1: Overview of risk-weighted exposure amounts
    - CR4: SA exposure and CRM effects
    - CR5: SA risk weight allocation by risk-weight bucket
    - CR6: IRB exposures by exposure class and PD range
    - CR6-A: Scope of IRB and SA use
    - CR7: Credit derivatives effect on RWEA
    - CR7-A: Extent of CRM techniques for IRB
    - CR8: RWEA flow statements for IRB
    - CR9: IRB PD back-testing per exposure class (Basel 3.1 only)
    - CR9.1: IRB PD back-testing for ECAI mapping (Basel 3.1 only)
    - CR10: Slotting approach exposures
    - CMS1: Output floor comparison by risk type (Basel 3.1 only)
    - CMS2: Output floor comparison by asset class (Basel 3.1 only)

References:
    CRR Part 8 (Art. 438, 444, 452, 453)
    PRA PS1/26 Disclosure (CRR) Part, Art. 456, Art. 2a
    PRA PS1/26 Annex XXII (CR9/CR9.1 back-testing instructions)
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.reporting.kernel import (
    available_columns as _available_columns,
)
from rwa_calc.reporting.kernel import (
    col_sum,
    filter_by_approach,
    null_row,
    safe_sum_or_none,
)
from rwa_calc.reporting.kernel import (
    filter_off_bs as _filter_off_bs,
)
from rwa_calc.reporting.kernel import (
    filter_on_bs as _filter_on_bs,
)
from rwa_calc.reporting.kernel import (
    pick as _pick,
)
from rwa_calc.reporting.pillar3.templates import (
    CMS1_COLUMNS,
    CMS1_ROWS,
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
    CR6_PD_RANGES,
    CR6A_COLUMNS,
    CR7_COLUMNS,
    CR8_COLUMNS,
    CR8_ROWS,
    CR9_1_COLUMN_REFS,
    CR9_AIRB_CLASSES,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMN_REFS,
    CR9_FIRB_CLASSES,
    CR10_CATEGORY_MAP,
    CR10_SLOTTING_ROWS,
    HVCRE_RISK_WEIGHTS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    SLOTTING_RISK_WEIGHTS,
    CR9ClassSpec,
    P3Row,
    _letter_ref,
    get_cr4_columns,
    get_cr4_rows,
    get_cr5_columns,
    get_cr5_risk_weights,
    get_cr5_rows,
    get_cr6_columns,
    get_cr6a_rows,
    get_cr7_rows,
    get_cr7a_columns,
    get_cr10_columns,
    get_cr10_subtemplates,
    get_ov1_rows,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from polars._typing import PolarsDataType
    from xlsxwriter import Workbook

    from rwa_calc.api.service import CalculationResponse
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import Pillar3CapitalRatioOverrides
    from rwa_calc.contracts.results import ExportResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pillar3TemplateBundle:
    """Bundle of all Pillar III disclosure DataFrames.

    Single-table templates are ``pl.DataFrame | None``.
    Per-class/type templates are ``dict[str, pl.DataFrame]``.
    CMS1/CMS2/CR9/CR9.1 are Basel 3.1 only — None/empty under CRR.
    """

    ov1: pl.DataFrame | None = None
    cr4: pl.DataFrame | None = None
    cr5: pl.DataFrame | None = None
    cr6: dict[str, pl.DataFrame] = field(default_factory=dict)
    cr6a: pl.DataFrame | None = None
    cr7: pl.DataFrame | None = None
    cr7a: dict[str, pl.DataFrame] = field(default_factory=dict)
    cr8: pl.DataFrame | None = None
    cr9: dict[str, pl.DataFrame] = field(default_factory=dict)
    cr9_1: dict[str, pl.DataFrame] = field(default_factory=dict)
    cr10: dict[str, pl.DataFrame] = field(default_factory=dict)
    cms1: pl.DataFrame | None = None
    cms2: pl.DataFrame | None = None
    framework: str = "CRR"
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class Pillar3Generator:
    """Generates Pillar III disclosure templates from pipeline results.

    Stateless generator — no constructor arguments.
    """

    # ---- public interface ----

    def generate(
        self,
        response: CalculationResponse,
        *,
        previous_period_results: pl.LazyFrame | None = None,
    ) -> Pillar3TemplateBundle:
        """Generate all Pillar III templates from a ``CalculationResponse``.

        When ``previous_period_results`` (a prior-run results LazyFrame of the
        same shape as the current results) is supplied, the CR8 RWEA flow
        statement gains an opening balance (row 1) and a signed residual
        (row 8); otherwise CR8 rows 1-8 stay null (unchanged behaviour).
        """
        results_lf = response.scan_results()
        return self.generate_from_lazyframe(
            results_lf,
            framework=response.framework,
            previous_period_results=previous_period_results,
        )

    def generate_from_lazyframe(
        self,
        results: pl.LazyFrame,
        *,
        framework: str = "CRR",
        capital_ratios: Pillar3CapitalRatioOverrides | None = None,
        output_floor_summary: OutputFloorSummary | None = None,
        previous_period_results: pl.LazyFrame | None = None,
    ) -> Pillar3TemplateBundle:
        """Generate all Pillar III templates from a pipeline results LazyFrame.

        ``previous_period_results`` is an optional prior-period results
        LazyFrame (same shape as ``results``) used to populate the CR8 opening
        balance (row 1) and signed residual (row 8). When ``None`` CR8 rows 1-8
        stay null.
        """
        cols = _available_columns(results)
        errors: list[str] = []

        sa_data = _filter_by_approach(results, "standardised", cols)
        irb_data = _filter_irb_non_slotting(results, cols)
        slotting_data = _filter_by_approach(results, "slotting", cols)

        prior_irb_data: pl.LazyFrame | None = None
        if previous_period_results is not None:
            prior_cols = _available_columns(previous_period_results)
            prior_irb_data = _filter_irb_non_slotting(previous_period_results, prior_cols)

        return Pillar3TemplateBundle(
            ov1=self._generate_ov1(
                results, cols, framework, errors, capital_ratios, output_floor_summary
            ),
            cr4=self._generate_cr4(sa_data, cols, framework, errors),
            cr5=self._generate_cr5(sa_data, cols, framework, errors),
            cr6=self._generate_all_cr6(irb_data, cols, framework, errors),
            cr6a=self._generate_cr6a(results, cols, framework, errors),
            cr7=self._generate_cr7(results, cols, framework, errors),
            cr7a=self._generate_all_cr7a(results, cols, framework, errors),
            cr8=self._generate_cr8(irb_data, cols, errors, prior_irb_data),
            cr9=self._generate_all_cr9(irb_data, cols, framework, errors),
            cr9_1=self._generate_cr9_1(irb_data, cols, framework, errors),
            cr10=self._generate_all_cr10(slotting_data, cols, framework, errors),
            cms1=self._generate_cms1(results, cols, framework, errors),
            cms2=self._generate_cms2(
                results, sa_data, irb_data, slotting_data, cols, framework, errors
            ),
            framework=framework,
            errors=errors,
        )

    def export_to_excel(
        self,
        bundle: Pillar3TemplateBundle,
        output_path: Path,
    ) -> ExportResult:
        """Write Pillar III templates to an Excel workbook."""
        from rwa_calc.contracts.results import ExportResult

        try:
            import xlsxwriter as xw
        except ModuleNotFoundError:
            msg = "xlsxwriter is required for Excel export. Install with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook = xw.Workbook(str(output_path))
        total_rows = 0
        prefix = "UKB" if bundle.framework == "BASEL_3_1" else "UK"

        try:
            if bundle.ov1 is not None:
                total_rows += _write_single_sheet(workbook, bundle.ov1, f"{prefix} OV1")
            if bundle.cr4 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cr4, f"{prefix} CR4")
            if bundle.cr5 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cr5, f"{prefix} CR5")
            total_rows += _write_dict_sheets(
                workbook, bundle.cr6, f"{prefix} CR6", IRB_EXPOSURE_CLASSES
            )
            if bundle.cr6a is not None:
                total_rows += _write_single_sheet(workbook, bundle.cr6a, f"{prefix} CR6-A")
            if bundle.cr7 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cr7, f"{prefix} CR7")
            total_rows += _write_dict_sheets(
                workbook,
                bundle.cr7a,
                f"{prefix} CR7-A",
                {"foundation_irb": "F-IRB", "advanced_irb": "A-IRB"},
            )
            if bundle.cr8 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cr8, f"{prefix} CR8")
            if bundle.cr9:
                cr9_display = _cr9_display_names(bundle.cr9)
                total_rows += _write_dict_sheets(workbook, bundle.cr9, f"{prefix} CR9", cr9_display)
            subtemplates = get_cr10_subtemplates(bundle.framework)
            total_rows += _write_dict_sheets(workbook, bundle.cr10, f"{prefix} CR10", subtemplates)
            if bundle.cms1 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cms1, f"{prefix} CMS1")
            if bundle.cms2 is not None:
                total_rows += _write_single_sheet(workbook, bundle.cms2, f"{prefix} CMS2")
        finally:
            workbook.close()

        return ExportResult(format="pillar3_excel", files=[output_path], row_count=total_rows)

    # ---- OV1 ----

    def _generate_ov1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
        capital_ratios: Pillar3CapitalRatioOverrides | None = None,
        output_floor_summary: OutputFloorSummary | None = None,
    ) -> pl.DataFrame | None:
        rwa_col = _pick(cols, "rwa_final", "rwa")
        if not rwa_col:
            errors.append("OV1: missing RWA column")
            return None

        approach_col = _pick(cols, "approach_applied", "approach")
        pre_floor_col = _pick(cols, "rwa_pre_floor")
        data = results.collect()
        column_refs = [c.ref for c in OV1_COLUMNS]

        total_rwa = _col_sum(data, rwa_col)
        own_funds = total_rwa * 0.08 if total_rwa else None
        rows_out: list[dict[str, object]] = [
            _ov1_row_values(
                row_def,
                data=data,
                cols=cols,
                rwa_col=rwa_col,
                approach_col=approach_col,
                pre_floor_col=pre_floor_col,
                total_rwa=total_rwa,
                own_funds=own_funds,
                capital_ratios=capital_ratios,
                output_floor_summary=output_floor_summary,
                column_refs=column_refs,
            )
            for row_def in get_ov1_rows(framework)
        ]
        return _build_df(rows_out, column_refs)

    # ---- CR4 ----

    def _generate_cr4(
        self,
        sa_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa")
        ec_col = _pick(cols, "exposure_class")
        if not ead_col or not rwa_col:
            errors.append("CR4: missing EAD or RWA column")
            return None

        data = sa_data.collect()
        cr4_rows = get_cr4_rows(framework)
        column_refs = [c.ref for c in get_cr4_columns(framework)]
        rows_out: list[dict[str, object]] = []

        for row_def in cr4_rows:
            if row_def.is_total:
                subset = data
            elif row_def.exposure_classes and ec_col:
                subset = data.filter(pl.col(ec_col).is_in(list(row_def.exposure_classes)))
            else:
                rows_out.append(_null_row(row_def, column_refs))
                continue

            values = _compute_cr4_values(subset, cols, ead_col, rwa_col)
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR5 ----

    def _generate_cr5(
        self,
        sa_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        ead_col = _pick(cols, "ead_final")
        rw_col = _pick(cols, "risk_weight")
        ec_col = _pick(cols, "exposure_class")
        if not ead_col or not rw_col:
            errors.append("CR5: missing EAD or risk_weight column")
            return None

        data = sa_data.collect()
        cr5_rows = get_cr5_rows(framework)
        rw_bands = get_cr5_risk_weights(framework)
        all_columns = get_cr5_columns(framework)
        column_refs = [c.ref for c in all_columns]
        is_b31 = framework == "BASEL_3_1"
        role_col = _pick(cols, "re_split_role")
        rows_out: list[dict[str, object]] = []

        for row_def in cr5_rows:
            if row_def.is_total:
                subset = data
            else:
                predicate = _cr5_row_predicate(row_def, ec_col, role_col)
                if predicate is None:
                    rows_out.append(_null_row(row_def, column_refs))
                    continue
                subset = data.filter(predicate)

            values = _compute_cr5_values(subset, cols, ead_col, rw_col, rw_bands, is_b31)
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR6 ----

    def _generate_all_cr6(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa")
        ec_col = _pick(cols, "exposure_class")
        if not ead_col or not rwa_col or not ec_col:
            errors.append("CR6: missing required columns")
            return {}

        data = irb_data.collect()
        if data.height == 0:
            return {}

        is_b31 = framework == "BASEL_3_1"
        alloc_pd_col = _pick(cols, "pd") if is_b31 else None
        report_pd_col = _pick(cols, "pd_floored")
        pd_col = alloc_pd_col or report_pd_col or _pick(cols, "pd_floored")

        if not pd_col:
            errors.append("CR6: missing PD column")
            return {}

        result: dict[str, pl.DataFrame] = {}
        for ec_val in data[ec_col].unique().to_list():
            if ec_val not in IRB_EXPOSURE_CLASSES:
                continue
            class_data = data.filter(pl.col(ec_col) == ec_val)
            result[ec_val] = self._generate_cr6_for_class(
                class_data,
                cols,
                ead_col,
                rwa_col,
                pd_col,
                report_pd_col or pd_col,
                framework,
            )

        return result

    def _generate_cr6_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        alloc_pd_col: str,
        report_pd_col: str,
        framework: str,
    ) -> pl.DataFrame:
        cr6_cols = get_cr6_columns(framework)
        column_refs = [c.ref for c in cr6_cols]
        rows_out: list[dict[str, object]] = []

        for lower, upper, row_ref, label in CR6_PD_RANGES:
            if math.isinf(upper):
                bucket = class_data.filter(pl.col(alloc_pd_col) >= lower)
            else:
                bucket = class_data.filter(
                    (pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper)
                )

            values = _compute_cr6_values(bucket, cols, ead_col, rwa_col, report_pd_col)
            values["a"] = label
            row = P3Row(row_ref, label)
            rows_out.append(_make_row(row, values, column_refs))

        # Total row
        total_values = _compute_cr6_values(class_data, cols, ead_col, rwa_col, report_pd_col)
        total_values["a"] = "Total"
        rows_out.append(_make_row(P3Row("18", "Total", is_total=True), total_values, column_refs))

        # Build with mixed types: col "a" is String, rest Float64
        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.String if ref == "a" else pl.Float64
        return pl.DataFrame(rows_out, schema=schema)

    # ---- CR6-A ----

    def _generate_cr6a(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        ead_col = _pick(cols, "ead_final")
        ec_col = _pick(cols, "exposure_class")
        approach_col = _pick(cols, "approach_applied", "approach")
        if not ead_col or not ec_col or not approach_col:
            errors.append("CR6-A: missing required columns")
            return None

        data = results.collect()
        cr6a_rows = get_cr6a_rows(framework)
        column_refs = [c.ref for c in CR6A_COLUMNS]
        irb_approaches = {"foundation_irb", "advanced_irb", "slotting"}
        rows_out: list[dict[str, object]] = []

        for row_def in cr6a_rows:
            if row_def.is_total:
                subset = data
            elif row_def.exposure_classes:
                subset = data.filter(pl.col(ec_col).is_in(list(row_def.exposure_classes)))
            else:
                rows_out.append(_null_row(row_def, column_refs))
                continue

            total_ead = _col_sum(subset, ead_col) or 0.0
            irb_subset = subset.filter(pl.col(approach_col).is_in(list(irb_approaches)))
            irb_ead = _col_sum(irb_subset, ead_col) or 0.0
            sa_subset = subset.filter(~pl.col(approach_col).is_in(list(irb_approaches)))
            sa_ead = _col_sum(sa_subset, ead_col) or 0.0

            values: dict[str, object] = {
                "a": irb_ead,
                "b": total_ead,
                "c": (sa_ead / total_ead * 100.0) if total_ead > 0 else None,
                "d": (irb_ead / total_ead * 100.0) if total_ead > 0 else None,
                "e": 0.0,  # Roll-out plan % — not available from pipeline
            }
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR7 ----

    def _generate_cr7(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        rwa_col = _pick(cols, "rwa_final", "rwa")
        approach_col = _pick(cols, "approach_applied", "approach")
        ec_col = _pick(cols, "exposure_class")
        if not rwa_col or not approach_col:
            errors.append("CR7: missing required columns")
            return None

        data = results.collect()
        cr7_rows = get_cr7_rows(framework)
        column_refs = [c.ref for c in CR7_COLUMNS]

        firb = data.filter(pl.col(approach_col) == "foundation_irb")
        airb = data.filter(pl.col(approach_col) == "advanced_irb")
        slotting = data.filter(pl.col(approach_col) == "slotting")

        rows_out: list[dict[str, object]] = []
        for row_def in cr7_rows:
            rwa = _cr7_row_rwa(
                row_def,
                framework=framework,
                data=data,
                firb=firb,
                airb=airb,
                slotting=slotting,
                ec_col=ec_col,
                approach_col=approach_col,
                rwa_col=rwa_col,
            )
            # Pre-CD RWEA approximation = post-CD RWEA (pre-CD tracking not available)
            rows_out.append(_make_row(row_def, {"a": rwa, "b": rwa}, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR7-A ----

    def _generate_all_cr7a(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa")
        approach_col = _pick(cols, "approach_applied", "approach")
        ec_col = _pick(cols, "exposure_class")
        if not ead_col or not rwa_col or not approach_col:
            errors.append("CR7-A: missing required columns")
            return {}

        data = results.collect()
        cr7a_cols = get_cr7a_columns(framework)
        column_refs = [c.ref for c in cr7a_cols]
        result: dict[str, pl.DataFrame] = {}

        from rwa_calc.reporting.pillar3.templates import CR7A_AIRB_ROWS, CR7A_FIRB_ROWS

        for approach_key, approach_val, row_defs in [
            ("foundation_irb", "foundation_irb", CR7A_FIRB_ROWS),
            ("advanced_irb", "advanced_irb", CR7A_AIRB_ROWS),
        ]:
            approach_data = data.filter(pl.col(approach_col) == approach_val)
            if approach_data.height == 0:
                continue

            rows_out: list[dict[str, object]] = []
            for row_def in row_defs:
                if row_def.is_total:
                    subset = approach_data
                elif row_def.exposure_classes and ec_col:
                    subset = approach_data.filter(
                        pl.col(ec_col).is_in(list(row_def.exposure_classes))
                    )
                else:
                    rows_out.append(_null_row(row_def, column_refs))
                    continue

                values = _compute_cr7a_values(subset, cols, ead_col)
                rows_out.append(_make_row(row_def, values, column_refs))

            result[approach_key] = _build_df(rows_out, column_refs)

        return result

    # ---- CR8 ----

    @cites("PS1/26, paragraph 147.2")
    def _generate_cr8(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        errors: list[str],
        prior_irb_data: pl.LazyFrame | None = None,
    ) -> pl.DataFrame | None:
        """Generate the CR8 RWEA flow statement for IRB credit-risk exposures.

        Row 9 (closing) sums the current-period IRB (non-slotting) ``rwa_final``;
        when ``prior_irb_data`` is supplied, row 1 (opening) sums the prior
        period on the same like-for-like basis and row 8 (Other) carries the
        signed residual ``closing - opening`` (positive = increase, negative =
        decrease per PS1/26 Annex XXII §11). Rows 2-7 (per-driver flow
        components) stay null — they need exposure-level period-over-period
        lineage not available from two point-in-time snapshots. When
        ``prior_irb_data`` is None, rows 1-8 stay null (unchanged behaviour).

        References:
            CRR Part 8 Art. 438(h); PRA PS1/26 Annex XXII §11.
        """
        rwa_col = _pick(cols, "rwa_final", "rwa")
        if not rwa_col:
            errors.append("CR8: missing RWA column")
            return None

        data = irb_data.collect()
        column_refs = [c.ref for c in CR8_COLUMNS]
        closing_rwa = _col_sum(data, rwa_col)

        opening_rwa: float | None = None
        other_rwa: float | None = None
        if prior_irb_data is not None:
            opening_rwa = _col_sum(prior_irb_data.collect(), rwa_col)
            # Row 8 (Other) = signed residual = closing - opening (rows 2-7 = 0).
            other_rwa = (closing_rwa or 0.0) - (opening_rwa or 0.0)

        rows_out: list[dict[str, object]] = []
        for row_def in CR8_ROWS:
            if row_def.ref == "9":
                values: dict[str, object] = {"a": closing_rwa}
            elif row_def.ref == "1":
                # Opening balance — prior-period closing (None without prior data).
                values = {"a": opening_rwa}
            elif row_def.ref == "8":
                # Other — signed residual delta (None without prior data).
                values = {"a": other_rwa}
            else:
                # Flow drivers (rows 2-7) — require multi-period comparison.
                values = {"a": None}
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR9 — PD back-testing per exposure class (Art. 452(h)) ----

    @cites("PS1/26, paragraph 147.2")
    def _generate_all_cr9(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate UKB CR9 PD back-testing templates.

        Basel 3.1 only. Returns separate DataFrames per approach-class
        combination, keyed as ``"{approach} - {class_display}"``.

        References:
            PRA PS1/26 Art. 452(h), Annex XXII paras 12-15
        """
        if framework != "BASEL_3_1":
            return {}

        ec_col = _pick(cols, "exposure_class")
        approach_col = _pick(cols, "approach_applied", "approach")
        if not ec_col or not approach_col:
            errors.append("CR9: missing required columns (exposure_class, approach)")
            return {}

        # PD column selection — CR9 should use PD at beginning of disclosure
        # period. Since the pipeline does not provide this temporal variant,
        # we use pd (pre-input-floor model PD) as closest proxy
        # for bucket allocation. The reported PD (cols f, g) uses post-floor PD.
        alloc_pd_col = _pick(cols, "pd", "pd_floored")
        report_pd_col = _pick(cols, "pd_floored", "pd")
        if not alloc_pd_col:
            errors.append("CR9: no PD column available — skipping PD backtesting")
            return {}

        data = irb_data.collect()
        if data.height == 0:
            return {}

        result: dict[str, pl.DataFrame] = {}

        for approach_val, _approach_display, class_defs in [
            ("foundation_irb", "F-IRB", CR9_FIRB_CLASSES),
            ("advanced_irb", "A-IRB", CR9_AIRB_CLASSES),
        ]:
            approach_data = data.filter(pl.col(approach_col) == approach_val)
            if approach_data.height == 0:
                continue

            for class_key, class_display, spec in class_defs:
                predicate = _cr9_class_predicate(spec, ec_col, cols)
                class_data = approach_data.filter(predicate)
                if class_data.height == 0:
                    continue

                key = f"{approach_val} - {class_key}"
                result[key] = self._generate_cr9_for_class(
                    class_data,
                    cols,
                    alloc_pd_col,
                    report_pd_col or alloc_pd_col,
                    class_display,
                )

        return result

    def _generate_cr9_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        alloc_pd_col: str,
        report_pd_col: str,
        class_display: str,
    ) -> pl.DataFrame:
        """Generate a single CR9 template for one exposure class."""
        column_refs = CR9_COLUMN_REFS
        rows_out: list[dict[str, object]] = []

        for lower, upper, row_ref, label in CR6_PD_RANGES:
            bucket_row = _cr9_bucket_row(
                class_data,
                cols,
                alloc_pd_col,
                report_pd_col,
                class_display,
                lower,
                upper,
                label,
                row_ref,
                column_refs,
            )
            if bucket_row is not None:
                rows_out.append(bucket_row)

        if class_data.height > 0:
            rows_out.append(
                _cr9_total_row(class_data, cols, report_pd_col, class_display, column_refs)
            )

        if not rows_out:
            return _cr9_empty_schema(column_refs)
        return pl.DataFrame(rows_out, schema=_cr9_schema(column_refs))

    # ---- CR9.1 — ECAI-based PD back-testing (Art. 180(1)(f)) ----

    @cites("PS1/26, paragraph 147.2")
    def _generate_cr9_1(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate UKB CR9.1 ECAI-based PD back-testing templates.

        Basel 3.1 only. Supplementary to CR9 for firms using Art. 180(1)(f)
        ECAI-based PD estimation: obligors in scope (``ecai_pd_mapping`` truthy)
        are grouped by their firm-grade-to-ECAI mapping
        (``external_rating_equivalent``) rather than by the fixed CR6 PD-range
        bands. Returns separate DataFrames per approach-class combination,
        keyed as ``"{approach} - {class_key}"``.

        References:
            PRA PS1/26 Art. 452(h), Art. 180(1)(f), Annex XXII paras 12-15
        """
        if framework != "BASEL_3_1":
            return {}

        ec_col = _pick(cols, "exposure_class")
        approach_col = _pick(cols, "approach_applied", "approach")
        mapping_col = _pick(cols, "ecai_pd_mapping")
        grade_col = _pick(cols, "external_rating_equivalent")
        if not ec_col or not approach_col or not mapping_col or not grade_col:
            return {}

        report_pd_col = _pick(cols, "pd_floored", "pd")
        if not report_pd_col:
            errors.append("CR9.1: no PD column available — skipping ECAI backtesting")
            return {}

        data = irb_data.collect()
        if data.height == 0:
            return {}

        # Only obligors flagged for Art. 180(1)(f) ECAI-based PD estimation.
        data = data.filter(pl.col(mapping_col))
        if data.height == 0:
            return {}

        result: dict[str, pl.DataFrame] = {}

        for approach_val, _approach_display, class_defs in [
            ("foundation_irb", "F-IRB", CR9_FIRB_CLASSES),
            ("advanced_irb", "A-IRB", CR9_AIRB_CLASSES),
        ]:
            approach_data = data.filter(pl.col(approach_col) == approach_val)
            if approach_data.height == 0:
                continue

            for class_key, class_display, spec in class_defs:
                predicate = _cr9_class_predicate(spec, ec_col, cols)
                class_data = approach_data.filter(predicate)
                if class_data.height == 0:
                    continue

                key = f"{approach_val} - {class_key}"
                result[key] = self._generate_cr9_1_for_class(
                    class_data,
                    cols,
                    report_pd_col,
                    grade_col,
                    class_display,
                )

        return result

    def _generate_cr9_1_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        report_pd_col: str,
        grade_col: str,
        class_display: str,
    ) -> pl.DataFrame:
        """Generate a single CR9.1 template for one exposure class.

        One row per distinct ECAI grade (``external_rating_equivalent``),
        followed by an aggregate Total row. Columns c-h reuse the CR9 value
        computation; the dynamic ECAI column carries the grade label.
        """
        column_refs = CR9_1_COLUMN_REFS
        rows_out: list[dict[str, object]] = []

        for grade in class_data[grade_col].unique(maintain_order=True).to_list():
            bucket = class_data.filter(pl.col(grade_col) == grade)
            values = _compute_cr9_values(bucket, cols, report_pd_col)
            values["a"] = class_display
            values["b"] = grade
            row = _make_row(P3Row(str(grade), str(grade)), values, column_refs)
            row[grade_col] = grade
            rows_out.append(row)

        # Aggregate Total row across all grades.
        total_values = _compute_cr9_values(class_data, cols, report_pd_col)
        total_values["a"] = class_display
        total_values["b"] = "Total"
        total_row = _make_row(P3Row("Total", "Total", is_total=True), total_values, column_refs)
        total_row[grade_col] = "Total"
        rows_out.append(total_row)

        return pl.DataFrame(rows_out, schema=_cr9_1_schema(column_refs, grade_col))

    # ---- CR10 ----

    def _generate_all_cr10(
        self,
        slotting_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa")
        if not ead_col or not rwa_col:
            errors.append("CR10: missing required columns")
            return {}

        data = slotting_data.collect()
        if data.height == 0:
            return {}

        subtemplates = get_cr10_subtemplates(framework)
        cr10_cols = get_cr10_columns(framework)
        column_refs = [c.ref for c in cr10_cols]
        sl_type_col = _pick(cols, "sl_type")
        cat_col = _pick(cols, "slotting_category")
        el_col = _pick(cols, "expected_loss")
        result: dict[str, pl.DataFrame] = {}

        for sl_key in subtemplates:
            type_data = _cr10_type_data(data, sl_type_col, sl_key, framework)
            if type_data.height == 0 and sl_key != "equity":
                continue

            rw_map = _cr10_rw_map_for(sl_key)
            rows_out: list[dict[str, object]] = []

            for row_def in CR10_SLOTTING_ROWS:
                subset_pair = _cr10_row_subset(row_def, type_data, cat_col, rw_map)
                if subset_pair is None:
                    rows_out.append(_null_row(row_def, column_refs))
                    continue
                subset, rw_value = subset_pair
                values = _compute_cr10_values(subset, cols, ead_col, rwa_col, el_col, rw_value)
                rows_out.append(_make_row(row_def, values, column_refs))

            result[sl_key] = _build_df(rows_out, column_refs)

        return result

    # ---- CMS1 — Output floor comparison by risk type (Art. 456(1)(a)) ----

    def _generate_cms1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate UKB CMS1: SA vs modelled RWA comparison by risk type.

        Basel 3.1 only — returns None under CRR. Only the credit risk row
        (0010) and total row (0080) are populated from the pipeline; other
        risk types (CCR, CVA, securitisation, market, op risk, residual)
        require data beyond credit risk scope and are left null.

        References:
            PRA PS1/26 Art. 456(1)(a), Art. 2a(1)
        """
        if framework != "BASEL_3_1":
            return None

        rwa_col = _pick(cols, "rwa_final", "rwa")
        approach_col = _pick(cols, "approach_applied", "approach")
        sa_rwa_col = _pick(cols, "sa_rwa")

        if not rwa_col:
            errors.append("CMS1: missing RWA column")
            return None

        data = results.collect()
        column_refs = [c.ref for c in CMS1_COLUMNS]
        rows_out: list[dict[str, object]] = []

        # Compute portfolio-level aggregates
        # Col a: RWA for modelled approaches (IRB + slotting)
        modelled_rwa = 0.0
        # Col b: RWA for SA-only portfolios
        sa_portfolio_rwa = 0.0
        if approach_col:
            modelled_approaches = ["foundation_irb", "advanced_irb", "slotting"]
            modelled = data.filter(pl.col(approach_col).is_in(modelled_approaches))
            sa_only = data.filter(~pl.col(approach_col).is_in(modelled_approaches))
            modelled_rwa = _col_sum(modelled, rwa_col) or 0.0
            sa_portfolio_rwa = _col_sum(sa_only, rwa_col) or 0.0

        # Col c: Total actual RWA = modelled + SA portfolio
        total_actual_rwa = modelled_rwa + sa_portfolio_rwa

        # Col d: Full SA RWA (all exposures under SA)
        full_sa_rwa = _col_sum(data, sa_rwa_col) if sa_rwa_col else None

        for row_def in CMS1_ROWS:
            values: dict[str, object] = {"a": None, "b": None, "c": None, "d": None}

            if row_def.ref in ("0010", "0080"):
                # Credit risk row and total row — populated from pipeline
                values["a"] = modelled_rwa
                values["b"] = sa_portfolio_rwa
                values["c"] = total_actual_rwa
                values["d"] = full_sa_rwa

            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CMS2 — Output floor comparison by asset class (Art. 456(1)(b)) ----

    def _generate_cms2(
        self,
        results: pl.LazyFrame,
        sa_data: pl.LazyFrame,
        irb_data: pl.LazyFrame,
        slotting_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate UKB CMS2: SA vs modelled RWA comparison by asset class.

        Basel 3.1 only — returns None under CRR. Breaks down credit risk
        exposures by asset class with modelled vs SA comparison. Excludes
        CCR, CVA, and securitisation.

        References:
            PRA PS1/26 Art. 456(1)(b), Art. 2a(2)
        """
        if framework != "BASEL_3_1":
            return None

        rwa_col = _pick(cols, "rwa_final", "rwa")
        ec_col = _pick(cols, "exposure_class")
        approach_col = _pick(cols, "approach_applied", "approach")
        sa_rwa_col = _pick(cols, "sa_rwa")

        if not rwa_col:
            errors.append("CMS2: missing RWA column")
            return None

        # Collect all sub-frames
        all_data = results.collect()
        sa_collected = sa_data.collect()
        irb_collected = irb_data.collect()
        slotting_collected = slotting_data.collect()

        # Merge IRB + slotting into "modelled" data
        modelled_data = pl.concat([irb_collected, slotting_collected], how="diagonal_relaxed")

        column_refs = [c.ref for c in CMS2_COLUMNS]
        rows_out: list[dict[str, object]] = []

        for row_def in CMS2_ROWS:
            values = _cms2_row_values(
                row_def,
                modelled_data=modelled_data,
                sa_collected=sa_collected,
                all_data=all_data,
                ec_col=ec_col,
                approach_col=approach_col,
                rwa_col=rwa_col,
                sa_rwa_col=sa_rwa_col,
            )
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _col_sum(data: pl.DataFrame, col_name: str | None) -> float | None:
    """Sum a single column, returning None if absent or empty.

    Thin adapter over ``kernel.col_sum`` keeping the Pillar 3 empty-frame
    semantics (empty subset -> null cell, ``empty_as_none=True``).
    """
    return col_sum(data, set(data.columns), col_name, empty_as_none=True)


def _safe_sum(data: pl.DataFrame, *col_names: str) -> float | None:
    """Sum multiple columns, skipping absent ones.

    Thin adapter over ``kernel.safe_sum_or_none`` keeping the Pillar 3
    no-column-present semantics (-> null cell).
    """
    return safe_sum_or_none(data, set(data.columns), *col_names)


def _approach_rwa(
    data: pl.DataFrame,
    approach_col: str,
    rwa_col: str,
    approach: str,
) -> float | None:
    """Sum RWA for a specific approach."""
    filtered = data.filter(pl.col(approach_col) == approach)
    if filtered.height == 0:
        return 0.0
    result = filtered.select(pl.col(rwa_col).sum()).item()
    return float(result) if result is not None else 0.0


def _ead_weighted_avg(
    data: pl.DataFrame,
    ead_col: str,
    metric_col: str | None,
) -> float | None:
    """Compute EAD-weighted average of a metric column."""
    if not metric_col or metric_col not in data.columns or data.height == 0:
        return None
    result = data.select(
        (pl.col(metric_col) * pl.col(ead_col)).sum() / pl.col(ead_col).sum()
    ).item()
    return float(result) if result is not None else None


def _null_row(row_def: P3Row, column_refs: list[str]) -> dict[str, object]:
    """Build a row dict with all column values set to None.

    Thin adapter over ``kernel.null_row`` taking a ``P3Row`` definition.
    """
    return null_row(row_def.ref, row_def.name, column_refs)


def _make_row(
    row_def: P3Row,
    values: Mapping[str, object],
    column_refs: list[str],
) -> dict[str, object]:
    """Build a row dict from computed values, filling missing refs with None."""
    row: dict[str, object] = {"row_ref": row_def.ref, "row_name": row_def.name}
    for ref in column_refs:
        row[ref] = values.get(ref)
    return row


def _build_df(rows: list[dict[str, object]], column_refs: list[str]) -> pl.DataFrame:
    """Materialise a list of row dicts into a typed Polars DataFrame."""
    schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
    schema.update(dict.fromkeys(column_refs, pl.Float64))
    return pl.DataFrame(rows, schema=schema)


def _filter_by_approach(
    results: pl.LazyFrame,
    approach_value: str,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter results to a specific approach_applied value.

    Thin adapter over ``kernel.filter_by_approach`` keeping the Pillar 3
    legacy ``approach`` column alias as a fallback candidate.
    """
    return filter_by_approach(
        results, approach_value, cols, candidates=("approach_applied", "approach")
    )


def _filter_irb_non_slotting(
    results: pl.LazyFrame,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter to F-IRB and A-IRB exposures (excluding slotting)."""
    approach_col = _pick(cols, "approach_applied", "approach")
    if not approach_col:
        return results.filter(pl.lit(False))
    return results.filter(pl.col(approach_col).is_in(["foundation_irb", "advanced_irb"]))


_OV1_RATIO_REFS: frozenset[str] = frozenset({"5a", "5b", "6a", "6b", "7a", "7b"})
# Floor rows whose column ``a`` is a multiplier (26) or RWA adjustment (27):
# column ``c`` (own-funds requirement) is meaningless for these and must stay
# null — they are excluded from the 8%-of-a auto-shim.
_OV1_FLOOR_NO_SHIM_REFS: frozenset[str] = frozenset({"26", "27"})
# Equity sub-approach discriminators (Basel 3.1 OV1 memo rows 11-14): each
# filters approach_applied=="equity" AND a sub-approach column == value.
_OV1_EQUITY_SUBAPPROACH_REFS: dict[str, tuple[str, str]] = {
    "11": ("equity_transitional_approach", "irb_transitional"),
    "12": ("ciu_approach", "look_through"),
    "13": ("ciu_approach", "mandate_based"),
    "14": ("ciu_approach", "fallback"),
}
# Refs whose value is _approach_rwa(approach_col, rwa_col, <approach>).
_OV1_APPROACH_REFS: dict[str, str] = {
    "3": "foundation_irb",
    "4": "slotting",
    "UK4a": "equity",
    "5": "advanced_irb",
}


def _ov1_row_values(
    row_def: P3Row,
    *,
    data: pl.DataFrame,
    cols: set[str],
    rwa_col: str,
    approach_col: str | None,
    pre_floor_col: str | None,
    total_rwa: float | None,
    own_funds: float | None,
    capital_ratios: Pillar3CapitalRatioOverrides | None,
    output_floor_summary: OutputFloorSummary | None,
    column_refs: list[str],
) -> dict[str, object]:
    """Compute OV1 cell values for a single template row."""
    ref = row_def.ref
    values = _ov1_cell_values(
        ref,
        data=data,
        cols=cols,
        rwa_col=rwa_col,
        approach_col=approach_col,
        pre_floor_col=pre_floor_col,
        total_rwa=total_rwa,
        own_funds=own_funds,
        capital_ratios=capital_ratios,
        output_floor_summary=output_floor_summary,
    )

    # Column b (T-1) always None — requires prior period data
    values.setdefault("b", None)
    # Auto-shim: own funds = a * 0.08, except for ratio rows where column c
    # is intentionally None (a is itself a percentage) and the floor rows
    # 26/27 where column a is a multiplier/adjustment, not an RWA amount.
    no_shim = ref in _OV1_RATIO_REFS or ref in _OV1_FLOOR_NO_SHIM_REFS
    if not no_shim and values.get("a") is not None and values.get("c") is None:
        values["c"] = float(cast("float", values["a"] or 0.0)) * 0.08

    return _make_row(row_def, values, column_refs)


def _ov1_cell_values(
    ref: str,
    *,
    data: pl.DataFrame,
    cols: set[str],
    rwa_col: str,
    approach_col: str | None,
    pre_floor_col: str | None,
    total_rwa: float | None,
    own_funds: float | None,
    capital_ratios: Pillar3CapitalRatioOverrides | None,
    output_floor_summary: OutputFloorSummary | None,
) -> dict[str, object]:
    """Resolve the populated cell values for one OV1 row (pre auto-shim)."""
    if ref in ("29", "1"):
        return {"a": total_rwa, "c": own_funds}
    if ref == "4a":
        return _ov1_pre_floor_row(data, pre_floor_col)
    if ref in _OV1_RATIO_REFS:
        return {"a": _ov1_ratio_value(capital_ratios, ref)}
    if ref == "24":
        return {"a": _ov1_memo_250_row(data, cols, rwa_col)}
    if ref in _OV1_EQUITY_SUBAPPROACH_REFS:
        return {"a": _ov1_equity_subapproach_rwa(ref, data, cols, approach_col, rwa_col)}
    if ref == "26":
        # Output floor multiplier — first non-null per-row output_floor_pct.
        return {"a": _ov1_floor_multiplier(data, cols)}
    if ref == "27":
        # Output floor adjustment (OF-ADJ) — lives only on the summary bundle.
        return {"a": output_floor_summary.of_adj if output_floor_summary else None}
    if approach_col:
        return _ov1_approach_cell(ref, data, approach_col, rwa_col)
    return {}


def _ov1_approach_cell(
    ref: str,
    data: pl.DataFrame,
    approach_col: str,
    rwa_col: str,
) -> dict[str, object]:
    """OV1 rows whose column ``a`` comes from a per-approach RWA sum."""
    if ref == "2":
        sa_rwa = _approach_rwa(data, approach_col, rwa_col, "standardised")
        eq_rwa = _approach_rwa(data, approach_col, rwa_col, "equity")
        return {"a": (sa_rwa or 0.0) + (eq_rwa or 0.0)}
    approach = _OV1_APPROACH_REFS.get(ref)
    if approach is None:
        return {}
    return {"a": _approach_rwa(data, approach_col, rwa_col, approach)}


def _ov1_pre_floor_row(
    data: pl.DataFrame,
    pre_floor_col: str | None,
) -> dict[str, object]:
    """OV1 row 4a: pre-floor total RWEAs."""
    if not pre_floor_col:
        # No pre-floor column — leave a/b/c as None (mirror existing fallback).
        return {}
    pre_floor_total = _col_sum(data, pre_floor_col)
    return {
        "a": pre_floor_total,
        "c": pre_floor_total * 0.08 if pre_floor_total is not None else None,
    }


def _ov1_ratio_value(
    capital_ratios: Pillar3CapitalRatioOverrides | None,
    ref: str,
) -> float | None:
    """Pre-floor capital-ratio cell value as a percentage."""
    ratio = _ratio_for_ref(capital_ratios, ref)
    return float(ratio) * 100.0 if ratio is not None else None


def _ov1_memo_250_row(
    data: pl.DataFrame,
    cols: set[str],
    rwa_col: str,
) -> float | None:
    """Memo row 24: RWA of exposures with a 250% risk weight."""
    rw_col = _pick(cols, "risk_weight")
    if not rw_col:
        return None
    memo = data.filter((pl.col(rw_col) >= 2.495) & (pl.col(rw_col) <= 2.505))
    return _col_sum(memo, rwa_col)


@cites("PS1/26, paragraph 132")
def _ov1_equity_subapproach_rwa(
    ref: str,
    data: pl.DataFrame,
    cols: set[str],
    approach_col: str | None,
    rwa_col: str,
) -> float | None:
    """OV1 memo rows 11-14: equity RWEA broken down by sub-approach.

    Sums ``rwa_final`` for ``approach_applied == "equity"`` AND the
    discriminator column/value for the row (IRB transitional, look-through,
    mandate-based, fall-back). These are "of which" sub-rows of equity already
    counted in row 2 — they are not added to the row-29 total.

    References:
        PRA PS1/26 Annex XX (UKB OV1 rows 11-14), Art. 132-132C (CIU sub-approaches).
    """
    disc = _OV1_EQUITY_SUBAPPROACH_REFS.get(ref)
    if disc is None:
        return None
    disc_col, disc_val = disc
    if not approach_col or disc_col not in cols:
        return None
    subset = data.filter((pl.col(approach_col) == "equity") & (pl.col(disc_col) == disc_val))
    return _col_sum(subset, rwa_col)


def _ov1_floor_multiplier(data: pl.DataFrame, cols: set[str]) -> float | None:
    """OV1 row 26: output floor multiplier (first non-null ``output_floor_pct``)."""
    floor_col = _pick(cols, "output_floor_pct")
    if not floor_col or data.height == 0:
        return None
    result = data.select(pl.col(floor_col).drop_nulls().first()).item()
    return float(result) if result is not None else None


# ---------------------------------------------------------------------------
# CR7 row helpers
# ---------------------------------------------------------------------------


_CR7_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")
_CR7_B31_CORP_CLASSES: tuple[str, ...] = ("corporate", "corporate_sme", "specialised_lending")
_CR7_CRR_CORP_CLASSES: tuple[str, ...] = ("corporate", "specialised_lending")
_CR7_B31_RETAIL_CLASSES: tuple[str, ...] = ("retail_mortgage", "retail_qrre", "retail_other")
_CR7_CRR_RETAIL_CLASSES: tuple[str, ...] = ("retail_other", "retail_qrre")


_Cr7Handler = Callable[[pl.DataFrame, pl.DataFrame, pl.DataFrame, str | None, str], float | None]


def _cr7_filter_in(
    frame: pl.DataFrame,
    ec_col: str | None,
    classes: tuple[str, ...],
) -> pl.DataFrame:
    """Filter ``frame`` to rows whose exposure_class is in ``classes``.

    Falls back to ``frame`` unchanged when no ``ec_col`` is available.
    """
    if not ec_col:
        return frame
    return frame.filter(pl.col(ec_col).is_in(list(classes)))


def _cr7_row_rwa(
    row_def: P3Row,
    *,
    framework: str,
    data: pl.DataFrame,
    firb: pl.DataFrame,
    airb: pl.DataFrame,
    slotting: pl.DataFrame,
    ec_col: str | None,
    approach_col: str,
    rwa_col: str,
) -> float | None:
    """Resolve the RWA total for a single CR7 row, dispatching by ref."""
    ref = row_def.ref
    is_b31 = framework == "BASEL_3_1"

    if ref == "1":
        return _col_sum(firb, rwa_col)
    if ref == "10" or row_def.is_total:
        return _col_sum(
            data.filter(pl.col(approach_col).is_in(list(_CR7_IRB_APPROACHES))),
            rwa_col,
        )
    if ref == "9":
        if not ec_col:
            return None
        return _col_sum(_cr7_filter_in(airb, ec_col, _CR7_CRR_RETAIL_CLASSES), rwa_col)

    handler = _CR7_HANDLERS_B31.get(ref) if is_b31 else _CR7_HANDLERS_CRR.get(ref)
    if handler is None:
        return None
    return handler(firb, airb, slotting, ec_col, rwa_col)


def _cr7_b31_ref2(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    if not ec_col:
        return None
    return _col_sum(firb.filter(pl.col(ec_col) == "institution"), rwa_col)


def _cr7_crr_ref2(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    if not ec_col:
        return None
    return _col_sum(firb.filter(pl.col(ec_col) == "central_govt_central_bank"), rwa_col)


def _cr7_b31_ref3(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    if not ec_col:
        return None
    return _col_sum(_cr7_filter_in(firb, ec_col, _CR7_B31_CORP_CLASSES), rwa_col)


def _cr7_crr_ref3(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    if not ec_col:
        return None
    return _col_sum(firb.filter(pl.col(ec_col) == "institution"), rwa_col)


def _cr7_b31_ref4(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(airb, rwa_col)


def _cr7_crr_ref4(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    subset = firb.filter(pl.col(ec_col) == "corporate_sme") if ec_col else firb
    return _col_sum(subset, rwa_col)


def _cr7_b31_ref5(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(_cr7_filter_in(airb, ec_col, _CR7_B31_CORP_CLASSES), rwa_col)


def _cr7_crr_ref5(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(_cr7_filter_in(firb, ec_col, _CR7_CRR_CORP_CLASSES), rwa_col)


def _cr7_b31_ref6(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(_cr7_filter_in(airb, ec_col, _CR7_B31_RETAIL_CLASSES), rwa_col)


def _cr7_crr_ref6(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(airb, rwa_col)


def _cr7_b31_ref7(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(slotting, rwa_col)


def _cr7_crr_ref7(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(_cr7_filter_in(airb, ec_col, _CR7_B31_CORP_CLASSES), rwa_col)


def _cr7_b31_ref8(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    subset = airb.filter(pl.col(ec_col) == "retail_mortgage") if ec_col else airb
    return _col_sum(subset, rwa_col)


def _cr7_crr_ref8(firb, airb, slotting, ec_col, rwa_col):  # noqa: ARG001
    return _col_sum(_cr7_filter_in(airb, ec_col, _CR7_CRR_RETAIL_CLASSES), rwa_col)


_CR7_HANDLERS_B31: dict[str, _Cr7Handler] = {
    "2": _cr7_b31_ref2,
    "3": _cr7_b31_ref3,
    "4": _cr7_b31_ref4,
    "5": _cr7_b31_ref5,
    "6": _cr7_b31_ref6,
    "7": _cr7_b31_ref7,
    "8": _cr7_b31_ref8,
}
_CR7_HANDLERS_CRR: dict[str, _Cr7Handler] = {
    "2": _cr7_crr_ref2,
    "3": _cr7_crr_ref3,
    "4": _cr7_crr_ref4,
    "5": _cr7_crr_ref5,
    "6": _cr7_crr_ref6,
    "7": _cr7_crr_ref7,
    "8": _cr7_crr_ref8,
}


# ---------------------------------------------------------------------------
# Per-template value computation
# ---------------------------------------------------------------------------


def _compute_cr4_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
) -> dict[str, object]:
    """Compute CR4 column values for a subset of SA exposures."""
    on_bs = _filter_on_bs(data, cols)
    off_bs = _filter_off_bs(data, cols)

    on_bs_pre = _safe_sum(on_bs, "drawn_amount", "interest") or 0.0
    off_bs_pre = _safe_sum(off_bs, "nominal_amount", "undrawn_amount") or 0.0
    on_bs_post = _col_sum(on_bs, ead_col) or 0.0
    off_bs_post = _col_sum(off_bs, ead_col) or 0.0
    rwa = _col_sum(data, rwa_col) or 0.0
    denominator = on_bs_post + off_bs_post

    return {
        "a": on_bs_pre,
        "b": off_bs_pre,
        "c": on_bs_post,
        "d": off_bs_post,
        "e": rwa,
        "f": rwa / denominator if denominator > 0 else None,
    }


def _cr5_row_predicate(
    row_def: P3Row,
    ec_col: str | None,
    role_col: str | None,
) -> pl.Expr | None:
    """Build the CR5 row membership predicate (or None if the row is inert).

    A row matches an exposure when its ``exposure_class`` is in the row's
    ``exposure_classes`` OR (Basel 3.1) its ``re_split_role`` is in the row's
    ``re_split_roles``. The role limb selects the 55%-LTV split legs (Art. 124F
    secured / Art. 124L residual) so the parent RE row reconciles to the
    un-split exposure and the 9f/9g "of which" sub-rows each pick one leg.
    """
    predicates: list[pl.Expr] = []
    if row_def.exposure_classes and ec_col:
        predicates.append(pl.col(ec_col).is_in(list(row_def.exposure_classes)))
    if row_def.re_split_roles and role_col:
        predicates.append(pl.col(role_col).is_in(list(row_def.re_split_roles)))
    if not predicates:
        return None
    combined = predicates[0]
    for extra in predicates[1:]:
        combined = combined | extra
    return combined


def _compute_cr5_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rw_col: str,
    rw_bands: list[tuple[float, str]],
    is_b31: bool,
) -> dict[str, object]:
    """Compute CR5 column values: EAD allocated to risk-weight buckets."""
    total_ead = _col_sum(data, ead_col) or 0.0
    allocated = 0.0
    values: dict[str, object] = {}

    # PRA PS1/26 Art. 123B: rows that fired the 1.5x currency-mismatch multiplier
    # are bucketed on their pre-multiplier risk weight so EAD lands in the
    # underlying credit-risk band rather than an inflated one. Frames without the
    # snapshot/flag columns (CRR, or older callers) bucket on rw_col exactly as
    # before.
    if (
        "risk_weight_pre_currency_mismatch" in data.columns
        and "currency_mismatch_multiplier_applied" in data.columns
    ):
        rw_bucket_expr = (
            pl.when(pl.col("currency_mismatch_multiplier_applied").fill_null(False))
            .then(pl.col("risk_weight_pre_currency_mismatch"))
            .otherwise(pl.col(rw_col))
        )
    else:
        rw_bucket_expr = pl.col(rw_col)

    for i, (rw_value, _label) in enumerate(rw_bands):
        ref = _letter_ref(i)
        # Filter to ±0.5pp tolerance for risk weight match
        tol = 0.005
        bucket = data.filter((rw_bucket_expr >= rw_value - tol) & (rw_bucket_expr < rw_value + tol))
        bucket_ead = _col_sum(bucket, ead_col) or 0.0
        values[ref] = bucket_ead
        allocated += bucket_ead

    n = len(rw_bands)
    # Residual bucket: total EAD minus all allocated bands
    values[_letter_ref(n)] = max(0.0, total_ead - allocated)
    # Total
    values[_letter_ref(n + 1)] = total_ead
    # Unrated
    if "sa_cqs" in data.columns:
        unrated = data.filter(pl.col("sa_cqs").is_null())
        values[_letter_ref(n + 2)] = _col_sum(unrated, ead_col)
    else:
        values[_letter_ref(n + 2)] = total_ead  # All unrated

    if is_b31:
        on_bs = _filter_on_bs(data, cols)
        off_bs = _filter_off_bs(data, cols)
        on_bs_ead = _safe_sum(on_bs, "drawn_amount", "interest")
        off_bs_ead = _safe_sum(off_bs, "nominal_amount", "undrawn_amount")
        ccf_col = _pick(cols, "ccf")
        avg_ccf = _ead_weighted_avg(off_bs, ead_col, ccf_col) if ccf_col else None
        values["ba"] = on_bs_ead
        values["bb"] = off_bs_ead
        values["bc"] = avg_ccf
        values["bd"] = total_ead

    return values


def _compute_cr6_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_col: str,
) -> dict[str, object]:
    """Compute CR6 column values for a PD-range bucket of IRB exposures."""
    if data.height == 0:
        return {}

    on_bs = _filter_on_bs(data, cols)
    off_bs = _filter_off_bs(data, cols)
    lgd_col = _pick(cols, "lgd_floored", "lgd_input")
    maturity_col = _pick(cols, "irb_maturity_m")
    el_col = _pick(cols, "expected_loss")
    ccf_col = _pick(cols, "ccf")
    prov_col = _pick(cols, "scra_provision_amount", "provision_held")

    ead_sum = _col_sum(data, ead_col) or 0.0
    rwa_sum = _col_sum(data, rwa_col) or 0.0

    values: dict[str, object] = {
        "b": _safe_sum(on_bs, "drawn_amount", "interest"),
        "c": _safe_sum(off_bs, "nominal_amount", "undrawn_amount"),
        "d": _ead_weighted_avg(off_bs, ead_col, ccf_col),
        "e": ead_sum,
        "f": _ead_weighted_avg(data, ead_col, pd_col),
        "g": _obligor_count(data, cols),
        "h": _ead_weighted_avg(data, ead_col, lgd_col),
        "i": _ead_weighted_avg(data, ead_col, maturity_col),
        "j": rwa_sum,
        "k": rwa_sum / ead_sum if ead_sum > 0 else None,
        "l": _col_sum(data, el_col),
        "m": _col_sum(data, prov_col),
    }

    # Convert PD/LGD to percentage for display
    if values.get("f") is not None:
        values["f"] = float(cast("float", values["f"])) * 100.0
    if values.get("h") is not None:
        values["h"] = float(cast("float", values["h"])) * 100.0

    return values


def _cr9_class_predicate(spec: CR9ClassSpec, ec_col: str, cols: set[str]) -> pl.Expr:
    """Resolve a CR9 leaf-class descriptor into a row-filter ``pl.Expr``.

    Builds the predicate over ``exposure_class`` plus the optional discriminator
    columns (``is_sme``, ``property_type``, ``cp_is_financial_sector_entity``).
    Degrades gracefully when a discriminator column is absent on the frame: the
    corresponding clause is dropped, so a generic corporate leaf with absent
    flags still matches (the residual ``corporate`` rows collapse onto
    ``corporate_other_non_sme`` for the financial/large split).

    References:
        PRA PS1/26 Annex XXII, Art. 147(2)(b)-(d), 147A.
    """
    predicate = pl.col(ec_col).is_in(list(spec.exposure_classes))

    if spec.is_sme is not None:
        sme_col = _pick(cols, "is_sme")
        if sme_col:
            predicate = predicate & (pl.col(sme_col) == spec.is_sme)

    if spec.property_type is not None:
        prop_col = _pick(cols, "property_type")
        if prop_col:
            predicate = predicate & (pl.col(prop_col) == spec.property_type)

    if spec.financial_large is not None:
        fin_col = _pick(cols, "cp_is_financial_sector_entity")
        if fin_col:
            flag = pl.col(fin_col).fill_null(False)
            predicate = predicate & (flag == spec.financial_large)
        elif spec.financial_large:
            # Discriminator absent: no row can be financial/large, so the
            # residual corporate rows fall through to the non-SME leaf.
            predicate = pl.lit(value=False)

    return predicate


def _cr9_schema(column_refs: list[str]) -> dict[str, PolarsDataType]:
    """Schema for CR9 frames: a/b are String, remaining cols Float64."""
    schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
    for ref in column_refs:
        schema[ref] = pl.String if ref in ("a", "b") else pl.Float64
    return schema


def _cr9_empty_schema(column_refs: list[str]) -> pl.DataFrame:
    """Empty CR9 frame with the correct schema."""
    return pl.DataFrame([], schema=_cr9_schema(column_refs))


def _cr9_1_schema(column_refs: list[str], grade_col: str) -> dict[str, PolarsDataType]:
    """Schema for CR9.1 frames: a/b/grade are String, remaining cols Float64."""
    schema = _cr9_schema(column_refs)
    schema[grade_col] = pl.String
    return schema


def _cr9_bucket_row(
    class_data: pl.DataFrame,
    cols: set[str],
    alloc_pd_col: str,
    report_pd_col: str,
    class_display: str,
    lower: float,
    upper: float,
    label: str,
    row_ref: str,
    column_refs: list[str],
) -> dict[str, object] | None:
    """Build a single CR9 PD-bucket row, or None when the bucket is empty."""
    if math.isinf(upper):
        bucket = class_data.filter(pl.col(alloc_pd_col) >= lower)
    else:
        bucket = class_data.filter((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
    if bucket.height == 0:
        return None
    values = _compute_cr9_values(bucket, cols, report_pd_col)
    values["a"] = class_display
    values["b"] = label
    return _make_row(P3Row(row_ref, label), values, column_refs)


def _cr9_total_row(
    class_data: pl.DataFrame,
    cols: set[str],
    report_pd_col: str,
    class_display: str,
    column_refs: list[str],
) -> dict[str, object]:
    """Build the CR9 total row for an exposure class."""
    total_values = _compute_cr9_values(class_data, cols, report_pd_col)
    total_values["a"] = class_display
    total_values["b"] = "Total"
    return _make_row(P3Row("18", "Total", is_total=True), total_values, column_refs)


def _compute_cr9_values(
    data: pl.DataFrame,
    cols: set[str],
    pd_col: str,
) -> dict[str, object]:
    """Compute CR9 column values for a PD-range bucket.

    Columns:
        a — Exposure class (set by caller)
        b — PD range label (set by caller)
        c — Number of obligors at end of previous year
        d — Of which: defaulted during the year
        e — Observed average default rate (%)
        f — Exposure-weighted average PD (%) — post input floor
        g — Average PD at disclosure date (%) — post input floor
        h — Average historical annual default rate (%)

    References:
        PRA PS1/26 Art. 452(h), Annex XXII paras 12-15
    """
    if data.height == 0:
        return {}

    n_rows = data.height
    cp_col = "counterparty_reference" if "counterparty_reference" in data.columns else None
    n_obligors = _cr9_obligor_count(data, cp_col, n_rows)
    n_defaults = _cr9_default_count(data, cols, pd_col, cp_col)
    prior_obligors = _cr9_prior_obligor_count(data, cols, n_obligors)
    observed_rate = (n_defaults / n_obligors * 100.0) if n_obligors > 0 else 0.0

    return {
        "c": prior_obligors,
        "d": n_defaults,
        "e": observed_rate,
        "f": _cr9_ewa_pd_pct(data, cols, pd_col),
        "g": _cr9_avg_pd_pct(data, pd_col),
        "h": _cr9_hist_rate_pct(data, cols, observed_rate, n_rows),
    }


def _cr9_obligor_count(data: pl.DataFrame, cp_col: str | None, n_rows: int) -> float:
    """Unique-obligor count when available, else row count."""
    if cp_col:
        return float(data.select(pl.col(cp_col).n_unique()).item())
    return float(n_rows)


def _cr9_default_count(
    data: pl.DataFrame,
    cols: set[str],
    pd_col: str,
    cp_col: str | None,
) -> float:
    """Count of defaulted obligors. Prefers ``is_defaulted``; falls back to PD>=1.0."""
    default_col = _pick(cols, "is_defaulted")
    if default_col and default_col in data.columns:
        defaulted = data.filter(pl.col(default_col) == True)  # noqa: E712
    elif pd_col in data.columns:
        defaulted = data.filter(pl.col(pd_col) >= 1.0)
    else:
        return 0.0
    if cp_col and defaulted.height > 0:
        return float(defaulted.select(pl.col(cp_col).n_unique()).item())
    return float(defaulted.height)


def _cr9_prior_obligor_count(
    data: pl.DataFrame,
    cols: set[str],
    n_obligors: float,
) -> float:
    """Prior-year obligor count when the column exists, else current period."""
    prior_col = _pick(cols, "prior_year_obligor_count")
    if prior_col and prior_col in data.columns:
        return float(data.select(pl.col(prior_col).fill_null(0.0).sum()).item())
    return n_obligors


def _cr9_ewa_pd_pct(
    data: pl.DataFrame,
    cols: set[str],
    pd_col: str,
) -> float | None:
    """Col f: exposure-weighted average PD (%), with arithmetic-mean fallback."""
    ead_col = _pick(cols, "ead_final")
    if ead_col and ead_col in data.columns and pd_col in data.columns:
        ewa_pd = _ead_weighted_avg(data, ead_col, pd_col)
        return float(ewa_pd) * 100.0 if ewa_pd is not None else None
    if pd_col in data.columns:
        avg_pd = data.select(pl.col(pd_col).mean()).item()
        return float(avg_pd) * 100.0 if avg_pd is not None else None
    return None


def _cr9_avg_pd_pct(data: pl.DataFrame, pd_col: str) -> float | None:
    """Col g: arithmetic average PD at disclosure date (%)."""
    if pd_col not in data.columns:
        return None
    avg = data.select(pl.col(pd_col).mean()).item()
    return float(avg) * 100.0 if avg is not None else None


def _cr9_hist_rate_pct(
    data: pl.DataFrame,
    cols: set[str],
    observed_rate: float,
    n_rows: int,
) -> float | None:
    """Col h: historical annual default rate (%), with current-period fallback."""
    hist_col = _pick(cols, "historical_annual_default_rate")
    if hist_col and hist_col in data.columns and n_rows > 0:
        hist_rate = data.select(pl.col(hist_col).fill_null(0.0).mean()).item()
        return float(hist_rate) * 100.0 if hist_rate is not None else None
    return observed_rate


def _compute_cr7a_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
) -> dict[str, object]:
    """Compute CR7-A column values for a filtered IRB subset."""
    total_ead = _col_sum(data, ead_col) or 0.0

    def _pct(col_name: str | None) -> float | None:
        if not col_name or col_name not in data.columns or total_ead == 0:
            return None
        val = _col_sum(data, col_name) or 0.0
        return val / total_ead * 100.0

    values: dict[str, object] = {
        "a": total_ead,
        "b": _pct(_pick(cols, "collateral_financial_value")),
        "d": _pct(_pick(cols, "collateral_re_value")),
        "e": _pct(_pick(cols, "collateral_receivables_value")),
        "f": _pct(_pick(cols, "collateral_other_physical_value")),
        "h": None,  # Cash on deposit — not separately tracked
        "i": None,  # Life insurance — not separately tracked
        "j": None,  # Instruments held by third party — not separately tracked
        "k": _pct(_pick(cols, "guaranteed_portion")),
        "m": _col_sum(data, _pick(cols, "rwa_final", "rwa")),
        "n": _col_sum(data, _pick(cols, "rwa_final", "rwa")),
    }

    # c = sum of d + e + f
    d_val = float(cast("float", values.get("d") or 0.0))
    e_val = float(cast("float", values.get("e") or 0.0))
    f_val = float(cast("float", values.get("f") or 0.0))
    values["c"] = d_val + e_val + f_val if (d_val or e_val or f_val) else None

    # g = sum of h + i + j
    values["g"] = None  # sub-categories not tracked

    # l = credit derivatives %
    values["l"] = None  # Not separately tracked from guarantees

    # o, p for B31 slotting — always None for F-IRB/A-IRB
    values["o"] = None
    values["p"] = None

    return values


def _cr10_type_data(
    data: pl.DataFrame,
    sl_type_col: str | None,
    sl_key: str,
    framework: str,
) -> pl.DataFrame:
    """Subset slotting data for a given subtemplate key.

    CRR groups IPRE with HVCRE; Basel 3.1 keeps them separate.
    """
    if not sl_type_col:
        return data.filter(pl.lit(False))
    if sl_key == "ipre" and framework != "BASEL_3_1":
        return data.filter(pl.col(sl_type_col).is_in(["ipre", "hvcre"]))
    return data.filter(pl.col(sl_type_col) == sl_key)


def _cr10_rw_map_for(sl_key: str) -> dict[str, float]:
    """Risk-weight lookup table for a CR10 subtemplate key."""
    return HVCRE_RISK_WEIGHTS if sl_key == "hvcre" else SLOTTING_RISK_WEIGHTS


def _cr10_row_subset(
    row_def: P3Row,
    type_data: pl.DataFrame,
    cat_col: str | None,
    rw_map: dict[str, float],
) -> tuple[pl.DataFrame, float | None] | None:
    """Return (subset, rw_value) for a CR10 row, or None to emit a null row."""
    if row_def.is_total:
        return type_data, None
    if not cat_col:
        return None
    pipeline_cat = CR10_CATEGORY_MAP.get(row_def.name)
    if not pipeline_cat:
        return None
    subset = type_data.filter(pl.col(cat_col) == pipeline_cat)
    return subset, rw_map.get(pipeline_cat)


def _compute_cr10_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    el_col: str | None,
    rw_value: float | None,
) -> dict[str, object]:
    """Compute CR10 column values for a slotting category."""
    on_bs = _filter_on_bs(data, cols)
    off_bs = _filter_off_bs(data, cols)

    return {
        "a": _safe_sum(on_bs, "drawn_amount", "interest"),
        "b": _safe_sum(off_bs, "nominal_amount", "undrawn_amount"),
        "c": rw_value * 100.0 if rw_value is not None else None,
        "d": _col_sum(data, ead_col),
        "e": _col_sum(data, rwa_col),
        "f": _col_sum(data, el_col) if el_col else None,
    }


# ---------------------------------------------------------------------------
# CMS2 row helpers
# ---------------------------------------------------------------------------


_CMS2_SUBROW_NULL_REFS: frozenset[str] = frozenset({"0044", "0045", "0054"})


def _cms2_row_values(
    row_def: P3Row,
    *,
    modelled_data: pl.DataFrame,
    sa_collected: pl.DataFrame,
    all_data: pl.DataFrame,
    ec_col: str | None,
    approach_col: str | None,
    rwa_col: str,
    sa_rwa_col: str | None,
) -> dict[str, object]:
    """Compute CMS2 column values for a single row, dispatching by ref."""
    if row_def.is_total:
        return _cms2_total_row(modelled_data, sa_collected, all_data, rwa_col, sa_rwa_col)
    if row_def.ref == "0041" and ec_col and approach_col:
        return _cms2_firb_row(
            modelled_data, sa_collected, all_data, ec_col, approach_col, rwa_col, sa_rwa_col
        )
    if row_def.ref == "0042" and ec_col and approach_col:
        return _cms2_airb_row(modelled_data, ec_col, approach_col, rwa_col, sa_rwa_col)
    if row_def.ref in _CMS2_SUBROW_NULL_REFS:
        # 0044 IPRE/HVCRE, 0045 purchased receivables (corp),
        # 0054 purchased receivables (retail) — pipeline data not available.
        return {"a": None, "b": None, "c": None, "d": None}
    if row_def.exposure_classes and ec_col:
        return _cms2_class_row(
            row_def, modelled_data, sa_collected, all_data, ec_col, rwa_col, sa_rwa_col
        )
    return {"a": None, "b": None, "c": None, "d": None}


def _cms2_total_row(
    modelled_data: pl.DataFrame,
    sa_collected: pl.DataFrame,
    all_data: pl.DataFrame,
    rwa_col: str,
    sa_rwa_col: str | None,
) -> dict[str, object]:
    """CMS2 total row: sum across all credit risk exposures."""
    modelled_rwa = _col_sum(modelled_data, rwa_col)
    sa_port_rwa = _col_sum(sa_collected, rwa_col) or 0.0
    return {
        "a": modelled_rwa,
        "b": _col_sum(modelled_data, sa_rwa_col) if sa_rwa_col else None,
        "c": (modelled_rwa or 0.0) + sa_port_rwa,
        "d": _col_sum(all_data, sa_rwa_col) if sa_rwa_col else None,
    }


def _cms2_firb_row(
    modelled_data: pl.DataFrame,
    sa_collected: pl.DataFrame,
    all_data: pl.DataFrame,
    ec_col: str,
    approach_col: str,
    rwa_col: str,
    sa_rwa_col: str | None,
) -> dict[str, object]:
    """Row 0041: 'Of which are FIRB' — corporate exposures under F-IRB."""
    corp_classes = list(CMS2_SA_CLASS_MAP.get("0040", ()))
    firb_corp = modelled_data.filter(
        pl.col(ec_col).is_in(corp_classes) & (pl.col(approach_col) == "foundation_irb")
    )
    a_val = _col_sum(firb_corp, rwa_col)
    sa_firb = sa_collected.filter(pl.col(ec_col).is_in(corp_classes))
    return {
        "a": a_val,
        "b": _col_sum(firb_corp, sa_rwa_col) if sa_rwa_col else None,
        "c": (a_val or 0.0) + (_col_sum(sa_firb, rwa_col) or 0.0),
        "d": (
            _col_sum(all_data.filter(pl.col(ec_col).is_in(corp_classes)), sa_rwa_col)
            if sa_rwa_col
            else None
        ),
    }


def _cms2_airb_row(
    modelled_data: pl.DataFrame,
    ec_col: str,
    approach_col: str,
    rwa_col: str,
    sa_rwa_col: str | None,
) -> dict[str, object]:
    """Row 0042: 'Of which are AIRB' — corporate exposures under A-IRB."""
    corp_classes = list(CMS2_SA_CLASS_MAP.get("0040", ()))
    airb_corp = modelled_data.filter(
        pl.col(ec_col).is_in(corp_classes) & (pl.col(approach_col) == "advanced_irb")
    )
    a_val = _col_sum(airb_corp, rwa_col)
    # Sub-row pattern: c mirrors a (no SA portfolio add); d compared at parent level.
    return {
        "a": a_val,
        "b": _col_sum(airb_corp, sa_rwa_col) if sa_rwa_col else None,
        "c": a_val,
        "d": None,
    }


def _cms2_class_row(
    row_def: P3Row,
    modelled_data: pl.DataFrame,
    sa_collected: pl.DataFrame,
    all_data: pl.DataFrame,
    ec_col: str,
    rwa_col: str,
    sa_rwa_col: str | None,
) -> dict[str, object]:
    """Standard CMS2 asset-class row driven by ``row_def.exposure_classes``."""
    ec_list = list(row_def.exposure_classes or ())
    class_modelled = modelled_data.filter(pl.col(ec_col).is_in(ec_list))
    a_val = _col_sum(class_modelled, rwa_col)

    class_sa = sa_collected.filter(pl.col(ec_col).is_in(ec_list))
    sa_port_rwa = _col_sum(class_sa, rwa_col) or 0.0

    sa_classes = CMS2_SA_CLASS_MAP.get(row_def.ref, ec_list)
    class_all = all_data.filter(pl.col(ec_col).is_in(list(sa_classes)))

    return {
        "a": a_val,
        "b": _col_sum(class_modelled, sa_rwa_col) if sa_rwa_col else None,
        "c": (a_val or 0.0) + sa_port_rwa,
        "d": _col_sum(class_all, sa_rwa_col) if sa_rwa_col else None,
    }


def _cr9_display_names(cr9_dict: dict[str, pl.DataFrame]) -> dict[str, str]:
    """Build display names for CR9 Excel sheets from composite keys.

    Keys are ``"{approach} - {class_key}"`` — display name uses approach
    abbreviation and human-readable class name.
    """
    display: dict[str, str] = {}
    for key in cr9_dict:
        parts = key.split(" - ", 1)
        approach = CR9_APPROACH_DISPLAY.get(parts[0], parts[0]) if len(parts) > 1 else key
        class_name = IRB_EXPOSURE_CLASSES.get(parts[1], parts[1]) if len(parts) > 1 else ""
        display[key] = f"{approach} {class_name}" if class_name else approach
    return display


def _ratio_for_ref(
    overrides: Pillar3CapitalRatioOverrides | None,
    ref: str,
) -> Decimal | None:
    """Look up the OV1 pre-floor capital ratio for a row ref.

    Maps OV1 row refs (5a/5b/6a/6b/7a/7b) to the matching field on the
    Pillar3CapitalRatioOverrides bundle. Returns None when no overrides
    were supplied or the matching field is None.
    """
    if overrides is None:
        return None
    mapping: dict[str, Decimal | None] = {
        "5a": overrides.cet1_ratio_pre_floor,
        "5b": overrides.cet1_ratio_pre_floor_transitional,
        "6a": overrides.tier1_ratio_pre_floor,
        "6b": overrides.tier1_ratio_pre_floor_transitional,
        "7a": overrides.total_ratio_pre_floor,
        "7b": overrides.total_ratio_pre_floor_transitional,
    }
    return mapping.get(ref)


def _obligor_count(data: pl.DataFrame, cols: set[str]) -> float | None:
    """Count unique obligors (counterparty references) in a dataset."""
    cp_col = _pick(cols, "counterparty_reference")
    if not cp_col or cp_col not in data.columns:
        return None
    return float(data.select(pl.col(cp_col).n_unique()).item())


# ---------------------------------------------------------------------------
# Excel sheet-writing helpers
# ---------------------------------------------------------------------------


def _sanitise_sheet_name(name: str) -> str:
    """Sanitise a string for use as an Excel sheet name."""
    return re.sub(r"[\[\]:*?/\\]", "", name)[:31]


def _write_single_sheet(workbook: Workbook, df: pl.DataFrame, name: str) -> int:
    """Write a single DataFrame to a workbook sheet. Returns row count."""
    sheet = _sanitise_sheet_name(name)
    df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
    return df.height


def _write_dict_sheets(
    workbook: Workbook,
    templates: dict[str, pl.DataFrame],
    prefix: str,
    display_names: dict[str, str],
) -> int:
    """Write per-class/type templates to workbook sheets. Returns total rows."""
    total = 0
    for key in sorted(templates):
        df = templates[key]
        if df.height == 0:
            continue
        display = display_names.get(key, key)
        sheet = _sanitise_sheet_name(f"{prefix} - {display}")
        df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
        total += df.height
    return total
