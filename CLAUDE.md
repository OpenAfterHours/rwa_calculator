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

The stages are wired as a fold (migration Phase 4): `engine/registry.py` is the single ordered, **literal** stage list (`StageSpec` entries — no conditionals; arch_check check 15), `engine/orchestrator.py::run_stages` threads an immutable `PipelineContext` (typed `ArtifactKey[T]` map, `contracts/context.py`) through one `run(ctx, rulepack, run_config) -> PipelineContext` adapter per stage under `engine/stages/` (arch_check check 16). `rulepack` is `RulepackV0` (`rwa_calc.rulebook`), the frozen regime facade built once per run. `engine/pipeline.py` remains the facade owning the run lifecycle (run_id, edge capture, FX-rate sync, error merge, audit persistence).

### Key Design Patterns
- **Protocols** (`contracts/protocols.py`): All components implement structural `Protocol` interfaces — not abstract base classes. New components must define and implement a protocol.
- **Frozen dataclass bundles** (`contracts/bundles.py`): All inter-stage data transfer uses `@dataclass(frozen=True)`. Never use plain dicts for stage outputs.
- **Plain typed transform functions**: Calculator/domain logic is plain module-level typed functions (`fn(lf: LazyFrame, config, ...) -> LazyFrame`, or `fn(expr, ...) -> Expr`) composed via `.pipe(fn, config)` — e.g. `engine/sa/risk_weights.py`, `engine/irb/transforms.py`, `engine/slotting/transforms.py`. Polars namespace registrations (`@pl.api.register_*_namespace`) are extinct and banned by `scripts/arch_check.py` check 14.
- **Factory methods on config**: Use `CalculationConfig.crr()` / `.basel_3_1()` for self-documenting configuration. Don't construct configs with raw kwargs.
- **Data/engine separation — the rulepack pack is the value home**: Regulatory values (risk weights, LGDs, CCFs, floors, scaling factors, LTV bands) live in the **rulepack packs** `src/rwa_calc/rulebook/packs/{common,crr,b31}.py` as cited entries (`ScalarParam` / `LookupTable` / `BandedTable` / `FormulaParams` / `Feature`), read through the resolved pack (`resolve(regime, date)`). A new regulatory value goes in a pack with a `Citation` — **not** in a data table. The `data/tables/` package was removed entirely (Phase 5 S13): the SA risk-weight and CRM supervisory-haircut table modules now live in `engine/` as thin pack-binding shims (`engine/sa/crr_risk_weight_tables.py`, `engine/sa/b31_risk_weight_tables.py`, `engine/crm/haircut_tables.py`) that read their values back from the rulepack. Input-domain / validation constants (eligible type-strings, category maps) live in `src/rwa_calc/data/schemas.py`. `engine/**` reads the resolved pack; it must not declare its own regulatory scalars or string-enum collections at module scope (checks 5 & 6), must not import `rwa_calc.data.tables` at all (check 12 hard ban — the package no longer exists; read the pack), and must not branch on `config.is_crr` / `config.is_basel_3_1` — regime behaviour reads a cited pack `Feature` (check 17). Enforced by `scripts/arch_check.py` and `tests/contracts/test_data_layer_boundary.py`; new exceptions need a justified allowlist entry at the top of `arch_check.py`.
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
- **Plain typed functions, not namespaces**: Domain-specific Polars operations are module-level typed functions composed via `.pipe(fn, config)`. Never register a Polars namespace (`@pl.api.register_*_namespace`) — banned by arch_check check 14.
- **No eager unless necessary**: If you need `.collect()` mid-pipeline, document why with a comment.

## Testing Standards

### Workflow
- **TDD**: Write a failing test first, then implement the minimum code to pass, then refactor.
- **Research before coding**: Understand the regulatory requirement and existing patterns before writing tests.

### Organisation
```
tests/
├── unit/          # Fast, isolated tests (~5,900 tests; reporting/ splits per template)
├── acceptance/    # Scenario-based regulatory tests (~1,500 tests)
├── contracts/     # Protocol/interface compliance tests (~650 tests)
├── integration/   # Cross-component integration tests (~300 tests)
├── benchmarks/    # Performance tests (marked @pytest.mark.benchmark)
├── oracle/        # Human-reviewed regulatory oracle cases (golden referee)
├── fixtures/      # Shared test data builders
└── expected_outputs/  # Golden files for acceptance tests
```

