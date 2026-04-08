0a. Study `docs/` structure with up to 3 parallel Sonnet subagents to understand the current documentation state.
0b. Study @DOCS_IMPLEMENTATION_PLAN.md — this is your work queue.
0c. For reference, the application source code is in `src/rwa_calc/` and the regulatory PDFs are in `docs/assets/`. If the PDFs are not there run `scripts/download_docs.py`. Use pymupdf to extract text from PDFs when you need to verify regulatory content.

1. Your task is to write and update documentation per @DOCS_IMPLEMENTATION_PLAN.md using parallel subagents. **Choose the single highest-priority item to address — complete only this one item, then commit and stop.** Before making changes, read the existing doc files and search the codebase (don't assume what's documented or undocumented) using Sonnet subagents. You may use up to 3 parallel Sonnet subagents for research/reads and 1 Opus subagent for writing/analysis. Use Opus subagents when complex regulatory reasoning is needed (interpreting PDF rules, resolving conflicting references, structuring new spec files).
2. After writing or updating documentation, validate the docs build. If content is missing or inaccurate per the regulatory PDFs and source code, fix it. Ultrathink.
2a. VALIDATION GATE: Run `uv run zensical build` to confirm the docs site builds without errors. Check for broken internal links. Fix all issues before committing.
3. When you discover new issues (gaps, inaccuracies, broken references), immediately update @DOCS_IMPLEMENTATION_PLAN.md with your findings using a subagent. When resolved, update and remove the item.
4. When validation passes, update @DOCS_IMPLEMENTATION_PLAN.md, then `git add -A` then `git commit` with a message describing the documentation changes. After the commit, `git push`.

99999. Important: Docs must capture the **why** — regulatory rationale, article references, and how rules differ between CRR and Basel 3.1. Tables and formulas should match the source PDFs exactly.
999999. Important: Single sources of truth. Do NOT duplicate regulatory content across files — cross-reference instead. If the same rule appears in `specifications/` and `user-guide/`, one should link to the other.
9999999. Important: Do NOT modify source code in `src/`. This prompt is for documentation only. If you find code bugs, document them in @DOCS_IMPLEMENTATION_PLAN.md.
99999999. Keep @DOCS_IMPLEMENTATION_PLAN.md current with learnings using a subagent — future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.
999999999. When you learn something new about the docs tooling or build process, update @AGENTS.md using a subagent but keep it brief.
9999999999. For any docs issues you notice (broken links, stale references, missing pages), resolve them or document them in @DOCS_IMPLEMENTATION_PLAN.md using a subagent even if unrelated to the current item.
99999999999. Write documentation completely. Placeholder sections and TODO stubs waste efforts and time redoing the same work.
999999999999. When @DOCS_IMPLEMENTATION_PLAN.md becomes large, periodically clean out completed items using a subagent.
9999999999999. When adding Basel 3.1 specification files, mirror the structure and depth of the existing CRR specs in `docs/specifications/crr/` — include scenario IDs, acceptance criteria, risk weight tables, formulas, and regulatory article references.
99999999999999. IMPORTANT: Keep @AGENTS.md operational only — status updates and progress notes belong in `DOCS_IMPLEMENTATION_PLAN.md`. A bloated AGENTS.md pollutes every future loop's context.
999999999999999. Use the `basel31` and `crr` skills when you need to look up specific regulatory rules during writing.
