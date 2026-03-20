# Contracts API

The `rwa_calc.contracts` package defines the data transfer types, error handling, and
protocol interfaces that glue the pipeline together. Every pipeline stage receives and
returns frozen dataclass bundles — never raw dicts — ensuring type safety and immutability
across the calculation flow.

**Why contracts matter:** The pipeline processes regulatory capital calculations where
correctness is paramount. Typed contracts catch structural errors at development time
rather than at runtime inside a 100K-exposure production run. The protocol-driven design
also allows any component to be swapped or mocked without modifying callers.

---

## Data Bundles

### Module: `rwa_calc.contracts.bundles`

Each bundle is a `@dataclass(frozen=True)` containing Polars `LazyFrame` fields. Bundles
flow through the pipeline in order:

```
Loader → RawDataBundle → HierarchyResolver → ResolvedHierarchyBundle
    → Classifier → ClassifiedExposuresBundle → CRMProcessor → CRMAdjustedBundle
    → SA/IRB/Slotting/Equity Calculators → Result Bundles
    → OutputAggregator → AggregatedResultBundle
```

#### `RawDataBundle`

Output from the data loader. Contains all raw input data as LazyFrames, exactly as loaded
from source systems with no transformations applied.

```python
@dataclass(frozen=True)
class RawDataBundle:
    # Required fields
    facilities: pl.LazyFrame           # Credit facility records
    loans: pl.LazyFrame                # Drawn loan records
    counterparties: pl.LazyFrame       # Counterparty/borrower information
    facility_mappings: pl.LazyFrame    # Facility hierarchy mappings
    lending_mappings: pl.LazyFrame     # Lending group mappings (for retail aggregation)

    # Optional fields
    org_mappings: pl.LazyFrame | None = None        # Organisational hierarchy
    contingents: pl.LazyFrame | None = None         # Off-balance sheet contingent items
    collateral: pl.LazyFrame | None = None          # Security/collateral items
    guarantees: pl.LazyFrame | None = None          # Guarantee/credit protection items
    provisions: pl.LazyFrame | None = None          # IFRS 9 provisions (SCRA/GCRA)
    ratings: pl.LazyFrame | None = None             # Internal and external credit ratings
    specialised_lending: pl.LazyFrame | None = None # Specialised lending metadata (slotting)
    equity_exposures: pl.LazyFrame | None = None    # Equity exposure details
    fx_rates: pl.LazyFrame | None = None            # FX rates for currency conversion
    model_permissions: pl.LazyFrame | None = None  # Per-model IRB approach permissions
```

#### `CounterpartyLookup`

Resolved counterparty hierarchy information. All lookups are LazyFrames — use joins to
look up values instead of dict access.

```python
@dataclass(frozen=True)
class CounterpartyLookup:
    counterparties: pl.LazyFrame         # Counterparty data with resolved hierarchy
    parent_mappings: pl.LazyFrame        # child_counterparty_reference → parent_counterparty_reference
    ultimate_parent_mappings: pl.LazyFrame  # counterparty_reference → ultimate_parent_reference, hierarchy_depth
    rating_inheritance: pl.LazyFrame     # counterparty_reference → rating info with inheritance metadata
```

#### `ResolvedHierarchyBundle`

Output from the hierarchy resolver. Contains exposures with fully resolved counterparty
hierarchies (for rating inheritance), facility hierarchies (for CRM inheritance), and
lending group aggregation (for retail threshold checks).

```python
@dataclass(frozen=True)
class ResolvedHierarchyBundle:
    exposures: pl.LazyFrame                          # Unified exposure records with hierarchy metadata
    counterparty_lookup: CounterpartyLookup           # Resolved counterparty information
    lending_group_totals: pl.LazyFrame                # Aggregated exposures by lending group
    collateral: pl.LazyFrame | None = None            # Collateral with beneficiary hierarchy resolved
    guarantees: pl.LazyFrame | None = None            # Guarantees with beneficiary hierarchy resolved
    provisions: pl.LazyFrame | None = None            # Provisions with beneficiary hierarchy resolved
    equity_exposures: pl.LazyFrame | None = None      # Equity exposure details (passed through)
    model_permissions: pl.LazyFrame | None = None    # Per-model IRB approach permissions
    hierarchy_errors: list = field(default_factory=list)  # Errors encountered during resolution
```

#### `ClassifiedExposuresBundle`

Output from the classifier. Contains exposures classified by exposure class
(`ExposureClass`) and calculation approach (`ApproachType`), split into SA-applicable
and IRB-applicable sets for downstream calculators.