### Conventions
- **AAA pattern**: Every test has clear Arrange / Act / Assert sections
- **Test naming**: `test_<behaviour_under_test>` — describe the what, not the how
- **One assert per concept**: Each test verifies a single logical assertion (multiple `assert` is fine if testing one concept)
- **Fixtures**: Use `@pytest.fixture` for shared setup. Test data builders live in `tests/fixtures/`
- **Markers**: `@pytest.mark.benchmark` for perf tests, `@pytest.mark.slow` for 10M+ scale tests, `@pytest.mark.stress` for the 10K-row correctness-at-scale suite (`tests/acceptance/stress/`)
- **Run tests**: `uv run pytest tests/` runs the dev-loop default — `-m 'not slow and not stress and not scale_1m and not benchmark'` with `--strict-markers`, distributed across workers via `pytest-xdist` (`-n auto --dist=loadfile`). To exercise the stress suite locally use `uv run pytest tests/ -m stress`; CI runs `-m 'not slow and not benchmark'` (stress included) plus a dedicated `benchmarks` job that uploads `benchmark-results.json` as the stored baseline artifact.
- **xdist worker count**: `loadfile` pins each test file to one worker, so session-scoped pipeline fixtures (`pipeline_results`, `crr_sa_result_10k_df`, …) are built per worker, not per test. Polars threads inside each worker — if `-n auto` oversubscribes cores, cap with `-n 4` or `PYTEST_XDIST_WORKER_COUNT=4`.

## Error Handling

- **Data quality errors**: Accumulated in `list[CalculationError]`, never raised. Each has an `ErrorCategory`, `ErrorSeverity`, error code, and optional regulatory reference.
- **Programming errors**: Use standard exceptions (`ValueError`, `TypeError`, etc.)
- **Validation**: Input validation is non-blocking — errors collected via `_validate_input_data()`, pipeline continues with valid data.
- **Error codes**: Prefixed by domain — `DQ` (data quality), `CL` (classification), `SA` (standardised approach), `IRB`, etc.

## Logging

Operational telemetry flows through stdlib `logging`, configured by `rwa_calc.observability`. Regulatory/data-quality issues remain in `CalculationError` — logging is strictly for observability and must never duplicate the error channel.

Rules for new code:
- **Module logger**: every stage module under `engine/` declares `logger = logging.getLogger(__name__)` at the top of file (after imports). Enforced by `scripts/arch_check.py` check 8 and `tests/contracts/test_logging_contract.py`.
- **Stage timing**: every registered stage is wrapped with `stage_timer(logger, spec.name)` by the fold (`engine/orchestrator.py::run_stages`) — a new stage gets timing for free by being added to `engine/registry.py`. Run-level records (pipeline start/finish, materialisation map) stay on `rwa_calc.engine.pipeline`.
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

- **`premise-auditor`** — read-only, Wave 0. Tries to **refute** a plan bullet before any design work starts: does the rule say what the bullet claims, does the code actually diverge, what is the RWA direction, is the scope right. Returns `PREMISE: confirmed | rescoped | refuted`. A refutation is a success.
- **`scenario-architect`** — read-only. Designs one CRR-* / B31-* / P-coded item end-to-end (inputs, hand-calc, citations). The premise audit is authoritative over the bullet.
- **`fixture-builder`** — owns `tests/fixtures/`. Implements parquet rows and builders from a scenario proposal.
- **`test-writer`** — owns `tests/{unit,acceptance,contracts,integration}/`. Writes the failing test that drives the next implementation step.
- **`engine-implementer`** — owns `src/rwa_calc/`. Makes the failing test pass with the minimum diff and a green validation gate (arch_check, ruff, ty, contracts).
- **`reviewer`** — **conformance** gate dispatched after every wave of `/next-items`. Critiques a role-agent's output against operator-supplied wave criteria and returns `VERDICT: pass | revise | drop`. Owns nothing on disk; has `Bash(uv run pytest:*)` solely so it can verify a claimed test outcome rather than trusting a quoted summary line.
- **`skeptic`** — **adversarial** reviewer running in parallel with `reviewer` on the design and implementation waves. Re-derives the number, re-runs the test, and attacks the test's ability to fail. Same verdict grammar; the worst verdict of the two decides the item. Its default is "unproven" — an untested claim is `revise`, not `pass`.
- **`plan-curator`** — owns the single work-queue file at the repo root: `IMPLEMENTATION_PLAN.md` (Tier 5 is the docs queue; `DOCS_IMPLEMENTATION_PLAN.md` was merged into it 2026-08-08 — migrated items keep their D-codes). Audits code/specs/PDFs against each other and writes prioritised bullet items.
- **`doc-writer`** — owns `docs/`. Writes or updates one canonical docs page per Tier 5 item in `IMPLEMENTATION_PLAN.md`; runs `uv run zensical build` before returning.

