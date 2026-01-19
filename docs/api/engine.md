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

## Related

- [Pipeline API](pipeline.md)
- [Contracts API](contracts.md)
- [Architecture - Components](../architecture/components.md)
