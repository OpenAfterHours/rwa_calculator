# Closing the gap between our tests and our users' data

**Status:** Proposal, 2026-08-12. Written from a review of the validation estate on
`fix/distribution-gate-and-escapes`. Every number below is measured on that branch and
reproducible with the commands quoted.

## The finding in one sentence

The test estate proves that **correct inputs produce correct outputs**; it has almost
nothing that proves **incorrect inputs produce an error rather than a plausible number** —
and the input contract that would enforce that is written, tested, and not connected to
the pipeline.

## The mechanism

Three things compound.

**1. The input domain is undeclared for numbers.** `COLUMN_VALUE_CONSTRAINTS` covers 51
string columns. Of 879 declared columns across 56 schemas, 123 are numeric and **none**
carries a range constraint — there is no range mechanism in `ColumnSpec` at all. 36 of
those numeric columns have obviously bounded regulatory domains (`pd`, `lgd`, `ltv`,
`cqs`, `delta`, `rate`, `ccf_modelled`, the maturity columns).

**2. The guards that would catch it are unreachable from production.** 10 of the 14
public validators in `contracts/validation.py` — 402 lines — cannot be reached from
`src/`:

| Validator | Lines | What it would catch |
|---|---|---|
| `validate_pd_range` | 23 | PD outside (0, 1] |
| `validate_lgd_range` | 23 | LGD outside [0, 1] |
| `validate_ccf_modelled` | 34 | CCF outside its domain |
| `validate_non_negative_amounts` | 29 | Negative exposure amounts |
| `validate_aggregated_bundle` | 80 | **Output bounds** — RW > 1250%, RW < 0, RWA < 0, null EAD |
| `validate_schema` | 60 | Declared-vs-actual schema drift |
| `validate_schema_to_errors` | 58 | as above, error-accumulating form |
| `validate_required_columns` | 23 | Missing required columns |
| `validate_raw_data_bundle` | 39 | (no callers at all, including tests) |
| `validate_resolved_hierarchy_bundle` | 33 | (no callers at all, including tests) |

Only `validate_bundle_values`, `scrub_non_finite_values`, `validate_column_values` and
`validate_collateral_links` are wired. All ten unreachable validators have green unit
tests — 48 of them pass in 2.7 seconds, testing code that never runs on customer data.

**3. Polars turns absence into a number, not an error.** A null predicate takes the
`otherwise` branch; nulls vanish from `sum()`; `fill_null(0.0)` is applied at the
aggregation boundary (`engine/aggregator/aggregator.py:205`). The engine's own debt
ratchet records **472 `fill_null` sites and 358 presence guards**
(`scripts/arch_metrics.json`). Each is a place where missing data becomes a confident
value.

The consequence is that **the engine's effective input domain is the union of the shapes
our fixtures happen to have.** That is not a new observation and not my phrasing — it is
the root-cause line in
[engine-defensiveness-boundary-hardening.md](engine-defensiveness-boundary-hardening.md),
written 2026-05-29, which also states plainly that "the `contracts/validation.py` bundle
validators were never wired into `pipeline.py`." That sentence is still true 2.5 months
later. Customers supply shapes outside our fixture union on day one.

## Evidence

Measured on this branch: CRR, £1m senior corporate, F-IRB where PD/LGD apply.

| Input | Engine returns | Correct answer | Signal raised |
|---|---|---|---|
| PD = 1.5 (feed sent `1.5` meaning 1.5%) | RWA **£603.67** | £1,119,286.69 | none |
| LGD = −0.2 | RWA **£0.00** | reject | none |
| PD = −0.01 | RWA £153,101.81 (silently floored) | reject | none |
| Maturity = −3 years | RWA £776,750.85 (silently → 0) | reject | none |
| LGD = 1.8 | RWA £3,914,232.38 | reject | none |
| CQS = 0, 7 or 99 on a corporate | RW 100% | reject — domain is 1–6 | none |

No exception, no null, no `CalculationError` in any case. Every one returns a number a
reviewer would accept.

The first row is the one that will reach a customer. A risk feed that expresses PD in
percent rather than as a fraction understates capital by **99.9461%** — a £1,118,683
shortfall on every £1m of exposure — silently. Out-of-domain CQS moves capital in both
directions: 100% against a true 20% at CQS 1 (5× overstatement), and 100% against 150%
at CQS 6 on an institution (understatement).

Reproduce:

```bash
.venv/bin/python scripts/validator_reachability.py   # the 10-of-14 census
```

