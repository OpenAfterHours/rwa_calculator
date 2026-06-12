---
description: Pick top N non-conflicting files from the open SonarQube backlog and drive them through engine-implementer + reviewer in parallel worktrees. Default N=3, capped at 5. Production-only (`src/rwa_calc/`). Hard-excludes shared engine files.
argument-hint: [N]
---

You are draining open **SonarQube** issues from `src/rwa_calc/` in batches.
Each batch item is **one file** with its full set of open Sonar issues.
Items run in their own git worktree, on `sonar/<batch-id>/<slug>` branches.
You drive a two-wave pipeline directly: `engine-implementer` fixes the
file, then `reviewer` gates the fix. Agents run with
`run_in_background: true` so your turns end after dispatch and the
operator can chat with you freely while the batch is in flight.

After every item has reached `merge_ready` or been dropped, squash-merge
each surviving worktree branch into the **current branch** (operator
pre-creates a feature branch like `chore/sonar-clean-<batch>` before
invoking this command), run the global validation gate **once** on the
merged tree, then re-query SonarQube to report the delta and clean up
the worktrees.

Parse `$ARGUMENTS` as integer **N** (default 3, cap 5). If `$ARGUMENTS`
is empty or not an integer, use 3.

## Core architecture

This command spans **multiple turns**. The orchestrator (you) is an
event-driven supervisor: kick off the batch in one turn, end the turn,
then react to agent completion notifications and operator messages
across subsequent turns until the batch is fully resolved.

To survive context compactions and operator interruptions, the
orchestrator persists batch state to
`.claude/state/sonar-clean-<batch-id>.json` and **reads that file at
the start of every turn** before doing anything else. The state file is
the source of truth for what is in flight.

## Step 1 — pull and bucket the Sonar backlog

Query SonarCloud via the MCP:

```
mcp__sonarqube__search_sonar_issues_in_projects
  projects=["OpenAfterHours_rwa_calculator"]
  issueStatuses=["OPEN", "CONFIRMED"]
  ps=500
```

The result is large — if it overflows the response and is saved to a
file under `.claude/projects/.../tool-results/`, parse it from that file
with `python3` (jq is not available in the sandbox). Page 2 may be
required (`p=2`) if `paging.total > 500`.

**Filter to production code only**: keep only issues whose `component`
contains `src/rwa_calc/`. Discard everything else (tests, workbooks,
scripts) — those are out of scope for this command.

**Bucket by file**: group issues by `component`. Each file becomes one
candidate item with this shape:

```json
{
  "file": "src/rwa_calc/engine/stages/hierarchy/resolver.py",
  "slug": "engine-stages-hierarchy-resolver",
  "issues": [
    {"key": "AZ...", "rule": "python:S3776", "severity": "CRITICAL",
     "line": 99, "message": "Refactor this function..."}
  ],
  "issue_count": 6,
  "critical_count": 4
}
```

The `slug` is the file path relative to `src/rwa_calc/`, with `/`
replaced by `-` and `.py` stripped (e.g. `engine/crm/guarantees.py` →
`engine-crm-guarantees`). It is used in branch names and worktree paths.

**Sort candidates** by `(critical_count desc, issue_count desc,
file asc)`. Take the top **N** (after hard exclusions in Step 1.5).

## Step 1.5 — hard exclusions

Force any file under these paths to single-stream / main-tree mode (no
worktree, no parallelism — pick it alone even if N>1 was requested):

- `src/rwa_calc/engine/pipeline.py`
- `src/rwa_calc/engine/registry.py`
- `src/rwa_calc/engine/orchestrator.py`
- `src/rwa_calc/contracts/protocols.py`
- `src/rwa_calc/contracts/bundles.py`
- `src/rwa_calc/engine/aggregator/aggregator.py`

