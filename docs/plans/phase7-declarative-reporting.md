# Phase 7 — Declarative Reporting on One Canonical Output Ledger

**Status:** ACTIVE — S0 (golden gate) + S1 (sealed-name retarget) MERGED (PR #395); execution resumes at S2.
**Date:** 2026-07-11
**Provenance:** Multi-agent investigation 2026-07-10 (5 mappers over Phase-6 residue / reporting layer /
output surface / reconciliation complexity / consumer duplication → 3 independent designs
[contract-first, cellspec-first, risk-first-minimalist] → 3-judge panel → synthesis →
adversarial fact-check, 5 corrections applied). Winner = **contract-first** (2 of 3 judges) with
recorded grafts from both runners-up.
**Supersedes:** `.claude/state/phase7-plan.md` from S2 onward (its S0/S1 record and locked harness
design remain the authority for what shipped).
**Parent:** `docs/plans/target-architecture-migration.md` → "Phase 7 — Declarative reporting" +
target principle 7.

---

## 0. The driving question

How do we guarantee **simplicity between the calculation outputs and the reporting outputs**?
Complexity has already crept in around pre- vs post-CRM views (guarantees with substitution
effects) in the UI reconciliation between the legacy calculator and this engine — each consumer
papers over the same gap differently.

**This plan's thesis: fix the output contract; reporting, reconciliation, and the UI then become
mechanical projections of it. CellSpec is a second-order consequence.** The canonical post-CRM
projection already exists — the aggregator computes it — but it sits on a frame that is dropped at
the API boundary, so every consumer re-derives it from raw columns and they disagree.

---

## 1. Phase 6 completion note (migration-doc correction)

**Phase 6 (`analysis/` layer) is COMPLETE — merged as PR #394 on 2026-06-17.** Per-goal audit:

| Goal | Verdict | Evidence |
|---|---|---|
| (a) comparison + recon out of `engine/`; registry out of `data/schemas.py` | **DELIVERED** | `engine/comparison.py`/`engine/reconciliation.py` deleted (S1 `7e707d6d`); registry → `analysis/recon_registry.py`, protocol → `analysis/reconciliation.py` (S2 `e8afbbf1`); arch_check check 12 bans engine→analysis; zero stale imports |
| (b) comparison → labelled two-run over rulepack-identified runs | **DELIVERED** | `RunSpec(config, label, rulepack)` at `analysis/comparison.py:85`; label gate replaces the regime gate (S3 `13031cdd`) |
| (c) CRR→B31 waterfall → one registered delta-attributor pairing | **DELIVERED** | `analysis/attribution.py` registry + `register_attributor("crr","b31",…)` self-registration (S4 `a9f59aa3`); scaling factor read from the pack |
| (d) transition = same pack at successive dates + floor-tail partial re-run | **PARTIAL — deviation recorded** | successive-dates loop delivered (S5a `ca128a77`); floor-tail partial re-run recorded **INFEASIBLE** (S5b `022dd30d`, `transition.py:58-69`): pre-floor IRB RWA is not date-invariant (Art. 162 effective maturity shortens), so only the SA floor benchmark is date-stable |

**Residue (audited 2026-07-10; none of it blocks Phase 7):**
- **R1 — stale doc imports:** `docs/api/engine.md:858,964` and
  `docs/framework-comparison/impact-analysis.md:29,79,161` still show
  `from rwa_calc.engine.comparison import …` (and `TransitionalScheduleRunner` now lives in
  `analysis/transition.py`). Fix as a docs item.
- **R2 — migration-doc self-contradiction:** status header + "Next = Phase 6" markers stale, and
  the §6 decision log has **zero Phase 6 rows** — the labelled-two-run semantics change and the
  floor-tail INFEASIBLE dead-end exist only in commit messages. Corrected alongside this plan.
- **R3 — `analysis` has no upward arch rule:** `IMPORT_DIRECTION_RULES` (arch_check check 12) has
  no `analysis` key, so an `analysis → api/ui` cycle would be undetected. Cheap close: add
  `"analysis": ("rwa_calc.api", "rwa_calc.ui")` (folded into §9 here).
- **R4 — analysis DTOs still in `contracts/bundles.py`:** `ComparisonBundle:958`,
  `TransitionalScheduleBundle:996`, `ReconciliationBundle:1067` — legal (downward import) but the
  target layout's `contracts/results.py` split remains outstanding; note for a later phase.
- **R5 — confirmed intended (not residue):** REC001–REC007 stay in `contracts/errors.py` (§3.3
  taxonomy stays central); the `RECON_*` output-domain tuples stay in `data/schemas.py:2805-2824`
  (consumed by `engine/aggregator/_collapse.py`, which may not import analysis).

**Since the merge (Phase 7 must build on the July surface, not the June snapshot):** 21 commits on
`analysis/` + `ui/views` delivered recon sign-off, calc-reuse (PR #434), and the post-guarantee
class tie-out workstream (`db9e0d7a`, `925c1bb3`, `9e1752d9`, `7cc1e000`, `5ee669f8`) — the last of
which moved the pre/post-CRM class semantics **into the sealed aggregator exit** as named, cited
columns. That is good news: the coherent semantic exists in one place; the residue is that
consumers still re-derive instead of reading it.

---

## 2. Starting-state recon (measured 2026-07-10, fact-checked)

### 2.1 The sealed edge already IS the reporting input — the projection is on the wrong frame

- The only per-row reporting input is `AggregatedResultBundle.results`, sealed as
  `aggregator_exit` (`contracts/bundles.py:88`, seal at `engine/aggregator/aggregator.py:383`).
  `EdgeContract.conform` strips undeclared columns (`contracts/edges.py:185-188`), so the declared
  set **is** the whole reporting/recon/UI input. Both generators read only
  `response.scan_results()` (`corep/generator.py:248`, `pillar3/generator.py:192`).
- **Keystone:** the canonical post-CRM projection (`reporting_exposure_class` / `reporting_ead` /
  `reporting_rw` / `reporting_approach`) already exists — computed in
  `engine/aggregator/_crm_reporting.py` on the **`post_crm_detailed` frame, which is dropped at
  the API boundary** and is absent from `AGGREGATOR_EXIT_EDGE` (only a docstring mention at
  `edges.py:1445`). `_summaries.py:45-150` consumes the `reporting_*` names behind
  `has_reporting = … in cols` presence-guards with raw-column fallbacks — a ladder of its own.
  COREP/Pillar 3/comparison/UI re-derive from raw columns instead.

### 2.2 Five class columns, four semantics — every consumer re-decides

Sealed class columns: `exposure_class` (origination + substitution routing),
`exposure_class_applied` (`edges.py:1459`, Art. 112 — + SME-managed-as-retail + defaulted; uniform
across a guaranteed exposure's legs; `aggregator.py:424`), `exposure_class_post_crm`
(`edges.py:1463`, Art. 235 — guaranteed slice under guarantor class; `aggregator.py:481`),
`pre_crm_exposure_class` (`edges.py:917`), `post_crm_exposure_class_guaranteed` (`edges.py:955`);
plus `approach`/`approach_applied`/`approach_post_crm` (`edges.py:1446`, `aggregator.py:515`) and
the dead `exposure_class_for_sa`.

Consumers diverge: COREP C07/C08.06 bucket on `exposure_class_applied`
(`generator.py:1522,2662`); COREP C02/C09 and all Pillar 3 class templates (CR4/CR5/CR6/CR9, 9
sites) bucket on raw `exposure_class`; reconciliation per-key attribution uses
`exposure_class_applied` (`recon_registry.py:61-80`) but its money allocation uses
`exposure_class_post_crm` (`reconciliation.py:924-933`); comparison groups on raw
`exposure_class` + `approach_applied`. **The same defaulted-SA exposure reports as "defaulted" in
COREP C07 and reconciliation but under its origination class in Pillar 3 CR4/CR5, the UI by-class
chart, and comparison.**

### 2.3 Guarantee substitution is physically a two-leg split, re-represented three times

- CRM physically splits each guaranteed exposure into `__G_<guarantor>` legs
  (`guaranteed_portion=EAD`, `is_guaranteed=True`) and `__REM` retained legs — plus Art. 234
  tranching sub-rows `__REM_FL`/`__REM_SEN` (`engine/crm/guarantees.py:459-533,719-790,1177`).
  The results frame is **per-leg for guaranteed rows, per-exposure otherwise**. On a `__G_` leg
  the SA blend collapses to pure guarantor RW (`engine/sa/rw_adjustments.py:251-269`) — the
  substituted values are already per-leg correct.
- The split is then re-derived three independent times: `_crm_reporting.py:126-274` re-splits
  each `__G_` leg again into reporting rows (~170 LOC); COREP `_compute_substitution_flows`
  re-derives outflow/inflow (`generator.py:3135`); reconciliation collapses legs back via
  `aggregate_to_key_grain` (`engine/aggregator/_collapse.py:45-96`).

### 2.4 Where this bites reconciliation and the UI (the operator's pain, diagnosed)

- **A — break attribution vs money allocation need different class bases.** Attribution keys on
  `exposure_class_applied` (uniform across legs, deterministic); allocation needs post-substitution
  `exposure_class_post_crm`. Two code paths, two columns (`925c1bb3` split them after `db9e0d7a`
  added the post-CRM basis).
- **B — the money allocation is a second, parallel recon engine.** `exposure_class_post_crm`
  differs across legs so it cannot survive the `.first()` collapse — `_build_class_allocation`
  (`reconciliation.py:814-899`) re-aggregates the **raw** frame, full-joined to a separately
  grouped legacy side.
- **C — the method dimension forks again, one level deeper.** `_class_allocation_by_method`
  pairs `exposure_class_post_crm` with `approach_post_crm` (`:936-946`); REC007 exists purely to
  warn about the basis trap (`9e1752d9`).
- **D — the guarantee component can only reconcile EAD, not the RWA benefit.** No persisted
  RWA-benefit figure survives to the per-exposure output (`recon_registry.py:162-184`); a
  guarantee-relief mismatch only shows up diffused across `risk_weight`/`rwa` deltas, never
  attributable to the guarantee (`7cc1e000` root cause was documentary column names being fiction).
- **E — the UI explains the basis fork in prose.** `templates/reconciliation.html:133-166` renders
  three class-dimensioned sections, each with a paragraph justifying its class basis. That prose
  is the papering-over, verbatim.

Recon correctness risks recorded in passing (not fixed here, tracked in §7):
`_our_class_col` hard-assumes the legacy extract is post-substitution (no basis toggle → phantom
offsetting deltas for an origination-basis legacy file, silent);
`RECON_HETEROGENEITY_COLUMNS = ("exposure_class","approach_applied")` (`data/schemas.py:2824`)
over-flags REC004 on every cross-approach guaranteed exposure (SA `__G_` leg + IRB `__REM` leg);
the headline tie-out (per-key frame) and class allocation (raw frame) have no cross-check.

### 2.5 Dead / duplicated surface

- **`exposure_class_for_sa` is dead** — declared `edges.py:805,1136`, produced
  `stages/classify/attributes.py:350`, zero read sites in `src/` (superseded by
  `exposure_class_applied`). Rides ~5 edges for nothing.
- **`substitute_rw` is produced-but-always-null** — `engine/crm/processor.py:1114` emits
  `pl.lit(None)…alias("substitute_rw")`; declared at `edges.py:953,1273`. The SA path writes
  substitution into `risk_weight`/`guarantor_rw` instead. Delete producer + declarations.
- `pre_crm_summary`/`post_crm_summary`/`post_crm_detailed` bundle fields have no production
  consumer beyond the opt-in audit cache (`engine/pipeline.py:481-505`); dropped at the API
  boundary (`api/formatters.py:105-176` persists only `results` + the three `summary_by_*`).
- **Duplication matrix D1–D10 (consumer-inventory, fact-checked):** approach→method bucket
  derived in ≥5 places on two different keys (D1); **161 `_pick`** (86 corep + 75 pillar3) +
  `recon_registry.our_columns` + `formatters._find_column_in_schema` +
  `_collapse.RECON_*_CANDIDATES` + `_summaries.py` `has_reporting` fallbacks — five candidate-
  ladder families (D2); three incompatible "post-CRM class" meanings (D3); six independent
  by-class and five by-approach group-bys on three different class columns (D4/D5); per-row
  `risk_weight` re-divided everywhere (D6); **three `floor_impact_rwa` re-folds**
  (`_summaries.py:242-314`, `transition.py:176-177`, `analysis/comparison.py:499-573` — note:
  COREP C02 reads `rwa_pre_floor`, a genuine pre-floor need, and `formatters._extract_floor_impact`
  reads `floor_binding`/`floor_add_on` from the separate `floor_impact` frame; neither is a re-fold
  of `floor_impact_rwa`) (D7); on/off-BS kernel-unified but with a reporting-side fallback
  (`kernel/filters.py:57-91`) (D8); the per-leg/per-exposure grain fork (D9); IRB sub-class
  re-derived via is_sme/FSE heuristics in COREP `_c02_00_irb_sub_agg:1227-1283` and Pillar 3 CR6
  (D10).

### 2.6 Regime branching, metadata, tests, goldens

- `framework == "BASEL_3_1"` / `is_b31` branches: **58 COREP + 14 Pillar 3** line-count (order
  ~70–77 by broader grep), plus ref-set sniffing (`"0171" in ref_set`, `generator.py:3437`;
  `"0031"/"0080"/"0107"/"0110" in column_refs`) and Pillar 3's `_CR7_HANDLERS_B31/_CRR` dispatch
  tables. **Rulepack reporting metadata today: essentially none** — generators are pack-blind
  (`generate_from_lazyframe(results, framework=str)`); the one reporting `Feature`
  (`b31_exposure_subclass_reporting_applies`) is consumed by the aggregator, not the generators.
- `test_corep.py` 9,525 LOC / ~703 tests (xdist `loadfile` straggler); `test_pillar3.py` 1,957.
  CCR reporting already split out (`test_corep_ccr.py` 1,115, `test_pillar3_ccr.py` 1,062) and
  newer tests live under `tests/unit/reporting/` — the split direction has begun. Many
  `test_corep.py` cell tests inject columns the seal strips — the unit estate is **not**
  production-grounded; the golden gate is.
- **Golden gate (S0):** `tests/acceptance/reporting/test_reporting_golden.py` runs the rich
  `tests/fixtures/reporting_portfolio.py` through the real pipeline; compares **structure-exact +
  Float64 rtol=1e-9/atol=1e-6** ("byte-identical" was rejected at S0 — Polars multi-threaded
  group-by float sums are not process-deterministic, the recorded Phase-2 finding). Estate
  provenance (corrected): **64 goldens at S0 (`c97c5e9c`) → 93 at S1 (`b41aba70`, un-emptied
  C08.02/03/05 + CR6/CR9 + equity) → 95 at `5ee669f8`** (defaulted + corporate_sme C07 splits).
- **Gate gap (fact-check finding): the post-scoping template families have NO goldens** —
  zero `of_07`/`of_08`/`c34_*`/`ccr*` NDJSON files exist or ever existed; the golden test doesn't
  reference them. The CCR templates (C34.01/02/04/08, CCR1/2/3/8 — `f776f67d`, `90d4a789`) are
  covered only by synthetic unit tests. Their strangler slices need goldens authored first (§5
  S8-pre) or a recorded scope-out.

---

## 3. Target design

### 3.1 One canonical output ledger: the sealed per-leg frame, named

**Grain A — the per-leg reporting ledger = `AGGREGATOR_EXIT_EDGE.results` itself, extended with a
first-class reporting projection.** The results frame *already is* the two-leg substitution ledger
(physical `__G_`/`__REM` legs). We do **not** introduce a new frame at a new grain — we *name* the
ledger already present. Four of the six class/approach columns are pure aliases of already-sealed
columns — **rename-and-consolidate, not new math** (minimalist graft, fact-checked):

| Sealed column (new) | Semantic | Source | New? |
|---|---|---|---|
| `reporting_class` | post-substitution class the RWA is bucketed under (Art. 235: guarantor class on guaranteed legs; applied origin class otherwise) | `exposure_class_post_crm` | alias |
| `reporting_class_origin` | obligor applied class (origination + SME-managed-as-retail + defaulted, Art. 112/123); uniform across a guaranteed exposure's legs | `exposure_class_applied` | alias |
| `reporting_approach` | post-substitution approach | `approach_post_crm` | alias |
| `reporting_approach_origin` | pre-substitution approach | `approach_applied` | alias |
| `reporting_method` | SA / FIRB / AIRB / SLOTTING / EQUITY label | `_summaries.py::method_label_expr`, materialised | derived |
| `reporting_leg_role` ∈ {`whole`,`guaranteed`,`retained`} | first-class marker of the physical guarantee split — replaces `is_guaranteed` + suffix sniffing. `retained` covers `__REM` and the Art. 234 tranche sub-rows `__REM_FL`/`__REM_SEN` (tranche identity stays on the existing reference columns; S2 records whether a `leg_detail` column is warranted) | derived from `is_guaranteed` + ref suffix | **new (names an existing fact)** |
| `reporting_on_balance_sheet` | on/off-BS declared at source (kills the `kernel/filters.py:57-91` fallback, D8) | `bs_type` at aggregator | derived |
| `reporting_subclass` | authoritative FIRB/AIRB + SME/FSE/property split (kills D10 re-derivations) | `exposure_subclass` | alias |
| `reporting_ead` | per-leg post-CRM EAD | `ead_final` | alias |
| `reporting_rw` | per-leg post-CRM risk weight | `risk_weight` | alias |

**`reporting_rwa` (per-row POST-FLOOR RWA) is deliberately NOT in this foundation.** The output
floor is a portfolio-level `max`; a per-row post-floor RWA is an allocation *convention*, not a
relabel. Ring-fenced to its own number-changing slice (S5) with oracle sign-off.

**Grain B — the three persisted summaries re-founded as pure group-bys of Grain A.**
`summary_by_class`/`summary_by_approach`/`summary_by_class_method` become group-bys of the sealed
ledger on `reporting_class`/`reporting_approach`/`reporting_method` and are established as the
**only** by-class/by-approach source. `_summaries.py` already consumes the `reporting_*` names
(today from the dropped frame, behind presence-guards) — this is a source relocation plus
guard deletion, not new logic. COREP C02.00, Pillar 3 OV1, `api/formatters`, comparison, and
transition retarget to these frames, collapsing D4/D5/D6.

**Substitution becomes a zero-re-derivation ledger.** Guaranteed exposure = one `retained` leg
(`reporting_class = reporting_class_origin =` obligor class, borrower RW) + one or more
`guaranteed` legs (`reporting_class_origin =` obligor, `reporting_class =` guarantor). The
movement reconstructs by grouping: outflow = Σ`reporting_ead` of `guaranteed` legs by
`reporting_class_origin`; inflow = same by `reporting_class`. `_compute_substitution_flows`, the
`_crm_reporting.py` re-split, and every consumer's class re-pick disappear.

**Out-of-frame inputs travel in a typed `ReportingContext`** side-car: `output_floor_summary`,
`output_floor_config`, `Pillar3CapitalRatioOverrides`, `previous_period_results`, the resolved
pack reporting metadata, and the C02.00 portfolio pre-pass. This closes the "sealed exit only"
incompleteness.

**The seam:** sealed per-leg ledger + 3 re-founded summaries + typed `ReportingContext`.
Reporting = filter+aggregate over the ledger; recon = `reporting_class_origin` (attribution) +
`reporting_class` (allocation) as single named literals; UI = project
`reporting_class`/`reporting_method` with a `reporting_leg_role` toggle that **is** the
pre/post-CRM view. The three prose paragraphs in `reconciliation.html` reduce to a basis label.

### 3.2 CellSpec: sized to the measured taxonomy — no expression DSL

The measured cell-semantics taxonomy has **14 kinds: 6 fit filter+aggregate; the rest are
policies or escapes.** The executor gets exactly **two escapes**.

```python
@dataclass(frozen=True)
class RowPredicate:                # generalises CR9ClassSpec (pillar3/templates.py:65)
    reporting_classes: tuple[str, ...] = ()
    method: str | None = None                       # reporting_method
    bs: Literal["on", "off"] | None = None          # reporting_on_balance_sheet
    leg_role: Literal["whole", "guaranteed", "retained"] | None = None
    is_defaulted: bool | None = None
    subclass: str | None = None                     # reporting_subclass
    pd_band: Band | None = None
    rw_band: Band | None = None

@dataclass(frozen=True)
class CellSpec:
    ref: str                                        # 4-digit column ref
    binding: ValueBinding
    empty_cell: Literal["zero", "null"] = "zero"    # per-cell policy — NEVER unified
    sign: Literal["positive", "negated"] = "positive"
    finite_only: bool = False                       # non-finite -> blank
```

Value-binding verbs → taxonomy kinds: `Sum(col)` (kind 1, dominant); `WeightedAvg(value_col,
weight="reporting_ead")` (kind 2 — one reconciled kernel primitive replacing the drifted copies);
`Mean(col)` (kind 3 — C08.05 avg-PD is deliberately NOT EAD-weighted, `generator.py:3989`);
`Ratio(num, den, scale)` (kind 4); `Count(col, distinct)` (kind 5); `Lookup(kernel_fn, keys)`
(kind 6 — C08.06 slotting RW `_c08_06_risk_weight_value:4319`; the spec references a typed kernel
fn, never inlines the table); `Formula(refs, fn)` (kind 7, the ONE intra-row escape — C07
`0040=0010−0030−0035:3277`, the `0110` waterfall `:3390`, `0150=max(0,0110−0130):3409`, ~5 cells
total); `SideContext(key)` / `PriorPeriod(binding)` / `Derived(col, const)` (kinds 8/11/12 —
CR8/C08.04 opening-RWEA carry-forward, the OV1 floor rows 26/27 handling
(`_OV1_FLOOR_NO_SHIM_REFS`, `pillar3/generator.py:1511`), capital overrides, OV1 col-c
`= a×0.08`).

- **Kind 9 (stateful C02.00 roll-up**, `_c02_00_aggregate_by_approach:1145-1201`) is a typed
  **pre-pass** kernel fn whose output enters via `ReportingContext`; C02.00 keeps a thin shell.
- **Kind 10 (substitution flows) is demoted to kind 1** by the ledger — two `Sum` bindings on
  different group keys.
- **Kinds 13/14 (sign / finite-only / empty-cell) are per-cell policy fields, not kinds.**

**One executor** (`reporting/cellspec.py`): for each row × column, compile
`RowPredicate → pl.Expr`, filter once, evaluate the binding, apply policies. `TemplateSpec` pairs
the existing frozen `COREPRow`/`COREPColumn`/`RowSection` / `P3Row`/`P3Column` layout constants
(already ~90% declarative and golden-asserted) with a `dict[col_ref, CellSpec]` — adding only the
missing value-binding layer, keyed on the same refs.

**"The specs define the edge"** (cellspec-first graft — the strongest guard against `_pick`
regrowth): enumerating every binding's required source column yields the exact sealed-column set
the aggregator must emit. A binding needing an absent column is a **recorded
add-to-contract-vs-accept-empty decision — never a fallback ladder.** This backs the §9 ban.

**Variant selection from rulepack metadata:** a cited `ReportingTemplateSet` RuleEntry, resolved
via `resolve(regime, date).reporting()`, selects the CRR vs B31 `TemplateSpec` (which
refs/rows/columns apply) and carries `reporting_basis`/`institution_type` plus the P7.5/P7.6
materiality/roll-out flags currently pinned in template constants. The executor is pack-blind at
cell level; metadata picks the spec. Retires the ~58+14 framework string-tests and the ref-set
sniffing.

**Strangler discipline — the dispatch-router** (cellspec-first graft): the generator keeps a
dispatch routing migrated templates through the executor and unmigrated ones through the legacy
path until the final convergence slice. Suite green every slice, independent of order.

### 3.3 Pre/post-CRM substitution — the representation, spelled out

**Representation = the declared two-leg ledger; NOT collapsed to one applied class.** COREP
**C 07.00** (Reg 2021/451 Annex I) is the referee: it reports `Original exposure` under the
**origination** class, a *"Substitution of the exposure due to CRM"* block with `(-) Outflows` /
`(+) Inflows`, then exposure value / RWEA on the **substituted** basis. Both endpoints of the
money movement are mandatory template columns — a single per-exposure applied class cannot
express them. The engine already computes this physically; the fix is a declaration.

**C07 attribution rule (recorded):** the `Original exposure` measure (col 0010) is attributed
**once** to the origin under `reporting_class_origin` (legs `whole`/`retained` + the guaranteed
leg's origin), never double-counted across legs — an explicit guard on the drawn/undrawn
double-count hazard.

---

## 4. Standing invariants (every slice)

1. **Golden gate:** every slice gated by `test_reporting_golden.py` — structure-exact + Float64
   rtol=1e-9/atol=1e-6 across the 95 NDJSON goldens. Do not attempt bit-exact (Polars float-sum
   nondeterminism, recorded Phase-2 decision).
2. **No silent regeneration:** `REGEN_REPORTING_GOLDENS=1` only with a recorded preserve-or-fix
   decision per changed cell; the `crr`/`basel31` skills + `tests/oracle/` are the referee.
   Bulk-regenerate-to-green is banned and a reviewer criterion.
3. **Full suite green every slice** via the dispatch-router; each slice a shippable master PR.
4. **Reporting input = the sealed aggregator exit + typed `ReportingContext`.** No consumer reads
   an unsealed frame.
5. **Specs define the edge:** no new multi-candidate column ladder anywhere in
   `reporting/`/`analysis/`; absent-column needs are recorded decisions.
6. **Number-neutral slices assert every existing cell unchanged** (modulo new columns);
   number-changing slices carry a §6 decision.
7. **Forced single-stream** for slices touching `contracts/edges.py`, `engine/aggregator/*`,
   `contracts/bundles.py`, or `analysis/reconciliation.py`.
8. **`summary_by_*` sequencing trap (hard):** do NOT re-point any consumer at the cached
   `summary_by_*` frames before their keying is explicit against
   `reporting_class`/`reporting_approach` — they key post-guarantee while api cards/COREP today
   key pre-guarantee (`approach_applied`); re-pointing early silently flips the split.
9. **Each strangler slice names the D1–D10 duplication site it deletes** and proves it dead —
   reviewer criterion.

---

## 5. Execution slices

*(S0 golden gate `c97c5e9c` and S1 sealed-name retarget `b41aba70` are merged; numbering
continues.)*

### S2 — Seal the canonical projection on the edge (NUMBER-NEUTRAL, single-stream) — **DONE 2026-07-11**

*As delivered:* `_add_reporting_projection` (`engine/aggregator/aggregator.py`), applied to
`combined` after the residual multiplier and output floor; 10 columns declared on
`AGGREGATOR_EXIT_EDGE` with citations + null-semantics. One recorded deviation:
`reporting_on_balance_sheet` derives from `exposure_type` (loan → on;
facility/contingent → off; else null), NOT from `bs_type` — `bs_type` is stripped upstream of
the branch seals and never reaches the aggregator, and the `exposure_type` rule is what the
reporting kernel actually applies in production today, so the exposure-type derivation is the
behaviour-preserving one. Art. 234 tranche legs (`__REM_FL`/`__REM_SEN`) map to `retained`
(tranche identity stays on the reference columns; no `leg_detail` column warranted yet). Gate:
7 new pins in `tests/unit/test_aggregator.py::TestReportingProjection`; 95 goldens
structure-identical; full suite 8,343 passed; arch_check + ruff green; citation snapshot
regenerated (137 fns).
- **Scope:** add the §3.1 projection columns *except* `reporting_rwa` — the four aliases plus
  `reporting_method`, `reporting_leg_role`, `reporting_on_balance_sheet`, `reporting_subclass`,
  `reporting_ead`, `reporting_rw`. Computed once at the aggregator (extending the existing
  `_add_exposure_class_applied`/`_add_post_crm_reporting_class`/`_add_post_crm_reporting_approach`
  cluster, `aggregator.py:147-149,424-539`), declared on `AGGREGATOR_EXIT_EDGE`. **No consumer
  switched yet.** `@cites` Art. 235 on `reporting_class`/`reporting_leg_role`, Art. 112 on
  `reporting_class_origin`. Record the leg-role enum decision (tranche sub-rows → `retained`).
- **Gate:** full suite + 95 goldens structure-identical; new columns present; zero cell movement.

### S3 — Delete the dead surface (NUMBER-NEUTRAL, single-stream) — **DONE 2026-07-11**

*As delivered:* `exposure_class_for_sa` producer deleted from
`stages/classify/attributes.py` + both edge-dict literals (`_classifier_added_columns`,
`_calc_output_common_columns` — covering all five edges); `substitute_rw` null-literal
producer deleted from `crm/processor.py` + both declarations. Recorded audit results: the
"zero readers" finding held for `src/`; five TEST files read the dead column and were
repointed — the two SL/defaulted-priority classifier tests deleted (semantics pinned at the
aggregator by `test_exposure_class_applied.py` and on the live `exposure_class_sa`), two
redundant defaulted asserts dropped (`is_defaulted` asserted alongside), the P2.14
acceptance asserts repointed to `exposure_class` (the SA branch frame — semantically
identical for non-defaulted, non-SL rows), and the fictional input column stripped from
`test_crr_crm.py` fixtures. Gate: goldens structure-identical; full suite green.
- **Scope:** remove `exposure_class_for_sa` (edges `805,1136` + `attributes.py:350` producer;
  0 readers verified). Remove `substitute_rw` — **including its null-literal producer at
  `engine/crm/processor.py:1114`** — and its declarations (`edges.py:953,1273`).
- **Gate:** full suite + goldens unchanged; recorded deletion note per column.

### S4 — Re-found the summaries on the ledger; delete the re-split; collapse the recon ladders (NUMBER-CHANGING, single-stream) — **DONE 2026-07-11**

*As delivered:* `_summaries.py` rewritten as pure group-bys of the sealed ledger
(`reporting_class` / `reporting_approach` / `reporting_method`, dual-path presence-guards
deleted); `_crm_reporting.py` deleted entirely (`post_crm_approach_expr` relocated into the
aggregator's projection cluster; the three dead view schemas deleted from `_schemas.py`);
`pre_crm_summary`/`post_crm_detailed`/`post_crm_summary` bundle fields + audit-cache entries
deleted; `_detect_non_finite_errors` drops its second-frame scan (the ledger's
`reporting_rw`/`reporting_ead` are aliases — covered by construction); recon
`_our_class_col`/`_our_method_col` deleted (allocation reads `reporting_class` +
`reporting_approach` literals) and all 12 `recon_registry.our_columns` ladders collapsed to
single sealed names (dead rungs killed: `sa_cqs`, `ccf_applied`, `irb_m`, `final_ead`, `ead`,
`risk_weight_effective`, `sme_supporting_factor`, `irb_expected_loss`, `final_rwa`, `rwa`,
`lgd_input`, `lgd`, `pd`). Recorded F1 sub-decisions (before/after diff on the reporting
portfolio showed exactly these and nothing else):

- **F1-a (FIX):** defaulted / SME-managed-as-retail rows re-bucket to their applied class —
  the `defaulted` summary bucket exists for the first time (matches COREP C07's defaulted
  sheet keying since `5ee669f8`).
- **F1-b (FIX):** `total_rwa` = Σ sealed `rwa_final` (post-floor when the floor ran), replacing
  the `reporting_ead × reporting_rw` reconstruction — which **overstated CRR totals by the
  supporting-factor relief** (measured +2,703,419 on the reporting portfolio, ~1.9%) and
  mispriced IRB-guaranteed legs at the flat `guarantor_rw` instead of the leg's
  parameter-substituted RW. All six summary frames now tie exactly to the portfolio
  `rwa_final` under both regimes (pinned). Implementation note: `rwa_final` is ALREADY
  post-floor (`_floor.py` rewrites it; adding `floor_impact_rwa` double-counts — caught by
  P1.130 during the slice).
- **F1-c (FIX):** `exposure_count` counts physical ledger legs — the detailed view's zero-EAD
  phantom "unguaranteed portion" row per guaranteed leg is gone.
- **Test-estate note:** the `partially_guaranteed_irb_results` and P1.146 fixtures carried the
  fictional single-row-both-portions shape and were re-baselined onto the physical
  `__G_`/`__REM` legs (all pinned constants held); `tests/fixtures/recon_ledger.py::
  with_reporting_ledger` mirrors the aggregator's projection onto hand-rolled recon test
  frames; one UI test pinned the fictional `sa_cqs` rung and now supplies `external_cqs`.
- **Scope:** point `summary_by_class`/`summary_by_approach`/`summary_by_class_method` at
  `reporting_class`/`reporting_approach`/`reporting_method`; delete the `_summaries.py`
  `has_reporting` presence-guard dual paths; establish the summaries as the only by-class/approach
  source. **Delete** `_crm_reporting.py::generate_post_crm_detailed`/`generate_post_crm_summary`
  (~170 LOC) and the `pre_crm_summary`/`post_crm_summary`/`post_crm_detailed` bundle fields
  (verify dead beyond the audit cache first). Collapse `reconciliation._our_class_col` /
  `_our_method_col` (`reconciliation.py:924-946`) and `recon_registry.our_columns` preference
  ladders to single literals (`reporting_class_origin` per-key; `reporting_class` +
  `reporting_approach` allocation); `_build_class_allocation` keeps its raw-frame aggregation but
  reads named columns.
- **Number-changing:** YES — `summary_by_class` basis shifts for unguaranteed defaulted /
  SME-managed-as-retail rows (F1). Kills the recon workarounds
  (`db9e0d7a`/`925c1bb3`/`9e1752d9`/`7cc1e000` become reads of named columns).
- **Gate:** recon acceptance tie-outs + goldens + full suite; every golden move a recorded
  decision with oracle sign-off.

### S5 — Per-row post-floor `reporting_rwa` (NUMBER-CHANGING, ring-fenced) — **RESOLVED AS MOOT 2026-07-11 (recorded)**

*S4 established that the premise was wrong:* the authoritative per-row post-floor RWA
**already exists** — `apply_floor_with_impact` rewrites `rwa_final` in place to the post-floor
value (`_floor.py:256`; the pre-floor snapshot moves to `rwa_pre_floor`, the add-on to
`floor_impact_rwa`). No new sealed column, no allocation-convention decision, and no F2 are
needed: the summaries read the sealed `rwa_final` since S4, and the two remaining
`floor_impact_rwa` read sites are legitimate **attribution** uses of the add-on, not re-folds —
`analysis/transition.py:176-177` reports per-year `total_floor_impact` and
`analysis/comparison.py:499-530` joins the B31 add-on for the waterfall's floor driver. Both
stay. F2 is closed with this recording; execution continues at S6.
- **Scope:** one authoritative per-row post-floor RWA on the edge. Retarget the **three**
  `floor_impact_rwa` re-fold sites — `_summaries.py:242-314`, `transition.py:176-177`,
  `analysis/comparison.py:499-573` — each as its own gated diff. **Explicitly NOT in scope
  (fact-checked):** COREP C02's `rwa_pre_floor` comparison (genuinely needs the pre-floor value)
  and `formatters._extract_floor_impact` (reads `floor_binding`/`floor_add_on` from the separate
  `floor_impact` frame — a different concept, revisited only if `floor_impact` itself is
  re-founded).
- **Number-changing:** YES — the floor is a portfolio-level max; the per-row allocation is a
  convention (F2): preserve portfolio totals exactly; oracle sign-off on the convention.
- **Gate:** portfolio-total parity + per-row goldens with recorded decision; floor acceptance
  suite.

### S6 — Rulepack reporting metadata + `ReportingContext` (NUMBER-NEUTRAL, single-stream)
- **Scope:** new cited `ReportingTemplateSet` RuleEntry (+ content-hash serialiser branch — the
  `_value_repr` raises on unknown shapes) + `resolve().reporting()` accessor + cited pack entries
  (per-regime template-set membership, variant/ref-set, `reporting_basis`/`institution_type`,
  P7.5/P7.6 Art. 150(1A)/147B flags). Typed `ReportingContext` carrying the metadata view + the
  out-of-frame inputs. Lands before any template is touched. Confirm check-17 coverage for
  `reporting/`.
- **Gate:** full suite; goldens unchanged.

### S7 — CellSpec model + one executor + kernel growth + CR8 pilot (NUMBER-NEUTRAL)
- **Scope:** `reporting/cellspec.py` (§3.2); grow `reporting/kernel/` with the reconciled
  `WeightedAvg`/`Ratio`/`Count`/`Lookup`/`_make_row`/`_build_df` primitives (deduping drifted
  copies); establish the dispatch-router; migrate exactly one stateless pilot — **Pillar 3 CR8**.
- **Gate:** CR8 golden structure-identical through the executor; full suite.

### S8-pre — Goldens for the post-scoping families (PRE-REQUISITE, recorded decision)
- **Scope (fact-check finding):** `OF07`/`OF08`/`C34.01/02/04/08` (COREP) and `CCR1/2/3/8`
  (Pillar 3) have **no goldens** — author them first by extending
  `tests/fixtures/reporting_portfolio.py` with the derivative/SFT trades those templates need,
  **or** record a scope-out (they stay on the legacy path + synthetic unit tests
  `test_corep_ccr.py`/`test_pillar3_ccr.py` until a fixture exists). Do not strangle an
  un-goldened template.
- **Gate:** regeneration-is-clean on the new goldens; recorded decision either way.

### S8..S(n−1) — Strangler per template family (golden-gated; Pillar 3 first, C02.00 last)
Order: **Pillar 3** OV1 → CR4/CR5 → CR6/CR6a/CR7/CR7a → CR9/CR9.1/CR10 → CMS1/2 → CCR1/2/3/8
(post S8-pre); then **COREP** C07 + skeleton-sharing C08.01/02/03/05 → C08.04/06/07 → C09.01/02 →
OF02.01 → OF07/OF08/C34.x (post S8-pre) → **C02.00 LAST** (portfolio pre-pass via
`ReportingContext`).
- **Per slice:** one `reporting/<pkg>/<template>.py` `TemplateSpec`; route through the router;
  delete that template's `_pick` ladders, framework tests + ref-set sniffing, bespoke
  `_compute_*_values` body; split its `test_corep.py`/`test_pillar3.py` class into a co-located
  per-template file (the `test_corep_ccr.py` / `tests/unit/reporting/` precedent).
- **Number-neutral by construction EXCEPT the flagged class-key retargets** (F3/F4/F5), each with
  its own recorded decision + oracle sign-off.
- **Gate per slice:** that template's golden structure-identical + full suite.

### Sn — Capstone: test split + consumer convergence + arch (NUMBER-NEUTRAL except F5 if pending)
- **Scope:** confirm `test_corep.py` fully split (~16 per-template files; kills the xdist
  straggler). Converge the remaining consumers on the ledger + summaries:
  `api/formatters.py` (delete `_SA/_IRB/_SLOTTING_APPROACHES`, `_approach_sum`,
  `_find_column_in_schema`), `analysis/comparison.py` (`_IRB_APPROACHES:190`,
  `_compute_summary`), `_collapse.RECON_*_CANDIDATES` — respecting invariant 8. Retire the two
  "Retired by Phase 7" arch_check inversions (`arch_check.py:413-414`). Add the §9 ratchets.
  Update `docs/specifications/` + changelog + `/next-items` Step-4d reviewer criteria in the same
  change.
- **Gate:** full suite; ratchets green.

---

## 6. Flagged number-changing items (each needs a recorded preserve-or-fix decision)

| ID | Slice | What moves | Recommended decision |
|---|---|---|---|
| **F1** | S4 | `summary_by_class` basis shift for unguaranteed defaulted / SME-managed-as-retail rows (raw → applied class) | **FIX** — align summaries to the applied/post-CRM semantic; oracle sign-off per diff |
| **F2** | S5 | Per-row post-floor `reporting_rwa` allocation of the portfolio floor add-on | **PRESERVE** portfolio totals exactly; **FIX** the per-row convention, ring-fenced, oracle-signed |
| **F3** | S8.. | Pillar 3 CR4/CR5/CR6/CR9 retarget raw `exposure_class` → `reporting_class` (SME/defaulted rows change sheet) | **FIX** — Pillar III post-CRM disclosure reports the applied/substituted class; per-template oracle sign-off |
| **F4** | S8.. | COREP C07 origin vs post-CRM column consistency (already on `exposure_class_applied` since `5ee669f8`) | **PRESERVE** C07.00 origination keying + outflow/inflow; confirm the split reproduces existing cells |
| **F5** | S8../Sn | UI by-class chart retarget raw `exposure_class` → `reporting_class` | **FIX** — UI matches COREP/Pillar 3 exactly; closes the operator-flagged UI/recon gap |
| **F6** | follow-ups | The S1-DEFERRED stripped/never-produced reads (`ccf_applied`, `sa_cqs`, `scra/gcra_provision_amount`, `ead_pre_ccf`, `exposure_post_crm`, …) — permanently-null cells today | **Per-column add-to-contract-vs-accept-empty decision**, never a blanket seal |
| **F7** | own slices | P2.27 (OF08.01 col 0275 SA-equivalent EAD), P3.3/P3.6 (pre-multiplier RW, equity transitional end-state RW, AIRB RE 4-way split) — need new engine columns | Own recorded-decision slices, not silent generator one-liners |
| **F8** | candidate | **Persisted guarantee RWA benefit** (`rwa_benefit` per guaranteed leg = leg RWA at borrower RW − at guarantor RW) — recon today reconciles guarantee EAD only; relief mismatches diffuse into `risk_weight` deltas, unattributable | Additive column, but new semantics — needs an Art. 235 definition decision + oracle scenario before sealing; schedule after S4 once the ledger is consumed |

---

## 7. Recorded-decision candidates

### G1 — The grain question (the central decision)
**Recommendation: adopt the per-leg frame as the canonical two-leg substitution ledger; do NOT
collapse to one applied class; do NOT introduce a new normalised frame — name the ledger already
physically present.** (Unanimous across the three designs and three judges; fact-checked.)
- COREP C 07.00 mandates both endpoints + outflow/inflow — a single label loses one endpoint.
- The engine already computes the ledger physically (`__G_`/`__REM`, `guarantees.py:459-533`) —
  a declaration, not new computation.
- Reconciliation already needs both bases (attribution vs allocation) — the two-column ledger
  serves both without re-picking.
- The UI's pre/post-CRM complexity **is** the undeclared ledger.
Consumer-facing surface = `reporting_class`, `reporting_class_origin`, `reporting_leg_role`,
`reporting_method`, the approach twin; everything else stays aggregator-internal or is deleted.

### G2 — Others
- **`reporting_rwa` floor-allocation convention** (F2) — record portfolio-preserving convention +
  oracle sign-off.
- **Summary re-founding basis** (F1) — record applied/post-CRM as authoritative.
- **Empty-cell policy stays per-cell** — COREP 0.0 vs Pillar 3 null is a `CellSpec.empty_cell`
  field; record "not unified".
- **Legacy-extract basis toggle (recon):** `_our_class_col` hard-assumes the legacy file is
  post-substitution; a firm reporting origination-basis sees phantom offsetting allocation deltas
  with no warning. Decide: a `legacy_class_basis` mapping setting (origination | substituted)
  selecting which ledger column the allocation compares against + a REC-code warning when unset.
- **REC004 heterogeneity refinement:** `RECON_HETEROGENEITY_COLUMNS` includes `approach_applied`,
  which legitimately differs across `__G_`/`__REM` legs of cross-approach guaranteed exposures —
  exclude `guaranteed` legs from the heterogeneity check or key it on
  `reporting_approach_origin`.
- **Tie-out cross-check:** headline totals (per-key frame) vs class allocation (raw frame) have
  no cross-check; add one assertion frame once both read the ledger.
- **`exposure_class_for_sa` / `substitute_rw` deletions** (S3) — record the 0-reader /
  null-producer audit results.
- **S8-pre scope decision** — goldens-first vs scope-out for the CCR/C34/OF07/OF08 families.

---

## 8. What NOT to build

1. **No general expression DSL.** Two escapes (`Formula` ~5 cells, `SideContext`); anything more
   is a typed kernel fn the spec references.
2. **Don't force C02.00's stateful roll-up or the `_irb_*_split` bucketing through pure CellSpec**
   — typed pre-pass kernel fns.
3. **Don't unify COREP-0.0 vs Pillar 3-null empty cells** — per-cell policy or values change.
4. **Don't chase byte-identical goldens** — structure-exact + rtol is the recorded decision.
5. **Don't seal every column the generators read** — the stripped/never-produced reads are
   permanently-null cells (F6), each a per-column call.
6. **Don't add a second per-exposure grain or a new normalised two-leg frame** — the physical
   split IS the ledger; `aggregate_to_key_grain` already collapses for recon.
7. **Don't invent a CellSpec kind for substitution flows** — the ledger demotes it to `Sum`.
8. **Don't re-point consumers at the cached `summary_by_*` frames before their keying is
   explicit** (invariant 8).
9. **Don't blind-delete the remaining `_pick` ladders** — S1 removed the pure-dead rungs; the
   rest need per-column decisions.
10. **No speculative reporting-metadata packs ahead of a real instrument; no long-lived branch;
    no v2 package.**
11. **Don't fold P2.27 / P3.3 / P3.6 / F8 in silently** — new engine columns need their own
    recorded-decision slices.
12. **Don't strangle an un-goldened template** (S8-pre) — a green synthetic unit suite is not a
    correctness oracle here.

---

## 9. arch_check / ratchet additions at phase exit

- **`max_reporting_module_loc` ratchet** — `reporting/` is currently un-ratcheted
  (`generator.py` at 5,178 LOC unbounded); mirror `max_engine_module_loc` in
  `RATCHET_MAX_METRICS` + `scripts/arch_metrics.json`; enforces one-module-per-template.
- **Multi-candidate column-ladder ban in `reporting/` + `analysis/`** — census of `_pick(` with
  >2 args, `our_columns`, `_find_column_in_schema`, `RECON_*_CANDIDATES`, and the `_summaries.py`
  presence-guard duals; ratcheted to 0.
- **Reporting class/approach read-allowlist** (post-retarget) — `reporting/`+`analysis/` may read
  only the `reporting_*` family; raw `exposure_class`/`approach_applied` reads banned outside the
  aggregator.
- **Extend check-17 (regime-bool ban) to `reporting/`** — no `framework ==`/`is_b31`
  branching or ref-set sniffing; variants read the pack token.
- **Sealed-column read-allowlist** — reporting reads only names in `AGGREGATOR_EXIT_EDGE`'s
  emitted set + `ReportingContext`; catches never-produced-read reintroduction.
- **Add the missing `analysis` upward rule** (Phase 6 residue R3):
  `"analysis": ("rwa_calc.api", "rwa_calc.ui")` in `IMPORT_DIRECTION_RULES`.
- **Test-file LOC ceiling** on `tests/unit/reporting/**` so the straggler cannot re-accrete.
- **Retire the two "Retired by Phase 7" inversions** (`arch_check.py:413-414`).
- **watchfire:** each `TemplateSpec` cites its template ref (Reg 2021/451 Annex I/II; CRR Part 8
  for Pillar 3); `ReportingTemplateSet` entries cite PS1/26 template guidance; the projection
  columns cite Art. 235 / Art. 112.
- **CLAUDE.md / workflow:** add the reporting-projection files to the forced-single-stream list;
  update `/next-items` Step-4d reviewer criteria in the same PR that moves the architecture
  (no bulk-regen-to-green; number-changing slices carry decisions; each slice names its D1–D10
  kill).
