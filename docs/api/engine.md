# Engine API

The engine module contains all calculation components. Each component implements a
structural `Protocol` (defined in `contracts/protocols.py`).

The engine is wired as a **fold over a literal stage registry**: `engine/registry.py`
holds the ordered `StageSpec` list, and `engine/orchestrator.py::run_stages` threads an
immutable `PipelineContext` (a typed `ArtifactKey[T]` map, `contracts/context.py`)
through one `run(ctx, rulepack, run_config)` adapter per stage under `engine/stages/`.
`engine/pipeline.py` is the run-lifecycle facade. Stages exchange **eager sealed frames**
(`materialise_edge` at every stage exit, with producer-sealed edge contracts in
`contracts/edges.py`); schema violations **raise**, while data-quality issues accumulate
in `list[CalculationError]`. The per-component classes described below are the stage
implementations invoked by those adapters.

Registered stage order (`engine/registry.py`):

```
securitisation_allocator → hierarchy_resolver → ccr_sa_ccr → classifier
    → crm_processor → re_splitter → calculators (SA/IRB/Slotting)
    → equity_calculator → aggregator
```

## Loader

### Module: `rwa_calc.engine.loader`

Loads input data from Parquet or CSV files into a `RawDataBundle`. Schema enforcement
ensures columns are cast to expected Polars types.

```python
@dataclass
class DataSourceConfig:
    """Configuration for data file locations (relative to base_path)."""
    counterparties_file: str               # default: "counterparty/counterparties.parquet"
    facilities_file: str                   # default: "exposures/facilities.parquet"
    loans_file: str                        # default: "exposures/loans.parquet"
    contingents_file: str                  # default: "exposures/contingents.parquet"
    collateral_file: str                   # default: "collateral/collateral.parquet"
    guarantees_file: str                   # default: "guarantee/guarantee.parquet"
    provisions_file: str                   # default: "provision/provision.parquet"
    ratings_file: str                      # default: "ratings/ratings.parquet"
    facility_mappings_file: str            # default: "exposures/facility_mapping.parquet"
    org_mappings_file: str                 # default: "mapping/org_mapping.parquet"
    lending_mappings_file: str             # default: "mapping/lending_mapping.parquet"
    equity_exposures_file: str | None      # default: None
    fx_rates_file: str | None              # default: "fx_rates/fx_rates.parquet"
```

```python
class ParquetLoader:
    """Load data from Parquet files."""

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None:
        """
        Args:
            base_path: Base directory containing data files.
            config: Optional data source configuration.
            enforce_schemas: Whether to enforce type casting based on schemas.
        """

    def load(self) -> RawDataBundle:
        """
        Load all required data and return as a RawDataBundle.

        Returns:
            RawDataBundle containing all input LazyFrames.

        Raises:
            DataLoadError: If required data cannot be loaded.

        Example:
            >>> loader = ParquetLoader(Path("./data"))
            >>> data = loader.load()
        """
```

```python
class CSVLoader:
    """Load data from CSV files."""

    def __init__(
        self,
        base_path: str | Path,
        config: DataSourceConfig | None = None,
        enforce_schemas: bool = True,
    ) -> None: ...

    def load(self) -> RawDataBundle: ...
```

#### Helper Functions

```python
def enforce_schema(
    lf: pl.LazyFrame,
    schema: dict[str, pl.DataType],
    strict: bool = False,
) -> pl.LazyFrame:
    """Enforce a schema on a LazyFrame by casting columns to expected types."""

def normalize_columns(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Normalize column names to lowercase with underscores."""

def create_test_loader(fixture_path: str | Path | None = None) -> ParquetLoader:
    """Create a loader configured for test fixtures."""
```

## Hierarchy Resolver

### Module: `rwa_calc.engine.hierarchy`

Resolves counterparty and facility hierarchies for rating inheritance,
lending group aggregation, facility-to-exposure traversal, and facility
undrawn calculation.

