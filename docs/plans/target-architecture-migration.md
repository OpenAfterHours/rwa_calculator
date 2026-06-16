# Target Architecture & Migration Plan

**Status:** Active — Phases 0–5 complete (2026-06-16); Phase 6 (`analysis/` layer) next
**Date:** 2026-06-11 (last updated 2026-06-16)
**Provenance:** Multi-agent architecture review (10 subsystem mappers, 6 adversarial
pain-point lenses → 49 evidenced findings, 3 independent greenfield designs scored by a
3-judge panel, 1 migration planner). Judge tally: Design B "regime as data / rulepack"
won all three lenses (auditability, evolution, performance) with 28 grafts absorbed from
the runner-up designs.
**Caveat:** File:line references and counts below were measured at review time
(v0.2.26) and were spot-verified, but they drift — re-verify before acting on any
specific reference.

---

## 1. Purpose

This document is the single source of truth for the architecture migration: what the
review found, what the target architecture is, the phase plan to get there, and the
standing rules (quick wins, do-not-dos, decision log). The two pre-existing
investigation plans are committed alongside and folded in:

- [Engine defensiveness / boundary hardening](engine-defensiveness-boundary-hardening.md)
  → executed in full by **Phase 3**.
- [Single-lazy-plan refactor](single-lazy-plan-refactor.md)
  → **SUPERSEDED** by **Phase 1** (eager edges); its empirical findings remain binding.

`IMPLEMENTATION_PLAN.md` cross-links here; migration work is scheduled per phase, not
as ad-hoc P-codes.

## 2. Review findings (severity-ranked clusters)

### 2.1 The laziness invariant is fiction; the workarounds are load-bearing (sev 5)

"LazyFrame first, collect only at the boundary" is falsified by the engine's own hot
path: ~6 production barrier sites, ~600–700 LOC that exist purely to manage laziness,
~221 `collect_schema()` probes across 53 files substituting for contracts, and a
cpu/streaming dual mode whose spill path had a silent in-memory fallback
(`materialise.py:234-239`). Barrier placement encodes nonlocal invariants no gate can
check — removing `crm_pre_guarantee` alone segfaults, and only a comment knows that.
The single-plan investigation proved the full-lazy ideal is unreachable on Polars 1.37
(SIGSEGV / 9.66 GB OOM on 150 rows / ~100× plan-construction slowdown — see the
superseded plan for the evidence).

### 2.2 No producer-enforced stage contracts (sev 5)

Stage I/O is typed at bundle granularity only; output schemas are applied
consumer-side. Measured: ~1,050 defensive pattern sites (~355 presence guards, ~474
`fill_null`s) — roughly **double** the ~189-guard baseline measured 2026-05-29, i.e.
the debt compounds. Null/absent semantics for the same regulatory column diverge across
consumers in **anti-conservative** directions: `qualifies_as_retail` defaults
True/True/False across three sites (`schemas.py`, `sa/namespace.py`,
`b31_risk_weights.py`); `has_default_definition_info` inverts absent-vs-null behaviour
on the equity 1.5× multiplier. `utils.has_required_columns` swallows all exceptions, so
"firm has no guarantees" and "refactor broke the key column" are indistinguishable — a
green run with a wrong RWA total is representable today.

### 2.3 The regime axis has no seam (sev 5)

CRR-vs-Basel-3.1 variation flows through six unreconciled mechanisms: config factories,
263+ engine `if`-branches, 64 `is_basel_3_1: bool` signatures across 21 files,
constructor regime state in `CRMProcessor`/`HaircutCalculator` (with a documented
two-orchestrator workaround in `comparison.py`), forked override chains, and split
permission maps. Booleans foreclose a third state — and "B31-as-published vs
B31-as-amended" is the predictable post-2027 workload. Duplicate sources of truth
exist: `config.scaling_factor` is set but ignored in favour of
`1.06 if config.is_crr else 1.0` reconstructed at four IRB sites; the Art. 161 LGDs are
declared twice in two formats; `COVERED_BOND_UNRATED_DERIVATION` is an unsuffixed alias
pointing CRR code at a B31 table.

### 2.4 Protocols and namespaces cancel each other (sev 5)

Protocols deliver no swappability (one implementation each; two with zero), while the
Polars namespace registration pattern forced **6 ty rules off project-wide** — so the
static checking the protocols exist for is disabled. Cross-cutting features are shotgun
surgery regardless (securitisation phase 1: 24 files, +47 protocols.py, +28 bundles.py,
+92 pipeline.py); CCR bypassed the protocol architecture entirely, leaving a dead,
signature-drifted protocol that is still contract-tested. `/next-items` hard-excluding
pipeline.py/protocols.py/bundles.py/aggregator.py is the symptom: the "stable"
abstraction layer is the #1 churn choke point.

### 2.5 God modules sit exactly where the churn is (sev 4–5)

`hierarchy.py` (3,749 LOC, ~107 commits) fuses six responsibilities including a leaked
SA risk-weight preview; `classifier.py` (2,412 LOC, ~114 commits) interleaves four
concerns; `schemas.py` (2,520 LOC) holds five unrelated concerns with ~179-file fan-in;
`corep/generator.py` (4,870 LOC, 147 functions) has no per-template seams and its
helper layer drifted semantically from the Pillar 3 copy. The aggregator package
(`aggregator.py` + `_collapse/_floor/_summaries`) proves the right anatomy exists — it
was never applied to the biggest stages. Four incompatible stage idioms coexist.

### 2.6 Test-estate economics are upside down (sev 4–5)

The fixture-generator tree is larger than the engine (≈63.6k LOC, 143 per-P-code
generator scripts, a 3,169-line hand-ordered registry, 358 gitignored parquet files).
Three-and-a-half parallel implementations of the regulatory math exist (engine, ~15k
LOC workbooks oracle, stdlib oracle, hand-copied conftest constants — `0.7619` appears
~246 times). A derived-column rename fans out across ~70–100 files via a 40-kwarg test
god-helper. ~112s of benchmark bodies executed in every default dev loop. Partly an
agent-workflow artifact: per-P-code agents' cheapest move is "create a new file".

### 2.7 Live correctness defects found in passing

1. **FCSM never runs on the production path** — `compute_fcsm_columns` /
   `undo_sa_ead_reduction` are called only in the legacy `get_crm_adjusted_bundle`
   path (`crm/processor.py:571,584`), not in `get_crm_unified_bundle`. A Simple Method
   election silently does nothing in production. *(Fixed in Phase 0.)*
2. **COREP and Pillar 3 disagree about on-balance-sheet** — the copied `_filter_on_bs`
   helpers drifted to clear-all vs return-all on missing columns
   (`corep/generator.py:2435` vs `pillar3/generator.py:1167`). *(Fixed in Phase 0.)*
3. `COVERED_BOND_UNRATED_DERIVATION = ..._B31` unsuffixed alias trap
   (`crr_risk_weights.py:788`). *(Deleted in Phase 5 pack split; flagged now.)*

## 3. Target architecture

### 3.1 Principles

1. **One regime seam.** A `ResolvedRulepack` — resolved once per run from
   `(regime_id, reporting_date)` — is the only carrier of regulatory variation. No
   framework enums, regime booleans, regulatory literals, or commencement-date
   comparisons anywhere in `engine/**` (arch-check enforced, mirroring the existing
   data/engine checks 5–6).
2. **Regimes are data.** A regime is a versioned, content-hashed pack: every entry
   Decimal-valued with a **mandatory article citation**, expressed in a small fixed
   vocabulary (ScalarParam, LookupTable, BandedTable, Schedule, DecisionTable,
   FormulaParams, Feature). `compile` turns packs into Polars expressions once per run —
   the only Decimal→float boundary. Amendments are delta packs; time (effective dates,
   transitionals) is resolved at `resolve()` time, never in engine code.
3. **Eager sealed stage edges.** Stages exchange materialised frames sealed at the
   producer's exit against one ColumnSpec contract per edge (assert + producer-owned
   defaults + strip undeclared scratch + brand). Null/absent semantics are declared
   once per column with a conservative-direction annotation reviewed like a regulatory
   parameter. Laziness is strictly intra-stage. Schema violations **raise**; only
   data-quality issues accumulate.
4. **One stage shape.** `Stage(ctx: PipelineContext, rulepack, run_config) ->
   PipelineContext` over a literal ordered registry; a ~150-LOC pure-fold orchestrator;
   one mandatory stage anatomy (package with thin `stage.py`, focused sub-modules,
   `exit_contract.py` — the aggregator pattern generalised); typed `ArtifactKey[T]`
   side-channels; a single error accumulator preserving codes.
5. **No registered Polars namespaces in first-party code.** Calculator logic is plain
   typed functions composed via `lf.pipe(fn, rulepack)`; the 6 disabled ty rules come
   back on. Protocols only at proven variation points (data-source loading, export).
6. **Analysis above engine.** Comparison (generic two-run over rulepack-identified
   runs), transition (same pack at successive dates), and reconciliation live in
   `analysis/`, not `engine/`.
7. **Declarative reporting down to cell semantics.** One `CellSpec` executor, one
   module per template, one shared kernel; template variant selected from rulepack
   reporting metadata carried on the result bundle.
8. **Test economics rebuilt on the contracts.** Contract-derived builders are the only
   way tests construct stage inputs; scenarios are declarative in-memory files; goldens
   exist in one format with a regeneration-is-clean CI check; the independent oracle's
   parameters are mechanically diffed against the packs.
9. **Auditability is structural.** Every run manifest records the rulepack id +
   content hash and serialises the full resolved parameter set with citations;
   `rulepack diff <a> <b>` materialises the regulatory delta between regimes as a
   reviewable artifact; watchfire validates citations on pack data as well as code.

### 3.2 Package layout (target)

```
rwa_calc/
├── rulebook/                  # THE regime seam
│   ├── model.py               # 7 rule shapes — frozen, Decimal, citation REQUIRED
│   ├── packs/
│   │   ├── common/            # genuinely regime-shared values
│   │   ├── crr/               # one module per topic; symbol set parity-tested vs b31
│   │   ├── b31/               # IDENTICAL symbol set; no cross-pack imports/aliases
│   │   └── amendments/        # delta packs keyed by instrument + commencement date
│   ├── registry.py            # regime ids → pack composition (base + amendments)
│   ├── resolve.py             # (regime_id, date) → frozen content-hashed ResolvedRulepack
│   ├── compile.py             # pack → Polars exprs once per run; ONLY Decimal→float point
│   └── audit.py               # citation index, run manifest, `rulepack diff` CLI
├── contracts/
│   ├── edges.py               # per-edge ColumnSpec + seal(); branded SealedFrame types
│   ├── context.py             # PipelineContext: frame + ArtifactKey[T] map + errors
│   ├── config.py              # RunConfig — ZERO regulatory values
│   ├── errors.py              # CalculationError taxonomy (kept)
│   └── results.py             # result/export DTOs (fixes contracts→api inversion)
├── engine/
│   ├── orchestrator.py        # ~150-LOC pure fold; stage_timer + run_id; no domain logic
│   ├── registry.py            # literal ordered stage list — one screen, no conditionals
│   ├── stages/                # load/ securitisation/ hierarchy/ ccr/ classify/ fx/
│   │   …                      #   crm/ re_split/ calc/{sa,irb,slotting,equity}/ aggregate/
│   └── kernels/               # multi-level allocator written ONCE; normal-stats; audit strings
├── analysis/                  # comparison.py, transition.py, reconciliation/
├── data/                      # inputs/ (schemas by family), domains.py, column_spec.py
├── domain/enums.py
├── reporting/                 # kernel/, cellspec.py, corep/<template>.py, pillar3/<template>.py
├── api/  ui/  observability/  # kept largely as-is
```

### 3.3 What deliberately stays

Error-accumulation taxonomy (narrowed: schema violations raise); Decimal-at-rest
discipline; watchfire `@cites` + citation matrix (extended to pack data, density
ratcheted — may never shrink); `arch_check.py` as the machine gate (rules evolve per
phase); ColumnSpec/`ensure_columns` mechanics repurposed producer-side; the aggregator
decomposition pattern (promoted to mandatory anatomy); the CCR synthetic-exposure-row
strategy; `tests/oracle/` (independent, SHA-pinned, human-reviewed); scenario-ID
traceability; `CreditRiskCalc` library-first layering with the FastAPI+Jinja UI;
observability layer as-is; `.crr()`/`.basel_3_1()` ergonomics as named constructors
over registered regime ids.

### 3.4 Accepted tradeoffs and standing risks

- **Interpreter indirection:** provenance becomes value → pack entry → compile →
  expression. Mitigated by citation-carrying entries, per-row audit columns, and the
  full per-run rulepack snapshot.
- **Eager edges** forfeit cross-stage pushdown (which the current code never achieved —
  it segfaults) and pin one frame per edge; a month-one measured-memory gate at 10M
  rows decides eager vs parquet-handle edges, as a dated recorded decision.
- **Bounded promise:** parameter/table/date/flag changes are pack edits; a genuinely
  novel calculation *shape* still needs one new engine mechanism module. The engine is
  an interpreter over a fixed vocabulary, not a rules engine.
- **Seam erosion is the #1 risk:** when a rule under-fits the vocabulary, the cheap
  move is an engine special case — exactly how today's six mechanisms formed. Defence
  is structural: whole-body regulatory-literal ban + framework-reference ban in
  `engine/**`, and the sanctioned escape hatch is a citation-carrying *pack-owned
  expression builder*, never an engine special case. Every regime-divergent PR must
  show a pack diff.
- **Pack parity ≠ semantic correctness:** a wrong value in both packs passes parity.
  The oracle-vs-pack diff is the only true cross-check; the oracle's independence is
  socially fragile in an agent workflow (see Do-not-do register).

## 4. Migration phases

Strangler migration; every step is a shippable PR on master with the full suite green;
no long-lived rewrite branch; `arch_check.py` is extended at each phase exit so landed
invariants become mechanically enforced. Ordered by risk-reduction per unit effort.

### Phase 0 — Ratchets, baselines, gate hygiene, live-bug fixes *(in progress)*

Goal: stop the debt compounding before moving anything.

- Commit this plan + the two investigation plans to `docs/plans/`; cross-link from
  `IMPLEMENTATION_PLAN.md`.
- `arch_check.py`: `check_ratchet_metrics` against a committed
  `scripts/arch_metrics.json` baseline — engine `fill_null` count, presence-guard
  count, `collect_schema()` count, max engine module LOC, watchfire `@cites` count
  (≥ baseline; the citation matrix may never shrink). Any increase fails; decreases
  rewrite the baseline.
