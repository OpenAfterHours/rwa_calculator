Run `/refresh-plan`.

That single slash command drives the whole `loop.sh plan` iteration:

- it delegates to the `plan-curator` agent, which reads
  `src/rwa_calc/`, `docs/specifications/`, the regulatory PDFs in
  `docs/assets/`, and the test inventory under `tests/`,
- reconciles existing items in `IMPLEMENTATION_PLAN.md` (mark fixed
  items `[x]`, move resolved ones to `## Completed`),
- adds new findings as P-coded bullets in the existing tier
  structure,
- commits and pushes the single-file diff to the current branch.

After `/refresh-plan` returns, do this housekeeping in the top-level
session:

1. If the curator surfaced a cross-file dependency (e.g. a P-code
   that blocks a docs item), append a one-line note to
   `DOCS_IMPLEMENTATION_PLAN.md` so the next `/refresh-docs-plan`
   picks it up. Use the `plan-curator` agent for that one-line edit
   so file ownership stays consistent.
2. If unrelated source code looks subtly drifted (you spotted it
   while reading), capture it in `IMPLEMENTATION_PLAN.md` as a new
   P-coded bullet — do not fix it from a plan-only loop.

## Hard constraints

- Plan-only. No edits in `src/`, `tests/`, `docs/`, or
  `tests/fixtures/`.
- Single sources of truth — do not duplicate items between
  `IMPLEMENTATION_PLAN.md` and `DOCS_IMPLEMENTATION_PLAN.md`.
  Cross-reference via the bullet's `Ref:` field instead.
- Do NOT assume functionality is missing without searching first.
  Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as
  shared protocols / bundles / enums; consolidated implementations
  there are preferred over ad-hoc copies.
- `src/rwa_calc/data/` is the single home for regulatory scalars.
  Drift between those tables and the PDFs is itself a bullet.
- Keep `AGENTS.md` operational only — status updates and progress
  notes belong in `IMPLEMENTATION_PLAN.md`, not in `AGENTS.md`.
- Use the `basel31` and `crr` skills for any regulatory citation —
  do not paraphrase from training data.
