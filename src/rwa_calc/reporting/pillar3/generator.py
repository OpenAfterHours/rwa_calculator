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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.pillar3.templates import (
    CMS1_COLUMNS,
    CMS1_ROWS,
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
    CR10_CATEGORY_MAP,
    CR10_SLOTTING_ROWS,
    CR6A_COLUMNS,
    CR6_PD_RANGES,
    CR7_COLUMNS,
    CR8_COLUMNS,
    CR8_ROWS,
    CR9_AIRB_CLASSES,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMN_REFS,
    CR9_COLUMNS,
    CR9_FIRB_CLASSES,
    HVCRE_RISK_WEIGHTS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    SA_DISCLOSURE_CLASSES,
    SLOTTING_RISK_WEIGHTS,
    P3Column,
    P3Row,
    _letter_ref,
    get_cr10_columns,
    get_cr10_subtemplates,
    get_cr4_columns,
    get_cr4_rows,
    get_cr5_columns,
    get_cr5_risk_weights,
    get_cr5_rows,
    get_cr6_columns,
    get_cr6a_rows,
    get_cr7_rows,
    get_cr7a_columns,
    get_ov1_rows,
)

if TYPE_CHECKING:
    from rwa_calc.api.export import ExportResult
    from rwa_calc.api.service import CalculationResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pillar3TemplateBundle:
    """Bundle of all Pillar III disclosure DataFrames.

    Single-table templates are ``pl.DataFrame | None``.
    Per-class/type templates are ``dict[str, pl.DataFrame]``.
    CMS1/CMS2/CR9 are Basel 3.1 only — None/empty under CRR.
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

    def generate(self, response: CalculationResponse) -> Pillar3TemplateBundle:
        """Generate all Pillar III templates from a ``CalculationResponse``."""
        results_lf = response.scan_results()
        return self.generate_from_lazyframe(results_lf, framework=response.framework)

    def generate_from_lazyframe(
        self,
        results: pl.LazyFrame,
        *,
        framework: str = "CRR",
    ) -> Pillar3TemplateBundle:
        """Generate all Pillar III templates from a pipeline results LazyFrame."""
        cols = _available_columns(results)
        errors: list[str] = []

        sa_data = _filter_by_approach(results, "standardised", cols)
        irb_data = _filter_irb_non_slotting(results, cols)
        slotting_data = _filter_by_approach(results, "slotting", cols)

        return Pillar3TemplateBundle(
            ov1=self._generate_ov1(results, cols, framework, errors),
            cr4=self._generate_cr4(sa_data, cols, framework, errors),
            cr5=self._generate_cr5(sa_data, cols, framework, errors),
            cr6=self._generate_all_cr6(irb_data, cols, framework, errors),
            cr6a=self._generate_cr6a(results, cols, framework, errors),
            cr7=self._generate_cr7(results, cols, framework, errors),
            cr7a=self._generate_all_cr7a(results, cols, framework, errors),
            cr8=self._generate_cr8(irb_data, cols, framework, errors),
            cr9=self._generate_all_cr9(irb_data, cols, framework, errors),
            cr10=self._generate_all_cr10(slotting_data, cols, framework, errors),
            cms1=self._generate_cms1(results, cols, framework, errors),
            cms2=self._generate_cms2(results, sa_data, irb_data, slotting_data,
                                     cols, framework, errors),
            framework=framework,
            errors=errors,
        )

    def export_to_excel(
        self,
        bundle: Pillar3TemplateBundle,
        output_path: Path,
    ) -> ExportResult:
        """Write Pillar III templates to an Excel workbook."""
        from rwa_calc.api.export import ExportResult

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
                total_rows += _write_single_sheet(
                    workbook, bundle.ov1, f"{prefix} OV1"
                )
            if bundle.cr4 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr4, f"{prefix} CR4"
                )
            if bundle.cr5 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr5, f"{prefix} CR5"
                )
            total_rows += _write_dict_sheets(
                workbook, bundle.cr6, f"{prefix} CR6", IRB_EXPOSURE_CLASSES
            )
            if bundle.cr6a is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr6a, f"{prefix} CR6-A"
                )
            if bundle.cr7 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr7, f"{prefix} CR7"
                )
            total_rows += _write_dict_sheets(
                workbook,
                bundle.cr7a,
                f"{prefix} CR7-A",
                {"foundation_irb": "F-IRB", "advanced_irb": "A-IRB"},
            )
            if bundle.cr8 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr8, f"{prefix} CR8"
                )
            if bundle.cr9:
                cr9_display = _cr9_display_names(bundle.cr9)
                total_rows += _write_dict_sheets(
                    workbook, bundle.cr9, f"{prefix} CR9", cr9_display
                )
            subtemplates = get_cr10_subtemplates(bundle.framework)
            total_rows += _write_dict_sheets(
                workbook, bundle.cr10, f"{prefix} CR10", subtemplates
            )
            if bundle.cms1 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cms1, f"{prefix} CMS1"
                )
            if bundle.cms2 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cms2, f"{prefix} CMS2"
                )
        finally:
            workbook.close()

        return ExportResult(
            format="pillar3_excel", files=[output_path], row_count=total_rows
        )

    # ---- OV1 ----

    def _generate_ov1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
        if not rwa_col:
            errors.append("OV1: missing RWA column")
            return None

        approach_col = _pick(cols, "approach_applied", "approach")
        data = results.collect()
        rows_out: list[dict[str, object]] = []
        column_refs = [c.ref for c in OV1_COLUMNS]

        total_rwa = _col_sum(data, cols, rwa_col)
        own_funds = total_rwa * 0.08 if total_rwa else None

        for row_def in get_ov1_rows(framework):
            values: dict[str, object] = {}
            ref = row_def.ref

            if ref == "29":
                values["a"] = total_rwa
                values["c"] = own_funds
            elif ref == "1":
                values["a"] = total_rwa
                values["c"] = own_funds
            elif ref == "2" and approach_col:
                sa_rwa = _approach_rwa(data, approach_col, rwa_col, "standardised")
                eq_rwa = _approach_rwa(data, approach_col, rwa_col, "equity")
                values["a"] = (sa_rwa or 0.0) + (eq_rwa or 0.0)
            elif ref == "3" and approach_col:
                values["a"] = _approach_rwa(data, approach_col, rwa_col, "foundation_irb")
            elif ref == "4" and approach_col:
                values["a"] = _approach_rwa(data, approach_col, rwa_col, "slotting")
            elif ref == "UK4a" and approach_col:
                values["a"] = _approach_rwa(data, approach_col, rwa_col, "equity")
            elif ref == "5" and approach_col:
                values["a"] = _approach_rwa(data, approach_col, rwa_col, "advanced_irb")
            elif ref == "24":
                # Memo: 250% RW exposures — filter to risk_weight == 2.50
                rw_col = _pick(cols, "risk_weight", "sa_final_risk_weight")
                if rw_col:
                    memo = data.filter(
                        (pl.col(rw_col) >= 2.495) & (pl.col(rw_col) <= 2.505)
                    )
                    values["a"] = _col_sum(memo, cols, rwa_col)
            elif ref == "26":
                # Output floor multiplier — from config, not pipeline data
                values["a"] = None
            elif ref == "27":
                # Output floor adjustment — from config
                values["a"] = None
            elif ref in ("11", "12", "13", "14"):
                # Equity sub-rows — pipeline equity data not granular enough
                values["a"] = None

            # Column b (T-1) always None — requires prior period data
            values.setdefault("b", None)
            if values.get("a") is not None and values.get("c") is None:
                values["c"] = (values["a"] or 0.0) * 0.08

            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR4 ----

    def _generate_cr4(
        self,
        sa_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
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
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rw_col = _pick(cols, "risk_weight", "sa_final_risk_weight")
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
        rows_out: list[dict[str, object]] = []

        for row_def in cr5_rows:
            if row_def.is_total:
                subset = data
            elif row_def.exposure_classes and ec_col:
                subset = data.filter(pl.col(ec_col).is_in(list(row_def.exposure_classes)))
            else:
                rows_out.append(_null_row(row_def, column_refs))
                continue

            values = _compute_cr5_values(
                subset, cols, ead_col, rw_col, rw_bands, is_b31
            )
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
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
        ec_col = _pick(cols, "exposure_class")
        if not ead_col or not rwa_col or not ec_col:
            errors.append("CR6: missing required columns")
            return {}

        data = irb_data.collect()
        if data.height == 0:
            return {}

        is_b31 = framework == "BASEL_3_1"
        alloc_pd_col = _pick(cols, "irb_pd_original") if is_b31 else None
        report_pd_col = _pick(cols, "irb_pd_floored")
        pd_col = alloc_pd_col or report_pd_col or _pick(cols, "irb_pd_floored")

        if not pd_col:
            errors.append("CR6: missing PD column")
            return {}

        result: dict[str, pl.DataFrame] = {}
        for ec_val in data[ec_col].unique().to_list():
            if ec_val not in IRB_EXPOSURE_CLASSES:
                continue
            class_data = data.filter(pl.col(ec_col) == ec_val)
            result[ec_val] = self._generate_cr6_for_class(
                class_data, cols, ead_col, rwa_col,
                pd_col, report_pd_col or pd_col, framework,
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
            if upper == float("inf"):
                bucket = class_data.filter(pl.col(alloc_pd_col) >= lower)
            else:
                bucket = class_data.filter(
                    (pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper)
                )

            values = _compute_cr6_values(
                bucket, cols, ead_col, rwa_col, report_pd_col
            )
            values["a"] = label
            row = P3Row(row_ref, label)
            rows_out.append(_make_row(row, values, column_refs))

        # Total row
        total_values = _compute_cr6_values(
            class_data, cols, ead_col, rwa_col, report_pd_col
        )
        total_values["a"] = "Total"
        rows_out.append(
            _make_row(P3Row("18", "Total", is_total=True), total_values, column_refs)
        )

        # Build with mixed types: col "a" is String, rest Float64
        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
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
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
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
                subset = data.filter(
                    pl.col(ec_col).is_in(list(row_def.exposure_classes))
                )
            else:
                rows_out.append(_null_row(row_def, column_refs))
                continue

            total_ead = _col_sum(subset, cols, ead_col) or 0.0
            irb_subset = subset.filter(pl.col(approach_col).is_in(list(irb_approaches)))
            irb_ead = _col_sum(irb_subset, cols, ead_col) or 0.0
            sa_subset = subset.filter(~pl.col(approach_col).is_in(list(irb_approaches)))
            sa_ead = _col_sum(sa_subset, cols, ead_col) or 0.0

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
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
        approach_col = _pick(cols, "approach_applied", "approach")
        ec_col = _pick(cols, "exposure_class")
        if not rwa_col or not approach_col:
            errors.append("CR7: missing required columns")
            return None

        data = results.collect()
        cr7_rows = get_cr7_rows(framework)
        column_refs = [c.ref for c in CR7_COLUMNS]
        rows_out: list[dict[str, object]] = []

        firb = data.filter(pl.col(approach_col) == "foundation_irb")
        airb = data.filter(pl.col(approach_col) == "advanced_irb")
        slotting = data.filter(pl.col(approach_col) == "slotting")

        for row_def in cr7_rows:
            ref = row_def.ref
            # Pre-CD RWEA approximation = post-CD RWEA (pre-CD tracking not available)
            if ref == "1":
                rwa = _col_sum(firb, cols, rwa_col)
            elif ref == "2" and ec_col:
                if framework == "BASEL_3_1":
                    rwa = _col_sum(
                        firb.filter(pl.col(ec_col) == "institution"), cols, rwa_col
                    )
                else:
                    rwa = _col_sum(
                        firb.filter(pl.col(ec_col) == "central_govt_central_bank"),
                        cols, rwa_col,
                    )
            elif ref == "3" and ec_col:
                if framework == "BASEL_3_1":
                    rwa = _col_sum(
                        firb.filter(
                            pl.col(ec_col).is_in(
                                ["corporate", "corporate_sme", "specialised_lending"]
                            )
                        ),
                        cols, rwa_col,
                    )
                else:
                    rwa = _col_sum(
                        firb.filter(pl.col(ec_col) == "institution"), cols, rwa_col
                    )
            elif ref == "4":
                if framework == "BASEL_3_1":
                    rwa = _col_sum(airb, cols, rwa_col)
                else:
                    rwa = _col_sum(
                        firb.filter(
                            pl.col(ec_col) == "corporate_sme"
                        ) if ec_col else firb,
                        cols, rwa_col,
                    )
            elif ref == "5":
                if framework == "BASEL_3_1":
                    rwa = _col_sum(
                        airb.filter(
                            pl.col(ec_col).is_in(
                                ["corporate", "corporate_sme", "specialised_lending"]
                            )
                        ) if ec_col else airb,
                        cols, rwa_col,
                    )
                else:
                    rwa = _col_sum(
                        firb.filter(
                            pl.col(ec_col).is_in(
                                ["corporate", "specialised_lending"]
                            )
                        ) if ec_col else firb,
                        cols, rwa_col,
                    )
            elif ref == "6":
                if framework == "BASEL_3_1":
                    rwa = _col_sum(
                        airb.filter(
                            pl.col(ec_col).is_in(
                                ["retail_mortgage", "retail_qrre", "retail_other"]
                            )
                        ) if ec_col else airb,
                        cols, rwa_col,
                    )
                else:
                    rwa = _col_sum(airb, cols, rwa_col)
            elif ref == "7":
                if framework == "BASEL_3_1":
                    rwa = _col_sum(slotting, cols, rwa_col)
                else:
                    rwa = _col_sum(
                        airb.filter(
                            pl.col(ec_col).is_in(
                                ["corporate", "corporate_sme", "specialised_lending"]
                            )
                        ) if ec_col else airb,
                        cols, rwa_col,
                    )
            elif ref == "8":
                if framework == "BASEL_3_1":
                    rwa = _col_sum(
                        airb.filter(
                            pl.col(ec_col) == "retail_mortgage"
                        ) if ec_col else airb,
                        cols, rwa_col,
                    )
                else:
                    rwa = _col_sum(
                        airb.filter(
                            pl.col(ec_col).is_in(
                                ["retail_other", "retail_qrre"]
                            )
                        ) if ec_col else airb,
                        cols, rwa_col,
                    )
            elif ref == "9" and ec_col:
                rwa = _col_sum(
                    airb.filter(
                        pl.col(ec_col).is_in(["retail_other", "retail_qrre"])
                    ),
                    cols, rwa_col,
                )
            elif ref == "10" or row_def.is_total:
                irb_all = data.filter(
                    pl.col(approach_col).is_in(
                        ["foundation_irb", "advanced_irb", "slotting"]
                    )
                )
                rwa = _col_sum(irb_all, cols, rwa_col)
            else:
                rwa = None

            values = {"a": rwa, "b": rwa}  # Pre-CD ≈ post-CD
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR7-A ----

    def _generate_all_cr7a(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
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

                values = _compute_cr7a_values(subset, cols, ead_col, rwa_col)
                rows_out.append(_make_row(row_def, values, column_refs))

            result[approach_key] = _build_df(rows_out, column_refs)

        return result

    # ---- CR8 ----

    def _generate_cr8(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
        if not rwa_col:
            errors.append("CR8: missing RWA column")
            return None

        data = irb_data.collect()
        column_refs = [c.ref for c in CR8_COLUMNS]
        closing_rwa = _col_sum(data, cols, rwa_col)
        rows_out: list[dict[str, object]] = []

        for row_def in CR8_ROWS:
            if row_def.ref == "9":
                values: dict[str, object] = {"a": closing_rwa}
            elif row_def.ref == "1":
                # Opening balance — requires prior period data
                values = {"a": None}
            else:
                # Flow drivers — require multi-period comparison
                values = {"a": None}
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CR9 — PD back-testing per exposure class (Art. 452(h)) ----

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
        # we use irb_pd_original (pre-input-floor model PD) as closest proxy
        # for bucket allocation. The reported PD (cols f, g) uses post-floor PD.
        alloc_pd_col = _pick(cols, "irb_pd_original", "irb_pd_floored")
        report_pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")
        if not alloc_pd_col:
            errors.append("CR9: no PD column available — skipping PD backtesting")
            return {}

        data = irb_data.collect()
        if data.height == 0:
            return {}

        result: dict[str, pl.DataFrame] = {}

        for approach_val, approach_display, class_defs in [
            ("foundation_irb", "F-IRB", CR9_FIRB_CLASSES),
            ("advanced_irb", "A-IRB", CR9_AIRB_CLASSES),
        ]:
            approach_data = data.filter(pl.col(approach_col) == approach_val)
            if approach_data.height == 0:
                continue

            for class_key, class_display in class_defs:
                class_data = approach_data.filter(pl.col(ec_col) == class_key)
                if class_data.height == 0:
                    continue

                key = f"{approach_val} - {class_key}"
                result[key] = self._generate_cr9_for_class(
                    class_data, cols, alloc_pd_col,
                    report_pd_col or alloc_pd_col, class_display,
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
            if upper == float("inf"):
                bucket = class_data.filter(pl.col(alloc_pd_col) >= lower)
            else:
                bucket = class_data.filter(
                    (pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper)
                )

            if bucket.height == 0:
                continue

            values = _compute_cr9_values(
                bucket, cols, report_pd_col,
            )
            values["a"] = class_display
            values["b"] = label
            row = P3Row(row_ref, label)
            rows_out.append(_make_row(row, values, column_refs))

        # Total row
        if class_data.height > 0:
            total_values = _compute_cr9_values(
                class_data, cols, report_pd_col,
            )
            total_values["a"] = class_display
            total_values["b"] = "Total"
            rows_out.append(
                _make_row(
                    P3Row("18", "Total", is_total=True), total_values, column_refs,
                )
            )

        if not rows_out:
            schema: dict[str, pl.DataType] = {
                "row_ref": pl.String, "row_name": pl.String,
            }
            for ref in column_refs:
                schema[ref] = pl.String if ref in ("a", "b") else pl.Float64
            return pl.DataFrame([], schema=schema)

        # Build with mixed types: cols a, b are String; rest Float64
        schema = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.String if ref in ("a", "b") else pl.Float64
        return pl.DataFrame(rows_out, schema=schema)

    # ---- CR10 ----

    def _generate_all_cr10(
        self,
        slotting_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
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
        el_col = _pick(cols, "irb_expected_loss", "expected_loss")
        result: dict[str, pl.DataFrame] = {}

        for sl_key in subtemplates:
            if sl_type_col:
                if sl_key == "ipre" and framework != "BASEL_3_1":
                    # CRR: IPRE combined with HVCRE
                    type_data = data.filter(
                        pl.col(sl_type_col).is_in(["ipre", "hvcre"])
                    )
                else:
                    type_data = data.filter(pl.col(sl_type_col) == sl_key)
            else:
                type_data = data.filter(pl.lit(False))

            if type_data.height == 0 and sl_key != "equity":
                continue

            is_hvcre = sl_key == "hvcre"
            rw_map = HVCRE_RISK_WEIGHTS if is_hvcre else SLOTTING_RISK_WEIGHTS
            rows_out: list[dict[str, object]] = []

            for row_def in CR10_SLOTTING_ROWS:
                if row_def.is_total:
                    subset = type_data
                    rw_value = None
                elif cat_col:
                    pipeline_cat = CR10_CATEGORY_MAP.get(row_def.name)
                    if pipeline_cat:
                        subset = type_data.filter(pl.col(cat_col) == pipeline_cat)
                        rw_value = rw_map.get(pipeline_cat)
                    else:
                        rows_out.append(_null_row(row_def, column_refs))
                        continue
                else:
                    rows_out.append(_null_row(row_def, column_refs))
                    continue

                values = _compute_cr10_values(
                    subset, cols, ead_col, rwa_col, el_col, rw_value
                )
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

        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
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
            sa_only = data.filter(
                ~pl.col(approach_col).is_in(modelled_approaches)
            )
            modelled_rwa = _col_sum(modelled, cols, rwa_col) or 0.0
            sa_portfolio_rwa = _col_sum(sa_only, cols, rwa_col) or 0.0

        # Col c: Total actual RWA = modelled + SA portfolio
        total_actual_rwa = modelled_rwa + sa_portfolio_rwa

        # Col d: Full SA RWA (all exposures under SA)
        full_sa_rwa = _col_sum(data, cols, sa_rwa_col) if sa_rwa_col else None

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

        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
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
        modelled_data = pl.concat(
            [irb_collected, slotting_collected], how="diagonal_relaxed"
        )

        column_refs = [c.ref for c in CMS2_COLUMNS]
        rows_out: list[dict[str, object]] = []

        for row_def in CMS2_ROWS:
            values: dict[str, object] = {"a": None, "b": None, "c": None, "d": None}

            if row_def.is_total:
                # Total row: sum all credit risk exposures
                values["a"] = _col_sum(modelled_data, cols, rwa_col)
                values["b"] = (
                    _col_sum(modelled_data, cols, sa_rwa_col) if sa_rwa_col else None
                )
                modelled_total = values["a"] or 0.0
                sa_port_rwa = _col_sum(sa_collected, cols, rwa_col) or 0.0
                values["c"] = modelled_total + sa_port_rwa
                values["d"] = _col_sum(all_data, cols, sa_rwa_col) if sa_rwa_col else None
            elif row_def.ref == "0041" and ec_col and approach_col:
                # "Of which are FIRB" — corporate exposures under F-IRB
                corp_classes = list(CMS2_SA_CLASS_MAP.get("0040", ()))
                firb_corp = modelled_data.filter(
                    pl.col(ec_col).is_in(corp_classes)
                    & (pl.col(approach_col) == "foundation_irb")
                )
                values["a"] = _col_sum(firb_corp, cols, rwa_col)
                values["b"] = (
                    _col_sum(firb_corp, cols, sa_rwa_col) if sa_rwa_col else None
                )
                sa_firb = sa_collected.filter(pl.col(ec_col).is_in(corp_classes)) if ec_col else sa_collected.filter(pl.lit(False))
                values["c"] = (values["a"] or 0.0) + (_col_sum(sa_firb, cols, rwa_col) or 0.0)
                values["d"] = (
                    _col_sum(
                        all_data.filter(pl.col(ec_col).is_in(corp_classes)),
                        cols,
                        sa_rwa_col,
                    )
                    if sa_rwa_col and ec_col
                    else None
                )
            elif row_def.ref == "0042" and ec_col and approach_col:
                # "Of which are AIRB" — corporate exposures under A-IRB
                corp_classes = list(CMS2_SA_CLASS_MAP.get("0040", ()))
                airb_corp = modelled_data.filter(
                    pl.col(ec_col).is_in(corp_classes)
                    & (pl.col(approach_col) == "advanced_irb")
                )
                values["a"] = _col_sum(airb_corp, cols, rwa_col)
                values["b"] = (
                    _col_sum(airb_corp, cols, sa_rwa_col) if sa_rwa_col else None
                )
                # c and d: same as FIRB sub-row pattern but filtered to AIRB
                values["c"] = values["a"]  # Sub-row: no SA portfolio add
                values["d"] = None  # Sub-row: comparison at parent level
            elif row_def.ref in ("0044", "0045", "0054"):
                # Sub-rows requiring pipeline data not currently available:
                # 0044 IPRE/HVCRE, 0045 purchased receivables (corp),
                # 0054 purchased receivables (retail)
                pass  # All null
            elif row_def.exposure_classes and ec_col:
                # Standard asset class row
                ec_list = list(row_def.exposure_classes)

                # Col a: modelled RWA for this class
                class_modelled = modelled_data.filter(
                    pl.col(ec_col).is_in(ec_list)
                )
                values["a"] = _col_sum(class_modelled, cols, rwa_col)

                # Col b: SA-equivalent RWA for modelled exposures
                values["b"] = (
                    _col_sum(class_modelled, cols, sa_rwa_col)
                    if sa_rwa_col
                    else None
                )

                # Col c: Total actual RWA = modelled + SA portfolio for this class
                class_sa = sa_collected.filter(pl.col(ec_col).is_in(ec_list))
                modelled_rwa = values["a"] or 0.0
                sa_port_rwa = _col_sum(class_sa, cols, rwa_col) or 0.0
                values["c"] = modelled_rwa + sa_port_rwa

                # Col d: Full SA RWA for all exposures in this class
                sa_class_key = row_def.ref
                sa_classes = CMS2_SA_CLASS_MAP.get(sa_class_key, ec_list)
                class_all = all_data.filter(pl.col(ec_col).is_in(list(sa_classes)))
                values["d"] = (
                    _col_sum(class_all, cols, sa_rwa_col) if sa_rwa_col else None
                )

            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get column names from a LazyFrame schema without collecting."""
    return set(lf.collect_schema().names())