```python
class HierarchyResolver:
    """Resolve counterparty and facility hierarchies.

    Implements HierarchyResolverProtocol for:
    - Org hierarchy lookups (ultimate parent resolution)
    - Rating inheritance from parent entities
    - Facility-to-exposure mappings (multi-level facility hierarchies)
    - Lending group exposure aggregation
    """

    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """
        Resolve all hierarchies and return enriched data.

        Steps:
        1. Build counterparty lookup (ultimate parents, rating inheritance)
        2. Unify exposures (loans + contingents + facility undrawn)
        3. FX conversion (if configured)
        4. Add collateral LTV
        5. Enrich with property coverage & lending groups

        Args:
            data: Raw data bundle from loader.
            config: Calculation configuration.

        Returns:
            ResolvedHierarchyBundle with enriched exposures and counterparty lookup.
        """
```

## Classifier

### Module: `rwa_calc.engine.classifier`

Determines exposure class, assigns calculation approach, checks SME/retail
thresholds, identifies defaults, and splits by approach.

```python
class ExposureClassifier:
    """Classify exposures by regulatory class and approach.

    Implements ClassifierProtocol. Uses 4 batched .with_columns() calls
    to keep the LazyFrame query plan shallow.

    Classification steps:
    1. Add counterparty attributes (entity_type, revenue, default status)
    2. Derive independent flags (exposure_class, is_mortgage, is_defaulted)
    3. SME + retail classification (is_sme, qualifies_as_retail)
    4. Corporate-to-retail reclassification (CRR Art. 147(5))
    5. Approach assignment + finalization (SA/FIRB/AIRB/SLOTTING)
    """

    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """
        Classify all exposures and split by approach.

        Args:
            data: Resolved hierarchy bundle.
            config: Calculation configuration.

        Returns:
            ClassifiedExposuresBundle with classified exposures,
            collateral, guarantees, provisions, counterparty_lookup,
            classification_audit, and classification_errors.
        """
```

#### Module-Level Constants

```python
ENTITY_TYPE_TO_SA_CLASS: dict[str, str]   # entity_type → SA exposure class
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str]  # entity_type → IRB exposure class
```

## CCF Calculator

### Module: `rwa_calc.engine.ccf`

Credit Conversion Factor (CCF) calculator for off-balance sheet items.
Calculates EAD for contingent exposures using regulatory CCFs:

- **SA** (CRR Art. 111): Full Risk = 100%, Medium Risk = 50%, Medium-Low Risk = 20%, Low Risk = 0% (Basel 3.1: Low Risk = 10%)
- **F-IRB** (CRR Art. 166(8)): Own-estimate CCF
- **F-IRB Exception** (CRR Art. 166(9)): Falls back to SA CCFs

```python
class CCFCalculator:
    """Calculate credit conversion factors for off-balance sheet items.

    Implements CRR CCF rules:
    - SA (Art. 111)
    - F-IRB (Art. 166(8))
    - F-IRB exception (Art. 166(9))
    """

    def apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CCF to calculate EAD for off-balance sheet exposures.

        Adds columns:
        - ead_from_ccf: EAD contribution from CCF application
        - ccf: The applied credit conversion factor
        - ead_pre_crm: Total EAD before CRM
        - ccf_calculation: Audit trail string

        Args:
            exposures: Exposures with risk_type, drawn_amount, nominal_amount columns.
            config: Calculation configuration.

        Returns:
            LazyFrame with CCF-derived EAD columns.
        """
```

#### Module-Level Functions

```python
def drawn_for_ead() -> pl.Expr:
    """Drawn amount floored at 0 for EAD calculations.
    Negative drawn (credit balances) should not reduce EAD without a netting agreement."""

def on_balance_ead() -> pl.Expr:
    """On-balance-sheet EAD: max(0, drawn) + accrued interest."""

def sa_ccf_expression(
    risk_type_col: str = "risk_type",
    is_basel_3_1: bool = False,
) -> pl.Expr:
    """Return a Polars expression that maps risk_type to SA CCFs.

    CRR (Art. 111): FR=100%, MR=50%, MLR=20%, LR=0%.
    Basel 3.1 (CRE20.88): LR changes to 10%.
    """

def create_ccf_calculator() -> CCFCalculator:
    """Create a CCF calculator instance."""
```

**Usage Example:**

```python
from rwa_calc.engine.ccf import create_ccf_calculator, sa_ccf_expression

# Use the calculator class
calculator = create_ccf_calculator()
exposures_with_ead = calculator.apply_ccf(exposures, config)

# Or use the expression directly in a Polars pipeline
result = exposures.with_columns(
    sa_ccf_expression(is_basel_3_1=False).alias("ccf")
)
```

