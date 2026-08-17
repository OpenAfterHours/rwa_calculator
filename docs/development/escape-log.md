# Escape log

A record of defects that **reached production**, and — the point of the file —
what now stops each one from happening again.

Every entry is written by `/postmortem`. The command's deliverable is not the
code fix; it is the answer to a single question:

> Which gate should have caught this, and why didn't it?

A defect that produced a fix commit and nothing else has taught the system
nothing, and will be paid for again. A defect that produced a new check, a new
fixture in `RUNS`, or a re-anchored assertion has been converted into
permanent capability.

## How to read an entry

- **Escape class** determines the fix:

  | Class | Meaning | Fix |
  |---|---|---|
  | `gate-not-run` | a catching gate existed but didn't run at that point | move the gate earlier |
  | `path-never-exercised` | the gate ran but no fixture reached the code | build the portfolio, register it in `RUNS` |
  | `test-shared-the-assumption` | a test covered it and passed, written from the same wrong sentence | re-anchor to a source of truth |
  | `no-assertion-of-presence` | output was absent/null rather than wrong | assert presence |
  | `wrong-premise` | the plan bullet was wrong and was faithfully implemented | strengthen Wave 0 |
  | `no-gate-exists` | nothing could have caught it | create the gate |
  | `ungateable` | not mechanically detectable | `.claude/LESSONS.md` entry, with reasoning |
  | `caught-and-parked` | a gate fired, and the record of the finding became its resting place | ratchet the finding register; give every parked entry an owning bullet |

  `caught-and-parked` was added on 2026-08-09. It is for the case where a gate did
  catch it, said so, and the wrong number shipped anyway. It is a distinct class
  because its fix targets **the register of tolerated findings** rather than the
  output — the only one of the eight that does — and because the shape recurs
  across at least four parallel registers here (`KNOWN_DISAGREEMENTS`,
  `classification_table.toml`'s `[[known_disagreement]]`, `known_broken_rules`,
  `known_vacuous_rules`) plus strict xfails and plan bullets. Note that
  `no-gate-exists` would prescribe roughly the right fix, so narrative fidelity
  alone is not the argument.

  An entry may also carry **no class**, and say why. A defect *in* a gate is not a
  defect that escaped one, and the eight classes all presume the latter — so
  forcing a class on it would prescribe the wrong fix. Leave the field unclassed
  with the reasoning, and name the class you would coin if it recurs.

- **Verified red** records the command and the failure line, confirming the new
  gate fails *without* the fix. A gate nobody has seen fail is not a gate. Along
  with the escape class and the gate change, it is what closes the defect: an
  entry missing any of the three means the defect is still open, whatever
  landed in `src/`.

## Related

- `.claude/LESSONS.md` — the working set of traps every agent reads before
  starting. Entries graduate out of it into executable checks.
- `scripts/arch_check.py` — the numbered architectural invariants. Each one is
  a lesson that graduated.
- `tests/acceptance/reporting/test_supervisory_validations.py` — the
  two-way-ratcheted register of published EBA/BoE rules; the estate's strongest
  oracle for reporting defects.

---

<!-- /postmortem appends entries below this line, newest last. -->

The first six entries were written together on 2026-08-09, from a review of the
validation estate rather than from six separate `/postmortem` runs. The first four
are the escapes this project had already established with evidence and never
recorded — the file having sat at zero entries while defects reached published
output is itself the first thing the review found. The last two came out of the
review itself, one of them a measured escape and one a defect in a gate that had
not yet shipped.

Their gate changes land in **the same change-set as this file**, not in an
earlier release, and each was still under adversarial review when its entry was
written. Every `Gate change` field therefore names the item that owns it; if a
review returns `revise`, that field and its `Verified red` are what must be
re-checked, and a red produced against a revised gate is not evidence for the
gate that shipped.

## 2026-08-09 — Estate coverage is measured to four decimal places and gated on nothing

- **Defect**: The four C 07.00 off-balance-sheet defects recorded in
  `.claude/LESSONS.md` B5 reached published output because every golden portfolio
  was 100% drawn loans. No data ever flowed through the off-balance-sheet
  columns, so the four published rules that tie them out (`boe_b0471`, `v6364_m`,
  `v1659_m`, `v1661_m`) were never evaluated, and the supervisory gate — which
  fails open — was green throughout. The metric that measures exactly this
  condition was already computed and consulted by nothing. Measured over the
  current 16-run matrix: **12.85% template-cell liveness, 55,553 dead cells, 785
  never-evaluated rules**, and only **257** CRR / **289** Basel 3.1 published
  rules binding.
- **Rule**: Not a regulatory escape. The regulatory content at risk is whatever
  lives in the 55,553 dead cells, which is the point: an unlit cell has no
  direction and no magnitude until something lights it.
- **Origin**: `scripts/coverage_report.py` and `scripts/coverage_baseline.json`,
  merged with the independent validation system (2026-08-08). `--check` was
  written, documented as a ratchet, and never called — not by CI, not by
  `scripts/arch_check.py`, not by any test.
- **Escape class**: `gate-not-run`
- **What the fix does and does not cover — reachability, not correctness**: every
  ratcheted quantity here is **value-insensitive by construction**. Liveness
  counts cells that are *non-null*; "binding" counts a rule that reaches `PASS`
  *or* `FAIL`. So a defect that changes a **number** in a cell that stays
  populated cannot move any of these metrics at all — it moves them only if it
  happens to null a cell or make a rule unevaluable. The worked example is the
  dropped `+ airb_sl_excl` term in C 02.00 row 0340: a full supervisory run does
  not detect it either (8 passed with the defect live). **This gate makes blind
  spots visible; catching a wrong value in a reachable cell is the supervisory
  register's job, and the C 02.00 subtotal shows the register currently fails at
  that too.** Two escapes, two separate fixes — a reader who merges them will
  conclude the estate is better defended than it is.
- **Why every gate missed it**: the gate was not weak, absent or wrongly
  anchored — it was unwired. A ratchet that no runner invokes has exactly the
  same effect on a defect as no ratchet, while reading in the repository like
  coverage is under control.

  Be precise about what wiring it would have bought, because the obvious claim is
  false. `coverage_report.py` was added on 2026-08-08 (`2a1e200c`), and the
  off-balance-sheet portfolio that surfaced the original B5 C 07.00 defects was
  built on 2026-08-01 (`00b13b83`) — the ratchet did not exist when they escaped.
  More fundamentally, **a ratchet fails on movement**: a cell that was already dead
  moves nothing, so wiring this gate would not have caught either the original B5
  defects or their recurrence. What it prevents is the *next* one — a live cell
  going dead, or a binding rule un-binding — and what it makes visible is the
  standing blind spot's size. That is worth having, and it is not the same claim as
  "this would have caught B5".

  **And the same inertness rotted the baseline it ratchets against.**
  The figures banked until this batch (`251 / 277 / 1298 / 52817`) reproduce at
  **neither** matrix: re-measured on today's tree against the exact `RUNS` tuple of
  the commit that banked them (`13046bee`, recovered with `git show`), the same
  code yields `253 / 279 / 1300 / 52803`. Nothing had re-derived those numbers
  since they were written, so they had stopped describing the estate before the
  matrix moved at all — a stronger statement of the same escape than "the matrix
  grew". Nothing noticed, because the baseline recorded no field saying which
  matrix, or which tree, it was measured over. A stale baseline is the second
  failure mode of an unwired instrument, and the one that survives the wiring.

  Do not read the `dead_cells` rise (52,817 → 55,553) as lost coverage: **live
  cells rose 7,891 → 8,193**, against 63,746 declared, so the ceiling moved because
  the declared population grew. And do not reason from the metric families moving in
  opposite directions — they are independent, so a real cell-coverage loss alongside
  an unrelated rule-coverage gain would look identical. The live-cell count is the
  decisive evidence; the direction of `dead_cells` alone is not evidence of
  anything. That property is the subject of its own entry below — the two cell
  metrics are not floors.
- **Gate change**: in this change-set, from task 0.2 —
  `tests/contracts/test_coverage_ratchet.py` (three always-on structural tests,
  including `test_the_coverage_ratchet_is_invoked_by_ci`, which asserts the CI job
  still invokes the script so unwiring it again fails locally, plus one
  `@pytest.mark.slow` test that shells out to the real ~46s measurement) and the
  `coverage-ratchet` job in `.github/workflows/ci.yml` running
  `scripts/coverage_report.py --check`. Deliberately **not** in
  `scripts/arch_check.py` or `arch_metrics.json`: the measurement is ~46s warm and
  `arch_check` runs on every commit via the pre-commit hook, so this is a
  considered placement rather than an omission to file.

  The staleness limb closed too, in the same change-set from task 0.2b: the
  baseline is re-banked over the 16-run matrix at `257 / 289 / 1285 / 55553 / 785`
  and now carries a `provenance` block naming the runs it was measured over, so
  `--check` reports a **matrix change as INVALID rather than as a regression** and
  a baseline with no provenance is called out as predating the field. That is the
  structural fix, not a re-measurement: the failure was that the numbers could not
  say what they described. Reducing the blind spot itself remains task 1.4.
- **Verified red**: two — one attacking the wiring, one attacking the ratchet.

  The one that matches this escape class — the `coverage-ratchet` job removed from
  a scratch copy of `ci.yml`, which is precisely the state the estate was in:

  ```
  .github/workflows/ci.yml has no `coverage-ratchet` job. The coverage ratchet is
  implemented but unrun, which is how it spent its whole life before P5.21: a
  change can kill a live cell or un-bind a published rule with every gate still
  green (.claude/LESSONS.md B5). Restore the job.
  ```

  And the ratchet itself rejecting a regression — a measurement moved as a defect
  that kills one column would move it, against the banked figures:

  ```
  [REGRESSED] union_binding_rules_crr: 257 -> 256 (may not decrease)
  [REGRESSED] cells_live: 8193 -> 8181 (may not decrease)
  [REGRESSED] dead_cells: 55553 -> 55565 (may not increase)
  [REGRESSED] never_evaluated_rules: 785 -> 786 (may not increase)
  ```

  Both run without mutating the tree. Task 0.2 also drove the real test body
  through six perturbations — including a typo'd metric name, which would otherwise
  surface as a `KeyError` 46 seconds into CI — and ran the `slow` test for real to a
  genuine `1 failed in 46.66s`.

  **Live caveat, and it belongs in this field rather than a footnote: `--check`
  does not run at all as of this commit.** `cells_live` is in `_RATCHET_MIN` and is
  not in the banked baseline, so `_check_baseline` raises `KeyError: 'cells_live'`
  — which is the typo'd-metric-name failure mode arriving for real, from a metric
  addition rather than a typo. The invocation guard passes throughout, because it
  asserts that CI *invokes* the script, not that the script *works*. So the red
  above was produced against the baseline with `cells_live` banked at 8,193, which
  is the state task 0.2b is landing, not the state on disk. Until that lands the
  gate is wired and broken, and the honest reading of this entry is that its
  escape is closed and its replacement gate is not yet demonstrably running.

  **The invocation guard is weaker than its own red suggests, and saying so here
  is the point of the field.** Its verified red exercises only the form where the
  `--check` invocation is deleted outright. A skeptic defeated it **five** other
  ways, each leaving the guard green: `run:` commented out, `if: false`,
  `continue-on-error: true`, the step deleted with the command left behind in a
  comment, and the workflow's `on:` triggers removed. A hardening is landing in
  this batch. Separately, the metric choice has a defect of its own — an absolute
  `dead_cells` ceiling can reward coverage *loss*, since dropping a template
  removes dead cells; ratcheting `cells_live` instead is filed. An escape log that
  overstates a gate's strength commits the error it exists to record.
