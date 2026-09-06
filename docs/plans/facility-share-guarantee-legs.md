# Facility Share × CRM legs — rank members, not legs

**Status:** proposed 2026-09-06 (user escape). Fix not started.
**Supersedes nothing.** Extends `facility-share-riskiest-member.md` (the design of record for the
fan-out, implemented in PR #493) by correcting one of its premises.
**Plan items:** P1.371 (resolver), P1.372 (allocation dilution), P5.65 (owed measurements).
**Closing artifact:** an entry in `../development/escape-log.md`, written by `/postmortem` once the
gate below has been observed red and the fix has landed.

---

## 0. Summary

A user reported a facility share carrying a guarantee: the guarantee was applied correctly, but the
uncovered remainder of the undrawn commitment did not land on the riskiest member — an unrated
standardised corporate. Reproduced on the FS-1 fixture with one member made unrated and a
facility-level guarantee added (Appendix A). Two defects, one root:

1. **The resolver ranks CRM legs, not members.** `engine/crm/guarantees.py::_apply_guarantee_splits`
   turns every guaranteed candidate `<fac>_UNDRAWN@<m>` into `<fac>_UNDRAWN@<m>__G_<guarantor>` +
   `<fac>_UNDRAWN@<m>__REM` *before* the calculators run. `engine/aggregator/_facility_share.py::
   resolve_facility_shares` groups on `facility_share_group` alone, so a three-member share with one
   guarantee has **six** candidates. Exactly one leg wins; every other leg — including the winner's
   own sibling — is dropped from all four frames. Whichever leg wins, part of the commitment
   vanishes from the submission, and the tie-break decides the attribution: the two standardised
   members' guaranteed legs tie on RWA and on the (guarantor's) risk weight, the PD rung is null on
   both, and the CQS rung sorts nulls last — so the **unrated** member loses to the rated owner.
   That is the user's symptom to the letter.
2. **Amount-based facility-level protection is diluted by the fan-out.** Every candidate carries the
   full headroom, and the pro-rata base for a facility-level guarantee (`kernels/allocation.py::
   expand_items_pro_rata`), facility-level collateral (`crm/processor.py::_build_facility_lookup`),
   provisions and the hierarchy's property-collateral window sums the headroom once **per member**.
   The drawn loans under the facility lose cover too, and only part of the pledge is recognised
   anywhere. `percentage_covered` passes through per row and is not diluted.

The design of record assumed the opposite in as many words — §2: *"EAD can differ by member wherever
CCF or CRM depends on the obligor (… a guarantee on one member)"*, i.e. CRM changes the member's
**one** row. It does not; it multiplies the row. No fixture could see it: FS-1 says *"Deliberately
absent — No collateral, guarantees, provisions or netting"*, and no other registered portfolio has a
share at all (design doc §1.4). LESSONS B5, path never exercised.

**Direction.** Defect 1 is RWA-**reducing** in both branches (a leg is always lost) and mis-attributes
the survivor. Defect 2 is RWA-**increasing** on the drawn book (less cover) and on the candidate.
Both fixes therefore need a measurement, and defect 1's fix releases no capital — it restores it.

---

## 1. What was measured

FS-1 (`tests/fixtures/facility_share_portfolio.py`), `nonbinding` variant, with `FS-CP-LOW`'s CQS-1
rating removed (unrated corporate, 100%) and a guarantee from a new institution `FS-GUAR-BANK`
(CQS 2) pledged at `beneficiary_type="facility"` on `FS-FAC-SHARE` (limit 1,000,000; drawn
600,000; headroom 400,000; CCF 50% SA / 75% F-IRB under CRR). Script in Appendix A.

### 1.1 The user's shape — `percentage_covered = 0.8`, CRR

