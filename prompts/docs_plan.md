Run `/refresh-docs-plan`.

That single slash command drives the whole `loop.sh docs_plan`
iteration:

- it delegates to the `plan-curator` agent, which audits `docs/`
  end-to-end against the regulatory PDFs in `docs/assets/` and
  against `src/rwa_calc/`,
- reconciles the existing **Tier 5 (docs queue)** items in
  `IMPLEMENTATION_PLAN.md` (mark resolved items `[x]`, prune them
  to the Completed Items reference list),
- adds new docs findings as bullets **in Tier 5** (next free
  P-code; migrated D-codes are legacy, do not mint new ones),
- refiles anything that turns out to need a `src/` or `tests/`
  change into the code tier that matches — Tier 5 is docs-only,
- commits and pushes the single-file diff to the current branch.

After `/refresh-docs-plan` returns, do this housekeeping in the
top-level session:

1. If the regulatory PDFs are missing from `docs/assets/`, surface
   that and stop — do not run `scripts/download_docs.py` from a
   plan-only loop.
2. Pages whose `verified:` front-matter stamp (P4.59) is older than
   ~2 months are staleness candidates — the curator should list
   them rather than re-reading the whole site.

## Hard constraints

- Plan-only. No edits in `src/`, `tests/`, or `docs/`.
- Primary output artifact: **Tier 5 of `IMPLEMENTATION_PLAN.md`** —
  the single work queue; there is no separate docs plan file
  (`DOCS_IMPLEMENTATION_PLAN.md` was merged in on 2026-08-08).
- `docs/data-model/regulatory-tables.md` is **generated** by
  `scripts/generate_regulatory_tables.py` — never file a docs item
  to hand-edit it; a wrong value there is a rulepack item instead.
- Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as the
  project's shared protocols, bundles, and enums when reasoning
  about code-doc alignment. Do NOT assume functionality is missing
  without searching first.
- Use pymupdf to extract text from PDFs in `docs/assets/`. Cite the
  exact section heading or paragraph number rather than paraphrasing.
- Use the `basel31` and `crr` skills for regulatory scalars. Do not
  invent values from training data.
- Keep `AGENTS.md` operational only.
