# Margined SFT — FCCM Extension (Orchestrated Implementation Plan)

> **Status:** Planned, not started · **Owner:** orchestrator (main session) · **Created:** 2026-06-20
> **Scope decision:** FCCM margined extension only. VaR (Art. 221) and IMM (Art. 283/285 full) SFT routes stay reserved.
> **Execution substrate:** per-phase **Workflow pipelines** (`plan → implement → review → challenge`), orchestrator-gated.

This is a *self-orchestrating* plan: it is written to be executed by the main session acting as an
orchestrator that launches one deterministic `Workflow` per phase. Each Workflow fans tasks through a
four-stage pipeline whose final stage is an adversarial 3-lens refute panel. The orchestrator adds a
fifth, human-in-the-loop gate: it independently challenges each phase's output, runs the validation
gate, and owns every git commit. Teammates never commit.

---

## 1. Why — the gap

The SFT path (`engine/sft/fccm.py`) implements **unmargined** FCCM only:

- The liquidation period is a **fixed module-load constant** `_LIQUIDATION_PERIOD_REPO = 5`
  (`fccm.py:66-67`, pack scalar `liquidation_period_repo`, `packs/common.py:603-606`).
- Haircuts are scaled with `H_10·√(T_m/10)` at that fixed 5-BD horizon only
  (`haircut_tables.py:96-119`).
- No SFT input field expresses a margin agreement, remargining frequency, or MPOR. `SFTConfig`
  (`contracts/config.py:586-605`) has a single `method` field.
- `fccm.py:27-28` docstring: *"Unmargined SFTs only … the margined FCCM extension lives in Art. 285
  and is not modelled."*

Consequence: a margined and an unmargined SFT compute **identical** `E*` / EAD / RWA today. (See the
margined-SFT investigation in this session; the adversarial verifier returned `refuted` on
"the setup supports margined SFT trades".)

## 2. Regulatory model to implement

FCCM core (already present, unchanged):

```
E* = max(0, E·(1 + HE) − C·(1 − HC − HFX))          (CRR Art. 223(5))
```

The extension adds a **per-netting-set holding period `T_M`** and a **margined branch**. The base
supervisory haircut `H_10` (Art. 224 Table 1, quoted at 10-BD daily revaluation) is turned into the
applied `H` by two composed scalings:

```
H = H_10 · √(T_M / 10) · √((N_R + T_M − 1) / T_M)     (Art. 224(2) period rescale + Art. 226 non-daily)
```

Two **mutually-exclusive** branches set `T_M` and decide whether the non-daily term applies:

| Branch | Condition | `T_M` | Non-daily Art. 226 term |
|---|---|---|---|
| **Unmargined / simply-collateralised** | not under a qualifying Art. 285 margin agreement | transaction-type period — **5 BD** for repo/sec-lending (Art. 224(2)(b)) | applied when revaluation frequency `N_R > 1` |
| **Margined** | under a qualifying margin agreement (Art. 285(2)–(4)) | `T_M = MPOR` per Art. 285 | **not** separately applied — `MPOR = F + N − 1` already encodes remargin frequency |

MPOR floors (Art. 285(2)–(5)), regime-invariant mechanics:

- `F = 5` BD for netting sets of **only** repos / securities-or-commodities lending / margin lending;
- `F = 10` BD otherwise;
- `F = 20` BD for sets > 5000 trades, or with illiquid collateral / hard-to-replace positions;
- `F` **doubled** for two quarters after > 2 margin-call disputes;
- for remargining periodicity `N` business days, `MPOR = F + N − 1`.

> **Correctness traps the Challenge stage must verify against citations:**
> 1. Art. 226 is `√((N_R + T_M − 1) / T_M)` — **not** `√(N_R / T_M)`. At `N_R = 1` it must collapse to 1.0. (Art. 226 has no numbered paragraphs; the `√(T_M/10)` period rescale is Art. 224(2), not "Art. 226(2)".)
> 2. The two branches are exclusive: do **not** stack Art. 226 non-daily scaling on top of an Art. 285 `F+N−1` MPOR.
> 3. At `is_margined = false, N_R = 1` the result must be **bit-identical** to today's output (regression guard).