| Leg (audit frame) | Member | EAD | RW | Own RWA | Rank |
|---|---|---:|---:|---:|---:|
| `…@FS-CP-SA__G_FS-GUAR-BANK` | owner, CQS 2 | 160,000 | 0.50 | 80,000 | **1 — wins** |
| `…@FS-CP-LOW__G_FS-GUAR-BANK` | unrated | 160,000 | 0.50 | 80,000 | 2 |
| `…@FS-CP-IRB__G_FS-GUAR-BANK` | F-IRB | 160,000 | 0.2757 | 44,117 | 3 |
| `…@FS-CP-LOW__REM` | unrated | 40,000 | 1.00 | 40,000 | 4 |
| `…@FS-CP-SA__REM` | owner | 40,000 | 0.50 | 20,000 | 5 |
| `…@FS-CP-IRB__REM` | F-IRB | 60,000 | 0.2757 | 16,544 | 6 |

Engine: one survivor, `FS-FAC-SHARE_UNDRAWN` attributed to **FS-CP-SA**, EAD 160,000, RWA 80,000.
Every `__REM` leg is dropped. Per member, the correct totals are FS-CP-LOW **120,000**, FS-CP-SA
100,000, FS-CP-IRB 60,660 — the unrated member is the riskiest by a clear margin, and the engine
reports 40,000 less than its capital under a different name.

### 1.2 The other branch — `percentage_covered = 0.5`, CRR

`FS-CP-LOW__REM` (100,000 EAD at 100%) wins; `FS-CP-LOW__G_…` (100,000 EAD at 50%, 50,000 RWA) is
dropped. Half the commitment leaves the book. Reported 100,000 against a correct 150,000.

### 1.3 Basel 3.1

Same shape (`amount_covered = 500,000`): winner `FS-CP-LOW__REM` at 158,333 EAD; the 41,667
guaranteed EAD at the ECRA 30% (12,500 RWA) is dropped. The floor-aware ranking inherits the defect
because `b_i` is scored on the same per-leg rows.

### 1.4 Dilution — `amount_covered = 500,000` on a 1,000,000 limit, CRR

