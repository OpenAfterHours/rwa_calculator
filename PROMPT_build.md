0a. Study `docs/specifications/*` with up to 15 parallel Sonnet subagents to learn the application specifications.
0b. Study @IMPLEMENTATION_PLAN.md.
0c. For reference, the application source code is in `src/rwa_calc/` and the regulatory documents are in .pdf within `docs/assets` if the regulatory docs are not there run `scripts/download_docs.py` to get the pdf - use pymupdf to extract the text.

1. Your task is to implement functionality per the specifications using parallel subagents. Follow @IMPLEMENTATION_PLAN.md and **choose the single most important item to address — complete only this one item, then commit and stop.** Before making changes, search the codebase (don't assume not implemented) using Sonnet subagents. You may use up to 10 parallel Sonnet subagents for searches/reads and only 1 Opus subagent for build/tests. Use Opus subagents when complex reasoning is needed (debugging, architectural decisions).
2. After implementing functionality or resolving problems, run the tests for that unit of code that was improved. If functionality is missing then it's your job to add it as per the application specifications. Ultrathink.
2a. VALIDATION GATE: Run `uv run python scripts/arch_check.py && uv run ruff check src/ && uv run ruff format --check src/ && uv run pytest tests/contracts/ --benchmark-skip -q`. These check architectural invariants (future annotations, no ABC, no raw .collect().lazy(), no engine= in collects), lint compliance, and protocol/bundle contracts. Fix all violations before committing.
2b. Run /simplify to review all changed code for reuse, quality, and efficiency. Fix any issues found.
2c. Re-run the validation gate from 2a to confirm /simplify changes didn't break anything. Fix any violations before committing.
3. When you discover issues, immediately update @IMPLEMENTATION_PLAN.md with your findings using a subagent. When resolved, update and remove the item.
4. When the tests pass, update @IMPLEMENTATION_PLAN.md, then `git add -A` then `git commit` with a message describing the changes. After the commit, `git push`.

99999. Important: When authoring documentation, capture the why — tests and implementation importance.
999999. Important: Single sources of truth, no migrations/adapters. If tests unrelated to your work fail, resolve them as part of the increment.
9999999. As soon as there are no build or test errors create a git tag. If there are no git tags start at 0.0.0 and increment patch by 1 for example 0.0.1 if 0.0.0 does not exist.
99999999. You may add extra logging if required to debug issues.
999999999. Keep @IMPLEMENTATION_PLAN.md current with learnings using a subagent — future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.
9999999999. When you learn something new about how to run the application, update @AGENTS.md using a subagent but keep it brief. For example if you run commands multiple times before learning the correct command then that file should be updated.
99999999999. For any bugs you notice, resolve them or document them in @IMPLEMENTATION_PLAN.md using a subagent even if it is unrelated to the current piece of work.
999999999999. Implement functionality completely. Placeholders and stubs waste efforts and time redoing the same work.
9999999999999. When @IMPLEMENTATION_PLAN.md becomes large periodically clean out the items that are completed from the file using a subagent.
99999999999999. If you find inconsistencies in `docs/specifications/*` then use an Opus 4.6 subagent with 'ultrathink' requested to update them.
999999999999999. IMPORTANT: Keep @AGENTS.md operational only — status updates and progress notes belong in `IMPLEMENTATION_PLAN.md`. A bloated AGENTS.md pollutes every future loop's context.
