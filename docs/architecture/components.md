# Component Overview

This document provides detailed documentation of each component in the RWA calculator.

## Component Summary

| Component | Module | Purpose |
|-----------|--------|---------|
| **Loader** | `engine/loader.py` | Load data from files |
| **Hierarchy Resolver** | `engine/hierarchy.py` | Resolve hierarchies |
| **Classifier** | `engine/classifier.py` | Classify exposures |
| **CRM Processor** | `engine/crm/processor.py` | Apply CRM |
| **SA Calculator** | `engine/sa/calculator.py` | Standardised RWA |
| **IRB Calculator** | `engine/irb/calculator.py` | IRB RWA |
| **Slotting Calculator** | `engine/slotting/calculator.py` | Slotting RWA |
| **Aggregator** | `engine/aggregator.py` | Combine results |

## Loader

### Purpose

Load raw data from Parquet or CSV files into LazyFrames.

### Interface

```python
class LoaderProtocol(Protocol):
    def load(self, path: Path) -> RawDataBundle:
        """Load raw data from the specified path."""
        ...
```

### Implementation

```python
class ParquetLoader:
    """Load data from Parquet files."""

    def load(self, path: Path) -> RawDataBundle:
        return RawDataBundle(
            counterparties=pl.scan_parquet(path / "counterparties.parquet"),
            facilities=pl.scan_parquet(path / "facilities.parquet"),
            loans=pl.scan_parquet(path / "loans.parquet"),
            contingents=self._load_optional(path / "contingents.parquet"),
            collateral=self._load_optional(path / "collateral.parquet"),
            guarantees=self._load_optional(path / "guarantees.parquet"),
            provisions=self._load_optional(path / "provisions.parquet"),
            ratings=self._load_optional(path / "ratings.parquet"),
            org_mapping=self._load_optional(path / "org_mapping.parquet"),
            lending_mapping=self._load_optional(path / "lending_mapping.parquet"),
        )

    def _load_optional(self, path: Path) -> pl.LazyFrame | None:
        return pl.scan_parquet(path) if path.exists() else None
```

### Key Features

- Lazy loading for performance
- Optional file handling
- Schema validation
- Error accumulation

## Hierarchy Resolver

### Purpose

Resolve counterparty and facility hierarchies, inherit ratings.

### Interface

```python
class HierarchyResolverProtocol(Protocol):
    def resolve(
        self,
        raw_data: RawDataBundle,
        config: CalculationConfig
    ) -> ResolvedHierarchyBundle:
        """Resolve hierarchies and inherit attributes."""
        ...
```

### Implementation

```python
class HierarchyResolver:
    """Resolve counterparty and lending group hierarchies."""

    def resolve(
        self,
        raw_data: RawDataBundle,
        config: CalculationConfig
    ) -> ResolvedHierarchyBundle:
        # Resolve counterparty hierarchy
        counterparties = self._resolve_counterparty_hierarchy(
            raw_data.counterparties,
            raw_data.org_mapping
        )

        # Resolve lending groups
        counterparties = self._resolve_lending_groups(
            counterparties,
            raw_data.lending_mapping
        )

        # Inherit ratings
        counterparties = self._inherit_ratings(
            counterparties,
            raw_data.ratings
        )

        # Build resolved bundle
        return ResolvedHierarchyBundle(
            counterparties=counterparties,
            facilities=raw_data.facilities,
            loans=raw_data.loans,
            # ... other data
        )
```

### Key Features

- Iterative join-based hierarchy resolution
- Support for deep hierarchies (up to 10 levels)
- Rating inheritance from parent
- Lending group aggregation

## Classifier

### Purpose

Assign regulatory exposure classes and calculation approaches.

### Interface

```python
class ClassifierProtocol(Protocol):
    def classify(
        self,
        resolved: ResolvedHierarchyBundle,
        config: CalculationConfig
    ) -> ClassifiedExposuresBundle:
        """Classify exposures into regulatory classes."""
        ...
```

### Implementation

