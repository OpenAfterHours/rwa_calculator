Run `/refresh-docs-plan`.

That single slash command drives the whole `loop.sh docs_plan`
iteration:

- it delegates to the `plan-curator` agent, which audits `docs/`
  end-to-end against the regulatory PDFs in `docs/assets/` and
  against `src/rwa_calc/`,
- reconciles existing items in `DOCS_IMPLEMENTATION_PLAN.md`
  (mark resolved items `[x]`, move them to `## Completed`),
- adds new findings under the existing priority buckets:
  - Priority 1: Critical Gaps (wrong regulatory values, missing
    material content),
  - Priority 2: Basel 3.1 Specification Parity,
  - Priority 3: Code-Docs Alignment,
  - Priority 4: Minor Fixes,
- commits and pushes the single-file diff to the current branch.

After `/refresh-docs-plan` returns, do this housekeeping in the
top-level session:

1. If the curator surfaced items that are really code bugs (Priority 3
   "Docs Correct, Code Has Known Issue"), append the corresponding
   P-coded bullet to `IMPLEMENTATION_PLAN.md` via the `plan-curator`
   agent so the next `/refresh-plan` or `/next-scenario` iteration
   picks them up.
2. If the regulatory PDFs are missing from `docs/assets/`, surface
   that and stop — do not run `scripts/download_docs.py` from a
   plan-only loop.

## Hard constraints

- Plan-only. No edits in `src/`, `tests/`, or `docs/`.
- Primary output artifact: `DOCS_IMPLEMENTATION_PLAN.md` — a
  prioritised bullet-point list of documentation gaps and fixes.
- Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as the
  project's shared protocols, bundles, and enums when reasoning
  about code-doc alignment. Do NOT assume functionality is missing
  without searching first.
- Use pymupdf to extract text from PDFs in `docs/assets/`. Cite the
  exact section heading or paragraph number rather than paraphrasing.
- Use the `basel31` and `crr` skills for regulatory scalars. Do not
  invent values from training data.
- Keep `AGENTS.md` operational only.
