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

## Polars Namespace Extensions

The calculator uses Polars namespace extensions to provide fluent, chainable APIs for calculations. Each namespace is registered when its module is imported.

| Namespace | Module | Description |
|-----------|--------|-------------|
| `lf.sa` | `engine/sa/namespace.py` | SA risk weights, RWA, supporting factors |
| `lf.irb` | `engine/irb/namespace.py` | IRB formulas, K calculation, floors |
| `lf.crm` | `engine/crm/namespace.py` | EAD waterfall, collateral, guarantees |
| `lf.haircuts` | `engine/crm/haircuts_namespace.py` | Supervisory haircuts, FX/maturity mismatch |
| `lf.slotting` | `engine/slotting/namespace.py` | Slotting risk weights |
| `lf.hierarchy` | `engine/hierarchy_namespace.py` | Parent resolution, rating inheritance |
| `lf.aggregator` | `engine/aggregator_namespace.py` | Result combination, output floor |
| `lf.audit` | `engine/audit_namespace.py` | Audit trail formatting |
| `expr.audit` | `engine/audit_namespace.py` | Column formatting (currency, %, bps) |

All namespaces are automatically registered when importing from `rwa_calc.engine`:

```python
from rwa_calc.engine import (
    SALazyFrame, IRBLazyFrame, CRMLazyFrame,
    HaircutsLazyFrame, SlottingLazyFrame,
    HierarchyLazyFrame, AggregatorLazyFrame,
    AuditLazyFrame, AuditExpr,
)
```

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

Assign regulatory exposure classes and calculation approaches based on counterparty entity type.

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

### Entity Type Mappings

The classifier uses `entity_type` as the **single source of truth** for exposure class determination. Two separate mappings exist for SA and IRB approaches:

**ENTITY_TYPE_TO_SA_CLASS** - Maps to SA exposure class for risk weight lookup:

| Entity Type | SA Class |
|-------------|----------|
| `sovereign`, `central_bank` | CENTRAL_GOVT_CENTRAL_BANK |
| `rgla_sovereign`, `rgla_institution` | RGLA |
| `pse_sovereign`, `pse_institution` | PSE |
| `mdb`, `international_org` | MDB |
| `institution`, `bank`, `ccp`, `financial_institution` | INSTITUTION |
| `corporate`, `company` | CORPORATE |
| `individual`, `retail` | RETAIL_OTHER |
| `specialised_lending` | SPECIALISED_LENDING |

**ENTITY_TYPE_TO_IRB_CLASS** - Maps to IRB exposure class for formula selection:

| Entity Type | IRB Class | Notes |
|-------------|-----------|-------|
| `sovereign`, `central_bank` | CENTRAL_GOVT_CENTRAL_BANK | |
| `rgla_sovereign`, `pse_sovereign` | CENTRAL_GOVT_CENTRAL_BANK | Govt-backed = central govt IRB treatment |
| `rgla_institution`, `pse_institution` | INSTITUTION | Commercial = institution IRB treatment |
| `mdb`, `international_org` | CENTRAL_GOVT_CENTRAL_BANK | CRR Art. 147(3) |
| `institution`, `bank`, `ccp`, `financial_institution` | INSTITUTION | |
| `corporate`, `company` | CORPORATE | |
| `individual`, `retail` | RETAIL_OTHER | |
| `specialised_lending` | SPECIALISED_LENDING | |

### Classification Pipeline

The `classify()` method executes these steps in sequence:

```
Step 1: _add_counterparty_attributes()
        Join exposures with counterparty data (entity_type, revenue, assets, etc.)

Step 2: _classify_exposure_class()
        Map entity_type to exposure_class_sa and exposure_class_irb

Step 3: _apply_sme_classification()
        Check annual_revenue < EUR 50m for CORPORATE -> CORPORATE_SME

Step 4: _apply_retail_classification()
        Aggregate by lending group, check EUR 1m threshold
        Apply mortgage classification for RETAIL_MORTGAGE

Step 5: _identify_defaults()
        Check default_status, set exposure_class_for_sa = DEFAULTED

Step 5a: _apply_infrastructure_classification()
        Check product_type for infrastructure lending

Step 5b: _apply_fi_scalar_classification()
        Determine if FI scalar (1.25x correlation) applies:
        - Large FSE: total_assets >= EUR 70bn
        - Unregulated FSE: is_regulated = False

Step 6: _determine_approach()
        Assign SA/FIRB/AIRB/SLOTTING based on IRB permissions

Step 7: _add_classification_audit()
        Build audit trail string for traceability

Step 7a: _enrich_slotting_exposures()
        Add slotting_category, sl_type, is_hvcre for specialised lending

Step 8: Split by approach
        Filter into sa_exposures, irb_exposures, slotting_exposures
```