```python
class ExposureClassifier:
    """Classify exposures by regulatory class and approach."""

    def classify(
        self,
        resolved: ResolvedHierarchyBundle,
        config: CalculationConfig
    ) -> ClassifiedExposuresBundle:
        # Classify each exposure
        classified = (
            resolved.exposures
            .with_columns(
                exposure_class=self._determine_exposure_class(
                    pl.col("counterparty_type"),
                    pl.col("is_defaulted"),
                    pl.col("total_exposure"),
                    pl.col("turnover"),
                    config
                ),
                approach_type=self._determine_approach(
                    pl.col("exposure_class"),
                    pl.col("has_irb_approval"),
                    config
                )
            )
        )

        # Calculate EAD
        classified = self._calculate_ead(classified, config)

        # Split by approach
        return ClassifiedExposuresBundle(
            sa_exposures=classified.filter(pl.col("approach_type") == "SA"),
            irb_exposures=classified.filter(pl.col("approach_type").is_in(["FIRB", "AIRB"])),
            slotting_exposures=classified.filter(pl.col("approach_type") == "SLOTTING"),
        )
```

### Key Features

- Exposure class determination
- Approach selection
- SME identification
- Retail eligibility checking
- EAD calculation with CCFs

## CRM Processor

### Purpose

Apply credit risk mitigation (collateral, guarantees, provisions).

### Interface

```python
class CRMProcessorProtocol(Protocol):
    def process(
        self,
        classified: ClassifiedExposuresBundle,
        config: CalculationConfig
    ) -> CRMAdjustedBundle:
        """Apply credit risk mitigation."""
        ...
```

### Implementation

```python
class CRMProcessor:
    """Process credit risk mitigation."""

    def process(
        self,
        classified: ClassifiedExposuresBundle,
        config: CalculationConfig
    ) -> CRMAdjustedBundle:
        # Process in order: provisions → collateral → guarantees

        # Step 1: Apply provisions
        after_provisions = self._apply_provisions(
            classified.all_exposures,
            classified.provisions
        )

        # Step 2: Apply collateral
        after_collateral = self._apply_collateral(
            after_provisions,
            classified.collateral,
            config
        )

        # Step 3: Apply guarantees
        after_guarantees = self._apply_guarantees(
            after_collateral,
            classified.guarantees,
            config
        )

        return CRMAdjustedBundle(
            sa_exposures=self._filter_sa(after_guarantees),
            irb_exposures=self._filter_irb(after_guarantees),
            slotting_exposures=self._filter_slotting(after_guarantees),
        )
```

### Key Features

- Supervisory haircut application
- Currency mismatch handling
- Maturity mismatch adjustment
- Guarantee substitution
- Provision allocation

## SA Calculator

### Purpose

Calculate RWA using the Standardised Approach.

### Interface

```python
class SACalculatorProtocol(Protocol):
    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> SAResultBundle:
        """Calculate SA RWA."""
        ...
```

### Implementation

```python
class SACalculator:
    """Calculate Standardised Approach RWA."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> SAResultBundle:
        result = (
            exposures
            # Look up risk weight
            .with_columns(
                risk_weight=self._get_risk_weight(
                    pl.col("exposure_class"),
                    pl.col("cqs"),
                    config
                )
            )
            # Calculate base RWA
            .with_columns(
                rwa_base=pl.col("ead") * pl.col("risk_weight")
            )
        )

        # Apply supporting factors (CRR only)
        if config.apply_sme_supporting_factor:
            result = self._apply_sme_factor(result, config)

        if config.apply_infrastructure_factor:
            result = self._apply_infrastructure_factor(result, config)

        return SAResultBundle(data=result)
```

### Key Features

- Risk weight lookup by class and CQS
- LTV-based real estate weights (Basel 3.1)
- SME supporting factor application
- Infrastructure factor application

## IRB Calculator

### Purpose

Calculate RWA using IRB approaches (F-IRB and A-IRB).

### Interface

```python
class IRBCalculatorProtocol(Protocol):
    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> IRBResultBundle:
        """Calculate IRB RWA."""
        ...
```

### Implementation