Orchestration lives in slash commands, not in agents. Each `loop.sh` mode maps to one slash command. The default build / docs_build commands are the **parallel batch** orchestrators (`/next-items`, `/next-docs`); the strict-serial single-item commands (`/next-scenario`, `/next-doc`) remain available for one-off / debugging use.

| `loop.sh` mode | Prompt file | Default command | Strict-serial alternative |
|---|---|---|---|
| `loop.sh` (build) | `PROMPT_build.md` | `/next-items 3` | `/next-scenario` |
| `loop.sh ccr` | `PROMPT_ccr.md` | `/next-items 3 ccr` | `/implement-scenario <P8.x>` |
| `loop.sh plan` | `PROMPT_plan.md` | `/refresh-plan` | — |
| `loop.sh docs_build` | `PROMPT_docs_build.md` | `/next-docs 3` | `/next-doc` |
| `loop.sh docs_plan` | `PROMPT_docs_plan.md` | `/refresh-docs-plan` (audits Tier 5 of the single plan) | — |

The batch commands pick N non-conflicting items and run the validation gate (or `uv run zensical build`) **once at the end** — not per agent. `/next-items` provisions one git worktree per item on `batch/<batch-id>/<P-code>` and drives the **five-wave** pipeline (`premise-auditor` → `scenario-architect` → `fixture-builder` → `test-writer` → `engine-implementer`) as an event-driven supervisor: agents are dispatched in the background (`run_in_background: true`), a `reviewer` gates every wave (`pass | revise | drop`) with a `skeptic` alongside it on the design and implementation waves, one revision retry per wave per item is allowed, and the orchestrator persists batch state to `.claude/state/next-items-<batch-id>.json` so it can survive context compactions and operator interjections across multiple turns.

