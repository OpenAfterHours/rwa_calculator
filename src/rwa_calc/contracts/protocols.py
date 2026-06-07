"""
Protocol definitions for RWA calculator components.

Defines interfaces using Python's Protocol (PEP 544) for structural
typing. Components implementing these protocols can be:
- Easily mocked for unit testing
- Swapped for different implementations
- Developed in parallel by different team members

Each protocol represents a distinct pipeline stage:
    LoaderProtocol -> HierarchyResolverProtocol -> ClassifierProtocol
        -> CRMProcessorProtocol -> SA/IRB/SlottingCalculatorProtocol

All protocols use LazyFrames to maintain deferred execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

    from rwa_calc.api.export import ExportResult
    from rwa_calc.api.models import CalculationResponse
    from rwa_calc.contracts.bundles import (
        AggregatedResultBundle,
        CapitalImpactBundle,
        ClassifiedExposuresBundle,
        ComparisonBundle,
        CRMAdjustedBundle,
        EquityResultBundle,
        RawCCRBundle,
        RawDataBundle,
        ReconciliationBundle,
        ResolvedHierarchyBundle,
    )
    from rwa_calc.contracts.config import (
        CalculationConfig,
        CCRConfig,
        LegacyColumnMapping,
        OutputFloorConfig,
    )
    from rwa_calc.contracts.errors import CalculationError, LazyFrameResult
    from rwa_calc.engine.crm.link_allocation import CollateralLinkAllocation


@runtime_checkable
class LoaderProtocol(Protocol):
    """
    Protocol for data loading components.

    Responsible for loading raw data from source systems,
    converting to LazyFrames with expected schemas, and
    validating categorical column values.

    The returned RawDataBundle carries any validation errors
    found during loading so downstream stages can trust the
    data at the boundary.

    Implementations may load from:
    - Files (CSV, Parquet, JSON)
    - Databases (PostgreSQL)
    - APIs or message queues
    """

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Returns:
            RawDataBundle containing all input LazyFrames and any
            validation errors discovered during loading

        Raises:
            DataLoadError: If required data cannot be loaded
        """
        ...


