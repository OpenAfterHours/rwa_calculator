---
description: Pick top N non-conflicting items from IMPLEMENTATION_PLAN.md and drive them through the five-wave pipeline (premise-auditor → scenario-architect → fixture-builder → test-writer → engine-implementer) per item, with a reviewer gate between every wave, an adversarial skeptic on the design and implementation waves, and one revision retry per wave per item. Agents run in the background so the operator can chat with the orchestrator mid-batch. Default N=3, capped at 5. Hard-excludes items that touch shared engine files. An optional scope arg (e.g. `ccr` / `tier8`) restricts selection to a single tier.
argument-hint: [N] [scope]
---

You are draining `IMPLEMENTATION_PLAN.md` in batches. Each item runs
in its **own git worktree**, on its own `batch/<batch-id>/<P-code>`
branch. You drive the five-wave premise-auditor → scenario-architect →
fixture-builder → test-writer → engine-implementer chain directly, with
a `reviewer` gate after every wave and an adversarial `skeptic`
alongside it on the design and implementation waves. Agents run with
`run_in_background: true` so your turns end after dispatch and the
operator can chat with you freely while the batch is in flight.

After all items have either reached `merge_ready` or been dropped,
you squash-merge each surviving worktree branch back into the
**current branch** (the operator pre-creates a feature branch before
invoking this command), run the global validation gate **once** on
the merged tree, run the **retro** that turns this batch's failures
into gates, then tick the plan and clean up the worktrees.

## Why the pipeline starts with a refutation

The four-wave chain that preceded this one was a closed inference
loop: the architect derived a hand-calc from the plan bullet, the
test asserted the architect's numbers, the implementer made them pass,
and the reviewer checked the chain against itself. Nothing in it could
notice that the **bullet was wrong** — and measured across two
consecutive drains, 6 of 10 and then 10 of 10 bullets had a materially
wrong premise, two of them prescribing actively unsafe fixes.

Wave 0 exists to kill those before any work is done, and the `skeptic`
exists so at least one node in each item is allowed to disagree with
the chain. Treat a `PREMISE: refuted` as the batch's cheapest success.

Parse `$ARGUMENTS` as an integer **N** (default 3, cap 5) optionally
followed by a **scope** token. The integer is N (if absent or not an
integer, use 3). Any non-integer token is the scope:

- `ccr`, `tier8`, or `P8` → **CCR scope**: select only Tier 8
  (Counterparty Credit Risk, `P8.*`) items. See Step 1.
- absent or anything else → **default scope**: the normal tier walk
  in Step 1.

Examples: `/next-items` → N=3 default scope; `/next-items 2` → N=2
default scope; `/next-items 3 ccr` → N=3 CCR scope; `/next-items ccr`
→ N=3 CCR scope.

## Core architecture

This command spans **multiple turns**. The orchestrator (you) is an
event-driven supervisor: kick off the batch in one turn, end the
turn, then react to agent completion notifications and operator
messages across subsequent turns until the batch is fully resolved.

To survive context compactions and operator interruptions, the
orchestrator persists batch state to
`.claude/state/next-items-<batch-id>.json` and **reads that file at
the start of every turn** before doing anything else. The state file
is the source of truth for what is in flight. Conversation context
is supplementary.

## Step 1 — pick a batch

Read `IMPLEMENTATION_PLAN.md`.

**If the scope is `ccr`** (from `$ARGUMENTS`, see above): consider
**only Tier 8 — Counterparty Credit Risk (CCR) Integration**. Pick
the highest-priority unchecked (`[ ]`) `P8.*` items in plan order,
skipping anything explicitly marked `DEFERRED v2.0` / Phase 10. Do
**not** fall through to any other tier — if Tier 8 has no eligible
unchecked items left, report "no CCR work to do" and stop. Everything
else in this command (worktrees, five-wave pipeline, reviewer loop,
hard exclusions, merge, gate, tick) is unchanged. Note that many CCR
items touch shared files (`engine/pipeline.py`, `contracts/bundles.py`,
`contracts/protocols.py`, `engine/registry.py`) and so will be forced
single-stream by the hard-exclusion rule below — that is expected.

**Otherwise (default scope)**, walk tiers in order:

