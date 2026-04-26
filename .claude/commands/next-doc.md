---
description: Pick the highest-priority docs item from DOCS_IMPLEMENTATION_PLAN.md and run doc-writer on it. Single-commit iteration.
---

You are picking the next docs item to implement from
`DOCS_IMPLEMENTATION_PLAN.md` (root of the repo).

## Step 1 — pick

Read `DOCS_IMPLEMENTATION_PLAN.md`. Items are grouped under:

1. **Priority 1: Critical Gaps** — wrong regulatory values, missing
   material content. Highest priority.
2. **Priority 2: Basel 3.1 Specification Parity** — B31 specs
   missing CRR-equivalent depth.
3. **Priority 3: Code-Docs Alignment** — mismatches between docs and
   source.
4. **Priority 4: Minor Fixes** — article references, formatting,
   stale metadata.

Pick the first item not marked `[x]` from the highest-priority bucket
that has any open items. Spot-check the cited docs page to confirm
the gap still exists before delegating.

## Step 2 — confirm

State to the operator, in one line, which item you picked, its
priority bucket, and the canonical docs page that will change
(e.g. "Priority 1 — wrong B31 PE/VC risk weight in
`docs/specifications/basel31/equity-approach.md` — D3.37").

## Step 3 — delegate to doc-writer

Invoke the `doc-writer` agent. Prompt:

> Update the documentation per the attached
> `DOCS_IMPLEMENTATION_PLAN.md` item. Stay strictly within `docs/`.
> Run `uv run zensical build` and confirm a clean build before
> returning.
>
> --- plan item ---
> {{exact bullet text from the plan, including ID and citation}}

## Step 4 — commit (top level, not via an agent)

Once doc-writer reports the build is clean:

1. Run `git status` and review the diff. Confirm changes are
   confined to `docs/`.
2. Update `DOCS_IMPLEMENTATION_PLAN.md` at the top level using
   the Edit tool: toggle the item from `[ ]` to `[x]` with a
   one-line resolution summary. This is a single-line tick — do
   not invoke `plan-curator` for it.
3. Append a one-line `docs/appendix/changelog.md` entry capturing
   the why (regulatory citation, what was wrong, what was fixed).
4. Stage, commit, push to the current branch with a message
   `docs(<area>): <one-line summary>`.

## Constraints

- One docs item per invocation. Do not chain.
- If doc-writer reports the item is actually a code bug (Priority 3
  with code wrong / docs right), stop and instruct the operator to
  re-file under `IMPLEMENTATION_PLAN.md`. Do not edit `src/` from
  this command.
- If `uv run zensical build` keeps failing despite the writer's
  attempts, surface the build error and stop — do not commit a
  broken site.
- If the backlog is empty across all four priority buckets, report so
  and stop.
