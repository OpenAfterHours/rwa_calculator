"""
COREP template generator for credit risk reporting.

Pipeline position:
    calculation results (ResultsSource) -> COREPGenerator -> COREPTemplateBundle -> Excel

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
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.corep.c02 import generate_c02_00
from rwa_calc.reporting.corep.c07 import generate_c07
from rwa_calc.reporting.corep.c08 import (
    generate_c08_01,
    generate_c08_02,
    generate_c08_03,
    generate_c08_04,
    generate_c08_05,
    generate_c08_06,
    generate_c08_07,
)
from rwa_calc.reporting.corep.c09 import generate_c09_01, generate_c09_02
from rwa_calc.reporting.corep.of02 import generate_of_02_01
from rwa_calc.reporting.corep.templates import (
    C34_01_ROWS,
    C34_02_ROWS,
    C34_04_ROWS,
    C34_08_ROWS,
    IRB_EXPOSURE_CLASS_ROWS,
    OF_02_01_COLUMNS,
    SA_EXPOSURE_CLASS_ROWS,
    get_c02_00_columns,
    get_c07_columns,
    get_c08_02_columns,
    get_c08_03_columns,
    get_c08_04_columns,
    get_c08_05_columns,
    get_c08_06_columns,
    get_c08_06_sl_types,
    get_c08_07_columns,
    get_c08_columns,
    get_c09_01_columns,
    get_c09_02_columns,
    get_c34_01_columns,
    get_c34_02_columns,
    get_c34_04_columns,
    get_c34_08_columns,
)
from rwa_calc.reporting.kernel import (
    available_columns as _available_columns,
)
from rwa_calc.reporting.kernel import (
    column_name_map,
    write_template_sheet,
)
from rwa_calc.reporting.kernel import (
    pick as _pick,
)
from rwa_calc.reporting.metadata import ResultsSource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from polars._typing import PolarsDataType
    from xlsxwriter import Workbook

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
        response: ResultsSource,
        *,
        output_floor_summary: OutputFloorSummary | None = None,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> COREPTemplateBundle:
        """Generate all COREP templates from a calculation results source."""
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
        c08_01 = self._generate_all_c08_01(results, cols, framework, errors)
        c08_02 = self._generate_all_c08_02(results, cols, framework, errors)
        c08_03 = self._generate_all_c08_03(results, cols, framework, errors)
        c08_04 = self._generate_all_c08_04(results, cols, framework, errors)
        c08_05 = self._generate_all_c08_05(results, cols, framework, errors)
        c08_06 = generate_c08_06(results, cols, framework, errors)

        # C 08.07 / OF 08.07 — IRB scope of use
        c08_07 = generate_c08_07(results, cols, framework, errors)

        # OF 02.01 — Output floor comparison (Basel 3.1 only)
        of_02_01 = generate_of_02_01(
            results,
            cols,
            framework,
            errors,
            output_floor_config=output_floor_config,
        )

        # C 02.00 / OF 02.00 — Own Funds Requirements
        c_02_00 = generate_c02_00(
            results,
            cols,
            framework,
            errors,
            output_floor_summary=output_floor_summary,
            output_floor_config=output_floor_config,
        )

        # C 09.01 / OF 09.01 — Geographical Breakdown SA
        c09_01 = generate_c09_01(results, cols, framework, errors)

        # C 09.02 / OF 09.02 — Geographical Breakdown IRB
        c09_02 = generate_c09_02(results, cols, framework, errors)

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
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 08.01 IRB templates.

        Dispatch-router entry (Phase 7 S8): C 08.01 is declarative — the
        cell semantics live in ``corep/c08.py::generate_c08_01`` and run
        through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 142-191; Reg (EU) 2021/451 Annex I/II; PS1/26 Annex II.
        """
        return generate_c08_01(results, cols, framework, errors)

    def _generate_all_c08_02(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 08.02 IRB grade/PD-band templates.

        Dispatch-router entry (Phase 7 S8): C 08.02 is declarative — the
        data-driven grade/PD-band rows and the String 0005 column live in
        ``corep/c08.py::generate_c08_02`` (the CR9.1 pattern).
        """
        return generate_c08_02(results, cols, framework, errors)

    def _generate_all_c08_03(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 08.03 PD-range templates.

        Dispatch-router entry (Phase 7 S8): declarative in
        ``corep/c08.py::generate_c08_03`` (sparse PD-range rows).
        """
        return generate_c08_03(results, cols, framework, errors)

    def _generate_all_c08_04(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 08.04 RWEA flow templates.

        Dispatch-router entry (Phase 7 S8): declarative in
        ``corep/c08.py::generate_c08_04`` (only the closing row populates).
        """
        return generate_c08_04(results, cols, framework, errors)

    def _generate_all_c08_05(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class C 08.05 PD back-testing templates.

        Dispatch-router entry (Phase 7 S8): declarative in
        ``corep/c08.py::generate_c08_05`` (sparse ranges, point-in-time
        proxies for the prior-year/historical carriers).
        """
        return generate_c08_05(results, cols, framework, errors)


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


_SECTION3_NULL_REFS: frozenset[str] = frozenset({"0160", "0170", "0175", "0180"})


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


# =============================================================================
# C 09.01 / OF 09.01 — GEOGRAPHICAL BREAKDOWN SA HELPERS
# =============================================================================


# =============================================================================
# C 09.02 / OF 09.02 — GEOGRAPHICAL BREAKDOWN IRB HELPERS
# =============================================================================


# =============================================================================
# CROSS-CUTTING LEAF HELPERS
# =============================================================================
# Helpers below are used by multiple ``_compute_*`` / ``_filter_*`` functions
# to remove verbatim-duplicated logic that drove up SonarQube cyclomatic
# complexity warnings (S3776).


# =============================================================================
# C 02.00 ROW-POPULATION HELPERS
# =============================================================================
# Helpers below split the monolithic ``_generate_c_02_00`` into per-section
# row-population steps. Each mutates ``row_values`` in place so the caller can
# continue to assemble the final DataFrame from one shared dict.
