# Engine API

The engine module contains all calculation components. Each component implements a
structural `Protocol` (defined in `contracts/protocols.py`) and follows the immutable
pipeline pattern: receive a frozen bundle, return a new frozen bundle.

Pipeline order:

```
Loader → HierarchyResolver → ExposureClassifier → CRMProcessor
    → SA/IRB/Slotting/Equity Calculators → OutputAggregator
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

**Factory:**

```python
def create_exposure_classifier() -> ExposureClassifier:
    """Create an exposure classifier instance."""
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

    def __init__(self, is_basel_3_1: bool = False) -> None:
        """
        Args:
            is_basel_3_1: True for Basel 3.1 framework.
        """

    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Apply credit risk mitigation to exposures.

        Returns LazyFrameResult with CRM-adjusted exposures and any errors.

        Args:
            data: Classified exposures bundle.
            config: Calculation configuration.

        Returns:
            LazyFrameResult with CRM-adjusted exposures.
        """

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM and return as a bundle.

        Includes mid-pipeline collect and approach split
        (separates SA, IRB, and slotting exposures into distinct LazyFrames).

        Args:
            data: Classified exposures bundle.
            config: Calculation configuration.

        Returns:
            CRMAdjustedBundle with sa_exposures, irb_exposures,
            slotting_exposures, equity_exposures, and errors.
        """

    def get_crm_unified_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM without fan-out split.

        No mid-pipeline collect for the approach split. Returns a unified
        LazyFrame for single-pass calculator processing.

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

        Called before CCF (CRR Art. 111(2)).

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
def create_crm_processor(is_basel_3_1: bool = False) -> CRMProcessor:
    """Create a CRM processor instance."""
```

### Module: `rwa_calc.engine.crm.namespace`

Polars namespace extensions for fluent EAD waterfall processing.

#### CRMLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("crm")
class CRMLazyFrame:
    """LazyFrame namespace for CRM/EAD calculations."""

    def initialize_ead_waterfall(self) -> pl.LazyFrame:
        """
        Initialize EAD waterfall columns.

        Adds columns:
        - ead_gross: Copy of ead_pre_crm
        - ead_after_collateral: Initialized to ead_gross
        - ead_after_guarantee: Initialized to ead_gross
        - ead_final: Initialized to ead_gross
        - collateral_adjusted_value: Initialized to 0
        - guarantee_amount: Initialized to 0
        - provision_allocated: Initialized to 0
        """

    def apply_collateral(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply collateral to reduce EAD (SA) or adjust LGD (IRB).

        SA approach: Reduces EAD directly
        IRB approach: Affects LGD calculation
        """

    def apply_guarantees(
        self,
        guarantees: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution.

        Calculates guarantee coverage and applies risk weight substitution
        based on guarantor type and CQS.
        """

    def resolve_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Resolve provisions with multi-level beneficiary allocation.

        Must be called BEFORE CCF application (Art. 111(2)).

        SA: Drawn-first deduction — provision reduces max(0, drawn) first,
            remainder reduces nominal before CCF.
        IRB/Slotting: Provisions tracked (provision_allocated) but NOT
            deducted from EAD (feeds EL shortfall/excess comparison).
        """

    def apply_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Legacy provision allocation (SA only).
        Prefer resolve_provisions() for Art. 111(2) compliant processing."""

    def finalize_ead(self) -> pl.LazyFrame:
        """Finalize EAD calculation ensuring non-negative values."""

    def apply_all_crm(
        self,
        collateral: pl.LazyFrame,
        guarantees: pl.LazyFrame,
        provisions: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply complete CRM pipeline."""
```

**Usage Example:**

```python
import polars as pl
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.crm.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent CRM pipeline (Art. 111(2) compliant order)
result = (
    exposures
    .crm.resolve_provisions(provisions, config)   # Before CCF
    .crm.initialize_ead_waterfall()                # Uses nominal_after_provision
    .crm.apply_collateral(collateral, config)
    .crm.apply_guarantees(guarantees, counterparty_lookup, config)
    .crm.finalize_ead()                            # No provision subtraction
    .collect()
)
```

