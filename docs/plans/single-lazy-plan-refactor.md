# Single-Lazy-Plan Refactor — SUPERSEDED

**Status: SUPERSEDED** by [Target Architecture Migration](target-architecture-migration.md)
**Phase 1** (eager stage edges). The two-collect target this plan proposed is no longer
pursued: eager materialised stage edges achieve the same depth-bounding goal without
the gating depth-reduction prerequisite. The empirical findings below remain **binding
evidence** — they are why Phase 1 exists and why the do-not-do register forbids
re-attempting a single-plan pipeline on Polars 1.37. Committed to the repo 2026-06-11
(previously held only in agent session memory).

*Update (June 2026): post-Phase-5, `sa/namespace.py` and `irb/namespace.py` no longer exist —
Polars namespaces are extinct and banned (arch_check check 14); SA/IRB logic now lives in
`engine/sa/risk_weights.py` and `engine/irb/transforms.py`. The file/line references below are
historical and preserved as point-in-time evidence.*

## The finding

A fully single-LazyFrame pipeline (zero mid-pipeline collects, one terminal collect)
is **not achievable on Polars 1.37.1** — it hard-SIGSEGVs (exit 139). Empirically
reproduced on the real pipeline at 10k AND 100k rows, CRR AND Basel 3.1.

## Mechanism (verified, not folklore)

The crash is recursive native plan-tree **depth**: the optimizer pass inside
`collect()`, and Rust `Drop` teardown of deeply-nested `LogicalPlan`/expr nodes. It
happens during **plan/schema construction, before any executor runs**, so the
streaming engine (`collect(engine="streaming")` / `sink_parquet`) does not rescue it.

- Measured thresholds ≈ **25,000 nodes** (collect-time) / ~20,000 (teardown) for
  trivial `with_columns` chains; far lower for heavy `when/then`+join expressions.
  The old ">500-node" comments in `materialise.py` / `crm/processor.py` were stale on
  the number but right that the barriers are load-bearing. Thresholds must be
  re-measured per Polars upgrade (Phase 1 plan-node ceiling tests own this).
- **NOT the mechanism:** `collect_schema()` density. It survived to N=200,000;
  reducing the ~15 calls in `sa/namespace.py` + 6 in `irb/namespace.py` only
  *relocates* the crash.

## The three faces of the same root cause (unbounded depth)

1. **SIGSEGV** — plan construction/teardown stack overflow.
2. **9.66 GB OOM on a 150-row fixture** — no-barrier + bigger stack converts the crash
   into a re-execution blow-up.
3. **~100× plan-construction slowdown** — replacing all barriers with lazy `.cache()`
   (dedups execution but does NOT reduce plan depth) gives byte-identical output but
   96–118s vs ~1s baseline on 150 rows (CRR timed out at 150s). On 150 rows execution
   is trivial, so the cost is pure plan construction + optimizer passes. **`.cache()`
   is NOT a barrier substitute.** The barrier's real job is bounding
   plan-construction/optimization *time*, not just avoiding the crash.

The "big calling-thread stack" lever is capped at 252 MB on Windows (CPython rejects
≥256 MB) and only converts hang→OOM; `RUST_MIN_STACK` (rayon workers) is irrelevant —
the cost is on the main thread.

## The one irreducible barrier

`crm_pre_guarantee_unified` (`crm/processor.py`). Removing it *alone* segfaults; every
other barrier removed individually runs byte-identical. Under the migration this
survives as the single documented **intra-stage checkpoint** inside the CRM stage,
protected by a plan-node ceiling contract test rather than a comment.

## Other durable findings

- `pl.collect_all([main, diag…])` does **not** CSE-share the upstream (0 CACHE nodes) —
  defer diagnostics via `pl.concat` UNION (shared CACHE) or aggregate-as-column.
- Dropping `pipeline_pre_branch` while the 3-branch calculator fork remains is a
  measured ~1.6–1.7× regression — relevant to Phase 1 edge placement.
- Caveat: the segfault was confirmed on **native Windows** (fiber/paging-file
  variant); reproduce on Linux CI before trusting platform-independence of the depth
  ceiling.

## Why superseded

The original target was TWO collects (Segment 1: load→…→collateral →
`crm_pre_guarantee` barrier → Segment 2: guarantees→…→aggregator → terminal collect),
gated on a large depth-reduction workstream (cut `collect_schema` calls, flatten
`when/then`→table-joins, batch `with_columns`). The architecture review concluded the
premise was inverted: the engine already materialises the full frame ~5× per run, the
single-plan ideal buys nothing achievable, and the barrier *placement* knowledge is
unenforceable folklore. Phase 1 instead makes materialisation the **uniform rule**
(every stage exit), turning the depth ceiling from an invariant maintained by comments
into one enforced by per-stage plan-node ceiling tests.
