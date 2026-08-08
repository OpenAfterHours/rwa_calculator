---
description: Implement one named code/test item end-to-end (architect → fixtures → tests → engine → commit). Usage: /implement-scenario P1.99 — also accepts CRR-A7 / B31-D3 style scenario IDs.
argument-hint: <P-CODE_OR_SCENARIO_ID>
---

You are orchestrating one work item: **$ARGUMENTS**.

Items live in `IMPLEMENTATION_PLAN.md` (P-codes like `P1.99`) or in
`docs/plans/implementation-plan.md` (acceptance scenario IDs like
`CRR-A7`). Either ID style is accepted.

Run the agents in strict sequence. Do not parallelise. Pass the
previous agent's return value verbatim into the next agent's prompt.

This is the serial twin of `/next-items` — it runs the same waves with
the same gates, one item at a time. It is **not** a fast path: do not
drop Step 0, the skeptic in Step 4a, or Tier 2 of the gate because
there is only one item.

## Step 0 — refute the premise

Measured across two `/next-items` drains, 6 of 10 and then 10 of 10
plan bullets had a materially wrong premise. Do this first, always.

**Extract the controlling article yourself before dispatching** —
agents cannot read `docs/assets/*.pdf` (`Read` needs `pdftoppm`, which
is absent), so an unaided auditor may quote from memory:

```bash
uv run python -c "
import fitz
doc = fitz.open('docs/assets/ps126app1.pdf')
print(doc[63].get_text())
"
```

Invoke `premise-auditor`. Prompt:

> This is a NEW item. It is NOT any item you may have seen before.
>
> Try to **refute** the plan bullet for **$ARGUMENTS** below. Answer
> the four questions in your system prompt and return a structured
> verdict. A refutation is a success.
>
> --- plan item ---
> {{exact bullet text}}
> --- audit entry (compliance-audit items only) ---
> {{matching §5 entry from
> docs/plans/compliance-audit-crr-111-241-rectification.md, verbatim}}
> --- verbatim regulatory text (extracted by the orchestrator) ---
> {{PDF text with filename + page index, or an explicit statement
> that it could not be located}}

Then:

- `PREMISE: confirmed` → continue to Step 1 on the bullet as written.
- `PREMISE: rescoped` → continue to Step 1 on the auditor's
  **Corrected premise**; correct the bullet in the plan file at Step 5.
- `PREMISE: refuted` → **stop.** Close the bullet as
  `[x] closed-claim-invalid: <basis>`, commit that alone, and report
  to the operator. This is the cheapest possible outcome — do not
  argue your way past it into building something.

## Step 1 — design

Invoke the `scenario-architect` agent. Prompt:

> Design the work needed for **$ARGUMENTS**. Locate the item in
> `IMPLEMENTATION_PLAN.md` (or `docs/plans/implementation-plan.md`
> if it is a CRR-* / B31-* scenario ID). Read the cited spec under
> `docs/specifications/` and produce the structured proposal per
> your system prompt. Cite every regulatory scalar via the
> basel31 or crr skill.
>
> --- premise audit (authoritative over the plan bullet) ---
> {{premise-auditor return value verbatim}}

Save the returned proposal verbatim — every later agent gets the full
text.

## Step 2 — fixtures (skip if not needed)

If the proposal calls for new fixture rows or builders, invoke
`fixture-builder`. Prompt:

> Implement the fixture data for **$ARGUMENTS** per the attached
> proposal from scenario-architect. Stay strictly within
> `tests/fixtures/`. Regenerate parquet outputs and confirm they
> load.
>
> --- proposal ---
> {{proposal text}}

If the proposal explicitly states no fixture changes are needed (a
typical bug-fix item like P1.92), skip this step and pass an empty
fixture report into Step 3.

## Step 3 — tests

Invoke `test-writer`. Prompt:

> Write the failing test(s) for **$ARGUMENTS** per the attached
> proposal. Use any new fixtures from Step 2. Confirm the test fails
> with the expected assertion (not an ImportError or fixture error).
>
> --- proposal ---
> {{proposal text}}
> --- fixture report ---
> {{fixture-builder return, or "no new fixtures"}}

## Step 4 — implementation

Invoke `engine-implementer`. Prompt:

> Make the failing test pass with the minimum change in
> `src/rwa_calc/`. Run the targeted test; the orchestrator runs the
> global gate at Step 4b.
>
> --- proposal ---
> {{proposal text}}
> --- premise audit ---
> {{premise-auditor return value verbatim}}
> --- failing test report ---
> {{test-writer return}}

## Step 4a — attack it

Invoke `skeptic` on the implementation before you gate. Prompt per the
`skeptic` system prompt, supplying the proposal, the premise audit, the
test-writer report, and the exact targeted pytest path.

A `revise` verdict gets one retry through `engine-implementer` with the
findings inline; a second `revise`, or any `drop`, stops the item and is
reported to the operator. Do not overrule the skeptic yourself — if you
believe it is wrong, say so to the operator and let them decide.

## Step 4b — the gate

Run the same tiered gate as `/next-items` Step 6, in order. **Tier 2 is
mandatory** — it is the tier that catches what reaches production:

```
uv run python scripts/arch_check.py
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run ty check src/rwa_calc/
uv run pytest tests/contracts/ --benchmark-skip -q
uv run pytest <the new test path> --benchmark-skip
uv run pytest tests/oracle/ --benchmark-skip -q
uv run pytest tests/acceptance/reporting/ --benchmark-skip -q
```

Then the full suite, as two **foreground** chunks (background Bash is
hard-killed at ~600s), whenever the change altered a conditional
expression's structure, added or narrowed a gate, or touched a shared
carrier:

```
uv run pytest tests/unit -q
uv run pytest tests/acceptance tests/integration tests/contracts tests/oracle -q
```

If any item added a `@cites` decorator, run
`uv run python scripts/generate_citation_matrix.py` **before** the gate.

Never regenerate goldens or the validation baseline to reach green.

## Step 5 — commit (top level, not via an agent)

Once the gate is green:

1. Run `git status` and review the diff yourself.
2. Confirm the diff covers only `tests/fixtures/`,
   `tests/{unit,acceptance,contracts,integration}/`,
   `src/rwa_calc/` (including `src/rwa_calc/rulebook/packs/` if a
   regulatory scalar was added), and — if Step 0 rescoped the item —
   the corrected bullet in `IMPLEMENTATION_PLAN.md`.
3. If anything outside that footprint changed, stop and ask the
   operator.
4. Update `IMPLEMENTATION_PLAN.md` (or
   `docs/plans/implementation-plan.md` for scenario IDs): use the
   Edit tool at the top level to toggle **$ARGUMENTS** from `[ ]`
   to `[x] FIXED v<x.y.z>` with a one-line summary of the change.
   This is a single-line tick — do not invoke `plan-curator` for
   it; that agent is for heavier refresh-mode audits.
5. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md` capturing the **why** (regulatory
   citation, pinning test).
6. Stage, commit, and push to the current branch with a message
   `feat($ARGUMENTS): <one-line summary>`. The
   `scripts/pre_commit_gate.sh` PreToolUse hook fires automatically.

## Step 6 — retro

Before you report done, ask the `/next-items` Step 7.5 question of
whatever went wrong on this item: a refuted premise, a revision, a
skeptic finding, a gate failure.

If it would recur on an unrelated item, **graduate it** — an
`arch_check` check, a ratchet, fixture coverage in `RUNS`, a reviewer
criterion, and only as a last resort a `.claude/LESSONS.md` entry in
`Trap` / `Why` / `Detect` form. Commit harness changes separately as
`chore(harness): retro from $ARGUMENTS — <what graduated>`.

If nothing generalisable happened, say so explicitly. Silence is not a
valid retro.

## Constraints

- Do not skip Step 0, 1, 3, 4, 4a, 4b, 5, or 6. Step 2 is the only one
  conditionally skippable.
- **Tier 2 of the gate is not optional**, and neither is the Step 4a
  skeptic. Being a single item is not a reason to run a weaker gate
  than a batch would.
- A `PREMISE: refuted` at Step 0 ends the item successfully. Close the
  bullet; do not look for a way to build something anyway.
- Do not run two agents in parallel.
- Do not commit between agents — one commit at the end, plus a
  separate harness commit if Step 6 graduated anything.
- If any agent fails, surface the failure to the operator; do not
  auto-retry more than once.
- The orchestrator owns PDF extraction, `.claude/LESSONS.md`,
  `docs/appendix/changelog.md`, and the citation matrix. Agents never
  write them.