```python
@dataclass(frozen=True)
class ClassifiedExposuresBundle:
    all_exposures: pl.LazyFrame                        # All exposures with classification metadata
    sa_exposures: pl.LazyFrame                         # Exposures for Standardised Approach
    irb_exposures: pl.LazyFrame                        # Exposures for IRB (F-IRB or A-IRB)
    slotting_exposures: pl.LazyFrame | None = None     # Specialised lending for slotting approach
    equity_exposures: pl.LazyFrame | None = None       # Equity exposures (SA only under Basel 3.1)
    collateral: pl.LazyFrame | None = None             # Collateral data for CRM processing
    guarantees: pl.LazyFrame | None = None             # Guarantee data for CRM processing
    provisions: pl.LazyFrame | None = None             # Provision data for CRM processing
    counterparty_lookup: CounterpartyLookup | None = None  # Counterparty data for guarantor risk weights
    classification_audit: pl.LazyFrame | None = None   # Audit trail of classification decisions
    classification_errors: list = field(default_factory=list)  # Errors during classification
```

#### `CRMAdjustedBundle`

Output from the CRM processor. Contains exposures with credit risk mitigation applied:
collateral effects (haircuts, allocation), guarantee effects (substitution), and provision
effects (SCRA/GCRA). EAD and LGD values are adjusted based on CRM.

```python
@dataclass(frozen=True)
class CRMAdjustedBundle:
    exposures: pl.LazyFrame                            # Exposures with CRM-adjusted EAD and LGD
    sa_exposures: pl.LazyFrame                         # SA exposures after CRM
    irb_exposures: pl.LazyFrame                        # IRB exposures after CRM
    slotting_exposures: pl.LazyFrame | None = None     # Specialised lending exposures for slotting
    equity_exposures: pl.LazyFrame | None = None       # Equity exposures (passed through, no CRM)
    crm_audit: pl.LazyFrame | None = None              # Detailed audit trail of CRM application
    collateral_allocation: pl.LazyFrame | None = None  # How collateral was allocated to exposures
    crm_errors: list = field(default_factory=list)     # Errors during CRM processing
```

#### Result Bundles

Each calculator produces its own result bundle:

```python
@dataclass(frozen=True)
class SAResultBundle:
    """Standardised Approach calculation results."""
    results: pl.LazyFrame                          # SA results with risk weights and RWA
    calculation_audit: pl.LazyFrame | None = None  # Detailed calculation breakdown
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class IRBResultBundle:
    """IRB calculation results (F-IRB and A-IRB)."""
    results: pl.LazyFrame                          # IRB results with K, RW, RWA
    expected_loss: pl.LazyFrame | None = None      # Expected loss calculations (PD × LGD × EAD)
    calculation_audit: pl.LazyFrame | None = None  # Detailed breakdown (PD, LGD, M, R, K)
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class SlottingResultBundle:
    """Slotting approach results for specialised lending."""
    results: pl.LazyFrame                          # Slotting results with risk weights and RWA
    calculation_audit: pl.LazyFrame | None = None  # Detailed calculation breakdown
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class EquityResultBundle:
    """Equity exposure results under Article 133 (SA) or Article 155 (IRB Simple)."""
    results: pl.LazyFrame                          # Equity results with risk weights and RWA
    calculation_audit: pl.LazyFrame | None = None  # Detailed calculation breakdown
    approach: str = "sa"                           # "sa" (Art. 133) or "irb_simple" (Art. 155)
    errors: list = field(default_factory=list)
```

#### `ELPortfolioSummary`

Portfolio-level expected loss summary with T2 credit cap. Aggregates per-exposure EL
shortfall/excess into portfolio totals and applies the T2 credit cap per CRR Art. 62(d).

**Why this exists:** Under IRB, provisions and expected loss interact with regulatory
capital through T2 credit (for excess provisions) and CET1/T2 deductions (for shortfalls).
This summary captures the full EL-to-capital flow in one place.

```python
@dataclass(frozen=True)
class ELPortfolioSummary:
    total_expected_loss: float         # Sum of EL across all IRB exposures
    total_provisions_allocated: float  # Sum of provisions allocated to IRB exposures
    total_el_shortfall: float          # Sum of max(0, EL - provisions) per exposure
    total_el_excess: float             # Sum of max(0, provisions - EL) per exposure
    total_irb_rwa: float               # Total IRB RWA (denominator for T2 cap)
    t2_credit_cap: float               # 0.6% of total IRB RWA (CRR Art. 62(d))
    t2_credit: float                   # min(total_el_excess, t2_credit_cap) — addable to T2 capital
    cet1_deduction: float              # 50% of total_el_shortfall — deducted from CET1 (CRR Art. 159)
    t2_deduction: float                # 50% of total_el_shortfall — deducted from T2 (CRR Art. 159)
```

