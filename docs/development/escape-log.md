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

  `caught-and-parked` was added on 2026-08-09 with the first entry that needed
  it. The other seven all answer *why didn't a gate catch it*; this one is for
  the case where a gate did catch it, said so, and the wrong number shipped
  anyway. Forcing that into `no-gate-exists` or `ungateable` would record the
  opposite of what happened, and its fix is not a new detector — detection
  already works — but a disposition rule for the register the finding sits in.

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
  coverage is under control. Two of that condition's consequences were already
  paid for (B5 and its 2026-08-08 recurrence) before anyone noticed the ratchet
  was inert. **And the same inertness rotted the baseline it ratchets against.**
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
  cells rose 7,891 → 8,193 at constant matrix**, against 63,746 declared, so the
  ceiling moved because the declared population grew. And do not reason from the
  metric families moving in opposite directions — they are independent, so a real
  cell-coverage loss alongside an unrelated rule-coverage gain would look
  identical. The live-cell count is the decisive evidence; the direction of
  `dead_cells` alone is not evidence of anything.
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

  The one that matches this escape class — the invocation deleted from a scratch
  copy of `ci.yml`, which is precisely the state the estate was in:

  ```
  .github/workflows/ci.yml does not invoke `scripts/coverage_report.py --check`.
  The coverage ratchet is implemented but unrun, which is how it spent its whole
  life before P5.21: a change can kill a live cell or un-bind a published rule
  with every gate still green. Restore the `coverage-ratchet` job.
  ```

  And the ratchet itself rejecting a regression, fed a synthetic measurement
  through `coverage_report.py::_check_baseline` with one metric moved in each
  direction, as a defect that kills one column would move them (exit 1):

  ```
  [REGRESSED] union_binding_rules_crr: 251 -> 250 (may not decrease)
  [REGRESSED] dead_cells: 52817 -> 52818 (may not increase)
  [REGRESSED] never_evaluated_rules: 785 -> 786 (may not increase)
  Coverage went backwards. Either restore it, or update the baseline
  deliberately with --update-baseline and say why in the commit message.
  ```

  The `was` side of those deltas is the **stale committed baseline**, not the
  estate's current position — the figures the paragraph above explains.

  Both run without mutating the tree. Task 0.2 also drove the real test body
  through six perturbations — including a typo'd metric name, which would
  otherwise surface as a `KeyError` 46 seconds into CI — and ran the `slow` test
  for real to a genuine `1 failed in 46.66s`.

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
- **Lesson**: graduated. `.claude/LESSONS.md` B5's closing note already pointed
  at this ratchet as the executable form of the lesson; it is now executable.

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
  detection rate is unmeasured. Its own documentation says that before the
  harness existed nobody could say whether the rate was 40% or 90%; that
  sentence is still true, because building the instrument and reading it are
  different acts. (2) Every gate command in the ladder was hardcoded to spawn
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
  campaign and a detection-rate ratchet as task S.3. A second instrument defect
  surfaced on the first attempt to run it — the reachability probe's *unreachable
  control* comes back reachable, task 0.1a — which is the same failure shape as
  limb (2), and a third, task 0.1b, has the harness rewriting mutation targets
  with CRLF line endings. This entry is closed for the runner and open for the
  measurement.
- **Lesson**: this is the second of these four entries whose class is
  `gate-not-run` for the same underlying reason — the estate's habit is to build
  the measurement and stop before wiring it. That is a pattern rather than two
  slips, and the coverage ratchet's `test_the_coverage_ratchet_is_invoked_by_ci`
  is the shape of its fix: an instrument ships with a test that it is invoked.

## 2026-08-09 — Four wrong numbers were found by the oracle and parked as accepted disagreements

