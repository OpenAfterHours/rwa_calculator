# Facility Share — Riskiest Member by Applied Approach (Investigation & Proposal)

> **Status:** APPROVED 2026-09-05 — mechanism O2 (candidate fan-out, resolved before the floor) in
> implementation · **Created:** 2026-09-05 · **Decision owner:** Phil · **Scope:** allocation of a
> shared facility's undrawn commitment to one of its member counterparties, under CRR and under
> Basel 3.1 with the output floor.
>
> **Decisions recorded 2026-09-05 (all as recommended in Section 7):** D1 rank on RWA
> (`rwa_pre_floor`), `risk_weight` first tie-break · D2 Basel 3.1 = P2 two-assignment rule by
> default with a `facility_share_metric` config election to pin P0 · D3 the facility owner is
> always a member · D4 candidates count toward their own member's obligor aggregates with no window
> special-casing (revised before implementation — see Section 4) · D5 delete the SA-only preview
> (P1.359 superseded). Runtime measured 2026-09-05: ~41 µs per extra candidate row through
> classifier→aggregator plus ~10 ms resolution pass at 112k rows; the unsecured-preview
> alternative (Section 4, O1) was ~20 ms fixed + ~1 µs/candidate — not a deciding factor.

This document answers three questions and ends with the decisions the proposal needs and a
sequenced way forward:

1. What does the calculator do today when a facility is shared, and why is that not "the riskiest
   member following their respective calculations"?
2. Where in the pipeline do the numbers needed for that comparison actually exist?
3. How does the Basel 3.1 output floor change what "riskiest" means, and what rule should apply?

---

## 0. Summary

- **Today** the winner is chosen in the hierarchy stage by an SA-only *preview* risk weight built
  from `entity_type`, `cqs` and `country_code`. It knows nothing about whether the member is on IRB
  or SA, its PD/LGD, its exposure class, any CRM on the facility, or the output floor. It is the
  mechanism P1.307 found choosing a 0%-weighted ECB and a mis-previewed MDB.
- **The requirement** — rank members on their *applied* approach (IRB formula for IRB members, SA
  table for SA members) — cannot be met at the hierarchy stage: approach, class, CRM and the floor
  are all decided downstream. The only point where every candidate's own-approach RWA and
  SA-equivalent RWA both exist is the exit of the `calculators` stage.
- **Proposal (mechanism):** *compute, then choose*. The hierarchy stage emits one undrawn candidate
  row per member; the candidates flow through classifier, CRM and the calculators as ordinary rows;
  a new resolution step at the head of the aggregator keeps one row per facility and drops the
  rest, before the output floor is applied. No second implementation of any pricing logic.
- **Basel 3.1 finding:** the floor is a portfolio-level `max`, so "riskiest" is *state-dependent*.
  The engine takes that max over the floor-eligible rows (IRB, slotting, CCR-via-SA) and adds the
  SA book outside it, so the choice reduces to two global assignments — every share by own-approach
  RWA (A), or every share by its floored-branch marginal (B: `x` × SA-equivalent for a modelled
  member, full RWA for an SA member) — each evaluated end-to-end, keeping the larger. That is a
  bound rather than an identity, because OF-ADJ moves with the winners' expected loss. A per-row
  "floored proxy" is provably wrong in both floor states.
- **Recommendation:** metric = own-approach `rwa_pre_floor` under CRR; under Basel 3.1 with the
  floor applicable, the two-assignment comparison above (P2), with a config election to pin the
  own-approach rule for firms that prefer stable obligor attribution. Section 7 lists the five
  decisions needed before design; Section 8 is the phased plan.

---

## 1. What the calculator does today

### 1.1 Detection

There is no input flag. A facility row carries exactly one `counterparty_reference` (its owner) and
the facility reference is a unique key (`TABLE_UNIQUE_KEYS`, `data/schemas.py`). Loans, contingents
and sub-facilities attach to a facility through `facility_mappings`
(`parent_facility_reference`, `child_reference`, `child_type`), and each child carries its own
counterparty reference. That is the only place a second counterparty can enter.

`engine/hierarchy/facility_undrawn.py::_derive_facility_share_counterparty` collects, per root
facility, the distinct counterparty references on all descendant loans, contingents and
sub-facilities (resolved to the root via `graph.build_facility_root_lookup`). More than one distinct
member ⇒ the facility is a **Facility Share**.

Two consequences of that rule worth stating plainly:

- **The facility's own owner is not a member** unless it also has a child exposure. A facility owned
  by A whose only mapped loan belongs to B has one member (B), is *not* a share, and its undrawn
  stays with A via the `coalesce(share_counterparty_reference, counterparty_reference)` fallback.
- **Nothing is drawn-weighted.** A member with a £1 loan and a member with a £10m loan are equal
  candidates. That is correct for the stated purpose (any member may draw the whole headroom).

### 1.2 Allocation