#### `AggregatedResultBundle`

Final aggregated output from the output aggregator. Combines SA, IRB, slotting, and equity
results with output floor application (Basel 3.1) and supporting factor adjustments (CRR).

```python
@dataclass(frozen=True)
class AggregatedResultBundle:
    results: pl.LazyFrame                                  # Final RWA results with all adjustments
    sa_results: pl.LazyFrame | None = None                 # Original SA results (for floor comparison)
    irb_results: pl.LazyFrame | None = None                # Original IRB results (before floor)
    slotting_results: pl.LazyFrame | None = None           # Original slotting results
    equity_results: pl.LazyFrame | None = None             # Equity calculation results
    floor_impact: pl.LazyFrame | None = None               # Output floor impact analysis (Basel 3.1)
    supporting_factor_impact: pl.LazyFrame | None = None   # Supporting factor impact (CRR only)
    summary_by_class: pl.LazyFrame | None = None           # RWA summarised by exposure class
    summary_by_approach: pl.LazyFrame | None = None        # RWA summarised by approach
    pre_crm_summary: pl.LazyFrame | None = None            # Pre-CRM summary (gross view by original class)
    post_crm_detailed: pl.LazyFrame | None = None          # Post-CRM detailed view (split rows for guarantees)
    post_crm_summary: pl.LazyFrame | None = None           # Post-CRM summary (net view by effective class)
    el_summary: ELPortfolioSummary | None = None           # Portfolio-level EL summary with T2 credit cap
    errors: list = field(default_factory=list)              # All errors accumulated throughout pipeline
```

#### Comparison and Impact Bundles

These bundles support dual-framework comparison during the Basel 3.1 transition:

```python
@dataclass(frozen=True)
class ComparisonBundle:
    """Dual-framework comparison results (M3.1).
    Holds CRR and Basel 3.1 pipeline results side by side."""
    crr_results: AggregatedResultBundle       # Full CRR pipeline output
    b31_results: AggregatedResultBundle       # Full Basel 3.1 pipeline output
    exposure_deltas: pl.LazyFrame             # Per-exposure CRR vs B31 RWA, risk weights, EAD
    summary_by_class: pl.LazyFrame            # Delta RWA aggregated by exposure class
    summary_by_approach: pl.LazyFrame         # Delta RWA aggregated by calculation approach
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class TransitionalScheduleBundle:
    """Transitional floor schedule modelling (M3.3).
    Models the year-by-year output floor from 50% (2027) to 72.5% (2032+)."""
    timeline: pl.LazyFrame                         # Year-by-year floor impact summary
    yearly_results: dict[int, AggregatedResultBundle] = field(default_factory=dict)
    errors: list = field(default_factory=list)

@dataclass(frozen=True)
class CapitalImpactBundle:
    """Capital impact analysis (M3.2).
    Decomposes RWA delta between CRR and Basel 3.1 into regulatory drivers:
    scaling factor removal, supporting factor removal, output floor, methodology changes."""
    exposure_attribution: pl.LazyFrame    # Per-exposure driver attribution
    portfolio_waterfall: pl.LazyFrame     # Portfolio-level waterfall steps (CRR baseline to B31)
    summary_by_class: pl.LazyFrame        # Attribution aggregated by exposure class
    summary_by_approach: pl.LazyFrame     # Attribution aggregated by calculation approach
    errors: list = field(default_factory=list)
```

### Helper Functions

Factory functions for creating empty bundles, primarily used in testing:

| Function | Returns | Purpose |
|----------|---------|---------|
| `create_empty_raw_data_bundle()` | `RawDataBundle` | Empty bundle with empty LazyFrames for required fields |
| `create_empty_counterparty_lookup()` | `CounterpartyLookup` | Empty lookup with correct schemas for all 4 fields |
| `create_empty_resolved_hierarchy_bundle()` | `ResolvedHierarchyBundle` | Empty bundle using `create_empty_counterparty_lookup()` |
| `create_empty_classified_bundle()` | `ClassifiedExposuresBundle` | Empty bundle with empty LazyFrames for `all_exposures`, `sa_exposures`, `irb_exposures` |
| `create_empty_crm_adjusted_bundle()` | `CRMAdjustedBundle` | Empty bundle with empty LazyFrames for `exposures`, `sa_exposures`, `irb_exposures` |