## CRM Processor

### Module: `rwa_calc.engine.crm.processor`

Credit Risk Mitigation processor. Applies the full CRM waterfall:

1. Provision deduction (drawn-first, before CCF — CRR Art. 110)
2. CCF application (CRR Art. 111)
3. EAD initialisation
4. Collateral haircuts and allocation (CRR Art. 223-224)
5. Guarantee substitution (CRR Art. 213-215)
6. EAD finalisation

```python
class CRMProcessor:
    """Apply credit risk mitigation to exposures.

    Implements CRMProcessorProtocol for:
    - CCF (CRR Art. 111)
    - Collateral haircuts (CRR Art. 223-224)
    - Guarantee substitution (CRR Art. 213-215)
    - Provision deduction (CRR Art. 110)
    """

    COLLATERAL_REQUIRED_COLUMNS = {"beneficiary_reference", "market_value"}
    GUARANTEE_REQUIRED_COLUMNS = {"beneficiary_reference", "amount_covered", "guarantor"}
    PROVISION_REQUIRED_COLUMNS = {"beneficiary_reference", "amount"}

    def __init__(self) -> None:
        """Construct a CRM processor.

        The processor holds no constructor regime-state — the regime is
        read per-method from the effective CalculationConfig / resolved
        pack at call time.
        """

    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM on the unified exposure frame (the single entry point).

        Returns the unified LazyFrame for single-pass calculator
        processing; errors accumulate on ``crm_errors``.

        Args:
            data: Classified exposures bundle.
            config: Calculation configuration.

        Returns:
            CRMAdjustedBundle with unified exposures field.
        """

    def apply_collateral(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply collateral to reduce EAD (SA) or LGD (IRB).

        Pre-computes shared exposure lookups once, then joins all
        lookup columns in a single pass.
        """

    def apply_guarantees(
        self,
        exposures: pl.LazyFrame,
        guarantees: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
        rating_inheritance: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution.

        For guaranteed portion, substitute borrower risk weight
        with guarantor risk weight.
        """

    def resolve_provisions(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Resolve provisions with multi-level beneficiary and drawn-first deduction.

        Called before CCF (CRR Art. 111(1)(a)-(b)).

        Adds columns:
        - provision_allocated: Total provision matched to this exposure
        - provision_on_drawn: Provision absorbed by drawn amount (SA only)
        - provision_on_nominal: Provision reducing nominal before CCF (SA only)
        - provision_deducted: Total = provision_on_drawn + provision_on_nominal
        - nominal_after_provision: nominal_amount - provision_on_nominal
        """
```

**Factory:**

```python
def create_crm_processor() -> CRMProcessor:
    """Create a CRM processor instance.

    The processor carries no constructor regime-state — the regime is read
    per-method from the effective CalculationConfig at call time.
    """
```

### Module: `rwa_calc.engine.crm.haircuts`

```python
class HaircutCalculator:
    """Apply CRR Art. 223-224 supervisory haircuts to financial collateral."""

    def apply_haircuts(self, ...) -> pl.LazyFrame:
        """Apply collateral, FX and maturity-mismatch haircuts across a frame."""

    def apply_exposure_haircut(self, ...) -> pl.LazyFrame: ...
    def apply_maturity_mismatch(self, ...) -> pl.LazyFrame: ...
    def calculate_single_haircut(self, ...) -> float: ...


def create_haircut_calculator() -> HaircutCalculator:
    """Create a HaircutCalculator instance."""
```

!!! note "Supervisory haircut values are pack-bound"
    The supervisory-haircut table builders live in the thin pack-binding shim
    `rwa_calc.engine.crm.haircut_tables` (e.g. `get_haircut_table(...)`), which
    reads the haircut values back from the rulepack. There is no free
    `get_haircut(...)` function — `HaircutCalculator` consumes the
    pack-resolved tables.

## SA Calculator

### Module: `rwa_calc.engine.sa.calculator`

Standardised Approach (SA) Calculator for RWA. Implements CRR Art. 112-134
and Basel 3.1 CRE20 risk weight lookups.

