# Defect-injection scorecard

Everything in the validation estate is a hypothesis about what would have been
caught. This harness measures it.

It injects a known-realistic defect into `src/`, walks a ladder of gates
cheapest-first, stops at the first gate that goes red, and records which one.
The output is a detection rate, the mean tier at which detection happens, and —
the part that actually matters — **the list of defects nothing caught**.

Before this existed, nobody could say whether the estate's detection rate was
40% or 90%.

| File | Role |
|---|---|
| `scripts/defect_catalogue.py` | The mutants. Adding one is a single entry; the runner never changes. |
| `scripts/defect_injection.py` | The runner: safety, reachability probe, ladder, scorecard. |
| `scripts/defect_scorecard.json` | Generated. Per-mutant verdicts plus the headline numbers. |

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

**Do not run a campaign while another agent is testing `src/`.** The harness
edits real source files. Their failures would be yours.

## Three verdicts, not two

| Verdict | Meaning |
|---|---|
| `DETECTED` | A gate went red. We know which, at what tier, and how long it took. |
| `ESCAPED` | The mutant changed output and every gate stayed green. |
| `UNREACHABLE` | The mutant applied cleanly but changed no observable output. |

`TIMEOUT` is its own gate outcome and is never counted as a pass.

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
rotted against the code.

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
modified file and `git checkout -- <that file>` is a complete recovery.

## Reading the scorecard

The headline detection rate is computed over **scored** mutants only —
`UNREACHABLE` ones are excluded from both numerator and denominator, because
counting them either way is a lie in one direction or the other.

The escaped list is the deliverable. A detection rate of 87% is a number; the
13% is a work queue. Target per the plan: **≥ 90% on the known-defect mutants**
— they have already escaped once, so failing to catch them is inexcusable — with
a published, tracked figure on the generic set.