Pro-rata basis is `ead_after_collateral` over the facility's descendants. Before the fan-out the
base was 400,000 + 200,000 + 200,000 (one undrawn row, owner's 50% CCF) = **800,000**; with three
candidates it is 400,000 + 200,000 + 200,000 + 200,000 + 300,000 = **1,300,000**.

| Row | Cover before fan-out | Cover measured now |
|---|---:|---:|
| `FS-LN-IRB` (400,000) | 62.5% | 38.5% |
| `FS-LN-LOW` (200,000) | 62.5% | 38.5% |
| SA candidate (nominal 400,000) | 31.25% | 19.2% |
| F-IRB candidate (nominal 400,000) | — | 28.8% |
| Recognised on the surviving book | 500,000 | **230,769** |

Control: the same pledge shape on the single-member `FS-FAC-SOLO` allocates exactly as before
(loan 75%, undrawn 37.5% of nominal). `percentage_covered = 0.5` gives 50% on every row — no dilution.

---

## 2. Mechanism — where the rows multiply

`engine/registry.py:53-55` orders `crm_processor → re_splitter → calculators`. Two stages between the
fan-out and the resolver multiply rows and rename them:

| Stage | Producer | New reference | Parent carrier |
|---|---|---|---|
| CRM guarantee split | `crm/guarantees.py::_build_guarantor_sub_rows` (`:916`) / `_retained_tranche_rows` (`:1022`) | `<ref>__G_<guarantor>`, `<ref>__REM`, `<ref>__REM_FL`, `<ref>__REM_SEN` | `parent_exposure_reference` (`:143`; typed null when the sub-step does not run — `contracts/edges.py:1348`) |
| Real-estate split | `re_split/splitter.py:710-757` | `<ref>_sec`, `<ref>_res`, mixed suffix | `split_parent_id` (`edges.py:1414`, `:1724`) |

Both copy every column of the parent row, so `facility_share_group`, `is_facility_share_candidate`
and `counterparty_reference` (the **borrower**, even on a `__G_` leg — `reporting/corep/c08.py:116`)
survive onto every leg. The resolver reads the concatenated calculator exits, on which
`parent_exposure_reference`, `split_parent_id`, `pre_crm_risk_weight` and
`original_counterparty_reference` are all declared (`_calc_output_common_columns`, `edges.py:1665`,
`:1724`, `:1761-1762`).

The resolver then does four things per leg that must be done per member:
`groups.setdefault(row[GROUP_COL], []).append(row)` (one list per facility, legs mixed in);
`_choose_assignment` takes `members[0]`; `collapse` maps only that one reference;
`dropped` is every other candidate reference. `_collapsed_reference` is `rsplit("@", 1)[0]`, which
on `X_UNDRAWN@M__G_B` yields `X_UNDRAWN` — so even two surviving legs would today collide on one name.

---

## 3. Design

### D1 — Member key: (`facility_share_group`, `counterparty_reference`)

Every leg of every splitter carries both, unchanged. The pair is 1:1 with the candidate root by
construction: `_derive_facility_share_members` uniques on exactly `(facility_reference,
counterparty_reference)`. No reference grammar is parsed.

Rejected: `parent_exposure_reference` alone (null when no guarantee sub-step ran; not re-pointed by
`re_split`); `split_parent_id` alone (null without an RE split); string-parsing `@…__` (a member
reference may itself contain `__`).

### D2 — The winner is a member; all of its legs survive; the collapse strips only `@<member>`

`collapse` becomes a per-leg map for **every** leg of the winning member, on three columns:
`exposure_reference`, `parent_exposure_reference`, `split_parent_id` (where non-null). The strip is
the literal `"@" + counterparty_reference`, nothing else. Result: a resolved share is byte-identical
in shape to a single-member facility with the same CRM — measured today on `FS-FAC-SOLO`:
`FS-FAC-SOLO_UNDRAWN__G_FS-GUAR-BANK` / `FS-FAC-SOLO_UNDRAWN__REM`. Legs stay unique (they differ by
their own suffix), the `__G_`/`__REM`/`_sec`/`_res` grammar every reporting and reconciliation
consumer keys on is preserved (`analysis/return_recon.py:1740` coalesces `parent_exposure_reference`
then `split_parent_id`), and no `@` reaches COREP.

`dropped` = every leg of every losing member. `drop_losing_candidates` applies the three-column
re-key and clears the candidate flag on all collapsed legs. `rekey_candidate_errors` keys on all
legs. `_facility_share_trea`'s `candidate_references` already holds every leg; `surviving` becomes the
union of the winners' leg sets.

### D3 — Metrics per member: `U_m = Σ u_i`, `B_m = Σ b_i` over the member's legs

`b_i` stays a **per-leg** quantity keyed on the leg's own `approach_applied` (a guaranteed leg and its
remainder may sit on different sides of the floor). Assignment A = argmax `U_m`, assignment B =
argmax `B_m` per group; the two-assignment, end-to-end evaluation and the skip-when-identical rule are
unchanged — a survivor set is now a union of member leg-sets, and `TREA` is still a pure function of
the set. Nothing in the Art. 92(2A) algebra moves.

### D4 — Tie-break at member level, on the member's **own** credit

The first rung becomes the EAD-weighted own risk weight `Σ ead·coalesce(pre_crm_risk_weight,
risk_weight) / Σ ead` (descending), so a guarantor's weight on a `__G_` leg cannot mask the member's
standing — this is the rung that separates an unrated corporate (100%) from a CQS 2 one (50%) and
makes the CQS rung's null placement moot in the reported case. Then max `pd_floored`, then `cqs`
(nulls still last, now behind a rung that already ranks "unrated" correctly), then the reference
rungs. The fallback ordering for a member whose every leg is non-finite uses the same rungs.

### D5 — Audit frame: one row per leg, member columns added

Keep one audit row per leg (so `_fs1_harness.adequacy_three_candidates` stays green — three legs are
three members on FS-1) and add `leg_count`, `member_rwa_pre_floor`,
`member_floored_branch_contribution`; `rank_own_approach` / `rank_floored_branch` become member
ranks repeated on each leg; `is_winner` is True on **every** leg of the winning member;
`collapsed_exposure_reference` is per leg. Contract: exactly one winning *member* per group
(replaces `test_resolver_marks_exactly_one_winner_and_one_collapsed_reference_per_group`'s one-row
claim). Additive schema change; the only readers are the bundle field and the FS-1 harness.