```python
class SACalculator:
    """Calculate RWA using Standardised Approach.

    Implements SACalculatorProtocol for:
    - CQS-based risk weight lookup (sovereigns, institutions, corporates)
    - Fixed retail weight (75%)
    - LTV-based real estate weights
    - Supporting factor application (CRR only)
    """

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights to SA rows on a unified frame.

        Operates on a frame containing SA + IRB + slotting rows together.
        Also stores SA-equivalent RWA for output floor calculation.
        """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Expects only SA rows — no approach guards needed. The optional
        ``errors`` accumulator receives SA004/SA005/SF001 warnings.
        """

```

**Factory:**

```python
def create_sa_calculator() -> SACalculator:
    """Create an SA calculator instance."""
```

### Module: `rwa_calc.engine.supporting_factors`

```python
def calculate_sme_factor(
    total_exposure: float,
    threshold: float,
    factor_below: float = 0.7619,
    factor_above: float = 0.85,
) -> float:
    """
    Calculate SME supporting factor.

    SME tiered factor: 0.7619 (<=EUR 2.5m) / 0.85 (>EUR 2.5m).

    Example:
        >>> factor = calculate_sme_factor(5_000_000, 2_500_000)
        >>> print(f"Factor: {factor:.4f}")
        Factor: 0.8110
    """
```

## IRB Calculator

### Module: `rwa_calc.engine.irb.calculator`

IRB (Internal Ratings-Based) Calculator for RWA. Implements
CRR Art. 153-154 for F-IRB and A-IRB approaches.

```python
class IRBCalculator:
    """Calculate RWA using IRB approach.

    Supports:
    - CRR: Single PD floor (0.03%), no LGD floors, 1.06 scaling factor
    - Basel 3.1: Differentiated PD floors, LGD floors for A-IRB, no scaling
    """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate IRB RWA on pre-filtered IRB-only rows.

        Steps: classify approach → apply F-IRB LGD → prepare columns
        → apply all formulas → compute EL shortfall/excess
        → apply guarantee substitution → supporting factors (CRR).
        Expected-loss columns are included in the output; the optional
        ``errors`` accumulator receives SF001 and EL diagnostics.
        """

```

**Factory:**

```python
def create_irb_calculator() -> IRBCalculator:
    """Create an IRB calculator instance."""
```

### Module: `rwa_calc.engine.irb.transforms`

Plain module-level typed functions for IRB calculations, composed via
`lf.pipe(fn, config)`. (Polars namespaces are extinct and banned —
`arch_check` check 14.)

#### LazyFrame transforms

```python
def classify_approach(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Classify exposures as F-IRB or A-IRB. Adds: approach, is_airb."""

def apply_firb_lgd(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply supervisory LGD for F-IRB (45% senior, 75% sub, 0% financial, 35-40% secured)."""

def prepare_columns(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Ensure required columns exist with defaults (pd=0.01, lgd=0.45, maturity=2.5)."""

def apply_all_formulas(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Full chain: PD floor → LGD floor → correlation → K → maturity adj → RWA → EL."""

def apply_pd_floor(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply PD floor (0.03% CRR, differentiated Basel 3.1)."""

def apply_lgd_floor(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply LGD floor (Basel 3.1 A-IRB only)."""

def calculate_correlation(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Calculate asset correlation with SME firm-size adjustment."""

def calculate_k(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Calculate capital requirement K using IRB formula."""

def calculate_maturity_adjustment(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Calculate maturity adjustment (non-retail only)."""

def calculate_rwa(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Calculate RWA = K x 12.5 x EAD x MA x [1.06]."""

def calculate_expected_loss(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Calculate expected loss = PD x LGD x EAD."""

def select_expected_loss(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Select expected loss columns for output."""

def build_audit(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Build audit trail with intermediate calculation values."""
```

#### Expression helpers

```python
def floor_pd(expr: pl.Expr, floor_value: float) -> pl.Expr:
    """Floor PD values to minimum."""

def floor_lgd(expr: pl.Expr, floor_value: float) -> pl.Expr:
    """Floor LGD values to minimum."""

def clip_maturity(expr: pl.Expr, floor: float = 1.0, cap: float = 5.0) -> pl.Expr:
    """Clip maturity to regulatory bounds [1, 5] years."""
```

**Usage Example:**