The end-of-batch gate runs in **tiers**, and **Tier 2 is mandatory**: `tests/oracle/` plus `tests/acceptance/reporting/` (the two-way-ratcheted supervisory validation register and the reporting goldens). Tiers 0–1 alone have repeatedly merged green over defects that Tier 2 catches. `loop.sh` pushes to a feature branch where CI does not fire, so Tier 3 (the full suite, in two foreground chunks) is the only thing that runs the whole estate before the PR. The operator can chat with the orchestrator mid-batch — ask for status, drop an item, inspect outputs — without interrupting in-flight agents. After all items reach `merge_ready` or `dropped`, the orchestrator squash-merges the surviving worktree branches into the current feature branch before the gate runs. `/next-docs` keeps the flat parallel `doc-writer` dispatch (no worktree, no reviewer — docs writes don't collide). Items that touch shared engine/reporting-projection files (`engine/pipeline.py`, `engine/registry.py`, `engine/orchestrator.py`, `contracts/protocols.py`, `contracts/bundles.py`, `contracts/edges.py`, any module under `engine/aggregator/`, `analysis/reconciliation.py`, `reporting/cellspec.py`, `reporting/metadata.py`) are forced single-stream by `/next-items` even when N>1 was requested, and run in the main tree without worktree machinery (the reviewer loop and background dispatch still apply).

Plus `/implement-scenario <ID>` for ad-hoc one-off work on a specific P-code or scenario ID, and `/postmortem <commit|PR|description>` when a defect reaches production.

## The learning loop

Gates catch what they were built to catch. The harness only improves if every
escape and every wasted batch turns into a new gate — so three artifacts are
load-bearing:

- **`.claude/LESSONS.md`** — the working set of traps this project has already
  paid for, in `Trap` / `Why` / `Detect` form. **Every agent reads it before
  starting work**, and its system prompt says so. It is capped at ~30 entries
  and is explicitly *not* an archive: an entry earns its place only while it is
  still prose.
- **`/next-items` Step 7.5 (retro)** — runs before cleanup, while the batch's
  evidence still exists. It separates one-off slips from repeatable patterns and
  **graduates** each pattern into the strongest available form: an `arch_check`
  check → a ratchet → fixture coverage in `RUNS` → a reviewer criterion →
  prose, in that order of preference. Prose is the fallback, not the default.
  Completed batch state is archived to `.claude/state/archive/`, never deleted.
- **`/postmortem` + `docs/development/escape-log.md`** — for defects that reach
  production. The deliverable is not the code fix but the answer to *which gate
  should have caught this, and why didn't it* — classified into one of eight
  escape classes, each of which prescribes its own gate change. The gate change
  is mandatory; the code fix may be deferred.

**The closing rule: a defect found in output is closed by its escape-log entry,
not by its fix commit.** `docs/development/escape-log.md` is the ticket-closing
artifact, and an entry closes a defect only when it carries an escape class, a
named gate change (file path, or a Tier 1 bullet ID if deferred), and evidence
the new gate was **observed red before the fix**. Any of the three missing means
the defect is still open — say so rather than reporting it done. The file sat at
zero entries while defects reached production output, which is exactly what a
fix-commit-closes-it convention produces.

A lesson that reaches production **twice** has proven it cannot survive as
prose — graduate it to an executable check, or file the graduation as a Tier 1
plan item. `scripts/arch_check.py`'s 17 numbered checks and the supervisory
validation register are what graduated lessons look like.

The clearest worked example is the **skill-value graduation (2026-08-08)**. The
regulatory skills restated rulepack values as prose tables and drifted three
times — corporate CQS5 stated as 100% in three files against a pack value of
150%, the QRRE limit as GBP 100k against 90k, and a CRR institution CQS 2 hint
that seeded a wrong scalar into the P8.20 fixture. Each was fixed as prose, and
each recurred. The graduation removed the *category* rather than the instances:
values are now generated into the skills from the pack, and prose that states a
value fails the build. Note the shape — the fix was not "be more careful with
the skills" but "make the skills structurally incapable of holding a value".

Agents never commit or push — commits land in the slash-command orchestrator only. The call graph is uniformly one level deep (orchestrator → role-agent or reviewer); sub-agents do not spawn other sub-agents. Claude Code does not propagate the project's `.claude/agents/` registry into sub-sessions, so a nested Agent call from a sub-agent cannot dispatch project role-agents — keep all dispatch in the slash-command orchestrator. The single root plan file (`IMPLEMENTATION_PLAN.md`) is the source of truth for outstanding work — Tier 5 is the docs queue drained by `/next-docs`, every other tier belongs to `/next-items`; `docs/plans/implementation-plan.md` is published narrative on the Zensical site.

## Documentation

- **Zensical site**: Source in `docs/`, config in `zensical.toml`. Run locally: `uv run zensical serve`
- **Generated pages — never hand-edit**: `docs/data-model/regulatory-tables.md` is rendered from the resolved rulepacks by `scripts/generate_regulatory_tables.py` (freshness gated by `tests/contracts/test_docs_freshness.py` — regenerate after any pack change); `docs/development/citation-matrix.md` by `scripts/generate_citation_matrix.py`; `docs/development/confidence-matrix.md` + `tests/contracts/data/confidence_snapshot.json` by `scripts/generate_confidence_matrix.py` (its evidence layers include a **text scan of the test tree**, so merely naming an article in a test docstring makes it stale).
- **The skills state no regulatory values**: the same `generate_regulatory_tables.py` fills `<!-- BEGIN/END GENERATED: id -->` regions inside `.claude/skills/{basel31,crr}/**/*.md` from the pack, and `scripts/check_skill_values.py` fails any percentage written into skill *prose* outside those regions (justified exceptions go in its `ALLOWANCES` list). Skill prose carries judgment — precedence, scope, mechanics, PRA-vs-BCBS divergence, traps — and names pack entries instead of quoting their values. To add a value to a skill, add the entry to `FRAGMENTS` in the generator and regenerate; never type the number.
- **Dead-link ratchet**: `scripts/check_doc_links.py --check` two-way ratchets the docs dead-link count against `scripts/docs_link_baseline.json` (same contract test). Fixing links requires banking the lower count with `--update-baseline`.
- **Specifications**: Single source of truth is `docs/specifications/`. Do not create a separate `specs/` directory.
- **Docstrings**: All public classes and functions must have docstrings following the module docstring pattern (purpose, responsibilities, references)
- **Changelog**: Update `docs/appendix/changelog.md` for any user-facing changes
- **After every change**: Update relevant docs, docstrings, and changelog entry

### Citation tracking (`watchfire`)

When you implement or modify a function whose responsibility maps onto a specific regulatory article, add a `@cites(...)` decorator alongside the existing docstring reference. Stack one decorator per article — CRR (primary) outer, PS1/26 (secondary) inner — when both frameworks apply to the same code path. The decorator is a no-op at runtime; `uv run watchfire matrix` materialises the article -> function index from these annotations, and `uv run python scripts/arch_check.py` invokes `watchfire check` as the final gate step. See [docs/development/citation-tracking.md](docs/development/citation-tracking.md) for the canonical citation grammar and the parser/index split — watchfire 0.3.1's parser accepts alphanumeric articles (`501a`, `123B`), but the bundled CRR index covers `501a` only; `123B` and `110A` remain Basel-3.1 amendments with no CRR equivalent and should cite the `PS1/26, paragraph …` form.
