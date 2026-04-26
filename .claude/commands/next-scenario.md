---
description: Pick the highest-priority unimplemented scenario from the docs implementation plan and run /implement-scenario on it.
---

You are picking the next scenario to implement from
`docs/plans/implementation-plan.md`.

## Step 1 — pick

Read `docs/plans/implementation-plan.md`. The priority order is:

1. **CRR remaining fixtures** — items still listed under "Remaining
   Fixture Work":
   - CRR-A7 (commercial RE low LTV)
   - CRR-A8 (off-balance sheet commitment CCF)
   - CRR-C3 (specialised lending A-IRB)

2. **Basel 3.1 extension** — items listed under "Basel 3.1 Extension",
   in scenario-table order (B31-A1, A2, … A10, then B31-F1 …).

3. **Spec divergences** — D-coded entries inside
   `docs/specifications/` (e.g. D1.38, D3.37 in
   `basel31/equity-approach.md`). Treat each divergence as its own
   scenario named `D<id>`.

Pick the first unimplemented item from the highest-priority bucket. To
check whether a scenario is implemented, grep
`tests/acceptance/` for the scenario ID — if a passing test asserts
its expected outputs, it is done.

## Step 2 — confirm

State to the user, in one line, which scenario you picked and why
(e.g. "CRR-A7 — first remaining fixture, no test currently asserts the
£600k @ 50% LTV → £300k RWA expected output").

## Step 3 — delegate

Invoke `/implement-scenario <SCENARIO_ID>` with the picked ID. Do not
re-implement the orchestration here — that command owns the sequence.

## Constraints

- One scenario per invocation. Do not chain into the next one.
- If the backlog is empty across all three buckets, report so and
  stop — do not invent work.
- If the picked scenario depends on infrastructure that does not yet
  exist (e.g. a missing engine subpackage for a new approach), stop
  and surface the dependency to the user; do not silently expand
  scope.
