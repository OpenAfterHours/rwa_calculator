Run `/next-items 3 ccr`.

That single slash command drives the whole `loop.sh ccr`
iteration as a parallel batch **scoped to Counterparty Credit Risk
only**:

- it picks up to 3 non-conflicting unchecked items from **Tier 8 —
  Counterparty Credit Risk (CCR) Integration** (`P8.*`) in
  `IMPLEMENTATION_PLAN.md`, in plan order, skipping anything marked
  `DEFERRED v2.0` / Phase 10. It does **not** consider any other tier,
- runs the four agent stages as four parallel waves
  (scenario-architect → fixture-builder → test-writer →
  engine-implementer), with N items in flight per wave and a reviewer
  gate between every wave,
- runs the global validation gate
  (`uv run python scripts/arch_check.py && uv run ruff check src/ && uv run ruff format --check src/ && uv run ty src/ && uv run pytest tests/contracts/ --benchmark-skip -q`)
  exactly once at the end of the engine-implementer wave —
  per-agent gate runs are forbidden because they would
  N×-redundantly churn ruff/format on each other's edits,
- on green: commits each item separately, then ticks the items off
  `IMPLEMENTATION_PLAN.md` in one final
  `chore(plan): tick N CCR items` commit and pushes.

Expect frequent single-stream downgrades: many CCR items touch shared
files (`engine/pipeline.py`, `engine/registry.py`,
`contracts/protocols.py`, `contracts/bundles.py`,
`engine/aggregator/aggregator.py`) and are forced single-stream by the
orchestrator — that's deliberate and not a bug. The CCR stage adds new
bundles and wires a new pipeline stage, so a degrade to N=1 is normal.

If you want strict-serial behaviour (one item per iteration), run
`/implement-scenario <P8.x>` directly on a specific CCR item.

After `/next-items 3 ccr` returns, do these housekeeping items in the
top-level session (not via a sub-agent):

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md`. Capture the **why** — regulatory
   citation (CRR Art. 274–282 / PRA PS1/26) and which test pins the
   behaviour — not just the **what**.
2. If the validation gate is green and the new test passes, create a
   git tag. If no tag exists yet start at `0.0.0`; otherwise bump the
   patch version (`0.0.0` → `0.0.1`).
3. If `/next-items 3 ccr` reported Tier 8 has no eligible unchecked
   items left, stop the loop and surface that to the operator. Do not
   invent work, do not fall through to other tiers, and do not
   silently promote any `DEFERRED v2.0` / Phase 10 item.
4. If `/next-items 3 ccr` reported the global validation gate was red,
   **no commits will have been made**. Do not retry blindly;
   inspect the failure attribution, fix forward in the next
   iteration, and rerun the loop manually.

## Hard constraints

- CCR scope is absolute: this loop only ever touches Tier 8 `P8.*`
  items. If you believe a non-CCR fix is required to land a CCR item,
  document it as a new bullet in `IMPLEMENTATION_PLAN.md` rather than
  silently doing it here.
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