- **Lesson**: **partially graduated — B5 stays as prose.** The ledger's 2026-08-09
  row records B5 as `PARTIALLY GRADUATED … STILL OPEN, narrowed to three`: the
  cell-granular case (the C 08.01 r0253 shape), the row-granular case (C 08.04's
  single column is live while six of nine movement rows never carry a figure), and
  `never_evaluated_rules`, the supervisory-register half. The first of those is
  exactly what the paragraph above concedes these metrics cannot see. Since the
  ledger's convention is that graduated prose gets deleted, calling this "graduated"
  would invite destroying the two-leg fixture pattern that is currently the only
  form the cell-granular case has. Do not delete it.

## 2026-08-09 — A defect that empties a column leaves all five register ratchets green

- **Defect**: A supervisory rule whose operands are all null or zero evaluates
  to `VACUOUS`. The per-run summary counts `VACUOUS` separately from `PASS` and
  `NOT_EVALUATED` — and then nothing constrains it. So a change that empties a
  column flips its rules `PASS` → `VACUOUS`, the register's five ratchet tests
  stay green, and the estate's strongest reporting oracle reports success for a
  column it stopped checking.
- **Rule**: Not a regulatory escape. The exposure is every published EBA/BoE
  rule whose operands can be emptied — i.e. all of them.
- **Origin**: `tests/acceptance/reporting/test_supervisory_validations.py`. The
  summary was deliberately built to keep the four statuses apart
  (`test_the_summary_keeps_unevaluable_rules_apart_from_passes` asserts they are
  all reported and sum to the enforced population) — a correct and useful
  design, one step short of a gate.
