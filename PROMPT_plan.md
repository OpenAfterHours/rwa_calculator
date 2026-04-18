0a. Study `docs/specifications/*` with up to 10 parallel Sonnet subagents to learn the application specifications.
0b. Study @IMPLEMENTATION_PLAN.md (if present) to understand the plan so far.
0c. Study `src/rwa_calc/contracts/`, `src/rwa_calc/domain/` and `src/rwa_calc/data/` with up to 10 parallel Sonnet subagents to understand shared protocols, bundles, enums, config and regulatory values used.
0d. Study the pdf docs in `doc/assets/` using pymupdf to extract the text with up to 10 parallel Sonnet subagents. This has all the regulatory text.
0e. For reference, the application source code is in `src/rwa_calc/`.

1. Study the `docs/specifications/*` and use up to 15 Sonnet subagents to study the regulatory text (pdf - using pymupdf) within the `doc/assets/` and compare against `docs/specifications/*`. Use 3 Opus subagents to analyze findings, priorize tasks, and update the files in `doc/specifications/*`

2. Study @IMPLEMENTATION_PLAN.md (if present; it may be incorrect) and use up to 15 Sonnet subagents to study existing source code in `src/rwa_calc/` and compare it against `docs/specifications/*`. Use 3 Opus subagent to analyze findings, prioritize tasks, and create/update @IMPLEMENTATION_PLAN.md as a bullet point list sorted in priority of items yet to be implemented. Ultrathink. Consider searching for TODO, minimal implementations, placeholders, skipped/flaky tests, and inconsistent patterns. Study @IMPLEMENTATION_PLAN.md to determine starting point for research and keep it up to date with items considered complete/incomplete using subagents.

IMPORTANT: Plan only. Do NOT implement anything within `src/`. Do NOT assume functionality is missing; confirm with code search first. Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as the project's shared protocols, bundles, and enums. Prefer consolidated, idiomatic implementations there over ad-hoc copies. `src/rwa_calc/data` represents all the values used from the regulatory texts. 

ULTIMATE GOAL: For the calculation to be compliant with Basel 3.0 (CRR) and Basel 3.1 (PRA SS1/25) implementation with full acceptance test coverage across both frameworks. Consider missing elements and plan accordingly. If an element is missing, search first to confirm it doesn't exist, then if needed author the specification at `docs/specifications/`. If you create a new element then document the plan to implement it in @IMPLEMENTATION_PLAN.md using a subagent.
