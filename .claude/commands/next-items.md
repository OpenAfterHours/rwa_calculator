---
description: Pick top N non-conflicting items from IMPLEMENTATION_PLAN.md and drive them through the four-wave pipeline (scenario-architect → fixture-builder → test-writer → engine-implementer) per item, with a reviewer gate between every wave and one revision retry per wave per item. Agents run in the background so the operator can chat with the orchestrator mid-batch. Default N=3, capped at 5. Hard-excludes items that touch shared engine files.
argument-hint: [N]
---

You are draining `IMPLEMENTATION_PLAN.md` in batches. Each item runs
in its **own git worktree**, on its own `batch/<batch-id>/<P-code>`
branch. You drive the four-wave scenario-architect → fixture-builder →
test-writer → engine-implementer chain directly, with a `reviewer`
gate between every wave. Agents run with `run_in_background: true` so
your turns end after dispatch and the operator can chat with you
freely while the batch is in flight.

After all items have either reached `merge_ready` or been dropped,
you squash-merge each surviving worktree branch back into the
**current branch** (the operator pre-creates a feature branch before
invoking this command), run the global validation gate **once** on
the merged tree, then tick the plan and clean up the worktrees.

Parse `$ARGUMENTS` as integer **N** (default 3, cap 5). If
`$ARGUMENTS` is empty or not an integer, use 3.

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

Read `IMPLEMENTATION_PLAN.md`. Walk tiers in order:

1. Tier 1: Calculation Correctness
2. Tier 2: Test Coverage Gaps
3. Tier 3: COREP Reporting Completeness
4. Tier 4: Pillar III Disclosure Gaps
5. (skip Tier 5: Documentation — that's `/next-docs` territory)
6. Tier 6: Code Quality
7. (skip Tier 7: Future / v2.0)

For each candidate item, infer its expected change footprint by
reading the bullet's `Ref:` field, the cited file paths, and the
named test.

**Soft preferences** (try to satisfy, but a violation is no longer a
disqualifier — the worktree merge surfaces conflicts cleanly):

1. Distinct top-level under `src/rwa_calc/engine/` (e.g. `engine/sa/`,
   `engine/irb/`, `engine/crm/`, `engine/slotting/`, `engine/equity/`,
   `engine/stages/re_split/`, `engine/stages/hierarchy/`,
   `engine/stages/classify/`).
2. Distinct file in `src/rwa_calc/rulebook/packs/` or `src/rwa_calc/data/tables/`.
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
- `src/rwa_calc/engine/aggregator/aggregator.py`

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
`<P-code> | Tier <n> | engine: <subpkg> | table: <file or none> | test: <path> | branch: batch/<batch-id>/<P-code> | worktree: ../rwa_calculator-<P-code>`

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

## Step 4 — drive the four-wave pipeline (background, with reviewer loop)

This step is multi-turn. It begins with a kickoff (Step 4a), then the
orchestrator processes one turn at a time (Step 4b) until every item
has reached `merge_ready` or `dropped`. The reviewer dispatch and
revision-retry mechanics are in Steps 4c–4e. The per-wave reviewer
criteria are in Step 4d.

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
      "current_wave": "scenario_architect",
      "agent_status": "in_flight",
      "revision_count": {
        "scenario_architect": 0,
        "fixture_builder": 0,
        "test_writer": 0,
        "engine_implementer": 0
      },
      "outputs": {},
      "drop_reason": null,
      "current_agent_name": "scenario-architect-P1.114-r0"
    }
  ]
}
```

`stream` is `"worktree"` for batched items and `"main_tree"` for
single-stream / hard-excluded items. For `main_tree` items,
`worktree_path` is `null`.

In a single message, dispatch one `scenario-architect` Agent call per
item, **all with `run_in_background: true`** and a stable `name` of
the form `scenario-architect-<P-CODE>-r0`. Use the prompt template:

> Design the work needed for **<P-CODE>**. Read the bullet from
> `IMPLEMENTATION_PLAN.md` below and the cited spec. Produce the
> structured proposal per your system prompt.
>
> --- plan item ---
> {{exact bullet text}}

`scenario-architect` is read-only and operates in the main tree; do
not include the worktree preamble for this wave.

End the kickoff turn with a one-line summary to the operator:

> Batch `<batch-id>` kicked off: N items in flight at Wave 1
> (scenario-architect). I'll continue when each returns; you can ask
> me anything — status, drop an item, inspect outputs — in the
> meantime.

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
   | `agent_status: returned` (role-agent just finished) | — | dispatch reviewer per Step 4c; set `agent_status: in_review`; set `current_agent_name: reviewer-<wave>-<P-CODE>-r<N>` |
   | `agent_status: in_review` | reviewer returned `VERDICT: pass` | advance `current_wave` to the next wave; if past Wave 4, set `current_wave: merge_ready` and stop dispatching for this item; otherwise dispatch the next role-agent (Step 4c again, with that wave's prompt) and set `agent_status: in_flight` with `current_agent_name: <next-wave>-<P-CODE>-r0` |
   | `agent_status: in_review` | reviewer returned `VERDICT: revise` AND `revision_count[<wave>] == 0` | re-dispatch the original role-agent per Step 4e; increment `revision_count[<wave>]`; set `agent_status: in_flight` with `current_agent_name: <wave>-<P-CODE>-r1` |
   | `agent_status: in_review` | reviewer returned `VERDICT: revise` AND `revision_count[<wave>] >= 1` | drop. Set `agent_status: dropped`, `drop_reason: "revision-failed-<wave>"`. Stop dispatching for this item. |
   | `agent_status: in_review` | reviewer returned `VERDICT: drop` | drop. Set `agent_status: dropped`, `drop_reason: "reviewer-drop-<wave>: <reviewer's drop-reason text>"`. Stop dispatching for this item. |

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

### Step 4c — reviewer dispatch

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

{{prior wave outputs, if any — e.g. for fixture-builder review,
include the scenario proposal verbatim}}

Worktree path: {{worktree_path or "n/a (main_tree)"}}

--- agent output ---
{{role-agent's full return value}}
```