- `arch_check.py`: `check_import_direction` (contracts imports nothing above domain;
  `engine/**` never imports api/ui/reporting; api→reporting one-way), current
  inversions allowlisted; clear the worst by moving `ExportResult` into
  `contracts/results.py`.
- Real `.pre-commit-config.yaml` (arch_check + ruff on src AND tests); fix red master
  CI; align local/CI pytest marker expressions (CI adds jobs, never swaps semantics).
- Register missing markers, `--strict-markers`, exclude benchmark bodies from the
  default loop; dedicated CI benchmark job with stored baselines.
- **FCSM production fix** (recorded regulatory decision: FIX): port
  `compute_fcsm_columns` + `undo_sa_ead_reduction` into `get_crm_unified_bundle`
  behind the Simple Method election; orchestrator-path acceptance test.
- **Reporting kernel dedup**: extract the duplicated corep/pillar3 helpers into
  `reporting/kernel/`; resolve the `_filter_on_bs` drift with one recorded decision.
- Relocate the audit-cache writer (`sink_audit`/`prune_audit_cache`) out of
  `engine/materialise.py` into `observability/` (the sink-locality rule it co-located
  for is a verified phantom — never implemented in arch_check).
- Delete verified-dead code: `tests/bdd/`, `config/fx_rates.py`,
  `utils.is_valid_optional_data`, the `contracts/validation.py` duplicate risk-type
  sets.
- Replace the manually-mirrored watchfire WHITELIST with a generated committed
  snapshot diffed in CI.
- Kick off oracle expansion (`tests/oracle/`) toward the parameters the migration will
  touch. **Hard ordering rule:** no golden-file regeneration in any later phase
  without either oracle confirmation or an explicit, recorded preserve-or-fix
  regulatory decision.
- Fix rotted load-bearing prose: `materialise.py` ">500-node" comment (measured
  ≈25,000); `pipeline-collect-barriers.md` stale refs and false "streaming default".

Validation: full suite green; arch_check green incl. new checks; master CI green;
FCSM acceptance scenario passes through the orchestrator; benchmark job produces
baselines; pre-commit fires.

### Phase 1 — Eager stage edges, plan-node budgets, one execution semantics *(DONE 2026-06-11, except the 1M+/10M measured-memory gate run — tooling shipped as `scripts/profile_memory.py`)*

- `materialise_edge(lf, config, label)` called at **every** stage exit (formalising
  the existing 5 hot-path materialisations). Bundle fields stay `pl.LazyFrame`-typed
  (cheap `.lazy()` wrap) so zero bundle/test churn; the type flip lands with the seal
  in Phase 3.
- Remove redundant intra-stage barriers; keep exactly one documented intra-stage
  checkpoint, `crm_pre_guarantee` (the empirically irreducible one).
- Plan-node ceiling contract tests at 10k rows per stage exit + a canary benchmark on
  the deepest intra-stage plan; recalibration procedure documented per Polars upgrade
  (calibration history: 500 claimed vs ~25,000 measured).
- Collapse cpu/streaming into one semantics: in-memory by default, optional spill;
  **spill failure emits a structured error or halts — never a silent fallback**;
  spill path exercised in CI; deprecate `config.collect_engine` (accept-and-warn one
  release).
- Month-one measured-memory decision gate: peak RSS per stage at 1M (and a manual 10M
  run); eager-vs-parquet-handle edge default at 10M is an explicit dated decision.
- Per-run materialisation map in the run manifest (stage, rows, bytes, wall time,
  spill).
- Eager post-aggregation: aggregator summaries and result-bundle accessors become
  eager; delete the ~12 re-collected lazy summary views; the only remaining lazy
  surface is `scan_parquet` pagination at the UI/results-cache boundary.
- arch_check: collects permitted only inside `materialise_edge` + explicit
  small-lookup allowlist + the `crm_pre_guarantee` checkpoint; every registered stage
  exit goes through `materialise_edge`.

Supersedes the single-lazy-plan refactor; its `crm_pre_guarantee` irreducibility
finding is preserved as the pinned checkpoint + ceiling test.

### Phase 2 — Dead-path deletion and protocol diet *(DONE 2026-06-12)*

- Delete the legacy dual CRM orchestration (`get_crm_adjusted_bundle`/`apply_crm`),
  triple calculator entry points, orphaned result bundles, duplicate error dataclasses,
  dead CRM/IRB twins kept alive only by tests; migrate call sites to the unified path.
- Delete zero-implementation protocols (CCRCalculator, SchemaValidator,
  DataQualityChecker); strip survivors to exactly what the orchestrator invokes;
  conformance asserted on REAL implementations via typed assignment, not stubs.
- Restore production error accumulation on the branch path (SA005/supporting-factor/EL
  warnings currently silently discarded); pin with a unit test per calculator.
- Eliminate empty-LazyFrame sentinels — optional frames are `None`; arch-check rule.
- Single-stream phase (touches the four hard-excluded shared files).

Validation: before/after parity on the 10k stress set — byte-identical RWA (error
lists may grow; asserted explicitly).

**As delivered (2026-06-12, branch `feat/phase2`):** all five bullets landed.
The deletion inventory: `apply_crm`/`get_crm_adjusted_bundle` (+`crm_post_audit_fanout`
edge and legacy-only collateral step), `SACalculator.calculate`/`get_sa_result_bundle`,
`IRBCalculator.calculate`/`get_irb_result_bundle`/`calculate_expected_loss`,
`SlottingCalculator.get_slotting_result_bundle`, `EquityCalculator.calculate`,
`LazyFrameResult`, `SAResultBundle`/`IRBResultBundle`/`SlottingResultBundle`,
`SACalculationError`, the approach-split fields (`sa/irb/slotting_exposures`,
`crm_audit`) on `ClassifiedExposuresBundle`/`CRMAdjustedBundle`, the uncalled
`validate_classified_bundle`/`validate_crm_adjusted_bundle`, and the three
zero-implementation protocols. Error channel: `calculate_branch(…, errors=)` on all
three branch calculators (+ SA `calculate_unified`), merged into the result bundle
with original codes (not `PIPELINE_*`); the misdirected-AIRB CRM006 diagnostic moved
from the dead path into `get_crm_unified_bundle`. Sentinels: `RawDataBundle.
lending_mappings` and `CollateralLinkAllocation.collateral` are `| None`; arch_check
check 13 (+ contracts mirror) bans bare `pl.LazyFrame()` in `engine/**`. Parity gate
shipped as `scripts/phase2_parity.py` (capture/compare). ~40 test files migrated;
conformance rewritten to real-implementation isinstance + typed assignment.

### Phase 3 — Producer-sealed edge contracts and defensive-guard retirement

**Status: DONE (2026-06-12, branch `feat/phase3`, 16 commits).** Every stage
exit loader→aggregator carries a producer seal (the aggregator exit is the
reporting input contract); guard ratchet banked at 549→374 presence /
469→446 fill_null / 191→166 collect_schema (hierarchy.py −413 LOC,
classifier.py −202 LOC); both anti-conservative divergences resolved as
recorded FIX decisions; the silent-skip layer is gone
(has_required_columns/has_rows raise on broken plans, with boundary
leniency owned by the CRM stage); contract-derived builders are the
sanctioned test construction path with a HARD lint (zero direct bundle
construction in tests); Wave-2 flipped 18 of 19 conditional columns to
injection after a verified null-equivalence rework — `guarantor_entity_type`
remains the one conditional sentinel (impossibility argument in §6).
Parity baselines: `../rwa_phase3_parity/post_wave2` is current. Next =
Phase 4 (uniform stage model).

Executes [engine-defensiveness-boundary-hardening](engine-defensiveness-boundary-hardening.md)
in full, upgraded with seal-strips-scratch, branded frames, and conservative-direction
annotations.

- `contracts/edges.py`: per-edge contracts seeded from the existing *_OUTPUT_SCHEMAs;
  `seal(df, EDGE)` asserts + applies producer-owned defaults + strips undeclared
  scratch + brands; bundle `__post_init__` validates the brand. Schema violations
  raise.
- Null/absent semantics declared once per column with conservative-direction
  annotations; regulatory citations on derived columns (e.g. `effectively_secured` ←
  CRR Art. 230) feeding the watchfire matrix.
- Resolve the known anti-conservative divergences (`qualifies_as_retail`,
  `has_default_definition_info`) with recorded preserve-or-fix decisions validated
  against the oracle — **never bulk-regenerated goldens**.
- Strangler order, producer-first: loader (alias translation happens here exactly
  once) → hierarchy → classifier → CRM → calculators → aggregator (whose sealed exit
  becomes the reporting input contract).
- After each edge seals, delete downstream guards per the committed KEEP/REMOVE triage
  (~130 KEEP guards stay; Float/String nulls are NEVER filled to 0.0); ratchet
  enforces monotone decrease.
- Fix the silent-skip layer: `has_required_columns` loses its bare
  `except Exception: return False`.
- Contract-derived test builders (generated from edges.py) become the sanctioned input
  construction path; test-lint introduced as a ratchet (hard ban in Phase 8).

### Phase 4 — Uniform stage model

**Status: DONE (2026-06-13, branch `feat/phase4`, 14 commits).** The pipeline
is a pure fold over the literal stage registry: `contracts/context.py`
(ArtifactKey/PipelineContext), `rwa_calc.rulebook.RulepackV0` (the frozen
`Stage(ctx, rulepack, run_config)` signature), `engine/orchestrator.py`
(fold + per-run components), `engine/registry.py` (nine literal StageSpecs),
stage adapters/packages under `engine/stages/`. God modules split per the
mandatory anatomy (`hierarchy.py` 3,363→7-module package; `classifier.py`
2,227→9-module package; both verbatim, shims retained); FX and RE-split
each have their package (FX registry promotion deferred — recorded);
the SA-RW preview left hierarchy onto the shared guarantor/entity RW
expression (`data/tables/guarantor_rw.py`), which also **closed the
IRB-guarantor PSE/RGLA substitution gap** (recorded FIX, 8 acceptance +
4 unit pins verified RED pre-fix) and the sibling IO/named-MDB/Table-2B
gaps; `engine/kernels/allocation.py` replaced six allocator copies
(FCSM level-blind copy recorded as residue); all four Polars namespaces
retired (ccr→slotting→sa→irb, ~570 call sites) and the **6 disabled ty
rules are back on** (1,366-diagnostic burn-down to zero, typing-only);
the error channel is unified — stage data-quality errors keep their
original codes/severity/context, PIPELINE_* survives only for crashes
(P2.21 closed); arch_check gains checks 14-16 (namespace ban,
registry-is-literal, stage anatomy) with contract mirrors, and CLAUDE.md +
agent charters were updated in the same change. Every commit gated on the
full suite + byte-identical parity vs `../rwa_phase4_parity/before`;
ratchet banked down across the phase (max engine module LOC 3,364→1,499,
target ~600; fill_null 446→431; presence guards 374→372). Next = Phase 5
(rulebook), with CRM constructor-state first.

- `PipelineContext` + `ArtifactKey[T]` + literal `engine/registry.py` + ~150-LOC fold
  orchestrator (no `self._*` scratch). **Define the final signature now**:
  `Stage(ctx, rulepack, run_config)` with a Rulepack-v0 facade over today's
  data/tables + config so Phase 5 swaps the implementation, not the signature.
- Migrate stages one at a time behind a bundle↔context adapter; apply the mandatory
  anatomy in the same PR: split `hierarchy.py` →
  `stages/hierarchy/{graph,ratings,facility_undrawn,unify,enrich}`, `classifier.py` →
  `stages/classify/{attributes,subtypes,permissions,approach,audit}`; FX becomes its
  own stage; RE-split co-located as one `re_split/` package; SA-RW preview leaves
  hierarchy (shared rulepack-compiled guarantor/entity RW expression — also closes the
  IRB-guarantor PSE/RGLA substitution gap, a recorded fix with its own acceptance
  test).
- Extract `engine/kernels/`: the multi-level direct/facility/counterparty allocator
  written once (today five drifting copies).
- Namespaces → plain typed functions, one calculator at a time; when the last
  registration goes, **re-enable the 6 disabled ty rules** and burn down what
  surfaces.
- Unify the error channel (preserve original codes; delete PIPELINE_* rewriting —
  closes P2.21).
- arch_check: ~600-LOC engine module ceiling, stage-anatomy lint, namespace ban,
  registry-is-literal lint. **Update /next-items wave criteria and agent charters in
  the same change.**
- Single-stream phase (shared files); per-stage parity runs gate each conversion.

### Phase 5 — `rulebook/`: regime as versioned, citation-carrying data

