---
description: Turn a production defect into a harness change. Establishes what was wrong, reconstructs how it escaped every gate, then fixes the gate that should have caught it — not just the code. Writes an escape record to docs/development/escape-log.md.
argument-hint: <commit-sha | PR# | short description of the defect>
---

You are running a postmortem on a defect that **reached production**:
**$ARGUMENTS**

The code fix is not the deliverable. The deliverable is the answer to one
question:

> **Which gate should have caught this, and why didn't it?**

A postmortem that ends in a fix commit and a shrug has taught the system
nothing. This project has 92 `fix(...)` commits in its last 400; the ones
that mattered changed a gate.

Read `.claude/LESSONS.md` first — this defect may already be a known trap
that was never graduated into a check, which is itself the finding.

## The closing rule

**A defect found in output is closed by its escape-log entry, not by its fix
commit.** The entry closes it only when all three of these are filled:

1. an **escape class** from the eight in Step 3;
2. a **named gate change** — a file path, or a Tier 1 plan bullet ID if deferred;
3. **verified red** — recorded evidence the new gate was observed failing
   *before* the fix, quoting the command and the failure line.

Any of the three missing means the defect is still open. Do not report it as
closed, and do not tell the operator the postmortem is done — say which of the
three is missing and what it would take. See Step 7's output contract.

## Step 1 — establish the defect

Do not take the report at face value; it may be a misreading of correct
output. Establish, with evidence:

- **What was produced**, and **what should have been produced**.
- **The controlling rule**, quoted verbatim. Extract from the PDFs yourself
  (`uv run python -c "import fitz; ..."` — see `.claude/LESSONS.md` A2) or
  via the `basel31` / `crr` Skill. Do not rely on recall.
- **The sign and magnitude**: does the defect over- or under-state capital,
  and by how much on a real portfolio? An understatement is a filing risk of
  a different order from an overstatement.
- **The blast radius**: which templates, regimes, and exposure classes.

If the reported defect turns out **not** to be a defect — a limit of a
published rule, a DPM evaluation artifact, an arithmetic coincidence — stop
here and record it in the escape log as `not-a-defect` with the reasoning.
That is a valuable outcome and it prevents the next person re-litigating it.

## Step 2 — reconstruct the escape path

Walk the defect backwards through the harness and name the **first** stage
that could have stopped it:

| Stage | The question |
|---|---|
| Plan bullet | Did a wrong bullet specify this? (see `IMPLEMENTATION_PLAN.md` history) |
| Wave 0 premise audit | Was the item audited? Did the audit miss it, or predate the wave? |
| scenario-architect | Was the hand-calc wrong, or right but not carried through? |
| fixture-builder | Did the fixture never reach this code path? |
| test-writer | Was the assertion absent, relative, or sharing the code's assumption? |
| engine-implementer | Was the implementation wrong against a correct spec? |
| reviewer / skeptic | Was it reviewed? Which attack should have found it? |
| Batch gate | Was the catching test in the gate at all, at the time? |
| CI | Did CI run the suite that covers it before merge? |

Use `git log` / `git blame` on the fixed lines to find the originating
commit and, from the commit message's `[batch <id>]` footer, the batch that
produced it. Archived batch state under `.claude/state/archive/` records the
verdicts that batch's reviewers gave.

## Step 3 — classify the escape

Pick exactly one. The category determines the fix.

