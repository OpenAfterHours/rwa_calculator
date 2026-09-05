# Facility Share — Riskiest Member by Applied Approach (Investigation & Proposal)

> **Status:** Proposal — investigation complete, nothing implemented · **Created:** 2026-09-05
> **Decision owner:** Phil · **Scope:** allocation of a shared facility's undrawn commitment to one
> of its member counterparties, under CRR and under Basel 3.1 with the output floor.

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
  The algebra reduces it to comparing exactly two global assignments — every share allocated by
  own-approach RWA, or every share allocated by SA-equivalent RWA — and taking the one that yields
  the higher floored total. A per-row "floored proxy" is provably wrong in both floor states.
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
| `calculators` (`stages/calc.py`) | `calculate_unified` runs the SA pipe **unconditionally pre-split**, so every row carries `sa_rwa`; the branch calculators then write the own-approach `rwa` | `contracts/edges.py` calc branch edges: `rwa`, `rwa_post_factor`, `risk_weight`, `ead_final`, `approach_applied`, `sa_rwa` |
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

**Aggregator, before the floor.** A new module `engine/aggregator/_facility_share.py` resolves each
`facility_share_group` to one winner by the policy metric (Sections 5–6), writes an audit frame
`facility_share_resolution` (one row per candidate: group, member, approach, `ead_final`,
`rwa_pre_floor`, `sa_rwa`, rank, winner flag, metric used), drops the losers from the results frame,
and only then hands the frame to `apply_floor_with_impact`. The aggregator exit therefore keeps
today's invariant — **one undrawn row per facility** — so COREP, Pillar 3, reconciliation and the
supervisory register see the same shape they see now, with `exposure_reference` collapsing back to
`<facility>_UNDRAWN` on the winner.

**Obligor-keyed aggregate windows.** Candidates are real rows during classification, so the
per-obligor aggregates would see them. The sites are:

| Site | Aggregate |
|---|---|
| `engine/hierarchy/enrich.py:555-567` | retail-threshold totals `.sum().over(lending_group_reference / counterparty_reference)` |
| `engine/classify/subtypes.py:407` | QRRE obligor aggregate `.sum().over("counterparty_reference")` |
| `engine/classify/attributes.py:713` | retail granularity `pl.len().over("counterparty_reference")` |
| `engine/supporting_factors.py::compute_e_star_group_drawn` | CRR Art. 501 E* across the lending group |

Proposed semantics: **a candidate counts only toward its own member's aggregate, and only on its own
row** — non-candidate rows see the real book without any candidate; each candidate sees the real
book plus itself. This is the "as if this member were the obligor" reading and it stops a losing
candidate from tipping the loser's *other* loans over a threshold. It is a two-step
`with_columns` (window over non-candidates, then a plain arithmetic add of the row's own amount when
it is a candidate) — the same shape arch_check check 21 requires, never a window inside a window.
One deliberate delta from today is recorded as Decision D4: the eventual winner's *sibling* loans no
longer see the undrawn in their threshold totals (today they do, because the single row exists
before classification).

