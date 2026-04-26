---
description: Pick the highest-priority unimplemented item from IMPLEMENTATION_PLAN.md and run /implement-scenario on it.
---

You are picking the next code/test item to implement from
`IMPLEMENTATION_PLAN.md` (root of the repo — **not** the published
`docs/plans/implementation-plan.md`, which is narrative).

## Step 1 — pick

Read `IMPLEMENTATION_PLAN.md`. Items are P-coded
(`P1.92`, `P2.13`, etc.) and grouped by tier:

1. **Tier 1 — Calculation Correctness** (highest priority).
2. **Tier 2 — Test Coverage Gaps**.
3. **Tier 3 — COREP Reporting Completeness**.
4. **Tier 4 — Pillar III Disclosure Gaps**.
5. **Tier 5 — Documentation & Consistency** — defer to
   `/next-doc` rather than handling here.
6. **Tier 6 — Code Quality**.
7. **Tier 7 — Future / v2.0** — skip unless explicitly asked.

Pick the first item that is **not** marked `[x] FIXED` and **not** in
Tier 5 / 7. Confirm the item is still open by spot-checking the cited
file/test rather than trusting the checkbox.

## Step 2 — confirm

State to the user, in one line, the picked P-code, its tier, and the
one-line summary from the plan (e.g. "P1.99 — Tier 1 — CRR short-term
institution risk weights (Art. 120) not applied").

## Step 3 — delegate

Invoke `/implement-scenario <P-CODE>` with the picked ID. The
slash command owns the agent sequence and the single end-of-iteration
commit.

## Constraints

- One item per invocation. Do not chain into the next one.
- If every Tier 1–4, 6 item is already fixed, report so and stop —
  do not promote Tier 5 or 7 work without operator approval.
- If the picked item is actually a docs gap mis-filed in the code
  plan, stop and surface that to the operator; do not silently shift
  to `/next-doc`.
- If the picked item depends on infrastructure that does not yet
  exist (a missing engine subpackage, a not-yet-modelled approach),
  stop and surface the dependency.
