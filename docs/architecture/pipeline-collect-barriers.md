# Stage-Edge Materialisation

## Current State

The pipeline runs on **eager stage edges** (migration Phase 1 —
[Target Architecture & Migration](../plans/target-architecture-migration.md)): every stage's
output plan is collected exactly once at its exit via
`materialise_edge(lf, config, label)` in `src/rwa_calc/engine/materialise.py`, and stages
exchange materialised frames. Laziness is strictly **intra-stage**. Bundle fields remain
`pl.LazyFrame`-typed (a cheap `.lazy()` wrap over the eager frame) until the Phase 3
producer seal flips them to `DataFrame` — so the edge discipline landed with zero bundle or
test churn.

Edge labels (e.g. `crm_exit`) are stable grep anchors; the file references below were
verified against the code as of 2026-06-13 (post the Phase-4 fold: edges fire from the
stage adapter modules under `engine/stages/` or inside producer components — never from
the `engine/pipeline.py` facade) and will drift — prefer the label or function name when
locating a site.

---

## What a Stage Edge Is

A stage edge is the single sanctioned materialisation point at a stage's exit:

```python
exposures = materialise_edge(new_exposures, config, "hierarchy_exit")
```

`materialise_edge` (`engine/materialise.py:161`):

1. collects the incoming plan — in-memory by default (`lf.collect()` then a cheap
   `.lazy()` wrap), or sunk to parquet and scanned back when spill mode is on;
2. records an `EdgeEvent` (`engine/materialise.py:75`) into the run-scoped capture:
   `label`, `rows`, `columns`, `estimated_bytes`, `wall_ms`, `spilled`, and optionally
   `plan_nodes`;
3. returns a lazy handle backed by in-memory data (or a parquet scan in spill mode), so
   the next stage starts from a flat plan.

The calculator branch fork uses the sibling `materialise_branches(branches, config,
labels)` (`engine/materialise.py`), which replaces raw `pl.collect_all()` and records
one `EdgeEvent` per branch; the calc stage invokes it through the sealing wrapper
`materialise_sealed_branches` (`engine/stages/calc.py`).

**Rules** (enforced by `scripts/arch_check.py`):

- Never call `.collect().lazy()` directly — that is `materialise_edge`'s job
  (arch_check check 3).
- Never call `pl.collect_all()` for pipeline branches — use `materialise_branches`.
- Never pass `engine=` to any collect call — execution mode is config-driven
  (arch_check check 4).
- Raw eager collects in `engine/**` outside `materialise.py` are a ratcheted census
  (`engine_eager_collect_sites`, arch_check check 11) — the small-lookup allowlist may
  not grow.

---

## Why Eager Edges (Verified Mechanism, Not Folklore)

The constraint that killed the lazy-first design is recursive plan-tree **depth**, not
executor capacity. On very deep plans Polars hard-crashes (SIGSEGV) during plan
construction, the optimizer pass inside `collect()`, or Rust `Drop` teardown of the nested
plan nodes — all **before any executor runs**, so the streaming engine does not avoid it.
Measured on Polars 1.37: the crash threshold is ≈25,000 plan nodes for trivial
`with_columns` chains, and far lower for heavy `when/then` + join expressions. Unbounded
depth also bounds plan-construction **time**: without materialisation, plan construction
and optimizer passes re-walk the full upstream per consumer (~100x slowdown measured on a
150-row fixture, where execution cost is trivial). `.cache()` dedups execution but does
not reduce plan depth — measured as a ~100x construction slowdown, so it is not a
substitute.

Materialising at every stage exit makes the *inter-stage* failure class unrepresentable:
no stage can hand a deep plan across its boundary. The residual *intra-stage* depth is
bounded by the per-edge plan-node ceiling tests (see below). The node threshold is a
property of the installed Polars version and must be re-measured on every Polars upgrade.
Full investigation: [Single-Lazy-Plan Refactor](../plans/single-lazy-plan-refactor.md)
(superseded by this design; its empirical findings remain binding).

The accepted tradeoff: eager edges forfeit cross-stage predicate/projection pushdown —
which the previous architecture never actually achieved (it segfaulted) — and pin one
frame per edge in memory. A measured-memory gate at 10M rows decides eager vs
parquet-handle edge defaults as a dated recorded decision (migration plan, Phase 1).

