# Adding Features

This guide explains how to extend the RWA calculator with new functionality.

## Extension Points

The calculator is designed for extensibility at several points:

1. **New exposure classes**
2. **New calculation approaches**
3. **New CRM types**
4. **Custom data loaders**
5. **New regulatory tables**

## Adding a New Exposure Class

### Step 1: Add Enum Value

```python
# src/rwa_calc/domain/enums.py

class ExposureClass(str, Enum):
    # ... existing classes ...
    NEW_CLASS = "NEW_CLASS"  # Add new class
```

### Step 2: Add Classification Logic

Classification logic lives in the `engine/stages/classify/` package
(`engine/classifier.py` is now only a back-compat shim re-exporting
`ExposureClassifier`). Add the class-determination rule in the relevant module,
e.g. `attributes.py` / `subtypes.py`:

```python
# src/rwa_calc/engine/stages/classify/subtypes.py

def _determine_exposure_class(
    counterparty_type: str,
    # ... other params ...
) -> ExposureClass:
    # Add classification rule
    if counterparty_type == "NEW_TYPE":
        return ExposureClass.NEW_CLASS

    # ... existing logic ...
```

### Step 3: Add Risk Weights to the Rulepack

Regulatory values live in the rulepack packs as **cited entries**, not in a
`data/tables/` module (that package was removed). Add a `LookupTable` (or
`BandedTable` / `ScalarParam`) keyed by CQS, each carrying a `Citation`, to the
relevant pack:

```python
# src/rwa_calc/rulebook/packs/crr.py  (and/or b31.py)

NEW_CLASS_RISK_WEIGHTS = LookupTable(
    name="new_class_risk_weights",
    citation=Citation("CRR Art. 1xx"),
    rows={
        CQS.CQS_1: Decimal("0.20"),
        CQS.CQS_2: Decimal("0.50"),
        # ... etc ...
    },
)
```

The engine reads the value back through the resolved pack — never a module-level
scalar in `engine/**` (banned by `scripts/arch_check.py` checks 5, 6 and 12):

```python
# in an engine transform, with the resolved pack in hand
pack = resolve(run_config.regime_id, run_config.reporting_date)
rw = pack.lookup("new_class_risk_weights", cqs)
```

### Step 4: Add Tests

```python
# tests/unit/test_new_class.py

class TestNewExposureClass:
    def test_classification(self):
        """NEW_TYPE counterparty classified as NEW_CLASS."""
        # ...

    def test_risk_weights(self):
        """NEW_CLASS risk weights are correct."""
        # ...
```

## Adding a Custom Calculator

### Step 1: Implement Protocol

```python
# src/rwa_calc/engine/custom/calculator.py

from rwa_calc.contracts.protocols import CalculatorProtocol
from rwa_calc.contracts.bundles import ResultBundle

class CustomCalculator:
    """Custom calculator for specialized exposures."""

    def calculate(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> ResultBundle:
        """Calculate RWA using custom methodology."""
        result = (
            exposures
            .with_columns(
                # Custom calculation logic
                rwa=self._calculate_custom_rwa(
                    pl.col("ead"),
                    pl.col("custom_param"),
                )
            )
        )

        return ResultBundle(data=result)

    def _calculate_custom_rwa(
        self,
        ead: pl.Expr,
        custom_param: pl.Expr,
    ) -> pl.Expr:
        """Custom RWA calculation."""
        return ead * custom_param * 0.08  # Example
```

### Step 2: Register in the Stage Registry

The pipeline is a **fold over a literal stage registry**, not a constructor that
wires component objects. Add a stage adapter module under `engine/stages/`
exposing `run(ctx, rulepack, run_config) -> PipelineContext`, then add an ordered
`StageSpec` entry to `PIPELINE_STAGES` in `engine/registry.py`:

```python
# src/rwa_calc/engine/stages/custom.py

from rwa_calc.contracts.context import PipelineContext

def run(ctx: PipelineContext, rulepack, run_config) -> PipelineContext:
    """Custom stage adapter — reads/writes typed ArtifactKey[T] entries."""
    ...
```

```python
# src/rwa_calc/engine/registry.py

from rwa_calc.engine.stages import custom

PIPELINE_STAGES: tuple[StageSpec, ...] = (
    # ... existing StageSpec entries ...
    StageSpec("custom", custom.run, error_type=...),
)
```

