# Pipeline Collect Barriers — Full Analysis

## Current State

The pipeline has `.collect()` calls across several engine files. The hot-path collects (every calculation run) are concentrated in the classifier exit, CRM processing, and the pipeline's split-once + collect_all pattern. All hot-path barriers go through `engine/materialise.py` (`materialise_barrier` / `materialise_branches`); barrier labels (e.g. `crm_pre_guarantee_unified`) are stable grep anchors even when line numbers drift. The pipeline cannot currently run as a single LazyFrame operation due to three categories of blockers.

Line references below were verified against the code as of 2026-06-11 and will drift; prefer the barrier label or function name when locating a site.

---

## Category 1: Polars Plan-Depth Limitations (Hardest to Fix)

These are **platform-level** constraints in Polars itself:

| Location | Label | Barrier | Root Cause |
|---|---|---|---|
| `classifier.py:189` | `classifier_output` | Post-classification materialisation | Both diagnostic emits and the downstream CRM stage reuse the materialised data instead of re-executing the upstream plan (saves ~880 ms / ~14 % of pipeline time at 100K). |
| `crm/processor.py:759` (`_run_ead_pipeline`) | `crm_post_ead_unified` / `crm_post_ead_fanout` | Post-init_ead materialisation | Flattens the provisions → CCF → init_ead plan so downstream lookup collects don't re-execute it, and bounds plan depth. |
| `crm/processor.py:700` | `crm_pre_guarantee_unified` | Pre-guarantee materialisation (unified path) | Collateral adds 3 lookup joins + haircuts + allocation; without this, the guarantee module's 3-path concat re-evaluates the full collateral plan per branch (~4x slowdown at 100K). This is the one barrier whose removal alone reproduces the deep-plan SIGSEGV. |
| `crm/processor.py:704` | `crm_no_guarantee` | Same point, no-guarantee variant | Same plan-depth reset when guarantee inputs are absent. |
| `crm/processor.py:605` | `crm_post_audit_fanout` | Post-audit materialisation (split path only — `get_crm_adjusted_bundle`; the orchestrator uses the unified path) | Prevents the per-approach branch filters from re-evaluating the full CRM plan. |
| `pipeline.py:828` | `pipeline_pre_branch` | Pre-branch materialisation | The guarantee plan (joins + finalize + audit) is deep enough that `collect_all` would re-evaluate it per SA/IRB/Slotting branch. |
| `pipeline.py:871` | `sa_branch` / `irb_branch` / `slotting_branch` | `materialise_branches()` for 3 branches | CPU mode uses `pl.collect_all` with CSE so the shared upstream computes once; streaming CSE is unsupported, so streaming mode sinks branches sequentially instead. |
| `crm/collateral.py:363` | — | 3 collateral lookup collects (`pl.collect_all`) | Each lookup is referenced in multiple downstream joins; without materialisation the `group_by`/`select` re-evaluates at each reference. Small frames — direct `collect_all` is allowed here. |
| `crm/processor.py:958` | — | Guarantee lookup collects (`pl.collect_all`) | Materialises guarantees + counterparty + rating-inheritance lookups to prevent parquet re-scans. Small frames. |

**Why they exist (verified mechanism, not folklore):** the constraint is recursive plan-tree **depth**, not executor capacity. On very deep plans Polars hard-crashes (SIGSEGV) during plan construction, the optimizer pass inside `collect()`, or Rust `Drop` teardown of the nested plan nodes — all **before any executor runs**, so the streaming engine does not avoid it. Measured on Polars 1.37: the crash threshold is ≈25,000 plan nodes for trivial `with_columns` chains, and far lower for heavy `when/then` + join expressions. The barriers also bound plan-construction **time**: without them, plan construction and optimizer passes re-walk the full upstream per consumer (~100x slowdown measured on a 150-row fixture, where execution cost is trivial). The threshold is a property of the installed Polars version and must be re-measured on every Polars upgrade. Full investigation: `docs/plans/single-lazy-plan-refactor.md`.

