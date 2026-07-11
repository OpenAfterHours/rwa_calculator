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
    - CCR1: Analysis of CCR exposure by approach (SA-CCR EAD / RWEA)
    - CCR2: CVA capital charge (BA-CVA RWEA, Basel 3.1)
    - CCR3: SA-CCR EAD allocation by risk-weight band
    - CCR8: Exposures to central counterparties (QCCP vs non-QCCP RWEA)

References:
    CRR Part 8 (Art. 438, 439, 444, 452, 453)
    PRA PS1/26 Disclosure (CRR) Part, Art. 456, Art. 2a
    PRA PS1/26 Annex XXII (CR9/CR9.1 back-testing instructions)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.kernel import (
    available_columns as _available_columns,
)
from rwa_calc.reporting.kernel import (
    col_sum,
    column_name_map,
    filter_by_approach,
    null_row,
    safe_sum_or_none,
    write_template_sheet,
)
from rwa_calc.reporting.kernel import (
    pick as _pick,
)
from rwa_calc.reporting.pillar3.cr4 import generate_cr4
from rwa_calc.reporting.pillar3.cr5 import generate_cr5
from rwa_calc.reporting.pillar3.cr6 import generate_cr6
from rwa_calc.reporting.pillar3.cr6a import generate_cr6a
from rwa_calc.reporting.pillar3.cr7 import generate_cr7
from rwa_calc.reporting.pillar3.cr7a import generate_cr7a
from rwa_calc.reporting.pillar3.cr8 import generate_cr8
from rwa_calc.reporting.pillar3.cr9 import generate_cr9, generate_cr9_1
from rwa_calc.reporting.pillar3.cr10 import generate_cr10
from rwa_calc.reporting.pillar3.ov1 import generate_ov1
from rwa_calc.reporting.pillar3.templates import (
    CCR1_COLUMNS,
    CCR1_ROWS,
    CCR2_COLUMNS,
    CCR2_ROWS,
    CCR3_COLUMNS,
    CCR8_COLUMNS,
    CCR8_ROWS,
    CMS1_COLUMNS,
    CMS1_ROWS,
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
    CR6A_COLUMNS,
    CR7_COLUMNS,
    CR8_COLUMNS,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMNS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    P3Row,
    get_ccr3_risk_weights,
    get_ccr3_rows,
    get_cr4_columns,
    get_cr5_columns,
    get_cr6_columns,
    get_cr7a_columns,
    get_cr10_columns,
    get_cr10_subtemplates,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    ccr1: pl.DataFrame | None = None
    ccr2: pl.DataFrame | None = None
    ccr3: pl.DataFrame | None = None
    ccr8: pl.DataFrame | None = None
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
            cr4=self._generate_cr4(results, cols, framework, errors),
            cr5=self._generate_cr5(results, cols, framework, errors),
            cr6=self._generate_all_cr6(results, cols, framework, errors),
            cr6a=self._generate_cr6a(results, cols, framework, errors),
            cr7=self._generate_cr7(results, cols, framework, errors),
            cr7a=self._generate_all_cr7a(results, cols, framework, errors),
            cr8=self._generate_cr8(irb_data, cols, errors, prior_irb_data),
            cr9=self._generate_all_cr9(results, cols, framework, errors),
            cr9_1=self._generate_cr9_1(results, cols, framework, errors),
            cr10=self._generate_all_cr10(results, cols, framework, errors),
            cms1=self._generate_cms1(results, cols, framework, errors),
            cms2=self._generate_cms2(
                results, sa_data, irb_data, slotting_data, cols, framework, errors
            ),
            ccr1=self._generate_ccr1(results, cols, errors),
            ccr2=self._generate_ccr2(results, cols, framework, errors),
            ccr3=self._generate_ccr3(results, cols, framework, errors),
            ccr8=self._generate_ccr8(results, cols, errors),
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
        framework = bundle.framework
        prefix = "UKB" if framework == "BASEL_3_1" else "UK"

        try:
            if bundle.ov1 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.ov1, f"{prefix} OV1", column_name_map(OV1_COLUMNS)
                )
            if bundle.cr4 is not None:
                total_rows += _write_single_sheet(
                    workbook,
                    bundle.cr4,
                    f"{prefix} CR4",
                    column_name_map(get_cr4_columns(framework)),
                )
            if bundle.cr5 is not None:
                total_rows += _write_single_sheet(
                    workbook,
                    bundle.cr5,
                    f"{prefix} CR5",
                    column_name_map(get_cr5_columns(framework)),
                )
            total_rows += _write_dict_sheets(
                workbook,
                bundle.cr6,
                f"{prefix} CR6",
                IRB_EXPOSURE_CLASSES,
                column_name_map(get_cr6_columns(framework)),
            )
            if bundle.cr6a is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr6a, f"{prefix} CR6-A", column_name_map(CR6A_COLUMNS)
                )
            if bundle.cr7 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr7, f"{prefix} CR7", column_name_map(CR7_COLUMNS)
                )
            total_rows += _write_dict_sheets(
                workbook,
                bundle.cr7a,
                f"{prefix} CR7-A",
                {"foundation_irb": "F-IRB", "advanced_irb": "A-IRB"},
                column_name_map(get_cr7a_columns(framework)),
            )
            if bundle.cr8 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cr8, f"{prefix} CR8", column_name_map(CR8_COLUMNS)
                )
            if bundle.cr9:
                cr9_display = _cr9_display_names(bundle.cr9)
                total_rows += _write_dict_sheets(
                    workbook, bundle.cr9, f"{prefix} CR9", cr9_display, column_name_map(CR9_COLUMNS)
                )
            subtemplates = get_cr10_subtemplates(framework)
            total_rows += _write_dict_sheets(
                workbook,
                bundle.cr10,
                f"{prefix} CR10",
                subtemplates,
                column_name_map(get_cr10_columns(framework)),
            )
            if bundle.cms1 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cms1, f"{prefix} CMS1", column_name_map(CMS1_COLUMNS)
                )
            if bundle.cms2 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.cms2, f"{prefix} CMS2", column_name_map(CMS2_COLUMNS)
                )
            if bundle.ccr1 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.ccr1, f"{prefix} CCR1", column_name_map(CCR1_COLUMNS)
                )
            if bundle.ccr2 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.ccr2, f"{prefix} CCR2", column_name_map(CCR2_COLUMNS)
                )
            if bundle.ccr3 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.ccr3, f"{prefix} CCR3", column_name_map(CCR3_COLUMNS)
                )
            if bundle.ccr8 is not None:
                total_rows += _write_single_sheet(
                    workbook, bundle.ccr8, f"{prefix} CCR8", column_name_map(CCR8_COLUMNS)
                )
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
        """Generate the OV1 overview of RWEAs.

        Dispatch-router entry (Phase 7 S8): OV1 is declarative — the cell
        semantics live in ``pillar3/ov1.py::build_ov1_spec`` and run through
        the one ``cellspec.execute`` executor.

        References:
            CRR Part 8 Art. 438; PRA PS1/26 Annex XX.
        """
        return generate_ov1(results, cols, framework, errors, capital_ratios, output_floor_summary)

    # ---- CR4 ----

    def _generate_cr4(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CR4 SA exposure-and-CRM-effects template.

        Dispatch-router entry (Phase 7 S8): CR4 is declarative — the cell
        semantics live in ``pillar3/cr4.py::build_cr4_spec`` (incl. the
        recorded F3 class-basis split) and run through the one
        ``cellspec.execute`` executor.

        References:
            CRR Art. 444(e); PRA PS1/26 Annex XX.
        """
        return generate_cr4(results, cols, framework, errors)

    # ---- CR5 ----

    def _generate_cr5(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CR5 SA risk-weight allocation template.

        Dispatch-router entry (Phase 7 S8): CR5 is declarative — the cell
        semantics live in ``pillar3/cr5.py::build_cr5_spec`` (post-
        substitution class rows, Art. 123B pre-multiplier banding) and run
        through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 444(e); PRA PS1/26 Annex XX.
        """
        return generate_cr5(results, cols, framework, errors)

    # ---- CR6 ----

    def _generate_all_cr6(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class CR6 IRB by-PD-range templates.

        Dispatch-router entry (Phase 7 S8): CR6 is declarative — the cell
        semantics live in ``pillar3/cr6.py::build_cr6_spec`` (obligor-class
        sheets, regime PD-allocation split, defaulted 100%-band landing)
        and run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 452(g); PRA PS1/26 Annex XXII.
        """
        return generate_cr6(results, cols, framework, errors)

    # ---- CR6-A ----

    def _generate_cr6a(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CR6-A scope-of-IRB-use template.

        Dispatch-router entry (Phase 7 S8): CR6-A is declarative — the cell
        semantics live in ``pillar3/cr6a.py::build_cr6a_spec`` (origination-
        class rows, IRB/SA percentage formulas) and run through the one
        ``cellspec.execute`` executor.

        References:
            CRR Art. 452(b); PRA PS1/26 Annex XXII.
        """
        return generate_cr6a(results, cols, framework, errors)

    # ---- CR7 ----

    def _generate_cr7(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CR7 credit-derivatives-effect template.

        Dispatch-router entry (Phase 7 S8): CR7 is declarative — the cell
        semantics live in ``pillar3/cr7.py::build_cr7_spec`` (origin
        approach x obligor-class rows; a == b recorded approximation) and
        run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 453(j); PRA PS1/26 Annex XXII.
        """
        return generate_cr7(results, cols, framework, errors)

    # ---- CR7-A ----

    def _generate_all_cr7a(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-approach CR7-A extent-of-CRM templates.

        Dispatch-router entry (Phase 7 S8): CR7-A is declarative — the cell
        semantics live in ``pillar3/cr7a.py::build_cr7a_spec`` (obligor-class
        rows, FCP/UFCP percentage ratios, m == n recorded approximation)
        and run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 453(g); PRA PS1/26 Annex XXII.
        """
        return generate_cr7a(results, cols, framework, errors)

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

        Dispatch-router entry (Phase 7 S7): CR8 is declarative — the cell
        semantics live in ``pillar3/cr8.py::CR8_SPEC`` and run through the one
        ``cellspec.execute`` executor. This method only routes the pre-filtered
        IRB (non-slotting) subset and the prior-period frame.

        References:
            CRR Part 8 Art. 438(h); PRA PS1/26 Annex XXII §11.
        """
        return generate_cr8(irb_data, prior_irb_data, cols, errors)

    # ---- CR9 — PD back-testing per exposure class (Art. 452(h)) ----

    @cites("PS1/26, paragraph 147.2")
    def _generate_all_cr9(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class CR9 PD back-testing templates (Basel 3.1).

        Dispatch-router entry (Phase 7 S8): CR9 is declarative — the cell
        semantics live in ``pillar3/cr9.py::generate_cr9`` (obligor-basis
        leaf-class sheets, sparse PD-band rows, point-in-time proxy columns)
        and run through the one ``cellspec.execute`` executor.

        References:
            PRA PS1/26 Art. 452(h), Annex XXII paras 12-15.
        """
        return generate_cr9(results, cols, framework, errors)

    # ---- CR9.1 ----

    @cites("PS1/26, paragraph 147.2")
    def _generate_cr9_1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-class CR9.1 ECAI back-testing templates (Basel 3.1).

        Dispatch-router entry (Phase 7 S8): CR9.1 is declarative — the cell
        semantics live in ``pillar3/cr9.py::generate_cr9_1`` (ECAI-grade row
        axis over the Art. 180(1)(f) scoped population; empty on the real
        pipeline — the recorded S1 accept-empty decision).

        References:
            PRA PS1/26 Art. 452(h), Art. 180(1)(f), Annex XXII paras 12-15.
        """
        return generate_cr9_1(results, cols, framework, errors)

    # ---- CR10 ----

    def _generate_all_cr10(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> dict[str, pl.DataFrame]:
        """Generate the per-sl_type CR10 slotting templates.

        Dispatch-router entry (Phase 7 S8): CR10 is declarative — the cell
        semantics live in ``pillar3/cr10.py::generate_cr10`` (supervisory-
        category rows, fixed Art. 153(5) risk-weight column, the CRR
        IPRE+HVCRE merge and equity force-emit).

        References:
            CRR Art. 438(e); PRA PS1/26 Annex XXIV.
        """
        return generate_cr10(results, cols, framework, errors)

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

    # ---- CCR1 — Analysis of CCR exposure by approach (Art. 439(f)) ----

    def _generate_ccr1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR1 SA-CCR analysis-by-approach table.

        The SA-CCR row (and the Total row) carry the portfolio CCR EAD
        (Σ ``ead_final`` over the synthetic ``ccr__`` netting-set rows;
        CRR Art. 274(2)) in column ``a`` and the non-QCCP default-risk RWEA
        (Σ ``rwa_final`` over the ``ccr__`` rows that are NOT QCCP trade legs;
        CRR Art. 107(2)(a)) in column ``f``. Both re-derive exactly the
        AggregatedResultBundle ``ead_ccr_total`` / ``rwa_ccr_default`` roll-ups.
        Returns ``None`` when the portfolio carries no CCR rows.

        References:
            CRR Art. 439(f); Art. 274(2); Art. 107(2)(a).
        """
        ccr_rows = _ccr_rows(results, cols)
        if ccr_rows is None or ccr_rows.height == 0:
            return None

        column_refs = [c.ref for c in CCR1_COLUMNS]
        ead_total = _col_sum(ccr_rows, "ead_final")
        rwea_default = _ccr_rwa(ccr_rows, qccp_trade=False)

        rows_out: list[dict[str, object]] = []
        for row_def in CCR1_ROWS:
            if row_def.ref in ("1", "11"):
                # SA-CCR approach row and Total — both the single SA-CCR phase.
                # Col a = EAD post-CRM, col b = non-QCCP default-risk RWEA.
                values: dict[str, object] = {"a": ead_total, "b": rwea_default}
            else:
                values = {"a": None, "b": None}
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CCR2 — CVA capital charge (Art. 439(h)) ----

    def _generate_ccr2(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR2 BA-CVA capital-charge table.

        Reads the portfolio RWEA_CVA from the ``cva_rwa`` broadcast
        column the aggregation stage stamps on the results frame (the BA-CVA
        charge is a standalone scalar, not an EAD-derived per-row figure). The
        BA-CVA row and the Total row carry that RWEA in column ``b``. Returns
        ``None`` when no CVA charge is present (CRR, or a portfolio with no
        in-scope CVA counterparties).

        References:
            CRR Art. 439(h); PS1/26 CVA Part 4.2-4.4 (BA-CVA reduced/full);
            Own Funds Part 4(b) (x12.5 RWEA multiplier).
        """
        cva_col = _pick(cols, "cva_rwa")
        if not cva_col:
            return None
        cva_rwea = _first_non_null(results, cva_col)
        if cva_rwea is None:
            return None

        column_refs = [c.ref for c in CCR2_COLUMNS]
        rows_out: list[dict[str, object]] = []
        for row_def in CCR2_ROWS:
            if row_def.ref in ("4", "6"):
                # BA-CVA row and Total — the single BA-CVA charge (col a = RWEA).
                values: dict[str, object] = {"a": cva_rwea}
            else:
                values = {"a": None}
            rows_out.append(_make_row(row_def, values, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CCR3 — SA-CCR EAD by risk-weight band (Art. 444(e)) ----

    def _generate_ccr3(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR3 SA-CCR-EAD-by-risk-weight-band table.

        One row per SA risk-weight band: each band row's EAD cell (col ``a``)
        sums ``ead_final`` over the ``ccr__`` rows whose ``risk_weight`` matches
        the band rate; unmatched rows fall to the "Other" row; the Total row
        re-derives ``ead_ccr_total``. Returns ``None`` when no CCR rows exist.

        References:
            CRR Art. 444(e); Art. 120(1) Table 3 (institution CQS bands).
        """
        ccr_rows = _ccr_rows(results, cols)
        if ccr_rows is None or ccr_rows.height == 0:
            return None
        if "risk_weight" not in ccr_rows.columns:
            errors.append("CCR3: missing risk_weight column")
            return None

        rw_bands = get_ccr3_risk_weights(framework)
        column_refs = [c.ref for c in CCR3_COLUMNS]
        band_eads = _ccr3_band_eads(ccr_rows, rw_bands)

        rows_out: list[dict[str, object]] = []
        for i, row_def in enumerate(get_ccr3_rows(framework)):
            ead = _col_sum(ccr_rows, "ead_final") if row_def.is_total else band_eads[i] or None
            rows_out.append(_make_row(row_def, {"a": ead}, column_refs))

        return _build_df(rows_out, column_refs)

    # ---- CCR8 — Exposures to central counterparties (Art. 439(i)) ----

    def _generate_ccr8(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR8 QCCP-vs-non-QCCP CCP-exposures table.

        Partitions the ``ccr__`` rows by the QCCP trade-leg discriminator
        (``cp_entity_type == "ccp"`` AND ``cp_is_qccp.fill_null(True)``, mirror
        of the aggregator). The QCCP row carries the QCCP trade-leg RWEA
        (``rwa_ccr_qccp_trade``; CRR Art. 306(1)/(4)); the non-QCCP row carries
        the default-risk RWEA (``rwa_ccr_default``) — null when all rows are
        QCCP. Returns ``None`` when no CCR rows exist.

        References:
            CRR Art. 439(i); Art. 306(1)(a) (2% QCCP proprietary trade RW).
        """
        ccr_rows = _ccr_rows(results, cols)
        if ccr_rows is None or ccr_rows.height == 0:
            return None

        column_refs = [c.ref for c in CCR8_COLUMNS]
        has_disc = {"cp_entity_type", "cp_is_qccp"} <= set(ccr_rows.columns)

        qccp_ead = _ccr_ead(ccr_rows, qccp_trade=True) if has_disc else None
        qccp_rwea = _ccr_rwa(ccr_rows, qccp_trade=True) if has_disc else None
        non_qccp_ead = _ccr_ead(ccr_rows, qccp_trade=False) if has_disc else None
        non_qccp_rwea = _ccr_rwa(ccr_rows, qccp_trade=False) if has_disc else None
        total_ead = _col_sum(ccr_rows, "ead_final")
        total_rwea = _col_sum(ccr_rows, "rwa_final")

        # Col a = RWEA (the disclosure's primary CCP figure), col b = EAD.
        per_ref: dict[str, dict[str, object]] = {
            "1": {"a": qccp_rwea, "b": qccp_ead},
            "2": {"a": non_qccp_rwea, "b": non_qccp_ead},
            "21": {"a": total_rwea, "b": total_ead},
        }
        rows_out = [
            _make_row(row_def, per_ref.get(row_def.ref, {}), column_refs) for row_def in CCR8_ROWS
        ]
        return _build_df(rows_out, column_refs)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _ccr_rows(results: pl.LazyFrame, cols: set[str]) -> pl.DataFrame | None:
    """Collect the synthetic ``ccr__``-prefixed CCR rows, or None if absent.

    The CCR disclosure tables read the same synthetic netting-set rows the
    aggregator rolls up (CRR Art. 274(2)). Returns ``None`` when the results
    frame carries no ``exposure_reference`` column.

    FCCM SFT rows (``risk_type == "CCR_SFT"``) share the ``ccr__`` prefix but are
    EXCLUDED here: they are SFT exposures reported under the SA template (COREP
    C 07.00 row 0090), not the SA-CCR / CCP disclosure tables (CCR1/CCR8). Only
    OTC derivatives and CCP exposures belong in these CCR templates. The
    exclusion is gated on ``risk_type`` being present so a portfolio that
    predates the column is unaffected.
    """
    ref_col = _pick(cols, "exposure_reference")
    if not ref_col:
        return None
    # An empty / all-null results frame can carry exposure_reference as a Null
    # dtype; ``.str.starts_with`` only operates on String. Cast defensively so
    # the CCR filter degenerates to an empty selection rather than raising.
    is_ccr = pl.col(ref_col).cast(pl.String).str.starts_with("ccr__")
    not_sft = pl.col("risk_type") != "CCR_SFT" if "risk_type" in cols else pl.lit(True)
    return results.filter(is_ccr & not_sft).collect()


def _ccr_qccp_trade_predicate() -> pl.Expr:
    """QCCP trade-leg discriminator — mirrors the aggregator partition exactly.

    ``(cp_entity_type == "ccp") & cp_is_qccp.fill_null(True)`` (CRR Art. 306).
    """
    return (pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(True)


def _ccr_rwa(ccr_rows: pl.DataFrame, *, qccp_trade: bool) -> float | None:
    """Sum ``rwa_final`` over the QCCP (or non-QCCP) ``ccr__`` partition.

    Mirrors the aggregator roll-ups: a zero partition total maps to ``None``
    (``rwa_ccr_default`` / ``rwa_ccr_qccp_trade`` are None when the partition
    is empty).
    """
    if not {"cp_entity_type", "cp_is_qccp", "rwa_final"} <= set(ccr_rows.columns):
        return None
    predicate = _ccr_qccp_trade_predicate()
    partition = ccr_rows.filter(predicate if qccp_trade else ~predicate)
    total = _col_sum(partition, "rwa_final")
    return total if total else None


def _ccr_ead(ccr_rows: pl.DataFrame, *, qccp_trade: bool) -> float | None:
    """Sum ``ead_final`` over the QCCP (or non-QCCP) ``ccr__`` partition."""
    if not {"cp_entity_type", "cp_is_qccp", "ead_final"} <= set(ccr_rows.columns):
        return None
    predicate = _ccr_qccp_trade_predicate()
    partition = ccr_rows.filter(predicate if qccp_trade else ~predicate)
    total = _col_sum(partition, "ead_final")
    return total if total else None


def _ccr3_band_eads(
    ccr_rows: pl.DataFrame,
    rw_bands: list[tuple[float, str]],
) -> list[float]:
    """Per-band CCR EAD totals plus a trailing "Other" total.

    Returns a list aligned with the CCR3 band rows: one entry per risk-weight
    band (``ead_final`` summed over ``ccr__`` rows whose ``risk_weight`` matches
    the band rate within a small tolerance) followed by the "Other" catch-all
    (rows whose risk_weight matched no band). The Total row is computed by the
    caller from the un-partitioned frame.
    """
    band_eads: list[float] = []
    matched_mask = pl.lit(False)
    for rate, _label in rw_bands:
        in_band = (pl.col("risk_weight") >= rate - 0.005) & (pl.col("risk_weight") <= rate + 0.005)
        matched_mask = matched_mask | in_band
        band = ccr_rows.filter(in_band)
        band_eads.append(_col_sum(band, "ead_final") or 0.0)

    unmatched = ccr_rows.filter(~matched_mask)
    band_eads.append(_col_sum(unmatched, "ead_final") or 0.0)
    return band_eads


def _first_non_null(results: pl.LazyFrame, col_name: str) -> float | None:
    """First non-null value of a broadcast scalar column, as a float."""
    data = results.select(pl.col(col_name).drop_nulls().first()).collect()
    if data.height == 0:
        return None
    value = data.item()
    return float(value) if value is not None else None


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


# ---------------------------------------------------------------------------
# CR7 row helpers
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


# ---------------------------------------------------------------------------
# Excel sheet-writing helpers
# ---------------------------------------------------------------------------


def _write_single_sheet(
    workbook: Workbook,
    df: pl.DataFrame,
    name: str,
    name_by_ref: Mapping[str, str],
) -> int:
    """Write a single DataFrame to a workbook sheet. Returns row count.

    The sheet carries a readable column-name banner above the disclosure ref
    codes (see ``kernel.write_template_sheet``).
    """
    return write_template_sheet(workbook, df, name, name_by_ref)


def _write_dict_sheets(
    workbook: Workbook,
    templates: dict[str, pl.DataFrame],
    prefix: str,
    display_names: dict[str, str],
    name_by_ref: Mapping[str, str],
) -> int:
    """Write per-class/type templates to workbook sheets. Returns total rows."""
    total = 0
    for key in sorted(templates):
        df = templates[key]
        if df.height == 0:
            continue
        display = display_names.get(key, key)
        total += write_template_sheet(workbook, df, f"{prefix} - {display}", name_by_ref)
    return total