Only the synthetic `<facility>_UNDRAWN` row is affected; drawn legs keep their own counterparties
and the undrawn *amount* never changes. The candidates are ranked by a **non-binding SA-equivalent
risk-weight preview** from `engine/sa/guarantor_rw.py::build_entity_rw_expr(entity_type, cqs,
country_code)`; ties break on higher CQS then alphabetical reference; the winner becomes the row's
`counterparty_reference` and the owner is kept in `original_counterparty_reference`. Multiple Option
Facility parents (any facility with a `child_type='facility'` mapping) skip the override because
their per-sub waterfall rows already carry each sub's counterparty. Without a counterparty lookup
carrying `entity_type` the override is silently skipped.

### 1.3 Why this is not "riskiest by applied approach"

| Gap | Effect |
|---|---|
| SA table only | An IRB member is ranked by the SA weight of its entity type, never by its PD/LGD formula. A low-PD IRB corporate previews at 100% (unrated) and wins over a 75% retail SA member, then is priced at its true IRB weight — possibly far below 75%. **Anti-conservative in exactly the case the rule exists for.** |
| Entity type + CQS only | No exposure class (the classifier assigns it later), no retail thresholds, no RE/LTV bands, no SME factor, no sovereign/ECB carve-outs (P1.307 fixed two; P1.359 — plain `central_bank` under Basel 3.1 — is still open). |
| No CRM | Facility-level collateral or a guarantee changes the true RWA of the row; the preview cannot see either. |
| No output floor | Under Basel 3.1 the marginal capital of an IRB member is not its IRB RWA when the floor binds (Section 6). |
| Regime read | The module reads `getattr(config, "is_basel_3_1")` under a check-17 allowlist entry ("no-pack bootstrap fallback"). A new design must read `pack.feature("output_floor")`, not the boolean. |

### 1.4 What the estate contains

Measured on 2026-09-05 over the generated fixture parquets (script in Appendix A):

| Measure | Value |
|---|---|
| Fixture directories with facilities + loans + mappings | 9 scanned, 3 skipped (no loan/facility file beside the mapping) |
| Facilities with > 1 distinct child counterparty | **0** |
| Facilities whose single child counterparty ≠ owner | **1** — `tests/fixtures/exposures`: `FAC_RTL_SME_001` owned by `RTL_SME_001`, its only loan booked to `RTL_SME_SCN_001` |

So the only exercised share path is the in-memory portfolio in
`tests/acceptance/test_p1_307_facility_share_counterparty_preview.py` plus unit pins in
`tests/unit/test_hierarchy.py`. No golden reporting portfolio contains a share, which means (a) the
reporting goldens will not move when the mechanism changes, and (b) **every reporting cell this
path can populate is currently dead** (LESSONS B5) — a new portfolio must be registered in `RUNS`.

---

## 2. Regulatory position (premise check)

**There is no rule for this.** Neither CRR nor PS1/26 defines a "facility share" or prescribes how
to attribute a commitment that several obligors may draw. The CCF articles (CRR Art. 111 / Annex I,
Art. 166(8)–(10); PS1/26 Art. 111 Table A1, Art. 166) define the undrawn EAD for a commitment with
*one* obligor. The riskiest-member rule is therefore **firm policy grounded in conservatism**
(capitalise the commitment against the worst credit that could draw it), and must be documented in
the methodology as such. It gets no `@cites` of its own; the EAD it produces cites the CCF articles.

The output floor is regulation, quoted verbatim from `ps126app1.pdf` (Required Level of Own Funds
(CRR) Part, Article 92, PDF page 13 — see Appendix B):

> 2A. Subject to paragraph 5, the total risk exposure amount shall be calculated as follows: …
> `TREA = max {U-TREA; x ∙ S-TREA + OF-ADJ}` where … `x = 72.5%`; `OF-ADJ = 12.5 * (IRB T2 – IRB
> CET1 – GCRA + SA T2)`.

Paragraph 5 is the transitional phase-in. The engine reads it from the pack Schedule
`output_floor_pct` (b31 pack; 2027 → 2030 steps) or `output_floor_pct_full` when the firm elects to
skip the transition; `engine/aggregator/_floor.py::apply_floor_with_impact` implements the `max`
at portfolio level and distributes any shortfall pro-rata by `sa_rwa` across floor-eligible rows
(IRB, slotting, CCR-via-SA — `FLOOR_ELIGIBLE_APPROACHES`). The floor is a **portfolio** quantity:
no exposure has "its own" floor; `is_floor_binding` is the same value on every eligible row.

**Engine versus article (premise audit 2026-09-05).** `apply_floor_with_impact` sums U-TREA and
S-TREA over the floor-eligible rows only and re-adds SA rows unscaled (`_floor.py:203-225`, `:326`:
`total_rwa_post_floor = (U_elig + shortfall) + sa_rwa_total + equity_rwa_total`). Art. 92(2A)/(3)/(3A)
take the max over whole-firm totals, in which SA rows appear on both sides. The two agree only at
`x = 1`; otherwise the engine binds more often and by more (conservative). This design builds to the
**engine's** formula; the deviation is filed separately in Section 10 and must not be fixed here.

