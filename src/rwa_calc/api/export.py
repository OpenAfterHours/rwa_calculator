"""
Result export utilities for RWA Calculator.

Pipeline position:
    CalculationResponse -> ResultExporter -> Parquet / CSV / Excel / COREP / Pillar III

Key responsibilities:
- Export calculation results to Parquet files (one per dataset)
- Export calculation results to CSV files (one per dataset)
- Export calculation results to multi-sheet Excel workbooks
- Generate COREP regulatory reporting templates (C 07.00, C 08.01, C 08.02)
- Generate Pillar III quantitative disclosure templates (OV1, CR4-CR10, CMS1/2, CCR1-8)
- Run the published supervisory validation rules over a run's generated estate
  and answer, in one field, whether the return can be submitted
- Provide a unified export interface regardless of output format

The exporter reads from cached parquet files via CalculationResponse's
lazy scan accessors, so no redundant in-memory materialisation occurs.
"""

from __future__ import annotations

import json
import logging
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl

from rwa_calc.contracts.results import ExportResult

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.api.models import (
        CalculationResponse,
        ComparisonExportResponse,
        ReconciliationResponse,
    )
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import OutputFloorConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.facts import FilingMetadata
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle
    from rwa_calc.reporting.validations import CoverageShortfall, RuleOutcome

logger = logging.getLogger(__name__)


# =============================================================================
# Export Result
# =============================================================================

# ExportResult moved to rwa_calc.contracts.results (layering: contracts and
# reporting must not import api). Re-exported here for backwards compatibility.
__all__ = [
    "ExportResult",
    "ResultExporter",
    "SubmissionValidationResult",
    "summarise_validation",
]


# =============================================================================
# Result Exporter
# =============================================================================