def _pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first candidate column name that exists in *cols*."""
    for c in candidates:
        if c in cols:
            return c
    return None


def _col_sum(data: pl.DataFrame, cols: set[str], col_name: str | None) -> float | None:
    """Sum a single column, returning None if absent or empty."""
    if not col_name or col_name not in data.columns or data.height == 0:
        return None
    result = data.select(pl.col(col_name).sum()).item()
    return float(result) if result is not None else None


def _safe_sum(data: pl.DataFrame, cols: set[str], *col_names: str) -> float | None:
    """Sum multiple columns, skipping absent ones."""
    total = 0.0
    found = False
    for cn in col_names:
        if cn in data.columns:
            val = data.select(pl.col(cn).sum()).item()
            if val is not None:
                total += float(val)
                found = True
    return total if found else None


def _approach_rwa(
    data: pl.DataFrame, approach_col: str, rwa_col: str, approach: str,
) -> float | None:
    """Sum RWA for a specific approach."""
    filtered = data.filter(pl.col(approach_col) == approach)
    if filtered.height == 0:
        return 0.0
    result = filtered.select(pl.col(rwa_col).sum()).item()
    return float(result) if result is not None else 0.0


def _ead_weighted_avg(
    data: pl.DataFrame, cols: set[str], ead_col: str, metric_col: str | None,
) -> float | None:
    """Compute EAD-weighted average of a metric column."""
    if not metric_col or metric_col not in data.columns or data.height == 0:
        return None
    result = data.select(
        (pl.col(metric_col) * pl.col(ead_col)).sum() / pl.col(ead_col).sum()
    ).item()
    return float(result) if result is not None else None


def _null_row(row_def: P3Row, column_refs: list[str]) -> dict[str, object]:
    """Build a row dict with all column values set to None."""
    row: dict[str, object] = {"row_ref": row_def.ref, "row_name": row_def.name}
    for ref in column_refs:
        row[ref] = None
    return row


def _make_row(
    row_def: P3Row, values: dict[str, object], column_refs: list[str],
) -> dict[str, object]:
    """Build a row dict from computed values, filling missing refs with None."""
    row: dict[str, object] = {"row_ref": row_def.ref, "row_name": row_def.name}
    for ref in column_refs:
        row[ref] = values.get(ref)
    return row


def _build_df(rows: list[dict[str, object]], column_refs: list[str]) -> pl.DataFrame:
    """Materialise a list of row dicts into a typed Polars DataFrame."""
    schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
    schema.update(dict.fromkeys(column_refs, pl.Float64))
    return pl.DataFrame(rows, schema=schema)


def _filter_by_approach(
    results: pl.LazyFrame, approach_value: str, cols: set[str],
) -> pl.LazyFrame:
    """Filter results to a specific approach_applied value."""
    approach_col = _pick(cols, "approach_applied", "approach")
    if not approach_col:
        return results.filter(pl.lit(False))
    return results.filter(pl.col(approach_col) == approach_value)


def _filter_irb_non_slotting(
    results: pl.LazyFrame, cols: set[str],
) -> pl.LazyFrame:
    """Filter to F-IRB and A-IRB exposures (excluding slotting)."""
    approach_col = _pick(cols, "approach_applied", "approach")
    if not approach_col:
        return results.filter(pl.lit(False))
    return results.filter(
        pl.col(approach_col).is_in(["foundation_irb", "advanced_irb"])
    )


def _filter_on_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to on-balance-sheet exposures."""
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "ONB")
    if "exposure_type" in data.columns:
        return data.filter(pl.col("exposure_type") == "loan")
    return data