**Premise verdict: confirmed, with one rescoping.** The brief says "highest risk weight". The
conservative purpose is capital, which is RWA = EAD × RW, and EAD can differ by member wherever CCF
or CRM depends on the obligor (own-estimate CCFs where permitted, facility-level collateral, a
guarantee on one member). The proposal ranks on **RWA** with RW as the first tie-break; the two
orderings coincide whenever EAD is obligor-invariant, which is the common case.

---

## 3. Where the numbers live (pipeline facts)

| Stage (`engine/registry.py`) | What is known about a candidate member | Source |
|---|---|---|
| `hierarchy_resolver` | `entity_type`, `cqs`, `country_code`; `model_id` via rating inheritance (`hierarchy/ratings.py` → `enrich.py::attach_counterparty_rating`) | joins on the row's `counterparty_reference` — so **the undrawn row's model id follows whichever member it carries** |
| `classifier` | exposure class; approach via `classify/permissions.py` (model id × class × geography × book) | still per row, still follows the carried member |
| `crm_processor` | collateral / guarantee effects on the row | — |
| `calculators` (`stages/calc.py`) | `calculate_unified` runs the SA pipe pre-split **only when the `output_floor` Feature is on** (`stages/calc.py:99-103`): under Basel 3.1 every row carries `sa_rwa`, under CRR none does and the CRR metric must not read it; the branch calculators then write the own-approach `rwa` | `contracts/edges.py` calc branch edges: `rwa`, `rwa_post_factor`, `risk_weight`, `ead_final`, `approach_applied`, `sa_rwa` |
| `aggregator` | `rwa_pre_floor` (= own-approach RWA), `sa_rwa`, U-TREA, S-TREA, OF-ADJ, `is_floor_binding`, `rwa_final` | `_floor.py`, `OutputFloorSummary` |

Two facts follow. First, **a preview at the hierarchy stage cannot be made "approach-aware" without
re-implementing the classifier's approach ladder, the IRB formula, CRM and the floor** — a second
home for pricing logic that will drift exactly as the skill-value tables did (the 2026-08-08
graduation). Second, **everything the comparison needs already exists per row at the calculators'
exit**; the only thing missing is *more than one row per shared facility*.

---

## 4. Mechanism options

### O1 — Approach-aware preview at the hierarchy stage (rejected)

Extend `_derive_facility_share_counterparty` with an IRB-formula preview (member PD from its
rating, facility LGD or supervisory LGD, facility maturity) gated on whether the member has a
permitted model, keep the SA preview otherwise, and add a floor term under Basel 3.1.

- Pro: local to one module; no new rows; no aggregate-window interaction.
- Con: duplicates the approach ladder (`classify/permissions.py` filters on class, geography and
  book — none known at hierarchy time), the IRB formula, CRM and the floor. Every P1.307-class
  divergence multiplies. Still a preview; still wrong wherever the real pipeline disagrees with it.
- Con: cannot express the Basel 3.1 answer at all, because the floor state is a portfolio fact.

### O2 — Candidate fan-out with post-calculator resolution (**recommended**)

**Hierarchy.** For each Facility Share, emit one `facility_undrawn` row per member instead of one
row for the preview winner. Each candidate carries:

| Column | Value |
|---|---|
| `exposure_reference` | `<facility>_UNDRAWN@<member>` (MOF suffix grammar unchanged; `_exposure_suffix` extended) |
| `source_exposure_reference` | `<facility>` (unchanged — reconciliation keys on it) |
| `counterparty_reference` | the member |
| `original_counterparty_reference` | the facility owner (unchanged semantics) |
| `facility_share_group` | `<facility>` (null on every non-share row) |
| `is_facility_share_candidate` | `True` |

All candidates carry the full undrawn headroom (each is "as if this member drew it all"). The
existing SA preview and `build_entity_rw_expr`'s only consumer go away (Decision D5).

**Classifier → CRM → calculators.** No change to any pricing code. Each candidate is classified,
CRM-adjusted and priced as an ordinary row with its own member's class, model permission, PD/LGD and
CRM, and — because the SA pipe runs on every row — its own `sa_rwa`.

