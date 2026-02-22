# RWA Calculator — Project Instructions

Basel 3.1 Credit Risk RWA Calculator compliant with PRA PS9/24. Python 3.13+, Polars-based, protocol-driven pipeline architecture.

## Architecture

### Pipeline Pattern
All calculations flow through an immutable pipeline of discrete stages:
```
RawDataBundle → Loader → HierarchyResolver → Classifier → CRMProcessor
    → SA/IRB/Slotting/Equity Calculators → OutputAggregator → AggregatedResultBundle
```
Each stage receives an immutable bundle, returns a new immutable bundle. Never mutate bundles in-place.

### Key Design Patterns
- **Protocols** (`contracts/protocols.py`): All components implement structural `Protocol` interfaces — not abstract base classes. New components must define and implement a protocol.
- **Frozen dataclass bundles** (`contracts/bundles.py`): All inter-stage data transfer uses `@dataclass(frozen=True)`. Never use plain dicts for stage outputs.
- **Polars custom namespaces**: Domain logic is exposed via registered namespace extensions (e.g., `df.rwa_sa.calculate()`). Place namespace code in `namespace.py` within each engine subpackage.
- **Factory methods on config**: Use `CalculationConfig.crr()` / `.basel_3_1()` for self-documenting configuration. Don't construct configs with raw kwargs.
- **Error accumulation**: Errors are collected in `list[CalculationError]` and propagated through bundles — never raise exceptions for data quality issues. Reserve exceptions for programming errors only.

## Reference Documentation

### UK Basel 3.1 Credit Risk References
Refer to these resources for RWA regulation context (PRA takes priority over BCBS):

#### Current regulations (Credit Risk sections)
- https://www.prarulebook.co.uk/pra-rules/crr-firms
- https://www.legislation.gov.uk/eur/2013/575/contents

#### Basel 3.1 implementation
- PRA PS9/24 — UK-specific rules: https://www.bankofengland.co.uk/prudential-regulation/publication/2024/september/implementation-of-the-basel-3-1-standards-near-final-policy-statement-part-2
- BCBS CRE standards — underlying methodology: https://www.bis.org/basel_framework/standard/CRE.htm?tldate=20260111
- PRA CP16/22 — implementation consultation: https://www.bankofengland.co.uk/prudential-regulation/publication/2022/november/implementation-of-the-basel-3-1-standards

PDFs of the above are in the `ref_docs/` folder.

Key topics: SA risk weights (CRE20-22), IRB approach (CRE30-36), Credit risk mitigation (CRE22), Equity (CRE60), Exposure classes and slotting criteria.

## Tools & Dependencies

- **Polars** (default dataframe library) — LazyFrames over eager. Docs: https://docs.pola.rs/api/python/stable/reference/index.html
- **polars-normal-stats** — for CDF, PPF, PDF (not scipy/numpy). Docs: https://pypi.org/project/polars-normal-stats/
- **DuckDB** — only where more suitable than Polars (e.g., complex SQL-style joins)
- **UV** — use `uv add` / `uv run`, never `pip install`
- **Pytest** — test runner with `pytest-benchmark` for perf tests
- **Ruff** — linter and formatter (config in `pyproject.toml`)
- **Mypy** — static type checking
- **Marimo** — interactive workbooks. Docs: https://docs.marimo.io/api/
- **MkDocs** (Material theme) — project documentation site

## Module Structure

Every module must read top-down like a narrative. Order:

1. **Module docstring** — purpose, pipeline position, key responsibilities, regulatory references
2. **Imports** — `from __future__ import annotations` first, then stdlib, third-party, local
3. **Constants / config** — module-level constants
4. **Main public entry point** — the primary class or function a caller would use
5. **Supporting public classes/functions** — secondary components used by the entry point
6. **Private helpers** — `_prefixed` internal functions at the bottom

Example docstring pattern:
```python
"""
Standardised Approach (SA) Calculator for RWA.

Pipeline position:
    CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Risk weight lookup by exposure class and CQS
- RWA calculation (EAD x RW x supporting factor)

References:
- CRR Art. 112-134: SA risk weights
"""
```

## Coding Conventions