**What would fix them upstream:** Polars would need:

1. Reliable CSE that handles deep plan trees without re-optimization per branch (`.cache()` dedups execution but does not reduce plan depth — measured as a ~100x construction slowdown, so it is not a barrier substitute)
2. Streaming engine CSE support
3. Iterative (non-recursive) plan construction / optimization / teardown so deep plans neither crash nor cost super-linear construction time

---

## Category 2: Graph Traversal Algorithm (Design Choice)

| Location | Barrier | Root Cause |
|---|---|---|
| `hierarchy.py:338` | Ultimate parent resolution | Collects edge data into an eager frame for iterative graph walk (cycle detection, depth tracking) |
| `hierarchy.py:613` | Facility root lookup | Same pattern — facility hierarchy edges collected for eager traversal |
| `hierarchy.py:686` | Facility ancestor closure | Same edges collected to build the ancestor list for multi-level collateral cascade |

**Why they exist:** The hierarchy resolver needs to walk parent→child chains of arbitrary depth to find ultimate roots (counterparty and facility). This is inherently an iterative/recursive algorithm that Polars expressions can't express natively.

**Data size:** Small (unique org/facility edges — typically <1,000 rows). Performance impact is negligible. A few further small eager passes exist in the same module (short-term rating lookup, duplicate-mapping dedup, truncation warnings) with the same small-data justification.

**Alternatives:**

- **Iterative self-join** — Polars `join` in a Python loop up to `max_depth` times. Stays "lazier" but still requires a fixed iteration count and builds a very wide plan.
- **Accept as-is** — The data is small and early in the pipeline. This is the lowest-impact collect in the entire chain.

---

## Category 3: Validation & Edge Cases (Non-blocking)

| Location | Barrier | Impact |
|---|---|---|
| `contracts/validation.py` (`validate_column_values` ~:544, `_validate_table_columns_batched` ~:977) | Column value validation | Collects invalid rows to build error messages. Not on hot path. |
| `engine/utils.py:119,185` | `has_rows()` checks | `.head(1).collect()` — minimal, checking if optional data exists. |
| `sa/calculator.py:296` (`_warn_equity_in_main_table`) | Equity-in-main-table diagnostic | `.head(1).collect()` to detect equity-class rows for the SA005 info message. |
| `irb/formulas.py:971` | Scalar formula wrapper | 1-row collect for scalar IRB calculations. |

These are all either off the hot path or trivially small.

---

## Architecture Diagram — Where Laziness Breaks

```
LAZY ──────────────────────────────────────────────────────────
  Loader (scan_parquet)
    │
  HierarchyResolver
    │  ├── COLLECT: graph edges (~1K rows) ← Category 2
    │  └── all joins/enrichments stay lazy
    │
  Classifier
    │
EAGER ─── BARRIER #1: classifier_output ──── Category 1 ───────
    │   (classifier.py:189 — diagnostics + CRM reuse materialised data)
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: provisions → CCF → init_ead
    │
EAGER ─── BARRIER #2: crm_post_ead_unified ── Category 1 ──────
    │   (crm/processor.py:759 via _run_ead_pipeline)
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: netting, collateral links, build 3 lookup tables (group_by)
    │
EAGER ─── COLLECT: 3 small collateral lookups ── Category 1 ───
    │   (crm/collateral.py:363 — pl.collect_all)
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: collateral allocation, life insurance
    │
EAGER ─── BARRIER #3: crm_pre_guarantee_unified ───────────────
    │   (crm/processor.py:700; crm_no_guarantee at :704 when
    │    guarantee inputs are absent)
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: guarantees (small lookup collect_all at processor.py:958),
       finalize_ead, audit columns
    │
  Pipeline: _run_calculators()
    │
EAGER ─── BARRIER #4: pipeline_pre_branch ── Category 1 ───────
    │   (pipeline.py:828 — materialise CRM output before split)
    │
LAZY ──────────────────────────────────────────────────────────
  SA calculate_unified() (Basel 3.1 only — SA-equiv RW on all rows)
  Split once by approach
  ├── SA calculator (lazy)
  ├── IRB calculator (lazy)
  └── Slotting calculator (lazy)
    │
EAGER ─── COLLECT: materialise_branches(3 branches) ───────────
    │   (pipeline.py:871 — collect_all with CSE in cpu mode)
    │
  Aggregator (re-lazify for summaries, then final output)
```