class ResultExporter:
    """
    Exports RWA calculation results to various file formats.

    Reads from CalculationResponse's cached parquet files and writes
    to the requested output format. Supports multi-dataset exports
    (results, summary by class, summary by approach).

    Usage:
        exporter = ResultExporter()
        result = exporter.export_to_parquet(response, Path("output/"))
        result = exporter.export_to_csv(response, Path("output/"))
        result = exporter.export_to_excel(response, Path("output/results.xlsx"))
    """

    def export_to_parquet(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to Parquet files in the given directory.

        Creates one file per dataset: results.parquet, summary_by_class.parquet,
        summary_by_approach.parquet.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write parquet files into

        Returns:
            ExportResult with list of written files and total row count
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0

        # Main results
        results_df = response.scan_results().collect()
        results_path = output_dir / "results.parquet"
        results_df.write_parquet(results_path)
        files.append(results_path)
        total_rows += len(results_df)

        # Summary by class
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()
            class_path = output_dir / "summary_by_class.parquet"
            class_df.write_parquet(class_path)
            files.append(class_path)

        # Summary by approach
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()
            approach_path = output_dir / "summary_by_approach.parquet"
            approach_df.write_parquet(approach_path)
            files.append(approach_path)

        return ExportResult(format="parquet", files=files, row_count=total_rows)

    def export_to_csv(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to CSV files in the given directory.

        Creates one file per dataset: results.csv, summary_by_class.csv,
        summary_by_approach.csv.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write CSV files into

        Returns:
            ExportResult with list of written files and total row count
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0

        # Main results (nested columns JSON-encoded so CSV can hold them).
        results_df = response.scan_results().collect()
        results_path = output_dir / "results.csv"
        _csv_safe(results_df).write_csv(results_path)
        files.append(results_path)
        total_rows += len(results_df)

        # Summary by class
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()
            class_path = output_dir / "summary_by_class.csv"
            _csv_safe(class_df).write_csv(class_path)
            files.append(class_path)

        # Summary by approach
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()
            approach_path = output_dir / "summary_by_approach.csv"
            _csv_safe(approach_df).write_csv(approach_path)
            files.append(approach_path)

        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_to_excel(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """
        Export results to a multi-sheet Excel workbook.

        Creates sheets: "Results", "Summary by Class", "Summary by Approach".
        Requires the xlsxwriter package (Polars dependency for write_excel).

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_rows = 0

        # Collect all datasets
        results_df = response.scan_results().collect()
        total_rows += len(results_df)

        class_df: pl.DataFrame | None = None
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()

        approach_df: pl.DataFrame | None = None
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()

        # Write to Excel with multiple sheets using xlsxwriter workbook
        import xlsxwriter as xw

        workbook = xw.Workbook(str(output_path))
        try:
            # Write main results sheet
            results_df.write_excel(
                workbook=workbook,
                worksheet="Results",
                autofit=True,
            )

            # Write summary by class sheet
            if class_df is not None and len(class_df) > 0:
                class_df.write_excel(
                    workbook=workbook,
                    worksheet="Summary by Class",
                    autofit=True,
                )

            # Write summary by approach sheet
            if approach_df is not None and len(approach_df) > 0:
                approach_df.write_excel(
                    workbook=workbook,
                    worksheet="Summary by Approach",
                    autofit=True,
                )
        finally:
            workbook.close()

        return ExportResult(
            format="excel",
            files=[output_path],
            row_count=total_rows,
        )

    def export_to_corep(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        output_floor_config: OutputFloorConfig | None = None,
        metadata: FilingMetadata | None = None,
        previous_period_results: pl.LazyFrame | None = None,
    ) -> ExportResult:
        """
        Export results as COREP regulatory reporting templates.

        Generates C 07.00 (SA credit risk), C 08.01 (IRB totals),
        and C 08.02 (IRB PD grade breakdown) in a multi-sheet Excel
        workbook following EBA/PRA COREP template structure.

        Why: CRR firms must submit quarterly COREP returns to the PRA.
        This reshapes the calculator's exposure-level results into the
        fixed-format regulatory templates (Regulation (EU) 2021/451).

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file
            output_floor_config: Optional floor config for reporting
                basis conditionality (Art. 92 para 2A). Gates floor
                indicators and materiality columns on entity type.
            metadata: Optional filing metadata — stamped as a "metadata"
                sheet in the workbook (``reporting/facts.py::FilingMetadata``).
            previous_period_results: Optional prior-period results LazyFrame
                (same sealed shape as the current results — a persisted
                results parquet scan, never a hand-built frame), threaded
                straight through to ``COREPGenerator.generate``. Populates
                C 08.04's RWEA flow opening balance (row 0010) and signed
                residual (row 0080); ``None`` (default) leaves those rows null.

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.reporting.corep.generator import COREPGenerator

        generator = COREPGenerator()
        bundle = generator.generate(
            response,
            output_floor_config=output_floor_config,
            previous_period_results=previous_period_results,
        )
        return generator.export_to_excel(bundle, output_path, metadata=metadata)

    def export_to_pillar3(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        metadata: FilingMetadata | None = None,
        previous_period_results: pl.LazyFrame | None = None,
        output_floor_summary: OutputFloorSummary | None = None,
    ) -> ExportResult:
        """Export results as Pillar III public disclosure templates.

        ``metadata``, when supplied, is stamped as a "metadata" sheet in the
        workbook (``reporting/facts.py::FilingMetadata``). ``previous_period_results``
        and ``output_floor_summary`` are threaded straight through to
        ``Pillar3Generator.generate_from_lazyframe`` — they populate CR8's RWEA
        flow rows and OV1's output-floor rows; both default to ``None`` (unchanged
        behaviour) when the caller supplies nothing.
        """
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        generator = Pillar3Generator()
        bundle = generator.generate_from_lazyframe(
            response.scan_results(),
            framework=response.framework,
            output_floor_summary=output_floor_summary,
            previous_period_results=previous_period_results,
        )
        return generator.export_to_excel(bundle, output_path, metadata=metadata)

    # -- cell facts -----------------------------------------------------------

    def export_corep_facts(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        fmt: Literal["parquet", "ndjson"] = "parquet",
        output_floor_config: OutputFloorConfig | None = None,
        metadata: FilingMetadata | None = None,
        previous_period_results: pl.LazyFrame | None = None,
    ) -> ExportResult:
        """Export COREP as a flat, keyed cell-fact feed (parquet or ndjson).

        One row per populated ``(template_id, sheet, row_ref, col_ref)`` cell
        — the shape a vendor filing tool maps against, rather than a
        merged-header spreadsheet. See ``reporting/facts.py`` for the fact
        schema and null/sign conventions.

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the output file
            fmt: "parquet" (default) or "ndjson"
            output_floor_config: Optional floor config, as ``export_to_corep``
            metadata: Optional filing metadata, stamped as constant columns
            previous_period_results: Optional prior-period results LazyFrame,
                as ``export_to_corep`` — populates C 08.04's opening/residual
                RWEA-flow rows.

        Returns:
            ExportResult with the written file path and fact-row count
        """
        from rwa_calc.reporting.corep.generator import COREPGenerator
        from rwa_calc.reporting.facts import build_fact_frame

        generator = COREPGenerator()
        bundle = generator.generate(
            response,
            output_floor_config=output_floor_config,
            previous_period_results=previous_period_results,
        )
        frame = build_fact_frame(bundle, None, metadata=metadata)
        return _write_fact_frame(frame, output_path, fmt, "corep_facts")

    def export_pillar3_facts(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        fmt: Literal["parquet", "ndjson"] = "parquet",
        metadata: FilingMetadata | None = None,
        previous_period_results: pl.LazyFrame | None = None,
        output_floor_summary: OutputFloorSummary | None = None,
    ) -> ExportResult:
        """Export Pillar III as a flat, keyed cell-fact feed (parquet or ndjson).

        See ``export_corep_facts`` for the fact shape; this is the same
        traversal over the Pillar III bundle instead of COREP.
        ``previous_period_results`` / ``output_floor_summary`` are threaded
        through as in ``export_to_pillar3``.
        """
        from rwa_calc.reporting.facts import build_fact_frame
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        generator = Pillar3Generator()
        bundle = generator.generate_from_lazyframe(
            response.scan_results(),
            framework=response.framework,
            output_floor_summary=output_floor_summary,
            previous_period_results=previous_period_results,
        )
        frame = build_fact_frame(None, bundle, metadata=metadata)
        return _write_fact_frame(frame, output_path, fmt, "pillar3_facts")

    # -- submission validation ------------------------------------------------

    def validate_submission(
        self,
        response: CalculationResponse,
        *,
        output_floor_config: OutputFloorConfig | None = None,
        previous_period_results: pl.LazyFrame | None = None,
        output_floor_summary: OutputFloorSummary | None = None,
    ) -> SubmissionValidationResult:
        """Run the supervisors' own validation rules over this run's estate.

        Generates the COREP and Pillar III bundles exactly as ``export_to_corep``
        / ``export_to_pillar3`` do, then evaluates every currently-enforced
        published rule for the run's framework (EBA for CRR, BoE for Basel 3.1)
        against them.

        Why this is the gate: an Error-severity break REJECTS the whole return at
        the supervisor's door — every template in the submission is blocked, not
        just the one that broke. ``SubmissionValidationResult.is_submittable``
        answers that in one field.

        Nothing here raises for a broken rule: a break is an expected business
        outcome, accumulated onto the result (and onto ``result.errors`` as
        ``VAL001`` / ``VAL002`` / ``VAL003`` findings) like every other
        data-quality finding.

        Args:
            response: CalculationResponse with cached results. Its ``framework``
                selects the rule catalogue.
            output_floor_config: Optional floor config, as ``export_to_corep`` —
                it gates C 02.00's floor rows, which several rules address.
            previous_period_results: Optional prior-period results LazyFrame,
                as ``export_to_corep`` / ``export_to_pillar3``.
            output_floor_summary: Optional floor summary for the Pillar III
                bundle, as ``export_to_pillar3``.

        Returns:
            A ``SubmissionValidationResult``: counts by outcome, the blocking
            (Error) breaks, the warnings, and the not-evaluated set with reasons.
        """
        from rwa_calc.reporting.corep.generator import COREPGenerator
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        corep = COREPGenerator().generate(
            response,
            output_floor_config=output_floor_config,
            previous_period_results=previous_period_results,
        )
        pillar3 = Pillar3Generator().generate_from_lazyframe(
            response.scan_results(),
            framework=response.framework,
            output_floor_summary=output_floor_summary,
            previous_period_results=previous_period_results,
        )
        return summarise_validation(corep, pillar3, response.framework)

    def export_validation_report(
        self,
        result: SubmissionValidationResult,
        output_path: Path,
        *,
        fmt: Literal["csv", "parquet", "ndjson"] = "csv",
    ) -> ExportResult:
        """Export a ``validate_submission`` result as a flat, keyed rule-outcome feed.

        One row per enforced rule — rule id, severity, status, the coordinate the
        first recorded break sits at, both figures, and the reason anything was
        not evaluated. This is the artefact a filer reviews (and files with the
        submission pack) before pressing send.

        Takes the *result* rather than the response, mirroring
        ``export_reconciliation_to_csv``: generating both template bundles is the
        expensive half of ``validate_submission``, so a caller that has already
        asked "can I submit?" must not pay for it twice to write the answer down.

        Args:
            result: The ``validate_submission`` result to write.
            output_path: Path for the output file.
            fmt: "csv" (default — the reviewable form), "parquet" or "ndjson".

        Returns:
            ExportResult with the written file path and one row per enforced rule.
        """
        return _write_fact_frame(
            _validation_report_frame(result), output_path, fmt, "validation_report"
        )

    # -- reconciliation -----------------------------------------------------

    def export_reconciliation_to_csv(
        self,
        response: ReconciliationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each reconciliation frame to its own CSV file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _reconciliation_frames(response):
            path = output_dir / f"reconciliation_{name}.csv"
            _csv_safe(df).write_csv(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_reconciliation_to_excel(
        self,
        response: ReconciliationResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export the reconciliation to a multi-sheet Excel workbook.

        Sheets: By Component, Totals Tie-Out, Class Allocation, Class Alloc by Method,
        Reconciliation, Breaks, By Class, By Approach, Errors. Requires xlsxwriter.
        Empty frames are skipped, so the by-method sheet is absent when the ``approach``
        component is unmapped.

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed.
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        import xlsxwriter as xw

        # Friendly sheet titles in report order (headline -> forensic).
        sheet_titles = {
            "summary_by_component": "By Component",
            "totals_tie_out": "Totals Tie-Out",
            "class_allocation": "Class Allocation",
            "class_allocation_by_method": "Class Alloc by Method",
            "summary_by_bucket": "By Bucket",
            "summary_by_exposure_class": "By Class",
            "summary_by_approach": "By Approach",
            "breaks_detail": "Breaks",
            "component_reconciliation": "Reconciliation",
        }
        total_rows = 0
        workbook = xw.Workbook(str(output_path))
        try:
            for name, df in _reconciliation_frames(response):
                if len(df) == 0:
                    continue
                df.write_excel(
                    workbook=workbook,
                    worksheet=sheet_titles.get(name, name)[:31],
                    autofit=True,
                )
                total_rows += len(df)
            errors_df = _reconciliation_errors_frame(response)
            if len(errors_df) > 0:
                errors_df.write_excel(workbook=workbook, worksheet="Errors", autofit=True)
        finally:
            workbook.close()
        return ExportResult(format="excel", files=[output_path], row_count=total_rows)

    # -- comparison ---------------------------------------------------------

    def export_comparison_to_csv(
        self,
        response: ComparisonExportResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each comparison frame to its own CSV file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _comparison_frames(response):
            path = output_dir / f"comparison_{name}.csv"
            _csv_safe(df).write_csv(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_comparison_to_parquet(
        self,
        response: ComparisonExportResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each comparison frame to its own Parquet file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _comparison_frames(response):
            path = output_dir / f"comparison_{name}.parquet"
            df.write_parquet(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="parquet", files=files, row_count=total_rows)

    def export_comparison_to_excel(
        self,
        response: ComparisonExportResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export the comparison to a multi-sheet Excel workbook.

        Sheets: Executive Summary, By Class, By Approach, Capital Impact Waterfall,
        Exposure Deltas, Driver Attribution, Errors. Requires xlsxwriter.

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed.
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        import xlsxwriter as xw

        # Friendly sheet titles in report order (headline -> per-exposure detail).
        sheet_titles = {
            "executive_summary": "Executive Summary",
            "summary_by_class": "By Class",
            "summary_by_approach": "By Approach",
            "waterfall": "Capital Impact Waterfall",
            "exposure_deltas": "Exposure Deltas",
            "exposure_attribution": "Driver Attribution",
        }
        total_rows = 0
        workbook = xw.Workbook(str(output_path))
        try:
            for name, df in _comparison_frames(response):
                if len(df) == 0:
                    continue
                df.write_excel(
                    workbook=workbook,
                    worksheet=sheet_titles.get(name, name)[:31],
                    autofit=True,
                )
                total_rows += len(df)
            errors_df = _comparison_errors_frame(response)
            if len(errors_df) > 0:
                errors_df.write_excel(workbook=workbook, worksheet="Errors", autofit=True)
        finally:
            workbook.close()
        return ExportResult(format="excel", files=[output_path], row_count=total_rows)


# =============================================================================
# Submission validation
# =============================================================================


@dataclass(frozen=True)
class SubmissionValidationResult:
    """The pre-submission verdict on one run's generated regulatory estate.

    Produced by ``ResultExporter.validate_submission``; written to disk by
    ``ResultExporter.export_validation_report``.

    The headline question is ``is_submittable``. It takes TWO things, and both
    are needed for the answer to mean anything:

    - no Error-severity published rule is broken, because a single Error break
      rejects the entire return — every template in the submission, not just the
      one that broke (warnings do not block: the return is accepted and the firm
      is expected to explain the flagged figure); and
    - the estate was actually checked — ``coverage_shortfall`` is not
      ``no_rule_executed``. Without that limb the gate FAILS OPEN: an estate on
      which NOTHING ran reports zero breaks, and a caller writing the obvious
      ``if not errors: submit()`` would file a return nothing checked. That is
      the flattering answer, not the true one, and it manufactures confidence
      exactly where there is least basis for it.

    Only the FIRST coverage limb blocks. ``template_not_covered`` — an emitted
    template no rule reached — is reported, never blocked on: today it is a
    standing limitation (the C 34.x templates are stubs no rule can resolve a
    reference against), and blocking on it would reject correct returns on every
    CCR filing. A control that cries wolf on a known gap stops being believed.
    The test ratchet holds that limb instead, so a NEW coverage hole fails CI
    while a standing one does not block a valid submission. Not blocking is not
    the same as not telling the filer: ``templates_uncovered`` is on the result,
    in ``headline()`` and on every row of the exported report.

    The coverage predicate is NOT re-implemented here. It has one home —
    ``ValidationReport.coverage_shortfall`` — which ``VAL003`` is also built
    from, so the finding, the report and this verdict cannot drift apart. This
    layer consumes it and decides which limb blocks.

    Every count is reported against its denominator for the same reason. "0
    blocking breaks" is the figure that misleads; "0 blocking out of 224
    executed, 484 not evaluable" is the one a filer can act on.

    A ``NOT_EVALUATED`` rule is neither a pass nor a break. It addresses a
    template, sheet, row or column this run never emitted, or uses a construct
    the evaluator refuses to approximate — so it carries no evidence either way,
    and it is counted separately rather than flattering the pass rate. A
    ``VACUOUS`` rule held only because every operand was null or zero, which is
    likewise no evidence of correctness.

    Attributes:
        framework: ``"CRR"`` or ``"BASEL_3_1"``.
        publisher: ``"EBA"`` or ``"BoE"`` — whose catalogue was run.
        rules_loaded: Rules in the packaged extract for this framework.
        rules_enforced: Of those, the rules currently in force (the denominator
            every count below is drawn from).
        passed / failed / vacuous / not_evaluated: Rule counts per outcome.
        rules_executed: Rules that reached a verdict — pass, fail or vacuous.
        templates_emitted: Bundle members this run produced (what would be
            filed).
        templates_covered: Those of them against which a rule actually ran.
        coverage_shortfall: The checker's structured reason for insufficient
            coverage (``"no_rule_executed"`` — the estate could not be reached
            at all, a plumbing problem; ``"template_not_covered"`` — specific
            templates went out unexamined), or ``None`` when coverage holds.
            The two demand different responses from a filer, which is why it is
            structured rather than a bare boolean.
        blocking_breaks: Broken Error-severity rules — the submission blockers.
        warning_breaks: Broken Warning-severity rules.
        not_evaluated_rules: Rules that produced no verdict, each carrying its
            ``reason`` and ``detail``.
        outcomes: Every enforced rule's outcome, in catalogue order.
        errors: The findings on the project's error channel — ``VAL001``
            (Error-severity break, blocking) / ``VAL002`` (Warning break) /
            ``VAL003`` (coverage too thin for an absent finding to mean
            anything) — for merging into a response's accumulated findings.
    """

    framework: str
    publisher: str
    rules_loaded: int
    rules_enforced: int
    passed: int
    failed: int
    vacuous: int
    not_evaluated: int
    rules_executed: int
    templates_emitted: tuple[str, ...]
    templates_covered: tuple[str, ...]
    coverage_shortfall: CoverageShortfall | None
    blocking_breaks: tuple[RuleOutcome, ...]
    warning_breaks: tuple[RuleOutcome, ...]
    not_evaluated_rules: tuple[RuleOutcome, ...]
    outcomes: tuple[RuleOutcome, ...]
    errors: tuple[CalculationError, ...]

    @property
    def is_submittable(self) -> bool:
        """Whether this estate can be filed.

        No Error-severity rule broken, AND the estate was checked at all. Never
        infer this from an empty finding list — that is the fail-open the second
        limb closes.

        ``template_not_covered`` deliberately does NOT block; see the class
        docstring. ``was_checked`` is the limb that does.
        """
        return not self.blocking_breaks and self.was_checked

    @property
    def was_checked(self) -> bool:
        """Whether ANY rule ran — the limb that blocks a submission.

        False only for ``no_rule_executed``: the estate could not be reached by
        the rule set at all, so an absent break asserts nothing whatsoever.
        """
        from rwa_calc.reporting.validations import COVERAGE_NO_RULE_EXECUTED

        return self.coverage_shortfall != COVERAGE_NO_RULE_EXECUTED

    @property
    def is_coverage_complete(self) -> bool:
        """Whether every emitted template was checked — NOT the submit decision.

        A null check on the checker's own verdict, NOT a second evaluation of
        it. False for EITHER coverage limb, so it is a quality signal: on a CCR
        estate it sits at False beside ``is_submittable`` True, which is correct
        and not a contradiction. Use ``is_submittable`` to decide whether to
        file, and ``templates_uncovered`` for what went out unexamined.

        Named "complete" rather than "sufficient" deliberately: sufficient *for
        what?* invites the reader to take it as a verdict, which it is not.
        """
        return self.coverage_shortfall is None

    @property
    def templates_uncovered(self) -> tuple[str, ...]:
        """Emitted templates that no executed rule looked at."""
        covered = set(self.templates_covered)
        return tuple(name for name in self.templates_emitted if name not in covered)

    @property
    def blocking_count(self) -> int:
        """Error-severity breaks — each one rejects the whole return."""
        return len(self.blocking_breaks)

    @property
    def warning_count(self) -> int:
        """Warning-severity breaks — accepted, but each must be explained."""
        return len(self.warning_breaks)

    def blocking_rule_ids(self) -> tuple[str, ...]:
        """The publisher rule ids that block this submission, in catalogue order."""
        return tuple(outcome.rule_id for outcome in self.blocking_breaks)

    def not_evaluated_reasons(self) -> dict[str, int]:
        """Not-evaluated rule counts per reason, commonest first."""
        counts = Counter(outcome.reason for outcome in self.not_evaluated_rules)
        return dict(counts.most_common())

    def headline(self) -> str:
        """The verdict in one line, for a log record or a filer's screen.

        Always states the DENOMINATOR — breaks out of rules actually executed,
        and how many could not be evaluated at all. "0 blocking breaks" alone is
        the number that misleads; "0 blocking of 224 executed, 484 not
        evaluable" is the one a filer can judge.
        """
        from rwa_calc.reporting.validations import COVERAGE_NO_RULE_EXECUTED

        verdict = "SUBMITTABLE" if self.is_submittable else "BLOCKED"
        if self.coverage_shortfall == COVERAGE_NO_RULE_EXECUTED:
            coverage = (
                f"; NOT CHECKED — no rule could be executed against the "
                f"{len(self.templates_emitted)} emitted template(s), so an absent break "
                "asserts nothing"
            )
        else:
            # Always stated, even when complete: "12 of 12 covered" is what makes
            # "12 of 13" legible when it appears. A non-blocking gap that nobody
            # is shown is a gap nobody closes.
            coverage = (
                f"; {len(self.templates_covered)} of {len(self.templates_emitted)} "
                "template(s) covered"
            )
            if self.templates_uncovered:
                coverage += f" — UNCHECKED (does not block): {', '.join(self.templates_uncovered)}"
        return (
            f"{verdict}: {self.blocking_count} blocking break(s) and "
            f"{self.warning_count} warning(s) out of {self.rules_executed} rule(s) executed "
            f"({self.passed} passed, {self.vacuous} vacuous); {self.not_evaluated} of "
            f"{self.rules_enforced} enforced {self.publisher} rules were not evaluable "
            f"({self.framework}){coverage}"
        )


def summarise_validation(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle | None,
    framework: str,
) -> SubmissionValidationResult:
    """Evaluate the published rules over a generated estate and summarise them.

    The bundle-level entry point behind ``ResultExporter.validate_submission``,
    exposed separately so a caller that already holds generated bundles (the
    REST template-bundle cache, a test harness) does not regenerate them.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar III bundle, or ``None``. Carried for the
            checker's contract; no published rule addresses a Pillar III
            template today (see ``validations.scope.build_template_index``).
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        The ``SubmissionValidationResult``. Never raises for a data condition —
        a bundle with no templates at all yields every rule NOT_EVALUATED, which
        reports ``no_rule_executed`` and is NOT submittable, because nothing was
        checked.

    Raises:
        ValueError: ``framework`` is not a supported framework (a programming
            error, raised by ``load_rules`` — not a data-quality outcome).
    """
    from rwa_calc.reporting.validations import (
        SEVERITY_ERROR,
        STATUS_FAIL,
        STATUS_NOT_EVALUATED,
        STATUS_PASS,
        STATUS_VACUOUS,
        check_supervisory_validations,
        evaluate_all,
    )

    report = evaluate_all(corep, pillar3, framework)
    counts = report.status_counts()
    breaks = report.by_status(STATUS_FAIL)
    result = SubmissionValidationResult(
        framework=report.framework,
        publisher=report.publisher,
        rules_loaded=report.rules_loaded,
        rules_enforced=report.rules_enforced,
        passed=counts[STATUS_PASS],
        failed=counts[STATUS_FAIL],
        vacuous=counts[STATUS_VACUOUS],
        not_evaluated=counts[STATUS_NOT_EVALUATED],
        rules_executed=report.rules_executed,
        templates_emitted=report.templates_emitted,
        templates_covered=report.templates_covered,
        coverage_shortfall=report.coverage_shortfall,
        blocking_breaks=tuple(o for o in breaks if o.severity == SEVERITY_ERROR),
        warning_breaks=tuple(o for o in breaks if o.severity != SEVERITY_ERROR),
        not_evaluated_rules=report.by_status(STATUS_NOT_EVALUATED),
        outcomes=report.outcomes,
        # The checker owns the VAL001/VAL002/VAL003 message wording, so the
        # findings are taken from its own adapter rather than re-formatted here.
        # It re-runs the evaluation (there is no public report -> findings entry
        # point), so this is the one place the rule set is walked twice.
        errors=tuple(check_supervisory_validations(corep, pillar3, framework)),
    )
    logger.info("submission validation: %s", result.headline())
    return result


# =============================================================================
# Cell-fact helpers
# =============================================================================


def _write_fact_frame(
    frame: pl.DataFrame,
    output_path: Path,
    fmt: Literal["parquet", "ndjson", "csv"],
    export_format_label: str,
) -> ExportResult:
    """Write a flat, keyed frame (cell facts, rule outcomes) to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "ndjson":
        frame.write_ndjson(output_path)
    elif fmt == "csv":
        _csv_safe(frame).write_csv(output_path)
    else:
        frame.write_parquet(output_path)
    return ExportResult(
        format=f"{export_format_label}_{fmt}", files=[output_path], row_count=frame.height
    )


# =============================================================================
# Submission validation report helpers
# =============================================================================

#: The validation report's schema, in column order. One row per enforced rule.
#: ``template_id`` / ``sheet`` / ``row_ref`` / ``col_ref`` / ``lhs`` / ``rhs``
#: describe the FIRST recorded failing coordinate and are null for any rule that
#: did not break; ``failing_coordinates`` carries every recorded one.
#:
#: ``blocking`` means "this row is blocking THIS submission" — broken AND
#: Error-severity — so filtering on it gives a filer exactly the rules to fix.
#: It is deliberately not "this rule is of blocking severity", which is true of
#: several hundred rules that passed or never ran; that reading is still
#: available on ``severity``.
#:
#: The ``run_*`` columns are run-level constants stamped on every row (the same
#: convention ``export_corep_facts`` uses for filing metadata). They carry the
#: coverage context — including a ``template_not_covered`` gap, which does NOT
#: block a submission but must still reach whoever reviews this file.
_VALIDATION_REPORT_SCHEMA: dict[str, PolarsDataType] = {
    "framework": pl.String,
    "publisher": pl.String,
    "rule_id": pl.String,
    "severity": pl.String,
    "blocking": pl.Boolean,
    "rule_type": pl.String,
    "status": pl.String,
    "reason": pl.String,
    "detail": pl.String,
    "tables": pl.String,
    "template_id": pl.String,
    "sheet": pl.String,
    "row_ref": pl.String,
    "col_ref": pl.String,
    "lhs": pl.Float64,
    "rhs": pl.Float64,
    "evaluated": pl.Int64,
    "passed": pl.Int64,
    "failed": pl.Int64,
    "vacuous": pl.Int64,
    "skipped": pl.Int64,
    "failing_coordinates": pl.String,
    "expression": pl.String,
    "label": pl.String,
    "run_is_submittable": pl.Boolean,
    "run_coverage_shortfall": pl.String,
    "run_templates_emitted": pl.Int64,
    "run_templates_covered": pl.Int64,
    "run_templates_uncovered": pl.String,
}


def _validation_report_frame(result: SubmissionValidationResult) -> pl.DataFrame:
    """Build the one-row-per-rule-outcome report frame.

    The schema is declared rather than inferred so an all-null column (no break
    recorded anywhere) reloads as its true dtype, and an estate with no enforced
    rules still writes a readable, correctly-typed empty file.
    """
    from rwa_calc.reporting.validations import SEVERITY_ERROR, SINGLE_SHEET, STATUS_FAIL

    # Run-level context, stamped on every row so the file is self-contained: a
    # reviewer sorting or filtering it can never end up looking at rule outcomes
    # without also seeing which templates were never checked.
    run_columns: dict[str, object] = {
        "run_is_submittable": result.is_submittable,
        "run_coverage_shortfall": result.coverage_shortfall,
        "run_templates_emitted": len(result.templates_emitted),
        "run_templates_covered": len(result.templates_covered),
        "run_templates_uncovered": "; ".join(result.templates_uncovered) or None,
    }

    rows: list[dict[str, object]] = []
    for outcome in result.outcomes:
        first = outcome.failures[0] if outcome.failures else None
        coordinate = first.coordinate if first is not None else None
        sheet = None if coordinate is None or coordinate.sheet == SINGLE_SHEET else coordinate.sheet
        rows.append(
            {
                "framework": outcome.framework,
                "publisher": outcome.publisher,
                "rule_id": outcome.rule_id,
                "severity": outcome.severity,
                "blocking": outcome.status == STATUS_FAIL and outcome.severity == SEVERITY_ERROR,
                "rule_type": outcome.rule_type,
                "status": outcome.status,
                "reason": outcome.reason,
                "detail": outcome.detail,
                "tables": "; ".join(outcome.tables),
                "template_id": coordinate.table if coordinate is not None else None,
                "sheet": sheet,
                "row_ref": coordinate.row if coordinate is not None else None,
                "col_ref": coordinate.column if coordinate is not None else None,
                "lhs": first.lhs if first is not None else None,
                "rhs": first.rhs if first is not None else None,
                "evaluated": outcome.evaluated,
                "passed": outcome.passed,
                "failed": outcome.failed,
                "vacuous": outcome.vacuous,
                "skipped": outcome.skipped,
                "failing_coordinates": "; ".join(outcome.coordinates) or None,
                "expression": outcome.expression,
                "label": outcome.label,
                **run_columns,
            }
        )
    return pl.DataFrame(rows, schema=_VALIDATION_REPORT_SCHEMA)


# =============================================================================
# CSV helpers
# =============================================================================


def _csv_safe(df: pl.DataFrame) -> pl.DataFrame:
    """Return *df* with any nested columns JSON-encoded so CSV can represent them.

    CSV has no nested types, so a List/Array/Struct column makes ``write_csv``
    raise ``ComputeError`` and leave a blank file. The results frame carries a few
    such columns (e.g. ``ancestor_facilities``, ``securitisation_pool_allocations``,
    ``addon_by_asset_class``); each is replaced by its JSON string so the data is
    preserved for downstream tools. Flat frames are returned unchanged.

    The per-row encode only touches the handful of nested columns; ``map_elements``
    is the one encoder uniform across List/Array/Struct in this Polars version.
    """
    nested = [n for n, t in df.schema.items() if t.base_type() in (pl.List, pl.Array, pl.Struct)]
    if not nested:
        return df
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pl.exceptions.PolarsInefficientMapWarning)
        return df.with_columns(
            pl.col(c).map_elements(_json_encode_value, return_dtype=pl.String).alias(c)
            for c in nested
        )


def _json_encode_value(value: object) -> str | None:
    """JSON-encode one nested cell: ``None`` stays null; a Series becomes a list first."""
    if value is None:
        return None
    if isinstance(value, pl.Series):
        value = value.to_list()
    return json.dumps(value, default=str)


# =============================================================================
# Reconciliation export helpers
# =============================================================================


def _reconciliation_frames(
    response: ReconciliationResponse,
) -> list[tuple[str, pl.DataFrame]]:
    """Collect the reconciliation bundle frames in report order (headline first).

    Reads through the response's *memoised* ``collect_*`` accessors rather than
    collecting the raw lazy bundle frames directly. The bundle frames are lazy
    views that re-scan the run's ``last_results.parquet`` on every ``.collect()``;
    reusing the cached eager snapshot (already warmed for the report/explorer) both
    avoids re-executing the reconcile join per export and keeps the export off the
    fresh-disk-re-scan path that can raise "File out of specification: The page
    header reported the wrong page size" on a torn / mis-written results parquet.
    """
    return [
        ("summary_by_component", response.collect_summary_by_component()),
        ("totals_tie_out", response.collect_totals_tie_out()),
        ("class_allocation", response.collect_class_allocation()),
        ("class_allocation_by_method", response.collect_class_allocation_by_method()),
        ("summary_by_bucket", response.collect_summary_by_bucket()),
        ("summary_by_exposure_class", response.collect_summary_by_exposure_class()),
        ("summary_by_approach", response.collect_summary_by_approach()),
        ("breaks_detail", response.collect_breaks_detail()),
        ("component_reconciliation", response.collect_component_reconciliation()),
    ]


def _reconciliation_errors_frame(response: ReconciliationResponse) -> pl.DataFrame:
    """Build a small DataFrame of the reconciliation warnings for the report."""
    return pl.DataFrame(
        {
            "code": [e.code for e in response.errors],
            "severity": [e.severity for e in response.errors],
            "message": [e.message for e in response.errors],
        }
    )


# =============================================================================
# Comparison export helpers
# =============================================================================


def _comparison_frames(
    response: ComparisonExportResponse,
) -> list[tuple[str, pl.DataFrame]]:
    """The comparison export frames in report order (headline first)."""
    return list(response.frames.items())


def _comparison_errors_frame(response: ComparisonExportResponse) -> pl.DataFrame:
    """Build a small DataFrame of the comparison warnings for the report."""
    return pl.DataFrame(
        {
            "code": [e.code for e in response.errors],
            "severity": [e.severity for e in response.errors],
            "message": [e.message for e in response.errors],
        }
    )
