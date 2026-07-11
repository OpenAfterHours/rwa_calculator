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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.reporting.corep.c07 import c07_population, generate_c07
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
    C34_01_ROWS,
    C34_02_ROWS,
    C34_04_ROWS,
    C34_08_ROWS,
    CRR_C02_00_COLUMN_REFS,
    IRB_EXPOSURE_CLASS_ROWS,
    OF_02_01_COLUMN_REFS,
    OF_02_01_COLUMNS,
    OF_02_01_ROW_SECTIONS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    COREPRow,
    get_c02_00_columns,
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
    get_c34_01_columns,
    get_c34_02_columns,
    get_c34_04_columns,
    get_c34_08_columns,
    get_irb_row_sections,
)
from rwa_calc.reporting.kernel import (
    available_columns as _available_columns,
)
from rwa_calc.reporting.kernel import (
    col_sum as _col_sum_eager,
)
from rwa_calc.reporting.kernel import (
    column_name_map,
    write_template_sheet,
)
from rwa_calc.reporting.kernel import (
    filter_off_bs as _filter_off_bs,
)
from rwa_calc.reporting.kernel import (
    filter_on_bs as _filter_on_bs,
)
from rwa_calc.reporting.kernel import (
    null_row as _null_row,
)
from rwa_calc.reporting.kernel import (
    pick as _pick,
)
from rwa_calc.reporting.kernel import (
    safe_sum as _safe_sum_eager,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from polars._typing import PolarsDataType
    from xlsxwriter import Workbook

    from rwa_calc.api.models import CalculationResponse
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import OutputFloorConfig
    from rwa_calc.contracts.results import ExportResult

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
    C 34.01 (CCR analysis by approach): Single DataFrame, SA-CCR total EAD
        (col 0010) and RWEA (col 0020). None when the portfolio has no CCR
        (``ccr__``-prefixed) rows.
    C 34.02 (SA-CCR EAD per netting set): dict keyed by ``netting_set_id``,
        each a 1-row DataFrame carrying that netting set's EAD (col 0010).
        Empty dict when the portfolio has no CCR rows.
    C 34.04 (CVA capital): Single DataFrame, total BA-CVA RWEA (col 0010).
        Basel 3.1 only — None under CRR or when ``cva_rwa`` is absent.
    C 34.08 (CCP exposures): Single DataFrame, QCCP trade-leg (2%/4%),
        non-QCCP, and default-fund EAD (col 0010) / RWEA (col 0020). The
        QCCP/non-QCCP partition mirrors the aggregator discriminator
        (``cp_entity_type == "ccp" & cp_is_qccp.fill_null(True)``). None when
        the portfolio has no CCP exposures.

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
    c34_01: pl.DataFrame | None = None
    c34_02: dict[str, pl.DataFrame] = field(default_factory=dict)
    c34_04: pl.DataFrame | None = None
    c34_08: pl.DataFrame | None = None
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
        # FCCM SFTs are SA-risk-weighted but carry the CCR-via-SA
        # ``approach_applied`` tag (``standardised_ccr``) under the output floor,
        # so a plain ``approach_applied == "standardised"`` filter would drop
        # them under Basel 3.1. Admit them explicitly via ``risk_type ==
        # "CCR_SFT"`` so the SFT EAD lands in C 07.00 (total row 0010 + the
        # SFT-netting breakdown row 0090, PS1/26 App. 17). SA-CCR derivatives are
        # NOT admitted here — they report under C 34 (CRR Art. 274).
        c07_00 = self._generate_all_c07(results, cols, framework, errors)

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
        c09_01 = self._generate_all_c09_01(c07_population(results, cols), cols, framework, errors)

        # C 09.02 / OF 09.02 — Geographical Breakdown IRB
        c09_02 = self._generate_all_c09_02(irb_data, cols, framework, errors)

        # C 34.01 / 02 / 04 / 08 — Counterparty Credit Risk (CCR)
        c34_01 = self._generate_c34_01(results, cols)
        c34_02 = self._generate_c34_02(results, cols)
        c34_04 = self._generate_c34_04(results, cols, framework)
        c34_08 = self._generate_c34_08(results, cols)

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
            c34_01=c34_01,
            c34_02=c34_02,
            c34_04=c34_04,
            c34_08=c34_08,
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
        from rwa_calc.contracts.results import ExportResult

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
            total_rows += self._export_all_template_sheets(workbook, bundle)
        finally:
            workbook.close()

        logger.info("COREP templates written to %s (%d rows)", output_path, total_rows)

        return ExportResult(
            format="corep_excel",
            files=[output_path],
            row_count=total_rows,
        )

    def _export_all_template_sheets(self, workbook: Workbook, bundle: COREPTemplateBundle) -> int:
        """Dispatch all per-template writers for ``bundle`` to ``workbook``.

        Returns the total row count written. Encapsulates the 8 per-class
        templates + 4 single-sheet templates + 2 geographical templates so
        the public ``export_to_excel`` stays focused on workbook lifecycle.
        """
        framework = bundle.framework
        is_b31 = framework == "BASEL_3_1"
        total = 0
        total += self._write_template_sheets(
            workbook,
            bundle.c07_00,
            "C 07.00",
            SA_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c07_columns(framework)),
        )
        total += self._write_template_sheets(
            workbook,
            bundle.c08_01,
            "C 08.01",
            IRB_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c08_columns(framework)),
        )
        total += self._write_template_sheets(
            workbook,
            bundle.c08_02,
            "C 08.02",
            IRB_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c08_02_columns(framework)),
        )
        total += self._write_template_sheets(
            workbook,
            bundle.c08_03,
            "C 08.03",
            IRB_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c08_03_columns(framework)),
        )
        total += self._write_template_sheets(
            workbook,
            bundle.c08_04,
            "OF 08.04" if is_b31 else "C 08.04",
            IRB_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c08_04_columns(framework)),
        )
        total += self._write_template_sheets(
            workbook,
            bundle.c08_05,
            "OF 08.05" if is_b31 else "C 08.05",
            IRB_EXPOSURE_CLASS_ROWS,
            column_name_map(get_c08_05_columns(framework)),
        )
        sl_type_names = get_c08_06_sl_types(framework)
        sl_class_map = {k: (k, v) for k, v in sl_type_names.items()}
        total += self._write_template_sheets(
            workbook,
            bundle.c08_06,
            "C 08.06",
            sl_class_map,
            column_name_map(get_c08_06_columns(framework)),
        )

        if bundle.c08_07 is not None:
            total += self._write_single_template_sheet(
                workbook,
                bundle.c08_07,
                "OF 08.07" if is_b31 else "C 08.07",
                column_name_map(get_c08_07_columns(framework)),
            )
        if bundle.of_02_01 is not None:
            total += self._write_single_template_sheet(
                workbook, bundle.of_02_01, "OF 02.01", column_name_map(OF_02_01_COLUMNS)
            )
        if bundle.c_02_00 is not None:
            total += self._write_single_template_sheet(
                workbook,
                bundle.c_02_00,
                "OF 02.00" if is_b31 else "C 02.00",
                column_name_map(get_c02_00_columns(framework)),
            )
        if bundle.c09_01:
            total += self._write_geo_template_sheets(
                workbook,
                bundle.c09_01,
                "OF 09.01" if is_b31 else "C 09.01",
                column_name_map(get_c09_01_columns(framework)),
            )
        if bundle.c09_02:
            total += self._write_geo_template_sheets(
                workbook,
                bundle.c09_02,
                "OF 09.02" if is_b31 else "C 09.02",
                column_name_map(get_c09_02_columns(framework)),
            )
        return total

    @staticmethod
    def _write_template_sheets(
        workbook: Workbook,
        templates: dict[str, pl.DataFrame],
        prefix: str,
        class_names: dict[str, tuple[str, str]],
        name_by_ref: Mapping[str, str],
    ) -> int:
        """Write per-class DataFrames as Excel sheets. Returns total rows written.

        Each sheet carries a readable column-name banner above the COREP ref
        codes (see ``kernel.write_template_sheet``).
        """
        total = 0
        for ec, df in sorted(templates.items()):
            if len(df) > 0:
                display = class_names.get(ec, (None, ec))[1]
                total += write_template_sheet(workbook, df, f"{prefix} - {display}", name_by_ref)
        return total

    @staticmethod
    def _write_single_template_sheet(
        workbook: Workbook,
        df: pl.DataFrame,
        sheet_name: str,
        name_by_ref: Mapping[str, str],
    ) -> int:
        """Write a single DataFrame as an Excel sheet. Returns rows written."""
        if len(df) == 0:
            return 0
        return write_template_sheet(workbook, df, sheet_name, name_by_ref)

    @staticmethod
    def _write_geo_template_sheets(
        workbook: Workbook,
        templates: dict[str, pl.DataFrame],
        prefix: str,
        name_by_ref: Mapping[str, str],
    ) -> int:
        """Write per-country geographical templates as Excel sheets.

        Used by both C 09.01 (SA) and C 09.02 (IRB) — they share the same
        ``{prefix} - {country}`` sheet-naming convention.
        Returns total rows written.
        """
        total = 0
        for country, df in sorted(templates.items()):
            if len(df) > 0:
                total += write_template_sheet(workbook, df, f"{prefix} - {country}", name_by_ref)
        return total

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
        ead_col = _pick(cols, "ead_final")
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

        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")

        lookups = _c08_07_group_by_class(results, ead_col, rwa_col, ec_col, approach_col)
        if lookups is None:
            return None
        class_irb_ead, class_sa_ead, class_irb_rwa, class_sa_rwa = lookups

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

        def _agg_values(
            irb_ead: float, sa_ead: float, irb_rwa: float, sa_rwa: float
        ) -> dict[str, object]:
            return self._compute_c08_07_values(
                irb_ead,
                sa_ead,
                irb_rwa,
                sa_rwa,
                column_refs,
                is_b31,
                is_consolidated=_is_consolidated,
            )

        for row_ref, row_name, ec_value in row_defs:
            if row_name == "Total":
                values = _agg_values(
                    sum(class_irb_ead.values()),
                    sum(class_sa_ead.values()),
                    sum(class_irb_rwa.values()),
                    sum(class_sa_rwa.values()),
                )
            elif ec_value is not None:
                values = _agg_values(
                    class_irb_ead.get(ec_value, 0.0),
                    class_sa_ead.get(ec_value, 0.0),
                    class_irb_rwa.get(ec_value, 0.0),
                    class_sa_rwa.get(ec_value, 0.0),
                )
            elif row_ref == "0090":
                # CRR "Retail" aggregate row
                values = _agg_values(
                    sum(class_irb_ead.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES),
                    sum(class_sa_ead.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES),
                    sum(class_irb_rwa.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES),
                    sum(class_sa_rwa.get(c, 0.0) for c in C08_07_CRR_RETAIL_CLASSES),
                )
            else:
                # Aggregate immateriality %, CRR SL-excluding-slotting (row 0060),
                # SME sub-rows — none can be populated from this data; report null.
                values = dict.fromkeys(column_refs)

            rows.append({"row_ref": row_ref, "row_name": row_name, **values})

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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

        # Direct refs available in all frameworks
        direct: dict[str, object] = {
            "0010": irb_ead,
            "0020": total_ead,
            # % subject to permanent partial use of SA — all SA is treated as
            # permanent partial use when IRB permissions exist.
            "0030": pct_sa,
            # % subject to roll-out plan — not tracked in pipeline.
            "0040": 0.0,
            "0050": pct_irb,
        }
        # B3.1-only refs (CRR layout doesn't include these)
        b31_only: dict[str, object] = {
            "0060": total_rwa,
            # RWEA for SA: other — all SA RWEA goes here when no
            # sa_use_reason column is available to split by reason.
            "0140": sa_rwa,
            "0150": irb_rwa,
            # Materiality cols (0160-0180) require institutional config —
            # populated as None until consolidated-basis data is available.
            "0160": None,
            "0170": None,
            "0180": None,
        }

        values: dict[str, object] = {}
        for ref in column_refs:
            if ref in direct:
                values[ref] = direct[ref]
            elif is_b31 and ref in b31_only:
                values[ref] = b31_only[ref]
            else:
                # SA RWEA breakdown cols 0070-0130 (B31): null until
                # sa_use_reason is tracked. CRR layout: anything not in
                # ``direct`` is a zero placeholder.
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
                if row_def.ref in ("0010", "0080"):
                    # 0010 = credit risk (excl. CCR); 0080 = total — same value
                    # for a credit-risk-only calculator (S1871 collapse).
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

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 34.01 / 02 / 04 / 08 — Counterparty Credit Risk (CCR)
    # =========================================================================

    def _generate_c34_01(
        self,
        results: pl.LazyFrame,
        cols: set[str],
    ) -> pl.DataFrame | None:
        """Generate C 34.01 — SA-CCR analysis by approach (EAD + RWEA total).

        Reports the portfolio SA-CCR exposure value (col 0010) and RWEA
        (col 0020) summed over the synthetic ``ccr__``-prefixed netting-set
        rows. Returns None when the portfolio carries no CCR rows — the gated
        precedent of ``_generate_of_02_01``.

        References:
            CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE).
        """
        ccr = _collect_ccr_rows(results, cols)
        if ccr is None or len(ccr) == 0:
            return None

        ead_total = float(ccr["ead_final"].fill_null(0.0).sum())
        rwea_total = float(ccr["rwa_final"].fill_null(0.0).sum())

        column_refs = [c.ref for c in get_c34_01_columns()]
        rows: list[dict[str, object]] = [
            {
                "row_ref": row.ref,
                "row_name": row.name,
                "0010": ead_total,
                "0020": rwea_total,
            }
            for row in C34_01_ROWS
        ]
        return _c34_frame(rows, column_refs)

    def _generate_c34_02(
        self,
        results: pl.LazyFrame,
        cols: set[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 34.02 — SA-CCR EAD per netting set.

        Returns a dict keyed by ``netting_set_id`` (derived by stripping the
        ``ccr__`` prefix from ``exposure_reference``). Each value is a 1-row
        DataFrame carrying that netting set's exposure value (col 0010).
        Empty dict when the portfolio has no CCR rows.

        References:
            CRR Art. 274(2): EAD = alpha * (RC + PFE) per netting set.
        """
        ccr = _collect_ccr_rows(results, cols)
        if ccr is None or len(ccr) == 0:
            return {}

        column_refs = [c.ref for c in get_c34_02_columns()]
        per_ns = ccr.group_by("netting_set_id").agg(
            pl.col("ead_final").fill_null(0.0).sum().alias("_ead")
        )

        result: dict[str, pl.DataFrame] = {}
        for ns_row in per_ns.iter_rows(named=True):
            ns_id = ns_row["netting_set_id"]
            if ns_id is None:
                continue
            rows: list[dict[str, object]] = [
                {"row_ref": row.ref, "row_name": row.name, "0010": float(ns_row["_ead"])}
                for row in C34_02_ROWS
            ]
            result[str(ns_id)] = _c34_frame(rows, column_refs)
        return result

    def _generate_c34_04(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
    ) -> pl.DataFrame | None:
        """Generate C 34.04 — CVA capital (BA-CVA RWEA). Basel 3.1 only.

        Reads the portfolio ``cva_rwa`` carried as a constant column on the
        results frame (surfaced by the aggregation stage's BA-CVA roll-up).
        Returns None under CRR, or when no ``cva_rwa`` column / value is
        present — mirroring the ``_generate_of_02_01`` gated-grid precedent.

        References:
            PRA PS1/26 App.1 CVA Part Ch.4.2-4.4 (BA-CVA reduced);
            PRA PS1/26 App.1 Own Funds Part 4(b): RWEA_CVA = OFR_CVA * 12.5.
        """
        if framework != "BASEL_3_1":
            return None
        cva_col = _pick(cols, "cva_rwa")
        if cva_col is None:
            return None

        cva_value = results.select(pl.col(cva_col).max().alias("_cva")).collect()["_cva"][0]
        if cva_value is None or float(cva_value) <= 0.0:
            return None

        column_refs = [c.ref for c in get_c34_04_columns()]
        rows: list[dict[str, object]] = [
            {"row_ref": row.ref, "row_name": row.name, "0010": float(cva_value)}
            for row in C34_04_ROWS
        ]
        return _c34_frame(rows, column_refs)

    def _generate_c34_08(
        self,
        results: pl.LazyFrame,
        cols: set[str],
    ) -> pl.DataFrame | None:
        """Generate C 34.08 — CCP exposures (QCCP trade, non-QCCP, default fund).

        Partitions the CCR rows by the QCCP trade-leg discriminator
        (``cp_entity_type == "ccp" & cp_is_qccp.fill_null(True)``) — mirroring
        the aggregator exactly — into QCCP (row 0010) and non-QCCP (row 0020)
        rows, plus a default-fund row (0030) keyed off the
        ``CCR_DEFAULT_FUND`` risk type. Each row reports EAD (col 0010) and
        RWEA (col 0020). Returns None when the portfolio has no CCP exposures.

        References:
            CRR Art. 306(1)(a)/(c): 2% / 4% QCCP trade-leg RW.
            CRR Art. 308/309: default fund contributions.
        """
        ccr = _collect_ccr_rows(results, cols)
        df_fund_ead, df_fund_rwea = _collect_default_fund(results, cols)
        if (ccr is None or len(ccr) == 0) and df_fund_rwea <= 0.0:
            return None

        qccp_ead = qccp_rwea = non_qccp_ead = non_qccp_rwea = 0.0
        if ccr is not None and len(ccr) > 0:
            is_qccp_trade = (pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(
                True
            )
            qccp = ccr.filter(is_qccp_trade)
            non_qccp = ccr.filter(~is_qccp_trade)
            qccp_ead = float(qccp["ead_final"].fill_null(0.0).sum())
            qccp_rwea = float(qccp["rwa_final"].fill_null(0.0).sum())
            non_qccp_ead = float(non_qccp["ead_final"].fill_null(0.0).sum())
            non_qccp_rwea = float(non_qccp["rwa_final"].fill_null(0.0).sum())

        row_values: dict[str, tuple[float, float]] = {
            "0010": (qccp_ead, qccp_rwea),
            "0020": (non_qccp_ead, non_qccp_rwea),
            "0030": (df_fund_ead, df_fund_rwea),
        }
        column_refs = [c.ref for c in get_c34_08_columns()]
        rows: list[dict[str, object]] = []
        for row in C34_08_ROWS:
            ead, rwea = row_values.get(row.ref, (0.0, 0.0))
            rows.append({"row_ref": row.ref, "row_name": row.name, "0010": ead, "0020": rwea})
        return _c34_frame(rows, column_refs)

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
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")

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
            total_rwa = self._c02_00_aggregate_by_approach(
                results, approach_col, ec_col, rwa_col, cols, is_b31, approach_rwa, sa_class_rwa
            )
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

        # SA per-class rows + B31 specialised-lending sub-row
        _c02_00_sa_rows(row_values, sa_class_rwa, is_b31)

        # IRB total
        row_values["0220"] = {"0010": irb_total_rwa}

        # F-IRB total + sub-rows (incl. B31 corporate splits)
        irb_class_rwa = getattr(self, "_irb_class_rwa", {})
        irb_sub_rwa = getattr(self, "_irb_sub_rwa", {})
        _c02_00_firb_rows(row_values, firb_rwa, irb_class_rwa, irb_sub_rwa, is_b31)

        # A-IRB total + sub-rows (corporate splits + retail breakdown)
        _c02_00_airb_corp_rows(row_values, airb_rwa, irb_class_rwa, irb_sub_rwa, is_b31)
        _c02_00_airb_retail_rows(row_values, irb_class_rwa, irb_sub_rwa, is_b31)

        # Slotting rows (CRR single row vs B31 per-SL-type breakdown)
        slotting_type_rwa = getattr(self, "_slotting_type_rwa", {})
        _c02_00_slotting_rows(row_values, slotting_rwa, slotting_type_rwa, is_b31)

        # Equity IRB
        row_values["0420"] = {"0010": equity_rwa}

        # B31 output floor indicator rows
        _c02_00_floor_indicator_rows(
            row_values, floor_activated, output_floor_summary, output_floor_config, is_b31
        )

        # Add B31 col 0020 (SA-equivalent) and col 0030 (output floor) values
        if is_b31:
            _c02_00_apply_b31_cols(row_values, sa_equiv_rwa, floor_rwa)

        # B31 memo row 0500 (PRA PS1/26 Art. 123B): portfolio-total RWEA of all
        # rows that fired the 1.5x currency-mismatch multiplier. Memo-only — only
        # col 0010 is populated (0020/0030 stay None via the build .get()), and
        # the row is excluded from the TREA total. Absent under CRR (the row is
        # not in CRR_C02_00_ROW_SECTIONS, so the build step never emits it).
        if is_b31 and "currency_mismatch_multiplier_applied" in cols:
            mismatch_rwea = float(
                results.filter(pl.col("currency_mismatch_multiplier_applied").fill_null(False))
                .select(pl.col(rwa_col).fill_null(0.0).sum().alias("rwea"))
                .collect()["rwea"][0]
            )
            row_values["0500"] = {"0010": mismatch_rwea}

        # Build DataFrame rows
        rows = _c02_00_build_rows(row_values, row_sections, column_refs)

        # Schema: String for refs/names, Float64 for data columns
        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        # Clean up temporary state
        self._irb_class_rwa = {}
        self._slotting_type_rwa = {}
        self._irb_sub_rwa = {}

        return pl.DataFrame(rows, schema=schema)

    def _c02_00_aggregate_by_approach(
        self,
        results: pl.LazyFrame,
        approach_col: str,
        ec_col: str,
        rwa_col: str,
        cols: set[str],
        is_b31: bool,
        approach_rwa: dict[str, float],
        sa_class_rwa: dict[str, float],
    ) -> float:
        """Populate per-approach/per-class aggregations on ``self`` + dicts.

        Returns the total RWA. Mutates ``approach_rwa`` and ``sa_class_rwa``
        in place and sets the three ``self._irb_*`` cache dicts (consumed by
        the ``_c02_00_*_rows`` helpers).
        """
        collected = results.select(
            pl.col(approach_col).alias("_approach"),
            pl.col(ec_col).alias("_ec"),
            pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
        ).collect()

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

        # IRB per-approach-and-class breakdown
        irb_rows = collected.filter(~sa_mask & ~equity_mask)
        irb_class_approach = irb_rows.group_by(["_approach", "_ec"]).agg(
            pl.col("_rwa").sum().alias("rwa")
        )
        self._irb_class_rwa = {
            (row["_approach"], row["_ec"]): float(row["rwa"])
            for row in irb_class_approach.iter_rows(named=True)
        }

        # Slotting by SL type
        self._slotting_type_rwa = self._c02_00_slotting_type_agg(
            results, approach_col, rwa_col, cols
        )

        # B3.1 finer-grained sub-row aggregation (SME/FSE/property-type)
        self._irb_sub_rwa = (
            self._c02_00_irb_sub_agg(results, approach_col, ec_col, rwa_col, cols) if is_b31 else {}
        )
        return total_rwa

    @staticmethod
    def _c02_00_slotting_type_agg(
        results: pl.LazyFrame, approach_col: str, rwa_col: str, cols: set[str]
    ) -> dict[str, float]:
        """Aggregate slotting RWA by ``sl_type``. Returns empty dict if absent."""
        if "sl_type" not in cols:
            return {}
        sl_collected = (
            results.filter(pl.col(approach_col) == "slotting")
            .select(
                pl.col("sl_type").alias("_sl"),
                pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
            )
            .collect()
        )
        by_sl = sl_collected.group_by("_sl").agg(pl.col("_rwa").sum().alias("rwa"))
        return {
            row["_sl"]: float(row["rwa"])
            for row in by_sl.iter_rows(named=True)
            if row["_sl"] is not None
        }

    @staticmethod
    def _c02_00_irb_sub_agg(
        results: pl.LazyFrame,
        approach_col: str,
        ec_col: str,
        rwa_col: str,
        cols: set[str],
    ) -> dict[tuple[str, str, bool | None, bool | None, str | None], float]:
        """Finer-grained IRB aggregation for B3.1 corporate/retail sub-rows."""
        sub_select: list[pl.Expr] = [
            pl.col(approach_col).alias("_approach"),
            pl.col(ec_col).alias("_ec"),
            pl.col(rwa_col).fill_null(0.0).alias("_rwa"),
        ]
        # The classifier-derived ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)(e)/(f))
        # is the canonical corporate split signal: ``corporate_financial_large``
        # (FSE OR revenue > GBP 440m) -> row 0295, ``corporate_sme`` -> 0296/0355,
        # ``corporate_other`` -> 0297/0356. When it is absent (e.g. CRR frames or
        # pre-classifier inputs) fall back to the is_sme / FSE-flag heuristic.
        has_subclass = "exposure_subclass" in cols
        has_sme = "is_sme" in cols
        has_fse = (
            has_subclass or "cp_apply_fi_scalar" in cols or "cp_is_financial_sector_entity" in cols
        )
        has_pt = "property_type" in cols
        if has_sme or has_subclass:
            has_sme = True
            if has_subclass:
                sme_expr = pl.col("exposure_subclass") == "corporate_sme"
                if "is_sme" in cols:
                    sme_expr = sme_expr | pl.col("is_sme").fill_null(False)
            else:
                sme_expr = pl.col("is_sme").fill_null(False)
            sub_select.append(sme_expr.alias("_sme"))
        if has_fse:
            if has_subclass:
                fse_expr = pl.col("exposure_subclass") == "corporate_financial_large"
            else:
                fse_col = (
                    "cp_apply_fi_scalar"
                    if "cp_apply_fi_scalar" in cols
                    else "cp_is_financial_sector_entity"
                )
                fse_expr = pl.col(fse_col).fill_null(False)
            sub_select.append(fse_expr.alias("_fse"))
        if has_pt:
            sub_select.append(pl.col("property_type").alias("_pt"))

        irb_approaches = {"foundation_irb", "advanced_irb"}
        sub_collected = (
            results.filter(pl.col(approach_col).is_in(irb_approaches)).select(sub_select).collect()
        )
        gb_cols = ["_approach", "_ec"]
        if has_sme:
            gb_cols.append("_sme")
        if has_fse:
            gb_cols.append("_fse")
        if has_pt:
            gb_cols.append("_pt")
        sub_agg = sub_collected.group_by(gb_cols).agg(pl.col("_rwa").sum().alias("rwa"))
        return {
            (
                row["_approach"],
                row["_ec"],
                row.get("_sme"),
                row.get("_fse"),
                row.get("_pt"),
            ): float(row["rwa"])
            for row in sub_agg.iter_rows(named=True)
        }

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
        total_df = self._generate_c09_01_for_country(sa_df, df_cols, row_defs, column_refs)
        result["TOTAL"] = total_df

        # Generate per-country templates
        countries = _collect_unique_countries(sa_df, country_col)

        for country in countries:
            country_data = sa_df.filter(pl.col(country_col) == country)
            if len(country_data) > 0:
                country_df = self._generate_c09_01_for_country(
                    country_data, df_cols, row_defs, column_refs
                )
                result[country] = country_df

        return result

    def _generate_c09_01_for_country(
        self,
        country_data: pl.DataFrame,
        cols: set[str],
        row_defs: list[COREPRow],
        column_refs: list[str],
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
                values = _compute_c09_01_values(country_data, cols, column_refs)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            elif row_def.exposure_class_value is not None:
                row_data = _filter_c09_01_row(country_data, cols, row_def.exposure_class_value)
                if len(row_data) > 0:
                    values = _compute_c09_01_values(row_data, cols, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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
            irb_df, df_cols, row_defs, column_refs, approach_col
        )
        result["TOTAL"] = total_df

        # Generate per-country templates
        countries = _collect_unique_countries(irb_df, country_col)

        for country in countries:
            country_data = irb_df.filter(pl.col(country_col) == country)
            if len(country_data) > 0:
                country_df = self._generate_c09_02_for_country(
                    country_data, df_cols, row_defs, column_refs, approach_col
                )
                result[country] = country_df

        return result

    def _generate_c09_02_for_country(
        self,
        country_data: pl.DataFrame,
        cols: set[str],
        row_defs: list[COREPRow],
        column_refs: list[str],
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
                values = _compute_c09_02_values(country_data, cols, column_refs)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            elif row_def.exposure_class_value is not None:
                row_data = _filter_c09_02_row(
                    country_data, cols, row_def.exposure_class_value, approach_col
                )
                if len(row_data) > 0:
                    values = _compute_c09_02_values(row_data, cols, column_refs)
                    rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
                else:
                    rows.append(_null_row(row_def.ref, row_def.name, column_refs))
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
        for ref in column_refs:
            schema[ref] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

    # =========================================================================
    # C 07.00 — SA Credit Risk (per exposure class)
    # =========================================================================

    def _generate_all_c07(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 07.00 SA templates.

        Dispatch-router entry (Phase 7 S8): C 07.00 is declarative — the
        cell semantics live in ``corep/c07.py::generate_c07`` (obligor-class
        sheets, substitution outflow/inflow, Annex II sign convention) and
        run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 111-113; COREP Annex II C 07.00; PRA PS1/26 App. 17.
        """
        return generate_c07(results, cols, framework, errors)

    def _generate_all_c08_01(
        self,
        irb_data: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate C 08.01 DataFrames for all IRB exposure classes."""
        ec_col = _pick(cols, "exposure_class")
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")

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
        sub_flows = _compute_substitution_flows(irb_df, data_cols)

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

        def _emit_subset_row(row_def, subset: pl.DataFrame | None) -> None:
            if subset is not None and len(subset) > 0:
                values = _compute_c08_values(subset, cols, ead_col, rwa_col, column_refs)
                rows.append({"row_ref": row_def.ref, "row_name": row_def.name, **values})
            else:
                rows.append(_null_row(row_def.ref, row_def.name, column_refs))

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
            _emit_subset_row(row_def, _c08_01_section2_subset(row_def.ref, class_data, cols))

        # Section 3: Calculation Approaches
        approach_col = "approach_applied" if "approach_applied" in cols else None
        for row_def in row_sections[2].rows:
            _emit_subset_row(
                row_def,
                _filter_section3_row(class_data, cols, row_def.ref, approach_col, framework),
            )

        schema: dict[str, PolarsDataType] = {
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
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        pd_col = _pick(cols, "pd_floored", "pd")
        # Firm-supplied internal rating grade (COREP Annex II, C 08.02): when
        # present, rows are keyed by the firm's obligor grade scale rather than
        # the fixed PD bands.
        grade_col = _pick(cols, "cp_internal_rating_grade")

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
                class_df, data_cols, ead_col, rwa_col, pd_col, framework, grade_col
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
        grade_col: str | None = None,
    ) -> pl.DataFrame:
        """Generate a C 08.02 DataFrame for a single IRB exposure class.

        Rows are keyed either by the firm-supplied internal rating grade
        (COREP Annex II, C 08.02 obligor grade scale) when ``grade_col`` is
        present and populated for the class, or by the fixed PD bands as a
        graceful fallback. Each row carries the same columns as C 08.01 plus
        an obligor grade identifier (col 0005) and PD (col 0010 for B3.1).
        """
        column_defs = get_c08_02_columns(framework)
        column_refs = [c.ref for c in column_defs]

        if grade_col is not None and grade_col in cols:
            graded = self._generate_c08_02_grade_rows(
                class_data, cols, ead_col, rwa_col, grade_col, column_refs
            )
            if graded is not None:
                return self._c08_02_frame_from_rows(graded, column_refs)

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

        return self._c08_02_frame_from_rows(rows, column_refs)

    def _generate_c08_02_grade_rows(
        self,
        class_data: pl.DataFrame,
        cols: set[str],
        ead_col: str,
        rwa_col: str,
        grade_col: str,
        column_refs: list[str],
    ) -> list[dict[str, object]] | None:
        """Build C 08.02 rows keyed by firm internal rating grade.

        Returns one row per distinct non-null grade label (col 0005 = the grade
        string); null-grade rows fall to a single "Unassigned" residual row.
        Returns ``None`` when every grade value for the class is null so the
        caller can fall back to the fixed PD-band path.
        """
        non_null = class_data.filter(pl.col(grade_col).is_not_null())
        if len(non_null) == 0:
            return None

        rows: list[dict[str, object]] = []
        grade_labels = non_null[grade_col].unique().sort().to_list()
        for label in grade_labels:
            grade_data = non_null.filter(pl.col(grade_col) == label)
            values = _compute_c08_values(grade_data, cols, ead_col, rwa_col, column_refs)
            # Col 0005: obligor grade identifier = the firm grade label
            values["0005"] = label
            rows.append({"row_ref": label, "row_name": label, **values})

        # Rows with a null grade fall to an "Unassigned" residual (do not
        # silently re-bucket them by PD).
        unassigned = class_data.filter(pl.col(grade_col).is_null())
        if len(unassigned) > 0:
            values = _compute_c08_values(unassigned, cols, ead_col, rwa_col, column_refs)
            values["0005"] = "Unassigned"
            rows.append({"row_ref": "Unassigned", "row_name": "Unassigned", **values})

        return rows

    @staticmethod
    def _c08_02_frame_from_rows(
        rows: list[dict[str, object]],
        column_refs: list[str],
    ) -> pl.DataFrame:
        """Materialise C 08.02 rows into a typed DataFrame.

        Col 0005 (obligor grade identifier) is String; remaining columns are
        Float64. Returns an empty, correctly-typed frame when ``rows`` is empty.
        """
        if not rows:
            empty_schema: dict[str, PolarsDataType] = {
                "row_ref": pl.String,
                "row_name": pl.String,
            }
            empty_schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=empty_schema)

        # Infer schema from column defs — 0005 is String, rest are Float64
        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")

        if ec_col is None or ead_col is None or rwa_col is None:
            errors.append("C08.03: Missing required columns (exposure_class/ead/rwa)")
            return {}

        # For row allocation: B31 uses pre-input-floor PD, CRR uses floored PD
        if framework == "BASEL_3_1":
            alloc_pd_col = _pick(cols, "pd", "pd_floored")
        else:
            alloc_pd_col = _pick(cols, "pd_floored", "pd")
        # For col 0050 (reported PD): always post-input-floor
        report_pd_col = _pick(cols, "pd_floored", "pd")

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
            schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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

        rwa_col = _pick(cols, "rwa_final", "rwa")
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

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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
            alloc_pd_col = _pick(cols, "pd", "pd_floored")
        else:
            alloc_pd_col = _pick(cols, "pd_floored", "pd")
        # For col 0010 (reported PD): always post-input-floor
        report_pd_col = _pick(cols, "pd_floored", "pd")

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
            schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
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
        ead_col = _pick(cols, "ead_final")
        rwa_col = _pick(cols, "rwa_final", "rwa_post_factor", "rwa")
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
                type_df = _c08_06_sl_type_filter(
                    slotting_df, sl_key, sl_type_col, hvcre_col, framework
                )

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
            cat_data = _c08_06_filter_row(
                type_data, cat_col, category_label, is_short, maturity_col
            )
            if cat_data is None:
                continue

            if len(cat_data) == 0 and category_label != "Total":
                # Still include the row with zero values for regulatory completeness
                values = _c08_06_row_values_or_zeros(column_refs, _rw_display)
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
            schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
            schema.update(dict.fromkeys(column_refs, pl.Float64))
            return pl.DataFrame(schema=schema)

        schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
        schema.update(dict.fromkeys(column_refs, pl.Float64))
        return pl.DataFrame(rows, schema=schema)


# =============================================================================
# C 07.00 SECTION-LEVEL FILTER CONFIGURATION
# =============================================================================


# =============================================================================
# RE ROW FILTER CONFIGURATION (Basel 3.1 OF 07.00 rows 0330-0360)
# =============================================================================


# =============================================================================
# EQUITY TRANSITIONAL ROW CONFIGURATION (Basel 3.1 OF 07.00 rows 0371-0374)
# =============================================================================


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


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


def _classify_re_bucket(is_comm: bool, is_sme: bool | None) -> tuple[int, int, int, int]:
    """Return a 4-tuple selector ``(resi_sme, resi_nonsme, comm_sme, comm_nonsme)``.

    Exactly one element is 1 (the bucket to credit), the rest are 0.
    Lets ``_irb_re_sub_split`` add RWA to the right bucket without a branch
    cascade.
    """
    if is_comm:
        return (0, 0, 1, 0) if is_sme else (0, 0, 0, 1)
    # residential / rre / null → default to residential
    return (1, 0, 0, 0) if is_sme else (0, 1, 0, 0)


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
    buckets = [0.0, 0.0, 0.0, 0.0]
    matched = False
    for key, rwa in sub_rwa.items():
        a, e, is_sme, _fse, pt = key
        if a != approach or e != ec:
            continue
        matched = True
        is_comm = pt in ("commercial", "cre")
        for idx, weight in enumerate(_classify_re_bucket(is_comm, is_sme)):
            buckets[idx] += weight * rwa
    if not matched:
        return 0.0, total, 0.0, 0.0
    return buckets[0], buckets[1], buckets[2], buckets[3]


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
    """Filter to defaulted exposures using available columns.

    Prefers the per-row ``is_defaulted`` flag the pipeline actually sets (it
    also carries row-level defaults, not just counterparty ``default_status``),
    falling back to legacy identification columns for hand-rolled frames.
    """
    if "is_defaulted" in cols:
        return data.filter(pl.col("is_defaulted").fill_null(False))  # noqa: FBT003
    if "default_status" in cols:
        return data.filter(pl.col("default_status") == True)  # noqa: E712
    class_col = "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
    if class_col in cols:
        return data.filter(pl.col(class_col) == "defaulted")
    if "pd_floored" in cols:
        return data.filter(pl.col("pd_floored") >= 1.0)
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

    Returns None if cp_apply_fi_scalar column is not available (cannot determine LFSE).
    """
    if "cp_apply_fi_scalar" in cols:
        return data.filter(pl.col("cp_apply_fi_scalar") == True)  # noqa: E712
    return None


_SECTION3_NULL_REFS: frozenset[str] = frozenset({"0160", "0170", "0175", "0180"})


def _filter_section3_unrated_corp(
    data: pl.DataFrame, cols: set[str], framework: str
) -> pl.DataFrame | None:
    """Row 0190: corporates without ECAI assessment (B3.1 only, unrated)."""
    if framework != "BASEL_3_1" or "exposure_class" not in cols:
        return None
    ec_filter = pl.col("exposure_class").str.contains("corporate", literal=True)
    if "sa_cqs" in cols:
        return data.filter(ec_filter & pl.col("sa_cqs").is_null())
    return data.filter(ec_filter)


def _filter_section3_unrated_ig(
    data: pl.DataFrame, cols: set[str], framework: str
) -> pl.DataFrame | None:
    """Row 0200: investment-grade subset of unrated corporates (B3.1 only)."""
    if framework != "BASEL_3_1" or "exposure_class" not in cols:
        return None
    ec_filter = pl.col("exposure_class").str.contains("corporate", literal=True)
    unrated_filter = pl.col("sa_cqs").is_null() if "sa_cqs" in cols else pl.lit(True)
    if "cp_is_investment_grade" in cols:
        return data.filter(
            ec_filter & unrated_filter & (pl.col("cp_is_investment_grade").fill_null(False) == True)  # noqa: E712
        )
    if "pd_floored" in cols:
        return data.filter(ec_filter & unrated_filter & (pl.col("pd_floored") <= 0.005))
    return None


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

    if row_ref in _SECTION3_NULL_REFS:
        # Rows requiring pipeline flags not yet available (RE alt-treatment,
        # free deliveries, purchased receivables, dilution risk).
        return None

    if row_ref == "0190":
        return _filter_section3_unrated_corp(data, cols, framework)

    if row_ref == "0200":
        return _filter_section3_unrated_ig(data, cols, framework)

    return None


def _of_02_01_row(
    row_ref: str,
    row_name: str,
    column_refs: list[str],
    *,
    modelled_rwa: float,
    sa_rwa: float,
) -> dict[str, object]:
    """Build an OF 02.01 row with modelled/SA RWA and U-TREA/S-TREA values.

    U-TREA (col 0030) = modelled RWA + SA RWA per Annex II §1.3.2;
    S-TREA (col 0040) = SA-equivalent RWA across the entire portfolio.
    """
    row: dict[str, object] = {"row_ref": row_ref, "row_name": row_name}
    values = {
        "0010": modelled_rwa,
        "0020": sa_rwa,
        "0030": modelled_rwa + sa_rwa,
        "0040": sa_rwa,
    }
    for ref in column_refs:
        row[ref] = values.get(ref)
    return row


def _collect_ccr_rows(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Materialise the synthetic SA-CCR netting-set rows from the results frame.

    Filters to the ``ccr__``-prefixed ``exposure_reference`` rows and derives a
    ``netting_set_id`` column by stripping that prefix (the per-row
    ``exposure_reference`` is ``ccr__{netting_set_id}``). Returns None when the
    discriminating columns are absent (CCR-free portfolio).

    FCCM SFT rows (``risk_type == "CCR_SFT"`` / ``ccr_method == "fccm_sft"``)
    share the ``ccr__`` reference prefix but are EXCLUDED here: per PS1/26
    App. 17 they are reported under SA template C 07.00 row 0090
    ("SFT netting sets"), not the SA-CCR templates (C 34.01/02/08). Only OTC
    derivatives (``risk_type == "CCR_DERIVATIVE"``) and CCP exposures belong in
    the SA-CCR templates (CRR Art. 274/306). The exclusion is gated on the
    ``risk_type`` column being present so a portfolio that predates the column
    is unaffected.

    References:
        CRR Art. 274(2): the synthetic SA-CCR rows carry EAD = alpha * (RC + PFE).
        PS1/26 App. 17: SFTs report under C 07.00 row 0090, not C 34.
    """
    if not ({"exposure_reference", "ead_final", "rwa_final"} <= cols):
        return None
    is_ccr = pl.col("exposure_reference").str.starts_with("ccr__")
    not_sft = pl.col("risk_type") != "CCR_SFT" if "risk_type" in cols else pl.lit(True)
    ccr = (
        results.filter(is_ccr & not_sft)
        .with_columns(
            pl.col("exposure_reference").str.strip_prefix("ccr__").alias("netting_set_id")
        )
        .collect()
    )
    if len(ccr) == 0:
        return None
    return ccr


def _collect_default_fund(results: pl.LazyFrame, cols: set[str]) -> tuple[float, float]:
    """Sum EAD and RWEA over the synthetic ``CCR_DEFAULT_FUND`` rows.

    Returns ``(0.0, 0.0)`` when the ``risk_type`` discriminator is absent or no
    default-fund rows are present (CRR Art. 308/309).
    """
    if "risk_type" not in cols or "rwa_final" not in cols:
        return 0.0, 0.0
    ead_expr = (
        pl.col("ead_final").fill_null(0.0).sum().alias("_ead")
        if "ead_final" in cols
        else pl.lit(0.0).alias("_ead")
    )
    stats = (
        results.filter(pl.col("risk_type") == "CCR_DEFAULT_FUND")
        .select(ead_expr, pl.col("rwa_final").fill_null(0.0).sum().alias("_rwea"))
        .collect()
    )
    if len(stats) == 0:
        return 0.0, 0.0
    return float(stats["_ead"][0]), float(stats["_rwea"][0])


def _c34_frame(rows: list[dict[str, object]], column_refs: list[str]) -> pl.DataFrame:
    """Build a C 34.xx DataFrame with the standard row_ref/row_name + refs schema."""
    schema: dict[str, PolarsDataType] = {"row_ref": pl.String, "row_name": pl.String}
    for ref in column_refs:
        schema[ref] = pl.Float64
    return pl.DataFrame(rows, schema=schema)


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


_C08_NEGATIVE_COLS: frozenset[str] = frozenset({"0290"})


def _negate_deduction_cols(values: dict[str, float | None], negative_cols: frozenset[str]) -> None:
    """Apply the COREP Annex II §1.3 "(-)" sign convention in place.

    Negates the magnitude of each "(-)"-labelled deduction column so the
    template emits it as a negative figure. Negative-zero is normalised to
    0.0; null stays null. Must run AFTER all cross-column arithmetic has
    consumed the positive intermediates.
    """
    for ref in negative_cols:
        magnitude = values.get(ref)
        if magnitude is None:
            continue
        negated = -magnitude
        values[ref] = 0.0 if negated == 0.0 else negated


def _c08_exposure_cols(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    ead_sum: float,
    lfse_data: pl.DataFrame | None,
) -> dict[str, float | None]:
    """Compute C 08.01/02 exposure columns (0010 PD, 0020 original, 0030 LFSE, 0035 netting)."""
    values: dict[str, float | None] = {}
    if "pd_floored" in cols and ead_sum > 0:
        pd_x_ead = float((data["pd_floored"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0010"] = pd_x_ead / ead_sum
    else:
        values["0010"] = None

    values["0020"] = _safe_sum_eager(data, cols, "drawn_amount", "undrawn_amount")

    if lfse_data is not None and len(lfse_data) > 0:
        values["0030"] = _safe_sum_eager(
            lfse_data, set(lfse_data.columns), "drawn_amount", "undrawn_amount"
        )
    else:
        values["0030"] = 0.0 if "cp_apply_fi_scalar" in cols else None

    values["0035"] = _col_sum_eager(data, cols, "on_bs_netting_amount")
    return values


def _c08_crm_cols(
    data: pl.DataFrame, cols: set[str], substitution_inflow: float
) -> dict[str, float | None]:
    """Compute C 08.01/02 CRM substitution columns (0040-0090)."""
    values: dict[str, float | None] = {}

    guar_only = _sum_by_protection_type(data, cols, "guarantee")
    values["0040"] = (
        guar_only if guar_only is not None else _col_sum_eager(data, cols, "guaranteed_portion")
    )

    cd_val = _sum_by_protection_type(data, cols, "credit_derivative")
    values["0050"] = cd_val if cd_val is not None else 0.0

    values["0060"] = _safe_sum_eager(
        data,
        cols,
        "collateral_re_value",
        "collateral_receivables_value",
        "collateral_other_physical_value",
    )

    values["0070"] = _compute_substitution_outflow(data, cols)
    values["0080"] = substitution_inflow if substitution_inflow else 0.0

    # 0090: Exposure after CRM substitution pre CCFs
    v_0020 = values.get("0020") or 0.0  # caller hasn't populated yet, intentionally 0
    v_0040 = values.get("0040") or 0.0
    v_0050 = values.get("0050") or 0.0
    v_0060 = values.get("0060") or 0.0
    v_0070 = values.get("0070") or 0.0
    v_0080 = values.get("0080") or 0.0
    values["0090"] = v_0020 - v_0040 - v_0050 - v_0060 - v_0070 + v_0080
    return values


def _c08_of_which_cols(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    lfse_data: pl.DataFrame | None,
    defaulted: pl.DataFrame,
) -> dict[str, float | None]:
    """Compute C 08.01/02 'of which' columns (0100, 0101-0104, 0110, 0120-0140)."""
    values: dict[str, float | None] = {}
    off_bs = _filter_off_bs(data, cols)
    if len(off_bs) > 0:
        values["0100"] = _col_sum_eager(off_bs, set(off_bs.columns), ead_col)
    else:
        values["0100"] = 0.0

    # 0101-0104: Slotting FCCM (B3.1 only, Phase 3A)
    for ref in ("0101", "0102", "0103", "0104"):
        values[ref] = None

    values["0110"] = _col_sum_eager(data, cols, ead_col)
    values["0120"] = None  # Off-BS — Phase 2B

    if len(defaulted) > 0:
        values["0125"] = _col_sum_eager(defaulted, set(defaulted.columns), ead_col)
    else:
        values["0125"] = 0.0

    values["0130"] = None  # CCR arising — Phase 3K

    if lfse_data is not None and len(lfse_data) > 0:
        values["0140"] = _col_sum_eager(lfse_data, set(lfse_data.columns), ead_col)
    else:
        values["0140"] = 0.0 if "cp_apply_fi_scalar" in cols else None
    return values


def _c08_lgd_protection_cols(data: pl.DataFrame, cols: set[str]) -> dict[str, float | None]:
    """Compute C 08.01/02 CRM-in-LGD protection columns (0150-0220)."""
    values: dict[str, float | None] = {}

    guar = _sum_by_protection_type(data, cols, "guarantee")
    values["0150"] = guar if guar is not None else _col_sum_eager(data, cols, "guaranteed_portion")
    cd_val = _sum_by_protection_type(data, cols, "credit_derivative")
    values["0160"] = cd_val if cd_val is not None else 0.0
    values["0170"] = 0.0  # Other funded credit protection catch-all
    values["0171"] = 0.0  # Cash on deposit
    values["0172"] = 0.0  # Life insurance policies
    values["0173"] = 0.0  # Instruments held by third party
    values["0180"] = _col_sum_eager(data, cols, "collateral_financial_value")
    values["0190"] = _col_sum_eager(data, cols, "collateral_re_value")
    values["0200"] = _col_sum_eager(data, cols, "collateral_other_physical_value")
    values["0210"] = _col_sum_eager(data, cols, "collateral_receivables_value")
    values["0220"] = _col_sum_eager(data, cols, "double_default_unfunded_protection")
    return values


def _c08_lfse_lgd_avg(
    lfse_data: pl.DataFrame | None,
    cols: set[str],
    ead_col: str,
) -> float | None:
    """Compute the LFSE EAD-weighted-average LGD for C 08 col 0240."""
    if lfse_data is None or len(lfse_data) == 0:
        return 0.0 if "cp_apply_fi_scalar" in cols else None
    lfse_cols = set(lfse_data.columns)
    lfse_lgd_col = _pick(lfse_cols, "lgd_floored", "lgd_input")
    lfse_ead_sum = float(lfse_data[ead_col].fill_null(0.0).sum()) if ead_col in lfse_cols else 0.0
    if lfse_lgd_col is None or lfse_ead_sum <= 0:
        return None
    lgd_x_ead = float(
        (lfse_data[lfse_lgd_col].fill_null(0.0) * lfse_data[ead_col].fill_null(0.0)).sum()
    )
    return lgd_x_ead / lfse_ead_sum


def _c08_lgd_maturity_cols(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    ead_sum: float,
    lfse_data: pl.DataFrame | None,
) -> dict[str, float | None]:
    """Compute C 08.01/02 LGD/maturity weighted-average columns (0230-0250)."""
    values: dict[str, float | None] = {}

    lgd_col = _pick(cols, "lgd_floored", "lgd_input")
    if lgd_col is not None and ead_sum > 0:
        lgd_x_ead = float((data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0230"] = lgd_x_ead / ead_sum
    else:
        values["0230"] = None

    values["0240"] = _c08_lfse_lgd_avg(lfse_data, cols, ead_col)

    if "irb_maturity_m" in cols and ead_sum > 0:
        m_x_ead = float(
            (data["irb_maturity_m"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0250"] = (m_x_ead / ead_sum) * 365.0
    else:
        values["0250"] = None
    return values


def _c08_rwea_factor_cols(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    defaulted: pl.DataFrame,
    lfse_data: pl.DataFrame | None,
) -> dict[str, float | None]:
    """Compute C 08.01/02 RWEA + supporting-factor + output-floor columns (0251-0276)."""
    values: dict[str, float | None] = {}

    # Post-model adjustments (B3.1)
    values["0251"] = _col_sum_eager(data, cols, "rwa_pre_adjustments")
    values["0252"] = _col_sum_eager(data, cols, "post_model_adjustment_rwa")
    values["0253"] = _col_sum_eager(data, cols, "mortgage_rw_floor_adjustment")
    values["0254"] = _col_sum_eager(data, cols, "unrecognised_exposure_adjustment")

    rwa_pre = _col_sum_eager(data, cols, "rwa_pre_factor")
    values["0255"] = rwa_pre if rwa_pre is not None else _col_sum_eager(data, cols, rwa_col)

    pre_factor_col = _pick(cols, "rwa_pre_factor")
    values["0256"] = _supporting_factor_adjustment(
        data, cols, "is_sme", "sme_supporting_factor_applied", pre_factor_col, rwa_col
    )
    values["0257"] = _supporting_factor_adjustment(
        data,
        cols,
        "is_infrastructure",
        "infrastructure_factor_applied",
        pre_factor_col,
        rwa_col,
    )

    values["0260"] = _col_sum_eager(data, cols, rwa_col)

    if len(defaulted) > 0:
        values["0265"] = _col_sum_eager(defaulted, set(defaulted.columns), rwa_col)
    else:
        values["0265"] = 0.0

    if lfse_data is not None and len(lfse_data) > 0:
        values["0270"] = _col_sum_eager(lfse_data, set(lfse_data.columns), rwa_col)
    else:
        values["0270"] = 0.0 if "cp_apply_fi_scalar" in cols else None

    values["0275"] = _col_sum_eager(data, cols, ead_col)
    sa_rwa_col = _pick(cols, "sa_rwa")
    values["0276"] = _col_sum_eager(data, cols, sa_rwa_col) if sa_rwa_col else None
    return values


@cites("PS1/26, paragraph 1.3")
def _c08_memorandum_cols(
    data: pl.DataFrame, cols: set[str], rwa_col: str
) -> dict[str, float | None]:
    """Compute C 08.01/02 memorandum columns (0280-0310).

    Col 0290 ("(-) Value adjustments and provisions") is emitted as a
    NEGATIVE figure per COREP Annex II §1.3; IRB col 0090 is computed
    upstream in ``_compute_c08_values`` from the positive magnitude and is
    not affected.
    """
    values: dict[str, float | None] = {}

    el_raw = _col_sum_eager(data, cols, "expected_loss")
    el_pre = _col_sum_eager(data, cols, "el_pre_adjustment")
    values["0280"] = el_pre if el_pre is not None else el_raw

    values["0281"] = _col_sum_eager(data, cols, "post_model_adjustment_el")
    values["0282"] = _col_sum_eager(data, cols, "el_after_adjustment")

    prov = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")
    if abs(prov) < 1e-9:
        held = _col_sum_eager(data, cols, "provision_held")
        values["0290"] = held if held is not None else prov
    else:
        values["0290"] = prov

    if "counterparty_reference" in cols:
        values["0300"] = float(data["counterparty_reference"].n_unique())
    else:
        values["0300"] = float(len(data))

    # 0310: Pre-credit derivatives RWEA. Both branches resolve to total RWEA
    # — when CD-protected exposures exist, the substitution benefit is already
    # embedded in ``rwa_col``; when none exist, pre-CD RWEA == total RWEA.
    values["0310"] = _col_sum_eager(data, cols, rwa_col)

    # COREP Annex II §1.3: emit "(-)"-labelled deduction col 0290 as negative.
    _negate_deduction_cols(values, _C08_NEGATIVE_COLS)
    return values


def _compute_c08_values(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: list[str],
    *,
    substitution_inflow: float = 0.0,
) -> dict[str, float | str | None]:
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

    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0
    lfse_data = _filter_lfse(data, cols)
    defaulted = _filter_defaulted(data, cols)

    values: dict[str, float | None] = {}
    values.update(_c08_exposure_cols(data, cols, ead_col, ead_sum, lfse_data))
    crm_values = _c08_crm_cols(data, cols, substitution_inflow)
    # 0090 needs the populated 0020 — recompute now that we have it
    v_0020 = values.get("0020") or 0.0
    crm_values["0090"] = (
        v_0020
        - (crm_values.get("0040") or 0.0)
        - (crm_values.get("0050") or 0.0)
        - (crm_values.get("0060") or 0.0)
        - (crm_values.get("0070") or 0.0)
        + (crm_values.get("0080") or 0.0)
    )
    values.update(crm_values)
    values.update(_c08_of_which_cols(data, cols, ead_col, lfse_data, defaulted))
    values.update(_c08_lgd_protection_cols(data, cols))
    values.update(_c08_lgd_maturity_cols(data, cols, ead_col, ead_sum, lfse_data))
    values.update(_c08_rwea_factor_cols(data, cols, ead_col, rwa_col, defaulted, lfse_data))
    values.update(_c08_memorandum_cols(data, cols, rwa_col))

    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _c08_03_exposure_cols(
    data: pl.DataFrame, cols: set[str], ead_sum: float
) -> dict[str, float | None]:
    """Compute C 08.03 exposure columns (0010 on-BS, 0020 off-BS, 0030 CCF, 0040 EAD)."""
    values: dict[str, float | None] = {}

    on_bs = _filter_on_bs(data, cols)
    if on_bs is not None and len(on_bs) > 0:
        values["0010"] = _safe_sum_eager(on_bs, set(on_bs.columns), "drawn_amount", "interest")
    else:
        values["0010"] = _safe_sum_eager(data, cols, "drawn_amount", "interest")

    off_bs = _filter_off_bs(data, cols)
    if off_bs is not None and len(off_bs) > 0:
        values["0020"] = _col_sum_eager(off_bs, set(off_bs.columns), "nominal_amount")
    else:
        values["0020"] = _col_sum_eager(data, cols, "nominal_amount")

    ccf_col = _pick(cols, "ccf")
    nominal_col = _pick(cols, "nominal_amount") if ccf_col is not None and ead_sum > 0 else None
    if ccf_col is not None and ead_sum > 0 and nominal_col is not None:
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

    values["0040"] = ead_sum if ead_sum > 0 else 0.0
    return values


def _c08_03_weighted_avg_cols(
    data: pl.DataFrame,
    cols: set[str],
    ead_col: str,
    pd_col: str,
    ead_sum: float,
) -> dict[str, float | None]:
    """Compute C 08.03 weighted-average columns (0050 PD, 0060 obligors, 0070 LGD, 0080 maturity)."""
    values: dict[str, float | None] = {}
    if pd_col in cols and ead_sum > 0:
        pd_x_ead = float((data[pd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0050"] = pd_x_ead / ead_sum
    else:
        values["0050"] = None

    if "counterparty_reference" in cols:
        values["0060"] = float(data["counterparty_reference"].n_unique())
    else:
        values["0060"] = float(len(data))

    lgd_col = _pick(cols, "lgd_floored", "lgd_input")
    if lgd_col is not None and ead_sum > 0:
        lgd_x_ead = float((data[lgd_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        values["0070"] = lgd_x_ead / ead_sum
    else:
        values["0070"] = None

    if "irb_maturity_m" in cols and ead_sum > 0:
        m_x_ead = float(
            (data["irb_maturity_m"].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum()
        )
        values["0080"] = m_x_ead / ead_sum
    else:
        values["0080"] = None
    return values


def _c08_03_rwea_provisions(
    data: pl.DataFrame, cols: set[str], rwa_col: str
) -> dict[str, float | None]:
    """Compute C 08.03 RWEA + EL + provisions columns (0090, 0100, 0110)."""
    values: dict[str, float | None] = {}
    values["0090"] = _col_sum_eager(data, cols, rwa_col)
    el_col = _pick(cols, "expected_loss")
    values["0100"] = _col_sum_eager(data, cols, el_col) if el_col else None

    prov = _safe_sum_eager(data, cols, "scra_provision_amount", "gcra_provision_amount")
    if abs(prov) < 1e-9:
        held = _col_sum_eager(data, cols, "provision_held")
        values["0110"] = held if held is not None else prov
    else:
        values["0110"] = prov
    return values


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
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0

    values: dict[str, float | None] = {}
    values.update(_c08_03_exposure_cols(data, cols, ead_sum))
    values.update(_c08_03_weighted_avg_cols(data, cols, ead_col, pd_col, ead_sum))
    values.update(_c08_03_rwea_provisions(data, cols, rwa_col))

    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _c08_05_default_counts(
    data: pl.DataFrame,
    cols: set[str],
    cp_col: str | None,
    pd_col: str,
) -> tuple[float, float]:
    """Return ``(n_obligors, n_defaults)`` for the C 08.05 PD-bucket data.

    Uses ``is_defaulted`` / ``default_status`` if present, otherwise falls
    back to ``PD >= 1.0``. Obligor counts unique on ``counterparty_reference``
    when available, else row count.
    """
    n_rows = len(data)
    n_obligors = float(data[cp_col].n_unique()) if cp_col is not None else float(n_rows)
    default_col = _pick(cols, "is_defaulted")

    if default_col is not None:
        defaulted = data.filter(pl.col(default_col) == True)  # noqa: E712
    elif pd_col in cols:
        defaulted = data.filter(pl.col(pd_col) >= 1.0)
    else:
        return n_obligors, 0.0

    if cp_col is not None:
        n_defaults = float(defaulted[cp_col].n_unique())
    else:
        n_defaults = float(len(defaulted))
    return n_obligors, n_defaults


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
    n_obligors, n_defaults = _c08_05_default_counts(data, cols, cp_col, pd_col)

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
        values["0050"] = float(cast("float", data[hist_rate_col].fill_null(0.0).mean()))
    else:
        # Fall back to current observed rate as single-period approximation
        values["0050"] = values["0040"]

    # Filter to only refs in this framework's column set (C 08.05)
    return {ref: values.get(ref) for ref in column_refs if ref in values}


def _c08_07_group_by_class(
    results: pl.LazyFrame,
    ead_col: str,
    rwa_col: str | None,
    ec_col: str,
    approach_col: str,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]] | None:
    """Aggregate the LazyFrame into 4 dicts keyed by exposure class.

    Returns ``(class_irb_ead, class_sa_ead, class_irb_rwa, class_sa_rwa)``
    or ``None`` when the grouped result is empty.
    """
    agg_exprs = [pl.col(ead_col).sum().alias("_sum_ead")]
    if rwa_col:
        agg_exprs.append(pl.col(rwa_col).sum().alias("_sum_rwa"))

    grouped = results.group_by([ec_col, approach_col]).agg(agg_exprs).collect()
    if len(grouped) == 0:
        return None

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

    return class_irb_ead, class_sa_ead, class_irb_rwa, class_sa_rwa


def _c08_01_section2_subset(
    row_ref: str, class_data: pl.DataFrame, cols: set[str]
) -> pl.DataFrame | None:
    """Resolve a C 08.01 Section 2 (Breakdown by Exposure Types) row."""
    if row_ref == "0020":
        return _filter_on_bs(class_data, cols)
    if row_ref == "0030":
        return _filter_off_bs(class_data, cols)
    return None


def _c08_06_sl_type_filter(
    slotting_df: pl.DataFrame,
    sl_key: str,
    sl_type_col: str,
    hvcre_col: str | None,
    framework: str,
) -> pl.DataFrame:
    """Filter slotting data to a single SL-type sheet, accounting for HVCRE.

    Encapsulates the CRR-vs-B3.1 IPRE/HVCRE routing:
    - CRR: IPRE template absorbs both ``ipre`` and ``hvcre`` rows.
    - B3.1: separate HVCRE template, identified by either ``sl_type='hvcre'``
      or the ``is_hvcre`` flag.
    """
    if sl_key == "ipre" and framework != "BASEL_3_1" and hvcre_col is not None:
        return slotting_df.filter(
            (pl.col(sl_type_col) == "ipre") | (pl.col(sl_type_col) == "hvcre")
        )
    if sl_key == "hvcre" and framework == "BASEL_3_1":
        if hvcre_col is not None:
            return slotting_df.filter(
                (pl.col(sl_type_col) == "hvcre") | (pl.col(hvcre_col) == True)  # noqa: E712
            )
        return slotting_df.filter(pl.col(sl_type_col) == "hvcre")
    return slotting_df.filter(pl.col(sl_type_col) == sl_key)


def _c08_06_filter_row(
    type_data: pl.DataFrame,
    cat_col: str,
    category_label: str,
    is_short: bool | None,
    maturity_col: str | None,
) -> pl.DataFrame | None:
    """Filter a slotting-type DataFrame to one C 08.06 category × maturity row.

    Returns ``None`` to signal "skip this row" (unmapped category). Returns
    an empty DataFrame when filtering eliminates everything — caller emits
    a zero row in that case.
    """
    category_value = C08_06_CATEGORY_MAP.get(category_label)
    is_sub_stronger = "substantially stronger" in category_label

    # Filter by category
    if category_label == "Total":
        cat_data = type_data
    else:
        if category_value is None:
            return None
        cat_data = type_data.filter(pl.col(cat_col) == category_value)

    # Filter by maturity band
    if is_short is not None and maturity_col is not None:
        cat_data = cat_data.filter(pl.col(maturity_col) == is_short)  # noqa: E712
    elif is_short is not None and maturity_col is None and is_short:
        cat_data = type_data.clear()

    # "Substantially stronger" sub-rows: no pipeline column identifies these
    # exposures yet; report as empty until a flag is added.
    if is_sub_stronger:
        cat_data = cat_data.clear()

    return cat_data


def _c08_06_row_values_or_zeros(
    column_refs: list[str], rw_display: str | None
) -> dict[str, float | None]:
    """Return a zero-filled value dict for an empty C 08.06 row.

    Sets ``0070`` (Risk weight) from the row definition's RW display string
    when available; falls back to ``None`` otherwise.
    """
    values: dict[str, float | None] = dict.fromkeys(column_refs, 0.0)
    if "0070" in values and rw_display:
        rw_pct = rw_display.replace("%", "").strip()
        try:
            values["0070"] = float(rw_pct) / 100.0
        except ValueError:
            values["0070"] = None
    else:
        values["0070"] = None
    return values


def _c08_06_exposure_cols(
    data: pl.DataFrame, cols: set[str], ead_col: str, ead_sum: float, column_refs: list[str]
) -> tuple[dict[str, float | None], pl.DataFrame | None]:
    """Compute C 08.06 exposure columns (0010-0060). Returns also the off-BS slice."""
    values: dict[str, float | None] = {}
    values["0010"] = _safe_sum_eager(
        data, cols, "drawn_amount", "interest", "nominal_amount", "undrawn_amount"
    )

    crm_col = _pick(cols, "ead_pre_ccf", "exposure_post_crm")
    if crm_col is not None:
        values["0020"] = _col_sum_eager(data, cols, crm_col)
    else:
        values["0020"] = values["0010"]

    off_bs = _filter_off_bs(data, cols)
    if off_bs is not None and len(off_bs) > 0:
        values["0030"] = _safe_sum_eager(
            off_bs, set(off_bs.columns), "nominal_amount", "undrawn_amount"
        )
    else:
        values["0030"] = _col_sum_eager(data, cols, "nominal_amount")

    if "0031" in column_refs:
        values["0031"] = None  # FCCM deduction (B3.1 only)

    values["0040"] = ead_sum if ead_sum > 0 else 0.0

    if off_bs is not None and len(off_bs) > 0:
        values["0050"] = _col_sum_eager(off_bs, set(off_bs.columns), ead_col)
    else:
        values["0050"] = None

    values["0060"] = None  # CCR exposure value (out of scope)
    return values, off_bs


def _c08_06_risk_weight_value(
    data: pl.DataFrame, cols: set[str], ead_col: str, ead_sum: float
) -> float | None:
    """Compute the exposure-weighted-average risk weight for C 08.06 col 0070."""
    rw_col = _pick(cols, "risk_weight")
    if rw_col is None:
        return None
    if ead_sum > 0:
        rw_x_ead = float((data[rw_col].fill_null(0.0) * data[ead_col].fill_null(0.0)).sum())
        return rw_x_ead / ead_sum
    rw_vals = data[rw_col].drop_nulls()
    return float(rw_vals[0]) if len(rw_vals) > 0 else None


def _c08_06_rwea_value(
    data: pl.DataFrame, cols: set[str], rwa_col: str, framework: str
) -> float | None:
    """Compute the C 08.06 col 0080 RWEA value, preferring CRR's rwa_post_factor."""
    if framework != "BASEL_3_1" and "rwa_post_factor" in cols:
        return _col_sum_eager(data, cols, "rwa_post_factor")
    return _col_sum_eager(data, cols, rwa_col)


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
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col in cols else 0.0

    values, _off_bs = _c08_06_exposure_cols(data, cols, ead_col, ead_sum, column_refs)
    values["0070"] = _c08_06_risk_weight_value(data, cols, ead_col, ead_sum)
    values["0080"] = _c08_06_rwea_value(data, cols, rwa_col, framework)

    # 0090: Expected loss amount
    el_col = _pick(cols, "expected_loss")
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


# Row keys whose filter is a single ``_filter_sme(base, cols)`` call.
_C09_01_SME_ROW_KEYS: frozenset[str] = frozenset(
    {"corporate_sme", "retail_sme", "mortgage_sme", "re_sme"}
)

# B3.1 RE sub-row filters: row_key → list of property_type values to match.
_C09_01_RE_PROPERTY_TYPES: dict[str, tuple[str, ...]] = {
    "re_residential": ("residential", "rre"),
    "re_commercial": ("commercial", "cre"),
    "re_other": ("other", "other_re"),
    "re_adc": ("adc",),
}

# B3.1 SL sub-row filters: row_key → sl_type value.
_C09_01_SL_TYPE_MAP: dict[str, str] = {
    "sl_object_finance": "object_finance",
    "sl_commodities_finance": "commodities_finance",
    "sl_project_finance": "project_finance",
}

# CIU sub-approach filters: row_key → ciu_approach value.
_C09_01_CIU_APPROACH_MAP: dict[str, str] = {
    "ciu_look_through": "look_through",
    "ciu_mandate": "mandate_based",
    "ciu_fallback": "fallback",
}


def _filter_c09_01_row(
    data: pl.DataFrame,
    cols: set[str],
    row_key: str,
) -> pl.DataFrame:
    """Filter SA data to match a C 09.01 row definition.

    Maps row keys to pipeline exposure_class values and applies additional
    sub-row filters (SME, RE sub-types, SL sub-types) as needed.
    """
    ec_col = _pick(cols, "exposure_class")
    if ec_col is None:
        return data.clear()

    matching_classes = [ec for ec, mapped in C09_01_SA_CLASS_MAP.items() if mapped == row_key]
    if not matching_classes:
        return data.clear()

    base = data.filter(pl.col(ec_col).is_in(matching_classes))

    # SME sub-row family — single _filter_sme call on the base.
    if row_key in _C09_01_SME_ROW_KEYS:
        return _filter_sme(base, cols)

    # B3.1 real-estate aggregate and property-type sub-rows.
    if row_key == "real_estate":
        return data.filter(pl.col(ec_col) == "retail_mortgage")
    if row_key in _C09_01_RE_PROPERTY_TYPES:
        if "property_type" not in cols:
            return data.clear()
        ptypes = list(_C09_01_RE_PROPERTY_TYPES[row_key])
        return data.filter(
            (pl.col(ec_col) == "retail_mortgage") & (pl.col("property_type").is_in(ptypes))
        )

    # B3.1 SL sub-types.
    if row_key in _C09_01_SL_TYPE_MAP:
        if "sl_type" not in cols:
            return data.clear()
        return data.filter(
            (pl.col(ec_col) == "specialised_lending")
            & (pl.col("sl_type") == _C09_01_SL_TYPE_MAP[row_key])
        )

    # CIU sub-approaches.
    if row_key in _C09_01_CIU_APPROACH_MAP:
        if "ciu_approach" not in cols:
            return data.clear()
        return data.filter(
            (pl.col(ec_col) == "ciu")
            & (pl.col("ciu_approach") == _C09_01_CIU_APPROACH_MAP[row_key])
        )

    # "retail" row = all retail classes combined.
    if row_key == "retail":
        return data.filter(pl.col(ec_col).is_in(["retail_other", "retail_qrre"]))

    return base


def _c09_01_exposure_provisions(
    data: pl.DataFrame,
    cols: set[str],
    ead_gross_col: str | None,
    ead_col: str | None,
) -> dict[str, object]:
    """Compute C 09.01 exposure + provision columns (0010-0075)."""
    values: dict[str, object] = {}

    values["0010"] = _col_sum_eager(data, cols, ead_gross_col)

    defaulted = _filter_defaulted(data, cols)
    if len(defaulted) > 0 and ead_gross_col:
        values["0020"] = float(defaulted[ead_gross_col].fill_null(0.0).sum())
    else:
        values["0020"] = 0.0

    values["0040"] = None  # Observed new defaults (requires temporal data)
    values["0050"] = _col_sum_eager(data, cols, "gcra_provision_amount")
    values["0055"] = _col_sum_eager(data, cols, "scra_provision_amount")
    values["0060"] = None  # Write-offs
    values["0061"] = None  # Additional value adjustments
    values["0070"] = None  # CRA for observed new defaults
    values["0075"] = _col_sum_eager(data, cols, ead_col)
    return values


def _c09_01_rwea_factors(
    data: pl.DataFrame,
    cols: set[str],
    column_refs: list[str],
    rwa_col: str | None,
) -> dict[str, object]:
    """Compute C 09.01 RWEA + supporting-factor columns (0080-0090)."""
    values: dict[str, object] = {}
    if "0080" in column_refs:
        values["0080"] = _col_sum_eager(data, cols, rwa_col)
    if "0081" in column_refs:
        values["0081"] = None  # SME supporting factor adjustment (CRR only)
    if "0082" in column_refs:
        values["0082"] = None  # Infrastructure supporting factor adjustment (CRR only)
    values["0090"] = _col_sum_eager(data, cols, rwa_col)
    return values


def _compute_c09_01_values(
    data: pl.DataFrame,
    cols: set[str],
    column_refs: list[str],
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
    ead_gross_col = _pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = _pick(cols, "ead_final")
    rwa_col = _pick(cols, "rwa_final", "rwa")

    values: dict[str, object] = {}
    values.update(_c09_01_exposure_provisions(data, cols, ead_gross_col, ead_col))
    values.update(_c09_01_rwea_factors(data, cols, column_refs, rwa_col))

    return {ref: values.get(ref) for ref in column_refs}


# =============================================================================
# C 09.02 / OF 09.02 — GEOGRAPHICAL BREAKDOWN IRB HELPERS
# =============================================================================


# C 09.02 row keys that map directly to a single exposure_class value.
_C09_02_DIRECT_EC: dict[str, str] = {
    "central_govt_central_bank": "central_govt_central_bank",
    "institution": "institution",
    "retail_mortgage": "retail_mortgage",
    "retail_qrre": "retail_qrre",
    "retail_other": "retail_other",
    "equity": "equity",
}

# C 09.02 row keys that always report empty (require flags not yet in pipeline).
_C09_02_EMPTY_KEYS: frozenset[str] = frozenset(
    {"corporate_purchased_receivables", "retail_purchased_receivables"}
)

# C 09.02 retail-RE non-SME row keys mapped to their property_type list.
_C09_02_RE_PROPERTY_TYPES: dict[str, tuple[str, ...]] = {
    "retail_resi_re_sme": ("residential", "rre"),
    "retail_resi_re_non_sme": ("residential", "rre"),
    "retail_comm_re_sme": ("commercial", "cre"),
    "retail_comm_re_non_sme": ("commercial", "cre"),
}


def _filter_c09_02_retail_re(
    data: pl.DataFrame, cols: set[str], ec_col: str, row_key: str
) -> pl.DataFrame:
    """Handle the four B3.1 retail-RE rows (resi/comm × SME/non-SME)."""
    base = data.filter(pl.col(ec_col) == "retail_mortgage")
    ptypes = list(_C09_02_RE_PROPERTY_TYPES[row_key])
    if "property_type" in cols:
        base = base.filter(pl.col("property_type").is_in(ptypes))
    return (
        _filter_sme(base, cols)
        if row_key.endswith("_sme") and not row_key.endswith("_non_sme")
        else _filter_non_sme(base, cols)
    )


def _filter_c09_02_sl_rows(
    data: pl.DataFrame,
    cols: set[str],
    ec_col: str,
    row_key: str,
    approach_col: str | None,
) -> pl.DataFrame | None:
    """Handle specialised-lending sub-rows of C 09.02 (sl_excl_slotting, sl_slotting)."""
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
    return None


def _filter_c09_02_corporate_non_sme(
    data: pl.DataFrame, cols: set[str], ec_col: str
) -> pl.DataFrame:
    """Non-SME general corporates: excludes SME-eligible and FSE/large rows."""
    base = data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"]))
    non_sme = base
    if "sme_supporting_factor_eligible" in cols:
        non_sme = base.filter(
            pl.col("sme_supporting_factor_eligible") != True  # noqa: E712
        )
    elif "exposure_class" in cols:
        non_sme = base.filter(~pl.col("exposure_class").str.contains("sme"))
    if "cp_apply_fi_scalar" in cols:
        non_sme = non_sme.filter(pl.col("cp_apply_fi_scalar") != True)  # noqa: E712
    return non_sme


def _filter_c09_02_corporate(
    data: pl.DataFrame, cols: set[str], ec_col: str, row_key: str, approach_col: str | None
) -> pl.DataFrame | None:
    """Handle corporate row family (sl_excl_slotting, sl_slotting, sme, fse_large, non_sme).

    Returns ``None`` when ``row_key`` is outside the corporate family — caller
    continues to the next branch.
    """
    if row_key == "corporate":
        return data.filter(
            pl.col(ec_col).is_in(["corporate", "corporate_sme", "specialised_lending"])
        )

    sl_result = _filter_c09_02_sl_rows(data, cols, ec_col, row_key, approach_col)
    if sl_result is not None:
        return sl_result

    if row_key == "corporate_sme":
        return _filter_sme(data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"])), cols)
    if row_key == "corporate_fse_large":
        base = data.filter(pl.col(ec_col).is_in(["corporate", "corporate_sme"]))
        if "cp_apply_fi_scalar" in cols:
            return base.filter(pl.col("cp_apply_fi_scalar") == True)  # noqa: E712
        return data.clear()
    if row_key == "corporate_non_sme":
        return _filter_c09_02_corporate_non_sme(data, cols, ec_col)
    return None


def _filter_c09_02_retail_basic(
    data: pl.DataFrame, cols: set[str], ec_col: str, row_key: str
) -> pl.DataFrame | None:
    """Handle CRR retail sub-rows: mortgage/other × SME/non-SME and retail aggregate."""
    if row_key == "retail":
        return data.filter(pl.col(ec_col).is_in(["retail_mortgage", "retail_qrre", "retail_other"]))
    if row_key == "retail_mortgage_sme":
        return _filter_sme(data.filter(pl.col(ec_col) == "retail_mortgage"), cols)
    if row_key == "retail_mortgage_non_sme":
        return _filter_non_sme(data.filter(pl.col(ec_col) == "retail_mortgage"), cols)
    if row_key == "retail_other_sme":
        return _filter_sme(data.filter(pl.col(ec_col) == "retail_other"), cols)
    if row_key == "retail_other_non_sme":
        return _filter_non_sme(data.filter(pl.col(ec_col) == "retail_other"), cols)
    return None


def _filter_c09_02_row(
    data: pl.DataFrame,
    cols: set[str],
    row_key: str,
    approach_col: str | None,
) -> pl.DataFrame:
    """Filter IRB data to match a C 09.02 row definition.

    Maps row keys to pipeline exposure_class values and applies additional
    sub-row filters (SL, SME, RE sub-types) as needed.
    """
    ec_col = _pick(cols, "exposure_class")
    if ec_col is None:
        return data.clear()

    if row_key in _C09_02_DIRECT_EC:
        return data.filter(pl.col(ec_col) == _C09_02_DIRECT_EC[row_key])
    if row_key in _C09_02_EMPTY_KEYS:
        return data.clear()

    corp_result = _filter_c09_02_corporate(data, cols, ec_col, row_key, approach_col)
    if corp_result is not None:
        return corp_result

    retail_result = _filter_c09_02_retail_basic(data, cols, ec_col, row_key)
    if retail_result is not None:
        return retail_result

    if row_key in _C09_02_RE_PROPERTY_TYPES:
        return _filter_c09_02_retail_re(data, cols, ec_col, row_key)

    return data.clear()


def _weighted_avg_or_mean(
    data: pl.DataFrame,
    value_col: str | None,
    weight_col: str | None,
    weight_sum: float,
) -> float | None:
    """EAD-weighted average of ``value_col``; falls back to simple mean.

    Returns None when ``value_col`` is absent or no non-null values exist.
    """
    if value_col is None:
        return None
    if weight_col is not None and weight_sum > 0:
        weighted = float((data[value_col].fill_null(0.0) * data[weight_col].fill_null(0.0)).sum())
        return weighted / weight_sum
    vals = data[value_col].drop_nulls()
    return float(cast("float", vals.mean())) if len(vals) > 0 else None


def _c09_02_pd_lgd_weighted(
    data: pl.DataFrame,
    defaulted: pl.DataFrame,
    ead_col: str | None,
    pd_col: str | None,
    lgd_col: str | None,
) -> dict[str, object]:
    """Compute PD/LGD weighted-average columns (0080, 0090, 0100)."""
    ead_sum = float(data[ead_col].fill_null(0.0).sum()) if ead_col else 0.0

    values: dict[str, object] = {
        "0080": _weighted_avg_or_mean(data, pd_col, ead_col, ead_sum),
        "0090": _weighted_avg_or_mean(data, lgd_col, ead_col, ead_sum),
    }

    if len(defaulted) > 0 and lgd_col:
        def_ead_sum = float(defaulted[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
        values["0100"] = _weighted_avg_or_mean(defaulted, lgd_col, ead_col, def_ead_sum)
    else:
        values["0100"] = None
    return values


def _c09_02_defaulted_metrics(
    defaulted: pl.DataFrame,
    column_refs: list[str],
    ead_col: str | None,
    rwa_col: str | None,
) -> dict[str, object]:
    """Compute defaulted-exposure metrics (0107 B31 only, 0120)."""
    values: dict[str, object] = {}
    if "0107" in column_refs:
        if len(defaulted) > 0 and ead_col:
            values["0107"] = float(defaulted[ead_col].fill_null(0.0).sum())
        else:
            values["0107"] = 0.0
    if len(defaulted) > 0 and rwa_col:
        values["0120"] = float(defaulted[rwa_col].fill_null(0.0).sum())
    else:
        values["0120"] = 0.0
    return values


def _c09_02_optional_cols(column_refs: list[str], data, cols, rwa_col) -> dict[str, object]:
    """Compute optional/CRR-only C 09.02 columns (0110/0121/0122)."""
    values: dict[str, object] = {}
    if "0110" in column_refs:
        values["0110"] = _col_sum_eager(data, cols, rwa_col)
    if "0121" in column_refs:
        values["0121"] = None
    if "0122" in column_refs:
        values["0122"] = None
    return values


def _compute_c09_02_values(
    data: pl.DataFrame,
    cols: set[str],
    column_refs: list[str],
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
    ead_gross_col = _pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = _pick(cols, "ead_final")
    rwa_col = _pick(cols, "rwa_final", "rwa")
    pd_col = _pick(cols, "pd_floored", "pd")
    lgd_col = _pick(cols, "lgd_post_crm")
    el_col = _pick(cols, "expected_loss")

    defaulted = _filter_defaulted(data, cols)

    values: dict[str, object] = {
        "0010": _col_sum_eager(data, cols, ead_gross_col),
        "0040": None,  # Observed new defaults
        "0050": _col_sum_eager(data, cols, "gcra_provision_amount"),
        "0055": _col_sum_eager(data, cols, "scra_provision_amount"),
        "0060": None,  # Write-offs
        "0070": None,  # CRA for observed new defaults
        "0105": _col_sum_eager(data, cols, ead_col),
        "0125": _col_sum_eager(data, cols, rwa_col),
        "0130": _col_sum_eager(data, cols, el_col) if el_col else None,
    }

    if len(defaulted) > 0 and ead_gross_col:
        values["0030"] = float(defaulted[ead_gross_col].fill_null(0.0).sum())
    else:
        values["0030"] = 0.0

    values.update(_c09_02_pd_lgd_weighted(data, defaulted, ead_col, pd_col, lgd_col))
    values.update(_c09_02_defaulted_metrics(defaulted, column_refs, ead_col, rwa_col))
    values.update(_c09_02_optional_cols(column_refs, data, cols, rwa_col))

    return {ref: values.get(ref) for ref in column_refs}


# =============================================================================
# CROSS-CUTTING LEAF HELPERS
# =============================================================================
# Helpers below are used by multiple ``_compute_*`` / ``_filter_*`` functions
# to remove verbatim-duplicated logic that drove up SonarQube cyclomatic
# complexity warnings (S3776).


def _supporting_factor_adjustment(
    data: pl.DataFrame,
    cols: set[str],
    flag_col: str,
    applied_col: str,
    pre_factor_col: str | None,
    rwa_col: str,
) -> float | None:
    """Compute the negative adjustment from a supporting factor.

    The adjustment = sum(rwa_pre_factor - rwa_final) over the rows where the
    factor was applied. Used for both SME (Art. 501) and infrastructure
    (Art. 501a) supporting factors in C 07.00 (rows 0216/0217) and
    C 08.01/02 (rows 0256/0257).

    Tries two column patterns in order:
    1. A dedicated ``<factor>_supporting_factor_applied`` flag on the row.
    2. The generic ``supporting_factor_applied`` flag combined with an
       ``is_sme`` / ``is_infrastructure`` indicator.

    Returns 0.0 when the columns are present but no rows match, and None when
    neither column pattern is available (CRR column should be reported null).
    """
    if pre_factor_col is None:
        return None

    applied_specific = _pick(cols, applied_col)
    if applied_specific is not None:
        subset = data.filter(pl.col(applied_specific) == True)  # noqa: E712
        if len(subset) == 0:
            return 0.0
        pre = float(subset[pre_factor_col].fill_null(0.0).sum())
        post = float(subset[rwa_col].fill_null(0.0).sum())
        return pre - post

    if flag_col in cols and "supporting_factor_applied" in cols:
        subset = data.filter(
            (pl.col(flag_col) == True)  # noqa: E712
            & (pl.col("supporting_factor_applied") == True)  # noqa: E712
        )
        if len(subset) == 0:
            return 0.0
        pre = float(subset[pre_factor_col].fill_null(0.0).sum())
        post = float(subset[rwa_col].fill_null(0.0).sum())
        return pre - post

    return None


def _filter_non_sme(base: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter ``base`` to non-SME rows by removing the SME subset.

    Used by C 09.02 retail non-SME sub-rows. Matches the pattern of computing
    SME refs first, then filtering ``base`` to ``~is_in(sme_refs)`` to
    preserve any rows that lack an ``is_sme`` indicator entirely.
    """
    sme = _filter_sme(base, cols)
    if len(sme) > 0 and "exposure_reference" in cols:
        sme_refs = set(sme["exposure_reference"].to_list())
        if sme_refs:
            return base.filter(~pl.col("exposure_reference").is_in(list(sme_refs)))
    return base


def _collect_unique_countries(df: pl.DataFrame, country_col: str) -> list[str]:
    """Return the sorted list of distinct non-null country codes in ``df``."""
    return (
        df.select(pl.col(country_col))
        .filter(pl.col(country_col).is_not_null())
        .unique()
        .sort(country_col)
        .to_series()
        .to_list()
    )


# =============================================================================
# C 02.00 ROW-POPULATION HELPERS
# =============================================================================
# Helpers below split the monolithic ``_generate_c_02_00`` into per-section
# row-population steps. Each mutates ``row_values`` in place so the caller can
# continue to assemble the final DataFrame from one shared dict.


def _c02_00_sa_rows(
    row_values: dict[str, dict[str, object]],
    sa_class_rwa: dict[str, float],
    is_b31: bool,
) -> None:
    """Populate SA per-class rows + B31 specialised-lending sub-row (0131)."""
    for ec_value, row_ref in C02_00_SA_CLASS_MAP.items():
        if ec_value in sa_class_rwa:
            if row_ref not in row_values:
                row_values[row_ref] = {"0010": 0.0}
            existing = float(cast("float", row_values[row_ref].get("0010", 0.0) or 0.0))
            row_values[row_ref]["0010"] = existing + sa_class_rwa[ec_value]

    if is_b31 and "specialised_lending" in sa_class_rwa:
        row_values["0131"] = {"0010": sa_class_rwa["specialised_lending"]}


def _c02_00_firb_rows(
    row_values: dict[str, dict[str, object]],
    firb_rwa: float,
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    is_b31: bool,
) -> None:
    """Populate F-IRB rows (0240, 0250, 0260, 0271, 0290, 0295-0297)."""
    row_values["0240"] = {"0010": firb_rwa}

    firb_inst = irb_class_rwa.get(("foundation_irb", "institution"), 0.0)
    row_values["0250"] = {"0010": firb_inst}
    if is_b31:
        row_values["0271"] = {"0010": firb_inst}

    firb_corp = irb_class_rwa.get(("foundation_irb", "corporate"), 0.0)
    firb_sl = irb_class_rwa.get(("foundation_irb", "specialised_lending"), 0.0)
    row_values["0260"] = {"0010": firb_corp + firb_sl}

    if is_b31:
        row_values["0290"] = {"0010": firb_sl}
        firb_fse, firb_sme, firb_nonsme = _irb_sub_split(
            irb_sub_rwa, "foundation_irb", "corporate", firb_corp
        )
        row_values["0295"] = {"0010": firb_fse}  # Financial/large corporates
        row_values["0296"] = {"0010": firb_sme}  # Other general corporates SME
        row_values["0297"] = {"0010": firb_nonsme}  # Other general corporates non-SME


def _c02_00_airb_corp_rows(
    row_values: dict[str, dict[str, object]],
    airb_rwa: float,
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    is_b31: bool,
) -> None:
    """Populate A-IRB sovereign / institution / corporate rows (0300-0356)."""
    row_values["0300"] = {"0010": airb_rwa}

    airb_sovereign = irb_class_rwa.get(("advanced_irb", "central_government"), 0.0)
    row_values["0310"] = {"0010": airb_sovereign}

    airb_inst = irb_class_rwa.get(("advanced_irb", "institution"), 0.0)
    row_values["0330"] = {"0010": airb_inst}

    airb_corp = irb_class_rwa.get(("advanced_irb", "corporate"), 0.0)
    airb_sl_excl = irb_class_rwa.get(("advanced_irb", "specialised_lending"), 0.0)
    row_values["0340"] = {"0010": airb_corp + airb_sl_excl}

    if is_b31:
        row_values["0350"] = {"0010": airb_sl_excl}
        airb_fse, airb_sme, airb_nonsme = _irb_sub_split(
            irb_sub_rwa, "advanced_irb", "corporate", airb_corp
        )
        row_values["0355"] = {"0010": airb_sme}
        row_values["0356"] = {"0010": airb_nonsme + airb_fse}


def _c02_00_airb_retail_rows(
    row_values: dict[str, dict[str, object]],
    irb_class_rwa: dict[tuple[str, str], float],
    irb_sub_rwa: dict[tuple[str, str, bool | None, bool | None, str | None], float],
    is_b31: bool,
) -> None:
    """Populate A-IRB retail rows (0370, 0380-0385, 0390, 0400, 0410-CRR)."""
    airb_retail_mort = irb_class_rwa.get(("advanced_irb", "retail_mortgage"), 0.0)
    airb_retail_qrre = irb_class_rwa.get(("advanced_irb", "retail_qrre"), 0.0)
    airb_retail_other = irb_class_rwa.get(("advanced_irb", "retail_other"), 0.0)

    row_values["0370"] = {"0010": airb_retail_mort + airb_retail_qrre + airb_retail_other}
    row_values["0380"] = {"0010": airb_retail_mort}

    if is_b31:
        resi_sme, resi_nonsme, comm_sme, comm_nonsme = _irb_re_sub_split(
            irb_sub_rwa, "advanced_irb", "retail_mortgage", airb_retail_mort
        )
        row_values["0382"] = {"0010": resi_sme}
        row_values["0383"] = {"0010": resi_nonsme}
        row_values["0384"] = {"0010": comm_sme}
        row_values["0385"] = {"0010": comm_nonsme}

    row_values["0390"] = {"0010": airb_retail_qrre}

    if is_b31:
        other_sme, other_nonsme = _irb_other_sme_split(
            irb_sub_rwa, "advanced_irb", "retail_other", airb_retail_other
        )
        row_values["0400"] = {"0010": other_sme}
        row_values["0410"] = {"0010": other_nonsme}
    else:
        row_values["0400"] = {"0010": airb_retail_other}


def _c02_00_slotting_rows(
    row_values: dict[str, dict[str, object]],
    slotting_rwa: float,
    slotting_type_rwa: dict[str, float],
    is_b31: bool,
) -> None:
    """Populate slotting rows: CRR single 0410 vs B31 per-SL-type 0411-0416."""
    if is_b31:
        row_values["0411"] = {"0010": slotting_rwa}
        row_values["0412"] = {"0010": slotting_type_rwa.get("project_finance", 0.0)}
        row_values["0413"] = {"0010": slotting_type_rwa.get("object_finance", 0.0)}
        row_values["0414"] = {"0010": slotting_type_rwa.get("commodities_finance", 0.0)}
        row_values["0415"] = {"0010": slotting_type_rwa.get("ipre", 0.0)}
        row_values["0416"] = {"0010": slotting_type_rwa.get("hvcre", 0.0)}
    else:
        row_values["0410"] = {"0010": slotting_rwa}


def _c02_00_apply_b31_cols(
    row_values: dict[str, dict[str, object]],
    sa_equiv_rwa: float,
    floor_rwa: float,
) -> None:
    """Fill B3.1 cols 0020 (SA-equivalent) and 0030 (output floor) for each row.

    Each row's policy follows row-ref membership: totals take the portfolio
    SA-equiv / floor values, indicator rows mirror col 0010, IRB rows zero out,
    and SA rows default to col 0010.
    """
    for ref, vals in row_values.items():
        col_0010 = vals.get("0010")
        if ref in {"0010", "0050"}:
            vals["0020"] = sa_equiv_rwa
            vals["0030"] = floor_rwa
        elif ref == "0040":
            vals["0020"] = sa_equiv_rwa * 0.08
            vals["0030"] = floor_rwa * 0.08
        elif ref in {"0034", "0035", "0036"}:
            vals["0020"] = col_0010
            vals["0030"] = col_0010
        elif ref == "0060":
            vals["0020"] = vals["0010"]
            vals["0030"] = vals["0010"]
        elif ref in {"0220", "0240", "0300"}:
            vals["0020"] = 0.0
            vals["0030"] = 0.0
        else:
            vals["0020"] = col_0010 if col_0010 is not None else None
            vals["0030"] = col_0010 if col_0010 is not None else None


def _c02_00_row_dict(
    row_def,
    row_values: dict[str, dict[str, object]],
    column_refs: list[str],
) -> dict[str, object]:
    """Build a single C 02.00 DataFrame row dict.

    Three regimes: populated (ref in row_values), zero-fill (credit-risk row
    without data), or null-fill (out-of-scope row).
    """
    if row_def.ref in row_values:
        vals = row_values[row_def.ref]
        return {
            "row_ref": row_def.ref,
            "row_name": row_def.name,
            **{ref: vals.get(ref) for ref in column_refs},
        }
    if row_def.ref in C02_00_CREDIT_RISK_ROWS:
        return {
            "row_ref": row_def.ref,
            "row_name": row_def.name,
            **dict.fromkeys(column_refs, 0.0),
        }
    return _null_row(row_def.ref, row_def.name, column_refs)


def _c02_00_build_rows(
    row_values: dict[str, dict[str, object]],
    row_sections,
    column_refs: list[str],
) -> list[dict[str, object]]:
    """Assemble C 02.00 DataFrame rows from ``row_values`` + section templates."""
    return [
        _c02_00_row_dict(row_def, row_values, column_refs)
        for section in row_sections
        for row_def in section.rows
    ]


def _c02_00_floor_indicator_rows(
    row_values: dict[str, dict[str, object]],
    floor_activated: bool,
    output_floor_summary: OutputFloorSummary | None,
    output_floor_config: OutputFloorConfig | None,
    is_b31: bool,
) -> None:
    """Populate B31 output floor indicator rows 0034/0035/0036.

    Art. 92 para 2A: floor applies only to certain entity-type/basis combos.
    When ``output_floor_config`` provides ``is_floor_applicable() == False``,
    the indicator rows are still emitted but with zero values.
    """
    if not is_b31:
        return

    floor_applicable = output_floor_config is None or output_floor_config.is_floor_applicable()
    if floor_applicable:
        row_values["0034"] = {"0010": 1.0 if floor_activated else 0.0}
        if output_floor_summary is not None:
            row_values["0035"] = {"0010": output_floor_summary.floor_pct * 100.0}
            row_values["0036"] = {"0010": output_floor_summary.of_adj}
        else:
            row_values["0035"] = {"0010": 0.0}
            row_values["0036"] = {"0010": 0.0}
    else:
        row_values["0034"] = {"0010": 0.0}
        row_values["0035"] = {"0010": 0.0}
        row_values["0036"] = {"0010": 0.0}