**Aggregator, at the top.** A new module `engine/aggregator/_facility_share.py` resolves each
`facility_share_group` to one winner by the policy metric (Sections 5–6) at the **head of
`OutputAggregator.aggregate`, on the three branch inputs** (`sa_results`, `irb_results`,
`slotting_results`) before anything reads them: `compute_el_portfolio_summary` reads the IRB and
slotting frames directly (`aggregator.py:289-292`), the securitisation summary and audit are built
off the concatenation at `:168-169`, and the residual multiplier and floor follow — so filtering the
combined frame alone would leave every losing candidate's EL inside OF-ADJ. It writes an audit frame
`facility_share_resolution` (one row per candidate: group, member, approach, `ead_final`,
pre-floor RWA, `sa_rwa` where present, rank, winner flag, metric used), drops the losers from all
three frames, collapses the winner's `exposure_reference` back to `<facility>_UNDRAWN`, and only
then does the existing flow run. The aggregator exit therefore keeps
today's invariant — **one undrawn row per facility** — so COREP, Pillar 3, reconciliation and the
supervisory register see the same shape they see now, with `exposure_reference` collapsing back to
`<facility>_UNDRAWN` on the winner.

**Obligor-keyed aggregate windows.** Candidates are real rows during classification, so the
per-obligor aggregates would see them. The sites are:

| Site | Aggregate |
|---|---|
| `engine/hierarchy/enrich.py:552-566` | retail-threshold totals `.sum().over(lending_group_reference / counterparty_reference)` — partition-local |
| `engine/classify/subtypes.py:407` | QRRE obligor aggregate `.sum().over("counterparty_reference")`, deduped on `parent_facility_reference` per obligor (`:325-380`) — partition-local; **do not change its key** |
| `engine/classify/attributes.py:703-722` | Art. 123A(1)(b)(ii) granularity — `pl.len().over("counterparty_reference")` feeds a **portfolio-wide** `portfolio_total` (no `.over()`); see D4 below |
| `engine/hierarchy/enrich.py:974`, `:979` | short-term rating spill-over `max()/min().over("counterparty_reference")` — value-idempotent because each candidate carries its member's own rating (verify in a test, do not assume) |
| `engine/hierarchy/enrich.py:1046`, `:1051` | short-term contamination flags `max().over("counterparty_reference")` — same |
| `engine/hierarchy/resolver.py:149-166` | `lending_group_totals` bundle field (`group_by(lending_group_reference)` with `exposure_count`) — inflated by candidates; no engine consumer, three tests assert on it (`tests/integration/test_loader_to_hierarchy.py:339`, `tests/unit/test_hierarchy.py:1224`, `:3807`) |

`compute_e_star_group_drawn` (CRR Art. 501 E*) **cannot move**: undrawn rows carry
`drawn_amount = 0.0` (`facility_undrawn.py:503`) and E* reads drawn plus interest.

Proposed semantics (Decision D4, revised before implementation): **no special-casing — every
candidate row counts toward its own member's aggregates exactly as any exposure of that member
would.** Each member's lending-group / obligor totals therefore include the full undrawn, which is
the conservative reading of "total amount owed" for a commitment any member may draw. Direction
versus today: the eventual winner's siblings are unchanged (the single undrawn row already counted
for them); a losing member's siblings gain the undrawn in their totals, so the **partition-local**
thresholds (retail GBP limit, QRRE limit) can only be crossed *upward*. **One site is not
partition-local and is RWA-reducing:** the Art. 123A(1)(b)(ii) granularity limb
(`attributes.py:703-722`) divides each obligor's aggregate by a portfolio-wide `portfolio_total`
that every extra candidate inflates, so unrelated retail obligors near the 0.2% limit would
requalify as retail. **Candidates are therefore excluded from that denominator** — an ex-candidate
aggregate computed as a separate window in `enrich.py` (never a window inside a window, check 21),
consumed only by the granularity denominator. That leaves the denominator without the eventual
winner's undrawn too (today it includes it), a deviation of one undrawn amount in the conservative
direction. A second, narrow path exists and is measured by the scenario rather than designed away:
a member demoted out of QRRE by the extra aggregate has correlation `0.03 + 0.13·exp(-35·PD)`,
which falls below QRRE's fixed 0.04 above PD ≈ 7.3%, so for such an obligor demotion *lowers* RWA;
it is partition-local (touches only that member) and is disclosed in the methodology page.
The rejected alternative — "own-inclusive", where non-candidate rows see no candidate — is exact
for losers but drops the undrawn from the winner's siblings, which is RWA-reducing relative to today.