### Module: `rwa_calc.engine.crm.haircuts`

```python
def get_haircut(
    collateral_type: CollateralType,
    cqs: CQS | None,
    residual_maturity_years: float,
) -> float:
    """Get supervisory haircut for collateral."""
```

### Module: `rwa_calc.engine.crm.haircuts_namespace`

Polars namespace extensions for collateral haircut calculations.

#### HaircutsLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("haircuts")
class HaircutsLazyFrame:
    """LazyFrame namespace for haircut calculations."""

    def classify_maturity_band(self) -> pl.LazyFrame:
        """Classify residual maturity into regulatory bands (<=1yr, 1-3yr, etc.)."""

    def apply_collateral_haircuts(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply supervisory haircuts based on collateral type and CQS."""

    def apply_fx_haircut(self, exposure_currency_col: str) -> pl.LazyFrame:
        """Apply FX mismatch haircut (8%) when currencies differ."""

    def apply_maturity_mismatch(self, exposure_maturity_col: str) -> pl.LazyFrame:
        """Apply maturity mismatch adjustment: P_adj = P * (t - 0.25) / (T - 0.25)."""

    def calculate_adjusted_value(self) -> pl.LazyFrame:
        """Calculate final adjusted collateral value after all haircuts."""

    def apply_all_haircuts(
        self,
        exposure_currency_col: str,
        exposure_maturity_col: str,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply complete haircut pipeline."""
```

**Usage Example:**

```python
import rwa_calc.engine.crm.haircuts_namespace  # Registers namespace

result = (
    collateral
    .haircuts.classify_maturity_band()
    .haircuts.apply_collateral_haircuts(config)
    .haircuts.apply_fx_haircut("exposure_currency")
    .haircuts.apply_maturity_mismatch("exposure_maturity")
    .haircuts.calculate_adjusted_value()
    .collect()
)
```

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

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate SA RWA for all SA exposures.

        Args:
            data: CRM-adjusted bundle (uses sa_exposures field).
            config: Calculation configuration.

        Returns:
            LazyFrameResult with SA RWA calculations.
        """

    def get_sa_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA and return as a bundle.

        Steps: risk weights → guarantee substitution → RWA
        → supporting factors → audit trail.

        Returns:
            SAResultBundle with results, calculation_audit, and errors.
        """

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
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
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Expects only SA rows — no approach guards needed.
        """

    def calculate_single_exposure(
        self,
        ead: Decimal,
        exposure_class: str,
        cqs: int | None = None,
        ltv: Decimal | None = None,
        is_sme: bool = False,
        is_infrastructure: bool = False,
        is_managed_as_retail: bool = False,
        has_income_cover: bool = False,
        property_type: str | None = None,
        is_adc: bool = False,
        is_presold: bool = False,
        seniority: str = "senior",
        scra_grade: str | None = None,
        is_investment_grade: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single exposure (convenience method).

        Returns dict with: ead, exposure_class, cqs, risk_weight,
        rwa_pre_factor, supporting_factor, rwa, supporting_factor_applied.

        Example:
            >>> calculator = SACalculator()
            >>> result = calculator.calculate_single_exposure(
            ...     ead=Decimal("1000000"),
            ...     exposure_class="CORPORATE",
            ...     cqs=3,
            ... )
            >>> print(f"RWA: {result['rwa']:,.0f}")
        """
```

**Factory:**

```python
def create_sa_calculator() -> SACalculator:
    """Create an SA calculator instance."""
```

### Module: `rwa_calc.engine.sa.namespace`

Polars namespace extensions for fluent, chainable SA calculations.

#### SALazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("sa")
class SALazyFrame:
    """LazyFrame namespace for SA calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """Ensure required columns exist with sensible defaults."""

    def apply_risk_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply risk weights based on exposure class and CQS."""

    def apply_residential_mortgage_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply LTV-based risk weights for residential mortgages."""

    def apply_cqs_based_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply CQS-based risk weights for sovereigns, institutions, corporates."""

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD x Risk Weight."""

    def apply_supporting_factors(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply SME and infrastructure supporting factors (CRR only)."""

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply complete SA pipeline: prepare → risk weights → RWA → supporting factors."""
```

#### SAExpr Namespace

```python
@pl.api.register_expr_namespace("sa")
class SAExpr:
    """Expression namespace for column-level SA operations."""

    def lookup_cqs_rw(self, exposure_class_col: str, config: CalculationConfig) -> pl.Expr:
        """Look up risk weight based on CQS and exposure class."""

    def apply_ltv_weight(self, ltv_thresholds: list[tuple[float, float]]) -> pl.Expr:
        """Apply LTV-based risk weight from threshold table."""
```

**Usage Example:**

```python
import rwa_calc.engine.sa.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent SA calculation pipeline
result = exposures.sa.apply_all(config).collect()

# Or step by step
result = (
    exposures
    .sa.prepare_columns(config)
    .sa.apply_risk_weights(config)
    .sa.calculate_rwa()
    .sa.apply_supporting_factors(config)
    .collect()
)
```

### Module: `rwa_calc.engine.sa.supporting_factors`

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

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate IRB RWA for all IRB exposures.

        Args:
            data: CRM-adjusted bundle (uses irb_exposures field).
            config: Calculation configuration.

        Returns:
            LazyFrameResult with IRB RWA calculations.
        """

    def get_irb_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> IRBResultBundle:
        """
        Calculate IRB RWA and return as a bundle.

        Steps: classify approach → apply F-IRB LGD → prepare columns
        → apply all formulas → compute EL shortfall/excess
        → apply guarantee substitution.

        Returns:
            IRBResultBundle with results, expected_loss,
            calculation_audit, and errors.
        """

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply IRB formulas to IRB rows on a unified frame.

        Uses filter-process-merge to avoid running expensive IRB
        formulas on non-IRB rows.
        """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate IRB RWA on pre-filtered IRB-only rows.

        Runs the namespace chain directly — expects only IRB rows.
        """

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """Calculate expected loss for IRB exposures. EL = PD x LGD x EAD."""

    def calculate_single_exposure(
        self,
        ead: Decimal,
        pd: Decimal,
        lgd: Decimal | None = None,
        maturity: Decimal = Decimal("2.5"),
        exposure_class: str = "CORPORATE",
        turnover_m: Decimal | None = None,
        collateral_type: str | None = None,
        is_subordinated: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single exposure (convenience method).

        Returns dict with full calculation results including expected_loss.

        Example:
            >>> calculator = IRBCalculator()
            >>> result = calculator.calculate_single_exposure(
            ...     ead=Decimal("5000000"),
            ...     pd=Decimal("0.01"),
            ...     lgd=Decimal("0.45"),
            ... )
            >>> print(f"RWA: {result['rwa']:,.0f}")
        """
```

**Factory:**

```python
def create_irb_calculator() -> IRBCalculator:
    """Create an IRB calculator instance."""
```

### Module: `rwa_calc.engine.irb.namespace`

Polars namespace extensions for fluent, chainable IRB calculations.

#### IRBLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("irb")
class IRBLazyFrame:
    """LazyFrame namespace for IRB calculations."""

    def classify_approach(self, config: CalculationConfig) -> pl.LazyFrame:
        """Classify exposures as F-IRB or A-IRB. Adds: approach, is_airb."""

    def apply_firb_lgd(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply supervisory LGD for F-IRB (45% senior, 75% sub, 0% financial, 35-40% secured)."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """Ensure required columns exist with defaults (pd=0.01, lgd=0.45, maturity=2.5)."""

    def apply_all_formulas(self, config: CalculationConfig) -> pl.LazyFrame:
        """Full chain: PD floor → LGD floor → correlation → K → maturity adj → RWA → EL."""

    def apply_pd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply PD floor (0.03% CRR, differentiated Basel 3.1)."""

    def apply_lgd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply LGD floor (Basel 3.1 A-IRB only)."""

    def calculate_correlation(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate asset correlation with SME firm-size adjustment."""

    def calculate_k(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate capital requirement K using IRB formula."""

    def calculate_maturity_adjustment(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate maturity adjustment (non-retail only)."""

    def calculate_rwa(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate RWA = K x 12.5 x EAD x MA x [1.06]."""

    def calculate_expected_loss(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate expected loss = PD x LGD x EAD."""

    def select_expected_loss(self) -> pl.LazyFrame:
        """Select expected loss columns for output."""

    def build_audit(self) -> pl.LazyFrame:
        """Build audit trail with intermediate calculation values."""
```

#### IRBExpr Namespace

```python
@pl.api.register_expr_namespace("irb")
class IRBExpr:
    """Expression namespace for column-level IRB operations."""

    def floor_pd(self, floor_value: float) -> pl.Expr:
        """Floor PD values to minimum."""

    def floor_lgd(self, floor_value: float) -> pl.Expr:
        """Floor LGD values to minimum."""

    def clip_maturity(self, floor: float = 1.0, cap: float = 5.0) -> pl.Expr:
        """Clip maturity to regulatory bounds [1, 5] years."""
```

**Usage Example:**

```python
import rwa_calc.engine.irb.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent IRB calculation pipeline
result = (
    exposures
    .irb.classify_approach(config)
    .irb.apply_firb_lgd(config)
    .irb.prepare_columns(config)
    .irb.apply_all_formulas(config)
    .collect()
)

# Expression namespace
result = lf.with_columns(
    pl.col("pd").irb.floor_pd(0.0003),
    pl.col("maturity").irb.clip_maturity(1.0, 5.0),
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

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate slotting RWA for all specialised lending exposures.

        Args:
            data: CRM-adjusted bundle (uses slotting_exposures field).
            config: Calculation configuration.

        Returns:
            LazyFrameResult with slotting RWA calculations.
        """

    def get_slotting_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SlottingResultBundle:
        """
        Calculate slotting RWA and return as a bundle.

        Handles None slotting exposures by returning empty frame.

        Returns:
            SlottingResultBundle with results, calculation_audit, and errors.
        """

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply slotting weights on unified frame (single-pass pipeline).

        Filters slotting rows, applies namespace chain, concats back.
        """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA on pre-filtered slotting-only rows.

        Uses: prepare_columns → apply_slotting_weights → calculate_rwa.
        """

    def calculate_single_exposure(
        self,
        ead: Decimal,
        category: str,
        is_hvcre: bool = False,
        sl_type: str = "project_finance",
        is_short_maturity: bool = False,
        is_pre_operational: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single slotting exposure (convenience method).

        Returns dict with: ead, category, is_hvcre, sl_type,
        risk_weight, rwa, framework.
        """
```

**Factory:**

```python
def create_slotting_calculator() -> SlottingCalculator:
    """Create a slotting calculator instance."""
```

### Module: `rwa_calc.engine.slotting.namespace`

Polars namespace extensions for specialised lending calculations.

#### SlottingLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("slotting")
class SlottingLazyFrame:
    """LazyFrame namespace for slotting calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """Ensure required columns exist with defaults."""

    def apply_slotting_weights(self, config: CalculationConfig) -> pl.LazyFrame:
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

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD x Risk Weight."""

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply complete slotting pipeline: prepare → weights → RWA."""
```

#### SlottingExpr Namespace

```python
@pl.api.register_expr_namespace("slotting")
class SlottingExpr:
    """Expression namespace for column-level slotting operations."""

    def lookup_rw(self, is_hvcre_col: str, config: CalculationConfig) -> pl.Expr:
        """Look up slotting risk weight based on category and HVCRE status."""
```

**Usage Example:**

```python
import rwa_calc.engine.slotting.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

result = specialised_lending.slotting.apply_all(config).collect()
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

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA for equity exposures.

        Args:
            data: CRM-adjusted bundle (uses equity_exposures field).
            config: Calculation configuration.

        Returns:
            LazyFrameResult with equity RWA calculations.
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

    def calculate_single_exposure(
        self,
        ead: Decimal,
        equity_type: str,
        is_diversified: bool = False,
        is_speculative: bool = False,
        is_exchange_traded: bool = False,
        is_government_supported: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single equity exposure (convenience method).

        Returns dict with: ead, equity_type, effective_type, is_diversified,
        is_speculative, is_exchange_traded, is_government_supported,
        approach, article, risk_weight, rwa.

        Example:
            >>> calculator = EquityCalculator()
            >>> result = calculator.calculate_single_exposure(
            ...     ead=Decimal("1000000"),
            ...     equity_type="private_equity",
            ...     is_diversified=True,
            ... )
            >>> print(f"RWA: {result['rwa']:,.0f}")
        """
```

**Factory:**

```python
def create_equity_calculator() -> EquityCalculator:
    """Create an equity calculator instance."""
```

### Module: `rwa_calc.engine.equity.namespace`

Polars namespace extensions for fluent equity calculations.

#### EquityLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("equity")
class EquityLazyFrame:
    """LazyFrame namespace for equity calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""

    def apply_equity_weights_sa(self) -> pl.LazyFrame:
        """Apply Article 133 (SA) equity risk weights (0%/100%/250%/400%)."""

    def apply_equity_weights_irb_simple(self) -> pl.LazyFrame:
        """Apply Article 155 (IRB Simple) equity risk weights (0%/190%/290%/370%)."""

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD x Risk Weight."""

    def apply_all_sa(self, config: CalculationConfig) -> pl.LazyFrame:
        """Full SA pipeline: prepare → SA weights → RWA."""

    def apply_all_irb_simple(self, config: CalculationConfig) -> pl.LazyFrame:
        """Full IRB Simple pipeline: prepare → IRB weights → RWA."""

    def build_audit(self, approach: str = "sa") -> pl.LazyFrame:
        """Build equity calculation audit trail."""
```

#### EquityExpr Namespace

```python
@pl.api.register_expr_namespace("equity")
class EquityExpr:
    """Expression namespace for column-level equity operations."""

    def lookup_rw(self, approach: str = "sa") -> pl.Expr:
        """Look up risk weight based on equity type.
        approach: "sa" for Article 133, "irb_simple" for Article 155."""
```

**Usage Example:**

```python
import rwa_calc.engine.equity.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# SA equity calculation
result = equity_exposures.equity.apply_all_sa(config).collect()

# IRB Simple equity calculation
result = equity_exposures.equity.apply_all_irb_simple(config).collect()

# Expression namespace for lookups
df = df.with_columns(
    pl.col("equity_type").equity.lookup_rw(approach="sa").alias("risk_weight"),
)
```

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
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Aggregate SA and IRB results into final output.

        Args:
            sa_results: SA calculation results LazyFrame.
            irb_results: IRB calculation results LazyFrame.
            config: Calculation configuration.

        Returns:
            Combined LazyFrame with final RWA.
        """

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
        equity_bundle: EquityResultBundle | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate with full audit trail and summaries.

        Returns AggregatedResultBundle containing:
        - results: Combined exposure-level results
        - sa_results, irb_results, slotting_results, equity_results: Per-approach results
        - floor_impact: Output floor impact analysis (Basel 3.1)
        - supporting_factor_impact: Supporting factor savings (CRR)
        - summary_by_class: RWA summary by exposure class
        - summary_by_approach: RWA summary by calculation approach
        - pre_crm_summary: Pre-CRM RWA summary
        - post_crm_detailed: Post-CRM exposure-level detail
        - post_crm_summary: Post-CRM aggregated summary
        - el_summary: Expected loss portfolio summary (ELPortfolioSummary)
        - errors: Accumulated errors
        """

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply output floor to IRB RWA (Basel 3.1 only).

        Final RWA = max(IRB RWA, SA RWA x floor_percentage).

        Transitional phase-in: 50% (2027) → 55% (2028) → 60% (2029)
        → 65% (2030) → 70% (2031) → 72.5% (2032+).
        """
```

**Factory:**

```python
def create_output_aggregator() -> OutputAggregator:
    """Create an OutputAggregator instance."""
```

## Audit Namespace

### Module: `rwa_calc.engine.audit_namespace`

Shared formatting utilities and audit trail builders for all calculation approaches.

#### AuditLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("audit")
class AuditLazyFrame:
    """LazyFrame namespace for audit trail generation."""

    def build_sa_calculation(self) -> pl.LazyFrame:
        """SA audit: SA: EAD={ead} x RW={rw}% x SF={sf}% -> RWA={rwa}"""

    def build_irb_calculation(self) -> pl.LazyFrame:
        """IRB audit: IRB: PD={pd}%, LGD={lgd}%, R={corr}%, K={k}%, MA={ma} -> RWA={rwa}"""

    def build_slotting_calculation(self) -> pl.LazyFrame:
        """Slotting audit: Slotting: Category={cat} (HVCRE?), RW={rw}% -> RWA={rwa}"""

    def build_crm_calculation(self) -> pl.LazyFrame:
        """CRM audit: EAD: gross={gross}; coll={coll}; guar={guar}; prov={prov}; final={final}"""

    def build_haircut_calculation(self) -> pl.LazyFrame:
        """Haircut audit: MV={mv}; Hc={hc}%; Hfx={hfx}%; Adj={adj}"""

    def build_floor_calculation(self) -> pl.LazyFrame:
        """Floor audit: Floor: IRB RWA={irb}; Floor RWA={floor} ({pct}%); Final={final}"""
```

#### AuditExpr Namespace

```python
@pl.api.register_expr_namespace("audit")
class AuditExpr:
    """Expression namespace for audit formatting."""

    def format_currency(self, decimals: int = 0) -> pl.Expr:
        """Format value as currency string (no symbol)."""

    def format_percent(self, decimals: int = 1) -> pl.Expr:
        """Format value as percentage string (e.g., '20.0%')."""

    def format_ratio(self, decimals: int = 3) -> pl.Expr:
        """Format value as ratio/decimal string."""

    def format_bps(self, decimals: int = 0) -> pl.Expr:
        """Format value as basis points string (e.g., '150 bps')."""
```

**Usage Example:**

```python
import rwa_calc.engine.audit_namespace  # Registers namespace

# Build audit trails
audited_sa = sa_results.audit.build_sa_calculation()
audited_irb = irb_results.audit.build_irb_calculation()

# Format individual columns
formatted = df.with_columns(
    pl.col("ead").audit.format_currency().alias("ead_formatted"),
    pl.col("risk_weight").audit.format_percent().alias("rw_formatted"),
    pl.col("pd").audit.format_bps().alias("pd_bps"),
)
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
    """Model the output floor phase-in across 2027-2032.

    Output floor percentages:
    - 2027: 50%
    - 2028: 55%
    - 2029: 60%
    - 2030: 65%
    - 2031: 70%
    - 2032+: 72.5%
    """

    def run(
        self,
        data: RawDataBundle,
        irb_permissions: IRBPermissions,
        reporting_dates: list[date] | None = None,
    ) -> TransitionalScheduleBundle:
        """
        Run the Basel 3.1 pipeline for each transitional year.

        Args:
            data: Raw data bundle.
            irb_permissions: IRB permissions configuration.
            reporting_dates: Optional custom reporting dates.
                Defaults to 2027-06-30 through 2032-06-30.

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

# Dual-framework comparison
runner = DualFrameworkRunner()
comparison = runner.compare(data, crr_config, b31_config)

# Capital impact analysis
analyzer = CapitalImpactAnalyzer()
impact = analyzer.analyze(comparison)

# Transitional schedule
schedule_runner = TransitionalScheduleRunner()
schedule = schedule_runner.run(data, irb_permissions)
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