Optional companion (Art. 227 — repo 0% carve-out): both legs cash or 0%-RW sovereign, same currency,
and either ≤ 1-day maturity or daily MtM / daily remargining ⇒ `H = 0`. **Scoped as an optional task in
Phase 2**; defer if it expands the blast radius.

Both regimes are covered by reading regime-resolved pack values — no `config.is_crr` / `is_basel_3_1`
branching (arch_check check 17).

## 3. Non-goals (explicit)

- VaR SFT EAD (Art. 221) and full IMM / Effective-EPE (Art. 283/285) — remain `NotImplementedError`.
- Multi-trade / multi-counterparty SFT netting sets (FCCM scope stays Art. 220(1)(a) single-CP).
- Fixing the pre-existing `is_basel_3_1=False` hardcode in `fccm.py:336,360` (SFT FCCM currently always
  reads CRR haircut tables). **Discovered adjacent gap — logged in §8, not in scope** unless promoted.

## 4. Architecture touchpoints

| Area | File(s) | Change |
|---|---|---|
| Input contract | `data/schemas.py` (SFT_TRADE_SCHEMA ~1118-1168) | **DONE (Phase 0).** Denormalised margining cols added (all `required=False`): `is_margined` (Bool, False), `remargining_frequency_days` (Int16, 1 — dual-purpose `N_R`/`N`), `mpor_floor_category` (String enum `repo_only`/`other`/`illiquid_or_large` → F=5/10/20, supersedes a lone illiquid Bool because Art. 285(3) has two F=20 triggers), `has_margin_dispute_doubling` (Bool, False — Art. 285(4)), `mpor_days_override` (Int16, null = "derive me"). Constrained via `VALID_MPOR_FLOOR_CATEGORIES` in `COLUMN_VALUE_CONSTRAINTS['sft_trades']` |
| Config | `contracts/config.py` (SFTConfig 586-605) | no new field expected — margining is per-trade data, not config; confirm during planning |
| Bundles / edges / loader | `contracts/bundles.py`, `contracts/edges.py` (SFT_TABLE_EDGES 409-436), `engine/loader.py` (`_build_raw_sft_bundle` 664-710), `config/data_sources.py` | carry new optional cols through the standard seal (`required=False`, defaulted) — additive, no brand change |
| Pack scalars | `rulebook/packs/common.py` (~603) | add cited MPOR-floor scalars (`mpor_floor_repo=5`, `mpor_floor_default=10`, `mpor_floor_illiquid=20`) + dispute-doubling rule constant; keep `liquidation_period_repo` |
| Haircut math | `engine/crm/haircut_tables.py` (`scale_haircut_for_liquidation_period` 96-119) | add Art. 226 non-daily form (new helper `scale_haircut_for_non_daily_revaluation` or extend signature with `revaluation_freq_days`) |
| Engine | `engine/sft/fccm.py` | replace module-constant `T_M` with per-NS derivation; add margined-vs-unmargined branch; thread `T_M`/`N_R` into `_compute_exposure_haircut` / `_compute_collateral_cva_contribution` |
| Reporting | `reporting/corep/*`, `reporting/pillar3/*` | confirm margined SFT EAD flows into the existing CCR/SFT rollups (C07 row 0090 etc.) — likely no change, verify |
| Tests | `tests/fixtures/ccr/sft_bundle_builder.py`, new acceptance scenarios under `tests/acceptance/ccr/` | margined vs unmargined hand-calcs; daily vs N-day remargin; regression-identical unmargined |
| Docs | `docs/specifications/`, `docs/appendix/changelog.md` | document the margined branch + citations |

## 5. Phases