### D6 — The invariant the defect violated, as a gate: **resolution conserves the commitment**

For every resolved group: `count(survivors) == leg_count(winner)` and
`Σ ead_final(survivors) == Σ ead_final(winner legs)` (and the same on `nominal_amount`, which the
splits carry pro-rata). Three forms, all owed:

- **Runtime**: after the drop in `aggregate()`, compare the survivors against the audit frame and
  append a new `AGG0xx` ERROR (`contracts/errors.py`) on any violation — never raise (LESSONS B9: a
  hazard the code knows about must assert, not log).
- **Unit**: a two-leg candidate group on the resolver, asserting both identities. On the current
  resolver this test fails with count 1 vs 2 — that is the **verified red**.
- **Acceptance**: FS-2 (below) asserts the winner, the survivor legs, their EAD and RWA to the penny.

### D7 — Dilution: allocate facility-level items as if the owner's candidate were the only undrawn row

Rule: in every facility-level pro-rata base, a share's candidates contribute **once**, at the
**owner candidate's** basis (D3 of the design of record guarantees the owner is always a member, so
the row always exists: `is_facility_share_candidate & counterparty_reference ==
original_counterparty_reference`); and **every** candidate of the group receives the owner
candidate's GBP allocation. The guarantee is a fixed GBP amount of protection on the facility and
its split between drawn and undrawn does not depend on who draws; only the candidate's coverage
*ratio* moves with its CCF, and the existing per-exposure cap (`_join_multi_guarantees` `_scale`)
already bounds it at 1.

