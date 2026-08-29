# Architecture review — structure, efficiency, parallelism (2026-08-29)

> **Status: EXECUTED 2026-08-29.** All seven items are closed — see
> [§0 Outcome](#0-outcome-what-was-actually-built) for what landed, which
> figures below turned out to be wrong, and what the batch found that this
> proposal did not anticipate.
>
> **The body of this document is left as written**, at `dbc2932a` (v0.3.27),
> including the numbers §0 corrects. It is the record of what was proposed and
> why; §2 in particular quotes the pre-move `CLAUDE.md` text verbatim as the
> thing item S1 reverses, so editing it would delete the argument for the change
> inside the record of the change.

---

## 0. Outcome — what was actually built

Seven items, ten commits, ~12,400 tests green. Each item ran
implementer → conformance reviewer → adversarial skeptic, with the worse of the
two verdicts deciding. **Five of seven items came back `revise` at least once**,
and in four of those the finding was invisible to a fully green suite.

| item | outcome | commit |
|---|---|---|
| **E4** — declared-vs-read column width | **closed by measurement, no code** | — |
| **P1** — batch scoped runs over a process pool | built | `9e572c30` |
| **E1** — one-pass cellspec executor | built | `8cb6d5e9` |
| **S2** — `StageComponents` | **froze it, and recorded why** | `d9766235` |
| **E2** — read the results frame once per filing | built | `3b2113dd`, `d46697c8` |
| **E3** — thread resolved schemas | built | `672f7594`, `ac359584` |
| **S1** — hoist domains out of `engine/stages/` | built | `90182122` |
| ratchet banking | — | `5ba85bb8`, `5c3a9435` |

### 0.1 Figures in this document that are wrong

Stated plainly, because they are quoted above and someone will read them:

- **§3.1's 7.8× for E1 is too high.** It came from two separate processes on a
  box that drifts ~2× between them. Measured in-process, alternating both
  algorithms: **6.8–6.9×** on C 07.00. Collect and filter counts were exact
  (14,642 → 18, 5,427 → 0).
- **§3.1 implies a single speedup; it is scale-dependent.** ~6.8× at C 07.00's
  shape (604 distinct predicates, ~2.2 cells each) rising to 15.7× at 50k rows.
- **§3.2's E2 win is portfolio-shaped, not scale-shaped.** Measured: **up to
  2.3× at 100k on an SA-only book, ~1.4× at 37k with live IRB**. The 2.3× is an
  upper bound — ~20 IRB templates each pay a full source scan then aggregate an
  *empty* population, maximising exactly the scan-to-work ratio E2 removes.
- **§3.3's E3 saving cannot be stated as one number.** Regime moves the count;
  row count and permission mode do not. **B3.1 206 → 193, CRR 207 → 195.** The
  `207 → 192` in commit `672f7594`'s message splices the CRR baseline onto a
  pre-guard B3.1 figure and overstates the saving twice over.
- **§3.4 was answered and the answer was "do nothing".** 334 of 342 columns at
  `aggregator_exit` are consumed downstream; 8 ride through unread. ~2% — not a
  lever.
- **A memory projection made during the batch, not in this document, was wrong
  by an order of magnitude** and is recorded here so it is not re-derived:
  extrapolating E2's +122–184 MB at 37k linearly gave 1.2–1.8 GB at 100k. The
  measured 100k delta is **+115 MB, inside the noise** — the shared frame
  displaces allocations the ~30 separate scans were making anyway.

### 0.2 What a green suite did not catch

Four findings that ~12,400 passing tests, `arch_check`, `ruff` and `ty` were all
green through:

1. **S1 broke the docs build.** Three `mkdocstrings` directives addressed deleted
   modules; `.github/workflows/docs.yml` runs `zensical build --clean` on every
   push to `master` touching `src/rwa_calc/**`. It would have broken CI on merge.
2. **52,102 characters had silently vanished from published pages.**
   `zensical.toml` sets `check_paths = false`, so a missing `--8<--` include
   emits nothing and raises nothing — and the build still exits 0. Now gated by
   `tests/contracts/test_doc_snippet_includes.py` (322 directives, asserts the
   content resolves, vacuity floor 150).
3. **E1 deleted an explicit `data.height == 0` guard** and relied on Polars
   returning null from `.drop_nulls().first()`. Correct — but no test in the
   repository reached it, and it is live via OV1's unpredicated `FirstNonNull`
   on an empty portfolio. Six branch tests added.
4. **`ensure_columns(present=)` fails silently and destructively** when
   under-specified: `with_columns` on an existing alias *replaces*, so an
   omission overwrites a live column with a typed null, and at the
   `ofcp_routing` site that null meets `.fill_null(True)` and flips every A-IRB
   leg onto the LGD-Modelling route. No current caller was vulnerable; it was a
   loaded gun. Guarded, at one extra resolution per run.

### 0.3 To file separately — found during the batch, out of scope for it

- **Tier 1: no production path passes `output_floor_summary` to
  `COREPGenerator`.** All seven supplying call sites reach a Pillar 3 generator
  or a formatter; two COREP export entry points do not even declare the
  parameter. C 02.00 / OF 02.00 rows 0035 and 0036 therefore publish **`0.0`,
  not null** (deliberate `else` branch at `c02.py:920-922`), across cols
  0010/0020/0030 — six cells. Row 0034's activation flag *is* populated
  correctly from `rwa_pre_floor`, so a Basel 3.1 filing with a binding floor
  states "floor activated = 1, floor percentage = 0%, OF-ADJ = 0" —
  self-contradictory on the face of a mandatory own-funds template. Same root
  cause leaves `output_floor_config` unsupplied, so the Art. 92(2A) gate always
  resolves "applicable" and OF 02.01 can never be suppressed. Pre-existing:
  `701bdf68e`, 2026-07-19, an ancestor of `master`.
- **The benchmark harness routes everything to SA.**
  `create_raw_data_bundle` supplies no `model_permissions`, so
  `PermissionMode.IRB` logs its warning and every IRB template runs on an empty
  population. This distorted three separate measurements in this batch. The
  check that would have caught it every time: read `approach_applied` off the
  result frame rather than trusting `permission_mode`. Wants a fixture.
- **The Art. 200(1) routing carriers are never exercised with a non-zero
  value.** `ofcp_lgd_cash_deposit`, `ofcp_lgd_life_insurance` and
  `ofcp_substitution_amount` read `0.00` on every registered portfolio, because
  none has both A-IRB rows and non-zero other-funded protection.
- **`COLLECT_ALLOWLIST` matches on basename**, so a new
  `reporting/kernel/materialise.py` would be silently exempt from check 3's
  `.collect().lazy()` ban. Latent, independent of this batch.
- **Doc paths are ungated.** A `check_doc_paths.py` prototype exists; 4 paths
  named in live docs do not resolve on disk, all pre-existing.

### 0.4 Lessons this batch paid for

- **A path rewrite is scoped by what references the path, not by ownership.**
  S1's sweep script excluded `docs/` because it sat outside the stated remit —
  and that exclusion was the entire blast radius of the two worst findings.
- **A mechanical sweep can turn stale-but-honest documentation into
  confidently-wrong documentation.** Two instances, and the second is the
  instructive one. First: `stage.py` moved the *opposite* way to its package, so
  the rewrite pointed at a file existing nowhere — the original text was at
  least historically true. Second, and less obvious: the sweep refreshed the
  arrow targets on two tree-diagram lines that described files **already
  deleted** (back-compat shims banned by check 18), so documentation of things
  that no longer exist came out reading as freshly maintained. The failure was
  not the sweep touching the wrong file; it was the sweep touching the *right*
  file and making a false statement look current. "Re-read every changed line"
  only catches that if the reader thinks to ask whether the line should exist at
  all. Close such a class **by existence** — every path named in live docs must
  resolve on disk — not by re-grepping.
  Two caveats for anyone writing the next sweep: the 12-file exclusion above
  must be carried forward, or it overwrites the record of a change with the
  change; and promoting `check_doc_paths.py` to a gate requires distinguishing
  genuinely broken paths from deliberately illustrative ones, or it reds on the
  "Adding a Custom Calculator" guide's fictional examples.
- **Extrapolating one measurement is not measuring.** Both figures this batch
  got badly wrong (E2's memory, E1's speedup) came from scaling a single
  observation instead of taking the second one.
- **A ratchet bump wants the state it measures to be final.** `5ba85bb8` banked
  mid-pass on a number a later commit in the same item made obsolete;
  `5c3a9435` undoes it.
- **A right conclusion resting on a wrong argument survives review and gets
  reused.** Two instances: `materialise_frame`'s absence from the
  materialisation map was justified by import direction (`_capture` is a
  `ContextVar` — dynamically scoped; the true reason is that it never touches
  `_capture` at all), and a guard docstring claimed to prevent "drift" that had
  never occurred (the layout it guards against was a deliberate prior decision).

---

Three questions were asked:

1. `engine/stages/` reads like "the stages of the calc", yet it is a *sub*folder
   of the engine. Is it in the right place?
2. Is the work being done as efficiently as possible?
3. Are processes set up to be parallelised as much as possible?

The short answers: **(1) the folder is doing two unrelated jobs under one
name** — that is the thing that feels wrong, and it is fixable mechanically.
**(2) No — the reporting pass costs 4.5× the entire calculation, and 7.8× of
that is recoverable with a number-neutral change.** **(3) Parallelism is not
the lever.** The pipeline gets 1.16× from 16 cores where a genuinely
data-parallel workload on the same box gets 4.9×; it is bound by a long serial
chain of small operations, not by a shortage of workers. The one place more
parallelism does pay is *between* runs, not inside one.

---

## 1. What was measured

Reference box: 16 cores. Dataset: the cached `10k` benchmark portfolio
(10,000 counterparties → **37,443 result rows × 321 columns**) and `100k`
(→ 373,928 rows). Framework: Basel 3.1, `PermissionMode.IRB`.

### 1.1 Where the wall time goes

| Phase | Wall time (10k) | Share |
|---|---:|---:|
| Full calculation pipeline (loader → aggregator) | **2,820 ms** | 17% |
| COREP template generation | **12,694 ms** | 75% |
| Pillar 3 template generation | **1,309 ms** | 8% |

**Generating the returns costs 4.5× more than calculating them.** That is the
single most surprising number in this review, and §3 is mostly about it.

Per-stage breakdown of the 2,820 ms calculation:

| Stage | ms |
|---|---:|
| `crm_processor` | 1,145 |
| `calculators` | 882 |
| `hierarchy_resolver` | 277 |
| `aggregator` | 149 |
| `classifier` | 131 |
| `re_splitter` | 116 |
| `resolve_scope` / `securitisation_allocator` / `ccr_sa_ccr` / `sft_fccm` / `equity_calculator` | ~0 |

### 1.2 The stage-edge materialisation map

Captured via `begin_edge_capture(count_plan_nodes=True)`:

| edge | rows | cols | plan nodes | wall ms |
|---|---:|---:|---:|---:|
| `hierarchy_exit` | 36,372 | 91 | **2,514** | 191 |
| `classifier_exit` | 36,372 | 144 | 175 | 146 |
| `crm_post_ead` | 36,372 | 185 | 148 | 111 |
| `crm_pre_guarantee_unified` | 36,372 | 215 | **4,438** | 225 |
| `crm_exit` | 36,372 | 231 | 1,259 | 114 |
| `re_split_exit` | 37,443 | 235 | 131 | 80 |
| `sa_branch` / `irb_branch` / `slotting_branch` | 37,443 / 0 / 0 | 248 / 282 / 256 | 81 / 154 / 119 | 600 (one shared `collect_all`) |
| **total** | | | | **2,667** |

Two things stand out: the frame **accretes 91 → 282 columns** across the run,
and every eager edge materialises all of them; and two edges carry
deep plans (4,438 and 2,514 nodes) against the ~25,000-node SIGSEGV ceiling
documented in `engine/materialise.py`. The ceiling is not at risk — but plan
depth is exactly what §3.3's fixed cost is proportional to.

---

## 2. Question 1 — is `engine/stages/` in the right place?

### 2.1 The actual problem: one name, two jobs

`engine/stages/` currently holds **two structurally different kinds of thing**:

| Registry stage | What lives in `engine/stages/` | Where the domain logic lives | LOC in `stages/` |
|---|---|---|---:|
| `resolve_scope` | **the whole domain** | — (no sibling) | 744 |
| `securitisation_allocator` | thin adapter | `engine/securitisation/` (493) | 70 |
| `hierarchy_resolver` | **the whole domain** | — (no sibling) | 3,943 |
| `ccr_sa_ccr` | thin adapter | `engine/ccr/` (3,625) | 262 |
| `sft_fccm` | thin adapter | `engine/sft/` (730) | 151 |
| `classifier` | **the whole domain** | — (no sibling) | 2,992 |
| `crm_processor` | thin adapter | `engine/crm/` (9,989) | 58 |
| `re_splitter` | **the whole domain** | — (no sibling) | 1,997 |
| `calculators` | thin adapter | `engine/{sa,irb,slotting}/` (11,303) | 203 |
| `equity_calculator` | thin adapter | `engine/equity/` (1,258) | 82 |
| `aggregator` | thin adapter | `engine/aggregator/` (2,929) | 158 |
| *(not a stage)* | `stages/fx/` — helper called from inside `stages/hierarchy/resolver.py` | — | 585 |

So for **7 of 11 stages** `engine/stages/<name>` means *"the 58–262 line wiring
adapter for the domain that lives at `engine/<name>`"*, and for **4 of 11** it
means *"the entire 744–3,943 line domain"*. A reader opening the directory
cannot tell which without opening the files. That asymmetry — not the nesting —
is what makes the folder feel wrong.

The nesting itself is right. `engine/stages/` is a *sub*folder of the engine
because the stages are the engine's wiring, not its content: the ordered list
lives in `engine/registry.py`, the fold in `engine/orchestrator.py`, the
lifecycle in `engine/pipeline.py`. Those three plus `stages/` are one layer.

Two further signs the current split is not load-bearing:

- **The stage↔domain map is not 1:1 and never can be.** `calculators` drives
  three domains (SA, IRB, slotting) from one adapter; `fx` is a domain with
  *no* stage, parked in `stages/` and invoked from inside another stage's
  resolver. A directory named after the pipeline steps cannot also be the home
  of the domains.
- **The separation already exists inside the co-located packages.**
  `stages/hierarchy/` already has `stage.py` (88 lines — the `run` adapter) sitting
  beside `enrich.py` (1,124), `facility_undrawn.py` (1,009), `graph.py` (665).
  The adapter is already a distinct file. Only the directory boundary is missing.

### 2.2 Proposal — `stages/` becomes wiring, and only wiring

```
engine/
  registry.py  orchestrator.py  pipeline.py  materialise.py   ← the runtime
  stages/          one adapter module per registry stage, 11 files, 58-262 loc each
  hierarchy/  classify/  re_split/  scope/  fx/               ← MOVED here
  crm/  sa/  irb/  slotting/  ccr/  sft/  cva/  equity/
  securitisation/  aggregator/  kernels/                      ← already here
```

Concretely: move `stages/{hierarchy,classify,re_split,scope,fx}/` to
`engine/{hierarchy,classify,re_split,scope,fx}/`, leaving each package's
existing `stage.py` behind as `engine/stages/<name>.py`. After the move,
**`engine/registry.py` is a literal table of contents for `engine/stages/`**,
every domain is a peer under `engine/`, and the answer to "what is a stage?" is
"a file in `stages/` named in `registry.py`" with no exceptions.

`fx` moves regardless of the rest: it is not a registry stage (it is pinned in
`arch_check.STAGE_PACKAGES_WITHOUT_RUN` precisely because it has no `run`), it
has four importers, and it is invoked from inside `hierarchy/resolver.py`. It
is a domain sitting in the wiring folder.

**Cost.** 18 source files and 59 test/script files import from these paths.
The move is mechanical (path rewrite, no logic change) but wide, and it is the
kind of change that must land alone in a single-stream batch.

**This reverses a deliberate choice, and should be recorded as such.**
`CLAUDE.md` currently states *"Each stage package is the single home of its
component… Import `HierarchyResolver` from `engine.stages.hierarchy`"*. That
rule has two parts: *single home* (keep — no aliases, no shells, `arch_check`
check 18 stays) and *which directory* (change). Landing this means updating
`CLAUDE.md`, the four package docstrings, and `arch_check`'s
`STAGE_PACKAGES_WITHOUT_RUN` (which becomes empty and can then be deleted
along with the allowlist).

**Cheaper alternative if the churn is unattractive:** keep co-location, but
make the rule explicit and executable — a new `arch_check` check that a package
under `engine/stages/` is *either* an adapter under N lines *or* the sole home
of a domain with exactly one consumer and no `engine/<name>/` sibling. Move
`fx` either way. This costs almost nothing and stops the drift, but it does not
fix legibility for someone browsing the tree — it only documents the
asymmetry. **Recommendation: do the move.** It is a one-batch job that pays
back every time someone reads the engine.

### 2.3 Adjacent: the adapter-era scaffolding is explicitly temporary

`orchestrator.py::StageComponents` describes itself as *"Adapter-era
scaffolding: as each stage converts to the uniform function-module anatomy its
slot here is deleted; the dataclass goes with the last class-shaped stage."*
All ten slots are still there. For the seven adapter stages the
class + protocol layer is doing nothing the module-level `run` function does
not already do — the components are rebuilt per run, hold no state, and are
looked up out of the context by a single caller. Either finish that conversion
or record that it is frozen; a scaffold with no demolition date reads as
architecture to the next person.

---

## 3. Question 2 — efficiency

### 3.1 E1 — the cellspec executor evaluates one cell at a time *(the big one)*

**Finding.** `reporting/cellspec.py::execute` is the single declarative
executor behind the whole COREP + Pillar 3 estate. Generating C 07.00's nine
exposure-class sheets costs **7,941 ms** and issues **14,642 separate
`LazyFrame.collect()` calls** and **5,427 `DataFrame.filter()` calls**. Across
the full COREP run: 16,787 collects, 43,967 `pl.lit()` calls, 896,062
`isinstance` checks.

**Why.** The executor already batches the *predicate masks* — `_predicate_subsets`
compiles every distinct predicate in one `select`. But it then **materialises a
physically filtered copy of the sheet frame for each distinct predicate**
(C 07.00 has 5,436 distinct predicates across its 18,144 cells) and evaluates
each cell against its copy via `_evaluate`. Every `col_sum` / `data[col].mean()`
in `_evaluate` is a separate Polars call, and in Polars an eager
`DataFrame.select` is `self.lazy().select(...).collect()` — so each cell pays a
full plan-construct-optimise-collect round trip on a frame it just copied.

**The fix.** Compute masks once as boolean columns, then express *every cell in
a sheet as one aggregation expression over the unfiltered frame* —
`pl.col(x).filter(mask_k).sum()` and friends — and evaluate all of them in a
single `select`. Same masks, same aggregations: number-neutral by construction.

**Measured on a working prototype** (`execute_batched`, run against the real
`c07_plans` output):

| | current | batched | |
|---|---:|---:|---|
| C 07.00, 9 sheets | 7,941 ms | **1,016 ms** | **7.8×** |
| `LazyFrame.collect()` calls | 14,642 | 18 | |
| `DataFrame.filter()` calls | 5,427 | 0 | |
| cells compared | | 19,440 | **0 mismatches** |

Because `execute` is the *one* executor, the win generalises to every
declarative template — C 07/C 08/C 09/OF 02 and CR4–CR10/OV1/CMS1/CMS2. On the
measured profile the executor is ~74% of COREP generation, so COREP should drop
from ~12.7 s to roughly ~4 s.

**Caveats, stated honestly.**
- The prototype leaves `SideContext` and `PriorPeriod` on the existing
  per-cell path (they read the context / prior frame, not the sheet frame).
  That fallback must build subsets only for *its own* predicates — building
  them for the whole spec is what made the first prototype only 1.2×.
- The prototype's `Ratio` branch returns `None` for an absent column where
  `_evaluate` returns `0.0` under COREP `empty_cell="zero"`. It did not fire on
  C 07.00 but it is exactly the class of divergence that matters. **Each
  binding kind must be re-derived line-by-line against `_evaluate`, and the
  reporting goldens plus the supervisory validation register are the gate** —
  not the 7.8×.
- Measured on one dataset, one box, C 07.00 only.

**Effort:** M. **Risk:** medium — it touches `reporting/cellspec.py`, which
`/next-items` forces single-stream. **Value:** the largest single efficiency win
available, and it is provably number-neutral.

### 3.2 E2 — the results parquet is re-scanned once per template

`CalculationResponse.scan_results()` is `pl.scan_parquet(self.results_path)`.
Each `generate_*` function calls it and collects its own population —
`_non_slotting(results, cols).collect()` appears five times in `corep/c08.py`
alone, `c07_population(...).collect()` again in `c07.py`, and so on across ~30
templates. On the production path (`api/rest.py:842-844`) COREP and Pillar 3
each scan independently.

Projection and predicate pushdown blunt this, but it is still ~30 re-reads and
~30 re-executions of overlapping filter work on every filing. **Fix:** collect
the results frame **once** at the generator boundary and thread the eager
`DataFrame` down; the per-template functions already accept a frame.
**Effort:** S. **Risk:** low. Do it *after* E1 — E1 changes what the templates
ask for.

### 3.3 E3 — schema resolution is a ~700 ms fixed tax per run

`LazyFrame.collect_schema()` is called **206 times per pipeline run**, costing:

| scale | rows | collect_schema | share of run |
|---|---:|---:|---:|
| 10k | 37,443 | **668 ms** | **21%** |
| 100k | 373,928 | **694 ms** | 3% |

Near-identical absolute cost at 10× the rows confirms it is **O(plan nodes),
not O(rows)** — a fixed per-run tax that hurts small books, the interactive UI,
and the ~700-file test suite, and disappears into the noise on big ones. Top
sites: `contracts/edges.py:185` (18 calls, 95 ms — inside `EdgeContract.conform`),
`data/column_spec.py:265` (14 calls, 79 ms — `ensure_columns`), and a cluster
in `engine/crm/guarantees.py` (11 calls, ~160 ms).

**The structural point:** since Phase 3 every stage boundary is producer-sealed,
so **the column set at each edge is already known statically from the edge
contract**. A stage handed an edge-sealed frame should not need to walk a plan
to learn its columns — it can read `EDGE.columns.keys()`. The `cols: set[str]`
parameter threaded through the reporting modules is exactly this idea applied
one layer up.

**Fix, cheapest first:** (a) have `conform` reuse the schema it already
resolved rather than re-resolving downstream; (b) give `ensure_columns` an
optional caller-supplied column set; (c) inside CRM, resolve the schema once
per checkpoint and thread it. **Effort:** S–M each. **Risk:** low — these are
read-only lookups; if the answer changes, something else is already wrong.

### 3.4 E4 — the frame is 282 columns wide by the time it reaches the calculators

91 → 144 → 185 → 215 → 231 → 235 → 248/282 columns across the eager edges (§1.2).
Every edge materialises the full width, and `contracts/edges.py` is 2,328 lines
of hand-declared columns to keep it that way. Eager edges are the right call —
`engine/materialise.py` documents the SIGSEGV evidence and it is convincing —
but they do mean projection pushdown cannot reach across a stage boundary.

**This is an observation, not yet a proposal.** The measurement to take first:
how many of the 231 columns declared at `crm_exit` are actually read after it?
If the answer is "most", the width is real and there is nothing to do. If it is
"half", trimming the contracts is a memory and time win at every edge and at
the results parquet. **Effort:** S to measure, unknown to fix. Do the
measurement before proposing anything.

---

## 4. Question 3 — parallelism

### 4.1 The measurement

Same box, same script, only `POLARS_MAX_THREADS` changed:

| workload | 1 thread | 16 threads | speedup |
|---|---:|---:|---:|
| **Control** — `group_by` + 3 aggs over 2M rows | 118 ms | 24 ms | **4.9×** |
| **RWA pipeline**, 10k (37k result rows) | 3,254 ms | 2,802 ms | **1.16×** |
| **RWA pipeline**, 100k (374k result rows) | 32,637 ms | 32,378 ms | **1.01×** |

The control proves the thread pool works on this machine. The pipeline captures
almost none of it — **and no more at 374k rows than at 37k**. The pipeline is
not starved of workers; it is a long serial chain of individually small
operations, where per-operation fixed cost (plan construction, schema
resolution, the eager-edge barriers) dominates the per-row work. Throwing
threads or processes at a single run buys ~1.2× at best.

**So: more parallelism inside a run is the wrong lever.** E1 and E3 are the
right ones — they remove operations rather than spreading them.

### 4.2 What is already parallel, and correctly so

- **CI** — 8 independent jobs (lint, typecheck, test, benchmarks, spill,
  template-coverage, branch-census, coverage-ratchet).
- **Tests** — `pytest-xdist`, `-n 8 --dist=loadfile`, with
  `POLARS_MAX_THREADS=1` pinned in `tests/conftest.py`. The reasoning recorded
  there (8m43s / 7.3 GB → 3m38s / 4.35 GB) is sound and, given §4.1, is the
  right trade: process-level parallelism where the work *is* independent,
  serial Polars inside each worker where it would not have helped anyway.
- **Calculator branches** — one `pl.collect_all` over SA/IRB/slotting with CSE
  on the shared upstream (`engine/materialise.py::materialise_branches`), plus
  five more `collect_all` sites in CRM, the aggregator, hierarchy ratings and
  the API formatters.
- **UI jobs** — `ThreadPoolExecutor(max_workers=4)` in `ui/app/progress.py`.

There is no obvious missing `collect_all` in the engine.

### 4.3 P1 — the one parallelism win worth taking: batch scoped runs

Multi-entity reporting ships today, and a group submission plus its solo
entities is **N independent full pipeline runs**. There is no batch driver:
`api/rest.py` takes one `reporting_entity` per request, so N submissions are N
sequential calls the caller must orchestrate.

Because a single run captures only ~1.16× of the machine (§4.1), **N runs in a
process pool scale nearly linearly** — the cores are sitting idle. A 12-entity
group would go from ~12× a run to ~2–3×. The same applies to the CRR-vs-Basel-3.1
comparison page, which needs two independent runs of the same book.

**Proposal:** a batch entry point that takes a list of scopes (and/or
frameworks), fans them out over a `ProcessPoolExecutor`, and returns the run
index entries. `api/run_index.py` already fingerprints and caches runs, so
dedup comes free. Process-, not thread-, level: the serial cost is Python and
plan construction, both GIL-bound. **Effort:** M. **Risk:** low — no engine
change, purely an entry point above `CreditRiskCalc`.

### 4.4 P2 — sheet-level parallelism in reporting, *only if E1 leaves a gap*

Templates and per-class/per-country sheets are pure functions of the results
frame and embarrassingly parallel. But E1 turns each sheet into one large
Polars `select`, which parallelises internally — so most of the headroom
disappears with E1. **Measure after E1; do not build this first.**

---

## 5. Sequenced proposal

| # | Item | Effort | Risk | Why this order |
|---|---|---|---|---|
| **1** | **E1** — batch the cellspec executor into one select per sheet | M | Med | Largest win (7.8× proven), number-neutral, unblocks E2 and settles P2 |
| **2** | **E2** — collect the results frame once at the generator boundary | S | Low | Cheap; after E1 because E1 changes what templates ask for |
| **3** | **E3** — stop re-deriving schemas the edge contracts already declare | S–M | Low | Removes a fixed ~700 ms/run tax; helps the UI and test suite most |
| **4** | **P1** — batch/parallel scoped runs (`ProcessPoolExecutor`) | M | Low | The only parallelism that pays; no engine change |
| **5** | **S1** — hoist `hierarchy`/`classify`/`re_split`/`scope`/`fx` out of `stages/` | M | Low/wide | Mechanical but touches ~100 files; land alone, single-stream |
| **6** | **E4** — measure declared-vs-read column width at each edge | S | None | Measurement only; propose nothing until the number exists |
| **7** | **S2** — finish or formally freeze `StageComponents` | S | Low | Removes a scaffold that reads as architecture |
| — | **P2** — sheet-level reporting parallelism | — | — | Re-measure after E1; likely unnecessary |

Gates for all of them: the project's Tier 2 is mandatory — `tests/oracle/` plus
`tests/acceptance/reporting/`. E1 and E2 change the reporting path, so the
**supervisory validation register and the reporting goldens are the real
gate**, and both must be observed green *without regeneration*. A change that
needs a golden regenerated is a change that moved a number, and E1 must not
move a number.

---

## 6. How to reproduce every number

All scripts used are throwaway harnesses over the cached benchmark datasets
(`tests/benchmarks/data/benchmark_{10k,100k}/`) and
`tests.benchmarks.test_pipeline_benchmark.create_raw_data_bundle`.

- **Per-stage timings** — run the pipeline with the `rwa_calc` logger at INFO
  and read the `stage_timer` exit records (`… completed in N ms`).
- **Edge map** — monkeypatch `engine.pipeline.begin_edge_capture` to pass
  `count_plan_nodes=True`, capture the list returned by `end_edge_capture`.
  (Patch the name in `engine.pipeline`, not `engine.materialise` — the pipeline
  imports it directly.)
- **Reporting profile** — `cProfile` around
  `COREPGenerator().generate_from_lazyframe(results.lazy(), framework="BASEL_3_1")`.
- **`collect_schema` cost** — wrap `pl.LazyFrame.collect_schema` with a timer
  that attributes each call to the first `rwa_calc` frame on the stack.
- **Thread scaling** — set `POLARS_MAX_THREADS` in the environment before
  importing Polars; always run a warm-up iteration first, and include a
  data-parallel control workload in the same process to prove the pool is live.
- **E1 prototype** — `execute_batched` mirrors `cellspec.execute` but builds one
  expression per cell over the unfiltered frame; compared cell-by-cell against
  `execute` over `c07_plans(...)`.

`tests/benchmarks/profile_stages.py` does **not** currently run — it calls CRM
internals (`_build_exposure_lookups`, `_join_collateral_to_lookups`,
`_resolve_pledge_from_joined`) whose signatures have drifted, and dies with a
Polars plan error mid-profile. It should be repaired or deleted; a profiler
that re-implements the pipeline will always drift from it. Timing the real
`run_with_data` and reading the `stage_timer` records is both simpler and
honest.

---

## 7. To file as plan items

None of the above is in `IMPLEMENTATION_PLAN.md` — the plan has **no
performance or parallelism items at all**. When `plan-curator` next runs,
these belong as: E1/E2/E3/E4 and P1 in a new performance grouping (Tier 6
adjacent to the 2026-07-19 reporting-estate review that produced P6.48–P6.53,
which E1 should be sequenced against — E1 touches `cellspec.py`, as does
P6.49's `Constant` verb); S1 and S2 in Tier 6 as structural debt.

Related existing items worth reading first: **P6.49** (kernel-ise shared
template helpers, adds a `Constant` verb to `cellspec.py`) and **P6.51** (split
`corep/c08.py`) both touch the files E1 touches.