### Financial Sector Entity (FSE) Classification

The classifier identifies Financial Sector Entities for the FI scalar (CRR Art. 153(2)):

```python
FINANCIAL_SECTOR_ENTITY_TYPES = {
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "pse_institution",   # PSE treated as institution
    "rgla_institution",  # RGLA treated as institution
}
```

**FI Scalar triggers 1.25x correlation multiplier when:**
- `is_large_financial_sector_entity`: total_assets >= EUR 70bn, OR
- `is_financial_sector_entity` AND `is_regulated = False`

### Key Features

- **Dual exposure class mapping**: SA and IRB classes tracked separately
- **Entity type as single source**: No conflicting boolean flags
- **SME identification**: Corporate exposures with revenue < EUR 50m
- **Retail threshold checking**: Lending group aggregation against EUR 1m
- **Mortgage detection**: Product type pattern matching
- **FI scalar determination**: Large or unregulated FSE identification
- **Infrastructure classification**: For supporting factor eligibility
- **Slotting enrichment**: Category, type, HVCRE flags from patterns
- **Full audit trail**: Classification reasoning captured per exposure

### Output Columns

The classifier adds these columns to exposures:

| Column | Description |
|--------|-------------|
| `exposure_class` | SA exposure class (backwards compatible) |
| `exposure_class_sa` | SA exposure class (explicit) |
| `exposure_class_irb` | IRB exposure class |
| `is_sme` | SME classification flag |
| `is_mortgage` | Mortgage product flag |
| `is_defaulted` | Default status flag |
| `is_infrastructure` | Infrastructure lending flag |
| `is_financial_sector_entity` | FSE flag |
| `is_large_financial_sector_entity` | Large FSE flag (>= EUR 70bn) |
| `requires_fi_scalar` | FI scalar required (1.25x correlation) |
| `qualifies_as_retail` | Meets retail threshold |
| `approach` | Assigned calculation approach (SA/FIRB/AIRB/SLOTTING) |
| `classification_reason` | Audit trail string |

See [Classification](../features/classification.md) for detailed documentation of the classification algorithm.

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

The IRB Calculator uses a Polars namespace extension (`IRBLazyFrame`) for fluent, chainable calculations:

```python
class IRBCalculator:
    """Calculate IRB RWA using K formula."""

    def get_irb_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig
    ) -> IRBResultBundle:
        # Apply IRB calculations using namespace for fluent pipeline
        exposures = (data.irb_exposures
            .irb.classify_approach(config)   # Determine F-IRB vs A-IRB
            .irb.apply_firb_lgd(config)      # Apply supervisory LGD for F-IRB
            .irb.prepare_columns(config)     # Ensure required columns exist
            .irb.apply_all_formulas(config)  # Run full IRB calculation
        )

        # Apply supporting factors (CRR only - Art. 501)
        exposures = self._apply_supporting_factors(exposures, config)

        return IRBResultBundle(
            results=exposures,
            expected_loss=exposures.irb.select_expected_loss(),
            calculation_audit=exposures.irb.build_audit(),
            errors=[],
        )
```

### IRB Namespace

The `.irb` namespace provides chainable methods for each calculation step:

| Method | Description |
|--------|-------------|
| `classify_approach(config)` | Classify as F-IRB or A-IRB |
| `apply_firb_lgd(config)` | Apply supervisory LGD for F-IRB |
| `prepare_columns(config)` | Ensure required columns exist |
| `apply_pd_floor(config)` | Apply PD floor (0.03% CRR, 0.05% Basel 3.1) |
| `apply_lgd_floor(config)` | Apply LGD floor (Basel 3.1 A-IRB only) |
| `calculate_correlation(config)` | Calculate asset correlation with SME adjustment |
| `calculate_k(config)` | Calculate capital requirement K |
| `calculate_maturity_adjustment(config)` | Calculate maturity adjustment |
| `calculate_rwa(config)` | Calculate RWA |
| `calculate_expected_loss(config)` | Calculate expected loss |
| `apply_all_formulas(config)` | Run complete calculation pipeline |

### Key Features

- **Fluent API**: Namespace enables readable, chainable method calls
- **Pure Polars expressions**: Full lazy evaluation with `polars-normal-stats` for statistical functions
- **Streaming-capable**: No data materialization required, enabling large dataset processing
- PD and LGD floor application
- Correlation calculation with SME adjustment
- K formula implementation using `normal_cdf` and `normal_ppf`
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