```python
from rwa_calc.engine.irb import transforms as irb

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# IRB calculation pipeline composed via .pipe(fn, config)
result = (
    exposures
    .pipe(irb.classify_approach, config)
    .pipe(irb.apply_firb_lgd, config)
    .pipe(irb.prepare_columns, config)
    .pipe(irb.apply_all_formulas, config)
    .collect()
)

# Expression helpers
result = lf.with_columns(
    irb.floor_pd(pl.col("pd"), 0.0003),
    irb.clip_maturity(pl.col("maturity"), 1.0, 5.0),
)
```

### Module: `rwa_calc.engine.irb.formulas`

Pure functions for the IRB capital requirement formula.

```python
def calculate_k(pd: float, lgd: float, correlation: float) -> float:
    """Calculate IRB capital requirement (K)."""

def calculate_correlation(
    exposure_class: ExposureClass,
    pd: float,
    turnover: float | None = None,
) -> float:
    """Calculate asset correlation with SME firm-size adjustment."""

def calculate_maturity_adjustment(pd: float, effective_maturity: float) -> float:
    """Calculate maturity adjustment factor."""
```

## Slotting Calculator

### Module: `rwa_calc.engine.slotting.calculator`

Slotting Calculator for Specialised Lending RWA. Implements CRR Art. 153(5)
supervisory slotting approach and Basel 3.1 revised weights.

```python
class SlottingCalculator:
    """Calculate RWA using supervisory slotting approach.

    CRR Art. 153(5): Non-HVCRE and HVCRE weights by maturity band.
    Basel 3.1 (BCBS CRE33): Revised operational, PF pre-op, and HVCRE weights.
    """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA on pre-filtered slotting-only rows.

        Uses: prepare_columns → apply_slotting_weights → calculate_rwa
        → supporting factors (CRR) → EL rates + shortfall/excess.
        """

```

**Factory:**

```python
def create_slotting_calculator() -> SlottingCalculator:
    """Create a slotting calculator instance."""
```

### Module: `rwa_calc.engine.slotting.transforms`

Plain module-level typed functions for specialised lending (slotting)
calculations, composed via `lf.pipe(fn, config)`. (Polars namespaces are
extinct and banned — `arch_check` check 14.)

#### LazyFrame transforms

```python
def prepare_columns(lf: pl.LazyFrame, config: CalculationConfig | None = None) -> pl.LazyFrame:
    """Ensure required columns exist with defaults."""

def apply_slotting_weights(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply slotting risk weights based on category and HVCRE status.

    CRR Art. 153(5) — with maturity differentiation:
    | Category     | Non-HVCRE >=2.5yr | Non-HVCRE <2.5yr | HVCRE >=2.5yr | HVCRE <2.5yr |
    |-------------|-------------------|------------------|---------------|--------------|
    | Strong      | 70%               | 50%              | 95%           | 70%          |
    | Good        | 90%               | 70%              | 120%          | 95%          |
    | Satisfactory| 115%              | 115%             | 140%          | 140%         |
    | Weak        | 250%              | 250%             | 250%          | 250%         |
    | Default     | 0%                | 0%               | 0%            | 0%           |

    Basel 3.1 — revised weights with HVCRE differentiation.
    """

def calculate_rwa(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Calculate RWA = EAD x Risk Weight."""

def apply_all(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply complete slotting pipeline: prepare → weights → RWA."""
```

#### Expression helper

```python
def lookup_rw(category_col: pl.Expr, is_hvcre_col: str, config: CalculationConfig) -> pl.Expr:
    """Look up slotting risk weight based on category and HVCRE status."""
```

**Usage Example:**

```python
from rwa_calc.engine.slotting import transforms as slotting

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

result = specialised_lending.pipe(slotting.apply_all, config).collect()
```

## Equity Calculator

### Module: `rwa_calc.engine.equity.calculator`

Equity Calculator for Equity Exposure RWA. Implements Article 133 (SA) and
Article 155 (IRB Simple Risk Weight Method). Under Basel 3.1, IRB equity
treatment is removed — all equities use SA.