---

## Edge Inventory

In registry order (`engine/registry.py`). Every edge fires from a stage adapter module
under `engine/stages/` or from a producer component — the `engine/pipeline.py` facade
fires none itself.

| Label | Location | When it fires | What it bounds |
|---|---|---|---|
| `hierarchy_exit` | `engine/stages/hierarchy/stage.py` (`run`, via `materialise_sealed_edge`) | Every run, after the securitisation lookup is attached | The hierarchy unify/enrich plan (measured ≈1,586 nodes at 10k) crossing to the CCR stage / Classifier |
| `ccr_exit` | `engine/stages/ccr.py` (`run`) | Only when `data.ccr` is present (the stage fn no-ops otherwise) | The `diagonal_relaxed` concat of synthetic SA-CCR exposure rows onto the hierarchy output |
| `classifier_exit` | `engine/stages/classify/classifier.py` (producer-side, in `classify`) | Every run | The classification flag/subtype/approach chain; the diagnostic emits below it read in-memory data, and CRM receives an eager-backed frame |
| `crm_post_ead` | `engine/crm/processor.py` (`_run_ead_pipeline`) | Every run | **First sanctioned intra-stage checkpoint** — the provisions → CCF → init-EAD chain; the collateral step builds several small lookups from this frame, and without the checkpoint each lookup collect re-executes that chain (A/B-measured 35–52% full-pipeline cost; see next section) |
| `crm_pre_guarantee_unified` | `engine/crm/processor.py` (`get_crm_unified_bundle`) | Only when valid guarantee inputs **and** a counterparty lookup are present | **Second sanctioned intra-stage checkpoint** — the collateral plan, before the guarantee module's 3-path concat (see next section) |
| `crm_exit` | `engine/crm/processor.py` (producer-side) | Every run | The full CRM plan (guarantees + `_finalize_ead` + audit columns); the collateral-allocation / CRM-audit projections below it read in-memory data instead of re-executing the guarantee plan |
| `re_split_exit` | `engine/stages/re_split/stage.py` (`run`) | Every run (the splitter itself is a no-op when no rows carry `re_split_mode`) | The RE loan-splitter output before the calculators fork the plan three ways — this edge replaces the old `pipeline_pre_branch` barrier one stage later |
| `sa_branch` / `irb_branch` / `slotting_branch` | `engine/stages/calc.py` via `materialise_sealed_branches` | Every run | The three per-approach calculator chains; cpu mode collects all three in one `pl.collect_all` (CSE computes the shared upstream once), spill mode sinks each branch sequentially |

**Removed at Phase 1:** the `classifier_output`, `crm_post_ead_fanout`,
`crm_no_guarantee`, and `pipeline_pre_branch` barriers. Their plan-flattening work is now
done by the formal stage edges above (a stage input is always eager-backed, so an extra
intra-stage barrier at the same point was redundant). `crm_post_ead` was also removed in
the first Phase 1 landing and then **restored** as a sanctioned checkpoint after a
controlled A/B showed its removal costs 35–52% on every full-pipeline benchmark
(decision log, migration plan §6).

**Removed at Phase 2:** the `crm_post_audit_fanout` edge, deleted together with the
legacy split path `get_crm_adjusted_bundle`/`apply_crm` it served.
`get_crm_unified_bundle` is the CRM stage's only entry point.

---

## The Two Intra-Stage Checkpoints

Exactly two materialisations are sanctioned *inside* a stage — both in the CRM
processor, both empirically justified on Polars 1.37, both pinned by the plan-node
ceiling tests (re-validate per Polars upgrade before attempting removal; Do-not-do
register, migration plan §5):

- **`crm_post_ead`** (`_run_ead_pipeline`): the collateral step that follows builds
  several small lookup frames from the post-EAD frame; without the checkpoint each
  lookup collect re-executes the provisions → CCF → init-EAD chain. Controlled
  single-variable A/B (2026-06-11, quiet machine): removing it costs **35–52%** on the
  full-pipeline benchmarks at 10k and 100k rows (e.g. crr_100k 7.2s → 15.2s).