## What this means for the test estate

The estate is large and genuinely sophisticated — 1,081 test files, a human-reviewed
oracle, conformance re-derivation, hypothesis property tests, a defect-injection harness,
several two-way ratchets. None of that is wasted and none of it should be disturbed.

But it is organised on a single axis: **by regulatory rule** — *does Art. 123 work?*
Every generator in it starts from a valid portfolio. `tests/properties/strategies.py`
bounds PD to `[0.0003, 0.20]` and amounts to `≥ £10k`, with every field populated; the
docstring is explicit that these ranges "are the coverage this suite actually has". That
is a good suite answering a different question.

What is missing is a second axis: **by input pathology** — *what happens when the data is
wrong?* That axis is where our users are, and it is empty.

## The plan

### Phase 0 — Wire what already exists, then make un-wiring impossible

*1–2 days. Highest return in the codebase — the code is written and tested.*

> **Done, 2026-08-12** (commit `6216ba41`). Census: 10 of 14 unreachable → 0 of 9.
> Three things resolved differently from how they are written below, each
> deliberately:
>
> - **"Wire or delete" resolved as a deletion of FIVE validators, not the two
>   named.** `validate_schema`, `validate_required_columns` and
>   `validate_schema_to_errors` went too. `RawDataBundle.__post_init__` raises
>   via `require_brand` on any unsealed frame, and `conform_lenient`
>   (`contracts/edges.py`) injects missing required columns as typed nulls
>   (DQ001), casts every mismatched dtype with `strict=False` and strips
>   extras — so a schema-shape check downstream of that seal is *structurally
>   incapable of firing*. They were unfirable, not merely unwired. `DQ003`
>   (`ERROR_TYPE_MISMATCH`) is now a reserved code with no producer.
> - **The gate was wired at the pipeline entry as well as the loader.**
>   `validate_bundle_values` was reachable only from `engine/loader.py`, so the
>   in-memory `run_with_data` entry had no input gate at all. The loader path
>   de-duplicates on an exact set difference over the frozen error dataclass.
> - **PD's domain is `[0, 1]`, closed at zero — not the `(0, 1]` written under
>   Phase 1 below.** CRR Art. 160(1) does not reach central governments or
>   central banks and the CRR pack carries `pd_floors["sovereign"] = 0`, so a
>   half-open domain would reject every sovereign IRB exposure priced at zero
>   and generate false errors on valid customer data.
>
> The predicted fixture churn **did not materialise**: a scan of all 504
> `tests/fixtures/**/*.parquet` for out-of-domain PD/LGD/CCF and negative
> amounts flagged zero file-columns, so the ERROR-severity gate carries no
> latent fixture debt. Escape-log entry: 2026-08-12, class `gate-not-run`.

- Wire the four numeric-range validators into `validate_bundle_values`.
- Wire `validate_aggregated_bundle` at the pipeline exit, so output bounds are checked on
  every run.
- Wire or delete `validate_raw_data_bundle` / `validate_resolved_hierarchy_bundle`. Dead
  code shaped like a guard is worse than no guard — it reads as coverage.
- **Graduate it:** `arch_check` check 20 — every public function in
  `contracts/validation.py` must be transitively reachable from `src/`.
  `scripts/validator_reachability.py` is the working seed.

Expect fixture churn: turning the PD/LGD range checks on will red-flag existing fixtures
carrying out-of-domain values. Those reds are the point, not an obstacle.

This is the **fifth instance of the project's dominant meta-pattern** — build the
instrument, stop before wiring it. Three escape-log entries are already classed
`gate-not-run` for exactly this, and the log itself names the habit: "the estate's habit
is to build the measurement and stop before wiring it." Check 20 is what stops the sixth
instance, in the same way check 14 killed Polars namespaces as a category.

### Phase 1 — Declare the input domain as data

*3–5 days.*

The root cause is that the domain lives in people's heads.

- Add an optional `domain` to `ColumnSpec` — a numeric interval or an enum set, unifying
  with `COLUMN_VALUE_CONSTRAINTS`.
- Populate the 36 bounded-domain numeric columns first: `pd`, `lgd`, `lgd_unsecured`,
  `ltv`, `prior_charge_ltv`, `property_ltv`, `cqs`, `sovereign_cqs`, `delta`, `rate`,
  `haircut_override`, `ccf_modelled`, `*_maturity_years`.
- One generic validator reads the declaration, so a new column gets validation by being
  declared rather than by someone remembering.