```python
class EquityCalculator:
    """Calculate RWA for equity exposures.

    Article 133 (SA): 0%/100%/250%/400% RW.
    Article 155 (IRB Simple): 0%/190%/290%/370% RW.
    Basel 3.1: IRB equity removed — all uses SA.
    """

    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """
        Calculate equity RWA and return as a bundle.

        Steps: determine approach → prepare columns → apply weights
        → calculate RWA → audit trail.

        Returns:
            EquityResultBundle with results and audit trail.
        """

```

**Factory:**

```python
def create_equity_calculator() -> EquityCalculator:
    """Create an equity calculator instance."""
```

Equity RWA is produced through `EquityCalculator.get_equity_result_bundle(...)`
(documented above). There is no separate equity transforms module or
expression accessor — the calculator owns the SA (Art. 133) and IRB-Simple
(Art. 155) weight application internally.

## Aggregator

### Module: `rwa_calc.engine.aggregator`

Output Aggregator for RWA Calculations. Combines SA, IRB, Slotting, and Equity
results with output floor (Basel 3.1), supporting factor tracking (CRR),
and portfolio-level EL summary.

```python
class OutputAggregator:
    """Aggregate final RWA results from all calculators.

    Implements OutputAggregatorProtocol for:
    - Combining results from SA, IRB, Slotting, and Equity calculators
    - Output floor application (Basel 3.1)
    - Supporting factor impact tracking (CRR)
    - Summary generation by class, approach, pre/post-CRM
    - Expected loss portfolio summary with T2 credit cap
    """

    _T2_CREDIT_CAP_RATE = 0.006  # CRR Art. 62(d)

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
        securitisation_audit: pl.LazyFrame | None = None,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate all calculator outputs into the final result bundle.

        The single public entry point — it combines SA, IRB, slotting and
        equity results, applies the output floor (Basel 3.1) and produces all
        summaries. The output-floor logic now lives in internal helpers
        (``engine/aggregator/_floor.py``); ``aggregate_with_audit`` and
        ``apply_output_floor`` are no longer public methods.

        Args:
            sa_results: SA branch results.
            irb_results: IRB branch results.
            slotting_results: Slotting branch results.
            equity_bundle: Equity result bundle (optional, separate path).
            config: Calculation configuration.
            securitisation_audit: Resolved securitisation lookup from the
                allocator stage (optional).
            pack: Resolved rulepack for the run's regime/date (Phase 5 —
                sources the output-floor / supporting-factor regime gates).
                Production threads the orchestrator's pack; direct callers may
                omit it, in which case one is resolved from ``config``.

        Returns:
            AggregatedResultBundle containing the combined exposure-level
            results, per-approach results, floor/supporting-factor impact,
            summaries (by class, by approach, pre/post-CRM), the EL portfolio
            summary, and accumulated errors.
        """
```

**Factory:**

```python
def create_output_aggregator() -> OutputAggregator:
    """Create an OutputAggregator instance."""
```

## Comparison & Impact Analysis

### Module: `rwa_calc.engine.comparison`

Dual-framework comparison, capital impact analysis, and transitional schedule
runners. These enable side-by-side CRR vs Basel 3.1 analysis for migration
planning.

#### DualFrameworkRunner

```python
class DualFrameworkRunner:
    """Run the same portfolio through CRR and Basel 3.1 pipelines and compare.

    Produces per-exposure delta columns:
    - delta_rwa: Absolute RWA change
    - delta_risk_weight: Risk weight change
    - delta_ead: EAD change
    - delta_pct: Percentage RWA change
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
            data: Raw data bundle (same data for both runs).
            crr_config: CRR framework configuration.
            b31_config: Basel 3.1 framework configuration.

        Returns:
            ComparisonBundle with per-exposure deltas and summaries.

        Raises:
            ValueError: If configs have wrong framework types.
        """
```

#### CapitalImpactAnalyzer

```python
class CapitalImpactAnalyzer:
    """Decompose the CRR vs Basel 3.1 RWA delta into regulatory drivers.

    Waterfall attribution:
    1. CRR RWA (starting point)
    2. Remove 1.06x scaling factor
    3. Remove supporting factors (SME/infrastructure)
    4. Apply Basel 3.1 methodology changes
    5. Apply output floor
    6. = Basel 3.1 RWA (ending point)
    """

    def analyze(self, comparison: ComparisonBundle) -> CapitalImpactBundle:
        """
        Decompose comparison deltas into driver-level attribution.

        Args:
            comparison: ComparisonBundle from DualFrameworkRunner.

        Returns:
            CapitalImpactBundle with per-exposure and portfolio-level
            waterfall attribution.
        """
```

