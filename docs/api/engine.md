# Engine API

The engine module contains all calculation components.

## Loader

### Module: `rwa_calc.engine.loader`

```python
class ParquetLoader:
    """Load data from Parquet files."""

    def load(self, path: Path) -> RawDataBundle:
        """
        Load all data files from directory.

        Args:
            path: Directory containing Parquet files.

        Returns:
            RawDataBundle: Loaded data.

        Example:
            >>> loader = ParquetLoader()
            >>> data = loader.load(Path("./data"))
        """
```

## Hierarchy Resolver

### Module: `rwa_calc.engine.hierarchy`

```python
class HierarchyResolver:
    """Resolve counterparty and facility hierarchies."""

    def resolve(
        self,
        raw_data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """
        Resolve hierarchies and inherit attributes.

        Args:
            raw_data: Raw data bundle.
            config: Calculation configuration.

        Returns:
            ResolvedHierarchyBundle: Resolved data.
        """
```

### Module: `rwa_calc.engine.hierarchy_namespace`

The Hierarchy module provides Polars namespace extensions for counterparty and facility hierarchy resolution.

#### HierarchyLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("hierarchy")
class HierarchyLazyFrame:
    """LazyFrame namespace for hierarchy operations."""

    def resolve_ultimate_parent(
        self,
        org_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """
        Resolve ultimate parent for each counterparty.

        Uses iterative join-based traversal (not recursive Python).

        Adds columns:
        - ultimate_parent_reference: The root parent
        - hierarchy_depth: Number of levels to root
        """

    def calculate_hierarchy_depth(self) -> pl.LazyFrame:
        """Calculate depth in hierarchy for each entity."""

    def inherit_ratings(
        self,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Inherit ratings from ultimate parent.

        If entity has own rating, use it.
        Otherwise, inherit from ultimate parent.

        Adds columns:
        - cqs: Credit quality step (own or inherited)
        - pd: Probability of default (own or inherited)
        - rating_value: Rating value (own or inherited)
        """

    def coalesce_ratings(self) -> pl.LazyFrame:
        """Coalesce own rating with inherited rating."""

    def calculate_lending_group_totals(
        self,
        lending_mappings: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Calculate aggregate exposure for lending groups.

        Adds columns:
        - total_exposure: Sum of exposures in lending group
        - exposure_count: Number of exposures in group
        """

    def add_lending_group_reference(
        self,
        lending_mappings: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Add lending group reference to exposures."""

    def add_collateral_ltv(self, collateral: pl.LazyFrame) -> pl.LazyFrame:
        """Add LTV from collateral to exposures."""
```

**Usage Example:**

```python
import polars as pl
import rwa_calc.engine.hierarchy_namespace  # Registers namespace

# Resolve ultimate parents
counterparties_with_parents = (
    counterparties
    .hierarchy.resolve_ultimate_parent(org_mappings, max_depth=10)
)

# Inherit ratings from parents
counterparties_with_ratings = (
    counterparties
    .hierarchy.inherit_ratings(ratings, ultimate_parents)
)

# Calculate lending group totals
exposures_with_groups = (
    exposures
    .hierarchy.calculate_lending_group_totals(lending_mappings)
)
```

## Classifier

### Module: `rwa_calc.engine.classifier`

```python
class ExposureClassifier:
    """Classify exposures by regulatory class and approach."""

    def classify(
        self,
        resolved: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """
        Classify all exposures.

        Args:
            resolved: Resolved hierarchy bundle.
            config: Calculation configuration.

        Returns:
            ClassifiedExposuresBundle: Classified exposures.
        """
```

## CCF Calculator

### Module: `rwa_calc.engine.ccf`

```python
def get_ccf(
    item_type: str,
    is_unconditionally_cancellable: bool,
    original_maturity_years: float,
    framework: RegulatoryFramework,
) -> float:
    """
    Get credit conversion factor.

    Args:
        item_type: Type of off-balance sheet item.
        is_unconditionally_cancellable: Whether unconditionally cancellable.
        original_maturity_years: Original maturity in years.
        framework: Regulatory framework.

    Returns:
        float: Credit conversion factor (0.0 to 1.0).

    Example:
        >>> ccf = get_ccf(
        ...     item_type="UNDRAWN_COMMITMENT",
        ...     is_unconditionally_cancellable=False,
        ...     original_maturity_years=3,
        ...     framework=RegulatoryFramework.CRR,
        ... )
        >>> print(f"CCF: {ccf:.0%}")
        CCF: 50%
    """
```

## CRM Processor

### Module: `rwa_calc.engine.crm.processor`

```python
class CRMProcessor:
    """Process credit risk mitigation."""

    def process(
        self,
        classified: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM to all exposures.

        Args:
            classified: Classified exposures.
            config: Calculation configuration.

        Returns:
            CRMAdjustedBundle: CRM-adjusted exposures.
        """
```

### Module: `rwa_calc.engine.crm.namespace`

The CRM module provides Polars namespace extensions for fluent EAD waterfall processing.

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

    def apply_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply provision allocation (SA only).

        SA: Deducts provisions from EAD
        IRB: No deduction (EL comparison handled separately)
        """

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

# Fluent CRM pipeline
result = (
    exposures
    .crm.initialize_ead_waterfall()
    .crm.apply_collateral(collateral, config)
    .crm.apply_guarantees(guarantees, counterparty_lookup, config)
    .crm.apply_provisions(provisions, config)
    .crm.finalize_ead()
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
    """
    Get supervisory haircut for collateral.

    Args:
        collateral_type: Type of collateral.
        cqs: Credit quality step of issuer (for bonds).
        residual_maturity_years: Residual maturity.

    Returns:
        float: Haircut percentage (0.0 to 1.0).
    """
```

### Module: `rwa_calc.engine.crm.haircuts_namespace`

The Haircuts module provides Polars namespace extensions for collateral haircut calculations.

#### HaircutsLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("haircuts")
class HaircutsLazyFrame:
    """LazyFrame namespace for haircut calculations."""

    def classify_maturity_band(self) -> pl.LazyFrame:
        """
        Classify residual maturity into regulatory bands.

        Bands: <=1yr, 1-3yr, 3-5yr, 5-7yr, 7-10yr, >10yr
        """

    def apply_collateral_haircuts(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply supervisory haircuts based on collateral type and CQS.

        Handles:
        - Cash: 0%
        - Gold: 15%
        - Government bonds: 0.5%-15% by CQS and maturity
        - Corporate bonds: 1%-30% by CQS and maturity
        - Equities: 15%-25%
        - Other physical: 40%
        """

    def apply_fx_haircut(self, exposure_currency_col: str) -> pl.LazyFrame:
        """
        Apply FX mismatch haircut (8%) when currencies differ.
        """

    def apply_maturity_mismatch(self, exposure_maturity_col: str) -> pl.LazyFrame:
        """
        Apply maturity mismatch adjustment.

        P_adj = P × (t - 0.25) / (T - 0.25)
        where t = collateral maturity, T = exposure maturity
        """

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
import polars as pl
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.crm.haircuts_namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent haircut calculation
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

```python
class SACalculator:
    """Calculate Standardised Approach RWA."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA for all exposures.

        Args:
            exposures: CRM-adjusted exposures.
            config: Calculation configuration.

        Returns:
            SAResultBundle: SA calculation results.
        """
```

### Module: `rwa_calc.engine.sa.namespace`

The SA module provides Polars namespace extensions for fluent, chainable SA calculations.

#### SALazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("sa")
class SALazyFrame:
    """LazyFrame namespace for SA calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure required columns exist with sensible defaults.

        Adds columns:
        - risk_weight: Initialized to 1.0
        - supporting_factor: Initialized to 1.0
        """

    def apply_risk_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply risk weights based on exposure class and CQS.

        Handles:
        - Sovereign CQS-based weights
        - Institution CQS-based weights (with UK deviation for CQS 2)
        - Corporate CQS-based and unrated weights
        - Retail flat weights
        - Residential mortgage LTV-based weights
        - Commercial real estate weights
        """

    def apply_residential_mortgage_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply LTV-based risk weights for residential mortgages."""

    def apply_cqs_based_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply CQS-based risk weights for sovereigns, institutions, corporates."""

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD × Risk Weight."""

    def apply_supporting_factors(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors (CRR only).

        SME tiered factor: 0.7619 (≤EUR 2.5m) / 0.85 (>EUR 2.5m)
        Infrastructure factor: 0.75
        """

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply complete SA calculation pipeline.

        Chains: prepare_columns -> apply_risk_weights -> calculate_rwa
        -> apply_supporting_factors
        """
```

#### SAExpr Namespace

```python
@pl.api.register_expr_namespace("sa")
class SAExpr:
    """Expression namespace for column-level SA operations."""

    def lookup_cqs_rw(
        self,
        exposure_class_col: str,
        config: CalculationConfig,
    ) -> pl.Expr:
        """Look up risk weight based on CQS and exposure class."""

    def apply_ltv_weight(self, ltv_thresholds: list[tuple[float, float]]) -> pl.Expr:
        """Apply LTV-based risk weight from threshold table."""
```

**Usage Example:**

```python
import polars as pl
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.sa.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent SA calculation pipeline
result = (
    exposures
    .sa.prepare_columns(config)
    .sa.apply_risk_weights(config)
    .sa.calculate_rwa()
    .sa.apply_supporting_factors(config)
    .collect()
)

# Or use the convenience method
result = exposures.sa.apply_all(config).collect()
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

    Args:
        total_exposure: Total exposure to counterparty.
        threshold: Tiered threshold (EUR 2.5m).
        factor_below: Factor for exposure below threshold.
        factor_above: Factor for exposure above threshold.

    Returns:
        float: SME supporting factor.

    Example:
        >>> factor = calculate_sme_factor(
        ...     total_exposure=5_000_000,
        ...     threshold=2_500_000,
        ... )
        >>> print(f"Factor: {factor:.4f}")
        Factor: 0.8110
    """
```

## IRB Calculator

### Module: `rwa_calc.engine.irb.calculator`

```python
class IRBCalculator:
    """Calculate IRB RWA."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> IRBResultBundle:
        """
        Calculate IRB RWA for all exposures.

        Args:
            exposures: CRM-adjusted exposures.
            config: Calculation configuration.

        Returns:
            IRBResultBundle: IRB calculation results.
        """
```

### Module: `rwa_calc.engine.irb.namespace`

The IRB module provides Polars namespace extensions for fluent, chainable IRB calculations.

#### IRBLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("irb")
class IRBLazyFrame:
    """LazyFrame namespace for IRB calculations."""

    def classify_approach(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Classify exposures as F-IRB or A-IRB.

        Adds columns:
        - approach: "F-IRB" or "A-IRB"
        - is_airb: Boolean flag
        """

    def apply_firb_lgd(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply supervisory LGD for F-IRB exposures.

        F-IRB supervisory LGD values:
        - Senior unsecured: 45%
        - Subordinated: 75%
        - Financial collateral: 0%
        - Other secured: 35-40%
        """

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure required columns exist with defaults.

        Sets defaults for missing columns:
        - pd: 0.01 (1%)
        - lgd: 0.45 (45%)
        - maturity: 2.5 years
        - exposure_class: "CORPORATE"
        """

    def apply_all_formulas(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply complete IRB calculation pipeline.

        Chains: apply_pd_floor -> apply_lgd_floor -> calculate_correlation
        -> calculate_k -> calculate_maturity_adjustment -> calculate_rwa
        -> calculate_expected_loss
        """

    def apply_pd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply PD floor based on framework (0.03% CRR, 0.05% Basel 3.1)."""

    def apply_lgd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply LGD floor (Basel 3.1 A-IRB only)."""

    def calculate_correlation(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate asset correlation with SME adjustment."""

    def calculate_k(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate capital requirement K using IRB formula."""

    def calculate_maturity_adjustment(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate maturity adjustment (non-retail only)."""

    def calculate_rwa(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate RWA = K × 12.5 × EAD × MA × [1.06]."""

    def calculate_expected_loss(self, config: CalculationConfig) -> pl.LazyFrame:
        """Calculate expected loss = PD × LGD × EAD."""

    def select_expected_loss(self) -> pl.LazyFrame:
        """Select expected loss columns for output."""

    def build_audit(self) -> pl.LazyFrame:
        """Build audit trail with intermediate calculation values."""
```

**Usage Example:**

```python
import polars as pl
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
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
# Use expression namespace directly
result = lf.with_columns(
    pl.col("pd").irb.floor_pd(0.0003),
    pl.col("maturity").irb.clip_maturity(1.0, 5.0),
)
```

### Module: `rwa_calc.engine.irb.formulas`

```python
def calculate_k(
    pd: float,
    lgd: float,
    correlation: float,
) -> float:
    """
    Calculate IRB capital requirement (K).

    Args:
        pd: Probability of default.
        lgd: Loss given default.
        correlation: Asset correlation.

    Returns:
        float: Capital requirement K.

    Example:
        >>> k = calculate_k(pd=0.01, lgd=0.45, correlation=0.20)
        >>> print(f"K: {k:.4f}")
    """

def calculate_correlation(
    exposure_class: ExposureClass,
    pd: float,
    turnover: float | None = None,
) -> float:
    """
    Calculate asset correlation.

    Args:
        exposure_class: Regulatory exposure class.
        pd: Probability of default.
        turnover: Counterparty turnover (for SME adjustment).

    Returns:
        float: Asset correlation.
    """

def calculate_maturity_adjustment(
    pd: float,
    effective_maturity: float,
) -> float:
    """
    Calculate maturity adjustment factor.

    Args:
        pd: Probability of default.
        effective_maturity: Effective maturity in years.

    Returns:
        float: Maturity adjustment factor.
    """
```

## Slotting Calculator

### Module: `rwa_calc.engine.slotting.calculator`

```python
class SlottingCalculator:
    """Calculate Slotting RWA for specialised lending."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> SlottingResultBundle:
        """
        Calculate Slotting RWA for all exposures.

        Args:
            exposures: CRM-adjusted exposures.
            config: Calculation configuration.

        Returns:
            SlottingResultBundle: Slotting calculation results.
        """
```

### Module: `rwa_calc.engine.slotting.namespace`

The Slotting module provides Polars namespace extensions for specialised lending calculations.

#### SlottingLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("slotting")
class SlottingLazyFrame:
    """LazyFrame namespace for slotting calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure required columns exist with defaults.

        Adds columns:
        - slotting_category: Default "unrated"
        - is_hvcre: Default False
        - risk_weight: Initialized to 1.0
        """

    def apply_slotting_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply slotting risk weights based on category.

        CRR Risk Weights (Strong=Good=70%, HVCRE same as standard):
        - Strong: 70%
        - Good: 70%
        - Satisfactory: 115%
        - Weak: 250%
        - Default: 0% (deducted)

        Basel 3.1 Risk Weights:
        - Strong: 50% (HVCRE: 70%)
        - Good: 70% (HVCRE: 95%)
        - Satisfactory: 100% (HVCRE: 125%)
        - Weak: 250%
        - Default: 0%
        """

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD × Risk Weight."""

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply complete slotting calculation pipeline.

        Chains: prepare_columns -> apply_slotting_weights -> calculate_rwa
        """
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
import polars as pl
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.slotting.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent slotting calculation
result = (
    specialised_lending
    .slotting.prepare_columns(config)
    .slotting.apply_slotting_weights(config)
    .slotting.calculate_rwa()
    .collect()
)

# Or use the convenience method
result = specialised_lending.slotting.apply_all(config).collect()
```

## Equity Calculator

### Module: `rwa_calc.engine.equity.calculator`

```python
class EquityCalculator:
    """
    Calculate RWA for equity exposures.

    Supports two approaches under CRR:
    - Article 133: Standardised Approach (100%/250%/400% RW)
    - Article 155: IRB Simple Risk Weight (190%/290%/370% RW)

    The approach is determined by config.irb_approach_option:
    - SA_ONLY: Uses Article 133
    - FIRB/AIRB: Uses Article 155
    """

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA for equity exposures.

        Args:
            data: CRM-adjusted exposures (uses equity_exposures field).
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

        Args:
            data: CRM-adjusted exposures.
            config: Calculation configuration.

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

        Args:
            ead: Exposure at default.
            equity_type: Type of equity exposure.
            is_diversified: Whether in diversified portfolio (for PE).
            is_speculative: Whether speculative unlisted.
            is_exchange_traded: Whether exchange traded.
            is_government_supported: Whether government supported.
            config: Calculation configuration (defaults to CRR SA).

        Returns:
            Dictionary with calculation results.

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

### Module: `rwa_calc.engine.equity.namespace`

The Equity module provides Polars namespace extensions for fluent equity calculations.

#### EquityLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("equity")
class EquityLazyFrame:
    """LazyFrame namespace for equity calculations."""

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure all required columns exist with defaults.

        Adds/normalizes:
        - ead_final: Exposure at default (from fair_value/carrying_value)
        - equity_type: Type of equity exposure
        - is_diversified_portfolio: Whether in diversified portfolio
        - is_speculative: Whether speculative unlisted
        - is_exchange_traded: Whether exchange traded
        - is_government_supported: Whether government supported
        """

    def apply_equity_weights_sa(self) -> pl.LazyFrame:
        """
        Apply Article 133 (SA) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Listed/Exchange-traded/Government-supported: 100%
        - Unlisted/Private equity: 250%
        - Speculative: 400%
        """

    def apply_equity_weights_irb_simple(self) -> pl.LazyFrame:
        """
        Apply Article 155 (IRB Simple) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Private equity (diversified portfolio): 190%
        - Government-supported: 190%
        - Exchange-traded/Listed: 290%
        - Other equity: 370%
        """

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD × Risk Weight."""

    def apply_all_sa(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full equity SA calculation pipeline.

        Chains: prepare_columns -> apply_equity_weights_sa -> calculate_rwa
        """

    def apply_all_irb_simple(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full equity IRB Simple calculation pipeline.

        Chains: prepare_columns -> apply_equity_weights_irb_simple -> calculate_rwa
        """

    def build_audit(self, approach: str = "sa") -> pl.LazyFrame:
        """
        Build equity calculation audit trail.

        Format: Equity (Art. 133 SA): Type={type}, RW={rw}%, RWA={rwa}
        """
```

#### EquityExpr Namespace

```python
@pl.api.register_expr_namespace("equity")
class EquityExpr:
    """Expression namespace for column-level equity operations."""

    def lookup_rw(self, approach: str = "sa") -> pl.Expr:
        """
        Look up risk weight based on equity type.

        Args:
            approach: "sa" for Article 133, "irb_simple" for Article 155

        Returns:
            Expression with risk weight
        """
```

**Usage Example:**

```python
import polars as pl
from datetime import date
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.equity.namespace  # Registers namespace

config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))

# Fluent equity calculation (SA)
result = (
    equity_exposures
    .equity.prepare_columns(config)
    .equity.apply_equity_weights_sa()
    .equity.calculate_rwa()
    .collect()
)

# Or use the convenience method for IRB Simple
result = equity_exposures.equity.apply_all_irb_simple(config).collect()

# Use expression namespace for lookups
df = df.with_columns(
    pl.col("equity_type").equity.lookup_rw(approach="sa").alias("risk_weight"),
)
```

## Aggregator

### Module: `rwa_calc.engine.aggregator`

```python
class OutputAggregator:
    """Aggregate calculation results."""

    def aggregate(
        self,
        sa_result: SAResultBundle,
        irb_result: IRBResultBundle,
        slotting_result: SlottingResultBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Aggregate results and apply final adjustments.

        Args:
            sa_result: SA calculation results.
            irb_result: IRB calculation results.
            slotting_result: Slotting calculation results.
            config: Calculation configuration.

        Returns:
            AggregatedResultBundle: Final aggregated results.
        """
```

### Module: `rwa_calc.engine.aggregator_namespace`

The Aggregator module provides Polars namespace extensions for result combination and output floor application.

#### AggregatorLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("aggregator")
class AggregatorLazyFrame:
    """LazyFrame namespace for result aggregation."""

    def combine_approach_results(
        self,
        sa: pl.LazyFrame | None = None,
        irb: pl.LazyFrame | None = None,
        slotting: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Combine results from all calculation approaches.

        Adds column:
        - approach_applied: SA, FIRB, AIRB, or SLOTTING
        """

    def apply_output_floor(
        self,
        sa_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Basel 3.1 output floor.

        Floor = floor_pct × SA equivalent RWA
        Final RWA = max(IRB RWA, Floor RWA)

        Adds columns:
        - floor_rwa: Floor RWA amount
        - is_floor_binding: Whether floor exceeds IRB RWA
        - rwa_final: Final RWA after floor
        """

    def calculate_floor_impact(self) -> pl.LazyFrame:
        """Calculate impact of output floor on RWA."""

    def generate_summary_by_class(self) -> pl.LazyFrame:
        """
        Generate RWA summary by exposure class.

        Returns:
        - exposure_class: Regulatory class
        - exposure_count: Number of exposures
        - total_ead: Sum of EAD
        - total_rwa: Sum of RWA
        - average_rw: Weighted average risk weight
        """

    def generate_summary_by_approach(self) -> pl.LazyFrame:
        """
        Generate RWA summary by calculation approach.

        Returns:
        - approach_applied: SA, FIRB, AIRB, SLOTTING
        - exposure_count: Number of exposures
        - total_ead: Sum of EAD
        - total_rwa: Sum of RWA
        """

    def generate_supporting_factor_impact(self) -> pl.LazyFrame:
        """Generate summary of supporting factor impact on RWA."""
```

**Usage Example:**

```python
import polars as pl
from rwa_calc.contracts.config import CalculationConfig
import rwa_calc.engine.aggregator_namespace  # Registers namespace

config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

# Combine results and apply output floor
final_results = (
    combined_results
    .aggregator.combine_approach_results(sa=sa_results, irb=irb_results)
    .aggregator.apply_output_floor(sa_for_floor, config)
)

# Generate summaries
by_class = final_results.aggregator.generate_summary_by_class()
by_approach = final_results.aggregator.generate_summary_by_approach()
```

## Audit Namespace

### Module: `rwa_calc.engine.audit_namespace`

The Audit module provides shared formatting utilities and audit trail builders for all calculation approaches.

#### AuditLazyFrame Namespace

```python
@pl.api.register_lazyframe_namespace("audit")
class AuditLazyFrame:
    """LazyFrame namespace for audit trail generation."""

    def build_sa_calculation(self) -> pl.LazyFrame:
        """
        Build SA calculation audit trail.

        Format: SA: EAD={ead} × RW={rw}% × SF={sf}% → RWA={rwa}

        Adds column: sa_calculation
        """

    def build_irb_calculation(self) -> pl.LazyFrame:
        """
        Build IRB calculation audit trail.

        Format: IRB: PD={pd}%, LGD={lgd}%, R={corr}%, K={k}%, MA={ma} → RWA={rwa}

        Adds column: irb_calculation
        """

    def build_slotting_calculation(self) -> pl.LazyFrame:
        """
        Build slotting calculation audit trail.

        Format: Slotting: Category={cat} (HVCRE?), RW={rw}% → RWA={rwa}

        Adds column: slotting_calculation
        """

    def build_crm_calculation(self) -> pl.LazyFrame:
        """
        Build CRM/EAD waterfall audit trail.

        Format: EAD: gross={gross}; coll={coll}; guar={guar}; prov={prov}; final={final}

        Adds column: crm_calculation
        """

    def build_haircut_calculation(self) -> pl.LazyFrame:
        """
        Build haircut audit trail.

        Format: MV={mv}; Hc={hc}%; Hfx={hfx}%; Adj={adj}

        Adds column: haircut_calculation
        """

    def build_floor_calculation(self) -> pl.LazyFrame:
        """
        Build output floor audit trail.

        Format: Floor: IRB RWA={irb}; Floor RWA={floor} ({pct}%); Final={final}; Binding={binding}

        Adds column: floor_calculation
        """
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
import polars as pl
import rwa_calc.engine.audit_namespace  # Registers namespace

# Build audit trails for SA exposures
audited_sa = sa_results.audit.build_sa_calculation()

# Build audit trails for IRB exposures
audited_irb = irb_results.audit.build_irb_calculation()

# Format individual columns
formatted = df.with_columns(
    pl.col("ead").audit.format_currency().alias("ead_formatted"),
    pl.col("risk_weight").audit.format_percent().alias("rw_formatted"),
    pl.col("pd").audit.format_bps().alias("pd_bps"),
)
```

## FX Converter

### Module: `rwa_calc.engine.fx_converter`

```python
class FXConverter:
    """Convert monetary values to base currency."""

    def convert_exposures(
        self,
        exposures: pl.LazyFrame,
        fx_rates: pl.LazyFrame,
        base_currency: str = "GBP",
    ) -> pl.LazyFrame:
        """
        Convert exposure amounts to base currency.

        Converts drawn_amount, undrawn_amount, nominal_amount.
        Preserves original values in audit columns.

        Args:
            exposures: Exposures with currency column.
            fx_rates: FX rate lookup table.
            base_currency: Target currency.

        Returns:
            LazyFrame with converted amounts.
        """

    def convert_collateral(
        self,
        collateral: pl.LazyFrame,
        fx_rates: pl.LazyFrame,
        base_currency: str = "GBP",
    ) -> pl.LazyFrame:
        """
        Convert collateral values to base currency.

        Converts market_value, nominal_value.
        """

    def convert_guarantees(
        self,
        guarantees: pl.LazyFrame,
        fx_rates: pl.LazyFrame,
        base_currency: str = "GBP",
    ) -> pl.LazyFrame:
        """Convert guarantee covered amounts to base currency."""

    def convert_provisions(
        self,
        provisions: pl.LazyFrame,
        fx_rates: pl.LazyFrame,
        base_currency: str = "GBP",
    ) -> pl.LazyFrame:
        """Convert provision amounts to base currency."""
```

**Usage Example:**

```python
from rwa_calc.engine.fx_converter import create_fx_converter

converter = create_fx_converter()

# Convert all monetary values to GBP
converted_exposures = converter.convert_exposures(
    exposures, fx_rates, base_currency="GBP"
)
converted_collateral = converter.convert_collateral(
    collateral, fx_rates, base_currency="GBP"
)
```

**Audit Trail:** Each conversion adds `original_currency`, `original_amount`, and `fx_rate_applied` columns for traceability.

## Related

- [Pipeline API](pipeline.md)
- [Contracts API](contracts.md)
- [Architecture - Components](../architecture/components.md)