1. **`gate-not-run`** — a gate that would have caught it existed, but did not
   run at that point (wrong tier, feature branch CI never fired, test outside
   the batch gate's set).
   → *Fix: move the gate earlier.*

2. **`path-never-exercised`** — the gate existed and ran, but no fixture
   drove data through the affected code, so every relevant rule was
   `NOT_EVALUATED`. The supervisory gate **fails open**, so this is
   indistinguishable from clean.
   → *Fix: build the portfolio, and register it in `RUNS`.*

3. **`test-shared-the-assumption`** — a test covered the code and passed,
   because it was written from the same wrong sentence (invented enum
   strings, hand-written lists, assertions relative to a baseline).
   → *Fix: re-anchor the assertion to a source of truth that cannot drift
   with the code.*

4. **`no-assertion-of-presence`** — the output was absent or null rather than
   wrong, and nothing asserted it should exist.
   → *Fix: add presence assertions; consider a systemic non-null check.*

5. **`wrong-premise`** — the plan bullet or spec was wrong and the harness
   faithfully implemented it.
   → *Fix: strengthen Wave 0 for this bullet class; correct the audit entry.*

6. **`no-gate-exists`** — nothing in the estate could have caught it.
   → *Fix: create the gate.*

7. **`ungateable`** — genuinely not mechanically detectable (requires
   judgement on ambiguous regulatory text).
   → *Fix: a `.claude/LESSONS.md` entry, with the reasoning for why it cannot
   be a check. Use this category sparingly and argue for it.*

8. **`caught-and-parked`** — a gate *did* fire. The finding was recorded (a
   strict xfail, a `KNOWN_DISAGREEMENTS` entry, a plan bullet) and the record
   became its resting place, so the wrong number shipped anyway. Detection is
   not the problem; disposition is.
   → *Fix: ratchet the register the finding sits in (its size may not grow, and
   an entry needs an owning bullet), not a new detector.*

## Step 4 — fix the gate

This is the step people skip. Do it before or alongside the code fix.

Implement the gate change in the same change-set where practical:

- **New/extended fixture portfolio** → `tests/fixtures/`, registered in
  `tests/fixtures/generate_all.py` **and** in `RUNS` in
  `tests/acceptance/reporting/test_supervisory_validations.py`.
- **New architectural invariant** → a numbered check in `scripts/arch_check.py`
  plus its allowlist entry, and a test in `tests/contracts/`.
- **New ratchet** → extend the relevant metric in `scripts/arch_metrics.json`.
- **Re-anchored assertion** → rewrite against the enum / sealed carrier /
  `validations/scope.py::SHEET_INDEX_MAPS`.
- **Reviewer criterion** → add it to the wave checklist in
  `.claude/commands/next-items.md` Step 4d, or an attack in
  `.claude/agents/skeptic.md`. A criterion is the weakest form of gate — use
  it only when the check cannot be executable.

If the gate change is too large for this pass, file it as a **Tier 1** bullet
in `IMPLEMENTATION_PLAN.md` with `Ref:` pointing at this escape-log entry. Do
not close the postmortem with the gate unfixed and unfiled.

### Step 4b — see the gate go red (required, not advice)

A gate nobody has seen fail is not a gate; it is a gate-shaped assertion that
happens to be true. Take the first route that works and **record the command
and the failure line verbatim** — a paraphrase is not evidence:

1. **Revert the code fix** in a detached worktree (`git worktree add --detach
   HEAD`) and run the new gate.
2. **Perturb the input instead**, where the fix is not revertible in isolation:
   empty the column, drop the fixture row, edit the baseline by hand. Restore
   afterwards and say so.
3. **Inject the mutant**: add the defect to `scripts/defect_catalogue.py` and
   run `scripts/defect_injection.py --mutants <id>`, which reports the tier that
   caught it. This is the strongest route — it leaves the check behind.

If none of the three can be made to work, the gate is not demonstrated. Either
keep working, or classify the escape `ungateable` and argue it. "Expected to
catch it" and "the test looks right" are not verification, and a gate whose red
you could not produce goes into the entry as `Verified red: NOT VERIFIED`,
which leaves the defect open.

## Step 5 — write the escape record

Append to `docs/development/escape-log.md` (create it if absent, with a short
header explaining the file's purpose). One entry:

```markdown
## <YYYY-MM-DD> — <one-line defect summary>

- **Defect**: <what was produced vs what should have been; sign and magnitude>
- **Rule**: <article, quoted phrase, source>
- **Origin**: <commit / batch id / "pre-harness">
- **Escape class**: `<one of the eight categories>`
- **Why every gate missed it**: <the specific mechanism — one paragraph>
- **Gate change**: <what now catches it, with the file path> | <or: plan bullet ID>
- **Verified red**: <the command, and the failure line it emitted, without the fix>
- **Lesson**: <graduated to a check | added to LESSONS.md as <section> | none needed>
```

Escape class, gate change and verified red are **not optional fields**. An
entry that leaves one blank, or fills it with "n/a", is not an entry — it is the
shrug this file exists to prevent. `not-a-defect` entries (Step 1) carry the
reasoning in place of the last three fields, and nothing else may.

## Step 6 — update the lessons working set

- If the escape was **already** a known trap in `.claude/LESSONS.md` and
  reached production anyway, that lesson has proven it cannot survive as
  prose. Graduate it to a check in this pass, or file the graduation as a
  Tier 1 bullet. Note the recurrence in the escape-log entry.
- If it is new and you graduated it: add a row to the **Graduation ledger**
  at the bottom of `.claude/LESSONS.md`. Do not also add prose.
- If it is new and `ungateable`: add the prose entry, with its detection
  recipe. An entry without a **Detect** line is not finished.

Keep `.claude/LESSONS.md` under ~30 entries. If adding yours pushes it over,
graduate or delete a stale one in the same pass and say which.

## Step 7 — report

**Output contract.** You may not conclude without all three of the closing
rule's items. Open the report with them, on three lines, before anything else:

```
Escape class: <one of the eight>
Gate change:  <file path | Tier 1 bullet ID>
Verified red: <command> -> <failure line>   (or: NOT VERIFIED — defect stays open)
```

Then, in this order:

1. The defect, its sign, and its magnitude.
2. The one-sentence mechanism by which every gate missed it.
3. Whether the code fix is included here or deferred.
4. Anything you found while digging that is a **separate** defect — file
   each as a plan bullet; do not fix it in this pass.

## Constraints

- **The gate change is mandatory; the code fix is optional.** If you can only
  do one in this pass, do the gate and file the code fix.
- **The escape-log entry is the closing artifact.** A fix commit with no entry
  leaves the defect open, however green the tree is.
- Never regenerate goldens or the validation baseline to make a gate green.
  A ratchet failing because you fixed something is the design working —
  remove the register entry deliberately, with its written reason.
- Do not commit unless the operator asks. Report what you changed.
- One defect per invocation. Separate defects found along the way get filed,
  not fixed.