#### TransitionalScheduleRunner

```python
class TransitionalScheduleRunner:
    """Model the output floor phase-in across 2027-2030.

    Output floor percentages (PRA PS1/26 Art. 92(5)):
    - 2027: 60%
    - 2028: 65%
    - 2029: 70%
    - 2030+: 72.5%
    """

    def run(
        self,
        data: RawDataBundle,
        permission_mode: PermissionMode = PermissionMode.IRB,
        reporting_dates: list[date] | None = None,
    ) -> TransitionalScheduleBundle:
        """
        Run the Basel 3.1 pipeline for each transitional year.

        Args:
            data: Raw data bundle.
            permission_mode: STANDARDISED or IRB (defaults to IRB for
                transitional analysis).
            reporting_dates: Optional custom reporting dates.
                Defaults to 2027-06-30 through 2030-06-30.

        Returns:
            TransitionalScheduleBundle with year-by-year floor impact timeline.
        """
```

**Usage Example:**

```python
from rwa_calc.engine.comparison import (
    DualFrameworkRunner,
    CapitalImpactAnalyzer,
    TransitionalScheduleRunner,
)
from rwa_calc.domain.enums import PermissionMode

# Dual-framework comparison
runner = DualFrameworkRunner()
comparison = runner.compare(data, crr_config, b31_config)

# Capital impact analysis
analyzer = CapitalImpactAnalyzer()
impact = analyzer.analyze(comparison)

# Transitional schedule
schedule_runner = TransitionalScheduleRunner()
schedule = schedule_runner.run(data, PermissionMode.IRB)
```

## FX Converter

### Module: `rwa_calc.engine.fx_converter`

Currency conversion from original currencies to the configured reporting
currency. Preserves original values in audit trail columns.

```python
class FXConverter:
    """Convert exposure and CRM amounts to reporting currency.

    Preserves original values in audit trail columns:
    - original_currency
    - original_amount
    - fx_rate_applied
    """

    def convert_exposures(
        self,
        exposures: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert exposure amounts to reporting currency.

        Converts: drawn_amount, undrawn_amount, nominal_amount, interest.
        """

    def convert_collateral(
        self,
        collateral: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Convert collateral values (market_value, nominal_value) to reporting currency."""

    def convert_guarantees(
        self,
        guarantees: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Convert guarantee amounts (amount_covered) to reporting currency."""

    def convert_provisions(
        self,
        provisions: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Convert provision amounts (amount) to reporting currency."""

    def convert_equity_exposures(
        self,
        equity_exposures: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Convert equity exposure values (carrying_value, fair_value) to reporting currency."""
```

**Factory:**

```python
def create_fx_converter() -> FXConverter:
    """Create an FX converter instance."""
```

**Usage Example:**

```python
from rwa_calc.engine.fx_converter import create_fx_converter

converter = create_fx_converter()

# Convert all monetary values to reporting currency
converted_exposures = converter.convert_exposures(exposures, fx_rates, config)
converted_collateral = converter.convert_collateral(collateral, fx_rates, config)
converted_guarantees = converter.convert_guarantees(guarantees, fx_rates, config)
converted_provisions = converter.convert_provisions(provisions, fx_rates, config)
converted_equity = converter.convert_equity_exposures(equity_exposures, fx_rates, config)
```

## Engine Utilities

### Module: `rwa_calc.engine.utils`

Shared utility functions for the RWA calculation engine.

```python
def has_rows(lf: pl.LazyFrame) -> bool:
    """Check if a LazyFrame has any rows.
    Note: triggers .head(1).collect() — prefer schema-only checks in pipeline."""

def has_required_columns(
    data: pl.LazyFrame | None,
    required_columns: set[str] | None = None,
) -> bool:
    """Check if a LazyFrame is not None and has the required columns.
    Schema-only check — does not materialise any data."""
```

## Related

- [Pipeline API](pipeline.md)
- [Contracts API](contracts.md)
- [Configuration API](configuration.md)
- [Architecture — Components](../architecture/components.md)
