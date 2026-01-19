# Contracts API

The contracts module defines interfaces and data contracts.

## Data Bundles

### Module: `rwa_calc.contracts.bundles`

#### `RawDataBundle`

```python
@dataclass(frozen=True)
class RawDataBundle:
    """
    Raw data loaded from source files.

    Attributes:
        counterparties: Counterparty master data.
        facilities: Credit facility data.
        loans: Individual loan data.
        contingents: Off-balance sheet items (optional).
        collateral: Collateral data (optional).
        guarantees: Guarantee data (optional).
        provisions: Provision data (optional).
        ratings: Rating data (optional).
        org_mapping: Organization hierarchy (optional).
        lending_mapping: Retail lending groups (optional).
    """

    counterparties: pl.LazyFrame
    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    contingents: pl.LazyFrame | None = None
    collateral: pl.LazyFrame | None = None
    guarantees: pl.LazyFrame | None = None
    provisions: pl.LazyFrame | None = None
    ratings: pl.LazyFrame | None = None
    org_mapping: pl.LazyFrame | None = None
    lending_mapping: pl.LazyFrame | None = None
```

#### `ResolvedHierarchyBundle`

```python
@dataclass(frozen=True)
class ResolvedHierarchyBundle:
    """
    Data with resolved hierarchies.

    Attributes:
        counterparties: Counterparties with resolved parents.
        facilities: Facilities data.
        loans: Loans data.
        exposures: Flattened exposure view.
    """

    counterparties: pl.LazyFrame
    facilities: pl.LazyFrame
    loans: pl.LazyFrame
    exposures: pl.LazyFrame
```

#### `ClassifiedExposuresBundle`

```python
@dataclass(frozen=True)
class ClassifiedExposuresBundle:
    """
    Classified exposures split by approach.

    Attributes:
        all_exposures: All classified exposures.
        sa_exposures: Exposures for SA calculation.
        irb_exposures: Exposures for IRB calculation.
        slotting_exposures: Exposures for Slotting calculation.
    """

    all_exposures: pl.LazyFrame
    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    slotting_exposures: pl.LazyFrame
```

#### `CRMAdjustedBundle`

```python
@dataclass(frozen=True)
class CRMAdjustedBundle:
    """
    Exposures after CRM application.

    Attributes:
        sa_exposures: SA exposures after CRM.
        irb_exposures: IRB exposures after CRM.
        slotting_exposures: Slotting exposures after CRM.
    """

    sa_exposures: pl.LazyFrame
    irb_exposures: pl.LazyFrame
    slotting_exposures: pl.LazyFrame
```

#### Result Bundles

```python
@dataclass(frozen=True)
class SAResultBundle:
    """SA calculation results."""
    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)

@dataclass(frozen=True)
class IRBResultBundle:
    """IRB calculation results."""
    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)

@dataclass(frozen=True)
class SlottingResultBundle:
    """Slotting calculation results."""
    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)
```

#### `AggregatedResultBundle`

```python
@dataclass(frozen=True)
class AggregatedResultBundle:
    """
    Final aggregated calculation results.

    Attributes:
        data: Detailed exposure-level results.
        errors: Any calculation errors.
        warnings: Any calculation warnings.
    """

    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)
    warnings: list[CalculationWarning] = field(default_factory=list)

    @property
    def total_rwa(self) -> float:
        """Total risk-weighted assets."""

    @property
    def total_ead(self) -> float:
        """Total exposure at default."""

    @property
    def sa_rwa(self) -> float:
        """Standardised Approach RWA."""

    @property
    def irb_rwa(self) -> float:
        """IRB RWA."""

    @property
    def slotting_rwa(self) -> float:
        """Slotting RWA."""

    @property
    def total_expected_loss(self) -> float:
        """Total expected loss (IRB only)."""

    @property
    def has_errors(self) -> bool:
        """Whether any errors occurred."""

    @property
    def has_warnings(self) -> bool:
        """Whether any warnings occurred."""

    def to_dataframe(self) -> pl.DataFrame:
        """Materialize results as DataFrame."""

    def to_parquet(self, path: str) -> None:
        """Export results to Parquet."""

    def to_csv(self, path: str) -> None:
        """Export results to CSV."""

    def to_json(self, path: str) -> None:
        """Export results to JSON."""

    def by_exposure_class(self) -> pl.DataFrame:
        """Get breakdown by exposure class."""

    def by_approach(self) -> pl.DataFrame:
        """Get breakdown by approach."""

    def by_counterparty(self) -> pl.DataFrame:
        """Get breakdown by counterparty."""
```

## Protocols

### Module: `rwa_calc.contracts.protocols`

```python
from typing import Protocol

class LoaderProtocol(Protocol):
    """Protocol for data loaders."""

    def load(self, path: Path) -> RawDataBundle:
        """Load raw data from path."""
        ...

class HierarchyResolverProtocol(Protocol):
    """Protocol for hierarchy resolvers."""

    def resolve(
        self,
        raw_data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """Resolve hierarchies."""
        ...

class ClassifierProtocol(Protocol):
    """Protocol for classifiers."""

    def classify(
        self,
        resolved: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """Classify exposures."""
        ...

class CRMProcessorProtocol(Protocol):
    """Protocol for CRM processors."""

    def process(
        self,
        classified: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """Process CRM."""
        ...

class SACalculatorProtocol(Protocol):
    """Protocol for SA calculators."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """Calculate SA RWA."""
        ...

class IRBCalculatorProtocol(Protocol):
    """Protocol for IRB calculators."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> IRBResultBundle:
        """Calculate IRB RWA."""
        ...

class SlottingCalculatorProtocol(Protocol):
    """Protocol for Slotting calculators."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> SlottingResultBundle:
        """Calculate Slotting RWA."""
        ...

class OutputAggregatorProtocol(Protocol):
    """Protocol for output aggregators."""

    def aggregate(
        self,
        sa_result: SAResultBundle,
        irb_result: IRBResultBundle,
        slotting_result: SlottingResultBundle,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """Aggregate results."""
        ...
```

## Error Handling

### Module: `rwa_calc.contracts.errors`

```python
@dataclass
class CalculationError:
    """
    Calculation error details.

    Attributes:
        exposure_id: Affected exposure identifier.
        stage: Pipeline stage where error occurred.
        message: Error description.
        details: Additional error details.
    """

    exposure_id: str | None
    stage: str
    message: str
    details: dict[str, Any] | None = None

@dataclass
class CalculationWarning:
    """
    Calculation warning details.

    Attributes:
        exposure_id: Affected exposure identifier.
        message: Warning description.
    """

    exposure_id: str | None
    message: str

@dataclass
class LazyFrameResult:
    """
    Result wrapper with error accumulation.

    Attributes:
        data: Result LazyFrame.
        errors: Accumulated errors.
        warnings: Accumulated warnings.
    """

    data: pl.LazyFrame
    errors: list[CalculationError] = field(default_factory=list)
    warnings: list[CalculationWarning] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Whether any errors occurred."""
        return len(self.errors) > 0
```

## Related

- [Domain API](domain.md)
- [Engine API](engine.md)
- [Architecture - Design Principles](../architecture/design-principles.md)