---

## Error Handling

### Module: `rwa_calc.contracts.errors`

The error handling system uses error accumulation rather than exceptions. Data quality
issues are collected as `CalculationError` instances and propagated through bundles —
the pipeline continues processing all exposures and reports all issues at the end.

**Why accumulation over exceptions:** A regulatory calculation that throws on the first
bad exposure and stops is far less useful than one that processes all valid exposures
and produces a complete error report. Auditors and risk analysts need to see every issue,
not just the first one.

#### `CalculationError`

Immutable representation of a calculation error or warning:

```python
@dataclass(frozen=True)
class CalculationError:
    code: str                                  # Error code (e.g., "CRM001", "DQ003")
    message: str                               # Human-readable description
    severity: ErrorSeverity                    # WARNING, ERROR, or CRITICAL
    category: ErrorCategory                    # DATA_QUALITY, BUSINESS_RULE, etc.
    exposure_reference: str | None = None      # Affected exposure identifier
    counterparty_reference: str | None = None  # Affected counterparty identifier
    regulatory_reference: str | None = None    # Regulatory article (e.g., "CRR Art. 153")
    field_name: str | None = None              # Name of the problematic field
    expected_value: str | None = None          # Description of expected value/format
    actual_value: str | None = None            # Actual value that caused the error
```

Methods:

- `__str__()` — Human-readable format: `[DQ001] ERROR: Required field 'pd' is missing | Exposure: EXP001 | Ref: CRR Art. 153`
- `to_dict()` — Dictionary serialisation of all fields

!!! note
    There is no separate `CalculationWarning` class. Warnings are `CalculationError`
    instances with `severity=ErrorSeverity.WARNING`.

#### `LazyFrameResult`

Result container combining a LazyFrame with accumulated errors. Implements the Result
pattern for LazyFrame operations, allowing errors to be collected without throwing
exceptions.

```python
@dataclass
class LazyFrameResult:
    frame: pl.LazyFrame                                 # The resulting LazyFrame
    errors: list[CalculationError] = field(default_factory=list)  # Accumulated errors/warnings
```

Properties:

| Property | Type | Description |
|----------|------|-------------|
| `has_errors` | `bool` | `True` if any errors with severity `ERROR` or `CRITICAL` |
| `has_critical_errors` | `bool` | `True` if any errors with severity `CRITICAL` |
| `warnings` | `list[CalculationError]` | Only `WARNING`-severity items |
| `critical_errors` | `list[CalculationError]` | Only `CRITICAL`-severity items |

Methods:

| Method | Signature | Description |
|--------|-----------|-------------|
| `errors_by_category()` | `(category: ErrorCategory) → list[CalculationError]` | Filter errors by category |
| `errors_by_exposure()` | `(exposure_reference: str) → list[CalculationError]` | Get all errors for a specific exposure |
| `add_error()` | `(error: CalculationError) → None` | Append a single error |
| `add_errors()` | `(errors: list[CalculationError]) → None` | Append multiple errors |
| `merge()` | `(other: LazyFrameResult) → LazyFrameResult` | Merge another result's errors (returns new result; caller handles frame combination) |

Usage:

```python
result = processor.apply_crm(data, config)
if result.has_critical_errors:
    log.error("Critical CRM failures", errors=result.critical_errors)
else:
    for w in result.warnings:
        log.warning(w)
    # Continue with result.frame
```

#### Error Code Constants

Error codes are prefixed by domain and numbered sequentially:

