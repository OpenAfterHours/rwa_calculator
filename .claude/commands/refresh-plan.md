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
> workflow, with the **audit pass first** — no skipping it on the
> grounds that the queue looks fine:
>
> 1. **Audit every existing item — open *and* completed.** Both
>    plan files are trust anchors for downstream agents; a wrong
>    bullet gets implemented as if it described a real fix. For
>    each bullet, verify: **claim is independently verifiable**
>    (don't take the bullet's reading of the regulation or the code
>    on trust — confirm via the `basel31` / `crr` Skill that the
>    rule says what the bullet claims, *and* confirm by reading the
>    cited source that the code actually diverges), citation
>    resolves, gap is still real (not silently fixed since it was
>    written), no newer duplicate, in the right plan, right tier,
>    right scope. Close `closed-claim-invalid` for bullets that
>    were wrong when filed; escalate `Unverifiable` when a claim
>    can't be confirmed in a reasonable spot-check rather than
>    leaving it silently in the queue. Close / re-tier / re-scope
>    / merge as needed per your system prompt's audit rules.
>    Refile pure docs-page fixes into Tier 5 (the docs queue) and
>    Tier 5 bullets that need code into the matching code tier —
>    same file, ordinary edits, listed under `Refiled`.
> 2. **Scan for new findings** — TODO / FIXME / HACK markers,
>    `pytest.mark.skip`, conditional fixture guards,
>    acceptance-test gaps, regulatory scalar drift between
>    `src/rwa_calc/rulebook/packs/{common,crr,b31}.py` (and the
>    pack-binding shims in `engine/`) and the PDFs. The
>    `data/tables/` package no longer exists.
> 3. **Add new items** in tier order with the standard bullet
>    format. Use the next free P-code integer in sequence.
>
> Cite every regulatory scalar via the `basel31` or `crr` Skill.
> Do not edit any file other than `IMPLEMENTATION_PLAN.md`.
> Return the structured audit summary (Added / Closed /
> Re-scoped / Merged / Unverifiable / Cross-file) defined in your
> system prompt.

## Step 2 — review (top level)

Once plan-curator returns:

1. Run `git diff IMPLEMENTATION_PLAN.md` and skim — focus on the
   audit changes (Closed, Re-scoped, Merged) as well as the Added
   list. Audit changes are easy to miss in diff because they're
   often a single bullet edit, but they're the load-bearing part
   of a refresh.
2. Confirm the diff is confined to `IMPLEMENTATION_PLAN.md`.
   If anything else changed, stop and ask the operator.
3. If plan-curator's return value listed **Refiled** items (moved
   between Tier 5 and a code tier), surface them to the operator so
   the right loop sees them next.
4. If plan-curator surfaced a dependency between a code item and a
   Tier 5 docs item (e.g. "P1.x blocks D3.61"), confirm both
   bullets carry the cross-reference.

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