Consequences, on the §1.4 portfolio: base 800,000; `FS-LN-IRB` 250,000 (62.5%), `FS-LN-LOW` 125,000
(62.5%), every candidate 125,000 (31.25% of nominal; 62,500 of the SA candidate's 200,000 EAD);
recognised on the surviving book 250,000 + 125,000 + 125,000 = **500,000 = pledged**, whichever member
wins, and never more.

Rejected: *max candidate basis* as the denominator (conservative and always ≤ pledged, but drifts the
drawn book off its pre-fan-out figure whenever candidates' CCFs differ, for no economic reason);
*owner basis with each candidate's own numerator* (over-recognises whenever the winner's CCF exceeds
the owner's — RWA-reducing, unsafe).

Sites, all through `engine/kernels/allocation.py`: `expand_items_pro_rata` (`totals`, `:403`) for
facility-level guarantees; `grouped_level_lookup` with membership (`:496`) feeding
`crm/processor.py::_build_facility_lookup` for collateral; the provisions facility cascade
(`crm/provisions.py:217`); the hierarchy's property-collateral window (`hierarchy/enrich.py:784`,
which runs on the unified frame *after* the fan-out). Implement once in the kernel as a
"share-deduplicated basis" helper and route the four sites through it; unit-test the kernel on a
synthetic three-candidate frame, then confirm the §1.4 numbers end to end on FS-2's amount variant.

Counterparty-level items are **not** changed by D7: only that member's own candidate is in its
group, so there is no multiplicity. The residual leak on a *losing* member (its candidate consumed
part of a counterparty-level item and left with it; RWA-increasing on that member's drawn book) is
measured under P5.65, not fixed here.

---

## 4. Slices and waves

Two `/next-items` items, run in this order. Both touch `engine/aggregator/` or the FS-2 fixture, so
P1.371 is forced single-stream; P1.372 depends on P1.371's fixture and runs after it.

### P1.371 — resolver per member (D1–D6) — **the escape**

| Wave | Deliverable |
|---|---|
| premise-auditor | Re-run Appendix A on `master`; confirm six audit rows, the `FS-CP-SA__G_` winner and the 40,000 shortfall. Confirm `parent_exposure_reference` is null on an unguaranteed run (D1's reason). |
| scenario-architect | **FS-2** = FS-1 + `FS-GUAR-BANK` (institution, CQS 2) + one facility-level guarantee, `percentage_covered = 0.8` (no dilution, so the hand-calc isolates the resolver). Members as FS-1 but `FS-CP-LOW` **unrated**. Hand-calc per leg and per member, both regimes, from `_fs1_expectations`' pack-read helpers — no typed regulatory values (LESSONS A4). Adequacy assertions: the per-leg argmax and the per-member argmax name **different** members (otherwise the test cannot fail); the winning member has ≥ 2 legs; the guarantor's RW is below the unrated weight and above the F-IRB weight. |
| fixture-builder | `tests/fixtures/facility_share_guarantee_portfolio.py` (in-memory, like FS-1); register `crr/facility-share-guarantee` and `b31/facility-share-guarantee` in `RUNS`; `EXPECTED_RUNS` grows. |
| test-writer | (a) `tests/acceptance/test_fs2_facility_share_guarantee_legs.py`: winner member, survivor references (`FS-FAC-SHARE_UNDRAWN__G_FS-GUAR-BANK`, `…__REM`), EAD and RWA per leg, total; (b) resolver unit tests: two-leg group, member ranking, three-column collapse, D6 identities, D4 own-RW rung, RE-split `_sec`/`_res` legs; (c) contract test for the `AGG0xx` runtime check; (d) `test_resolver_marks_exactly_one_winner…` re-anchored to "one winning member". **All red on `master`.** Record the failure lines — they are the escape-log's *Verified red*. |
| engine-implementer | `_facility_share.py` (D1–D5), `aggregator.py` (D6 runtime check), `contracts/errors.py` (code), spec + design-doc updates (§6). |

Gate: Tier 2 mandatory — goldens for the two new runs, `scripts/template_cell_coverage_baseline.json`
and `scripts/coverage_baseline.json` re-banked by measurement, the supervisory register read rule by
rule (LESSONS C4); any new break gets `OWNER: P1.371`. Then `/postmortem` (§7).

### P1.372 — allocation dilution (D7)

Fixture wave adds FS-2's `amount` variant (500,000 on the 1,000,000 limit) and a collateral twin
(facility-level financial collateral of the same size) so both kernels are measured; test wave pins
§1.4's "before" column on every row **and** the recognised-total identity; engine wave lands the
kernel helper and routes the four sites. Register both variants in `RUNS`.

### P5.65 — owed measurements, no code

Counterparty-level guarantee on a losing member (the D7 residual); an RE-secured member whose
candidate splits `_sec`/`_res`; a candidate carrying an Art. 234 tranched guarantee (`__REM_FL` /
`__REM_SEN`, three legs). Each is a fixture + assertion that the D6 identities hold; any material
number becomes a Tier 1 bullet.

---

## 5. Gates that must move

- **`RUNS`** gains FS-2 (P1.371) and its two variants (P1.372). The fan-out's only existing portfolio
  has no CRM; after this batch the share path is exercised with a guarantee, an amount-based
  guarantee and facility collateral, in both regimes and — via FS-1's twins — both floor states.
- **D6 runtime check** is the portfolio-independent gate: it fires on any future splitter placed
  between the fan-out and the resolver, whatever the fixture estate looks like.
- **Resolver unit tests** get their first multi-leg groups. Today's `candidate()` helper builds one
  row per member and cannot express the defect (LESSONS C11).
- **`test_p1_307_facility_share_zero_rw_member_cannot_win.py`** — re-read before implementing: it
  reasons about `guarantor_rw` on a share and may pin per-row behaviour (LESSONS C1).

---

## 6. Documentation to change (in the same batch, not after)

- `docs/specifications/facility-share-allocation.md`: **Mechanism** (legs are the unit the resolver
  receives; the member is the unit it ranks), **Tie-breaks and the fallback** (D4 rungs), **What is
  exposed for audit** (D5 columns), new section **Interaction with CRM and real-estate splits**
  (D2 grammar, D6 invariant, D7 rule), **Known findings** (P5.65 residuals).
- `docs/plans/facility-share-riskiest-member.md` §2: a dated note under the "premise verdict"
  paragraph that "a guarantee on one member" multiplies the row rather than changing it, pointing
  here. Do not rewrite history in the design of record.
- `zensical.toml` nav: this page (done with this proposal).
- `.claude/LESSONS.md` (retro): *"A row-multiplying stage between a producer and its consumer turns
  per-row logic into per-leg logic."* Detect: before ranking, deduplicating or dropping on
  `exposure_reference`, list every producer of `parent_exposure_reference` / `split_parent_id`
  between you and your input (`registry.py` order), and write the conservation identity.

---

## 7. The escape-log entry (shape, for `/postmortem`)

- **Escape class:** `path-never-exercised` — the gate that would have caught it (a registered share
  portfolio with CRM) did not exist; FS-1 excluded CRM by design and said so. Note the contributing
  premise error in the design of record (§2), which is the *design-doc* form of `wrong-premise`.
- **Gate change:** FS-2 in `RUNS` (portfolio) **and** the D6 runtime identity (structural).
- **Verified red:** the P1.371 test-writer's failure lines on `master`: FS-2 winner `FS-CP-SA`
  against expected `FS-CP-LOW`; survivor EAD 160,000 against 200,000; resolver unit count 1 vs 2.
- **Code fix:** may follow the entry, not precede it (project closing rule).

---

## 8. Risks and traps

- **Ranking on legs is also how the FS-1 goldens were captured.** FS-1 has no CRM, so its numbers
  must not move; assert that explicitly (the two existing runs' goldens are the regression pin).
- **`_collapsed_reference` today collides two surviving legs on one name.** D2 must land with D1 —
  keeping the winner's legs without the three-column strip produces duplicate `exposure_reference`
  values on the sealed exit, which several reporting joins silently multiply.
- **`parent_exposure_reference` is a typed null on unguaranteed runs.** D1 does not key on it; D2
  must re-key it only where non-null.
- **`rwa_post_factor` is null on Basel 3.1 IRB rows** — rank on the caller-resolved
  `rwa_final` as today (`_utils.resolve_own_approach_rwa_col`); summing per member changes nothing
  here.
- **Mutation probes need a fresh process** (retro of PR #493): cached fixtures gave a false green.
- **The register counts mislead** (LESSONS C4): expect C 07.00 / C 08.01 rows to move when FS-2's
  guaranteed leg starts surviving; read every changed verdict.
- **Fixture parquets** are not involved — FS-1 and FS-2 are in-memory builders; nothing to register
  in `generate_all.py`.

---

## Appendix A — reproduction

Both scripts run from the repo root with `PYTHONPATH=. PYTHONIOENCODING=utf-8 uv run python …`.
They are not committed; the recipe is the FS-1 builders plus one guarantee row:

```python
frames = dict(counterparties=…FS-1 + {"FS-GUAR-BANK", entity_type="institution"},
              loans=_loans("nonbinding"), facilities=_facilities(),
              facility_mappings=_facility_mappings(),
              ratings=…FS-1 minus FS-RTG-LOW, plus external CQS 2 on FS-GUAR-BANK,
              model_permissions=create_firb_only_model_permissions())
guarantee = {"guarantee_reference": "FS-GUAR-001", "guarantor": "FS-GUAR-BANK",
             "beneficiary_type": "facility", "beneficiary_reference": "FS-FAC-SHARE",
             "percentage_covered": 0.8,  # or amount_covered=500_000.0
             "currency": "GBP", "maturity_date": date(2031, 12, 31)}
result = PipelineOrchestrator().run_with_data(
    make_raw_bundle(**frames, guarantees=pl.DataFrame([guarantee], schema=dtypes_of(GUARANTEE_SCHEMA))),
    facility_share_config("CRR"))
result.facility_share_resolution.collect()   # six rows, not three
result.results.collect().filter(pl.col("exposure_reference").str.contains("UNDRAWN"))
```

The single-member control is the same guarantee on `FS-FAC-SOLO` with `amount_covered = 150_000.0`.
