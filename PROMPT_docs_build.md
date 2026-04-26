Run `/next-docs 3`.

That single slash command drives the whole `loop.sh docs_build`
iteration as a parallel batch:

- it picks the top 3 non-conflicting items from
  `DOCS_IMPLEMENTATION_PLAN.md` (each touching a distinct
  canonical docs page),
- dispatches 3 `doc-writer` agents in one parallel message, each
  scoped to its own page,
- runs `uv run zensical build` once at the end of the batch (not
  per agent) to confirm the docs site still builds,
- commits each item separately, then ticks the 3 items off
  `DOCS_IMPLEMENTATION_PLAN.md` in one final
  `chore(plan): tick 3 docs items` commit and pushes.

If you want strict-serial behaviour (one item per iteration), run
`/next-doc` instead — both commands remain available.

After `/next-docs` returns, do this housekeeping in the top-level
session:

1. If the change is user-facing, append a one-line entry to
   `docs/appendix/changelog.md` capturing the **why** — regulatory
   citation, what was wrong, what was fixed.
2. If `doc-writer` reported the item is actually a code bug
   (Priority 3, "Docs Correct, Code Has Known Issue"), append a new
   P-coded bullet to `IMPLEMENTATION_PLAN.md` via `plan-curator` so
   the next `/next-scenario` iteration can pick it up. Do NOT edit
   `src/` from this loop.
3. If `DOCS_IMPLEMENTATION_PLAN.md` is empty across all four
   priority buckets, surface that and stop — do not invent work.
4. If `/next-docs` reported the global `uv run zensical build` was
   red, **no commits will have been made**. Do not retry blindly;
   inspect the build error, fix the offending docs page (or
   surface the item as needing operator review), and rerun the
   loop manually.

## Hard constraints

- Docs-only. No edits in `src/` or `tests/`. If you find code
  bugs while reading source, route them to `IMPLEMENTATION_PLAN.md`.
- Single sources of truth — every regulatory concept lives once.
  Cross-reference via `pymdownx.snippets`, never duplicate text
  between specs and the user guide.
- Mirror existing CRR specs when adding Basel 3.1 specs: scenario
  IDs, acceptance criteria, risk weight tables, formulas,
  regulatory article references.
- Document the **why** — regulatory rationale and CRR↔B31 deltas —
  not just the **what**. Tables and formulas must match the source
  PDFs exactly.
- Use the `basel31` and `crr` skills when looking up regulatory
  rules. Do not paraphrase from training data.
- Keep `AGENTS.md` operational only — status updates and progress
  notes belong in `DOCS_IMPLEMENTATION_PLAN.md`.