- **Defect**: `tests/oracle/` found four engine/oracle disagreements and all four
  sit in `KNOWN_DISAGREEMENTS` as `xfail(strict=True)` rather than fixed. One
  understates capital; the other three are conservative, which is not the same as
  harmless — they are wrong numbers in published templates:
  - **`ORC-109`** — CRR Art. 121(1) Table 5 is never applied to the institution
    exposure class; an unrated institution takes a flat 100% for every sovereign
    CQS. At **CQS 6 the engine returns 100% against a required 150% — an
    understatement of capital by a third**. Scope is narrower than the finding's
    original framing: a currency-mismatched row already reaches 150% via the
    PS1/26 Art. 121(6) floor (measured during the P1.316 Wave 0 audit), so the
    shortfall is the local-currency case. `ORC-105` (CQS 1, 20% vs 100%) and
    `ORC-020` (CQS 2, 50% vs 100%) are the conservative limbs of the same
    unwired ladder, and the family is pinned across its whole domain precisely
    because its direction is not uniform.
  - **`ORC-142`** — PS1/26 Art. 154(4A)(b) limb (iii). The 10% IRB mortgage
    RWEA floor is applied to residential property outside the UK: oracle floor
    adjustment 0.00, engine 373,345.27. Conservative in direction, but the limb
    is not mis-gated — it is **unrepresentable**. No module under `engine/irb/`
    reads any obligor or property country column (the only country carrier there
    is `guarantor_country_code`, for guarantee substitution), so no input could
    switch it off. The same missing carrier blocks **P2.50**.
- **Rule**: CRR Art. 121(1) Table 5 and Art. 121(2); PS1/26 Art. 121(6),
  Art. 154(4A)(b), Art. 163(1)(b)-(c).
- **Origin**: found 2026-08-08 by the independent oracle, on merge of the
  validation estate. The engine defects themselves predate it.
- **Escape class**: `caught-and-parked` — the eighth class, added with this
  entry. Every other class in the table answers *why didn't a gate catch it*, and
  here the gate worked exactly as designed: it derived the number independently,
  disagreed, and said so in the article's own terms. What failed is the
  disposition of that output. Classifying it `no-gate-exists` or `ungateable`
  would record the opposite of what happened, and `test-shared-the-assumption` is
  the reverse of the truth — the oracle refused to share the assumption, which is
  why it found this at all.
- **Why every gate missed it**: no gate missed it. `strict=True` is real
  discipline in one direction — it prevents a silent *fix*, because an entry that
  starts agreeing becomes an XPASS and a hard failure — and no discipline at all
  in the other. `KNOWN_DISAGREEMENTS` has no size ratchet, no owning bullet per
  entry, and no expiry, so a live capital understatement can rest there
  indefinitely while the suite reports green. The register was built to make
  findings triageable and became the place they are stored instead.
- **Gate change**: **deferred, and named.** The code fixes are tracked
  (`ORC-105`/`ORC-020`/`ORC-109` under **P1.316**, which must delete all three
  register entries in the same change; `ORC-142` needs the property-location
  carrier that **P2.50** also needs, and has no bullet of its own yet), and the
  workstream item is task S.2, ORC-109 first as the only anti-conservative limb.
  The *gate* change this class prescribes is separate and not yet filed: a two-way
  ratchet on the size of `KNOWN_DISAGREEMENTS`, plus a requirement that each entry
  names an owning plan bullet, so parking a finding costs something and ageing one
  is visible.
- **Verified red**: n/a for detection — the disagreements are red today, by
  design, as strict xfails. **NOT VERIFIED** for the disposition ratchet, which
  does not exist yet. By this file's closing rule the escape therefore remains
  open, which is the correct state to record: what exists today is the detection,
  not the correction.
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
- **Why every gate missed it**: `v0211_m` is one of **five** live ERROR rules on
  the C 02.00 hierarchy — `v0204_m`, `v0205_m`, `v0207_m`, `v0210_m`, `v0211_m` —
  that appear **nowhere** in `validation_known_breaks.json`, neither as broken nor
  as vacuous. They do not run at all. The leading hypothesis, filed as task #19,
  is that C 02.00 never passes through the cellspec executor the register reads, so
  the whole template sits outside the machinery. Two consequences worth stating
  plainly:

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
  step 0.1's scorecard), task #17 for the row-axis shift, task #19 for the five
  unevaluated rules. The order matters: making `v0204_m`/`v0210_m`/`v0211_m`
  evaluate is the cheapest of the three and, on the evidence above, catches the
  row shift and the subtotal composition together. Independent re-derivation of
  C 02.00's class rows in `tests/conformance/` is the belt-and-braces second layer,
  not the first move.
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
- **Gate change**: in this change-set, from task 0.2b — `cells_live` added to
  `_RATCHET_MIN` as a true floor, banked at **8,193**. It is already computed as
  `payload["cells"]["live"]`, it fell in 15 of the 16 deletions and in both
  config-silencing variants, and it never rose on a loss. Filed separately:
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