The registry is a single ordered **literal** list — no conditionals
(`scripts/arch_check.py` check 15). Any regime- or election-dependent behaviour
lives inside the stage function (reading a pack `Feature`), never as a registry
branch.

### Step 3: Add Tests

```python
# tests/unit/test_custom_calculator.py

class TestCustomCalculator:
    def test_implements_protocol(self):
        calculator = CustomCalculator()
        # Verify protocol compliance

    def test_calculation_logic(self, sample_exposures, config):
        calculator = CustomCalculator()
        result = calculator.calculate(sample_exposures, config)
        # Verify results
```

## Adding a New Data Loader

### Step 1: Implement Protocol

```python
# src/rwa_calc/engine/loaders/csv_loader.py

from rwa_calc.contracts.protocols import LoaderProtocol
from rwa_calc.contracts.bundles import RawDataBundle

class CSVLoader:
    """Load data from CSV files."""

    def load(self, path: Path) -> RawDataBundle:
        """Load all data files from directory."""
        return RawDataBundle(
            counterparties=pl.scan_csv(path / "counterparties.csv"),
            facilities=pl.scan_csv(path / "facilities.csv"),
            loans=pl.scan_csv(path / "loans.csv"),
            # ... other files ...
        )
```

### Step 2: Use in Pipeline

```python
from rwa_calc.engine.loaders.csv_loader import CSVLoader
from rwa_calc.engine.pipeline import RWAPipeline

# Create pipeline with CSV loader
csv_loader = CSVLoader()
pipeline = RWAPipeline(
    loader=csv_loader,
    # ... other components ...
)
```

## Adding New CRM Type

### Step 1: Add Collateral Type

```python
# src/rwa_calc/domain/enums.py

class CollateralType(str, Enum):
    # ... existing types ...
    NEW_COLLATERAL = "NEW_COLLATERAL"
```

### Step 2: Add Haircuts to the Rulepack

Supervisory haircut values are cited rulepack entries, not a `data/tables/`
module. Add a `BandedTable` (banded by residual maturity) with a `Citation` to
the relevant pack:

```python
# src/rwa_calc/rulebook/packs/crr.py  (and/or b31.py)

NEW_COLLATERAL_HAIRCUTS = BandedTable(
    name="new_collateral_haircuts",
    citation=Citation("CRR Art. 224"),
    bands=[
        # (upper_bound_years, haircut)
        (1, Decimal("0.05")),
        (5, Decimal("0.10")),
        (None, Decimal("0.15")),
    ],
)
```

`engine/crm/haircut_tables.py` is the thin pack-binding shim that reads these
values back from the resolved pack.

### Step 3: Update CRM Haircut Application

Haircut application lives in `engine/crm/haircuts.py`; it reads the values from
the resolved pack via `engine/crm/haircut_tables.py`, never from an inline
`NEW_COLLATERAL_HAIRCUTS` dict:

```python
# src/rwa_calc/engine/crm/haircuts.py

# the supervisory-haircut values come from the resolved pack via
# engine/crm/haircut_tables.py — apply them as a Polars expression keyed
# on collateral_type + residual_maturity band.
```

## Adding Basel 3.1 Features

Regime is **data**, not a config branch. The engine must not select behaviour by
branching on the regime (`config.is_crr` / `config.is_basel_3_1` are banned in
`engine/**` by `scripts/arch_check.py` check 17, and config carries no regulatory
values). Regime-divergent behaviour reads a cited pack `Feature`.

### Step 1: Add a Cited Feature to the Pack

```python
# src/rwa_calc/rulebook/packs/b31.py  (and/or crr.py for the CRR value)

NEW_FEATURE = Feature(
    name="new_feature_enabled",
    citation=Citation("PS1/26, paragraph 4.xx"),
    value=True,
)
```

### Step 2: Read the Feature in the Engine

```python
# in an engine transform — branch on the resolved Feature, not the regime
def apply_treatment(lf: pl.LazyFrame, run_config, *, pack) -> pl.LazyFrame:
    if pack.feature("new_feature_enabled"):
        return _apply_new_treatment(lf, pack)
    return lf
```

The regime is resolved once per run into the `ResolvedRulepack` from
`(regime_id, reporting_date)`, so the same engine code path serves both CRR and
Basel 3.1 — only the pack values differ.

## Adding a New Regulatory Value

Regulatory values are cited entries in the rulepack packs, read at runtime via
`resolve(regime_id, reporting_date)`. There is no `data/tables/` module to add to
— that package was removed (Phase 5 S13).