### Type Hints
- Every module starts with `from __future__ import annotations`
- Use `TYPE_CHECKING` guard for imports only needed by type checkers
- Full type hints on all function signatures — no untyped public functions
- Use `Protocol` for structural interfaces, not ABC

### Style
- Line length: 100 characters (ruff enforced)
- Imports sorted by isort (ruff `I` rule)
- Use comprehensions over `map`/`filter` (ruff `C4` rule)
- Use modern Python 3.13+ syntax — `X | Y` over `Union[X, Y]`, `list[x]` over `List[x]` (ruff `UP` rule)
- Prefer early returns to reduce nesting
- No dead code — delete unused code outright, don't comment it out

### Naming
- Classes: `PascalCase` (e.g., `SACalculator`, `RawDataBundle`)
- Functions/methods: `snake_case`, verb-first for actions (e.g., `calculate_rwa`, `resolve_hierarchy`)
- Private: `_single_underscore` prefix
- Constants: `UPPER_SNAKE_CASE`
- Enums: class `PascalCase`, members `UPPER_SNAKE_CASE` (defined in `domain/enums.py`)
- Error codes: short prefix + number (e.g., `DQ006`, `CL001`)

### Data & Immutability
- All data transfer objects: `@dataclass(frozen=True)`
- Don't pass raw dicts between components — use typed bundles
- Prefer `Decimal` for regulatory parameters (risk weights, LGD floors) to avoid float precision issues

## Polars Conventions

- **LazyFrame first**: All pipeline operations use `LazyFrame`. Only `.collect()` at the final output boundary (aggregator or API layer).
- **Expression-based**: Use `pl.when().then().otherwise()` chains, `pl.col()` expressions — avoid row-wise Python loops.
- **Column naming**: `snake_case` for all column names. Prefix derived columns to indicate their stage (e.g., `sa_risk_weight`, `irb_pd_adjusted`).
- **Namespace extensions**: Domain-specific Polars operations go in `namespace.py` files within engine subpackages. Register via `@pl.api.register_lazyframe_namespace`.
- **No eager unless necessary**: If you need `.collect()` mid-pipeline, document why with a comment.

## Testing Standards

### Workflow
- **TDD**: Write a failing test first, then implement the minimum code to pass, then refactor.
- **Research before coding**: Understand the regulatory requirement and existing patterns before writing tests.

### Organisation
```
tests/
├── unit/          # Fast, isolated tests (~1,050 tests)
├── acceptance/    # Scenario-based regulatory tests (~74 tests)
├── benchmarks/    # Performance tests (marked @pytest.mark.benchmark)
├── fixtures/      # Shared test data builders
└── expected_outputs/  # Golden files for acceptance tests
```

### Conventions
- **AAA pattern**: Every test has clear Arrange / Act / Assert sections
- **Test naming**: `test_<behaviour_under_test>` — describe the what, not the how
- **One assert per concept**: Each test verifies a single logical assertion (multiple `assert` is fine if testing one concept)
- **Fixtures**: Use `@pytest.fixture` for shared setup. Test data builders live in `tests/fixtures/`
- **Markers**: Use `@pytest.mark.benchmark` for perf tests, `@pytest.mark.slow` for 10M+ scale tests
- **Run tests**: `uv run pytest tests/` (benchmarks auto-skipped via `--benchmark-skip`)

## Error Handling

- **Data quality errors**: Accumulated in `list[CalculationError]`, never raised. Each has an `ErrorCategory`, `ErrorSeverity`, error code, and optional regulatory reference.
- **Programming errors**: Use standard exceptions (`ValueError`, `TypeError`, etc.)
- **Validation**: Input validation is non-blocking — errors collected via `_validate_input_data()`, pipeline continues with valid data.
- **Error codes**: Prefixed by domain — `DQ` (data quality), `CL` (classification), `SA` (standardised approach), `IRB`, etc.

## Documentation

- **MkDocs site**: Source in `docs/`, built with `mkdocs-material`. Run locally: `uv run mkdocs serve`
- **Docstrings**: All public classes and functions must have docstrings following the module docstring pattern (purpose, responsibilities, references)
- **Changelog**: Update `docs/appendix/changelog.md` for any user-facing changes
- **After every change**: Update relevant docs, docstrings, and changelog entry
