Run `/next-doc`.

That single slash command drives the whole `loop.sh docs_build`
iteration:

- it picks the highest-priority unresolved item from
  `DOCS_IMPLEMENTATION_PLAN.md`,
- delegates to the `doc-writer` agent, which owns `docs/` and
  edits only the canonical page for that regulatory concept,
- runs `uv run zensical build` to confirm the docs site still
  builds with no broken internal links,
- updates `DOCS_IMPLEMENTATION_PLAN.md` via `plan-curator` to mark
  the item `[x]`, and
- commits and pushes once at the end of the iteration.

After `/next-doc` returns, do this housekeeping in the top-level
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
