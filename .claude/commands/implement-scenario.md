---
description: Implement one named acceptance scenario end-to-end (architect → fixtures → tests → engine → commit). Usage: /implement-scenario CRR-A7
argument-hint: <SCENARIO_ID>
---

You are orchestrating one acceptance scenario from the docs implementation
plan: **$ARGUMENTS**

Run the four agents in strict sequence. Do not parallelise — each step
depends on the previous one's output. Pass the previous agent's return value
into the next agent's prompt verbatim.

## Step 1 — design

Invoke the `scenario-architect` agent. Prompt:

> Design scenario **$ARGUMENTS** from `docs/plans/implementation-plan.md`.
> Read the relevant spec under `docs/specifications/` and produce the
> structured proposal per your system prompt. Cite every regulatory scalar
> via the basel31 or crr skill.

Save the returned proposal verbatim — every later agent gets the full text.

## Step 2 — fixtures

Invoke the `fixture-builder` agent with the proposal. Prompt:

> Implement the fixture data for scenario **$ARGUMENTS** per the attached
> proposal from scenario-architect. Stay strictly within
> `tests/fixtures/`.
> Regenerate parquet outputs and confirm they load.
>
> --- proposal ---
> {{proposal text}}

If the agent reports a deviation from the proposal, surface it to the user
before continuing.

## Step 3 — tests

Invoke the `test-writer` agent. Prompt:

> Write the failing test for scenario **$ARGUMENTS** per the attached
> proposal and using the fixtures fixture-builder just produced. Confirm
> the test fails with the expected assertion (not an ImportError or
> fixture error).
>
> --- proposal ---
> {{proposal text}}
> --- fixture report ---
> {{fixture-builder return}}

## Step 4 — implementation

Invoke the `engine-implementer` agent. Prompt:

> Make the test from test-writer pass with the minimum change in
> `src/rwa_calc/`. Run the full validation gate before returning.
>
> --- proposal ---
> {{proposal text}}
> --- failing test report ---
> {{test-writer return}}

## Step 5 — commit (executed by you, not by an agent)

Once engine-implementer reports the gate is green:

1. Run `git status` and review the diff yourself.
2. Confirm the diff covers only `tests/fixtures/`, `tests/{unit,acceptance,contracts,integration}/`, and `src/rwa_calc/` (plus optionally `data/tables/`).
3. If anything outside that footprint changed, stop and ask the user.
4. Update `docs/plans/implementation-plan.md` to tick the scenario off the
   "Remaining Fixture Work" / "Basel 3.1 Extension" list.
5. Stage, commit, and push to the current branch. Use a commit message of
   the form `feat(scenario): implement $ARGUMENTS`. The
   `scripts/pre_commit_gate.sh` PreToolUse hook will run automatically.

## Constraints

- Do not skip an agent. Do not run two agents in parallel.
- Do not commit between agents — one commit at the end.
- If any agent fails, surface the failure to the user; do not auto-retry
  more than once.