| Code | Constant | Domain | Description |
|------|----------|--------|-------------|
| `DQ001` | `ERROR_MISSING_FIELD` | Data Quality | Required field is missing or null |
| `DQ002` | `ERROR_INVALID_VALUE` | Data Quality | Invalid value for a field |
| `DQ003` | `ERROR_TYPE_MISMATCH` | Data Quality | Column type does not match schema |
| `DQ004` | `ERROR_DUPLICATE_KEY` | Data Quality | Duplicate key in reference data |
| `DQ005` | `ERROR_ORPHAN_REFERENCE` | Data Quality | Foreign key reference has no match |
| `DQ006` | `ERROR_INVALID_COLUMN_VALUE` | Data Quality | Column value not in allowed set |
| `HIE001` | `ERROR_CIRCULAR_HIERARCHY` | Hierarchy | Circular reference in hierarchy |
| `HIE002` | `ERROR_MISSING_PARENT` | Hierarchy | Parent counterparty not found |
| `HIE003` | `ERROR_HIERARCHY_DEPTH` | Hierarchy | Hierarchy exceeds maximum depth |
| `CLS001` | `ERROR_UNKNOWN_EXPOSURE_CLASS` | Classification | Cannot determine exposure class |
| `CLS002` | `ERROR_APPROACH_NOT_PERMITTED` | Classification | Requested approach not permitted by config |
| `CLS003` | `ERROR_MISSING_RATING` | Classification | No rating available for rated class |
| `CRM001` | `ERROR_INELIGIBLE_COLLATERAL` | CRM | Collateral type not eligible for CRM |
| `CRM002` | `ERROR_MATURITY_MISMATCH` | CRM | Collateral maturity < exposure maturity |
| `CRM003` | `ERROR_CURRENCY_MISMATCH` | CRM | Collateral currency ≠ exposure currency |
| `CRM004` | `ERROR_COLLATERAL_OVERALLOCATION` | CRM | Collateral allocated exceeds available amount |
| `CRM005` | `ERROR_INVALID_GUARANTEE` | CRM | Guarantee does not meet eligibility criteria |
| `IRB001` | `ERROR_PD_OUT_OF_RANGE` | IRB | PD value outside valid range (0, 1] |
| `IRB002` | `ERROR_LGD_OUT_OF_RANGE` | IRB | LGD value outside valid range [0, 1] |
| `IRB003` | `ERROR_MATURITY_INVALID` | IRB | Effective maturity outside [1, 5] range |
| `IRB004` | `ERROR_MISSING_PD` | IRB | No PD value available for IRB exposure |
| `IRB005` | `ERROR_MISSING_LGD` | IRB | No LGD value available for A-IRB exposure |
| `SA001` | `ERROR_INVALID_CQS` | SA | CQS value not in valid range |
| `SA002` | `ERROR_MISSING_RISK_WEIGHT` | SA | Cannot determine risk weight |
| `SA003` | `ERROR_INVALID_LTV` | SA | LTV ratio invalid for property class |
| `CFG001` | `ERROR_INVALID_CONFIG` | Configuration | Invalid configuration parameter |
| `CFG002` | `ERROR_MISSING_PERMISSION` | Configuration | Required IRB permission not granted |

#### Error Factory Functions

Convenience functions for creating common error types:

```python
def missing_field_error(
    field_name: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a DQ001 missing field error."""

def invalid_value_error(
    field_name: str,
    actual_value: str,
    expected_value: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a DQ002 invalid value error."""

def business_rule_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
) -> CalculationError:
    """Create a business rule violation error with custom code and severity."""

def hierarchy_error(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    counterparty_reference: str | None = None,
) -> CalculationError:
    """Create a hierarchy-related error (HIE001-HIE003)."""

def crm_warning(
    code: str,
    message: str,
    exposure_reference: str | None = None,
    regulatory_reference: str | None = None,
) -> CalculationError:
    """Create a CRM-related warning (severity=WARNING, category=CRM)."""
```

---

## Protocols

### Module: `rwa_calc.contracts.protocols`

All pipeline components implement structural `Protocol` interfaces (PEP 544). This means
any class with the right method signatures satisfies the protocol — no inheritance required.
All protocols are `@runtime_checkable`.

**Why protocols over ABCs:** Protocols enable structural (duck) typing. A test mock that
implements `calculate()` with the right signature automatically satisfies
`SACalculatorProtocol` without inheriting from it. This makes testing and alternative
implementations frictionless.

### Pipeline Stage Protocols

#### `LoaderProtocol`

```python
class LoaderProtocol(Protocol):
    def load(self) -> RawDataBundle:
        """Load all required data and return as a RawDataBundle."""
        ...
```

#### `HierarchyResolverProtocol`

```python
class HierarchyResolverProtocol(Protocol):
    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """Resolve all hierarchies and return enriched data."""
        ...
```

#### `ClassifierProtocol`

```python
class ClassifierProtocol(Protocol):
    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """Classify exposures and split by approach."""
        ...
```

#### `CRMProcessorProtocol`

Provides two interfaces: `apply_crm()` returns a `LazyFrameResult` (for error inspection),
while `get_crm_adjusted_bundle()` wraps the result into a `CRMAdjustedBundle`.

