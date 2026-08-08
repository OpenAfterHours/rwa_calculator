---
description: Refresh Tier 5 (the docs queue) of IMPLEMENTATION_PLAN.md — audit docs/ vs the regulatory PDFs and source code for new gaps. Plan-only; no docs/ edits.
---

You are refreshing the project's documentation work queue — **Tier 5
of `IMPLEMENTATION_PLAN.md`** (root of the repo). There is no
separate docs plan file (`DOCS_IMPLEMENTATION_PLAN.md` was merged in
on 2026-08-08). Plan-only iteration — no `docs/` or `src/` edits are
allowed.

## Step 1 — delegate to plan-curator

Invoke the `plan-curator` agent. Prompt:

> Curate **Tier 5 (the docs queue)** of `IMPLEMENTATION_PLAN.md`.
> Audit `docs/` end-to-end against the regulatory PDFs in
> `docs/assets/` and against `src/rwa_calc/`. Apply your standard
> workflow, with the **audit pass first** — no skipping it on the
> grounds that the queue looks fine:
>
> 1. **Audit every existing Tier 5 item — open *and* completed.**
>    The plan is a trust anchor for downstream agents; a wrong
>    bullet gets implemented as if it described a real gap. For
>    each bullet, verify: **claim is independently verifiable**
>    (don't take the bullet's reading of the regulation or the
>    docs on trust — confirm via the `basel31` / `crr` Skill that
>    the regulatory source says what the bullet claims, *and*
>    confirm by reading the cited docs page that it actually
>    misses or misstates the rule), cited target page still
>    exists, the gap is still real (the docs page hasn't been
>    written or corrected since the bullet was filed), no newer
>    duplicate, right position within the tier, right scope. Close
>    `closed-claim-invalid` for bullets that were wrong when
>    filed; escalate `Unverifiable` when a claim can't be
>    confirmed in a reasonable spot-check rather than leaving it
>    silently in the queue. **Refile any Tier 5 bullet that turns
>    out to need a `src/` or `tests/` change into the code tier
>    that matches — Tier 5 is docs-only.** Pages whose `verified:`
>    front-matter stamp is older than ~2 months are staleness
>    candidates to check first.
> 2. **Scan for new findings**:
>    - PDF-to-docs mapping per `PROMPT_docs_plan.md`
>      (`ps126app1.pdf`, `crr.pdf`, comparison PDF, COREP/Pillar 3
>      instruction PDFs).
>    - Code-docs alignment — risk weights, formulas, article
>      references, scenario-ID coverage. Note
>      `docs/data-model/regulatory-tables.md` is GENERATED from
>      the rulepacks — a wrong value there is a rulepack bullet
>      (code tier), never a docs bullet.
>    - Basel 3.1 spec parity vs. the matching CRR specs.
> 3. **Add new items** to Tier 5 in priority position with the
>    standard bullet format. Use the next free P-code — migrated
>    D-codes are legacy; do not mint new D-codes.
>
> Cite every regulatory scalar via the `basel31` or `crr` Skill.
> Do not edit any file other than `IMPLEMENTATION_PLAN.md`.
> Return the structured audit summary (Added / Closed /
> Re-scoped / Merged / Unverifiable / Refiled) defined in your
> system prompt.

## Step 2 — review (top level)

Once plan-curator returns:

1. Run `git diff IMPLEMENTATION_PLAN.md` and skim — focus on the
   audit changes (Closed, Re-scoped, Merged, Refiled) as well as
   the Added list. Audit changes are easy to miss in diff because
   they're often a single bullet edit, but they're the load-bearing
   part of a refresh.
2. Confirm the diff is confined to `IMPLEMENTATION_PLAN.md`.
3. If the curator refiled items into code tiers, surface them to
   the operator so the next `/next-items` selection sees them.

## Step 3 — commit

Stage, commit, and push to the current branch with a message
`chore(plan): refresh docs queue (Tier 5) (+N items, -M completed)`.

## Constraints

- No `docs/`, no `src/`, no test edits. Only the plan file.
- Do not auto-trigger `/next-doc` from here.
- If you discover the regulatory PDFs are missing from
  `docs/assets/`, surface that and stop — do not run
  `scripts/download_docs.py` from a plan-only loop.