- **`crm_pre_guarantee_unified`** (`get_crm_unified_bundle`): the guarantee module's
  3-path concat (no-guarantee / single-guarantor / multi-guarantor split) re-evaluates
  the full collateral plan per branch without it (~4x slowdown at 100K scale), and
  removing it **alone** reproduces the deep-plan SIGSEGV — the single-lazy-plan
  investigation's hardest finding. It only fires when guarantee inputs are present and
  valid; on guarantee-free runs the CRM stage runs as one unbroken lazy plan from
  `crm_post_ead` to `crm_exit`.

---

## Spill Mode

One execution semantics, two storage strategies:

| Mode | `materialise_edge` | `materialise_branches` |
|---|---|---|
| In-memory (default) | `.collect()` + cheap `.lazy()` wrap | One `pl.collect_all()` with CSE |
| Spill (`spill_edges=True`) | `sink_parquet` → `scan_parquet` (disk spill) | Sink each branch sequentially → `read_parquet` (peak memory = one branch) |

- **Opt-in:** `spill_edges: bool = False` on `CalculationConfig`
  (`contracts/config.py:983`), for out-of-core processing of datasets larger than RAM.
  Spill caps peak memory at roughly one column batch per edge.
- **`spill_dir: Path | None`** (`contracts/config.py:984`) — directory for temp parquet
  files; `None` uses the system temp directory.