After dispatching, set `agent_status: in_review` in the state file.

### Step 4d — per-wave reviewer criteria (operator-visible)

These checklists are pasted verbatim into the reviewer's prompt at
Step 4c. They are deliberately written here, not derived implicitly
from each role-agent's system prompt, so the operator can audit and
tune them in this single file.

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
       OR to a specific rulepack pack entry (`rulebook/packs/*.py`) or
       `data/tables/` shim.
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
       `src/rwa_calc/contracts/bundles.py`, or
       `src/rwa_calc/engine/aggregator/aggregator.py` are modified
       UNLESS the item explicitly required it (in which case the
       item should have been hard-excluded at Step 1; flag this as a
       structural drop).
C4.4 — Targeted pytest path matches what the test-writer reported
       in Wave 3.
C4.5 — The targeted pytest result is PASS. The report quotes the
       pytest summary line ("X passed in Ys") or equivalent.
```

### Step 4e — re-dispatch on revision

When a reviewer returns `VERDICT: revise` and the wave's revision
count is 0:

Spawn a fresh role-agent of the original wave's type, with
`run_in_background: true` and `name: <wave>-<P-CODE>-r1`. Prompt:

```
Your prior output for **<P-CODE>** failed review. Address the
following feedback and resubmit. Do not re-design unless the
feedback explicitly asks you to.

--- reviewer feedback ---
{{reviewer's "Feedback" section verbatim}}

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

For `main_tree`-stream items (single-stream / hard-excluded), omit
the preamble.

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

Run once, on the merged tree, in this order:

```
uv run python scripts/arch_check.py
uv run ruff check src/ && uv run ruff format --check src/
uv run ty src/
uv run pytest tests/contracts/ --benchmark-skip -q
uv run pytest <union of all merged items' new test paths> -x --benchmark-skip
```

The "merged items" set excludes anything dropped in Steps 4 or 5.

If anything fails, surface:
- the gate command that failed,
- the failing test names or arch_check messages,
- a best-effort attribution to the merged item (match failing file
  paths to the engine sub-package each item targeted in Step 1).

**Do not tick the plan if the gate is red.** The squash commits are
already on the feature branch — the operator decides whether to
revert specific commits, fix forward, or push as-is for review.

## Step 7 — tick the plan

For each item that successfully merged **and** survived the global
gate, edit `IMPLEMENTATION_PLAN.md` at the top level: toggle from
`[ ]` to `[x] FIXED v<x.y.z>` with a one-line summary. One Edit per
item, then a single commit:

```
chore(plan): tick N code items [batch <batch-id>]
```

## Step 8 — cleanup and push

For every item — including dropped ones — tear down the worktree and
its branch:

```
git worktree remove --force ../rwa_calculator-<P-code>
git branch -D batch/<batch-id>/<P-code>
```

Sanity check: `git worktree list` should show only the main tree;
`git branch --list 'batch/*'` should be empty.

Delete the state file:

```
rm .claude/state/next-items-<batch-id>.json
```

Push the merge-target branch to its remote (`loop.sh` also does this
on iteration end, but pushing here makes the batch boundary
observable).

## Constraints

- Cap N at 5 even if the user asks for more.
- Never tick the plan if the global gate is red.
- Do not run the global gate inside any role-agent or reviewer — it
  runs once at Step 6 on the merged tree.
- The call graph is exactly one level deep: this orchestrator → one
  of `scenario-architect` / `fixture-builder` / `test-writer` /
  `engine-implementer` / `reviewer`. The orchestrator drives every
  wave and every reviewer dispatch directly; sub-agents do not spawn
  other sub-agents.
- Hard cap of one revision per wave per item. Two reviewer-`revise`
  verdicts on the same wave drops the item. Reviewer-`drop` drops
  immediately, no revision.
- All role-agent and reviewer dispatches use `run_in_background:
  true` with a stable, unique `name` of the form
  `<role>-<P-CODE>-r<revision-count>` (or
  `reviewer-<wave>-<P-CODE>-r<revision-count>`). Foreground dispatch
  defeats the conversational supervision the state file enables.
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