**MOF parents** keep today's exclusion: their waterfall rows already carry each sub's counterparty.
The residual row (parent's own risk type) is not a candidate. Revisit only if a portfolio needs it.

**Errors.** Classification/CRM warnings raised on a losing candidate are noise; the resolution step
suppresses (or re-keys to the group) any `CalculationError` whose `exposure_reference` belongs to a
dropped candidate.

**Edge contracts.** The two new columns must be declared on **nine** contracts in
`contracts/edges.py`: HIERARCHY_RESOLVED_EDGE (`:882`), HIERARCHY_EXIT_EDGE (`:888`),
CLASSIFIER_EXIT_EDGE (`:1187`), CRM_EXIT_EDGE (`:1364`), RE_SPLIT_EXIT_EDGE (`:1396`),
SA_BRANCH_EDGE (`:1769`), IRB_BRANCH_EDGE (`:1785`), SLOTTING_BRANCH_EDGE (`:1846`), and
AGGREGATOR_EXIT_EDGE (`:1868`) for `facility_share_group` on the surviving winner row.
`EdgeContract.conform` (`edges.py:336-341`) drops an undeclared column with **no error and no
warning**, so one missed edge turns the feature into a green no-op (LESSONS B1). A contract test
must assert both columns are declared on every edge in that chain. The only `exposure_reference`
de-dup in `src/` is `classify/permissions.py:261`; the `@<member>` suffix keeps candidates distinct
through it.

**Cost.** Rows added = Σ(members − 1) over Facility Shares; a handful per portfolio. No new
materialisation; the resolution is a `.over(facility_share_group)` rank plus a filter.

### O3 — Shadow second pass (rejected)

Run the pipeline once as today, then re-run classifier → calculators on the candidate rows only with
the first pass's aggregates as context, and patch the winner in. Exact, but it needs stages to be
re-entrant on a sub-frame with injected context, which the fold (`engine/orchestrator.py`) does not
support, and it doubles the plan depth on a path already near the single-lazy-plan ceiling.

---

## 5. The ranking metric under CRR

Under CRR the `output_floor` Feature is off and capital is additive, so the capital-maximising
choice is per group:

```
winner(g) = argmax_{i ∈ members(g)} rwa_pre_floor_i        # own approach, post supporting factor
tie-break: risk_weight desc → pd_floored / cqs desc (worse credit) → counterparty_reference asc
```

`rwa_pre_floor` is the calculators' own-approach RWA including the SME / infrastructure supporting
factors (Art. 501 / 501a), so an SME member's relief is honoured — the metric is *capital*, not a
gross weight. Ranking on `risk_weight` instead is a one-line change of sort key; the proposal
recommends RWA (Section 2) and records the choice as Decision D1.

---

## 6. The ranking metric under Basel 3.1 — the output floor

### 6.1 Why the floor changes the answer

Let the non-share book contribute `U0` / `S0` to the floor-eligible totals and `SA0` to the SA book.
For a Facility Share `g` with members `i`, let `u_i` be the member's own-approach pre-floor RWA and
`s_i` its SA-equivalent (`sa_rwa`, present only under Basel 3.1). An assignment `c` picks one member
per group. With the engine's formula (Section 2), a modelled member's `u_i`/`s_i` enter `U_elig`/`S_elig`
and an SA member's `u_i` enters the SA book outside the max:

```
TREA(c) = SA(c) + EQ + max( U_elig(c),  x·S_elig(c) + OF-ADJ(c) )
```

The marginal capital of a member is `u_i` when the floor does not bind; when it binds it is `x·s_i`
for a member on a floor-eligible approach and still `u_i` for an SA member. Those can rank members
differently. Worked micro-example (symbolic `x`; the pack Schedule gives `x` for the reporting year):

| Member | approach | `u_i` | `s_i` | marginal, floor NOT binding | marginal, floor binding |
|---|---|---|---|---|---|
| A | IRB corporate, low PD, high SA-equivalent | 30 | 150 | 30 | 150·x |
| B | IRB corporate, higher PD | 80 | 80 | **80** | 80·x |
| C | SA retail (owner) | 75 | 75 | 75 | 75 |

Not binding ⇒ B is riskiest. Binding ⇒ A is riskiest at every Schedule step (`150x ≥ 90 > 75 > 80x`).
An SA member wins under a binding floor only when its full RWA exceeds every modelled member's
`x·s_i`. A rule that does not know the floor state picks the wrong member in one of the two states.

### 6.2 The reduction to two assignments

`TREA(c)` is the maximum of two branches. The un-floored branch `F1(c) = SA(c) + U_elig(c)` is
additive over groups, so it is maximised exactly by **A** = "every group by `argmax u_i`". The
floored branch `F2(c) = SA(c) + x·S_elig(c) + OF-ADJ(c)` has per-member marginal
`b_i = x·s_i` (floor-eligible approach) or `u_i` (SA approach); **B** = "every group by
`argmax b_i`". When OF-ADJ is constant, `F2` is additive too and

```
TREA(c) ≤ max( F1(A), F2(B) ) ≤ max( TREA(A), TREA(B) )     for every c
```

so the capital-maximising assignment is one of exactly two, found by evaluating the floored total
twice. **OF-ADJ is not constant** (premise audit): the GCRA cap is 1.25% of `S_elig`
(`compute_of_adj`, live only when `config.output_floor.gcra_amount > 0`, shipped default 0), and IRB
T2 / IRB CET1 come from `compute_el_portfolio_summary(irb_results, slotting_results)`
(`aggregator.py:289-292`, `:317-320`), so the winning modelled member's expected loss feeds them.
The floored branch stays strictly increasing in `S` (slope `x − 12.5·0.0125 ≥ 0.44375` while the
cap binds, `x` above it), so `argmax b_i` still maximises it group by group, but the branch is no
longer additive and the reduction is a **bound, not an identity**: `max(TREA(A), TREA(B))`, each
evaluated end-to-end with the EL summary of that assignment, is exact for those two assignments and
a lower bound on the true optimum. The EL channel is bounded by
`12.5·(PD_i·LGD_i + PD_j·LGD_j)·EAD` against an S channel of `x·RW_SA·EAD`, and dominates only above
`PD·LGD ≈ 0.058` at full `x` and 100% SA weight. `x` comes from
`_output_floor_pct(pack, config.output_floor, reporting_date)` exactly as the aggregator reads it.

### 6.3 Policy options

| | Rule | Capital-maximising? | Local & stable? | Notes |
|---|---|---|---|---|
| **P0** | own-approach `u_i` (same as CRR) | only when the floor does not bind | yes | The "obligor risk" reading: assignment is a classification decision; the floor is applied afterwards at the level the rule prescribes. Under-capitalises the share when the floor binds and an IRB member's SA-equivalent is the largest. |
| **P1** | per-row proxy `max(u_i, x·s_i)` | **no** — wrong in both states (A scores `max(30,100x)`, B scores 75: picks B when `100x < 75`, but if the floor binds A was riskier; picks A when `100x > 75` even when the floor does not bind and B was riskier) | yes | Tempting because it looks like "a floored RW". A per-exposure floor is not how Art. 92(2A) works. **Rejected.** |
| **P2** | evaluate `TREA(A)` and `TREA(B)` end-to-end, apply the larger | **yes** for the two evaluated assignments (exact when OF-ADJ is constant; a bound when its EL channel is live) | no — the assignment can flip with the floor state, with the phase-in step (`output_floor_pct` moves 2027→2030), and between reporting scopes (the floor is per entity of application; `resolve_scope` runs per scope) | The "riskiest member" under the floor. `TREA(P2) ≥ TREA(A)` always; versus today's preview winner it is not guaranteed when the floor binds, by at most the EL-channel bound. Attribution flips are visible in obligor-level COREP (C 08.x) and reconciliation. |
| **P3** | floored-branch marginal `b_i` always | only when the floor binds | yes | Right whenever the floor binds; wrong otherwise. No better than P0 in principle, and it contradicts the CRR rule for the same firm. |

### 6.4 Recommendation

- **CRR:** P0 (Section 5).
- **Basel 3.1, floor applicable** (`pack.feature("output_floor")` on **and**
  `config.output_floor.is_entity_in_scope()` — the gate the engine composes at `aggregator.py:309`;
  not `is_floor_applicable()`, which duplicates the regime Feature in a config boolean): **P2**,
  implemented as: rank every group under both metrics (`u_i`, then `b_i`), evaluate each assignment
  **end-to-end with the aggregator's own functions** — EL summary, OF-ADJ and floor computed on
  that assignment's resolved frames — and keep the assignment with the larger `total_rwa_post_floor`
  (ties → A, the own-approach assignment, for stability). Record which won in `OutputFloorSummary`
  (`facility_share_metric_used`, `facility_share_trea_alternative`) so the flip is never silent.
- **Basel 3.1, floor not applicable** (Art. 92(2A)(b)–(d) exemptions): P0.
- **Firm election:** a `facility_share_metric` field on `CalculationConfig` (`"floor_aware"` default,
  `"own_approach"` to pin P0) — a firm election belongs in config, like `OutputFloorConfig.skip_transitional`,
  not in the pack; the *regime* gate is the existing `output_floor` Feature (check 17).

Why P2 over P0 as the default: the stated purpose of the rule is conservatism, and under Basel 3.1
the firm's capital is `TREA`, not U-TREA. The estate already accepts portfolio-state-dependent
per-exposure numbers (`floor_impact_rwa` is pro-rata of a portfolio shortfall); P2 makes the
*attribution* depend on the same state, which is a visible but honest consequence. The election
exists for firms whose reporting or reconciliation cannot tolerate attribution moving with the floor.

**Free by-product.** Because every candidate is priced, the audit frame is a per-facility
*allocation sensitivity table* (RWA under every member, both metrics). That is directly useful
against the legacy system in reconciliation, whose own share rule is unknown.

---

## 7. Decisions required before design

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Rank on RWA (`rwa_pre_floor`) or on RW (`risk_weight`)? | **RWA**, RW as first tie-break (Section 2). |
| **D2** | Basel 3.1 policy: P0 / P2 / P3? Default of the election? | **P2 default, P0 election** (Section 6.4). |
| **D3** | Is the facility **owner** always a member? | **Yes.** The owner is the legal borrower and can draw. This turns `FAC_RTL_SME_001` in `tests/fixtures/exposures` into a two-member share — measure that fixture's consumers with the full unit suite before relying on any green (LESSONS D2). |
| **D4** | Candidate rows in obligor aggregates: count each candidate toward its own member's partition-local totals, and exclude candidates from the portfolio-wide Art. 123A granularity denominator (Section 4)? | **Yes** — conservative at every site; record it in the methodology page with the high-PD QRRE residual. "Own-inclusive" rejected as RWA-reducing for the winner's siblings; a second pass is O3. |
| **D5** | Delete the SA preview (`build_entity_rw_expr` and its `_share_*` plumbing)? | **Yes** — it has one consumer and the fan-out replaces it. P1.359 becomes superseded; P1.358 is the *guarantor* path and is unaffected. |

---

## 8. Way forward

Sized for `/next-items`; the aggregator and `contracts/edges.py` are shared files, so S3 is a
**single-stream** item. Suggested bullet IDs are placeholders for `plan-curator` (next free is
P1.367).

| Step | Deliverable | Gate |
|---|---|---|
| **S0** | Decisions D1–D5 recorded at the top of this page. | — |
| **S1 — fixtures & failing tests (TDD)** | A generated portfolio `tests/fixtures/facility_share/` with one facility, three members: the owner (SA, unrated corporate), an IRB corporate (low PD, so `u < s`), and an SA retail member; two variants so the floor **binds in one and not the other** (the two-leg pattern from LESSONS B5). Register in `generate_all.py` and in `RUNS`. Oracle case with the hand-calc for both regimes and both floor states. Unit tests for the resolution function (both regimes, both states, ties). Named mutation detector: `argmax → argmin` in the resolver must redden a specific test (C1.11). | red before S2/S3 |
| **S2 — hierarchy fan-out** (P1.367) | Candidate rows, the two new columns, owner-as-member, the ex-candidate granularity aggregate (separate window), the nine edge declarations plus a contract test that pins them, preview deletion with its footprint (S5), rulepack threaded into `facility_undrawn.py` so the check-17 allowlist entry retires; tests pin that each candidate contributes to its own member's partition-local totals and that the short-term spill-over windows are value-idempotent. | arch_check 16/17/18/21 green; full `tests/unit` (column footprint changes — LESSONS D2) |
| **S3 — aggregator resolution** (P1.368, single-stream) | `engine/aggregator/_facility_share.py` called at the head of `aggregate()` on the three branch frames: metric per policy, `TREA(A)`/`TREA(B)` evaluated end-to-end, loser drop from all three frames, winner reference collapse, error re-key, `facility_share_resolution` audit frame on `AggregatedResultBundle`, summary fields, `facility_share_metric` config election. | Tier 2 mandatory: `tests/oracle` + `tests/acceptance/reporting`; `coverage_report.py --check` (cells newly live ⇒ `--update-baseline`, re-measured) |
| **S4 — docs** (Tier 5) | `docs/architecture/components.md` hierarchy + aggregator rows; a methodology page `docs/specifications/facility-share-allocation.md` stating the policy, the two-assignment rule and D4; changelog. The basel31/crr skills get a *mechanics* paragraph only — no values. | `uv run zensical build`; `check_doc_links.py --check` |
| **S5 — close out** | Retire P1.359 as superseded (its `Ev:` path is already stale). **D5 deletion footprint:** `build_entity_rw_expr` has one production consumer (`facility_undrawn.py:986`) but deleting it means regenerating `tests/contracts/data/citation_snapshot.json` (7 entries) *before* the suite, `tests/contracts/data/confidence_snapshot.json` (7 references — its evidence layer text-scans the test tree) and `docs/development/citation-matrix.md`; correcting `docs/specifications/crr/sa-risk-weights.md:274-283`; retiring the check-17 allowlist entry for `facility_undrawn.py`; and re-pointing the defect-pinning tests that assert the old SA-preview winner — `tests/unit/test_entity_rw_preview.py` (whole file), `tests/unit/test_hierarchy.py` `:6379`, `:6475` (rename — under D3 it is a two-member share), `:6674`, `:6780` and the eight `test_p1_307_share_*`, and `tests/acceptance/test_p1_307_facility_share_counterparty_preview.py` `:292`, `:323`, `:351`, `:375`. Add the resolution rule to the reconciliation docs (sensitivity table). | stress suite before PR |

Effort: S1 M · S2 M · S3 M · S4 S — **L overall**, two batches.

---

## 9. Risks and traps (from `.claude/LESSONS.md`)

- **D1 — every `engine/sa/` transform is a floor consumer.** Candidates' `sa_rwa` are real S-TREA
  contributions until the losers are dropped; the drop must happen *before* `apply_floor_with_impact`
  or S-TREA is inflated by every losing candidate.
- **D2 — measure blast radius with the full unit suite.** Owner-as-member (D3) changes an existing
  fixture; the aggregate-window change alters a conditional expression's column footprint.
- **D3 — edge dtype violations redden the whole acceptance suite.** Two new columns on nine edges.
- **B1 — an undeclared column is dropped silently by `EdgeContract.conform`.** A missed edge makes
  the resolver a no-op and every test that only checks "one row per facility" stays green. Pin the
  declarations in a contract test and assert the audit frame has one row per candidate.
- **Four-frame input.** `aggregate()` receives the three branch frames separately and the EL
  summary reads two of them directly; resolve on all three at the head, never on `combined` alone.
- **C7 — both regimes, shown red separately.** The metric differs by regime by design; a
  both-regimes parametrisation that is red only under Basel 3.1 proves one regime.
- **B5 — dead cells.** No golden portfolio has a share today. Registration in `RUNS` is necessary;
  the floor-binding/non-binding pair is what makes the cell *move*.
- **Check 21.** D4 adds no window. If a later change does special-case candidates in an aggregate,
  it must be two `with_columns`, never a window whose input is another window.
- **LOC ratchet.** `max_engine_module_loc` is 1709 (`crm/guarantees.py` at 1708 binds);
  `facility_undrawn.py` is 1009 and `aggregator/aggregator.py` should not grow — hence the new
  `_facility_share.py` module. `engine_fill_null_sites` (468) also binds: reuse predicates.
- **Attribution flips under P2 are a feature, not a bug** — but they must be surfaced in the
  summary and the audit frame, never inferred from a moved COREP row.

---

## 10. Findings out of scope (filed for Phil, not fixed here)

1. **The engine floors the modelled subset, not the firm.** `apply_floor_with_impact` computes
   `max(U_elig, x·S_elig + OF-ADJ) + SA + equity` (`_floor.py:203-225`, `:309`, `:326`; the comment
   at `:192-193` "SA exposures cancel out" holds only at `x = 1`). Art. 92(2A)/(3)/(3A) take the max
   over whole-firm totals. Example at `x = 0.725`: `U_irb = 50`, `S_irb = 100`, `SA = 100` — article
   `max(150, 145) = 150`, engine `max(50, 72.5) + 100 = 172.5`. Conservative today; **fixing it is
   RWA-reducing** and needs its own plan bullet, evidence and sign-off (LESSONS A2, D1). Every
   reporting golden and the supervisory register bank the current behaviour.
2. **`InstitutionType` has no member for a ring-fenced body outside a sub-consolidation group**
   (`domain/enums.py:622-624`), which Art. 92(2A)(a)(i) says *is* floored on an individual basis.
   Reachability not established.
3. **QRRE demotion at high PD lowers RWA** (Section 4, D4) — measured by the scenario in S1 and
   disclosed; a candidate-aware QRRE aggregate would need the obligor's PD at classification time.

## Appendix A — estate measurement

`scan_shares.py` (run 2026-09-05 from the main checkout; joins each fixture directory's
`facility_mapping(s).parquet` to its `loan(s)` / `contingent(s)` / `facility|facilities` parquets and
counts distinct child counterparties per parent facility):

```
exposures: shares=0 owner_mismatch_single_member=1
    [{'fac': 'FAC_RTL_SME_001', 'owner': 'RTL_SME_001', 'counterparty_reference': 'RTL_SME_SCN_001'}]
scanned=9 dirs_with_findings=1 skipped=3
  skipped: p1_118
  skipped: p1_142
  skipped: p1_151
```

## Appendix B — PS1/26 Art. 92(2A), verbatim (`ps126app1.pdf`, 0-indexed page 12, printed "Page 13 of 492"; 2A(b)-(d) on 0-indexed page 13; 3A and paragraph 5 on 0-indexed page 14)

```
2A. Subject to paragraph 5, the total risk exposure amount shall be calculated as follows:
(a) for the purposes of complying with the obligations of this Part:
  (i)   on an individual basis, a stand-alone institution in the UK and a ring-fenced body that
        is not a member of a sub-consolidation group;
  (ii)  on a sub-consolidated basis, a ring-fenced body that is a member of a sub-consolidation
        group; and
  (iii) on the basis of its consolidated situation, a CRR consolidation entity that is not an
        international subsidiary,
shall calculate the total risk exposure amount as follows:
        TREA = max {U-TREA; x ∙ S-TREA + OF-ADJ}
where:
  TREA   = the total risk exposure amount of the entity;
  U-TREA = the un-floored total risk exposure amount of the entity calculated in accordance
           with paragraph 3;
  S-TREA = the standardised total risk exposure amount of the entity calculated in accordance
           with paragraph 3A;
  x      = 72.5%;
  OF-ADJ = 12.5 * (IRB T2 – IRB CET1 – GCRA + SA T2);
  ...
  GCRA   = general credit risk adjustments, gross of tax effects, of up to 1.25% of
           risk-weighted exposure amounts calculated in accordance with paragraph 3A;
```

Related pages: [Architecture components](../architecture/components.md) ·
[Implementation plan](implementation-plan.md) · [Escape log](../development/escape-log.md)