---

## Path to Fewer Collects

| Priority | Action | Collects Removed | Difficulty | Dependency |
|---|---|---|---|---|
| 1 | **Wait for Polars CSE / plan-depth improvements** | Up to 5 (classifier + CRM + pipeline) | None (upstream) | Polars roadmap — CSE for deep plans and streaming; non-recursive plan handling |
| 2 | **Flatten CRM plan tree** — restructure provisions/CCF/collateral to produce a shallower plan | Potentially 1-2 | High | Requires significant CRM refactor; risk of correctness regressions |
| 3 | **Move lookup collects into the CRM plan** — if Polars adds `cache()` / explicit CSE hints that also bound construction cost | Up to 5 (lookups) | Low (if available) | Polars `LazyFrame.cache()` dedups execution but today costs ~100x in plan construction — unusable until construction is bounded |
| 4 | **Two-collect architecture** — collapse the 3-branch fork into approach-gated unified calculators, keep only the `crm_pre_guarantee` barrier + one terminal collect | 3 (classifier, post-ead, pre-branch) | High | Gated on plan-depth reduction work; see `docs/plans/single-lazy-plan-refactor.md` |

---

## Out-of-Core Support (Implemented)

All hot-path collects now go through `engine/materialise.py`, which selects strategy based on `config.collect_engine`:

| Engine | `materialise_barrier()` | `materialise_branches()` |
|--------|------------------------|--------------------------|
| `"cpu"` (default) | `.collect().lazy()` (in-memory) | `pl.collect_all()` with CSE |
| `"streaming"` | `sink_parquet` → `scan_parquet` (disk spill) | Sink each branch sequentially → read back |

**Streaming mode** caps peak memory to approximately one column-batch at a time by spilling intermediate results to temp parquet files. This enables the pipeline to process datasets larger than available RAM. It is **opt-in** — the default is in-memory `"cpu"`.

**Config options:**
- `collect_engine: "cpu"` (default) — in-memory collect (`contracts/config.py`, `CalculationConfig.collect_engine`)
- `collect_engine: "streaming"` — disk-spill for out-of-core support on large datasets
- `spill_dir: Path | None` — directory for temp files (default: system temp)

**Fallback:** If `sink_parquet` fails for a particular expression (unsupported in streaming engine), the barrier falls back to in-memory `.collect().lazy()`.

**Cleanup:** Temp files are cleaned up via `cleanup_spill_files()` in `PipelineOrchestrator.run_with_data()`'s `finally` block (`pipeline.py:388`), plus an `atexit` safety net registered in `materialise.py`.

---

## Key Takeaway

**Most hot-path collects exist because of Polars plan-depth limitations** (SIGSEGV / unbounded construction time on deep plans, re-execution of shared upstreams, no streaming CSE). The remaining ones are algorithmic (graph traversal on small data) or off the hot path. The materialization barriers are strategy-aware via `engine/materialise.py`, supporting both in-memory (default) and disk-spill modes. The realistic path forward is:

1. **Short term** (done): Strategy-aware materialization via `materialise_barrier` / `materialise_branches`, with opt-in disk spill for out-of-core processing.
2. **Medium term**: Reduce plan depth (fewer `collect_schema` calls, table-joins over deep `when/then` chains) — the gating prerequisite for removing any barrier; gate on plan-construction wall-clock, not row throughput. See `docs/plans/single-lazy-plan-refactor.md`.
3. **Long term**: A two-collect (or fewer) architecture becomes feasible only when Polars can handle deep plan trees with fan-out without re-execution, super-linear construction cost, or crashes — and the depth ceiling must be re-measured on every Polars upgrade.