- **No silent fallback:** a sink failure raises `SpillError`
  (`engine/materialise.py:65`). The only reason to enable spill mode is a memory
  ceiling, so silently substituting an in-memory collect would convert an explicit
  operator choice into an OOM at the worst moment. Fix the sink failure or disable
  `spill_edges`. (The previous architecture's silent in-memory fallback is gone.)
- **Deprecated alias:** `collect_engine="streaming"` is the legacy spelling of
  `spill_edges=True` — accepted with a once-per-run `WARNING` for one release
  (`_spill_requested`, `engine/materialise.py:315`; `contracts/config.py:974-979`).
  New code must use `spill_edges`.
- **Cleanup:** spill files are registered in the run-scoped capture and deleted by
  `end_edge_capture` in the `finally` block of the facade's `run_with_data`
  (`engine/pipeline.py`). The old module-global spill registry and `atexit` hook were
  removed — spill-file lifetime is now exactly the run's lifetime.

---

## The Materialisation Map

Every run captures its edge events through a run-scoped lifecycle in
`engine/materialise.py`:

- `begin_edge_capture()` — called at run start (`run_with_data`, `engine/pipeline.py`);
  returns a context-var token. `count_plan_nodes=True` additionally records the
  unoptimised plan-node count of every incoming edge plan (test-only; off by default
  because rendering the plan costs a full plan walk).
- `current_edge_events()` — snapshot hook used by the manifest writer.
- `end_edge_capture(token)` — in the run's `finally` (`run_with_data`): deletes spill
  files and returns the event list.

Two consumers:

1. **INFO log, every run** — the facade logs one summary line on run completion
   (`run_with_data`, `engine/pipeline.py`):

    ```text
    materialisation map: hierarchy_exit=10000r/18MiB/142.7ms; classifier_exit=10000r/24MiB/96.1ms; …
    ```

2. **Run manifest, when the audit cache is enabled** — `manifest.json` carries a
   `materialisation_map` array (`_persist_audit_artifacts`, `engine/pipeline.py`), one
   object per edge event with
   `label` / `rows` / `columns` / `estimated_bytes` / `wall_ms` / `spilled` (and
   `plan_nodes` when captured). Schema and example:
   [Audit cache — `materialisation_map`](../specifications/audit-cache.md#materialisation_map).

---

## Plan-Node Ceilings and Recalibration

`tests/integration/test_stage_edges.py` pins two invariants over the orchestrated
pipeline:

1. **Edge inventory** — a plain run emits exactly the documented edge sequence, in
   pipeline order; a guaranteed run adds `crm_pre_guarantee_unified` between
   `crm_post_ead` and `crm_exit` and nothing else. A missing edge means a stage
   started exchanging lazy plans across its boundary again; an unexpected edge means a
   new materialisation was added without updating this page.
2. **Plan-node ceilings** — the unoptimised plan arriving at each edge stays under a
   pinned per-edge ceiling (`_EDGE_NODE_CEILINGS`), so residual intra-stage depth growth
   is a failing test instead of a Polars SIGSEGV.

The metric is `plan_node_count()` (`engine/materialise.py:148`): non-blank lines of
`lf.explain(optimized=False)` — a *consistent proxy* for native plan-tree size, not an
exact node census.

Measured 2026-06-11 on Polars 1.37 (10k-row fixture, both CRM checkpoints in place):
`hierarchy_exit` 1,586, `classifier_exit` 88, `crm_post_ead` 22,
`crm_pre_guarantee_unified` 1,021, `crm_exit` 1,025 (1,225 with guarantees),
`re_split_exit` 100, branches 28–85. Ceilings are pinned at roughly 2–4x measured; the
SIGSEGV threshold is ≈25,000.

**Recalibration procedure (required on every Polars upgrade):**

1. The version-pin test (`test_pipeline_polars_version_pin_reminder`) fails on a Polars
   minor-version bump — that is the trigger.
2. Run the stage-edge tests with `RWA_PRINT_EDGE_NODES=1` to print the measured per-edge
   node counts.
3. Re-pin `_EDGE_NODE_CEILINGS` at roughly 2x the measured values and update the version
   string in the pin test.
4. Never trust a stale ceiling: the standing warning is the ">500 nodes" comment that
   survived in `materialise.py` for months while the measured threshold was ≈25,000.

---

## Sanctioned Intra-Stage Eager Work

Small eager passes inside stages are allowed where the data is small and the
materialisation is a lookup, not a pipeline plan. They are direct collects (not edges)
and their census is ratcheted by arch_check check 11:

| Location | What | Why |
|---|---|---|
| `engine/stages/hierarchy/graph.py` | Graph-edge collects (ultimate parent / facility root / facility ancestor closure) | Iterative graph walk (cycle detection, depth tracking) that Polars expressions can't express; unique org/facility edges, typically <1,000 rows |
| `engine/stages/hierarchy/ratings.py` | Best internal/external rating lookups (`pl.collect_all`) | Small per-counterparty frames referenced by multiple downstream joins |
| `engine/crm/collateral.py:363` | 3 collateral lookup collects (`pl.collect_all`) | Each lookup feeds multiple downstream joins; without materialisation the `group_by`/`select` re-evaluates at each reference |
| `engine/crm/processor.py:982` | Guarantee + counterparty + rating-inheritance lookups (`pl.collect_all`) | Prevents parquet re-scans; small frames |
| `contracts/validation.py`, `engine/utils.py` (`has_rows`), `sa/calculator.py` (`_warn_equity_in_main_table`), `irb/formulas.py` (scalar wrapper) | Validation / diagnostics / scalar helpers | Off the hot path or `.head(1)`-sized |

---

## History — the Superseded Barrier Architecture

Before Phase 1 the pipeline was nominally "LazyFrame-first" with ~6 ad-hoc hot-path
**collect barriers** (`materialise_barrier` / raw `.collect().lazy()`) placed wherever
deep plans had been observed to crash or slow down: `classifier_output`,
`crm_post_ead_unified`/`crm_post_ead_fanout`, `crm_pre_guarantee_unified` /
`crm_no_guarantee`, and `pipeline_pre_branch`, plus a cpu/streaming dual mode whose spill
path silently fell back to in-memory on sink failure and cleaned up via a module-global
registry with an `atexit` hook.

That design's barrier placement encoded nonlocal invariants no gate could check — removing
one specific barrier alone segfaulted, and only a comment knew it. The single-lazy-plan
investigation ([Single-Lazy-Plan Refactor](../plans/single-lazy-plan-refactor.md),
superseded) proved the full-lazy ideal unreachable on Polars 1.37 and identified
`crm_pre_guarantee` as the irreducible checkpoint. Phase 1 of the
[Target Architecture & Migration plan](../plans/target-architecture-migration.md) replaced
the barriers with the formal stage edges on this page: every stage exit materialises, the
inventory is contract-tested, depth is budgeted per edge, spill is explicit and
fail-loud, and every collect is observable through the materialisation map.
