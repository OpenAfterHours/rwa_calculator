# Test-suite runtime: where 6m47s goes, and the path to ~4 minutes

**Status:** Proposal, 2026-09-06. Nothing here is implemented. Every number below was
measured on `master` at `cd25836b` (v0.3.34) on the reference dev box (16 cores, 8 xdist
workers, `POLARS_MAX_THREADS=1`) and is reproducible with the commands in the appendix.
The stress suite is out of scope — PR #491 already took it from 9m52s to ~2m15s.

## The finding in one sentence

The dev loop is not slow because thousands of tests each cost a fraction of a second; it
is slow because **about 1,300 tests each run a whole pipeline or a whole COREP
generation**, and the *fixed* cost of one pipeline run — 0.4 s on a single-row frame,
~0.8 s inside the 8-worker suite — is paid roughly 1,250 times, on top of ~1,600 COREP
generations at 0.6–1.3 s each.

The per-test overhead framing is worth killing explicitly, because it points at the wrong
fix. 6,922 of the 13,074 tests (53%) finish in under 10 ms and together cost **20 CPU-s**,
which is 2.5 s of wall on eight workers. Nothing done to pytest, fixtures or collection
for those tests can move the total. The 871 tests that take a second or more are 70% of
the time; the 1,317 that take half a second or more are 82%.

## The measured picture

### Headline

| Quantity | Value |
|---|---|
| Tests run (dev-loop marker filter) | 13,074 (12,992 passed, 81 skipped/xfailed) |
| Wall | 405 s (6m47s) |
| Test-seconds (setup + call + teardown, all workers) | 2,938 s |
| — of which setup (fixtures) | 655 s |
| — of which call | 2,275 s |
| Per-worker busy time | 364–375 s |
| First test report (worker start + collection) | 26.7 s |
| Last test report, per worker | 395–402 s |

Scheduling is already efficient: every worker is busy for ~367 s of a 405 s run, the
workers finish within 7 s of each other, and the 27 s before the first report is
collection. **Wall ≈ collection + (test-seconds ÷ 8).** The only lever on wall time today
is total CPU; the loadfile tail only starts to bind once CPU falls (see §Lever 4).

### Where the time sits, by duration band

| Per-test total | Tests | CPU-s | Cumulative share |
|---|---|---|---|
| < 10 ms | 6,922 | 20 | 0.7% |
| 10–100 ms | 3,172 | 152 | 5.9% |
| 100–500 ms | 1,663 | 356 | 18.0% |
| 0.5–1 s | 446 | 343 | 29.6% |
| 1–2 s | 571 | 808 | 57.1% |
| 2–5 s | 252 | 757 | 82.9% |
| ≥ 5 s | 48 | 502 | 100% |

### By directory

| Directory | Tests | CPU-s | Setup | Call |
|---|---|---|---|---|
| `tests/acceptance` | 2,398 | 990 | 475 | 514 |
| `tests/unit` | 8,398 | 984 | 54 | 925 |
| `tests/integration` | 498 | 409 | 116 | 292 |
| `tests/properties` | 439 | 407 | 0 | 406 |
| `tests/oracle` | 222 | 88 | 0 | 87 |
| `tests/contracts` | 1,005 | 53 | 4 | 49 |
| `tests/conformance` | 114 | 7 | 6 | 1 |

Acceptance setup is 475 s because its session-scoped pipeline fixtures are built **once
per worker**, not once per session — `--dist=loadfile` sends each file to one of eight
workers, and xdist has no cross-worker fixture sharing. That is a known cost, not a
proposal item (see §Not proposed).

### The 15 files that own 45% of the time

