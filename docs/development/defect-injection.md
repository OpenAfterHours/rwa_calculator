# Defect-injection scorecard

Everything in the validation estate is a hypothesis about what would have been
caught. This harness measures it.

It injects a known-realistic defect into `src/`, walks a ladder of gates
cheapest-first, stops at the first gate that goes red, and records which one. The
output is a detection rate, the mean tier at which detection happens, and — the
part that actually matters — **the list of defects nothing caught**.

## Status: the mechanism exists, the number does not

**No campaign has ever been run end to end, so the estate's detection rate is
unknown.** Nobody can currently say whether it is 40% or 90%. The harness was
built to answer that and has not yet been able to; the reasons are two concrete
blockers, both recorded below with their task references.

Read that as a standing correction to anything on this page that sounds like a
result. The numbers used in the explanations here are *worked examples* — the
only figures anyone has actually measured are the reachability verdicts of a
handful of individual mutants, gathered while debugging the probe. In particular
`scripts/defect_scorecard.json`, which is checked in, is the output of a
`--reachability-only` run over **one** mutant, not a campaign: every verdict in
it is `PROBED`, and the ratchet refuses it.

The mechanism is nonetheless wired, gated and reviewable: the nightly workflow
runs both ladders, publishes the board, and a ratchet fails **non-zero** for as
long as the baseline stays un-banked. It is red by design until the first
campaign is measured. A workflow claiming to gate on a number nobody has
measured would be worse than no workflow.

| File | Role |
|---|---|
| `scripts/defect_catalogue.py` | The mutants. Adding one is a single entry; the runner never changes. |
| `scripts/defect_injection.py` | The runner: safety, reachability probe, ladder, scorecard. |
| `scripts/defect_scorecard.json` | Generated. The checked-in copy is a one-mutant probe run, not a campaign. |
| `scripts/injection_ratchet.py` | Renders the board (`--summary`), gates it (`--check`), banks it (`--bank`). |
| `scripts/injection_baseline.json` | The banked verdict sets. Currently `status: UNBANKED`. |
| `.github/workflows/nightly-injection.yml` | Runs both ladders nightly, publishes the artefacts, runs the gate. |

## Running it

```bash
uv run python scripts/defect_injection.py --self-test          # verifies the catalogue, applies nothing
uv run python scripts/defect_injection.py --reachability-only  # probes, runs no gates
uv run python scripts/defect_injection.py --ladder legacy      # the before rate
uv run python scripts/defect_injection.py --ladder full        # the after rate
```