### Step 1: Add a Cited Entry to the Pack

```python
# src/rwa_calc/rulebook/packs/crr.py  (and/or b31.py)

from rwa_calc.rulebook.model import Citation, LookupTable

NEW_TABLE = LookupTable(
    name="new_table",
    citation=Citation("CRR Art. 1xx"),
    rows={
        "A": Decimal("0.10"),
        "B": Decimal("0.20"),
        "C": Decimal("0.30"),
    },
)
```

The engine reads it back through the resolved pack
(`pack.lookup("new_table", category)`); `compile.py` is the only
`Decimal` -> `float` boundary.

### Step 2: Add Tests

```python
# tests/unit/test_new_table.py

class TestNewTable:
    @pytest.mark.parametrize("category,expected", [
        ("A", Decimal("0.10")),
        ("B", Decimal("0.20")),
        ("C", Decimal("0.30")),
    ])
    def test_lookup_returns_correct_value(self, category, expected):
        pack = resolve("crr", date(2026, 12, 31))
        result = pack.lookup("new_table", category)
        assert result == expected
```

## Adding a Calculation Transform

Calculator and domain logic is written as **plain module-level typed functions**
composed via `lf.pipe(fn, ...)` — Polars namespace registrations
(`@pl.api.register_lazyframe_namespace` / `register_expr_namespace`) are extinct
and banned by `scripts/arch_check.py` check 14. The canonical pattern is a
function that takes a `LazyFrame` (or an `Expr`) and returns the same type:

```python
# src/rwa_calc/engine/sa/risk_weights.py (pattern)

def apply_risk_weights(lf: pl.LazyFrame, config, *, pack) -> pl.LazyFrame:
    """Apply SA risk weights from the resolved pack."""
    return lf.with_columns(
        (pl.col("ead") * pl.col("sa_risk_weight")).alias("sa_rwa")
    )
```

Compose transforms by chaining `.pipe`:

```python
result = (
    exposures
    .pipe(apply_risk_weights, config, pack=pack)
    .pipe(apply_supporting_factor, config, pack=pack)
)
```

For computationally intensive formulas, use pure Polars expressions with
`polars-normal-stats` (`normal_cdf`, `normal_ppf`, `normal_pdf`) so the whole
chain stays lazy:

```python
from polars_normal_stats import normal_cdf

def _capital_requirement_expr() -> pl.Expr:
    """Pure Polars expression — stays lazy, streams, scales past memory."""
    return normal_cdf(pl.col("scaled_pd"))
```

See `engine/sa/risk_weights.py`, `engine/sa/rw_adjustments.py`,
`engine/irb/transforms.py`, and `engine/slotting/transforms.py` for the
canonical transform-function style.

## Best Practices

### 1. Follow Existing Patterns

Look at existing implementations for guidance:
- `engine/sa/risk_weights.py` for calculation-transform patterns
- `rulebook/packs/*.py` for regulatory values (cited entries); `engine/sa/*_risk_weight_tables.py` and `engine/crm/haircut_tables.py` for the pack-binding shims
- `contracts/bundles.py` for data contracts

### 2. Write Tests First

Follow TDD:
1. Write failing acceptance test
2. Write failing unit tests
3. Implement to pass tests
4. Refactor

### 3. Use Type Hints

```python
def calculate_rwa(
    ead: float,
    risk_weight: Decimal,
    factor: Decimal | None = None,
) -> Decimal:
    """Calculate RWA with optional factor."""
    base_rwa = Decimal(str(ead)) * risk_weight
    if factor is not None:
        return base_rwa * factor
    return base_rwa
```

### 4. Document Regulatory References

```python
def calculate_sme_factor(total_exposure: Decimal) -> Decimal:
    """
    Calculate SME supporting factor per CRR Article 501.

    The factor provides capital relief using a tiered approach:
    - Exposure <= EUR 2.5m: 0.7619 factor
    - Exposure > EUR 2.5m: Blended factor

    Args:
        total_exposure: Total exposure to SME counterparty.

    Returns:
        SME supporting factor (0.7619 to 0.85).
    """
```

### 5. Update Documentation

After adding features, update:
- API documentation
- User guide (if user-facing)
- Changelog

## Next Steps

- [Code Style](code-style.md) - Coding conventions
- [Testing Guide](testing.md) - Writing tests
- [Architecture](../architecture/index.md) - System design
