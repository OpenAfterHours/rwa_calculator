---
description: Refresh IMPLEMENTATION_PLAN.md — audit src/, tests/, docs/specifications/, and the regulatory PDFs for new code/test gaps. Plan-only; no src/ or tests/ edits.
---

You are refreshing the project's code/test work queue at
`IMPLEMENTATION_PLAN.md` (root of the repo). Plan-only iteration —
no source or test edits are allowed.

## Step 1 — delegate to plan-curator

Invoke the `plan-curator` agent. Prompt:

> Curate `IMPLEMENTATION_PLAN.md`. Audit `src/rwa_calc/`,
> `docs/specifications/`, the regulatory PDFs in `docs/assets/`,
> and the test inventory under `tests/`. Apply your standard
> workflow:
>
> 1. Reconcile existing items (mark genuinely-fixed items
>    `[x] FIXED v<x.y.z>`, demote stale ones, move resolved
>    items to `## Completed`).
> 2. Scan for new findings — TODO / FIXME / HACK markers,
>    `pytest.mark.skip`, conditional fixture guards,
>    acceptance-test gaps, regulatory scalar drift between
>    `src/rwa_calc/data/tables/` and the PDFs.
> 3. Add new items in tier order with the standard bullet
>    format. Use the next free P-code integer in sequence.
>
> Cite every regulatory scalar via the `basel31` or `crr` Skill.
> Do not edit any file other than `IMPLEMENTATION_PLAN.md`.

## Step 2 — review (top level)

Once plan-curator returns:

1. Run `git diff IMPLEMENTATION_PLAN.md` and skim the new items.
2. Confirm the diff is confined to `IMPLEMENTATION_PLAN.md`.
   If anything else changed, stop and ask the operator.
3. If plan-curator surfaced a cross-file dependency (e.g. "P1.x
   blocks docs item D2.y"), capture it for the operator —
   either as a comment in the commit message or by triggering
   `/refresh-docs-plan` afterwards.

## Step 3 — commit

Stage, commit, and push to the current branch with a message
`chore(plan): refresh IMPLEMENTATION_PLAN.md (+N items, -M completed)`.
The `scripts/pre_commit_gate.sh` PreToolUse hook runs automatically.

## Constraints

- No `src/`, no `tests/`, no `docs/`, no fixture edits. Only the
  plan file.
- Do not run two `plan-curator` invocations in parallel.
- Do not auto-trigger `/next-scenario` from here. Refreshing the
  plan and working the plan are separate loop modes by design.