`--mutants` and `--categories` filter the run, and `--timeout` overrides every
gate's timeout. `--out` names the scorecard: its directory must already exist
and be writable, and so must the file if there is one. The harness refuses to
start otherwise (exit 4) rather than find out when it first writes. The
scorecard is replaced after **every** scored mutant — written beside `--out` as
`<name>.partial` and renamed over it, never rewritten in place — so a campaign
that dies part-way, a crash or a Ctrl-C even mid-write, keeps everything it
measured, and `--resume` finishes it (see
[Resuming a campaign](#resuming-a-campaign)). Without `--resume`, `--out` is
replaced by this run's selection alone, whatever the file held. The nightly
uploads each leg's scorecard whatever the campaign step's outcome, so a leg
stopped by the job's own timeout publishes what it measured too. Every pytest
gate carries `-n 0`: this runs on a machine with ~2.7 GB free, and `-n auto`
would spawn sixteen workers each building session fixtures.

Where `uv` is unavailable — a bare venv, a git worktree with no `.venv` — set
`DEFECT_INJECTION_PYTHON` to an interpreter and every gate command is retargeted
through it. Before any gate runs, the harness makes that interpreter import an
engine entry point once; if it cannot spawn, the campaign **aborts non-zero with
nothing scored**, rather than scoring every gate red and publishing a fabricated
~100% detection rate. That covers an interpreter that cannot start, hangs, is
killed, or cannot import the engine; it does not cover one that imports the
engine but cannot run a gate's own tool (see below).

`tests/contracts/test_defect_injection_spawn.py` gates both behaviours without
running the real `uv`:

- Unset, every spawned argv is byte-identical to its declaration: the pre-flight,
  every gate and every `baseline_cmd`.
- Set, every spawned argv is retargeted, and a command that cannot be retargeted
  is refused rather than left on `uv`.
- Every pre-flight failure branch raises, including an interpreter that starts
  and imports `rwa_calc` but not the engine's dependency stack. So the probe
  cannot be weakened from `rwa_calc.engine.pipeline` to bare `rwa_calc`, which is
  lazy and lets that interpreter through. An interpreter killed by a signal (an
  OOM kill reports exit `-9`) is refused too, so a refusal of only positive exit
  codes fails the test.
- `uv`'s own lock failure is refused: `error: Could not acquire lock: Read-only
  file system` on stderr, then exit 2. It is refused on the default path, with
  the override unset and a `uv` stub on `PATH` that fails that way. That models
  the sandbox where this was measured: the harness started from the venv's
  Python, and the inner `uv` failing. It is also refused through an override
  interpreter that fails the same way. The abort must quote that error. So a
  refusal made conditional on the override, or one that tolerates "lock" in
  stderr, fails the test.
- `main()` exits 2 before the baseline digest, before any mutant and before
  writing a scorecard. This is checked with the override set to a missing
  interpreter. With the override unset it is checked twice: `uv` that cannot be
  found, and `uv` that exits 2 on its lock. Each case runs under the legacy,
  `full` and `fast` ladders, with `--mutants` naming one mutant, and with
  `--resume`. So a pre-flight skipped for any of those runs fails the test.

What these tests do not cover is a gate that is red on the clean tree for a
reason of its own while the interpreter starts and imports the engine. The
pre-flight passes, and every mutant that gets past the rungs below that gate is
scored `DETECTED` at it. Two instances are known. On a runner with no `uv`, the
`contracts` rung is one such gate: `tests/contracts/test_wheel_install_gate.py`
requires `uv` on `PATH`. And an override interpreter that imports the engine but
has no `pytest` (a wheel-only or `--no-dev` environment) passes the pre-flight
and turns every pytest gate red. Until the
harness runs every gate once on the clean tree before any mutant, a campaign
with `DEFECT_INJECTION_PYTHON` set on a machine without `uv` can fabricate
detections at that rung.

**Do not run a campaign while another agent is testing `src/`.** The harness
edits real source files. Their failures would be yours.

### Resuming a campaign

`--resume` merges into the scorecard already at `--out`. It keeps every
**settled** verdict — `DETECTED`, `ESCAPED` or `UNREACHABLE` (`PROBED` or
`UNREACHABLE` for `--reachability-only`) with no gate timed out — and measures
the rest of the selection: mutants the file does not have, and any `ERROR`,
`UNPROVEN`, or verdict a gate timed out on. A detection behind a timed-out gate
is measured again too, because the ratchet refuses any `TIMEOUT` and a kept one
could never be cleared. It writes the **union**, this run's result winning, with
the scorecard recomputed over all of it, so a resumed campaign over the whole
catalogue is a complete, bankable one. The union includes every earlier result
this run did not select: a campaign too long for one window is chunked with
`--categories` (or `--mutants`), each later chunk resumed into the same `--out`,
and re-running one timed-out mutant with `--resume --mutants <id>` keeps the
rest of the file.

It refuses to merge (exit 5, nothing written) unless the earlier file was
measured the same way: same ladder, gate list, interpreter, mode
(`--reachability-only` or not), commit, and narrow and wide baseline digests. The
first five are checked before anything is spawned, the digests once the baselines
are captured. A file holding two estates' measurements would read as one
campaign, and the ratchet could not tell — the catalogue would be complete. A
field the earlier file does not record is a mismatch, never a match, so every
scorecard written before `--resume` merged (none records the mode, the commit or
the wide digest) is refused: kept, a probe-only file's gate-less `UNREACHABLE`
verdicts would be banked as if a gate had run.

What it cannot see is an **uncommitted** edit outside the catalogue targets — a
gate's test file, a gate command. The dirty-target refusal covers only the
catalogue's `src/` targets, and such an edit moves neither the commit nor either
digest, so the earlier file would merge. Do not edit the tree between a run and
its resume; commit first, and the changed commit is refused.

`--resume` does not shard a campaign across parallel CI legs: each leg starts
from a fresh checkout with no earlier file, and the ratchet takes one scorecard
per ladder. Sharding still needs a step that combines the legs' scorecards.

## Three verdicts, not two

| Verdict | Meaning |
|---|---|
| `DETECTED` | A gate went red. We know which, at what tier, and how long it took. |
| `ESCAPED` | The mutant changed output and every gate stayed green. |
| `UNREACHABLE` | No gate went red, and the mutant changed no observable output. |

The three stay distinct everywhere they are published — in the scorecard JSON, in
the rendered board, and in the ratchet. Collapsing `UNREACHABLE` into `ESCAPED`
makes the headline rate fiction in the pessimistic direction; the reverse makes
it fiction in the optimistic one.

`TIMEOUT` is a fourth gate *outcome*, and is never counted as a pass — nor as
the evidence for a verdict. `ESCAPED` and `UNREACHABLE` both say every gate stayed
green, and a gate that timed out never finished: it may be the one that would
have caught the mutant. So a mutant **no gate caught while any gate timed out**
is scored `UNPROVEN`, whatever the probe said — on the probe-dead branch as much
as the reachable one, because gates do catch mutants the probe calls dead.
`UNPROVEN` is not a result. It is outside the rate, the escape list and the
unreachable list, listed on its own with the gates that timed out, and the
ratchet refuses a scorecard that carries it. A gate that goes red after an
earlier one timed out is still `DETECTED`: the ladder carries on past a timeout,
and the red rung is a measured catch.

### Why UNREACHABLE has to exist

Mutating the rulepack's `output_floor_pct_full` from 0.725 to 0.100 once left
52 of 52 output-floor properties passing. That reads as proof the properties
were vacuous. They were not — that scalar is only consumed when a firm elects
`skip_transitional` on `OutputFloorConfig`, which no test does. The mutation
applied perfectly to a **dead path**.

Without a reachability probe, that mutant scores as an escape and the headline
rate is fiction in the pessimistic direction. So every mutant is probed for
whether it moves an output, and a mutant that no gate catches counts as an escape
only if it did. The probe runs `rich` through both regimes and hashes every
generated template cell, escalating to the whole RUNS matrix when `rich` shows
nothing. Both regimes, because a Basel-3.1-only mutant moves nothing under CRR,
and "wrong regime" must not be mistaken for "dead path".

**The gates run on every mutant; the probe never overrides one.** The probe sees
only the RUNS portfolios' templates, and a unit test reaches paths no portfolio
exercises: a scalar wrapper, or an (approach, class) pair no fixture carries. A
gate going red is a detection whatever the probe says. The probe decides one
thing: whether a mutant **no** gate caught is `ESCAPED` or `UNREACHABLE`. Until
2026-11-14 the harness skipped the gates whenever the probe said unreachable.
That went unnoticed only because the probe never said so (see below). Once it
did, two of the four known defects that a unit-test gate catches would have
scored `UNREACHABLE`.

**The digest must be deterministic, and is checked to be.** The pipeline's
parallel sums are not bit-reproducible. Two unmutated captures rendered one
Basel 3.1 C 09.01 cell as `51355833.333333336` and then `51355833.33333333`.
Hashed at full precision, that one-ulp difference moved the digest on every call,
so every mutant probed reachable and none was ever escalated to the wide matrix.
Floats now enter the digest at `DIGEST_SIGNIFICANT_FIGURES` (10). Each baseline
is also captured twice, and the campaign aborts (exit 3) before scoring anything
if the two captures disagree.

### The two controls

The catalogue carries a matched pair whose verdicts prove the probe still works:

- `control-unreachable-output-floor-full` — the dead scalar above. **Must** come
  back `UNREACHABLE`. If the scorecard ever calls it an escape, the probe is
  broken and every other "not detected" verdict in the report is unsafe.
- `control-reachable-output-floor-schedule` — the schedule step that *is* read.
  **Must** come back `REACHABLE`.

Both are judged on the **probe's** result (`reachable` in the scorecard), not on
the verdict. A gate may still catch the dead-path control: its pack key is listed
by name in `scripts/generate_regulatory_tables.py`, so renaming it can turn the
docs freshness test red. That is a detection, not a broken probe. Any mutant whose probe result contradicts its
`expect_unreachable` flag is reported under **expectation mismatches**, which is
the signal that the catalogue has rotted against the code. `injection_ratchet.py --check` fails on any such
mismatch, independently of the baseline: while a control disagrees with its flag
there is no licence to believe any non-detection verdict, so there is nothing
worth ratcheting.

### Reachable is not the same as observable

The reachable control got its direction wrong first time and is worth
understanding, because the same trap will catch the next person.

The reporting date on the rich portfolio is 2027-06-01, which selects the
`(2027-01-01, 0.60)` schedule step — so the entry is unambiguously on the live
path. But **the output floor does not bind on that portfolio at 60%**, so
*lowering* it to 10% changed nothing and the probe correctly said `UNREACHABLE`.
Raising it to 95% forces it to bind.

> A mutant on a live path can still be unobservable if it only relaxes a
> constraint that was already slack.

That also tells you something about the estate: on the current portfolio matrix,
**no floor-lowering mutation is observable at all**, which is worth remembering
when reading any floor-related property as evidence.

## The catalogue

22 mutants over 11 files, seeded in descending order of evidential weight.

| Category | Count | Source |
|---|---|---|
| `known_defect` | 4 | Defects this project actually found |
| `lessons` | 3 | `.claude/LESSONS.md` traps with a mechanical form |
| `generic` | 13 | Constant perturbations, flipped operators, dropped casts |
| `control` | 2 | The reachability pair above |

### Known defects are injected on their *twin*

A known defect that is still in the tree cannot be injected again — that would be
a no-op — so each is applied to the **adjacent correct site of the same shape**:
if the estate catches the twin, it would have caught the original. A twin outlives
its original: the two C 02.00 defects were fixed on 2026-11-13, and their mutants
stay, on the sites that were always correct.

For example, C 02.00 asked for `("advanced_irb", "central_government")` where the
enum says `central_govt_central_bank`, pinning the A-IRB central-governments row to
zero for as long as the template existed. The mutant does the same thing to the
*correct* institution lookup on the next line.

### Adding a mutant

One `Mutant(...)` entry. `old` must appear **exactly once** in `target` — the
self-test enforces presence and uniqueness, which is what stops the catalogue
rotting silently as the code moves underneath it. Set `expect_unreachable=True`
if the mutant is a deliberate dead-path control.

A new mutant makes the banked baseline stale by construction: it appears in no
banked set, so `--check` reports it and demands a re-bank. That is the intended
flow — measure the new mutant, then bank it with a `--note` saying what it is.

## The ladder

Cheapest first, so the tier of detection is a real measure of how early the
estate notices.

| Tier | Gate | In the legacy ladder? |
|---|---|---|
| 0 | `arch_check` | yes |
| 1 | `tests/oracle` | no |
| 2 | `tests/properties` | no |
| 3 | `tests/unit` | yes |
| 4 | `tests/contracts` | yes |
| 5 | `tests/acceptance` | yes |
| 6 | `tests/acceptance/reporting` | yes |
| 7 | `scripts/coverage_report.py` | no |
| 8 | `scripts/impact_report.py compare` | no |

`--ladder legacy` runs only the gates that existed before the independent
validation work; `--ladder full` adds the rest. **Running both gives a
before/after detection rate from one build**, which is the number that says
whether C1–C5 were worth their cost.

Adding a gate is one `Gate(...)` entry. `baseline_cmd` runs once on the clean
tree for gates that compare against a captured snapshot (the impact report needs
one); `{baseline}` is substituted with a scratch path.

## Safety

The harness edits real source files, so:

- It **refuses to start if any catalogue target is dirty in git**. Recovery is
  therefore always `git checkout -- <file>`, and no uncommitted work can be
  destroyed.
- Restoration is triple-guarded: a context manager `finally`, an `atexit` hook
  armed for the duration, and a byte-comparison after restoring that raises if
  the file did not come back.
- A mutant naming a file outside the catalogue's declared targets is refused.
- One mutant is applied at a time. There is no combined state.

If the process is killed mid-mutation anyway, `git status` shows exactly one
modified file and `git checkout -- <that file>` is a complete recovery. Note that
`atexit` does not run under `SIGKILL`, so a hard-killed campaign is the one case
where the guards do not fire and the manual recovery is the only recovery.

## The nightly

`.github/workflows/nightly-injection.yml` runs the campaign at **02:17 UTC
daily**, and is also `workflow_dispatch`-able by hand — which matters more than
the cron for now, because the first real run will be a manual one.

Why that time. GitHub's hosted-runner fleet is busiest during US and European
working hours, and scheduled workflows are queued rather than guaranteed. 02:17
UTC is ~03:17 UK, well outside the operator's working day, so an hours-long
campaign never competes with interactive CI for runner concurrency and the result
is waiting at the start of the next working day. The `:17` is deliberate too:
GitHub queues scheduled workflows in bulk on the hour, and on-the-hour crons are
the most delayed of all.

Two mechanics to know before wondering why a nightly did not run:

- `schedule` fires **only on the default branch**. A nightly that lives on a
  feature branch never runs — the same silent-no-op shape as the `master`-only
  push trigger `ci.yml` was built to fix. This workflow has to reach `master`.
- GitHub disables scheduled workflows after 60 days with no repository activity,
  and mails the owner. Re-enable from the Actions tab.

### What it does

| Job | What it runs |
|---|---|
| `campaign (legacy)` | self-test, then `--ladder legacy` → `scorecard-legacy.json` |
| `campaign (full)` | self-test, then `--ladder full` → `scorecard-full.json` |
| `ratchet` | needs both; renders the combined board, uploads it, then `--check` |

The two ladders are matrix legs with `fail-fast: false`, so a failure in one does
not throw away the other half of the before/after measurement. Both are required
by the `ratchet` job, because a single-ladder run cannot answer whether the added
gates were worth their cost.

Artefacts, all uploaded with `if-no-files-found: error` so a silently absent
result fails the job rather than reading as a clean run:

- `injection-scorecard-legacy` / `injection-scorecard-full` — the scorecard JSON
  plus that ladder's rendered board.
- `injection-summary` — the combined before/after board: detection rate, mean
  tier of detection, and the `ESCAPED` list.

Each board is also appended to the run's `$GITHUB_STEP_SUMMARY`, so the result is
readable in the GitHub UI without downloading anything. The combined board is
rendered and uploaded **before** the gate runs, on purpose: `--check` is expected
to fail while the baseline is un-banked, and the board is the artefact that has
to survive that failure.

There are no `workflow_dispatch` inputs. A filtered campaign (`--mutants`,
`--categories`) is not bankable — the ratchet refuses a scorecard that does not
carry a verdict for every catalogue mutant, because the un-run ones would bank as
though they did not exist. Debugging runs belong on a developer machine.

The campaign job carries `timeout-minutes: 330`, under the 6-hour hosted-runner
ceiling so the timeout is ours and legible rather than GitHub's opaque cancel.
**The real wall clock is unmeasured.** If a leg hits that ceiling the fix is not
to raise it past 360 — it is to shard the catalogue across more matrix legs, and
to combine the shards' scorecards into one complete file before banking.

## The ratchet, and its deferred baseline

`scripts/injection_ratchet.py --check` is the gate. It runs four groups of
checks, reports all of them, and exits non-zero if any failed — deliberately not
fail-fast, because the first manual run needs to see everything in one pass or
banking becomes a guess-and-retry loop.

It also requires **both ladders** (listed first among the findings, and, like
every other check, not stopping the rest): a run holding only one scorecard is
itself a finding, because the before/after pair from one build is
the point of running two, and one ladder cannot answer whether the added gates
were worth their cost.

**1. Trust.** Is this scorecard readable at all? Each of these makes the headline
rate fiction in a known direction, so they are checked before anything is
compared against a baseline:

- every catalogue mutant carries a verdict (a filtered or sharded run does not);
- no verdicts for mutants absent from the catalogue (a stale scorecard);
- no mutant's reachability contradicts its `expect_unreachable` flag;
- no gate `TIMEOUT` anywhere;
- no verdict outside `DETECTED` / `ESCAPED` / `UNREACHABLE` (an `ERROR`, a
  `PROBED`, or an `UNPROVEN` resting on a timed-out gate);
- the scorecard records which interpreter produced it.

A ladder that fails any of these has its verdict sets **skipped**, not compared:
an untrustworthy scorecard's sets are not comparable to anything, and comparing
them anyway buries the one real finding under a wall of derived ones.

**2. The known-defect floor.** At least **90%** of the catalogue's
`known_defect` mutants must be `DETECTED`. The denominator comes from the
catalogue, not from the verdicts, which has two consequences worth stating
plainly. With four known-defect mutants, "≥ 90%" is arithmetically "all four" —
3/4 is 75% — so it is not a soft target. And an `UNREACHABLE` known-defect
mutant counts **against** the floor: it means the twin site is dead, and we
cannot demonstrate the estate would catch a defect that already got through once.

**3. The baseline.** `scripts/injection_baseline.json` currently carries
`status: UNBANKED`, and `--check` fails on that alone — loudly, printing the
reason, the blockers, and the banking command. An unrecognised status is treated
as un-banked too, never as banked, so a typo cannot read as a green gate.

**4. The two-way set ratchet**, once banked. Per ladder:

| Set | Invariant |
|---|---|
| `detected_ids` | may not **lose** a member |
| `escaped_ids` | may not **gain** a member |
| `unreachable_ids` | may not **gain** a member |

Movement in the good direction fails too, as `BANK REQUIRED`. A ratchet going
red because you fixed something is the design working; bank the improvement
deliberately (`.claude/LESSONS.md` E1).

### How the gate itself is tested

While the baseline is `UNBANKED`, `--check` can never pass: the status is itself
a finding, reported alongside whatever else fails. So the nightly cannot reach
the `BANKED` branch, and cannot see the gate pass. A gate that has never been
seen to pass cannot be shown to tell a good run from a bad one, so
`tests/contracts/test_injection_ratchet_gate.py` drives `check()` directly with
synthetic boards — no campaign, no pipeline run:

- a trust-clean, floor-clean `BANKED` pair whose sets equal the baseline must
  exit **0**;
- each of the **18** kinds of finding — the missing ladder, the six trust
  checks (the reachability one in both directions, so seven kinds), the floor,
  `UNBANKED`, an unrecognised status, a `BANKED` baseline with no entry for a
  ladder, and the three regressions and three `BANK REQUIRED` improvements of
  the set ratchet — is introduced **alone** on top of that clean pair, on each
  ladder where the check is per ladder, and must exit **1** with exactly that
  one finding. The unrecognised status is reached two ways, a wrong value and
  no `status` key at all, because reading an absent status as `BANKED` would
  turn the gate quiet;
- the floor is read from the baseline (a missing `known_defect_floor` means
  90%, and a rate equal to the floor meets it), and a set missing from a banked
  ladder entry is read as empty, never as whatever the board holds now, so
  everything the board holds in that set is reported as movement;
- several groups failing at once must all be reported (not fail-fast), and an
  untrusted ladder's sets must be skipped while the other ladder is still
  compared — its missing baseline entry too, which surfaces once the ladder is
  trusted again; a `BANKED` baseline with no `ladders` key at all is one
  missing-entry finding per ladder, never a crash;
- a known defect that is `UNREACHABLE`, carries another verdict, or never ran
  must fail the **floor** as well as trust, on each ladder. Trust alone would
  keep the exit code at 1, so this is the case that pins the floor's
  catalogue denominator against the headline rate's scored pool;
- `--summary` must publish every section, in order, with its content — every
  per-ladder section carrying a line for **each** ladder, `legacy` first. Its
  two alarms must tell good from bad (`.claude/LESSONS.md` B9): the "these
  numbers are not evidence" banner must be absent on a clean pair and present
  when either ladder, or both, fails trust, and the trust all-clear must appear
  exactly when no ladder fails. Its quiet branches (a floor with every known
  defect detected, nothing unreachable, a ladder that caught nothing) are
  pinned line for line. A floor that passes while still missing a known defect
  is not a quiet branch: it names the missed defect, and that is pinned too.

The test asserts no count of checks. A count still passes when one check is
changed to return nothing; a case per finding kind does not.

`check()` and `render_summary()` are each split into one small function per
group or section (SonarCloud `python:S3776` had flagged both, at cognitive
complexity 38 and 36). The group list in `check()` and the section list in
`render_summary()` are the one place each is enumerated. Any further change to
either runs under the test above, unchanged.

### Why the gate is on sets and not on the rate

The headline detection rate is `detected / (detected + escaped)` with
`UNREACHABLE` excluded from both halves, so its **denominator moves with its
numerator**. A mutant that drifts onto a dead path leaves the scored pool
entirely: absolute detection falls while the rate can *rise*. That is
`.claude/LESSONS.md` B8 — ratchet the accumulator, never a ratio of it — so the
gate is stated on three absolute id sets and the rate is reported only.

`unreachable_ids` is ratcheted for exactly that reason. Letting the unreachable
set grow silently is the single move that lets the published rate improve while
the estate's measured coverage shrinks.

### Banking the first baseline

Once both blockers below are clear, dispatch the workflow by hand, download the
two scorecards, and bank them:

```bash
uv run python scripts/injection_ratchet.py --bank \
  --note 'First measured campaign: <what the numbers were and why they are trustworthy>' \
  --ladder legacy --ladder full
```

`--ladder` takes a ladder NAME, not a path. The scorecards are read from fixed
locations under `nightly-injection/` (see `_SCORECARD_PATHS`), so put the
downloaded artefacts there. The script deliberately accepts no arbitrary paths:
operator-supplied path arguments were a genuine traversal surface and are gone
rather than sanitised — see the note above `_SCORECARD_PATHS`.

`--note` is mandatory: a baseline that moved for a reason nobody wrote down is
indistinguishable from one someone widened to clear a red gate. `--bank` refuses
a scorecard that failed any trust check — a baseline banked from fiction would
enshrine that fiction as the thing every future run is measured against.

To render or re-render a board without gating anything:

```bash
uv run python scripts/injection_ratchet.py --summary \
  --ladder legacy --ladder full --write-summary
```

Like `--bank`, it reads the scorecards from `nightly-injection/` and, with
`--write-summary`, writes `nightly-injection/summary.md` (or
`summary-<ladder>.md` for one ladder); without it the markdown goes to stdout.

`--summary` is a renderer, not a gate. `--check` is the gate.

## Two blockers before the first bankable run

Both are real, both are recorded in `scripts/injection_baseline.json` under
`blockers`, and both are owned elsewhere. Do not rediscover them.

**Probe-unreachable catalogue entries.** With the probe deterministic, 11 of the
22 mutants move nothing in the RUNS matrix (measured with `--reachability-only`,
2026-11-14):
- **3 by design:** the flagged `expect_unreachable` mutants.
- **8 the catalogue expects to be reachable:**
  - three of the four known defects (`known-c02-phantom-class-key`,
    `known-p3-empty-class-tuple`, `known-sovereign-ladder-flattened`);
  - `lessons-e3-subtotal-double-count`;
  - `generic-firb-corporate-stranded`, `generic-benefit-cap-inverted`,
    `generic-b31-institution-cqs2` and `generic-scaling-regime-inverted`.

`lessons-e3-subtotal-double-count` and `generic-b31-institution-cqs2` were
re-targeted on 2026-11-20 and now probe reachable (see "Catalogue drift" below),
which leaves 6 of the 8. The other 6 were all caught by a gate in the
2026-11-16 campaign, so they do not fail the trust check.

Two causes so far:
- C 02.00 rows that are empty in every RUNS portfolio (the A-IRB institutions and
  F-IRB specialised-lending lookups).
- `engine/irb/formulas.py::calculate_irb_rwa`, a scalar wrapper the pipeline
  never calls.

Gates still run on all of them. Any mutant that **no** gate catches scores
`UNREACHABLE` and fails the trust check until it is re-targeted at a live site,
or a RUNS portfolio exercises its path.

**A quiet tree** (task `0.1`). The campaign mutates `src/` one file at a time and
refuses to start if any catalogue target is dirty in git, so it cannot run while
anyone is editing `src/` — and if it did, their failures would score as
detections. This is why the first bankable run is a manual dispatch on a quiet
`master` rather than an ordinary nightly.

Two more, now closed:
- **The interpreter override.** The harness hardcoded `uv run` for every gate.
  On a runner where `uv` cannot spawn, every gate returned non-zero, every mutant
  scored `DETECTED`, and the campaign would have published a fabricated ~100%
  rate. `DEFECT_INJECTION_PYTHON` plus the spawn pre-flight fixed that. The
  nightly does not depend on the override, since GitHub runners have `uv`, but a
  locally measured baseline does.
- **The control pair that stopped discriminating** (task `0.1a`). Every mutant,
  `control-unreachable-output-floor-full` included, probed reachable because the
  digest was not deterministic (above). It was recorded as a docs artefact moving
  under the probe, but the probe hashes template cells only. Fixed 2026-11-14:
  under the stable probe, all three `expect_unreachable` mutants come back
  `UNREACHABLE` and `control-reachable-output-floor-schedule` comes back
  reachable.

A run of the harness also used to leave `engine/irb/formulas.py` dirty. That file
is committed with CRLF endings, and `injected` restored the decoded text rather
than the bytes. It now restores and verifies the bytes, so the next campaign is
no longer refused on a dirty target.

### Catalogue drift (2026-11-17 to 2026-11-20)

From 2026-11-17 every nightly died in the catalogue self-test, about 13 seconds
in, because four mutants' `old` strings had moved under them:

- `lessons-b1-dead-carrier`: the CCF carrier ladder left `corep/c07.py` for
  `corep/ccf_buckets.py` (`CCF_CARRIERS`, now shared by C 07.00 and OF 08.01).
- `generic-corporate-correlation-low`, `-high` and `generic-correlation-decay`:
  the Art. 153(1) corporate correlation now lives in
  `engine/irb/formulas.py::_corporate_correlation_expr_from_pd`, the live path.

All four are re-targeted at the new sites. Two more mutants were re-targeted
because they could never move an output, which is what failed the trust check
on every completed campaign before that:

- `generic-b31-institution-cqs2` renamed the ECRA table's `name` field, which no
  lookup reads (the pack binds on the dict key). It now reverts CQS 2 to the
  CRR 50%.
- `lessons-e3-subtotal-double-count` added col 0040 inside the 0090 subtotal,
  but the 0090 `Formula`'s `refs` never include 0040, so the extra term was
  always `None`. It now has col 0110 deduct 0090 twice, the defect
  `_net_after_substitution` records.

The self-test is the guard against the first kind; nothing but a campaign
catches the second.

## Reading the board

The headline detection rate is computed over **scored** mutants only —
`UNREACHABLE` ones are excluded from both numerator and denominator, because
counting them either way is a lie in one direction or the other. `UNPROVEN` ones
are excluded from both halves too, and listed separately with the gates that
timed out: an escape resting on a gate that never finished is unproven, not
measured.

The escaped list is the deliverable. A detection rate is a number; its complement
is a work queue. The plan's target is **≥ 90% on the known-defect mutants** —
they have already escaped once, so failing to catch them is inexcusable — with a
published, tracked figure on the generic set. Neither figure exists yet.

Three defects found while wiring the nightly were closed on 2026-11-23 (P5.46).
Until then a mutant whose only catching gate timed out finished as `ESCAPED`, in
the published escape list and indistinguishable from a real escape, or as
`UNREACHABLE` when the probe called it dead; `--resume` overwrote `--out` with
only the mutants it had just run; and the scorecard was written once, at the very
end, into a directory nothing had checked existed, so any abort before that write
lost the whole campaign. The ratchet refused both corrupted shapes throughout (any
`TIMEOUT`, and any catalogue mutant with no verdict), so nothing wrong was ever
bankable — but the board and the scorecard JSON published it. Pinned in
`tests/contracts/test_defect_injection_probe.py`.
