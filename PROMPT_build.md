Run `/next-scenario`.

That single slash command drives the whole loop iteration:

- it picks the highest-priority unimplemented scenario from
  `docs/plans/implementation-plan.md`,
- delegates to `/implement-scenario <ID>`, which runs scenario-architect,
  fixture-builder, test-writer, and engine-implementer in sequence with
  strict file ownership,
- runs the validation gate (`uv run python scripts/arch_check.py && uv run ruff check src/ && uv run ruff format --check src/ && uv run ty src/ && uv run pytest tests/contracts/ --benchmark-skip -q`) inside engine-implementer,
- ticks the scenario off `docs/plans/implementation-plan.md`, then
  commits and pushes once at the end.

After `/next-scenario` returns, do these housekeeping items in the top-level
session (not via a sub-agent):

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md`. Capture the **why** — regulatory citation
   and which test pins the behaviour — not just the **what**.
2. If the validation gate is green and the new acceptance test passes,
   create a git tag. If no tag exists yet start at `0.0.0`; otherwise bump
   the patch version (`0.0.0` → `0.0.1`).
3. If `/next-scenario` reported the backlog is empty across all three
   buckets (CRR fixtures, B31 extension, spec divergences), stop the loop
   and surface that to the operator. Do not invent work.

## Hard constraints

- Single sources of truth. No migrations, no adapters, no parallel
  re-implementations. If unrelated tests fail during the iteration,
  resolve them as part of this increment or document them in
  `docs/plans/implementation-plan.md`.
- No placeholders or stubs. Implement functionality completely.
- Keep `AGENTS.md` operational only — status notes belong in
  `docs/plans/implementation-plan.md`.
- Do not bypass agent file ownership. fixture-builder owns
  `tests/fixtures/`, test-writer owns `tests/{unit,acceptance,contracts,integration}/`,
  engine-implementer owns `src/rwa_calc/`. Anything else is a top-level
  edit.
- Add extra logging if needed to debug, following the rules in
  `CLAUDE.md` § Logging — never `print()`, never f-strings in log calls,
  never `logging.basicConfig()`.