Each phase is one `Workflow` run (§6). A phase's tasks that touch the **same engine file** are merged
into a single pipeline item (worktree-merge safety, mirroring the repo's shared-file single-stream rule).

### Phase 0 — Regulatory design + input contract
- **0a (plan-only, no code):** author the authoritative hand-calc + citation map for the §2 model — the
  exact Art. 224/226/285 interaction, the branch table, and 3 worked numeric examples (unmargined daily,
  unmargined 3-day remargin, margined 5-trade repo set with N=2). This is the spec the rest of the phase
  and the Challenge panels verify against.
- **0b:** add margining columns to `SFT_TRADE_SCHEMA` (+ `COLUMN_VALUE_CONSTRAINTS` if needed), thread
  through bundles / edges / loader / data_sources as additive optional fields; extend
  `sft_bundle_builder.py`.
- **Acceptance:** schema/bundle/edge contract tests green; existing SFT tests unchanged (fields default to
  unmargined); arch_check + ruff + ty + contracts pass.

### Phase 1 — Pack scalars — **DONE via reuse (no new scalars)**
The Art. 285 MPOR floors + dispute-doubling already exist in `packs/common.py` (added for the SA-CCR
margined maturity-factor cascade; values/citations are regime-invariant). Phase 2 consumes these:
- `mf_margined_floor_days_repo_sft=5` (285(2)(a)) ← `mpor_floor_category='repo_only'`
- `mf_margined_floor_days_otc=10` (285(2)(b)) ← `'other'`
- `mf_margined_floor_days_large_or_illiquid=20` (285(3)) ← `'illiquid_or_large'`
- `mf_margined_dispute_multiplier=2` (285(4)) ← `has_margin_dispute_doubling`
- `liquidation_period_repo=5` (224(2)(b)) ← unmargined branch (a) `T_M`
- `zero_haircut_max_sovereign_cqs=1` (227(2)(a)) ← optional 2c carve-out
Verified: all resolve identically for `crr` and `b31`; already covered by `test_sa_ccr_factors.py` /
`test_liquidation_period_haircuts.py`. **Naming note for Phase 2:** the `mf_margined_*` prefix is
SA-CCR-flavoured; reuse as-is (values/citations are authoritative) and add a clarifying comment — a
neutral `mpor_floor_days_*` alias is optional cleanup, out of scope.

### Phase 2 — Engine (the core)
- **2a:** add the Art. 226(1) non-daily helper to `haircut_tables.py` with unit tests pinning
  `N_R=1 ⇒ ×1.0` and a known multi-day value.
- **2b:** in `fccm.py`, derive per-NS `T_M` (MPOR vs transaction-period branch) from the new trade
  columns; thread `T_M` and `N_R` into the two haircut helpers; keep the unmargined default path
  bit-identical.
- **2c (optional):** Art. 227 0% repo carve-out.
- **Acceptance:** new unit tests for both branches; the unmargined regression golden (CCR-A12 family)
  unchanged to ≤ 1 ppm; full validation gate green.

### Phase 3 — Acceptance scenarios
- New `tests/acceptance/ccr/` scenarios with golden fixtures: margined vs unmargined same trade;
  daily vs 5-day remargin; margined repo-only set MPOR=5 vs mixed set MPOR=10. Each with a hand-calc
  derived in 0a.
- **Acceptance:** scenarios green; numbers match the 0a hand-calcs exactly.

### Phase 4 — Reporting, docs, changelog
- Verify margined SFT EAD lands correctly in COREP C07 / Pillar 3 SFT rollups (add a reporting test if a
  gap is found).
- Update `docs/specifications/` (SFT/FCCM page), `fccm.py` module docstring (remove the "unmargined only"
  scope note), and `docs/appendix/changelog.md`.
- **Acceptance:** `uv run zensical build` clean; changelog entry present; watchfire citation matrix
  includes the new Art. 226/285 bindings.

## 6. Orchestration model — Workflow pipelines

Each phase runs as a single `Workflow`. The reusable shape:

```
phase('Plan');  phase('Implement');  phase('Review');  phase('Challenge')

pipeline(
  TASKS,                                   // this phase's task specs (often 1–3)
  // 1. PLAN  — read-only design: regulatory hand-calc, file/diff plan, test list.
  t        => agent(planPrompt(t),   {label:`plan:${t.id}`,   phase:'Plan',      schema: PLAN_SCHEMA}),
  // 2. IMPLEMENT — TDD (failing test first), minimum diff, worktree-isolated.
  (plan,t) => agent(implPrompt(t,plan), {label:`impl:${t.id}`, phase:'Implement', isolation:'worktree', schema: IMPL_SCHEMA}),
  // 3. REVIEW — runs the validation gate, checks standards/altitude, returns pass|revise.
  (impl,t) => agent(reviewPrompt(t,impl), {label:`review:${t.id}`, phase:'Review', schema: REVIEW_SCHEMA}),
  // 4. CHALLENGE — 3 independent lenses, each prompted to REFUTE; majority refute => fail.
  (rev,t)  => parallel(['regulatory-fidelity','correctness-edge','standards-arch'].map(lens => () =>
                agent(challengePrompt(t,rev,lens), {label:`challenge:${t.id}:${lens}`, phase:'Challenge', schema: VERDICT_SCHEMA})))
              .then(v => ({task:t, review:rev, verdicts:v.filter(Boolean)})),
)
```

**Stage contracts:**

- **Plan** (read-only). Produces: regulatory derivation citing Art. 224/226/285, exact diff plan
  (files + line anchors), the failing-test list, and the expected-numbers hand-calc. For Phase 0a this
  *is* the deliverable.
- **Implement** (`isolation: 'worktree'`). TDD discipline embedded in the prompt: write the failing test
  first, minimum diff, then make it pass. Must run `uv run python scripts/arch_check.py`, `ruff`, `ty`,
  and the touched contract tests **inside the worktree** before returning. Returns the diff summary +
  gate output.
- **Review.** Re-runs the validation gate independently, checks module-narrative/altitude/naming against
  CLAUDE.md, confirms no `config.is_*` branching and no engine-scope regulatory scalars. Returns
  `pass | revise` with specifics.
- **Challenge** (adversarial, 3 lenses, each defaults to `refuted` when uncertain):
  - `regulatory-fidelity` — does the math match Art. 224/226/285 and the 0a hand-calc? Catches the
    `√(N_R/T)` vs `√((N_R+T_M−1)/T_M)` trap and branch-stacking.
  - `correctness-edge` — `N_R=1` collapse, unmargined regression identity, null/ineligible collateral,
    same-currency HFX=0, MPOR floor boundaries.
  - `standards-arch` — arch_check rules, immutability, no namespaces, pack-as-value-home, citation
    decorators present.
  - **Verdict rule:** ≥ 2 of 3 `refuted` ⇒ the task fails the Challenge and returns to the orchestrator
    for a revision dispatch (one retry; a second failure ⇒ the orchestrator decides drop/redesign).

**Orchestrator gate (the fifth stage — me, between phases):** after a phase Workflow returns I will
(1) read every task's review + 3 verdicts; (2) **independently** run the full validation gate in the
main tree on the merged worktree branch; (3) apply my own challenge — re-derive at least one hand-calc
and diff it against the implementation; (4) **only then** squash-merge the worktree branch and commit;
(5) advance to the next phase. A failed gate or an unrefuted-but-wrong number stops the phase and
re-dispatches. I never let a teammate's green self-report substitute for my own gate run.

**State & resume.** Phase progress is journaled to `.claude/state/margined-sft-fccm.json`
(`{phase, status, batch_id, worktree_branch, run_id, verdicts}`), written atomically. Each phase
Workflow's `runId` is recorded so a stalled phase can be resumed with
`Workflow({scriptPath, resumeFromRunId})` (cached unchanged stages return instantly). I read this file
at the start of every orchestration turn before reacting.

**Validation gate (canonical, run by Implement, Review, and the orchestrator):**
```
uv run python scripts/arch_check.py && uv run ruff check . && uv run ruff format --check . \
  && uv run ty check && uv run pytest tests/contracts tests/unit/<touched> -q
```
plus `uv run pytest tests/ -m 'not slow and not stress and not benchmark'` at the orchestrator gate for
Phases 2–4, and `uv run zensical build` for Phase 4.

## 7. Runbook (how the orchestrator executes)

1. Read `.claude/state/margined-sft-fccm.json` (create on first run, `phase: 0`).
2. For the current phase: author the per-phase Workflow script (embed `TASKS` + the §6 stage prompts +
   the schemas), launch it in the background, end the turn.
3. On completion notification: read structured results, run the orchestrator gate (§6), update state.
4. If the gate passes: squash-merge worktree branch into `feat/sft-phases` (current feature branch),
   commit with a `feat(sft)`/`refactor(sft)` message + the `Co-Authored-By` trailer, advance `phase`.
5. If it fails: re-dispatch the failing task (one revision), or stop and surface to the user for a
   scope/design call.
6. After Phase 4: open/refresh the PR per the repo's PR workflow; do not push without the user's go.

The user can interject at any turn (status, drop a task, inspect a diff, change scope) — the state file,
not the conversation, is the source of truth.

## 8. Risks & open questions

- **Art. 224/226/285 interaction** is the genuine regulatory subtlety; Phase 0a must settle the exact
  branch semantics with citations before any code. Treat 0a's hand-calc as load-bearing.
- **`is_basel_3_1=False` hardcode** (`fccm.py:336,360`) means SFT FCCM currently ignores the B31
  recalibrated haircut tables. Adjacent to this work; **decide** whether to fix it here or log a separate
  `IMPLEMENTATION_PLAN.md` item. *(Recommend: separate item — keeps margined scope clean.)*
- **Grain.** Margining is a netting-set property; we denormalise onto the trade (consistent with how
  `counterparty_reference` is handled under single-CP scope). A future multi-trade NS would want a proper
  SFT netting-set / margin table — note in code, don't build now.
- **Worktree merges** for same-file tasks: enforce the single-stream merge rule per phase to avoid
  conflicts on `fccm.py`.
- **Determinism.** Polars group-by float sums are not process-deterministic (per migration notes); pin
  acceptance tolerances at ≤ 1 ppm, not bit-equality, for aggregated numbers — except the unmargined
  regression which must stay within the existing CCR-A12 tolerance.

### Phase 0 outcomes (carried into later phases)

- **Deferred branch-(a) `T_M` limit (Phase 2 watch-item):** the engine hardcodes `T_M = 5 BD` (repo)
  for the whole FCCM path; no field expresses an SFT transaction sub-type, so a 20-BD secured-lending or
  10-BD other-capital-market SFT's `T_M` cannot be represented. Pre-existing and design-scoped to repo —
  acceptable for now. If non-repo SFT scenarios land, add a transaction-type field; otherwise keep the
  5-BD repo assumption explicit in Phase 2.
- **Dormant value-constraint (Phase 2/3 watch-item):** `COLUMN_VALUE_CONSTRAINTS['sft_trades']`
  (`mpor_floor_category`) is declared but not yet enforced — `validate_bundle_values`' `frame_mapping`
  omits `sft_trades` (mirrors the existing dormant `trades` entry). Wire the SFT frame into validation
  when the engine starts consuming the field.
- **Stale engine citations to fix in Phase 2/4:** `engine/sft/fccm.py` still cites `Art. 224(2)(c)` for
  the 5-BD repo period (correct = `Art. 224(2)(b)`) and `Art. 226(2)` for the period rescale (Art. 226
  has no numbered paragraphs; the rescale is Art. 224(2)). Left untouched in Phase 0 (carry-only); fix
  when Phase 2 edits the file and refresh the module docstring in Phase 4. **DONE** (Phases 2 + 4) for
  the SFT/FCCM subsystem (`fccm.py`, `sft/__init__.py`, the two touched `haircut_tables.py` docstrings,
  CCR-A11/A12 docstrings, SFT spec doc).

### Follow-up (out of this scope — separate item)

- **Codebase-wide `Art. 226(2)` mis-citation.** The same `Art. 226(2)` convention is used pervasively in
  the broader CRM haircut path (`engine/crm/haircuts.py` ×7, `packs/common.py`, several basel31 tests,
  and a test literally named `test_p2_18_art_226_1_...`). Phase 0's CRR-PDF reading (twice-verified) says
  Art. 226 has no numbered paragraphs and the `√(T_M/10)` rescale is Art. 224(2). Before any mass change,
  open a **focused investigation** to confirm this against the authoritative UK CRR text (the `art_226_1`
  test name suggests a prior contrary belief) — then de-stale repo-wide in one dedicated pass. NOT folded
  into the margined-SFT work to avoid touching unrelated subsystems.
```
