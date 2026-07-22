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
    column_name_map,
    write_metadata_sheet,
    write_template_sheet,
)
from rwa_calc.reporting.metadata import ResultsSource
from rwa_calc.reporting.pillar3.ccr import (
    generate_ccr1,
    generate_ccr2,
    generate_ccr3,
    generate_ccr8,
)
from rwa_calc.reporting.pillar3.cms1 import generate_cms1
from rwa_calc.reporting.pillar3.cms2 import generate_cms2
from rwa_calc.reporting.pillar3.cr4 import generate_cr4
from rwa_calc.reporting.pillar3.cr5 import generate_cr5
from rwa_calc.reporting.pillar3.cr6 import generate_cr6
from rwa_calc.reporting.pillar3.cr6a import generate_cr6a
from rwa_calc.reporting.pillar3.cr7 import generate_cr7
from rwa_calc.reporting.pillar3.cr7a import generate_cr7a
from rwa_calc.reporting.pillar3.cr8 import generate_cr8, irb_non_slotting_population
from rwa_calc.reporting.pillar3.cr9 import generate_cr9, generate_cr9_1
from rwa_calc.reporting.pillar3.cr10 import generate_cr10
from rwa_calc.reporting.pillar3.ov1 import generate_ov1
from rwa_calc.reporting.pillar3.templates import (
    CCR1_COLUMNS,
    CCR2_COLUMNS,
    CCR3_COLUMNS,
    CCR8_COLUMNS,
    CMS1_COLUMNS,
    CMS2_COLUMNS,
    CR6A_COLUMNS,
    CR7_COLUMNS,
    CR8_COLUMNS,
    CR9_APPROACH_DISPLAY,
    CR9_COLUMNS,
    IRB_EXPOSURE_CLASSES,
    OV1_COLUMNS,
    get_cr4_columns,
    get_cr5_columns,
    get_cr6_columns,
    get_cr7a_columns,
    get_cr10_columns,
    get_cr10_subtemplates,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xlsxwriter import Workbook

    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.results import ExportResult
    from rwa_calc.reporting.facts import FilingMetadata

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
        response: ResultsSource,
        *,
        previous_period_results: pl.LazyFrame | None = None,
    ) -> Pillar3TemplateBundle:
        """Generate all Pillar III templates from a results source (``ResultsSource``).

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

        irb_data = irb_non_slotting_population(results, cols)

        prior_irb_data: pl.LazyFrame | None = None
        if previous_period_results is not None:
            prior_cols = _available_columns(previous_period_results)
            prior_irb_data = irb_non_slotting_population(previous_period_results, prior_cols)

        return Pillar3TemplateBundle(
            ov1=self._generate_ov1(results, cols, framework, errors, output_floor_summary),
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
            cms2=self._generate_cms2(results, cols, framework, errors),
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
        *,
        metadata: FilingMetadata | None = None,
    ) -> ExportResult:
        """Write Pillar III templates to an Excel workbook.

        When *metadata* is supplied, an additional "metadata" sheet carries
        the run's filing context (reporting date, framework, entity
        identifier, run id, generator version) — see
        ``reporting/facts.py::FilingMetadata``.
        """
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
            _write_optional_metadata_sheet(workbook, metadata)
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
        output_floor_summary: OutputFloorSummary | None = None,
    ) -> pl.DataFrame | None:
        """Generate the OV1 overview of RWEAs.

        Dispatch-router entry (Phase 7 S8): OV1 is declarative — the cell
        semantics live in ``pillar3/ov1.py::build_ov1_spec`` and run through
        the one ``cellspec.execute`` executor.

        References:
            CRR Part 8 Art. 438; PRA PS1/26 Annex II.
        """
        return generate_ov1(results, cols, framework, errors, output_floor_summary)

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
        return _single_frame(generate_cr4(results, cols, framework, errors))

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
        return _single_frame(generate_cr5(results, cols, framework, errors))

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
        return _single_frame(generate_cr6a(results, cols, framework, errors))

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
        return _single_frame(generate_cr7(results, cols, framework, errors))

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
        """Generate the CMS1 by-risk-type output-floor comparison (Basel 3.1).

        Dispatch-router entry (Phase 7 S8): CMS1 is declarative — the cell
        semantics live in ``pillar3/cms1.py::build_cms1_spec`` (modelled vs
        the explicit standardised-side complement incl. equity) and run
        through the one ``cellspec.execute`` executor.

        References:
            PRA PS1/26 Art. 456(1)(a), Art. 2a(1).
        """
        return _single_frame(generate_cms1(results, cols, framework, errors))

    # ---- CMS2 ----

    def _generate_cms2(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CMS2 by-asset-class output-floor comparison (Basel 3.1).

        Dispatch-router entry (Phase 7 S8): CMS2 is declarative — the cell
        semantics live in ``pillar3/cms2.py::build_cms2_spec`` (origination-
        class rows; column c = the class's total actual RWA across ALL
        approaches, the recorded equity fix) and run through the one
        ``cellspec.execute`` executor.

        References:
            PRA PS1/26 Art. 456(1)(b), Art. 2a(2).
        """
        return _single_frame(generate_cms2(results, cols, framework, errors))

    @cites("CRR Art. 274")
    def _generate_ccr1(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR1 SA-CCR analysis-by-approach table.

        Dispatch-router entry (Phase 7 S8): CCR1 is declarative — the cell
        semantics live in ``pillar3/ccr.py::generate_ccr1`` (the SA-CCR / Total
        rows sum EAD col ``a`` over the ``ccr__`` netting-set population, FCCM
        SFTs excluded, and the non-QCCP default-risk RWEA col ``b`` over the
        derived ``ccr1_default_risk`` partition) and run through the one
        ``cellspec.execute`` executor.

        References:
            CRR Art. 439(f); Art. 274(2); Art. 107(2)(a).
        """
        return generate_ccr1(results, cols)

    # ---- CCR2 — CVA capital charge (Art. 439(h)) ----

    @cites("PS1/26, paragraph 4.2")
    def _generate_ccr2(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR2 BA-CVA capital-charge table.

        Dispatch-router entry (Phase 7 S8): CCR2 is declarative — the cell
        semantics live in ``pillar3/ccr.py::generate_ccr2`` (the BA-CVA / Total
        rows read the portfolio ``cva_rwa`` roll-up as a broadcast per-row
        constant via ``FirstNonNull`` — the C 34.04 idiom; presence-gated, so
        None under CRR) and run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 439(h); PS1/26 CVA Part 4.2-4.4 (BA-CVA reduced/full);
            Own Funds Part 4(b) (x12.5 RWEA multiplier).
        """
        return generate_ccr2(results, cols)

    # ---- CCR3 — SA-CCR EAD by risk-weight band (Art. 444(e)) ----

    @cites("CRR Art. 444")
    def _generate_ccr3(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        framework: str,
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR3 SA-CCR-EAD-by-risk-weight-band table.

        Dispatch-router entry (Phase 7 S8): CCR3 is declarative — the cell
        semantics live in ``pillar3/ccr.py::generate_ccr3`` (one band row per CR5
        risk-weight band keyed on the derived ``ccr3_band`` label, an "Other"
        catch-all, the Total row summing the whole SA-CCR population; a missing
        ``risk_weight`` column records the CCR3 error) and run through the one
        ``cellspec.execute`` executor.

        References:
            CRR Art. 444(e); Art. 120(1) Table 3 (institution CQS bands).
        """
        return generate_ccr3(results, cols, framework, errors)

    # ---- CCR8 — Exposures to central counterparties (Art. 439(i)) ----

    @cites("CRR Art. 306")
    def _generate_ccr8(
        self,
        results: pl.LazyFrame,
        cols: set[str],
        errors: list[str],
    ) -> pl.DataFrame | None:
        """Generate the CCR8 QCCP-vs-non-QCCP CCP-exposures table.

        Dispatch-router entry (Phase 7 S8): CCR8 is declarative — the cell
        semantics live in ``pillar3/ccr.py::generate_ccr8`` (the CCP population,
        ``include_sft=True`` per CRR Art. 301(1)(b), split by the derived
        ``ccr8_qccp`` flag into QCCP row ``1`` / non-QCCP row ``2`` / Total ``21``;
        the R5 CCP restriction keeps a bilateral counterparty out of every row)
        and run through the one ``cellspec.execute`` executor.

        References:
            CRR Art. 439(i); Art. 306(1)(a) (2% QCCP proprietary trade RW);
            Art. 301(1)(b) (SFTs within the CCP material scope).
        """
        return generate_ccr8(results, cols)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _single_frame(frames: dict[str, pl.DataFrame]) -> pl.DataFrame | None:
    """Unwrap a single-frame template's ``{key: frame}`` dict for the bundle field.

    The declarative single-frame Pillar 3 generators (cr4/cr5/cr6a/cr7, plus
    the Basel-3.1-only cms1/cms2) return the lineage-shaped
    ``{canonical key: frame}`` dict — the same key their ``<t>_plans`` uses, so
    ``reporting.lineage`` can read a cell's spec and its reported value under
    one key. The bundle field is a bare ``pl.DataFrame | None``, so the router
    takes the one frame (None when the error contract yielded no plan — and, for
    cms1/cms2, an empty dict under CRR).
    """
    return next(iter(frames.values()), None)


# ---------------------------------------------------------------------------
# CR7 row helpers
# ---------------------------------------------------------------------------
# CMS2 row helpers
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


def _write_optional_metadata_sheet(workbook: Workbook, metadata: FilingMetadata | None) -> None:
    """Write the "metadata" sheet when *metadata* is supplied; a no-op otherwise.

    Factored out of ``export_to_excel`` (SonarCloud cognitive-complexity gate,
    PR #442) so the one extra branch the metadata feature added lives here
    instead of lengthening that method's already-long flat if-chain.
    """
    if metadata is not None:
        write_metadata_sheet(workbook, metadata.as_sheet_fields())


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