| CPU-s | Tests | Setup | Call | File | What it repeats |
|---|---|---|---|---|---|
| 220 | 179 | 0 | 220 | `unit/analysis/test_return_recon.py` | `build_recon` (two COREP generations each) uncached on most paths |
| 143 | 18 | 0 | 143 | `properties/test_monotonicity.py` | 180 single-row pipeline runs (3 rungs × 3 examples × 10 × 2 regimes) |
| 116 | 45 | 49 | 67 | `integration/test_ui_reconciliation.py` | function-scoped `recon_dir` runs `CreditRiskCalc.calculate()` per test; autouse `run_index.clear()` forces a second run per request |
| 95 | 32 | 0 | 95 | `acceptance/reporting/test_crm_substitution_flows.py` | `_run(regime)` is unmemoised: 32 pipeline + COREP runs for 2 distinct inputs |
| 93 | 111 | 1 | 93 | `unit/analysis/test_legacy_ledger.py` | 18 `COREPGenerator().generate` sites + 33 `_load` sites re-writing the same parquet per test |
| 88 | 222 | 0 | 87 | `oracle/test_oracle.py` | one pipeline run per oracle case (by design) |
| 77 | 56 | 0 | 77 | `properties/test_differential_shadow.py` | pipeline per generated portfolio (by design) |
| 77 | 8 | 77 | 0 | `acceptance/reporting/test_supervisory_validations.py` | 18 pipeline + COREP runs in one session fixture (`RUNS`) |
| 57 | 49 | 10 | 46 | `integration/test_rest_api.py` | fresh `TestClient` + cleared run index per test |
| 54 | 52 | 0 | 54 | `properties/test_structural_invariants.py` | pipeline per generated portfolio (by design) |
| 53 | 59 | 0 | 53 | `unit/reporting/test_membership.py` | `_tie_out_census` issues ~18,700 one-cell collects per test |
| 50 | 13 | 0 | 50 | `acceptance/reporting/test_reporting_s1_reconciliation.py` | pipeline + COREP per test |
| 50 | 12 | 25 | 25 | `integration/test_audit_cache_pipeline.py` | full test-fixture pipeline per test to check a directory layout |
| 38 | 39 | 9 | 29 | `acceptance/reporting/test_lineage_tieout.py` | pipeline + COREP + lineage per (template, portfolio, regime) |
| 38 | 40 | 5 | 34 | `integration/test_ui_app.py` | fresh `TestClient` + cleared run index per test |

"By design" marks files whose run count *is* the coverage — the fixed cost per run is
their only lever.

## Anatomy of one run