@runtime_checkable
class SecuritisationAllocatorProtocol(Protocol):
    """
    Protocol for the securitisation-pool allocator stage.

    Resolves the user-supplied ``securitisation_allocations`` table into
    a per-exposure lookup carrying ``securitisation_residual_pct`` and
    ``securitisation_pool_allocations`` (a list-of-struct column). The
    resolved frame is also the audit trail consumed by downstream
    aggregator reporting.

    Phase 1 scope: flag and exclude securitised portions from standard
    credit-risk RWA totals. The securitisation RWA framework itself
    (SEC-SA, SEC-IRBA — CRR Art. 259-264) is out of scope.

    Input: RawDataBundle (reads ``securitisation_allocations`` if present).
    Output: RawDataBundle with ``securitisation_allocations`` left as-is
    and a per-exposure resolved lookup returned alongside via a tuple, or
    propagated through the ResolvedHierarchyBundle.securitisation_audit
    field once the hierarchy resolver joins it onto unified exposures.

    References:
    - CRR Art. 109, Art. 244-246 (significant risk transfer)
    - PRA PS1/26 Art. 147A(1)(j)
    """

    def allocate(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> tuple[RawDataBundle, pl.LazyFrame | None, list[CalculationError]]:
        """Resolve allocations and emit the per-exposure lookup.

        Args:
            data: Raw data bundle from loader.
            config: Calculation configuration.

        Returns:
            Tuple of (raw bundle unchanged, resolved lookup LazyFrame
            keyed by (exposure_reference, exposure_type), validation
            errors). The lookup is None when no allocations were
            supplied or the input frame was empty.
        """
        ...


@runtime_checkable
class HierarchyResolverProtocol(Protocol):
    """
    Protocol for hierarchy resolution components.

    Responsible for:
    - Resolving counterparty organisational hierarchies
    - Resolving facility/exposure hierarchies
    - Aggregating lending groups for retail threshold
    - Propagating ratings through hierarchy

    Input: RawDataBundle
    Output: ResolvedHierarchyBundle
    """

    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """
        Resolve all hierarchies and return enriched data.

        Args:
            data: Raw data bundle from loader
            config: Calculation configuration

        Returns:
            ResolvedHierarchyBundle with hierarchy metadata added
        """
        ...


@runtime_checkable
class ClassifierProtocol(Protocol):
    """
    Protocol for exposure classification components.

    Responsible for:
    - Determining exposure class (central_govt_central_bank, institution, corporate, etc.)
    - Assigning calculation approach (SA, F-IRB, A-IRB, slotting)
    - Mapping external ratings to CQS
    - Splitting exposures by approach

    Input: ResolvedHierarchyBundle
    Output: ClassifiedExposuresBundle
    """

    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """
        Classify exposures and split by approach.

        Args:
            data: Hierarchy-resolved data
            config: Calculation configuration

        Returns:
            ClassifiedExposuresBundle with exposures split by approach
        """
        ...


@runtime_checkable
class CCRCalculator(Protocol):
    """
    Protocol for the Counterparty Credit Risk EAD calculator.

    Responsible for:
    - Computing the per-netting-set Replacement Cost (RC) per Art. 275.
    - Computing the per-netting-set Potential Future Exposure (PFE)
      per Art. 278 (aggregate add-on x multiplier).
    - Producing the SA-CCR EAD = alpha * (RC + PFE) per Art. 274(2),
      with alpha = 1.4 default or firm-specific alpha under PRA permission.

    First-batch scope: SA-CCR only (unmargined, single-trade netting
    sets for CCR-A1). Simplified SA-CCR and OEM are deferred to v2.0;
    IMM (Art. 283-294) is deferred to v2.0.

    Pipeline position:
        Classifier -> CCRCalculator -> CRMProcessor (P8.20 wiring)

    The CCR EAD output is joined onto the unified exposure frame on
    ``netting_set_id`` so downstream SA / IRB stages see a single
    ``ead_pre_crm`` column regardless of whether the EAD came from
    on-balance-sheet drawn/contingent rows or from SA-CCR.

    Input: RawCCRBundle (the four P8.1 leaf bundles, composed in P8.2).
    Output: LazyFrame keyed by ``netting_set_id`` with columns
        ``rc``, ``pfe``, ``alpha``, ``ead_ccr``, ``ccr_method``.

    References:
    - CRR Art. 271 (scope), Art. 272 (definitions)
    - PRA Rulebook CCR (CRR) Part Art. 274(2) (alpha factor)
    - PRA Rulebook CCR (CRR) Part Art. 275(1)-(2) (RC formula)
    - PRA Rulebook CCR (CRR) Part Art. 278 (PFE multiplier)
    - BCBS CRE52.1-52.43
    """

    def compute_ead(
        self,
        data: RawCCRBundle,
        config: CCRConfig,
    ) -> pl.LazyFrame:
        """Compute per-netting-set SA-CCR EAD.

        Args:
            data: CCR input bundle. The four leaf LazyFrames
                (``trades``, ``netting_sets``, ``margin_agreements``,
                ``ccr_collateral``) may each be empty (zero rows,
                schema present) -- e.g. CCR-A1 has empty
                ``margin_agreements``.
            config: CCR-specific configuration (alpha factor, method
                selection, MPOR overrides). Owned by P8.6.

        Returns:
            LazyFrame with one row per netting set, schema:

            - ``netting_set_id`` (pl.String): primary key, mirrors
              ``RawCCRBundle.netting_sets`` ordering.
            - ``rc`` (pl.Float64): Replacement Cost per Art. 275.
              Non-negative.
            - ``pfe`` (pl.Float64): Potential Future Exposure per
              Art. 278. Non-negative.
            - ``alpha`` (pl.Float64): alpha factor per Art. 274(2).
              Sourced from ``config`` (default 1.4).
            - ``ead_ccr`` (pl.Float64): alpha * (RC + PFE).
              Non-negative.
            - ``ccr_method`` (pl.String): method discriminator.
              First batch returns ``"sa_ccr"`` for every row;
              future values include ``"simplified_sa_ccr"``,
              ``"oem"``, ``"imm"``.

        The method does not raise on data-quality issues; row-level
        errors are accumulated on the leaf bundles' ``errors`` lists
        by upstream stages (loader, P8.5). Bundle-wide wiring errors
        live on ``RawCCRBundle.errors``.
        """
        ...


@runtime_checkable
class CollateralLinkAllocatorProtocol(Protocol):
    """
    Protocol for splitting one finite collateral item across many beneficiaries.

    Expands the optional M:N ``collateral_links`` table into per-beneficiary
    collateral slices, allocating each finite value greedily for the most
    beneficial RWA impact (highest pre-CRM RWA density first, honouring any
    ``priority`` override and ``max_pledge_amount`` cap) without over-claiming.

    The expanded frame has the same shape as the single-beneficiary collateral
    table, so the Art. 231 waterfall consumes it unchanged.

    Input: exposures + collateral + collateral_links
    Output: CollateralLinkAllocation (expanded collateral, audit, errors)
    """

    def allocate_links(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
        collateral_links: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> CollateralLinkAllocation:
        """
        Expand ``collateral_links`` into per-beneficiary collateral slices.

        Returns the original collateral unchanged when no usable links table is
        supplied. Never raises — data-quality issues are accumulated on the
        result's ``errors`` list.
        """
        ...


@runtime_checkable
class CRMProcessorProtocol(Protocol):
    """
    Protocol for credit risk mitigation processing.

    Responsible for:
    - Applying collateral haircuts and allocations
    - Processing guarantee substitution
    - Applying provision offsets
    - Calculating final EAD and LGD values

    Input: ClassifiedExposuresBundle
    Output: LazyFrameResult containing CRMAdjustedBundle
    """

    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Apply credit risk mitigation to exposures.

        Args:
            data: Classified exposures
            config: Calculation configuration

        Returns:
            LazyFrameResult with CRM-adjusted exposures and any errors
        """
        ...

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM and return as a bundle with approach-split exposures.

        Performs full CRM pipeline including collateral, guarantees, provisions,
        and CCF, then splits exposures by approach (SA/IRB/Slotting).

        Args:
            data: Classified exposures
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with adjusted exposures split by approach
        """
        ...

    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM and return a unified bundle without approach splitting.

        Performs the same CRM pipeline as get_crm_adjusted_bundle but returns
        all exposures in a single unified LazyFrame without splitting by
        approach. Used by the pipeline for single-pass calculator processing.

        Args:
            data: Classified exposures
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with all exposures in the unified frame
        """
        ...


@runtime_checkable
class RealEstateSplitterProtocol(Protocol):
    """
    Protocol for the post-CRM real estate loan-splitter.

    Implements the CRR Art. 125/126 and PRA PS1/26 Art. 124F/H loan-
    splitting mechanics by physically partitioning property-collateralised
    SA-bound exposures into:

    - a secured row in ``RESIDENTIAL_MORTGAGE`` / ``COMMERCIAL_MORTGAGE``
      capped at the regulatory secured-LTV cap, and
    - a residual row that retains the original counterparty exposure
      class so the standard corporate / retail risk weight applies.

    Both rows share a ``split_parent_id`` lineage key so downstream
    aggregations can reconcile back to the original exposure.

    Input: CRMAdjustedBundle (post-CRM, pre-calculator)
    Output: CRMAdjustedBundle with split rows materialised
    """

    def split(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """Apply RE loan-splitting to candidate rows.

        Args:
            data: CRM-adjusted bundle from CRMProcessor. Candidate rows
                must already carry the classifier-emitted columns
                ``re_split_target_class``, ``re_split_mode``,
                ``re_split_property_value``.
            config: Calculation configuration. The regime (CRR vs B3.1)
                is selected via ``config.is_basel_3_1``.

        Returns:
            New ``CRMAdjustedBundle`` with the unified frame (and any
            approach-split frames, when set) replaced by the row-split
            equivalent. Rows that are not candidates are passed through
            unchanged. The optional ``re_split_audit`` LazyFrame
            captures one row per original exposure that was split.
        """
        ...


@runtime_checkable
class SACalculatorProtocol(Protocol):
    """
    Protocol for Standardised Approach calculations.

    Responsible for:
    - Looking up risk weights by CQS and exposure class
    - Applying LTV-based weights for real estate
    - Calculating RWA = EAD x RW

    Input: CRMAdjustedBundle (SA exposures)
    Output: LazyFrameResult with SA calculations
    """

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights on unified frame (single-pass pipeline).

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with SA columns populated for SA rows
        """
        ...

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Args:
            exposures: Pre-filtered SA rows only
            config: Calculation configuration

        Returns:
            LazyFrame with SA RWA columns populated.
            Must include ``approach_applied`` and ``rwa_final``.
        """
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using Standardised Approach.

        Args:
            data: CRM-adjusted exposures (uses sa_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with SA RWA calculations
        """
        ...


@runtime_checkable
class IRBCalculatorProtocol(Protocol):
    """
    Protocol for IRB approach calculations.

    Responsible for:
    - Applying PD floors
    - Determining LGD (supervisory for F-IRB, floored for A-IRB)
    - Calculating correlation (R)
    - Calculating capital requirement (K)
    - Applying scaling factor (1.06)
    - Calculating RWA = K x 12.5 x EAD

    Input: CRMAdjustedBundle (IRB exposures)
    Output: LazyFrameResult with IRB calculations
    """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate IRB RWA on pre-filtered IRB-only rows.

        Args:
            exposures: Pre-filtered IRB rows only
            config: Calculation configuration

        Returns:
            LazyFrame with IRB RWA columns populated.
            Must include ``approach_applied`` and ``rwa_final``.
        """
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using IRB approach.

        Args:
            data: CRM-adjusted exposures (uses irb_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with IRB RWA calculations
        """
        ...

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate expected loss for IRB exposures.

        EL = PD x LGD x EAD

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            LazyFrameResult with expected loss calculations
        """
        ...


@runtime_checkable
class SlottingCalculatorProtocol(Protocol):
    """
    Protocol for specialised lending slotting calculations.

    Responsible for:
    - Mapping slotting categories to risk weights
    - Applying maturity adjustments (<2.5 years)
    - Handling HVCRE higher weights

    Input: CRMAdjustedBundle (slotting exposures)
    Output: LazyFrameResult with slotting calculations
    """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA on pre-filtered slotting-only rows.

        Args:
            exposures: Pre-filtered slotting rows only
            config: Calculation configuration

        Returns:
            LazyFrame with slotting RWA columns populated.
            Must include ``approach_applied`` and ``rwa_final``.
        """
        ...


@runtime_checkable
class EquityCalculatorProtocol(Protocol):
    """
    Protocol for equity exposure calculations.

    Responsible for:
    - Determining equity risk weights under SA (Art. 133) or IRB Simple (Art. 155)
    - Calculating RWA = EAD x RW
    - Handling diversified portfolio treatment for private equity

    Input: CRMAdjustedBundle (equity exposures)
    Output: LazyFrameResult with equity calculations
    """

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA for equity exposures.

        Args:
            data: CRM-adjusted exposures (uses equity_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with equity RWA calculations
        """
        ...

    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """
        Calculate equity RWA and return as bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            EquityResultBundle with results and audit trail
        """
        ...


@runtime_checkable
class OutputAggregatorProtocol(Protocol):
    """
    Protocol for output aggregation components.

    Responsible for:
    - Combining SA, IRB, Slotting, and Equity results
    - Applying output floor (Basel 3.1)
    - Generating supporting factor impact (CRR)
    - Generating summaries by class and approach
    - Generating pre/post-CRM reporting views
    - Computing EL portfolio summary with T2 credit cap

    Input: Per-approach calculator results + CalculationConfig
    Output: AggregatedResultBundle
    """

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
        securitisation_audit: pl.LazyFrame | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate calculator outputs into final result bundle.

        Args:
            sa_results: SA branch results (already collected and re-lazied).
            irb_results: IRB branch results.
            slotting_results: Slotting branch results.
            equity_bundle: Equity result bundle (optional, separate path).
            config: Calculation configuration.

        Returns:
            AggregatedResultBundle with all summaries and adjustments.
        """
        ...


@runtime_checkable
class PipelineProtocol(Protocol):
    """
    Protocol for the complete calculation pipeline.

    Orchestrates all components from data loading through
    final output generation.
    """

    def run(self, config: CalculationConfig) -> AggregatedResultBundle:
        """
        Execute the complete RWA calculation pipeline.

        Args:
            config: Calculation configuration

        Returns:
            AggregatedResultBundle with all results and audit trail
        """
        ...

    def run_with_data(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Execute pipeline with pre-loaded data.

        Args:
            data: Pre-loaded raw data bundle
            config: Calculation configuration

        Returns:
            AggregatedResultBundle with all results and audit trail
        """
        ...


@runtime_checkable
class ComparisonRunnerProtocol(Protocol):
    """
    Protocol for dual-framework comparison execution.

    Runs the same portfolio through both CRR and Basel 3.1 pipelines
    and produces a ComparisonBundle with per-exposure deltas and
    summary impact analysis.

    Why: During Basel 3.1 transition, firms need to quantify the capital
    impact of moving from CRR to Basel 3.1. This protocol defines the
    interface for orchestrating that comparison.
    """

    def compare(
        self,
        data: RawDataBundle,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> ComparisonBundle:
        """
        Run both frameworks on the same data and produce comparison.

        Args:
            data: Pre-loaded raw data bundle (shared between frameworks)
            crr_config: CRR configuration
            b31_config: Basel 3.1 configuration

        Returns:
            ComparisonBundle with per-exposure deltas and summaries
        """
        ...


@runtime_checkable
class CapitalImpactAnalyzerProtocol(Protocol):
    """
    Protocol for capital impact analysis (M3.2).

    Decomposes the RWA delta between CRR and Basel 3.1 into attributable
    regulatory drivers using a sequential waterfall methodology.

    Why: Understanding WHY RWA changes between frameworks (not just by
    how much) is essential for capital planning. This protocol defines
    the interface for decomposing the total delta into its component
    drivers: scaling factor removal, supporting factor removal, output
    floor impact, and methodology/parameter changes.
    """

    def analyze(
        self,
        comparison: ComparisonBundle,
    ) -> CapitalImpactBundle:
        """
        Decompose comparison deltas into driver-level attribution.

        Args:
            comparison: Pre-computed dual-framework comparison bundle

        Returns:
            CapitalImpactBundle with per-exposure and portfolio attribution
        """
        ...


@runtime_checkable
class ReconciliationRunnerProtocol(Protocol):
    """
    Protocol for parallel-run reconciliation execution.

    Reconciles our per-exposure results against an external legacy calculator's
    output (already mapped onto our canonical components and a composite/custom
    join key) and produces a ReconciliationBundle with per-component buckets,
    summaries, a break worklist, and a totals tie-out.

    Why: firms migrating to this calculator run it in parallel with their
    existing engine and must demonstrate, component by component, where the two
    agree and where (and why) they diverge. This protocol defines the interface
    for that reconciliation, independent of how the legacy file was loaded or
    how the result is surfaced (API / export / UI).
    """

    def reconcile(
        self,
        our_results: pl.LazyFrame,
        legacy_results: pl.LazyFrame,
        mapping: LegacyColumnMapping,
    ) -> ReconciliationBundle:
        """
        Reconcile our results against a mapped legacy output.

        Args:
            our_results: Our per-exposure results LazyFrame (e.g. from
                ``CalculationResponse.scan_results()``).
            legacy_results: The legacy output already mapped to canonical
                ``legacy_<component>`` columns and key columns.
            mapping: The column/key mapping and per-component tolerances.

        Returns:
            ReconciliationBundle with per-component reconciliation and summaries.
        """
        ...


# =============================================================================
# VALIDATION HELPER PROTOCOLS
# =============================================================================


@runtime_checkable
class SchemaValidatorProtocol(Protocol):
    """
    Protocol for schema validation components.

    Validates LazyFrame schemas against expected definitions
    without materializing the data.
    """

    def validate(
        self,
        lf: pl.LazyFrame,
        expected_schema: dict[str, pl.DataType],
        context: str,
    ) -> list[str]:
        """
        Validate LazyFrame schema against expected schema.

        Args:
            lf: LazyFrame to validate
            expected_schema: Expected column types
            context: Context for error messages

        Returns:
            List of validation error messages (empty if valid)
        """
        ...


@runtime_checkable
class DataQualityCheckerProtocol(Protocol):
    """
    Protocol for data quality checking components.

    Performs data quality checks on input data.
    """

    def check(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> list[CalculationError]:
        """
        Run data quality checks on raw data.

        Args:
            data: Raw data bundle to check
            config: Calculation configuration

        Returns:
            List of CalculationError for any issues found
        """
        ...


# =============================================================================
# EXPORT PROTOCOLS
# =============================================================================


@runtime_checkable
class ResultExporterProtocol(Protocol):
    """
    Protocol for result export components.

    Exports CalculationResponse data to external file formats.
    Each method writes one or more files and returns an ExportResult
    describing what was written.

    Why: Firms need calculation results in formats consumable by
    downstream systems — Parquet for analytics pipelines, CSV for
    ad-hoc analysis, Excel for stakeholder reporting, and COREP
    templates for quarterly regulatory submissions to the PRA.
    """

    def export_to_parquet(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to Parquet files.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write parquet files into

        Returns:
            ExportResult with list of written files and row count
        """
        ...

    def export_to_csv(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to CSV files.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write CSV files into

        Returns:
            ExportResult with list of written files and row count
        """
        ...

    def export_to_excel(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """
        Export results to a multi-sheet Excel workbook.

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with the written file path and row count
        """
        ...

    def export_to_corep(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> ExportResult:
        """
        Export results as COREP regulatory reporting templates.

        Generates C 07.00 (SA credit risk), C 08.01 (IRB totals),
        and C 08.02 (IRB PD grade breakdown) in a multi-sheet Excel
        workbook following EBA/PRA COREP template structure.

        Why: CRR firms must submit quarterly COREP returns to the PRA.
        This reshapes the calculator's exposure-level results into the
        fixed-format regulatory templates (Regulation (EU) 2021/451).

        References:
            - CRR Art. 99: COREP reporting obligation
            - PRA PS1/26: Basel 3.1 OF-variant templates
            - PRA PS1/26 Art. 92 para 2A: entity-type floor applicability

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file
            output_floor_config: Optional floor config for reporting
                basis conditionality. Gates floor indicators and
                materiality columns on entity type and reporting basis.

        Returns:
            ExportResult with the written file path and row count
        """
        ...

    def export_to_pillar3(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """
        Export results as Pillar III public disclosure templates.

        Generates 9 quantitative credit risk templates (OV1, CR4, CR5,
        CR6, CR6-A, CR7, CR7-A, CR8, CR10) in a multi-sheet Excel
        workbook following CRR Part 8 / Disclosure (CRR) Part structure.

        Why: CRR firms must publish Pillar III disclosures for market
        transparency. CRR templates use the UK prefix; Basel 3.1
        templates use UKB prefix.

        References:
            - CRR Part 8 (Art. 438, 444, 452, 453)
            - PRA PS1/26 Disclosure (CRR) Part

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with the written file path and row count
        """
        ...
