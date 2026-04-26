---
description: Pick top N non-conflicting items from DOCS_IMPLEMENTATION_PLAN.md and dispatch N doc-writer agents in parallel. Default N=3, capped at 5.
argument-hint: [N]
---

You are draining `DOCS_IMPLEMENTATION_PLAN.md` in batches.

Parse `$ARGUMENTS` as integer **N** (default 3, cap 5). If `$ARGUMENTS`
is empty or not an integer, use 3.

## Step 1 — pick a non-conflicting batch

Read `DOCS_IMPLEMENTATION_PLAN.md` (root of the repo). Walk the
priority buckets in order:

1. Priority 1: Critical Gaps
2. Priority 2: Basel 3.1 Specification Parity
3. Priority 3: Code-Docs Alignment
4. Priority 4: Minor Fixes

Select up to N items where each item's **canonical docs target page
is unique within the batch** — two writers on the same `.md` file is
the only collision worth blocking. To resolve the target page, scan
the bullet for an explicit path; if absent, infer from the bullet's
section heading and any cited spec.

If two top items share a target page, take the higher-priority one
into the batch and skip the other this round (it will be eligible
next batch).

If the queue is empty, report "nothing to do" and stop without
dispatching anything.

## Step 2 — confirm before dispatch

State to the operator: the picked item IDs, their priority
buckets, and the distinct target docs page for each. One line per
item. Stop here if the operator hasn't seen the list before — for
headless `loop.sh` runs, proceed automatically.

## Step 3 — parallel dispatch

In a **single message with N Agent tool blocks**, invoke the
`doc-writer` agent N times. Each invocation gets its own item's
bullet text verbatim. Prompt template per dispatch:

> Update the documentation per the attached
> `DOCS_IMPLEMENTATION_PLAN.md` item. Stay strictly within `docs/`,
> and stay strictly within the canonical target page named below.
> Do **not** run `uv run zensical build` from within the agent —
> the orchestrator will run it once at the end.
>
> --- target page ---
> {{absolute path}}
>
> --- plan item ---
> {{exact bullet text including ID and citation}}

Wait for all N to return.

## Step 4 — single global build

Run `uv run zensical build` exactly once. If it fails, surface the
error and the implicated item IDs (any item whose target page is
mentioned in the build error), then stop **without committing**.
Operator decides whether to squash, drop, or fix forward.

## Step 5 — sequential commits

For each returned item, in priority order:

1. `git add` the files reported by that item's `doc-writer`.
2. Commit with `docs(<area>): <one-line summary> [batch <ID>]`
   where `<batch ID>` is a short hash like `b<unix-timestamp>` or
   the first 6 chars of `git rev-parse HEAD`.

The `pre_commit_gate.sh` PreToolUse hook fires per commit — that's
intentional.

## Step 6 — tick the plan and final commit

Use the Edit tool at the top level (no agent needed) to toggle each
batched item from `[ ]` to `[x]` in `DOCS_IMPLEMENTATION_PLAN.md`.
One Edit per item, then a single commit:

```
chore(plan): tick N docs items [batch <ID>]
```

Push to the current branch.

## Constraints

- Cap N at 5 even if the user asks for more — context cost is
  super-linear past that.
- Never commit if the global build is red.
- Do not rerun `uv run zensical build` per agent — N agents × per-item
  builds is the failure mode this command exists to avoid.
- If a `doc-writer` returns "this item is actually a code bug",
  exclude its files from the commit and surface the finding so
  the operator can refile it under `IMPLEMENTATION_PLAN.md`. The
  remaining batched items still commit.