- Ratchet the count of columns carrying a declared domain, two-way, like
  `coverage_baseline.json`.

The payoff is not the validation. It is that **the declaration becomes a generator** —
Phase 2 fuzzes directly off it, so the domain is stated once and used twice.

### Phase 2 — Fuzz the pathology axis end-to-end

*1–2 weeks. This is the missing test space.*

A new suite, `tests/robustness/`, driving the **full pipeline** rather than
`calculate_branch`, asserting a triage invariant instead of a number:

> For every input row, exactly one of: (a) it carries a finite, in-bounds result, or
> (b) a `CalculationError` names it.

That invariant needs no hand-derived expected value, so it scales to millions of
generated shapes — and it is precisely the invariant that "silently returns a plausible
number" violates. Generators to build, in rough priority order:

1. **Unit-scale errors** — ×100 and ÷100 on every ratio column. The highest-probability
   real defect, and the one measured above.
2. Out-of-domain numerics, driven off the Phase 1 declarations.
3. Null each optional field in turn, one at a time, across a known-good portfolio.
4. Unknown enum strings, including case variants and whitespace.
5. Sign flips on amounts; duplicate keys; orphan foreign keys.
6. Structural extremes — empty tables, single row, missing optional files, 1M rows.

Run it nightly rather than in the dev loop; it is a search, not a regression check.

### Phase 3 — Make absence loud

*2–3 weeks, incremental. Sequence after Phase 2.*

> **Done for two of the four paths, 2026-08-12.** SA risk weight
> (`sa_risk_weight_branch_reason`) and IRB LGD (`irb_lgd_branch_reason`) are
> instrumented; **CRM substitution and guarantor lookup are NOT started**, and
> that is a deliberate stop rather than an oversight — see below. Resolved
> differently from how it is written:
>
> - **The reason column is a `pl.Enum`, and that is load-bearing, not an
>   optimisation.** "A branch reached by zero rows is a finding" is
>   unimplementable over a `String` column: it carries the values that occurred
>   and is silent about the ones that did not. An `Enum` carries its categories
>   in the *dtype*, so the census reads the declared population off the schema
>   and the reached population off the data. It is also 6.2x cheaper.
> - **One `decide()` primitive, not four hand-written reason chains.** Value and
>   reason are built from the SAME predicate objects
>   (`engine/branch_reason.py`), so they cannot drift — the B3 trap, in a shape
>   that would have been invisible.
> - **Two paths, not four.** Instrumenting the guarantor chain
>   (`sa/guarantor_rw.py`, 11 branches, consumed by BOTH the SA and IRB
>   substitution paths) needs a provable value-equivalence argument per branch
>   per regime; CRM substitution lives in `crm/guarantees.py`, which sits on the
>   `max_engine_module_loc` ratchet with **one line** of headroom and cannot be
>   touched without an extraction first. Half-instrumenting either would have
>   produced exactly the "reads as coverage" artefact this proposal exists to
>   close, so the `GuarantorRwReason` vocabulary that had been drafted was
>   **deleted** rather than shipped without a producer — the same call Phase 0
>   made about its five unfirable validators.
> - **BR001 is a WARNING, not an ERROR.** An `UNKNOWN_FALLBACK` row is
>   *unjustified*, not provably wrong. ERROR would have reddened every run
>   touching the two known-open defects the instrument was built to expose, and
>   a gate that reddens on a pre-existing defect gets switched off rather than
>   fixed. The census ratchets the population; the error names the rows.
>
> **What the first census found**, over 14 portfolios x 2 regimes:
>
> - **The Art. 121(6) sovereign floor never binds anywhere in the estate.**
>   `floor_bound` and `floor_not_binding` are both dead across all 28 runs. The
>   30 existing unit tests all supply `cp_local_currency` explicitly, which is
>   precisely the path production rows do not take.
> - **P1.333's prescribed one-line fix is unsafe, and the census measured it.**
>   The only two rows in the estate that reach the rule are a QCCP netting set;
>   applying `fill_null(False)` moves it from RW 2% to 100% (RWA 109,933.82 ->
>   5,496,700) against the Art. 306 pin. Its null also does not come from the
>   non-EU `replace_strict` path the bullet blames — the row is GB/GBP, and the
>   null enters through `denomination_currency_expr` reading a null
>   `original_currency`. Filed as **P1.342**, to sequence before P1.333.
>
> Cost, measured at 60,000 rows: 296 -> 298 columns, **+0.13%** of frame bytes
> (~1.06 bytes/row/column), **+9.9%** wall (1.672s -> 1.837s). The time, not the
> space, is the real cost — each predicate is evaluated a second time for its
> nullity test.