```python
class IRBCalculator:
    """Calculate IRB RWA using K formula."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> IRBResultBundle:
        result = (
            exposures
            # Apply PD floor
            .with_columns(
                pd=pl.max_horizontal(
                    pl.col("pd"),
                    self._get_pd_floor(pl.col("exposure_class"), config)
                )
            )
            # Apply LGD floor (A-IRB, Basel 3.1)
            .with_columns(
                lgd=self._apply_lgd_floor(
                    pl.col("lgd"),
                    pl.col("collateral_type"),
                    config
                )
            )
            # Calculate correlation
            .with_columns(
                correlation=self._calculate_correlation(
                    pl.col("exposure_class"),
                    pl.col("pd"),
                    pl.col("turnover")
                )
            )
            # Calculate K
            .with_columns(
                k=self._calculate_k(
                    pl.col("pd"),
                    pl.col("lgd"),
                    pl.col("correlation")
                )
            )
            # Calculate maturity adjustment
            .with_columns(
                ma=self._calculate_maturity_adjustment(
                    pl.col("pd"),
                    pl.col("effective_maturity")
                )
            )
            # Calculate RWA
            .with_columns(
                rwa=pl.col("k") * 12.5 * pl.col("ead") * pl.col("ma") *
                    config.scaling_factor
            )
            # Calculate expected loss
            .with_columns(
                expected_loss=pl.col("pd") * pl.col("lgd") * pl.col("ead")
            )
        )

        return IRBResultBundle(data=result)
```

### Key Features

- PD and LGD floor application
- Correlation calculation with SME adjustment
- K formula implementation
- Maturity adjustment
- Expected loss calculation
- CRR 1.06 scaling factor

## Slotting Calculator

### Purpose

Calculate RWA using the slotting approach for specialised lending.

### Interface

```python
class SlottingCalculatorProtocol(Protocol):
    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> SlottingResultBundle:
        """Calculate Slotting RWA."""
        ...
```

### Implementation

```python
class SlottingCalculator:
    """Calculate Slotting RWA for specialised lending."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig
    ) -> SlottingResultBundle:
        result = (
            exposures
            # Look up slotting risk weight
            .with_columns(
                risk_weight=self._get_slotting_weight(
                    pl.col("lending_type"),
                    pl.col("slotting_category"),
                    pl.col("is_pre_operational"),  # For project finance
                    config
                )
            )
            # Calculate RWA
            .with_columns(
                rwa=pl.col("ead") * pl.col("risk_weight")
            )
        )

        # Apply infrastructure factor (CRR only)
        if config.apply_infrastructure_factor:
            result = self._apply_infrastructure_factor(result, config)

        return SlottingResultBundle(data=result)
```

### Key Features

- Slotting category to risk weight mapping
- Pre-operational project finance handling
- HVCRE treatment
- Infrastructure factor application

## Aggregator

### Purpose

Combine results from all calculators, apply output floor.

### Interface

```python
class OutputAggregatorProtocol(Protocol):
    def aggregate(
        self,
        sa_result: SAResultBundle,
        irb_result: IRBResultBundle,
        slotting_result: SlottingResultBundle,
        config: CalculationConfig
    ) -> AggregatedResultBundle:
        """Aggregate results and apply final adjustments."""
        ...
```

### Implementation

```python
class OutputAggregator:
    """Aggregate calculation results."""

    def aggregate(
        self,
        sa_result: SAResultBundle,
        irb_result: IRBResultBundle,
        slotting_result: SlottingResultBundle,
        config: CalculationConfig
    ) -> AggregatedResultBundle:
        # Combine all results
        combined = pl.concat([
            sa_result.data.with_columns(approach=pl.lit("SA")),
            irb_result.data.with_columns(approach=pl.lit("IRB")),
            slotting_result.data.with_columns(approach=pl.lit("SLOTTING")),
        ])

        # Apply output floor (Basel 3.1)
        if config.framework == RegulatoryFramework.BASEL_3_1:
            combined = self._apply_output_floor(
                combined,
                config.output_floor_config
            )

        # Calculate totals
        totals = self._calculate_totals(combined)

        return AggregatedResultBundle(
            data=combined,
            total_rwa=totals.rwa,
            sa_rwa=totals.sa_rwa,
            irb_rwa=totals.irb_rwa,
            slotting_rwa=totals.slotting_rwa,
            total_expected_loss=totals.expected_loss,
        )
```

### Key Features

- Result combination
- Output floor application
- Floor impact calculation
- Total aggregation
- Breakdown by approach/class

## Next Steps

- [API Reference](../api/index.md) - Complete API documentation
- [Data Model](../data-model/index.md) - Schema definitions
- [Development Guide](../development/index.md) - Extending the calculator
