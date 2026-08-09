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

`--mutants`, `--categories`, `--timeout`, `--resume` and `--out` all work as you
would expect. Every pytest gate carries `-n 0`: this runs on a machine with
~2.7 GB free, and `-n auto` would spawn sixteen workers each building session
fixtures.

Where `uv` is unavailable — a bare venv, a git worktree with no `.venv` — set
`DEFECT_INJECTION_PYTHON` to an interpreter and every gate command is retargeted
through it. Before any gate runs, the harness makes that interpreter import an
engine entry point once; if it cannot spawn, the campaign **aborts non-zero with
nothing scored**, rather than scoring every gate red and publishing a fabricated
~100% detection rate.

**Do not run a campaign while another agent is testing `src/`.** The harness
edits real source files. Their failures would be yours.

## Three verdicts, not two

| Verdict | Meaning |
|---|---|
| `DETECTED` | A gate went red. We know which, at what tier, and how long it took. |
| `ESCAPED` | The mutant changed output and every gate stayed green. |
| `UNREACHABLE` | The mutant applied cleanly but changed no observable output. |

The three stay distinct everywhere they are published — in the scorecard JSON, in
the rendered board, and in the ratchet. Collapsing `UNREACHABLE` into `ESCAPED`
makes the headline rate fiction in the pessimistic direction; the reverse makes
it fiction in the optimistic one.

`TIMEOUT` is a fourth gate *outcome*, and is never counted as a pass. It is not a
verdict — see the caveat under [Reading the board](#reading-the-board) for what
the harness does with it today and why the ratchet treats it as a hard failure.

### Why UNREACHABLE has to exist

Mutating the rulepack's `output_floor_pct_full` from 0.725 to 0.100 once left
52 of 52 output-floor properties passing. That reads as proof the properties
were vacuous. They were not — that scalar is only consumed when a firm elects
`skip_transitional` on `OutputFloorConfig`, which no test does. The mutation
applied perfectly to a **dead path**.

Without a reachability probe, that mutant scores as an escape and the headline
rate is fiction in the pessimistic direction. So every mutant must be shown to
move an output *before* any gate runs. The probe runs one portfolio through both
regimes and hashes every generated template cell; both regimes, because a
Basel-3.1-only mutant moves nothing under CRR and "wrong regime" must not be
mistaken for "dead path".

### The two controls

The catalogue carries a matched pair whose verdicts prove the probe still works:

- `control-unreachable-output-floor-full` — the dead scalar above. **Must** come
  back `UNREACHABLE`. If the scorecard ever calls it an escape, the probe is
  broken and every other "not detected" verdict in the report is unsafe.
- `control-reachable-output-floor-schedule` — the schedule step that *is* read.
  **Must** come back `REACHABLE`.

Any mutant whose verdict contradicts its `expect_unreachable` flag is reported
under **expectation mismatches**, which is the signal that the catalogue has
rotted against the code. `injection_ratchet.py --check` fails on any such
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

22 mutants over 10 files, seeded in descending order of evidential weight.

| Category | Count | Source |
|---|---|---|
| `known_defect` | 4 | Defects this project actually found |
| `lessons` | 3 | `.claude/LESSONS.md` traps with a mechanical form |
| `generic` | 13 | Constant perturbations, flipped operators, dropped casts |
| `control` | 2 | The reachability pair above |

### Known defects are injected on their *twin*

The four known defects exist in the tree today, so injecting them again would be
a no-op. Each is instead applied to the **adjacent correct site of the same
shape** — if the estate catches the twin, it would have caught the original.

For example, C 02.00 asks for `("advanced_irb", "central_government")` where the
enum says `central_govt_central_bank`, pinning row 0310 to zero permanently. The
mutant does the same thing to the *correct* institution lookup on the next line.

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

**1. Trust.** Is this scorecard readable at all? Each of these makes the headline
rate fiction in a known direction, so they are checked before anything is
compared against a baseline:

- every catalogue mutant carries a verdict (a filtered or sharded run does not);
- no verdicts for mutants absent from the catalogue (a stale scorecard);
- no mutant's reachability contradicts its `expect_unreachable` flag;
- no gate `TIMEOUT` anywhere;
- no verdict outside `DETECTED` / `ESCAPED` / `UNREACHABLE`;
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
  --scorecard nightly-injection/scorecard-legacy.json \
  --scorecard nightly-injection/scorecard-full.json
```

`--note` is mandatory: a baseline that moved for a reason nobody wrote down is
indistinguishable from one someone widened to clear a red gate. `--bank` refuses
a scorecard that failed any trust check — a baseline banked from fiction would
enshrine that fiction as the thing every future run is measured against.

To render or re-render a board without gating anything:

```bash
uv run python scripts/injection_ratchet.py --summary \
  --scorecard nightly-injection/scorecard-legacy.json \
  --scorecard nightly-injection/scorecard-full.json \
  --out nightly-injection/summary.md
```

`--summary` is a renderer, not a gate. `--check` is the gate.

## Two blockers before the first bankable run

Both are real, both are recorded in `scripts/injection_baseline.json` under
`blockers`, and both are owned elsewhere. Do not rediscover them.

**The reachability probe's control pair has stopped discriminating** (task
`0.1a`). `control-unreachable-output-floor-full` carries
`expect_unreachable=True` and comes back **reachable**, because
`scripts/generate_regulatory_tables.py:314` enumerates the very pack key the
mutation renames — so the mutation moves a generated docs artefact and the probe
sees output move. The catalogue's own rationale is explicit that while a control
contradicts its flag, every "not detected" verdict is unsafe. Diagnosed, not yet
re-based. `--check` fails on it independently of the baseline, which is the
intended behaviour, not a nuisance.

**A quiet tree** (task `0.1`). The campaign mutates `src/` one file at a time and
refuses to start if any catalogue target is dirty in git, so it cannot run while
anyone is editing `src/` — and if it did, their failures would score as
detections. This is why the first bankable run is a manual dispatch on a quiet
`master` rather than an ordinary nightly.

A third, now closed: the harness hardcoded `uv run` for every gate, so on a
runner where `uv` cannot spawn every gate returned non-zero, every mutant scored
`DETECTED`, and the campaign would have published a fabricated ~100% rate.
`DEFECT_INJECTION_PYTHON` plus the spawn pre-flight fixed that. The nightly does
not depend on the override — GitHub runners have `uv` — but a locally measured
baseline does.

## Reading the board

The headline detection rate is computed over **scored** mutants only —
`UNREACHABLE` ones are excluded from both numerator and denominator, because
counting them either way is a lie in one direction or the other.

The escaped list is the deliverable. A detection rate is a number; its complement
is a work queue. The plan's target is **≥ 90% on the known-defect mutants** —
they have already escaped once, so failing to catch them is inexcusable — with a
published, tracked figure on the generic set. Neither figure exists yet.

Two caveats found while wiring the nightly, both in `defect_injection.py` and
both **still open**:

- **A gate `TIMEOUT` does not stop the ladder and does not score as a
  detection** — the runner continues to the next rung. That is right as far as it
  goes, but it means a mutant whose only catching gate timed out can still finish
  as `ESCAPED`, and an escape resting on a gate that never completed is
  *unproven*, not measured. The ratchet therefore treats any `TIMEOUT` as a hard
  failure of the whole campaign rather than letting it be banked.
- **`--resume` does not merge earlier results into the scorecard it writes.** It
  filters which mutants it runs, then overwrites `--out` with only the resumed
  subset. A resumed run is therefore not a complete one and cannot be banked —
  which is also why sharding a long campaign needs a real combine step, not
  `--resume`.
