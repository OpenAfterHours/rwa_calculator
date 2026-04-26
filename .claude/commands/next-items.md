---
description: Pick top N non-conflicting items from IMPLEMENTATION_PLAN.md and run the four-stage agent pipeline as parallel waves. Default N=3, capped at 5. Hard-excludes items that touch shared engine files.
argument-hint: [N]
---

You are draining `IMPLEMENTATION_PLAN.md` in batches.

Parse `$ARGUMENTS` as integer **N** (default 3, cap 5). If
`$ARGUMENTS` is empty or not an integer, use 3.

This command is more delicate than `/next-docs` because the
validation gate is global and several files in `src/rwa_calc/` are
touched by many items. Read the collision rules carefully.

## Step 1 — pick a non-conflicting batch

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
named test. Apply these collision-prevention rules; any violation
disqualifies the candidate from this batch (it remains eligible
next batch):

1. **Distinct engine sub-package**: each batched item touches a
   different top-level under `src/rwa_calc/engine/` (e.g.
   `engine/sa/`, `engine/irb/`, `engine/crm/`,
   `engine/slotting/`, `engine/equity/`,
   `engine/re_splitter.py`, `engine/hierarchy.py`,
   `engine/classifier.py`). Two SA fixes in one batch is a
   collision.
2. **Distinct data table**: each item touches a different file in
   `src/rwa_calc/data/tables/`. Two items both editing the same
   risk-weight or LGD table is a collision.
3. **Distinct new test file**: each item produces a different
   new test path under `tests/`. Two writers on the same module
   is a collision.

**Hard exclusions** — any candidate that requires changes to:

- `src/rwa_calc/engine/pipeline.py`
- `src/rwa_calc/contracts/protocols.py`
- `src/rwa_calc/contracts/bundles.py`
- `src/rwa_calc/engine/aggregator/aggregator.py`

is forced single-stream. Pick it alone, even if N>1 was
requested, and report the downgrade ("Picked P-code only;
touches pipeline.py — single-stream").

If the queue is empty, report "nothing to do" and stop.

## Step 2 — confirm before dispatch

State to the operator, one line per item:
`<P-code> | Tier <n> | engine: <subpkg> | table: <file or none> | test: <path>`

If any candidate was downgraded to single-stream, say so.

## Step 3 — four parallel waves

Run the agent pipeline as **four sequential waves**, each wave
parallel across the N items.

### Wave 1 — scenario-architect (parallel)

In a single message, dispatch N `scenario-architect` calls, one per
item. Each gets the item's bullet verbatim. Prompt template:

> Design the work needed for **<P-CODE>**. Read the bullet from
> `IMPLEMENTATION_PLAN.md` below and the cited spec.
> Produce the structured proposal per your system prompt.
>
> --- plan item ---
> {{exact bullet text}}

Wait for all N proposals.

### Wave 2 — fixture-builder (parallel, may include skips)

For each item whose proposal calls for new fixtures, dispatch
`fixture-builder` with that item's proposal. Items needing no
fixture changes are skipped (pass an empty fixture report into
Wave 3 for those).

Run all needed fixture-builder calls in one parallel message. Wait
for all to return.

### Wave 3 — test-writer (parallel)

In one parallel message, dispatch N `test-writer` calls. Each gets
its item's proposal plus its fixture report (or "no new
fixtures"). Each writer must leave its test failing for the right
reason before returning.

### Wave 4 — engine-implementer (parallel)

In one parallel message, dispatch N `engine-implementer` calls.
Each gets its item's proposal + failing test report.

**Important**: instruct each engine-implementer to run only its
own item's pytest target — **not** the global validation gate —
because the orchestrator runs the global gate once at the end of
this wave. Per-agent global runs would be N× redundant and could
churn ruff/format on each other's edits.

## Step 4 — single global validation gate

Run once, in this order:

```
uv run python scripts/arch_check.py
uv run ruff check src/ && uv run ruff format --check src/
uv run ty src/
uv run pytest tests/contracts/ --benchmark-skip -q
uv run pytest <union of all batched items' new test paths> -x --benchmark-skip
```

If anything fails, surface:
- the gate command that failed,
- the failing test names or arch_check messages,
- a best-effort attribution of which batched item is implicated
  (match failing file paths to the engine sub-packages picked in
  Step 1).

**Do not commit if the gate is red.** Operator decides whether to
squash, drop, or fix forward.

## Step 5 — sequential commits

For each item in tier-priority order:

1. `git add` only the files reported by that item's
   engine-implementer (plus its fixture-builder and test-writer if
   they ran).
2. Commit with `feat(<P-code>): <one-line summary> [batch <ID>]`.

The `pre_commit_gate.sh` PreToolUse hook fires per commit.

## Step 6 — tick the plan and final commit

Edit `IMPLEMENTATION_PLAN.md` at the top level: toggle each batched
item from `[ ]` to `[x] FIXED v<x.y.z>` with a one-line summary.
One Edit per item, then a single commit:

```
chore(plan): tick N code items [batch <ID>]
```

Push to the current branch.

## Constraints

- Cap N at 5 even if the user asks for more.
- Never commit if the global gate is red.
- Do not rerun the gate inside any engine-implementer — global gate
  runs once at the end of Wave 4.
- If a stage fails for any single item (e.g. test-writer can't
  produce a clean failure), drop that item from the batch and
  continue with the rest. Surface the dropped item to the
  operator.
- Hard-excluded items never appear in a multi-item batch — they
  always run alone with the same wave structure.
