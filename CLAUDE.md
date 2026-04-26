# RWA Calculator — Project Instructions

Basel 3.1 Credit Risk RWA Calculator compliant with PRA PS1/26. Python 3.13+, Polars-based, protocol-driven pipeline architecture.

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
- **Data/engine separation**: Regulatory values (risk weights, LGDs, CCFs, floors, scaling factors) live in `src/rwa_calc/data/tables/*.py`. Input-domain / validation constants (eligible type-strings, category maps) live in `src/rwa_calc/data/schemas.py`. `engine/**` imports these — it must not declare its own regulatory scalars or string-enum collections at module scope. Enforced by `scripts/arch_check.py` (checks 5 & 6) and `tests/contracts/test_data_layer_boundary.py`; new exceptions must be justified in the allowlist at the top of `arch_check.py`.
- **Error accumulation**: Errors are collected in `list[CalculationError]` and propagated through bundles — never raise exceptions for data quality issues. Reserve exceptions for programming errors only.

## Reference Documentation

### UK Basel 3.1 Credit Risk References
Refer to these resources for RWA regulation context (PRA takes priority over BCBS):

#### Current regulations (Credit Risk sections)
- https://www.prarulebook.co.uk/pra-rules/crr-firms
- https://www.legislation.gov.uk/eur/2013/575/contents

#### Basel 3.1 implementation
- New regulations PS1/26 Appendix 1: https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january/ps126app1.pdf
- PRA PS1/26  — UK-specific rules: https://www.bankofengland.co.uk/prudential-regulation/publication/2026/january/implementation-of-the-basel-3-1-final-rules-policy-statement
- Template guidance: https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/policy-statement/2026/january/ps126app17.pdf
- BCBS CRE standards — underlying methodology: https://www.bis.org/basel_framework/standard/CRE.htm?tldate=20260111

PDFs of the above are in the `docs/assets/` folder.

Key topics: SA risk weights (CRE20-22), IRB approach (CRE30-36), Credit risk mitigation (CRE22), Equity (CRE60), Exposure classes and slotting criteria.

## Tools & Dependencies

- **Polars** (default dataframe library) — LazyFrames over eager. Docs: https://docs.pola.rs/api/python/stable/reference/index.html
- **polars-normal-stats** — for CDF, PPF, PDF (not scipy/numpy). Docs: https://pypi.org/project/polars-normal-stats/
- **UV** — use `uv add` / `uv run`, never `pip install`
- **Pytest** — test runner with `pytest-benchmark` for perf tests
- **Ruff** — linter and formatter (config in `pyproject.toml`)
- **ty** — static type checking
- **Marimo** — interactive workbooks. Docs: https://docs.marimo.io/api/
- **Zensical** — project documentation site

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
├── unit/          # Fast, isolated tests (~4,500 tests)
├── acceptance/    # Scenario-based regulatory tests (~500 tests)
├── contracts/     # Protocol/interface compliance tests (~150 tests)
├── integration/   # Cross-component integration tests (~130 tests)
├── benchmarks/    # Performance tests (marked @pytest.mark.benchmark)
├── bdd/           # BDD-style tests (step definitions)
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

## Logging

Operational telemetry flows through stdlib `logging`, configured by `rwa_calc.observability`. Regulatory/data-quality issues remain in `CalculationError` — logging is strictly for observability and must never duplicate the error channel.

