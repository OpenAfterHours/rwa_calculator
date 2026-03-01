"""
Protocol definitions for RWA calculator components.

Defines interfaces using Python's Protocol (PEP 544) for structural
typing. Components implementing these protocols can be:
- Easily mocked for unit testing
- Swapped for different implementations
- Developed in parallel by different team members

Each protocol represents a distinct pipeline stage:
    LoaderProtocol -> HierarchyResolverProtocol -> ClassifierProtocol
        -> CRMProcessorProtocol -> SA/IRBCalculatorProtocol
        -> OutputAggregatorProtocol

All protocols use LazyFrames to maintain deferred execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import polars as pl

    from rwa_calc.contracts.bundles import (
        AggregatedResultBundle,
        CapitalImpactBundle,
        ClassifiedExposuresBundle,
        ComparisonBundle,
        CRMAdjustedBundle,
        EquityResultBundle,
        IRBResultBundle,
        RawDataBundle,
        ResolvedHierarchyBundle,
        SAResultBundle,
        SlottingResultBundle,
    )
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import LazyFrameResult


@runtime_checkable
class LoaderProtocol(Protocol):
    """
    Protocol for data loading components.

    Responsible for loading raw data from source systems and
    converting to LazyFrames with expected schemas.

    Implementations may load from:
    - Files (CSV, Parquet, JSON)
    - Databases (DuckDB, PostgreSQL)
    - APIs or message queues
    """

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Returns:
            RawDataBundle containing all input LazyFrames

        Raises:
            DataLoadError: If required data cannot be loaded
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
        Apply CRM and return as a bundle (alternative interface).

        Args:
            data: Classified exposures
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with adjusted exposures
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
            LazyFrame with SA RWA columns populated
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

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply IRB formulas on unified frame (single-pass pipeline).

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with IRB columns populated for IRB rows
        """
        ...

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
            LazyFrame with IRB RWA columns populated
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

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply slotting weights on unified frame (single-pass pipeline).

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with slotting columns populated for slotting rows
        """
        ...

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
            LazyFrame with slotting RWA columns populated
        """
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using supervisory slotting approach.

        Args:
            data: CRM-adjusted exposures (specialised lending)
            config: Calculation configuration

        Returns:
            LazyFrameResult with slotting RWA calculations
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
    Protocol for aggregating final results.

    Responsible for:
    - Combining SA and IRB results
    - Applying output floor (Basel 3.1)
    - Applying supporting factors (CRR)
    - Generating summary statistics
    - Combining all audit trails

    Input: SA and IRB LazyFrames
    Output: Final aggregated LazyFrame
    """

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Aggregate SA and IRB results into final output.

        Args:
            sa_results: Standardised Approach calculations
            irb_results: IRB approach calculations
            config: Calculation configuration

        Returns:
            Combined LazyFrame with all calculations
        """
        ...

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
        equity_bundle: EquityResultBundle | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate with full audit trail.

        Args:
            sa_bundle: SA calculation results bundle
            irb_bundle: IRB calculation results bundle
            slotting_bundle: Slotting calculation results bundle
            config: Calculation configuration
            equity_bundle: Equity calculation results bundle

        Returns:
            AggregatedResultBundle with audit information
        """
        ...

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply output floor to IRB RWA (Basel 3.1 only).

        Final RWA = max(IRB RWA, SA RWA x floor_percentage)

        Args:
            irb_rwa: IRB RWA before floor
            sa_equivalent_rwa: Equivalent SA RWA for comparison
            config: Calculation configuration

        Returns:
            LazyFrame with floor-adjusted RWA
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
    ) -> list:
        """
        Run data quality checks on raw data.

        Args:
            data: Raw data bundle to check
            config: Calculation configuration

        Returns:
            List of CalculationError for any issues found
        """
        ...
