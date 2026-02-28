0a. Study `specs/*` with up to 2 parallel Opus subagents to learn the application specifications. Refer to `ref_docs/` for regulatory source documents.
0b. Study @IMPLEMENTATION_PLAN.md (if present) to understand the plan so far.
0c. Study `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` with up to 2 parallel Opus subagents to understand shared protocols, bundles, enums & config.
0d. For reference, the application source code is in `src/rwa_calc/`.

1. Study @IMPLEMENTATION_PLAN.md (if present; it may be incorrect) and use up to 2 Opus subagents to study existing source code in `src/rwa_calc/` and compare it against `specs/*`. Use an Opus subagent to analyze findings, prioritize tasks, and create/update @IMPLEMENTATION_PLAN.md as a bullet point list sorted in priority of items yet to be implemented. Ultrathink. Consider searching for TODO, minimal implementations, placeholders, skipped/flaky tests, and inconsistent patterns. Study @IMPLEMENTATION_PLAN.md to determine starting point for research and keep it up to date with items considered complete/incomplete using subagents.

IMPORTANT: Plan only. Do NOT implement anything. Do NOT assume functionality is missing; confirm with code search first. Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as the project's shared protocols, bundles, and enums. Prefer consolidated, idiomatic implementations there over ad-hoc copies.

ULTIMATE GOAL: Achieve 100% CRR (Basel 3.0) acceptance test pass rate (currently 71/74, 3 skipped: A7, A8, C3), then complete Basel 3.1 (PRA PS9/24) implementation with full acceptance test coverage across both frameworks. Consider missing elements and plan accordingly. If an element is missing, search first to confirm it doesn't exist, then if needed author the specification at `specs/`. If you create a new element then document the plan to implement it in @IMPLEMENTATION_PLAN.md using a subagent.
