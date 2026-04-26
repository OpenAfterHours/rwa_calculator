---
description: Refresh DOCS_IMPLEMENTATION_PLAN.md — audit docs/ vs the regulatory PDFs and source code for new gaps. Plan-only; no docs/ edits.
---

You are refreshing the project's documentation work queue at
`DOCS_IMPLEMENTATION_PLAN.md` (root of the repo). Plan-only
iteration — no `docs/` or `src/` edits are allowed.

## Step 1 — delegate to plan-curator

Invoke the `plan-curator` agent. Prompt:

> Curate `DOCS_IMPLEMENTATION_PLAN.md`. Audit `docs/`
> end-to-end against the regulatory PDFs in `docs/assets/` and
> against `src/rwa_calc/`. Apply your standard workflow:
>
> 1. Reconcile existing items (mark genuinely-resolved items
>    `[x]`, move them to `## Completed`).
> 2. Scan for new findings:
>    - PDF-to-docs mapping per `PROMPT_docs_plan.md`
>      (`ps126app1.pdf`, `crr.pdf`, comparison PDF, COREP/Pillar 3
>      instruction PDFs).
>    - Code-docs alignment — risk weights, formulas, article
>      references, scenario-ID coverage.
>    - Basel 3.1 spec parity vs. the matching CRR specs.
> 3. Add new items in priority order with the standard bullet
>    format. Use the existing `Phase N Findings` sub-headings or
>    open a new dated phase if appropriate.
>
> Cite every regulatory scalar via the `basel31` or `crr` Skill.
> Do not edit any file other than `DOCS_IMPLEMENTATION_PLAN.md`.

## Step 2 — review (top level)

Once plan-curator returns:

1. Run `git diff DOCS_IMPLEMENTATION_PLAN.md` and skim.
2. Confirm the diff is confined to `DOCS_IMPLEMENTATION_PLAN.md`.
3. If plan-curator flags items that are really code bugs (Priority 3
   "Docs Correct, Code Has Known Issue"), surface them — they
   belong in `IMPLEMENTATION_PLAN.md`, not the docs plan.

## Step 3 — commit

Stage, commit, and push to the current branch with a message
`chore(plan): refresh DOCS_IMPLEMENTATION_PLAN.md (+N items, -M completed)`.

## Constraints

- No `docs/`, no `src/`, no test edits. Only the plan file.
- Do not auto-trigger `/next-doc` from here.
- If you discover the regulatory PDFs are missing from
  `docs/assets/`, surface that and stop — do not run
  `scripts/download_docs.py` from a plan-only loop.
