## Build & Run

- Package manager: `uv` (never `pip install`)
- Add dependencies: `uv add <package>`
- Run anything: `uv run <command>`

## Validation

Run these after implementing to get immediate feedback:

- Tests: `uv run pytest tests/ --benchmark-skip`
- Typecheck: `uv run mypy src/`
- Lint: `uv run ruff check src/ && uv run ruff format --check src/`
- Fix lint: `uv run ruff check --fix src/ && uv run ruff format src/`
- Single test file: `uv run pytest tests/unit/test_<name>.py -x`
- Acceptance tests: `uv run pytest tests/acceptance/ --benchmark-skip`

## Operational Notes

- Python 3.13+ required
- Source code: `src/rwa_calc/`
- Tests: `tests/` (unit/, acceptance/, benchmarks/, fixtures/)
- Docs: `docs/` (MkDocs Material), serve with `uv run mkdocs serve`
- Config: `pyproject.toml` (ruff, mypy, pytest settings)
- Line length: 100 chars (ruff enforced)
- Every module starts with `from __future__ import annotations`

### Codebase Patterns

- **Pipeline**: immutable frozen dataclass bundles flow through 6 stages (Loader → Hierarchy → Classifier → CRM → Calculators → Aggregator)
- **Polars LazyFrame**: all pipeline ops use LazyFrame; only `.collect()` at final output boundary
- **Protocols**: structural `Protocol` interfaces, not ABC — defined in `contracts/protocols.py`
- **Error accumulation**: data quality errors collected in `list[CalculationError]`, never raised
- **Enums**: all in `domain/enums.py`
- **Namespaces**: domain logic via `@pl.api.register_lazyframe_namespace` in `namespace.py` files
- **Config**: use `CalculationConfig.crr()` / `.basel_3_1()` factory methods