1. Tier 1: Calculation Correctness
2. Tier 2: Test Coverage Gaps
3. Tier 3: COREP Reporting Completeness
4. Tier 4: Pillar III Disclosure Gaps
5. (skip Tier 5: the docs queue — that's `/next-docs` territory)
6. Tier 6: Code Quality
7. (skip Tier 7: Future / v2.0)
8. (skip Tier 8: CCR — only reached via the `ccr` scope above)
9. (skip Tier 9 and beyond unless promoted into Tiers 1–6)

Items migrated from the retired docs plan (2026-08-08) carry legacy
`D<n>.<n>` codes but are ordinary items — use the D-code wherever
these instructions say P-code (worktree branch names, state file
keys, commit messages).

For each candidate item, infer its expected change footprint by
reading the bullet's `Ref:` field, the cited file paths, and the
named test.

**Soft preferences** (try to satisfy, but a violation is no longer a
disqualifier — the worktree merge surfaces conflicts cleanly):

1. Distinct top-level under `src/rwa_calc/engine/` (e.g. `engine/sa/`,
   `engine/irb/`, `engine/crm/`, `engine/slotting/`, `engine/equity/`,
   `engine/stages/re_split/`, `engine/stages/hierarchy/`,
   `engine/stages/classify/`).
2. Distinct file in `src/rwa_calc/rulebook/packs/`, or a distinct
   pack-binding shim (`engine/sa/{crr,b31}_risk_weight_tables.py`,
   `engine/crm/haircut_tables.py`). The `data/tables/` package no
   longer exists.
3. Distinct new test path under `tests/`.

If two candidates clearly target the same shared helper or the same
data-table row, prefer to defer one to the next batch — that avoids
a known-bad merge before you start.

**Hard exclusions** — any candidate that requires changes to:

- `src/rwa_calc/engine/pipeline.py`
- `src/rwa_calc/engine/registry.py`
- `src/rwa_calc/engine/orchestrator.py`
- `src/rwa_calc/contracts/protocols.py`
- `src/rwa_calc/contracts/bundles.py`
- `src/rwa_calc/contracts/edges.py`
- `src/rwa_calc/engine/aggregator/` (any module — the reporting projection
  spans `aggregator.py` + `_summaries.py` + `_collapse.py`)
- `src/rwa_calc/analysis/reconciliation.py`
- `src/rwa_calc/reporting/cellspec.py`
- `src/rwa_calc/reporting/metadata.py`

is forced single-stream. Pick it alone, even if N>1 was requested,
report the downgrade ("Picked P-code only; touches pipeline.py —
single-stream, no worktree"), and run it in the **main tree** as the
old flow did. The worktree machinery is only worth it when N>1.

If the queue is empty, report "nothing to do" and stop.

Generate a short batch identifier `<batch-id>` (e.g. timestamp
`YYYYMMDD-HHMM`) — used for branch names, commit footers, and the
state filename.

## Step 2 — confirm before dispatch

Capture the **current branch** (`git branch --show-current`) — this
is the merge target. If it is `master`, warn the operator: squash
commits will land on master unless they abort and check out a feature
branch.

State to the operator, one line per item:
`<P-code> | Tier <n> | engine: <subpkg> | pack: <file or none> | test: <path> | branch: batch/<batch-id>/<P-code> | worktree: ../rwa_calculator-<P-code>`

If any candidate was downgraded to single-stream, say so and skip
Step 3 (no worktree).

## Step 3 — provision worktrees

Skip this step entirely for single-stream / hard-excluded items.

For each batched item, run from the main repo:

```
git worktree add -b batch/<batch-id>/<P-code> ../rwa_calculator-<P-code> HEAD
```

This creates one branch + one tree per item, all rooted at the
current HEAD of the merge-target branch. Capture each worktree's
absolute path — agents will need it.

Sanity check after all worktrees are created:

```
git worktree list
```

Expect the main tree plus N sibling entries.

## Step 4 — drive the five-wave pipeline (background, with reviewer loop)

This step is multi-turn. It begins with a kickoff (Step 4a), then the
orchestrator processes one turn at a time (Step 4b) until every item
has reached `merge_ready` or `dropped`. The reviewer dispatch and
revision-retry mechanics are in Steps 4c–4e. The per-wave reviewer
criteria are in Step 4d.

The waves, in order:

| # | Wave | Agent | Reviewed by |
|---|---|---|---|
| 0 | `premise_audit` | `premise-auditor` | `reviewer` |
| 1 | `scenario_architect` | `scenario-architect` | `reviewer` + `skeptic` |
| 2 | `fixture_builder` | `fixture-builder` | `reviewer` |
| 3 | `test_writer` | `test-writer` | `reviewer` |
| 4 | `engine_implementer` | `engine-implementer` | `reviewer` + `skeptic` |

### Step 4a — kickoff

Create the state file at
`.claude/state/next-items-<batch-id>.json` with this initial schema.
Use the Write tool to overwrite the file as a complete JSON document
— do not patch line by line, JSON edits by an LLM are too brittle.

```json
{
  "batch_id": "<batch-id>",
  "merge_target_branch": "<current branch>",
  "main_venv_path": "<absolute path to repo .venv>",
  "started_at": "<ISO 8601 timestamp>",
  "items": [
    {
      "p_code": "P1.114",
      "tier": 1,
      "bullet_text": "<exact bullet text from IMPLEMENTATION_PLAN.md>",
      "stream": "worktree",
      "branch": "batch/<batch-id>/P1.114",
      "worktree_path": "<absolute worktree path>",
      "current_wave": "premise_audit",
      "agent_status": "in_flight",
      "premise_verdict": null,
      "revision_count": {
        "premise_audit": 0,
        "scenario_architect": 0,
        "fixture_builder": 0,
        "test_writer": 0,
        "engine_implementer": 0
      },
      "review_verdicts": {"conformance": null, "skeptic": null},
      "outputs": {},
      "drop_reason": null,
      "retro_notes": [],
      "current_agent_name": "premise-auditor-P1.114-r0"
    }
  ]
}
```

`stream` is `"worktree"` for batched items and `"main_tree"` for
single-stream / hard-excluded items. For `main_tree` items,
`worktree_path` is `null`.

`premise_verdict` is set from Wave 0 and is `confirmed`, `rescoped`,
or `refuted`. `review_verdicts` holds the current wave's verdicts and
is reset to `{"conformance": null, "skeptic": null}` on every wave
advance. `retro_notes` accumulates anything Step 7.5 should consider —
append to it whenever a reviewer or the gate surfaces something that
looks repeatable rather than item-specific.

**Before dispatching Wave 0, extract the regulatory text yourself.**
Role-agents cannot read `docs/assets/*.pdf` — `Read` needs `pdftoppm`,
which is not installed — so a `premise-auditor` left to its own devices
may quote an article from memory and sound certain. For each item,
locate and extract the controlling article:

```bash
uv run python -c "
import fitz
doc = fitz.open('docs/assets/ps126app1.pdf')
print(doc[63].get_text())
"
```

Paste the verbatim text into the Wave 0 prompt. This is **mandatory**
for any item whose fix would reduce RWA. If you cannot locate the
article, say so in the prompt rather than omitting it silently.

In a single message, dispatch one `premise-auditor` Agent call per
item, **all with `run_in_background: true`** and a stable `name` of
the form `premise-auditor-<P-CODE>-r0`. Use the prompt template:

> This is a NEW item. It is NOT any item you may have seen before.
>
> Try to **refute** the plan bullet for **<P-CODE>** below. Answer the
> four questions in your system prompt and return a structured verdict.
> A refutation is a success — do not look for reasons to confirm.
>
> --- plan item ---
> {{exact bullet text}}
>
> --- audit entry (if this is a compliance-audit item) ---
> {{the matching §5 entry from
> docs/plans/compliance-audit-crr-111-241-rectification.md, verbatim}}
>
> --- verbatim regulatory text (extracted by the orchestrator) ---
> {{PDF text, with filename and page index — or an explicit statement
> that it could not be located}}

`premise-auditor` is read-only and operates in the main tree; do not
include the worktree preamble for this wave.

End the kickoff turn with a one-line summary to the operator:

> Batch `<batch-id>` kicked off: N items in flight at Wave 0
> (premise-auditor). I'll continue when each returns; you can ask me
> anything — status, drop an item, inspect outputs — in the meantime.

### Step 4b — supervisor protocol (every subsequent turn)

At the start of every turn during a live batch, before responding to
the operator or processing notifications:

1. **Read the state file**
   `.claude/state/next-items-<batch-id>.json`. If it does not exist,
   the batch is over — proceed to Step 5 if there are merge-ready
   items, otherwise stop.

2. **Identify what changed since last turn**:
   - **Operator message**: respond to the operator. Common requests:
     - *Status*: summarise the state file. Format per item:
       `<P-code>: wave=<current_wave> status=<agent_status> revisions=<sum>`.
     - *Drop an item*: set its `agent_status` to `dropped`,
       `drop_reason` to `"operator-drop"`, and if the agent for that
       item is still in flight, attempt to stop it via the `TaskStop`
       tool (look up its schema via `ToolSearch` if you don't have
       it). Persist state. Confirm to operator.
     - *Inspect output*: read the corresponding entry's `outputs`
       map and surface it.
   - **Agent completion notification**: identify which item it
     corresponds to (by `current_agent_name`). Store the agent's
     output in the appropriate `outputs` slot. Then progress that
     item — see step 3.

3. **Per-item progression rules** (apply to every item whose
   `agent_status` just changed):

   | Current state | Trigger | Next action |
   |---|---|---|
   | `agent_status: in_flight` | (no completion yet) | keep waiting |
   | `agent_status: returned` (role-agent just finished) | — | dispatch the review set for this wave per Step 4c; set `agent_status: in_review`; reset `review_verdicts` to nulls |
   | `agent_status: in_review` | **some** dispatched reviewer still outstanding | record the returned verdict in `review_verdicts` and keep waiting — do **not** advance on a single `pass` |
   | `agent_status: in_review` | all dispatched reviewers returned, **worst** verdict `pass` | advance `current_wave` to the next wave; if past Wave 4, set `current_wave: merge_ready` and stop dispatching for this item; otherwise dispatch the next role-agent (Step 4c again, with that wave's prompt) and set `agent_status: in_flight` with `current_agent_name: <next-wave>-<P-CODE>-r0` |
   | `agent_status: in_review` | worst verdict `revise` AND `revision_count[<wave>] == 0` | re-dispatch the original role-agent per Step 4e with **both** reviewers' feedback; increment `revision_count[<wave>]`; set `agent_status: in_flight` with `current_agent_name: <wave>-<P-CODE>-r1` |
   | `agent_status: in_review` | worst verdict `revise` AND `revision_count[<wave>] >= 1` | drop. Set `agent_status: dropped`, `drop_reason: "revision-failed-<wave>"`. Stop dispatching for this item. |
   | `agent_status: in_review` | worst verdict `drop` | drop. Set `agent_status: dropped`, `drop_reason: "reviewer-drop-<wave>: <drop-reason text>"`. Stop dispatching for this item. |

   **Verdict precedence** on waves with two reviewers: `drop` beats
   `revise` beats `pass`. Both must return before the item moves. A
   `skeptic` `revise` on a `reviewer` `pass` is the normal, expected
   case — it is the whole reason the skeptic exists, so do not treat
   the disagreement as an error to be arbitrated.

3a. **Wave 0 verdict handling** (before the table above applies).
   When the `premise-auditor` returns, record `premise_verdict` and
   act on it:

   - `confirmed` → dispatch `reviewer` per Step 4c, then proceed
     normally.
   - `rescoped` → dispatch `reviewer` per Step 4c. On pass, advance to
     Wave 1 and pass the auditor's **Corrected premise** as the
     authoritative task, with the original bullet included only as
     context marked *superseded*. Note the rescope in `retro_notes`
     and surface it to the operator — the bullet in
     `IMPLEMENTATION_PLAN.md` will need correcting at Step 7.
   - `refuted` → **stop the item.** Set `agent_status: dropped`,
     `drop_reason: "premise-refuted: <auditor's one-line basis>"`.
     Append the refutation to `retro_notes`. This is a **success**, not
     a failure — report it that way to the operator, and note that
     Step 7 must close the bullet in `IMPLEMENTATION_PLAN.md` as
     `closed-claim-invalid` rather than leaving it to be re-picked by
     the next batch.

   Wave 0 gets the same one-revision allowance as any other wave: a
   `reviewer` `revise` on a thin or unsourced audit re-dispatches the
   `premise-auditor` once.

4. **Persist state**: after processing all changes in this turn,
   write the updated state file. Use atomic-write semantics: write
   to `<file>.tmp` via Write, then `mv <file>.tmp <file>` via Bash.

5. **Decide whether to end turn or continue**:
   - If at least one new role-agent or reviewer was dispatched this
     turn, end the turn with a brief one-line status summary so the
     operator can interject. Do not poll.
   - If every item is either `merge_ready` or `dropped`, the batch
     is complete — proceed to Step 5 in this same turn.
   - If you only processed an operator message and no new dispatches
     were made, end the turn after responding.

### Step 4c — review dispatch

When a role-agent returns and you're advancing to review:

Spawn one `reviewer` Agent call per just-returned item, with
`run_in_background: true` and `name: reviewer-<wave>-<P-CODE>-r<revision-count>`.
Use this prompt template:

```
You are reviewing the output of a `<wave>` agent for item
**<P-CODE>** in batch `<batch-id>`. Apply only the criteria below
and return a structured verdict per your system prompt.

--- pass criteria ---
{{wave-specific checklist from Step 4d}}

--- prior context ---
Plan bullet:
{{bullet_text}}

Premise verdict: {{premise_verdict}}
{{the auditor's Corrected premise, if rescoped}}

{{prior wave outputs, if any — e.g. for fixture-builder review,
include the scenario proposal verbatim}}

Worktree path: {{worktree_path or "n/a (main_tree)"}}
Main venv path (for `UV_PROJECT_ENVIRONMENT`): {{main_venv_path}}

--- agent output ---
{{role-agent's full return value}}
```

**On Waves 1 and 4 only**, dispatch a `skeptic` in the *same message*,
with `run_in_background: true` and
`name: skeptic-<wave>-<P-CODE>-r<revision-count>`. It runs in parallel
with the reviewer, not after it. Prompt template:

```
Attack the output of the `<wave>` agent for item **<P-CODE>** in
batch `<batch-id>`. Run every applicable attack from your system
prompt and return a structured verdict. Your default is "unproven" —
a claim you could not test is `revise`, not `pass`.

--- what is being claimed ---
{{role-agent's full return value}}

--- premise (authoritative over the plan bullet) ---
Verdict: {{premise_verdict}}
{{the auditor's Corrected premise and Verbatim regulatory text}}
{{the auditor's Defect-pinning tests and Hazards sections}}

--- prior context ---
{{the scenario proposal verbatim; for Wave 4, also the test-writer
report and the exact targeted pytest path}}

Worktree path: {{worktree_path or "n/a (main_tree)"}}
Main venv path (for `UV_PROJECT_ENVIRONMENT`): {{main_venv_path}}

--- specific attacks the orchestrator wants run ---
{{name any that apply to this item: RWA direction, crossing amount,
column-footprint change, defect-pinning survivors, RUNS registration,
golden/baseline regen}}
```

After dispatching, set `agent_status: in_review` and reset
`review_verdicts` to `{"conformance": null, "skeptic": null}` (leave
`skeptic` as `"n/a"` on waves 0, 2 and 3 so the "all returned" test
is unambiguous).

### Step 4d — per-wave reviewer criteria (operator-visible)

These checklists are pasted verbatim into the reviewer's prompt at
Step 4c. They are deliberately written here, not derived implicitly
from each role-agent's system prompt, so the operator can audit and
tune them in this single file.

#### Wave 0 — premise-auditor verdict

```
C0.1 — First line is exactly `PREMISE: confirmed|refuted|rescoped`,
       alone on its own line.
C0.2 — All four questions answered explicitly (rule says what the
       bullet claims / code diverges / direction / scope), each with
       a one-line justification.
C0.3 — The "Verbatim regulatory text" section contains actual quoted
       article text with a named source (skill name, or PDF filename
       + page index) — OR an explicit statement that source text
       could not be obtained. A confident paraphrase with no source
       is a `revise`: that is precisely the failure mode this wave
       exists to prevent.
C0.4 — Question 3 (direction) states the sign. If the answer is
       RWA-reducing, it is flagged as such in capitals.
C0.5 — For `refuted` / `rescoped`: the "Corrected premise" section is
       present and concrete enough for scenario-architect to design
       from without re-reading the bullet.
C0.6 — The defect-pinning-test search was performed and its result
       reported (paths + function names, or an explicit "none
       found"). Any test whose assertion is RELATIVE to a baseline is
       called out.
C0.7 — Use Read on the cited source file to confirm the divergence
       claim in question 2 points at code that exists and says what
       the auditor says it says.
C0.8 — The verdict follows from the four answers. A `confirmed` with
       any question answered against the bullet is incoherent —
       `revise`.
```

#### Wave 1 — scenario-architect proposal

```
C1.1 — Header lists framework (CRR or Basel 3.1) and a specific
       citation: article number AND paragraph or table reference.
C1.2 — Inputs section maps every field to a column in
       `src/rwa_calc/contracts/bundles.py` (FACILITY_SCHEMA,
       EXPOSURE_SCHEMA, COUNTERPARTY_SCHEMA, COLLATERAL_SCHEMA,
       GUARANTEE_SCHEMA, PROVISION_SCHEMA, RATING_SCHEMA, or
       MODEL_PERMISSIONS_SCHEMA). Each categorical field cites the
       enum value if applicable.
C1.3 — Hand-calc shows every regulatory term on its own line. Each
       scalar (risk weight, CCF, LGD floor, supervisory haircut,
       slotting band, supporting factor, output floor percentage) is
       attributed either to the relevant Skill (`basel31` / `crr`)
       OR to a specific rulepack pack entry (`rulebook/packs/*.py`)
       or pack-binding shim (`engine/sa/{crr,b31}_risk_weight_tables.py`,
       `engine/crm/haircut_tables.py`). `data/tables/` no longer
       exists — a citation to it is stale.
C1.4 — Expected outputs include exact RWA, EAD, risk weight, and K
       (or the subset the test will assert on, with the unused
       fields explicitly listed as out-of-scope under C1.5).
C1.5 — "Edge cases the scenario does not cover" section is present
       and lists at least one edge case explicitly out of scope.
C1.6 — Citations point to real files / articles. Use Read on at
       least one cited spec file under `docs/specifications/` to
       confirm it exists; use the relevant Skill (`basel31` /
       `crr`) to confirm at least one cited article actually
       contains the rule.
C1.7 — "Presence expectations" section is present and names what must
       be EMITTED and NON-NULL (template/sheet or bundle key, the
       cells that must carry a value where there is exposure, and any
       breakdown that must sum to a named parent total). "The values
       are in section 4" is not a substitute — absence is the
       dominant escape class.
C1.8 — "Direction and blast radius" section states whether the change
       raises or lowers RWA. An RWA-reducing proposal says so in
       capitals and names the output-floor evidence it will need.
C1.9 — Consistency with Wave 0: if `premise_verdict` was `rescoped`,
       the proposal designs the auditor's Corrected premise, not the
       original bullet. Designing the superseded bullet is a `revise`.
C1.10 — SIBLING DIVERGENCE. If the proposed expression has an in-repo
       sibling solving a similar problem, the proposal NAMES it by
       file:line and states how its own shape DIFFERS. Copying a
       sibling that is right for its own rule and wrong for this one
       is the most common way a design passes every leg and still
       ships a defect. Fired three times in batch 20260815-1 alone.
C1.11 — EVERY NAMED GUARD MUST BE SHOWN TO FAIL. Any test the proposal
       calls a "leak detector", "must stay green", or a guard against
       a specific wrong implementation is accompanied by the mutation
       it detects, and by evidence (or an explicit instruction to the
       test wave to obtain evidence) that it FAILS under that
       mutation. A test green in both states guards nothing, and
       labelling it a detector is worse than having none because it
       stops anyone looking. In batch 20260815-1 a design named two
       existing tests as leak detectors for a non-target; both passed
       under the correct code AND the wrong code, and the branch they
       "guarded" turned out to be dead in both regimes.
```

#### Wave 2 — fixture-builder report

```
C2.1 — Lists every parquet and Python builder file created or
       modified, with absolute paths.
C2.2 — For worktree items, every modified file path begins with the
       item's worktree path; for main_tree items, every modified
       file path is under `tests/fixtures/`. No edits outside
       `tests/fixtures/`.
C2.3 — Every listed file actually exists. Use Read on at least the
       new builder module and confirm it imports cleanly (no syntax
       errors visible at the top of the file).
C2.4 — The number of rows added per parquet matches the proposal's
       input shape (counterparties, exposures, collateral, etc.).
C2.5 — If the proposal said "no new fixtures", the report explicitly
       says "skipped" and explains why (typically: existing fixtures
       cover the scenario shape).
C2.6 — Every NEW builder module is registered in
       `tests/fixtures/generate_all.py`. Grep the file to confirm.
       The parquets are git-ignored build artifacts, so an
       unregistered builder passes locally and fails on a fresh
       checkout and in CI.
C2.7 — If the fixture reaches a reporting column or template no
       existing portfolio exercises, it is registered in `RUNS` in
       `tests/acceptance/reporting/test_supervisory_validations.py`
       — or the report explains why it is not needed. The gate FAILS
       OPEN: an unreached column makes every rule over it
       NOT_EVALUATED, which is indistinguishable from passing.
C2.8 — For a substitution / basis scenario, the report states the
       CROSSING AMOUNT and it is non-zero. A 0%-RW guarantor makes
       both bases agree, so the scenario could not distinguish a
       correct basis from an incomplete one.
```

#### Wave 3 — test-writer report

```
C3.1 — Names a new test path under one of `tests/unit/`,
       `tests/acceptance/`, `tests/contracts/`, or
       `tests/integration/`, with the test function name.
C3.2 — Test path exists. Use Read on the test file to confirm.
C3.3 — Report states the test was run and FAILED.
C3.4 — Failure mode is an assertion failure, not an import error,
       fixture-load error, or test-collection error. The report's
       quoted failure message includes "AssertionError" or pytest's
       assertion-rewrite output.
C3.5 — Asserted bundle fields cover the proposal's expected outputs
       (e.g. if proposal expects RWA=12345 and EAD=10000, the test
       asserts on `rwa` and `ead` columns of the aggregated bundle).
C3.6 — No edits outside `tests/{unit,acceptance,contracts,integration}/`.
C3.7 — NEGATIVE SPACE. The test asserts the proposal's C1.7 presence
       expectations, not only its values: the sheet / template /
       bundle key is emitted, in-scope cells are non-null where the
       portfolio has exposure, and any new breakdown sums to its
       named parent total. Read the test to confirm — a report that
       claims this without the assertions present is a `revise`.
C3.8 — THE TEST CAN FAIL. Read the assertions and check:
       (a) no assertion is RELATIVE to a baseline
           (`rwa_override > rwa_default`) where an absolute expected
           value was available;
       (b) class/row expectations are anchored to a source of truth
           that cannot drift with the code — the enum
           (`{m.value for m in ExposureClass}`), the sealed carrier,
           `validations/scope.py::SHEET_INDEX_MAPS` — not a
           hand-written list copied from the implementation.
       A test written from the same sentence as the code validates
       nothing.
C3.9 — The defect-pinning grep was run (`uniform`, `all classes`,
       `flat`, `backward compat`, `ignored for`, `has no effect on`)
       and its result reported. If Wave 0 named such tests, the
       report accounts for each one.
```

#### Wave 4 — engine-implementer report

```
C4.1 — Lists every `src/rwa_calc/` file modified, with absolute
       paths.
C4.2 — Every modified file is under `src/rwa_calc/`. No test edits,
       no fixture edits.
C4.3 — None of `src/rwa_calc/engine/pipeline.py`,
       `src/rwa_calc/engine/registry.py`,
       `src/rwa_calc/engine/orchestrator.py`,
       `src/rwa_calc/contracts/protocols.py`,
       `src/rwa_calc/contracts/bundles.py`,
       `src/rwa_calc/contracts/edges.py`,
       `src/rwa_calc/engine/aggregator/` (any module),
       `src/rwa_calc/analysis/reconciliation.py`,
       `src/rwa_calc/reporting/cellspec.py`, or
       `src/rwa_calc/reporting/metadata.py` are modified
       UNLESS the item explicitly required it (in which case the
       item should have been hard-excluded at Step 1; flag this as a
       structural drop).
C4.6 — Reporting-slice criteria (any item touching `src/rwa_calc/reporting/`
       or `tests/expected_outputs/reporting/`):
       (a) NO bulk-regen-to-green — the report must not show
           `REGEN_REPORTING_GOLDENS=1` without a recorded per-cell
           preserve-or-fix decision; the golden gate
           (`tests/acceptance/reporting/test_reporting_golden.py`)
           passed structure-exact + rtol without blanket regeneration.
       (b) Number-changing slices carry a recorded decision — every
           golden cell that moved cites its §6 (F1–F8) / recorded
           preserve-or-fix sign-off (the `crr`/`basel31` skills +
           `tests/oracle/` are the referee).
       (c) The slice names its D1–D10 duplication kill (plan §2.5
           matrix) and proves the deleted site dead.
C4.4 — Targeted pytest path matches what the test-writer reported
       in Wave 3.
C4.5 — The targeted pytest result is PASS — and YOU RAN IT. Do not
       accept the report's quoted summary line as evidence; execute
       `uv run pytest <path> --benchmark-skip` yourself (prefixed
       with `UV_PROJECT_ENVIRONMENT=<main venv path>` for a worktree
       item) and compare. If your run disagrees with the report,
       your run wins.
C4.7 — RWA DIRECTION. The report states whether the change raises or
       lowers RWA and agrees with the proposal's C1.8. An
       RWA-reducing change without output-floor evidence is a
       `revise`, not a `pass` — remember every `engine/sa/` transform
       runs unconditionally to feed the Basel 3.1 output floor, so
       "only SA reads this column" does not make a change IRB-safe.
C4.8 — If the change altered the structure of a conditional
       expression (deleted a short-circuit, widened a gate), the
       report shows the FULL `tests/unit` run, not just the touched
       subdirectory. Such a change alters the expression's column
       footprint and has broken tests in unrelated files.
C4.9 — No golden or validation-baseline regeneration was used to
       reach green (see C4.6(a)). `REGEN_VALIDATION_BASELINE=1`
       without a per-entry written reason is a `drop`.
```

### Step 4e — re-dispatch on revision

When the worst verdict is `revise` and the wave's revision count is 0:

Spawn a fresh role-agent of the original wave's type, with
`run_in_background: true` and `name: <wave>-<P-CODE>-r1`. Prompt:

```
Your prior output for **<P-CODE>** failed review. Address ALL of the
following feedback and resubmit. Do not re-design unless the feedback
explicitly asks you to.

--- conformance feedback (reviewer) ---
{{reviewer's "Feedback" section verbatim, or "passed"}}

--- adversarial findings (skeptic) ---
{{skeptic's "Findings" section verbatim, or "n/a for this wave"}}

The skeptic's findings are about whether the work is CORRECT, not
whether it is well-formed. Where the two reviewers disagree, satisfy
both — a conformance pass does not excuse a broken attack.

--- your prior output ---
{{role-agent's prior return value}}

--- original task ---
{{original wave prompt — including worktree preamble for waves
2/3/4 and the targeted-pytest scoping clause for wave 4}}
```

Increment `revision_count[<wave>]` to 1 and set `agent_status:
in_flight`.

If a reviewer returns `VERDICT: revise` on a revised submission
(`revision_count[<wave>] == 1` already), do not retry — drop the
item per Step 4b's table.

### Worktree preamble (waves 2, 3, 4)

Every Agent call to `fixture-builder`, `test-writer`, or
`engine-implementer` for a `worktree`-stream item must include this
preamble verbatim, with the two paths substituted:

> Operate inside the worktree at `<absolute worktree path>` for this
> task. Use absolute paths beginning with that prefix in all Read /
> Edit / Write / Bash calls. Do **not** edit files in the main repo
> tree. The repo's main virtual environment is shared via
> `UV_PROJECT_ENVIRONMENT=<absolute main .venv path>` — prepend it
> to any `uv run` command, e.g.
> `UV_PROJECT_ENVIRONMENT=<...> uv run pytest <...>`.
>
> ⚠ **`PYTHONPATH=.` SILENTLY MEASURES THE MAIN TREE — use
> `PYTHONPATH=.:src`.** The shared venv's `_editable_impl_rwa_calc.pth`
> puts the **main** checkout's `/src` on `sys.path`, so `PYTHONPATH=.`
> makes only `tests` importable and `import rwa_calc` still resolves to
> the main checkout. You would then report numbers for code you did not
> change. **Verify before measuring, do not assume:**
> `PYTHONPATH=.:src <venv>/bin/python -c "import rwa_calc.engine.sa.risk_weights as m; print(m.__file__)"`
> must print a path under the worktree. Useful side effect: running the
> same target with `PYTHONPATH=.` gives the **pre-fix** behaviour and
> with `PYTHONPATH=.:src` the **post-fix** behaviour, on one machine.

For `main_tree`-stream items (single-stream / hard-excluded), omit
the preamble.

**Committing inside a worktree.** The pre-commit gate shells to
`uv run`, which — with no `UV_PROJECT_ENVIRONMENT` set — creates a
fresh empty `.venv` **inside the worktree** and then fails with
`No module named 'watchfire'` / `Failed to spawn: ruff`. Either export
`UV_PROJECT_ENVIRONMENT=<absolute main .venv path>` for the commit, or
commit from the main tree with `git -C <worktree>`. Delete any stray
worktree `.venv` afterwards.

### Engine-implementer scoping clause (wave 4)

Append this to every `engine-implementer` prompt (both the original
dispatch and any revision):

> Run only this item's targeted pytest target — **not** the global
> validation gate. The parent orchestrator runs the global gate
> once on the merged feature branch after all items return. Do not
> run `ruff check src/`, `ty src/`, or `pytest tests/contracts/`
> here — those are deferred. The targeted test you must verify
> green is the path your test-writer reported.

## Step 5 — squash-merge into the current branch

Skip any item with `agent_status: dropped` — its worktree branch has
nothing to merge. Tear it down in Step 8 and keep going.

Single-stream / hard-excluded items: this step is replaced by the
old in-place commit sequence (`git add` the engine-implementer's
files, commit with `feat(<P-code>): <summary> [batch <batch-id>]`).
Skip to Step 6.

For multi-item batches, in **tier-priority order**, for every item
with `current_wave: merge_ready`:

```
git checkout <merge-target-branch>
git merge --squash batch/<batch-id>/<P-code>
git commit -m "feat(<P-code>): <one-line summary> [batch <batch-id>]"
```

The pre-commit gate (`scripts/pre_commit_gate.sh`) fires on each
commit and runs `arch_check.py` + `ruff check src/`. Substantive
gating happens once at Step 6.

### Conflict policy

If `git merge --squash` reports a conflict for item X:

1. `git merge --abort` (resets the index but leaves the worktree
   branch intact).
2. Mark item X as **dropped** in the state file with
   `drop_reason: "merge-conflict-<files>"`. Surface to the operator:
   "Dropped <P-code>: merge conflict in <files>". Do not tick it in
   `IMPLEMENTATION_PLAN.md`. The branch and worktree are torn down
   with the others in Step 8 — the work is not lost because the
   failing item is regenerated cleanly in a future batch.
3. Continue with the remaining items. Do **not** abort the rest of
   the batch.

Drop also applies if a per-commit hook fails for item X (e.g.
arch_check spots a violation introduced by the merge resolution).

## Step 6 — single global validation gate

Run once, on the merged tree, in **tier order**. Do not reorder, and
do not stop before Tier 2 — Tier 2 is the tier that catches the
defects this project actually ships.

If any item added a `@cites` decorator, regenerate the citation
snapshot **before** running anything:
`uv run python scripts/generate_citation_matrix.py`.

**Tier 0 — static (fast, fails early)**

```
uv run python scripts/arch_check.py
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run ty check src/rwa_calc/
```

**Tier 1 — contracts and the batch's own tests**

```
uv run pytest tests/contracts/ --benchmark-skip -q
uv run pytest <union of all merged items' new test paths> --benchmark-skip
```

Note: no `-x` on the union run. You want the full failure list for
attribution, not the first one.

**Tier 2 — the oracle tier (MANDATORY — never skip, never defer)**

```
uv run pytest tests/oracle/ --benchmark-skip -q
uv run pytest tests/acceptance/reporting/ --benchmark-skip -q
```

`tests/acceptance/reporting/` contains the supervisory validation
ratchet (741 published EBA/BoE rules, ratcheted **both** ways) and the
reporting goldens. This is the only part of the estate that has
reliably caught the reporting defects that reach production: on one
CRM substitution block a fully green 10,552-test suite found **none**
of ten real defects, while wiring the portfolio into the register
found three in the first hour.

It is expensive — the validation test alone is eighteen full pipeline
runs — and it is expensive **once per batch**, against a batch that
took hours. That trade is not close. If you are tempted to skip it
because the batch "didn't touch reporting", don't: the ledger is
sealed on aggregator exit, so an engine change reaches it.

**Tier 3 — full suite**

Run as **two foreground chunks** — background Bash tasks are hard-killed
at ~600s:

```
uv run pytest tests/unit -q
uv run pytest tests/acceptance tests/integration tests/contracts tests/oracle -q
```

Tier 3 is mandatory when any item changed the structure of a
conditional expression (a deleted short-circuit changes an
expression's *column footprint* and breaks tests in unrelated files),
added or narrowed an eligibility gate, or altered a shared carrier.
When in doubt, run it: `loop.sh` pushes to a feature branch where CI
does **not** fire, so if you skip Tier 3 nothing runs the full suite
until the PR — dozens of items later, when attribution is hopeless.

If an xdist worker reports "node down", re-run before treating the
suite as red — that failure mode is transient.

The "merged items" set excludes anything dropped in Steps 4 or 5.

If anything fails, surface:
- the gate command and tier that failed,
- the failing test names or arch_check messages,
- a best-effort attribution to the merged item (match failing file
  paths to the engine sub-package each item targeted in Step 1),
- for a Tier 2 failure, whether the break is **new** or a **baseline
  entry that has been fixed**. The register ratchets both ways, so
  `test_no_baseline_break_has_been_fixed_without_being_removed`
  failing is the design working — the entry is removed deliberately,
  with its written reason. **Never** regenerate goldens or the
  validation baseline to reach green; that banks a live defect as
  expected behaviour.

**Do not tick the plan if the gate is red.** The squash commits are
already on the feature branch — the operator decides whether to
revert specific commits, fix forward, or push as-is for review.
Record every gate failure in the failing item's `retro_notes` before
you move on: Step 7.5 needs them.

## Step 7 — tick the plan

For each item that successfully merged **and** survived the global
gate, edit `IMPLEMENTATION_PLAN.md` at the top level: toggle from
`[ ]` to `[x] FIXED v<x.y.z>` with a one-line summary.

**Also resolve the Wave 0 outcomes** — otherwise a refuted bullet sits
in the queue and the next batch pays to refute it again:

- `premise_verdict: refuted` → close the bullet as
  `[x] closed-claim-invalid: <auditor's one-line basis>` and move it
  to `## Completed`. Do **not** leave it unchecked.
- `premise_verdict: rescoped` → rewrite the bullet's summary and
  `Ref:` to the auditor's corrected premise, whether or not the item
  went on to merge. The next reader must not inherit the wrong claim.

One Edit per item, then a single commit:

```
chore(plan): tick N code items [batch <batch-id>]
```

## Step 7.5 — retro (turn this batch's failures into gates)

**Run this before Step 8 destroys the evidence.** This is the step
that makes the harness learn; skipping it means the next batch repeats
this batch's mistakes at full price.

You run this yourself — not via a sub-agent. You are the only party
with the whole batch in view, and `.claude/LESSONS.md` is a shared
file that concurrent agents would race on.

1. **Gather.** From the state file, collect every: `revision_count`
   above 0, `drop_reason`, `premise_verdict` of `refuted`/`rescoped`,
   skeptic `Findings`, entry in `retro_notes`, and Step 6 gate
   failure.

2. **Separate one-offs from patterns.** For each, ask: *would this
   recur on an unrelated item?* A typo is a one-off. "The agent
   asserted against a hand-written list" is a pattern. Discard the
   one-offs — this is not a diary.

3. **Graduate, don't narrate.** For every pattern, take the **first**
   option that is achievable in this pass:

   | Preference | Form | Where |
   |---|---|---|
   | 1 (best) | executable check | a numbered check in `scripts/arch_check.py` + a `tests/contracts/` test |
   | 2 | ratchet | a metric in `scripts/arch_metrics.json` |
   | 3 | fixture coverage | a portfolio registered in `RUNS` |
   | 4 | reviewer criterion | a `C<n>.<m>` in Step 4d, or an attack in `.claude/agents/skeptic.md` |
   | 5 (last) | prose | an entry in `.claude/LESSONS.md` |

   Prose is the **fallback**, not the default. `arch_check.py` already
   carries 17 numbered checks and the validation register carries
   hundreds of entries — every one of them is a lesson that graduated.
   That is what "learning" looks like here; a paragraph nobody rereads
   is not.

   If the right check is too large for this pass, file it as a **Tier
   1** bullet in `IMPLEMENTATION_PLAN.md` and add the prose entry as
   the interim. Record the bullet ID in the prose entry so the two
   stay linked.

4. **Write it.** For each graduated lesson, add a row to the
   **Graduation ledger** at the bottom of `.claude/LESSONS.md`
   (date | lesson | graduated to) and do **not** also add prose. For
   each prose entry, use the file's `Trap` / `Why` / `Detect` format —
   **an entry with no `Detect` line is not finished.**

5. **Keep the working set small.** `.claude/LESSONS.md` is capped at
   ~30 entries. If your additions push it over, graduate or delete a
   stale entry in the same pass and say which. A lessons file nobody
   can read in one sitting is a lessons file nobody reads.

6. **Check for recurrence.** If a pattern this batch hit was *already*
   in `.claude/LESSONS.md`, that lesson has proven it cannot survive
   as prose. Graduate it now, or file its graduation as Tier 1. Say so
   explicitly in the report — a repeat is the strongest signal the
   harness gives you.

7. **File the batch's docs impact.** Docs staleness is an emitted
   work item, not a hoped-for side effect. Walk the batch's merged
   diff against these doc-bearing surfaces and, for each hit, append
   a bullet to **Tier 5 (the docs queue) of `IMPLEMENTATION_PLAN.md`**
   naming the change, the affected page, and the batch id:

   | Change in the batch | Docs item to file |
   |---|---|
   | rulepack pack value added/changed | regenerate `docs/data-model/regulatory-tables.md` (`scripts/generate_regulatory_tables.py`) — usually done in-batch; file only if skipped |
   | new/renamed pipeline stage or registry entry | `docs/architecture/pipeline.md` + `docs/specifications/architecture.md` |
   | new input schema column | `docs/data-model/input-schemas.md` |
   | new reporting template/cell coverage | the matching `docs/features/*-reporting.md` page |
   | behaviour change a user would notice | `docs/appendix/changelog.md` (should already be in-batch; file if missing) |

   No hit → say "no docs impact" in the report; do not invent items.

Commit any harness changes separately:

```
chore(harness): retro from batch <batch-id> — <N> graduated, <M> recorded
```

Report to the operator: what recurred, what graduated and into what,
what stayed prose and why, and any Tier 1 bullets filed.

## Step 8 — cleanup and push

For every item — including dropped ones — tear down the worktree and
its branch:

```
git worktree remove --force ../rwa_calculator-<P-code>
git branch -D batch/<batch-id>/<P-code>
```

Sanity check: `git worktree list` should show only the main tree;
`git branch --list 'batch/*'` should be empty.

**Archive the state file — do not delete it:**

```
mkdir -p .claude/state/archive
mv .claude/state/next-items-<batch-id>.json .claude/state/archive/
```

The archive is the only record of what each reviewer caught, which
waves needed revision, and why items were dropped. `/postmortem` reads
it to find the batch that produced a defect, and drop reasons across
batches are the highest-signal dataset for tuning the Step 4d
criteria. Deleting it — as this command used to — threw away exactly
the evidence needed to stop the next escape.

(`.claude/state/` is git-ignored, so the archive is local to this
machine. That is fine for tuning; anything that must survive a fresh
clone belongs in `.claude/LESSONS.md` or `docs/development/escape-log.md`.)

Push the merge-target branch to its remote (`loop.sh` also does this
on iteration end, but pushing here makes the batch boundary
observable).

## Constraints

- Cap N at 5 even if the user asks for more.
- Never tick the plan if the global gate is red.
- **Tier 2 of the gate is not optional.** No batch merges on Tier 0+1
  alone. If you are short of time, drop an item — never a tier.
- **Never skip Step 7.5.** A batch that merges without a retro has
  spent the money and thrown away the lesson. If nothing generalisable
  happened, say so explicitly in the report — that is a valid outcome,
  silence is not.
- Do not run the global gate inside any role-agent or reviewer — it
  runs once at Step 6 on the merged tree. The `reviewer` and `skeptic`
  may run the item's **targeted** test to verify a claim; that is not
  the gate.
- The call graph is exactly one level deep: this orchestrator → one
  of `premise-auditor` / `scenario-architect` / `fixture-builder` /
  `test-writer` / `engine-implementer` / `reviewer` / `skeptic`. The
  orchestrator drives every wave and every review dispatch directly;
  sub-agents do not spawn other sub-agents.
- **The orchestrator owns PDF extraction.** Role-agents cannot read
  `docs/assets/*.pdf`. Extract with pymupdf and paste verbatim text
  into the prompt — mandatory for any RWA-reducing item. Never ask an
  agent to "confirm the citation": it cannot, and its confident quote
  may be reconstructed from memory.
- Hard cap of one revision per wave per item. Two `revise` verdicts on
  the same wave drops the item. A `drop` verdict drops immediately, no
  revision. On two-reviewer waves the worst verdict decides.
- All role-agent and reviewer dispatches use `run_in_background:
  true` with a stable, unique `name` of the form
  `<role>-<P-CODE>-r<revision-count>` (or
  `reviewer-<wave>-<P-CODE>-r<revision-count>` /
  `skeptic-<wave>-<P-CODE>-r<revision-count>`). Foreground dispatch
  defeats the conversational supervision the state file enables.
- The orchestrator owns `.claude/LESSONS.md`, `docs/appendix/changelog.md`,
  the citation matrix, and `scripts/arch_metrics.json`. Agents must
  never write them — concurrent writes to shared files have already
  cost misattributed commits and a silently dropped import line.
- The state file at `.claude/state/next-items-<batch-id>.json` is
  authoritative. Read it at the start of every turn before reacting
  to anything else. Persist via atomic write (`<file>.tmp` then
  rename). Do not patch the JSON line by line.
- Operator interjections during the batch are first-class. Common
  requests: status, drop an item, inspect an output. Honor them
  before continuing supervision work in the same turn.
- Hard-excluded items never appear in a multi-item batch — they
  always run alone, in the main tree, with no worktree machinery
  (Step 3 and Step 5's merge are both skipped). Step 4's per-wave
  dispatch and reviewer loop are unchanged except the worktree
  preamble is omitted for waves 2/3/4.
- Every agent is told to read `.claude/LESSONS.md` first. Do not
  paste its contents into prompts — point at it, so there is one copy
  and the retro's edits take effect on the next dispatch.
- A batch where every reviewer passed everything and the retro found
  nothing is a warning sign, not a triumph. Measured baseline: 6 of 10
  then 10 of 10 plan bullets had a materially wrong premise. If Wave 0
  confirms every bullet in a batch, say so to the operator and treat
  the audit itself as suspect.