**MOF parents** keep today's exclusion: their waterfall rows already carry each sub's counterparty.
The residual row (parent's own risk type) is not a candidate. Revisit only if a portfolio needs it.

**Errors.** Classification/CRM warnings raised on a losing candidate are noise; the resolution step
suppresses (or re-keys to the group) any `CalculationError` whose `exposure_reference` belongs to a
dropped candidate.

**Edge contracts.** The two new columns must be whitelisted on every edge from `hierarchy_exit`
through `crm_exit` and the three calc branch edges to the aggregator (`contracts/edges.py`) — the
crm-exit whitelist trap is in memory and in LESSONS D3.

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

Let the non-share book contribute `U0` to U-TREA and `S0` to S-TREA. For a Facility Share `g` with
members `i`, let `u_i = rwa_pre_floor_i` (own approach) and `s_i = sa_rwa_i` (SA-equivalent; for an
SA member `s_i = u_i`). An assignment `c` picks one member per group and yields

```
U(c) = U0 + Σ_g u_{c(g)}          S(c) = S0 + Σ_g s_{c(g)}
TREA(c) = max( U(c),  x·S(c) + OF-ADJ )
```

The marginal capital of a member is `u_i` when the floor does not bind and `x·s_i` when it does —
and those can rank members differently. Worked micro-example (symbolic `x`; substitute the pack
Schedule value for the reporting year):

| Member | approach | `u_i` | `s_i` | marginal, floor NOT binding | marginal, floor binding |
|---|---|---|---|---|---|
| A | IRB corporate, low PD | 30 | 100 | 30 | 100·x |
| B | SA retail | 75 | 75 | **75** | 75·x |

Not binding ⇒ B is riskiest. Binding ⇒ A is riskiest (`100x > 75x`). A rule that does not know the
floor state picks the wrong member in one of the two states.

### 6.2 The reduction to two assignments

`TREA(c)` is the maximum of two functions that are each additive over groups, so for every `c`:

```
TREA(c) ≤ max( max_c U(c),  x·max_c S(c) + OF-ADJ )
        = max( U(A),        x·S(B) + OF-ADJ )
        ≤ max( TREA(A), TREA(B) )
```

where **A** = "every group by `argmax u_i`" (maximises U) and **B** = "every group by
`argmax s_i`" (maximises S). Both are feasible, so the capital-maximising assignment is always one
of exactly two candidates, found by evaluating the floored total twice. No search, no mixing.
OF-ADJ does not depend on the assignment. `x` comes from `_output_floor_pct(pack, config.output_floor,
reporting_date)` exactly as the aggregator already reads it.

### 6.3 Policy options

| | Rule | Capital-maximising? | Local & stable? | Notes |
|---|---|---|---|---|
| **P0** | own-approach `u_i` (same as CRR) | only when the floor does not bind | yes | The "obligor risk" reading: assignment is a classification decision; the floor is applied afterwards at the level the rule prescribes. Under-capitalises the share when the floor binds and an IRB member's SA-equivalent is the largest. |
| **P1** | per-row proxy `max(u_i, x·s_i)` | **no** — wrong in both states (A scores `max(30,100x)`, B scores 75: picks B when `100x < 75`, but if the floor binds A was riskier; picks A when `100x > 75` even when the floor does not bind and B was riskier) | yes | Tempting because it looks like "a floored RW". A per-exposure floor is not how Art. 92(2A) works. **Rejected.** |
| **P2** | evaluate `TREA(A)` and `TREA(B)`, apply the larger | **yes, always** | no — the assignment can flip with the floor state, with the phase-in step (`output_floor_pct` moves 2027→2030), and between reporting scopes (the floor is per entity of application; `resolve_scope` runs per scope) | The exact "riskiest member" under the floor. Attribution flips are visible in obligor-level COREP (C 08.x) and reconciliation. |
| **P3** | SA-equivalent `s_i` always | only when the floor binds | yes | Right whenever the floor binds; wrong otherwise. No better than P0 in principle, and it contradicts the CRR rule for the same firm. |

### 6.4 Recommendation

- **CRR:** P0 (Section 5).
- **Basel 3.1, floor applicable** (`pack.feature("output_floor")` on **and**
  `config.output_floor.is_floor_applicable()`): **P2**, implemented as: rank every group under both
  metrics, compute `TREA(A)` and `TREA(B)` from the candidate frame plus `U0`/`S0`, keep the
  assignment with the larger total (ties → A, the own-approach assignment, for stability). Record
  which won in `OutputFloorSummary` (`facility_share_metric_used`, `facility_share_trea_alternative`)
  so the flip is never silent.
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
| **D4** | Candidate rows in obligor aggregates: "own-inclusive" (Section 4) — accepting that the winner's sibling loans no longer see the undrawn before resolution? | **Yes**, and record it in the methodology page. The alternative (a second pass) is O3. |
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
| **S2 — hierarchy fan-out** (P1.367) | Candidate rows, the two new columns, owner-as-member, own-inclusive aggregates at the four sites, preview deletion, edge whitelists. | arch_check 16/17/18/21 green; full `tests/unit` (column footprint changes — LESSONS D2) |
| **S3 — aggregator resolution** (P1.368, single-stream) | `engine/aggregator/_facility_share.py`: metric per policy, `TREA(A)`/`TREA(B)`, loser drop, error re-key, `facility_share_resolution` audit frame on `AggregatedResultBundle`, summary fields, `facility_share_metric` config election. | Tier 2 mandatory: `tests/oracle` + `tests/acceptance/reporting`; `coverage_report.py --check` (cells newly live ⇒ `--update-baseline`, re-measured) |
| **S4 — docs** (Tier 5) | `docs/architecture/components.md` hierarchy + aggregator rows; a methodology page `docs/specifications/facility-share-allocation.md` stating the policy, the two-assignment rule and D4; changelog. The basel31/crr skills get a *mechanics* paragraph only — no values. | `uv run zensical build`; `check_doc_links.py --check` |
| **S5 — close out** | Retire P1.359 as superseded; add the resolution rule to the reconciliation docs (sensitivity table). | stress suite before PR |

Effort: S1 M · S2 M · S3 M · S4 S — **L overall**, two batches.

---

## 9. Risks and traps (from `.claude/LESSONS.md`)

- **D1 — every `engine/sa/` transform is a floor consumer.** Candidates' `sa_rwa` are real S-TREA
  contributions until the losers are dropped; the drop must happen *before* `apply_floor_with_impact`
  or S-TREA is inflated by every losing candidate.
- **D2 — measure blast radius with the full unit suite.** Owner-as-member (D3) changes an existing
  fixture; the aggregate-window change alters a conditional expression's column footprint.
- **D3 — edge dtype violations redden the whole acceptance suite.** Two new columns on five edges.
- **C7 — both regimes, shown red separately.** The metric differs by regime by design; a
  both-regimes parametrisation that is red only under Basel 3.1 proves one regime.
- **B5 — dead cells.** No golden portfolio has a share today. Registration in `RUNS` is necessary;
  the floor-binding/non-binding pair is what makes the cell *move*.
- **Check 21.** The own-inclusive aggregate must be two `with_columns`, never a window whose input
  is another window.
- **LOC ratchet.** `max_engine_module_loc` is 1709 (`crm/guarantees.py` at 1708 binds);
  `facility_undrawn.py` is 1009 and `aggregator/aggregator.py` should not grow — hence the new
  `_facility_share.py` module. `engine_fill_null_sites` (468) also binds: reuse predicates.
- **Attribution flips under P2 are a feature, not a bug** — but they must be surfaced in the
  summary and the audit frame, never inferred from a moved COREP row.

---

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

## Appendix B — PS1/26 Art. 92(2A), verbatim (`ps126app1.pdf`, PDF page 13)

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