`otherwise` is doing double duty: "the rule does not apply" and "I do not know".
Separating them is what turns a silent fallback into a finding.

- On the high-stakes paths — SA risk weight, IRB LGD, CRM substitution, guarantor lookup
  — emit a `*_branch_reason` column beside the value.
- Assert that no row lands on `UNKNOWN_FALLBACK` without an accompanying error.
- This delivers the **branch census** already filed as a plan idea: a run-level histogram
  of which branch each row took. Ratchet it — a branch reached by zero rows across the
  entire fixture estate is either dead code or an untested path, and both are findings.

Two known-open defects would have been caught by this and are the natural first targets:
the Art. 121(6) sovereign floor silently dead for every non-EU counterparty, and the
guarantor-side institution/PSE/RGLA coarse country fallback.

Phase 2 should run first because it tells you which branches actually absorb bad data.

### Phase 4 — Bring real data shapes in

*Ongoing; start in parallel with Phase 1.*

Fuzzing finds *classes* of defect; only real portfolios find *shapes*.

- Build a corpus of anonymised or realistically-messy customer-shaped portfolios —
  nested facilities, partial collateral links, absent optional files, unusual entity
  mixes — and register them in `RUNS` for the nightly run. Every escape recorded so far
  was found by someone holding real data.
- Make repro-first standing policy on user reports: reproduce the customer's actual input
  shape before concluding the engine is correct.
- **Drain the parked registers.** Measured on `fix/input-domain-correctness`, 2026-08-12:
  **8** entries in `KNOWN_DISAGREEMENTS`, **7 of them understating capital** — six FCSM
  cases at 10.0% each and `ORC-280` at 33.3% — plus `ORC-142`, which runs the other way
  (the engine applies a 373,345.27 mortgage-floor adjustment where the oracle applies
  0.00, so it is conservative, and its limb is *unrepresentable* rather than mis-gated).
  A further **8** sit in `tests/conformance/classification_table.toml` as
  `[[known_disagreement]]` D1–D7 including D1b, plus roughly 25 open defect items.

  An earlier draft of this bullet said "11 entries, 8 of them understating capital". Both
  figures were wrong by the time anyone read them, and that is the argument for the fix
  rather than a footnote to it: 11 was the count at the moment `docs/development/escape-log.md`'s
  2026-08-09 entry 4 was corrected, three of which (the Art. 121(1) Table 5 family — `ORC-105`,
  `ORC-020`, `ORC-109`) were discharged hours later by P1.316. **A register whose size lives in
  prose is stale the moment the register moves.**

  The `caught-and-parked` escape class already names the failure mode: a gate fired, the
  finding was recorded, and the wrong number shipped anyway. Ratchet the size of every
  tolerated-findings register so it can only shrink.

  **Done (P5.41, 2026-08-12)** for the two registers that had no ratchet at all. One shared
  mechanism — `scripts/tolerated_findings.py` — now backs all four: the two declared
  registers above are gated shrink-only by `scripts/check_parked_registers.py --check`
  (run in-suite by `tests/contracts/test_parked_register_ratchet.py`), and the measured
  supervisory register (`known_broken_rules` / `known_uncovered_templates` /
  `known_vacuous_rules`) routes its seven legs through the same set-diff. Every one of the
  16 declared entries now names the plan bullet that owns it. Draining them is still owed,
  and is the point — the ratchet only stops the population growing while that happens.

## Sequencing

| Phase | Effort | What it finds | When |
|---|---|---|---|
| 0 — Wire the validators, add check 20 | 1–2 days | Out-of-range PD/LGD/CCF/amounts; out-of-bounds outputs | Now |
| 1 — Declare the domain | 3–5 days | Nothing directly; enables Phase 2 | Next |
| 2 — Pathology fuzzing | 1–2 weeks | The bulk of latent silent-wrong-number defects | Then |
| 3 — Branch reasons + census | 2–3 weeks | Silently dead regulatory limbs | After 2 |
| 4 — Real-data corpus | ongoing | Shapes nobody imagined | In parallel |

## What to do first

Phase 0, this week. It is a two-day change that switches on five guards that are already
written and already tested, and check 20 converts "we forgot to wire it" from a recurring
escape class into a build failure. Everything after it is a larger bet. That one is
already paid for — we are simply not collecting.