Rules for new code:
- **Module logger**: every stage module under `engine/` declares `logger = logging.getLogger(__name__)` at the top of file (after imports). Enforced by `scripts/arch_check.py` check 8 and `tests/contracts/test_logging_contract.py`.
- **Stage timing**: pipeline stages are wrapped with `stage_timer(logger, "<stage>")` in the orchestrator. New stages added to the pipeline must be wrapped the same way.
- **Levels**: INFO for stage entry/exit and pipeline summary; DEBUG for branch decisions; WARNING for missing optional inputs or fallbacks; ERROR reserved for truly unexpected exceptions.
- **No `print()`**: banned project-wide by ruff `T20`. Route user-visible output (e.g., marimo startup banner) through `logger.info`.
- **No `logging.basicConfig()`**: handler setup is the job of `rwa_calc.observability.configure_logging`, called at the entry point (`CreditRiskCalc.calculate`). It is idempotent and attaches only to the `rwa_calc` namespace logger.
- **Lazy formatting**: use `logger.info("loaded %d exposures", n)`, not f-strings. Enforced by ruff `G`.
- **Never `.collect()` just to log**: a log line is not worth materialising a LazyFrame. Prefer `len(lf.collect_schema().names())` for cheap width, or defer the log to a stage that already materialises.
- **Correlation IDs**: `PipelineOrchestrator.run_with_data` binds a fresh `run_id` via `new_run_id()` and clears it in `finally`. Every LogRecord emitted during a run carries that id via `RunIdFilter`.
- **Configuration**: `log_level` and `log_format` (`"text"` | `"json"`) are fields on `CalculationConfig` and may be passed through `CreditRiskCalc(log_format="json")`.

Reference stage skeleton and format details — see `docs/specifications/observability.md`.

## Agents and Slash Commands

Project subagents in `.claude/agents/` (role-based, not domain-based — regulatory knowledge stays in the `basel31` and `crr` skills):

- **`scenario-architect`** — read-only. Designs one CRR-* / B31-* / P-coded item end-to-end (inputs, hand-calc, citations).
- **`fixture-builder`** — owns `tests/fixtures/`. Implements parquet rows and builders from a scenario proposal.
- **`test-writer`** — owns `tests/{unit,acceptance,contracts,integration}/`. Writes the failing test that drives the next implementation step.
- **`engine-implementer`** — owns `src/rwa_calc/`. Makes the failing test pass with the minimum diff and a green validation gate (arch_check, ruff, ty, contracts).
- **`plan-curator`** — owns the two work-queue files at the repo root: `IMPLEMENTATION_PLAN.md` and `DOCS_IMPLEMENTATION_PLAN.md`. Audits code/specs/PDFs against each other and writes prioritised bullet items.
- **`doc-writer`** — owns `docs/`. Writes or updates one canonical docs page per `DOCS_IMPLEMENTATION_PLAN.md` item; runs `uv run zensical build` before returning.

Orchestration lives in slash commands, not in agents. Each `loop.sh` mode maps to one slash command, and each slash command commits once at the end:

| `loop.sh` mode | Prompt file | Slash command | Owns |
|---|---|---|---|
| `loop.sh` (build) | `PROMPT_build.md` | `/next-scenario` | code/test backlog → implementation |
| `loop.sh plan` | `PROMPT_plan.md` | `/refresh-plan` | refresh `IMPLEMENTATION_PLAN.md` |
| `loop.sh docs_build` | `PROMPT_docs_build.md` | `/next-doc` | docs backlog → docs page edit |
| `loop.sh docs_plan` | `PROMPT_docs_plan.md` | `/refresh-docs-plan` | refresh `DOCS_IMPLEMENTATION_PLAN.md` |

Plus `/implement-scenario <ID>` for ad-hoc one-off work on a specific P-code or scenario ID.

Agents do not have commit/push permissions and do not invoke other agents — keep the call graph one level deep so `scripts/pre_commit_gate.sh` fires once per iteration with full context. The two root plan files (`IMPLEMENTATION_PLAN.md`, `DOCS_IMPLEMENTATION_PLAN.md`) are the source of truth for outstanding work; `docs/plans/implementation-plan.md` is published narrative on the Zensical site.

## Documentation

- **Zensical site**: Source in `docs/`, config in `zensical.toml`. Run locally: `uv run zensical serve`
- **Specifications**: Single source of truth is `docs/specifications/`. Do not create a separate `specs/` directory.
- **Docstrings**: All public classes and functions must have docstrings following the module docstring pattern (purpose, responsibilities, references)
- **Changelog**: Update `docs/appendix/changelog.md` for any user-facing changes
- **After every change**: Update relevant docs, docstrings, and changelog entry
