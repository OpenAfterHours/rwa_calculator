---
description: Implement one named code/test item end-to-end (architect → fixtures → tests → engine → commit). Usage: /implement-scenario P1.99 — also accepts CRR-A7 / B31-D3 style scenario IDs.
argument-hint: <P-CODE_OR_SCENARIO_ID>
---

You are orchestrating one work item: **$ARGUMENTS**.

Items live in `IMPLEMENTATION_PLAN.md` (P-codes like `P1.99`) or in
`docs/plans/implementation-plan.md` (acceptance scenario IDs like
`CRR-A7`). Either ID style is accepted.

Run the four agents in strict sequence. Do not parallelise. Pass the
previous agent's return value verbatim into the next agent's prompt.

## Step 1 — design

Invoke the `scenario-architect` agent. Prompt:

> Design the work needed for **$ARGUMENTS**. Locate the item in
> `IMPLEMENTATION_PLAN.md` (or `docs/plans/implementation-plan.md`
> if it is a CRR-* / B31-* scenario ID). Read the cited spec under
> `docs/specifications/` and produce the structured proposal per
> your system prompt. Cite every regulatory scalar via the
> basel31 or crr skill.

Save the returned proposal verbatim — every later agent gets the full
text.

## Step 2 — fixtures (skip if not needed)

If the proposal calls for new fixture rows or builders, invoke
`fixture-builder`. Prompt:

> Implement the fixture data for **$ARGUMENTS** per the attached
> proposal from scenario-architect. Stay strictly within
> `tests/fixtures/`. Regenerate parquet outputs and confirm they
> load.
>
> --- proposal ---
> {{proposal text}}

If the proposal explicitly states no fixture changes are needed (a
typical bug-fix item like P1.92), skip this step and pass an empty
fixture report into Step 3.

## Step 3 — tests

Invoke `test-writer`. Prompt:

> Write the failing test(s) for **$ARGUMENTS** per the attached
> proposal. Use any new fixtures from Step 2. Confirm the test fails
> with the expected assertion (not an ImportError or fixture error).
>
> --- proposal ---
> {{proposal text}}
> --- fixture report ---
> {{fixture-builder return, or "no new fixtures"}}

## Step 4 — implementation

Invoke `engine-implementer`. Prompt:

> Make the failing test pass with the minimum change in
> `src/rwa_calc/`. Run the full validation gate before returning.
>
> --- proposal ---
> {{proposal text}}
> --- failing test report ---
> {{test-writer return}}

## Step 5 — commit (top level, not via an agent)

Once engine-implementer reports the gate is green:

1. Run `git status` and review the diff yourself.
2. Confirm the diff covers only `tests/fixtures/`,
   `tests/{unit,acceptance,contracts,integration}/`, and
   `src/rwa_calc/` (plus optionally `src/rwa_calc/data/tables/` if a
   regulatory scalar was added).
3. If anything outside that footprint changed, stop and ask the
   operator.
4. Update `IMPLEMENTATION_PLAN.md` (or
   `docs/plans/implementation-plan.md` for scenario IDs): use the
   Edit tool at the top level to toggle **$ARGUMENTS** from `[ ]`
   to `[x] FIXED v<x.y.z>` with a one-line summary of the change.
   This is a single-line tick — do not invoke `plan-curator` for
   it; that agent is for heavier refresh-mode audits.
5. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md` capturing the **why** (regulatory
   citation, pinning test).
6. Stage, commit, and push to the current branch with a message
   `feat($ARGUMENTS): <one-line summary>`. The
   `scripts/pre_commit_gate.sh` PreToolUse hook fires automatically.

## Constraints

- Do not skip Step 1, 3, 4, or 5. Step 2 is the only one
  conditionally skippable.
- Do not run two agents in parallel.
- Do not commit between agents — one commit at the end.
- If any agent fails, surface the failure to the operator; do not
  auto-retry more than once.