- **Escape class**: `no-assertion-of-presence`
- **Why every gate missed it**: the register asserts that no *enforced* rule
  breaks, and vacuity is not breakage — it is the absence of an evaluation. The
  count was recorded and treated as informational, which means the number moved
  and no test cared. Note this is the neighbour of `path-never-exercised`, not
  an instance of it: the 2026-08-08 recurrence proved that class's prescribed fix
  (build the portfolio, register it in `RUNS`) is necessary and **not
  sufficient** — the portfolio *was* registered and the **cell** was dead. C
  08.01 r0253 held `0.00` in all six goldens, so the mandatory Tier 2 gate was
  structurally incapable of seeing a change to that column. Closing it took a
  two-leg fixture (a live cell that survives the change plus one that moves) and
  activated five previously-`VACUOUS` rules to `PASS`, including `boe_b0752_27`,
  the r0253 tie-out itself.

  **The same interlock is live right now on the FCSM path, which is what makes this
  worth reading twice.** The seven Art. 197 capital understatements in the last
  entry are *unreachable by the estate's only FCSM golden portfolio*
  (`reporting_funded_protection_portfolio.py`), because both of its pledges are
  CQS 1 — a CQS 1 security carries the obligor's own weight, so the defect cannot
  express itself there. And that portfolio is the one **deliberately withheld from
  `RUNS`**, having been registered against a config that silenced the very feature
  it exists to exercise (B5's third form). So the defect sits behind two
  independent layers of unreachability: a portfolio outside the register, and a
  fixture shape that would not show it even inside. Neither vacuity nor coverage
  can see that; only the oracle did.
- **Gate change**: in this change-set, from task 0.3 — a two-way vacuity ratchet
  in the same register, keyed on `(regime, rule_id)` and stored as
  `known_vacuous_rules` in
  `tests/expected_outputs/reporting/validation_known_breaks.json`:
  `test_no_rule_falls_to_vacuous_outside_the_baseline` (leg f) fails a rule that
  falls to vacuity outside the register, and
  `test_no_baseline_vacuous_rule_asserts_again_without_being_removed` (leg g)
  fails a register entry that starts asserting again, so the population can only
  shrink deliberately. Both drive extracted predicates
  (`_rules_newly_vacuous` / `_rules_no_longer_vacuous`) rather than inline
  logic. Baselined at **218** rules — 57 CRR / 161 Basel 3.1, 143 Error and 75
  Warning severity — each carrying a written reason.

  **It is not a per-run count.** The key matches `known_broken_rules` because a
  vacuous rule has no failing coordinate to key on, and the 85 rule ids shared
  across the two published extracts would otherwise collide. Membership is the
  **union over the sixteen runs**: a rule qualifies only if it reaches a verdict
  somewhere and never reaches `PASS` or `FAIL` anywhere. The per-run `VACUOUS`
  counts stay in the register's `summary` block, descriptive and unasserted — the
  ratchet does not read them. The consequence is worth knowing before relying on
  it: a defect that empties a column on one portfolio **while another portfolio
  still exercises the same rule does not move this population**, and that case
  belongs to the goldens. Leg (f) catches the rule that stops asserting anything
  *anywhere*, which is the case no other gate saw.
- **Verified red**: both legs, driven through the real test functions with a
  synthetic *measured set* against the real committed register — deliberately not
  a faked pipeline run. Leg (f), inserting `b31/boe_b0752_27` (the C 08.01 r0253
  tie-out, which passes on `irb-classes` today and is therefore absent from the
  register) as vacuity-only, with its real measured facts:

  ```
  1 published rule(s) now hold ONLY VACUOUSLY, 1 of them Error-severity. Every
  operand was null or exactly zero, so the rule asserts nothing about our figures
  while still reporting a green outcome:
    b31/boe_b0752_27  [ERROR] held vacuously on 3 coordinate(s) across 4 portfolio(s)
        rule: {t: OF08.01.01.01, r: 0070, c: 0253} = sum({t: OF08.02.01.01, c: 0253})
  This is how a defect that empties a column passes this gate (LESSONS B5,
  recurrence 2026-08-08). Find what emptied the cells.
  ```

  Leg (g), removing `b31/boe_b0958` (the OF 07.00 defaulted-exposure footing)
  from the measured set, reported the entry leaving the vacuity population and
  demanded the distinction that matters — banked activation versus a cell or run
  that went away, *"the estate got WORSE — fix that instead of deleting the
  entry"*. I independently exercised the same `_rules_newly_vacuous` predicate
  against the committed 218-entry register while writing this entry and saw it
  reject the same rule. Register regeneration is idempotent over the curated
  reasons; the suite is green at 8 tests.
- **Lesson**: second production-class recurrence of `.claude/LESSONS.md` B5, and
  the second time B5 has been fixed as prose. Its executable form is this ratchet
  plus the coverage ratchet in the entry above; B5's prose should retain only the
  two-leg fixture pattern, which neither ratchet can express. The recurrence case
  is now load-bearing rather than illustrative: `boe_b0752_27` passes on
  `irb-classes` and remains vacuous on `rich`, `crm-substitution` and `art199`, so
  that one registered run is the whole reason it sits outside the vacuity
  population — re-empty r0253 and leg (f) fires. Its 26 siblings
  (`boe_b0752_*`, `boe_b0814_*`, `boe_b0757`, all Error severity) are in the
  register with the B5 discharge precedent written on each entry, so the family is
  ratcheted rather than merely known.

## 2026-08-09 — The detection rate of the whole estate is unknown, and the instrument that measures it would have lied

- **Defect**: Two compounding things. (1) `scripts/defect_injection.py` — 22
  mutants, a data-driven gate ladder, reachability as a first-class verdict —
  has never been run as a campaign, so no scorecard exists and the estate's
  detection rate is unmeasured. The plan that commissioned it
  (`docs/plans/independent-validation-system.md:455`) says that before the harness
  existed nobody could say whether the rate was 40% or 90%; that sentence is still
  true, because building the instrument and reading it are different acts. (2) Every gate command in the ladder was hardcoded to spawn
  through `uv run`. On a runner without a usable `uv`, every gate fails to spawn,
  each failure scores as a *detection*, and the harness publishes a fictitious
  detection rate near 100%. **This is measured, not hypothetical**: on this
  project's own sandbox the default `uv run` path exits 2 with
  `Could not acquire lock … Read-only file system`, so `--ladder legacy` run here
  before the fix would have reported ~100% detection and zero escapes. The one
  number the harness exists to produce was the number it was most likely to get
  wrong.
- **Rule**: Not a regulatory escape.
- **Origin**: `scripts/defect_injection.py`, merged 2026-08-08 with the
  independent validation system.
- **Escape class**: `gate-not-run`, for the unrun campaign. Limb (2) is a defect
  *in* a gate rather than one that escaped a gate, and the taxonomy has no class
  for that; it is recorded here rather than given a class it does not fit. The
  general shape is worth naming: **a gate that can go red for a reason unrelated
  to the defect scores that red as success**, so any instrument whose signal is
  "something failed" needs to distinguish *failed* from *did not run*.
- **Why every gate missed it**: nothing consumes the scorecard, so its absence
  is invisible — there is no baseline to regress against and no CI job to go
  red. Limb (2) survived review because the ladder is declared in the form a
  developer types, and on a developer's machine `uv run` works; the failure mode
  only appears on a runner nobody had tried.
- **Gate change**: in this change-set, from the injection-harness runner
  override — `DEFECT_INJECTION_PYTHON` (`INTERPRETER_ENV_VAR`,
  `scripts/defect_injection.py:127`) retargets the ladder through a named
  interpreter via a single `resolve_command` chokepoint (`:150`) that every gate
  command and the baseline command pass through. A partially retargeted ladder is
  worse than an unretargeted one, so a command it cannot rewrite is a hard error
  rather than a silent pass-through. `preflight()` (`:187`) then imports
  `rwa_calc.engine.pipeline` — not bare `rwa_calc`, whose lazy `__init__` imports
  in ~150µs without touching polars — and raises `InterpreterUnusable`, exiting 2
  from `main()`, so a broken interpreter aborts the campaign instead of reddening
  every gate.

  **Owed, not done**: no test guards any of this. Nothing under `tests/` imports
  `defect_injection` at all. The graduation target is a contract test asserting
  that an unset env var leaves every `LADDER` command and `baseline_cmd` byte
  identical, and that `preflight()` raises on a nonexistent interpreter. Until
  that exists the guard is correct-by-inspection-and-one-manual-run, which is what
  this file exists to stop people calling a gate.
- **Verified red**: the pre-flight aborting a real campaign invocation
  (`--ladder fast --mutants control-reachable-output-floor-schedule`) with
  `DEFECT_INJECTION_PYTHON=/nonexistent/python`, exit code 2, before the baseline
  digest capture and before any mutant was applied:

  ```
  SPAWN PRE-FLIGHT FAILED — CAMPAIGN ABORTED, NOTHING SCORED
    command   /nonexistent/python -c import rwa_calc.engine.pipeline
    reason    the executable does not exist ([Errno 2] No such file or directory: '/nonexistent/python')
  ```

  Two further reds from the same guard: `/usr/bin/python3` spawns but cannot
  import (`reason  it exited 1`, with the `ModuleNotFoundError` quoted), and **the
  default `uv run` path in this sandbox** gives `reason  it exited 2` with
  `Could not acquire lock … Read-only file system` — the escape this guard actually
  closes. Separately, I exercised `resolve_command` in-process and saw it refuse
  both shapes it cannot rewrite (a command not beginning `uv run`, and
  `uv run watchfire check`) rather than passing them through, which is the
  silent-partial-retarget failure mode.

  **The campaign itself is still unrun, and no scorecard exists.** Only
  `--reachability-only` probes have run, which execute no gates; their two outputs
  were written under `tmp/dij/` and deleted by another agent's `rm -rf tmp`, and a
  third run died in `out.write_text` because `main()` never creates `--out`'s
  parent directory. The default output path is `scripts/defect_scorecard.json`,
  which is gitignored. **Anyone quoting a detection rate for this workstream today
  is quoting a number that does not exist.** Filed as task 0.1, with the nightly
  campaign and a detection-rate ratchet as task S.3.

  **Closed for the runner override; the reachability probe is a separate instrument
  and it is open.** A 22-mutant probe run (1,164s) produced **four mismatches out of
  22, including the deliberate UNREACHABLE control moving output** — so the probe
  currently reports reachable for a mutant chosen to be unreachable, which would
  corrupt the denominator of any detection rate it is used to compute
  (`UNREACHABLE` mutants are excluded from numerator and denominator both). Task
  0.1a. A third defect, task 0.1b, has the harness rewriting mutation targets with
  CRLF line endings. Splitting the claim matters here: two of the three instrument
  defects in this entry are still live, and only the spawn path is demonstrably
  fixed.
- **Lesson**: this is the second of these four entries whose class is
  `gate-not-run` for the same underlying reason — the estate's habit is to build
  the measurement and stop before wiring it. That is a pattern rather than two
  slips, and the coverage ratchet's `test_the_coverage_ratchet_is_invoked_by_ci`
  is the shape of its fix: an instrument ships with a test that it is invoked.

## 2026-08-09 — Eleven wrong numbers found by the oracle and parked as accepted disagreements, eight of them understating capital

- **Defect**: `KNOWN_DISAGREEMENTS` in `tests/oracle/test_oracle.py` holds **11
  entries, all `xfail(strict=True)` rather than fixed, and eight of them understate
  capital.** Seven of the eight were added *inside this batch* by the CRM oracle
  (`7c454be1`), which is the fact this entry is really about: the register grew
  **4 → 11 in a matter of hours** with nothing constraining its size.
  - **`ORC-280` — the largest.** Art. 197 collateral eligibility is never applied
    on the Art. 222 Financial Collateral Simple Method path. At full cover on a
    CQS 5 sovereign security the oracle gives 1,500,000 against the engine's
    1,000,000 — an **understatement of 33.3%**, the whole exposure moving from the
    obligor's 150% to the security's own Art. 114(2) 100%.
  - **`ORC-257`, `ORC-258`, `ORC-275`, `ORC-278`, `ORC-279`, `ORC-281`** — the same
    defect at 30% cover, each **understating 10.0%** (1,500,000 against 1,350,000),
    across Art. 197(1)(b) rated and unrated sovereigns, Art. 197(1)(d) rated and
    unrated corporates, Art. 197(1)(f) equity, and the Art. 218 credit-linked note
    on which the engine raises `CRM019` and then recognises the pledge anyway. The
    family's own reason text is unambiguous: *"DIRECTION IS UNIFORMLY
    ANTI-CONSERVATIVE OR NEUTRAL, never conservative."* Mechanism:
    `engine/crm/processor.py` runs `compute_fcsm_columns` at Step 3.8, **before**
    `apply_haircuts` at Step 4 — and `apply_haircuts` is the only place the engine
    overrides a firm-supplied eligibility attestation, so the Simple Method
    recognises collateral the Comprehensive Method rejects. `ORC-282`, the
    Comprehensive-Method control, passes, which localises it to the one method.
  - **`ORC-109`** — CRR Art. 121(1) Table 5 not applied to the institution class:
    at CQS 6 the engine returned 100% against a required 150%, an understatement by
    a third, with `ORC-105` (CQS 1) and `ORC-020` (CQS 2) as the conservative limbs
    of the same unwired ladder. **This family is being discharged as this entry is
    written** — P1.316 has wired `cp_sovereign_cqs` through Table 5 under task S.2,
    so all three leave the register. It is recorded here because it was parked for
    a day with a known capital shortfall in it, not because it is still open.
  - **`ORC-142`** — PS1/26 Art. 154(4A)(b) limb (iii): the 10% IRB mortgage RWEA
    floor applied to residential property outside the UK (oracle 0.00, engine
    373,345.27). Conservative in direction, and **unrepresentable** rather than
    mis-gated: no module under `engine/irb/` reads any obligor or property country
    column, so no input could switch it off. Rescoped under task #21 — the fix
    needs a `property_country_code` carrier, *not* the obligor-country gate the
    original framing implied.

  **The count in this paragraph is a snapshot, and that is the point.** It was 4
  when the entry was drafted, 11 when it was corrected, and lower again by the time
  P1.316 lands. A register whose size is recorded in prose is stale the moment the
  register moves, which is exactly why the fix is a ratchet and not a sentence.
- **Rule**: CRR Art. 197(1)(b)/(d)/(f), Art. 198(1)(a), Art. 218, Art. 222,
  Art. 114(2); CRR Art. 121(1) Table 5 and Art. 121(2); PS1/26 Art. 121(6),
  Art. 154(4A)(b), Art. 163(1)(b)-(c).
- **Origin**: found 2026-08-08 by the independent oracle, on merge of the
  validation estate. The engine defects themselves predate it.
- **Escape class**: `caught-and-parked` — the eighth class, added with this entry.
  The case for a new class is **not** that the existing labels read wrong
  narratively; this file's own discriminator is that *the class determines the fix*,
  and `no-gate-exists` → "create the gate" would in fact produce the register
  ratchet named below. A class added to fit one datum is fitted, not derived. It
  earns its place on two other grounds. First, **the shape recurs across at least
  four parallel registers in this repository** — `KNOWN_DISAGREEMENTS`,
  `classification_table.toml`'s `[[known_disagreement]]` D1-D7, `known_broken_rules`
  and `known_vacuous_rules` — plus strict xfails and plan bullets, so it is a
  standing structural feature rather than one incident. Second, **its fix targets
  the register rather than a detector**, which none of the other seven prescribe:
  every one of them ends in something that *looks at the output*, and this one ends
  in something that looks at the list of things we have agreed to tolerate. The
  4 → 11 growth inside hours of the class being coined is the class earning its keep.
- **Why every gate missed it**: no gate missed it. `strict=True` is real discipline
  in one direction — it prevents a silent *fix*, because an entry that starts
  agreeing becomes an XPASS and a hard failure — and none at all in the other.
  `KNOWN_DISAGREEMENTS` has no size ratchet, no owning bullet per entry and no
  expiry, so seven new capital understatements were added in one batch and every
  gate stayed green. The register was built to make findings triageable and became
  the place they are stored.
- **Gate change**: **filed as task #28 while this entry was being corrected** — a
  two-way ratchet on the size of `KNOWN_DISAGREEMENTS` plus a requirement that each
  entry names an owning plan bullet. The 4 → 11 growth is what moved it from a
  nice-to-have to the urgent item: the entry described a mechanism, and the
  mechanism then fired. Code fixes tracked separately: the Art. 121 family under
  **P1.316** (landing now, task S.2, which must delete all three entries in the same
  change), the FCSM family needing the Art. 197 gate factored out of
  `apply_haircuts` so it applies to the Simple Method input as well — explicitly
  **not** a step reorder, since Step 3.8 must precede the Comprehensive computation
  that IRB LGD still needs — and `ORC-142` under task #21.
- **Verified red**: n/a for detection — the disagreements are red today, by design,
  as strict xfails. **NOT VERIFIED** for the disposition ratchet, which does not
  exist yet. By this file's closing rule the escape therefore remains open, which is
  the correct state to record: what exists today is the detection, not the
  correction.
- **Lesson**: candidate for `.claude/LESSONS.md` — *a strict xfail is a decision
  to ship the wrong number; it needs an owner and a date, not just a reason.*
  Filed with the team lead rather than added here, since this file does not own
  that one.

## 2026-08-09 — The register does not notice a term dropped from a C 02.00 subtotal

- **Defect**: `reporting/corep/c02.py` builds C 02.00 row 0340 (A-IRB corporate)
  as `airb_corp + airb_sl_excl`. With `+ airb_sl_excl` removed — the A-IRB
  specialised-lending contribution silently leaving the row — a **full run of the
  supervisory validation suite reported `8 passed`**. The mutation was live in the
  tree while that run happened. Direction: the term is only ever added, so
  dropping it **understates** the reported A-IRB corporate figure, and its RWEA
  goes missing from the class breakdown while the approach total still counts it —
  `.claude/LESSONS.md` B6's shape, arrived at through a dropped term rather than a
  re-key.
- **Rule**: COREP C 02.00 row 0340 composition. Ten published rules name that
  cell; the two that bear on it are `v0211_m` (ERROR, footing identity
  `{r0310} = {r0320} + … + {r0410}`) and `v4252_i` (ERROR, cross-template identity
  `{C 02.00, r0340, c0010} == {C 08.01.a, r0010, c0260, s0007}`).
- **Origin**: the mutation was transient, injected during task 0.3's work. The
  *escape* is the register's inability to see it, which is a standing property of
  the estate.
- **Escape class**: `gate-not-run`. The catching gate is not missing — **this
  repository ships it**. `v0211_m` is a live ERROR-severity footing identity in
  `src/rwa_calc/reporting/validations/rules/crr-eba-v3.0-credit-risk.json`, and it
  is never evaluated. That is the class's definition exactly, and it is why
  `no-gate-exists` would be the wrong label: the fix is to make an existing rule
  run, not to invent a check.
- **Why every gate missed it**: `v0211_m` is one of **four live ERROR rules** on the
  C 02.00 hierarchy that are never evaluated anywhere — `v0204_m`, `v0207_m`,
  `v0210_m`, `v0211_m`; the fifth rule in that family, `v0205_m`, is **WARNING**
  severity, and `v0207_m` **does** evaluate, so "none of them runs" is false and the
  split is the evidence. The mechanism is **not** that C 02.00 sits outside the
  machinery: the recorded reason is `{'row_not_emitted': 8}`, so C 02.00 *is* in the
  cellspec executor and the **rows the rules name are not emitted**. `v0210_m` needs
  r0250-0300 and `v0211_m` needs r0310-0410, which the repo does not emit;
  `v0207_m` needs r0060-0211, which it does — hence one evaluates and the others do
  not. That mechanism is already written verbatim in plan item **P1.318**, uncited
  until now. Two consequences worth stating plainly:

  - **The estate ships the rule that detects its own headline own-funds defect and
    never runs it.** `v0204_m` asserts
    `{r0010} = {r0040} + {r0490} + {r0520} + {r0590} + {r0630} + {r0640} + {r0680} + {r0690}`,
    which on a credit-only book forces `r0040 == r0010`; our `r0040` is
    `r0010 / 12.5`. `v0210_m` gives `r0250` five children, so r0250 is a parent
    where the engine puts the institutions leaf — the row-axis shift of task #17,
    detected by a rule we already own.
  - The second candidate mechanism is real but secondary: `v4252_i`, the only
    cell-level tie-out of r0340 (`== {C 08.01.a, r0010, c0260, s0007}`), carries
    `if_value_missing: do not run rule`, so a missing sheet silently removes it.
    Fail-open by the publisher's own semantics, on top of a rule set that is not
    being evaluated anyway.

  What is *not* the explanation: the path is exercised. The cell is populated and
  C 02.00 is emitted on every portfolio. And the coverage ratchet cannot see the
  *value* defect — its metrics are value-insensitive (first entry) — but it can see
  precisely this: an ERROR rule that never runs is one of the **785
  `never_evaluated_rules`** that entry counts and that nothing gated. These five
  are concrete instances of that aggregate, which is what an aggregate is for.
- **Gate change**: **deferred and filed** — task #16 for this data point (it feeds
  step 0.1's scorecard), task #17 for the row-axis shift, task #19 for the four
  unevaluated ERROR rules. Making `v0204_m`/`v0210_m`/`v0211_m` evaluate is the
  fix that catches the row shift and the subtotal composition together, but it is
  **not cheap**: emitting the rows those rules address is plan item **P1.318**,
  **Effort: L, single-stream**, moving 10 golden frames plus the validation
  baseline. I said "cheapest of the three" in an earlier draft and that was wrong.
  Independent re-derivation of C 02.00's class rows in `tests/conformance/` remains
  the second layer.
- **Verified red**: **inverted — the gate was observed not firing**, which is the
  strongest evidence in this file. A full supervisory run with the mutation live
  reported `8 passed`. That is a measured negative result rather than an inference
  from reading the rules: whatever the register checks, it does not check this.
- **Lesson**: this is the estate's first `ESCAPED` verdict, and it arrived free as
  a side effect of another item — before the injection campaign built to produce
  such verdicts has run even once (tasks 0.1 / 0.1a). Logged in the same run and
  deliberately not chased: `C 02.00: row 0300 (14,625,069.66) exceeds its class
  breakdown (21,574.13)` — a headline own-funds row exceeding the sum of its own
  class rows, a live B6 condition that the estate emits as a log line and nothing
  fails on.

## 2026-08-09 — A ratchet that can be satisfied by deleting the coverage it measures

- **Defect**: two of the coverage ratchet's five metrics are not floors.
  `template_cell_liveness_bp` is a **ratio whose denominator shrinks with its
  numerator**, and `dead_cells` is an absolute count of the complement
  (`declared − live`). Analytically, dropping N declared cells of which K are live
  passes **both** ratchets whenever `K/N ≤ 0.1285` — so deleting any region less
  live than the estate's own average *improves* both numbers. Measured: dropping
  `b31/rich` loses **689 live cells** while `template_cell_liveness_bp` improves
  1285 → 1374 and `dead_cells` improves 55,553 → 47,123. Across 16 leave-one-out
  runs the two cell metrics never caught anything on their own, and on 4 of 16
  they registered an improvement while real liveness fell; every genuine red came
  from a binding-rule fall or a `never_evaluated` rise. "Cell liveness may not
  FALL" is therefore not a coverage floor, and the CI comment and the script's
  docstrings say that it is.
- **Rule**: Not a regulatory escape.
- **Origin**: `scripts/coverage_report.py`, `_RATCHET_MIN` / `_RATCHET_MAX` — in
  this change-set. The gate had **not shipped**.
- **Escape class**: **none of the eight, and it should not be forced.** Every
  class presumes a defect that reached production; this one was caught by
  adversarial review of a gate *before* it landed, and its subject is the gate
  rather than the engine. It is recorded here because this file's question — which
  gate should have caught this — has a real answer worth keeping (adversarial
  review of a new gate's metric algebra, which is what did catch it), and because
  anyone tracing the coverage ratchet's history needs to find it. If entries of
  this shape recur, `gate-unfit` is the name to give them; one instance is not a
  taxonomy.
- **Why nothing else would have caught it**: the metric algebra is invisible to
  tests. Every structural test of the ratchet — including task 0.2's six
  perturbations — checks that a *declared regression* is rejected, which these
  metrics do correctly. None asks whether the quantity being ratcheted is the
  quantity that matters. Only leave-one-out measurement over the real matrix
  exposes it, and nothing in the estate does that automatically.
- **Gate change**: in this change-set, from task 0.2b, and **half-landed as of this
  commit** — `cells_live` is in `_RATCHET_MIN` in the code and is **not** in the
  banked baseline, so `--check` currently raises `KeyError: 'cells_live'` rather
  than gating. The floor value is 8,193; banking it is what completes this, and
  until then the gate this entry describes is broken rather than working. It is
  already computed as `payload["cells"]["live"]`, it fell in 15 of the 16 deletions
  and in both config-silencing variants, and it never rose on a loss. Filed
  separately:
  `never_evaluated_error_severity_{crr,b31}` (175 / 195) is computed and
  unratcheted, so swapping one ERROR-severity never-evaluated rule in for one INFO
  out is invisible to the flat total — while the script's own docstring calls an
  ERROR rule that never runs anywhere the worst case in the estate.
- **Verified red**: the leave-one-out measurement is itself the red, and it is red
  in the diagnostic direction — the two metrics **passed while coverage fell**, on
  4 of 16 deletions. `cells_live` was then checked against the same 16 deletions
  before being adopted and fell in 15; the one deletion it did not catch is a
  residual the follow-up should name rather than leave implied.
- **Lesson**: the executable form is the `cells_live` floor itself. The
  transferable rule — *ratchet the quantity you care about, not a ratio of it and
  not its complement* — is offered to the operator as a `.claude/LESSONS.md`
  entry, since a ratio-shaped ratchet reads as a floor to every reviewer who does
  not do the algebra.

## 2026-08-11 — The release script's test run happens before the mutation it should catch

- **Defect**: `scripts/deploy.py` bumped the package version and regenerated two
  of the four generated artifacts. Three targets embed the version in their own
  output — `docs/data-model/regulatory-tables.md`
  (`generate_regulatory_tables.py:811`), `docs/development/confidence-matrix.md`
  and `tests/contracts/data/confidence_snapshot.json`
  (`generate_confidence_matrix.py:525,747`) — so **the bump alone was sufficient
  to make all three stale**, with no other change in the tree. v0.3.25 was
  committed and tagged in that state; CI on the release commit failed
  `test_regulatory_tables_page_is_fresh` and `test_confidence_matrix_is_fresh`.
  A second, latent instance rode along: `generate_citation_matrix.py` writes
  `tests/contracts/data/citation_snapshot.json`, which `GIT_STAGE_FILES` never
  staged — the same defect, one release away from firing.
- **Rule**: Not a regulatory escape.
- **Origin**: `scripts/deploy.py::build_release` / `GIT_STAGE_FILES`, standing
  since the generated pages acquired their version stamps. Every prior release
  had the same hole; it only became visible when a freshness contract test
  covered the stamped targets.
- **Escape class**: `gate-not-run`, with a twist worth recording. A catching gate
  existed and was in fine health: both freshness contract tests ship, run in the
  default suite, and pass. `deploy.py` runs the suite as step one and bumps the
  version as step two, so the gate measured a tree in which the defect **did not
  yet exist**. The class table prescribes "move the gate earlier"; here the
  correct move is the opposite, **later** — after the mutation. The class is
  about a gate that ran at the wrong point, and *earlier* is simply the common
  case, not the definition. If this shape recurs, the prescription column should
  read "move the gate to the other side of the mutation".
- **Why every gate missed it**: ordering, and nothing else. Local `pytest`
  passed (measured pre-bump). The pre-commit gate passed (same reason). CI was
  the only gate positioned after the mutation, and CI is the last one — by the
  time it spoke, the version commit and the annotated tag existed, and the tag
  had been pushed. Note what this rules out: it is *not* that the freshness tests
  are weak or that a path went unexercised. They are strong and they ran. A gate's
  **position in the sequence** is part of its specification, and nothing in this
  estate had ever stated the position of these two.
- **Gate change**: `scripts/deploy.py::build_release` now runs both
  version-stamped generators after the bump, and `GIT_STAGE_FILES` carries their
  three targets plus `citation_snapshot.json`. That fixes the instance. The
  *category* is closed by `tests/contracts/test_release_regeneration.py`, which
  discovers version-stamped generators by inspection — any `scripts/generate_*.py`
  reading `pyproject.toml`'s version — and fails when one is not invoked by
  `deploy.py`. Discovery is deliberately not a hand-maintained list, because a
  hand-maintained list is exactly what was wrong. Its companion test asserts the
  sweep is non-empty, so a drifted heuristic fails loudly instead of passing
  vacuously.
- **Verified red**: run against the real pre-fix `deploy.py` at `6f513697`:

  ```
  RED against pre-fix deploy.py (6f513697).
  Not regenerated by the release script:
    - generate_confidence_matrix.py
    - generate_regulatory_tables.py
  ```

  Green against the shipped `deploy.py` (`2 passed`). The red is produced from
  the actual defective commit, not a reconstruction of it.
- **Lesson**: *a gate that runs before the step it protects has not run.* The
  release script's ordering — test, then mutate, then commit — reads as
  conscientious and is precisely backwards for anything the mutation itself can
  break. Worth a `.claude/LESSONS.md` entry in the operator's judgement, because
  the shape generalises past releases: any sequence that validates and then
  transforms has this hole.

## 2026-08-11 — A wheel outgrew the pinned uploader, and no gate in the release flow could see it

- **Defect**: publishing v0.3.25 to PyPI failed with

  ```
  Checking dist/rwa_calc-0.3.25-py3-none-any.whl: ERROR
  InvalidDistribution: Invalid distribution metadata:
  '2.5' is not a valid metadata version
  ```

  `uv build` resolves the build backend fresh on every run, and the current
  backend emits `Metadata-Version: 2.5`. `.github/workflows/publish.yml` pinned
  `pypa/gh-action-pypi-publish` at `cef22109…` (v1.14.0), whose vendored Twine 6
  predates 2.5 and refuses it. **Nothing in this repository changed**: v0.3.24
  published on 5 August and v0.3.25 did not, because one of the two components
  moved on its own.
- **Rule**: Not a regulatory escape.
- **Origin**: standing since the action was pinned. The pin is correct practice —
  it is the reason the failure was a clean refusal rather than a supply-chain
  surprise — but pinning one side of a two-sided compatibility relation converts
  "we are current" into "we are frozen against a moving target".
- **Escape class**: `no-gate-exists`. Nothing anywhere — locally, in the
  pre-commit gate, in CI, or in `deploy.py` — inspected a built distribution.
  `uv build` was run for its exit code alone, and its exit code is 0 for a
  perfectly well-formed wheel that this particular uploader happens to reject.
- **Why every gate missed it**: the whole estate tests *the source tree*, and
  this defect does not exist in the source tree. It exists only in the artifact,
  and only in relation to a version pinned in a YAML file that no test reads.
  Note in particular that **`twine check` alone would not have caught it**: any
  Twine new enough to install today accepts 2.5 happily, so a local `twine check`
  is green on precisely the wheel that fails. The failure is not "malformed
  distribution", it is "distribution newer than the pinned publisher" — a skew
  between two versions, visible only when both are read together. A gate built on
  the obvious reading of this incident would not have caught this incident.
- **Gate change**: `scripts/check_distribution.py` — reads `Metadata-Version`
  from every built wheel and sdist, reads the pinned publisher version out of
  `publish.yml`, and fails when the former outruns what the latter accepts
  (`PUBLISHER_METADATA_SUPPORT`). Invoked from `deploy.py::build_release` and
  from the CI `build` job, with `uvx twine check dist/*` alongside it in CI for
  the malformed-distribution class it *does* cover. `tests/contracts/test_distribution_gate.py`
  covers the checker and asserts both call sites still exist — this project has
  shipped an inert ratchet before, and a script nothing calls reports success
  forever. An empty `dist/` is a failure, not a pass.
- **Verified red**: the shipped gate, via
  `check_distributions(dist_dir, workflow)` — the gate exposes no path-typed CLI
  argument, so a reproduction calls the function, exactly as the contract tests
  do — against the real v0.3.25 artifacts with the pre-fix pin from `451e97db`:

  ```
  Built distributions declare core metadata newer than the pinned publisher accepts.
    - rwa_calc-0.3.25-py3-none-any.whl declares Metadata-Version 2.5
    - rwa_calc-0.3.25.tar.gz declares Metadata-Version 2.5
    pypa/gh-action-pypi-publish is pinned at v1.14.0, which accepts up to Metadata-Version 2.4
  ```

  Exit 1. Green (exit 0) against the shipped v1.14.2 pin. Both the artifacts and
  the pin are the genuine article, so this reproduces the escape rather than
  modelling it. The disarm case was checked too: replacing the `deploy.py` call
  site fails `test_gate_is_actually_invoked`.
- **Note — the gate's own first version failed the quality gate**: it took
  `--dist-dir` / `--workflow` as `type=Path` CLI arguments, which SonarCloud
  flagged as `pythonsecurity:S8707` (MAJOR), taking `new_security_rating` to C
  against a required A. That is the third instance of this rule here, after
  `injection_ratchet.py` and `coverage_report.py`'s `bank()`. The remedy is
  already settled and is **not** a containment guard: commit `a5d34c0d` records
  two successive attempts at resolve-then-contain that left the finding in place.
  Both path arguments were therefore removed rather than sanitised, and
  `test_gate_exposes_no_path_typed_cli_argument` now asserts that no `type=Path`
  argument returns.

  Three instances of one rule, each fixed the same way, is a lesson that has
  proven it cannot survive as prose, so it was **graduated to `arch_check.py`
  check 19**: no `type=Path` argparse argument anywhere in `scripts/`. Verified
  red by restoring this script's own pre-fix body from `d4fdcee6` — the exact
  code SonarCloud rejected — which the check names argument by argument:

  ```
  scripts/check_distribution.py: add_argument(--dist-dir) uses type=Path...
  scripts/check_distribution.py: add_argument(--workflow) uses type=Path...
  arch_check exit=1
  ```

  Exit 0 once restored. **Running it for the first time found nine further
  instances that no one had counted** — `coverage_report.py --out`,
  `defect_injection.py --out`, five in `impact_report.py`, two in
  `parity_gate.py`. They ship as a **shrink-only** `CLI_PATH_ARG_ALLOWLIST`
  rather than being fixed here, because draining them means touching four
  scripts and their workflow call sites; filed as task #36. Two things are worth
  recording about that number. It is more than double the instances anyone knew
  about, which is the usual result of converting prose into a check. And
  `coverage_report.py` is on the list *despite* commit `89bf0323` having already
  fixed this rule in that same file — the earlier pass removed `bank()`'s
  `baseline_path` and left `--out` untouched, which is precisely what
  per-instance fixing looks like from the outside: a file that has been "fixed"
  and still carries the defect.
- **Lesson**: *pinning one side of a compatibility relation makes the other side
  a moving target, and the skew is nobody's regression.* Neither component was
  wrong; both were doing their job. The general form — when you freeze one of two
  things that must agree, something has to assert they still agree — is the part
  worth carrying, and it applies to every pinned tool in this repo, not just the
  uploader.

## 2026-08-12 — The input contract was written, unit-tested, and connected to nothing

- **Defect**: 10 of the 14 public validators in `src/rwa_calc/contracts/validation.py`
  — **402 lines**, every one of them carrying green unit tests — could not be
  reached from any production path under `src/`. `validate_pd_range`,
  `validate_lgd_range`, `validate_ccf_modelled`, `validate_non_negative_amounts`,
  `validate_schema`, `validate_schema_to_errors`, `validate_required_columns`,
  `validate_raw_data_bundle`, `validate_resolved_hierarchy_bundle`, and
  `validate_aggregated_bundle` — the last of which is the **output**-bounds guard
  (RW > 1250%, RW < 0, RWA < 0, null EAD) that would have run on every result the
  engine has ever produced. 48 unit tests pass over that code in 2.7 seconds,
  testing logic that never runs on customer data.

  The consequence is measured, not inferred. On CRR, £1m senior corporate, F-IRB:
  a risk feed sending `PD = 1.5` to mean "1.5%" returns RWA **£603.67** against a
  correct £1,119,286.69 — an understatement of **99.9461%**, a £1,118,683 capital
  shortfall on every £1m of exposure, with no exception, no null and no
  `CalculationError`. `LGD = -0.2` returns £0.00. `Maturity = -3` years returns
  £776,750.85. `CQS = 0`, `7` or `99` on a corporate returns RW 100%, which moves
  capital in **both** directions — 100% against a true 20% at CQS 1, and 100%
  against 150% at CQS 6 on an institution. Every one of those is a number a
  reviewer would accept.
- **Rule**: Not a single regulatory article — the exposure is the input domain of
  every article the engine implements. The output-bounds limb is the closest to a
  named rule: RW is capped at 1250% (CRR Art. 92 / PS1/26), and
  `validate_aggregated_bundle` is the only thing in the estate that would have
  said so.
- **Origin**: `src/rwa_calc/contracts/validation.py`. The escape is old and was
  **already documented**: `docs/plans/engine-defensiveness-boundary-hardening.md`,
  written 2026-05-29, states in its root-cause line that "the
  `contracts/validation.py` bundle validators were never wired into
  `pipeline.py`." That sentence was still true 2.5 months later, which is the part
  of this entry worth reading twice — the finding did not escape detection, it
  escaped *conversion into a gate*.
- **Escape class**: `gate-not-run`. The catching gate is not missing; this
  repository ships it, with tests. It is never invoked on customer data. That is
  the class's definition exactly, and it is why `no-gate-exists` would prescribe
  the wrong fix — nothing needed inventing, only wiring. It is the **fourth**
  entry in this file to carry that class, and the fifth measured instance of the
  habit the log itself names: *build the measurement and stop before wiring it.*
- **Why every gate missed it**: no gate looks at reachability. Every existing
  guard in the estate answers "is this output right?", and an unreachable
  validator produces no output to be wrong. Worse, it produces the *opposite* of a
  signal: 48 passing unit tests over 402 lines of validation logic read, to any
  reviewer and to every coverage instrument, as an input contract that is
  enforced. Coverage tooling counts those lines as covered, because they are —
  by tests, not by the pipeline.

  Note the asymmetry with the four earlier `gate-not-run` entries. Those were
  instruments nobody had run *yet*; this one had been run, its finding recorded in
  a plan document, and the plan document then sat. A written root-cause line is not
  a gate. Prose has now failed at this five times.
- **Gate change**: `scripts/arch_check.py` **check 20 —
  `check_guard_reachability`**, registered in `main()` so
  `python scripts/arch_check.py` runs it on every commit via the pre-commit hook.
  Every public function in `contracts/validation.py` (the input contract, which is
  guard-shaped in whole) and every guard-**named** public function elsewhere under
  `contracts/` (`validate_` / `check_` / `assert_` / `require_` / `ensure_`) must
  be transitively reachable from production code under `src/`. Scoped by shape
  rather than by path so a future `contracts/checks.py` is covered on the day it
  is written; deliberately not extended to the layer's `create_empty_*` factories
  and `*_error` constructors, 10 of which are unreachable today and would have
  given the check a ten-entry allowlist on arrival.

  Three properties are load-bearing, each aimed at a way this file records gates
  going soft:

  - `GUARD_REACHABILITY_ALLOWLIST` is **empty by design**. Seeding it with the ten
    known-unreachable validators would have made the check vacuous on arrival —
    the `caught-and-parked` shape, where a gate fires, the finding is filed, and
    the wrong behaviour ships anyway. Stale entries are themselves violations, so
    the list can only be drained.
  - `CONTRACTS_GUARD_SURFACE` **pins the population**, because reachability alone
    is satisfiable by removing the thing it measures: rename `validate_pd_range`
    to `_validate_pd_range` and it leaves the measured set; delete it and the
    violation leaves with it. This repo has shipped that shape before — four
    back-compat shells silently disarmed a regression guard that read
    `module.__file__` (check 18). Deleting a guard stays legitimate; it just has
    to be deliberate, so the pin is removed in the same change and a reviewer sees
    which guard went away. **It fired for real during this batch** (see below).
  - `tests/contracts/test_guard_reachability_gate.py::test_every_arch_check_check_is_registered`
    generalises the wiring assertion past check 20: **no** `check_*` function in
    `arch_check.py` may exist without `main()` invoking it. An unregistered check
    is this escape class committed inside the gate itself.

  The analysis has exactly one implementation. `scripts/validator_reachability.py`
  — the census this grew out of, and the reproduce command in the proposal — now
  reads `measure_guard_reachability` from `arch_check` instead of keeping its own
  copy, and `test_the_reachability_analysis_has_one_implementation` asserts both
  that it does and that the two agree on the population. The dependency points
  diagnostic → gate and never the other way, so the gate keeps working if the
  diagnostic is renamed or deleted.
- **Verified red**: two, and the second was not planned.

  **(1) The escape itself**, check 20 run against the committed pre-wiring tree
  (`git archive aa2182bd src`, so the measurement is of the state that shipped
  rather than of a scratch mutation):

  ```
  [FAIL] Contracts guards are reachable from production (wire it, or delete it)
    contracts/validation.py:1140: validate_aggregated_bundle -- guard unreachable from production
    contracts/validation.py:403: validate_ccf_modelled -- guard unreachable from production
    contracts/validation.py:373: validate_lgd_range -- guard unreachable from production
    contracts/validation.py:317: validate_non_negative_amounts -- guard unreachable from production
    contracts/validation.py:348: validate_pd_range -- guard unreachable from production
    contracts/validation.py:236: validate_raw_data_bundle -- guard unreachable from production
    contracts/validation.py:151: validate_required_columns -- guard unreachable from production
    contracts/validation.py:277: validate_resolved_hierarchy_bundle -- guard unreachable from production
    contracts/validation.py:64: validate_schema -- guard unreachable from production
    contracts/validation.py:176: validate_schema_to_errors -- guard unreachable from production

  Total: 10 violation(s)
  ```

  Ten violations, zero allowlist entries, and the same ten the proposal's census
  named — an AST-based reference analysis independently reproducing the seed
  script's regex-based answer.

  **(2) The population pin, firing unprompted.** While the wiring work was landing
  in parallel, five of the ten validators were **deleted** rather than wired
  (`validate_schema`, `validate_schema_to_errors`, `validate_required_columns`,
  `validate_raw_data_bundle`, `validate_resolved_hierarchy_bundle`). The
  reachability limb went green as they disappeared — exactly the defusal the pin
  exists for — and the pin caught all five:

  ```
  contracts: validation.py::validate_schema -- pinned in CONTRACTS_GUARD_SURFACE but no
  longer a public module-level function there. Check 20 may not be satisfied by deleting,
  privatising or relocating the guard it measures; if the removal is deliberate, delete
  the pin in the same commit so a reviewer sees it
  ```

  This is the strongest evidence in the entry, because it was not a constructed
  probe: the check's anti-defusal limb fired on real concurrent work within an
  hour of being written, on a removal nobody had announced. Two of those five
  deletions are prescribed by the proposal; the other three are a wider call, and
  the pin is what turned them into a decision somebody has to state. Before the
  pins were dropped the removal was verified complete — definitions and their
  private helpers gone, and **no reference to any of the five surviving anywhere
  under `src/` or `tests/`** — so what the change-set records is a finished
  deletion, not a half-migration. The consequence worth stating plainly: the
  estate now ships **no declared-vs-actual schema-drift check at all**.

  **(3) Six adversarial perturbations**, run against a throwaway copy of `src/`
  so the real tree was never mutated (a killed injection run leaving a live
  mutation in `src/` has cost this project hours before). Control: 0 violations.
  Privatising `validate_pd_range` to `_validate_pd_range` → 1 (the pin, not the
  reachability limb, which goes *quiet* — that is the defusal). Deleting
  `validate_lgd_range` outright → 1. A new `contracts/checks.py::validate_nothing`
  that nothing calls → 1, which is the scope-by-shape decision earning its keep:
  the check covers a module it has never seen, so hard-coding `validation.py`
  would have let that through. Deleting `contracts/validation.py` entirely → 9.
  And the negative control that matters, since a gate that fires on everything
  is not a gate: a new *non-guard* public function in the same unreachable
  position (`create_empty_thing`) → **0 violations**, confirming the scope
  boundary is the one documented rather than an accident.
- **Lesson**: this is the fifth instance of the estate's dominant meta-pattern and
  the second time it has been "fixed" by writing it down. `.claude/LESSONS.md`
  carries the graduation rule for exactly this case — a lesson that reaches
  production twice cannot survive as prose — so the entry belongs in the
  Graduation ledger rather than the working set. Check 20 is the same move check
  14 made on Polars namespaces: it removes the *category*, not the instances.
  What remains prose, because no check can express it: the proposal's other three
  phases (declare the input domain as data, fuzz the pathology axis, make absence
  loud) are what stop the next silent-plausible-number defect; check 20 only
  guarantees that a guard we have already written is running.

## 2026-08-12 — The registers of tolerated findings had no size gate and named no owner, and the count everyone quoted was wrong in both directions

- **Defect**: This file's 2026-08-09 entry 4 recorded eleven wrong numbers parked
  as accepted disagreements and named its own gate change — a ratchet plus an
  owning bullet per entry — then closed its **Verified red** field with
  *"**NOT VERIFIED** for the disposition ratchet, which does not exist yet. By
  this file's closing rule the escape therefore remains open."* It stayed open for
  three days. This entry is that closure, and it is filed as its own entry rather
  than an edit because the interval produced two findings of its own.

  **First: the population was never counted again.** Measured on
  `fix/input-domain-correctness`, 2026-08-12 — `KNOWN_DISAGREEMENTS` holds **8**
  entries, **7** of them understating capital: six FCSM cases at 10.0% and
  `ORC-280` at 33.3%. The eighth, `ORC-142`, runs the *other* way (engine applies
  a 373,345.27 mortgage-floor adjustment where the oracle applies 0.00) and its
  limb is *unrepresentable* rather than mis-gated. So "11 entries, 8 understating"
  — the figure in `docs/plans/test-space-correctness-proposal.md`, in
  `IMPLEMENTATION_PLAN.md` P5.41, and in this file's own entry 4 heading — was
  wrong on **both** numbers by the time anyone acted on it. Three of the eleven
  (the Art. 121(1) Table 5 family) were discharged by P1.316 hours after entry 4
  was written. Entry 4 predicted this in terms: *"a register whose size is recorded
  in prose is stale the moment the register moves, which is exactly why the fix is
  a ratchet and not a sentence."* Its own heading is now the worked example.

  **Second: not one of sixteen entries named an owner.** Across both declared
  registers — 8 in `KNOWN_DISAGREEMENTS`, 8 in `tests/conformance/classification_table.toml`
  (D1–D7 *including D1b*, which is why the parallel register is 8 and not the 7
  everything referring to it says) — **0/16** reason strings named the plan bullet
  responsible for the fix, against `.claude/LESSONS.md` B7's explicit instruction
  to put one there. All sixteen owning bullets already existed in
  `IMPLEMENTATION_PLAN.md`; nothing linked an entry to one, so a register of
  sixteen shipped-wrong numbers had zero accountable owners while every bullet
  that would have fixed them sat filed and unreferenced.
- **Rule**: Not a regulatory escape in itself. The regulatory content at risk is
  what the sixteen entries park: CRR Art. 197(1)(b)/(d)/(f), Art. 198(1)(a),
  Art. 218, Art. 222, Art. 114(2); PS1/26 Art. 154(4A)(b); CRR Art. 154(4)(c) /
  PS1/26 Art. 147(5A)(c); PS1/26 Art. 147(4C)(b)(ii); CRR Art. 147(2)/(3)/(7).
- **Origin**: `tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS` and
  `tests/conformance/classification_table.toml`. Both were built correctly —
  `tests/oracle/README.md` is emphatic that when the engine and the oracle
  disagree you adjust neither — and both were built without a size gate.
- **Escape class**: `caught-and-parked`. Confirmed against the definition at the
  top of this file rather than assumed: *"a gate fired, and the record of the
  finding became its resting place"*, fix *"ratchet the finding register; give
  every parked entry an owning bullet"*. Both limbs match exactly, and the
  prescribed fix is the fix that landed. Worth noting that the class's *own*
  justification — "the shape recurs across at least four parallel registers here"
  — is what made the shared mechanism below the right answer rather than four
  bespoke ratchets.
- **Why every gate missed it**: `xfail(strict=True)` is a real gate in exactly one
  direction. It fails when an entry starts **agreeing**, so a silent fix is
  impossible and requirement (b) has always been enforced at the only place that
  can enforce it. Nothing anywhere constrained **growth**, and nothing read the
  reason strings at all — they are prose attached to a marker, and prose is not
  parsed. The population could therefore rise without limit while every gate
  including the two mandatory Tier 2 ones stayed green, which is precisely what
  4 → 11 in one batch looked like from the outside: a green suite.
- **Gate change**: in this change-set, from P5.41. **ONE mechanism, two runners.**
  - `scripts/tolerated_findings.py` — the shared primitive: a direction-neutral
    generic set-diff (`diff`) and the owner grammar (`owner_of` / `unowned`).
    Extracted from the supervisory register rather than written fresh.
  - `scripts/check_parked_registers.py --check` — the gate over the two
    **declared** registers, against `scripts/parked_registers_baseline.json`.
  - `tests/contracts/test_parked_register_ratchet.py` — 13 tests. Three run the
    real gate over the real registers, including one that shells the CLI; ten
    drive the mechanism synthetically so both directions are demonstrable in
    milliseconds.
  - `tests/acceptance/reporting/test_supervisory_validations.py` — all seven legs
    now route their set arithmetic through the same `diff`. Semantics-preserving:
    8 passed, unchanged.

  **Script *and* pytest, for a stated reason.** The four registers split on what it
  costs to compute current membership. The supervisory three are **measured** — a
  union over sixteen pipeline runs, and only pytest owns the fixtures that produce
  them — so that ratchet stays where the data is. The two declared ones are a dict
  literal and a TOML array; reading them is a few milliseconds, so they get a
  script, which buys the explicit `--update-baseline` verb that makes *banking* a
  separate reviewable act from *checking*.

  **Deliberately in-suite rather than a CI job.** This file's 2026-08-09 entry 1
  records a CI-only invocation guard defeated **six** ways while staying green. A
  millisecond census belongs where nobody has to remember to run it.

  **Stronger than the bullet asked: additions are shrink-only, not two-way.**
  `--update-baseline` prunes departed ids and refreshes owners and **refuses to
  add**, so banking a new parked finding means hand-editing the baseline — a diff
  in a file whose whole purpose is to be reviewed. Every other ratchet in this repo
  can be satisfied by re-banking a worse number; this one cannot, because what it
  counts is figures an independent derivation has shown are wrong.
  **Removals stay free**, and the docstrings say why: a gate that reddens on a fix
  teaches people to stop fixing, and `strict=True` already forces the entry's
  removal in the same change. The residual hole is stated in
  `scripts/tolerated_findings.py` rather than hidden — while a baseline id is
  stale it is slack in the addition gate — and closing it would mean gating
  removals.

  **Requirement (c) landed as ownership, not as a grandfathered exception set.**
  All 16 entries carry an `OWNER: P<n>.<n>` token; every owning bullet already
  existed and no new bullet was filed. `ORC-142` → **P1.337**;
  `ORC-257/258/275/278/279/280/281` → **P1.330**; `D1`/`D1b` → **P1.320**; `D2` →
  **P1.321**; `D3`/`D4`/`D6` → **P1.303**; `D5`/`D7` → **P1.322**. The grammar is
  an explicit token and not a bare `P\d+\.\d+` scan, which was tried and rejected
  on measurement: `_ART_154_4A_B_SCOPE` already reads "Since P1.319,
  engine/irb/adjustments.py gates on the first two and not the third" — a
  *historical* reference to the bullet that narrowed the gate, not an owner for
  what remains. A bare regex would have passed the one entry whose ownership was
  hardest to establish and failed the seven whose owner was obvious; it would have
  measured prose style, not accountability. That case is pinned by
  `test_a_historical_bullet_reference_is_not_an_owner`.
- **Verified red**: six, and the first two are the ones this entry's class
  demands. All were produced against the **real** registers — four by writing the
  perturbation to disk and restoring it in a `finally`, so nothing was faked
  in-process.

  (1) A ninth disagreement added to `tests/oracle/test_oracle.py`, driven through
  the suite (`2 failed, 11 passed`):

  ```
  NEW PARKED FINDING (tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS): 1 entry/entries outside the committed baseline:
      ORC-999  (owner: P1.330)
    This register may only SHRINK. Every entry is a number we have independent evidence is WRONG and are shipping anyway, so growing the population is a decision, not a side effect.
    FIX THE DEFECT. If the finding is genuinely accepted, hand-edit parked_registers_baseline.json to add the id with its owning bullet — --update-baseline will not do it for you.
  ```

  (2) The owner token stripped from `_ART_197_FCSM_ELIGIBILITY` — requirement (c),
  firing on all seven consumers of the shared reason (`3 failed, 10 passed`):

  ```
  NO OWNING BULLET (tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS): 7 entry/entries name no plan bullet:
      ORC-257
      ORC-258
      ORC-275
      ORC-278
      ORC-279
      ORC-280
      ORC-281
    An entry with no owner is the review finding, not the xfail (.claude/LESSONS.md B7). Add `OWNER: P<tier>.<n>` to the entry's reason text, naming the IMPLEMENTATION_PLAN.md bullet that owns the fix — and file that bullet in the same change if it does not exist yet.
  ```

  (3) and (4) are the same two against the *other* register, proving the mechanism
  is shared and not a single-register special case — a ninth
  `[[known_disagreement]]` appended to `classification_table.toml` gives
  `NEW PARKED FINDING … D8-synthetic-ninth (owner: P1.303)`, and stripping D2's
  token gives `NO OWNING BULLET … D2-large-corporate-test-keys-on-one-entity-type-string`.
  Both exit 1.

  (5) The whole gate before the fix, on the untouched tree, which is the state the
  estate was actually in — two `NO OWNING BULLET` blocks, `8 entry/entries` each,
  naming all sixteen ids, exit 1.

  (6) The shrink-only claim attacked directly, since a refusal that is only
  documented is not a refusal. `--update-baseline` asked to bank the ninth entry:

  ```
  baseline banked at 16 parked finding(s)

  REFUSED to bank 1 NEW entry/entries:
    oracle_known_disagreements: ORC-999
  Additions are shrink-only. Fix the defect, or hand-edit parked_registers_baseline.json so the decision to ship a known-wrong number appears in the diff.
  ```

  with the baseline file **byte-identical afterwards** — checked, not assumed.

  **What this gate does NOT do, and it is the thing a reader will assume.** It
  constrains the *size* of the register. It does not shrink it, and it says nothing
  about whether any of the sixteen parked numbers is right. Seven capital
  understatements are still shipping today; P1.330 and P1.337 own them. This is a
  ratchet, so it fails on **movement** — the sixteen entries already there move it
  not at all, and a reader who takes a green gate as evidence the estate is clean
  has read it exactly backwards. Draining is Phase 4's actual objective; this only
  stops the queue growing while that happens.
- **Lesson**: `.claude/LESSONS.md` **B7 is now graduable, and the graduation is
  filed rather than performed here** — following entry 4's own precedent, since
  this file does not own `.claude/LESSONS.md` and two other agents were editing
  the tree concurrently. Both of B7's limbs are executable for both declared
  registers: membership (`--check` on the baseline) and ownership (the `OWNER:`
  token), so its Detect line — *"a register entry naming no bullet is the thing to
  catch in review"* — is no longer a thing to catch in review. What should survive
  the trim is the judgment B7 carries and no check can: that registering the
  disagreement is the *right* first move, and that the failure is treating the
  registration as the end of it. Keep B8 ("ratchet the accumulator, not a ratio")
  as prose in full: this mechanism
  *applies* it — the accumulator is the id set, so a register that grows by one and
  shrinks by one is detected as movement — but B8's own worked example is about
  choosing the right metric, which no check can express. What also does not
  graduate, and belongs here rather than in a lesson: **the count in the bullet was
  wrong, in a bullet whose entire subject was that counts in prose go stale.** The
  ratchet fixes the register; nothing fixes a figure typed into a sentence.

## 2026-08-12 — Three input pathologies produce a plausible number and no signal, and the codes that would report two of them are declared with no producer

- **Defect**: three distinct silent-wrong-number paths, all found in the first
  hours of the `tests/robustness/` suite existing. Each returns a populated
  results row a reviewer would accept.

  **(1) An orphan or null `counterparty_reference`.** Every counterparty-attribute
  join in the hierarchy stage is `how="left"` — the obligor rating/CQS lift at
  `engine/stages/hierarchy/enrich.py:131-135`, the entity-type gate lookup at
  `:253`, and the graph joins at `graph.py:388-420` — so a loan whose obligor
  cannot be found survives with null obligor attributes, classifies to `other`,
  and takes the 100% fallback risk weight. Measured on CRR, one GBP
  1,000,000 senior loan: a CQS 6 corporate is CRR Art. 122 **150%** = GBP
  1,500,000; pointed at a reference that does not exist it returns GBP
  **1,000,000**, a **33.3% understatement** on a one-character typo. The direction
  reverses with the obligor's true class — a CQS 1 corporate is 20% = GBP 200,000
  and orphaning it returns GBP 1,000,000, a **5x overstatement** — so the defect
  is not conservative in either direction. A *null* `counterparty_reference`
  reaches the identical fallback, which matters because that is the more common
  feed shape (an outer join upstream, or a column never populated).
  `ERROR_ORPHAN_REFERENCE` (**DQ005**) is declared in `contracts/errors.py:93` and
  re-exported from `contracts/__init__.py`, and appears nowhere else under `src/`.

  **(2) An unreadable numeric is indistinguishable from an absent one.**
  **FIXED while this entry was being written** — see the closing section below;
  the measurement here is the pre-fix state, and is what the new gate was verified
  red against. `EdgeContract.conform_lenient` (`contracts/edges.py:198-251`) cast every
  mismatched declared column with `strict=False`, so Polars turns a value it
  cannot parse into a **null**, `missing` comes back empty, and no data-quality
  error is emitted. Composed with the input contract's own (correct) rule that
  null is never a domain violation, the result is a hole. Measured: the same GBP
  1,000,000 loan whose `drawn_amount` arrives as the string `"1,000,000.00"` — a
  plain CSV export with a thousands separator — reports `ead_final = 0.00` and
  `rwa_final = 0.00` against a correct GBP 200,000, with no error. Seven ordinary
  export artefacts do this (`£1000000`, `1 000 000`, `(1000000)`, `n/a`, the empty
  string, a truncated `1.0e`). `CSVLoader` reads with `pl.scan_csv`, which infers
  such a column as `String`, so this was the shipped CSV path and not a contrived
  bundle.

  **(3) A duplicated input row vanishes.**
  `engine/stages/classify/permissions.py:261` de-duplicates on
  `exposure_reference` after the model-permission join — correct for its own
  purpose, which is to stop a fan-out when several permissions match — and in
  doing so collapses genuine duplicate INPUT rows. Three input loan rows produce
  two output rows and no error; a whole file delivered twice loses every duplicate
  silently. `ERROR_DUPLICATE_KEY` (**DQ004**) exists but is emitted only for the
  org-hierarchy multi-parent case (`engine/stages/hierarchy/graph.py:474`), never
  for an exposure table.
- **Rule**: no single article. As with the 2026-08-12 input-contract entry above,
  the exposure is the input domain of every article the engine implements. The
  closest named rules are the ones the fallback silently substitutes for: CRR
  Art. 122 (corporate SA risk weights by CQS) for (1), and CRR Art. 111 (exposure
  value) for (2), where a GBP 1m exposure is reported at GBP 0.
- **Origin**: (1) `engine/stages/hierarchy/enrich.py`; (2)
  `contracts/edges.py::conform_lenient`; (3)
  `engine/stages/classify/permissions.py`.
- **Escape class**: `no-gate-exists` for all three, and the word *exists* is doing
  precise work in (1) and (3). An error **code** is declared for each; no producer
  is. That is a recognisable relative of the four `gate-not-run` entries above —
  the estate's habit of building the instrument and stopping before wiring it —
  but it is not the same class and would not take the same fix. A constant with no
  producer is not a gate that failed to run; there is nothing to move earlier. It
  has to be written. What it shares with `gate-not-run` is the *appearance* of
  coverage: `ERROR_ORPHAN_REFERENCE` in an `__all__` reads, to a reviewer and to
  every grep, as referential integrity that is enforced.
- **Why every gate missed it**: the whole estate is organised on one axis — **by
  regulatory rule**, *does Art. 123 work?* — and every generator in it starts from
  a **valid** portfolio. `tests/properties/strategies.py` bounds PD to
  `[0.0003, 0.20]` and amounts to at least GBP 10k with every field populated, and
  its docstring says so plainly. The oracle, the conformance table, the goldens
  and the supervisory register all consume well-formed fixtures. Nothing in 1,081
  test files asked what happens when the data is **wrong**, so a wrong answer to
  that question could not be observed.

  Two structural specifics are worth recording beyond that general point. First,
  `tests/acceptance/stress/test_stress_pipeline.py::TestRowCountPreservation` is
  the *only* place in the estate that states a count identity between input and
  output rows, and it counts a clean portfolio — so (3), which is exactly a
  row-count defect, was outside its reach by construction. Second, (2) is
  **pinned** at unit level: `tests/contracts/test_edge_contracts.py:368-380`
  (`test_dtype_mismatch_cast_not_raised`) asserts that an uncastable value becomes
  null with `missing == []`. That test is
  correct about `conform_lenient`'s contract and says nothing about the
  end-to-end consequence, which is a GBP 1m exposure reporting zero capital. A
  test can pin a mechanism faithfully and leave its consequence unexamined.
- **Gate change**: **`tests/robustness/`** — a new suite driving the FULL pipeline
  (not `calculate_branch`) over deliberately broken inputs, asserting a triage
  invariant rather than a hand-derived number so it scales to as many generated
  shapes as the runner will pay for. Six generators: unit-scale errors on every
  ratio column, out-of-domain numerics read off the Phase 1 `ColumnSpec.domain`
  declarations, one nulled optional field at a time, unknown enum strings with
  case and whitespace variants, sign flips / duplicate keys / orphan foreign keys,
  and structural extremes up to 1M rows. `tests/robustness/harness.py` owns the
  invariant; `.github/workflows/nightly-robustness.yml` runs it nightly under CRR
  and Basel 3.1 as separate matrix legs, and both `pyproject.toml`'s `addopts` and
  ci.yml's `test` job exclude the `robustness` marker so it never enters the dev
  loop.

  The invariant has **four** clauses, not the two the proposal drafted, and the
  two additions are what make it usable rather than what soften it. Clause (c)
  accepts a table/column-level aggregate error, because `_collect_domain_violations`
  names at most `sample_cap=5` rows per column and summarises the rest, and DQ001
  / DQ010 name no row at all — without it the suite reports false failures on
  *correct* behaviour, which is how a suite gets switched off. Clause (d) — the row
  produced no output row and no error mentions it — is the failure, and is what
  catches (1) and (3). A fifth outcome, `collapsed`, counts input **rows** as well
  as references, because a duplicate reference IS present in the output and is
  therefore invisible to any per-reference identity.

  The join back to the input row is on **`source_exposure_reference`**, never
  `exposure_reference`: the RE splitter, guarantee substitution and the
  facility-undrawn leg all make the latter non-unique per input row, and joining
  on it would report every correct split as a vanished row.

  **Not gated per-PR, deliberately.** This is a search, not a regression check;
  its output is a list of shapes to triage. It is also **red on arrival** on
  exactly the three defects above, which is the deliverable rather than a fault in
  the workflow — a green run would mean they were fixed, not that the search found
  nothing.
- **Verified red** — each defect against its own new test, before any fix, on the
  quiet tree:

  ```
  .venv/bin/python -m pytest tests/robustness/ -m robustness -o addopts= -q

  E  AssertionError: an exposure whose counterparty_reference 'CP_DOES_NOT_EXIST'
     matches no counterparty produced GBP 1,000,000.00 against a correct GBP
     1,500,000.00 — a 33.3% understatement — and the run raised NO error at all.
     DQ005 ERROR_ORPHAN_REFERENCE is declared in contracts/errors.py and emitted
     nowhere in src/.

  E  AssertionError: an exposure with no counterparty_reference at all produced
     GBP 1,000,000.00 and no error names it

  E  AssertionError: 1 input row(s) unaccounted for (3 input rows -> 2 output rows)
       injections: ['loans.loan_reference (duplicated row)']
       accumulated error codes: ['<no errors at all>']
         [collapsed] loans:LN000 — 2 input rows share this reference and collapsed
                     to 1 output row(s); no error says so

  E  AssertionError: drawn_amount='1,000,000.00' could not be cast, was silently
     nulled, and produced a zero-capital exposure with no error
  ```

  All four assertions state what **ought** to be true and none pins the wrong
  number, so a fix turns each one green rather than requiring the test to be
  rewritten (`.claude/LESSONS.md` C1) — which is not merely a claim about the
  tests but a measured fact about one of them, since the fourth went green under
  DQ014 without being touched. The measured control values are asserted
  *first* in each test, so a failure is unambiguously about the missing signal and
  not about the risk weights having moved underneath the test.
- **Defect (2) is CLOSED, by the gate rather than around it.** The eight
  `test_cast_failures.py` tests were written red against the measurement above and
  handed to the concurrent Phase 1 work as an acceptance check. **DQ014
  `ERROR_UNREADABLE_INPUT_DTYPE`** now reports a column supplied in a dtype whose
  cast is destructive: `seal_lenient` returns `LossyCast` findings alongside
  `missing`, the loader turns them into one error per (table, column)
  (`engine/loader.py:223-234`), and `tests/fixtures/raw_bundle.py` routes them into
  the bundle's error list so an in-memory bundle carries the same load-boundary
  errors a production load would. All eight tests flipped green with **no edit to
  any of them**, which is the strongest available form of this evidence: the gate
  was written first, observed red, and turned green by the fix rather than by being
  rewritten. Deliberately NOT routed through DQ003 `ERROR_TYPE_MISMATCH`, which
  Phase 0 retired as unfirable, nor through DQ001 — a value that is present and
  unreadable needs the feed RE-SENT where a missing column needs it EXTENDED, and
  `test_an_uncastable_value_is_not_reported_as_a_missing_column` pins the
  distinction.
- **Defects (1) and (3) are now CLOSED as well, and by the same route: the four
  remaining tests were turned green by the fix, with no edit to any of them.**
  DQ005 has a producer, DQ004 has an exposure-table producer, and both are read
  off DECLARATIONS in `data/schemas.py` rather than hand-written per column —
  `TABLE_FOREIGN_KEYS` (a new `ForeignKey` declaration alongside `NumericDomain`
  / `EnumDomain`) and `TABLE_UNIQUE_KEYS`, both consumed by
  `contracts/validation.py::validate_referential_integrity` and
  `::validate_duplicate_keys`. Three decisions in that fix are worth recording
  because each was a fork where the obvious move was wrong:

  **The join stays `how="left"`.** The recommendation above ("emit DQ005 from
  the counterparty-enrichment join by counting left-join misses") was followed in
  substance and not in location. The detection sits at the INPUT gate, which runs
  on both pipeline entries, because the information is strictly richer there: at
  the join the miss is a null obligor attribute, indistinguishable from an
  obligor row that exists and has no rating, and the reference that was supplied
  — the one thing an operator needs to repair the feed — has already been
  consumed. Nothing in the fix drops a row: an exposure that has left the
  portfolio is worse than one priced off a fallback, because its capital is gone
  and no total says so.

  **Null and orphan carry DIFFERENT codes**, against this entry's own
  recommendation that they "should carry the same code". They reach the same
  engine fallback, which is exactly why the distinction has to be drawn at the
  gate or not at all — downstream both are a null attribute and the information
  is gone. But they are repaired in different files: an orphan needs the PARENT
  feed extended or corrected (DQ005), a null needs THIS row's column populated
  (DQ001, `absent_reference_error`, category `DATA_QUALITY` to keep it apart from
  the seal's missing-COLUMN DQ001 under `SCHEMA_VALIDATION`). One code would have
  sent an operator looking in the wrong file.

  **DQ004 is uncapped here, breaking the module's own `sample_cap` contract**,
  and deliberately. The domain gates sample a property of a COLUMN — naming any 5
  of 900 out-of-domain rows locates the repair — whereas a duplicate key is a
  property of a ROW, and a sampled duplicate leaves every un-sampled row exactly
  as unaccounted-for as it was before the gate existed. That is also precisely
  what `tests/robustness/harness.py` encodes by refusing to let clause (c) excuse
  a `collapsed` row. The population is bounded by the number of DISTINCT
  duplicated keys: zero on well-formed input, equal to the corruption on broken
  input.

  Cost of the two new materialisations, measured on a synthetic portfolio where
  every reference resolves and every key is unique (so both checks pay their full
  scan and emit nothing): **1.06%** of a full pipeline run at 100k loans / 10k
  counterparties, **0.63%** at 1M loans. Both live in the input gate, which
  already collects per table; no collect was added to a lazy stage.

  Two fixture repairs were needed and neither loosened an assertion.
  `tests/unit/test_loader.py::test_scrub_and_validate_returns_empty_for_valid_data`
  passed `pl.LazyFrame()` for loans and facilities — a zero-COLUMN frame is not a
  zero-ROW one, and the seal's literals broadcast it to a **single phantom
  all-null row**, so the "valid data" bundle contained an exposure with no
  obligor. It now declares a key column and is genuinely empty.
  `tests/contracts/test_validation.py::test_clean_bundle_raises_nothing` declared
  a rating for a counterparty absent from the bundle and gave its loan and
  facility no obligor at all; it now names an obligor that exists. Both were
  asserting that a broken bundle is silent.
- **Lesson**: **a declared error code with no producer is negative coverage.** It
  reads as enforcement to every reviewer, to every grep and to every import-graph
  tool, while enforcing nothing — the same shape as the 402 lines of unreachable
  validators in the entry above, one level further out. Check 20
  (`check_guard_reachability`) closed the unreachable-*validator* case; the
  unreachable-*code* case is its exact analogue and is mechanically checkable in
  the same way: every `ERROR_*` constant in `contracts/errors.py` should either
  have a producer under `src/` or be explicitly listed as reserved, as Phase 0 did
  for DQ003. Two of the three defects in this entry sat behind a declared code;
  the third had no code at all until DQ014 was written for it, so the check would
  have flagged exactly the two that were flaggable.
  That is the graduation candidate this entry files; it is not performed here
  because `scripts/arch_check.py` was being edited by another agent in the same
  tree and check 20's own entry records the same reason for the same restraint.

## 2026-08-17 — Two fixes for one taint finding, neither of which touched the flow the tool reported

- **Defect**: `pythonsecurity:S2083` (BLOCKER) on
  `scripts/generate_regulatory_tables.py` survived two fixes written to close
  it. Commit `2b1be086` introduced `TARGET_PATHS` and removed `targets.items()`
  as the write-loop iterator; its successor went further and bound the loop
  variable directly off the constant at the sink, duplicating a comparison to do
  so. Neither moved the finding, because the flow SonarCloud actually reports is
  not about the path. It is two steps, identical on both versions (line numbers
  from `master` / the PR head):

  ```
  source  line 821 / 848: path.read_text(...) in _splice   → the file CONTENT
  sink    line 703 / 729: path.write_text(desired, ...)     → "a malicious value
                                                              can be used as argument"
  ```

  `_splice` reads the target to preserve the hand-written prose outside the
  `GENERATED` markers; that content becomes `targets[path]`, then `desired`,
  then the write's data argument. The taint is the content. Writing
  file-derived content to a compile-time-constant path is not path injection,
  so there was never a structural fix to find — the flow is the feature.
- **Rule**: Not a regulatory escape. No RWA number is affected; the script is
  developer/CI codegen whose only external input is a boolean `--check` flag.
- **Origin**: the diagnosis, not the code. `sonar-project.properties` asserted
  that "`scripts/` findings are always structural" and cited this very file as
  the worked example, so both fixes started from a premise the tool's own
  evidence contradicts.
- **Escape class**: `wrong-premise`. The premise ("the write path is taken from
  a mapping whose values were read off disk, therefore S2083") was wrong and was
  faithfully implemented twice, which is exactly what the class describes. Note
  that `test-shared-the-assumption` also fits the *symptom* —
  `test_generator_write_paths_do_not_come_from_the_rendered_mapping` passed
  against an unfixed finding, because it encoded the same wrong sentence — but
  it prescribes re-anchoring the test, and re-anchoring a test to a false
  mechanism produces a better-engineered wrong gate. The first attempt at this
  entry made that mistake: it classed the escape `test-shared-the-assumption`
  and shipped an AST gate asserting the write path is bound from the constant,
  a property that is real, cheap, and irrelevant to what was flagged. The class
  has to name the wrong belief, not the instrument that agreed with it.
- **Why every gate missed it**: only SonarCloud can see this flow, and nothing
  in the loop ever read what it said. The finding arrives as a rule name plus
  one line number, and both fixes were designed from that — the rule's title
  ("I/O function calls should not be vulnerable to path injection") points at
  the path, and the flow points at the content. The full source → sink was
  available the whole time and never fetched: SonarCloud uploads SARIF to GitHub
  code scanning, so `codeFlows` is two `gh api` calls away and needs no
  SonarCloud credentials. Local gates cannot substitute — `ruff` and
  `arch_check` have no taint model, and the freshness tests measure output bytes
  and were green throughout, correctly, since both refactors were
  behaviour-neutral.
- **Gate change**: the misdirecting premise is deleted at its source. The
  `S6549 / S2083` note in `sonar-project.properties` no longer claims
  `scripts/` findings are always structural; it records this flow verbatim, and
  carries the `gh api` incantation that retrieves any flow from the SARIF
  without SonarCloud access. `.claude/LESSONS.md` gains the trap in
  Trap/Why/Detect form, `Detect` being that command. The finding itself is
  resolved as **Accepted** in the SonarCloud platform (issue
  `AaAMt-IEKije7nS9AwhB`), which is the only mechanism available: taint findings
  cannot be suppressed from the properties file under Automatic Analysis, as the
  same note already recorded.

  This is prose-tier and that is a real weakness, so the stronger form is filed
  rather than hand-waved: `scripts/sonar_flow.py`, a helper that takes an alert
  number or rule key and prints the source → sink chain, would make the
  retrieval a command nobody can skip rather than a paragraph they must
  remember. It is not built here because the fix for a wrong premise is to
  delete the premise, and shipping a new script alongside it would put a second
  unreviewed thing in the same change-set.
- **Verified red**: the retrieval run against the *pre-fix* commit
  (`6456d808`, master) returns the true flow, contradicting the premise that
  shipped in both fixes:

  ```
  RULE: pythonsecurity:S2083 in scripts/generate_regulatory_tables.py
    step 1: line 821  Source: a user can craft an HTTP request with malicious content
    step 2: line 703  Sink: this invocation is not safe; a malicious value can be
                            used as argument
  ```

  Line 821 on `master` is `for line in path.read_text(encoding="utf-8")` inside
  `_splice` — the content read, not a path expression. Two minutes of this
  against the original finding would have prevented both fixes; that is the
  sense in which the gate is observed red.
- **Lesson**: *a taint finding is a flow, not a line.* The rule name tells you
  the sink family and nothing about the source, and a sink can be reported for a
  tainted **argument** rather than a tainted path — which inverts the whole
  remedy. The tell here was misread twice as evidence: `read_text` sitting
  unflagged beside a flagged `write_text` looks like proof that provenance is
  the variable, when it only means the read takes no tainted argument. Fetch the
  `codeFlows` first; every fix designed from the rule title alone in this repo
  has failed.
