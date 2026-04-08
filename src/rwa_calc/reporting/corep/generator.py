"""
COREP template generator for credit risk reporting.

Pipeline position:
    CalculationResponse -> COREPGenerator -> COREPTemplateBundle -> Excel

Key responsibilities:
- Generate per-exposure-class COREP template DataFrames with row sections
- Populate COREP columns from pipeline calculation results using 4-digit refs
- Generate C 08.04 / OF 08.04 RWEA flow statements per IRB exposure class
- Generate C 08.05 / OF 08.05 PD backtesting per IRB exposure class
- Generate C 08.06 / OF 08.06 specialised lending slotting per SL type
- Generate C 08.07 / OF 08.07 IRB scope of use (portfolio-level)
- Generate OF 02.01 output floor comparison (Basel 3.1, portfolio-level)
- Generate C 09.01 / OF 09.01 geographical breakdown SA (per country)
- Generate C 09.02 / OF 09.02 geographical breakdown IRB (per country)
- Support both CRR and Basel 3.1 framework variants
- Export to Excel with per-class sheet structure

Why: COREP templates are the regulatory reporting format mandated by
the PRA for quarterly capital adequacy returns. Each template is submitted
once per exposure class with a fixed multi-section row structure. This module
reshapes exposure-level results into that fixed layout.

References:
- Regulation (EU) 2021/451, Annex I/II (CRR templates)
- CRR Art. 111-134 (SA), Art. 142-191 (IRB)
- PRA PS1/26 (Basel 3.1 reporting amendments)
- PRA PS1/26, Annex I/II (Basel 3.1 OF templates)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.corep.templates import (
    B31_C02_00_COLUMN_REFS,
    C02_00_CREDIT_RISK_ROWS,
    C02_00_SA_CLASS_MAP,
    C08_03_PD_RANGES,
    C08_04_ROWS,
    C08_06_CATEGORY_MAP,
    C08_07_CRR_RETAIL_CLASSES,
    C08_07_IRB_APPROACHES,
    C09_01_SA_CLASS_MAP,
    CRR_C02_00_COLUMN_REFS,
    IRB_EXPOSURE_CLASS_ROWS,
    OF_02_01_COLUMN_REFS,
    OF_02_01_ROW_SECTIONS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    COREPRow,
    get_c02_00_row_sections,
    get_c07_columns,
    get_c08_02_columns,
    get_c08_03_columns,
    get_c08_04_columns,
    get_c08_05_columns,
    get_c08_06_columns,
    get_c08_06_rows,
    get_c08_06_sl_types,
    get_c08_07_columns,
    get_c08_07_rows,
    get_c08_columns,
    get_c09_01_columns,
    get_c09_01_rows,
    get_c09_02_columns,
    get_c09_02_rows,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)

if TYPE_CHECKING:
    from rwa_calc.api.export import ExportResult
    from rwa_calc.api.models import CalculationResponse
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import OutputFloorConfig

logger = logging.getLogger(__name__)


# =============================================================================
# COREP TEMPLATE BUNDLE
# =============================================================================


@dataclass(frozen=True)
class COREPTemplateBundle:
    """Bundle of generated COREP template DataFrames.

    Each per-class template is a dict keyed by exposure class value, where
    each value is a DataFrame with row sections and 4-digit COREP column refs.

    C 07.00 (SA): One DataFrame per SA exposure class, with 5 row sections.
    C 08.01 (IRB): One DataFrame per IRB exposure class, with 3 row sections.
    C 08.02 (IRB by PD grade): One DataFrame per IRB exposure class.
    C 08.03 (IRB PD ranges): One DataFrame per IRB exposure class, 17 fixed
        regulatory PD range buckets, 11 columns. Slotting excluded.
    C 08.04 (IRB RWEA flow): One DataFrame per IRB exposure class, 9 rows
        (opening RWEA, 7 movement drivers, closing RWEA), 1 column (RWEA).
        Closing RWEA populated from pipeline; opening and drivers require
        prior-period data. Slotting excluded.
    C 08.05 (IRB PD backtesting): One DataFrame per IRB exposure class, 17
        fixed PD range buckets, 5 columns. Validates PD model calibration by
        comparing assigned PDs against observed default rates. Slotting excluded.
    C 08.06 (IRB slotting): One DataFrame per SL type, rows by slotting
        category (Strong-Default) × maturity band (< 2.5yr / ≥ 2.5yr).
        10 columns (CRR) / 11 columns (Basel 3.1 adds FCCM deduction).
    C 08.07 / OF 08.07 (IRB scope of use): Single DataFrame showing IRB vs SA
        coverage per exposure class. 5 columns (CRR) / 18 columns (Basel 3.1
        adds RWEA decomposition and materiality). CRR: 17 rows by Art. 147(2)
        exposure class. Basel 3.1: 11 rows by Art. 147B roll-out class.
    OF 02.01 (Output Floor comparison): Single DataFrame, 8 risk-type rows,
        4 columns (modelled RWA, SA RWA, U-TREA, S-TREA). Basel 3.1 only.
    C 02.00 / OF 02.00 (Own Funds Requirements): Single DataFrame aggregating
        RWEA across all risk types. CRR: 1 column. Basel 3.1: 3 columns
        (all approaches, SA-only, output floor). Includes output floor
        indicator rows (0034-0036) under Basel 3.1.
    C 09.01 / OF 09.01 (Geo breakdown SA): One DataFrame per country code,
        rows by SA exposure class. 13 columns (CRR) / 10 columns (Basel 3.1
        removes supporting factors). Includes total-level aggregation.
    C 09.02 / OF 09.02 (Geo breakdown IRB): One DataFrame per country code,
        rows by IRB exposure class. 17 columns (CRR) / 15 columns (Basel 3.1
        adds defaulted EV, removes supporting factors).

    Why: COREP templates are submitted per exposure class to the regulator.
    Each class gets a fixed row structure (totals, exposure types, risk weights,
    CIU approach, memorandum) and fixed column structure (the credit risk
    waterfall from original exposure through CRM to final RWEA).
    """

    c07_00: dict[str, pl.DataFrame]
    c08_01: dict[str, pl.DataFrame]
    c08_02: dict[str, pl.DataFrame]
    c08_03: dict[str, pl.DataFrame] = field(default_factory=dict)
    c08_04: dict[str, pl.DataFrame] = field(default_factory=dict)
    c08_05: dict[str, pl.DataFrame] = field(default_factory=dict)
    c08_06: dict[str, pl.DataFrame] = field(default_factory=dict)
    c08_07: pl.DataFrame | None = None
    of_02_01: pl.DataFrame | None = None
    c_02_00: pl.DataFrame | None = None
    c09_01: dict[str, pl.DataFrame] = field(default_factory=dict)
    c09_02: dict[str, pl.DataFrame] = field(default_factory=dict)
    framework: str = "CRR"
    reporting_basis: str | None = None
    institution_type: str | None = None
    errors: list[str] = field(default_factory=list)


# =============================================================================
# COREP GENERATOR
# =============================================================================


class COREPGenerator:
    """Generates COREP credit risk templates from RWA calculation results.

    Produces per-exposure-class DataFrames for C 07.00 (SA), C 08.01 (IRB totals),
    C 08.02 (IRB PD grade breakdown), C 08.03 (IRB PD ranges), C 08.04
    (IRB RWEA flow statements), C 08.05 (PD backtesting), C 08.06
    (IRB specialised lending slotting), C 08.07 / OF 08.07 (IRB scope of use),
    C 09.01 / OF 09.01 (Geographical Breakdown SA), and C 09.02 / OF 09.02
    (Geographical Breakdown IRB) with correct 4-digit COREP column references
    and multi-section row structure.

    Usage:
        generator = COREPGenerator()
        bundle = generator.generate(response)
        bundle = generator.generate_from_lazyframe(results_lf, framework="CRR")
    """

    def generate(
        self,
        response: CalculationResponse,
        *,
        output_floor_summary: OutputFloorSummary | None = None,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> COREPTemplateBundle:
        """Generate all COREP templates from a CalculationResponse."""
        results_lf = response.scan_results()
        return self.generate_from_lazyframe(
            results_lf,
            framework=response.framework,
            output_floor_summary=output_floor_summary,
            output_floor_config=output_floor_config,
        )

    def generate_from_lazyframe(
        self,
        results: pl.LazyFrame,
        *,
        framework: str = "CRR",
        output_floor_summary: OutputFloorSummary | None = None,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> COREPTemplateBundle:
        """Generate all COREP templates from a results LazyFrame.

        Primary entry point for direct pipeline integration. Produces
        per-exposure-class DataFrames with correct row sections and
        4-digit COREP column references.

        Args:
            results: Combined results LazyFrame with all approaches
            framework: Regulatory framework ("CRR" or "BASEL_3_1")
            output_floor_summary: Optional floor summary for OF 02.00
                rows 0035 (multiplier) and 0036 (OF-ADJ).
            output_floor_config: Optional floor config for reporting
                basis conditionality (Art. 92 para 2A). When provided,
                gates floor indicator rows and materiality columns on
                entity-type applicability and reporting basis.
        """
        errors: list[str] = []
        cols = _available_columns(results)

        # SA templates (C 07.00)
        sa_data = _filter_by_approach(results, "standardised", cols)
        c07_00 = self._generate_all_c07(sa_data, cols, framework, errors)

        # IRB templates (C 08.01, C 08.02, C 08.03, C 08.06)
        irb_data = _filter_by_irb_approach(results, cols)
        c08_01 = self._generate_all_c08_01(irb_data, cols, framework, errors)
        c08_02 = self._generate_all_c08_02(irb_data, cols, framework, errors)
        c08_03 = self._generate_all_c08_03(irb_data, cols, framework, errors)
        c08_04 = self._generate_all_c08_04(irb_data, cols, framework, errors)
        c08_05 = self._generate_all_c08_05(irb_data, cols, framework, errors)
        c08_06 = self._generate_all_c08_06(irb_data, cols, framework, errors)

        # C 08.07 / OF 08.07 — IRB scope of use
        c08_07 = self._generate_c08_07(
            results,
            cols,
            framework,
            errors,
            output_floor_config=output_floor_config,
        )

        # OF 02.01 — Output floor comparison (Basel 3.1 only)
        of_02_01 = self._generate_of_02_01(
            results,
            cols,
            framework,
            errors,
            output_floor_config=output_floor_config,
        )

        # C 02.00 / OF 02.00 — Own Funds Requirements
        c_02_00 = self._generate_c_02_00(
            results,
            cols,
            framework,
            errors,
            output_floor_summary=output_floor_summary,
            output_floor_config=output_floor_config,
        )

        # C 09.01 / OF 09.01 — Geographical Breakdown SA
        c09_01 = self._generate_all_c09_01(sa_data, cols, framework, errors)

        # C 09.02 / OF 09.02 — Geographical Breakdown IRB
        c09_02 = self._generate_all_c09_02(irb_data, cols, framework, errors)

        # Extract reporting_basis / institution_type for bundle metadata
        _rb = None
        _it = None
        if output_floor_config is not None:
            _rb = (
                output_floor_config.reporting_basis.value
                if output_floor_config.reporting_basis is not None
                else None
            )
            _it = (
                output_floor_config.institution_type.value
                if output_floor_config.institution_type is not None
                else None
            )

        return COREPTemplateBundle(
            c07_00=c07_00,
            c08_01=c08_01,
            c08_02=c08_02,
            c08_03=c08_03,
            c08_04=c08_04,
            c08_05=c08_05,
            c08_06=c08_06,
            c08_07=c08_07,
            of_02_01=of_02_01,
            c_02_00=c_02_00,
            c09_01=c09_01,
            c09_02=c09_02,
            framework=framework,
            reporting_basis=_rb,
            institution_type=_it,
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
            msg = "COREP Excel export requires 'xlsxwriter'. Install with: uv add xlsxwriter"
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
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_03, "C 08.03", IRB_EXPOSURE_CLASS_ROWS
            )
            c08_04_prefix = "OF 08.04" if bundle.framework == "BASEL_3_1" else "C 08.04"
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_04, c08_04_prefix, IRB_EXPOSURE_CLASS_ROWS
            )
            c08_05_prefix = "OF 08.05" if bundle.framework == "BASEL_3_1" else "C 08.05"
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_05, c08_05_prefix, IRB_EXPOSURE_CLASS_ROWS
            )
            sl_type_names = get_c08_06_sl_types(bundle.framework)
            sl_class_map = {k: (k, v) for k, v in sl_type_names.items()}
            total_rows += self._write_template_sheets(
                workbook, bundle.c08_06, "C 08.06", sl_class_map
            )
            if bundle.c08_07 is not None:
                c08_07_prefix = "OF 08.07" if bundle.framework == "BASEL_3_1" else "C 08.07"
                total_rows += self._write_single_template_sheet(
                    workbook, bundle.c08_07, c08_07_prefix
                )
            if bundle.of_02_01 is not None:
                total_rows += self._write_single_template_sheet(
                    workbook, bundle.of_02_01, "OF 02.01"
                )
            if bundle.c_02_00 is not None:
                c02_prefix = "OF 02.00" if bundle.framework == "BASEL_3_1" else "C 02.00"
                total_rows += self._write_single_template_sheet(
                    workbook, bundle.c_02_00, c02_prefix
                )
            # C 09.01 / OF 09.01 — Geographical Breakdown SA
            if bundle.c09_01:
                c09_01_prefix = "OF 09.01" if bundle.framework == "BASEL_3_1" else "C 09.01"
                for country, df in sorted(bundle.c09_01.items()):
                    if len(df) > 0:
                        sheet = f"{c09_01_prefix} - {country}"
                        sheet = re.sub(r"[\[\]:*?/\\]", "", sheet)[:31]
                        df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
                        total_rows += len(df)
            # C 09.02 / OF 09.02 — Geographical Breakdown IRB
            if bundle.c09_02:
                c09_02_prefix = "OF 09.02" if bundle.framework == "BASEL_3_1" else "C 09.02"
                for country, df in sorted(bundle.c09_02.items()):
                    if len(df) > 0:
                        sheet = f"{c09_02_prefix} - {country}"
                        sheet = re.sub(r"[\[\]:*?/\\]", "", sheet)[:31]
                        df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
                        total_rows += len(df)
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
                raw_sheet = f"{prefix} - {display}"
                sheet = re.sub(r"[\[\]:*?/\\]", "", raw_sheet)[:31]
                df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
                total += len(df)
        return total

    @staticmethod
    def _write_single_template_sheet(
        workbook: object,
        df: pl.DataFrame,
        sheet_name: str,
    ) -> int:
        """Write a single DataFrame as an Excel sheet. Returns rows written."""
        if len(df) == 0:
            return 0
        sheet = re.sub(r"[\[\]:*?/\\]", "", sheet_name)[:31]
        df.write_excel(workbook=workbook, worksheet=sheet, autofit=True)
        return len(df)

    # =========================================================================
    # C 08.07 / OF 08.07 — IRB Scope of Use
    # =========================================================================

    def _generate_c08_07(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
        *,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> pl.DataFrame | None:
        """Generate C 08.07 (CRR) / OF 08.07 (Basel 3.1) IRB scope of use.

        Shows the split of exposures between SA and IRB approaches per
        exposure class. CRR: 5 columns (exposure values + coverage %).
        Basel 3.1: 18 columns (adds RWEA decomposition + materiality).

        Uses full results LazyFrame (not just IRB data) because the template
        reports both SA and IRB coverage.

        Materiality columns (0160-0180) are consolidated-basis only per
        Art. 150(1A). When ``output_floor_config`` provides a reporting
        basis, these columns are gated on ``CONSOLIDATED`` basis.

        References:
        - CRR Art. 147(2), Art. 148, Art. 150
        - PRA PS1/26 Art. 147B, Art. 150(1A)
        """
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        approach_col = _pick(cols, "approach_applied", "approach")
        ec_col = _pick(cols, "exposure_class")

        if ead_col is None or approach_col is None or ec_col is None:
            missing = [
                n
                for n, v in [("ead", ead_col), ("approach", approach_col), ("class", ec_col)]
                if v is None
            ]
            errors.append(f"C 08.07: missing columns: {', '.join(missing)}")
            return None

        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        # Collect grouped data: (exposure_class, approach_applied) -> (sum_ead, sum_rwa)
        agg_exprs = [pl.col(ead_col).sum().alias("_sum_ead")]
        if rwa_col:
            agg_exprs.append(pl.col(rwa_col).sum().alias("_sum_rwa"))

        grouped = results.group_by([ec_col, approach_col]).agg(agg_exprs).collect()

        if len(grouped) == 0:
            return None

        # Build lookup: (exposure_class, is_irb) -> (sum_ead, sum_rwa)
        class_irb_ead: dict[str, float] = {}
        class_sa_ead: dict[str, float] = {}
        class_irb_rwa: dict[str, float] = {}
        class_sa_rwa: dict[str, float] = {}

        for row in grouped.iter_rows(named=True):
            ec = row[ec_col]
            approach = row[approach_col]
            ead = row["_sum_ead"] or 0.0
            rwa_val = row.get("_sum_rwa", 0.0) or 0.0

            if approach in C08_07_IRB_APPROACHES:
                class_irb_ead[ec] = class_irb_ead.get(ec, 0.0) + ead
                class_irb_rwa[ec] = class_irb_rwa.get(ec, 0.0) + rwa_val
            else:
                class_sa_ead[ec] = class_sa_ead.get(ec, 0.0) + ead
                class_sa_rwa[ec] = class_sa_rwa.get(ec, 0.0) + rwa_val

        column_defs = get_c08_07_columns(framework)
        column_refs = [c.ref for c in column_defs]
        row_defs = get_c08_07_rows(framework)

        is_b31 = framework == "BASEL_3_1"
        # Materiality columns (0160-0180) are consolidated-basis only
        _is_consolidated = (
            output_floor_config is not None
            and output_floor_config.reporting_basis is not None
            and output_floor_config.reporting_basis.value == "consolidated"
        )
        rows: list[dict[str, object]] = []

        for row_ref, row_name, ec_value in row_defs:
            values: dict[str, object] = {}

            if row_name == "Total" or row_name == "Aggregate immateriality %":
                if row_name == "Total":
                    irb_ead = sum(class_irb_ead.values())
                    sa_ead = sum(class_sa_ead.values())
                    irb_rwa = sum(class_irb_rwa.values())
                    sa_rwa = sum(class_sa_rwa.values())
                    values = self._compute_c08_07_values(
                        irb_ead,
                        sa_ead,
                        irb_rwa,
                        sa_rwa,
                        column_refs,
                        is_b31,
                        is_consolidated=_is_consolidated,
                    )
                else:
                    # Materiality row: null (requires institutional config)
                    values = dict.fromkeys(column_refs)
            elif ec_value is not None:
                # Direct exposure class mapping
                irb_ead = class_irb_ead.get(ec_value, 0.0)
                sa_ead = class_sa_ead.get(ec_value, 0.0)
                irb_rwa = class_irb_rwa.get(ec_value, 0.0)
                sa_rwa = class_sa_rwa.get(ec_value, 0.0)
                values = self._compute_c08_07_values(
                    irb_ead,
                    sa_ead,
                    irb_rwa,
                    sa_rwa,
                    column_refs,
                    is_b31,
                    is_consolidated=_is_consolidated,
                )
            elif row_ref == "0090":
                # CRR "Retail" aggregate row
                irb_ead = sum(class_irb_ead.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES)
                sa_ead = sum(class_sa_ead.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES)
                irb_rwa = sum(class_irb_rwa.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES)
                sa_rwa = sum(class_sa_rwa.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES)
                values = self._compute_c08_07_values(
                    irb_ead,
                    sa_ead,
                    irb_rwa,
                    sa_rwa,
                    column_refs,
                    is_b31,
                    is_consolidated=_is_consolidated,
                )
            elif row_ref == "0060":
                # CRR "SL excluding slotting" — SL on IRB (non-slotting approaches)
                # Cannot distinguish from data; report as null
                values = dict.fromkeys(column_refs)
            else:
                # Sub-rows without direct mapping (SME sub-rows, etc.)
                values = dict.fromkeys(column_refs)

            rows.append({"row_ref": row_ref, "row_name": row_name, **values})

        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
        return pl.DataFrame(rows, schema=schema)

    @staticmethod
    def _compute_c08_07_values(
        irb_ead: float,
        sa_ead: float,
        irb_rwa: float,
        sa_rwa: float,
        column_refs: list[str],
        is_b31: bool,
        *,
        is_consolidated: bool = False,
    ) -> dict[str, object]:
        """Compute column values for a single C 08.07 / OF 08.07 row.

        Args:
            irb_ead: Total EAD under IRB approaches for this class.
            sa_ead: Total EAD under SA for this class.
            irb_rwa: Total RWEA under IRB for this class.
            sa_rwa: Total RWEA under SA for this class.
            column_refs: Ordered list of column reference strings.
            is_b31: Whether Basel 3.1 (18-column) layout is active.
            is_consolidated: Whether reporting is on consolidated basis.
                Materiality columns (0160-0180) are populated only when
                True, per Art. 150(1A) consolidated-basis-only rule.
        """
        total_ead = irb_ead + sa_ead
        total_rwa = irb_rwa + sa_rwa

        # Percentages: avoid division by zero
        pct_sa = (sa_ead / total_ead * 100.0) if total_ead > 0 else 0.0
        pct_irb = (irb_ead / total_ead * 100.0) if total_ead > 0 else 0.0

        values: dict[str, object] = {}
        for ref in column_refs:
            if ref == "0010":
                values[ref] = irb_ead
            elif ref == "0020":
                values[ref] = total_ead
            elif ref == "0030":
                # % subject to permanent partial use of SA — all SA is treated
                # as permanent partial use when IRB permissions exist
                values[ref] = pct_sa
            elif ref == "0040":
                # % subject to roll-out plan — not tracked in pipeline
                values[ref] = 0.0
            elif ref == "0050":
                values[ref] = pct_irb
            elif ref == "0060" and is_b31:
                values[ref] = total_rwa
            elif ref == "0140" and is_b31:
                # RWEA for SA: other — all SA RWEA goes here when no
                # sa_use_reason column is available to split by reason
                values[ref] = sa_rwa
            elif ref == "0150" and is_b31:
                values[ref] = irb_rwa
            elif ref in {"0160", "0170", "0180"} and is_b31:
                # Materiality columns: consolidated-basis only (Art. 150(1A)).
                # Non-consolidated reporting basis → not applicable (None).
                # Consolidated basis → in scope but requires institutional
                # config data not yet available (also None for now).
                values[ref] = None
            elif is_b31:
                # SA RWEA breakdown cols 0070-0130: null (requires sa_use_reason)
                values[ref] = 0.0
            else:
                values[ref] = 0.0

        return values

    # =========================================================================
    # OF 02.01 — Output Floor Comparison (Basel 3.1 only)
    # =========================================================================

    def _generate_of_02_01(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
        *,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> pl.DataFrame | None:
        """Generate OF 02.01 output floor comparison template.

        Basel 3.1 only (no CRR equivalent). Compares modelled (U-TREA) vs
        standardised (S-TREA) total risk exposure amounts by risk type.

        Requires ``rwa_pre_floor`` and ``sa_rwa`` columns in the results
        LazyFrame (added by the output floor calculation in the aggregator).
        Returns None under CRR, when floor columns are absent, or when the
        entity is exempt from the output floor per Art. 92 para 2A.

        References:
            PRA PS1/26 Art. 92 para 2A/3A
        """
        if framework != "BASEL_3_1":
            return None

        # Exempt entities do not report the output floor comparison.
        # Art. 92 para 2A restricts the floor to 3 entity-type/basis combos.
        if output_floor_config is not None and not output_floor_config.is_floor_applicable():
            return None

        if "rwa_pre_floor" not in cols or "sa_rwa" not in cols:
            errors.append(
                "OF 02.01 skipped: rwa_pre_floor and/or sa_rwa columns not found "
                "(output floor not applied)"
            )
            return None

        # Compute credit risk totals from the full results LazyFrame.
        # rwa_pre_floor = actual modelled RWA (before floor add-on).
        # sa_rwa = SA-equivalent RWA for each exposure.
        credit_risk_stats = results.select(
            pl.col("rwa_pre_floor").fill_null(0.0).sum().alias("modelled_rwa"),
            pl.col("sa_rwa").fill_null(0.0).sum().alias("sa_rwa_total"),
        ).collect()

        modelled_rwa = float(credit_risk_stats["modelled_rwa"][0])
        sa_rwa_total = float(credit_risk_stats["sa_rwa_total"][0])

        column_refs = OF_02_01_COLUMN_REFS
        rows: list[dict[str, object]] = []

        for section in OF_02_01_ROW_SECTIONS:
            for row_def in section.rows:
                if row_def.ref == "0010":
                    # Credit risk (excluding CCR) — populated from pipeline
                    rows.append(
                        _of_02_01_row(
                            row_def.ref,
                            row_def.name,
                            column_refs,
                            modelled_rwa=modelled_rwa,
                            sa_rwa=sa_rwa_total,
                        )
                    )
                elif row_def.ref == "0080":
                    # Total — same as credit risk for credit-risk-only calculator
                    rows.append(
                        _of_02_01_row(
                            row_def.ref,
                            row_def.name,
                            column_refs,
                            modelled_rwa=modelled_rwa,
                            sa_rwa=sa_rwa_total,
                        )
                    )
                else:
                    # CCR, CVA, securitisation, market, op risk, other — out of scope
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 02.00 / OF 02.00 — Own Funds Requirements (CA2)
    # =========================================================================

    def _generate_c_02_00(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
        *,
        output_floor_summary: OutputFloorSummary | None = None,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> pl.DataFrame | None:
        """Generate C 02.00 (CRR) / OF 02.00 (Basel 3.1) Own Funds Requirements.

        The master capital template aggregating RWEA across all risk types.
        This calculator only populates credit risk rows (SA, F-IRB, A-IRB,
        slotting, equity); all other risk-type rows (CCR, market, op risk)
        are null.

        CRR: 1 column (col 0010 — all approaches RWEA).
        Basel 3.1: 3 columns — col 0010 (U-TREA components), col 0020
        (SA-only / S-TREA components), col 0030 (output floor RWEA).

        Basel 3.1 adds indicator rows: 0034 (floor activated Yes/No),
        0035 (floor multiplier %), 0036 (OF-ADJ monetary value). These
        rows are gated on entity-type floor applicability (Art. 92 para
        2A) when ``output_floor_config`` is provided.

        References:
            CRR Art. 92 (own funds requirements)
            PRA PS1/26 Art. 92 para 2A/3A/5 (output floor)
        """
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        if ead_col is None or rwa_col is None:
            errors.append("C 02.00 skipped: missing EAD or RWA columns in results")
            return None

        is_b31 = framework == "BASEL_3_1"
        column_refs = B31_C02_00_COLUMN_REFS if is_b31 else CRR_C02_00_COLUMN_REFS
        row_sections = get_c02_00_row_sections(framework)

        # SA RWEA by exposure class
        ec_col = _pick(cols, "exposure_class")
        approach_col = _pick(cols, "approach_applied")

        # Compute totals per approach
        approach_rwa: dict[str, float] = {}
        sa_class_rwa: dict[str, float] = {}
        total_rwa = 0.0

        if approach_col and ec_col:
            collected = results.select(
                pl.col(approach_col).alias("_approach"),
                pl.col(ec_col).alias("_ec"),
                pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
            ).collect()

            # Total RWA
            total_rwa = float(collected["_rwa"].sum())

            # RWA by approach
            by_approach = collected.group_by("_approach").agg(pl.col("_rwa").sum().alias("rwa"))
            for row in by_approach.iter_rows(named=True):
                approach_rwa[row["_approach"]] = float(row["rwa"])

            # SA class breakdown
            sa_mask = collected["_approach"] == "standardised"
            equity_mask = collected["_approach"] == "equity"
            sa_rows = collected.filter(sa_mask | equity_mask)
            by_class = sa_rows.group_by("_ec").agg(pl.col("_rwa").sum().alias("rwa"))
            for row in by_class.iter_rows(named=True):
                sa_class_rwa[row["_ec"]] = float(row["rwa"])

            # IRB sub-approach breakdowns
            irb_rows = collected.filter(~sa_mask & ~equity_mask)

            # Per-approach + class breakdown for IRB sub-rows
            irb_class_approach = irb_rows.group_by(["_approach", "_ec"]).agg(
                pl.col("_rwa").sum().alias("rwa")
            )
            self._irb_class_rwa = {}
            for row in irb_class_approach.iter_rows(named=True):
                key = (row["_approach"], row["_ec"])
                self._irb_class_rwa[key] = float(row["rwa"])

            # Slotting by SL type
            self._slotting_type_rwa: dict[str, float] = {}
            if "sl_type" in cols:
                sl_collected = (
                    results.filter(pl.col(approach_col) == "slotting")
                    .select(
                        pl.col("sl_type").alias("_sl"),
                        pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
                    )
                    .collect()
                )
                by_sl = sl_collected.group_by("_sl").agg(pl.col("_rwa").sum().alias("rwa"))
                for row in by_sl.iter_rows(named=True):
                    if row["_sl"] is not None:
                        self._slotting_type_rwa[row["_sl"]] = float(row["rwa"])

            # Finer-grained IRB sub-row aggregation for B31 OF 02.00.
            # Computes SME/FSE splits for F-IRB/A-IRB corporate and retail
            # RE sub-rows using pipeline columns is_sme, apply_fi_scalar,
            # and property_type.
            self._irb_sub_rwa: dict[
                tuple[str, str, bool | None, bool | None, str | None], float
            ] = {}
            if is_b31:
                sub_select: list[pl.Expr] = [
                    pl.col(approach_col).alias("_approach"),
                    pl.col(ec_col).alias("_ec"),
                    pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
                ]
                has_sme = "is_sme" in cols
                has_fse = "apply_fi_scalar" in cols or "cp_is_financial_sector_entity" in cols
                has_pt = "property_type" in cols
                if has_sme:
                    sub_select.append(pl.col("is_sme").fill_null(False).alias("_sme"))
                if has_fse:
                    fse_col = (
                        "apply_fi_scalar"
                        if "apply_fi_scalar" in cols
                        else "cp_is_financial_sector_entity"
                    )
                    sub_select.append(pl.col(fse_col).fill_null(False).alias("_fse"))
                if has_pt:
                    sub_select.append(pl.col("property_type").alias("_pt"))
                irb_approaches = {"foundation_irb", "advanced_irb"}
                sub_collected = (
                    results.filter(pl.col(approach_col).is_in(irb_approaches))
                    .select(sub_select)
                    .collect()
                )
                gb_cols = ["_approach", "_ec"]
                if has_sme:
                    gb_cols.append("_sme")
                if has_fse:
                    gb_cols.append("_fse")
                if has_pt:
                    gb_cols.append("_pt")
                sub_agg = sub_collected.group_by(gb_cols).agg(pl.col("_rwa").sum().alias("rwa"))
                for row in sub_agg.iter_rows(named=True):
                    key = (
                        row["_approach"],
                        row["_ec"],
                        row.get("_sme"),
                        row.get("_fse"),
                        row.get("_pt"),
                    )
                    self._irb_sub_rwa[key] = float(row["rwa"])
        else:
            # Fallback: just compute total RWA
            total_stats = results.select(
                pl.col(rwa_col).fill_null(0.0).sum().alias("total_rwa"),
            ).collect()
            total_rwa = float(total_stats["total_rwa"][0])

        # SA-equivalent RWA for floor comparison (B31 col 0020)
        sa_equiv_rwa = 0.0
        if is_b31 and "sa_rwa" in cols:
            sa_equiv_stats = results.select(
                pl.col("sa_rwa").fill_null(0.0).sum().alias("sa_equiv"),
            ).collect()
            sa_equiv_rwa = float(sa_equiv_stats["sa_equiv"][0])

        # Output floor RWEA (B31 col 0030)
        floor_rwa = total_rwa  # Default: no floor binding
        floor_activated = False
        if is_b31 and "rwa_pre_floor" in cols:
            pre_floor_stats = results.select(
                pl.col("rwa_pre_floor").fill_null(0.0).sum().alias("pre_floor"),
            ).collect()
            pre_floor_total = float(pre_floor_stats["pre_floor"][0])
            # floor_rwa = total RWA (which includes floor add-on if binding)
            floor_rwa = total_rwa
            floor_activated = total_rwa > pre_floor_total + 0.01

        # Convenience: approach totals
        sa_rwa_total = approach_rwa.get("standardised", 0.0)
        equity_rwa = approach_rwa.get("equity", 0.0)
        firb_rwa = approach_rwa.get("foundation_irb", 0.0)
        airb_rwa = approach_rwa.get("advanced_irb", 0.0)
        slotting_rwa = approach_rwa.get("slotting", 0.0)
        irb_total_rwa = firb_rwa + airb_rwa + slotting_rwa

        # Own funds requirement = 8% × TREA (Art. 92(1))
        own_funds_req = total_rwa * 0.08

        # Build row values
        row_values: dict[str, dict[str, object]] = {}

        # Total and summary rows
        row_values["0010"] = {"0010": total_rwa}
        row_values["0040"] = {"0010": own_funds_req}
        row_values["0050"] = {"0010": total_rwa}  # Credit risk = total (only CR in scope)
        row_values["0060"] = {"0010": sa_rwa_total + equity_rwa}

        # SA per-class breakdown
        for ec_value, row_ref in C02_00_SA_CLASS_MAP.items():
            if ec_value in sa_class_rwa:
                if row_ref not in row_values:
                    row_values[row_ref] = {"0010": 0.0}
                existing = float(row_values[row_ref].get("0010", 0.0) or 0.0)
                row_values[row_ref]["0010"] = existing + sa_class_rwa[ec_value]

        # Specialised lending sub-row (B31 only, under SA corporates)
        if is_b31 and "specialised_lending" in sa_class_rwa:
            row_values["0131"] = {"0010": sa_class_rwa["specialised_lending"]}

        # IRB total
        row_values["0220"] = {"0010": irb_total_rwa}

        # F-IRB total and sub-rows
        row_values["0240"] = {"0010": firb_rwa}
        irb_class_rwa = getattr(self, "_irb_class_rwa", {})
        # F-IRB — Institutions
        firb_inst = irb_class_rwa.get(("foundation_irb", "institution"), 0.0)
        row_values["0250"] = {"0010": firb_inst}
        if is_b31:
            row_values["0271"] = {"0010": firb_inst}
        # F-IRB — Corporates
        firb_corp = irb_class_rwa.get(("foundation_irb", "corporate"), 0.0)
        firb_sl = irb_class_rwa.get(("foundation_irb", "specialised_lending"), 0.0)
        row_values["0260"] = {"0010": firb_corp + firb_sl}
        if is_b31:
            row_values["0290"] = {"0010": firb_sl}
            # F-IRB corporate sub-splits using finer-grained IRB aggregation
            firb_fse, firb_sme, firb_nonsme = _irb_sub_split(
                self._irb_sub_rwa,
                "foundation_irb",
                "corporate",
                firb_corp,
            )
            row_values["0295"] = {"0010": firb_fse}  # Financial/large corporates
            row_values["0296"] = {"0010": firb_sme}  # Other general corporates SME
            row_values["0297"] = {"0010": firb_nonsme}  # Other general corporates non-SME

        # A-IRB total and sub-rows
        row_values["0300"] = {"0010": airb_rwa}
        # A-IRB by exposure class
        airb_sovereign = irb_class_rwa.get(("advanced_irb", "central_government"), 0.0)
        row_values["0310"] = {"0010": airb_sovereign}
        airb_inst = irb_class_rwa.get(("advanced_irb", "institution"), 0.0)
        row_values["0330"] = {"0010": airb_inst}
        airb_corp = irb_class_rwa.get(("advanced_irb", "corporate"), 0.0)
        airb_sl_excl = irb_class_rwa.get(("advanced_irb", "specialised_lending"), 0.0)
        row_values["0340"] = {"0010": airb_corp + airb_sl_excl}
        if is_b31:
            row_values["0350"] = {"0010": airb_sl_excl}
            # A-IRB corporate sub-splits
            airb_fse, airb_sme, airb_nonsme = _irb_sub_split(
                self._irb_sub_rwa,
                "advanced_irb",
                "corporate",
                airb_corp,
            )
            row_values["0355"] = {"0010": airb_sme}  # Other general corporates SME
            row_values["0356"] = {"0010": airb_nonsme + airb_fse}  # Non-SME (incl. FSE)

        # A-IRB retail
        airb_retail_mort = irb_class_rwa.get(("advanced_irb", "retail_mortgage"), 0.0)
        airb_retail_qrre = irb_class_rwa.get(("advanced_irb", "retail_qrre"), 0.0)
        airb_retail_other = irb_class_rwa.get(("advanced_irb", "retail_other"), 0.0)
        airb_retail_total = airb_retail_mort + airb_retail_qrre + airb_retail_other
        row_values["0370"] = {"0010": airb_retail_total}
        row_values["0380"] = {"0010": airb_retail_mort}
        if is_b31:
            # A-IRB retail RE sub-splits by property type and SME
            resi_sme, resi_nonsme, comm_sme, comm_nonsme = _irb_re_sub_split(
                self._irb_sub_rwa,
                "advanced_irb",
                "retail_mortgage",
                airb_retail_mort,
            )
            row_values["0382"] = {"0010": resi_sme}
            row_values["0383"] = {"0010": resi_nonsme}
            row_values["0384"] = {"0010": comm_sme}
            row_values["0385"] = {"0010": comm_nonsme}
        row_values["0390"] = {"0010": airb_retail_qrre}
        # A-IRB retail other sub-splits by SME
        if is_b31:
            other_sme, other_nonsme = _irb_other_sme_split(
                self._irb_sub_rwa,
                "advanced_irb",
                "retail_other",
                airb_retail_other,
            )
            row_values["0400"] = {"0010": other_sme}
            row_values["0410"] = {"0010": other_nonsme}
        else:
            row_values["0400"] = {"0010": airb_retail_other}

        # Slotting
        slotting_type_rwa = getattr(self, "_slotting_type_rwa", {})
        if is_b31:
            row_values["0411"] = {"0010": slotting_rwa}
            row_values["0412"] = {"0010": slotting_type_rwa.get("project_finance", 0.0)}
            row_values["0413"] = {"0010": slotting_type_rwa.get("object_finance", 0.0)}
            row_values["0414"] = {"0010": slotting_type_rwa.get("commodities_finance", 0.0)}
            row_values["0415"] = {"0010": slotting_type_rwa.get("ipre", 0.0)}
            row_values["0416"] = {"0010": slotting_type_rwa.get("hvcre", 0.0)}
        else:
            row_values["0410"] = {"0010": slotting_rwa}

        # Equity IRB
        row_values["0420"] = {"0010": equity_rwa}

        # B31 output floor indicator rows.
        # Art. 92 para 2A: floor only applies to 3 entity-type/basis combos.
        # When output_floor_config is provided, gate on is_floor_applicable().
        _floor_applicable = output_floor_config is None or output_floor_config.is_floor_applicable()
        if is_b31:
            if _floor_applicable:
                row_values["0034"] = {"0010": 1.0 if floor_activated else 0.0}
                # Row 0035: floor multiplier % (e.g. 72.5 for 72.5%)
                # Row 0036: OF-ADJ monetary value
                if output_floor_summary is not None:
                    row_values["0035"] = {
                        "0010": output_floor_summary.floor_pct * 100.0,
                    }
                    row_values["0036"] = {"0010": output_floor_summary.of_adj}
                else:
                    row_values["0035"] = {"0010": 0.0}
                    row_values["0036"] = {"0010": 0.0}
            else:
                # Exempt entity: floor not applicable (Art. 92 para 2A).
                # Rows present but indicate no floor activation.
                row_values["0034"] = {"0010": 0.0}
                row_values["0035"] = {"0010": 0.0}
                row_values["0036"] = {"0010": 0.0}

        # Add B31 col 0020 (SA-equivalent) and col 0030 (output floor) values
        if is_b31:
            for ref, vals in row_values.items():
                col_0010 = vals.get("0010")
                if ref == "0010":
                    # Total row: col 0020 = SA-equivalent TREA, col 0030 = floor TREA
                    vals["0020"] = sa_equiv_rwa
                    vals["0030"] = floor_rwa
                elif ref == "0040":
                    # Own funds: 8% of respective column totals
                    vals["0020"] = sa_equiv_rwa * 0.08
                    vals["0030"] = floor_rwa * 0.08
                elif ref in {"0034", "0035", "0036"}:
                    # Indicator rows: same value across all columns
                    vals["0020"] = col_0010
                    vals["0030"] = col_0010
                elif ref == "0050":
                    # Credit risk total = SA-equiv for col 0020
                    vals["0020"] = sa_equiv_rwa
                    vals["0030"] = floor_rwa
                elif ref == "0060":
                    # SA subtotal: SA-equiv includes all SA + equity
                    vals["0020"] = vals["0010"]  # SA-only RWEA is what SA produces
                    vals["0030"] = vals["0010"]  # SA approach doesn't get floored
                elif ref in {"0220", "0240", "0300"}:
                    # IRB totals: col 0020 = SA-equivalent of IRB exposures
                    vals["0020"] = 0.0  # IRB → SA equivalent not separately tracked here
                    vals["0030"] = 0.0
                else:
                    # Default: col 0020/0030 same as col 0010 for SA rows,
                    # 0.0 for IRB rows (SA equivalent not separately computed)
                    vals["0020"] = col_0010 if col_0010 is not None else None
                    vals["0030"] = col_0010 if col_0010 is not None else None

        # Build DataFrame rows
        rows: list[dict[str, object]] = []
        for section in row_sections:
            for row_def in section.rows:
                if row_def.ref in row_values:
                    row_data: dict[str, object] = {
                        "row_ref": row_def.ref,
                        "row_name": row_def.name,
                    }
                    vals = row_values[row_def.ref]
                    for ref in column_refs:
                        row_data[ref] = vals.get(ref)
                    rows.append(row_data)
                elif row_def.ref in C02_00_CREDIT_RISK_ROWS:
                    # Credit risk row without data — zero
                    row_data = {"row_ref": row_def.ref, "row_name": row_def.name}
                    for ref in column_refs:
                        row_data[ref] = 0.0
                    rows.append(row_data)
                else:
                    # Non-credit-risk rows — null (out of scope)
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Schema: String for refs/names, Float64 for data columns
        schema: dict[str, pl.DataType] = {
            "row_ref": pl.String,
            "row_name": pl.String,
        }
        for ref in column_refs:
            schema[ref] = pl.Float64

        # Clean up temporary state
        self._irb_class_rwa = {}
        self._slotting_type_rwa = {}
        self._irb_sub_rwa = {}

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 09.01 / OF 09.01 — Geographical Breakdown SA
    # =========================================================================

    def _generate_all_c09_01(
        self,
        sa_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 09.01 / OF 09.01 DataFrames per country.

        Produces one DataFrame per unique country code found in the SA data,
        plus a "TOTAL" entry aggregating all countries. Each DataFrame has
        rows by SA exposure class and columns per the C 09.01 spec.

        Requires ``cp_country_code`` and ``exposure_class`` columns.

        References:
            Regulation (EU) 2021/451, Annex I/II (C 09.01)
            PRA PS1/26, Annex I/II (OF 09.01)
        """
        ec_col = _pick(cols, "exposure_class")
        country_col = _pick(cols, "cp_country_code")

        if ec_col is None:
            errors.append("C09.01: Missing required column (exposure_class)")
            return {}

        if country_col is None:
            errors.append(
                "C09.01: Missing cp_country_code column — cannot produce geographical breakdown"
            )
            return {}

        sa_df: pl.DataFrame = sa_data.collect()
        if len(sa_df) == 0:
            return {}

        row_defs = get_c09_01_rows(framework)
        column_defs = get_c09_01_columns(framework)
        column_refs = [c.ref for c in column_defs]
        df_cols = set(sa_df.columns)

        result: dict[str, pl.DataFrame] = {}

        # Generate total-level template first
        total_df = self._generate_c09_01_for_country(
            sa_df, df_cols, row_defs, column_refs, framework
        )
        result["TOTAL"] = total_df

        # Generate per-country templates
        countries = (
            sa_df.select(pl.col(country_col))
            .filter(pl.col(country_col).is_not_null())
            .unique()
            .sort(country_col)
            .to_series()
            .to_list()
        )

        for country in countries:
            country_data = sa_df.filter(pl.col(country_col) == country)
            if len(country_data) > 0:
                country_df = self._generate_c09_01_for_country(
                    country_data, df_cols, row_defs, column_refs, framework
                )
                result[country] = country_df

        return result

    def _generate_c09_01_for_country(
        self,
        country_data: pl.DataFrame,
        cols: set[str],
        row_defs: list[COREPRow],
        column_refs: list[str],
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 09.01 DataFrame for a single country (or total).

        Rows: SA exposure classes as defined in row_defs.
        Columns: 13 (CRR) or 10 (Basel 3.1) columns covering original exposure,
        defaults, provisions, exposure value, and RWEA.
        """
        rows: list[dict[str, object]] = []

        for row_def in row_defs:
            if row_def.ref == "0170":
                # Total row: sum across all exposure classes
                values = _compute_c09_01_values(country_data, cols, column_refs, framework)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            elif row_def.exposure_class_value is not None:
                row_data = _filter_c09_01_row(
                    country_data, cols, row_def.exposure_class_value, framework
                )
                if len(row_data) > 0:
                    values = _compute_c09_01_values(row_data, cols, column_refs, framework)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 09.02 / OF 09.02 — Geographical Breakdown IRB
    # =========================================================================

    def _generate_all_c09_02(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 09.02 / OF 09.02 DataFrames per country.

        Produces one DataFrame per unique country code found in the IRB data,
        plus a "TOTAL" entry aggregating all countries. Each DataFrame has
        rows by IRB exposure class and columns per the C 09.02 spec.

        Requires ``cp_country_code`` and ``exposure_class`` columns.

        References:
            Regulation (EU) 2021/451, Annex I/II (C 09.02)
            PRA PS1/26, Annex I/II (OF 09.02)
        """
        ec_col = _pick(cols, "exposure_class")
        country_col = _pick(cols, "cp_country_code")

        if ec_col is None:
            errors.append("C09.02: Missing required column (exposure_class)")
            return {}

        if country_col is None:
            errors.append(
                "C09.02: Missing cp_country_code column — cannot produce geographical breakdown"
            )
            return {}

        # Exclude slotting from main IRB data for non-slotting rows
        approach_col = _pick(cols, "approach_applied", "approach")
        irb_df: pl.DataFrame = irb_data.collect()
        if len(irb_df) == 0:
            return {}

        row_defs = get_c09_02_rows(framework)
        column_defs = get_c09_02_columns(framework)
        column_refs = [c.ref for c in column_defs]
        df_cols = set(irb_df.columns)

        result: dict[str, pl.DataFrame] = {}

        # Generate total-level template first
        total_df = self._generate_c09_02_for_country(
            irb_df, df_cols, row_defs, column_refs, framework, approach_col
        )
        result["TOTAL"] = total_df

        # Generate per-country templates
        countries = (
            irb_df.select(pl.col(country_col))
            .filter(pl.col(country_col).is_not_null())
            .unique()
            .sort(country_col)
            .to_series()
            .to_list()
        )

        for country in countries:
            country_data = irb_df.filter(pl.col(country_col) == country)
            if len(country_data) > 0:
                country_df = self._generate_c09_02_for_country(
                    country_data, df_cols, row_defs, column_refs, framework, approach_col
                )
                result[country] = country_df

        return result

    def _generate_c09_02_for_country(
        self,
        country_data: pl.DataFrame,
        cols: set[str],
        row_defs: list[COREPRow],
        column_refs: list[str],
        framework: str,
        approach_col: str | None,
    ) -> pl.DataFrame:
        """Generate a C 09.02 DataFrame for a single country (or total).

        Rows: IRB exposure classes as defined in row_defs.
        Columns: 17 (CRR) or 15 (Basel 3.1) columns covering original exposure,
        defaults, provisions, PD, LGD, exposure value, RWEA, and expected loss.
        """
        rows: list[dict[str, object]] = []

        for row_def in row_defs:
            if row_def.ref == "0150":
                # Total row: sum across all IRB exposure classes
                values = _compute_c09_02_values(country_data, cols, column_refs, framework)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            elif row_def.exposure_class_value is not None:
                row_data = _filter_c09_02_row(
                    country_data, cols, row_def.exposure_class_value, framework, approach_col
                )
                if len(row_data) > 0:
                    values = _compute_c09_02_values(row_data, cols, column_refs, framework)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

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

        sa_df: pl.DataFrame = sa_data.collect()
        if len(sa_df) == 0:
            return {}

        # Art. 112 Table A2: Under SA, specialised lending is a corporate
        # sub-type (Art. 112(1)(g)), not a separate exposure class.  Merge SL
        # into corporate so C 07.00 reports SL under the corporate sheet; the
        # SL "of which" sub-rows (0021-0026) still populate via sl_type.
        sa_df = sa_df.with_columns(
            pl.when(pl.col(ec_col) == ExposureClass.SPECIALISED_LENDING.value)
            .then(pl.lit(ExposureClass.CORPORATE.value))
            .otherwise(pl.col(ec_col))
            .alias(ec_col)
        )

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
                    class_data,
                    cols,
                    ead_col,
                    rwa_col,
                    column_refs,
                    substitution_inflow=substitution_inflow,
                )
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            elif row_def.ref == "0015":
                # Row 0015: of which: Defaulted exposures
                subset = _filter_defaulted(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0020":
                # Row 0020: of which: SME
                subset = _filter_sme(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
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
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in ("0024", "0025", "0026"):
                # Project finance phase "of which" rows (B3.1 rows 0024-0026)
                phase_map = {
                    "0024": "pre_operational",
                    "0025": "operational",
                    "0026": "high_quality_operational",
                }
                subset = _filter_project_phase(class_data, cols, phase_map[row_def.ref])
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in _RE_ROW_FILTERS:
                # Real estate "of which" rows (B3.1 rows 0330-0360)
                re_kwargs = _RE_ROW_FILTERS[row_def.ref]
                subset = _filter_re(class_data, cols, **re_kwargs)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0030":
                # CRR: of which: Exposures subject to SME-supporting factor
                subset = _filter_supporting_factor(class_data, cols, "sme")
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0035":
                # CRR: of which: Exposures subject to infrastructure supporting factor
                subset = _filter_supporting_factor(class_data, cols, "infrastructure")
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # Other "of which" rows (0040/0050/0060) — require
                # pipeline columns not yet available
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 2: Breakdown by Exposure Types
        for row_def in row_sections[1].rows:
            if row_def.ref == "0070":
                # On balance sheet exposures
                subset = _filter_on_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0080":
                # Off balance sheet exposures
                subset = _filter_off_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
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
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 4: Breakdown by CIU Approach (Art. 132-132C)
        _CIU_ROW_APPROACH = {"0281": "look_through", "0282": "mandate_based", "0283": "fallback"}
        ciu_col = _pick(cols, "ciu_approach")
        for row_def in row_sections[3].rows:
            if row_def.ref in _CIU_ROW_APPROACH and ciu_col:
                subset = class_data.filter(pl.col(ciu_col) == _CIU_ROW_APPROACH[row_def.ref])
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 5: Memorandum Items
        _MEMO_DEFAULTED_RW = {"0300": 1.0, "0320": 1.5}
        _MEMO_RE_SECURED = {"0290": "commercial", "0310": "residential"}
        for row_def in row_sections[4].rows:
            if row_def.ref in _EQUITY_TRANSITIONAL_FILTERS:
                eq_filter = _EQUITY_TRANSITIONAL_FILTERS[row_def.ref]
                subset = _filter_equity_transitional(class_data, cols, **eq_filter)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0380":
                # Currency mismatch multiplier (Basel 3.1 Art. 123B / CRE20.93)
                subset = _filter_currency_mismatch(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in _MEMO_DEFAULTED_RW:
                # Defaulted at specific RW (CRR Art. 127 / PRA Art. 127)
                target_rw = _MEMO_DEFAULTED_RW[row_def.ref]
                subset = _filter_defaulted_at_rw(class_data, cols, target_rw)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref in _MEMO_RE_SECURED:
                # CRR: Exposures secured by mortgages (Art. 124-126)
                prop_type = _MEMO_RE_SECURED[row_def.ref]
                subset = _filter_re_secured(class_data, cols, prop_type)
                if len(subset) > 0:
                    values = _compute_c07_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {
            "row_ref": pl.String,
            "row_name": pl.String,
        }
        schema.update(dict.fromkeys(column_refs, pl.Float64))
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

        irb_df: pl.DataFrame = irb_data.collect()
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
                    class_data,
                    cols,
                    ead_col,
                    rwa_col,
                    column_refs,
                    substitution_inflow=substitution_inflow,
                )
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 2: Breakdown by Exposure Types
        for row_def in row_sections[1].rows:
            if row_def.ref == "0020":
                # On balance sheet items
                subset = _filter_on_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c08_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            elif row_def.ref == "0030":
                # Off balance sheet items
                subset = _filter_off_bs(class_data, cols)
                if len(subset) > 0:
                    values = _compute_c08_values(subset, cols, ead_col, rwa_col, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                # CCR/other rows — not implemented
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        # Section 3: Calculation Approaches
        # Splits the total IRB exposure by calculation method: PD/LGD model
        # (row 0070) vs slotting (row 0080), plus sub-portfolios.
        approach_col = "approach_applied" if "approach_applied" in cols else None
        for row_def in row_sections[2].rows:
            subset = _filter_section3_row(
                class_data,
                cols,
                row_def.ref,
                approach_col,
                framework,
            )
            if subset is not None and len(subset) > 0:
                values = _compute_c08_values(subset, cols, ead_col, rwa_col, column_refs)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, pl.DataType] = {
            "row_ref": pl.String,
            "row_name": pl.String,
        }
        schema.update(dict.fromkeys(column_refs, pl.Float64))
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
            errors.append("C08.02: No PD column available — skipping PD grade breakdown")
            return {}

        irb_df: pl.DataFrame = irb_data.collect()
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
                pl.when((pl.col(pd_col) >= lower) & (pl.col(pd_col) < upper))
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
            values = _compute_c08_values(band_data, cols, ead_col, rwa_col, column_refs)
            # Col 0005: obligor grade identifier = the PD band label
            values["0005"] = label
            rows.append({"row_ref": label, "row_name": label, **values})

        # Handle unassigned
        unassigned = banded.filter(pl.col("_pd_band") == "Unassigned").drop("_pd_band")
        if len(unassigned) > 0:
            values = _compute_c08_values(unassigned, cols, ead_col, rwa_col, column_refs)
            values["0005"] = "Unassigned"
            rows.append({"row_ref": "Unassigned", "row_name": "Unassigned", **values})

        if not rows:
            schema: dict[str, pl.DataType] = {
                "row_ref": pl.String,
                "row_name": pl.String,
            }
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        # Infer schema from column defs — 0005 is String, rest are Float64
        schema = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.String if ref == "0005" else pl.Float64

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.03 — IRB PD Ranges (per exposure class, 17 fixed regulatory buckets)
    # =========================================================================

    def _generate_all_c08_03(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.03 / OF 08.03 DataFrames for all IRB exposure classes.

        C 08.03 provides PD distribution analysis using 17 fixed regulatory PD
        range buckets (0.00-0.03% through 100% default). Each row contains
        aggregated exposure, PD, LGD, maturity, RWEA, EL, and provision data
        for exposures falling within the PD range.

        Slotting exposures are excluded (they use category-based weights,
        not PD-based calculation).

        Basel 3.1 distinction: Row allocation uses pre-input-floor PD,
        but col 0050 reports post-input-floor average PD.

        References:
        - CRR Art. 153, Regulation (EU) 2021/451 Annex I
        - PRA PS1/26 Annex I/II (OF 08.03)
        """
        ec_col = _pick(cols, "exposure_class")
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        if ec_col is None or ead_col is None or rwa_col is None:
            errors.append("C08.03: Missing required columns (exposure_class/ead/rwa)")
            return {}

        # For row allocation: B31 uses pre-input-floor PD, CRR uses floored PD
        if framework == "BASEL_3_1":
            alloc_pd_col = _pick(cols, "irb_pd_original", "irb_pd_floored")
        else:
            alloc_pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")
        # For col 0050 (reported PD): always post-input-floor
        report_pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")

        if alloc_pd_col is None:
            errors.append("C08.03: No PD column available — skipping PD range breakdown")
            return {}

        # Exclude slotting exposures — C 08.03 covers F-IRB/A-IRB only
        approach_col = _pick(cols, "approach_applied", "approach")
        if approach_col is not None:
            irb_no_slotting = irb_data.filter(pl.col(approach_col) != "slotting")
        else:
            irb_no_slotting = irb_data

        irb_df: pl.DataFrame = irb_no_slotting.collect()
        if len(irb_df) == 0:
            return {}

        data_cols = set(irb_df.columns)
        classes = irb_df[ec_col].unique().sort().to_list()
        result: dict[str, pl.DataFrame] = {}

        for ec in classes:
            class_df = irb_df.filter(pl.col(ec_col) == ec)
            template_df = self._generate_c08_03_for_class(
                class_df,
                data_cols,
                ead_col,
                rwa_col,
                alloc_pd_col,
                report_pd_col or alloc_pd_col,
                framework,
            )
            result[ec] = template_df

        return result

    def _generate_c08_03_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        alloc_pd_col: str,
        report_pd_col: str,
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 08.03 DataFrame for a single IRB exposure class.

        Rows = 17 fixed regulatory PD range buckets (plus optional unassigned).
        Columns = 11: on/off-BS exposure, avg CCF, EAD, avg PD, obligors,
        avg LGD, avg maturity, RWEA, EL, provisions.

        Args:
            class_data: DataFrame filtered to a single exposure class.
            cols: Available column names.
            ead_col: EAD column name.
            rwa_col: RWA column name.
            alloc_pd_col: PD column for row allocation (pre-floor for B31).
            report_pd_col: PD column for col 0050 reporting (post-floor).
            framework: "CRR" or "BASEL_3_1".
        """
        column_defs = get_c08_03_columns(framework)
        column_refs = [c.ref for c in column_defs]

        # Assign PD range buckets using the allocation PD column
        band_expr = pl.lit("Unassigned")
        for lower, upper, _row_ref, label in reversed(C08_03_PD_RANGES):
            band_expr = (
                pl.when((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
                .then(pl.lit(label))
                .otherwise(band_expr)
            )
        banded = class_data.with_columns(band_expr.alias("_pd_range"))

        rows: list[dict[str, object]] = []

        for _lower, _upper, row_ref, label in C08_03_PD_RANGES:
            band_data = banded.filter(pl.col("_pd_range") == label).drop("_pd_range")
            if len(band_data) == 0:
                continue

            values = _compute_c08_03_values(
                band_data, cols, ead_col, rwa_col, report_pd_col, column_refs
            )
            rows.append({"row_ref": row_ref, "row_name": label, **values})

        # Handle unassigned (e.g. null PD)
        unassigned = banded.filter(pl.col("_pd_range") == "Unassigned").drop("_pd_range")
        if len(unassigned) > 0:
            values = _compute_c08_03_values(
                unassigned, cols, ead_col, rwa_col, report_pd_col, column_refs
            )
            rows.append({"row_ref": "9999", "row_name": "Unassigned", **values})

        if not rows:
            schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.04 / OF 08.04 — IRB RWEA FLOW STATEMENTS
    # =========================================================================

    def _generate_all_c08_04(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.04 / OF 08.04 DataFrames for all IRB exposure classes.

        C 08.04 reports quarter-over-quarter movements in IRB RWEA, decomposed
        into seven standardised driver categories. Submitted once per IRB
        exposure class, excluding CCR and slotting exposures.

        The pipeline provides current-period data only. Row 0090 (closing RWEA)
        is populated from current results. Rows 0010 (opening RWEA) and
        0020-0080 (movement drivers) are null because they require prior-period
        comparison data that a single pipeline run cannot produce.

        Why: Flow statements help supervisors understand *why* capital
        requirements changed, not just *that* they changed. The structured
        driver decomposition (asset size, quality, models, methodology,
        acquisitions, FX, other) is mandatory for IRB firms.

        References:
        - Regulation (EU) 2021/451, Annex I/II (C 08.04)
        - PRA PS1/26, Annex I/II (OF 08.04)
        """
        ec_col = _pick(cols, "exposure_class")

        if ec_col is None:
            errors.append("C08.04: Missing required column (exposure_class)")
            return {}

        # Exclude slotting exposures — C 08.04 covers F-IRB/A-IRB only
        approach_col = _pick(cols, "approach_applied", "approach")
        if approach_col is not None:
            irb_no_slotting = irb_data.filter(pl.col(approach_col) != "slotting")
        else:
            irb_no_slotting = irb_data

        irb_df: pl.DataFrame = irb_no_slotting.collect()
        if len(irb_df) == 0:
            return {}

        classes = irb_df[ec_col].unique().sort().to_list()
        result: dict[str, pl.DataFrame] = {}

        for ec in classes:
            class_df = irb_df.filter(pl.col(ec_col) == ec)
            template_df = self._generate_c08_04_for_class(
                class_df,
                set(irb_df.columns),
                framework,
            )
            result[ec] = template_df

        return result

    def _generate_c08_04_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 08.04 DataFrame for a single IRB exposure class.

        Rows = 9: opening balance, 7 movement drivers, closing balance.
        Columns = 1: RWEA (col ref 0010).

        Only row 0090 (closing RWEA) is populated from the current pipeline.
        All other rows require prior-period data and are null.

        Args:
            class_data: DataFrame filtered to a single exposure class.
            cols: Available column names.
            framework: "CRR" or "BASEL_3_1".
        """
        column_defs = get_c08_04_columns(framework)
        column_refs = [c.ref for c in column_defs]

        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
        closing_rwea: float | None = None
        if rwa_col is not None and len(class_data) > 0:
            closing_rwea = float(class_data[rwa_col].fill_null(0.0).sum())

        rows: list[dict[str, object]] = []
        for row_def in C08_04_ROWS:
            if row_def.ref == "0090":
                # Closing RWEA — populated from current pipeline results
                values: dict[str, object] = {"0010": closing_rwea}
            else:
                # Opening (0010) and movement drivers (0020-0080)
                # require prior-period comparison data
                values = {"0010": None}
            rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})

        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.05 / OF 08.05 — IRB PD BACKTESTING
    # =========================================================================

    def _generate_all_c08_05(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.05 / OF 08.05 DataFrames for all IRB exposure classes.

        C 08.05 provides PD backtesting analysis using 17 fixed regulatory PD
        range buckets (same as C 08.03). Each row contains PD model validation
        metrics: arithmetic average PD, obligor count, defaults, and default
        rates. Slotting exposures are excluded.

        Basel 3.1 distinction: Row allocation uses pre-input-floor PD,
        but col 0010 reports the arithmetic average post-input-floor PD.

        Why: PD backtesting is critical for IRB model validation. Comparing
        assigned PDs against realised default rates reveals model calibration
        drift and supports supervisory review of internal models.

        References:
        - CRR Art. 180 (PD validation requirements)
        - Regulation (EU) 2021/451, Annex I/II (C 08.05)
        - PRA PS1/26, Annex I/II (OF 08.05)
        """
        ec_col = _pick(cols, "exposure_class")

        if ec_col is None:
            errors.append("C08.05: Missing required column (exposure_class)")
            return {}

        # For row allocation: B31 uses pre-input-floor PD, CRR uses floored PD
        if framework == "BASEL_3_1":
            alloc_pd_col = _pick(cols, "irb_pd_original", "irb_pd_floored")
        else:
            alloc_pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")
        # For col 0010 (reported PD): always post-input-floor
        report_pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")

        if alloc_pd_col is None:
            errors.append("C08.05: No PD column available — skipping PD backtesting")
            return {}

        # Exclude slotting exposures — C 08.05 covers F-IRB/A-IRB only
        approach_col = _pick(cols, "approach_applied", "approach")
        if approach_col is not None:
            irb_no_slotting = irb_data.filter(pl.col(approach_col) != "slotting")
        else:
            irb_no_slotting = irb_data

        irb_df: pl.DataFrame = irb_no_slotting.collect()
        if len(irb_df) == 0:
            return {}

        classes = irb_df[ec_col].unique().sort().to_list()
        result: dict[str, pl.DataFrame] = {}

        for ec in classes:
            class_df = irb_df.filter(pl.col(ec_col) == ec)
            template_df = self._generate_c08_05_for_class(
                class_df,
                set(irb_df.columns),
                alloc_pd_col,
                report_pd_col or alloc_pd_col,
                framework,
            )
            result[ec] = template_df

        return result

    def _generate_c08_05_for_class(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        alloc_pd_col: str,
        report_pd_col: str,
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 08.05 DataFrame for a single IRB exposure class.

        Rows = 17 fixed regulatory PD range buckets (plus optional unassigned).
        Columns = 5: arithmetic avg PD, obligors (prior year), defaults,
        observed default rate, historical annual default rate.

        Args:
            class_data: DataFrame filtered to a single exposure class.
            cols: Available column names.
            alloc_pd_col: PD column for row allocation (pre-floor for B31).
            report_pd_col: PD column for col 0010 reporting (post-floor).
            framework: "CRR" or "BASEL_3_1".
        """
        column_defs = get_c08_05_columns(framework)
        column_refs = [c.ref for c in column_defs]

        # Assign PD range buckets using the allocation PD column
        band_expr = pl.lit("Unassigned")
        for lower, upper, _row_ref, label in reversed(C08_03_PD_RANGES):
            band_expr = (
                pl.when((pl.col(alloc_pd_col) >= lower) & (pl.col(alloc_pd_col) < upper))
                .then(pl.lit(label))
                .otherwise(band_expr)
            )
        banded = class_data.with_columns(band_expr.alias("_pd_range"))

        rows: list[dict[str, object]] = []

        for _lower, _upper, row_ref, label in C08_03_PD_RANGES:
            band_data = banded.filter(pl.col("_pd_range") == label).drop("_pd_range")
            if len(band_data) == 0:
                continue

            values = _compute_c08_05_values(band_data, cols, report_pd_col, column_refs)
            rows.append({"row_ref": row_ref, "row_name": label, **values})

        # Handle unassigned (e.g. null PD)
        unassigned = banded.filter(pl.col("_pd_range") == "Unassigned").drop("_pd_range")
        if len(unassigned) > 0:
            values = _compute_c08_05_values(unassigned, cols, report_pd_col, column_refs)
            rows.append({"row_ref": "9999", "row_name": "Unassigned", **values})

        if not rows:
            schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 08.06 / OF 08.06 — IRB SPECIALISED LENDING SLOTTING
    # =========================================================================

    def _generate_all_c08_06(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.06 / OF 08.06 DataFrames for all SL types.

        C 08.06 reports specialised lending exposures under slotting criteria.
        One template per SL type. Rows by slotting category × maturity band.
        Only slotting-approach exposures are included (F-IRB/A-IRB excluded).

        CRR: 4 SL types (IPRE+HVCRE combined), 12 rows, 10 columns.
        Basel 3.1: 5 SL types (HVCRE separated), 14 rows (adds "substantially
        stronger" sub-rows), 11 columns (adds FCCM deduction col 0031).

        References:
        - CRR Art. 153(5), Regulation (EU) 2021/451 Annex I (C 08.06)
        - PRA PS1/26 Art. 153(5) Table A (OF 08.06)
        """
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")
        approach_col = _pick(cols, "approach_applied", "approach")

        if ead_col is None or rwa_col is None:
            errors.append("C08.06: Missing required columns (ead/rwa)")
            return {}

        # Filter to slotting-only exposures
        if approach_col is not None:
            slotting_data = irb_data.filter(pl.col(approach_col) == "slotting")
        else:
            errors.append("C08.06: No approach column — cannot identify slotting exposures")
            return {}

        slotting_df: pl.DataFrame = slotting_data.collect()
        if len(slotting_df) == 0:
            return {}

        data_cols = set(slotting_df.columns)

        # Validate required slotting columns
        cat_col = _pick(data_cols, "slotting_category")
        maturity_col = _pick(data_cols, "is_short_maturity")
        if cat_col is None:
            errors.append("C08.06: Missing slotting_category column — cannot generate template")
            return {}

        sl_type_col = _pick(data_cols, "sl_type")
        hvcre_col = _pick(data_cols, "is_hvcre")
        sl_types = get_c08_06_sl_types(framework)

        result: dict[str, pl.DataFrame] = {}

        if sl_type_col is not None:
            # Route by sl_type column
            for sl_key, _sl_display in sl_types.items():
                if sl_key == "ipre" and framework != "BASEL_3_1" and hvcre_col is not None:
                    # CRR combines IPRE+HVCRE into one type
                    type_df = slotting_df.filter(
                        (pl.col(sl_type_col) == "ipre") | (pl.col(sl_type_col) == "hvcre")
                    )
                elif sl_key == "hvcre" and framework == "BASEL_3_1":
                    # B31 separates HVCRE
                    if hvcre_col is not None:
                        type_df = slotting_df.filter(
                            (pl.col(sl_type_col) == "hvcre") | (pl.col(hvcre_col) == True)  # noqa: E712
                        )
                    else:
                        type_df = slotting_df.filter(pl.col(sl_type_col) == "hvcre")
                else:
                    type_df = slotting_df.filter(pl.col(sl_type_col) == sl_key)

                if len(type_df) == 0:
                    continue

                template_df = self._generate_c08_06_for_type(
                    type_df,
                    data_cols,
                    ead_col,
                    rwa_col,
                    cat_col,
                    maturity_col,
                    framework,
                )
                result[sl_key] = template_df
        else:
            # No sl_type column — generate a single "all" template
            template_df = self._generate_c08_06_for_type(
                slotting_df,
                data_cols,
                ead_col,
                rwa_col,
                cat_col,
                maturity_col,
                framework,
            )
            result["specialised_lending"] = template_df

        return result

    def _generate_c08_06_for_type(
        self,
        type_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        cat_col: str,
        maturity_col: str | None,
        framework: str,
    ) -> pl.DataFrame:
        """Generate a C 08.06 DataFrame for a single SL type.

        Rows = slotting categories (Strong-Default) × maturity bands (< 2.5yr / ≥ 2.5yr).
        Columns = 10 (CRR) or 11 (Basel 3.1, adds FCCM deduction).

        Args:
            type_data: DataFrame filtered to a single SL type.
            cols: Available column names.
            ead_col: EAD column name.
            rwa_col: RWA column name.
            cat_col: Slotting category column name.
            maturity_col: is_short_maturity column name (None if absent).
            framework: "CRR" or "BASEL_3_1".
        """
        column_defs = get_c08_06_columns(framework)
        column_refs = [c.ref for c in column_defs]
        row_defs = get_c08_06_rows(framework)

        rows: list[dict[str, object]] = []

        for row_ref, category_label, is_short, _rw_display in row_defs:
            category_value = C08_06_CATEGORY_MAP.get(category_label)
            is_sub_stronger = "substantially stronger" in category_label

            # Filter by category
            if category_label == "Total":
                cat_data = type_data
            else:
                if category_value is None:
                    continue
                cat_data = type_data.filter(pl.col(cat_col) == category_value)

            # Filter by maturity band
            if is_short is not None and maturity_col is not None:
                cat_data = cat_data.filter(
                    pl.col(maturity_col) == is_short  # noqa: E712
                )
            elif is_short is not None and maturity_col is None and is_short:
                cat_data = type_data.clear()

            # "Substantially stronger" sub-rows: currently no pipeline column
            # identifies these exposures. They are reported as empty until
            # a `is_substantially_stronger` flag is added to the pipeline.
            if is_sub_stronger:
                cat_data = cat_data.clear()

            if len(cat_data) == 0 and category_label != "Total":
                # Still include the row with zero values for regulatory completeness
                values = dict.fromkeys(column_refs, 0.0)
                # Risk weight from row definition
                if "0070" in values and _rw_display:
                    rw_pct = _rw_display.replace("%", "").strip()
                    try:
                        values["0070"] = float(rw_pct) / 100.0
                    except ValueError:
                        values["0070"] = None
                else:
                    values["0070"] = None
                rows.append({"row_ref": row_ref, "row_name": category_label, **values})
                continue

            values = _compute_c08_06_values(
                cat_data,
                cols,
                ead_col,
                rwa_col,
                column_refs,
                framework,
            )
            rows.append({"row_ref": row_ref, "row_name": category_label, **values})

        if not rows:
            schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema: dict[str, pl.DataType] = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
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
    # Other real estate (Art. 124J) — non-qualifying RE
    "0350": {"is_qualifying": False},
    "0351": {"is_qualifying": False, "property_type": "residential", "materially_dependent": False},
    "0352": {"is_qualifying": False, "property_type": "residential", "materially_dependent": True},
    "0353": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": False},
    "0354": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": True},
    # Land ADC (CRE20.88)
    "0360": {"is_adc": True},
}

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


def _irb_sub_split(
    sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float, float]:
    """Split IRB corporate RWA into (FSE/large, SME, non-SME) using sub_rwa.

    When sub_rwa has no data for the given approach/ec, falls back to
    (0.0, 0.0, total) — all RWA reported as non-SME.
    """
    fse = 0.0
    sme = 0.0
    nonsme = 0.0
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, is_fse, _pt = key
        if a != approach or e != ec:
            continue
        matched = True
        if is_fse:
            fse += rwa
        elif is_sme:
            sme += rwa
        else:
            nonsme += rwa
    if not matched:
        return 0.0, 0.0, total
    return fse, sme, nonsme


def _irb_re_sub_split(
    sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float, float, float]:
    """Split IRB retail mortgage into (resi_sme, resi_nonsme, comm_sme, comm_nonsme).

    Uses property_type ('residential'/'rre' vs 'commercial'/'cre') and is_sme
    from the sub_rwa dict. Falls back to (0, total, 0, 0) when no sub data.
    """
    resi_sme = 0.0
    resi_nonsme = 0.0
    comm_sme = 0.0
    comm_nonsme = 0.0
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, _fse, pt = key
        if a != approach or e != ec:
            continue
        matched = True
        is_comm = pt in ("commercial", "cre")
        if is_comm:
            if is_sme:
                comm_sme += rwa
            else:
                comm_nonsme += rwa
        else:
            # residential, rre, or null → default to residential
            if is_sme:
                resi_sme += rwa
            else:
                resi_nonsme += rwa
    if not matched:
        return 0.0, total, 0.0, 0.0
    return resi_sme, resi_nonsme, comm_sme, comm_nonsme


def _irb_other_sme_split(
    sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    approach: str,
    ec: str,
    total: float,
) -> tuple[float, float]:
    """Split IRB retail_other into (SME, non-SME).

    Falls back to (total, 0.0) when no sub data (all reported as SME for
    backward compatibility with CRR row 0400).
    """
    sme = 0.0
    nonsme = 0.0
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, _fse, _pt = key
        if a != approach or e != ec:
            continue
        matched = True
        if is_sme:
            sme += rwa
        else:
            nonsme += rwa
    if not matched:
        return total, 0.0
    return sme, nonsme


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


def _filter_sl_type(data: pl.DataFrame, cols: set[str], sl_type: str) -> pl.DataFrame:
    """Filter to exposures with a given specialised lending type."""
    if "sl_type" not in cols:
        return data.clear()
    return data.filter(pl.col("sl_type") == sl_type)


def _filter_project_phase(data: pl.DataFrame, cols: set[str], phase: str) -> pl.DataFrame:
    """Filter to project finance exposures in a given phase."""
    if "sl_type" not in cols or "sl_project_phase" not in cols:
        return data.clear()
    return data.filter(
        (pl.col("sl_type") == "project_finance") & (pl.col("sl_project_phase") == phase)
    )


def _filter_re(
    data: pl.DataFrame,
    cols: set[str],
    *,
    property_type: str | None = None,
    materially_dependent: bool | None = None,
    is_sme: bool | None = None,
    is_adc: bool | None = None,
    is_qualifying: bool | None = None,
) -> pl.DataFrame:
    """Filter to real estate exposures with optional sub-criteria.

    Args:
        property_type: "residential" or "commercial" (None = any RE)
        materially_dependent: True/False filter on materially_dependent_on_property
        is_sme: True/False filter for SME sub-split (uses _filter_sme logic)
        is_adc: True/False filter on is_adc column
        is_qualifying: True/False filter on is_qualifying_re (Art. 124A)
    """
    if "property_type" not in cols:
        return data.clear()

    result = data.filter(pl.col("property_type").is_not_null())

    if is_qualifying is not None and "is_qualifying_re" in cols:
        result = result.filter(pl.col("is_qualifying_re").fill_null(True) == is_qualifying)
    elif is_qualifying is False:
        # No is_qualifying_re column — no non-qualifying RE to report
        return data.clear()

    if property_type is not None:
        result = result.filter(pl.col("property_type") == property_type)

    if materially_dependent is not None:
        # Prefer materially_dependent_on_property (exact regulatory field).
        # Fall back to has_income_cover (SA calculator proxy — True means
        # income depends on property, same semantics as materially_dependent).
        # Then is_income_producing (raw input, same meaning).
        md_col: str | None = None
        for candidate in (
            "materially_dependent_on_property",
            "has_income_cover",
            "is_income_producing",
        ):
            if candidate in cols:
                md_col = candidate
                break
        if md_col is not None:
            if md_col == "materially_dependent_on_property":
                # Exact field: null means unclassified — exclude from split
                result = result.filter(pl.col(md_col) == materially_dependent)
            else:
                # Fallback proxy: null defaults to False (not dependent)
                result = result.filter(pl.col(md_col).fill_null(False) == materially_dependent)
        else:
            return data.clear()

    if is_sme is not None:
        sme_subset = _filter_sme(result, set(result.columns))
        if is_sme:
            result = sme_subset
        else:
            sme_refs = (
                set(sme_subset["exposure_reference"].to_list()) if len(sme_subset) > 0 else set()
            )
            if sme_refs:
                result = result.filter(~pl.col("exposure_reference").is_in(sme_refs))

    if is_adc is not None and "is_adc" in cols:
        result = result.filter(pl.col("is_adc") == is_adc)
    elif is_adc is True:
        return data.clear()

    return result


def _filter_currency_mismatch(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to exposures where the currency mismatch multiplier was applied.

    Used for Basel 3.1 OF 07.00 memorandum row 0380.
    """
    if "currency_mismatch_multiplier_applied" not in cols:
        return data.clear()
    return data.filter(pl.col("currency_mismatch_multiplier_applied") == True)  # noqa: E712


def _filter_defaulted_at_rw(data: pl.DataFrame, cols: set[str], target_rw: float) -> pl.DataFrame:
    """Filter to defaulted exposures with a specific risk weight.

    Used for C 07.00 / OF 07.00 memorandum items:
    - Row 0300: Exposures in default subject to RW of 100% (target_rw=1.0)
    - Row 0320: Exposures in default subject to RW of 150% (target_rw=1.5)

    References:
        CRR Art. 127: Defaulted exposure risk weights
        PRA PS1/26 Art. 127: Defaulted exposure risk weights
    """
    defaulted = _filter_defaulted(data, cols)
    if len(defaulted) == 0:
        return defaulted
    rw_col = _pick(set(defaulted.columns), "risk_weight", "sa_final_risk_weight")
    if rw_col is None:
        return data.clear()
    return defaulted.filter(pl.col(rw_col).round(4) == round(target_rw, 4))


def _filter_re_secured(data: pl.DataFrame, cols: set[str], property_type: str) -> pl.DataFrame:
    """Filter to exposures secured by mortgages on immovable property.

    Used for CRR C 07.00 memorandum items:
    - Row 0290: Exposures secured by mortgages on commercial immovable property
    - Row 0310: Exposures secured by mortgages on residential immovable property

    References:
        CRR Art. 124-126: Exposures secured by immovable property
    """
    if "property_type" not in cols:
        return data.clear()
    return data.filter(pl.col("property_type") == property_type)


def _filter_supporting_factor(data: pl.DataFrame, cols: set[str], factor_type: str) -> pl.DataFrame:
    """Filter to exposures where a specific supporting factor was applied.

    Args:
        factor_type: "sme" or "infrastructure"

    Used for CRR C 07.00 Section 1 "of which" rows:
    - Row 0030: Exposures subject to SME-supporting factor
    - Row 0035: Exposures subject to infrastructure supporting factor

    References:
        CRR Art. 501: SME supporting factor
        CRR Art. 501a: Infrastructure supporting factor
    """
    flag_col = "is_sme" if factor_type == "sme" else "is_infrastructure"
    if flag_col not in cols:
        return data.clear()

    # Check for specific factor_applied columns first, then generic
    sf_applied = _pick(
        cols,
        f"{factor_type}_supporting_factor_applied",
        "supporting_factor_applied",
    )
    if sf_applied is None:
        # No supporting factor tracking — filter by flag only
        return data.filter(pl.col(flag_col) == True)  # noqa: E712

    return data.filter(
        (pl.col(flag_col) == True)  # noqa: E712
        & (pl.col(sf_applied) == True)  # noqa: E712
    )


def _filter_section3_row(
    data: pl.DataFrame,
    cols: set[str],
    row_ref: str,
    approach_col: str | None,
    framework: str,
) -> pl.DataFrame | None:
    """Filter class_data for a C 08.01 Section 3 row.

    Section 3 splits the total IRB exposure by calculation method:
    - 0070: PD/LGD model approach (F-IRB + A-IRB, excluding slotting)
    - 0080: Specialised lending slotting approach
    - 0160: Alternative treatment for real estate (CRR only)
    - 0170: Exposures from free deliveries
    - 0175: Purchased receivables (Basel 3.1 only)
    - 0180: Dilution risk on purchased receivables
    - 0190: Corporates without ECAI (Basel 3.1 only, unrated)
    - 0200: of which: investment grade (subset of 0190)

    Returns None for rows that cannot be populated from available data.

    References:
    - CRR Art. 142-191 (IRB approach assignment)
    - PRA PS1/26 Art. 122D (investment grade assessment)
    """
    if approach_col is None:
        return None

    if row_ref == "0070":
        # Exposures assigned to obligor grades or pools — non-slotting IRB
        return data.filter(pl.col(approach_col).is_in(["foundation_irb", "advanced_irb"]))

    if row_ref == "0080":
        # Specialised lending slotting approach
        return data.filter(pl.col(approach_col) == "slotting")

    if row_ref == "0160":
        # Alternative treatment: Secured by real estate (CRR only)
        # Requires a dedicated pipeline flag not yet available
        return None

    if row_ref == "0170":
        # Exposures from free deliveries (alternative RW or 100%)
        # Requires free_delivery identification not yet in pipeline
        return None

    if row_ref == "0175":
        # Purchased receivables (Basel 3.1 only)
        # Requires purchased_receivable identification not yet in pipeline
        return None

    if row_ref == "0180":
        # Dilution risk: Total purchased receivables
        # Requires dilution risk tracking not yet in pipeline
        return None

    if row_ref == "0190":
        # Corporates without ECAI — unrated corporates (Basel 3.1 only)
        if framework != "BASEL_3_1":
            return None
        if "exposure_class" not in cols:
            return None
        ec_filter = pl.col("exposure_class").str.contains("corporate", literal=True)
        # Unrated = no external credit assessment (sa_cqs is null or absent)
        if "sa_cqs" in cols:
            return data.filter(ec_filter & pl.col("sa_cqs").is_null())
        # Without sa_cqs, all IRB corporates are treated as unrated for this row
        return data.filter(ec_filter)

    if row_ref == "0200":
        # of which: investment grade (subset of unrated corporates)
        if framework != "BASEL_3_1":
            return None
        if "exposure_class" not in cols:
            return None
        ec_filter = pl.col("exposure_class").str.contains("corporate", literal=True)
        unrated_filter = pl.col("sa_cqs").is_null() if "sa_cqs" in cols else pl.lit(True)
        # Investment grade: use cp_is_investment_grade if available,
        # otherwise approximate from PD (Art. 122D: PD <= 0.5% as proxy)
        if "cp_is_investment_grade" in cols:
            return data.filter(
                ec_filter
                & unrated_filter
                & (pl.col("cp_is_investment_grade").fill_null(False) == True)  # noqa: E712
            )
        if "irb_pd_floored" in cols:
            return data.filter(ec_filter & unrated_filter & (pl.col("irb_pd_floored") <= 0.005))
        return None

    return None


def _null_row(row_ref: str, row_name: str, column_refs: list[str]) -> dict[str, object]:
    """Build a row dict with null values for all COREP columns."""
    row: dict[str, object] = {"row_ref": row_ref, "row_name": row_name}
    for ref in column_refs:
        row[ref] = None
    return row


def _of_02_01_row(
    row_ref: str,
    row_name: str,
    column_refs: list[str],
    *,
    modelled_rwa: float,
    sa_rwa: float,
) -> dict[str, object]:
    """Build an OF 02.01 row with modelled/SA RWA and U-TREA/S-TREA values.

    For a credit-risk-only calculator, U-TREA = modelled RWA and S-TREA = SA RWA
    for the credit risk row. At the total row, these are the same (only credit
    risk is in scope).
    """
    row: dict[str, object] = {"row_ref": row_ref, "row_name": row_name}
    values = {
        "0010": modelled_rwa,
        "0020": sa_rwa,
        "0030": modelled_rwa,
        "0040": sa_rwa,
    }
    for ref in column_refs:
        row[ref] = values.get(ref)
    return row


def _safe_sum_eager(data: pl.DataFrame, cols: set[str], *col_names: str) -> float:
    """Sum multiple columns from an eager DataFrame. Missing columns skipped."""
    total = 0.0
    for c in col_names:
        if c in cols:
            total += float(data[c].fill_null(0.0).sum())
    return total


def _col_sum_eager(data: pl.DataFrame, cols: set[str], col_name: str | None) -> float | None:
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
    migrated = full_df.filter((pl.col(gp_col) > 0) & (pl.col(pre_col) != pl.col(post_col)))
    if len(migrated) == 0:
        return {}

    result: dict[str, dict[str, float]] = {}

    # Outflows: grouped by pre_crm class (exposure leaving)
    outflows = migrated.group_by(pre_col).agg(pl.col(gp_col).sum().alias("outflow"))
    for row in outflows.iter_rows(named=True):
        ec = row[pre_col]
        result.setdefault(ec, {"outflow": 0.0, "inflow": 0.0})
        result[ec]["outflow"] = float(row["outflow"])

    # Inflows: grouped by post_crm class (exposure arriving)
    inflows = migrated.group_by(post_col).agg(pl.col(gp_col).sum().alias("inflow"))
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

    migrated = data.filter((pl.col(gp_col) > 0) & (pl.col(pre_col) != pl.col(post_col)))
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
        return dict.fromkeys(column_refs)

    ref_set = set(column_refs)
    values: dict[str, float | None] = {}

    # --- Exposure ---
    # 0010: Original exposure pre conversion factors
    values["0010"] = _safe_sum_eager(data, cols, "drawn_amount", "undrawn_amount")

    # 0030: (-) Value adjustments and provisions
    values["0030"] = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")

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
    # 0070: (-) Financial collateral: Simple method (Art. 222)
    # When Simple Method is elected, this is the total collateral value recognised.
    # Under Comprehensive Method, this is always 0.
    if "fcsm_collateral_value" in data.columns:
        values["0070"] = data["fcsm_collateral_value"].sum()
    else:
        values["0070"] = 0.0

    # 0080: (-) Other funded credit protection (non-financial collateral)
    values["0080"] = _sum_cols_eager(
        data,
        cols,
        "collateral_re_value",
        "collateral_receivables_value",
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
    # Try rwa_before_sme_factor first (legacy), then rwa_pre_factor (pipeline)
    rwa_pre = _col_sum_eager(data, cols, "rwa_before_sme_factor")
    if rwa_pre is None:
        rwa_pre = _col_sum_eager(data, cols, "rwa_pre_factor")
    values["0215"] = rwa_pre if rwa_pre is not None else _col_sum_eager(data, cols, rwa_col)

    # Pre-factor column: pipeline uses rwa_pre_factor; legacy uses rwa_before_sme_factor
    pre_factor_col = _pick(cols, "rwa_before_sme_factor", "rwa_pre_factor")

    # 0216: (-) SME supporting factor adjustment (CRR only)
    # Adjustment = sum(rwa_pre_factor - rwa_final) for SME-factor-applied exposures
    sme_applied_col = _pick(cols, "sme_supporting_factor_applied")
    if sme_applied_col and pre_factor_col:
        sme_data = data.filter(pl.col(sme_applied_col) == True)  # noqa: E712
        if len(sme_data) > 0:
            pre = float(sme_data[pre_factor_col].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0216"] = pre - post
        else:
            values["0216"] = 0.0
    elif "is_sme" in cols and "supporting_factor_applied" in cols and pre_factor_col:
        # Fallback: use is_sme + supporting_factor_applied (pipeline columns)
        sme_data = data.filter(
            (pl.col("is_sme") == True)  # noqa: E712
            & (pl.col("supporting_factor_applied") == True)  # noqa: E712
        )
        if len(sme_data) > 0:
            pre = float(sme_data[pre_factor_col].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0216"] = pre - post
        else:
            values["0216"] = 0.0
    else:
        values["0216"] = None

    # 0217: (-) Infrastructure supporting factor adjustment (CRR only)
    infra_applied_col = _pick(cols, "infrastructure_factor_applied")
    if infra_applied_col and pre_factor_col:
        infra_data = data.filter(pl.col(infra_applied_col) == True)  # noqa: E712
        if len(infra_data) > 0:
            pre = float(infra_data[pre_factor_col].fill_null(0.0).sum())
            post = float(infra_data[rwa_col].fill_null(0.0).sum())
            values["0217"] = pre - post
        else:
            values["0217"] = 0.0
    elif "is_infrastructure" in cols and "supporting_factor_applied" in cols and pre_factor_col:
        # Fallback: use is_infrastructure + supporting_factor_applied (pipeline columns)
        infra_data = data.filter(
            (pl.col("is_infrastructure") == True)  # noqa: E712
            & (pl.col("supporting_factor_applied") == True)  # noqa: E712
        )
        if len(infra_data) > 0:
            pre = float(infra_data[pre_factor_col].fill_null(0.0).sum())
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
        return dict.fromkeys(column_refs)

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
        values["0030"] = _safe_sum_eager(
            lfse_data, set(lfse_data.columns), "drawn_amount", "undrawn_amount"
        )
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
        data,
        cols,
        "collateral_re_value",
        "collateral_receivables_value",
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
    values["0090"] = v_c08_0020 - v_c08_0040 - v_c08_0050 - v_c08_0060 - v_c08_0070 + v_c08_0080

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

    # 0220: Double default unfunded protection (CRR only) — Art. 153(3), 202-203
    values["0220"] = _col_sum_eager(data, cols, "double_default_unfunded_protection")

    # --- Parameters ---
    # 0230: Exposure-weighted average LGD (%)
    lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
    if lgd_col is not None and ead_sum > 0:
        lgd_x_ead = float((data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0230"] = lgd_x_ead / ead_sum
    else:
        values["0230"] = None

    # 0240: EAD-weighted average LGD for LFSE — Phase 2F
    if lfse_data is not None and len(lfse_data) > 0:
        lfse_cols = set(lfse_data.columns)
        lfse_lgd_col = _pick(lfse_cols, "irb_lgd_floored", "irb_lgd_original")
        lfse_ead_sum = (
            float(lfse_data[ead_col].fill_null(0.0).sum()) if ead_col in lfse_cols else 0.0
        )
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
            (data["irb_maturity_m"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0250"] = (m_x_ead / ead_sum) * 365.0  # Convert years to days
    else:
        values["0250"] = None

    # --- RWEA ---
    # 0251-0254: Post-model adjustments (B3.1) — Task 3F
    values["0251"] = _col_sum_eager(data, cols, "rwa_pre_adjustments")
    values["0252"] = _col_sum_eager(data, cols, "post_model_adjustment_rwa")
    values["0253"] = _col_sum_eager(data, cols, "mortgage_rw_floor_adjustment")
    values["0254"] = _col_sum_eager(data, cols, "unrecognised_exposure_adjustment")

    # 0255: RWEA pre supporting factors (CRR only)
    rwa_pre = _col_sum_eager(data, cols, "rwa_before_sme_factor")
    if rwa_pre is None:
        rwa_pre = _col_sum_eager(data, cols, "rwa_pre_factor")
    values["0255"] = rwa_pre if rwa_pre is not None else _col_sum_eager(data, cols, rwa_col)

    # Pre-factor column: pipeline uses rwa_pre_factor; legacy uses rwa_before_sme_factor
    c08_pre_factor_col = _pick(cols, "rwa_before_sme_factor", "rwa_pre_factor")

    # 0256: (-) SME supporting factor adjustment (CRR only)
    sme_applied = _pick(cols, "sme_supporting_factor_applied")
    if sme_applied and c08_pre_factor_col:
        sme_data = data.filter(pl.col(sme_applied) == True)  # noqa: E712
        if len(sme_data) > 0:
            pre = float(sme_data[c08_pre_factor_col].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0256"] = pre - post
        else:
            values["0256"] = 0.0
    elif "is_sme" in cols and "supporting_factor_applied" in cols and c08_pre_factor_col:
        sme_data = data.filter(
            (pl.col("is_sme") == True)  # noqa: E712
            & (pl.col("supporting_factor_applied") == True)  # noqa: E712
        )
        if len(sme_data) > 0:
            pre = float(sme_data[c08_pre_factor_col].fill_null(0.0).sum())
            post = float(sme_data[rwa_col].fill_null(0.0).sum())
            values["0256"] = pre - post
        else:
            values["0256"] = 0.0
    else:
        values["0256"] = None

    # 0257: (-) Infrastructure supporting factor adjustment (CRR only)
    infra_applied = _pick(cols, "infrastructure_factor_applied")
    if infra_applied and c08_pre_factor_col:
        infra_data = data.filter(pl.col(infra_applied) == True)  # noqa: E712
        if len(infra_data) > 0:
            pre = float(infra_data[c08_pre_factor_col].fill_null(0.0).sum())
            post = float(infra_data[rwa_col].fill_null(0.0).sum())
            values["0257"] = pre - post
        else:
            values["0257"] = 0.0
    elif "is_infrastructure" in cols and "supporting_factor_applied" in cols and c08_pre_factor_col:
        infra_data = data.filter(
            (pl.col("is_infrastructure") == True)  # noqa: E712
            & (pl.col("supporting_factor_applied") == True)  # noqa: E712
        )
        if len(infra_data) > 0:
            pre = float(infra_data[c08_pre_factor_col].fill_null(0.0).sum())
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
    # 0280: Expected loss amount (pre post-model adjustments for B3.1)
    el_raw = _col_sum_eager(data, cols, "irb_expected_loss")
    el_pre = _col_sum_eager(data, cols, "el_pre_adjustment")
    values["0280"] = el_pre if el_pre is not None else el_raw

    # 0281-0282: EL adjustments (B3.1) — Task 3F
    values["0281"] = _col_sum_eager(data, cols, "post_model_adjustment_el")
    values["0282"] = _col_sum_eager(data, cols, "el_after_adjustment")

    # 0290: (-) Value adjustments and provisions
    prov = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")
    if abs(prov) < 1e-9:
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
            result[label] = _compute_c07_values(band_data, cols, ead_col, rwa_col, column_refs)

    return result


def _compute_c08_03_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_col: str,
    column_refs: list[str],
) -> dict[str, float | None]:
    """Compute C 08.03 column values for a PD range bucket.

    11 columns: on/off-BS exposure, average CCF, EAD, average PD,
    obligor count, average LGD, average maturity, RWEA, EL, provisions.

    Args:
        data: DataFrame filtered to a single PD range bucket.
        cols: Available column names in the data.
        ead_col: EAD column name.
        rwa_col: RWA column name.
        pd_col: PD column for reporting (post-input-floor for B31).
        column_refs: List of column refs to include in output.

    References:
    - CRR Art. 153 / Regulation (EU) 2021/451 Annex I (C 08.03)
    - PRA PS1/26 Annex I/II (OF 08.03)
    """
    values: dict[str, float | None] = {}
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0

    # 0010: Original exposure — on-balance sheet
    on_bs = _filter_on_bs(data, cols)
    if on_bs is not None and len(on_bs) > 0:
        values["0010"] = _safe_sum_eager(on_bs, set(on_bs.columns), "drawn_amount", "interest")
    else:
        values["0010"] = _safe_sum_eager(data, cols, "drawn_amount", "interest")

    # 0020: Original exposure — off-balance sheet
    off_bs = _filter_off_bs(data, cols)
    if off_bs is not None and len(off_bs) > 0:
        values["0020"] = _col_sum_eager(off_bs, set(off_bs.columns), "nominal_amount")
    else:
        values["0020"] = _col_sum_eager(data, cols, "nominal_amount")

    # 0030: Average CCF (%)
    ccf_col = _pick(cols, "ccf_applied", "ccf")
    if ccf_col is not None and ead_sum > 0:
        # Weighted average by nominal amount (off-BS component)
        nominal_col = _pick(cols, "nominal_amount")
        if nominal_col is not None:
            nominal_sum = float(data[nominal_col].fill_null(0.0).sum())
            if nominal_sum > 0:
                ccf_x_nominal = float(
                    (data[ccf_col].fill_null(0.0) * data[nominal_col].fill_null(0.0)).sum()
                )
                values["0030"] = ccf_x_nominal / nominal_sum
            else:
                values["0030"] = None
        else:
            values["0030"] = None
    else:
        values["0030"] = None

    # 0040: Exposure value (EAD, post CCF and post CRM)
    values["0040"] = ead_sum if ead_sum > 0 else 0.0

    # 0050: Exposure-weighted average PD (%)
    if pd_col in cols and ead_sum > 0:
        pd_x_ead = float((data[pd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0050"] = pd_x_ead / ead_sum
    else:
        values["0050"] = None

    # 0060: Number of obligors
    if "counterparty_reference" in cols:
        values["0060"] = float(data["counterparty_reference"].n_unique())
    else:
        values["0060"] = float(len(data))

    # 0070: Exposure-weighted average LGD (%)
    lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
    if lgd_col is not None and ead_sum > 0:
        lgd_x_ead = float((data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0070"] = lgd_x_ead / ead_sum
    else:
        values["0070"] = None

    # 0080: Exposure-weighted average maturity (years)
    if "irb_maturity_m" in cols and ead_sum > 0:
        m_x_ead = float(
            (data["irb_maturity_m"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0080"] = m_x_ead / ead_sum
    else:
        values["0080"] = None

    # 0090: RWEA
    values["0090"] = _col_sum_eager(data, cols, rwa_col)

    # 0100: Expected loss amount
    el_col = _pick(cols, "irb_expected_loss", "expected_loss")
    values["0100"] = _col_sum_eager(data, cols, el_col) if el_col else None

    # 0110: Value adjustments and provisions
    prov = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")
    if abs(prov) < 1e-9:
        held = _col_sum_eager(data, cols, "provision_held")
        values["0110"] = held if held is not None else prov
    else:
        values["0110"] = prov

    # Filter to only refs in this framework's column set (C 08.03)
    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _compute_c08_05_values(
    data: pl.DataFrame,
    cols: set[str],
    pd_col: str,
    column_refs: list[str],
) -> dict[str, float | None]:
    """Compute C 08.05 column values for a PD range bucket.

    5 columns: arithmetic average PD, obligor count (prior year),
    defaults during year, observed default rate, historical annual default rate.

    Why: PD backtesting compares model-assigned PDs against realised default
    rates per PD bucket. This is a key supervisory metric for IRB model
    validation under CRR Art. 180 and PRA PS1/26.

    Note on historical data: Cols 0020 (prior-year obligors) and 0050
    (historical annual default rate) ideally require multi-year lookback data.
    When only current-period data is available from the pipeline, col 0020
    uses current obligor count and col 0050 uses the current-period observed
    default rate as best-effort approximations.

    Args:
        data: DataFrame filtered to a single PD range bucket.
        cols: Available column names in the data.
        pd_col: PD column for reporting (post-input-floor for B31).
        column_refs: List of column refs to include in output.

    References:
    - CRR Art. 180, Regulation (EU) 2021/451 Annex I (C 08.05)
    - PRA PS1/26 Annex I/II (OF 08.05)
    """
    values: dict[str, float | None] = {}
    n_rows = len(data)

    # 0010: Arithmetic average PD (%)
    # Unlike C 08.03 col 0050 (EAD-weighted), this is a simple arithmetic average
    if pd_col in cols and n_rows > 0:
        pd_sum = float(data[pd_col].fill_null(0.0).sum())
        values["0010"] = pd_sum / n_rows
    else:
        values["0010"] = None

    # Determine obligor count and default count
    cp_col = "counterparty_reference" if "counterparty_reference" in cols else None
    default_col = _pick(cols, "is_defaulted", "default_status")

    n_obligors = float(data[cp_col].n_unique()) if cp_col is not None else float(n_rows)

    if default_col is not None:
        defaulted = data.filter(pl.col(default_col) == True)  # noqa: E712
        if cp_col is not None:
            n_defaults = float(defaulted[cp_col].n_unique())
        else:
            n_defaults = float(len(defaulted))
    else:
        # Fall back to PD >= 1.0 as default indicator
        if pd_col in cols:
            defaulted = data.filter(pl.col(pd_col) >= 1.0)
            if cp_col is not None:
                n_defaults = float(defaulted[cp_col].n_unique())
            else:
                n_defaults = float(len(defaulted))
        else:
            n_defaults = 0.0

    # 0020: Number of obligors at end of previous year
    # Best-effort: use current-period obligor count when historical data absent
    prior_year_col = _pick(cols, "prior_year_obligor_count")
    if prior_year_col is not None:
        values["0020"] = float(data[prior_year_col].fill_null(0.0).sum())
    else:
        values["0020"] = n_obligors

    # 0030: Of which: defaulted during the year
    values["0030"] = n_defaults

    # 0040: Observed average default rate (%)
    if n_obligors > 0:
        values["0040"] = n_defaults / n_obligors
    else:
        values["0040"] = 0.0

    # 0050: Average historical annual default rate (%)
    # Best-effort: use current observed default rate when multi-year data absent
    hist_rate_col = _pick(cols, "historical_annual_default_rate")
    if hist_rate_col is not None and n_rows > 0:
        values["0050"] = float(data[hist_rate_col].fill_null(0.0).mean())
    else:
        # Fall back to current observed rate as single-period approximation
        values["0050"] = values["0040"]

    # Filter to only refs in this framework's column set (C 08.05)
    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _compute_c08_06_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: list[str],
    framework: str,
) -> dict[str, float | None]:
    """Compute C 08.06 column values for a slotting category × maturity row.

    10 columns (CRR) or 11 (Basel 3.1): original exposure, post-CRM exposure,
    off-BS items, FCCM deduction (B31 only), exposure value (EAD), off-BS
    exposure value, CCR exposure value, risk weight, RWEA, EL, provisions.

    Args:
        data: DataFrame filtered to a single category/maturity bucket.
        cols: Available column names in the data.
        ead_col: EAD column name.
        rwa_col: RWA column name.
        column_refs: List of column refs to include in output.
        framework: "CRR" or "BASEL_3_1".

    References:
    - CRR Art. 153(5) / Regulation (EU) 2021/451 Annex I (C 08.06)
    - PRA PS1/26 Annex I/II (OF 08.06)
    """
    values: dict[str, float | None] = {}
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0

    # 0010: Original exposure pre conversion factors
    values["0010"] = _safe_sum_eager(
        data, cols, "drawn_amount", "interest", "nominal_amount", "undrawn_amount"
    )

    # 0020: Exposure after CRM substitution effects pre CCFs
    crm_col = _pick(cols, "ead_pre_ccf", "exposure_post_crm")
    if crm_col is not None:
        values["0020"] = _col_sum_eager(data, cols, crm_col)
    else:
        values["0020"] = values["0010"]

    # 0030: Of which: off-balance sheet items (original)
    off_bs = _filter_off_bs(data, cols)
    if off_bs is not None and len(off_bs) > 0:
        values["0030"] = _safe_sum_eager(
            off_bs, set(off_bs.columns), "nominal_amount", "undrawn_amount"
        )
    else:
        values["0030"] = _col_sum_eager(data, cols, "nominal_amount")

    # 0031: (-) Change in exposure due to FCCM (Basel 3.1 only)
    if "0031" in column_refs:
        values["0031"] = None

    # 0040: Exposure value (EAD)
    values["0040"] = ead_sum if ead_sum > 0 else 0.0

    # 0050: Of which: off-balance sheet items (exposure value)
    if off_bs is not None and len(off_bs) > 0:
        off_cols = set(off_bs.columns)
        values["0050"] = _col_sum_eager(off_bs, off_cols, ead_col)
    else:
        values["0050"] = None

    # 0060: Of which: arising from counterparty credit risk (out of scope)
    values["0060"] = None

    # 0070: Risk weight (exposure-weighted average for this bucket)
    rw_col = _pick(cols, "risk_weight")
    if rw_col is not None and ead_sum > 0:
        rw_x_ead = float((data[rw_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0070"] = rw_x_ead / ead_sum
    elif rw_col is not None:
        rw_vals = data[rw_col].drop_nulls()
        values["0070"] = float(rw_vals[0]) if len(rw_vals) > 0 else None
    else:
        values["0070"] = None

    # 0080: RWEA (after supporting factors for CRR, plain RWEA for B31)
    if framework != "BASEL_3_1" and "rwa_post_factor" in cols:
        values["0080"] = _col_sum_eager(data, cols, "rwa_post_factor")
    else:
        values["0080"] = _col_sum_eager(data, cols, rwa_col)

    # 0090: Expected loss amount
    el_col = _pick(cols, "expected_loss", "irb_expected_loss")
    values["0090"] = _col_sum_eager(data, cols, el_col) if el_col else None

    # 0100: (-) Value adjustments and provisions
    prov = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")
    if abs(prov) < 1e-9:
        held = _col_sum_eager(data, cols, "provision_held")
        values["0100"] = held if held is not None else prov
    else:
        values["0100"] = prov

    # Filter to only refs in this framework's column set (C 08.06)
    return {ref: values.get(ref) for ref in column_refs if ref in values}


# =============================================================================
# C 09.01 / OF 09.01 — GEOGRAPHICAL BREAKDOWN SA HELPERS
# =============================================================================


def _filter_c09_01_row(
    data: pl.DataFrame,
    cols: set[str],
    row_key: str,
    framework: str,
) -> pl.DataFrame:
    """Filter SA data to match a C 09.01 row definition.

    Maps row keys to pipeline exposure_class values and applies additional
    sub-row filters (SME, RE sub-types, SL sub-types) as needed.
    """
    ec_col = _pick(cols, "exposure_class")
    if ec_col is None:
        return data.clear()

    # Main exposure class rows — filter by the pipeline class values that map
    # to this row key via C09_01_SA_CLASS_MAP
    matching_classes = [ec for ec, mapped in C09_01_SA_CLASS_MAP.items() if mapped == row_key]

    if not matching_classes:
        return data.clear()

    base = data.filter(pl.col(ec_col).is_in(matching_classes))

    # Sub-row filters for SME, RE, SL sub-types
    if row_key == "corporate_sme":
        return _filter_sme(base, cols)
    if row_key == "retail_sme":
        return _filter_sme(base, cols)
    if row_key == "mortgage_sme":
        return _filter_sme(base, cols)
    if row_key == "re_sme":
        return _filter_sme(base, cols)

    # B31-specific sub-rows
    if row_key == "real_estate":
        # "Real estate exposures" — all mortgage-class exposures
        return data.filter(pl.col(ec_col) == "retail_mortgage")
    if row_key == "re_residential":
        if "property_type" in cols:
            return data.filter(
                (pl.col(ec_col) == "retail_mortgage")
                & (pl.col("property_type").is_in(["residential", "rre"]))
            )
        return data.clear()
    if row_key == "re_commercial":
        if "property_type" in cols:
            return data.filter(
                (pl.col(ec_col) == "retail_mortgage")
                & (pl.col("property_type").is_in(["commercial", "cre"]))
            )
        return data.clear()
    if row_key == "re_other":
        if "property_type" in cols:
            return data.filter(
                (pl.col(ec_col) == "retail_mortgage")
                & (pl.col("property_type").is_in(["other", "other_re"]))
            )
        return data.clear()
    if row_key == "re_adc":
        if "property_type" in cols:
            return data.filter(
                (pl.col(ec_col) == "retail_mortgage") & (pl.col("property_type") == "adc")
            )
        return data.clear()

    # SL sub-types (B31 only)
    if row_key in ("sl_object_finance", "sl_commodities_finance", "sl_project_finance"):
        sl_type_map = {
            "sl_object_finance": "object_finance",
            "sl_commodities_finance": "commodities_finance",
            "sl_project_finance": "project_finance",
        }
        if "sl_type" in cols:
            return data.filter(
                (pl.col(ec_col) == "specialised_lending")
                & (pl.col("sl_type") == sl_type_map[row_key])
            )
        return data.clear()

    # CIU sub-approaches
    if row_key == "ciu_look_through":
        if "ciu_approach" in cols:
            return data.filter(
                (pl.col(ec_col) == "ciu") & (pl.col("ciu_approach") == "look_through")
            )
        return data.clear()
    if row_key == "ciu_mandate":
        if "ciu_approach" in cols:
            return data.filter(
                (pl.col(ec_col) == "ciu") & (pl.col("ciu_approach") == "mandate_based")
            )
        return data.clear()
    if row_key == "ciu_fallback":
        if "ciu_approach" in cols:
            return data.filter((pl.col(ec_col) == "ciu") & (pl.col("ciu_approach") == "fallback"))
        return data.clear()

    # "retail" row = all retail classes combined
    if row_key == "retail":
        return data.filter(pl.col(ec_col).is_in(["retail_other", "retail_qrre"]))

    return base


def _compute_c09_01_values(
    data: pl.DataFrame,
    cols: set[str],
    column_refs: list[str],
    framework: str,
) -> dict[str, object]:
    """Compute column values for a C 09.01 / OF 09.01 row.

    Maps COREP column refs to pipeline columns:
    - 0010: Original exposure pre conversion factors (ead_gross / nominal_amount)
    - 0020: Defaulted exposures (ead_gross where default_status=True)
    - 0040: Observed new defaults for the period (null — requires temporal data)
    - 0050: General credit risk adjustments (gcra_provision_amount)
    - 0055: Specific credit risk adjustments (scra_provision_amount)
    - 0060: Write-offs (null — requires write-off tracking)
    - 0061: Additional value adjustments (null — requires AVA tracking)
    - 0070: Credit risk adjustments/write-offs for observed new defaults (null)
    - 0075: Exposure value (ead_final)
    - 0080: RWEA pre supporting factors (rwa_final, CRR only)
    - 0081: (-) SME supporting factor adjustment (CRR only, null)
    - 0082: (-) Infrastructure supporting factor adjustment (CRR only, null)
    - 0090: RWEA after supporting factors / Risk-weighted exposure amount
    """
    values: dict[str, object] = {}

    ead_gross_col = _pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = _pick(cols, "ead_final", "final_ead", "ead")
    rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")

    # 0010: Original exposure pre conversion factors
    values["0010"] = _col_sum_eager(data, cols, ead_gross_col)

    # 0020: Defaulted exposures
    defaulted = _filter_defaulted(data, cols)
    if len(defaulted) > 0 and ead_gross_col:
        values["0020"] = float(defaulted[ead_gross_col].fill_null(0.0).sum())
    else:
        values["0020"] = 0.0

    # 0040: Observed new defaults (requires temporal data — null)
    values["0040"] = None

    # 0050: General credit risk adjustments
    values["0050"] = _col_sum_eager(data, cols, "gcra_provision_amount")

    # 0055: Specific credit risk adjustments
    values["0055"] = _col_sum_eager(data, cols, "scra_provision_amount")

    # 0060: Write-offs (null — requires write-off tracking)
    values["0060"] = None

    # 0061: Additional value adjustments (null — requires AVA tracking)
    values["0061"] = None

    # 0070: Credit risk adjustments for observed new defaults (null)
    values["0070"] = None

    # 0075: Exposure value (ead_final)
    values["0075"] = _col_sum_eager(data, cols, ead_col)

    # 0080: RWEA pre supporting factors (CRR only)
    if "0080" in column_refs:
        values["0080"] = _col_sum_eager(data, cols, rwa_col)

    # 0081: (-) SME supporting factor adjustment (CRR only, null)
    if "0081" in column_refs:
        values["0081"] = None

    # 0082: (-) Infrastructure supporting factor adjustment (CRR only, null)
    if "0082" in column_refs:
        values["0082"] = None

    # 0090: RWEA (after supporting factors for CRR, plain for B31)
    values["0090"] = _col_sum_eager(data, cols, rwa_col)

    return {ref: values.get(ref) for ref in column_refs}


# =============================================================================
# C 09.02 / OF 09.02 — GEOGRAPHICAL BREAKDOWN IRB HELPERS
# =============================================================================


def _filter_c09_02_row(
    data: pl.DataFrame,
    cols: set[str],
    row_key: str,
    framework: str,
    approach_col: str | None,
) -> pl.DataFrame:
    """Filter IRB data to match a C 09.02 row definition.

    Maps row keys to pipeline exposure_class values and applies additional
    sub-row filters (SL, SME, RE sub-types) as needed.
    """
    ec_col = _pick(cols, "exposure_class")
    if ec_col is None:
        return data.clear()

    # Main IRB exposure class rows
    if row_key == "central_govt_central_bank":
        return data.filter(pl.col(ec_col) == "central_govt_central_bank")

    if row_key == "institution":
        return data.filter(pl.col(ec_col) == "institution")

    if row_key == "corporate":
        # All corporate-class exposures (corporate, corporate_sme, specialised_lending)
        return data.filter(
            pl.col(ec_col).is_in(["corporate", "corporate_sme", "specialised_lending"])
        )

    # Corporate sub-rows
    if row_key == "sl_excl_slotting":
        base = data.filter(pl.col(ec_col) == "specialised_lending")
        if approach_col and approach_col in cols:
            return base.filter(pl.col(approach_col) != "slotting")
        return base

    if row_key == "sl_slotting":
        if approach_col and approach_col in cols:
            return data.filter(
                (pl.col(ec_col) == "specialised_lending") & (pl.col(approach_col) == "slotting")
            )
        return data.clear()

    if row_key == "corporate_sme":
        return _filter_sme(
            data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"])),
            cols,
        )

    if row_key == "corporate_fse_large":
        # B31 Art. 147(4C) — financial corporates and large corporates
        base = data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"]))
        if "apply_fi_scalar" in cols:
            return base.filter(pl.col("apply_fi_scalar") == True)  # noqa: E712
        return data.clear()

    if row_key == "corporate_purchased_receivables":
        return data.clear()  # Requires purchased receivable tracking

    if row_key == "corporate_non_sme":
        # Non-SME general corporates (excludes SL and FSE/large)
        base = data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"]))
        non_sme = base
        if "sme_supporting_factor_eligible" in cols:
            non_sme = base.filter(
                pl.col("sme_supporting_factor_eligible") != True  # noqa: E712
            )
        elif "exposure_class" in cols:
            non_sme = base.filter(~pl.col("exposure_class").str.contains("sme"))
        if "apply_fi_scalar" in cols:
            non_sme = non_sme.filter(
                pl.col("apply_fi_scalar") != True  # noqa: E712
            )
        return non_sme

    # Retail main row
    if row_key == "retail":
        return data.filter(pl.col(ec_col).is_in(["retail_mortgage", "retail_qrre", "retail_other"]))

    # CRR retail sub-rows
    if row_key == "retail_mortgage":
        return data.filter(pl.col(ec_col) == "retail_mortgage")

    if row_key == "retail_mortgage_sme":
        return _filter_sme(data.filter(pl.col(ec_col) == "retail_mortgage"), cols)

    if row_key == "retail_mortgage_non_sme":
        base = data.filter(pl.col(ec_col) == "retail_mortgage")
        sme = _filter_sme(base, cols)
        if len(sme) > 0:
            sme_refs = (
                set(sme["exposure_reference"].to_list()) if "exposure_reference" in cols else set()
            )
            if sme_refs:
                return base.filter(~pl.col("exposure_reference").is_in(list(sme_refs)))
        return base

    if row_key == "retail_qrre":
        return data.filter(pl.col(ec_col) == "retail_qrre")

    if row_key == "retail_other":
        return data.filter(pl.col(ec_col) == "retail_other")

    if row_key == "retail_other_sme":
        return _filter_sme(data.filter(pl.col(ec_col) == "retail_other"), cols)

    if row_key == "retail_other_non_sme":
        base = data.filter(pl.col(ec_col) == "retail_other")
        sme = _filter_sme(base, cols)
        if len(sme) > 0:
            sme_refs = (
                set(sme["exposure_reference"].to_list()) if "exposure_reference" in cols else set()
            )
            if sme_refs:
                return base.filter(~pl.col("exposure_reference").is_in(list(sme_refs)))
        return base

    # B31 retail RE sub-rows
    if row_key == "retail_resi_re_sme":
        base = data.filter(pl.col(ec_col) == "retail_mortgage")
        if "property_type" in cols:
            base = base.filter(pl.col("property_type").is_in(["residential", "rre"]))
        return _filter_sme(base, cols)

    if row_key == "retail_resi_re_non_sme":
        base = data.filter(pl.col(ec_col) == "retail_mortgage")
        if "property_type" in cols:
            base = base.filter(pl.col("property_type").is_in(["residential", "rre"]))
        sme = _filter_sme(base, cols)
        if len(sme) > 0:
            sme_refs = (
                set(sme["exposure_reference"].to_list()) if "exposure_reference" in cols else set()
            )
            if sme_refs:
                return base.filter(~pl.col("exposure_reference").is_in(list(sme_refs)))
        return base

    if row_key == "retail_comm_re_sme":
        base = data.filter(pl.col(ec_col) == "retail_mortgage")
        if "property_type" in cols:
            base = base.filter(pl.col("property_type").is_in(["commercial", "cre"]))
        return _filter_sme(base, cols)

    if row_key == "retail_comm_re_non_sme":
        base = data.filter(pl.col(ec_col) == "retail_mortgage")
        if "property_type" in cols:
            base = base.filter(pl.col("property_type").is_in(["commercial", "cre"]))
        sme = _filter_sme(base, cols)
        if len(sme) > 0:
            sme_refs = (
                set(sme["exposure_reference"].to_list()) if "exposure_reference" in cols else set()
            )
            if sme_refs:
                return base.filter(~pl.col("exposure_reference").is_in(list(sme_refs)))
        return base

    if row_key == "retail_purchased_receivables":
        return data.clear()  # Requires purchased receivable tracking

    if row_key == "equity":
        return data.filter(pl.col(ec_col) == "equity")

    return data.clear()


def _compute_c09_02_values(
    data: pl.DataFrame,
    cols: set[str],
    column_refs: list[str],
    framework: str,
) -> dict[str, object]:
    """Compute column values for a C 09.02 / OF 09.02 row.

    Maps COREP column refs to pipeline columns:
    - 0010: Original exposure pre conversion factors
    - 0030: Of which: defaulted
    - 0040: Observed new defaults (null — requires temporal data)
    - 0050: General credit risk adjustments
    - 0055: Specific credit risk adjustments
    - 0060: Write-offs (null)
    - 0070: Credit risk adjustments for observed new defaults (null)
    - 0080: PD assigned to obligor grade (EAD-weighted average)
    - 0090: Exposure weighted average LGD (%)
    - 0100: Of which: defaulted (LGD)
    - 0105: Exposure value (ead_final)
    - 0107: Of which: defaulted (exposure value, B31 only)
    - 0110: RWEA pre supporting factors (CRR only)
    - 0120: Of which: defaulted (RWEA)
    - 0121: (-) SME supporting factor adjustment (CRR only, null)
    - 0122: (-) Infrastructure supporting factor adjustment (CRR only, null)
    - 0125: RWEA after supporting factors / RWEA
    - 0130: Expected loss amount
    """
    values: dict[str, object] = {}

    ead_gross_col = _pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = _pick(cols, "ead_final", "final_ead", "ead")
    rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa")
    pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")
    lgd_col = _pick(cols, "lgd_post_crm", "irb_lgd_floored", "lgd_final")
    el_col = _pick(cols, "expected_loss", "irb_expected_loss")

    # 0010: Original exposure pre conversion factors
    values["0010"] = _col_sum_eager(data, cols, ead_gross_col)

    # 0030: Of which: defaulted
    defaulted = _filter_defaulted(data, cols)
    if len(defaulted) > 0 and ead_gross_col:
        values["0030"] = float(defaulted[ead_gross_col].fill_null(0.0).sum())
    else:
        values["0030"] = 0.0

    # 0040: Observed new defaults (null)
    values["0040"] = None

    # 0050: General credit risk adjustments
    values["0050"] = _col_sum_eager(data, cols, "gcra_provision_amount")

    # 0055: Specific credit risk adjustments
    values["0055"] = _col_sum_eager(data, cols, "scra_provision_amount")

    # 0060: Write-offs (null)
    values["0060"] = None

    # 0070: Credit risk adjustments for observed new defaults (null)
    values["0070"] = None

    # 0080: PD assigned to obligor grade — EAD-weighted average
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
    if pd_col and ead_col and ead_sum > 0:
        pd_x_ead = float((data[pd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0080"] = pd_x_ead / ead_sum
    elif pd_col:
        pd_vals = data[pd_col].drop_nulls()
        values["0080"] = float(pd_vals.mean()) if len(pd_vals) > 0 else None
    else:
        values["0080"] = None

    # 0090: Exposure weighted average LGD (%)
    if lgd_col and ead_col and ead_sum > 0:
        lgd_x_ead = float((data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0090"] = lgd_x_ead / ead_sum
    elif lgd_col:
        lgd_vals = data[lgd_col].drop_nulls()
        values["0090"] = float(lgd_vals.mean()) if len(lgd_vals) > 0 else None
    else:
        values["0090"] = None

    # 0100: Of which: defaulted (LGD)
    if len(defaulted) > 0 and lgd_col:
        def_ead_sum = float(defaulted[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
        if def_ead_sum > 0 and ead_col:
            lgd_x_ead_def = float(
                (defaulted[lgd_col].fill_null(0.0) * defaulted[ead_col].fill_null(0.0)).sum()
            )
            values["0100"] = lgd_x_ead_def / def_ead_sum
        else:
            def_lgd = defaulted[lgd_col].drop_nulls()
            values["0100"] = float(def_lgd.mean()) if len(def_lgd) > 0 else None
    else:
        values["0100"] = None

    # 0105: Exposure value (ead_final)
    values["0105"] = _col_sum_eager(data, cols, ead_col)

    # 0107: Of which: defaulted (exposure value, B31 only)
    if "0107" in column_refs:
        if len(defaulted) > 0 and ead_col:
            values["0107"] = float(defaulted[ead_col].fill_null(0.0).sum())
        else:
            values["0107"] = 0.0

    # 0110: RWEA pre supporting factors (CRR only)
    if "0110" in column_refs:
        values["0110"] = _col_sum_eager(data, cols, rwa_col)

    # 0120: Of which: defaulted (RWEA)
    if len(defaulted) > 0 and rwa_col:
        values["0120"] = float(defaulted[rwa_col].fill_null(0.0).sum())
    else:
        values["0120"] = 0.0

    # 0121: (-) SME supporting factor adjustment (CRR only, null)
    if "0121" in column_refs:
        values["0121"] = None

    # 0122: (-) Infrastructure supporting factor adjustment (CRR only, null)
    if "0122" in column_refs:
        values["0122"] = None

    # 0125: RWEA (after supporting factors for CRR, plain for B31)
    values["0125"] = _col_sum_eager(data, cols, rwa_col)

    # 0130: Expected loss amount
    values["0130"] = _col_sum_eager(data, cols, el_col) if el_col else None

    return {ref: values.get(ref) for ref in column_refs}
