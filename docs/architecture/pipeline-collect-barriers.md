# Pipeline Collect Barriers — Full Analysis

## Current State

The pipeline has `.collect()` calls across several engine files. The hot-path collects (every calculation run) are concentrated in CRM processing and the pipeline's split-once + collect_all pattern. The pipeline cannot currently run as a single LazyFrame operation due to three categories of blockers.

---

## Category 1: Polars Optimizer Limitations (Hardest to Fix)

These are **platform-level** constraints in Polars itself:

| Location | Barrier | Root Cause |
|---|---|---|
| `pipeline.py:631` | Pre-branch materialisation | CRM output is a deep plan tree. Without collecting, `collect_all` re-optimizes it 3× (once per SA/IRB/Slotting branch). |
| `pipeline.py:665` | `collect_all()` for 3 branches | Must use CPU engine (not streaming) because streaming doesn't support CSE. Without CSE, each branch re-executes the full CRM plan (~9× slower). |
| `crm/processor.py:379` | Post-init_ead materialisation (fan-out path) | Flattens deep plan to prevent re-evaluation when 3 lookup collects reference the upstream. |
| `crm/processor.py:424` | Post-init_ead materialisation (unified path) | Same as above but for Basel 3.1 output floor path (all rows, no approach split). |
| `crm/processor.py:480` | Pre-collateral materialisation (unified path) | Without this, the 3 downstream lookup collects each re-execute provisions → CCF → init_ead (4× total). |
| `crm/processor.py:816-818` | 3 lookup table collects | Each lookup is referenced in 5+ downstream joins. Without materialisation, the `group_by().agg()` expressions re-evaluate at each reference. |

**Why they exist:** Polars' lazy engine lacks robust CSE (Common Subexpression Elimination) for deep plan trees. When the same LazyFrame is referenced by multiple downstream consumers (fan-out pattern), the optimizer either re-executes the shared upstream per consumer or segfaults on very deep plans.

**What would fix them upstream:** Polars would need:

1. Reliable CSE that handles deep plan trees without re-optimization per branch
2. Streaming engine CSE support
3. Optimizer stability with very deep plans (no segfaults)

---

## Category 2: Graph Traversal Algorithm (Design Choice)

| Location | Barrier | Root Cause |
|---|---|---|
| `hierarchy.py:265` | Ultimate parent resolution | Collects edge data into Python dict for iterative graph walk (cycle detection, depth tracking) |
| `hierarchy.py:473` | Facility root lookup | Same pattern — facility hierarchy edges collected for dict traversal |

**Why they exist:** The hierarchy resolver needs to walk parent→child chains of arbitrary depth to find ultimate roots (counterparty and facility). This is inherently an iterative/recursive algorithm that Polars expressions can't express natively.

**Data size:** Small (unique org/facility edges — typically <1,000 rows). Performance impact is negligible.

**Alternatives:**

- **Iterative self-join** — Polars `join` in a Python loop up to `max_depth` times. Stays "lazier" but still requires a fixed iteration count and builds a very wide plan.
- **DuckDB recursive CTE** — `WITH RECURSIVE` can express graph traversal natively. Could scan the edges LazyFrame via DuckDB and return results as a LazyFrame. This is the most natural fit but introduces a DuckDB dependency mid-pipeline.
- **Accept as-is** — The data is small and early in the pipeline. This is the lowest-impact collect in the entire chain.

---

## Category 3: Validation & Edge Cases (Non-blocking)

| Location | Barrier | Impact |
|---|---|---|
| `contracts/validation.py:574,701` | Column value validation | Collects invalid rows to build error messages. Not on hot path. |
| `engine/utils.py` (5 calls) | `has_rows()` checks | `.head(1).collect()` — minimal, checking if optional data exists. |
| `sa/calculator.py:884` | Single-scenario mode | Not vectorized path — only for one-off testing. |
| `irb/formulas.py:560` | Scalar formula wrapper | 1-row collect for scalar IRB calculations. |

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
  Classifier (fully lazy, schema checks only)
    │
  CRM: provisions → CCF → init_ead
    │
EAGER ─── COLLECT #1: post-init_ead flatten ── Category 1 ────
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: build 3 lookup tables (group_by)
    │
EAGER ─── COLLECT #2: 3 small lookups ──── Category 1 ────────
    │
LAZY ──────────────────────────────────────────────────────────
  CRM: collateral allocation, guarantees, finalize_ead
    │   (no final CRM collect — plan tree is shallow post-collateral)
    │
  Pipeline: _run_single_pass()
    │
EAGER ─── COLLECT #3: pre-branch flatten ── Category 1 ───────
    │   (pipeline.py:631 — materialise CRM output before split)
    │
LAZY ──────────────────────────────────────────────────────────
  SA calculate_unified() (Basel 3.1 only — SA-equiv RW on all rows)
  Split once by approach
  ├── SA calculator (lazy)
  ├── IRB calculator (lazy)
  └── Slotting calculator (lazy)
    │
EAGER ─── COLLECT #4: collect_all(3 branches) ─────────────────
    │   (pipeline.py:665 — CPU engine, not streaming)
    │
  Aggregator (re-lazify for summaries, then final output)
```

---

## Path to Fewer Collects

| Priority | Action | Collects Removed | Difficulty | Dependency |
|---|---|---|---|---|
| 1 | **Wait for Polars CSE improvements** | Up to 5 (CRM + pipeline) | None (upstream) | Polars roadmap — CSE for deep plans and streaming |
| 2 | **Replace graph traversal with DuckDB recursive CTE** | 2 (hierarchy) | Medium | Already a project dependency |
| 3 | **Flatten CRM plan tree** — restructure provisions/CCF/collateral to produce a shallower plan | Potentially 1-2 | High | Requires significant CRM refactor; risk of correctness regressions |
| 4 | **Move lookup collects into the CRM plan** — if Polars adds `cache()` / explicit CSE hints | 3 (lookups) | Low (if available) | Polars `LazyFrame.cache()` API (proposed but not yet stable) |
| 5 | **Single-collect architecture** — eliminate pre-branch collect by moving to a single `collect_all` with CSE | 1 (pipeline:622) | Low-Medium | Requires Polars optimizer to handle deep plans without segfault |

---

## Key Takeaway

**Most hot-path collects exist because of Polars optimizer limitations** (deep plan re-execution, no streaming CSE). The remaining 2 are algorithmic (graph traversal on small data). The pipeline architecture is already well-optimized — the `collect().lazy()` pattern at each barrier is the standard workaround. The realistic path forward is:

1. **Short term**: Accept current architecture. The collects are well-placed and well-documented.
2. **Medium term**: Monitor Polars' `LazyFrame.cache()` and CSE roadmap. When available, the 3 lookup collects and the pre-branch collect can likely be replaced.
3. **Long term**: A single `collect_all()` at the output boundary becomes feasible only when Polars can handle deep plan trees with fan-out without re-execution or segfaults.
