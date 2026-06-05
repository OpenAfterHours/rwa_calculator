Run `/implement-scenario` for the next Tier 8 CCR item.

That single slash command drives the whole `loop.sh` build
iteration:

- you need to pick the next item from P-coded items from
  `IMPLEMENTATION_PLAN.md` to implement,
- it will then run the four agent stages as four parallel waves
  (scenario-architect → fixture-builder → test-writer →
  engine-implementer), with N items in flight per wave,
- runs the global validation gate
  (`uv run python scripts/arch_check.py && uv run ruff check src/ && uv run ruff format --check src/ && uv run ty src/ && uv run pytest tests/contracts/ --benchmark-skip -q`)
  exactly once at the end of the engine-implementer wave —
  per-agent gate runs are forbidden because they would
  N×-redundantly churn ruff/format on each other's edits,
- on green: commits the item, then ticks the item off
  `IMPLEMENTATION_PLAN.md` in one final
  `chore(plan): tick N code item` commit and pushes.

Items that touch shared files (`engine/pipeline.py`,
`contracts/protocols.py`, `contracts/bundles.py`,
`engine/aggregator/aggregator.py`) are forced single-stream by
the orchestrator — that's deliberate and not a bug.

After `/implement-scenario` returns, do these housekeeping items in the
top-level session (not via a sub-agent):

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md`. Capture the **why** — regulatory
   citation and which test pins the behaviour — not just the **what**.
2If `/implement-scenario` reported the global validation gate was red,
   **no commits will have been made**. Do not retry blindly;
   inspect the failure attribution, fix forward in the next
   iteration, and rerun the loop manually.

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
