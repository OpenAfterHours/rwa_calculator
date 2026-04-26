Run `/next-scenario`.

That single slash command drives the whole `loop.sh` build iteration:

- it picks the highest-priority unfixed P-coded item from
  `IMPLEMENTATION_PLAN.md` (root of the repo — the project's code/test
  work queue),
- delegates to `/implement-scenario <P-CODE>`, which runs
  scenario-architect, fixture-builder, test-writer, and
  engine-implementer in sequence with strict file ownership,
- runs the validation gate (`uv run python scripts/arch_check.py && uv run ruff check src/ && uv run ruff format --check src/ && uv run ty src/ && uv run pytest tests/contracts/ --benchmark-skip -q`) inside engine-implementer,
- ticks the item off `IMPLEMENTATION_PLAN.md` at the top level
  (single-line Edit; no agent needed for a checkbox toggle), then
  commits and pushes once at the end.

After `/next-scenario` returns, do these housekeeping items in the
top-level session (not via a sub-agent):

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md`. Capture the **why** — regulatory
   citation and which test pins the behaviour — not just the **what**.
2. If the validation gate is green and the new test passes, create a
   git tag. If no tag exists yet start at `0.0.0`; otherwise bump the
   patch version (`0.0.0` → `0.0.1`).
3. If `/next-scenario` reported the backlog is empty across Tiers 1–4
   and 6, stop the loop and surface that to the operator. Do not invent
   work, and do not silently promote Tier 5 (docs) or Tier 7 (v2.0)
   items — Tier 5 belongs in the `loop.sh docs_build` mode.

## Hard constraints

- Single sources of truth. No migrations, no adapters, no parallel
  re-implementations. If unrelated tests fail during the iteration,
  resolve them as part of this increment or document them in
  `IMPLEMENTATION_PLAN.md`.
- No placeholders or stubs. Implement functionality completely.
- Keep `AGENTS.md` operational only — status notes belong in
  `IMPLEMENTATION_PLAN.md`.
- Do not bypass agent file ownership. fixture-builder owns
  `tests/fixtures/`, test-writer owns
  `tests/{unit,acceptance,contracts,integration}/`,
  engine-implementer owns `src/rwa_calc/`, plan-curator owns the two
  root plan files. Anything else is a top-level edit.
- Add extra logging if needed to debug, following the rules in
  `CLAUDE.md` § Logging — never `print()`, never f-strings in log
  calls, never `logging.basicConfig()`.
