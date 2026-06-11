# Target Architecture & Migration Plan

**Status:** Active — Phase 0 in progress
**Date:** 2026-06-11
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

### Phase 1 — Eager stage edges, plan-node budgets, one execution semantics

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

### Phase 2 — Dead-path deletion and protocol diet

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

### Phase 3 — Producer-sealed edge contracts and defensive-guard retirement

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

*(Append further preserve-or-fix decisions here as phases land.)*