If the top-priority candidate is on this list, downgrade to N=1
single-stream, surface the downgrade ("Picked <file> only; touches
shared infrastructure — single-stream, no worktree"), and run it in
the main tree.

If the queue is empty (no `src/rwa_calc/` issues remain), report
"nothing to do" and stop.

Generate a short batch identifier `<batch-id>` (e.g. timestamp
`YYYYMMDD-HHMM`).

## Step 2 — confirm before dispatch

Capture the **current branch** (`git branch --show-current`) — this is
the merge target. If it is `master`, warn the operator: squash commits
will land on master unless they abort and check out a feature branch.

State to the operator, one line per item:

```
<slug> | file: <relative path> | issues: <count> (<crit> crit) | branch: sonar/<batch-id>/<slug> | worktree: ../rwa_calculator-sonar-<slug>
```

If any candidate was downgraded to single-stream, say so and skip
Step 3 (no worktree).

## Step 3 — provision worktrees

Skip this step entirely for single-stream / hard-excluded items.

For each batched item, run from the main repo:

```
git worktree add -b sonar/<batch-id>/<slug> ../rwa_calculator-sonar-<slug> HEAD
```

Capture each worktree's absolute path — the engine-implementer needs it.

Sanity check after all worktrees are created:

```
git worktree list
```

Expect the main tree plus N sibling entries.

## Step 4 — drive the two-wave pipeline (background, with reviewer loop)

This step is multi-turn. It begins with a kickoff (Step 4a), then the
orchestrator processes one turn at a time (Step 4b) until every item
has reached `merge_ready` or `dropped`.

### Step 4a — kickoff

Write the state file at `.claude/state/sonar-clean-<batch-id>.json`
with this initial schema. Use the Write tool to overwrite the file as a
complete JSON document — do not patch line by line.

```json
{
  "batch_id": "<batch-id>",
  "merge_target_branch": "<current branch>",
  "main_repo_path": "<absolute path to main repo>",
  "main_venv_path": "<absolute path to repo .venv>",
  "started_at": "<ISO 8601 timestamp>",
  "initial_open_count": <total open issues in src/rwa_calc/ at start>,
  "items": [
    {
      "slug": "engine-stages-hierarchy-resolver",
      "file": "src/rwa_calc/engine/stages/hierarchy/resolver.py",
      "issue_count": 6,
      "critical_count": 4,
      "issues": [ {"key":"...", "rule":"...", "severity":"...",
                   "line":N, "message":"..."} ],
      "stream": "worktree",
      "branch": "sonar/<batch-id>/engine-stages-hierarchy-resolver",
      "worktree_path": "<absolute worktree path>",
      "current_wave": "engine_implementer",
      "agent_status": "in_flight",
      "revision_count": { "engine_implementer": 0 },
      "outputs": {},
      "drop_reason": null,
      "current_agent_name": "sonar-fix-engine-stages-hierarchy-resolver-r0"
    }
  ]
}
```

`stream` is `"worktree"` for batched items and `"main_tree"` for
single-stream / hard-excluded items. For `main_tree` items,
`worktree_path` is `null`.

In a single message, dispatch one `engine-implementer` Agent call per
item, **all with `run_in_background: true`** and a stable `name` of the
form `sonar-fix-<slug>-r0`. Use the prompt template:

```
You are fixing SonarQube issues in **one file only**:
`<absolute path to file in worktree>` (relative: `<relative path>`).

You may add private helpers within the same file. You may NOT:
- modify any other file
- change a regulatory scalar (risk weight, CCF, LGD, supervisory
  haircut, supporting factor, output floor percentage, slotting band)
- alter the public API of any function/class (signature, return type,
  raised exceptions). The single exception is removing an unused
  parameter flagged by S1172 — that is the intended fix.
- introduce a new module-level dependency
- run the global pytest suite. Only the targeted test below.

If you believe an issue is a false-positive, do NOT add a `# noqa` or
`# NOSONAR` suppression — report `deferred: <rule> at line <N>: <reason>`
in your return value and leave the code as-is for that issue.

Address each Sonar issue listed below.

After fixing, run the local validation gate as defined in your system
prompt, in order, fixing issues as they appear. Replace the "new test
path" step with the targeted-test path below.

Targeted test path: `<derived test path>`
  - For `src/rwa_calc/engine/<sub>/<mod>.py` try `tests/unit/test_<mod>.py`
    first; if missing, fall back to `tests/unit/test_<sub>_<mod>.py`,
    then to `tests/unit/<sub>/` (directory).
  - For `src/rwa_calc/data/tables/<mod>.py` try `tests/unit/test_<mod>.py`.
  - For `src/rwa_calc/ui/marimo/*.py` there is often no unit test. If
    you cannot find a targeted test, report `targeted_test: none — orchestrator will run global suite` and skip that step. Do NOT invent one.

--- worktree preamble ---
Operate inside the worktree at `<absolute worktree path>` for this
task. Use absolute paths beginning with that prefix in all Read /
Edit / Write / Bash calls. Do **not** edit files in the main repo
tree. The repo's main virtual environment is shared via
`UV_PROJECT_ENVIRONMENT=<absolute main .venv path>` — prepend it to
any `uv run` command, e.g.
`UV_PROJECT_ENVIRONMENT=<...> uv run pytest <...>`.

--- file under fix ---
<relative path>

--- SonarQube issues to address ---
- <rule> [<severity>] line <line>: <message>
- <rule> [<severity>] line <line>: <message>
- ...

--- return value ---
Report:
1. Files modified (absolute paths).
2. Per-issue disposition: `addressed` (one-line description of the
   fix) | `deferred` (with reason).
3. Local validation gate output (pass/fail per step).
4. Targeted-test outcome (pass + summary line, or `none`).
```

For `main_tree`-stream items, omit the worktree preamble.

End the kickoff turn with a one-line summary to the operator:

> Batch `<batch-id>` kicked off: N Sonar files in flight at Wave 1
> (engine-implementer). I'll continue when each returns; you can ask
> me anything — status, drop an item, inspect outputs — in the
> meantime.

### Step 4b — supervisor protocol (every subsequent turn)

At the start of every turn during a live batch, before responding to
the operator or processing notifications:

1. **Read the state file** `.claude/state/sonar-clean-<batch-id>.json`.
   If it does not exist, the batch is over — proceed to Step 5 if
   there are merge-ready items, otherwise stop.

2. **Identify what changed since last turn**:
   - **Operator message**: respond to the operator. Common requests:
     - *Status*: summarise the state file. Format per item:
       `<slug>: wave=<current_wave> status=<agent_status> revisions=<sum>`.
     - *Drop an item*: set its `agent_status` to `dropped`,
       `drop_reason` to `"operator-drop"`, and if the agent for that
       item is still in flight, attempt `TaskStop`. Persist state.
       Confirm to operator.
     - *Inspect output*: read the corresponding entry's `outputs` map
       and surface it.
   - **Agent completion notification**: identify which item it
     corresponds to (by `current_agent_name`). Store the agent's
     output in the appropriate `outputs` slot. Then progress that
     item per the rules below.

3. **Per-item progression rules**:

   | Current state | Trigger | Next action |
   |---|---|---|
   | `agent_status: in_flight` | (no completion yet) | keep waiting |
   | `agent_status: returned` (engine-implementer just finished) | — | dispatch reviewer per Step 4c; set `agent_status: in_review`; set `current_agent_name: reviewer-engine-implementer-<slug>-r<N>` |
   | `agent_status: in_review` | reviewer returned `VERDICT: pass` | set `current_wave: merge_ready`. Stop dispatching for this item. |
   | `agent_status: in_review` | reviewer returned `VERDICT: revise` AND `revision_count.engine_implementer == 0` | re-dispatch engine-implementer per Step 4e; increment `revision_count.engine_implementer`; set `agent_status: in_flight` with `current_agent_name: sonar-fix-<slug>-r1` |
   | `agent_status: in_review` | reviewer returned `VERDICT: revise` AND `revision_count.engine_implementer >= 1` | drop. Set `agent_status: dropped`, `drop_reason: "revision-failed-engine_implementer"`. Stop dispatching for this item. |
   | `agent_status: in_review` | reviewer returned `VERDICT: drop` | drop. Set `agent_status: dropped`, `drop_reason: "reviewer-drop: <reviewer's drop-reason text>"`. Stop dispatching for this item. |

4. **Persist state**: after processing all changes in this turn, write
   the updated state file. Use atomic-write semantics: write to
   `<file>.tmp` via Write, then `mv <file>.tmp <file>` via Bash.

5. **Decide whether to end turn or continue**:
   - If at least one new role-agent or reviewer was dispatched this
     turn, end the turn with a brief one-line status summary so the
     operator can interject. Do not poll.
   - If every item is either `merge_ready` or `dropped`, the batch is
     complete — proceed to Step 5 in this same turn.
   - If you only processed an operator message and no new dispatches
     were made, end the turn after responding.

### Step 4c — reviewer dispatch

When an engine-implementer returns and you're advancing to review:

Spawn one `reviewer` Agent call per just-returned item, with
`run_in_background: true` and `name: reviewer-engine-implementer-<slug>-r<revision-count>`.
Use this prompt template:

```
You are reviewing the output of an `engine-implementer` agent for the
Sonar-clean item **<slug>** in batch `<batch-id>`. Apply only the
criteria below and return a structured verdict per your system prompt.

--- pass criteria ---
C1 — Exactly one file under `src/rwa_calc/` was modified. List it.
     Use Bash `git -C <worktree_path> diff --name-only HEAD` (or
     `git -C <main_repo_path> diff --name-only HEAD` for main_tree
     items) to confirm.
C2 — Every Sonar issue from the supplied list was either addressed
     or explicitly deferred (with a reason in the agent's report).
     Spot-check 2 fixes against the line range cited in the issue by
     reading the file at the cited line range.
C3 — No regulatory scalar was changed. Grep the modified hunks for
     numeric literals that look like risk weights, CCFs, LGDs, or
     haircuts (e.g. patterns like `0\.[0-9]+`, `1\.5`, `12\.5`). Any
     change to such a literal versus the file at HEAD warrants
     `revise`. Use `git -C <repo> show HEAD:<file>` and diff against
     the modified version to surface scalar changes.
C4 — No public API was changed. List the file's top-level `def` and
     `class` signatures before/after — counts and parameter lists
     must match. The single allowed exception is removal of a
     function parameter flagged by S1172 — confirm any such removal
     corresponds to an S1172 issue in the supplied list.
C5 — Targeted-pytest result was PASS (or explicitly `none`, with
     justification). The report quotes the pytest summary line.
C6 — The engine-implementer ran arch_check + ruff + ty + tests/contracts/
     as part of its local gate and they passed. The report confirms
     this; if any step failed or was skipped without justification,
     `revise`.

--- prior context ---
Sonar issues for this file:
{{full issue list, one per line, formatted as
  - <rule> [<severity>] line <line>: <message>}}

Worktree path: {{worktree_path or "n/a (main_tree, edits in main repo)"}}
Main repo path: {{main_repo_path}}
File under fix: {{relative path}}

--- agent output ---
{{engine-implementer's full return value}}
```

After dispatching, set `agent_status: in_review` in the state file.

### Step 4e — re-dispatch on revision

When a reviewer returns `VERDICT: revise` and the revision count is 0:

Spawn a fresh `engine-implementer` Agent, with `run_in_background: true`
and `name: sonar-fix-<slug>-r1`. Prompt:

```
Your prior Sonar-fix output for **<slug>** failed review. Address the
following feedback and resubmit. Do not re-design unless the feedback
explicitly asks you to.

--- reviewer feedback ---
{{reviewer's "Feedback" section verbatim}}

--- your prior output ---
{{engine-implementer's prior return value}}

--- original task ---
{{original Sonar-fix prompt from Step 4a — including worktree preamble
for worktree items and the full issue list}}
```

Increment `revision_count.engine_implementer` to 1 and set
`agent_status: in_flight`.

If a reviewer returns `VERDICT: revise` on a revised submission
(`revision_count.engine_implementer == 1` already), do not retry —
drop the item per Step 4b's table.

## Step 5 — squash-merge into the current branch

Skip any item with `agent_status: dropped` — its worktree branch has
nothing to merge. Tear it down in Step 8 and keep going.

Single-stream / hard-excluded items: this step is replaced by an
in-place commit in the main tree:

```
git -C <main_repo_path> add <relative file path>
git -C <main_repo_path> commit -m "refactor(sonar): clear <issue_count> issues in <relative file> [batch <batch-id>]"
```

Skip to Step 6.

For multi-item batches, in `(critical_count desc, issue_count desc)`
order, for every item with `current_wave: merge_ready`:

```
git -C <main_repo_path> checkout <merge-target-branch>
git -C <main_repo_path> merge --squash sonar/<batch-id>/<slug>
git -C <main_repo_path> commit -m "refactor(sonar): clear <issue_count> issues in <relative file> [batch <batch-id>]"
```

The pre-commit gate (`scripts/pre_commit_gate.sh`) fires on each commit
and runs `arch_check.py` + `ruff check src/`. Substantive gating
happens once at Step 6.

### Conflict policy

If `git merge --squash` reports a conflict for item X:

1. `git merge --abort` (resets the index but leaves the worktree branch
   intact).
2. Mark item X as **dropped** in the state file with
   `drop_reason: "merge-conflict-<files>"`. Surface to the operator:
   "Dropped <slug>: merge conflict in <files>". The branch and
   worktree are torn down with the others in Step 8 — the work is not
   lost because the failing item is regenerated cleanly in a future
   batch.
3. Continue with the remaining items. Do **not** abort the rest of the
   batch.

Drop also applies if a per-commit hook fails for item X.

## Step 6 — single global validation gate

Run once, on the merged tree, in this order:

```
uv run python scripts/arch_check.py
uv run ruff check src/ && uv run ruff format --check src/
uv run ty src/
uv run pytest tests/ --benchmark-skip -x
```

The full pytest suite (not just the targeted tests) — Sonar refactors
can perturb behaviour in subtle ways, and the targeted-test selection
during fixing is intentionally narrow.

If anything fails, surface:
- the gate command that failed,
- the failing test names or arch_check messages,
- a best-effort attribution to the merged item (match failing file
  paths to the file each item targeted).

**Do not proceed to Step 7 if the gate is red.** The squash commits are
already on the feature branch — the operator decides whether to revert
specific commits, fix forward, or push as-is for review.

## Step 7 — re-query Sonar and report delta

Re-run the Step 1 query against SonarCloud:

```
mcp__sonarqube__search_sonar_issues_in_projects
  projects=["OpenAfterHours_rwa_calculator"]
  issueStatuses=["OPEN", "CONFIRMED"]
  ps=500
```

Note: the SonarCloud scan only re-runs after a push to a tracked
branch, so the open-issue count may not have moved yet at this point.
That is expected — the merged commits are local. Report the delta as
"local (pre-push)" and remind the operator that the next CI scan after
push will surface the actual drop.

Also re-query the quality gate:

```
mcp__sonarqube__get_project_quality_gate_status
  projectKey="OpenAfterHours_rwa_calculator"
```

Surface to the operator:

```
Batch <batch-id> complete.
  Merged: <count> items (<sum of issue counts> issues addressed locally)
  Dropped: <count> items (reasons: <list>)
  Quality gate (pre-push, server-side cache): <status>
  Next CI scan after push should reflect the local drop.
```

## Step 8 — cleanup

For every item — including dropped ones — tear down the worktree and
its branch:

```
git worktree remove --force ../rwa_calculator-sonar-<slug>
git branch -D sonar/<batch-id>/<slug>
```

Sanity check: `git worktree list` should show only the main tree;
`git branch --list 'sonar/<batch-id>/*'` should be empty.

Delete the state file:

```
rm .claude/state/sonar-clean-<batch-id>.json
```

Do **not** push the merge-target branch from this command — pushing is
the operator's call (they may want to inspect the diff or rebase
first).

## Constraints

- Cap N at 5 even if the user asks for more.
- Never proceed past Step 6 if the global gate is red.
- Do not run the global gate inside any role-agent or reviewer — it
  runs once at Step 6 on the merged tree.
- The call graph is exactly one level deep: this orchestrator → one
  of `engine-implementer` / `reviewer`. The orchestrator drives every
  wave and every reviewer dispatch directly; sub-agents do not spawn
  other sub-agents.
- Hard cap of one revision per item. Two reviewer-`revise` verdicts on
  the same item drops it. Reviewer-`drop` drops immediately, no
  revision.
- All role-agent and reviewer dispatches use `run_in_background: true`
  with a stable, unique `name`:
  `sonar-fix-<slug>-r<revision-count>` for fixes,
  `reviewer-engine-implementer-<slug>-r<revision-count>` for reviews.
  Foreground dispatch defeats the conversational supervision the state
  file enables.
- The state file at `.claude/state/sonar-clean-<batch-id>.json` is
  authoritative. Read it at the start of every turn before reacting
  to anything else. Persist via atomic write (`<file>.tmp` then
  rename). Do not patch the JSON line by line.
- Operator interjections during the batch are first-class. Common
  requests: status, drop an item, inspect an output. Honor them
  before continuing supervision work in the same turn.
- Hard-excluded files (`engine/pipeline.py`, `engine/registry.py`,
  `engine/orchestrator.py`, `contracts/protocols.py`,
  `contracts/bundles.py`, `engine/aggregator/aggregator.py`) never
  appear in a multi-item batch — they always run alone, in the main
  tree, with no worktree machinery (Step 3 and Step 5's merge are both
  skipped). Step 4's dispatch and reviewer loop are unchanged except
  the worktree preamble is omitted.
- Production-only scope: items must have `component` containing
  `src/rwa_calc/`. Test, workbook, and script issues are out of scope
  for this command — they are handled by the existing
  `sonar-project.properties` suppressions or by separate one-off PRs.
- Do NOT add `# noqa`, `# NOSONAR`, or rule-level suppressions in
  source files to silence Sonar. Real fixes only; defer if you cannot
  fix.
- Do NOT edit `sonar-project.properties` from this command. Suppression
  changes are a separate decision and a separate PR.
