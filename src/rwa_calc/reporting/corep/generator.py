"""
COREP template generator for credit risk reporting.

Pipeline position:
    CalculationResponse -> COREPGenerator -> COREPTemplateBundle -> Excel

Key responsibilities:
- Generate per-exposure-class COREP template DataFrames with row sections
- Populate COREP columns from pipeline calculation results using 4-digit refs
- Support both CRR and Basel 3.1 framework variants
- Export to Excel with per-class sheet structure

Why: COREP templates are the regulatory reporting format mandated by
the PRA for quarterly capital adequacy returns. Each template is submitted
once per exposure class with a fixed multi-section row structure. This module
reshapes exposure-level results into that fixed layout.

References:
- Regulation (EU) 2021/451, Annex I/II (CRR templates)
- CRR Art. 111-134 (SA), Art. 142-191 (IRB)
- PRA PS1/26, Annex I/II (Basel 3.1 OF templates)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.corep.templates import (
    IRB_EXPOSURE_CLASS_ROWS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    get_c07_columns,
    get_c08_02_columns,
    get_c08_columns,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)

if TYPE_CHECKING:
    from rwa_calc.api.export import ExportResult
    from rwa_calc.api.models import CalculationResponse

logger = logging.getLogger(__name__)


# =============================================================================
# COREP TEMPLATE BUNDLE
# =============================================================================


@dataclass(frozen=True)
class COREPTemplateBundle:
    """Bundle of generated COREP template DataFrames.

    Each template is a dict keyed by exposure class value, where each value
    is a DataFrame with row sections and 4-digit COREP column references.

    C 07.00 (SA): One DataFrame per SA exposure class, with 5 row sections.
    C 08.01 (IRB): One DataFrame per IRB exposure class, with 3 row sections.
    C 08.02 (IRB by PD grade): One DataFrame per IRB exposure class.

    Why: COREP templates are submitted per exposure class to the regulator.
    Each class gets a fixed row structure (totals, exposure types, risk weights,
    CIU approach, memorandum) and fixed column structure (the credit risk
    waterfall from original exposure through CRM to final RWEA).
    """

    c07_00: dict[str, pl.DataFrame]
    c08_01: dict[str, pl.DataFrame]
    c08_02: dict[str, pl.DataFrame]
    framework: str = "CRR"
    errors: list[str] = field(default_factory=list)


# =============================================================================
# COREP GENERATOR
# =============================================================================


class COREPGenerator:
    """Generates COREP credit risk templates from RWA calculation results.

    Produces per-exposure-class DataFrames for C 07.00 (SA), C 08.01 (IRB totals),
    and C 08.02 (IRB PD grade breakdown) with correct 4-digit COREP column
    references and multi-section row structure.

    Usage:
        generator = COREPGenerator()
        bundle = generator.generate(response)
        bundle = generator.generate_from_lazyframe(results_lf, framework="CRR")
    """

    def generate(self, response: CalculationResponse) -> COREPTemplateBundle:
        """Generate all COREP templates from a CalculationResponse."""
        results_lf = response.scan_results()
        return self.generate_from_lazyframe(results_lf, framework=response.framework)

    def generate_from_lazyframe(
        self,
        results: pl.LazyFrame,
        *,
        framework: str = "CRR",
    ) -> COREPTemplateBundle:
        """Generate all COREP templates from a results LazyFrame.

        Primary entry point for direct pipeline integration. Produces
        per-exposure-class DataFrames with correct row sections and
        4-digit COREP column references.

        Args:
            results: Combined results LazyFrame with all approaches
            framework: Regulatory framework ("CRR" or "BASEL_3_1")
        """
        errors: list[str] = []
        cols = _available_columns(results)

        # SA templates (C 07.00)
        sa_data = _filter_by_approach(results, "standardised", cols)
        c07_00 = self._generate_all_c07(sa_data, cols, framework, errors)

        # IRB templates (C 08.01, C 08.02)
        irb_data = _filter_by_irb_approach(results, cols)
        c08_01 = self._generate_all_c08_01(irb_data, cols, framework, errors)
        c08_02 = self._generate_all_c08_02(irb_data, cols, framework, errors)

        return COREPTemplateBundle(
            c07_00=c07_00,
            c08_01=c08_01,
            c08_02=c08_02,
            framework=framework,
            errors=errors,
        )

    def export_to_excel(
        self,
        bundle: COREPTemplateBundle,
        output_path: Path,
    ) -> ExportResult:
        """Write COREP templates to a multi-sheet Excel workbook.

        Creates one sheet per exposure class per template type:
        - "C 07.00 - Corporate", "C 07.00 - Institution", etc.
        - "C 08.01 - Corporate", etc.
        - "C 08.02 - Corporate", etc.
        """
        from rwa_calc.api.export import ExportResult

        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = (
                "COREP Excel export requires 'xlsxwriter'. Install with: uv add xlsxwriter"
            )
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_rows = 0

        import xlsxwriter as xw

        workbook = xw.Workbook(str(output_path))
        try:
            total_rows += self._write_template_sheets(
                workbook, bundle.c07_00, "C 07.00", SA_EXPOSURE_CLASS_ROWS
            )
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_01, "C 08.01", IRB_EXPOSURE_CLASS_ROWS
            )
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_02, "C 08.02", IRB_EXPOSURE_CLASS_ROWS
            )
        finally:
            workbook.close()

        logger.info("COREP templates written to %s (%d rows)", output_path, total_rows)

        return ExportResult(
            format="corep_excel",
            files=[output_path],
            row_count=total_rows,
        )

    @staticmethod
    def _write_template_sheets(
        workbook: object,
        templates: dict[str, pl.DataFrame],
        prefix: str,
        class_names: dict[str, tuple[str, str]],
    ) -> int:
        """Write per-class DataFrames as Excel sheets. Returns total rows written."""
        total = 0
        for ec, df in sorted(templates.items()):
            if len(df) > 0:
                display = class_names.get(ec, (None, ec))[1]
                sheet = f"{prefix} - {display}"[:31]  # Excel 31-char limit
                df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
                total += len(df)
        return total

    # =========================================================================
    # C 07.00 — SA Credit Risk (per exposure class)
    # =========================================================================

    def _generate_all_c07(
        self,
        sa_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 07.00 DataFrames for all SA exposure classes."""
        ec_col = _pick(cols, "exposure_class")
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        if ec_col is None or ead_col is None or rwa_col is None:
            if ead_col is None or rwa_col is None:
                errors.append("C07: Missing EAD or RWA columns in results")
            if ec_col is None:
                errors.append("C07: Missing exposure_class column")
            return {}

        sa_df = sa_data.collect()
        if len(sa_df) == 0:
            return {}

        data_cols = set(sa_df.columns)
        classes = sa_df[ec_col].unique().sort().to_list()

        # Pre-compute CRM substitution flows (inflows require full dataset)
        sub_flows = _compute_substitution_flows(sa_df, data_cols, ec_col)

        result: dict[str, pl.DataFrame] = {}
        for ec in classes:
            class_df = sa_df.filter(pl.col(ec_col) == ec)
            inflow = sub_flows.get(ec, {}).get("inflow", 0.0)
            template_df = self._generate_c07_for_class(
                class_df, data_cols, ead_col, rwa_col, framework, inflow
            )
            result[ec] = template_df

        return result

    def _generate_c07_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        framework: str,
        substitution_inflow: float = 0.0,
    ) -> pl.DataFrame:
        """Generate a C 07.00 DataFrame for a single SA exposure class.

        Builds all 5 row sections:
        1. Total Exposures (row 0010 + "of which" detail rows)
        2. Breakdown by Exposure Types (on-BS, off-BS, CCR)
        3. Breakdown by Risk Weights (one row per RW band)
        4. Breakdown by CIU Approach
        5. Memorandum Items
        """
        column_defs = get_c07_columns(framework)
        column_refs = [c.ref for c in column_defs]
        row_sections = get_sa_row_sections(framework)
        rw_bands = get_sa_risk_weight_bands(framework)

        rows: list[dict[str, object]] = []

        # Section 1: Total Exposures
        for row_def in row_sections[0].rows:
            if row_def.ref == "0010":
                # Row 0010: aggregate ALL class data (with class-level inflows)
                values = _compute_c07_values(
                    class_data, cols, ead_col, rwa_col, column_refs,
                    substitution_inflow=substitution_inflow,
                )
                rows.append(
                    {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                )
            elif row_def.ref == "0015":
                # Row 0015: of which: Defaulted exposures
                subset = _filter_defaulted(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0020":
                # Row 0020: of which: SME
                subset = _filter_sme(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in ("0021", "0022", "0023"):
                # Specialised lending "of which" rows (B3.1 rows 0021-0023)
                sl_type_map = {
                    "0021": "object_finance",
                    "0022": "commodities_finance",
                    "0023": "project_finance",
                }
                subset = _filter_sl_type(class_data, cols, sl_type_map[row_def.ref])
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in ("0024", "0025", "0026"):
                # Project finance phase "of which" rows (B3.1 rows 0024-0026)
                phase_map = {
                    "0024": "pre_operational",
                    "0025": "operational",
                    "0026": "high_quality_operational",
                }
                subset = _filter_project_phase(
                    class_data, cols, phase_map[row_def.ref]
                )
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in _RE_ROW_FILTERS:
                # Real estate "of which" rows (B3.1 rows 0330-0360)
                re_kwargs = _RE_ROW_FILTERS[row_def.ref]
                subset = _filter_re(class_data, cols, **re_kwargs)
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # Other "of which" rows — Phase 3 features (equity), null for now
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 2: Breakdown by Exposure Types
        for row_def in row_sections[1].rows:
            if row_def.ref == "0070":
                # On balance sheet exposures
                subset = _filter_on_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0080":
                # Off balance sheet exposures
                subset = _filter_off_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # CCR rows (0090-0130) — not implemented
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 3: Breakdown by Risk Weights
        rw_col = _pick(cols, "risk_weight", "sa_final_risk_weight")
        rw_row_data = _compute_rw_section_rows(
            class_data, cols, ead_col, rwa_col, column_refs, rw_bands, rw_col
        )
        for row_def in row_sections[2].rows:
            if row_def.name in rw_row_data:
                values = rw_row_data[row_def.name]
                rows.append(
                    {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                )
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 4: Breakdown by CIU Approach — not implemented, null
        for row_def in row_sections[3].rows:
            rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 5: Memorandum Items
        for row_def in row_sections[4].rows:
            if row_def.ref in _EQUITY_TRANSITIONAL_FILTERS:
                eq_filter = _EQUITY_TRANSITIONAL_FILTERS[row_def.ref]
                subset = _filter_equity_transitional(
                    class_data, cols, **eq_filter
                )
                if len(subset) > 0:
                    values = _compute_c07_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # Other memorandum rows (0300, 0320, 0380) — not yet implemented
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {
            "row_ref": pl.String,
            "row_name": pl.String,
        }
        schema.update({ref: pl.Float64 for ref in column_refs})
        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.01 — IRB Totals (per exposure class)
    # =========================================================================

    def _generate_all_c08_01(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.01 DataFrames for all IRB exposure classes."""
        ec_col = _pick(cols, "exposure_class")
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        if ec_col is None or ead_col is None or rwa_col is None:
            if ead_col is None or rwa_col is None:
                errors.append("C08.01: Missing EAD or RWA columns")
            if ec_col is None:
                errors.append("C08.01: Missing exposure_class column")
            return {}

        irb_df = irb_data.collect()
        if len(irb_df) == 0:
            return {}

        data_cols = set(irb_df.columns)
        classes = irb_df[ec_col].unique().sort().to_list()

        # Pre-compute CRM substitution flows (inflows require full dataset)
        sub_flows = _compute_substitution_flows(irb_df, data_cols, ec_col)

        result: dict[str, pl.DataFrame] = {}
        for ec in classes:
            class_df = irb_df.filter(pl.col(ec_col) == ec)
            inflow = sub_flows.get(ec, {}).get("inflow", 0.0)
            template_df = self._generate_c08_01_for_class(
                class_df, data_cols, ead_col, rwa_col, framework, inflow
            )
            result[ec] = template_df

        return result

    def _generate_c08_01_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        framework: str,
        substitution_inflow: float = 0.0,
    ) -> pl.DataFrame:
        """Generate a C 08.01 DataFrame for a single IRB exposure class.

        Builds 3 row sections:
        1. Total (+ supporting factors for CRR)
        2. Breakdown by Exposure Types
        3. Calculation Approaches
        """
        column_defs = get_c08_columns(framework)
        column_refs = [c.ref for c in column_defs]
        row_sections = get_irb_row_sections(framework)

        rows: list[dict[str, object]] = []

        # Section 1: Total
        for row_def in row_sections[0].rows:
            if row_def.ref == "0010":
                values = _compute_c08_values(
                    class_data, cols, ead_col, rwa_col, column_refs,
                    substitution_inflow=substitution_inflow,
                )
                rows.append(
                    {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                )
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 2: Breakdown by Exposure Types
        for row_def in row_sections[1].rows:
            if row_def.ref == "0020":
                # On balance sheet items
                subset = _filter_on_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c08_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0030":
                # Off balance sheet items
                subset = _filter_off_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c08_values(
                        subset, cols, ead_col, rwa_col, column_refs
                    )
                    rows.append(
                        {"row_ref": row_def.ref, "row_name": row_def.name, **values}
                    )
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # CCR/other rows — not implemented
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 3: Calculation Approaches — null for now
        for row_def in row_sections[2].rows:
            rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {
            "row_ref": pl.String,
            "row_name": pl.String,
        }
        schema.update({ref: pl.Float64 for ref in column_refs})
        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.02 — IRB PD Grade Breakdown (per exposure class)
    # =========================================================================

    def _generate_all_c08_02(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.02 DataFrames for all IRB exposure classes."""
        ec_col = _pick(cols, "exposure_class")
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")
        pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")

        if ec_col is None or ead_col is None or rwa_col is None:
            errors.append("C08.02: Missing required columns")
            return {}

        if pd_col is None:
            errors.append(
                "C08.02: No PD column available — skipping PD grade breakdown"
            )
            return {}

        irb_df = irb_data.collect()
        if len(irb_df) == 0:
            return {}

        data_cols = set(irb_df.columns)
        classes = irb_df[ec_col].unique().sort().to_list()
        result: dict[str, pl.DataFrame] = {}

        for ec in classes:
            class_df = irb_df.filter(pl.col(ec_col) == ec)
            template_df = self._generate_c08_02_for_class(
                class_df, data_cols, ead_col, rwa_col, pd_col, framework
            )
            result[ec] = template_df

        return result

    def _generate_c08_02_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        pd_col: str,
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 08.02 DataFrame for a single IRB exposure class.

        Rows = PD bands. Each row has the same columns as C 08.01 plus
        an obligor grade identifier (col 0005) and PD (col 0010 for B3.1).
        """
        column_defs = get_c08_02_columns(framework)
        column_refs = [c.ref for c in column_defs]

        # Assign PD bands
        band_expr = pl.lit("Unassigned")
        for lower, upper, label in reversed(PD_BANDS):
            band_expr = (
                pl.when(
                    (pl.col(pd_col) >= lower) & (pl.col(pd_col) < upper)
                )
                .then(pl.lit(label))
                .otherwise(band_expr)
            )

        banded = class_data.with_columns(band_expr.alias("_pd_band"))

        # Build one row per PD band
        rows: list[dict[str, object]] = []
        band_labels = [label for _, _, label in PD_BANDS]

        for label in band_labels:
            band_data = banded.filter(pl.col("_pd_band") == label).drop("_pd_band")
            if len(band_data) == 0:
                continue

            # Compute C 08.01-equivalent values for this band
            values = _compute_c08_values(
                band_data, cols, ead_col, rwa_col, column_refs
            )
            # Col 0005: obligor grade identifier = the PD band label
            values["0005"] = label
            rows.append(
                {"row_ref": label, "row_name": label, **values}
            )

        # Handle unassigned
        unassigned = banded.filter(pl.col("_pd_band") == "Unassigned").drop("_pd_band")
        if len(unassigned) > 0:
            values = _compute_c08_values(
                unassigned, cols, ead_col, rwa_col, column_refs
            )
            values["0005"] = "Unassigned"
            rows.append(
                {"row_ref": "Unassigned", "row_name": "Unassigned", **values}
            )

        if not rows:
            schema: dict[str, pl.DataType] = {
                "row_ref": pl.String,
                "row_name": pl.String,
            }
            schema.update({ref: pl.Float64 for ref in column_refs})
            return pl.DataFrame(schema=schema)

        # Infer schema from column defs — 0005 is String, rest are Float64
        schema = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.String if ref == "0005" else pl.Float64

        return pl.DataFrame(rows, schema=schema)


# =============================================================================
# RE ROW FILTER CONFIGURATION (Basel 3.1 OF 07.00 rows 0330-0360)
# =============================================================================

# Maps row refs to _filter_re() kwargs. Each entry defines the filter criteria
# for a real estate "of which" row in B3.1 Section 1.
_RE_ROW_FILTERS: dict[str, dict[str, object]] = {
    # Regulatory residential RE (CRE20.71-82)
    "0330": {"property_type": "residential"},
    "0331": {"property_type": "residential", "materially_dependent": False},
    "0332": {"property_type": "residential", "materially_dependent": True},
    # Regulatory commercial RE (CRE20.83-87)
    "0340": {"property_type": "commercial"},
    "0341": {"property_type": "commercial", "materially_dependent": False, "is_sme": False},
    "0342": {"property_type": "commercial", "materially_dependent": True},
    "0343": {"property_type": "commercial", "materially_dependent": False, "is_sme": True},
    "0344": {"property_type": "commercial", "materially_dependent": True, "is_sme": True},
    # Land ADC (CRE20.88)
    "0360": {"is_adc": True},
}
# Note: Rows 0350-0354 ("Other real estate") require a separate "other" RE
# classification not yet in the pipeline. They remain null until a
# regulatory_re_category field is added to distinguish regulatory vs other RE.

# =============================================================================
# EQUITY TRANSITIONAL ROW CONFIGURATION (Basel 3.1 OF 07.00 rows 0371-0374)
# =============================================================================

_EQUITY_TRANSITIONAL_FILTERS: dict[str, dict[str, object]] = {
    "0371": {"approach": "sa_transitional", "higher_risk": True},
    "0372": {"approach": "sa_transitional", "higher_risk": False},
    "0373": {"approach": "irb_transitional", "higher_risk": True},
    "0374": {"approach": "irb_transitional", "higher_risk": False},
}

# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def _pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from candidates that exists in cols."""
    for c in candidates:
        if c in cols:
            return c
    return None


def _filter_by_approach(
    results: pl.LazyFrame,
    approach_value: str,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter results to a specific approach_applied value."""
    approach_col = _pick(cols, "approach_applied")
    if approach_col is None:
        return results.filter(pl.lit(False))
    return results.filter(pl.col(approach_col) == approach_value)


def _filter_by_irb_approach(
    results: pl.LazyFrame,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter results to IRB approaches (F-IRB, A-IRB, slotting)."""
    approach_col = _pick(cols, "approach_applied")
    if approach_col is None:
        return results.filter(pl.lit(False))
    return results.filter(
        pl.col(approach_col).is_in(["foundation_irb", "advanced_irb", "slotting"])
    )


def _filter_defaulted(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to defaulted exposures using available columns."""
    if "default_status" in cols:
        return data.filter(pl.col("default_status") == True)  # noqa: E712
    if "exposure_class" in cols:
        return data.filter(pl.col("exposure_class") == "defaulted")
    if "irb_pd_floored" in cols:
        return data.filter(pl.col("irb_pd_floored") >= 1.0)
    return data.clear()


def _filter_sme(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to SME exposures using available columns."""
    if "sme_supporting_factor_eligible" in cols:
        return data.filter(pl.col("sme_supporting_factor_eligible") == True)  # noqa: E712
    if "exposure_class" in cols:
        return data.filter(pl.col("exposure_class").str.contains("sme"))
    return data.clear()


def _filter_lfse(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame | None:
    """Filter to large financial sector entity exposures.

    Returns None if apply_fi_scalar column is not available (cannot determine LFSE).
    """
    if "apply_fi_scalar" in cols:
        return data.filter(pl.col("apply_fi_scalar") == True)  # noqa: E712
    return None


def _filter_on_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to on-balance-sheet exposures."""
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "ONB")
    if "exposure_type" in cols:
        return data.filter(pl.col("exposure_type") == "loan")
    return data.clear()


def _filter_off_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to off-balance-sheet exposures."""
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "OFB")
    if "exposure_type" in cols:
        return data.filter(pl.col("exposure_type").is_in(["facility", "contingent"]))
    return data.clear()


def _filter_equity_transitional(
    data: pl.DataFrame,
    cols: set[str],
    *,
    approach: str,
    higher_risk: bool,
) -> pl.DataFrame:
    """Filter to equity exposures under a transitional approach.

    Args:
        approach: "sa_transitional" or "irb_transitional"
        higher_risk: True for 400%+ RW (speculative/venture capital)
    """
    if "equity_transitional_approach" not in cols:
        return data.clear()

    result = data.filter(pl.col("equity_transitional_approach") == approach)

    if "equity_higher_risk" in cols:
        result = result.filter(pl.col("equity_higher_risk") == higher_risk)
    elif higher_risk:
        return data.clear()

    return result


def _filter_sl_type(
    data: pl.DataFrame, cols: set[str], sl_type: str
) -> pl.DataFrame:
    """Filter to exposures with a given specialised lending type."""
    if "sl_type" not in cols:
        return data.clear()
    return data.filter(pl.col("sl_type") == sl_type)


def _filter_project_phase(
    data: pl.DataFrame, cols: set[str], phase: str
) -> pl.DataFrame:
    """Filter to project finance exposures in a given phase."""
    if "sl_type" not in cols or "sl_project_phase" not in cols:
        return data.clear()
    return data.filter(
        (pl.col("sl_type") == "project_finance")
        & (pl.col("sl_project_phase") == phase)
    )


def _filter_re(
    data: pl.DataFrame,
    cols: set[str],
    *,
    property_type: str | None = None,
    materially_dependent: bool | None = None,
    is_sme: bool | None = None,
    is_adc: bool | None = None,
) -> pl.DataFrame:
    """Filter to real estate exposures with optional sub-criteria.

    Args:
        property_type: "residential" or "commercial" (None = any RE)
        materially_dependent: True/False filter on materially_dependent_on_property
        is_sme: True/False filter for SME sub-split (uses _filter_sme logic)
        is_adc: True/False filter on is_adc column
    """
    if "property_type" not in cols:
        return data.clear()

    result = data.filter(pl.col("property_type").is_not_null())

    if property_type is not None:
        result = result.filter(pl.col("property_type") == property_type)

    if materially_dependent is not None and "materially_dependent_on_property" in cols:
        result = result.filter(
            pl.col("materially_dependent_on_property") == materially_dependent
        )
    elif materially_dependent is not None:
        return data.clear()

    if is_sme is not None:
        sme_subset = _filter_sme(result, set(result.columns))
        if is_sme:
            result = sme_subset
        else:
            sme_refs = set(sme_subset["exposure_reference"].to_list()) if len(sme_subset) > 0 else set()
            if sme_refs:
                result = result.filter(~pl.col("exposure_reference").is_in(sme_refs))

    if is_adc is not None and "is_adc" in cols:
        result = result.filter(pl.col("is_adc") == is_adc)
    elif is_adc is True:
        return data.clear()

    return result


def _null_row(
    row_ref: str, row_name: str, column_refs: list[str]
) -> dict[str, object]:
    """Build a row dict with null values for all COREP columns."""
    row: dict[str, object] = {"row_ref": row_ref, "row_name": row_name}
    for ref in column_refs:
        row[ref] = None
    return row


def _safe_sum_eager(
    data: pl.DataFrame, cols: set[str], *col_names: str
) -> float:
    """Sum multiple columns from an eager DataFrame. Missing columns skipped."""
    total = 0.0
    for c in col_names:
        if c in cols:
            total += float(data[c].fill_null(0.0).sum())
    return total


def _col_sum_eager(
    data: pl.DataFrame, cols: set[str], col_name: str | None
) -> float | None:
    """Sum a single column from an eager DataFrame."""
    if col_name is None or col_name not in cols:
        return None
    return float(data[col_name].fill_null(0.0).sum())


def _sum_cols_eager(data: pl.DataFrame, cols: set[str], *col_names: str) -> float:
    """Sum multiple collateral-type columns, treating missing columns as 0."""
    total = 0.0
    for c in col_names:
        v = _col_sum_eager(data, cols, c)
        if v is not None:
            total += v
    return total


def _sum_by_protection_type(
    data: pl.DataFrame,
    cols: set[str],
    ptype: str,
    value_col: str = "guaranteed_portion",
) -> float | None:
    """Sum value_col for rows matching a specific protection_type.

    Returns None if protection_type column is absent. Returns 0.0 if column
    exists but no rows match.
    """
    if "protection_type" not in cols or value_col not in cols:
        return None
    filtered = data.filter(pl.col("protection_type") == ptype)
    if len(filtered) == 0:
        return 0.0
    return float(filtered[value_col].fill_null(0.0).sum())


def _compute_substitution_flows(
    full_df: pl.DataFrame,
    cols: set[str],
    ec_col: str,
) -> dict[str, dict[str, float]]:
    """Pre-compute CRM substitution outflows and inflows per exposure class.

    Outflow from class X: sum of guaranteed_portion where exposure_class == X
    but post_crm_exposure_class_guaranteed != X (leaving this class).

    Inflow to class X: sum of guaranteed_portion where
    post_crm_exposure_class_guaranteed == X but exposure_class != X
    (arriving from other classes).

    Returns dict mapping class name to {"outflow": float, "inflow": float}.
    """
    pre_col = _pick(cols, "pre_crm_exposure_class")
    post_col = _pick(cols, "post_crm_exposure_class_guaranteed")
    gp_col = _pick(cols, "guaranteed_portion")

    if pre_col is None or post_col is None or gp_col is None:
        return {}

    # Only consider rows where substitution actually occurs
    migrated = full_df.filter(
        (pl.col(gp_col) > 0) & (pl.col(pre_col) != pl.col(post_col))
    )
    if len(migrated) == 0:
        return {}

    result: dict[str, dict[str, float]] = {}

    # Outflows: grouped by pre_crm class (exposure leaving)
    outflows = migrated.group_by(pre_col).agg(
        pl.col(gp_col).sum().alias("outflow")
    )
    for row in outflows.iter_rows(named=True):
        ec = row[pre_col]
        result.setdefault(ec, {"outflow": 0.0, "inflow": 0.0})
        result[ec]["outflow"] = float(row["outflow"])

    # Inflows: grouped by post_crm class (exposure arriving)
    inflows = migrated.group_by(post_col).agg(
        pl.col(gp_col).sum().alias("inflow")
    )
    for row in inflows.iter_rows(named=True):
        ec = row[post_col]
        result.setdefault(ec, {"outflow": 0.0, "inflow": 0.0})
        result[ec]["inflow"] = float(row["inflow"])

    return result


def _compute_substitution_outflow(data: pl.DataFrame, cols: set[str]) -> float:
    """Compute substitution outflow from a data subset.

    Returns the sum of guaranteed_portion for rows where the guaranteed
    portion migrates to a different exposure class (pre != post).
    """
    pre_col = _pick(cols, "pre_crm_exposure_class")
    post_col = _pick(cols, "post_crm_exposure_class_guaranteed")
    gp_col = _pick(cols, "guaranteed_portion")

    if pre_col is None or post_col is None or gp_col is None:
        return 0.0

    migrated = data.filter(
        (pl.col(gp_col) > 0) & (pl.col(pre_col) != pl.col(post_col))
    )
    if len(migrated) == 0:
        return 0.0

    return float(migrated[gp_col].fill_null(0.0).sum())


def _compute_c07_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: list[str],
    *,
    substitution_inflow: float = 0.0,
) -> dict[str, float | None]:
    """Compute C 07.00 column values from a data subset.

    Maps pipeline columns to 4-digit COREP column refs. Columns without
    a pipeline source are set to None (to be populated in Phase 2/3).

    Args:
        substitution_inflow: Pre-computed inflow of guaranteed_portion from
            other exposure classes into this class. Only meaningful for the
            total row (0010); sub-rows pass 0.
    """
    if len(data) == 0:
        return {ref: None for ref in column_refs}

    ref_set = set(column_refs)
    values: dict[str, float | None] = {}

    # --- Exposure ---
    # 0010: Original exposure pre conversion factors
    values["0010"] = _safe_sum_eager(data, cols, "drawn_amount", "undrawn_amount")

    # 0030: (-) Value adjustments and provisions
    values["0030"] = _safe_sum_eager(
        data, cols, "scra_provision_amount", "gcra_provision_amount"
    )

    # 0035: (-) On-balance sheet netting (B3.1 col 0035, CRR Art. 195)
    values["0035"] = _col_sum_eager(data, cols, "on_bs_netting_amount")

    # 0040: Exposure net of value adjustments (and netting for B3.1)
    v_0010 = values["0010"] or 0.0
    v_0030 = values["0030"] or 0.0
    v_0035 = values.get("0035") or 0.0
    values["0040"] = v_0010 - v_0030 - v_0035

    # --- CRM Substitution: Unfunded ---
    # 0050: (-) Guarantees (excluding credit derivatives)
    guar_only = _sum_by_protection_type(data, cols, "guarantee")
    if guar_only is not None:
        values["0050"] = guar_only
    else:
        # Backward compatible: if protection_type not tracked, all are guarantees
        values["0050"] = _col_sum_eager(data, cols, "guaranteed_portion")

    # 0060: (-) Credit derivatives (CDS, CLN, TRS)
    cd_val = _sum_by_protection_type(data, cols, "credit_derivative")
    values["0060"] = cd_val if cd_val is not None else 0.0

    # --- CRM Substitution: Funded ---
    # 0070: (-) Financial collateral: Simple method
    # Comprehensive method is used; simple method not implemented → always 0
    values["0070"] = 0.0

    # 0080: (-) Other funded credit protection (non-financial collateral)
    values["0080"] = _sum_cols_eager(
        data, cols,
        "collateral_re_value", "collateral_receivables_value",
        "collateral_other_physical_value",
    )

    # --- CRM Substitution flows ---
    # 0090: (-) Substitution outflows — guaranteed portion leaving this class
    values["0090"] = _compute_substitution_outflow(data, cols)

    # 0100: Substitution inflows — guaranteed portion arriving from other classes
    values["0100"] = substitution_inflow if substitution_inflow else 0.0

    # --- Post-CRM ---
    # 0110: Net exposure after CRM substitution pre CCFs
    # Formula: 0040 - 0050 - 0060 - 0070 - 0080 - 0090 + 0100
    v_0040 = values.get("0040") or 0.0
    v_0050 = values.get("0050") or 0.0
    v_0060 = values.get("0060") or 0.0  # Credit derivatives — Phase 3B
    v_0070 = values.get("0070") or 0.0  # Fin collateral simple — Phase 3A
    v_0080 = values.get("0080") or 0.0  # Other funded protection — Phase 3A
    v_0090 = values.get("0090") or 0.0
    v_0100 = values.get("0100") or 0.0
    values["0110"] = v_0040 - v_0050 - v_0060 - v_0070 - v_0080 - v_0090 + v_0100

    # --- Financial Collateral Comprehensive ---
    # 0120: Volatility adjustment to exposure (He)
    # He = 0 for loan exposures; only non-zero for repo-style transactions
    values["0120"] = 0.0

    # 0130: (-) Financial collateral: adjusted value (Cvam)
    values["0130"] = _col_sum_eager(data, cols, "collateral_adjusted_value")

    # 0140: (-) Of which: volatility and maturity adjustments
    # The vol+mat adjustment = market_value - adjusted_value
    v_mv = _col_sum_eager(data, cols, "collateral_market_value")
    v_cv = values["0130"] or 0.0
    values["0140"] = (v_mv - v_cv) if v_mv is not None else None

    # 0150: Fully adjusted exposure value (E*)
    # E* = max(0, col_0110 - col_0130) under comprehensive method (He=0 for loans)
    v_0110 = values.get("0110") or 0.0
    v_0130 = values.get("0130") or 0.0
    values["0150"] = max(0.0, v_0110 - v_0130)

    # --- CCF Breakdown --- Phase 2C
    # Off-BS exposures grouped by ccf_applied into COREP CCF buckets.
    # CRR: 0%→0160, 20%→0170, 50%→0180, 100%→0190
    # B3.1: 10%→0160, 20%→0170, 40%→0171, 50%→0180, 100%→0190
    if "ccf_applied" in cols:
        off_bs = _filter_off_bs(data, cols) if "bs_type" in cols else data
        is_b31 = "0171" in ref_set
        ccf_map: dict[float, str] = (
            {0.1: "0160", 0.2: "0170", 0.4: "0171", 0.5: "0180", 1.0: "0190"}
            if is_b31
            else {0.0: "0160", 0.2: "0170", 0.5: "0180", 1.0: "0190"}
        )
        # Initialise all CCF columns to 0
        for ref in ("0160", "0170", "0171", "0180", "0190"):
            values[ref] = 0.0
        if len(off_bs) > 0 and ead_col in cols:
            for ccf_val, col_ref in ccf_map.items():
                bucket = off_bs.filter(pl.col("ccf_applied").round(4) == round(ccf_val, 4))
                if len(bucket) > 0:
                    values[col_ref] = float(bucket[ead_col].fill_null(0.0).sum())
    else:
        for ref in ("0160", "0170", "0171", "0180", "0190"):
            values[ref] = None

    # --- Final ---
    # 0200: Exposure value (EAD)
    values["0200"] = _col_sum_eager(data, cols, ead_col)

    # 0210: Of which: arising from CCR — Phase 3K
    values["0210"] = None

    # 0211: Of which: CCR excl CCP — Phase 3K
    values["0211"] = None

    # --- RWEA ---
    # 0215: RWEA pre supporting factors (CRR only)
    rwa_pre = _col_sum_eager(data, cols, "rwa_before_sme_factor")
    values["0215"] = rwa_pre if rwa_pre is not None else _col_sum_eager(data, cols, rwa_col)

    # 0216: (-) SME supporting factor adjustment (CRR only)
    if "sme_supporting_factor_applied" in cols and "rwa_before_sme_factor" in cols:
        sme_data = data.filter(pl.col("sme_supporting_factor_applied") == True)  # noqa: E712
        if len(sme_data) > 0:
            pre = float(sme_data["rwa_before_sme_factor"].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0216"] = pre - post
        else:
            values["0216"] = 0.0
    else:
        values["0216"] = None

    # 0217: (-) Infrastructure supporting factor adjustment (CRR only)
    if "infrastructure_factor_applied" in cols and "rwa_before_sme_factor" in cols:
        infra_data = data.filter(pl.col("infrastructure_factor_applied") == True)  # noqa: E712
        if len(infra_data) > 0:
            pre = float(infra_data["rwa_before_sme_factor"].fill_null(0.0).sum())
            post = float(infra_data[rwa_col].fill_null(0.0).sum())
            values["0217"] = pre - post
        else:
            values["0217"] = 0.0
    else:
        values["0217"] = None

    # 0220: RWEA (after supporting factors for CRR, plain for B3.1)
    values["0220"] = _col_sum_eager(data, cols, rwa_col)

    # 0230: Of which: with ECAI credit assessment
    if "sa_cqs" in cols and rwa_col in cols:
        ecai_data = data.filter(pl.col("sa_cqs").is_not_null())
        values["0230"] = float(ecai_data[rwa_col].fill_null(0.0).sum())
    else:
        values["0230"] = None

    # 0235: Of which: without ECAI credit assessment (B3.1 only) — Phase 2E
    if "sa_cqs" in cols and rwa_col in cols:
        no_ecai = data.filter(pl.col("sa_cqs").is_null())
        values["0235"] = float(no_ecai[rwa_col].fill_null(0.0).sum())
    else:
        values["0235"] = None

    # 0240: Of which: credit assessment derived from central govt
    values["0240"] = None

    # Filter to only refs present in this framework's column set
    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _compute_c08_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: list[str],
    *,
    substitution_inflow: float = 0.0,
) -> dict[str, float | None]:
    """Compute C 08.01/08.02 column values from a data subset.

    Maps pipeline columns to 4-digit COREP column refs. Weighted averages
    are computed for PD, LGD, and maturity. Maturity is converted from
    years to days (COREP col 0250 requires days).

    Args:
        substitution_inflow: Pre-computed inflow of guaranteed_portion from
            other exposure classes into this class. Only meaningful for the
            total row (0010); sub-rows pass 0.
    """
    if len(data) == 0:
        return {ref: None for ref in column_refs}

    values: dict[str, float | None] = {}
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0

    # --- Internal Rating ---
    # 0010: PD assigned (EAD-weighted average)
    if "irb_pd_floored" in cols and ead_sum > 0:
        pd_x_ead = float(
            (data["irb_pd_floored"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0010"] = pd_x_ead / ead_sum
    else:
        values["0010"] = None

    # --- Exposure ---
    # 0020: Original exposure pre conversion factors
    values["0020"] = _safe_sum_eager(data, cols, "drawn_amount", "undrawn_amount")

    # 0030: Of which: large financial sector entities — Phase 2F
    lfse_data = _filter_lfse(data, cols)
    if lfse_data is not None and len(lfse_data) > 0:
        values["0030"] = _safe_sum_eager(lfse_data, set(lfse_data.columns),
                                         "drawn_amount", "undrawn_amount")
    else:
        values["0030"] = 0.0 if "apply_fi_scalar" in cols else None

    # 0035: (-) On-BS netting (B3.1 col 0035, CRR Art. 195)
    values["0035"] = _col_sum_eager(data, cols, "on_bs_netting_amount")

    # --- CRM Substitution ---
    # 0040: (-) Guarantees (excluding credit derivatives)
    guar_only_irb = _sum_by_protection_type(data, cols, "guarantee")
    if guar_only_irb is not None:
        values["0040"] = guar_only_irb
    else:
        values["0040"] = _col_sum_eager(data, cols, "guaranteed_portion")

    # 0050: (-) Credit derivatives (CDS, CLN, TRS)
    cd_val_irb = _sum_by_protection_type(data, cols, "credit_derivative")
    values["0050"] = cd_val_irb if cd_val_irb is not None else 0.0

    # 0060: (-) Other funded credit protection (non-financial collateral)
    values["0060"] = _sum_cols_eager(
        data, cols,
        "collateral_re_value", "collateral_receivables_value",
        "collateral_other_physical_value",
    )

    # 0070: (-) Substitution outflows — guaranteed portion leaving this class
    values["0070"] = _compute_substitution_outflow(data, cols)

    # 0080: Substitution inflows — guaranteed portion arriving from other classes
    values["0080"] = substitution_inflow if substitution_inflow else 0.0

    # --- Post-CRM ---
    # 0090: Exposure after CRM substitution pre CCFs
    # Formula: 0020 - 0040 - 0050 - 0060 - 0070 + 0080
    v_c08_0020 = values.get("0020") or 0.0
    v_c08_0040 = values.get("0040") or 0.0
    v_c08_0050 = values.get("0050") or 0.0
    v_c08_0060 = values.get("0060") or 0.0
    v_c08_0070 = values.get("0070") or 0.0
    v_c08_0080 = values.get("0080") or 0.0
    values["0090"] = (
        v_c08_0020 - v_c08_0040 - v_c08_0050 - v_c08_0060 - v_c08_0070 + v_c08_0080
    )

    # 0100: Of which: off balance sheet
    off_bs = _filter_off_bs(data, cols)
    if len(off_bs) > 0:
        values["0100"] = _col_sum_eager(off_bs, set(off_bs.columns), ead_col)
    else:
        values["0100"] = 0.0

    # --- Slotting FCCM (B3.1 only, 0101-0104) --- Phase 3A
    for ref in ("0101", "0102", "0103", "0104"):
        values[ref] = None

    # --- Exposure Value ---
    # 0110: Exposure value (EAD)
    values["0110"] = _col_sum_eager(data, cols, ead_col)

    # 0120: Of which: off balance sheet — Phase 2B
    values["0120"] = None

    # 0125: Of which: defaulted (B3.1)
    defaulted = _filter_defaulted(data, cols)
    if len(defaulted) > 0:
        values["0125"] = _col_sum_eager(defaulted, set(defaulted.columns), ead_col)
    else:
        values["0125"] = 0.0

    # 0130: Of which: arising from CCR — Phase 3K
    values["0130"] = None

    # 0140: Of which: LFSE — Phase 2F
    if lfse_data is not None and len(lfse_data) > 0:
        values["0140"] = _col_sum_eager(lfse_data, set(lfse_data.columns), ead_col)
    else:
        values["0140"] = 0.0 if "apply_fi_scalar" in cols else None

    # --- CRM in LGD estimates (0150-0210) ---
    # 0150: Unfunded credit protection: Guarantees (excluding credit derivatives)
    guar_lgd = _sum_by_protection_type(data, cols, "guarantee")
    if guar_lgd is not None:
        values["0150"] = guar_lgd
    else:
        values["0150"] = _col_sum_eager(data, cols, "guaranteed_portion")

    # 0160: Unfunded credit protection: Credit derivatives
    cd_lgd = _sum_by_protection_type(data, cols, "credit_derivative")
    values["0160"] = cd_lgd if cd_lgd is not None else 0.0

    # 0170: Other funded credit protection (catch-all not in 0180-0210)
    values["0170"] = 0.0
    # 0171: Of which: cash on deposit (with third-party institutions)
    values["0171"] = 0.0
    # 0172: Of which: life insurance policies pledged
    values["0172"] = 0.0
    # 0173: Of which: instruments held by third party
    values["0173"] = 0.0

    # 0180: Eligible financial collateral
    values["0180"] = _col_sum_eager(data, cols, "collateral_financial_value")
    # 0190: Real estate collateral
    values["0190"] = _col_sum_eager(data, cols, "collateral_re_value")
    # 0200: Other physical collateral
    values["0200"] = _col_sum_eager(data, cols, "collateral_other_physical_value")
    # 0210: Receivables
    values["0210"] = _col_sum_eager(data, cols, "collateral_receivables_value")

    # 0220: Double default (CRR only) — Phase 3E
    values["0220"] = None

    # --- Parameters ---
    # 0230: Exposure-weighted average LGD (%)
    lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
    if lgd_col is not None and ead_sum > 0:
        lgd_x_ead = float(
            (data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0230"] = lgd_x_ead / ead_sum
    else:
        values["0230"] = None

    # 0240: EAD-weighted average LGD for LFSE — Phase 2F
    if lfse_data is not None and len(lfse_data) > 0:
        lfse_cols = set(lfse_data.columns)
        lfse_lgd_col = _pick(lfse_cols, "irb_lgd_floored", "irb_lgd_original")
        lfse_ead_sum = float(lfse_data[ead_col].fill_null(0.0).sum()) if ead_col in lfse_cols else 0.0
        if lfse_lgd_col is not None and lfse_ead_sum > 0:
            lgd_x_ead = float(
                (lfse_data[lfse_lgd_col].fill_null(0.0) * lfse_data[ead_col].fill_null(0.0)).sum()
            )
            values["0240"] = lgd_x_ead / lfse_ead_sum
        else:
            values["0240"] = None
    else:
        values["0240"] = 0.0 if "apply_fi_scalar" in cols else None

    # 0250: Exposure-weighted average maturity (DAYS, not years)
    if "irb_maturity_m" in cols and ead_sum > 0:
        m_x_ead = float(
            (
                data["irb_maturity_m"].fill_null(0.0) * data[ead_col].fill_null(0.0)
            ).sum()
        )
        values["0250"] = (m_x_ead / ead_sum) * 365.0  # Convert years to days
    else:
        values["0250"] = None

    # --- RWEA ---
    # 0251-0254: Post-model adjustments (B3.1) — Phase 3F
    for ref in ("0251", "0252", "0253", "0254"):
        values[ref] = None

    # 0255: RWEA pre supporting factors (CRR only)
    rwa_pre = _col_sum_eager(data, cols, "rwa_before_sme_factor")
    values["0255"] = rwa_pre if rwa_pre is not None else _col_sum_eager(data, cols, rwa_col)

    # 0256: (-) SME supporting factor adjustment (CRR only)
    if "sme_supporting_factor_applied" in cols and "rwa_before_sme_factor" in cols:
        sme_data = data.filter(pl.col("sme_supporting_factor_applied") == True)  # noqa: E712
        if len(sme_data) > 0:
            pre = float(sme_data["rwa_before_sme_factor"].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0256"] = pre - post
        else:
            values["0256"] = 0.0
    else:
        values["0256"] = None

    # 0257: (-) Infrastructure supporting factor adjustment (CRR only)
    if "infrastructure_factor_applied" in cols and "rwa_before_sme_factor" in cols:
        infra_data = data.filter(pl.col("infrastructure_factor_applied") == True)  # noqa: E712
        if len(infra_data) > 0:
            pre = float(infra_data["rwa_before_sme_factor"].fill_null(0.0).sum())
            post = float(infra_data[rwa_col].fill_null(0.0).sum())
            values["0257"] = pre - post
        else:
            values["0257"] = 0.0
    else:
        values["0257"] = None

    # 0260: RWEA total
    values["0260"] = _col_sum_eager(data, cols, rwa_col)

    # 0265: Of which: defaulted RWEA (B3.1)
    if len(defaulted) > 0:
        values["0265"] = _col_sum_eager(defaulted, set(defaulted.columns), rwa_col)
    else:
        values["0265"] = 0.0

    # 0270: Of which: LFSE RWEA — Phase 2F
    if lfse_data is not None and len(lfse_data) > 0:
        values["0270"] = _col_sum_eager(lfse_data, set(lfse_data.columns), rwa_col)
    else:
        values["0270"] = 0.0 if "apply_fi_scalar" in cols else None

    # 0275-0276: Output floor (B3.1) — Phase 2D
    # 0275: Non-modelled (SA-equivalent) exposure value
    values["0275"] = _col_sum_eager(data, cols, ead_col)
    # 0276: Non-modelled (SA-equivalent) RWEA
    sa_rwa_col = _pick(cols, "sa_equivalent_rwa", "rwa_sa_equivalent", "sa_rwa")
    values["0276"] = _col_sum_eager(data, cols, sa_rwa_col) if sa_rwa_col else None

    # --- Memorandum ---
    # 0280: Expected loss amount
    values["0280"] = _col_sum_eager(data, cols, "irb_expected_loss")

    # 0281-0282: EL adjustments (B3.1) — Phase 3F
    values["0281"] = None
    values["0282"] = None

    # 0290: (-) Value adjustments and provisions
    prov = _safe_sum_eager(
        data, cols, "scra_provision_amount", "gcra_provision_amount"
    )
    if prov == 0.0:
        # Fall back to provision_held
        held = _col_sum_eager(data, cols, "provision_held")
        values["0290"] = held if held is not None else prov
    else:
        values["0290"] = prov

    # 0300: Number of obligors
    if "counterparty_reference" in cols:
        values["0300"] = float(data["counterparty_reference"].n_unique())
    else:
        values["0300"] = float(len(data))

    # 0310: Pre-credit derivatives RWEA
    # Total RWEA including credit-derivative-protected exposures at pre-substitution RW
    # Approximation: rwa_final already includes substitution benefit, so pre-CD RWEA
    # = rwa_final + the RWA benefit from credit derivatives. Without separate pre/post
    # tracking per protection type, use total RWEA as a lower bound.
    cd_rwa = _sum_by_protection_type(data, cols, "credit_derivative", rwa_col)
    if cd_rwa is not None and cd_rwa > 0:
        # There are credit-derivative-protected exposures — their RWEA already
        # reflects the substitution benefit. Pre-CD RWEA = total RWEA (since the
        # benefit is embedded in rwa_final via guarantor RW substitution).
        values["0310"] = _col_sum_eager(data, cols, rwa_col)
    else:
        # No credit derivatives: pre-CD RWEA = total RWEA
        total_rwa = _col_sum_eager(data, cols, rwa_col)
        values["0310"] = total_rwa

    # Filter to only refs in this framework's column set
    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _compute_rw_section_rows(
    class_data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: list[str],
    rw_bands: list[tuple[float, str]],
    rw_col: str | None,
) -> dict[str, dict[str, float | None]]:
    """Compute C 07.00 column values for each risk weight band.

    Returns a dict mapping band label (e.g., "100%") to column values.
    Exposures not matching any standard band go to "Other risk weights".
    """
    if rw_col is None or rw_col not in cols or len(class_data) == 0:
        return {}

    # Assign risk weight bands
    band_expr = pl.lit("Other risk weights")
    for rw_value, label in reversed(rw_bands):
        band_expr = (
            pl.when(pl.col(rw_col).round(4) == round(rw_value, 4))
            .then(pl.lit(label))
            .otherwise(band_expr)
        )

    banded = class_data.with_columns(band_expr.alias("_rw_band"))

    result: dict[str, dict[str, float | None]] = {}
    for label in banded["_rw_band"].unique().to_list():
        band_data = banded.filter(pl.col("_rw_band") == label).drop("_rw_band")
        if len(band_data) > 0:
            result[label] = _compute_c07_values(
                band_data, cols, ead_col, rwa_col, column_refs
            )

    return result