def _filter_off_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to off-balance-sheet exposures."""
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "OFB")
    if "exposure_type" in data.columns:
        return data.filter(pl.col("exposure_type").is_in(["facility", "contingent"]))
    return data.filter(pl.lit(False))


# ---------------------------------------------------------------------------
# Per-template value computation
# ---------------------------------------------------------------------------


def _compute_cr4_values(
    data: pl.DataFrame, cols: set[str], ead_col: str, rwa_col: str,
) -> dict[str, object]:
    """Compute CR4 column values for a subset of SA exposures."""
    on_bs = _filter_on_bs(data, cols)
    off_bs = _filter_off_bs(data, cols)

    on_bs_pre = _safe_sum(on_bs, cols, "drawn_amount", "interest") or 0.0
    off_bs_pre = _safe_sum(off_bs, cols, "nominal_amount", "undrawn_amount") or 0.0
    on_bs_post = _col_sum(on_bs, cols, ead_col) or 0.0
    off_bs_post = _col_sum(off_bs, cols, ead_col) or 0.0
    rwa = _col_sum(data, cols, rwa_col) or 0.0
    denominator = on_bs_post + off_bs_post

    return {
        "a": on_bs_pre,
        "b": off_bs_pre,
        "c": on_bs_post,
        "d": off_bs_post,
        "e": rwa,
        "f": rwa / denominator if denominator > 0 else None,
    }


def _compute_cr5_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rw_col: str,
    rw_bands: list[tuple[float, str]],
    is_b31: bool,
) -> dict[str, object]:
    """Compute CR5 column values: EAD allocated to risk-weight buckets."""
    total_ead = _col_sum(data, cols, ead_col) or 0.0
    allocated = 0.0
    values: dict[str, object] = {}

    for i, (rw_value, _label) in enumerate(rw_bands):
        ref = _letter_ref(i)
        # Filter to ±0.5pp tolerance for risk weight match
        tol = 0.005
        bucket = data.filter(
            (pl.col(rw_col) >= rw_value - tol) & (pl.col(rw_col) < rw_value + tol)
        )
        bucket_ead = _col_sum(bucket, cols, ead_col) or 0.0
        values[ref] = bucket_ead
        allocated += bucket_ead

    n = len(rw_bands)
    # Other/Deducted = residual
    values[_letter_ref(n)] = max(0.0, total_ead - allocated)
    # Total
    values[_letter_ref(n + 1)] = total_ead
    # Unrated
    if "sa_cqs" in data.columns:
        unrated = data.filter(pl.col("sa_cqs").is_null())
        values[_letter_ref(n + 2)] = _col_sum(unrated, cols, ead_col)
    else:
        values[_letter_ref(n + 2)] = total_ead  # All unrated

    if is_b31:
        on_bs = _filter_on_bs(data, cols)
        off_bs = _filter_off_bs(data, cols)
        on_bs_ead = _safe_sum(on_bs, cols, "drawn_amount", "interest")
        off_bs_ead = _safe_sum(off_bs, cols, "nominal_amount", "undrawn_amount")
        ccf_col = _pick(cols, "ccf_applied", "ccf")
        avg_ccf = _ead_weighted_avg(off_bs, cols, ead_col, ccf_col) if ccf_col else None
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
    lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
    maturity_col = _pick(cols, "irb_maturity_m")
    el_col = _pick(cols, "irb_expected_loss", "expected_loss")
    ccf_col = _pick(cols, "ccf_applied", "ccf")
    prov_col = _pick(cols, "scra_provision_amount", "provision_held")

    ead_sum = _col_sum(data, cols, ead_col) or 0.0
    rwa_sum = _col_sum(data, cols, rwa_col) or 0.0

    values: dict[str, object] = {
        "b": _safe_sum(on_bs, cols, "drawn_amount", "interest"),
        "c": _safe_sum(off_bs, cols, "nominal_amount", "undrawn_amount"),
        "d": _ead_weighted_avg(off_bs, cols, ead_col, ccf_col),
        "e": ead_sum,
        "f": _ead_weighted_avg(data, cols, ead_col, pd_col),
        "g": _obligor_count(data, cols),
        "h": _ead_weighted_avg(data, cols, ead_col, lgd_col),
        "i": _ead_weighted_avg(data, cols, ead_col, maturity_col),
        "j": rwa_sum,
        "k": rwa_sum / ead_sum if ead_sum > 0 else None,
        "l": _col_sum(data, cols, el_col),
        "m": _col_sum(data, cols, prov_col),
    }

    # Convert PD/LGD to percentage for display
    if values.get("f") is not None:
        values["f"] = float(values["f"]) * 100.0
    if values.get("h") is not None:
        values["h"] = float(values["h"]) * 100.0

    return values


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

    # Col c: obligor count — prefer unique counterparty_reference
    cp_col = "counterparty_reference" if "counterparty_reference" in data.columns else None
    n_obligors = (
        float(data.select(pl.col(cp_col).n_unique()).item())
        if cp_col
        else float(n_rows)
    )

    # Default detection: is_defaulted → PD >= 1.0 fallback
    default_col = _pick(cols, "is_defaulted", "default_status")
    if default_col and default_col in data.columns:
        defaulted = data.filter(pl.col(default_col) == True)  # noqa: E712
        n_defaults = (
            float(defaulted.select(pl.col(cp_col).n_unique()).item())
            if cp_col and defaulted.height > 0
            else float(defaulted.height)
        )
    elif pd_col in data.columns:
        defaulted = data.filter(pl.col(pd_col) >= 1.0)
        n_defaults = (
            float(defaulted.select(pl.col(cp_col).n_unique()).item())
            if cp_col and defaulted.height > 0
            else float(defaulted.height)
        )
    else:
        n_defaults = 0.0

    # Col c: prior year obligors — use prior_year_obligor_count if available,
    # else fall back to current-period count
    prior_col = _pick(cols, "prior_year_obligor_count")
    if prior_col and prior_col in data.columns:
        prior_obligors = float(data.select(pl.col(prior_col).fill_null(0.0).sum()).item())
    else:
        prior_obligors = n_obligors

    # Col e: observed average default rate
    observed_rate = (n_defaults / n_obligors * 100.0) if n_obligors > 0 else 0.0

    # Col f: exposure-weighted average PD (post input floor) — same as CR6 col f
    ead_col = _pick(cols, "ead_final", "final_ead", "ead")
    if ead_col and ead_col in data.columns and pd_col in data.columns:
        ewa_pd = _ead_weighted_avg(data, cols, ead_col, pd_col)
        ewa_pd_pct = float(ewa_pd) * 100.0 if ewa_pd is not None else None
    elif pd_col in data.columns:
        # Fallback to arithmetic average if no EAD column
        avg_pd = data.select(pl.col(pd_col).mean()).item()
        ewa_pd_pct = float(avg_pd) * 100.0 if avg_pd is not None else None
    else:
        ewa_pd_pct = None

    # Col g: arithmetic average PD at disclosure date (obligor-weighted, not
    # exposure-weighted) — includes PD input floors
    if pd_col in data.columns:
        avg_pd_g = data.select(pl.col(pd_col).mean()).item()
        avg_pd_pct = float(avg_pd_g) * 100.0 if avg_pd_g is not None else None
    else:
        avg_pd_pct = None

    # Col h: average historical annual default rate (5-year simple average)
    hist_col = _pick(cols, "historical_annual_default_rate")
    if hist_col and hist_col in data.columns and n_rows > 0:
        hist_rate = data.select(pl.col(hist_col).fill_null(0.0).mean()).item()
        hist_rate_pct = float(hist_rate) * 100.0 if hist_rate is not None else None
    else:
        # Fall back to current-period observed rate as single-period approximation
        hist_rate_pct = observed_rate

    return {
        "c": prior_obligors,
        "d": n_defaults,
        "e": observed_rate,
        "f": ewa_pd_pct,
        "g": avg_pd_pct,
        "h": hist_rate_pct,
    }


def _compute_cr7a_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
) -> dict[str, object]:
    """Compute CR7-A column values for a filtered IRB subset."""
    total_ead = _col_sum(data, cols, ead_col) or 0.0

    def _pct(col_name: str | None) -> float | None:
        if not col_name or col_name not in data.columns or total_ead == 0:
            return None
        val = _col_sum(data, cols, col_name) or 0.0
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
        "m": _col_sum(data, cols, _pick(cols, "rwa_final", "final_rwa", "rwa")),
        "n": _col_sum(data, cols, _pick(cols, "rwa_final", "final_rwa", "rwa")),
    }

    # c = sum of d + e + f
    d_val = values.get("d") or 0.0
    e_val = values.get("e") or 0.0
    f_val = values.get("f") or 0.0
    values["c"] = d_val + e_val + f_val if (d_val or e_val or f_val) else None

    # g = sum of h + i + j
    values["g"] = None  # sub-categories not tracked

    # l = credit derivatives %
    values["l"] = None  # Not separately tracked from guarantees

    # o, p for B31 slotting — always None for F-IRB/A-IRB
    values["o"] = None
    values["p"] = None

    return values


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
        "a": _safe_sum(on_bs, cols, "drawn_amount", "interest"),
        "b": _safe_sum(off_bs, cols, "nominal_amount", "undrawn_amount"),
        "c": rw_value * 100.0 if rw_value is not None else None,
        "d": _col_sum(data, cols, ead_col),
        "e": _col_sum(data, cols, rwa_col),
        "f": _col_sum(data, cols, el_col) if el_col else None,
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


def _write_single_sheet(workbook: object, df: pl.DataFrame, name: str) -> int:
    """Write a single DataFrame to a workbook sheet. Returns row count."""
    sheet = _sanitise_sheet_name(name)
    df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)  # type: ignore[arg-type]
    return df.height


def _write_dict_sheets(
    workbook: object,
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
        df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)  # type: ignore[arg-type]
        total += df.height
    return total