Measured in a single process, no pytest, no contention. Inside the 8-worker suite the same
run costs ~1.7× (the monotonicity file's 180 single-row runs average 0.8 s).

### Pipeline

| Input | Wall | `collect()` calls | `collect_schema()` calls | Time inside those two |
|---|---|---|---|---|
| 1 exposure, CRR IRB | 0.38 s | 98 | 140 | 0.26 s (68%) |
| 1 exposure, Basel 3.1 IRB | 0.55 s | 96 | 139 | 0.35 s (64%) |
| 150-row acceptance fixture, CRR SA | 0.97 s | 121 | 199 | 0.78 s (80%) |
| 150-row acceptance fixture, CRR IRB | 1.20 s | 123 | 202 | 0.94 s |
| 150-row acceptance fixture, Basel 3.1 SA | 1.52 s | 119 | 198 | 1.10 s |

Per stage on the single-row CRR run: CRM 125 ms, calculators 88 ms, aggregator 40 ms,
re-split 37 ms, hierarchy 34 ms, classifier 26 ms. On the 150-row fixture CRM is 630 ms
of 970 ms. The stage plans are not the cost — the *number of separate plan executions* is.
Concretely, on the 150-row run:

- **Warning recorders re-execute deep lazy plans to find a handful of rows.** 14
  `_record_*` functions under `engine/`, 10 of which call `.collect()` on the stage's
  un-materialised plan. `crm/third_party_deposit.py::_record_third_party_deposit_warnings`
  alone is 78–123 ms of a 970 ms run; `crm/guarantees.py::_record_ineligible_guarantors`
  36 ms.
- **Schema resolution is repeated on un-materialised plans.** 199 `collect_schema()` calls
  cost 0.25 s (0.42 s under Basel 3.1). `engine/crm` has 67 call sites; `contracts/edges.py::conform`
  is called 18 times per run and resolves the schema each time (65–84 ms).
- **The input-domain gate runs 10 separate collects.** `contracts/validation.py::validate_bundle_values`
  is 89–120 ms per run via `_validate_table_columns_batched`.
- The six `materialise_edge` calls (0.26–0.32 s) are the real work and stay: the memory
  on the single-lazy-plan segfault says why they must remain eager.

### COREP generation

| Framework | Wall | `RowPredicate._compile` calls | `pl.lit` calls | `collect()` calls |
|---|---|---|---|---|
| CRR | 0.60 s | 4,849 | 778 | 159 |
| Basel 3.1 | 1.33 s | 7,634 | 1,027 | 156 |

The profile of one CRR generation (1.93 s under cProfile) shows C 07.00 at 1.5 s, and
roughly **half of the cost is Python-side expression construction**: 23k `pl.lit`, 32k
`pl.col`, 119k `wrap_expr`, 419k `isinstance`. `_compile` is called 4,849 times for a
predicate set that does not change between generations. Every one of those expressions is
a pure function of (predicate, column set) and can be built once. Pillar 3 is 0.06 / 0.15 s
and not worth touching.

### Collection

Single-process collection of the tree is 9.9 s; with eight workers each collecting the
full tree concurrently the first test starts at 26.7 s. Inside it: importing 744 test
modules 5.9 s, parametrisation 4.1 s, and 2.3 s in hypothesis's `_get_local_constants`
(it walks `sys.modules` for constants at collection; hypothesis 6.165 exposes no switch).
Seven percent of wall; a second-order lever.

## Levers, ranked

Each lever names what stays unchanged. None changes a marker, an example count, an
assertion, or a fixture's data. The projections are CPU-seconds; divide by 8 for wall.

### Lever 1 — stop repeating work inside test files (≈ −450 CPU-s, tests only)

The cheapest and safest lever: the same pipeline run or template generation is rebuilt per
test where a module-level memo would do. One PR per row; each is verified by re-running
the timing plugin on that file alone.

| File | Today | Fix | Target |
|---|---|---|---|
| `acceptance/reporting/test_crm_substitution_flows.py` | 32 runs of 2 distinct inputs | `@lru_cache` on `_run(regime)`; tests read the frames, never mutate them | 95 → ~10 s |
| `integration/test_ui_reconciliation.py` | 45 dataset writes + 45 `calculate()` in setup, and a second `calculate()` per request because `run_index.clear()` is autouse | build the dataset and `ours` once per module (`tmp_path_factory`); copy the directory per test where a test writes into it; keep the run-index clear only on the tests that assert cold-start behaviour | 116 → ~35 s |
| `unit/analysis/test_return_recon.py` | `_combined` / `_single_cause` are cached, `_slotting_single_cause` and nine inline `build_recon` calls are not; 73 tests in the 0.5–3 s band | cache the slotting pairs on `(cause, framework)`; route the inline builds through the cached helpers where the inputs are identical | 220 → ~110 s |
| `unit/analysis/test_legacy_ledger.py` | 18 `generate` + 33 `_load` sites over two fixed `_ROUTES` | memoise the reference-side bundle per `(route, framework)` and the loader per `(route, rows-key)`; the legacy parquet is written once per module | 93 → ~45 s |
| `integration/test_audit_cache_pipeline.py` | 16 full-fixture runs to test run-dir pruning and manifest keys | a one-row bundle for the lifecycle tests; keep the full fixture for the two tests that assert artefact contents | 50 → ~12 s |
| `unit/reporting/test_membership.py` | `_tie_out_census` collects one cell at a time (~18,700 collects per test) | one `group_by` over the membership keys, then dictionary lookups | 53 → ~20 s |
| `integration/test_rest_api.py`, `integration/test_ui_app.py` | fresh app + cold run index per test | module-scoped client; a module-scoped warmed run for the tests that only assert on response shape | 95 → ~50 s |
| `unit/test_pipeline.py` | 18 full runs on function-scoped fixtures | module-scoped result fixtures for the read-only tests | 32 → ~12 s |

**Rule for every memo:** the cached object is shared and must be read-only. A test that
needs to mutate what it gets calls the uncached builder — `test_return_recon.py` already
documents the memo-poisoning failure this prevents.

### Lever 2 — cut the fixed cost of a pipeline run (≈ −400 to −500 CPU-s, and faster production)

This is the lever the "by design" files depend on: oracle, properties, monotonicity, the
acceptance session fixtures. Target: a single-row run from 0.38 s to ~0.20 s and the
150-row fixture from 0.97 s to ~0.60 s, with the per-run collect count as the ratchet.

1. **Recorders read the materialised edge, not the plan.** Every `_record_*` that filters
   the stage frame to raise warnings runs after the stage's `materialise_edge` and filters
   the collected frame (`.lazy()` wrap, one cheap scan), or the stage batches the gate
   columns into the one collect it already does. Output must be byte-identical: the golden
   and oracle suites plus a `CalculationError` count/code assertion on the 150-row fixture
   prove it. ≈ −0.15 s per 150-row run.
2. **Resolve each stage's schema once.** Replace the 67 `collect_schema()` sites in
   `engine/crm` with a `cols: frozenset[str]` computed once per stage function at the
   materialised edge and passed down; `contracts/edges.py::conform` takes the schema it is
   handed instead of re-resolving. ≈ −0.15 s (CRR) to −0.3 s (Basel 3.1) per run.
3. **Batch the input-domain gate.** `_validate_table_columns_batched` issues ten collects;
   one `collect_all` over the ten small aggregations. ≈ −0.06 s per run.
4. **Graduate the number into a check.** A dev-loop contract test that runs a one-row
   bundle under a `collect()` / `collect_schema()` counter and ratchets both counts
   *downward* — the same shape as the nested-window scaling guard from PR #488 and the
   reporting coverage ratchet. This is the lesson the learning loop asks for: the count
   drifted up to 98 + 140 with nobody noticing because nothing measured it.

### Lever 3 — compile COREP cell expressions once (≈ −150 to −200 CPU-s)

`RowPredicate` is a frozen dataclass, so `_compile(cols)` memoises cleanly on
`(self, frozenset(cols))`; the per-template cell aggregation lists in
`cellspec._evaluate_batched` are likewise a pure function of (template, framework, column
signature). `pl.Expr` is immutable, so cached expressions are safe to reuse across frames.
Expected: ~40% off every generation (0.60 → ~0.35 s CRR, 1.33 → ~0.8 s Basel 3.1) across
~1,600 generations, minus what Lever 1 removes first. Verified by the reporting goldens and
the supervisory register, which must not move at all.

### Lever 4 — the tail, once CPU falls (wall only)

After Levers 1–3 the estate is ~1,850 test-seconds, ~230 s across eight workers. Under
`loadfile` a file cannot be split across workers, so wall is bounded below by the longest
single file plus collection. Today's longest files after the fixes above are
`test_return_recon.py` (~110 s), `test_monotonicity.py` (~85 s with Lever 2) and
`test_supervisory_validations.py` (~55 s with Levers 2–3) — under the ~230 s per-worker
budget, so no split is needed to reach the target. Split `test_return_recon.py` by template
family (C 07.00 / C 08.01–08.03 / C 08.06) only if a later measurement shows it binding.

### Lever 5 — collection (≈ −10 s wall)

Second order. The worthwhile pieces are cheap: the hypothesis constants scan cannot be
disabled, but every conftest that imports `rwa_calc` at module level for one fixture can
defer that import into the fixture (the acceptance conftests already do), and the 4.1 s
of parametrisation is dominated by a few very wide `parametrize` products that could be
generated lazily. Measure before touching: single-process `--collect-only` is 9.9 s and
the plugin's *first report* column shows the fleet figure.

## Not proposed, and why

- **Lowering hypothesis example counts or oracle case counts.** That is coverage, not
  overhead; the properties and the oracle are the parts of the estate that found real
  defects the unit suite missed.
- **Batching oracle cases into one pipeline run.** Per-case isolation is what makes an
  oracle disagreement attributable. Lever 2 gives those 222 runs the same saving without
  losing it.
- **A persistent on-disk cache of pipeline results keyed on a source-tree hash.** It only
  pays off when `src/` has not changed since the last run, which in this dev loop is the
  minority case, and a stale-key bug would be a silent false green.
- **Raising `-n` above 8.** Available RAM fell below 500 MB during the run at 8 workers.
- **Cross-worker sharing of the acceptance session fixtures.** xdist cannot do it; pinning
  the acceptance tree to one worker with `--dist=loadgroup` would create exactly the tail
  Lever 4 avoids.

## Sequence and projection

| Phase | Content | CPU-s saved | Wall after |
|---|---|---|---|
| 0 | Commit the timing plugin; bank this baseline | — | 6m47s |
| 1 | Lever 1, one PR per file group; re-measure each file | ~450 | ~5m50s |
| 2 | Lever 2 items 1–3 behind the collect-count ratchet (item 4), landed first as a red test | ~450 | ~4m50s |
| 3 | Lever 3 | ~170 | ~4m30s |
| 4 | Lever 5; re-measure; split a file only if it binds | ~10 s wall | ~4m15s |

Projection: **2,938 → ~1,850 test-seconds, 6m47s → roughly 4m15s**, with the same 13,074
tests, the same assertions and the same example counts. Getting materially below four
minutes from there needs one of the items in §Not proposed, which is a different
conversation.

Phase 2 is the only phase that touches `src/rwa_calc/`, and it also speeds every
production run — the 150-row fixed cost is what a small book pays per run, and the
recorder and schema costs scale with plan depth, not row count.

## Appendix — reproducing the numbers

```bash
# Full dev loop with per-test timings (controller writes PERF_OUT at session end)
PYTHONPATH=scripts PERF_OUT=timings.json uv run pytest tests/ -p pytest_timings -q

# The report: bands, directories, files, workers, slowest tests, setup-heavy files
uv run python scripts/pytest_timings.py timings.json

# One file after a Lever 1 change
PYTHONPATH=scripts PERF_OUT=one.json uv run pytest tests/unit/analysis/test_return_recon.py -p pytest_timings -q -n 0

# Single-process collection cost
uv run pytest tests/ --collect-only -q -n 0
```

The per-run anatomy was measured by wrapping `pl.LazyFrame.collect` / `collect_schema`
with counters around one `PipelineOrchestrator().run_with_data(...)` on (a) a one-row
`tests/properties/portfolios.py` bundle and (b) the acceptance fixture via
`tests/acceptance/acceptance_helpers.build_raw_bundle`, reading the stage times from the
`elapsed_ms` extra that `observability.context.stage_timer` puts on its log records, and
`cProfile` for the call attribution. The COREP figures wrap `RowPredicate._compile` and
`pl.lit` the same way around `COREPGenerator().generate_from_lazyframe`.