```python
class CRMProcessorProtocol(Protocol):
    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Apply credit risk mitigation. Returns LazyFrameResult with CRM-adjusted
        exposures and any errors."""
        ...

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """Apply CRM and return as a bundle (alternative interface)."""
        ...
```

### Calculator Protocols

All calculator protocols follow a three-method pattern:

- `calculate_unified()` — operates on a unified frame (single-pass pipeline)
- `calculate_branch()` — operates on pre-filtered approach-specific rows
- `calculate()` — takes a `CRMAdjustedBundle` and returns `LazyFrameResult`

#### `SACalculatorProtocol`

```python
class SACalculatorProtocol(Protocol):
    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply SA risk weights on unified frame (single-pass pipeline)."""
        ...

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Calculate SA RWA on pre-filtered SA-only rows."""
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate RWA using Standardised Approach."""
        ...
```

#### `IRBCalculatorProtocol`

Extends the three-method pattern with `calculate_expected_loss()`:

```python
class IRBCalculatorProtocol(Protocol):
    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply IRB formulas on unified frame (single-pass pipeline)."""
        ...

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Calculate IRB RWA on pre-filtered IRB-only rows."""
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate RWA using IRB approach."""
        ...

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate expected loss for IRB exposures (EL = PD × LGD × EAD)."""
        ...
```

#### `SlottingCalculatorProtocol`

```python
class SlottingCalculatorProtocol(Protocol):
    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply slotting weights on unified frame."""
        ...

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Calculate slotting RWA on pre-filtered slotting-only rows."""
        ...

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate RWA using supervisory slotting approach."""
        ...
```

#### `EquityCalculatorProtocol`

```python
class EquityCalculatorProtocol(Protocol):
    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate RWA for equity exposures."""
        ...

    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """Calculate equity RWA and return as bundle."""
        ...
```

#### `OutputAggregatorProtocol`

```python
class OutputAggregatorProtocol(Protocol):
    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Aggregate SA and IRB results into final output."""
        ...

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
        equity_bundle: EquityResultBundle | None = None,
    ) -> AggregatedResultBundle:
        """Aggregate with full audit trail from all calculator bundles."""
        ...

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply output floor to IRB RWA (Basel 3.1 only).
        Final RWA = max(IRB RWA, SA RWA × floor_percentage)."""
        ...
```

### Orchestration Protocols

#### `PipelineProtocol`

```python
class PipelineProtocol(Protocol):
    def run(self, config: CalculationConfig) -> AggregatedResultBundle:
        """Execute the complete RWA calculation pipeline."""
        ...

    def run_with_data(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Execute pipeline with pre-loaded data."""
        ...
```

#### `ComparisonRunnerProtocol`

```python
class ComparisonRunnerProtocol(Protocol):
    def compare(
        self,
        data: RawDataBundle,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> ComparisonBundle:
        """Run both frameworks on the same data and produce comparison."""
        ...
```

#### `CapitalImpactAnalyzerProtocol`

```python
class CapitalImpactAnalyzerProtocol(Protocol):
    def analyze(
        self,
        comparison: ComparisonBundle,
    ) -> CapitalImpactBundle:
        """Decompose comparison deltas into driver-level attribution."""
        ...
```

### Validation and Export Protocols

#### `SchemaValidatorProtocol`

```python
class SchemaValidatorProtocol(Protocol):
    def validate(
        self,
        lf: pl.LazyFrame,
        expected_schema: dict[str, pl.DataType],
        context: str,
    ) -> list[str]:
        """Validate LazyFrame schema against expected schema.
        Returns list of error messages (empty if valid)."""
        ...
```

#### `DataQualityCheckerProtocol`

```python
class DataQualityCheckerProtocol(Protocol):
    def check(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> list:
        """Run data quality checks on raw data.
        Returns list of CalculationError for any issues found."""
        ...
```

#### `ResultExporterProtocol`

```python
class ResultExporterProtocol(Protocol):
    def export_to_parquet(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export results to Parquet files."""
        ...

    def export_to_csv(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export results to CSV files."""
        ...

    def export_to_excel(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export results to a multi-sheet Excel workbook."""
        ...
```

---

## Related

- [Domain API](domain.md) — enums used by contracts (`ErrorSeverity`, `ErrorCategory`, etc.)
- [Engine API](engine.md) — implementations of these protocols
- [Configuration API](configuration.md) — `CalculationConfig` referenced by all protocols
- [Architecture - Design Principles](../architecture/design-principles.md)
