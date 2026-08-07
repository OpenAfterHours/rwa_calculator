Run `/next-items 3`.

That single slash command drives the whole `loop.sh` build
iteration as a parallel batch:

- it picks up to 3 non-conflicting P-coded items from
  `IMPLEMENTATION_PLAN.md` (each touching a distinct engine
  sub-package, distinct rulepack pack file, and distinct new
  test path),
- runs the five agent stages as five parallel waves
  (premise-auditor → scenario-architect → fixture-builder →
  test-writer → engine-implementer), with N items in flight per
  wave, a `reviewer` after every wave and a `skeptic` alongside it
  on the design and implementation waves,
- runs the global validation gate exactly once at the end of the
  engine-implementer wave — per-agent gate runs are forbidden
  because they would N×-redundantly churn ruff/format on each
  other's edits. The gate runs in tiers, and **Tier 2 is
  mandatory**: after arch_check / ruff / ty / contracts and the
  batch's own tests, it runs `tests/oracle/` and
  `tests/acceptance/reporting/` (the supervisory validation ratchet
  and the reporting goldens), then the full suite in two foreground
  chunks. Tiers 0–1 alone have merged green over real defects,
- on green: commits each item separately, runs the **Step 7.5
  retro** (graduating this batch's repeatable failures into checks,
  ratchets, fixture coverage or `.claude/LESSONS.md`), then ticks
  the items off `IMPLEMENTATION_PLAN.md` in one final
  `chore(plan): tick N code items` commit and pushes.

Items that touch shared files (`engine/pipeline.py`,
`contracts/protocols.py`, `contracts/bundles.py`,
`engine/aggregator/aggregator.py`) are forced single-stream by
the orchestrator — that's deliberate and not a bug.

If you want strict-serial behaviour (one item per iteration), run
`/next-scenario` instead — both commands remain available.

After `/next-items` returns, do these housekeeping items in the
top-level session (not via a sub-agent):

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md`. Capture the **why** — regulatory
   citation and which test pins the behaviour — not just the **what**.
2. If the validation gate is green and the new test passes, create a
   git tag. If no tag exists yet start at `0.0.0`; otherwise bump the
   patch version (`0.0.0` → `0.0.1`).
3. If `/next-items` reported the backlog is empty across Tiers 1–4
   and 6, stop the loop and surface that to the operator. Do not
   invent work, and do not silently promote Tier 5 (docs) or
   Tier 7 (v2.0) items — Tier 5 belongs in the `loop.sh docs_build`
   mode.
4. If `/next-items` reported the global validation gate was red,
   **no commits will have been made**. Do not retry blindly;
   inspect the failure attribution, fix forward in the next
   iteration, and rerun the loop manually.
5. If `/next-items` reported any item dropped with
   `premise-refuted`, confirm the bullet was closed in
   `IMPLEMENTATION_PLAN.md` as `closed-claim-invalid` — otherwise
   the next iteration pays to refute it again. A refuted premise is
   a successful outcome, not a failed item.
6. Confirm the retro ran and report what it graduated. A batch that
   merged without a Step 7.5 retro has spent the money and thrown
   away the lesson.

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
  root plan files. premise-auditor, reviewer and skeptic own nothing
  on disk. `.claude/LESSONS.md`, `docs/appendix/changelog.md`, the
  citation matrix and `scripts/arch_metrics.json` are
  orchestrator-only — concurrent agent writes to shared files have
  already cost misattributed commits. Anything else is a top-level
  edit.
- Add extra logging if needed to debug, following the rules in
  `CLAUDE.md` § Logging — never `print()`, never f-strings in log
  calls, never `logging.basicConfig()`.