**Status: DONE (2026-06-16, branch `feat/phase5`, PR #392).** The rulepack is now the
single value home. `model.py` (10 frozen shapes — the planned 7 plus the three raw-value
primitives `IntParam`/`DateParam`/`CategoryMap` added in S13), `compile.py` (the only
Decimal→float boundary), `registry.py`, and `resolve.py` (→ frozen content-hashed
`ResolvedRulepack`) are landed; every regulatory value lives in
`rulebook/packs/{common,crr,b31}.py` as a cited entry and `data/tables/` **is deleted**
(`data/` now holds only `column_spec.py` + `schemas.py`). Regime variation is read as pack
`Feature`s — `engine/**` reads neither `config.is_crr`/`config.is_basel_3_1` (arch_check
**check 17**) nor `rwa_calc.data.tables` (arch_check **check 12**, now a zero-tolerance hard
ban), and a new `check_no_numeric_tables_in_engine` guards against module-level float-rate
tables re-entering the engine. `contracts/config.py` is `RunConfig` — firm inputs +
elections + a `regime_id` (str), **zero** regulatory values (the `PDFloors`/`LGDFloors`/
`SupportingFactors`/`RegulatoryThresholds` dataclasses and their fields deleted) — with
`.crr()`/`.basel_3_1()` kept as named constructors. `rulebook/audit.py` ships the run-manifest
rulepack snapshot (id + content hash + full resolved parameter set with citations) and the
`rulepack diff` CLI; watchfire `@cites` now covers pack data. Delivered as ~120 byte-identical
slices (S1–S13), each gated on per-slice byte-identical parity vs `../rwa_phase5_parity/before`
across all four configs (crr_sa/crr_irb/b31_sa/b31_irb); suite 7506 passed / 2 skipped at close.
The slice-group narrative and every recorded preserve-or-fix decision are in the §6 decision
log (S1–S13). Deliberately deferred (recorded, **not** residue): the `ccr/sft_fccm.py`
regime-insensitive SFT haircut (number-changing — needs a B31 SFT fixture + PS1/26
determination + oracle) and the regime-invariant formula-embedded constants kept inline per
the S5d precedent. Next = Phase 6 (`analysis/` layer).

- Land `model.py` (7 shapes) + `compile.py` + `registry.py`; pack-owned expression
  builders as the sanctioned under-fit escape hatch.
- Strangler-move `data/tables/` into `packs/{common,crr,b31}` behind shim getters
  (identical symbol sets, parity-tested; no cross-pack imports; delete the
  `COVERED_BOND_UNRATED_DERIVATION` alias trap).
- Single-source the duplicated values (1.06 scaling factor ×4 sites; Art. 161 LGDs ×2
  formats; EUR/GBP 0.8732 ×~12 sites) with oracle-vs-pack diff coverage.
- `resolve(regime_id, reporting_date)` → frozen content-hashed ResolvedRulepack;
  migrate the three temporal patterns into Schedule entries; engine never compares
  reporting_date to a regulatory date again.
- Thread the real rulepack package-by-package (CRM constructor-state first → calc →
  classify → reporting metadata), deleting all six regime mechanisms; per-package
  parity gates; the oracle as referee across the 169 CRR + 212 B31 acceptance
  scenarios.
- Split `contracts/config.py`: RunConfig with zero regulatory values; keep
  `.crr()`/`.basel_3_1()` as named constructors.
- Run manifest: rulepack id + hash + **full serialised resolved parameter set with
  citations**; ship `rulepack diff`; amendment delta-pack composition machinery with
  deterministic ordering rules and dedicated tests **before** the first real amendment.
- arch_check: regime-containment ban + whole-body regulatory-literal ban in
  `engine/**`; every regime-divergent PR shows a pack diff.

#### Phase 5 execution slices *(derived from the 2026-06-13 regime-seam recon on `feat/phase5`; parity anchor `../rwa_phase5_parity/before`)*

Starting state established by recon: `rulepack` (RulepackV0) is threaded to every
stage but **ignored** (`# noqa: ARG001` on ~13 adapters) — all regime reads go
through `config`. `CalculationConfig` is the de-facto rulepack (8 regulatory
sub-config dataclasses + `scaling_factor`/`eur_gbp_rate`/`irb_permissions`, forked
by `.crr()`/`.basel_3_1()`). `data/tables/` is ~80% regime-as-data already
(CRR+B31 constants side by side, selected by `is_basel_3_1`). ~62 `config.is_*`
branch reads across 21 files; ~80 bare `is_basel_3_1: bool` own-params; 2
constructor-regime-state classes (`CRMProcessor`, `HaircutCalculator`); 3
transitional schedules; 4 inline `1.06 if is_crr else 1.0`.

Standing invariants for every slice: resolve the pack **after** the EUR/GBP
FX-sync (`pipeline.py` hoist → `orchestrator` build); the StageFn signature
`Stage(ctx, rulepack, run_config)` never changes (Phase 5 swaps what `rulepack`
carries, not the signature); per-slice byte-identical parity vs the anchor
(group-by sum frames at rtol 1e-9 per the Phase 2 decision); the oracle is the
referee for any number that moves; **no silent golden regeneration**.

- **S1 — rulebook foundation (additive, zero engine wiring).** `model.py` (7
  frozen shapes: ScalarParam, LookupTable, BandedTable, Schedule, DecisionTable,
  FormulaParams, Feature — Decimal-valued, citation REQUIRED), `compile.py`
  (pack→Polars-expr, the only Decimal→float boundary), `registry.py` (regime ids
  → pack composition, literal), `resolve.py` (`resolve(regime_id, reporting_date)`
  → frozen content-hashed `ResolvedRulepack`); a small proof pack exercising every
  shape; unit tests (construction, citation-required, compile correctness, schedule
  date resolution, content-hash determinism+sensitivity). Parity trivial.
- **S2 — pack-build seam + regime accessors (single-stream).** Orchestrator builds
  the pack via `resolve(...)` (feeding/replacing `RulepackV0.from_config`);
  `ResolvedRulepack` keeps the back-compat surface (`is_crr`/`is_basel_3_1`/
  `scaling_factor`/`regime`/`config`) and grows pack accessors. Flip the 4 inline
  `1.06 if is_crr else 1.0` → `rulepack.scaling_factor` and the orchestrator regime
  read. Stage adapters start consuming `rulepack` (drop `noqa` where flipped).
- **S3 — CRM constructor-state elimination (single-stream; the plan's "CRM first").**
  Drop `is_basel_3_1` from `CRMProcessor`/`HaircutCalculator.__init__`; thread
  `rulepack` at the call boundary; repoint `collateral.py`'s supplier (it already
  takes the bool); delete the `orchestrator.py:305` injection; unify the
  `haircuts.py:128` dual-source; correct the `comparison.py` two-orchestrator
  docstring. **Verify (recorded decision, not silent fix)** the `sft_fccm.py:289`
  and `risk_weights.py:1284` hardcoded `is_basel_3_1=False`.
- **S4 — CRM/CCF/haircut tables → packs.** Resolve supervisory LGD (ONE canonical
  entry feeding both the FIRB-shape and the CRM-shape — collapse the
  `firb_lgd`/`crm_supervisory` duplication), haircut tables (regime-band-keyed),
  overcollateralisation (Feature + LookupTable), SA-CCF, FCSM RW dicts,
  min-collateralisation thresholds.
- **S5 — IRB calc → pack.** Thread `rulepack` into `irb/formulas+transforms+
  guarantee`; resolve PD/LGD floors (Feature `airb_lgd_floor` + banded floors),
  FIRB supervisory LGD, maturity Features (`firb_sft_supervisory_maturity`,
  one-day floor, revolving-termination), `double_default` Feature.
- **S6 — SA calc → pack.** SA CQS RW tables (LookupTable), the two override ladders
  (pack-owned expr builders / DecisionTables), defaulted-RW basis Feature,
  due-diligence Feature, supporting factors, IG assessment. **Move the
  `rw_adjustments.py:299` Art.123B date comparison** to a resolved Schedule/flag.
- **S7 — Slotting + Equity → pack.** Slotting RW/EL (BandedTable/DecisionTable),
  equity RW LookupTable pairs, equity PD/LGD bundle (CRR-only FormulaParams),
  equity transitional Schedule, equity-IRB-removed Feature.
- **S8 — Classify → pack.** Permission map (regime DecisionTable), B31 approach
  restrictions (pack-owned expr + threshold entries), class-remap Features
  (high-risk, income-reroute, corporate-subclass, retail-granularity), entity-type
  sets; split `psm_lgd_source` out of the permission map.
- **S9 — CCR + temporal schedules → pack.** SA-CCR factors (common); the
  transitional add-on resolved at `reporting_date` (moved out of engine); all 3
  schedules through the single Schedule primitive — engine never compares
  `reporting_date` to a regulatory date again.
- **S10 — strangler-move `data/tables/` → `packs/{common,crr,b31}`** behind shim
  getters; **delete the `COVERED_BOND_UNRATED_DERIVATION` alias trap**;
  single-source the dup values (1.06 ×4, Art.161 LGDs ×2, 0.8732 ×~12, 0.7619); no
  cross-pack imports; symbol-set parity + oracle-vs-pack diff tests. (Table
  *content* moves with each consumer in S4–S9; S10 is the cleanup/parity capstone.)
- **S11 — `contracts/config.py` split → RunConfig (single-stream).** RunConfig with
  ZERO regulatory values; keep `.crr()`/`.basel_3_1()` as named constructors
  building `(RunConfig, regime_id)`; route the elections (`permission_mode`,
  `use_investment_grade_assessment`, `equity_pd_lgd`, `enable_double_default`,
  `enforce_retail_granularity`, `crm_collateral_method`, `airb_collateral_method`,
  `psm_lgd_source`, output-floor OF-ADJ inputs) to RunConfig, resolved against the
  pack; delete the six regime mechanisms' last remnants.
- **S12 — manifest + `rulepack diff` + arch_check.** `rulebook/audit.py`
  (id+hash+resolved-params-with-citations serializer, `rulepack diff` CLI); manifest
  records the rulepack snapshot (pass `rulepack` into `_persist_audit_artifacts`);
  watchfire extended to pack-data citations; new arch_check **regime-containment**
  check + whole-body regulatory-literal ban; shrink the allowlists; **update
  /next-items wave criteria + agent charters in the same change** (do-not-do
  register requirement).

Flagged number-changing items (each gets a recorded preserve-or-fix decision in
§6 when its slice lands, validated against the oracle — never bulk-regenerated):
`sft_fccm.py:289` regime-insensitive haircut (S3), `risk_weights.py:1284`
institution-guarantor pin (S3), `firb_lgd`↔`crm_supervisory` dual-shape collapse
(S4), `COVERED_BOND_UNRATED_DERIVATION` alias (S10).

### Phase 6 — `analysis/` layer

- Move comparison + reconciliation out of `engine/` (and the reconciliation registry
  out of `data/schemas.py`); comparison generalises to labelled two-run over
  rulepack-identified runs (unlocks B31-vs-B31-amended, election-vs-election); the
  CRR→B31 waterfall becomes one registered delta-attributor pairing; transition = same
  pack resolved at successive dates + floor-tail partial re-run.

### Phase 7 — Declarative reporting

- `reporting/cellspec.py` + one executor; strangler by template family with
  byte-identical golden gates; reporting input = the sealed aggregator exit (deletes
  the ~160 `_pick` fallback ladders); template variant from rulepack metadata (deletes
  ~40 framework string-tests and ref-set sniffing); split the 9,428-LOC
  `test_corep.py` xdist straggler alongside.

### Phase 8 — Test-economics completion

- Builder lint flips ratchet → hard ban; acceptance scenarios become declarative
  in-memory files cohort-by-cohort (dissolving `generate_all.py` and the parquet
  round-trip); one-format goldens (JSON) with a CI regeneration-is-clean check;
  workbooks golden-generators retired per-group as oracle coverage reaches them;
  test tree mirrors src/ 1:1 with a ~500-LOC size lint; **agent workflow charters
  (fixture-builder, test-writer, /next-items reviewer criteria) updated in the same
  change** — this is the explicitly-flagged regression vector.

## 5. Do-not-do register

- **Do not** attempt the single-lazy-plan/two-collect refactor — verified dead end on
  Polars 1.37; eager edges supersede it. Keep `crm_pre_guarantee` until ceiling tests
  prove it removable on a future Polars.
- **Do not** bulk-delete defensive guards — ~130 of the audited 189 are KEEP;
  Float/String nulls are NEVER filled to 0.0 (anti-conservative for EAD/provisions).
- **Do not** delete `engine/ccr/ccp.py`, `failed_trades.py`, or `wwr_lgd_override` as
  dead code — they are open planned wirings (P8.39/P8.53/P5.17).
- **Do not** regenerate goldens silently when semantics fixes change results — every
  diff gets a recorded preserve-or-fix decision validated against the oracle. Bulk
  regeneration is how a wrong number becomes a pinned number.
- **Do not** let any agent edit `tests/oracle/` to match engine output — oracle
  changes are human-reviewed and SHA-pinned only.
- **Do not** start a long-lived rewrite branch or a parallel "v2" package.
- **Do not** change the StageFn signature twice — define it in Phase 4 with the
  Rulepack-v0 facade.
- **Do not** share values between packs via imports/inheritance/aliases — explicit
  duplication guarded by parity + oracle-diff tests.
- **Do not** author speculative amendment packs ahead of a real PRA instrument.
- **Do not** convert all four calculator namespaces in one PR; do not re-enable the ty
  rules before the last namespace registration is gone.
- **Do not** migrate the per-P-code fixture directories before the builders and seal
  exist.
- **Do not** update the architecture without updating the agent orchestration in the
  same change.

## 6. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-11 | Target architecture = Design B (rulepack) + 28 grafts; phases 0–8 as above | Judge panel 3/3 lenses; see provenance header |
| 2026-06-11 | FCSM divergence: **FIX** (port to unified path), not preserve | Simple Method election must have effect in production; CRR Art. 222 |
| 2026-06-11 | `_filter_on_bs` missing-column drift: unify on **return empty** | A missing balance-sheet indicator must not silently pass all rows (double-counts across on/off-BS cells); detectable failure preferred; absence becomes a contract violation in Phase 3 |
| 2026-06-11 | Phase 1 **deviation**: CRM keeps **two** intra-stage checkpoints, not one — `crm_post_ead` restored alongside `crm_pre_guarantee_unified` | Controlled single-variable A/B (quiet machine, Polars 1.37): removing `crm_post_ead` costs **35–52%** on every full-pipeline benchmark at 10k and 100k rows — the collateral step's lookup collects re-execute the provisions→CCF→EAD chain without it. Re-validate per Polars upgrade via the plan-node ceiling tests |
| 2026-06-11 | Plan-node ceilings pinned (Polars 1.37): hierarchy_exit 3200, classifier_exit 400, crm_post_ead 2400, crm_pre_guarantee 4000, crm_exit 4000, re_split_exit 500, branches 300–500 | Measured: hierarchy 1,586; crm_pre_guarantee 1,021; crm_exit 1,025–1,225; rest ≤100. SIGSEGV threshold ~25,000. Recalibrate via `RWA_PRINT_EDGE_NODES=1` on every Polars upgrade (test pins the Polars minor version) |
| 2026-06-11 | Spill-edge default at scale: **OPEN** — decision deferred to a 1M+ profile run | First measurement (5k rows, `scripts/profile_memory.py`): spill mode is strictly worse at small scale (+146% peak RSS, 20× wall, dominated by the pre-guarantee sink). Run the gate at 1M+ before choosing the 10M default; do not enable `spill_edges` below the measured crossover |
| 2026-06-12 | Phase 2: misdirected-AIRB diagnostic (CRM006) **migrated** into `get_crm_unified_bundle`, not deleted with the legacy path | The diagnostic only ever fired on the dead `get_crm_adjusted_bundle` path — production never emitted it. The finder early-returns unless collateral carries `is_airb_model_collateral`, so the production cost is zero for typical data; deleting it would have silently lost a CRR Art. 181 / B3.1 Art. 169A data-quality signal |
| 2026-06-12 | Phase 2: `IRBCalculator.calculate_expected_loss` deleted **with** its P1.88/P1.144 tests | The method was a bundle-based twin never invoked by the orchestrator; production EL flows through the `lf.irb` namespace whose `ead_final` basis and formula are pinned by `test_irb_namespace.py::TestCalculateExpectedLoss`. The IRB004/IRB005 missing-PD/LGD warnings existed only on the dead twin (production `prepare_columns` supplies the columns before EL) |
| 2026-06-12 | Phase 2 parity gate: per-row frames compared **byte-exact**; group-by sum aggregates compared to float-reassociation tolerance (rtol 1e-9) | Verified on identical code: Polars' multi-threaded group-by Float64 summation is NOT deterministic across processes — two fresh runs differ in the last 1–2 ulps of 41k-row sums (`pre_crm_summary`, `summary_by_class/approach`). A byte-exact gate on those frames would flake; the per-exposure frames are the real invariant and stayed byte-identical |
| 2026-06-12 | Phase 2 parity result: per-exposure RWA byte-identical across all four configs; error growth = exactly **one SA004 per B31 run** | The restored branch error channel surfaces the Art. 110A due-diligence warning the production path was silently discarding (the stress portfolio's unified frame carries no `due_diligence_performed` column). Asserted explicitly via `scripts/phase2_parity.py compare` |
| 2026-06-12 | Ratchet baseline re-banked: presence guards 552→549, collect_schema 192→191, `max_engine_module_loc` 3750→**3760** | The +10 LOC is `hierarchy.py`'s None-handling for the now-optional `lending_mappings` — a deliberate contract improvement (sentinel elimination), reviewed here rather than squeezed out; hierarchy.py splits in Phase 4 regardless |
| 2026-06-12 | Phase 3: the brand is a plain instance attribute on the LazyFrame, lost on any transformation; bundle `__post_init__` validates via a growing `SEALED_FRAME_FIELDS` registry | Verified on Polars 1.37: attribute survives nothing — exactly the wanted semantics (a derived frame has not been through the seal). A wrapper type would have churned every consumer signature; an id()-keyed registry risks reuse-after-GC. The registry gives the strangler a per-edge enforcement ramp |
| 2026-06-12 | Phase 3: loader edge is **lenient** (missing required columns → DQ001 + typed-null injection); inter-stage edges are strict (violations raise) | Input validation is non-blocking by project rule — external data quality must never raise; a producing *stage* violating its own output contract is a programming error. DQ001 finally implements the `ColumnSpec.required` contract that was documentary only |
| 2026-06-12 | Phase 3: five smuggled loan columns declared as contract (`ltv`, `property_type`, `has_income_cover`, `ava_amount`, `other_own_funds_reductions`); `COLLATERAL_SCHEMA.is_main_index` default **removed** | The loader strip surfaced columns the engine reads but the schemas never declared (P1.181 CRE split, P1.127 Pool B). `is_main_index`: a load-time False fill silently re-rated unreported equity to the higher other-listed haircut, contradicting the engine's pinned null→main-index resolution (CRR Art. 224 Table 4). Direction (unknown→preferential) flagged for the Phase 3 recorded-decisions batch alongside `qualifies_as_retail` |
| 2026-06-12 | Phase 3: parity re-baselined after the loader seal (`../rwa_phase3_parity/post_loader_seal`); the gate itself stays fully strict (no column exclusions) | The stress fixtures bypassed the loader, so the pre-phase baseline preserved nulls production parquet loading has always Boolean-filled. Sealing unified the paths: `has_sufficient_collateral_data` null→False moved 9,151 AIRB rows from modelled unsecured LGD to the CRR Art. 169A/169B supervisory fallback (`lgd_unsecured`/`lgd_post_crm` only; `rwa_final` byte-identical — floors/post-CRM already bound; all other columns byte-identical, verified per-column across all four configs). Pre-phase snapshot retained at `.../before` |

| 2026-06-12 | Phase 3 classifier seal: model-permission audit columns (`model_*_permitted`, `ppu_reason`) declared OPTIONAL-null — present on every run; parity re-baselined (`post_classifier_seal`) | Zero value drift, zero removals across all four configs — SA runs gain the three columns as typed nulls (uniform downstream shape; IRB runs already carried them). Securitisation lookup columns likewise optional at this edge so resolver-direct classifier invocation stays constructible |
| 2026-06-12 | Phase 3 findings (recorded, not yet fixed): (a) post-seal, `_merge_netting_collateral` always replaces a None/invalid collateral table — `collateral_allocation` is a zero-value frame, never None, contradicting its docstring; (b) `original_currency` present-but-null silently disables Art. 224/233 FX haircuts (anti-conservative, pre-dates the seal — a loans file with no currency column gets full un-haircut collateral recognition with no warning); (c) `has_required_columns` bare-except converts dtype-mismatch plan failures into misleading CRM001 "missing columns" | (a) reconcile docstring-vs-behaviour with the CRM edge work (task: CRM exit seal); (b) DQ-guard candidate for the recorded-decisions batch alongside `qualifies_as_retail`; (c) is the task-17 silent-skip fix, now with a concrete reproduction |

| 2026-06-12 | Phase 3 CRM seal: path-dependent columns are **CONDITIONAL** (`EdgeColumn(inject=False)` — validated and never stripped when present, never injected when absent), NOT optional-with-injection | The parity gate caught the alternative: blanket null-injection of the 17 guarantee/provision columns made the SA/IRB substitution machinery's presence-gated branches execute on null data and **moved b31_irb risk weights**. Conditional mode restores byte-identical parity; each column group flips to inject=True alongside its consumer's guard deletion, with null-path equivalence verified per consumer |
| 2026-06-12 | Phase 3 CRM seal: the CRM001 unusable-collateral skip path now runs the collateral step with an empty schema-valid table | Every path through a stage must emit the stage's output contract. The skip path previously omitted the 14 collateral-derived columns, so the producer violated its own seal; running on an empty table emits the identical neutral values as the genuine no-collateral path with no duplicated column inventory to drift. FCSM's two SIMPLE-election columns declared conditional (the SA consumer fill_null(0.0)s them) |

| 2026-06-12 | `qualifies_as_retail` unknown: **FIX** — default False at Sites 1-3 (CLASSIFIER_OUTPUT_SCHEMA default, both SA retail-branch fills); `b31_risk_weights` coalesce-False unchanged | CRR Art. 123 / PS1/26 Art. 123A / CRE20.65-67: the 75% weight is preferential and requires demonstrated qualification — unknown must take 100%. The classifier always recomputes non-null in-pipeline, so goldens are untouched; the True/True/False incoherence (same null row preferential in one branch, denied in another) is resolved. 7 direct-invocation tests now affirmatively qualify; the null-pin test flips to 100% |
| 2026-06-12 | `has_default_definition_info` unknown: **FIX** — default False + fill_null(False) (schema + equity calculator) | CRR Art. 155(3) final subpara: the 1.5x PD/LGD scaling applies unless the institution affirmatively holds Art. 178 default-definition data; null/absent previously SKIPPED the scaling, contradicting the contract comment on EQUITY_EXPOSURE_SCHEMA itself. Path is CRR-only, config-gated (equity_pd_lgd), sunsets end-2026; zero goldens (acceptance fixture sets the flag explicitly). New pins: null and absent both -> 1.5x |
| 2026-06-12 | `is_main_index` unknown: **PRESERVE** engine null→main-index resolution (Art. 224 Table 4) | Recorded with the loader-seal slice (default removed from COLLATERAL_SCHEMA): the committed acceptance scenarios (CRR/B31 D3) and the unit pin define null→main-index as intended behaviour. Direction (unknown→lower haircut) noted as generous; revisiting requires an oracle scenario and Risk sign-off, not a code-side flip |
| 2026-06-12 | Oracle expansion for the two FIX decisions deferred to the human-reviewed oracle workstream | tests/oracle/ is deliberately not agent-written (hash-locked derivations). No golden regeneration occurred, so the Phase 0 ordering rule is not engaged; README roadmap items 2 (SA retail unrated, Art. 123) and 8 (equity Art. 155) are the designated slots |

| 2026-06-12 | Wave-2: 18 of the 19 CRM conditional columns flipped to injection after null-equivalence rework; `guarantor_entity_type` stays the ONE conditional sentinel | Two-step protocol: rework verified byte-identical with columns still absent, then the flip verified as exactly-18 all-null additions with zero drift in any shared column across all four configs × 13 frames. The sentinel is structurally necessary: both substitution machineries gate on it, and lazy column addition is row-independent — once the gate passes, ~17 derived audit columns and a `pre_crm_summary` aggregate appear regardless of values, so an all-null run can match the absent branch's values but never its shape (the recorded 2026-06-12 failure mode). A value-level gate would need a mid-pipeline collect. `_inst_guarantor_short_term` scratch leak removed from the branch/aggregator contracts (dropped at source). Parity re-baselined at `post_wave2` |

| 2026-06-12 | Phase 4 slice 1: fold skeleton landed — `contracts/context.py` (ArtifactKey/PipelineContext), `rulebook.RulepackV0`, `engine/orchestrator.py` (pure fold + per-run `build_components`), literal `engine/registry.py` (9 StageSpecs), `engine/stages/*` adapters; run lifecycle (run_id, edge capture, FX sync, error merge, audit persist) stays on the `pipeline.py` facade for now | The facade keeps `PipelineProtocol` conformance, the `begin_edge_capture` monkeypatch seam (test_stage_edges) and the run-level logger pins at `rwa_calc.engine.pipeline` — ~90 test files at zero churn; stage_timer records move to `rwa_calc.engine.orchestrator` (one CCR test re-pointed). Lifecycle migrates into the orchestrator when the facade dissolves, not before. Parity byte-identical on all four configs |
| 2026-06-12 | Phase 4 slice 1: components are built **per run** from the effective config; the orchestrator caches nothing across runs | Deliberate behaviour change (improvement) over the pre-fold lazy-init cache: `CRMProcessor(is_basel_3_1=…)` constructor state made a reused orchestrator framework-stale (the documented comparison.py two-orchestrator workaround). Construction cost is negligible (the haircut table is a small eager frame). The workaround in comparison.py is now redundant but harmless — removed when CRM constructor-state dies (Phase 5) |
| 2026-06-12 | Phase 4 slice 1: adapter-era context grain is **whole bundles** (RAW_DATA, RESOLVED_HIERARCHY, CLASSIFIED, CRM_ADJUSTED, …), not per-frame keys; the four error channels keep their exact pre-fold merge order, incl. the calc/aggregator-failure double-conversion quirk | Bundle `__post_init__` brand validation keeps firing free at every stage boundary, and zero behaviour change is provable by the parity gate. Per-frame keys land slice-by-slice as stages convert to the uniform anatomy; the error channels collapse in the dedicated slice (P2.21) where the observable code changes are reviewed once, deliberately |

| 2026-06-12 | Phase 4 slice 4: FX conversion gets its own package (`stages/fx/` — FXConverter + `convert_resolved_frames`, resolver delegates at the identical unify→FX→enrich seam); **registry-stage promotion deferred** with this recorded decision. RE-split co-located as `stages/re_split/` (splitter + the classifier's flagging brain + stage adapter; shims left behind) | The FX seam is intra-hierarchy and load-bearing (LTV / property coverage / lending-group totals / classifier GBP thresholds all assume reporting-currency amounts); promoting FX to a registered stage requires two new intermediate edge contracts (pre-FX hierarchy state) whose parity verification belongs to a dedicated slice, not mid-move. The plan's other FX requirement — the mid-run `config.with_fx_rate` mutation moving out of the fold — landed in slice 1 (facade hoists eur_gbp sync before components/rulepack are built) |
| 2026-06-12 | Phase 4 findings (recorded, NOT fixed — number-changing): (a) `sa/namespace.py apply_currency_mismatch_multiplier` (Art. 123B / PS1/26) tests borrower income currency against the post-FX `currency` column (= base currency on every converted row), not `denomination_currency_expr`/`original_currency` — a USD loan to a USD-income borrower is flagged mismatched after conversion to GBP; (b) FX-haircut null polarity disagrees across paths: `ccr/sft_fccm.py` applies H_fx when either currency is null (conservative) while `crm/haircuts.py`/`crm/guarantees.py` skip it (anti-conservative, the Phase 3 recorded `original_currency`-null finding) | Both change B3.1/CRM numbers; per the do-not-do register they need fixture verification + oracle coverage + a recorded preserve-or-fix decision each, not a silent flip during a move slice. (a) is P1.135-class — verify with a fixture before the namespace-retirement slice moves that code; (b) unify polarity in the CRM/kernel slice with a parity-gate decision |

| 2026-06-12 | IRB-guarantor PSE/RGLA substitution gap: **FIX** — the shared guarantor RW expression (`data/tables/guarantor_rw.py`, branch chain mirrors the SA twin character-for-character) replaces `_compute_guarantor_rw_sa`'s when/then chain, granting PSE (Art. 116(2) Table 2A) and RGLA (Art. 115(1)(b) Table 1B) guarantors their preferential RW on the IRB RWSM path. Same expression closes the sibling gaps in the same `.otherwise(null)`: international organisations 0% (Art. 118), named MDBs 0% (Art. 117(2)), rated MDBs Table 2B (Art. 117(1) — previously misrouted to institution Table 3). RWA-decreasing by design; pinned by 8 acceptance tests (CRR+B31 arms, hand-calculated: PSE CQS2/CQS3 → 50% → 500k; unrated GB RGLA → 20% → 200k; unrated DE → 100% → 1M) + 4 IO/MDB unit pins, all verified RED pre-fix | CRR Art. 235 RWSM substitutes the guarantor's SA risk weight; the IRB chain returning null made `is_guarantee_beneficial` false and silently discarded the guarantee with a misleading `GUARANTEE_NOT_APPLIED_NON_BENEFICIAL` label. The SA twin already implemented every missing branch — the asymmetry was pure drift between two hand-maintained chains, exactly what the shared rulepack-compiled expression exists to kill. Zero pre-existing tests changed outcome (no estate scenario exercised these guarantor types — the P5.11 acceptance hole) |
| 2026-06-12 | Unrated PSE/RGLA **guarantors** keep the SA-side documented approximation (country GB → 20%, else → 100%), NOT the full Art. 116(1)/115(1)(a) sovereign-derived tables | The guarantor join (`crm/guarantees._join_guarantor_counterparty`) carries no guarantor sovereign CQS; adding that join touches the shared CRM stage mid-slice. The approximation is conservative for sub-CQS1 sovereigns' PSEs and exact for the UK book; threading a real `guarantor_sovereign_cqs` is recorded as a follow-up candidate for the CRM/kernel slice. The acceptance test docstring pins which rule produced the 20% |
| 2026-06-12 | IRB guarantor institution short-term flag (Art. 120(2) Table 4) **deferred**: the shared expression takes `short_term_flag_col` but the IRB path passes None | The flag derivation lives in SA-stage scratch (`_inst_guarantor_short_term`, dropped at source per Wave-2); deriving it on the IRB path needs the guarantee original-maturity plumbing reviewed separately. Behaviour for institution guarantors on the IRB path is unchanged (matches the pre-fix `build_institution_guarantor_rw_expr` call) |

| 2026-06-12 | Phase 4 slice 6: `engine/kernels/allocation.py` — the multi-level direct/facility/counterparty allocator written once; six copies converted (provisions, hierarchy property coverage, guarantees pro-rata expand, CRM lookup builders, LTV metadata precedence, link demand pooling), each provably parameter-preserving (drift axes = kernel parameters, documented per copy). Two residues recorded: (a) **FCSM's allocator copy is level-BLIND** — one `beneficiary_reference`-keyed aggregate joined under three keys double-counts when loan/facility/counterparty reference namespaces collide, plus a direct-first RW coalesce whose comment contradicts the code; (b) the collateral-core `ancestor_facilities` literal materialisation with its null-list fallback stays caller-side. `look_through.py` verified to contain no multi-level allocation | Routing FCSM through the level-aware kernel CHANGES results for colliding-namespace data — that is a behaviour fix needing a recorded decision + oracle scenario (CRR Art. 222 path), not a silent unification during an extraction slice. Gates: all counts at exact pre-slice values; parity byte-identical; ratchet banked (fill_null 439→431, presence guards 374→372) |

| 2026-06-13 | Phase 5 S3: CRM constructor regime-state **eliminated** — `is_basel_3_1` dropped from `CRMProcessor`/`HaircutCalculator.__init__` (+ factories); regime now read from the per-method `config` (already passed to `get_crm_unified_bundle(data, config)`), whose signature is **unchanged**. **Deviation from the doc's S3 wording:** "thread the rulepack at the call boundary (stages/crm.py)" moved to **S4** — `get_crm_unified_bundle` has ~60 call sites, so its signature change is bundled with S4's table-pack migration (which actually needs the rulepack), not paid twice | `config.is_basel_3_1` is identical to the old constructor flag (set from it at build time), so the change is byte-identical parity; killing the constructor state removes the "framework-stale cached component" hazard (the comparison.py two-orchestrator workaround's root) with zero call-site/protocol ripple. `HaircutCalculator` resolves its haircut table per-call (`get_haircut_table(config.is_basel_3_1)`) instead of caching it from the flag, unifying the `haircuts.py:128` dual-source |
| 2026-06-13 | Phase 5 S3 investigation — `sa/risk_weights.py:1284` `build_institution_guarantor_rw_expr(is_basel_3_1=False)`: **PRESERVE** (intentional CRR-branch pin, not a regime leak) | The literal sits inside the CRR override ladder `_apply_crr_risk_weight_overrides` (dispatched at risk_weights.py:311 only when `not config.is_basel_3_1`), building the CRR institution RW (Art. 117(1)/120 Table 3) for a non-named MDB treated as an institution; B31 runs take the separate `_apply_b31_risk_weight_overrides` chain. Correct as written. The `is_basel_3_1=False` literal dissolves naturally in S6 when the two SA override ladders become pack-owned expression builders (no bool needed) |
| 2026-06-13 | Phase 5 S3 investigation — `ccr/sft_fccm.py:289` `lookup_collateral_haircut(is_basel_3_1=False)`: **FLAG / DEFER** (candidate regime-insensitivity, number-changing) | The SFT FCCM exposure-side supervisory haircut (`_lookup_haircut_unscaled` → `_compute_exposure_haircut`, CRR Art. 224 Table 1) is pinned to the CRR haircut table regardless of run regime, while the general supervisory haircut table DID change CRR→B31 (3-band→5-band maturity). Whether this is a bug turns on PS1/26 Art. 224-226 for SFT FCCM. Requires (1) a B31 SFT fixture confirming reachability + numeric divergence, (2) a regulatory determination (basel31 skill / PS1/26), (3) a recorded preserve-or-fix decision with oracle coverage — number-changing, so not in a parity-byte-identical slice. Scheduled for S9 (CCR → pack) where the haircut table becomes a regime-resolved pack entry; cross-linked from S4 |

| 2026-06-13 | Phase 5 S4a: rulepack threaded into `get_crm_unified_bundle` + FCSM Art. 222 floors → common pack | The deferred-from-S3 signature change lands as a **keyword-only** `pack: ResolvedRulepack \| None = None` (resolved from `config` when omitted), **not** the required param the S3 note anticipated: the recon found all 116 call sites pass positionally `(data, config)`, so the keyword default keeps the structural blast radius to **4 files** (processor, `CRMProcessorProtocol`, stage adapter, the one sentinel mock) with **zero test churn**, while production threads `pack=rulepack.pack`. The five FCSM scalars (`fcsm_rw_floor` 0.20, `fcsm_sovereign_bond_discount` 0.20, `fcsm_sft_cmp_floor` 0.00, `fcsm_sft_non_cmp_floor` 0.10, `fcsm_equity_collateral_rw` 1.00) move to `packs/common.py` (Art. 222 is single-regime — PS1/26 retains it); `simple_method.py` reads them via a `_FcsmFloors` holder + the new `compile.scalar_value` float boundary + the new `ResolvedRulepack.scalar_param` accessor (`_secured_floor_expr`/`_apply_currency_and_sovereign_discount` were not directly tested so threaded freely; `_derive_collateral_rw_expr`'s equity RW is a keyword-default to keep its 5 direct-test callers green). Byte-identical: same string-Decimals → same floats; FCSM fires only under the SIMPLE election so the Comprehensive stress parity set is untouched (the 30 FCSM unit/acceptance tests exercise the new path via the fallback). `contracts/protocols.py`→`rulebook.resolve` added to the check-12 allowlist — the pack type is genuinely part of the CRM contract (same TYPE_CHECKING-inversion shape as the existing `link_allocation` allowlist entry) |

| 2026-06-13 | Phase 5 S4b: overcollateralisation ratios + minimum-collateralisation thresholds → common-pack `LookupTable`s + regime `Feature`s | The CRR Art. 230 Table 5 divisors (`overcollateralisation_ratios`: financial/life 1.0, receivables 1.25, RE/other 1.40) and the 30% C*/C** thresholds (`min_collateralisation_thresholds`: RE/other 0.30, else 0.0) move to `packs/common.py` as `LookupTable`s — the values are **regime-invariant**, so they are NOT duplicated per regime. The regime-conditional *behaviour* (Basel 3.1 PS1/26 Art. 230(1) replaces the step-function with the continuous LGD* formula → no divisor, no threshold gate) becomes two regime `Feature`s `firb_overcollateralisation_divisor_applies` / `firb_min_collateralisation_threshold_applies` (CRR True, B31 False) — per the doc's "Feature + LookupTable" intent, this is the first time a B31 regime-behaviour branch becomes pack data rather than a `config.is_basel_3_1` read. `expressions.py` (`overcollateralisation_ratio_expr` now takes the pack + checks the Feature; `min_collateralisation_threshold_expr` reads the lookup) + `collateral.py` (`_apply_collateral_unified` resolves the pack via the S4a keyword-default+fallback, the `:838` gate now keys off the Feature, the `:840/842` reads come from the lookup) via the new `compile.lookup_float_map` boundary. Pack threaded processor→`apply_collateral`→`_apply_collateral_unified` (3 hops, all keyword-default so the ~4 direct `_apply_collateral_unified` tests stay green; 2 `test_life_insurance` expr-builder calls updated to pass a CRR pack). Byte-identical on all 4 configs (values are float-equal: `float(Decimal("1.40"))==1.40`; the B31 short-circuit/threshold-skip preserved exactly by the Features). |

| 2026-06-13 | Phase 5 S4c: F-IRB supervisory LGD dual-shape collapse (CRM half) → canonical `firb_supervisory_lgd` DecisionTable — **PRESERVE / byte-identical** (the flagged number-changing item, verified) | The recon established the two shapes (`firb_lgd.py` FIRB-shape, `crm_supervisory.py` CRM-shape) encode the SAME LGD numbers with **zero disagreements at every overlapping cell**, so the collapse is number-safe. One canonical `DecisionTable` (per regime, in `packs/crr.py`+`packs/b31.py`) keyed by `(collateral_type, seniority, is_fse)` at FIRB granularity is now the single source; `engine/crm/expressions.py::supervisory_lgd_values(pack)` **projects** it to the CRM simple-category dict (financial/receivables/real_estate/other_physical/unsecured/covered_bond/life_insurance, + `unsecured_fse` iff the regime splits FSE, + the `*_subordinated` secured-portion LGDS iff the regime carries them) — reproducing `CRR_SUPERVISORY_LGD` (10 keys) and `BASEL31_SUPERVISORY_LGD` (8 keys) EXACTLY, pinned by `test_supervisory_lgd_values_{crr,b31}_projection_byte_identical`. `collateral_lgd_expr(pack)` reads via the projection. Consumers threaded: `_apply_collateral_unified` reuses the S4b `resolved_pack`; `apply_firb_supervisory_lgd_no_collateral` (config-optional, heavily direct-tested) gets a `_resolve_pack_for_lgd(pack, config, is_basel_3_1)` fallback (placeholder date — LGD has no Schedule) so its ~20 direct unit-test callers stay green with zero churn; the `CRMProcessor._apply_firb_supervisory_lgd_no_collateral` wrapper passes config (fallback resolves). **Only the CRM half lands here** — the FIRB-shape consumers (`irb/transforms.py`, `irb/guarantee.py`) are wired to the SAME canonical table in S5, completing the single-source. **Deferred:** the hardcoded subordinated `pl.lit(0.75)` in `collateral.py` (an engine literal = the FIRB `subordinated` key, not a `crm_supervisory` dict read) rides S5 with the FIRB side. Parity byte-identical on all 4 configs; suite +2 projection pins. |

| 2026-06-13 | Phase 5 S4d: FCCM supervisory haircut table → per-regime `collateral_haircuts` DecisionTable + the FX / restructuring haircut scalars → pack, landed as three byte-identical sub-commits (S4d-1 data+helper, S4d-2 the JOIN consumer, S4d-3 the guarantee scalars) | The haircut table is the **only** DataFrame-JOIN consumer in the engine, so it gets the one new compile primitive `decision_table_df(t, *, value_name, key_dtypes)` — the DataFrame sibling of `decision_expr`, rendering a Decimal `DecisionTable` to a keyed lookup frame at the Decimal→float boundary, with `key_dtypes={"cqs": pl.Int8}` pinning the join-critical dtype. The per-regime tables (`packs/crr.py` 28 rows / 3 bands, `packs/b31.py` 42 rows / 5 bands) carry literal rows **machine-generated from the existing `data/tables` specs** to eliminate transcription error, and a pin asserts `decision_table_df(pack)` is frame-equal (schema + values, order-insensitive — order is not load-bearing for a keyed left join) to `get_haircut_table()` for both regimes. `HaircutCalculator.apply_haircuts`/`apply_exposure_haircut` gain keyword `pack=None` + a `_resolve_pack_for_haircut` fallback (config, else `is_basel_3_1` placeholder-date — the Art. 224 table has no Schedule) mirroring `_resolve_pack_for_lgd`; the Int8/Boolean join keys are re-cast engine-side so the rendered frame matches the join schema exactly. `fx_haircut` + the new `restructuring_exclusion_haircut` common-pack scalars feed `apply_haircuts` and the two **production** guarantee helpers (`_apply_fx_haircut_to_guarantees`/`_apply_restructuring_haircut_to_guarantees`), with the run's pack threaded the full chain `get_crm_unified_bundle → _apply_guarantees_step → apply_guarantees → _prepare_guarantees` (all keyword-default → zero churn on the many positional `apply_guarantees` test/benchmark callers). Byte-identical on all 4 configs each sub-commit; `get_haircut_table` retained (its own dict↔DF parity tests are untouched). |
| 2026-06-13 | Phase 5 S4d finding (recorded, not actioned): `_apply_guarantee_fx_haircut` / `_apply_restructuring_exclusion_haircut` (`guarantees.py:1253/1309`) are **production-dead** — called only from `test_guarantee_submodules.py`, never from `apply_guarantees`. Their `FX_HAIRCUT`/`RESTRUCTURING_EXCLUSION_HAIRCUT` constant reads (and those imports) are left as-is | Migrating a test-only function to the pack adds churn for zero production benefit; the vestigial pair is a dead-code-deletion candidate (with its tests) for a separate cleanup slice, not a parity slice. The live guarantee path uses the `_apply_*_to_guarantees` siblings, which S4d-3 migrated |
| 2026-06-13 | Phase 5: **SA-CCF migration DEFERRED out of S4** (recorded decision) | The SA undrawn CCF mapping (`engine/ccf.py::sa_ccf_expression`) is the one CRM-adjacent regime table that does NOT fit the keyword-default-pack-into-CRM pattern: it is also called from `engine/stages/hierarchy/facility_undrawn.py` (synthetic facility-undrawn rows, outside the CRM stage), and it carries a `_normalize_risk_type` step that `compile.lookup_expr` does not replicate (the lookup is not a plain key→value map). Migrating it cleanly needs either a pack-owned expression builder that subsumes the normalisation or a shared CCF kernel threaded into both the hierarchy and CRM stages — scoped to its own slice, not bundled into S4's CRM-table work. The CCF tables stay in `data/tables` until then |

| 2026-06-13 | Phase 5 S5a: IRB pack-threading skeleton + the `1.06` scaling factor → pack | `rulepack.pack` threaded `stages/calc.py → IRBCalculator.calculate_branch → _run_irb_chain` as a keyword-only `pack: ResolvedRulepack \| None = None` (fallback `RulepackV0.from_config(config).pack`, the S4a pattern); the four `irb_scaling_factor` reads (`transforms.apply_all_formulas`, `formulas.apply_irb_formulas`, `guarantee._apply_parameter_substitution`, the NBD-floor helper) now read `scalar_value(pack.scalar_param("irb_scaling_factor"))` (CRR 1.06 / B31 1.0). `IRBCalculatorProtocol.calculate_branch` gained the kwarg; the `# noqa: ARG001` on `rulepack` in `stages/calc.py` dropped. Byte-identical on all 4 configs (same string-Decimal → same float). |
| 2026-06-13 | Phase 5 S5b: F-IRB supervisory LGD dual-shape collapse (IRB half) → the canonical `firb_supervisory_lgd` DecisionTable, completing the S4c single-source | New `formulas.firb_supervisory_lgd_values(pack)` projects the canonical table to the FIRB-granularity dict, reproducing `FIRB_SUPERVISORY_LGD` (16 keys) / `BASEL31_FIRB_SUPERVISORY_LGD` (12 keys) EXACTLY (pinned `test_firb_supervisory_lgd_values_{crr,b31}_projection_byte_identical`). `transforms.apply_firb_lgd` swaps `get_firb_lgd_table_for_framework(is_b31)` → the projection; `guarantee.py`'s `_firb_lgd_tuple`/`_adjust_expected_loss` read it too. The S4c-deferred hardcoded `pl.lit(0.75)` subordinated-unsecured literals (×5 in `collateral.py`) retired via new `crm/expressions.subordinated_unsecured_lgd(pack)` (75% regime-invariant — the `(unsecured, subordinated, …)` row). `supervisory_lgd_values` (the CRM projection) left untouched so the S4c pins stay green. Byte-identical on all 4 configs. |
| 2026-06-13 | Phase 5 S5c: IRB PD/LGD floors → pack — operator chose **pack-direct + rewrite P2.36** (the truest end-state) over the pack-as-config-default alternative | Three byte-identical sub-commits. **S5c-1** (additive): `pd_floors`/`lgd_floors` `FormulaParams` in `packs/{crr,b31}.py` keyed identically to `contracts/config.py::PDFloors`/`LGDFloors`; the `airb_lgd_floor` Feature added to `packs/crr.py` (enabled=False) so `pack.feature("airb_lgd_floor")` resolves on both regimes; new `compile.formula_float_map` (the dict sibling of `formula_param_lit`). Pins: `test_floor_pack_parity.py` (pack bundles == config factories field-for-field; Feature False/True per regime). **S5c-2**: PD floors pack-direct — `_pd_floor_expression` reads the bundle via `formula_float_map`; pack threaded through `apply_pd_floor`/`apply_all_formulas`/`apply_irb_formulas` + the 3 guarantee sites (incl. threading `pack` into `_apply_double_default`); zero `config.pd_floors` engine reads remain. **S5c-3**: LGD floors pack-direct — the 3 `_lgd_floor_*` builders + `apply_lgd_floor`/`_lgd_floored_expr`/`apply_irb_formulas`, with the inner `config.is_crr → 0.0` AND the outer `config.is_basel_3_1` LGD-path gates BOTH replaced by `pack.feature("airb_lgd_floor")` (True iff B31); zero `config.lgd_floors`/`config.is_*` floor reads remain. **Blocker resolved:** the two P2.36 `*_override_drives_dispatch_not_fallback` tests override `config.pd_floors` and assert end-to-end RWA — pure pack-sourcing would ignore the override. Fix = a pipeline pack-injection seam (`RulepackV0.from_resolved` + an internal `_pack_override` field, `ResolvedRulepack.with_overrides(**entries)` with content-hash recompute, `PipelineOrchestrator.run_with_data(*, rulepack=None)`), and the two tests re-expressed to override the pack's `pd_floors` entry and inject it — **asserted RWA numbers UNCHANGED, only the override mechanism moved**. `PDFloors`/`LGDFloors` dataclasses **stay** (config surface; field-existence + factory-value tests untouched) until the S11 config→RunConfig split; `api/service.py`'s metadata echo still reads `config.pd_floors` (not a calc path). Byte-identical on all 4 configs each sub-commit; full suite 7637 passed; a 4-dimension adversarial review of the full diff returned pass / zero findings. |

| 2026-06-13 | Phase 5 S5d: IRB maturity + double-default regime branches → pack Features (one byte-identical commit) | Four regime on/off branches move off `config.is_crr`/`config.is_basel_3_1` onto cited pack `Feature`s (added to BOTH packs so each resolves on both regimes): `firb_sft_supervisory_maturity` (CRR T/B31 F — `_apply_firb_sft_supervisory_maturity`, whose now-unused `config` arg was dropped), `one_day_maturity_floor` (CRR T/B31 F — `_effective_one_day_floor_flag`), `revolving_uses_termination_maturity` (CRR F/B31 T — `_maturity_base_expr`), `double_default_treatment` (CRR T/B31 F — `guarantee._apply_double_default`, replacing only the `is_crr` half; the `config.enable_double_default` ELECTION stays, routing to RunConfig in S11). **Constants stay engine literals** (0.5y SFT supervisory M, the 1/365 one-day floor `_ONE_DAY_YEARS`, the 0.15+160×PD double-default multiplier) — only the regime decision is pack data; the 1/365 value is genuinely regime-invariant in application (it fires whenever the flag is set, CRR-derived or explicit), so the Feature gates the *derivation*, not the value. The resolved pack threads once through `prepare_columns` (keyword-default + `RulepackV0.from_config` fallback; only production site `_run_irb_chain` passes `pack=resolved_pack`) down to the four maturity helpers as a **required** arg (no test calls them directly — verified). `_apply_double_default` already carried the pack from S5c-2. Pin: `test_maturity_double_default_features.py` locks all four Feature values per regime. Out of scope (left as-is): the `apply_firb_lgd` FSE-LGD-split `is_basel_3_1` (S5b territory, a distinct future Feature candidate). Byte-identical on all 4 configs; full suite 7637 passed/2 skipped (incl. test_firb_sft_maturity, test_b31_revolving_maturity, test_one_day_maturity_floor_propagation, test_irb_double_default, P1.118, P1.94d). |

| 2026-06-13 | Phase 5 S5e: close the IRB-calc regime reads — F-IRB FSE senior-LGD-split → Feature; the 3 recon-facet-F residual items DEFERRED to their paired slices | A 3-facet recon (wf_808febef) assessed the recon-facet-F residual; the disposition: **(1) SME correlation turnover threshold + `is_b31` currency basis → DEFER to S8.** The CRR threshold is **FX-rate-derived** (`config.thresholds.sme_turnover_threshold` is set by the EUR/GBP FX-sync to EUR 50m × rate), so a static pack `ScalarParam` would be byte-identical only at the default rate — a masked semantics change for non-default-FX runs. It is also **shared with the classifier's `is_sme` gate** (`stages/classify/attributes.py`); both consumers should migrate together when `RegulatoryThresholds` moves in S8 (EUR-base value + engine-side ×FX, or an FX-aware accessor). `is_b31` is also threaded into the guarantor NBD floor (`_apply_no_better_than_direct_floor` → `_parametric_irb_risk_weight_expr`), so the correlation-basis flag is best migrated coherently there too. **(2) `apply_post_model_adjustments` B31 mortgage RW floor → DEFER to S11.** `engine/irb/adjustments.py` has **zero** `is_crr`/`is_basel_3_1` reads — PMAs are gated purely by `config.post_model_adjustments.enabled`, an **overridable config election** (a B31 run may pass `PostModelAdjustmentConfig.crr()`), not a hard regime read; converting it to a Feature would silently remove that override. The `mortgage_rw_floor` value (regulatory 0.10) is heavily test-overridden (0.15/0.20/0.0) — P2.36-class — and the same `PostModelAdjustmentConfig` carries firm-election PMA scalars. The whole sub-config is best dismantled as a unit in the S11 config→RunConfig split (floor value → pack regulatory default with a seam override; `enabled` + scalars → RunConfig). **(3) `guarantee._compute_guarantor_rw_sa` `is_b31` → DEFER to S6.** It is a pure consumer of the SA risk-weight tables (`build_guarantor_rw_expr` / `data/tables/guarantor_rw.py`: institution ECRA/CQS, corporate Table 6, PSE/RGLA/MDB) that S6 migrates as pack-owned LookupTables/expr-builders; migrating the flag in isolation duplicates work and risks churn when S6 refactors the builder (confirms the recorded memory note). **Migrated now (the one clean, byte-identical in-theme read the facet-F recon missed):** `transforms.apply_firb_lgd`'s senior-unsecured FSE LGD split `if config.is_basel_3_1:` → `pack.feature("firb_fse_senior_lgd_split")` (CRR False / B31 True). A Feature — not an unconditional `.get(..., default_lgd)` rewrite — was used deliberately to preserve the exact per-regime column-reference behaviour (the CRR path must never reference `cp_is_financial_sector_entity` nor the projection's conditional `unsecured_senior_fse` key, which the B31 projection adds only because 45% != 40%). Pin `test_firb_fse_senior_lgd_split_feature_per_regime`. **S5 (IRB calc → pack) is COMPLETE** (S5a scaling + S5b FIRB LGD + S5c PD/LGD floors + S5d maturity/double-default + S5e FSE split); the only remaining IRB regime reads are the three above, correctly assigned to S6/S8/S11. Byte-identical on all 4 configs; full suite 7642 passed/2 skipped. |
| 2026-06-13 | Phase 5 S6a: SA calculator stage made pack-aware + the two `_prepare_risk_weight_lookup` regime reads → cited Features | A 5-facet recon (wf_67bad1c3) mapped the SA regime surface; a key scope correction vs the recon: the **only genuine `config.is_crr`/`is_basel_3_1` reads** in the SA stage are `risk_weights.py:{311 dispatch, 841 CQS-table-selection, 916 SL-CQS-nulling, 1450 defaulted-fork}` and `rw_adjustments.py:{205 SA-guarantor, 293 currency-mismatch, 418 due-diligence}` — the recon's "high-risk 150% / subordinated 150% / covered-bond" sites are **not** config reads (they are unconditional branches *inside* `_apply_b31_risk_weight_overrides`, which only runs under B31, so already regime-correct), and `:1284`'s `is_basel_3_1=False` is a **literal** inside the CRR-only ladder (no config read). **Design choice: follow the S5 Feature-gate pattern** (gate the regime branch with a cited Feature; table VALUES stay in `data/tables/`) rather than the recon's "lift the combined-CQS table into the pack as a DecisionTable" — lower parity risk (avoids the left-join/null-sentinel shape trap) and matches the pack's own documented convention. **Prerequisite fixed:** `engine/stages/calc.py` passed `pack=rulepack.pack` only to the IRB branch; S6a threads it into both SA calls (`calculate_unified` floor path + `calculate_branch`). Threading: `calc.py → SACalculator.calculate_unified/calculate_branch (*, pack=None) → apply_risk_weights (*, pack=None, forwards) → _prepare_risk_weight_lookup (*, pack=None, RulepackV0.from_config fallback for direct callers)`; `SACalculatorProtocol` methods gain `pack` (mirrors `IRBCalculatorProtocol`). Migrated reads: `:841` `if config.is_basel_3_1: get_b31_combined…` → `if pack.feature("sa_revised_risk_weight_tables")` (CRR F/B31 T; reused by the S6c guarantor builder); `:916` SL non-issue-specific-ECAI CQS-nulling → `pack.feature("sa_sl_inferred_rating_disapplied")` (CRR F/B31 T, PS1/26 Art. 139(2B)). The other SA reads are assigned to later sub-slices (S6b defaulted, S6c guarantor incl. the deferred-from-S5e `_compute_guarantor_rw_sa`, S6d currency-mismatch + due-diligence) and the `:311` dispatch fork is the strangler top-level branch retired LAST (S10). `arch_metrics.json` `max_engine_module_loc` 1499→1510 (pack threading grew `risk_weights.py`). Pin `test_sa_risk_weight_features.py`. Byte-identical on all 4 configs; full suite 7644 passed/2 skipped. |
| 2026-06-13 | Phase 5 S6b–S6d: the remaining SA leaf regime reads → cited Features; **S6 (SA calc → pack) COMPLETE** | All on the S5 Feature-gate pattern (gate the regime branch; VALUES stay in `data/tables/`), each a byte-identical commit, all reusing the keyword-default + `RulepackV0.from_config` fallback threading. **S6b** (`a13917d2`): `_apply_defaulted_risk_weight`'s single `if config.is_basel_3_1:` block → `pack.feature("sa_revised_defaulted_treatment")` (CRR F: Art. 127 pre-provision `ead_final` denominator, no RE carve-out; B31 T: gross-outstanding denominator + Art. 127(3) RESI-RE non-income flat 100%). Because ONE Feature gates the whole block and no value moves, the recon's CRR-vs-B31 threshold-value disagreement is **moot**. `arch_metrics.json` 1510→1513. **S6c** (`9ab196fb`): the guarantor SA-RW path — both shared-builder call sites (`sa/rw_adjustments.py:205` `_build_guarantor_rw_expr` + `irb/guarantee.py:287` `_compute_guarantor_rw_sa`) migrated **atomically** to `pack.feature("sa_revised_risk_weight_tables")` (the same S6a Feature — institution ECRA/SCRA + corporate Table 6 ride the same regime axis). `data/tables/guarantor_rw.py::build_guarantor_rw_expr` KEEPS its `is_basel_3_1: bool` param (fed from the Feature) — **zero data/tables churn**. Closes the guarantor item **deferred from S5e**. `build_entity_rw_expr` (hierarchy preview, separate fn+stage) left for a hierarchy slice. **S6d** (`3aae3761`): the two Basel-3.1-only post-RW function gates → `pack.feature("sa_currency_mismatch_multiplier")` (Art. 123B) and `pack.feature("sa_due_diligence_override")` (Art. 110A); the `:299` `reporting_date < B31_EFFECTIVE_DATE` is a per-run **date comparison, NOT a `config.is_*` read**, so deliberately left as engine logic (no Schedule). **Two SA items DEFERRED with rationale: (1) the `:318` top-level dispatch fork** (`if config.is_basel_3_1: _apply_b31_risk_weight_overrides else _apply_crr…`) — the ONE remaining SA `config.is_*` read; it is intrinsic **control-flow** divergence between two structurally-different ladder *functions* (not a value/gate the rulepack model replaces, and the ladders have no internal regime reads), so it is the strangler top-level seam best retired with the `config` regime-facade removal in **S10/S11**, not as a leaf rename. **(2) supporting factors** (`engine/supporting_factors.py::apply_factors` `config.supporting_factors.enabled`) → **S8**: verified strictly regime-derived (set ONLY by `SupportingFactors.crr()`=True / `.basel_3_1()`=False — zero independent `SupportingFactors(enabled=…)` constructions or `replace()` in src/tests, so byte-identical to the latent `supporting_factors` pack Feature), BUT it lives in the **cross-approach** calculator shared by SA+IRB+slotting and its tier factors + SME threshold are the same threshold/election family deferred to S8; migrating only the gate would split the concept and pull IRB/slotting threading into an "SA calc" slice — migrate the whole `SupportingFactors` unit together in S8. **S6 added 5 SA Features** (`sa_revised_risk_weight_tables`, `sa_sl_inferred_rating_disapplied`, `sa_revised_defaulted_treatment`, `sa_currency_mismatch_multiplier`, `sa_due_diligence_override`) to BOTH packs, all pinned in `test_sa_risk_weight_features.py`. Byte-identical on all 4 configs each slice; full suite 7647 passed/2 skipped at S6d. |
| 2026-06-13 | Phase 5 S7a–S7b: slotting + equity calculators → pack Features; **S7 COMPLETE** | S5 Feature-gate pattern throughout (gate the regime branch; VALUES stay in `data/tables/`). **S7a slotting** (`5e1778ac`): `apply_slotting_weights` + `apply_el_rates` (`transforms.py:168,202`) source `is_crr = not pack.feature("slotting_revised_tables")` instead of `config.is_crr`; the `lookup_rw`/`lookup_el_rate` helpers keep their `is_crr: bool` param (fed from the Feature). Threaded `pack` calc.py → `SlottingCalculator.calculate_branch` (`*, pack=None`) → both transforms; `SlottingCalculatorProtocol` gains `pack`. Feature: `slotting_revised_tables` (CRR F: Art. 153(5) single table, HVCRE Table 2 not onshored; B31 T: PS1/26 Art. 153(5) Table A / CRE33, HVCRE + PF pre-op). **S7b equity** (`6180c10a`): migrated 4 of equity's 5 reads + threaded the pipeline pack into the equity stage (its `rulepack` param was previously unused / `noqa ARG001`). `_determine_approach` (`:300`) + the COREP transitional-approach label (`:992`) → `equity_irb_approaches_available` (CRR T: Art. 155 IRB Simple/PD-LGD available; B31 F: removed, all equity SA per CRE20.58-62); `_apply_equity_weights_sa` (`:535`) → `equity_revised_sa_risk_weights` (CRR F: Art. 133(2) 100% flat; B31 T: Art. 133(3)-(5) 250%/400%/150%); `_resolve_look_through_rw` CIU CQS table (`:383`) **reuses** `sa_revised_risk_weight_tables`. `get_equity_result_bundle` (+ protocol) gains `*, pack=None` and forwards to the four private methods (each with `RulepackV0.from_config` fallback); `stages/equity.py` passes `pack=rulepack.pack`. The `SentinelEquityCalculator` test stub was conformed to the new signature (forwards `pack`) — a protocol-conformance fix, not an expectation change. **DEFERRED to S8: equity's IRB-equity PD/LGD correlation read** (`_apply_equity_weights_pd_lgd` → `_correlation_expr_from_pd(is_b31=config.is_basel_3_1)`, now `calculator.py:878`) — it is the **shared IRB correlation formula** (`engine/irb/formulas.py`), the exact `is_b31` correlation-basis concern deferred from S5e; migrate it with the IRB correlation + SME-threshold family in S8, not in isolation. After S7, slotting has **zero** `config.is_*` reads and equity has exactly the one deferred correlation read. Pins `test_slotting_features.py` / `test_equity_features.py`. Byte-identical on all 4 configs each slice; full suite 7650 passed/2 skipped at S7b. |
| 2026-06-13 | Phase 5 S8a–S8c: classifier + shared IRB-correlation regime gates → pack Features; **S8 (classify + correlation) COMPLETE**; supporting-factors DEFERRED to S11 | A 3-facet recon (wf_977cf296) mapped the surface; the governing insight (verified) is the **GATE/VALUE separation**: a regime GATE migrates to a Feature now (byte-identical); the FX-rate-derived VALUEs it sits near stay config (→ S11), because the SME thresholds = EUR base × `eur_gbp_rate` (FX-sync-mutated) and a static pack scalar is byte-identical ONLY at the default rate. **S8a** (`c388362f`): the classifier Art. 147A IRB-approach-restriction family → ONE Feature `approach_restrictions_b31_applicable` (approach.py:154 `_apply_b31_approach_restrictions`, :252 `pl.lit` EU-domestic-sovereign gate, :261 IPRE/HVCRE forced-slotting, audit.py:76 CLS008 conservatism warning); wired the pipeline pack into the classify stage (stage.py was discarding rulepack via noqa ARG001) → `classify(*, pack=None)` → `assign_approach` + `collect_input_warnings`; `ClassifierProtocol.classify` gains `pack`; `SentinelClassifier` test stub conformed. The FX-derived thresholds those branches read (`sme_balance_sheet`, `large_corporate_revenue`) stay config. **S8b** (`ade34e64`): the three remaining pure-regime classifier gates → Features `b31_high_risk_class_applicable` (attributes.py:275 HIGH_RISK→OTHER, Art. 128 omitted from UK CRR by SI 2021/1078), `b31_art_124e_three_property_limit_applies` (attributes.py:356 natural-person RRE re-route), `b31_exposure_subclass_reporting_applies` (subtypes.py:289 COREP corporate sub-class); reuse the S8a classify(pack) plumbing. **S8c** (`c2d58306`): the shared IRB SME-correlation regime selector → ONE Feature `irb_correlation_sme_gbp_native`, migrated **atomically across ALL FIVE call sites** (the recon's survey first found three; source has five — formulas.py:498 apply_irb_formulas, transforms.py:383 calculate_correlation + :621 apply_all_formulas, guarantee.py:388 NBD floor, equity.py:878 PD/LGD). **Option B** (S6c/S7a pattern): the shared `_correlation_expr_from_pd`/`_polars_correlation_expr` helpers KEEP their `is_b31: bool` param (so the scalar/test correlation surface is untouched); only the production config reads move; ty enforces atomicity. **Closes the correlation-basis `is_b31` deferred from BOTH S5e (IRB) and S7b (equity).** **DEFERRED to S11 — supporting factors (`config.supporting_factors.enabled`):** the recon proposed an S8d migrating "the single shared gate", but source has **8+ engine reads** (5× in supporting_factors.py, plus aggregator.py:253 — a shared forced-single-stream file —, irb/calculator.py:147, slotting/calculator.py:156, + api/service.py reporting). `enabled` is a config FIELD (not a `config.is_*` regime read) that S11 removes, and its tier-factor + FX-threshold VALUEs are S11 anyway, so the whole `SupportingFactors` object dismantles coherently in the config→RunConfig split — migrating 8 gates now (incl. the shared aggregator) only for S11 to remove the field is churn. The latent `supporting_factors` Feature in crr.py stays unconsumed until then. **Also DEFERRED to S11:** classifier `attributes.py:551` Art. 123A retail two-path (`enforce_retail_granularity` election + FX SME turnover threshold). S8 added 5 Features (`approach_restrictions_b31_applicable`, `b31_high_risk_class_applicable`, `b31_art_124e_three_property_limit_applies`, `b31_exposure_subclass_reporting_applies`, `irb_correlation_sme_gbp_native`); pins in `test_classifier_features.py` / `test_irb_correlation_features.py`. Byte-identical on all 4 configs each slice; full suite 7655 passed/2 skipped at S8c. Remaining engine `config.is_*` reads (21): CRM (haircuts/processor/provisions/simple_method), ccf.py, comparison.py, re_split (flagging/splitter), stages/ccr.py, sa/risk_weights.py:318 dispatch, pipeline.py, + the two S11 defers — to be sliced in S9+. |

| 2026-06-14 | Phase 5 S9a–S9h: CRM / CCF / re_split / CCR regime gates → pack Features; **S9 COMPLETE** | A 5-cluster recon (wf_55c9c563) mapped the surface; reconciled against an independent grep (18 inventory sites + 5 hidden splitter-plumbing groups, all accounted). Governing rule again the **GATE/VALUE separation** — every migrated branch was verified to gate static regulatory constants (CCF %s, LGD tables, LTV caps, alpha phase-fractions), **zero FX-derived values**, so the FX trap was confined entirely to the deferred `pipeline.py:258`. All on the S5 Feature-gate pattern (keyword-default `pack` + `RulepackV0.from_config` fallback), each a byte-identical commit. **S9a** (`d3043c3`, CCR): SA-CCR transitional alpha add-on → `ccr_transitional_alpha_addon_applicable` (Art. 274(2A), B31-only phase-in); CCR stage `noqa: ARG001` dropped. **S9b** (`0514dcc5`, FCSM): Simple-Method collateral RW table selection (`simple_method.py:330`) **reuses** `sa_revised_risk_weight_tables` (Art. 120 ECRA/SCRA + Art. 122 Table 6 — same regime concept; dedupe, no new Feature). **S9d** (`a264aa92`, haircuts): FCCM collateral-haircut maturity-band structure → `collateral_haircut_maturity_bands_revised` (CRR 3-band / B31 5-band, Art. 224); the table VALUES already pack-backed (S4d). **S9c** (`90feba6a`, CCF): F-IRB-uses-SA-CCF routing (Art. 166C) → `firb_uses_sa_ccf` + A-IRB EAD floors (Art. 166D(5)) → `airb_ead_floor_applies`; pack threaded processor→`apply_ccf`/`_compute_ccf`/`_compute_ead` (CCF is a concrete calculator, no protocol). **S9e** (`8c55849c`, provisions): SA-CCF table used as the pro-rata provision-weighting basis → `sa_revised_ccf_table` (distinct from `firb_uses_sa_ccf` — table-selection vs routing); reuses the S9c `_run_ead_pipeline(pack=…)` plumbing. **S9f** (`c042e8ab`, re_split flagging): three RE loan-split decision gates (run inside the classifier stage) → `sa_re_split_cre_rental_coverage_required` (CRR True / B31 False — the rental-coverage test, the lone affirmative-under-CRR Feature in S9), `sa_re_split_art_124_4_all_or_nothing`, `sa_re_split_whole_loan_path_applies`. **S9g** (`df7c69ed`, re_split splitter): RE-split parameter-set selection → `sa_re_split_revised_parameters`; **forced-single-stream** (added `pack` to `RealEstateSplitterProtocol.split`), so its own last slice; stage `noqa: ARG001` dropped. **S9h — the CRM collateral-LGD surface (operator chose "honest internal-read")**: the 4 processor bools (813/960/826/984) each passed `config.is_basel_3_1` into a `collateral.py` helper where it fanned out to ≥4 distinct concepts — an Option-B call-site swap would have been byte-identical but **dishonest** (one Feature name can't represent a 4-concept bool). **S9h-1** (`7debc2a1`): `apply_firb_supervisory_lgd_no_collateral` branches read `firb_fse_senior_lgd_split` (reused) + the **one genuinely new** Feature `airb_lgd_collateral_method_applicable` (Art. 169A/169B AIRB Foundation/LGD-modelling; CRR AIRB is free-form). The `is_basel_3_1` param was demoted to a keyword-only no-config bootstrap hint for `_resolve_pack_for_lgd` (branches read Features off the SAME resolved pack — more consistent than the prior bool/values split), keeping all ~40 keyword test-callers green. **S9h-2** (`df0c30d6`): the shared `airb_lgd_preserved_expr` + its 3 callers (`find_misdirected_airb_model_collateral`, `apply_collateral`, `_apply_collateral_unified`) migrated atomically — FSE split (596) → `firb_fse_senior_lgd_split`, exposure-haircut bands (357) → `collateral_haircut_maturity_bands_revised`, Art. 230(2) subordinated secured-portion LGDS rows (924) → `firb_overcollateralisation_divisor_applies` (reused: same CRR Art. 230 step-function the B31 LGD* formula removes), AIRB method (83/85/1004/1006) → `airb_lgd_collateral_method_applicable`. `is_basel_3_1` dropped outright from all four (config/pack always present); the 9 config-consistent `_apply_collateral_unified` direct-test callers + 1 benchmark dropped the now-removed arg (no expected values changed). **KEEP (not migrations):** `comparison.py:424/426` `_validate_configs` — public-API config-*identity* assertions (DualFrameworkRunner runs two separate orchestrators; no single effective pack), gate no values. **DEFER:** `pipeline.py:258` (FX-sync bootstrap, runs BEFORE pack resolution → circular; the FX-derived thresholds it rebuilds are S11) → **S11**; `sa/risk_weights.py:318` dispatch fork → **S10**; `attributes.py:551` Art. 123A retail → **S11**. **NOT closed by S9 (recorded honestly):** the S3-scheduled `ccr/sft_fccm.py:289` `is_basel_3_1=False` literal is a **number-changing** regime-insensitivity investigation (needs a B31 SFT fixture + PS1/26 determination + oracle), not a byte-identical pack-migration — it is not a `config.is_*` read and was out of scope for S9's byte-identical slices; it remains open for the number-changing workstream. S9 added 8 new Features (`ccr_transitional_alpha_addon_applicable`, `collateral_haircut_maturity_bands_revised`, `firb_uses_sa_ccf`, `airb_ead_floor_applies`, `sa_revised_ccf_table`, `sa_re_split_{cre_rental_coverage_required,art_124_4_all_or_nothing,whole_loan_path_applies,revised_parameters}` [4], `airb_lgd_collateral_method_applicable`) + reused 3 existing; pins in `test_{ccr,haircut,ccf,provisions,re_split,collateral_lgd}_features.py`. Byte-identical on all 4 configs every sub-slice; full suite 7665 passed/2 skipped at S9h-2. Remaining engine `config.is_*` reads: only the S10 (risk_weights:318) + S11 (pipeline:258, attributes:551, supporting-factors, post-model mortgage floor) defers and the `comparison.py` KEEP. |

| 2026-06-14 | Phase 5 S10: retire the SA risk-weight override-ladder regime dispatch → Feature + delete the `COVERED_BOND_UNRATED_DERIVATION` alias trap (one byte-identical commit `b5693543`) | **Scope note (divergence from the written S10 bullet above):** the plan's S10 line describes the *table-move capstone* (`data/tables/` → `packs/{common,crr,b31}` behind shim getters + dup single-sourcing + symbol-set parity tests). The S4–S9 execution deliberately followed the **S5 Feature-gate pattern** (gate the regime branch; VALUES stay in `data/tables/`), so the table *content* did NOT migrate into packs along the way — the bulk table-move remains a **distinct, larger, still-outstanding effort** (its own future slice). What S10 discharges here are the two concrete, number-sensitive, byte-identical items the capstone called out by name: the dispatch seam and the alias trap. **(1) The dispatch fork** — `apply_risk_weights`'s `if config.is_basel_3_1: _apply_b31_risk_weight_overrides else _apply_crr_…` — was the **last `config.is_*` read in `engine/sa/risk_weights.py`** (the strangler top-level seam deferred from S6d). It moves onto a NEW cited Feature `sa_revised_risk_weight_overrides` (CRR F/B31 T), genuinely **distinct** from `sa_revised_risk_weight_tables`: the latter selects the base CQS-join table in `_prepare_risk_weight_lookup` (+ equity/irb/crm/rw_adjustments consumers), the former selects the whole when/then **override-ladder function** applied on top — two materially different functions, not synonyms (adversarial review confirmed). The file is now **regime-read-free**. **(2) The alias** `COVERED_BOND_UNRATED_DERIVATION = …_B31` (the §6 flagged number-changing item) is **deleted**. **PRESERVE decision:** the engine CRR covered-bond expr (`_crr_unrated_cb_rw_expr`) already indexed the explicit `_CRR` dict (4-key, Art. 129(5)(b) 0.50→0.20), so **no CRR number ever borrowed the B31 (b)=0.25 value** — the alias was a latent *risk*, not a live bug (it was consumed only by the B31 expr + tests). Each consumer now selects its regime dict explicitly: B31 engine path → `_B31` (the identical object the alias pointed at, byte-identical); B31 covered-bond/SCRA tests → `_B31`; the CRR-labelled `test_crr_derivation_matches_tables` → `_CRR` (asserts **membership only**, and all six CRR institution RWs ∈ `_CRR` domain, so behaviour-preserving *and* now regime-honest); the both-regimes-unrated test keeps `_B31` (superset). **All asserted numeric values unchanged.** **LOC-ratchet coupling:** both items live in `risk_weights.py`, so they ship as ONE commit — the now-stale 2-line covered-bond comment compresses to 1 line, offsetting the added `resolved_pack` line so the module holds the monotone-decreasing `max_engine_module_loc` baseline (no bump). The resolved pack also threads into the defaulted-RW call so the non-production fallback path resolves the pack twice (pre-S10 count), not thrice; production passes the run pack → zero extra resolution. Pin: `sa_revised_risk_weight_overrides` added to `test_sa_risk_weight_features.py` (False, True). A **3-lens adversarial review** (wf_d9ceb33a: feature-semantics / alias-completeness / number-integrity) returned **pass / high confidence** on all three, zero blockers — its only nits were stale narrative in historical changelog/plan/state notes (non-load-bearing) and the fallback-path resolution count (since neutralised). Byte-identical on all 4 configs; full suite 7666 passed/2 skipped. **Remaining engine `config.is_*` reads after S10:** the S11 defers (`pipeline.py:258` FX-sync bootstrap, `attributes.py:551` Art. 123A retail, supporting-factors, post-model mortgage floor) + the `comparison.py:424/426` KEEP. |

| 2026-06-14 | Phase 5 sequencing decision (operator-confirmed): the bulk `data/tables/` → `packs/{common,crr,b31}` table-move (the plan's written S10 capstone) is **deferred to the S12 capstone area**; **S11 (config→RunConfig) runs next** | Dependency analysis: the table-move is **independent of S11** (disjoint value-homes — S11 moves *config*-resident values + deletes the regime facade; the move touches `data/tables/`→packs; neither needs the other) and its real **forcing-function is S12** (principles 2 & 9 + the S12 regime-containment arch_check / manifest / `rulepack diff` are what require the tables in the pack). Doing it before S11 front-loads the single largest, highest-parity-risk chunk (~6,289 LOC across 21 modules, 24 engine importers / 45 imports — each table must round-trip byte-identically through the `compile` Decimal→float boundary with S4d-style frame-equal pins) for **zero dependency benefit**; S11-first also clears the `config.is_*` facade so the engine-side table rewiring is unambiguous. A **scoping sub-decision** (every table vs. only regime-divergent ones — regime-invariant tables like `entity_class_mapping`/`output_floor`/`sa_ccr_factors` may belong in `packs/common.py` or stay put — plus which new `compile` primitives the remaining shapes need) is best made at S12-time when requirements are concrete. The move remains a genuine end-state requirement (not a skip), only re-sequenced. |

| 2026-06-14 | Phase 5 S11: `contracts/config.py` → RunConfig (regime as data); **S11 COMPLETE** — RunConfig now carries firm inputs + elections + a `regime_id`, ZERO regulatory values, every regulatory value resolved from the rulepack | Landed as a long chain of byte-identical (numerics-identical) slices, each gated on all 4 configs (crr_sa/crr_irb/b31_sa/b31_irb) vs `../rwa_phase5_parity/before`. **Gates → Features (S11a/b/d):** supporting-factors enable + multipliers (S11a `a8f7a30b`), Art. 123A retail two-path (S11b `1056ae32`), and the three capital-stack gates output_floor/equity_transitional/post_model_adjustments (S11d `69749311`, which also pack-threaded the aggregator `aggregate(*, pack=)` — a forced-single-stream protocol add — and converted the S11a from_config fallback). **The FX trap (S11c `7c511c21`):** the FX-derived monetary thresholds moved to the pack as FX-INVARIANT EUR bases (CRR) / native GBP (B31) under a `regulatory_thresholds` FormulaParams + a `regulatory_thresholds_fx_derived` Feature, with a NEW engine accessor `engine/thresholds.py::regulatory_threshold(pack, name, eur_gbp_rate)` applying `× rate` engine-side — `eur_gbp_rate` stays on RunConfig as a market input, not a regulatory value. **Mandatory blind-spot coverage:** the 10k×4 parity gate ships no fx_rates so it runs only at the default 0.8732 and is BLIND to the FX path — `test_thresholds_features.py` (7 fields × 4 rates × 2 regimes + a wiring-flip test) is that coverage. **Value migrations (S11e-v1/v2/v3):** equity transitional RW schedule → two b31 Schedules + None-before-first accessor (`bfcde683`); PMA mortgage RW floor → b31 ScalarParam with the `with_overrides` seam at the unit-test layer (`b1828a5f`); output-floor pcts → `output_floor_pct` Schedule + `output_floor_pct_full` scalar, with `skip_transitional` becoming an explicit election field (`c35209df`). **The carve (S11e-carve 1-6):** delete the engine-unread regulatory FIELDS from RunConfig one per commit — scaling_factor (`5dd6914a`), pd_floors+lgd_floors (`66a2829f`), supporting_factors (`1d459abd`), thresholds + simplify with_fx_rate to carry only eur_gbp_rate (`eae1440a`) — then delete the now-dead PDFloors/LGDFloors/SupportingFactors/RegulatoryThresholds CLASS defs + `_CRR_*_EUR` constants + 31 orphaned factory-tests in one wave (`6d75e513`), repointing every value pin (test_floor_pack_parity / test_thresholds_features / test_supporting_factors_features → hardcoded canonical dicts; conftest/loans/crr_params → inline EUR×rate) so no regulatory value lost its pin. **The pivotal decision — field, not pair:** the plan's `(RunConfig, regime_id)` PAIR was measured to force a ~1,100-site atomic, regime-aware refactor (845 `.crr()/.basel_3_1()` callers across 323 files + 319 `from_config`-fallback unit-test sites that would each need a regime-aware pack) — the "blast radius isolated to S11" assumption was false. The operator (re-confirmed with the numbers) switched to a `regime_id` FIELD, which keeps `RulepackV0.from_config` working and turns the whole carve into the independent byte-identical slices above. carve(5) (`08febc16`) renames the field `framework`(enum) → `regime_id`(str) and keeps `framework` as a derived @property so every enum-typed read site (pipeline logging, COREP/Pillar3, comparison, v0.from_config) stays byte-identical; only the 2 factories + 4 direct-construction test sites flip `framework=` → `regime_id=`. **PMA cleave (recon decision-6, operator-resolved):** PMA scalars → RunConfig elections; mortgage_rw_floor → pack scalar + override seam; `enabled` → Feature; Art. 92 2A applicable-entities (`is_entity_in_scope`) stays the firm-election half composed with the `output_floor` Feature gate. Full suite 7740 passed / 2 skipped; ruff + ty + arch_check clean throughout. **Still open (number-changing, NOT S11):** `ccr/sft_fccm.py:289` regime-insensitive SFT haircut (needs a B31 SFT fixture + PS1/26 determination + oracle). **Next:** S12 capstone area (bulk `data/tables/` → packs move + manifest + `rulepack diff` + regime-containment arch_check). |

| 2026-06-15 | Phase 5 S12: the bulk `data/tables/` → `packs/{common,crr,b31}` table-move (the deferred written-S10 capstone) + the audit/manifest/arch_check capstone; **S12 COMPLETE** | Two strands landed together. **(1) The table-move** that the S4–S9 Feature-gate pattern had deliberately left in `data/tables/`: the regulatory VALUES (SA-RW CQS tables, institution SCRA/ECRA, corporate/covered-bond, sovereign/PSE/RGLA/MDB, RE LTV bands + secured/junior scalars, specialised-lending slotting RWs, equity PD/LGD + SA/IRB-simple RW tables, SA/F-IRB CCF schedules, RE-split secured-LTV caps, failed-trade settlement multipliers, the whole SA-CCR factor/correlation/option-vol/CDO-delta/duration/maturity surface incl. the transitional add-on, the A-IRB floor + GCRA cap, the WWR LGD override) moved into the packs as cited entries, each a byte-identical sub-commit round-tripping through the `compile` Decimal→float boundary with frame-equal pins. The redundant F-IRB/CRM supervisory-LGD + overcollateralisation subsystem was retired (`6ebb9a5d`), the production-dead guarantee FX/restructuring haircut pair deleted (`a397e6cf`), the FCSM-scalar twin `crr_simple_method.py` deleted (`ef2645f6`), and the `crr↔b31` import cycle broken by relocating the guarantor SA-RW builders to `engine/` (`3a95d9e1`). The remaining `engine → data.tables` import surface was put under a shrink-only ratchet (`fe3041ca`). **(2) The audit capstone:** `rulebook/audit.py` — the pack manifest (id + content hash + full resolved-params-with-citations serializer) recorded into the run manifest + the `rulepack diff` CLI (`6ac17974`); PS1/26 pack citations cite at instrument level with sub-article in a note (`a267b4c4`); the watchfire pack-citation bridge — pack-data citations join the `@cites` index and `arch_check` gates them (`d5dfe168`); the **regime-containment** arch_check (**check 17**) banning `config.is_crr`/`config.is_basel_3_1` in `engine/` (`926df998`); and the pack-as-value-home register propagated across `CLAUDE.md` + the agent/command charters in the same change (`f768bf12`, per the do-not-do register requirement). **Scope note:** the written-S10 line's "shim getters / symbol-set parity" mechanic was not used — values moved into packs directly (no `data/tables/` shim layer survived), so the move's cleanup tail (emptying `data/tables/` to zero + the hard import ban) became S13 rather than part of S12. Byte-identical on all 4 configs every sub-slice. |
| 2026-06-16 | Phase 5 S13: finish the migration tail — empty `data/tables/` to zero, flip the import ratchet to a hard ban, delete the package; **S13 + Phase 5 COMPLETE** | The values S12 left in `data/tables/` were the table BUILDERS and a handful of int/date/string primitives. **Three new raw-value pack primitives** were designed (each: model shape + resolve accessor + manifest/content-hash handling + unit test): `IntParam` (S13-a, int-typed regulatory counts — no Decimal→float boundary, engine reads `.value`), `DateParam` (S13-g, e.g. `b31_effective_date`), `CategoryMap` (S13-d, cited str→str maps consumed Python-side via `replace_strict`). Using them, the int counts (SA-CCR MPOR, failed-trade band bounds, CRM liquidation periods Art. 224(2), OC/zero-haircut/3-property singletons), the entity-type→class and EU-domestic-currency and Annex-I OBS-product maps, and the `B31_EFFECTIVE_DATE`/retail-granularity singletons all moved to the packs (S13-a..h), with their builders relocated into `engine/` (`engine/ccf.py`, `engine/eu_sovereign.py`, `engine/entity_class_maps.py`). The three remaining table modules — the CRR and B31 SA risk-weight tables and the collateral-haircut module — were `git mv`'d into `engine/` as thin **pack-binding shims** that read their values back from the pack (`engine/sa/crr_risk_weight_tables.py`, `engine/sa/b31_risk_weight_tables.py`, `engine/crm/haircut_tables.py`; S13-i/j/k), the haircut move also resolving a pack↔`data/tables` value DUPLICATION (the `COLLATERAL_HAIRCUTS`/`FX_HAIRCUT` literals were independent duplicates of the pack `collateral_haircuts` DecisionTable / `fx_haircut` scalar — now derived from the pack). That drove the `engine_data_tables_import_edges` ratchet 104 → 0 across the workstream (104→97→92→89→83→73→72→70→67→35→7→0), at which point **check 12 flipped from a shrink-only ratchet to a zero-tolerance hard ban** (`check_no_engine_data_tables_imports`, no allowlist) and the now-empty `data/tables/` package was **deleted entirely** (S13-l) — `data/` now holds only `column_spec.py` + `schemas.py`. The dead/test-only `firb_lgd.py` was removed (its CRR_PD_FLOOR/K_SCALING values are cited pack literals; MATURITY_FLOOR/CAP are engine inline defaults). **Inline-literal residue (S13-m):** the one genuine drift hazard — the life-insurance Art. 232 RW map, a `{float:float}` dict that checks 5/6 miss and that had silently duplicated a hardcoded production when/then chain — was pack-homed as a common-pack `BandedTable` and the expression now builds its chain from the pack (m1); a forward-guard `check_no_numeric_tables_in_engine` was added to catch module-level float-rate tables re-entering the engine (m2). **Deliberately left in engine (recorded, per the S5d precedent):** the regime-invariant formula-embedded constants (Art. 162 1y/5y maturity bounds, Art. 238/239 0.25/5y mismatch params, the Art. 153 `CORRELATION_PARAMS`) — pack-homing them would be inconsistent with S5d's "constants stay engine literals (0.5y SFT M, 1÷365, 0.15+160×PD)" and a blanket inline-`pl.lit(<float>)` ban is not mechanically feasible. Byte-identical on all 4 configs every sub-slice; suite 7506 passed / 2 skipped. **Migration tail complete: `data/tables/` is gone; the engine reads every regulatory value from the rulepack via `resolve`.** |

*(Append further preserve-or-fix decisions here as phases land.)*
